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

from _ingest_dedupe import SHAIndex  # noqa: E402  (shared registry-index name)


async def _delete_tenant_data(
    *,
    graph_db: Any,
    raw_os_client: Any,
    index_prefix: str,
    label_prefix: str,
    dry_run: bool,
    tenant_id: str = "",
    clear_registry_entries: bool = False,
) -> list[str]:
    """Core deletion logic (testable without argparse).

    Index operations go through the raw opensearch-py client
    (``raw_os_client.indices.get_alias`` / ``.delete`` and
    ``raw_os_client.delete_by_query``); Neptune node deletion uses
    ``graph_db.query(..., tenant=None)``. Returns the list of deleted index
    names (empty on dry-run).
    """
    from opensearchpy.exceptions import NotFoundError

    # 1. list candidate indices via the raw client; a glob with no match
    #    raises NotFoundError → treat as zero indices, not an error.
    try:
        alias_map = await asyncio.to_thread(
            raw_os_client.indices.get_alias, index=f"{index_prefix}*"
        )
        all_prefixed = list(alias_map.keys())
    except NotFoundError:
        all_prefixed = []
    target_indices = [i for i in all_prefixed if i.startswith(index_prefix)]

    # discover Neptune labels (read-only). Neptune supports neither the any()
    # list predicate nor CALL db.labels(); DISTINCT labels(n) + a Python-side
    # filter is the supported dialect. tenant=None so _rewrite_cypher does not
    # re-prefix the query.
    label_rows = await graph_db.query(
        "MATCH (n) RETURN DISTINCT labels(n) AS labels", tenant=None
    )
    seen: set[str] = set()
    for row in label_rows:
        for lbl in (row.get("labels") or []):
            seen.add(lbl)
    target_labels = sorted(lbl for lbl in seen if lbl.startswith(label_prefix))

    print(f"# OpenSearch indices to delete ({len(target_indices)}):")
    for idx in target_indices:
        print(f"  - {idx}")
    print(f"# Neptune labels to delete ({len(target_labels)}):")
    for lbl in target_labels:
        print(f"  - {lbl}")
    if clear_registry_entries:
        print(
            f"# Registry entries to clear: {SHAIndex.REGISTRY_INDEX} "
            f"where tenant_id == {tenant_id!r} (the index itself is preserved)"
        )

    if dry_run:
        print("# [DRY-RUN] no mutations performed.")
        return []

    # 2. delete each prefixed index
    for idx in target_indices:
        await asyncio.to_thread(raw_os_client.indices.delete, index=idx)

    # 3. Neptune: one back-tick-quoted DETACH DELETE per discovered label.
    #    Labels cannot be parameterized → interpolate; tenant=None (no rewrite).
    for lbl in target_labels:
        await graph_db.query(f"MATCH (n:`{lbl}`) DETACH DELETE n", tenant=None)

    # 4. registry delete-by-query (only with the flag); index itself preserved.
    if clear_registry_entries:
        await asyncio.to_thread(
            raw_os_client.delete_by_query,
            index=SHAIndex.REGISTRY_INDEX,
            body={"query": {"term": {"tenant_id": tenant_id}}},
        )
        print(f"[OK] cleared registry entries for tenant_id={tenant_id!r}.")

    print(f"[OK] tenant data cleaned up ({len(target_indices)} indices deleted).")
    return target_indices


async def run_delete(
    *,
    tenant_id: str,
    catalog_path: str,
    dry_run: bool,
    vector_db: Any | None = None,
    graph_db: Any | None = None,
    raw_os_client: Any | None = None,
    clear_registry_entries: bool = False,
) -> int:
    """Main logic — returns exit code (0=success, 1=unknown, 2=refused).

    ``vector_db`` is accepted for call-site symmetry / the DI test seam but is
    not used for index management — those operations go through the raw
    opensearch-py client (``raw_os_client``).
    """
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
        graph_db=graph_db,
        raw_os_client=raw_os_client,
        index_prefix=tenant.index_prefix,
        label_prefix=tenant.label_prefix,
        dry_run=dry_run,
        tenant_id=tenant.tenant_id,
        clear_registry_entries=clear_registry_entries,
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
    p.add_argument("--clear-registry-entries", action="store_true",
                   help="Also clear this tenant's entries in the shared "
                        "mdc-content-sha-registry (the index itself is preserved).")
    args = p.parse_args()

    # Build the real connected data layer (same helper the ingestion scripts use).
    from _ingest_common import build_ingestion_data_access

    uda = None
    try:
        uda, raw_os_client = await build_ingestion_data_access()
    except Exception as e:
        print(f"[ERROR] failed to connect data layer: {e}", file=sys.stderr)
        print("  Check DB_BACKEND / OPENSEARCH_ENDPOINT / NEPTUNE_ENDPOINT / AWS_REGION",
              file=sys.stderr)
        return 1

    try:
        return await run_delete(
            tenant_id=args.tenant,
            catalog_path=args.catalog,
            dry_run=args.dry_run,
            vector_db=uda.vector_db,
            graph_db=uda.graph_db,
            raw_os_client=raw_os_client,
            clear_registry_entries=args.clear_registry_entries,
        )
    finally:
        if uda is not None:
            await uda.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
