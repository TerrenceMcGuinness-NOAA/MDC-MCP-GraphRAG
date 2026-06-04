"""Tenant-aware EXPDIR config ingestion (v8) — graph-only.

Discovers materialized experiment directories and writes Experiment +
EXPDIRConfig nodes plus PART_OF, RESOLVES_FROM, and SETS_ENV edges to Neptune.
No OpenSearch, no SHAIndex — Neptune MERGE provides idempotency.

Implements: R4, R5, R8.4, R9–R13 of graph-port-workflow-structure.
"""
from __future__ import annotations

import asyncio
import os
import re
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
from _config_parser import ConfigFileParser

VERSION = "8.0.0"

# Strip hash suffix: "C48_ATM_250b0130-10380" → "C48_ATM"
HASH_SUFFIX = re.compile(r'_[0-9a-f]{6,12}-[0-9a-f]{3,6}$')
_RESOLUTION = re.compile(r'(C\d+)')


def resolve_expdir_base(tenant) -> Path:
    """Resolve the EXPDIR artifacts base, respecting MCP_EXPDIR_BASE_OVERRIDE.

    Default (local): supported_repos/EXPDIR/ under the repo root.
    """
    override = os.environ.get("MCP_EXPDIR_BASE_OVERRIDE")
    if override:
        return Path(override)
    return Path(__file__).parents[2] / "supported_repos" / "EXPDIR"


def discover_experiments(expdir_base: Path, experiment_filter: str | None = None
                         ) -> list[dict]:
    """Enumerate experiment directories under the EXPDIR base.

    Returns dicts: {dir_name, abs_path, experiment_name, pslot, resolution,
    configs[], xml_path}.
    """
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

        res = _RESOLUTION.match(d.name)
        configs = sorted(str(f) for f in d.iterdir()
                         if f.is_file() and f.name.startswith('config.'))
        xml_files = list(d.glob("*.xml"))
        experiments.append({
            'dir_name': d.name,
            'abs_path': str(d),
            'experiment_name': HASH_SUFFIX.sub('', d.name),
            'pslot': d.name,
            'resolution': res.group(1) if res else 'unknown',
            'configs': configs,
            'xml_path': str(xml_files[0]) if xml_files else None,
        })
    return experiments


# ════════════════════════════════════════════════════════════════════════
# Neptune write helper — f-string label prefixing, tenant=None (R5)
# ════════════════════════════════════════════════════════════════════════


