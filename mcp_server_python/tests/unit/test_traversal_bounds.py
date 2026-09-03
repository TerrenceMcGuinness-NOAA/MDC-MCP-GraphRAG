"""Unit tests for ``src.tools._traversal_bounds`` (Task 1.1).

Covers the bounded-graph-traversal helpers and tunables:

* :func:`effective_depth` clamps negative / zero / huge / in-range
  ``max_depth`` into ``[1, ceiling]`` and reports the clamped flag
  (Validates R2.1, Property 1).
* :func:`anchor_degree` returns the measured count for a small node,
  ``0`` for an empty / deg-less probe result (non-hub, backward compat),
  and ``None`` when the probe raises / times out (R1.5 fail-safe), and
  carries ``tenant=`` + ``timeout=`` + the single-hop ``count(r)`` shape
  (R1.1, R1.4, Property 5).
* :func:`degraded_notice` includes the node name, measured degree, and
  threshold (R4.2, R4.3).
* :func:`is_hub` / :func:`truncation_marker` boundary behaviour.
* Env overrides change the module constants on reload; invalid values
  fall back to the conservative defaults (R6.2).

No live AWS calls. The graph fixture is :class:`MockGraphDB`.
"""

from __future__ import annotations

import asyncio
import importlib
from typing import Any

import pytest

from src.tools import _traversal_bounds as tb
from tests.conftest import MockGraphDB

pytestmark = pytest.mark.unit


# ── effective_depth ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "requested, ceiling, expected_depth, expected_clamped",
    [
        (10, 5, 5, True),        # huge -> clamped to ceiling
        (5, 5, 5, False),        # at ceiling -> not clamped
        (3, 5, 3, False),        # in range -> unchanged
        (1, 5, 1, False),        # min in range
        (0, 5, 1, False),        # zero -> raised to 1, not a reduction
        (-7, 5, 1, False),       # negative -> raised to 1, not a reduction
        (10_000, 4, 4, True),    # very large -> ceiling
    ],
)
def test_effective_depth_clamps_into_range(
    requested: int, ceiling: int, expected_depth: int, expected_clamped: bool
) -> None:
    depth, clamped = tb.effective_depth(requested, ceiling)
    assert depth == expected_depth
    assert clamped is expected_clamped
    assert 1 <= depth <= max(1, ceiling)


def test_effective_depth_handles_unparseable_request() -> None:
    depth, clamped = tb.effective_depth("not-an-int", 5)
    assert depth == 5
    assert clamped is False


def test_effective_depth_ceiling_below_one_is_raised() -> None:
    depth, clamped = tb.effective_depth(3, 0)
    assert depth == 1
    assert clamped is True  # 3 > effective ceiling of 1


# ── anchor_degree ──────────────────────────────────────────────────────


async def test_anchor_degree_returns_count_for_small_node() -> None:
    graph = MockGraphDB()
    graph.canned_rows = []
    graph.add_response("count(r) AS deg", [{"deg": 5}])
    deg = await tb.anchor_degree(graph, "foo", "CALLS", tenant=None)
    assert deg == 5


async def test_anchor_degree_empty_result_is_zero_non_hub() -> None:
    graph = MockGraphDB()
    graph.canned_rows = []
    deg = await tb.anchor_degree(graph, "foo", "CALLS", tenant=None)
    assert deg == 0
    assert tb.is_hub(deg) is False


async def test_anchor_degree_missing_deg_key_is_zero() -> None:
    """A successful probe that returns rows without a ``deg`` key is
    treated as degree 0 (non-hub) so non-seeding existing tests are
    unaffected — only genuine errors/timeouts produce the hub fail-safe."""
    graph = MockGraphDB()
    graph.add_response("count(r) AS deg", [{"name": "noisy"}])
    deg = await tb.anchor_degree(graph, "foo", "CALLS", tenant=None)
    assert deg == 0


async def test_anchor_degree_returns_none_on_query_error() -> None:
    graph = MockGraphDB()
    graph.raise_on_query = RuntimeError("boom")
    deg = await tb.anchor_degree(graph, "foo", "CALLS", tenant=None)
    assert deg is None
    assert tb.is_hub(deg) is True  # fail-safe toward hub (R1.5)


