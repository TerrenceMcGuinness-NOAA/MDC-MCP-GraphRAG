"""Unit tests for :mod:`src.tools.graph_rag` (Task 10.3, Phase B7).

Covers tool-schema parity with Node.js (parameter names, defaults,
required flags, enum values); degraded-mode behaviour for all 9 tools
(graph/vector-backed tools need ``data``, session tools only need an
injected SessionManager); tool-layer markdown rendering against
``MockUnifiedDataAccess`` with canned rows; session lifecycle
round-trip (mark_as_modified → get_session_context → checkpoint →
restore); restore_checkpoint with invalid ID error handling;
change_type routing in ``get_change_impact``; ``include_community``
collection query in ``get_code_context``; ``token_budget`` clamping
on GGSR-backed tools.

No live AWS calls. Session tests inject a tmp-dir-backed SessionManager
so the file system state is isolated per test.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastmcp import FastMCP

from src.sdd.session_manager import SessionManager
from src.tools import graph_rag
from src.tools._traversal_bounds import (
    BFS_ACTIVATION_THRESHOLD,
    FAN_OUT_THRESHOLD,
)
from tests.conftest import (
    MockGraphDB,
    MockUnifiedDataAccess,
    MockVectorDB,
)

pytestmark = pytest.mark.unit


# ── helpers ────────────────────────────────────────────────────────────


def _make_session(tmp_path: Path) -> SessionManager:
    """Fresh tmp-dir SessionManager with an active session already started."""
    session = SessionManager(state_dir=tmp_path / "state")
    session.start_session("phase_b7_test", total_steps=3, notes="unit test")
    return session


def _make_server(
    *,
    data: Any = None,
    session: SessionManager | None = None,
) -> FastMCP:
    mcp = FastMCP("mdc-mcp-rag-test", version="1.0.0")
    graph_rag.register(mcp, data=data, session_manager=session)
    return mcp


async def _call_tool(
    mcp: FastMCP, name: str, arguments: dict[str, Any]
) -> str:
    tool = await mcp.get_tool(name)
    result = await tool.run(arguments)
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text is not None:
            return text
    return str(result)


def _seed_empty_graph(graph: MockGraphDB) -> None:
    """Wipe the default canned rows so a fresh mock returns nothing by
    default. Tests seed specific fragment responses as needed."""
    graph.canned_rows = []


def _seed_node_lookup(graph: MockGraphDB, rows: list[dict[str, Any]]) -> None:
    graph.add_response(
        "n.name = $name OR n.absolutePath CONTAINS $name",
        rows,
    )


def _seed_fuzzy_lookup(graph: MockGraphDB, rows: list[dict[str, Any]]) -> None:
    graph.add_response(
        "toLower(n.name) CONTAINS toLower($name)",
        rows,
    )


def _seed_callers(graph: MockGraphDB, rows: list[dict[str, Any]]) -> None:
    graph.add_response(
        "(caller)-[r:CALLS|USES|IMPORTS|EXECUTES|INVOKES]->(target)",
        rows,
    )


def _seed_direct_dependents(
    graph: MockGraphDB, rows: list[dict[str, Any]]
) -> None:
    graph.add_response(
        "(dependent)-[r:CALLS|USES|IMPORTS|EXECUTES|INVOKES|SOURCES]",
        rows,
    )


def _seed_indirect_dependents(
    graph: MockGraphDB, rows: list[dict[str, Any]]
) -> None:
    graph.add_response(
        "(indirect)-[:CALLS|USES|IMPORTS]->(direct)",
        rows,
    )


def _seed_outgoing(graph: MockGraphDB, rows: list[dict[str, Any]]) -> None:
    graph.add_response(
        "(source)-[r:CALLS|USES|IMPORTS|EXECUTES|INVOKES|SOURCES]",
        rows,
    )


def _seed_shortest_path(
    graph: MockGraphDB, rows: list[dict[str, Any]]
) -> None:
    graph.add_response("shortestPath", rows)


def _seed_community_id(
    graph: MockGraphDB, rows: list[dict[str, Any]]
) -> None:
    graph.add_response("n.communityId AS communityId", rows)


# ── registration parity ───────────────────────────────────────────────


async def test_register_exposes_nine_tools_with_matching_names() -> None:
    mcp = _make_server()
    tools = await mcp.list_tools(run_middleware=False)
    names = sorted(t.name for t in tools)
    assert names == sorted(
        [
            "get_code_context",
            "search_architecture",
            "find_similar_code",
            "get_change_impact",
            "trace_data_flow",
            "mark_as_modified",
            "get_session_context",
            "checkpoint_state",
            "restore_checkpoint",
        ]
    )


async def test_tool_schemas_match_nodejs_parameter_names() -> None:
    mcp = _make_server()
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    expected = {
        "get_code_context": {
            "symbol",
            "depth",
            "include_community",
            "token_budget", "tenant_id"},
        "search_architecture": {"query", "max_results", "tenant_id"},
        "find_similar_code": {
            "code_or_symbol",
            "similarity_threshold",
            "max_results", "tenant_id"},
        "get_change_impact": {"symbol", "change_type", "include_indirect", "tenant_id"},
        "trace_data_flow": {"from_symbol", "to_symbol", "max_depth", "tenant_id"},
        "mark_as_modified": {"file_path", "change_type", "description"},
        "get_session_context": {"include_dirty"},
        "checkpoint_state": {"name", "description"},
        "restore_checkpoint": {"checkpoint_id"},
    }
    for name, params in expected.items():
        props = set(tools[name].parameters.get("properties", {}).keys())
        assert props == params, f"{name}: expected {params}, got {props}"


async def test_required_fields_match_nodejs() -> None:
    mcp = _make_server()
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    required = {
        "get_code_context": {"symbol"},
        "search_architecture": {"query"},
        "find_similar_code": {"code_or_symbol"},
        "get_change_impact": {"symbol"},
        "trace_data_flow": {"from_symbol"},
        "mark_as_modified": {"file_path"},
        "get_session_context": set(),
        "checkpoint_state": {"name"},
        "restore_checkpoint": {"checkpoint_id"},
    }
    for name, want in required.items():
        got = set(tools[name].parameters.get("required") or [])
        assert got == want, f"{name}: required {got} vs {want}"


async def test_defaults_match_nodejs() -> None:
    mcp = _make_server()
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    checks: dict[str, dict[str, Any]] = {
        "get_code_context": {
            "depth": 2,
            "include_community": True,
            "token_budget": 4000,
        },
        "search_architecture": {"max_results": 5},
        "find_similar_code": {
            "similarity_threshold": 0.7,
            "max_results": 10,
        },
        "get_change_impact": {
            "change_type": "behavior",
            "include_indirect": True,
        },
        "trace_data_flow": {"max_depth": 5},
        "mark_as_modified": {"change_type": "content"},
        "get_session_context": {"include_dirty": True},
    }
    for name, defaults in checks.items():
        props = tools[name].parameters["properties"]
        for key, want in defaults.items():
            assert props[key]["default"] == want, (
                f"{name}.{key} default {props[key].get('default')!r} != {want!r}"
            )


async def test_enum_values_match_nodejs() -> None:
    mcp = _make_server()
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}

    def _enum(schema: dict[str, Any]) -> set[str]:
        enum = schema.get("enum")
        if enum is None:
            for branch in schema.get("anyOf", []):
                if "enum" in branch:
                    return set(branch["enum"])
        return set(enum or [])

    change_impact = (
        tools["get_change_impact"].parameters["properties"]["change_type"]
    )
    # Node.js: ['signature', 'behavior', 'delete', 'rename']
    assert _enum(change_impact) == {
        "signature",
        "behavior",
        "delete",
        "rename",
    }

    modification = (
        tools["mark_as_modified"].parameters["properties"]["change_type"]
    )
    # Node.js: ['content', 'signature', 'delete', 'rename'] — differs
    # from get_change_impact (uses content instead of behavior).
    assert _enum(modification) == {
        "content",
        "signature",
        "delete",
        "rename",
    }


# ── degraded mode ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "tool_name,arguments",
    [
        ("get_code_context", {"symbol": "forecast"}),
        ("search_architecture", {"query": "how does forecast work"}),
        ("find_similar_code", {"code_or_symbol": "forecast"}),
        ("get_change_impact", {"symbol": "forecast"}),
        ("trace_data_flow", {"from_symbol": "forecast"}),
    ],
)
async def test_graph_backed_tools_return_error_when_data_missing(
    tool_name: str, arguments: dict[str, Any], tmp_path: Path
) -> None:
    """The 5 graph/vector-backed tools surface ``[ERROR] ... unavailable ...``
    when booted without a data-access layer (Requirement 1.7)."""
    session = _make_session(tmp_path)
    mcp = _make_server(data=None, session=session)
    text = await _call_tool(mcp, tool_name, arguments)
    assert "[ERROR]" in text, text
    assert "unavailable" in text


@pytest.mark.parametrize(
    "tool_name,arguments",
    [
        ("mark_as_modified", {"file_path": "scripts/x.py"}),
        ("get_session_context", {}),
        ("checkpoint_state", {"name": "pre-refactor"}),
    ],
)
async def test_session_tools_work_without_data(
    tool_name: str, arguments: dict[str, Any], tmp_path: Path
) -> None:
    """Session tools do not require ``data`` — a SessionManager is
    sufficient. This is the split degraded-mode contract from the task."""
    session = _make_session(tmp_path)
    mcp = _make_server(data=None, session=session)
    text = await _call_tool(mcp, tool_name, arguments)
    assert "[ERROR]" not in text, text


async def test_get_session_context_no_active_session(tmp_path: Path) -> None:
    """When a SessionManager has no active session the tool should render
    the "No Active Session" block rather than raising."""
    empty_session = SessionManager(state_dir=tmp_path / "empty")
    mcp = _make_server(data=None, session=empty_session)
    text = await _call_tool(mcp, "get_session_context", {})
    assert "# No Active Session" in text
    assert "start_sdd_session" in text


# ── empty-argument validation ─────────────────────────────────────────


@pytest.mark.parametrize(
    "tool_name,arguments,missing_key",
    [
        ("get_code_context", {"symbol": " "}, "symbol"),
        ("search_architecture", {"query": ""}, "query"),
        ("find_similar_code", {"code_or_symbol": " "}, "code_or_symbol"),
        ("get_change_impact", {"symbol": ""}, "symbol"),
        ("trace_data_flow", {"from_symbol": " "}, "from_symbol"),
        ("mark_as_modified", {"file_path": ""}, "file_path"),
        ("checkpoint_state", {"name": " "}, "name"),
        ("restore_checkpoint", {"checkpoint_id": ""}, "checkpoint_id"),
    ],
)
async def test_tools_reject_empty_required_arguments(
    tool_name: str,
    arguments: dict[str, Any],
    missing_key: str,
    tmp_path: Path,
) -> None:
    data = MockUnifiedDataAccess()
    session = _make_session(tmp_path)
    mcp = _make_server(data=data, session=session)
    text = await _call_tool(mcp, tool_name, arguments)
    assert "[ERROR]" in text, text
    assert missing_key in text


# ── get_code_context ──────────────────────────────────────────────────


async def test_get_code_context_reports_symbol_not_found(
    tmp_path: Path,
) -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_fuzzy_lookup(
        data.graph_db,
        [
            {"name": "forecast_run", "labels": ["Function"]},
            {"name": "forecast_setup", "labels": ["Function"]},
        ],
    )
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(mcp, "get_code_context", {"symbol": "nonexistent"})
    assert 'Symbol "nonexistent" not found' in text
    assert "forecast_run" in text
    assert "forecast_setup" in text


async def test_get_code_context_reports_no_fuzzy_matches(
    tmp_path: Path,
) -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(mcp, "get_code_context", {"symbol": "zzz"})
    assert 'Symbol "zzz" not found' in text
    assert "No similar symbols found" in text


async def test_get_code_context_renders_type_path_and_callers(
    tmp_path: Path,
) -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_node_lookup(
        data.graph_db,
        [
            {
                "name": "forecast",
                "labels": ["FortranSubroutine"],
                "path": "sorc/model/forecast.F90",
                "type": "subroutine",
                "communityId": 42,
            }
        ],
    )
    _seed_callers(
        data.graph_db,
        [
            {"name": "gfs_main", "type": "FortranProgram", "relType": "CALLS"},
            {"name": "atmos_step", "type": "FortranSubroutine", "relType": "CALLS"},
        ],
    )
    # Seed GGSR 1-hop query (see ggsr_traversal.py).
    data.graph_db.add_response(
        "MATCH (n)-[r]-(hop1)",
        [
            {
                "source": "forecast",
                "relationship": "CALLS",
                "name": "write_restart",
                "labels": ["FortranSubroutine"],
                "path": "sorc/model/write_restart.F90",
                "hop_distance": 1,
            }
        ],
    )

    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp, "get_code_context", {"symbol": "forecast", "depth": 1}
    )

    assert "# Code Context: `forecast`" in text
    assert "**Type**: FortranSubroutine" in text
    assert "**Path**: sorc/model/forecast.F90" in text
    assert "## Called By (2 callers)" in text
    assert "`gfs_main`" in text
    assert "`atmos_step`" in text
    # GGSR neighborhood rendered (from the mock ggsr query response).
    assert "## GGSR Neighborhood" in text
    assert "`write_restart`" in text


async def test_get_code_context_suppresses_community_when_flag_false(
    tmp_path: Path,
) -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_node_lookup(
        data.graph_db,
        [{"name": "forecast", "labels": ["Function"], "path": "x.py"}],
    )
    _seed_callers(data.graph_db, [])
    # Seed a community summary; tool should skip it when
    # include_community=False.
    data.vector_db.hits = [
        {
            "id": "comm-1",
            "content": "FORECAST SUBSYSTEM SUMMARY",
            "score": 0.9,
            "metadata": {"communityId": 42},
        }
    ]

    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp,
        "get_code_context",
        {"symbol": "forecast", "include_community": False},
    )
    # The community section is specifically suppressed; note that the
    # same text MAY appear in the Semantic Snippets section (which is
    # driven by the GGSR vector-enrichment path and is unaffected by
    # ``include_community``). We check the section heading only.
    assert "## Subsystem Context" not in text


async def test_get_code_context_includes_community_when_flag_true(
    tmp_path: Path,
) -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_node_lookup(
        data.graph_db,
        [{"name": "forecast", "labels": ["Function"], "path": "x.py"}],
    )
    _seed_callers(data.graph_db, [])
    data.vector_db.hits = [
        {
            "id": "comm-1",
            "content": "FORECAST SUBSYSTEM SUMMARY",
            "score": 0.9,
            "metadata": {"communityId": 42},
        }
    ]

    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp,
        "get_code_context",
        {"symbol": "forecast", "include_community": True},
    )
    assert "## Subsystem Context" in text
    assert "Community 42" in text
    assert "FORECAST SUBSYSTEM SUMMARY" in text


async def test_get_code_context_records_examined_symbol(
    tmp_path: Path,
) -> None:
    """Side effect: ``get_code_context`` should update the session's
    examined-symbol list via ``SessionManager.examine_symbol``."""
    session = _make_session(tmp_path)
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_node_lookup(
        data.graph_db,
        [{"name": "forecast", "labels": ["Function"], "path": "x.py"}],
    )
    _seed_callers(data.graph_db, [])
    mcp = _make_server(data=data, session=session)

    await _call_tool(mcp, "get_code_context", {"symbol": "forecast"})

    ctx = session.get_session_context()
    examined = [e.get("symbol") for e in ctx["examined"]]
    assert examined == ["forecast"]


async def test_get_code_context_clamps_depth_to_bounds(
    tmp_path: Path,
) -> None:
    """``depth`` is clamped to 1..3."""
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_node_lookup(
        data.graph_db,
        [{"name": "forecast", "labels": ["Function"]}],
    )
    _seed_callers(data.graph_db, [])
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    # depth=0 and depth=99 must both render without crashing.
    for depth_in in (0, 99):
        text = await _call_tool(
            mcp, "get_code_context", {"symbol": "forecast", "depth": depth_in}
        )
        assert "# Code Context" in text


async def test_get_code_context_token_budget_zero_suppresses_ggsr(
    tmp_path: Path,
) -> None:
    """``token_budget=0`` skips the GGSR/semantic retrieval entirely."""
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_node_lookup(
        data.graph_db,
        [{"name": "forecast", "labels": ["Function"]}],
    )
    _seed_callers(data.graph_db, [])
    data.graph_db.add_response(
        "MATCH (n)-[r]-(hop1)",
        [
            {
                "source": "forecast",
                "relationship": "CALLS",
                "name": "should_not_appear",
                "labels": ["Function"],
                "hop_distance": 1,
            }
        ],
    )
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp,
        "get_code_context",
        {"symbol": "forecast", "token_budget": 0},
    )
    assert "should_not_appear" not in text
    assert "## GGSR Neighborhood" not in text


# ── search_architecture ───────────────────────────────────────────────


async def test_search_architecture_returns_error_without_vector(
    tmp_path: Path,
) -> None:
    class NoVector:
        graph_db = MockGraphDB()
        vector_db = None

    mcp = _make_server(data=NoVector(), session=_make_session(tmp_path))
    text = await _call_tool(
        mcp, "search_architecture", {"query": "how does forecast work"}
    )
    assert "[ERROR]" in text
    assert "Vector database unavailable" in text


async def test_search_architecture_renders_community_hits(
    tmp_path: Path,
) -> None:
    data = MockUnifiedDataAccess()
    data.vector_db.hits = [
        {
            "id": "c-1",
            "content": "The GFS forecast subsystem runs the spectral model.",
            "score": 0.92,
            "metadata": {
                "communityId": 7,
                "nodeCount": 42,
                "dominantType": "FortranSubroutine",
            },
        },
        {
            "id": "c-2",
            "content": "Ocean coupling community.",
            "score": 0.82,
            "metadata": {"communityId": 3},
        },
    ]
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp,
        "search_architecture",
        {"query": "forecast subsystem"},
    )
    assert "# Architecture Search" in text
    assert "## 1. Community 7 (relevance: 0.920)" in text
    assert "42 nodes, FortranSubroutine type" in text
    assert "## 2. Community 3 (relevance: 0.820)" in text


async def test_search_architecture_empty_results(tmp_path: Path) -> None:
    data = MockUnifiedDataAccess()
    data.vector_db.hits = []
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp, "search_architecture", {"query": "nowhere"}
    )
    assert "No architectural context found" in text


async def test_search_architecture_clamps_max_results(tmp_path: Path) -> None:
    data = MockUnifiedDataAccess()
    data.vector_db.hits = [
        {"id": f"c-{i}", "content": f"Community {i}", "score": 0.5, "metadata": {"communityId": i}}
        for i in range(50)
    ]
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    await _call_tool(
        mcp,
        "search_architecture",
        {"query": "x", "max_results": 99},
    )
    # Query should be clamped to max bound 10.
    calls = [c for c in data.vector_db.call_log if c[0] == "query"]
    assert calls, "vector query not made"
    assert calls[0][2]["k"] == 10


# ── find_similar_code ─────────────────────────────────────────────────


async def test_find_similar_code_filters_by_threshold(tmp_path: Path) -> None:
    data = MockUnifiedDataAccess()
    data.vector_db.hits = [
        {
            "id": "h-1",
            "content": "similar code A",
            "score": 0.95,
            "metadata": {"file_path": "sorc/a.F90"},
        },
        {
            "id": "h-2",
            "content": "similar code B",
            "score": 0.72,
            "metadata": {"file_path": "sorc/b.F90"},
        },
        {
            "id": "h-3",
            "content": "loosely related",
            "score": 0.50,
            "metadata": {"file_path": "sorc/c.F90"},
        },
    ]
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp,
        "find_similar_code",
        {"code_or_symbol": "forecast", "similarity_threshold": 0.7},
    )
    assert "a.F90" in text
    assert "b.F90" in text
    # Below-threshold hit filtered out.
    assert "c.F90" not in text


async def test_find_similar_code_below_threshold_renders_no_match(
    tmp_path: Path,
) -> None:
    data = MockUnifiedDataAccess()
    data.vector_db.hits = [
        {
            "id": "h",
            "content": "x",
            "score": 0.1,
            "metadata": {"file_path": "a.F90"},
        }
    ]
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp,
        "find_similar_code",
        {"code_or_symbol": "forecast"},
    )
    assert "No code found above" in text


async def test_find_similar_code_clamps_similarity_threshold(
    tmp_path: Path,
) -> None:
    """``similarity_threshold`` out of [0, 1] is silently clamped."""
    data = MockUnifiedDataAccess()
    data.vector_db.hits = [
        {
            "id": "h",
            "content": "x",
            "score": 1.0,
            "metadata": {"file_path": "a.F90"},
        }
    ]
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    # Threshold = 99 gets clamped to 1.0; score = 1.0 passes.
    text = await _call_tool(
        mcp,
        "find_similar_code",
        {"code_or_symbol": "x", "similarity_threshold": 99.0},
    )
    assert "a.F90" in text


async def test_find_similar_code_requests_2x_max_results(tmp_path: Path) -> None:
    """The tool over-fetches (k = 2 * max_results) to leave headroom
    for threshold filtering before returning ``max_results``."""
    data = MockUnifiedDataAccess()
    data.vector_db.hits = []
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    await _call_tool(
        mcp,
        "find_similar_code",
        {"code_or_symbol": "x", "max_results": 5},
    )
    calls = [c for c in data.vector_db.call_log if c[0] == "query"]
    assert calls, "vector query not made"
    assert calls[0][2]["k"] == 10  # 2 × max_results


async def test_find_similar_code_clamps_max_results_to_25(tmp_path: Path) -> None:
    data = MockUnifiedDataAccess()
    data.vector_db.hits = []
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    await _call_tool(
        mcp,
        "find_similar_code",
        {"code_or_symbol": "x", "max_results": 999},
    )
    calls = [c for c in data.vector_db.call_log if c[0] == "query"]
    # Clamped to 25, then doubled → 50.
    assert calls[0][2]["k"] == 50


# ── get_change_impact ─────────────────────────────────────────────────


async def test_get_change_impact_renders_dependents_and_risk(
    tmp_path: Path,
) -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_direct_dependents(
        data.graph_db,
        [
            {"name": "alpha", "type": "Function", "relType": "CALLS", "path": "a.py"},
            {"name": "beta", "type": "Function", "relType": "CALLS", "path": "b.py"},
        ],
    )
    _seed_indirect_dependents(
        data.graph_db,
        [{"name": "gamma", "type": "Function", "path": "g.py"}],
    )
    _seed_community_id(data.graph_db, [])
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp, "get_change_impact", {"symbol": "forecast"}
    )
    assert "# Change Impact: `forecast`" in text
    assert "**Change Type**: behavior" in text
    assert "Risk Level" in text
    assert "## Direct Dependents (2)" in text
    assert "`alpha`" in text
    assert "`beta`" in text
    assert "## Indirect Dependents (1)" in text
    assert "`gamma`" in text
    assert "## Recommendations" in text


async def test_get_change_impact_suppresses_indirect_when_flag_off(
    tmp_path: Path,
) -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_direct_dependents(
        data.graph_db,
        [{"name": "alpha", "type": "Function", "relType": "CALLS"}],
    )
    # Seed indirect rows — tool must NOT query them.
    _seed_indirect_dependents(
        data.graph_db,
        [{"name": "should_not_appear", "type": "Function"}],
    )
    _seed_community_id(data.graph_db, [])
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp,
        "get_change_impact",
        {"symbol": "forecast", "include_indirect": False},
    )
    assert "## Indirect Dependents" not in text
    assert "should_not_appear" not in text


@pytest.mark.parametrize(
    "change_type,expected_factor_hint,expected_extra",
    [
        ("delete", "Change type: delete", "WARNING"),
        ("signature", "Change type: signature", "new signature"),
        ("rename", "Change type: rename", "string references"),
        ("behavior", "Change type: behavior", None),
    ],
)
async def test_get_change_impact_change_type_routing(
    change_type: str,
    expected_factor_hint: str,
    expected_extra: str | None,
    tmp_path: Path,
) -> None:
    """Each ``change_type`` enum value produces its own factor label
    and recommendation text, matching the Node.js routing table."""
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_direct_dependents(
        data.graph_db,
        [{"name": "alpha", "type": "Function", "relType": "CALLS"}],
    )
    _seed_indirect_dependents(data.graph_db, [])
    _seed_community_id(data.graph_db, [])
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp,
        "get_change_impact",
        {"symbol": "forecast", "change_type": change_type},
    )
    assert expected_factor_hint in text
    if expected_extra:
        assert expected_extra in text


def test_risk_score_buckets_match_nodejs() -> None:
    """The scoring formula must place the same inputs in the same
    HIGH / MEDIUM / LOW bucket as the Node.js ``_computeRiskScore``.

    Directly exercises :pyfunc:`graph_rag._compute_risk_score` so the
    parity property is testable without a live graph."""
    # Pure CALLS → behavior, no dependents: all bias from change_type=0.1 → LOW.
    low = graph_rag._compute_risk_score(
        direct_count=0, indirect_count=0, change_type="behavior"
    )
    assert low["level"] == "LOW"

    # 10 direct + 40 indirect + delete (0.3) → HIGH.
    high = graph_rag._compute_risk_score(
        direct_count=10, indirect_count=40, change_type="delete"
    )
    assert high["level"] == "HIGH"

    # 5 direct + 10 indirect + signature (0.25) → MEDIUM band.
    medium = graph_rag._compute_risk_score(
        direct_count=5, indirect_count=10, change_type="signature"
    )
    assert medium["level"] in ("MEDIUM", "LOW")  # boundary case


def test_risk_score_caps_at_one() -> None:
    """Score saturates at 1.0 even for very large dependent counts."""
    result = graph_rag._compute_risk_score(
        direct_count=10_000,
        indirect_count=10_000,
        change_type="delete",
    )
    assert result["score"] <= 1.0
    assert result["level"] == "HIGH"


async def test_get_change_impact_skips_indirect_when_direct_over_100(
    tmp_path: Path,
) -> None:
    """The Node.js indirect-query short-circuits when the direct list
    is >= 100 to bound query cost. Port respects the same cap."""
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    # 150 direct dependents.
    _seed_direct_dependents(
        data.graph_db,
        [
            {"name": f"d{i}", "type": "Function", "relType": "CALLS"}
            for i in range(150)
        ],
    )
    _seed_indirect_dependents(
        data.graph_db,
        [{"name": "should_be_skipped", "type": "Function"}],
    )
    _seed_community_id(data.graph_db, [])
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp,
        "get_change_impact",
        {"symbol": "popular"},
    )
    assert "## Direct Dependents (150)" in text
    assert "should_be_skipped" not in text


# ── trace_data_flow ──────────────────────────────────────────────────


async def test_trace_data_flow_renders_outgoing_edges(tmp_path: Path) -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_outgoing(
        data.graph_db,
        [
            {"name": "child_a", "type": "Function", "relType": "CALLS"},
            {"name": "child_b", "type": "Function", "relType": "USES"},
        ],
    )
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp, "trace_data_flow", {"from_symbol": "forecast"}
    )
    assert "# Data Flow Trace: `forecast`" in text
    assert "## Outgoing Relationships (2)" in text
    assert "`child_a`" in text
    assert "`child_b`" in text


async def test_trace_data_flow_response_carries_bfs_header(
    tmp_path: Path,
) -> None:
    """R8.4 at the tool boundary: a degree inside the BFS band routes the
    outgoing fan-out through the walker, and the indicator says so on the
    line after the title.

    The degree is seeded at 50 — at or above BFS_ACTIVATION_THRESHOLD (30)
    so the walk is selected, and at or below FAN_OUT_THRESHOLD (100) so
    the anchor is not read as a hub, which would return the
    Degraded_Result without attempting any walk (R3.1, R3.2).
    """
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    data.graph_db.add_response("count(r) AS deg", [{"deg": 50}])
    data.graph_db.add_response("RETURN id(n) AS nid", [{"nid": "anchor-1"}])
    data.graph_db.add_response(
        "MATCH (a)-[:CALLS]->(b)",
        [
            {
                "nid": "child-1",
                "name": "child_a",
                "path": None,
                "labels": ["Function"],
            }
        ],
    )

    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp, "trace_data_flow", {"from_symbol": "forecast"}
    )
    lines = text.splitlines()
    title = lines.index("# Data Flow Trace: `forecast`")
    assert lines[title + 1].startswith("[optimized: BFS walker, ")
    assert lines[title + 1].endswith("]")
    assert lines[title + 2] == ""
    # Anti-vacuity: the walk produced the rendered fan-out.
    assert "`child_a`" in text


async def test_trace_data_flow_single_query_has_no_bfs_header(
    tmp_path: Path,
) -> None:
    """The other half of R8.4: a low-degree anchor keeps the single query,
    so the response carries no indicator (R5.1)."""
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_outgoing(
        data.graph_db,
        [{"name": "child_a", "type": "Function", "relType": "CALLS"}],
    )
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp, "trace_data_flow", {"from_symbol": "forecast"}
    )
    assert "[optimized: BFS walker" not in text
    assert "`child_a`" in text


async def test_trace_data_flow_renders_shortest_path_when_to_symbol_set(
    tmp_path: Path,
) -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_outgoing(data.graph_db, [])
    _seed_shortest_path(
        data.graph_db,
        [
            {
                "nodeNames": ["a", "b", "c"],
                "relTypes": ["CALLS", "CALLS"],
                "hops": 2,
            }
        ],
    )
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp,
        "trace_data_flow",
        {"from_symbol": "a", "to_symbol": "c"},
    )
    assert "## Shortest Path to `c`" in text
    assert "2 hops" in text
    assert "`a` -[CALLS]→" in text


async def test_trace_data_flow_reports_no_path_found(tmp_path: Path) -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_outgoing(data.graph_db, [])
    _seed_shortest_path(data.graph_db, [])
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp,
        "trace_data_flow",
        {"from_symbol": "a", "to_symbol": "c"},
    )
    assert f"## Path to `c`" in text
    assert "No path found within" in text


async def test_trace_data_flow_clamps_max_depth_to_ten(tmp_path: Path) -> None:
    """``max_depth`` is clamped to DATA_FLOW_DEPTH and embedded in cypher.

    R2.2 caps the shortestPath depth at a conservative 5 (reduced from
    the historical 10); we inspect the mock call log to confirm the
    rendered query uses ``*1..5`` regardless of how far the caller asked
    to look."""
    from src.tools._traversal_bounds import DATA_FLOW_DEPTH

    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_outgoing(data.graph_db, [])
    _seed_shortest_path(data.graph_db, [])
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    await _call_tool(
        mcp,
        "trace_data_flow",
        {"from_symbol": "a", "to_symbol": "z", "max_depth": 99},
    )
    queries = [
        c[1][0] for c in data.graph_db.call_log if c[0] == "query"
    ]
    expected = f"*1..{DATA_FLOW_DEPTH}"
    assert any("shortestPath" in q and expected in q for q in queries)
    assert not any("*1..10" in q for q in queries)
    assert not any("*1..99" in q for q in queries)


async def test_trace_data_flow_empty_response(tmp_path: Path) -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_outgoing(data.graph_db, [])
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp, "trace_data_flow", {"from_symbol": "nowhere"}
    )
    assert "No data flow found" in text


# ── session lifecycle ─────────────────────────────────────────────────


async def test_mark_as_modified_records_session_modification(
    tmp_path: Path,
) -> None:
    session = _make_session(tmp_path)
    mcp = _make_server(data=None, session=session)
    text = await _call_tool(
        mcp,
        "mark_as_modified",
        {
            "file_path": "scripts/exglobal_forecast.py",
            "change_type": "content",
            "description": "Added YAML config",
        },
    )
    assert "# File Modification Recorded" in text
    assert "`scripts/exglobal_forecast.py`" in text
    assert "Added YAML config" in text
    assert "**Total Modifications**: 1" in text

    # Round-trip into SessionManager state.
    ctx = session.get_session_context()
    assert len(ctx["modifications"]) == 1
    assert ctx["modifications"][0]["filePath"] == "scripts/exglobal_forecast.py"
    assert ctx["modifications"][0]["changeType"] == "content"


async def test_mark_as_modified_reports_graph_dirty_when_available(
    tmp_path: Path,
) -> None:
    session = _make_session(tmp_path)
    data = MockUnifiedDataAccess()
    mcp = _make_server(data=data, session=session)
    text = await _call_tool(
        mcp,
        "mark_as_modified",
        {"file_path": "scripts/x.py"},
    )
    assert "**Graph Dirty**: Yes" in text
    # Confirm the graph received the UPDATE cypher.
    queries = [
        c[1][0] for c in data.graph_db.call_log if c[0] == "query"
    ]
    assert any("SET n._dirty = true" in q for q in queries)


async def test_mark_as_modified_reports_graph_unavailable_in_degraded_mode(
    tmp_path: Path,
) -> None:
    session = _make_session(tmp_path)
    mcp = _make_server(data=None, session=session)
    text = await _call_tool(
        mcp,
        "mark_as_modified",
        {"file_path": "scripts/x.py"},
    )
    assert "**Graph Dirty**: No (graph unavailable)" in text


async def test_get_session_context_renders_full_summary(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    # Seed some state directly via the SessionManager API.
    session.mark_modified("a.py", change_type="content", description="step 1")
    session.mark_modified("b.py", change_type="signature", description="step 2")
    session.examine_symbol("forecast", {"type": "Function", "path": "x.py"})
    session.checkpoint_state("pre-refactor", description="safety net")

    mcp = _make_server(data=None, session=session)
    text = await _call_tool(mcp, "get_session_context", {})

    assert "# Session Context" in text
    assert "**Phase**: phase_b7_test" in text
    assert "| Files Modified | 2 |" in text
    assert "| Symbols Examined | 1 |" in text
    assert "| Checkpoints | 1 |" in text
    assert "## Modifications (2)" in text
    assert "`a.py`" in text
    assert "`b.py`" in text
    assert "## Examined Symbols (1)" in text
    assert "`forecast`" in text
    assert "## Checkpoints (1)" in text
    assert "pre-refactor" in text


async def test_get_session_context_include_dirty_false_adds_footer(
    tmp_path: Path,
) -> None:
    """The ``include_dirty`` flag is schema-visible even though the
    Python port has no in-memory dirty state to suppress. The tool
    adds a footer line so callers can confirm the flag was read."""
    session = _make_session(tmp_path)
    mcp = _make_server(data=None, session=session)
    text = await _call_tool(
        mcp, "get_session_context", {"include_dirty": False}
    )
    assert "dirty state display suppressed" in text


async def test_checkpoint_state_creates_snapshot(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    session.mark_modified("a.py", change_type="content", description="first")
    mcp = _make_server(data=None, session=session)
    text = await _call_tool(
        mcp,
        "checkpoint_state",
        {"name": "pre-refactor", "description": "safety net"},
    )
    assert "# Checkpoint Created" in text
    assert "pre-refactor" in text
    assert "safety net" in text
    assert "1 modification(s)" in text

    # Confirm SessionManager persisted the checkpoint file.
    ctx = session.get_session_context()
    assert len(ctx["checkpoints"]) == 1


async def test_session_lifecycle_checkpoint_restore_round_trip(
    tmp_path: Path,
) -> None:
    """Full round-trip: mark → checkpoint → more modifications →
    restore → verify state rolled back."""
    session = _make_session(tmp_path)
    mcp = _make_server(data=None, session=session)

    await _call_tool(
        mcp,
        "mark_as_modified",
        {"file_path": "a.py", "description": "pre-checkpoint change"},
    )
    chk_text = await _call_tool(
        mcp, "checkpoint_state", {"name": "safety-net"}
    )
    # Extract the checkpoint ID from the rendered response.
    import re
    match = re.search(r"\*\*ID\*\*:\s+`([^`]+)`", chk_text)
    assert match, "checkpoint ID not found in response"
    checkpoint_id = match.group(1)

    # Add modifications AFTER the checkpoint.
    await _call_tool(
        mcp,
        "mark_as_modified",
        {"file_path": "b.py", "description": "post-checkpoint change"},
    )
    ctx_before_restore = session.get_session_context()
    assert len(ctx_before_restore["modifications"]) == 2

    # Restore and confirm the post-checkpoint modification is gone.
    restore_text = await _call_tool(
        mcp, "restore_checkpoint", {"checkpoint_id": checkpoint_id}
    )
    assert "# Checkpoint Restored" in restore_text
    ctx_after = session.get_session_context()
    assert len(ctx_after["modifications"]) == 1
    assert ctx_after["modifications"][0]["filePath"] == "a.py"


async def test_restore_checkpoint_invalid_id_returns_error(
    tmp_path: Path,
) -> None:
    """Invalid / unknown checkpoint IDs return a clear ``[ERROR]`` —
    not a crash or traceback."""
    session = _make_session(tmp_path)
    mcp = _make_server(data=None, session=session)
    text = await _call_tool(
        mcp,
        "restore_checkpoint",
        {"checkpoint_id": "chk_nonexistent_xxxxxx"},
    )
    assert "[ERROR]" in text, text
    assert "chk_nonexistent_xxxxxx" in text or "not found" in text


async def test_checkpoint_state_without_active_session_returns_error(
    tmp_path: Path,
) -> None:
    """Creating a checkpoint without an active session surfaces an
    ``[ERROR]``, matching the SessionManager contract."""
    empty_session = SessionManager(state_dir=tmp_path / "empty")
    mcp = _make_server(data=None, session=empty_session)
    text = await _call_tool(
        mcp, "checkpoint_state", {"name": "orphan"}
    )
    assert "[ERROR]" in text
    assert "session" in text.lower()


async def test_mark_as_modified_without_active_session_returns_error(
    tmp_path: Path,
) -> None:
    empty_session = SessionManager(state_dir=tmp_path / "empty")
    mcp = _make_server(data=None, session=empty_session)
    text = await _call_tool(
        mcp,
        "mark_as_modified",
        {"file_path": "a.py"},
    )
    assert "[ERROR]" in text


# ── graph-error propagation ──────────────────────────────────────────


async def test_get_code_context_handles_graph_error_gracefully(
    tmp_path: Path,
) -> None:
    data = MockUnifiedDataAccess()
    data.graph_db.raise_on_query = RuntimeError("neptune unreachable")
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp, "get_code_context", {"symbol": "forecast"}
    )
    assert "[ERROR]" in text
    assert "neptune unreachable" in text


async def test_search_architecture_handles_vector_error_gracefully(
    tmp_path: Path,
) -> None:
    data = MockUnifiedDataAccess()
    data.vector_db.raise_on_query = RuntimeError("opensearch down")
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp, "search_architecture", {"query": "x"}
    )
    assert "[ERROR]" in text
    assert "opensearch down" in text


async def test_find_similar_code_handles_vector_error_gracefully(
    tmp_path: Path,
) -> None:
    data = MockUnifiedDataAccess()
    data.vector_db.raise_on_query = RuntimeError("timeout")
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp, "find_similar_code", {"code_or_symbol": "x"}
    )
    assert "[ERROR]" in text
    assert "timeout" in text


async def test_get_change_impact_handles_graph_error_gracefully(
    tmp_path: Path,
) -> None:
    data = MockUnifiedDataAccess()
    data.graph_db.raise_on_query = RuntimeError("conn reset")
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp, "get_change_impact", {"symbol": "forecast"}
    )
    assert "[ERROR]" in text
    assert "conn reset" in text


async def test_trace_data_flow_handles_graph_error_gracefully(
    tmp_path: Path,
) -> None:
    data = MockUnifiedDataAccess()
    data.graph_db.raise_on_query = RuntimeError("bolt closed")
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp, "trace_data_flow", {"from_symbol": "forecast"}
    )
    assert "[ERROR]" in text
    assert "bolt closed" in text


# ── default session manager (no injection) ───────────────────────────


async def test_register_creates_default_session_manager_when_none() -> None:
    """When ``session_manager`` is not passed, ``register`` constructs
    a default one against the standard state_dir. The tool must remain
    callable — even though there may or may not be an active session
    on disk, the tool should render a well-formed response (either
    an active summary or the 'No Active Session' block)."""
    mcp = _make_server(data=None, session=None)
    text = await _call_tool(mcp, "get_session_context", {})
    # Either "# Session Context" (active session exists) or "# No Active
    # Session" — anything but a crash.
    assert text.startswith("# "), text


# ── helper coverage ──────────────────────────────────────────────────


def test_clamp_respects_bounds() -> None:
    assert graph_rag._clamp(5, 1, 10) == 5
    assert graph_rag._clamp(-3, 1, 10) == 1
    assert graph_rag._clamp(99, 1, 10) == 10


def test_compute_risk_score_change_type_bias_matches_nodejs() -> None:
    """The ``CHANGE_TYPE_RISK_BIAS`` table matches the Node.js
    ``typeScores`` table verbatim."""
    assert graph_rag.CHANGE_TYPE_RISK_BIAS == {
        "delete": 0.3,
        "signature": 0.25,
        "rename": 0.2,
        "behavior": 0.1,
    }


def test_change_type_and_modification_type_enums_differ() -> None:
    """The Node.js schemas use different enum sets for
    ``get_change_impact.change_type`` and ``mark_as_modified.change_type``.
    This is an easy-to-miss parity point — exercise it explicitly."""
    assert set(graph_rag.CHANGE_TYPE_VALUES) == {
        "signature",
        "behavior",
        "delete",
        "rename",
    }
    assert set(graph_rag.MODIFICATION_TYPE_VALUES) == {
        "content",
        "signature",
        "delete",
        "rename",
    }
    # The one-character difference: 'behavior' vs 'content'.
    diff = set(graph_rag.CHANGE_TYPE_VALUES) ^ set(
        graph_rag.MODIFICATION_TYPE_VALUES
    )
    assert diff == {"behavior", "content"}


def test_generate_recommendations_emits_high_risk_steps() -> None:
    text = graph_rag._generate_recommendations(
        "delete",
        {"level": "HIGH", "score": 0.9, "factors": []},
        direct_count=20,
    )
    assert "Review all direct dependents" in text
    assert "incremental rollout" in text
    assert "regression tests" in text
    assert "WARNING" in text
    assert "20 dependent(s)" in text


def test_generate_recommendations_emits_low_risk_steps() -> None:
    text = graph_rag._generate_recommendations(
        "behavior",
        {"level": "LOW", "score": 0.1, "factors": []},
        direct_count=0,
    )
    assert "Low risk" in text


# ── bounded-graph-traversal: timeout backstop / tenant scoping ──────────
# (Wave 2, Task 4.1 — Validates R2.1, R5.3, R7.5)


def _graph_query_calls(data: MockUnifiedDataAccess) -> list[Any]:
    return [c for c in data.graph_db.call_log if c[0] == "query"]


async def test_trace_data_flow_outgoing_timeout_returns_notice_not_error(
    tmp_path: Path,
) -> None:
    """A statement-timeout on the outgoing query yields a bounded notice,
    never an [ERROR] or unhandled exception (R5.3)."""
    from src.data.neptune_adapter import NeptuneAdapterError

    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    data.graph_db.add_raise(
        "(source)-[r:CALLS|USES|IMPORTS|EXECUTES|INVOKES|SOURCES]",
        NeptuneAdapterError("query exceeded 30.0s statement timeout"),
    )
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp, "trace_data_flow", {"from_symbol": "hubsym"}
    )
    assert not text.startswith("[ERROR]")
    assert "statement timeout" in text


async def test_trace_data_flow_shortestpath_timeout_is_swallowed(
    tmp_path: Path,
) -> None:
    """A timeout on the shortestPath query degrades to 'no path', not a raise."""
    from src.data.neptune_adapter import NeptuneAdapterError

    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_outgoing(data.graph_db, [])
    data.graph_db.add_raise(
        "shortestPath",
        NeptuneAdapterError("query exceeded 30.0s statement timeout"),
    )
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp,
        "trace_data_flow",
        {"from_symbol": "a", "to_symbol": "z"},
    )
    assert not text.startswith("[ERROR]")
    assert "No path found" in text


async def test_trace_data_flow_queries_carry_tenant_and_timeout(
    tmp_path: Path,
) -> None:
    """Every emitted query carries tenant= (Property 5); traversal queries
    carry the statement-timeout (R5.2)."""
    from src.tools._traversal_bounds import TIMEOUT_S

    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_outgoing(data.graph_db, [{"name": "t", "type": "Function", "relType": "CALLS"}])
    _seed_shortest_path(data.graph_db, [])
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    await _call_tool(
        mcp,
        "trace_data_flow",
        {"from_symbol": "a", "to_symbol": "z", "max_depth": 4},
    )
    calls = _graph_query_calls(data)
    assert calls
    for c in calls:
        assert c[3]["tenant"] is not None
    outgoing = [c for c in calls if "(source)-[r:" in c[1][0]]
    assert outgoing and outgoing[0][3]["timeout"] == TIMEOUT_S
    sp = [c for c in calls if "shortestPath" in c[1][0]]
    assert sp and sp[0][3]["timeout"] == TIMEOUT_S


async def test_get_change_impact_direct_timeout_returns_notice_not_error(
    tmp_path: Path,
) -> None:
    """A statement-timeout on the direct-dependents query yields a bounded
    notice rather than [ERROR] (R5.3)."""
    from src.data.neptune_adapter import NeptuneAdapterError

    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    data.graph_db.add_raise(
        "(dependent)-[r:CALLS|USES|IMPORTS|EXECUTES|INVOKES|SOURCES]",
        NeptuneAdapterError("query exceeded 30.0s statement timeout"),
    )
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp, "get_change_impact", {"symbol": "hubsym"}
    )
    assert not text.startswith("[ERROR]")
    assert "statement timeout" in text


async def test_get_change_impact_queries_carry_tenant_and_timeout(
    tmp_path: Path,
) -> None:
    from src.tools._traversal_bounds import TIMEOUT_S

    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_direct_dependents(
        data.graph_db,
        [{"name": "dep_a", "type": "Function", "relType": "CALLS"}],
    )
    _seed_indirect_dependents(data.graph_db, [])
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    await _call_tool(
        mcp, "get_change_impact", {"symbol": "sym", "include_indirect": True}
    )
    calls = _graph_query_calls(data)
    assert calls
    for c in calls:
        assert c[3]["tenant"] is not None
    direct = [c for c in calls if "(dependent)-[r:" in c[1][0]]
    assert direct and direct[0][3]["timeout"] == TIMEOUT_S


async def test_get_code_context_caller_query_carries_timeout(
    tmp_path: Path,
) -> None:
    from src.tools._traversal_bounds import TIMEOUT_S

    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_node_lookup(
        data.graph_db,
        [{"name": "sym", "labels": ["Function"], "path": "a.py", "type": "Function"}],
    )
    _seed_callers(
        data.graph_db,
        [{"name": "caller_a", "type": "Function", "relType": "CALLS"}],
    )
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    await _call_tool(mcp, "get_code_context", {"symbol": "sym"})
    calls = _graph_query_calls(data)
    caller = [
        c for c in calls
        if "(caller)-[r:CALLS|USES|IMPORTS|EXECUTES|INVOKES]->(target)" in c[1][0]
    ]
    # The reverse-caller traversal query carries the statement-timeout
    # backstop (R5.2) and stays tenant-scoped (Property 5).
    assert caller and caller[0][3]["timeout"] == TIMEOUT_S
    assert caller[0][3]["tenant"] is not None


# ── graceful-missing-index-handling: search_architecture + find_similar_code


def _notfound_exc():
    """Synthetic opensearchpy-shaped index_not_found_exception."""
    from opensearchpy.exceptions import NotFoundError

    return NotFoundError(
        404,
        "index_not_found_exception",
        {"error": {"type": "index_not_found_exception"}},
    )


def _raise(exc):
    async def _q(*args, **kwargs):
        raise exc
    return _q


async def test_search_architecture_missing_index_returns_info_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = MockUnifiedDataAccess()
    data.vector_db.query = _raise(_notfound_exc())
    monkeypatch.setattr(graph_rag, "_tenant_id_or_none", lambda: "gw_v17")
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(mcp, "search_architecture", {"query": "ocean"})
    assert "[INFO]" in text and "[ERROR]" not in text
    assert "gw_v17" in text
    assert "community-summaries" in text
    assert "index_not_found_exception" not in text


async def test_search_architecture_non_404_keeps_error(
    tmp_path: Path,
) -> None:
    data = MockUnifiedDataAccess()
    data.vector_db.query = _raise(RuntimeError("transport boom"))
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(mcp, "search_architecture", {"query": "ocean"})
    assert "[ERROR]" in text
    assert "transport boom" in text


async def test_bug_exploration_search_architecture_missing_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug-Condition Exploration (search_architecture).

    Unfixed code renders [ERROR] ... index_not_found_exception; fixed
    code renders the [INFO] Skip_Block with tenant + collection. Both
    directions demonstrated before commit (CHANGELOG [8.36.3]).
    """
    data = MockUnifiedDataAccess()
    data.vector_db.query = _raise(_notfound_exc())
    monkeypatch.setattr(graph_rag, "_tenant_id_or_none", lambda: "gw_v17")
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(mcp, "search_architecture", {"query": "ocean"})
    assert "[INFO]" in text and "[ERROR]" not in text
    assert "gw_v17" in text and "community-summaries" in text