async def _ingest_experiment(graph_db, prefix: str, exp: dict, tenant, report):
    """Create Experiment + EXPDIRConfig nodes + all edges for one experiment."""
    exp_name = exp['experiment_name']
    now = datetime.now(timezone.utc).isoformat()

    cypher = (
        f"MERGE (e:`{prefix}Experiment` {{name: $name}}) "
        f"SET e.pslot = $pslot, e.resolution = $resolution, "
        f"e.config_count = $config_count, e.has_xml = $has_xml, "
        f"e.tenant_id = $tenant_id, e.version = $version, e.updated_at = $updated_at"
    )
    await graph_db.query(cypher, params={
        "name": exp_name, "pslot": exp['pslot'],
        "resolution": exp['resolution'], "config_count": len(exp['configs']),
        "has_xml": exp['xml_path'] is not None,
        "tenant_id": tenant.tenant_id, "version": VERSION, "updated_at": now,
    }, tenant=None)
    report.increment(f"nodes:{prefix}Experiment")

    for config_path in exp['configs']:
        filename = Path(config_path).name
        parsed = ConfigFileParser.parse_config_file(config_path)
        config_key = f"{exp_name}/{filename}"
        category = ConfigFileParser.categorize_config(filename)

        cypher = (
            f"MERGE (ec:`{prefix}EXPDIRConfig` {{name: $name}}) "
            f"SET ec.experiment = $experiment, ec.category = $category, "
            f"ec.env_var_count = $env_var_count, ec.file_path = $file_path, "
            f"ec.tenant_id = $tenant_id, ec.version = $version, "
            f"ec.updated_at = $updated_at"
        )
        await graph_db.query(cypher, params={
            "name": config_key, "experiment": exp_name, "category": category,
            "env_var_count": len(parsed['env_vars']), "file_path": config_path,
            "tenant_id": tenant.tenant_id, "version": VERSION, "updated_at": now,
        }, tenant=None)
        report.increment(f"nodes:{prefix}EXPDIRConfig")

        # PART_OF → Experiment
        await graph_db.query(
            f"MATCH (ec:`{prefix}EXPDIRConfig` {{name: $config_key}}) "
            f"MATCH (e:`{prefix}Experiment` {{name: $exp_name}}) "
            f"MERGE (ec)-[:PART_OF]->(e)",
            params={"config_key": config_key, "exp_name": exp_name},
            tenant=None)
        report.increment("relationships_created")

        # RESOLVES_FROM → template ConfigFile (skip platform resource overrides)
        if not filename.startswith('config.resources.'):
            short_name = ConfigFileParser.config_short_name(filename)
            await graph_db.query(
                f"MATCH (ec:`{prefix}EXPDIRConfig` {{name: $config_key}}) "
                f"MATCH (cf:`{prefix}ConfigFile` {{name: $short_name}}) "
                f"MERGE (ec)-[:RESOLVES_FROM]->(cf)",
                params={"config_key": config_key, "short_name": short_name},
                tenant=None)
            report.increment("relationships_created")

        # SETS_ENV → EnvironmentVariable (cap 50)
        for var in parsed['env_vars'][:50]:
            if not var['name']:
                continue
            await graph_db.query(
                f"MATCH (ec:`{prefix}EXPDIRConfig` {{name: $config_key}}) "
                f"MERGE (ev:`{prefix}EnvironmentVariable` {{name: $var_name}}) "
                f"MERGE (ec)-[r:SETS_ENV]->(ev) "
                f"SET r.value = $value, r.is_default = $is_default",
                params={
                    "config_key": config_key, "var_name": var['name'],
                    "value": str(var.get('default_value', ''))[:200],
                    "is_default": var.get('is_default', False),
                }, tenant=None)
            report.increment("relationships_created")


# ════════════════════════════════════════════════════════════════════════
# Entry point
# ════════════════════════════════════════════════════════════════════════


async def main() -> int:
    parser = build_ingestion_parser("EXPDIR config ingestion (v8) — graph-only")
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

    experiments = discover_experiments(expdir_base, args.experiment_filter)
    print(f"[INFO] tenant={tenant.tenant_id} expdir_base={expdir_base} "
          f"experiments={len(experiments)}")

    if args.dry_run:
        total_configs = sum(len(e['configs']) for e in experiments)
        print("=" * 60)
        print("DRY-RUN SUMMARY (no writes performed)")
        print("=" * 60)
        print(f"  Experiments:       {len(experiments)}")
        print(f"  EXPDIRConfig:      {total_configs} (would create)")
        print(f"  RESOLVES_FROM:     ~{total_configs} (would link)")
        print("=" * 60)
        return 0

    try:
        uda, _ = await build_ingestion_data_access()
    except Exception as e:
        print(f"[ERROR] Failed to connect data layer: {e}", file=sys.stderr)
        return 1

    graph_db = uda.graph_db
    report = IngestionReportWriter(tenant.tenant_id, tenant.branch, mode)

    for exp in experiments:
        report.increment("total_files_processed", len(exp['configs']))
        try:
            await _ingest_experiment(graph_db, prefix, exp, tenant, report)
        except Exception as e:
            print(f"[WARN] experiment {exp['experiment_name']}: {e}", file=sys.stderr)
            continue

    report_path = report.finalize()
    print(f"[DONE] report: {report_path}")
    await uda.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