async def test_anchor_degree_returns_none_on_timeout() -> None:
    import asyncio

    graph = MockGraphDB()
    graph.raise_on_query = asyncio.TimeoutError()
    deg = await tb.anchor_degree(graph, "foo", "CALLS", tenant=None)
    assert deg is None


async def test_anchor_degree_probe_is_single_hop_count_with_tenant_and_timeout() -> None:
    """The probe is a single-hop ``count(r)`` (never a variable-length
    pattern, R1.4) and carries tenant= + timeout= (Property 5, R5.2)."""
    sentinel_tenant = object()
    graph = MockGraphDB()
    graph.canned_rows = []
    graph.add_response("count(r) AS deg", [{"deg": 3}])
    await tb.anchor_degree(
        graph, "foo", "SOURCES|INVOKES|EXECUTES",
        tenant=sentinel_tenant, scope_pred=" AND a.`__tenant` = 'gw'",
    )
    entry = [c for c in graph.call_log if c[0] == "query"][-1]
    cypher = entry[1][0]
    kwargs = entry[3]
    assert "count(r) AS deg" in cypher
    assert "*" not in cypher  # never a variable-length pattern
    assert "SOURCES|INVOKES|EXECUTES" in cypher
    assert "AND a.`__tenant` = 'gw'" in cypher  # scope_pred carried
    assert kwargs["tenant"] is sentinel_tenant
    assert kwargs["timeout"] == tb.TIMEOUT_S


async def test_anchor_degree_handles_string_deg_value() -> None:
    graph = MockGraphDB()
    graph.canned_rows = []
    graph.add_response("count(r) AS deg", [{"deg": "42"}])
    deg = await tb.anchor_degree(graph, "foo", "CALLS", tenant=None)
    assert deg == 42


# ── anchor_degree UNION_ALL_Decomposition (Task 2.6) ───────────────────
# The probe's own Anchor_Predicate was the dominant remaining graph cost
# (R1.5). It is now two queries: an index-seekable UNION ALL resolution
# of the anchor's ids, then a count over those ids.


_RESOLVE_FRAGMENT = "RETURN id(a) AS nid"


def _seed_probe(
    graph: MockGraphDB,
    *,
    nids: list[dict[str, Any]] | None = None,
    deg: Any = 7,
) -> None:
    """Seed both stages of the two-query degree probe."""
    graph.canned_rows = []
    # ``nids=[]`` is the no-match case, distinct from "seed the default".
    rows = [{"nid": "a-1"}] if nids is None else list(nids)
    graph.add_response(_RESOLVE_FRAGMENT, rows)
    graph.add_response("count(r) AS deg", [{"deg": deg}])


def _probe_queries(graph: MockGraphDB) -> list[Any]:
    return [c for c in graph.call_log if c[0] == "query"]


async def test_anchor_degree_resolves_anchor_with_union_all_not_or() -> None:
    """The anchor is resolved by two single-property equality branches
    joined by ``UNION ALL``, never an index-defeating ``OR`` (R1.1)."""
    graph = MockGraphDB()
    _seed_probe(graph)
    await tb.anchor_degree(graph, "foo", "CALLS", tenant=None)
    cyphers = [c[1][0] for c in _probe_queries(graph)]
    assert len(cyphers) == 2, "expected resolve-then-count"
    resolve, count = cyphers
    assert resolve.count("UNION ALL") == 1
    assert "MATCH (a) WHERE a.name = $name" in resolve
    assert "MATCH (a) WHERE a.path = $name" in resolve
    assert " OR " not in resolve
    # No OR survives anywhere in the probe.
    assert "a.name = $name OR a.path = $name" not in count
    assert " OR " not in count


async def test_anchor_degree_counts_edges_by_resolved_ids() -> None:
    """The count seeks the resolved ids rather than re-matching on
    ``name``/``path`` -- the same shape ``_expand_one_hop`` uses."""
    graph = MockGraphDB()
    _seed_probe(graph, nids=[{"nid": "a-1"}, {"nid": "a-2"}], deg=9)
    deg = await tb.anchor_degree(graph, "foo", "CALLS", tenant=None)
    assert deg == 9
    count_call = _probe_queries(graph)[-1]
    cypher = count_call[1][0]
    assert "WHERE id(a) IN $ids" in cypher
    assert "count(r) AS deg" in cypher
    assert "$name" not in cypher
    assert sorted(count_call[2]["ids"]) == ["a-1", "a-2"]


