"""Unit tests for the Collection_Condition probe (shared-scope-query-
routing Task 7.2).

Covers ``ChromaDBAdapter.collection_condition`` and
``OpenSearchAdapter.collection_condition`` -- the three-way classifier
(``unprovisioned`` / ``provisioned-empty`` / ``provisioned-populated``)
added to :class:`~src.data.protocols.VectorDBProtocol` by Task 7.1.
Nothing calls this method from the query path yet: that wiring is Task
7.3's atomic-unit step. This file tests the classifier standalone.

Swept over both backends via the ``adapters()`` fixture defined in
``tests/properties/conftest.py`` (Task 2.4), imported directly rather
than duplicated -- pytest fixture discovery is directory-scoped to the
conftest's own subtree, so importing the fixture function into this
module's namespace is how a ``tests/unit/`` test reaches a fixture whose
canonical home is ``tests/properties/``.

Hermetic: no network, no live backend. Each adapter is exercised over
the ``FakeChromaClient`` / ``FakeOpenSearchRawClient`` doubles the
fixture wires up, and every double records every call it receives so
the "no mutating call on any path" assertions can inspect ``.calls``.
"""

from __future__ import annotations

import logging

import pytest

from src.data.read_router import CollectionCondition
from tests.properties.conftest import adapters  # noqa: F401 - fixture import

pytestmark = pytest.mark.unit

_MUTATING_METHODS = frozenset(
    {
        "get_or_create_collection",
        "upsert",
        "add",
        "delete",
        "delete_collection",
        "create",
        "create_index",
        "index",
        "bulk",
        "update",
    }
)


def _seed(adapter, raw_client, name: str, *, count: int) -> None:
    """Seed one physical collection with ``count`` documents.

    Works across both fixture parameterisations: ``FakeChromaClient``
    exposes ``add_collection(name, response=...)`` and
    ``FakeOpenSearchRawClient`` exposes ``add_index(name, count=...)``.
    """
    if hasattr(raw_client, "add_collection"):
        ids = [f"id-{i}" for i in range(count)]
        raw_client.add_collection(
            name,
            response={
                "ids": [ids],
                "documents": [["x"] * count],
                "metadatas": [[{}] * count],
                "distances": [[0.0] * count],
            },
        )
        # _FakeChromaCollection.count() reports len(ids), matching `count`.
    else:
        raw_client.add_index(name, hits=[], count=count)


class TestThreeWayClassification:
    """Each of the three Collection_Condition outcomes."""

    async def test_absent_collection_is_unprovisioned(self, adapters):
        adapter, _raw = adapters
        result = await adapter.collection_condition("nonexistent-collection")
        assert result == CollectionCondition.UNPROVISIONED

    async def test_present_empty_collection_is_provisioned_empty(
        self, adapters
    ):
        adapter, raw = adapters
        _seed(adapter, raw, "empty-one", count=0)
        result = await adapter.collection_condition("empty-one")
        assert result == CollectionCondition.PROVISIONED_EMPTY

    async def test_present_populated_collection_is_provisioned_populated(
        self, adapters
    ):
        adapter, raw = adapters
        _seed(adapter, raw, "populated-one", count=3)
        result = await adapter.collection_condition("populated-one")
        assert result == CollectionCondition.PROVISIONED_POPULATED


class TestZeroHitDoesNotImplyEmpty:
    """A populated collection that returns zero hits for a query is still
    ``PROVISIONED_POPULATED`` -- ``collection_condition`` answers "does
    this collection hold anything", not "did the query match", and is
    independent of any particular query's hit count (R7.8).
    """

    async def test_populated_collection_classifies_populated_despite_query(
        self, adapters
    ):
        adapter, raw = adapters
        _seed(adapter, raw, "populated-but-no-match", count=5)
        # collection_condition takes a physical name, not a query result;
        # there is no "zero hits" input to this method at all, which is
        # exactly the point -- it cannot be confused by an empty query
        # result because it never sees one.
        result = await adapter.collection_condition(
            "populated-but-no-match"
        )
        assert result == CollectionCondition.PROVISIONED_POPULATED


class TestCachingBehaviour:
    """UNPROVISIONED is never cached; the two positive conditions are."""

    async def test_unprovisioned_is_not_cached(self, adapters, monkeypatch):
        adapter, raw = adapters
        first = await adapter.collection_condition("still-missing")
        assert first == CollectionCondition.UNPROVISIONED

        # Now provision it and probe again -- if UNPROVISIONED had been
        # cached, this would still (incorrectly) report UNPROVISIONED.
        _seed(adapter, raw, "still-missing", count=1)
        second = await adapter.collection_condition("still-missing")
        assert second == CollectionCondition.PROVISIONED_POPULATED

    async def test_positive_conditions_are_cached(self, adapters):
        adapter, raw = adapters
        _seed(adapter, raw, "cached-one", count=2)
        first = await adapter.collection_condition("cached-one")
        assert first == CollectionCondition.PROVISIONED_POPULATED

        calls_before = len(raw.calls)
        second = await adapter.collection_condition("cached-one")
        assert second == CollectionCondition.PROVISIONED_POPULATED
        # No new call was issued for the cached hit.
        assert len(raw.calls) == calls_before

    async def test_ttl_boundary_expires_the_cache(
        self, adapters, monkeypatch
    ):
        adapter, raw = adapters
        monkeypatch.setenv("MCP_COLLECTION_CONDITION_TTL_S", "0")
        _seed(adapter, raw, "short-ttl", count=1)

        first = await adapter.collection_condition("short-ttl")
        assert first == CollectionCondition.PROVISIONED_POPULATED

        calls_before = len(raw.calls)
        second = await adapter.collection_condition("short-ttl")
        assert second == CollectionCondition.PROVISIONED_POPULATED
        # TTL of 0 means the cached entry is always considered stale, so
        # a fresh probe call is issued.
        assert len(raw.calls) > calls_before

    async def test_ttl_within_window_reuses_the_cache(
        self, adapters, monkeypatch
    ):
        adapter, raw = adapters
        monkeypatch.setenv("MCP_COLLECTION_CONDITION_TTL_S", "300")
        _seed(adapter, raw, "long-ttl", count=1)

        await adapter.collection_condition("long-ttl")
        calls_before = len(raw.calls)
        await adapter.collection_condition("long-ttl")
        assert len(raw.calls) == calls_before


