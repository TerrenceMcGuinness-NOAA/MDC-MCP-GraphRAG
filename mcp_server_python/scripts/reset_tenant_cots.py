#!/usr/bin/env python3
"""reset_tenant_cots.py — COTS-aware tenant reset (ChromaDB + Neo4j).

The COTS sibling of ``delete_tenant_indices.py`` (which drives OpenSearch +
Neptune, AWS only). Removes, for a target Collection_Version and tenant:

  * the tenant's target ChromaDB collections (scoped by ``index_prefix`` +
    the version-tagged names derived from the SAME helper the ingesters use,
    so a fresh version never touches the serving/unversioned collections), and
  * the tenant's Neo4j graph nodes (scoped by ``label_prefix``; for the default
    ``gw`` tenant, only version-stamped nodes, never the serving baseline).

Guards (Requirement 9, 11.4):
  * ``CONFIRM_DESTRUCTIVE=yes`` is required for any real deletion.
  * ``--dry-run`` prints the plan and touches nothing.
  * a ChromaDB data-dir snapshot + a Neo4j dump are attempted BEFORE any real
    deletion (Requirement 9.3); ``--skip-backup`` overrides with a loud warning.
  * the reset is idempotent — deleting an already-absent collection/label is a
    no-op success (Requirement 9.4).

Spec: .kiro/specs/cots-reingest-ralph-loop/ (Tasks 3.1, 3.2).

Usage:
  python3 scripts/reset_tenant_cots.py --tenant gw_v17 --collection-version v9-0-0 --dry-run
  CONFIRM_DESTRUCTIVE=yes python3 scripts/reset_tenant_cots.py --tenant gw_v17 --collection-version v9-0-0
"""
from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_SERVER_ROOT = _SCRIPT_DIR.parent
_REPO_ROOT = _SERVER_ROOT.parent
for _p in (str(_SCRIPT_DIR), str(_SERVER_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _ingest_common import DEFAULT_COLLECTION_VERSION
from src.data.collection_namer import resolve_collection_name

# Tenant-scoped content domains a per-tenant reset OWNS. Documentation,
# EE2 standards, and community summaries are SHARED (unprefixed, NWS-wide)
# — a per-tenant reset must NEVER touch them (rag-data-plane-gap-closure
# R3.4), so they are deliberately excluded here. Names are derived from the
# single scope-aware namer so reset and the ingesters always agree.
_TENANT_DOMAINS = (
    "code-context",   # ingest_code_v8 + ingest_config_files_v8
    "jjobs",          # ingest_jjobs_v8
)


def _utcnow_tag() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}] {msg}")


# ---------------------------------------------------------------------------
# Scope computation
# ---------------------------------------------------------------------------


def compute_target_collections(tenant: Any, version: str) -> list[str]:
    """Version-tagged ChromaDB collection names this tenant+version owns.

    Derived through the single scope-aware namer (R3.3) over the tenant-scoped
    domains only; shared collections are never in a per-tenant reset's scope.
    """
    return [
        resolve_collection_name(
            domain=domain, scope="tenant", tenant=tenant, version=version
        )
        for domain in _TENANT_DOMAINS
    ]


# ---------------------------------------------------------------------------
# Backup hook (Requirement 9.3)
# ---------------------------------------------------------------------------


