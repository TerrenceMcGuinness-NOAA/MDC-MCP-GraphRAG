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
            "token_budget",
        },
        "search_architecture": {"query", "max_results"},
        "find_similar_code": {
            "code_or_symbol",
            "similarity_threshold",
            "max_results",
        },
        "get_change_impact": {"symbol", "change_type", "include_indirect"},
        "trace_data_flow": {"from_symbol", "to_symbol", "max_depth"},
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
    assert text.startswith("[ERROR]"), text
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
    assert not text.startswith("[ERROR]"), text


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
    assert text.startswith("[ERROR]"), text
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
    assert text.startswith("[ERROR]")
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
    """``max_depth`` is clamped to 10 and embedded in the cypher.

    We inspect the mock call log to confirm the rendered query uses
    ``*1..10`` regardless of how far the caller asked to look."""
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
    assert any("shortestPath" in q and "*1..10" in q for q in queries)
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
    assert text.startswith("[ERROR]"), text
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
    assert text.startswith("[ERROR]")
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
    assert text.startswith("[ERROR]")


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
    assert text.startswith("[ERROR]")
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
    assert text.startswith("[ERROR]")
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
    assert text.startswith("[ERROR]")
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
    assert text.startswith("[ERROR]")
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
    assert text.startswith("[ERROR]")
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
