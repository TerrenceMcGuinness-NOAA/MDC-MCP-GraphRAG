"""Unit tests for ``aws_config.resolve_index`` profile routing
(Phase C-2c, Requirements 8, 11.5).

Covers titan1024 routing for all five known collections, mpnet768
routing for all five, unknown-collection passthrough for both, and a
Nova profile (``nova1024``) returning the collection name unchanged
because no index map is registered for it.
"""

from __future__ import annotations

import pytest

from src.config.aws_config import (
    PRODUCTION_INDICES_BY_PROFILE,
    get_production_indices,
    resolve_index,
)


KNOWN_COLLECTIONS = (
    "code-with-context-v8-0-0",
    "global-workflow-docs-v8-0-0",
    "jjobs-v8-0-0",
    "community-summaries",
    "ee2-standards-v5-0-0-enhanced",
)


# ── titan1024 routing (Requirement 8.1) ───────────────────────────────


@pytest.mark.parametrize(
    "collection, expected",
    [
        ("code-with-context-v8-0-0",      "mdc-code-context-titan1024"),
        ("global-workflow-docs-v8-0-0",   "mdc-workflow-docs-titan1024"),
        ("jjobs-v8-0-0",                  "mdc-jjobs-titan1024"),
        ("community-summaries",           "mdc-community-summaries-titan1024"),
        ("ee2-standards-v5-0-0-enhanced", "mdc-ee2-standards-titan1024"),
    ],
)
def test_titan1024_routes_each_known_collection(
    collection: str, expected: str
) -> None:
    assert resolve_index(collection, "titan1024") == expected


# ── mpnet768 routing (Requirement 8.2) ────────────────────────────────


@pytest.mark.parametrize(
    "collection, expected",
    [
        ("code-with-context-v8-0-0",      "mdc-code-context-mpnet768"),
        ("global-workflow-docs-v8-0-0",   "mdc-workflow-docs-mpnet768"),
        ("jjobs-v8-0-0",                  "mdc-jjobs-mpnet768"),
        ("community-summaries",           "mdc-community-summaries-mpnet768"),
        ("ee2-standards-v5-0-0-enhanced", "mdc-ee2-standards-mpnet768"),
    ],
)
def test_mpnet768_routes_each_known_collection(
    collection: str, expected: str
) -> None:
    assert resolve_index(collection, "mpnet768") == expected


# ── unknown-collection passthrough (Requirement 8.4) ──────────────────


@pytest.mark.parametrize("profile", ["titan1024", "mpnet768"])
def test_unknown_collection_passes_through(profile: str) -> None:
    """An unmapped collection name returns unchanged for both
    registered profiles (Req 8.4)."""
    assert resolve_index("custom-collection", profile) == "custom-collection"


# ── Nova profiles return collection unchanged (Requirement 8.3) ───────


@pytest.mark.parametrize("nova_profile", ["nova256", "nova512", "nova1024", "nova3072"])
def test_nova_profiles_have_no_registered_map(nova_profile: str) -> None:
    """Nova has no production index map yet, so every collection name
    passes through unchanged (Req 8.3)."""
    assert get_production_indices(nova_profile) == {}


@pytest.mark.parametrize("nova_profile", ["nova256", "nova512", "nova1024", "nova3072"])
@pytest.mark.parametrize("collection", KNOWN_COLLECTIONS)
def test_nova_resolve_index_returns_collection_unchanged(
    nova_profile: str, collection: str
) -> None:
    assert resolve_index(collection, nova_profile) == collection


# ── default profile (Requirement 8.5) ─────────────────────────────────


def test_resolve_index_defaults_to_titan1024_when_profile_omitted() -> None:
    """The single-arg form picks up titan1024 — backwards compatible
    with callers that pre-date the profile argument (Req 8.5)."""
    assert resolve_index("jjobs-v8-0-0") == "mdc-jjobs-titan1024"


# ── get_production_indices ────────────────────────────────────────────


def test_get_production_indices_titan1024_has_five_entries() -> None:
    indices = get_production_indices("titan1024")
    assert set(indices.keys()) == set(KNOWN_COLLECTIONS)


def test_get_production_indices_mpnet768_has_five_entries() -> None:
    indices = get_production_indices("mpnet768")
    assert set(indices.keys()) == set(KNOWN_COLLECTIONS)


def test_get_production_indices_unknown_profile_returns_empty() -> None:
    assert get_production_indices("not-a-profile") == {}


def test_production_indices_by_profile_contains_titan_and_mpnet() -> None:
    assert "titan1024" in PRODUCTION_INDICES_BY_PROFILE
    assert "mpnet768" in PRODUCTION_INDICES_BY_PROFILE