def _backup(*, tenant_id: str, version: str, backup_dir: Path) -> dict[str, Any]:
    """Best-effort pre-reset snapshot of ChromaDB data dir + Neo4j dump.

    Returns a dict of captured artifact paths (or reasons they were skipped).
    Never raises — the caller decides whether an empty capture blocks the reset.
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    tag = _utcnow_tag()
    captured: dict[str, Any] = {"chromadb": None, "neo4j": None}

    # ChromaDB data dir snapshot.
    data_dir = os.environ.get("CHROMADB_DATA_DIR")
    candidates = [data_dir] if data_dir else [
        str(_REPO_ROOT / "chromadb_data"),
        "/mcp_rag_eib/chromadb_data",
    ]
    src = next((c for c in candidates if c and Path(c).is_dir()), None)
    if src:
        dest = backup_dir / f"chromadb_{tag}.tar.gz"
        try:
            with tarfile.open(dest, "w:gz") as tar:
                tar.add(src, arcname=Path(src).name)
            captured["chromadb"] = str(dest)
            _log(f"[OK] ChromaDB snapshot -> {dest}")
        except Exception as exc:  # pragma: no cover - filesystem dependent
            captured["chromadb"] = f"FAILED: {exc}"
            _log(f"[WARN] ChromaDB snapshot failed: {exc}")
    else:
        captured["chromadb"] = "SKIPPED: data dir not located (set CHROMADB_DATA_DIR)"
        _log("[WARN] ChromaDB data dir not located; set CHROMADB_DATA_DIR to enable snapshot")

    # Neo4j dump (best-effort; community edition may require the DB stopped).
    admin = shutil.which("neo4j-admin")
    if admin:
        dest = backup_dir / f"neo4j_{tag}.dump"
        for cmd in (
            [admin, "database", "dump", "neo4j", f"--to-path={backup_dir}"],
            [admin, "dump", f"--to={dest}"],
        ):
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=1800)
                captured["neo4j"] = str(dest)
                _log(f"[OK] Neo4j dump -> {backup_dir}")
                break
            except Exception as exc:  # pragma: no cover - env dependent
                captured["neo4j"] = f"FAILED: {exc}"
        if isinstance(captured["neo4j"], str) and captured["neo4j"].startswith("FAILED"):
            _log(f"[WARN] Neo4j dump failed: {captured['neo4j']}")
    else:
        captured["neo4j"] = "SKIPPED: neo4j-admin not on PATH"
        _log("[WARN] neo4j-admin not on PATH; Neo4j dump skipped")

    return captured


# ---------------------------------------------------------------------------
# Core reset
# ---------------------------------------------------------------------------


async def run_reset(
    *,
    tenant: Any,
    version: str,
    dry_run: bool,
    reset_vectors: bool,
    reset_graph: bool,
    version_scoped_labels: bool,
    allow_inplace_default: bool,
    chroma_client: Any = None,
    graph_db: Any = None,
) -> int:
    """Execute (or plan) the reset. Returns an exit code."""
    index_prefix = tenant.index_prefix
    label_prefix = tenant.label_prefix
    in_place_default = version == DEFAULT_COLLECTION_VERSION

    # R9.1 / baseline protection: refuse an in-place default rebuild of the
    # shared (empty-prefix) gw baseline unless explicitly allowed.
    if in_place_default and not index_prefix and not allow_inplace_default:
        _log("[ERROR] refusing in-place rebuild of the default serving version "
             f"({DEFAULT_COLLECTION_VERSION}) for the empty-prefix baseline "
             "tenant — pass --allow-inplace-default to override (this DELETES "
             "the serving collections).")
        return 2

    target_collections = compute_target_collections(tenant, version)

    _log(f"# Reset plan: tenant={tenant.tenant_id} version={version} "
         f"(dry_run={dry_run}, in_place_default={in_place_default})")

    # ── ChromaDB scope ──
    chroma_present: list[str] = []
    if reset_vectors and chroma_client is not None:
        existing = {c.name for c in chroma_client.list_collections()}
        chroma_present = [c for c in target_collections if c in existing]
        _log(f"# ChromaDB collections to delete ({len(chroma_present)} of "
             f"{len(target_collections)} targets present):")
        for c in target_collections:
            mark = "DELETE" if c in existing else "absent (no-op)"
            _log(f"  - {c}  [{mark}]")

    # ── Neo4j scope ──
    graph_plan = ""
    if reset_graph and graph_db is not None:
        if label_prefix:
            if version_scoped_labels:
                graph_plan = (
                    f"nodes with a label starting '{label_prefix}' AND "
                    f"collection_version = '{version}'"
                )
            else:
                graph_plan = f"ALL nodes with a label starting '{label_prefix}'"
        else:
            # Default gw: only ever version-stamped nodes, never the baseline.
            graph_plan = (
                f"default-tenant nodes with collection_version = '{version}' "
                f"(baseline unversioned nodes are NEVER touched)"
            )
        _log(f"# Neo4j nodes to delete: {graph_plan}")

    if dry_run:
        _log("# [DRY-RUN] no mutations performed.")
        return 0

    # ── Execute ChromaDB deletes (idempotent) ──
    if reset_vectors and chroma_client is not None:
        for c in chroma_present:
            chroma_client.delete_collection(c)
            _log(f"[OK] deleted ChromaDB collection: {c}")

    # ── Execute Neo4j deletes ──
    if reset_graph and graph_db is not None:
        deleted = await _delete_graph_nodes(
            graph_db=graph_db,
            label_prefix=label_prefix,
            version=version,
            version_scoped_labels=version_scoped_labels,
        )
        _log(f"[OK] deleted {deleted} Neo4j nodes ({graph_plan})")

    _log(f"[OK] reset complete for tenant={tenant.tenant_id} version={version}")
    return 0


async def _delete_graph_nodes(
    *,
    graph_db: Any,
    label_prefix: str,
    version: str,
    version_scoped_labels: bool,
) -> int:
    """Delete the scoped nodes; returns the count removed. Idempotent."""
    if label_prefix:
        # tenant=None so the adapter does NOT re-prefix our label predicate.
        if version_scoped_labels:
            cypher = (
                "MATCH (n) WHERE any(l IN labels(n) WHERE l STARTS WITH $p) "
                "AND n.collection_version = $cv "
                "WITH n LIMIT 100000 DETACH DELETE n RETURN count(n) AS c"
            )
            params = {"p": label_prefix, "cv": version}
        else:
            cypher = (
                "MATCH (n) WHERE any(l IN labels(n) WHERE l STARTS WITH $p) "
                "WITH n LIMIT 100000 DETACH DELETE n RETURN count(n) AS c"
            )
            params = {"p": label_prefix}
    else:
        # Default gw: version-stamped nodes ONLY (never the serving baseline).
        cypher = (
            "MATCH (n) WHERE n.collection_version = $cv "
            "WITH n LIMIT 100000 DETACH DELETE n RETURN count(n) AS c"
        )
        params = {"cv": version}

    total = 0
    while True:
        rows = await graph_db.query(cypher, params=params, tenant=None)
        n = int(rows[0]["c"]) if rows else 0
        total += n
        if n == 0:
            break
    return total


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


async def main() -> int:
    p = argparse.ArgumentParser(
        description="COTS-aware tenant reset (ChromaDB collections + Neo4j nodes)."
    )
    p.add_argument("--tenant", required=True, help="Tenant ID from tenants.yaml.")
    p.add_argument("--collection-version",
                   default=os.environ.get("REINGEST_COLLECTION_VERSION", "v9-0-0"),
                   help="Target Collection_Version to reset.")
    p.add_argument("--catalog",
                   default=os.environ.get(
                       "MCP_TENANT_CATALOG_PATH",
                       str(_SERVER_ROOT / "src" / "config" / "tenants.yaml")))
    p.add_argument("--dry-run", action="store_true",
                   help="Print the plan and exit 0 without deleting.")
    p.add_argument("--no-reset-vectors", action="store_true",
                   help="Skip ChromaDB collection deletion.")
    p.add_argument("--no-reset-graph", action="store_true",
                   help="Skip Neo4j node deletion.")
    p.add_argument("--version-scoped-labels", action="store_true",
                   help="Force: delete only nodes whose collection_version "
                        "matches (default for a fresh/alongside version).")
    p.add_argument("--full-prefix-wipe", action="store_true",
                   help="Force: delete ALL of a non-default tenant's prefixed "
                        "nodes (in-place rebuild; DESTRUCTIVE to that tenant's "
                        "serving graph).")
    p.add_argument("--allow-inplace-default", action="store_true",
                   help="Permit deleting the serving default-version / "
                        "empty-prefix baseline (DESTRUCTIVE to serving data).")
    p.add_argument("--skip-backup", action="store_true",
                   help="Skip the pre-reset backup (only if you backed up "
                        "externally). Loudly discouraged.")
    p.add_argument("--backup-dir",
                   default=str(_REPO_ROOT / "backups" / "reingest"),
                   help="Directory for pre-reset snapshots.")
    args = p.parse_args()

    from src.config.tenants import load_catalog

    catalog = load_catalog(args.catalog)
    tenant = catalog.by_id(args.tenant)
    if tenant is None:
        _log(f"[ERROR] unknown tenant: {args.tenant!r}; known: {catalog.tenant_ids}")
        return 1

    # Destructive gate (Requirement 11.4).
    if not args.dry_run and os.environ.get("CONFIRM_DESTRUCTIVE") != "yes":
        _log("[ERROR] refusing to delete without CONFIRM_DESTRUCTIVE=yes "
             "(use --dry-run to preview).")
        return 2

    # Safe default: for a FRESH (alongside) version, scope graph deletes to that
    # version's stamped nodes so the serving graph is never touched (Req 1.3).
    # Full-prefix wipe only for an in-place rebuild or when explicitly forced.
    in_place_default = args.collection_version == DEFAULT_COLLECTION_VERSION
    version_scoped = args.version_scoped_labels or (
        not in_place_default and not args.full_prefix_wipe
    )
    if args.full_prefix_wipe and not in_place_default:
        _log("[WARN] --full-prefix-wipe on a fresh version will DELETE this "
             "tenant's entire serving graph for its prefix.")

    # Pre-reset backup (Requirement 9.3) — before ANY mutation.
    if not args.dry_run and not args.skip_backup:
        backup_dir = Path(args.backup_dir) / args.collection_version
        captured = _backup(tenant_id=tenant.tenant_id,
                           version=args.collection_version, backup_dir=backup_dir)
        got_any = any(
            isinstance(v, str) and not v.startswith(("SKIPPED", "FAILED"))
            for v in captured.values()
        )
        if not got_any:
            _log("[ERROR] no backup artifact was captured and --skip-backup was "
                 "not set; refusing to reset. Back up manually or pass "
                 "--skip-backup after confirming an external backup exists.")
            return 2

    # Build COTS clients directly (ChromaDBAdapter has no OpenSearch raw client).
    chroma_client = None
    graph_db = None
    if not args.no_reset_vectors:
        try:
            import chromadb
            chroma_client = chromadb.HttpClient(
                host=os.environ.get("CHROMADB_HOST", "localhost"),
                port=int(os.environ.get("CHROMADB_PORT", "8080")),
            )
        except Exception as exc:
            _log(f"[ERROR] could not connect ChromaDB: {exc}")
            return 1
    if not args.no_reset_graph:
        from src.data.neo4j_adapter import Neo4jAdapter
        graph_db = Neo4jAdapter(
            uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
            user=os.environ.get("NEO4J_USER", "neo4j"),
            password=os.environ.get("NEO4J_PASSWORD", "gfsworkflow2025"),
        )
        try:
            await graph_db.connect()
        except Exception as exc:
            _log(f"[ERROR] could not connect Neo4j: {exc}")
            return 1

    try:
        return await run_reset(
            tenant=tenant,
            version=args.collection_version,
            dry_run=args.dry_run,
            reset_vectors=not args.no_reset_vectors,
            reset_graph=not args.no_reset_graph,
            version_scoped_labels=version_scoped,
            allow_inplace_default=args.allow_inplace_default,
            chroma_client=chroma_client,
            graph_db=graph_db,
        )
    finally:
        if graph_db is not None:
            await graph_db.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