async def test_anchor_degree_does_not_double_count_dual_match_anchor(
) -> None:
    """A node whose ``name`` AND ``path`` both equal ``$name`` is returned
    by both ``UNION ALL`` branches. Its id must be counted once, so the
    reported degree is the node's real degree -- not twice it.

    This is why the probe resolves ids and then counts, instead of
    ``UNION ALL``-ing two ``count(r)`` branches: ``UNION ALL`` does not
    deduplicate, so summing the branches would report ``2 * deg`` and
    could push a non-hub over the Fan_Out_Threshold (R1.3)."""
    graph = MockGraphDB()
    # Same nid from both branches -- the dual-match case.
    _seed_probe(
        graph, nids=[{"nid": "dual-1"}, {"nid": "dual-1"}], deg=60
    )
    deg = await tb.anchor_degree(graph, "exglobal_forecast.sh", "CALLS",
                                 tenant=None)
    count_call = _probe_queries(graph)[-1]
    assert count_call[2]["ids"] == ["dual-1"], "id was not deduplicated"
    # One count over one id: the real degree, not 120.
    assert deg == 60
    assert tb.is_hub(deg) is False  # 60 <= 100; doubling would flip this


async def test_anchor_degree_scope_pred_and_timeout_on_both_stages(
) -> None:
    """The Label_Scope_Predicate is carried on *both* resolution branches
    and on the count, and every query carries the tenant and the
    Statement_Timeout (R1.4)."""
    sentinel = object()
    scope = (
        " AND size([__lbl IN labels(a) WHERE __lbl STARTS WITH 'GW_V17_'])"
        " > 0"
    )
    graph = MockGraphDB()
    _seed_probe(graph)
    await tb.anchor_degree(
        graph, "foo", "CALLS", tenant=sentinel, scope_pred=scope
    )
    calls = _probe_queries(graph)
    assert len(calls) == 2
    resolve, count = calls
    assert resolve[1][0].count(scope) == 2  # one per branch
    head, _, tail = resolve[1][0].partition("UNION ALL")
    assert scope in head and scope in tail
    assert scope in count[1][0]
    for c in calls:
        assert c[3]["tenant"] is sentinel
        assert c[3]["timeout"] == tb.TIMEOUT_S


async def test_anchor_degree_unresolvable_anchor_is_zero_non_hub() -> None:
    """An anchor that resolves to nothing keeps returning ``0`` -- the
    pre-decomposition probe's value, since a grouping-key-less
    ``count(r)`` yields one ``0`` row even on no match. Preserved because
    the degree-probe fail-safe feeds the hub gate."""
    graph = MockGraphDB()
    _seed_probe(graph, nids=[], deg=0)
    deg = await tb.anchor_degree(graph, "nosuchsymbol", "CALLS", tenant=None)
    assert deg == 0
    assert tb.is_hub(deg) is False
    # The count is still issued (with an empty id list), so the shape of
    # this path is unchanged rather than short-circuited to a lookalike.
    assert len(_probe_queries(graph)) == 2
    assert _probe_queries(graph)[-1][2]["ids"] == []


@pytest.mark.parametrize(
    "exc", [RuntimeError("boom"), asyncio.TimeoutError()]
)
async def test_anchor_degree_resolution_failure_is_none_hub(
    exc: BaseException,
) -> None:
    """A failure in the *resolution* stage is unmeasurable degree, not
    degree 0: it returns ``None`` so callers treat the anchor as a hub
    (R1.5 fail-safe). Without this, the resolution's graceful empty list
    would silently become a non-hub."""
    graph = MockGraphDB()
    _seed_probe(graph)
    graph.add_raise(_RESOLVE_FRAGMENT, exc)
    deg = await tb.anchor_degree(graph, "foo", "CALLS", tenant=None)
    assert deg is None
    assert tb.is_hub(deg) is True
    # The count is never attempted without ids.
    cyphers = [c[1][0] for c in _probe_queries(graph)]
    assert not any("count(r) AS deg" in q for q in cyphers)


async def test_anchor_degree_count_failure_is_none_hub() -> None:
    """A failure in the *count* stage is equally unmeasurable (R1.5)."""
    graph = MockGraphDB()
    _seed_probe(graph)
    graph.add_raise("count(r) AS deg", RuntimeError("count boom"))
    deg = await tb.anchor_degree(graph, "foo", "CALLS", tenant=None)
    assert deg is None
    assert tb.is_hub(deg) is True


