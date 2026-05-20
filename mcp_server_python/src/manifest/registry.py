"""In-memory registry for the unified ingest manifest (Requirements
1.11, 2.2, 2.4, 5.1 – 5.4).

The :class:`ManifestRegistry` is the single in-memory representation of
``unified_manifest.json`` consulted by every MCP tool that needs to
report on knowledge-base sources. It is constructed at server boot
(see :mod:`src.manifest.loader`) and passed to
:func:`src.tools.semantic_search.register`.

Design notes
------------

* :class:`SourceEntry` is frozen — :meth:`update_source` builds a
  replacement entry rather than mutating in place. The ``_by_name``
  index is rebuilt incrementally so lookups remain O(1).
* :meth:`get_legacy_format` produces a dict structurally identical to
  the existing ``documentation_sources.json`` so the
  ``list_ingested_urls`` and ``get_ingested_urls_array`` tools can
  fall back to file-shaped data without per-tool special cases.
* :meth:`save` writes JSON with ``indent=2`` and ``sort_keys=False``
  to keep the on-disk diff stable across regenerations — fields are
  already emitted in a deterministic order by
  :meth:`SourceEntry.to_dict`.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import SourceEntry, SourceType, UnifiedManifest

log = logging.getLogger(__name__)


class ManifestRegistry:
    """In-memory view of ``unified_manifest.json``.

    Construct directly from a :class:`UnifiedManifest` (e.g. inside
    the loader after migration), or via :meth:`load` to hit disk.
    """

    def __init__(self, manifest: UnifiedManifest) -> None:
        self._manifest: UnifiedManifest = manifest
        self._by_name: dict[str, SourceEntry] = {
            s.name: s for s in manifest.sources
        }
        # Track the path the manifest was loaded from so :meth:`save`
        # can default to the same location. Set by :meth:`load`.
        self._source_path: Path | None = None

    # ── construction ─────────────────────────────────────────────────

    @classmethod
    def load(cls, path: Path | None = None) -> "ManifestRegistry":
        """Load a manifest from ``path`` (or the default candidate chain).

        This is a thin convenience wrapper around the package-level
        :func:`src.manifest.loader.load_manifest`. The full fallback
        chain (env var → bundled → legacy migration) lives there;
        this method exists so calling code can do
        ``ManifestRegistry.load()`` without importing the loader
        module separately.
        """
        # Local import to avoid a circular dependency between
        # ``registry`` and ``loader`` at module load time.
        from .loader import load_manifest

        return load_manifest(path)

    # ── filtered queries (Requirement 3.2, 3.3) ──────────────────────

    def get_sources(
        self,
        *,
        source_type: SourceType | str | None = None,
        collection: str | None = None,
        enabled_only: bool = True,
    ) -> list[SourceEntry]:
        """Return entries matching the given filters.

        ``source_type`` accepts either a :class:`SourceType` or its
        string value to keep call sites convenient. Unknown strings
        match no entries (rather than raising) — this matches the
        Node.js tool semantics where an invalid filter yields an
        empty result set.
        """
        type_filter: SourceType | None
        if isinstance(source_type, SourceType):
            type_filter = source_type
        elif isinstance(source_type, str):
            try:
                type_filter = SourceType(source_type)
            except ValueError:
                return []
        else:
            type_filter = None

        out: list[SourceEntry] = []
        for entry in self._manifest.sources:
            if enabled_only and not entry.enabled:
                continue
            if type_filter is not None and entry.source_type != type_filter:
                continue
            if collection is not None and entry.collection_target != collection:
                continue
            out.append(entry)
        return out

    def get_url_sources(self) -> list[SourceEntry]:
        """Return only ``url_crawl`` sources.

        Used by the backward-compatibility path in
        ``list_ingested_urls`` / ``get_ingested_urls_array`` which
        only ever cared about URL-based documentation. ``enabled``
        filtering is *not* applied here so the legacy view continues
        to surface disabled URLs (matching the existing
        ``documentation_sources.json`` behaviour).
        """
        return [
            s for s in self._manifest.sources
            if s.source_type == SourceType.URL_CRAWL
        ]

    # ── legacy compatibility (Requirements 2.2, 2.3, 2.4) ────────────

    def get_legacy_format(self) -> dict[str, Any]:
        """Return a ``documentation_sources.json``-compatible dict.

        Field names and value shapes match the existing
        ``documentation_sources.json`` so any code path expecting
        that dict (e.g. the resolver in ``semantic_search.py``)
        continues to work unmodified.
        """
        url_entries = self.get_url_sources()
        legacy_sources: list[dict[str, Any]] = []
        for entry in url_entries:
            legacy_sources.append(
                {
                    "name": entry.name,
                    "url": entry.get("url", ""),
                    "type": entry.get("crawl_type", ""),
                    "tier": entry.get("tier", ""),
                    "priority": entry.get("priority", 0),
                    "description": entry.description,
                    "max_pages": entry.get("max_pages", 0),
                    "enabled": entry.enabled,
                }
            )
        enabled_count = sum(1 for s in url_entries if s.enabled)
        return {
            "version": self._manifest.version,
            "description": self._manifest.description,
            "generated_by": "src.manifest.registry.ManifestRegistry",
            "total_sources": len(legacy_sources),
            "enabled_sources": enabled_count,
            "sources": legacy_sources,
        }

    # ── post-ingestion updates (Requirements 5.1, 5.4) ───────────────

    def update_source(
        self,
        name: str,
        *,
        last_ingested: str,
        doc_count: int,
    ) -> None:
        """Update the post-ingestion metadata for one source.

        Raises :class:`KeyError` if ``name`` is not registered. The
        replacement entry preserves every other field; only
        ``last_ingested`` and ``doc_count`` change.
        """
        existing = self._by_name.get(name)
        if existing is None:
            raise KeyError(
                f"ManifestRegistry.update_source: unknown source name {name!r}"
            )

        # Build the replacement entry. ``frozen=True`` means we can't
        # mutate, so we copy over every field and override the two
        # being updated.
        replacement = SourceEntry(
            name=existing.name,
            source_type=existing.source_type,
            collection_target=existing.collection_target,
            embedding_profile=existing.embedding_profile,
            enabled=existing.enabled,
            description=existing.description,
            last_ingested=str(last_ingested),
            ingestion_script=existing.ingestion_script,
            doc_count=int(doc_count),
            type_fields=dict(existing.type_fields),
        )

        # Splice in place to preserve declaration order; the index
        # picks up the new reference too.
        self._manifest.sources = [
            replacement if s.name == name else s
            for s in self._manifest.sources
        ]
        self._by_name[name] = replacement

    def update_source_from_ingest(self, name: str, doc_count: int) -> None:
        """Convenience wrapper for post-ingestion writeback.

        Stamps ``last_ingested`` with the current UTC time and
        delegates to :meth:`update_source`. Raises :class:`KeyError`
        for unknown source names (propagated from
        :meth:`update_source`).
        """
        self.update_source(
            name,
            last_ingested=datetime.now(timezone.utc).isoformat(),
            doc_count=doc_count,
        )

    # ── persistence ──────────────────────────────────────────────────

    def save(self, path: Path | None = None) -> None:
        """Persist the current manifest state to disk.

        Defaults to the path the manifest was loaded from (or the
        ``MCP_UNIFIED_MANIFEST_PATH`` env var, mirroring the loader).
        Writes pretty-printed JSON so manifests stay diff-friendly in
        version control.
        """
        target = self._resolve_save_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = self._manifest.to_dict()
        with target.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
            fh.write("\n")
        # Remember the latest path so future ``save()`` calls without
        # an explicit argument continue writing to the same file.
        self._source_path = target

    def _resolve_save_path(self, override: Path | None) -> Path:
        if override is not None:
            return Path(override)
        if self._source_path is not None:
            return self._source_path
        env = os.environ.get("MCP_UNIFIED_MANIFEST_PATH")
        if env:
            return Path(env)
        raise ValueError(
            "ManifestRegistry.save: no path supplied and no source path "
            "remembered from load. Pass path= explicitly or set "
            "MCP_UNIFIED_MANIFEST_PATH."
        )

    # ── convenience accessors ───────────────────────────────────────

    @property
    def manifest(self) -> UnifiedManifest:
        """The underlying :class:`UnifiedManifest`."""
        return self._manifest

    @property
    def version(self) -> str:
        return self._manifest.version

    @property
    def total_sources(self) -> int:
        return len(self._manifest.sources)

    @property
    def enabled_sources(self) -> int:
        return sum(1 for s in self._manifest.sources if s.enabled)

    @property
    def source_path(self) -> Path | None:
        """The path the manifest was last loaded from / saved to."""
        return self._source_path

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._by_name

    def __len__(self) -> int:
        return self.total_sources


__all__ = ["ManifestRegistry"]
