"""Tenant-aware shell operational graph ingestion (v8).

Creates ShellScript, EnvironmentVariable, ConfigFile, ShellFunction nodes
plus SOURCES, INVOKES, EXPORTS, DEPENDS_ON_ENV, READS_CONFIG, DEFINES edges.
Graph-only — no Bedrock embeddings, no OpenSearch writes, no SHAIndex.
Neptune MERGE provides idempotency.

Implements: R1–R3, R5–R6, R8–R10 of graph-port-shell-ops.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1]))

from _ingest_common import (
    build_ingestion_parser,
    resolve_tenant_and_mode,
    resolve_worktree_root,
)
from _ingest_cost_model import IngestionReportWriter
from _parallel_runner import ParallelConfig, run_parallel_parse
from _shell_parser import ShellParseResult, ShellScriptParser

VERSION = "8.0.0"


# ════════════════════════════════════════════════════════════════════════
# Module-level parse wrapper (picklable for ProcessPoolExecutor)
# ════════════════════════════════════════════════════════════════════════

_WORKTREE_ROOT: str | None = None


def _parse_one_shell_file(filepath: Path) -> ShellParseResult | None:
    """Module-level wrapper for ShellScriptParser.parse (picklable).

    Each worker creates its own ShellScriptParser instance. Reads the file
    content and computes the relative path.
    """
    try:
        content = filepath.read_text(errors="replace")
    except OSError:
        return None
    rel_path = str(filepath.relative_to(_WORKTREE_ROOT))
    parser = ShellScriptParser()
    return parser.parse(rel_path, content)


# ════════════════════════════════════════════════════════════════════════
# Discovery
# ════════════════════════════════════════════════════════════════════════

_SHELL_EXTENSIONS = frozenset((".sh", ".bash", ".ksh"))


def _is_binary(path: Path) -> bool:
    """Check for null byte in first 512 bytes (binary detection)."""
    try:
        data = path.read_bytes()[:512]
        return b"\x00" in data
    except OSError:
        return True


def _is_jjob_or_exscript(p: Path) -> bool:
    """Extensionless J-Jobs (dev/jobs/ or uppercase J) and ex-scripts."""
    if p.suffix:
        return False
    rel = str(p)
    if "dev/jobs" in rel or (p.name.startswith("J") and p.name == p.name.upper()):
        return True
    if "dev/scripts" in rel and p.name.startswith("ex"):
        return True
    return False


def discover_shell_scripts(worktree_root: Path, mode: str) -> list[Path]:
    """Discover shell scripts for graph ingestion.

    Full mode: rglob for .sh/.bash/.ksh + extensionless J-Jobs/ex-scripts.
    Diff mode: git diff --name-only through the same filter.
    Excludes .git/ and binary files.
    """
    if mode == "diff":
        return _discover_diff(worktree_root)
    return _discover_full(worktree_root)


def _discover_full(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file() or ".git" in p.parts:
            continue
        if p.suffix in _SHELL_EXTENSIONS:
            if not _is_binary(p):
                candidates.append(p)
        elif _is_jjob_or_exscript(p):
            if not _is_binary(p):
                candidates.append(p)
    return candidates


def _discover_diff(root: Path) -> list[Path]:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "develop..HEAD"],
            capture_output=True, text=True, cwd=str(root), check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    candidates: list[Path] = []
    for line in result.stdout.strip().splitlines():
        p = root / line
        if not p.is_file() or ".git" in p.parts:
            continue
        if p.suffix in _SHELL_EXTENSIONS or _is_jjob_or_exscript(p):
            if not _is_binary(p):
                candidates.append(p)
    return candidates


# ════════════════════════════════════════════════════════════════════════
# Neptune write helpers — f-string label prefixing, tenant=None
# ════════════════════════════════════════════════════════════════════════


async def _write_script_node(graph_db, prefix: str, r: ShellParseResult, tenant_id: str):
    cypher = (
        f"MERGE (s:`{prefix}ShellScript` {{path: $path}}) "
        f"SET s.name = $name, s.type = $type, s.category = $category, "
        f"s.tenant_id = $tenant_id, s.version = $version, "
        f"s.updated_at = $updated_at"
    )
    await graph_db.query(cypher, params={
        "path": r.path, "name": r.name, "type": r.type,
        "category": r.category, "tenant_id": tenant_id,
        "version": VERSION, "updated_at": datetime.now(timezone.utc).isoformat(),
    }, tenant=None)


async def _write_sources(graph_db, prefix: str, r: ShellParseResult):
    for src in r.sources:
        target_path = src.get("resolved") or src["path"]
        cypher = (
            f"MATCH (s:`{prefix}ShellScript` {{path: $sp}}) "
            f"MERGE (t:`{prefix}ShellScript` {{path: $tp}}) "
            f"ON CREATE SET t.name = $tn, t.type = 'sourced' "
            f"MERGE (s)-[r:SOURCES]->(t) SET r.line = $line"
        )
        await graph_db.query(cypher, params={
            "sp": r.path, "tp": target_path,
            "tn": Path(src["path"]).name, "line": src["line"],
        }, tenant=None)


async def _write_invokes(graph_db, prefix: str, r: ShellParseResult):
    for inv in r.invokes:
        cypher = (
            f"MATCH (s:`{prefix}ShellScript` {{path: $sp}}) "
            f"MERGE (t:`{prefix}ShellScript` {{name: $tn}}) "
            f"ON CREATE SET t.type = 'exscript', t.package = $pkg "
            f"MERGE (s)-[r:INVOKES]->(t) SET r.line = $line, r.variable = $var"
        )
        await graph_db.query(cypher, params={
            "sp": r.path, "tn": inv["script"],
            "pkg": inv["package"], "line": inv["line"],
            "var": inv.get("variable"),
        }, tenant=None)


async def _write_exports(graph_db, prefix: str, r: ShellParseResult):
    for exp in r.exports:
        cypher = (
            f"MATCH (s:`{prefix}ShellScript` {{path: $sp}}) "
            f"MERGE (e:`{prefix}EnvironmentVariable` {{name: $vn}}) "
            f"ON CREATE SET e.default_value = $dv "
            f"MERGE (s)-[r:EXPORTS]->(e) SET r.line = $line"
        )
        await graph_db.query(cypher, params={
            "sp": r.path, "vn": exp["name"],
            "dv": exp.get("value", ""), "line": exp["line"],
        }, tenant=None)


async def _write_depends_on_env(graph_db, prefix: str, r: ShellParseResult):
    for var in r.env_deps:
        cypher = (
            f"MATCH (s:`{prefix}ShellScript` {{path: $sp}}) "
            f"MERGE (e:`{prefix}EnvironmentVariable` {{name: $vn}}) "
            f"MERGE (s)-[:DEPENDS_ON_ENV]->(e)"
        )
        await graph_db.query(cypher, params={
            "sp": r.path, "vn": var,
        }, tenant=None)


async def _write_reads_config(graph_db, prefix: str, r: ShellParseResult):
    for cfg in r.configs:
        config_path = f"parm/config/config.{cfg['name']}"
        cypher = (
            f"MATCH (s:`{prefix}ShellScript` {{path: $sp}}) "
            f"MERGE (c:`{prefix}ConfigFile` {{name: $cn}}) "
            f"ON CREATE SET c.path = $cp "
            f"MERGE (s)-[r:READS_CONFIG]->(c) SET r.line = $line"
        )
        await graph_db.query(cypher, params={
            "sp": r.path, "cn": cfg["name"],
            "cp": config_path, "line": cfg["line"],
        }, tenant=None)


async def _write_defines(graph_db, prefix: str, r: ShellParseResult):
    for func in r.functions:
        cypher = (
            f"MATCH (s:`{prefix}ShellScript` {{path: $sp}}) "
            f"MERGE (f:`{prefix}ShellFunction` {{name: $fn, script: $sp}}) "
            f"SET f.line = $line "
            f"MERGE (s)-[:DEFINES]->(f)"
        )
        await graph_db.query(cypher, params={
            "sp": r.path, "fn": func["name"], "line": func["line"],
        }, tenant=None)


# ════════════════════════════════════════════════════════════════════════
# Entry point
# ════════════════════════════════════════════════════════════════════════


async def main() -> int:
    global _WORKTREE_ROOT

    parser = build_ingestion_parser("Shell operational graph ingestion (v8)")
    parser.add_argument("--workers", type=int,
                        default=max(1, (os.cpu_count() or 2) - 1),
                        help="Number of parallel parse workers (default: cpu_count-1)")
    parser.add_argument("--timeout", type=int, default=120,
                        help="Per-file parse timeout in seconds (default: 120)")
    args = parser.parse_args()

    catalog_path = os.environ.get(
        "MCP_TENANT_CATALOG_PATH",
        str(Path(__file__).parents[1] / "src" / "config" / "tenants.yaml"),
    )
    from src.config.tenants import load_catalog

    catalog = load_catalog(catalog_path)
    tenant, mode = resolve_tenant_and_mode(args, catalog)
    worktree_root = resolve_worktree_root(tenant)
    prefix = tenant.label_prefix

    # Set module-level worktree root for the picklable parse wrapper
    _WORKTREE_ROOT = str(worktree_root)

    print(f"[INFO] tenant={tenant.tenant_id} mode={mode} "
          f"worktree={worktree_root} prefix={prefix!r}")

    # Discover shell scripts
    scripts = discover_shell_scripts(worktree_root, mode)
    print(f"[INFO] Discovered {len(scripts)} shell scripts")

    config = ParallelConfig(
        workers=args.workers,
        timeout=args.timeout,
        progress_interval=50,
        batch_size=50,
    )

    if args.dry_run:
        totals: dict[str, int] = {
            "sources": 0, "invokes": 0, "exports": 0,
            "env_deps": 0, "configs": 0, "functions": 0,
        }
        errors = 0
        parsed = 0

        for batch in run_parallel_parse(scripts, _parse_one_shell_file, config,
                                        label="shell-parse"):
            for fr in batch:
                if not fr.success or fr.result is None:
                    errors += 1
                    continue
                parsed += 1
                r: ShellParseResult = fr.result
                totals["sources"] += len(r.sources)
                totals["invokes"] += len(r.invokes)
                totals["exports"] += len(r.exports)
                totals["env_deps"] += len(r.env_deps)
                totals["configs"] += len(r.configs)
                totals["functions"] += len(r.functions)

        print("=" * 60)
        print("DRY-RUN SUMMARY (no writes performed)")
        print("=" * 60)
        print(f"  Scripts found:       {len(scripts)}")
        print(f"  Scripts parsed:      {parsed}")
        print(f"  SOURCES edges:       {totals['sources']}")
        print(f"  INVOKES edges:       {totals['invokes']}")
        print(f"  EXPORTS edges:       {totals['exports']}")
        print(f"  DEPENDS_ON_ENV:      {totals['env_deps']}")
        print(f"  READS_CONFIG edges:  {totals['configs']}")
        print(f"  DEFINES edges:       {totals['functions']}")
        print(f"  Read errors:         {errors}")
        print(f"  Workers:             {config.workers}")
        print("=" * 60)
        return 0

    # Live mode — connect graph
    try:
        from _ingest_common import build_ingestion_data_access
        uda, _ = await build_ingestion_data_access()
    except Exception as e:
        print(f"[ERROR] Failed to connect data layer: {e}", file=sys.stderr)
        return 1

    graph_db = uda.graph_db
    report = IngestionReportWriter(tenant.tenant_id, tenant.branch, mode)
    errors = 0
    processed = 0

    for batch in run_parallel_parse(scripts, _parse_one_shell_file, config,
                                    label="shell-parse"):
        for fr in batch:
            if not fr.success or fr.result is None:
                errors += 1
                continue
            processed += 1
            r: ShellParseResult = fr.result
            report.increment("total_files_processed")

            try:
                await _write_script_node(graph_db, prefix, r, tenant.tenant_id)
                await _write_sources(graph_db, prefix, r)
                await _write_invokes(graph_db, prefix, r)
                await _write_exports(graph_db, prefix, r)
                await _write_depends_on_env(graph_db, prefix, r)
                await _write_reads_config(graph_db, prefix, r)
                await _write_defines(graph_db, prefix, r)

                report.increment(f"nodes:{prefix}ShellScript")
                report.increment("relationships_created",
                                 len(r.sources) + len(r.invokes) + len(r.exports)
                                 + len(r.env_deps) + len(r.configs) + len(r.functions))
            except Exception as e:
                print(f"[WARN] Neptune error for {r.path}: {e}", file=sys.stderr)
                errors += 1
                continue

    print(f"[INFO] Processed {processed} scripts, {errors} errors")
    report_path = report.finalize()
    print(f"[DONE] report: {report_path}")
    await uda.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