# ── is_hub ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "degree, threshold, expected",
    [
        (None, 100, True),    # probe failed -> hub
        (101, 100, True),     # over threshold
        (100, 100, False),    # exactly at threshold -> not hub
        (0, 100, False),      # leaf -> not hub
        (5, 100, False),
    ],
)
def test_is_hub_boundaries(degree, threshold, expected) -> None:
    assert tb.is_hub(degree, threshold) is expected


# ── degraded_notice ────────────────────────────────────────────────────


def test_degraded_notice_contains_name_degree_threshold() -> None:
    notice = tb.degraded_notice("JGLOBAL_FORECAST", 512, 100)
    assert "JGLOBAL_FORECAST" in notice
    assert "512" in notice
    assert "100" in notice
    assert notice.startswith("[INFO]")
    assert notice.isascii()


def test_degraded_notice_handles_unknown_degree() -> None:
    notice = tb.degraded_notice("hubby", None, 100)
    assert "hubby" in notice
    assert "100" in notice
    assert "could not be measured" in notice
    assert notice.isascii()


# ── truncation_marker ──────────────────────────────────────────────────


def test_truncation_marker_emitted_when_total_exceeds_shown() -> None:
    assert tb.truncation_marker(200, 350) == "[truncated: 200 of 350 shown]"


def test_truncation_marker_empty_when_within_limit() -> None:
    assert tb.truncation_marker(200, 200) == ""
    assert tb.truncation_marker(200, 10) == ""


# ── env overrides (R6.2) ───────────────────────────────────────────────


def test_env_overrides_change_constants_on_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_TRAVERSAL_FANOUT_THRESHOLD", "250")
    monkeypatch.setenv("MCP_TRAVERSAL_FULLCHAIN_DEPTH", "7")
    monkeypatch.setenv("MCP_TRAVERSAL_TIMEOUT_S", "12.5")
    monkeypatch.setenv("MCP_TRAVERSAL_RESULT_LIMIT", "50")
    try:
        importlib.reload(tb)
        assert tb.FAN_OUT_THRESHOLD == 250
        assert tb.FULL_CHAIN_DEPTH == 7
        assert tb.TIMEOUT_S == 12.5
        assert tb.RESULT_LIMIT == 50
    finally:
        monkeypatch.undo()
        importlib.reload(tb)
    # Restored to conservative defaults after reload with env cleared.
    assert tb.FAN_OUT_THRESHOLD == 100
    assert tb.TIMEOUT_S == 30.0


def test_invalid_env_values_fall_back_to_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_TRAVERSAL_FANOUT_THRESHOLD", "not-a-number")
    monkeypatch.setenv("MCP_TRAVERSAL_CALLCHAIN_DEPTH", "-3")  # non-positive
    monkeypatch.setenv("MCP_TRAVERSAL_TIMEOUT_S", "0")          # non-positive
    try:
        importlib.reload(tb)
        assert tb.FAN_OUT_THRESHOLD == 100
        assert tb.CALL_CHAIN_DEPTH == 4
        assert tb.TIMEOUT_S == 30.0
    finally:
        monkeypatch.undo()
        importlib.reload(tb)
    assert tb.CALL_CHAIN_DEPTH == 4


# ── BFS constants (R3.4, R6.1, R6.2, R6.3) ─────────────────────────────


def test_bfs_constant_defaults() -> None:
    """Conservative defaults: activation 30, fan-out 100 (R3.2, R6.1)."""
    assert tb.BFS_ACTIVATION_THRESHOLD == 30
    assert tb.BFS_FAN_OUT_LIMIT == 100


def test_bfs_activation_threshold_below_hub_threshold() -> None:
    """BFS kicks in well before the hub / Degraded_Result cut-off (R3.4)."""
    assert tb.BFS_ACTIVATION_THRESHOLD < tb.FAN_OUT_THRESHOLD


def test_bfs_symbols_exported() -> None:
    for sym in ("BFS_ACTIVATION_THRESHOLD", "BFS_FAN_OUT_LIMIT", "_use_bfs"):
        assert sym in tb.__all__


