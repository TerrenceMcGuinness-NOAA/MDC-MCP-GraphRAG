"""Shared helpers for tenant-aware v8 ingestion entry scripts.

Implements: Requirements 3.1, 3.2 of omd-tenants-2-v17-pilot.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

# Ensure the server root is importable so the module-level
# ``src.data.collection_namer`` import below resolves whether this module is
# imported by an ingester (which sets up sys.path) or standalone.
_SERVER_ROOT = str(Path(__file__).resolve().parents[1])
if _SERVER_ROOT not in sys.path:
    sys.path.insert(0, _SERVER_ROOT)

if TYPE_CHECKING:
    from src.config.tenants import Tenant, TenantCatalog

# Canonical collection tokens for the (collection, sha) dedupe key.
# Entry scripts import these rather than using string literals so a typo
# cannot silently regress dedupe (the token MUST be stable across runs).
COLLECTION_DOCUMENTATION = "documentation"
COLLECTION_CODE = "code"
COLLECTION_JJOBS = "jjobs"
COLLECTION_CONFIG = "config"
# Graph-only token for the Fortran AST ingester. Unused for dedupe (Fortran
# ingestion is graph-only and relies on Neptune MERGE for idempotency) but
# kept consistent with the other collection tokens.
COLLECTION_FORTRAN_GRAPH = "fortran_graph"

_LIFECYCLE_MODE_MAP = {
    "experimental": "diff",
    "staging": "full",
    "production": "full",
}
_REFUSED_LIFECYCLES = {"merged", "stale"}

# ── Collection versioning (cots-reingest-ralph-loop, Requirement 1.2/4.1) ──
# The serving collections carry no version suffix on their physical names, so
# the default version returns names UNCHANGED — preserving current behaviour
# byte-for-byte. A non-default version appends ``-<version>`` so a fresh,
# isolated collection set is built alongside the serving one.
#
# DEFAULT_COLLECTION_VERSION + the scope-aware resolve_collection_name are the
# single naming authority (rag-data-plane-gap-closure R3) — imported here so
# the ingesters can reach them via the existing _ingest_common import surface.
from src.data.collection_namer import (  # noqa: E402
    DEFAULT_COLLECTION_VERSION,
    resolve_collection_name,
)


def resolve_collection_version(args) -> str:
    """Resolve the target Collection_Version for an ingest run.

    Precedence: ``--collection-version`` > env ``REINGEST_COLLECTION_VERSION``
    > :data:`DEFAULT_COLLECTION_VERSION` (which preserves current serving
    behaviour).
    """
    cv = getattr(args, "collection_version", None)
    if cv:
        return cv
    return os.environ.get("REINGEST_COLLECTION_VERSION") or DEFAULT_COLLECTION_VERSION


def versioned_collection_name(base: str, version: str) -> str:
    """Return ``base`` for the default version, else ``base-<version>``.

    Threads the single Collection_Version value through every target
    collection/index name so one value drives them all (Requirement 1.2). The
    default version is a no-op so existing collections and the serving layer's
    ``resolve_index`` mapping are untouched (Requirement 4.1).
    """
    if not version or version == DEFAULT_COLLECTION_VERSION:
        return base
    return f"{base}-{version}"


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
    p.add_argument("--collection-version", default=None,
                   help="Target Collection_Version (env REINGEST_COLLECTION_VERSION). "
                        "Default preserves current serving collection names.")
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


async def write_vector_doc(
    uda,
    raw_os_client,
    *,
    index: str,
    doc_id: str,
    content: str,
    metadata: dict,
    embedding,
) -> None:
    """Write one embedded document to the active vector backend.

    AWS: index into OpenSearch via the raw client. COTS: upsert into ChromaDB
    via the adapter (``raw_os_client`` is None there). Lets the v8 vector
    ingesters run unchanged on either backend (cots-reingest-ralph-loop).
    """
    import asyncio as _asyncio

    if raw_os_client is not None:
        body = {"content": content, "metadata": metadata, "embedding": embedding}
        await _asyncio.to_thread(raw_os_client.index, index=index, id=doc_id, body=body)
    else:
        await uda.vector_db.upsert_document(
            collection=index, doc_id=doc_id, content=content,
            metadata=metadata, embedding=embedding,
        )


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

    # AWS OpenSearchAdapter exposes ``_raw_client``; the COTS ChromaDBAdapter
    # does not (it has a collection-based API, not an OpenSearch client). On
    # COTS return None so the graph-only ingesters (which never touch the raw
    # client) can still connect and run; the vector ingesters remain gated on
    # a ChromaDB write path (out of scope here). AWS behaviour is unchanged.
    raw_client_fn = getattr(uda.vector_db, "_raw_client", None)
    raw_os_client = raw_client_fn() if callable(raw_client_fn) else None
    return uda, raw_os_client
