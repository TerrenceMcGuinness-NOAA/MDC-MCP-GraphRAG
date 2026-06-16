"""Rebuild_dedupe_aws phase (Task 11).

Reconstructs the Dedupe_Registry deterministically from the re-imported
content (R8.3, R8.4). For every re-imported Vector_Export record the entry key
is ``(tenant_id, collection_token, sha)`` where ``sha`` is the SHA-256 of the
record's content -- exactly the key the inbound dedupe used. Because the key is
a pure function of content, running the rebuild any number of times yields the
identical registry (idempotent / deterministic, R8.4).

The resulting entries are written to ``mdc-content-sha-registry`` via an
injected ``write_fn`` so unit tests avoid a live table.

Requirements: 8.3, 8.4.
"""

from __future__ import annotations

import hashlib
from typing import Callable, Iterable, Optional

from portable_export.adapters import DedupeRow
from portable_export.manifest import ExportManifest
from portable_export.serialization import jsonl_gz_decode

PHASE = "rebuild_dedupe_aws"

#: Map a manifest collection name to its stable dedupe collection token.
_COLLECTION_TOKENS = {
    "code": "code",
    "docs": "documentation",
    "jjobs": "jjobs",
    "config": "config",
}


def collection_token(collection_name: str) -> str:
    """Derive the stable dedupe collection token from an index/collection name."""
    name = collection_name.lower()
    if "code" in name:
        return "code"
    if "workflow-docs" in name or "docs" in name:
        return "documentation"
    if "jjobs" in name:
        return "jjobs"
    if "config" in name:
        return "config"
    return collection_name


def content_sha(content: str) -> str:
    """SHA-256 of the record content (stable dedupe key component)."""
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def rebuild_dedupe(
    fetch: Callable[[str], bytes],
    manifest: ExportManifest,
    *,
    write_fn: Optional[Callable[[Iterable[DedupeRow]], int]] = None,
) -> list[DedupeRow]:
    """Deterministically rebuild the registry from re-imported content.

    Returns the sorted, de-duplicated list of :class:`DedupeRow`. When
    ``write_fn`` is supplied the rows are also written to the registry.
    """
    seen: set[tuple[str, str, str]] = set()
    for entry in manifest.vector_exports:
        token = collection_token(entry.collection_name)
        for part_key in entry.parts:
            for rec in jsonl_gz_decode(fetch(part_key)):
                sha = content_sha(rec.get("content", ""))
                seen.add((entry.tenant_id, token, sha))
    rows = [
        DedupeRow(tenant_id=t, collection=c, sha=s)
        for (t, c, s) in sorted(seen)
    ]
    if write_fn is not None:
        write_fn(rows)
    return rows


__all__ = ["rebuild_dedupe", "collection_token", "content_sha", "PHASE"]
