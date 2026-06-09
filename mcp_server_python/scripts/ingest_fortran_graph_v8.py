"""Tenant-aware Fortran AST graph ingestion (v8).

Creates FortranModule, FortranSubroutine, FortranFunction, FortranProgram nodes
plus CALLS, USES, CONTAINS edges. Graph-only — no Bedrock embeddings, no
OpenSearch writes, no SHAIndex. Neptune MERGE provides idempotency.

Two-pass write strategy: Phase 1 parses all files and writes NODES; Phase 2
writes RELATIONSHIPS. This ensures every MERGE target node exists before any
edge references it.

Memory fix (scalable-ingestion-pipeline Phase 1): results are streamed per-batch
via run_parallel_parse — never holds all FortranParseResult objects in memory.

Implements: R1, R5–R13 of graph-port-fortran-ast.
"""
from __future__ import annotations

import asyncio
import gc
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1]))

from _fortran_parser import FortranParseResult, FortranParser
from _ingest_common import (
    build_ingestion_parser,
    resolve_tenant_and_mode,
    resolve_worktree_root,
)
from _ingest_cost_model import IngestionReportWriter
from _parallel_runner import FileResult, ParallelConfig, run_parallel_parse

VERSION = "8.0.0"


# ════════════════════════════════════════════════════════════════════════
# Module-level parse wrapper (picklable for ProcessPoolExecutor)
# ════════════════════════════════════════════════════════════════════════

# These globals are set by main() / _dry_run() before run_parallel_parse
# is called. They provide the worktree_root to the wrapper without
# requiring it as an argument (which would make the callable non-picklable
# due to closure over mutable state).
_WORKTREE_ROOT: str | None = None


def _parse_one_fortran_file(filepath: Path) -> FortranParseResult | None:
    """Module-level wrapper for FortranParser.parse_file (picklable).

    Each worker creates its own FortranParser with its own fparser2
    instance. When the worker process dies, all fparser2 memory is freed.
    """
    parser = FortranParser(_WORKTREE_ROOT)
    return parser.parse_file(filepath)


# ════════════════════════════════════════════════════════════════════════
# Neptune write helpers — Phase 1: NODES
# f-string-interpolated, back-tick-quoted labels, tenant=None bypass
# ════════════════════════════════════════════════════════════════════════


