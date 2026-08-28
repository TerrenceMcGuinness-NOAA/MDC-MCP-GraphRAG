"""Property 8 -- reporting agreement.

# Feature: shared-scope-query-routing, Property 8: Reporting agreement

shared-scope-query-routing Task 10.5 (Requirements 1.4, 9.1, 9.7, 10.1,
11.1, 13.7). For any Tenant ``T`` and any profile ``p``, the set the
Status_Reporter lists, the set the Integrity_Checker samples, and the set
the Health_Reporter enumerates are each equal to
``tenant_collection_set(T, profile=p)``.

The generator INJECTS arbitrary non-member names into the stubbed
enumeration -- a foreign tenant's prefixed collection and a bookkeeping
index (``mdc-content-sha-registry``) -- and asserts none appears in any of
the three outputs. Without that injection the property degenerates into
three functions agreeing because they were all handed a clean list, which
proves nothing about the filtering that is the actual subject. What
structurally excludes the injected names is that all three reporting paths
take their collection set from the Read_Router (names come from
``tenant_collection_set``), never from the backend enumeration.

Scope note
----------
The property is asserted over PREFIXED tenants. For the Default_Tenant the
three reporters deliberately retain their pre-change, byte-equivalent
behaviour (name-shape health enumeration incl. the bookkeeping over-count
for status; ``sample_metadata(collection=None)`` for integrity; legacy
``indexCount`` for health), which Requirement 6.3 grants precedence over
Requirements 9/10/11. Reporting agreement with injected-non-member
exclusion is therefore a property of non-empty-prefix tenants; the default
tenant is covered by the byte-equivalence regression suite instead.

Run against BOTH adapters. As in Task 7.4's P10, Hypothesis does not
compose cleanly with the function-scoped ``adapters()`` fixture, so this
module reuses that fixture's client doubles and builds a fresh adapter per
example, parameterised over the same two backend ids.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.data.chromadb_adapter import ChromaDBAdapter
from src.data.opensearch_adapter import OpenSearchAdapter
from src.data.read_router import tenant_collection_set
from src.data.unified_data_access import UnifiedDataAccess
from src.tools import semantic_search as ss
from tests.properties.conftest import (
    FakeChromaClient,
    FakeOpenSearchRawClient,
    _NamespaceWithRawClient,
    prefixed_tenants,
)

pytestmark = pytest.mark.property

_PREFIXED = list(prefixed_tenants())
_PROFILES = ("titan1024", "mpnet768")

#: A bookkeeping index that must never enter a tenant's listing (R9.7).
_BOOKKEEPING = "mdc-content-sha-registry"


def _embedding_function(texts: list[str]) -> list[list[float]]:
    return [[0.0, 0.0] for _ in texts]


def _build_adapter(backend: str):
    if backend == "chromadb":
        adapter = ChromaDBAdapter(embedding_function=_embedding_function)
        client = FakeChromaClient()
        adapter._client = client
        adapter._connected = True
        return adapter, client
    adapter = OpenSearchAdapter(
        endpoint="https://example.invalid",
        embedding_function=_embedding_function,
    )
    raw = FakeOpenSearchRawClient()
    adapter._client = _NamespaceWithRawClient(raw)
    adapter._connected = True
    return adapter, raw


def _seed_present(backend: str, client, name: str, count: int) -> None:
    """Make ``name`` appear in the adapter's deep health enumeration."""
    if backend == "chromadb":
        ids = [[f"{name}-{i}" for i in range(count)]]
        client.add_collection(
            name,
            response={
                "ids": ids,
                "documents": [["x"] * count],
                "metadatas": [[{}] * count],
                "distances": [[0.0] * count],
            },
        )
    else:
        client.add_index(name, hits=[], count=count)


def _listed_status_names(lines: list[str]) -> set[str]:
    """Collection names rendered in the scoped status block.

    Detail rows have the shape ``  - <name> (<scope>): <count|unprovisioned>``.
    Header rows (``- **Collections:** ...`` etc.) carry no ``(scope):`` and
    are ignored.
    """
    names: set[str] = set()
    for ln in lines:
        s = ln.strip()
        if s.startswith("- ") and " (" in s and "):" in s:
            names.add(s[2:].split(" (", 1)[0].strip())
    return names


def _foreign_prefix(active_prefix: str) -> str:
    for t in _PREFIXED:
        if t.index_prefix != active_prefix:
            return t.index_prefix
    return "zzz_"  # pragma: no cover - catalog always has >=2 prefixed


@pytest.mark.parametrize("backend", ["chromadb", "opensearch"])
@settings(max_examples=100, deadline=None)
@given(
    tenant_idx=st.integers(min_value=0, max_value=len(_PREFIXED) - 1),
    profile=st.sampled_from(_PROFILES),
)
def test_p8_reporting_agreement(
    backend: str, tenant_idx: int, profile: str
) -> None:
    tenant = _PREFIXED[tenant_idx]
    expected = set(tenant_collection_set(tenant, profile=profile).physical_names)

    # Non-member names the backend also enumerates: a foreign tenant's
    # prefixed collection and a bookkeeping index. Neither is a member of
    # this tenant's Read_Router union.
    injected = {
        f"{_foreign_prefix(tenant.index_prefix)}mdc-code-context-{profile}",
        _BOOKKEEPING,
    }
    injected -= expected  # defensive: never collide with a real member
    assert injected, "the injection set must be non-empty to prove filtering"

    adapter, client = _build_adapter(backend)
    for name in expected:
        _seed_present(backend, client, name, count=3)
    for name in injected:
        _seed_present(backend, client, name, count=9)

    prior_profile = os.environ.get("MCP_EMBEDDING_PROFILE")
    os.environ["MCP_EMBEDDING_PROFILE"] = profile
    prior_tenant_fn = ss._tenant
    ss._tenant = lambda: tenant
    try:
        # (1) Status_Reporter -- names come from the router, not the backend.
        status_lines = asyncio.run(
            ss._render_vector_status_block(adapter)
        )
        status_set = _listed_status_names(status_lines)

        # (2) Integrity_Checker -- the set it samples is the union it
        # iterates; counts_out is keyed by exactly the members it touches.
        counts: dict = {}
        asyncio.run(
            ss._allocate_scoped_sample(
                adapter, list(expected), 25, counts
            )
        )
        integrity_set = set(counts.keys())

        # (3) Health_Reporter -- enumerates the router set, not the backend.
        raw = asyncio.run(adapter.health_check(deep=True))
        health_block = UnifiedDataAccess(
            vector_db=adapter, graph_db=None
        )._scoped_vector_health(raw, tenant)
        health_set = {c["name"] for c in health_block["collections"]}
    finally:
        ss._tenant = prior_tenant_fn
        if prior_profile is None:
            os.environ.pop("MCP_EMBEDDING_PROFILE", None)
        else:
            os.environ["MCP_EMBEDDING_PROFILE"] = prior_profile

    # All three sets equal tenant_collection_set(T, profile=p).
    assert status_set == expected
    assert integrity_set == expected
    assert health_set == expected

    # No injected non-member appears in any of the three outputs.
    status_text = "\n".join(status_lines)
    for name in injected:
        assert name not in status_set
        assert name not in status_text
        assert name not in integrity_set
        assert name not in health_set
