"""Unit tests for the manifest ``scope`` field (rag-data-plane-gap-closure R1).

Covers Task 1.4: schema round-trip; a missing ``scope`` raises; an unknown
``scope`` value raises. Also verifies the live ``unified_manifest.json`` loads
and that ``scope`` sits in the stable common-field ordering (right after
``description``).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.manifest.models import SourceEntry, SourceType, UnifiedManifest

_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2] / "src" / "config" / "unified_manifest.json"
)


def _valid_raw(**overrides) -> dict:
    base = {
        "name": "sample",
        "source_type": "url_crawl",
        "collection_target": "global-workflow-docs-v8-0-0",
        "embedding_profile": "titan1024",
        "enabled": True,
        "description": "a source",
        "scope": "shared",
        "url": "https://example.com",
        "crawl_type": "readthedocs",
        "max_pages": 10,
        "tier": "tier1",
    }
    base.update(overrides)
    return base


def test_scope_round_trip_stable() -> None:
    """A valid entry serializes with scope right after description and re-loads."""
    entry = SourceEntry.from_dict(_valid_raw(scope="tenant", source_type="code_parse",
                                             root_path="x", languages=["fortran"],
                                             chunk_strategy="function_boundary"))
    assert entry.scope == "tenant"
    out = entry.to_dict()
    keys = list(out.keys())
    assert keys[keys.index("description") + 1] == "scope"
    # Round-trip is stable.
    again = SourceEntry.from_dict(out)
    assert again.scope == "tenant"
    assert again.to_dict() == out


def test_missing_scope_raises() -> None:
    raw = _valid_raw()
    del raw["scope"]
    with pytest.raises(ValueError, match=r"missing required field 'scope'"):
        SourceEntry.from_dict(raw)


def test_unknown_scope_raises() -> None:
    with pytest.raises(ValueError, match=r"invalid scope 'global'"):
        SourceEntry.from_dict(_valid_raw(scope="global"))


def test_scope_not_swept_into_type_fields() -> None:
    entry = SourceEntry.from_dict(_valid_raw())
    assert "scope" not in entry.type_fields


def test_live_manifest_loads_with_scope_on_every_source() -> None:
    """The regenerated unified_manifest.json carries scope on every source (R1.5)."""
    manifest = UnifiedManifest.from_dict(
        json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    )
    assert manifest.sources, "manifest has no sources"
    for src in manifest.sources:
        assert src.scope in {"tenant", "shared"}, f"{src.name} has scope {src.scope!r}"
    # Classification sanity: docs/standards/community are shared; code/config/jjobs tenant.
    by_type = {}
    for src in manifest.sources:
        by_type.setdefault(src.source_type, set()).add(src.scope)
    assert by_type.get(SourceType.URL_CRAWL) == {"shared"}
    assert by_type.get(SourceType.CODE_PARSE) == {"tenant"}
    assert by_type.get(SourceType.JJOB_DOCS) == {"tenant"}