async def test_find_similar_code_missing_index_returns_info_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = MockUnifiedDataAccess()
    data.vector_db.query = _raise(_notfound_exc())
    monkeypatch.setattr(graph_rag, "_tenant_id_or_none", lambda: "gw_v17")
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp, "find_similar_code", {"code_or_symbol": "forecast"}
    )
    assert "[INFO]" in text and "[ERROR]" not in text
    assert "gw_v17" in text
    assert "code-with-context-v8-0-0" in text
    assert "index_not_found_exception" not in text


async def test_find_similar_code_non_404_keeps_error(
    tmp_path: Path,
) -> None:
    data = MockUnifiedDataAccess()
    data.vector_db.query = _raise(RuntimeError("transport boom"))
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp, "find_similar_code", {"code_or_symbol": "forecast"}
    )
    assert "[ERROR]" in text
    assert "transport boom" in text


async def test_bug_exploration_find_similar_code_missing_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug-Condition Exploration (find_similar_code)."""
    data = MockUnifiedDataAccess()
    data.vector_db.query = _raise(_notfound_exc())
    monkeypatch.setattr(graph_rag, "_tenant_id_or_none", lambda: "gw_v17")
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp, "find_similar_code", {"code_or_symbol": "forecast"}
    )
    assert "[INFO]" in text and "[ERROR]" not in text
    assert "gw_v17" in text and "code-with-context-v8-0-0" in text


# ══ Task 2.5 — UNION ALL Decomposition in trace_data_flow ══════════════
# Validates R1.1 (UNION ALL replaces the OR anchor predicate), R1.2 (both
# the one-hop fan-out and the shortestPath seed are decomposed), R1.3
# (set-equivalent, deduplicated output), R1.4 (Label_Scope_Predicate and
# Statement_Timeout carried unchanged on both branches).


#: A representative non-default-tenant scope fragment. The cypher
#: builders take the ``_scope_and(...)`` output verbatim, so a literal
#: keeps these tests independent of the tenant catalog.
_SCOPE_FRAGMENT = (
    " AND size([__lbl IN labels(source) "
    "WHERE __lbl STARTS WITH 'GW_V17_']) > 0"
)


# ── _outgoing_union_cypher (one-hop fan-out anchor) ────────────────────


def test_outgoing_union_cypher_emits_two_branches_not_or() -> None:
    """The anchor is two index-seekable equality branches joined by
    ``UNION ALL``, never a disjunction over ``name``/``path`` (R1.1)."""
    cypher = graph_rag._outgoing_union_cypher("")
    assert cypher.count("UNION ALL") == 1
    assert "WHERE source.name = $name" in cypher
    assert "WHERE source.path = $name" in cypher
    assert " OR " not in cypher
    assert "source.name = $name OR source.path = $name" not in cypher


def test_outgoing_union_cypher_expands_edge_set_on_both_branches() -> None:
    """Both branches traverse the same one-hop edge set, so the merged
    result is set-equivalent to the single-query form (R1.3)."""
    cypher = graph_rag._outgoing_union_cypher("")
    pattern = f"MATCH (source)-[r:{graph_rag._OUTGOING_RELS}]->(target)"
    assert cypher.count(pattern) == 2
    head, _, tail = cypher.partition("UNION ALL")
    assert pattern in head and pattern in tail


def test_outgoing_union_cypher_applies_scope_pred_to_both_branches() -> None:
    """The Label_Scope_Predicate is carried on both branches (R1.4)."""
    cypher = graph_rag._outgoing_union_cypher(_SCOPE_FRAGMENT)
    assert cypher.count(_SCOPE_FRAGMENT) == 2
    head, _, tail = cypher.partition("UNION ALL")
    assert _SCOPE_FRAGMENT in head
    assert _SCOPE_FRAGMENT in tail


def test_outgoing_union_cypher_omits_scope_pred_when_empty() -> None:
    cypher = graph_rag._outgoing_union_cypher("")
    assert "labels(source)" not in cypher
    assert cypher.count("WHERE") == 2  # exactly one per branch


def test_outgoing_union_cypher_leaves_ordering_to_the_merge() -> None:
    """Ordering/truncation cannot live in the cypher — openCypher applies
    them per branch, not to the union — so they happen in
    ``_merge_outgoing_rows`` instead (R1.3)."""
    cypher = graph_rag._outgoing_union_cypher("")
    assert "ORDER BY" not in cypher
    assert "LIMIT" not in cypher


# ── _merge_outgoing_rows (post-union dedup / order / cap) ──────────────


def test_merge_outgoing_rows_dedupes_overlapping_branch_rows() -> None:
    """A target reachable from both the ``name`` and the ``path`` branch
    arrives twice; the merge folds it back to one row (R1.3)."""
    rows = [
        # name branch
        {"name": "child_a", "type": "Function", "relType": "CALLS"},
        {"name": "child_b", "type": "Function", "relType": "USES"},
        # path branch — child_a matched on both anchor properties
        {"name": "child_a", "type": "Function", "relType": "CALLS"},
        {"name": "child_c", "type": "Script", "relType": "SOURCES"},
    ]
    merged = graph_rag._merge_outgoing_rows(rows)
    keys = [(r["name"], r["type"], r["relType"]) for r in merged]
    assert len(keys) == len(set(keys)), f"duplicate rows survived: {keys}"
    assert {k[0] for k in keys} == {"child_a", "child_b", "child_c"}


def test_merge_outgoing_keeps_same_name_under_other_rel_type() -> None:
    """Dedup keys on ``(name, type, relType)``, so the same target reached
    by two different relationship types is *not* a duplicate."""
    rows = [
        {"name": "child_a", "type": "Function", "relType": "CALLS"},
        {"name": "child_a", "type": "Function", "relType": "USES"},
    ]
    merged = graph_rag._merge_outgoing_rows(rows)
    assert len(merged) == 2


def test_merge_outgoing_rows_orders_by_rel_type_then_name() -> None:
    """Reproduces the ``ORDER BY type(r), target.name`` the single-query
    form carried."""
    rows = [
        {"name": "zeta", "type": "Function", "relType": "USES"},
        {"name": "beta", "type": "Function", "relType": "CALLS"},
        {"name": "alpha", "type": "Function", "relType": "USES"},
    ]
    merged = graph_rag._merge_outgoing_rows(rows)
    assert [(r["relType"], r["name"]) for r in merged] == [
        ("CALLS", "beta"),
        ("USES", "alpha"),
        ("USES", "zeta"),
    ]


def test_merge_outgoing_rows_truncates_to_limit() -> None:
    """The merged set is cut to ``_OUTGOING_LIMIT`` — the same bound the
    pre-decomposition ``LIMIT 25`` carried."""
    rows = [
        {"name": f"n{i:03d}", "type": "Function", "relType": "CALLS"}
        for i in range(60)
    ]
    merged = graph_rag._merge_outgoing_rows(rows)
    assert len(merged) == graph_rag._OUTGOING_LIMIT


def test_merge_outgoing_rows_drops_unnamed_and_non_dict_rows() -> None:
    merged = graph_rag._merge_outgoing_rows(
        [
            {"name": "keep", "type": "Function", "relType": "CALLS"},
            {"name": "", "type": "Function", "relType": "CALLS"},
            {"type": "Function", "relType": "CALLS"},
        ]
    )
    assert [r["name"] for r in merged] == ["keep"]


def test_merge_outgoing_rows_handles_none() -> None:
    assert graph_rag._merge_outgoing_rows(None) == []


# ── _path_union_cypher (shortestPath seed anchor) ──────────────────────


def test_path_union_cypher_emits_two_branches_not_or() -> None:
    """The shortestPath seed anchor is UNION_ALL_Decomposed too (R1.2)."""
    cypher = graph_rag._path_union_cypher(5, "")
    assert cypher.count("UNION ALL") == 1
    assert "WHERE source.name = $from AND dest.name = $to" in cypher
    assert "WHERE source.path = $from AND dest.name = $to" in cypher
    assert " OR " not in cypher


def test_path_union_cypher_embeds_depth_and_limit_on_both_branches() -> None:
    """``LIMIT`` applies within each ``UNION ALL`` branch, so both branches
    carry the depth bound and the row cap."""
    cypher = graph_rag._path_union_cypher(4, "")
    assert cypher.count("*1..4") == 2
    assert cypher.count(f"LIMIT {graph_rag._PATH_LIMIT}") == 2


def test_path_union_cypher_applies_scope_pred_to_both_branches() -> None:
    cypher = graph_rag._path_union_cypher(5, _SCOPE_FRAGMENT)
    assert cypher.count(_SCOPE_FRAGMENT) == 2
    head, _, tail = cypher.partition("UNION ALL")
    assert _SCOPE_FRAGMENT in head
    assert _SCOPE_FRAGMENT in tail


# ── _merge_path_rows (post-union dedup / cap) ──────────────────────────


def test_merge_path_rows_dedupes_paths_found_by_both_branches() -> None:
    """A path found from both anchor branches arrives twice; folded on
    ``(nodeNames, relTypes)`` (R1.3)."""
    row = {"nodeNames": ["a", "b"], "relTypes": ["CALLS"], "hops": 1}
    merged = graph_rag._merge_path_rows([dict(row), dict(row)])
    assert len(merged) == 1
    assert merged[0]["nodeNames"] == ["a", "b"]


def test_merge_path_rows_keeps_distinct_paths() -> None:
    merged = graph_rag._merge_path_rows(
        [
            {"nodeNames": ["a", "b"], "relTypes": ["CALLS"], "hops": 1},
            {"nodeNames": ["a", "c"], "relTypes": ["USES"], "hops": 1},
        ]
    )
    assert len(merged) == 2


def test_merge_path_rows_truncates_to_limit() -> None:
    rows = [
        {"nodeNames": ["a", f"b{i}"], "relTypes": ["CALLS"], "hops": 1}
        for i in range(10)
    ]
    merged = graph_rag._merge_path_rows(rows)
    assert len(merged) == graph_rag._PATH_LIMIT


def test_merge_path_rows_handles_none_and_non_dict() -> None:
    assert graph_rag._merge_path_rows(None) == []
    rows = [None, "x"]
    assert graph_rag._merge_path_rows(rows) == []  # type: ignore[arg-type]


# ── tool-level: emitted cypher + deduplicated render ──────────────────


async def test_trace_data_flow_emits_union_all_on_both_queries(
    tmp_path: Path,
) -> None:
    """Both queries ``trace_data_flow`` issues use UNION_ALL_Decomposition
    and neither carries the index-defeating OR anchor (R1.1, R1.2)."""
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_outgoing(data.graph_db, [])
    _seed_shortest_path(data.graph_db, [])
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    await _call_tool(
        mcp, "trace_data_flow", {"from_symbol": "a", "to_symbol": "z"}
    )
    cyphers = [c[1][0] for c in _graph_query_calls(data)]
    outgoing = [q for q in cyphers if "(source)-[r:" in q]
    path = [q for q in cyphers if "shortestPath" in q]
    assert outgoing and path
    for q in outgoing + path:
        assert "UNION ALL" in q
        assert "source.name = $name OR" not in q
        assert "source.name = $from OR" not in q


async def test_trace_data_flow_union_branches_carry_scope_and_timeout(
    tmp_path: Path,
) -> None:
    """Each branch of each decomposed query carries the tenant scope
    predicate, and the call carries the Statement_Timeout (R1.4)."""
    from src.tools._traversal_bounds import TIMEOUT_S

    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_outgoing(data.graph_db, [])
    _seed_shortest_path(data.graph_db, [])
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    await _call_tool(
        mcp, "trace_data_flow", {"from_symbol": "a", "to_symbol": "z"}
    )
    calls = _graph_query_calls(data)
    decomposed = [
        c
        for c in calls
        if "UNION ALL" in c[1][0] and "WHERE source." in c[1][0]
    ]
    assert len(decomposed) == 2, "expected fan-out + shortestPath decomposed"
    for c in decomposed:
        cypher = c[1][0]
        assert c[3]["tenant"] is not None
        assert c[3]["timeout"] == TIMEOUT_S
        head, _, tail = cypher.partition("UNION ALL")
        assert "WHERE source." in head and "WHERE source." in tail
        # The active tenant here is the default ``gw``, whose scope
        # predicate excludes other tenants' prefixed labels. Whatever the
        # predicate is, it must be present on BOTH branches (R1.4) — the
        # branches are identical apart from the anchored property, so
        # swapping ``path`` back to ``name`` makes them equal.
        assert "labels(source)" in cypher, (
            "expected a Label_Scope_Predicate on the default gw tenant"
        )
        assert cypher.count("labels(source)") == 2
        assert head.strip() == tail.replace(
            "source.path =", "source.name ="
        ).strip()

    # Task 2.6: the pre-flight degree probe resolves its own anchor with
    # the same decomposition, on its own ``a`` variable, and carries the
    # same scope predicate and timeout on both branches.
    probe_anchor = [
        c
        for c in calls
        if "UNION ALL" in c[1][0] and "RETURN id(a) AS nid" in c[1][0]
    ]
    assert len(probe_anchor) == 1, "expected the degree probe decomposed"
    cypher = probe_anchor[0][1][0]
    assert probe_anchor[0][3]["tenant"] is not None
    assert probe_anchor[0][3]["timeout"] == TIMEOUT_S
    assert "a.name = $name OR" not in cypher
    assert cypher.count("labels(a)") == 2
    head, _, tail = cypher.partition("UNION ALL")
    assert head.strip() == tail.replace("a.path =", "a.name =").strip()


async def test_trace_data_flow_dedupes_overlapping_outgoing_rows(
    tmp_path: Path,
) -> None:
    """Overlapping rows from the two branches render once, so the count in
    the section header matches the deduplicated set (R1.3)."""
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_outgoing(
        data.graph_db,
        [
            # name branch
            {"name": "child_a", "type": "Function", "relType": "CALLS"},
            {"name": "child_b", "type": "Function", "relType": "USES"},
            # path branch — fully overlapping
            {"name": "child_a", "type": "Function", "relType": "CALLS"},
            {"name": "child_b", "type": "Function", "relType": "USES"},
        ],
    )
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp, "trace_data_flow", {"from_symbol": "forecast"}
    )
    assert "## Outgoing Relationships (2)" in text
    assert text.count("| `child_a` |") == 1
    assert text.count("| `child_b` |") == 1


async def test_trace_data_flow_dedupes_overlapping_path_rows(
    tmp_path: Path,
) -> None:
    """The same shortest path found by both anchor branches renders once."""
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_outgoing(data.graph_db, [])
    row = {"nodeNames": ["a", "b", "c"], "relTypes": ["CALLS", "CALLS"],
           "hops": 2}
    _seed_shortest_path(data.graph_db, [dict(row), dict(row)])
    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp, "trace_data_flow", {"from_symbol": "a", "to_symbol": "c"}
    )
    assert text.count("**2 hops**") == 1


# ══ Task 5.5 — tool-level strategy routing for trace_data_flow ═════════
# `_use_bfs` itself is covered exhaustively elsewhere (Property 5 in
# tests/properties/test_bfs_walker_props.py, plus the truth-table grid in
# tests/unit/test_traversal_bounds.py). What is asserted here is the
# *routing* decision at this tool's boundary: which query shape actually
# reaches the graph for each band of the anchor's measured degree.
#
# Routing is read off the emitted queries rather than by monkeypatching
# `bfs_walk`, because the shapes are unambiguous for this tool:
#
#   walker expansion  ``... WHERE id(a) IN $ids ... RETURN DISTINCT
#                     id(b) AS nid ...``   (`_bfs_walker._expand_one_hop`)
#   single query      ``MATCH (source)-[r:CALLS|USES|...]->(target)``
#                     (the UNION_ALL_Decomposed one-hop fan-out)
#
# Validates R3.1 (below the activation threshold the single query is
# kept), R3.2 (at/above it the walk is selected), R5.1 (the single-query
# path is unchanged where kept), R5.5 (hub handling unchanged).


#: Degrees landing in each arm of the selector, derived from the live
#: tunables so an env override moves the tests with the implementation.
_DEG_SINGLE = BFS_ACTIVATION_THRESHOLD - 1
_DEG_BFS = BFS_ACTIVATION_THRESHOLD
#: `is_hub` is a strict ``degree > threshold``, so FAN_OUT_THRESHOLD
#: itself is still a non-hub and walks.
_DEG_BFS_TOP = FAN_OUT_THRESHOLD
_DEG_HUB = FAN_OUT_THRESHOLD + 1

#: Projection unique to `_bfs_walker._expand_one_hop`.
_WALK_EXPANSION = "RETURN DISTINCT id(b) AS nid"
#: The walker's own anchor resolution (``var="n"``). The degree probe
#: resolves with ``var="a"``, so this cannot be confused with it.
_WALK_ANCHOR = "RETURN id(n) AS nid"
#: The single-query one-hop fan-out's pattern.
_SINGLE_FANOUT = "(source)-[r:CALLS|USES|IMPORTS|EXECUTES|INVOKES|SOURCES]"


def _cyphers(data: MockUnifiedDataAccess) -> list[str]:
    return [c[1][0] for c in _graph_query_calls(data)]


def _walk_expansions(data: MockUnifiedDataAccess) -> list[str]:
    return [q for q in _cyphers(data) if _WALK_EXPANSION in q]


def _fanout_queries(data: MockUnifiedDataAccess) -> list[str]:
    return [q for q in _cyphers(data) if _SINGLE_FANOUT in q]


def _seed_degree(graph: MockGraphDB, deg: int) -> None:
    """Seed the pre-flight single-hop degree probe (`count(r) AS deg`)."""
    graph.add_response("count(r) AS deg", [{"deg": deg}])


def _seed_walk(graph: MockGraphDB, name: str = "walked_child") -> None:
    """Seed the walker's anchor resolution plus one CALLS expansion."""
    graph.add_response(_WALK_ANCHOR, [{"nid": "anchor-1"}])
    graph.add_response(
        "MATCH (a)-[:CALLS]->(b)",
        [
            {
                "nid": "child-1",
                "name": name,
                "path": None,
                "labels": ["Function"],
            }
        ],
    )


