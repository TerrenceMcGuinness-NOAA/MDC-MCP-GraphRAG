"""Unified ingest manifest data models (Requirements 1.1 – 1.10).

This module defines the dataclasses backing ``unified_manifest.json``
the SPOT (Source of Production Truth) declaration of every ingestion
source in the knowledge base. The manifest extends the URL-only
``documentation_sources.json`` to all seven source types feeding the
OpenSearch + Neptune knowledge base.

Top-level shapes:

* :class:`SourceType` — string enum of the seven valid source types.
* :class:`SourceEntry` — frozen dataclass for a single source. Common
  fields (``name``, ``source_type``, ``collection_target``,
  ``embedding_profile``, ``enabled``, ``description``,
  ``last_ingested``, ``ingestion_script``, ``doc_count``) are explicit
  fields; type-specific fields (``url``, ``crawl_type``, ``local_path``,
  ``parser`` …) live in the ``type_fields`` dict so each source_type
  can carry its own schema without bloating the base dataclass.
* :class:`UnifiedManifest` — top-level wrapper with ``version``,
  ``description``, ``generated_at``, and a list of :class:`SourceEntry`.

Both dataclasses provide ``to_dict`` / ``from_dict`` round-trip helpers
that produce JSON-serializable output with deterministic key ordering
so manifest files are diffable across regenerations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping


# ── source-type enum (Requirement 1.2) ────────────────────────────────


class SourceType(str, Enum):
    """Valid values for :attr:`SourceEntry.source_type`.

    String-Enum so JSON serialization yields the bare value (e.g.
    ``"url_crawl"``) rather than ``"SourceType.URL_CRAWL"``.
    """

    URL_CRAWL = "url_crawl"
    ON_DISK_SUBMODULE = "on_disk_submodule"
    CODE_PARSE = "code_parse"
    CONFIG_PARSE = "config_parse"
    STANDARDS = "standards"
    COMMUNITY_SUMMARY = "community_summary"
    JJOB_DOCS = "jjob_docs"


#: Common fields every :class:`SourceEntry` must declare (Requirement 1.10).
_COMMON_REQUIRED_FIELDS: tuple[str, ...] = (
    "name",
    "source_type",
    "collection_target",
    "embedding_profile",
    "enabled",
    "description",
)

#: Per-source-type required fields enforced in :meth:`SourceEntry.from_dict`
#: (Requirements 1.3 – 1.9). A field is "required" only in that the
#: deserializer rejects entries missing it; default values are not
#: imputed because the manifest is human-curated.
_TYPE_SPECIFIC_REQUIRED: dict[SourceType, tuple[str, ...]] = {
    SourceType.URL_CRAWL: ("url", "crawl_type", "max_pages", "tier"),
    SourceType.ON_DISK_SUBMODULE: ("local_path", "file_patterns", "parser"),
    SourceType.CODE_PARSE: ("root_path", "languages", "chunk_strategy"),
    SourceType.CONFIG_PARSE: ("config_root", "file_patterns", "parser"),
    SourceType.STANDARDS: ("standards_source", "document_count"),
    SourceType.COMMUNITY_SUMMARY: ("graph_source", "community_algorithm"),
    SourceType.JJOB_DOCS: ("job_script_root", "documentation_format"),
}


# ── SourceEntry (Requirements 1.3 – 1.10) ──────────────────────────────


@dataclass(frozen=True)
class SourceEntry:
    """A single ingestion source entry in the unified manifest.

    The dataclass is ``frozen=True`` so registry-level updates
    (``ManifestRegistry.update_source``) must produce a replacement
    entry rather than mutating in place — keeping the in-memory state
    immutable simplifies reasoning about concurrent reads.

    Type-specific fields (e.g. ``url`` for ``url_crawl``,
    ``local_path`` for ``on_disk_submodule``) are stored in
    :attr:`type_fields` so the dataclass shape stays uniform across
    source types. Use :meth:`get` for a flat view that includes both
    common and type-specific fields.
    """

    name: str
    source_type: SourceType
    collection_target: str
    embedding_profile: str
    enabled: bool
    description: str
    last_ingested: str | None = None
    ingestion_script: str | None = None
    doc_count: int = 0
    type_fields: Mapping[str, Any] = field(default_factory=dict)

    # ── flat-view accessor ───────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        """Return ``key`` from the entry, looking in common fields first
        then ``type_fields``.

        Convenience for renderers that want to treat common +
        type-specific fields uniformly without reaching into
        ``type_fields``.
        """
        if key in {
            "name",
            "source_type",
            "collection_target",
            "embedding_profile",
            "enabled",
            "description",
            "last_ingested",
            "ingestion_script",
            "doc_count",
        }:
            value = getattr(self, key)
            if isinstance(value, SourceType):
                return value.value
            return value
        return self.type_fields.get(key, default)

    # ── serialization ────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready dict representation.

        Common fields appear first in a stable order, followed by
        type-specific fields in their original declaration order. This
        makes the on-disk manifest diff-friendly across regenerations.
        """
        out: dict[str, Any] = {
            "name": self.name,
            "source_type": self.source_type.value,
            "collection_target": self.collection_target,
            "embedding_profile": self.embedding_profile,
            "enabled": self.enabled,
            "description": self.description,
            "last_ingested": self.last_ingested,
            "ingestion_script": self.ingestion_script,
            "doc_count": self.doc_count,
        }
        # Append type-specific fields in their declared order so the
        # JSON output is stable across regenerations.
        for k, v in self.type_fields.items():
            if k in out:
                continue
            out[k] = v
        return out

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "SourceEntry":
        """Construct a :class:`SourceEntry` from a JSON dict.

        Validates common required fields (Requirement 1.10) and the
        type-specific required fields for the declared
        ``source_type`` (Requirements 1.3 – 1.9). Raises
        :class:`ValueError` on validation failure with a message
        identifying the offending source name and field.
        """
        if not isinstance(raw, Mapping):
            raise ValueError(
                f"SourceEntry.from_dict: expected mapping, got {type(raw).__name__}"
            )

        name = raw.get("name")
        # Common-field validation. Empty strings on required fields are
        # treated as missing — they would render as blank rows in the
        # MCP tools and are never a valid manifest entry.
        for fld in _COMMON_REQUIRED_FIELDS:
            if fld not in raw:
                raise ValueError(
                    f"SourceEntry {name!r}: missing required field {fld!r}"
                )

        # Coerce source_type into the enum so the rest of the codebase
        # can rely on enum-value comparisons. ``SourceType(value)`` raises
        # ValueError for unknown strings — re-raise with context.
        raw_type = raw["source_type"]
        try:
            source_type = SourceType(raw_type)
        except ValueError as exc:
            raise ValueError(
                f"SourceEntry {name!r}: invalid source_type {raw_type!r} "
                f"(valid values: {[t.value for t in SourceType]})"
            ) from exc

        # Type-specific required fields (Requirements 1.3 – 1.9).
        for fld in _TYPE_SPECIFIC_REQUIRED.get(source_type, ()):
            if fld not in raw:
                raise ValueError(
                    f"SourceEntry {name!r} ({source_type.value}): missing "
                    f"required type-specific field {fld!r}"
                )

        # Pull the type-specific fields out of the raw dict so they
        # land in ``type_fields`` and not as unknown kwargs.
        common_keys = set(_COMMON_REQUIRED_FIELDS) | {
            "last_ingested",
            "ingestion_script",
            "doc_count",
        }
        type_fields: dict[str, Any] = {
            k: v for k, v in raw.items() if k not in common_keys
        }

        return cls(
            name=str(raw["name"]),
            source_type=source_type,
            collection_target=str(raw["collection_target"]),
            embedding_profile=str(raw["embedding_profile"]),
            enabled=bool(raw["enabled"]),
            description=str(raw["description"]),
            last_ingested=raw.get("last_ingested"),
            ingestion_script=raw.get("ingestion_script"),
            doc_count=int(raw.get("doc_count") or 0),
            type_fields=type_fields,
        )


