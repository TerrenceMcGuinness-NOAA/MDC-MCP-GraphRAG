"""Unit tests for the mock adapters in ``tests/conftest.py`` (Requirement 13.1).

The mocks are test infrastructure, so they get their own test file to
guarantee they (a) match :class:`~src.data.protocols.VectorDBProtocol`
and :class:`~src.data.protocols.GraphDBProtocol` structurally and
(b) behave predictably when seeded.
"""

from __future__ import annotations

import pytest

from src.data.protocols import (
    VECTOR_RESULT_KEYS,
    GraphDBProtocol,
    VectorDBProtocol,
)
from tests.conftest import (
    SAMPLE_GRAPH_ROWS,
    SAMPLE_VECTOR_HITS,
    FakeClock,
    MockGraphDB,
    MockUnifiedDataAccess,
    MockVectorDB,
    build_mock_tool_caller,
    make_deterministic_id_factory,
)

pytestmark = pytest.mark.unit


# ── protocol compliance ────────────────────────────────────────────────


def test_mock_vector_db_matches_protocol() -> None:
    # ``runtime_checkable`` Protocol → isinstance works.
    assert isinstance(MockVectorDB(), VectorDBProtocol)


def test_mock_graph_db_matches_protocol() -> None:
    assert isinstance(MockGraphDB(), GraphDBProtocol)


# ── MockVectorDB behaviour ────────────────────────────────────────────


async def test_mock_vector_db_query_filters_by_threshold() -> None:
    db = MockVectorDB()
    hits = await db.query(
        "mdc-code-context-mpnet768", "forecast", k=10, similarity_threshold=0.8
    )
    assert all(h["score"] >= 0.8 for h in hits)
    # The canonical sample set has two hits ≥ 0.8.
    assert len(hits) == 2


async def test_mock_vector_db_query_respects_k_cap() -> None:
    db = MockVectorDB()
    hits = await db.query("c", "q", k=1)
    assert len(hits) == 1


async def test_mock_vector_db_raise_on_query_propagates() -> None:
    db = MockVectorDB(raise_on_query=RuntimeError("boom"))
    with pytest.raises(RuntimeError, match="boom"):
        await db.query("c", "q")


async def test_mock_vector_db_hits_match_vector_result_keys() -> None:
    # Every canonical sample has exactly the required keys.
    for hit in SAMPLE_VECTOR_HITS:
        assert VECTOR_RESULT_KEYS.issubset(hit.keys())


async def test_mock_vector_db_multi_collection_merges_and_sorts() -> None:
    db = MockVectorDB()
    merged = await db.multi_collection_query(
        ["a", "b"], "forecast", k=3, similarity_threshold=0.0
    )
    # Sorted by score desc.
    scores = [h["score"] for h in merged]
    assert scores == sorted(scores, reverse=True)


async def test_mock_vector_db_list_collections_returns_five() -> None:
    db = MockVectorDB()
    assert len(await db.list_collections()) == 5


async def test_mock_vector_db_health_check_shape() -> None:
    db = MockVectorDB()
    health = await db.health_check(deep=True)
    assert health["status"] == "healthy"
    assert "indices" in health or "collections" in health


async def test_mock_vector_db_call_log_tracks_operations() -> None:
    db = MockVectorDB()
    await db.connect()
    await db.query("c", "q", k=5)
    await db.close()
    methods = [entry[0] for entry in db.call_log]
    assert methods == ["connect", "query", "close"]


# ── MockGraphDB behaviour ─────────────────────────────────────────────


async def test_mock_graph_db_default_rows_returned() -> None:
    db = MockGraphDB()
    rows = await db.query("MATCH (n) RETURN n")
    assert rows == SAMPLE_GRAPH_ROWS


async def test_mock_graph_db_add_response_matches_fragment() -> None:
    db = MockGraphDB()
    db.add_response("RETURN count(n)", [{"count": 42}])
    rows = await db.query("MATCH (n) RETURN count(n) AS count")
    assert rows == [{"count": 42}]


