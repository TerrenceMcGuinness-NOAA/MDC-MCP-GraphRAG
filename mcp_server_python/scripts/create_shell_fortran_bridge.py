"""Tenant-aware Shell→Fortran EXECUTES bridge.

Creates EXECUTES edges from ShellScript nodes to existing FortranProgram nodes
by parsing shell scripts for executable references. Graph-only — no embeddings.

Implements: R4, R7, R8.2, R8.4, R10.2 of graph-port-shell-ops.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1]))

from _ingest_common import (
    build_ingestion_parser,
    resolve_tenant_and_mode,
    resolve_worktree_root,
)
from _ingest_cost_model import IngestionReportWriter
from ingest_shell_graph_v8 import discover_shell_scripts


# ════════════════════════════════════════════════════════════════════════
# Exec-reference extraction patterns (verbatim from legacy)
# ════════════════════════════════════════════════════════════════════════

EXEC_PATTERNS: list[re.Pattern] = [
    re.compile(r'\$\{?EXEC[a-z]*\}?/([a-zA-Z0-9_-]+)\.x\b'),
    re.compile(r'\$\{?HOME[a-z]*\}?/exec/([a-zA-Z0-9_-]+)\.x\b'),
    re.compile(r'export\s+pgm\s*=\s*["\']?([a-zA-Z0-9_-]+)'),
    re.compile(r'\bpgm\s*=\s*["\']?([a-zA-Z0-9_-]+)'),
]

# Known executable→FortranProgram mappings (names that differ at compile time)
KNOWN_EXEC_MAPPINGS: dict[str, str | None] = {
    "enkf": "enkf_main",
    "gsi": "gsi",
    "tocsbufr": "TOCSBUFR",
    "calc_increment_ens": "calc_increment",
    "calc_increment_ens_ncio": "calc_increment",
    "getsfcensmeanp": "getsfcensmeanp",
    "recentersigp": "recentersigp",
    # None → known exec with no matching Fortran PROGRAM node (skip silently)
    "gaussian_sfcanl": None,
    "gfs_bufr": None,
    "fbwndgfs": None,
    "supvit": None,
    "syndat_getjtbul": None,
    "syndat_maksynrc": None,
    "syndat_qctropcy": None,
    "overgridid": None,
    "rdbfmsua": None,
    "mkgfsawps": None,
    "tave": None,
    "vint": None,
    "webtitle": None,
    "ensstat": None,
    "calc_analysis": None,
    "getsigensmeanp_smooth": None,
    "interp_inc": None,
    "oznmon_horiz": None,
    "oznmon_time": None,
    "radmon_angle": None,
    "radmon_bcoef": None,
    "radmon_bcor": None,
    "radmon_time": None,
    "emcsfc_ice_blend": None,
    "emcsfc_snow2mdl": None,
    "global_cycle": None,
    "wgrib2": None,
    "cnvgrib": None,
}


# ════════════════════════════════════════════════════════════════════════
# Extraction + matching
# ════════════════════════════════════════════════════════════════════════


def extract_exec_references(content: str) -> set[str]:
    """Extract executable references from shell script content."""
    refs: set[str] = set()
    for pattern in EXEC_PATTERNS:
        for m in pattern.finditer(content):
            name = m.group(1).strip().lower()
            if name and len(name) > 1:
                refs.add(name)
    return refs


def match_exec_to_program(
    exec_name: str, programs: dict[str, str]
) -> str | None:
    """Multi-strategy matching: known-mappings → exact → _main suffix →
    prefix → exec-starts-with-program → progressive suffix stripping.

    Parameters
    ----------
    exec_name : str
        Extracted executable name (lowercased).
    programs : dict[str, str]
        Mapping of lowercase-program-name → canonical-program-name from
        Neptune FortranProgram nodes.

    Returns
    -------
    str | None
        The canonical FortranProgram node name, or None if no match.
    """
    lower = exec_name.lower()

    # Strategy 0: known mappings
    if lower in KNOWN_EXEC_MAPPINGS:
        mapped = KNOWN_EXEC_MAPPINGS[lower]
        if mapped is None:
            return None
        if mapped.lower() in programs:
            return programs[mapped.lower()]

    # Strategy 1: exact
    if lower in programs:
        return programs[lower]

    # Strategy 2: _main suffix
    if f"{lower}_main" in programs:
        return programs[f"{lower}_main"]

    # Strategy 3: prefix match (program starts with exec_name)
    for pname in programs:
        if pname.startswith(lower) and (
            pname == lower or pname[len(lower):].startswith("_")
        ):
            return programs[pname]

    # Strategy 4: exec starts with program
    for pname in programs:
        if lower.startswith(pname) and (
            len(lower) == len(pname) or lower[len(pname)] == "_"
        ):
            return programs[pname]

    # Strategy 5: progressive suffix stripping
    parts = lower.split("_")
    for i in range(len(parts) - 1, 0, -1):
        partial = "_".join(parts[:i])
        if partial in programs:
            return programs[partial]
        if f"{partial}_main" in programs:
            return programs[f"{partial}_main"]

    return None


# ════════════════════════════════════════════════════════════════════════
# Entry point
# ════════════════════════════════════════════════════════════════════════


async def main() -> int:
    parser = build_ingestion_parser("Shell-Fortran EXECUTES bridge")
    args = parser.parse_args()

    catalog_path = os.environ.get(
        "MCP_TENANT_CATALOG_PATH",
        str(Path(__file__).parents[1] / "src" / "config" / "tenants.yaml"),
    )
    from src.config.tenants import load_catalog

    catalog = load_catalog(catalog_path)
    tenant, _ = resolve_tenant_and_mode(args, catalog)
    worktree_root = resolve_worktree_root(tenant)
    prefix = tenant.label_prefix

    print(f"[INFO] tenant={tenant.tenant_id} prefix={prefix!r} "
          f"worktree={worktree_root}")

    # Connect graph
    try:
        from _ingest_common import build_ingestion_data_access
        uda, _ = await build_ingestion_data_access()
    except Exception as e:
        print(f"[ERROR] Failed to connect data layer: {e}", file=sys.stderr)
        return 1

    graph_db = uda.graph_db

    # R7 guard: verify FortranProgram nodes exist
    check = await graph_db.query(
        f"MATCH (p:`{prefix}FortranProgram`) RETURN count(p) AS c",
        tenant=None,
    )
    count = check[0].get("c", 0) if check else 0
    if count == 0:
        print(
            f"[WARN] No {prefix}FortranProgram nodes found. "
            "Run ingest_code_v8.py first.",
            file=sys.stderr,
        )
        await uda.close()
        return 1

    # Fetch existing programs for matching
    rows = await graph_db.query(
        f"MATCH (p:`{prefix}FortranProgram`) RETURN p.name AS name",
        tenant=None,
    )
    programs: dict[str, str] = {
        r["name"].lower(): r["name"] for r in rows if r.get("name")
    }
    print(f"[INFO] {len(programs)} FortranProgram nodes available for matching")

    # Scan shell scripts for exec references
    shell_files = discover_shell_scripts(worktree_root, "full")
    report = IngestionReportWriter(tenant.tenant_id, tenant.branch, "bridge")
    matched = 0
    unmatched_set: set[str] = set()

    for path in shell_files:
        try:
            content = path.read_text(errors="replace")
        except OSError:
            continue

        refs = extract_exec_references(content)
        if not refs:
            continue

        report.increment("total_files_processed")
        rel_path = str(path.relative_to(worktree_root))

        for ref in refs:
            prog = match_exec_to_program(ref, programs)
            if prog:
                if not args.dry_run:
                    cypher = (
                        f"MATCH (s:`{prefix}ShellScript` {{path: $sp}}) "
                        f"MATCH (p:`{prefix}FortranProgram` {{name: $pn}}) "
                        f"MERGE (s)-[:EXECUTES]->(p)"
                    )
                    await graph_db.query(cypher, params={
                        "sp": rel_path, "pn": prog,
                    }, tenant=None)
                matched += 1
                report.increment("relationships_created")
            else:
                unmatched_set.add(ref)

    if args.dry_run:
        print("=" * 60)
        print("DRY-RUN SUMMARY (no writes performed)")
        print("=" * 60)
        print(f"  Shell files scanned: {len(shell_files)}")
        print(f"  EXECUTES matches:    {matched}")
        print(f"  Unmatched refs:      {len(unmatched_set)}")
        print("=" * 60)
        await uda.close()
        return 0

    print(f"[INFO] Created {matched} EXECUTES edges, "
          f"{len(unmatched_set)} unmatched refs")
    report_path = report.finalize()
    print(f"[DONE] report: {report_path}")
    await uda.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
