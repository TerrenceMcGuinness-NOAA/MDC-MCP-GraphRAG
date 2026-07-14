"""Unit tests for the scope-aware collection namer (rag-data-plane-gap-closure R3).

Task 3.3: 8 cases across (shared|tenant) x (default|explicit version) x
(empty|non-empty index_prefix), plus alignment with the live serving physical
names and default-version stability (R3.2/R9).
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.data.collection_namer import (
    DEFAULT_COLLECTION_VERSION,
    resolve_collection_name,
)


@dataclass
class _T:
    index_prefix: str


GW = _T(index_prefix="")          # default tenant — empty prefix
V17 = _T(index_prefix="gw_v17_")  # non-default tenant


_EXPLICIT = "v9-0-0"
_P = "mpnet768"


@pytest.mark.parametrize(
    "scope,tenant,version,expected",
    [
        # shared: prefix is ALWAYS ignored (R3.4)
        ("shared", GW, DEFAULT_COLLECTION_VERSION, "mdc-workflow-docs-mpnet768"),
        ("shared", V17, DEFAULT_COLLECTION_VERSION, "mdc-workflow-docs-mpnet768"),
        ("shared", GW, _EXPLICIT, "mdc-workflow-docs-mpnet768-v9-0-0"),
        ("shared", V17, _EXPLICIT, "mdc-workflow-docs-mpnet768-v9-0-0"),
        # tenant: prefix applied for non-default; empty for gw
        ("tenant", GW, DEFAULT_COLLECTION_VERSION, "mdc-workflow-docs-mpnet768"),
        ("tenant", V17, DEFAULT_COLLECTION_VERSION, "gw_v17_mdc-workflow-docs-mpnet768"),
        ("tenant", GW, _EXPLICIT, "mdc-workflow-docs-mpnet768-v9-0-0"),
        ("tenant", V17, _EXPLICIT, "gw_v17_mdc-workflow-docs-mpnet768-v9-0-0"),
    ],
)
def test_eight_cases(scope, tenant, version, expected):
    assert (
        resolve_collection_name(
            domain="workflow-docs", scope=scope, tenant=tenant,
            version=version, profile=_P,
        )
        == expected
    )


def test_default_version_has_no_suffix():
    """Default serving version drops the suffix so serving names are stable."""
    name = resolve_collection_name(
        domain="code-context", scope="tenant", tenant=V17,
        version=DEFAULT_COLLECTION_VERSION, profile=_P,
    )
    assert name == "gw_v17_mdc-code-context-mpnet768"
    assert not name.endswith(DEFAULT_COLLECTION_VERSION)


def test_matches_live_serving_names():
    """Shared docs / tenant code at default version reproduce the serving
    physical names (mpnet768) byte-for-byte (R9)."""
    assert resolve_collection_name(
        domain="workflow-docs", scope="shared", tenant=GW, profile=_P
    ) == "mdc-workflow-docs-mpnet768"
    assert resolve_collection_name(
        domain="code-context", scope="tenant", tenant=GW, profile=_P
    ) == "mdc-code-context-mpnet768"
    assert resolve_collection_name(
        domain="jjobs", scope="tenant", tenant=GW, profile=_P
    ) == "mdc-jjobs-mpnet768"


def test_none_tenant_yields_unprefixed():
    assert resolve_collection_name(
        domain="jjobs", scope="tenant", tenant=None, profile=_P
    ) == "mdc-jjobs-mpnet768"


def test_invalid_scope_raises():
    with pytest.raises(ValueError, match="invalid scope"):
        resolve_collection_name(domain="jjobs", scope="global", profile=_P)


def test_profile_derived_from_env(monkeypatch):
    monkeypatch.setenv("MCP_EMBEDDING_PROFILE", "titan1024")
    assert resolve_collection_name(
        domain="workflow-docs", scope="shared"
    ) == "mdc-workflow-docs-titan1024"