async def _write_module_nodes(graph_db, prefix: str, r: FortranParseResult, tenant_id: str):
    for mod in r.modules:
        cypher = (
            f"MERGE (m:`{prefix}FortranModule` {{name: $name}}) "
            f"SET m.file_path = $file_path, m.line_start = $line_start, "
            f"m.tenant_id = $tenant_id, m.version = $version, "
            f"m.updated_at = $updated_at"
        )
        await graph_db.query(cypher, params={
            "name": mod["name"],
            "file_path": r.relative_path,
            "line_start": mod.get("line_start"),
            "tenant_id": tenant_id,
            "version": VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, tenant=None)


async def _write_subroutine_nodes(graph_db, prefix: str, r: FortranParseResult, tenant_id: str):
    for sub in r.subroutines:
        cypher = (
            f"MERGE (s:`{prefix}FortranSubroutine` "
            f"{{name: $name, file_path: $file_path}}) "
            f"SET s.line_start = $line_start, s.parent_module = $parent_module, "
            f"s.tenant_id = $tenant_id, s.version = $version, "
            f"s.updated_at = $updated_at"
        )
        await graph_db.query(cypher, params={
            "name": sub["name"],
            "file_path": r.relative_path,
            "line_start": sub.get("line_start"),
            "parent_module": sub.get("parent_module"),
            "tenant_id": tenant_id,
            "version": VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, tenant=None)


async def _write_function_nodes(graph_db, prefix: str, r: FortranParseResult, tenant_id: str):
    for func in r.functions:
        cypher = (
            f"MERGE (f:`{prefix}FortranFunction` "
            f"{{name: $name, file_path: $file_path}}) "
            f"SET f.line_start = $line_start, f.parent_module = $parent_module, "
            f"f.return_type = $return_type, "
            f"f.tenant_id = $tenant_id, f.version = $version, "
            f"f.updated_at = $updated_at"
        )
        await graph_db.query(cypher, params={
            "name": func["name"],
            "file_path": r.relative_path,
            "line_start": func.get("line_start"),
            "parent_module": func.get("parent_module"),
            "return_type": func.get("return_type"),
            "tenant_id": tenant_id,
            "version": VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, tenant=None)


async def _write_program_nodes(graph_db, prefix: str, r: FortranParseResult, tenant_id: str):
    for prog in r.programs:
        cypher = (
            f"MERGE (p:`{prefix}FortranProgram` {{name: $name}}) "
            f"SET p.file_path = $file_path, p.executable_name = $exe_name, "
            f"p.tenant_id = $tenant_id, p.version = $version, "
            f"p.updated_at = $updated_at"
        )
        await graph_db.query(cypher, params={
            "name": prog["name"],
            "file_path": r.relative_path,
            "exe_name": prog.get("executable_name"),
            "tenant_id": tenant_id,
            "version": VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, tenant=None)


# ════════════════════════════════════════════════════════════════════════
# Neptune write helpers — Phase 2: RELATIONSHIPS
# ════════════════════════════════════════════════════════════════════════


async def _write_calls(graph_db, prefix: str, r: FortranParseResult):
    """Create CALLS relationships (R6.1, R6.5).

    MERGE a placeholder FortranSubroutine for the callee if it does not yet
    exist (it may live in a file not yet processed), then MERGE the CALLS edge
    from any node in the current file (subroutine/function/program) to it.
    """
    for call in r.calls:
        cypher = (
            f"MERGE (callee:`{prefix}FortranSubroutine` {{name: $callee_name}}) "
            f"WITH callee "
            f"MATCH (caller) WHERE caller.file_path = $file_path "
            f"AND (caller:`{prefix}FortranSubroutine` "
            f"OR caller:`{prefix}FortranFunction` "
            f"OR caller:`{prefix}FortranProgram`) "
            f"MERGE (caller)-[rel:CALLS]->(callee) "
            f"SET rel.line = $line, rel.source_file = $source_file"
        )
        await graph_db.query(cypher, params={
            "callee_name": call["callee"],
            "file_path": r.relative_path,
            "line": call.get("line"),
            "source_file": r.relative_path,
        }, tenant=None)


async def _write_uses(graph_db, prefix: str, r: FortranParseResult):
    """Create USES relationships (R6.2)."""
    for use in r.uses:
        cypher = (
            f"MERGE (mod:`{prefix}FortranModule` {{name: $module_name}}) "
            f"WITH mod "
            f"MATCH (user) WHERE user.file_path = $file_path "
            f"MERGE (user)-[rel:USES]->(mod) "
            f"SET rel.only = $only_clause"
        )
        await graph_db.query(cypher, params={
            "module_name": use["module"],
            "file_path": r.relative_path,
            "only_clause": use.get("only"),
        }, tenant=None)


async def _write_contains(graph_db, prefix: str, r: FortranParseResult):
    """Create CONTAINS relationships from modules to contained children (R6.3).

    Emitted only for subroutines/functions whose ``parent_module`` is set.
    """
    for sub in r.subroutines:
        if sub.get("parent_module"):
            cypher = (
                f"MATCH (m:`{prefix}FortranModule` {{name: $mod_name}}) "
                f"MATCH (s:`{prefix}FortranSubroutine` "
                f"{{name: $sub_name, file_path: $file_path}}) "
                f"MERGE (m)-[:CONTAINS]->(s)"
            )
            await graph_db.query(cypher, params={
                "mod_name": sub["parent_module"],
                "sub_name": sub["name"],
                "file_path": r.relative_path,
            }, tenant=None)

    for func in r.functions:
        if func.get("parent_module"):
            cypher = (
                f"MATCH (m:`{prefix}FortranModule` {{name: $mod_name}}) "
                f"MATCH (f:`{prefix}FortranFunction` "
                f"{{name: $func_name, file_path: $file_path}}) "
                f"MERGE (m)-[:CONTAINS]->(f)"
            )
            await graph_db.query(cypher, params={
                "mod_name": func["parent_module"],
                "func_name": func["name"],
                "file_path": r.relative_path,
            }, tenant=None)


# ════════════════════════════════════════════════════════════════════════
# Counting + reporting helpers
# ════════════════════════════════════════════════════════════════════════


def _result_node_counts(r: FortranParseResult) -> dict[str, int]:
    return {
        "FortranModule": len(r.modules),
        "FortranSubroutine": len(r.subroutines),
        "FortranFunction": len(r.functions),
        "FortranProgram": len(r.programs),
    }


def _result_rel_counts(r: FortranParseResult) -> dict[str, int]:
    contains = sum(1 for s in r.subroutines if s.get("parent_module"))
    contains += sum(1 for f in r.functions if f.get("parent_module"))
    return {
        "CALLS": len(r.calls),
        "USES": len(r.uses),
        "CONTAINS": contains,
    }


def _dry_run(files: list[Path], config: ParallelConfig) -> int:
    """Parse all files (streaming) and print a summary without Neptune (R11).

    Memory-safe: processes results per-batch, discards parse output immediately.
    """
    global _WORKTREE_ROOT

    parsed = 0
    failed = 0
    timed_out = 0
    node_totals = {"FortranModule": 0, "FortranSubroutine": 0,
                   "FortranFunction": 0, "FortranProgram": 0}
    rel_totals = {"CALLS": 0, "USES": 0, "CONTAINS": 0}

    for batch in run_parallel_parse(files, _parse_one_fortran_file, config,
                                    label="dry-run"):
        for fr in batch:
            if fr.success and fr.result is not None:
                parsed += 1
                for k, v in _result_node_counts(fr.result).items():
                    node_totals[k] += v
                for k, v in _result_rel_counts(fr.result).items():
                    rel_totals[k] += v
            else:
                failed += 1
                if fr.error == "timeout":
                    timed_out += 1
        # Release batch memory immediately
        gc.collect()

    total = parsed + failed
    rate = (parsed / total * 100) if total else 0.0
    print("=" * 60)
    print("DRY-RUN SUMMARY (no writes performed)")
    print("=" * 60)
    print(f"  Files discovered:    {len(files)}")
    print(f"  Files parsed:        {parsed}")
    print(f"  Files failed:        {failed}")
    print(f"  Files timed out:     {timed_out}")
    print(f"  Parse success rate:  {rate:.1f}%")
    print(f"  Workers:             {config.workers}")
    print("  Nodes that would be created:")
    print(f"    FortranModule:     {node_totals['FortranModule']:,}")
    print(f"    FortranSubroutine: {node_totals['FortranSubroutine']:,}")
    print(f"    FortranFunction:   {node_totals['FortranFunction']:,}")
    print(f"    FortranProgram:    {node_totals['FortranProgram']:,}")
    print("  Relationships that would be created:")
    print(f"    CALLS:             {rel_totals['CALLS']:,}")
    print(f"    USES:              {rel_totals['USES']:,}")
    print(f"    CONTAINS:          {rel_totals['CONTAINS']:,}")
    print("=" * 60)
    return 0


# ════════════════════════════════════════════════════════════════════════
# Entry point
# ════════════════════════════════════════════════════════════════════════


async def main() -> int:
    global _WORKTREE_ROOT

    parser = build_ingestion_parser("Fortran AST graph ingestion (v8)")
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
    prefix = tenant.label_prefix  # e.g. "GW_V17_" or "" for gw

    # Set module-level worktree root for the picklable parse wrapper
    _WORKTREE_ROOT = str(worktree_root)

    print(f"[INFO] tenant={tenant.tenant_id} mode={mode} "
          f"worktree={worktree_root} prefix={prefix!r}")

    fortran_parser = FortranParser(worktree_root)

    # Discover files (R1, R13.2).
    try:
        files = fortran_parser.discover_fortran_files()
    except FileNotFoundError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    include_dirs = fortran_parser.discover_include_dirs()
    print(f"[INFO] Discovered {len(files)} Fortran files, "
          f"{len(include_dirs)} include directories")

    if not files:
        print("[INFO] No Fortran files discovered (shallow checkout?); "
              "nothing to ingest.")

    config = ParallelConfig(
        workers=args.workers,
        timeout=args.timeout,
        progress_interval=50,
        batch_size=50,
    )

    # Dry-run: parse + summarize, no Neptune connection (R11.3).
    if args.dry_run:
        return _dry_run(files, config)

    # Live mode — connect graph (R10.5: connection failure exits 1).
    try:
        from _ingest_common import build_ingestion_data_access
        uda, _ = await build_ingestion_data_access()
    except Exception as e:
        print(f"[ERROR] Failed to connect data layer: {e}", file=sys.stderr)
        return 1

    graph_db = uda.graph_db
    report = IngestionReportWriter(tenant.tenant_id, tenant.branch, mode)
    t_start = time.time()
    errors: list[dict] = []
    parsed = 0
    failed = 0
    total_nodes = 0
    total_rels = 0

    # ── Phase 1: parse + write NODES (streaming, per-batch) ────────────
    # Keep only lightweight references (relative_path + rel counts) for Phase 2.
    rel_refs: list[FortranParseResult] = []

    for batch in run_parallel_parse(files, _parse_one_fortran_file, config,
                                    label="fortran-parse"):
        for fr in batch:
            report.increment("total_files_processed")
            if not fr.success or fr.result is None:
                failed += 1
                continue
            parsed += 1
            result: FortranParseResult = fr.result

            try:
                await _write_module_nodes(graph_db, prefix, result, tenant.tenant_id)
                await _write_subroutine_nodes(graph_db, prefix, result, tenant.tenant_id)
                await _write_function_nodes(graph_db, prefix, result, tenant.tenant_id)
                await _write_program_nodes(graph_db, prefix, result, tenant.tenant_id)
                for label_name, count in _result_node_counts(result).items():
                    if count:
                        report.increment(f"nodes:{prefix}{label_name}", count)
                        total_nodes += count
            except Exception as e:
                if len(errors) < 200:
                    errors.append({"file": result.relative_path, "error": str(e)})
                print(f"[WARN] Neptune node-write error for {result.relative_path}: {e}",
                      file=sys.stderr)
                continue

            # Keep the result for Phase 2 relationship writes.
            # These hold CALLS/USES/CONTAINS refs — typically small dicts.
            rel_refs.append(result)
        gc.collect()

    # ── Phase 2: write RELATIONSHIPS ───────────────────────────────────
    for result in rel_refs:
        try:
            await _write_calls(graph_db, prefix, result)
            await _write_uses(graph_db, prefix, result)
            await _write_contains(graph_db, prefix, result)
            rels = sum(_result_rel_counts(result).values())
            report.increment("relationships_created", rels)
            total_rels += rels
        except Exception as e:
            if len(errors) < 200:
                errors.append({"file": result.relative_path, "error": str(e)})
            print(f"[WARN] Neptune rel-write error for {result.relative_path}: {e}",
                  file=sys.stderr)
            continue

    total = parsed + failed
    rate = (parsed / total * 100) if total else 0.0
    print("=" * 60)
    print(f"Fortran graph ingestion complete — {int(time.time() - t_start)}s")
    print("=" * 60)
    print(f"  Files discovered:   {len(files)}")
    print(f"  Files parsed:       {parsed}")
    print(f"  Files failed:       {failed}")
    print(f"  Parse success rate: {rate:.1f}%")
    print(f"  Workers:            {config.workers}")
    print(f"  Nodes created:      {total_nodes:,}")
    print(f"  Relationships:      {total_rels:,}")
    print(f"  Write errors:       {len(errors)}")

    report_path = report.finalize()
    # Augment report with parse-provenance (best-effort).
    try:
        import json
        report_data = json.loads(Path(report_path).read_text())
        report_data["parallel_config"] = {
            "workers": config.workers,
            "timeout": config.timeout,
        }
        Path(report_path).write_text(json.dumps(report_data, indent=2) + "\n")
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] could not augment report: {e}", file=sys.stderr)
    print(f"[DONE] report: {report_path}")
    await uda.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