def test_bfs_env_overrides_change_constants_on_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_BFS_ACTIVATION_THRESHOLD", "12")
    monkeypatch.setenv("MCP_BFS_FAN_OUT_LIMIT", "250")
    try:
        importlib.reload(tb)
        assert tb.BFS_ACTIVATION_THRESHOLD == 12
        assert tb.BFS_FAN_OUT_LIMIT == 250
    finally:
        monkeypatch.undo()
        importlib.reload(tb)
    # Restored to conservative defaults after reload with env cleared.
    assert tb.BFS_ACTIVATION_THRESHOLD == 30
    assert tb.BFS_FAN_OUT_LIMIT == 100


@pytest.mark.parametrize("bad", ["not-a-number", "-5", "0", ""])
def test_invalid_bfs_env_values_fall_back_to_defaults(
    monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    monkeypatch.setenv("MCP_BFS_ACTIVATION_THRESHOLD", bad)
    monkeypatch.setenv("MCP_BFS_FAN_OUT_LIMIT", bad)
    try:
        importlib.reload(tb)
        assert tb.BFS_ACTIVATION_THRESHOLD == 30
        assert tb.BFS_FAN_OUT_LIMIT == 100
    finally:
        monkeypatch.undo()
        importlib.reload(tb)


def test_bfs_activation_threshold_override_is_honoured_by_use_bfs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_use_bfs`` reads the (overridable) module constant (R6.2, R6.3)."""
    monkeypatch.setenv("MCP_BFS_ACTIVATION_THRESHOLD", "5")
    try:
        importlib.reload(tb)
        assert tb._use_bfs(5, 1) is True   # at the lowered threshold
        assert tb._use_bfs(4, 1) is False  # below it
    finally:
        monkeypatch.undo()
        importlib.reload(tb)
    # Default threshold restored: 5 is now below it.
    assert tb._use_bfs(5, 1) is False


# ── _use_bfs strategy selector (R3.1, R3.2, Property 5) ────────────────


@pytest.mark.parametrize("degree", [0, 1, 5, 29])
@pytest.mark.parametrize("depth", [1, 2, 3])
def test_use_bfs_false_for_low_degree_and_shallow_depth(
    degree: int, depth: int
) -> None:
    """Low degree AND depth <= 3 keeps the existing single query (R3.1)."""
    assert tb._use_bfs(degree, depth) is False


@pytest.mark.parametrize("degree", [30, 31, 99, 100, 5_000])
@pytest.mark.parametrize("depth", [1, 2, 3])
def test_use_bfs_true_at_or_above_activation_threshold(
    degree: int, depth: int
) -> None:
    """Degree >= BFS_ACTIVATION_THRESHOLD selects the BFS_Walker (R3.2)."""
    assert tb._use_bfs(degree, depth) is True


@pytest.mark.parametrize("degree", [0, 1, 29, 30, 500])
@pytest.mark.parametrize("depth", [4, 5, 10])
def test_use_bfs_true_when_depth_exceeds_three(
    degree: int, depth: int
) -> None:
    """Depth > 3 selects the BFS_Walker regardless of degree (R3.2)."""
    assert tb._use_bfs(degree, depth) is True


@pytest.mark.parametrize("depth", [1, 2, 3, 4, 10])
def test_use_bfs_true_when_degree_is_none_fail_safe(depth: int) -> None:
    """Probe failure (degree None) takes the bounded walk (R3.2 fail-safe)."""
    assert tb._use_bfs(None, depth) is True


def test_use_bfs_boundary_at_threshold_and_depth() -> None:
    """Exact boundaries: 29/3 -> single query, 30/3 and 29/4 -> BFS."""
    assert tb._use_bfs(tb.BFS_ACTIVATION_THRESHOLD - 1, 3) is False
    assert tb._use_bfs(tb.BFS_ACTIVATION_THRESHOLD, 3) is True
    assert tb._use_bfs(tb.BFS_ACTIVATION_THRESHOLD - 1, 4) is True


def test_use_bfs_is_disjoint_from_single_query_condition() -> None:
    """``_use_bfs`` is False only when degree < threshold AND depth <= 3
    (Property 5 sanity check over a small grid)."""
    for degree in (None, 0, 15, 29, 30, 42, 300):
        for depth in (1, 3, 4, 8):
            expected = (
                degree is None
                or degree >= tb.BFS_ACTIVATION_THRESHOLD
                or depth > 3
            )
            assert tb._use_bfs(degree, depth) is expected
