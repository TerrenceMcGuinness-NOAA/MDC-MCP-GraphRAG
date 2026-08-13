"""Provenance stamping for tenant-aware ingestion (disk-priority-ingest, Req 3).

A single ``build_provenance`` helper returns only the *additive* metadata keys
that record how a document was ingested: which manifest source owns it, what kind
of source it came from, the resolved path, the commit SHA of the containing
repo/submodule, whether that checkout was dirty, and the embedding profile +
vector dimension actually used.

The keys are additive by design (Req 3.5): callers merge the returned dict into
their existing ``doc_meta`` (and into the ``metadata`` sub-dict of a reference
document) so no existing key or its meaning changes. Stamping provenance at
write time makes drift computable in Phase 2 (ingested SHA vs current SHA) and
makes the mis-target rollback in design.md possible (delete-by-query on
``source_kind``).
"""
from __future__ import annotations

from pathlib import Path


def build_provenance(
    *,
    source_name: str,
    source_kind: str,
    resolved_path: str | Path | None,
    commit_sha: str | None,
    dirty: bool,
    profile: str,
    dimension: int,
) -> dict:
    """Return the additive provenance metadata keys for one document.

    Parameters
    ----------
    source_name
        The manifest source that owns the file (e.g. ``"cice"``,
        ``"ufs-utils"``). Without it a document records *where* the file lives
        but not *which source owns it*, so nothing downstream can attribute a
        write to a source — and overlapping subtrees (the coupled-model paths
        inside ``sorc/ufs_model.fd``) are only inferable by prefix matching.
        ``resolve_doc_file_set`` returns the owning ``DocSource`` alongside each
        path, so the value is in hand at write time.
    source_kind
        How the content was obtained, e.g. ``"disk"`` for a worktree file.
    resolved_path
        The concrete path (or path-like) the content was read from. Stored as
        a string so the metadata is JSON-serialisable. ``None`` is preserved.
    commit_sha
        Commit SHA of the repo or submodule that contains ``resolved_path``.
        For a path nested inside another submodule the superproject (worktree
        root) HEAD is stamped uniformly; the consistency gate verifies every
        submodule is at-pin, so that SHA is a sufficient repo-level drift
        signal (see design.md).
    dirty
        Whether the containing checkout had uncommitted changes at read time.
    profile
        Embedding-profile short-name actually used (e.g. ``"titan1024"``),
        taken from the resolved embedding provider — not re-read from the env.
    dimension
        Embedding vector dimension actually produced (e.g. ``1024``).

    Returns
    -------
    dict
        Exactly the additive keys ``source_name``, ``source_kind``,
        ``resolved_path``, ``commit_sha``, ``dirty``, ``embedding_profile``,
        ``dimension``.
    """
    return {
        "source_name": source_name,
        "source_kind": source_kind,
        "resolved_path": str(resolved_path) if resolved_path is not None else None,
        "commit_sha": commit_sha,
        "dirty": bool(dirty),
        "embedding_profile": profile,
        "dimension": dimension,
    }


__all__ = ["build_provenance"]