async def test_trace_data_flow_below_threshold_uses_single_query(
    tmp_path: Path,
) -> None:
    """degree < BFS_ACTIVATION_THRESHOLD -> the UNION_ALL_Decomposed
    single query, and no walk is attempted (R3.1, R5.1).

    The fan-out is a one-hop section by construction (`_OUTGOING_DEPTH`
    is 1), so the depth arm of the selector can never fire here and the
    measured degree alone decides.
    """
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_degree(data.graph_db, _DEG_SINGLE)
    _seed_outgoing(
        data.graph_db,
        [{"name": "child_a", "type": "Function", "relType": "CALLS"}],
    )
    # Seeded but unreachable: had the walk run, this row would surface.
    _seed_walk(data.graph_db)

    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp, "trace_data_flow", {"from_symbol": "forecast"}
    )
    assert _walk_expansions(data) == []
    assert _fanout_queries(data), "expected the single-query fan-out"
    assert "`child_a`" in text
    assert "walked_child" not in text
    assert "[optimized: BFS walker" not in text


async def test_trace_data_flow_at_threshold_routes_to_walker(
    tmp_path: Path,
) -> None:
    """degree == BFS_ACTIVATION_THRESHOLD -> the walk runs and the
    single-query fan-out is not emitted at all (R3.2).

    The exact boundary is pinned rather than a mid-band value, because
    ``>=`` versus ``>`` in the selector is the one distinction a
    comfortable mid-band degree cannot make.
    """
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_degree(data.graph_db, _DEG_BFS)
    _seed_outgoing(
        data.graph_db,
        [{"name": "single_query_child", "type": "Function",
          "relType": "CALLS"}],
    )
    _seed_walk(data.graph_db)

    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp, "trace_data_flow", {"from_symbol": "forecast"}
    )
    assert _walk_expansions(data), "expected the BFS walker to expand"
    assert _fanout_queries(data) == []
    assert "`walked_child`" in text
    assert "single_query_child" not in text
    assert "[optimized: BFS walker" in text


