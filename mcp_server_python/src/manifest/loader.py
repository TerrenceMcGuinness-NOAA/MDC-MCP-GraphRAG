"""Manifest loader with fallback chain (Requirements 8.1 – 8.5).

Resolves the path of ``unified_manifest.json`` from one of three
candidates and falls back to the legacy ``documentation_sources.json``
if no unified manifest can be parsed.

Resolution order (Requirements 8.1, 8.2):

1. Explicit ``path`` argument (used by tests).
2. ``MCP_UNIFIED_MANIFEST_PATH`` environment variable.
3. Bundled file at ``src/config/unified_manifest.json``.

Failure handling (Requirements 8.3, 8.4, 8.5):

* Missing manifest at every candidate → fall back to legacy
  ``documentation_sources.json`` and emit a WARNING.
* Malformed JSON → fall back to legacy and emit an ERROR (no crash).
* Successful load → emit an INFO log line with version, total source
  count, and enabled source count.
* Legacy fallback also fails → return an empty ``ManifestRegistry``
  so the server still boots.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from .models import SourceEntry, SourceType, UnifiedManifest
from .registry import ManifestRegistry

log = logging.getLogger(__name__)


#: Bundled manifest path inside the Python package
#: (``mcp_server_python/src/config/unified_manifest.json``).
BUNDLED_MANIFEST_PATH: Path = (
    Path(__file__).resolve().parent.parent / "config" / "unified_manifest.json"
)

#: Bundled legacy file at the same location used for fallback.
BUNDLED_LEGACY_PATH: Path = (
    Path(__file__).resolve().parent.parent / "config" / "documentation_sources.json"
)


# ── path resolution (Requirements 8.1, 8.2) ────────────────────────────


def resolve_manifest_path() -> Path | None:
    """Return the first existing candidate path, or ``None``.

    The search order is the env var first, then the bundled path. The
    explicit-path branch is handled by :func:`load_manifest` so this
    helper can be used independently (e.g. by ``validate_manifest.py``).
    """
    env = os.environ.get("MCP_UNIFIED_MANIFEST_PATH")
    if env:
        env_path = Path(env)
        if env_path.is_file():
            return env_path
        # Env var points to a missing file — log so an operator can
        # see why fallback is happening, then keep walking the chain.
        log.warning(
            "MCP_UNIFIED_MANIFEST_PATH=%s does not exist; trying bundled path",
            env,
        )
    if BUNDLED_MANIFEST_PATH.is_file():
        return BUNDLED_MANIFEST_PATH
    return None


# ── full loader (Requirements 8.3, 8.4, 8.5) ──────────────────────────


def load_manifest(path: Path | None = None) -> ManifestRegistry:
    """Load and validate the unified manifest, with full fallback chain.

    Parameters
    ----------
    path
        Explicit override (highest precedence). When ``None`` the
        candidate chain from :func:`resolve_manifest_path` is used.

    Returns
    -------
    ManifestRegistry
        Always returns a registry — never raises. If every load path
        fails (no unified manifest, no legacy file), the registry is
        empty so callers can boot in degraded mode.
    """
    target = Path(path) if path is not None else resolve_manifest_path()

    if target is not None and target.is_file():
        try:
            with target.open("r", encoding="utf-8") as fh:
                raw: dict[str, Any] = json.load(fh)
        except json.JSONDecodeError as exc:
            log.error(
                "[ERROR] failed to parse unified manifest at %s: %s — "
                "falling back to legacy documentation_sources.json",
                target,
                exc,
            )
            return _load_legacy_fallback()
        except OSError as exc:
            log.error(
                "[ERROR] could not read unified manifest at %s: %s — "
                "falling back to legacy documentation_sources.json",
                target,
                exc,
            )
            return _load_legacy_fallback()

        try:
            manifest = UnifiedManifest.from_dict(raw)
        except ValueError as exc:
            log.error(
                "[ERROR] invalid unified manifest at %s: %s — "
                "falling back to legacy documentation_sources.json",
                target,
                exc,
            )
            return _load_legacy_fallback()

        registry = ManifestRegistry(manifest)
        # Remember the source path so :meth:`save` can default to it.
        registry._source_path = target  # noqa: SLF001 — internal handoff
        log.info(
            "[OK] loaded unified manifest from %s (version=%s, sources=%d, enabled=%d)",
            target,
            registry.version,
            registry.total_sources,
            registry.enabled_sources,
        )
        return registry

    # No unified manifest found anywhere — fall back to legacy.
    log.warning(
        "[WARN] no unified manifest found (env var, bundled path both empty); "
        "falling back to legacy documentation_sources.json",
    )
    return _load_legacy_fallback()


# ── legacy fallback (Requirement 8.3) ─────────────────────────────────


def _load_legacy_fallback() -> ManifestRegistry:
    """Build a :class:`ManifestRegistry` from ``documentation_sources.json``.

    On further failure (missing legacy file, malformed JSON), returns
    an empty registry. The MCP server is expected to keep booting —
    only tools that depend on declared sources will degrade.
    """
    legacy_path = _resolve_legacy_path()
    if legacy_path is None:
        log.error(
            "[ERROR] legacy documentation_sources.json not found; "
            "starting with empty manifest registry"
        )
        return ManifestRegistry(_empty_manifest())

    try:
        manifest = _migrate_legacy(legacy_path)
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        log.error(
            "[ERROR] failed to migrate legacy manifest at %s: %s — "
            "starting with empty manifest registry",
            legacy_path,
            exc,
        )
        return ManifestRegistry(_empty_manifest())

    registry = ManifestRegistry(manifest)
    log.info(
        "[OK] migrated legacy manifest from %s (version=%s, url_sources=%d)",
        legacy_path,
        registry.version,
        registry.total_sources,
    )
    return registry


def _resolve_legacy_path() -> Path | None:
    """Locate the legacy ``documentation_sources.json``.

    Honors ``MCP_DOCUMENTATION_SOURCES_PATH`` (already used by
    ``semantic_search.py``) before falling back to the bundled path.
    """
    env = os.environ.get("MCP_DOCUMENTATION_SOURCES_PATH")
    if env:
        env_path = Path(env)
        if env_path.is_file():
            return env_path
    if BUNDLED_LEGACY_PATH.is_file():
        return BUNDLED_LEGACY_PATH
    # Developer fallback — the Node.js config lives at this sibling
    # path in the repository, mirroring the resolver in
    # ``semantic_search.py``.
    dev_path = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "mcp_server_node"
        / "config"
        / "documentation_sources.json"
    )
    if dev_path.is_file():
        return dev_path
    return None


def _migrate_legacy(legacy_path: Path) -> UnifiedManifest:
    """Convert ``documentation_sources.json`` → :class:`UnifiedManifest`.

    Each legacy source becomes a :class:`SourceEntry` with
    ``source_type=url_crawl`` and the legacy ``type``/``tier``/
    ``priority``/``max_pages`` fields preserved in
    :attr:`SourceEntry.type_fields`. Disabled entries are kept (the
    legacy view does too) so ``enabled=False`` URLs still render in
    the URL-listing tools.
    """
    with legacy_path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)

    if not isinstance(raw, dict):
        raise ValueError(
            f"legacy manifest at {legacy_path} is not a JSON object"
        )

    legacy_sources = raw.get("sources") or []
    if not isinstance(legacy_sources, list):
        raise ValueError(
            f"legacy manifest at {legacy_path}: 'sources' is not a list"
        )

    sources: list[SourceEntry] = []
    for entry in legacy_sources:
        if not isinstance(entry, dict):
            log.warning(
                "skipping non-object legacy source entry: %r", entry
            )
            continue
        try:
            sources.append(_legacy_entry_to_source(entry))
        except ValueError as exc:
            log.warning(
                "skipping invalid legacy entry %r: %s",
                entry.get("name", "<unnamed>"),
                exc,
            )
            continue

    return UnifiedManifest(
        version=str(raw.get("version") or "0.0.0-legacy"),
        description=str(
            raw.get("description")
            or "Migrated from documentation_sources.json"
        ),
        generated_at=raw.get("generated_at"),
        sources=sources,
    )


def _legacy_entry_to_source(entry: dict[str, Any]) -> SourceEntry:
    """Map a legacy entry to a :class:`SourceEntry`.

    Legacy entries are URL-only and use ``type`` for the crawler
    (``readthedocs`` / ``github_pages`` / etc). The unified schema
    renames this to ``crawl_type`` to free up ``source_type`` for the
    seven-way classification.
    """
    name = entry.get("name")
    url = entry.get("url")
    if not name or not url:
        raise ValueError("legacy entry missing 'name' or 'url'")

    type_fields: dict[str, Any] = {
        "url": str(url),
        "crawl_type": str(entry.get("type") or "readthedocs"),
        "max_pages": int(entry.get("max_pages") or 0),
        "tier": str(entry.get("tier") or "tier3_optional"),
    }
    # Preserve any other legacy fields (priority, local_path hints) so
    # they survive a round-trip without manual re-entry.
    for k in ("priority", "local_path"):
        if k in entry:
            type_fields[k] = entry[k]

    return SourceEntry(
        name=str(name),
        source_type=SourceType.URL_CRAWL,
        # Legacy file does not declare a target index — assume the
        # production workflow-docs target. Operators can override
        # by hand-editing the migrated manifest.
        collection_target="global-workflow-docs-v8-0-0",
        embedding_profile="titan1024",
        enabled=bool(entry.get("enabled", True)),
        description=str(entry.get("description") or ""),
        last_ingested=entry.get("last_ingested"),
        ingestion_script=entry.get("ingestion_script"),
        doc_count=int(entry.get("doc_count") or 0),
        type_fields=type_fields,
    )


def _empty_manifest() -> UnifiedManifest:
    """Build an empty :class:`UnifiedManifest` for the no-files case."""
    return UnifiedManifest(
        version="0.0.0-empty",
        description="No manifest file found at boot — running with no sources.",
        generated_at=None,
        sources=[],
    )


__all__ = [
    "BUNDLED_LEGACY_PATH",
    "BUNDLED_MANIFEST_PATH",
    "load_manifest",
    "resolve_manifest_path",
]
