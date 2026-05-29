"""Content-addressed dedupe for tenant-aware ingestion.

Cross-tenant SHA-256 lookup avoids re-embedding files that are
identical between tenants (e.g. shared parm/ files between gw and
gw_v17). The registry index is unprefixed (system-level, shared
across all tenants) — the rollback script (Group G) deliberately
does NOT touch it.

Implements: Requirements 3.4, 5.1, 5.4 of omd-tenants-2-v17-pilot.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


@dataclass(frozen=True)
class DedupeResult:
    """Result of a SHA lookup against the cross-tenant registry."""

    is_duplicate: bool
    canonical_index: str | None
    canonical_id: str | None


class SHAIndex:
    """Cross-tenant SHA → (index, _id) lookup.

    The registry lives in a single unprefixed OpenSearch index
    ``mdc-content-sha-registry`` (lifecycle: shared, system-level).
    Each entry: {sha, tenant_id, index, doc_id, first_seen_at}.

    Constructor accepts an optional ``client`` (OpenSearch-like object
    with async ``search`` and ``index`` methods) for dependency
    injection. When ``client`` is None, lookup/register are no-ops
    (useful for dry-run or testing without a live backend).
    """

    REGISTRY_INDEX = "mdc-content-sha-registry"

    def __init__(self, client: Any = None):
        self._client = client

    def hash_file(self, path: Path) -> str:
        """Stream SHA-256 of a file in 64 KiB chunks."""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(64 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    async def lookup(self, sha: str) -> DedupeResult:
        """Check if a SHA exists in the cross-tenant registry."""
        if self._client is None:
            return DedupeResult(is_duplicate=False, canonical_index=None, canonical_id=None)

        import asyncio

        body = {"query": {"term": {"sha": sha}}, "size": 1}
        resp = await asyncio.to_thread(
            self._client.search, index=self.REGISTRY_INDEX, body=body
        )
        hits = resp.get("hits", {}).get("hits", [])
        if not hits:
            return DedupeResult(is_duplicate=False, canonical_index=None, canonical_id=None)

        src = hits[0]["_source"]
        return DedupeResult(
            is_duplicate=True,
            canonical_index=src["index"],
            canonical_id=src["doc_id"],
        )

    async def register(self, sha: str, *, tenant: Any, index: str, doc_id: str) -> None:
        """Register a SHA in the cross-tenant registry (upsert)."""
        if self._client is None:
            return

        import asyncio
        from datetime import datetime, timezone

        doc = {
            "sha": sha,
            "tenant_id": tenant.tenant_id,
            "index": index,
            "doc_id": doc_id,
            "first_seen_at": datetime.now(timezone.utc).isoformat(),
        }
        await asyncio.to_thread(
            self._client.index,
            index=self.REGISTRY_INDEX,
            id=sha,
            body=doc,
        )


def make_reference_document(
    *,
    tenant: Any,
    source_path: str,
    sha: str,
    canonical_index: str,
    canonical_id: str,
    canonical_tenant: str,
) -> dict:
    """Build a reference document (no embedding, no full content).

    The reference occupies one OpenSearch row, has ``embedding: null``
    (saving the Bedrock call), and is resolvable at query time by
    chasing ``metadata.canonical_index`` / ``canonical_id``.
    """
    return {
        "metadata": {
            "tenant_id": tenant.tenant_id,
            "source": source_path,
            "content_sha256": sha,
            "is_reference": True,
            "canonical_tenant": canonical_tenant,
            "canonical_index": canonical_index,
            "canonical_id": canonical_id,
        },
        "content": "<reference: see canonical doc>",
        "embedding": None,
    }
