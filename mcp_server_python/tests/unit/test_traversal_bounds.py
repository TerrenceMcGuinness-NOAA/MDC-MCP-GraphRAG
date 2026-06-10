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
