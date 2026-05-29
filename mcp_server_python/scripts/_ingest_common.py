"""Shared helpers for tenant-aware v8 ingestion entry scripts.

Implements: Requirements 3.1, 3.2 of omd-tenants-2-v17-pilot.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.config.tenants import Tenant, TenantCatalog

# Canonical collection tokens for the (collection, sha) dedupe key.
# Entry scripts import these rather than using string literals so a typo
# cannot silently regress dedupe (the token MUST be stable across runs).
COLLECTION_DOCUMENTATION = "documentation"
COLLECTION_CODE = "code"
COLLECTION_JJOBS = "jjobs"

_LIFECYCLE_MODE_MAP = {
    "experimental": "diff",
    "staging": "full",
    "production": "full",
}
_REFUSED_LIFECYCLES = {"merged", "stale"}


def derive_mode_from_lifecycle(lifecycle: str) -> str:
    """Map tenant lifecycle to default ingestion mode.

    Raises ValueError for merged/stale (operator must choose explicitly).
    """
    if lifecycle in _REFUSED_LIFECYCLES:
        raise ValueError(
            f"lifecycle '{lifecycle}' refuses automatic ingestion — "
            f"tenant must be transitioned to a different lifecycle or "
            f"use an explicit --mode override"
        )
    if lifecycle not in _LIFECYCLE_MODE_MAP:
        raise ValueError(f"unknown lifecycle: {lifecycle!r}")
    return _LIFECYCLE_MODE_MAP[lifecycle]


def build_ingestion_parser(description: str) -> argparse.ArgumentParser:
    """Build the common argparse parser for all v8 ingestion scripts."""
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--tenant", default=None,
                   help="Tenant ID from tenants.yaml. None → catalog default (gw).")
    p.add_argument("--mode", choices=("diff", "full"), default=None,
                   help="Ingestion strategy. Default derived from tenant.lifecycle.")
    p.add_argument("--tiers", nargs="*", default=None,
                   help="Documentation tiers to ingest (documentation script only).")
    p.add_argument("--dry-run", action="store_true",
                   help="Print plan without writing to AWS.")
    p.add_argument("--delay", type=float, default=0.5,
                   help="Delay between API calls (seconds).")
    p.add_argument("--only", nargs="*", default=None,
                   help="Only process these specific sources/files.")
    return p


def resolve_tenant_and_mode(args, catalog: "TenantCatalog") -> tuple["Tenant", str]:
    """Resolve tenant from args + catalog, derive mode. Exits on error."""
    tid = args.tenant or catalog.defaults.tenant_id
    tenant = catalog.by_id(tid)
    if tenant is None:
        print(f"[ERROR] unknown tenant_id={tid!r}; known: {catalog.tenant_ids}",
              file=sys.stderr)
        raise SystemExit(1)

    if args.mode:
        mode = args.mode
    else:
        try:
            mode = derive_mode_from_lifecycle(tenant.lifecycle)
        except ValueError as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            raise SystemExit(1)

    return tenant, mode


def resolve_worktree_root(tenant: "Tenant") -> Path:
    """Resolve the worktree root, respecting MCP_WORKTREE_ROOT_OVERRIDE."""
    override = os.environ.get("MCP_WORKTREE_ROOT_OVERRIDE")
    if override:
        return Path(override) / tenant.workflow_subdir
    return tenant.workflow_root


async def build_ingestion_data_access():
    """Build and connect the data access layer for ingestion scripts.

    Returns (uda, raw_os_client) where:
      - uda is the UnifiedDataAccess facade (vector_db + graph_db)
      - raw_os_client is the underlying opensearch-py client for
        SHAIndex and direct document writes
    """
    from src.config.environment import load_config
    from src.data.backend_selector import create_data_access

    config = load_config()
    uda = await create_data_access(config)

    if uda.vector_db is None:
        raise RuntimeError(
            "vector_db is None — check OPENSEARCH_ENDPOINT env var"
        )

    raw_os_client = uda.vector_db._raw_client()
    return uda, raw_os_client
