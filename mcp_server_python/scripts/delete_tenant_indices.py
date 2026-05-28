"""Tenant rollback script — removes a tenant's prefixed data.

Deletes OpenSearch indices and Neptune nodes scoped to a single
tenant's prefix. The shared mdc-content-sha-registry (system index,
cross-tenant) is NEVER touched.

Does NOT remove the EFS worktree (manual: git worktree remove).
Does NOT remove the catalog entry (manual: edit tenants.yaml).

Implements: Requirements 7.1, 7.2, 7.3 of omd-tenants-2-v17-pilot.

Usage:
  python3.12 scripts/delete_tenant_indices.py --tenant gw_v17 --dry-run
  python3.12 scripts/delete_tenant_indices.py --tenant gw_v17
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1]))


async def _delete_tenant_data(
    *,
    vector_db: Any,
    graph_db: Any,
    index_prefix: str,
    label_prefix: str,
    dry_run: bool,
) -> list[str]:
    """Core deletion logic (testable without argparse).

    Returns list of deleted index names (empty on dry-run).
    """
    all_indices = await vector_db.list_indices()
    target_indices = [
        idx for idx in all_indices
        if idx.startswith(index_prefix)
    ]

    print(f"# OpenSearch indices to delete ({len(target_indices)}):")
    for idx in target_indices:
        print(f"  - {idx}")
    print(f"# Neptune nodes to delete: labels starting with {label_prefix!r}")

    if dry_run:
        print("# [DRY-RUN] no mutations performed.")
        return []

    for idx in target_indices:
        await vector_db.delete_index(idx)

    cypher = (
        "MATCH (n) "
        "WHERE any(label IN labels(n) WHERE label STARTS WITH $prefix) "
        "DETACH DELETE n"
    )
    await graph_db.execute_cypher(cypher, {"prefix": label_prefix})

    print(f"[OK] tenant data cleaned up ({len(target_indices)} indices deleted).")
    return target_indices


async def run_delete(
    *,
    tenant_id: str,
    catalog_path: str,
    dry_run: bool,
    vector_db: Any | None = None,
    graph_db: Any | None = None,
) -> int:
    """Main logic — returns exit code (0=success, 1=unknown, 2=refused)."""
    from src.config.tenants import load_catalog

    catalog = load_catalog(catalog_path)
    tenant = catalog.by_id(tenant_id)

    if tenant is None:
        print(f"[ERROR] unknown tenant: {tenant_id!r}; "
              f"known: {catalog.tenant_ids}", file=sys.stderr)
        return 1

    # R7.3 — refuse empty-prefix tenants (protects gw baseline)
    if not tenant.index_prefix or not tenant.label_prefix:
        print(
            f"[ERROR] refusing to delete tenant {tenant_id!r} with "
            f"empty index_prefix={tenant.index_prefix!r} or "
            f"label_prefix={tenant.label_prefix!r} — this would destroy "
            f"the unprefixed baseline shared with the gw tenant",
            file=sys.stderr,
        )
        return 2

    print(f"# Plan for tenant={tenant.tenant_id} (dry_run={dry_run})")

    await _delete_tenant_data(
        vector_db=vector_db,
        graph_db=graph_db,
        index_prefix=tenant.index_prefix,
        label_prefix=tenant.label_prefix,
        dry_run=dry_run,
    )
    return 0


async def main() -> int:
    p = argparse.ArgumentParser(
        description="Remove a tenant's prefixed OpenSearch indices and Neptune nodes."
    )
    p.add_argument("--tenant", required=True,
                   help="Tenant ID whose data will be deleted.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would be deleted, then exit 0.")
    p.add_argument("--catalog", default="src/config/tenants.yaml",
                   help="Path to tenants.yaml catalog file.")
    args = p.parse_args()

    # Build real data access layer (only when not testing)
    # TODO(Phase C): wire build_unified_data_access() here
    vector_db = None
    graph_db = None

    return await run_delete(
        tenant_id=args.tenant,
        catalog_path=args.catalog,
        dry_run=args.dry_run,
        vector_db=vector_db,
        graph_db=graph_db,
    )


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