async def test_mock_graph_db_longest_fragment_wins() -> None:
    db = MockGraphDB()
    db.add_response("COUNT", [{"x": 1}])
    db.add_response("MATCH (n) RETURN COUNT(n)", [{"x": 2}])
    rows = await db.query("MATCH (n) RETURN COUNT(n) AS c")
    assert rows == [{"x": 2}]


async def test_mock_graph_db_raise_on_query_propagates() -> None:
    db = MockGraphDB(raise_on_query=ValueError("nope"))
    with pytest.raises(ValueError, match="nope"):
        await db.query("MATCH (n)")


async def test_mock_graph_db_get_statistics_returns_defaults() -> None:
    db = MockGraphDB()
    stats = await db.get_statistics()
    assert stats["nodes"] > 0
    assert stats["relationships"] > 0


async def test_mock_graph_db_health_check_defaults() -> None:
    db = MockGraphDB()
    health = await db.health_check()
    assert health["status"] == "healthy"
    assert health["nodes"] == 59_759


# ── MockUnifiedDataAccess.health_check composition ────────────────────


async def test_unified_health_check_healthy_when_both_ok() -> None:
    da = MockUnifiedDataAccess()
    await da.connect()
    health = await da.health_check()
    assert health["status"] == "healthy"
    assert health["vector"]["ok"] is True
    assert health["graph"]["ok"] is True
    assert health["vector"]["indexCount"] == 5
    assert health["graph"]["nodeCount"] == 59_759


async def test_unified_health_check_degraded_when_few_indices() -> None:
    da = MockUnifiedDataAccess()
    da.vector_db.collections = ["only-one"]  # below min_indices=5
    await da.connect()
    health = await da.health_check()
    assert health["status"] == "degraded"
    assert health["vector"]["ok"] is False
    assert "only 1 indices" in health["vector"]["reason"]


async def test_unified_health_check_degraded_when_graph_empty() -> None:
    da = MockUnifiedDataAccess()
    da.graph_db.statistics = {"nodes": 0, "relationships": 0}
    await da.connect()
    health = await da.health_check()
    assert health["status"] == "degraded"
    assert health["graph"]["ok"] is False


async def test_unified_health_check_deep_flag_forwarded() -> None:
    da = MockUnifiedDataAccess()
    await da.health_check(deep=True)
    # Last vector health_check call should record deep=True.
    hc_calls = [c for c in da.vector_db.call_log if c[0] == "health_check"]
    assert hc_calls and hc_calls[-1][2]["deep"] is True


# ── FakeClock + deterministic IDs ─────────────────────────────────────


def test_fake_clock_advances_monotonically() -> None:
    clock = FakeClock()
    t1 = clock()
    t2 = clock()
    assert t1 < t2
    assert t1.endswith("Z")
    assert t2.endswith("Z")


def test_deterministic_id_factory_produces_sequential_ids() -> None:
    factory = make_deterministic_id_factory("chk")
    assert factory() == "chk000001"
    assert factory() == "chk000002"


def test_deterministic_id_factory_respects_width() -> None:
    factory = make_deterministic_id_factory("x", width=3)
    assert factory() == "x001"


# ── build_mock_tool_caller ────────────────────────────────────────────


async def test_mock_tool_caller_returns_mapped_value() -> None:
    caller = build_mock_tool_caller({"t": "ok"})
    assert await caller("t", {}) == "ok"


async def test_mock_tool_caller_callable_value_receives_arguments() -> None:
    caller = build_mock_tool_caller({"t": lambda args: args["q"].upper()})
    assert await caller("t", {"q": "hi"}) == "HI"


async def test_mock_tool_caller_unknown_tool_raises() -> None:
    caller = build_mock_tool_caller({"known": 1})
    with pytest.raises(KeyError, match="unknown"):
        await caller("unknown", {})


async def test_mock_tool_caller_latency_simulated() -> None:
    import time as _time

    caller = build_mock_tool_caller({"t": "ok"}, latency_ms=10)
    start = _time.perf_counter()
    await caller("t", {})
    assert (_time.perf_counter() - start) >= 0.005  # lenient lower bound
