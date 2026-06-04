"""Tenant-aware Rocoto XML ingestion (v8) — graph-only.

Parses Rocoto workflow XML and writes the full job-dependency DAG to Neptune:
RocotoTask, RocotoMetatask, RocotoCycledef, DataDependency nodes plus
DEPENDS_ON, DEPENDS_ON_DATA, MEMBER_OF, RUNS_ON, RUNS_SCRIPT, and USES_ENV
edges. Cross-links to pre-existing ShellScript / EnvironmentVariable nodes.

Implements: R6–R13 of graph-port-workflow-structure.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1]))

from _ingest_common import (
    build_ingestion_data_access,
    build_ingestion_parser,
    resolve_tenant_and_mode,
)
from _ingest_cost_model import IngestionReportWriter
from _rocoto_parser import RocotoXMLParser
from ingest_expdir_configs_v8 import HASH_SUFFIX, resolve_expdir_base

VERSION = "8.0.0"


def discover_xml_experiments(expdir_base: Path, experiment_filter: str | None = None
                             ) -> list[dict]:
    """Find Rocoto XML files under EXPDIR subdirs. Returns {xml_path, experiment}."""
    base = Path(expdir_base)
    if not base.is_dir():
        print(f"[ERROR] EXPDIR base not found: {base}", file=sys.stderr)
        return []
    experiments: list[dict] = []
    for d in sorted(base.iterdir()):
        if not d.is_dir():
            continue
        if experiment_filter and experiment_filter not in d.name:
            continue
        xml_files = list(d.glob("*.xml"))
        if not xml_files:
            continue
        experiments.append({
            'xml_path': str(xml_files[0]),
            'experiment': HASH_SUFFIX.sub('', d.name),
        })
    return experiments


def _collect_all_tasks(parsed: dict) -> list[dict]:
    """Collect tasks from top level and (recursively) all metatasks."""
    tasks = list(parsed['tasks'])
    for mt in parsed['metatasks']:
        tasks.extend(_collect_metatask_tasks(mt))
    return tasks


def _collect_metatask_tasks(mt: dict) -> list[dict]:
    tasks = list(mt['tasks'])
    for nested in mt['nested_metatasks']:
        tasks.extend(_collect_metatask_tasks(nested))
    return tasks


# ════════════════════════════════════════════════════════════════════════
# Node write helpers — f-string label prefixing, tenant=None (R7)
# ════════════════════════════════════════════════════════════════════════


async def _write_cycledef(graph_db, prefix: str, cd: dict, experiment: str, tenant):
    """MERGE a RocotoCycledef node (key: group, experiment)."""
    await graph_db.query(
        f"MERGE (c:`{prefix}RocotoCycledef` {{group: $group, experiment: $experiment}}) "
        f"SET c.definition = $definition, c.tenant_id = $tenant_id, "
        f"c.version = $version, c.updated_at = $updated_at",
        params={
            "group": cd['group'], "experiment": experiment,
            "definition": cd['definition'], "tenant_id": tenant.tenant_id,
            "version": VERSION, "updated_at": datetime.now(timezone.utc).isoformat(),
        }, tenant=None)


async def _write_task(graph_db, prefix: str, task: dict, experiment: str, tenant):
    """MERGE a RocotoTask node (composite key: name, experiment)."""
    resources = task.get('resources', {})
    await graph_db.query(
        f"MERGE (t:`{prefix}RocotoTask` {{name: $name, experiment: $experiment}}) "
        f"SET t.command = $command, t.cycledefs = $cycledefs, "
        f"t.maxtries = $maxtries, t.walltime = $walltime, "
        f"t.nodes_spec = $nodes_spec, t.cores = $cores, t.queue = $queue, "
        f"t.memory = $memory, t.is_final = $is_final, "
        f"t.dependency_tree_json = $dep_json, t.log_path = $log_path, "
        f"t.tenant_id = $tenant_id, t.version = $version, t.updated_at = $updated_at",
        params={
            "name": task['name'], "experiment": experiment,
            "command": task['command'], "cycledefs": task['cycledefs'],
            "maxtries": task['maxtries'], "walltime": resources.get('walltime'),
            "nodes_spec": resources.get('nodes_spec'), "cores": resources.get('cores'),
            "queue": resources.get('queue'), "memory": resources.get('memory'),
            "is_final": task['is_final'],
            "dep_json": json.dumps(task.get('dependency_tree', {})),
            "log_path": task.get('log_path'), "tenant_id": tenant.tenant_id,
            "version": VERSION, "updated_at": datetime.now(timezone.utc).isoformat(),
        }, tenant=None)


async def _write_metatask(graph_db, prefix: str, mt: dict, experiment: str,
                          tenant, report):
    """MERGE a RocotoMetatask node, its child tasks (+MEMBER_OF), then recurse."""
    member_count = 1
    for values in mt['variables'].values():
        member_count *= len(values)

    await graph_db.query(
        f"MERGE (m:`{prefix}RocotoMetatask` {{name: $name, experiment: $experiment}}) "
        f"SET m.mode = $mode, m.variables = $variables, "
        f"m.member_count = $member_count, m.tenant_id = $tenant_id, "
        f"m.version = $version, m.updated_at = $updated_at",
        params={
            "name": mt['name'], "experiment": experiment, "mode": mt['mode'],
            "variables": json.dumps(mt['variables']), "member_count": member_count,
            "tenant_id": tenant.tenant_id, "version": VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, tenant=None)
    report.increment(f"nodes:{prefix}RocotoMetatask")

    for task in mt['tasks']:
        await _write_task(graph_db, prefix, task, experiment, tenant)
        report.increment(f"nodes:{prefix}RocotoTask")
        await graph_db.query(
            f"MATCH (t:`{prefix}RocotoTask` {{name: $task_name, experiment: $exp}}) "
            f"MATCH (m:`{prefix}RocotoMetatask` {{name: $mt_name, experiment: $exp}}) "
            f"MERGE (t)-[:MEMBER_OF]->(m)",
            params={"task_name": task['name'], "mt_name": mt['name'],
                    "exp": experiment}, tenant=None)
        report.increment("relationships_created")

    for nested in mt['nested_metatasks']:
        await _write_metatask(graph_db, prefix, nested, experiment, tenant, report)


# ════════════════════════════════════════════════════════════════════════
# Edge write helpers (R7, R8)
# ════════════════════════════════════════════════════════════════════════


async def _walk_deps(graph_db, prefix: str, task_name: str, dep_node: dict,
                     experiment: str, report, condition: str | None = None):
    """Recursive dependency-tree walker → DEPENDS_ON edges."""
    if 'operator' in dep_node:
        op = dep_node['operator']
        for child in dep_node.get('children', []):
            await _walk_deps(graph_db, prefix, task_name, child, experiment,
                             report, condition=op)
    elif dep_node.get('type') in ('task', 'metatask', 'taskvalid'):
        dep_name = dep_node.get('name')
        if not dep_name:
            return
        await graph_db.query(
            f"MATCH (t:`{prefix}RocotoTask` {{name: $task_name, experiment: $exp}}) "
            f"MERGE (d:`{prefix}RocotoTask` {{name: $dep_name, experiment: $exp}}) "
            f"MERGE (t)-[r:DEPENDS_ON]->(d) "
            f"SET r.dep_type = $dep_type, r.cycle_offset = $cycle_offset, "
            f"r.condition = $condition",
            params={
                "task_name": task_name, "dep_name": dep_name, "exp": experiment,
                "dep_type": dep_node.get('type'),
                "cycle_offset": dep_node.get('cycle_offset'), "condition": condition,
            }, tenant=None)
        report.increment("relationships_created")


async def _write_data_dependencies(graph_db, prefix: str, task: dict,
                                   experiment: str, report):
    """DEPENDS_ON_DATA edges to DataDependency nodes (R7.6)."""
    for data_dep in task.get('data_dependencies', []):
        path_pattern = data_dep.get('path', '')
        if not path_pattern:
            continue
        await graph_db.query(
            f"MATCH (t:`{prefix}RocotoTask` {{name: $task_name, experiment: $exp}}) "
            f"MERGE (d:`{prefix}DataDependency` {{path_pattern: $path_pattern}}) "
            f"MERGE (t)-[r:DEPENDS_ON_DATA]->(d) SET r.age = $age",
            params={"task_name": task['name'], "exp": experiment,
                    "path_pattern": path_pattern, "age": data_dep.get('age')},
            tenant=None)
        report.increment("relationships_created")


async def _write_runs_script(graph_db, prefix: str, task: dict, experiment: str,
                             report, unmatched: list):
    """RUNS_SCRIPT edge via ENDS WITH basename; graceful when no match (R8.5)."""
    command = task.get('command', '')
    if not command:
        return
    basename = Path(command).name
    if not basename:
        return
    match = await graph_db.query(
        f"MATCH (s:`{prefix}ShellScript`) WHERE s.path ENDS WITH $basename "
        f"RETURN s.path AS path LIMIT 1",
        params={"basename": basename}, tenant=None)
    if not match:
        unmatched.append({"task": task['name'], "basename": basename})
        return
    await graph_db.query(
        f"MATCH (t:`{prefix}RocotoTask` {{name: $task_name, experiment: $exp}}) "
        f"MATCH (s:`{prefix}ShellScript`) WHERE s.path ENDS WITH $basename "
        f"MERGE (t)-[:RUNS_SCRIPT]->(s)",
        params={"task_name": task['name'], "exp": experiment, "basename": basename},
        tenant=None)
    report.increment("relationships_created")


async def _write_uses_env(graph_db, prefix: str, task: dict, experiment: str, report):
    """USES_ENV edges from task envars to EnvironmentVariable (R8.2)."""
    for var_name in task.get('envars', {}):
        if not var_name:
            continue
        await graph_db.query(
            f"MATCH (t:`{prefix}RocotoTask` {{name: $task_name, experiment: $exp}}) "
            f"MERGE (e:`{prefix}EnvironmentVariable` {{name: $var_name}}) "
            f"MERGE (t)-[:USES_ENV]->(e)",
            params={"task_name": task['name'], "exp": experiment,
                    "var_name": var_name}, tenant=None)
        report.increment("relationships_created")


async def _write_runs_on(graph_db, prefix: str, task: dict, experiment: str, report):
    """RUNS_ON edges from task to its cycle definitions (R7.8)."""
    for group in task.get('cycledefs', '').split(','):
        group = group.strip()
        if not group:
            continue
        await graph_db.query(
            f"MATCH (t:`{prefix}RocotoTask` {{name: $task_name, experiment: $exp}}) "
            f"MERGE (c:`{prefix}RocotoCycledef` {{group: $group, experiment: $exp}}) "
            f"MERGE (t)-[:RUNS_ON]->(c)",
            params={"task_name": task['name'], "exp": experiment, "group": group},
            tenant=None)
        report.increment("relationships_created")


async def _ingest_rocoto_workflow(graph_db, prefix: str, parsed: dict,
                                  experiment: str, tenant, report, unmatched):
    """Two-pass ingestion: create all nodes, then all edges."""
    # Phase 1 — nodes
    for cd in parsed['cycledefs']:
        await _write_cycledef(graph_db, prefix, cd, experiment, tenant)
        report.increment(f"nodes:{prefix}RocotoCycledef")
    for mt in parsed['metatasks']:
        await _write_metatask(graph_db, prefix, mt, experiment, tenant, report)
    for task in parsed['tasks']:
        await _write_task(graph_db, prefix, task, experiment, tenant)
        report.increment(f"nodes:{prefix}RocotoTask")

    # Phase 2 — edges (all target nodes now exist)
    for task in _collect_all_tasks(parsed):
        dep_tree = task.get('dependency_tree', {})
        if dep_tree:
            await _walk_deps(graph_db, prefix, task['name'], dep_tree,
                             experiment, report)
        await _write_data_dependencies(graph_db, prefix, task, experiment, report)
        await _write_runs_script(graph_db, prefix, task, experiment, report, unmatched)
        await _write_uses_env(graph_db, prefix, task, experiment, report)
        await _write_runs_on(graph_db, prefix, task, experiment, report)


# ════════════════════════════════════════════════════════════════════════
# Entry point
# ════════════════════════════════════════════════════════════════════════


async def main() -> int:
    parser = build_ingestion_parser("Rocoto XML ingestion (v8) — graph-only")
    parser.add_argument("--experiment-filter", default=None,
                        help="Only process experiments matching this substring")
    args = parser.parse_args()

    catalog_path = os.environ.get(
        "MCP_TENANT_CATALOG_PATH",
        str(Path(__file__).parents[1] / "src" / "config" / "tenants.yaml"),
    )
    from src.config.tenants import load_catalog

    catalog = load_catalog(catalog_path)
    tenant, mode = resolve_tenant_and_mode(args, catalog)
    prefix = tenant.label_prefix
    expdir_base = resolve_expdir_base(tenant)

    experiments = discover_xml_experiments(expdir_base, args.experiment_filter)
    print(f"[INFO] tenant={tenant.tenant_id} expdir_base={expdir_base} "
          f"xml_files={len(experiments)}")

    if args.dry_run:
        total_tasks = total_deps = 0
        for exp in experiments:
            try:
                parsed = RocotoXMLParser.parse_rocoto_xml(exp['xml_path'])
            except Exception as e:
                print(f"[WARN] XML parse error {exp['experiment']}: {e}", file=sys.stderr)
                continue
            tasks = _collect_all_tasks(parsed)
            total_tasks += len(tasks)
            total_deps += sum(len(t.get('dependency_names', [])) for t in tasks)
        print("=" * 60)
        print("DRY-RUN SUMMARY (no writes performed)")
        print("=" * 60)
        print(f"  XML files:         {len(experiments)}")
        print(f"  RocotoTask nodes:  {total_tasks} (would create)")
        print(f"  DEPENDS_ON edges:  {total_deps} (would create)")
        print("=" * 60)
        return 0

    try:
        uda, _ = await build_ingestion_data_access()
    except Exception as e:
        print(f"[ERROR] Failed to connect data layer: {e}", file=sys.stderr)
        return 1

    graph_db = uda.graph_db
    report = IngestionReportWriter(tenant.tenant_id, tenant.branch, mode)
    unmatched: list[dict] = []

    for exp in experiments:
        report.increment("total_files_processed")
        try:
            parsed = RocotoXMLParser.parse_rocoto_xml(exp['xml_path'])
            await _ingest_rocoto_workflow(graph_db, prefix, parsed,
                                          exp['experiment'], tenant, report, unmatched)
        except Exception as e:
            print(f"[WARN] XML parse error {exp['experiment']}: {e}", file=sys.stderr)
            report.increment("xml_parse_errors")
            continue

    if unmatched:
        print(f"[WARN] {len(unmatched)} unmatched RUNS_SCRIPT commands "
              f"(graph-port-shell-ops should run first)")
    report_path = report.finalize()
    print(f"[DONE] report: {report_path}")
    await uda.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
