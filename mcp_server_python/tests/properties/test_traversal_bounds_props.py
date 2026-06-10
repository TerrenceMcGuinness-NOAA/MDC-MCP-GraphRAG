"""Property-based tests for ``bounded-graph-traversal`` (Task 5, P1-P5).

Feature: bounded-graph-traversal

One Hypothesis test per correctness property from the design:

* P1 Bounded depth always (R2.1, R2.2, R2.4)
* P2 Hub short-circuit (R1.2, R1.5, R4.1, R4.4)
* P3 Non-hub equivalence (R3.4, R7.3)
* P4 Timeout never raises (R5.3, R8.1)
* P5 Tenant scoping preserved (R7.4, R7.5)

The tool-layer properties are async; each ``@given`` example drives a
fresh event loop via :pyfunc:`asyncio.run` (the test functions stay
synchronous so Hypothesis can shrink them). No live AWS — the graph
fixture is :class:`MockGraphDB`.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import pytest
from fastmcp import FastMCP
from hypothesis import given, settings
from hypothesis import strategies as st

from src.data.neptune_adapter import NeptuneAdapterError
from src.tools import code_analysis
from src.tools._traversal_bounds import (
    CALL_CHAIN_DEPTH,
    DATA_FLOW_DEPTH,
    FAN_OUT_THRESHOLD,
    FULL_CHAIN_DEPTH,
    anchor_degree,
    effective_depth,
    is_hub,
)
from tests.conftest import MockGraphDB, MockUnifiedDataAccess

pytestmark = pytest.mark.property

_SETTINGS = settings(max_examples=100, deadline=None)

_ONE_HOP_FRAGMENT = (
    "RETURN DISTINCT x.name AS name, coalesce(x.filepath, x.path) AS file"
)
_TIMEOUT_EXC = NeptuneAdapterError("query exceeded 30.0s statement timeout")


# ── harness ──────────────────────────────────────────────────────────────


def _make_server(data: Any) -> FastMCP:
    mcp = FastMCP("mdc-traversal-props", version="1.0.0")
    code_analysis.register(mcp, data=data)
    return mcp


async def _call_tool(mcp: FastMCP, name: str, arguments: dict[str, Any]) -> str:
    tool = await mcp.get_tool(name)
    result = await tool.run(arguments)
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text is not None:
            return text
    return str(result)


def _trace_data(graph_overrides=None) -> MockUnifiedDataAccess:
    data = MockUnifiedDataAccess()
    data.graph_db.canned_rows = []
    data.graph_db.add_response("RETURN labels(n) AS labels LIMIT 1", [{"labels": ["Function"]}])
    if graph_overrides:
        graph_overrides(data.graph_db)
    return data


def _cyphers(data: MockUnifiedDataAccess) -> list[str]:
    return [c[1][0] for c in data.graph_db.call_log if c[0] == "query"]


# ── P1: Bounded depth always ─────────────────────────────────────────────


@_SETTINGS
@given(
    requested=st.integers(min_value=-10_000, max_value=10**9),
    ceiling=st.sampled_from([CALL_CHAIN_DEPTH, FULL_CHAIN_DEPTH, DATA_FLOW_DEPTH]),
)
def test_p1_bounded_depth_always(requested: int, ceiling: int) -> None:
    depth, clamped = effective_depth(requested, ceiling)
    # Always a finite, explicit bound in [1, ceiling].
    assert 1 <= depth <= ceiling
    # The emitted pattern is always an explicit *1..N (never * or *1..).
    pattern = f"*1..{depth}"
    assert re.fullmatch(r"\*1\.\.\d+", pattern)
    # clamped flag is True exactly when the caller asked for more than the
    # ceiling.
    assert clamped == (requested > ceiling)


@_SETTINGS
@given(requested=st.integers(min_value=-10_000, max_value=10**9))
def test_p1_zero_or_negative_never_unbounded(requested: int) -> None:
    depth, _ = effective_depth(requested, CALL_CHAIN_DEPTH)
    assert depth >= 1


# ── P2: Hub short-circuit ────────────────────────────────────────────────


@_SETTINGS
@given(
    degree=st.one_of(
        st.integers(min_value=FAN_OUT_THRESHOLD + 1, max_value=10**7),
        st.none(),  # probe failure -> fail-safe hub
    )
)
def test_p2_hub_short_circuit(degree: int | None) -> None:
    # The pure predicate.
    assert is_hub(degree, FAN_OUT_THRESHOLD) is True

    def seed(g: MockGraphDB) -> None:
        if degree is None:
            g.add_raise("count(r) AS deg", RuntimeError("probe failed"))
        else:
            g.add_response("count(r) AS deg", [{"deg": degree}])
        g.add_response(_ONE_HOP_FRAGMENT, [{"name": "nb", "file": "f.py"}])

    data = _trace_data(seed)
    text = asyncio.run(
        _call_tool(_make_server(data), "trace_execution_path", {"function_name": "foo"})
    )
    # Degraded_Result is a successful, labeled response.
    assert not text.startswith("[ERROR]")
    assert "Highly connected node" in text
    # No variable-length expansion was ever issued.
    assert not any("*1.." in q for q in _cyphers(data))


# ── P3: Non-hub equivalence ──────────────────────────────────────────────


@_SETTINGS
@given(degree=st.integers(min_value=0, max_value=FAN_OUT_THRESHOLD))
def test_p3_non_hub_runs_bounded_expansion(degree: int) -> None:
    def seed(g: MockGraphDB) -> None:
        g.add_response("count(r) AS deg", [{"deg": degree}])
        g.add_response("CALLS*1..", [{"callee": "alpha", "file": "a.py", "depth": 1}])

    data = _trace_data(seed)
    text = asyncio.run(
        _call_tool(
            _make_server(data),
            "trace_execution_path",
            {"function_name": "foo", "include_weights": False},
        )
    )
    # Non-hub: not degraded, renders the seeded callee, and issues the
    # bounded *1..N expansion (never unbounded).
    assert "Highly connected node" not in text
    assert "alpha" in text
    cyphers = _cyphers(data)
    assert any(f"CALLS*1..{CALL_CHAIN_DEPTH}" in q for q in cyphers) or any(
        re.search(r"CALLS\*1\.\.\d+", q) for q in cyphers
    )
    for q in cyphers:
        for seg in q.split("*1..")[1:]:
            assert seg[:1].isdigit()


# ── P4: Timeout never raises ─────────────────────────────────────────────


@_SETTINGS
@given(raise_fragment=st.sampled_from(["count(r) AS deg", "CALLS*1..", _ONE_HOP_FRAGMENT]))
def test_p4_timeout_never_raises(raise_fragment: str) -> None:
    def seed(g: MockGraphDB) -> None:
        # Non-hub by default so the expansion path is reachable; one of the
        # three traversal queries times out depending on the example.
        if raise_fragment != "count(r) AS deg":
            g.add_response("count(r) AS deg", [{"deg": 3}])
        g.add_response("CALLS*1..", [{"callee": "alpha", "depth": 1}])
        g.add_response(_ONE_HOP_FRAGMENT, [{"name": "nb", "file": "f.py"}])
        g.add_raise(raise_fragment, _TIMEOUT_EXC)

    data = _trace_data(seed)
    # Must not raise — returns a string Degraded_Result / notice.
    text = asyncio.run(
        _call_tool(_make_server(data), "trace_execution_path", {"function_name": "foo"})
    )
    assert isinstance(text, str) and text
    # A statement-timeout degrades to a successful response, not [ERROR].
    assert not text.startswith("[ERROR]")


# ── P5: Tenant scoping preserved ─────────────────────────────────────────


@_SETTINGS
@given(
    label=st.text(
        alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ_", min_size=1, max_size=10
    ),
    rels=st.sampled_from(["CALLS", "SOURCES|INVOKES|EXECUTES"]),
)
def test_p5_probe_carries_given_tenant_and_scope(label: str, rels: str) -> None:
    sentinel = ("tenant", label)
    scope_pred = f" AND a.`{label}_tenant` = '{label}'"

    async def _run() -> MockGraphDB:
        g = MockGraphDB()
        g.canned_rows = []
        g.add_response("count(r) AS deg", [{"deg": 1}])
        await anchor_degree(g, "foo", rels, tenant=sentinel, scope_pred=scope_pred)
        return g

    g = asyncio.run(_run())
    probe = [c for c in g.call_log if c[0] == "query" and "count(r) AS deg" in c[1][0]]
    assert probe
    # The probe carries the exact tenant object and the scope predicate.
    assert probe[0][3]["tenant"] == sentinel
    assert scope_pred in probe[0][1][0]
    assert rels in probe[0][1][0]


@_SETTINGS
@given(tenant_id=st.sampled_from(["gw", None]))
def test_p5_tool_queries_carry_tenant(tenant_id: str | None) -> None:
    def seed(g: MockGraphDB) -> None:
        g.add_response("count(r) AS deg", [{"deg": 2}])
        g.add_response("CALLS*1..", [{"callee": "alpha", "depth": 1}])

    data = _trace_data(seed)
    args: dict[str, Any] = {"function_name": "foo", "include_weights": False}
    if tenant_id is not None:
        args["tenant_id"] = tenant_id
    asyncio.run(_call_tool(_make_server(data), "trace_execution_path", args))
    calls = [c for c in data.graph_db.call_log if c[0] == "query"]
    assert calls
    # Every emitted query carries a resolved tenant (never None).
    for c in calls:
        assert c[3]["tenant"] is not None