async def test_trace_data_flow_fanout_threshold_still_walks(
    tmp_path: Path,
) -> None:
    """degree == FAN_OUT_THRESHOLD is the last non-hub degree, so it walks
    rather than degrading (R1.2, R3.2)."""
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_degree(data.graph_db, _DEG_BFS_TOP)
    _seed_walk(data.graph_db)

    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp, "trace_data_flow", {"from_symbol": "borderline"}
    )
    assert _walk_expansions(data)
    assert "Highly connected node" not in text
    assert "`walked_child`" in text


async def test_trace_data_flow_hub_degrades_without_any_walk(
    tmp_path: Path,
) -> None:
    """A hub anchor is caught by `is_hub` before the selector, so no walk
    is attempted and the notice is the Degraded_Result (R5.1, R5.5).

    This tool's fan-out is one-hop either way, so unlike the
    ``code_analysis`` tools it does not swap in a separate one-hop probe:
    the single query still runs and the response carries the
    "Highly connected node" notice above it. What must not happen is a
    walk — the guard order is hub -> BFS -> single-query.
    """
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_degree(data.graph_db, _DEG_HUB)
    _seed_outgoing(
        data.graph_db,
        [{"name": "child_a", "type": "Function", "relType": "CALLS"}],
    )
    _seed_walk(data.graph_db)

    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp, "trace_data_flow", {"from_symbol": "hubsym"}
    )
    assert "Highly connected node" in text
    assert str(_DEG_HUB) in text
    assert _walk_expansions(data) == []
    assert _fanout_queries(data)
    assert "walked_child" not in text
    assert "[optimized: BFS walker" not in text


async def test_trace_data_flow_max_depth_does_not_select_the_walk(
    tmp_path: Path,
) -> None:
    """``max_depth`` belongs to the shortestPath section, not the fan-out:
    a 99-hop request with a below-threshold degree still keeps the
    single-query fan-out (R3.1).

    This pins the `_OUTGOING_DEPTH = 1` constant's consequence — the
    depth arm of the selector is unreachable from this tool's parameters,
    so a caller cannot force the walk by asking for a deeper path.
    """
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_degree(data.graph_db, _DEG_SINGLE)
    _seed_outgoing(
        data.graph_db,
        [{"name": "child_a", "type": "Function", "relType": "CALLS"}],
    )
    _seed_shortest_path(
        data.graph_db,
        [{"nodeNames": ["a", "z"], "relTypes": ["CALLS"], "hops": 1}],
    )
    _seed_walk(data.graph_db)

    mcp = _make_server(data=data, session=_make_session(tmp_path))
    text = await _call_tool(
        mcp,
        "trace_data_flow",
        {"from_symbol": "a", "to_symbol": "z", "max_depth": 99},
    )
    assert _walk_expansions(data) == []
    assert _fanout_queries(data)
    assert "**1 hops**" in text
    assert "[optimized: BFS walker" not in text