class TestKillSwitch:
    """``MCP_COLLECTION_CONDITION_PROBE=0`` disables the probe."""

    async def test_kill_switch_reports_populated_without_probing(
        self, adapters, monkeypatch, caplog
    ):
        adapter, raw = adapters
        monkeypatch.setenv("MCP_COLLECTION_CONDITION_PROBE", "0")

        calls_before = len(raw.calls)
        logger_name = (
            "src.data.chromadb_adapter"
            if hasattr(raw, "add_collection")
            else "src.data.opensearch_adapter"
        )
        with caplog.at_level(logging.INFO, logger=logger_name):
            result = await adapter.collection_condition(
                "never-provisioned-and-never-probed"
            )
        assert result == CollectionCondition.PROVISIONED_POPULATED
        # No probe call was issued at all -- kill switch short-circuits
        # before any read.
        assert len(raw.calls) == calls_before
        assert any(
            "probe disabled" in rec.getMessage() for rec in caplog.records
        )

    async def test_kill_switch_default_is_enabled(self, adapters):
        adapter, _raw = adapters
        # Without setting the env var, the probe runs normally and an
        # absent collection classifies UNPROVISIONED, not the kill-switch
        # fallback PROVISIONED_POPULATED.
        result = await adapter.collection_condition("definitely-absent")
        assert result == CollectionCondition.UNPROVISIONED


class TestNeverRaisesNeverWrites:
    """R12.5: no create, delete, or write on any path, including absence."""

    async def test_absent_collection_path_issues_no_mutating_call(
        self, adapters
    ):
        adapter, raw = adapters
        await adapter.collection_condition("absent-for-mutation-check")
        mutating = [
            call for call in raw.calls if call.method in _MUTATING_METHODS
        ]
        assert mutating == []

    async def test_populated_collection_path_issues_no_mutating_call(
        self, adapters
    ):
        adapter, raw = adapters
        _seed(adapter, raw, "populated-for-mutation-check", count=2)
        await adapter.collection_condition("populated-for-mutation-check")
        mutating = [
            call for call in raw.calls if call.method in _MUTATING_METHODS
        ]
        assert mutating == []

    async def test_empty_collection_path_issues_no_mutating_call(
        self, adapters
    ):
        adapter, raw = adapters
        _seed(adapter, raw, "empty-for-mutation-check", count=0)
        await adapter.collection_condition("empty-for-mutation-check")
        mutating = [
            call for call in raw.calls if call.method in _MUTATING_METHODS
        ]
        assert mutating == []

    async def test_collection_condition_never_raises(self, adapters):
        adapter, _raw = adapters
        # A name that cannot be resolved to anything sensible still
        # returns a classification rather than raising.
        result = await adapter.collection_condition("")
        assert result in (
            CollectionCondition.UNPROVISIONED,
            CollectionCondition.PROVISIONED_EMPTY,
            CollectionCondition.PROVISIONED_POPULATED,
        )


class TestGwZeroHitByteEquivalence:
    """R6.8: the probe fires for gw too, but response bytes are unchanged
    because a log line is not rendered output. This test operates at the
    adapter level -- it asserts the probe itself does not touch anything
    that could reach a rendered response (it returns a plain enum value,
    never a string destined for a tool body), leaving the tool-layer
    byte-equivalence claim to the Task 6 baseline-comparison suite.
    """

    async def test_probe_return_value_is_not_response_text(self, adapters):
        adapter, raw = adapters
        _seed(adapter, raw, "gw-zero-hit-collection", count=1)
        result = await adapter.collection_condition("gw-zero-hit-collection")
        # The return value is the enum itself, not a rendered string --
        # nothing here can leak into a tool response body by accident.
        assert isinstance(result, CollectionCondition)

    async def test_probe_runs_identically_regardless_of_tenant_prefix(
        self, adapters
    ):
        """The classifier takes a bare physical name; it has no tenant
        parameter to special-case gw against, so the same code path
        executes for a gw-owned (unprefixed) and a tenant-owned
        (prefixed) physical collection name alike.
        """
        adapter, raw = adapters
        _seed(adapter, raw, "mdc-ee2-standards-titan1024", count=1)
        _seed(adapter, raw, "gw_v17_mdc-ee2-standards-titan1024", count=1)

        gw_result = await adapter.collection_condition(
            "mdc-ee2-standards-titan1024"
        )
        tenant_result = await adapter.collection_condition(
            "gw_v17_mdc-ee2-standards-titan1024"
        )
        assert gw_result == CollectionCondition.PROVISIONED_POPULATED
        assert tenant_result == CollectionCondition.PROVISIONED_POPULATED