# ── UnifiedManifest (Requirements 1.1, 1.2) ───────────────────────────


@dataclass
class UnifiedManifest:
    """Top-level manifest container.

    ``generated_at`` is an ISO-8601 timestamp recorded by the
    generation script; it has no bearing on runtime behaviour and is
    optional so hand-curated manifests don't need to carry one.
    """

    version: str
    description: str
    generated_at: str | None
    sources: list[SourceEntry] = field(default_factory=list)

    # ── serialization ────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready dict representation (deterministic order)."""
        return {
            "version": self.version,
            "description": self.description,
            "generated_at": self.generated_at,
            "sources": [s.to_dict() for s in self.sources],
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "UnifiedManifest":
        """Construct a manifest from a JSON dict.

        ``raw["sources"]`` is delegated to :meth:`SourceEntry.from_dict`;
        any per-entry validation error propagates with the offending
        entry name in its message.
        """
        if not isinstance(raw, Mapping):
            raise ValueError(
                f"UnifiedManifest.from_dict: expected mapping, "
                f"got {type(raw).__name__}"
            )
        if "version" not in raw:
            raise ValueError("UnifiedManifest: missing required field 'version'")
        if "sources" not in raw or not isinstance(raw["sources"], Iterable):
            raise ValueError(
                "UnifiedManifest: 'sources' must be a list of source entries"
            )

        sources = [SourceEntry.from_dict(s) for s in raw["sources"]]
        return cls(
            version=str(raw["version"]),
            description=str(raw.get("description") or ""),
            generated_at=raw.get("generated_at"),
            sources=sources,
        )


__all__ = [
    "SourceEntry",
    "SourceType",
    "UnifiedManifest",
]
