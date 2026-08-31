"""Unit tests for :mod:`src.tools.code_analysis` (Task 9.3, Phase B6).

Covers tool-schema parity with Node.js (parameter names, defaults,
required flags, enum values), degraded-mode behaviour for all 6 tools,
tool-layer markdown rendering against ``MockUnifiedDataAccess`` with
canned graph rows, ``token_budget`` clamping, ``cross_language``
BRIDGE_DECAY_OVERRIDE routing, ``languages`` filter on
``trace_full_execution_chain``, and ``max_depth`` bounds behaviour.

No live AWS calls. The graph fixture is :class:`MockGraphDB` from
``tests/conftest.py``; see its ``add_response`` fragment-matching
docstring for how cypher queries are routed to canned row lists.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastmcp import FastMCP

from src.graphrag import BRIDGE_DECAY_OVERRIDE, GGSRTraversal
from src.tools import code_analysis
from src.tools._traversal_bounds import (
    BFS_ACTIVATION_THRESHOLD,
    FAN_OUT_THRESHOLD,
)
from tests.conftest import MockGraphDB, MockUnifiedDataAccess, MockVectorDB

pytestmark = pytest.mark.unit


# ── helpers ────────────────────────────────────────────────────────────


def _make_server(*, data: Any = None) -> FastMCP:
    mcp = FastMCP("mdc-mcp-rag-test", version="1.0.0")
    code_analysis.register(mcp, data=data)
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


def _seed_symbols(graph: MockGraphDB, rows: list[dict[str, Any]]) -> None:
    graph.add_response("DEFINES|CONTAINS", rows)


def _seed_imports(graph: MockGraphDB, modules: list[str]) -> None:
    graph.add_response(
        "IMPORTS|USES|SOURCES|INVOKES",
        [{"moduleName": m} for m in modules],
    )


def _seed_importers(graph: MockGraphDB, files: list[str]) -> None:
    # Importers use a slightly different cypher than imports — it
    # queries ``(src)-[...]->(t)`` and returns ``filePath``. The
    # fragment matcher picks the longest substring match, so we seed
    # with the filePath column alias to disambiguate.
    graph.add_response(
        "RETURN DISTINCT coalesce(src.path, src.name) AS filePath",
        [{"filePath": f} for f in files],
    )


def _seed_entity_type(graph: MockGraphDB, labels: list[str]) -> None:
    graph.add_response(
        "RETURN labels(n) AS labels LIMIT 1",
        [{"labels": labels}],
    )


def _seed_call_chain(graph: MockGraphDB, edges: str, rows: list[dict[str, Any]]) -> None:
    """Seed the variable-length call-chain query (``CALLS*1..N`` or
    ``SOURCES|INVOKES|EXECUTES*1..N``) with ``rows``.

    ``edges`` is the fragment unique to the query (e.g. ``CALLS*1..``)
    so the mock's longest-prefix matcher routes correctly.
    """
    graph.add_response(edges, rows)


def _seed_callers(graph: MockGraphDB, rows: list[dict[str, Any]]) -> None:
    graph.add_response("(caller)-[:CALLS]->(f)", rows)


# ── registration parity ───────────────────────────────────────────────


async def test_register_exposes_six_tools_with_matching_names() -> None:
    mcp = _make_server()
    tools = await mcp.list_tools(run_middleware=False)
    names = sorted(t.name for t in tools)
    assert names == sorted(
        [
            "analyze_code_structure",
            "find_dependencies",
            "trace_execution_path",
            "find_callers_callees",
            "trace_full_execution_chain",
            "find_env_dependencies",
        ]
    )


async def test_tool_schemas_match_nodejs_parameter_names() -> None:
    mcp = _make_server()
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    expected = {
        "analyze_code_structure": {
            "file_path",
            "include_dependencies",
            "depth",
            "token_budget", "tenant_id"},
        "find_dependencies": {"target", "direction", "max_depth", "token_budget", "tenant_id"},
        "trace_execution_path": {
            "function_name",
            "file_path",
            "max_depth",
            "include_callers",
            "include_weights",
            "token_budget", "tenant_id"},
        "find_callers_callees": {
            "function_name",
            "file_path",
            "include_source",
            "token_budget",
            "cross_language", "tenant_id"},
        "trace_full_execution_chain": {
            "start",
            "direction",
            "max_depth",
            "languages", "tenant_id"},
        "find_env_dependencies": {
            "variable_name",
            "show_exports",
            "limit",
            "token_budget", "tenant_id"},
    }
    for name, params in expected.items():
        props = set(tools[name].parameters.get("properties", {}).keys())
        assert props == params, f"{name}: expected {params}, got {props}"


async def test_required_fields_match_nodejs() -> None:
    mcp = _make_server()
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    required = {
        "analyze_code_structure": {"file_path"},
        "find_dependencies": {"target"},
        "trace_execution_path": {"function_name"},
        "find_callers_callees": {"function_name"},
        "trace_full_execution_chain": {"start"},
        "find_env_dependencies": {"variable_name"},
    }
    for name, want in required.items():
        got = set(tools[name].parameters.get("required") or [])
        assert got == want, f"{name}: required {got} vs {want}"


async def test_defaults_match_nodejs() -> None:
    mcp = _make_server()
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    checks: dict[str, dict[str, Any]] = {
        "analyze_code_structure": {
            "include_dependencies": True,
            "depth": 2,
            "token_budget": 4000,
        },
        "find_dependencies": {
            "direction": "both",
            "max_depth": 3,
            "token_budget": 4000,
        },
        "trace_execution_path": {
            "max_depth": 3,
            "include_callers": False,
            "include_weights": True,
            "token_budget": 4000,
        },
        "find_callers_callees": {
            "include_source": False,
            "token_budget": 4000,
            "cross_language": False,
        },
        "trace_full_execution_chain": {"direction": "forward", "max_depth": 5},
        "find_env_dependencies": {
            "show_exports": True,
            "limit": 50,
            "token_budget": 4000,
        },
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

    direction_schema = (
        tools["find_dependencies"].parameters["properties"]["direction"]
    )
    assert _enum(direction_schema) == {"upstream", "downstream", "both"}

    chain_dir_schema = (
        tools["trace_full_execution_chain"].parameters["properties"]["direction"]
    )
    assert _enum(chain_dir_schema) == {"forward", "reverse", "both"}

    languages_schema = (
        tools["trace_full_execution_chain"].parameters["properties"]["languages"]
    )
    # The Literal list wraps ``items.enum`` inside an anyOf for the
    # nullable case. Unwrap one level.
    items_enum: set[str] = set()
    for branch in languages_schema.get("anyOf", [languages_schema]):
        items = branch.get("items")
        if items and "enum" in items:
            items_enum.update(items["enum"])
    assert items_enum == {"shell", "fortran", "python"}


# ── degraded mode ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "tool_name,arguments",
    [
        ("analyze_code_structure", {"file_path": "x.py"}),
        ("find_dependencies", {"target": "x.py"}),
        ("trace_execution_path", {"function_name": "foo"}),
        ("find_callers_callees", {"function_name": "foo"}),
        ("trace_full_execution_chain", {"start": "JGLOBAL_FORECAST"}),
        ("find_env_dependencies", {"variable_name": "HOMEgfs"}),
    ],
)
async def test_all_tools_return_error_when_data_missing(
    tool_name: str, arguments: dict[str, Any]
) -> None:
    """All 6 tools return ``[ERROR] ... Graph database unavailable ...``
    when booted without a data-access layer (Requirement 1.7)."""
    mcp = _make_server(data=None)
    text = await _call_tool(mcp, tool_name, arguments)
    assert "[ERROR]" in text, text
    assert "Graph database unavailable" in text


@pytest.mark.parametrize(
    "tool_name,arguments,missing_key",
    [
        ("analyze_code_structure", {"file_path": "  "}, "file_path"),
        ("find_dependencies", {"target": ""}, "target"),
        ("trace_execution_path", {"function_name": " "}, "function_name"),
        ("find_callers_callees", {"function_name": ""}, "function_name"),
        ("trace_full_execution_chain", {"start": ""}, "start"),
        ("find_env_dependencies", {"variable_name": " "}, "variable_name"),
    ],
)
async def test_tools_reject_empty_primary_argument(
    tool_name: str, arguments: dict[str, Any], missing_key: str
) -> None:
    """Whitespace-only required fields are rejected with an explicit
    ``[ERROR]`` message — mirrors the Node.js ``!input.trim()`` guard."""
    data = MockUnifiedDataAccess()
    mcp = _make_server(data=data)
    text = await _call_tool(mcp, tool_name, arguments)
    assert "[ERROR]" in text
    assert missing_key in text


# ── analyze_code_structure ────────────────────────────────────────────


async def test_analyze_code_structure_renders_overview_and_dependencies() -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_symbols(
        data.graph_db,
        [
            {
                "name": "run_forecast",
                "labels": ["Function"],
                "docstring": "Top-level forecast entry.",
                "lineNumber": 42,
            },
            {
                "name": "ForecastRunner",
                "labels": ["Class"],
                "docstring": "Coordinates UFS run.",
                "lineNumber": 5,
            },
        ],
    )
    _seed_imports(data.graph_db, ["os", "pathlib"])
    _seed_importers(data.graph_db, ["jobs/JGLOBAL_FORECAST"])

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "analyze_code_structure",
        {"file_path": "scripts/exglobal_forecast.py"},
    )
    assert "# Code Structure Analysis: scripts/exglobal_forecast.py" in text
    assert "## Overview" in text
    assert "**Functions:** 1" in text
    assert "**Classes:** 1" in text
    assert "## Functions" in text
    assert "### `run_forecast`" in text
    assert "*Line 42*" in text
    assert "## Classes" in text
    assert "### `ForecastRunner`" in text
    assert "## Dependencies" in text
    assert "### Imports (2)" in text
    assert "- `os`" in text
    assert "### Imported By (1)" in text
    assert "- `jobs/JGLOBAL_FORECAST`" in text
    assert "## Related Queries" in text


async def test_analyze_code_structure_reports_file_not_found() -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    # No symbols seeded — all queries return [].
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "analyze_code_structure",
        {"file_path": "nonexistent.py"},
    )
    assert "File not found: nonexistent.py" in text
    assert 'search_documentation query:"nonexistent.py"' in text


async def test_analyze_code_structure_skips_dependencies_when_disabled() -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_symbols(
        data.graph_db,
        [{"name": "foo", "labels": ["Function"]}],
    )
    _seed_imports(data.graph_db, ["must_not_appear"])

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "analyze_code_structure",
        {"file_path": "x.py", "include_dependencies": False},
    )
    assert "## Dependencies" not in text
    assert "must_not_appear" not in text


async def test_analyze_code_structure_clamps_depth_to_bounds() -> None:
    """The ``depth`` arg is clamped to 1..3 (matches Node.js schema)."""
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_symbols(data.graph_db, [{"name": "f", "labels": ["Function"]}])

    mcp = _make_server(data=data)
    # depth=0 and depth=99 should both be silently clamped; no crash
    # and both produce a well-formed Overview section.
    for depth_in in (0, 99):
        text = await _call_tool(
            mcp, "analyze_code_structure", {"file_path": "x.py", "depth": depth_in}
        )
        assert "## Overview" in text


# ── find_dependencies ────────────────────────────────────────────────


async def test_find_dependencies_renders_both_directions() -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_imports(data.graph_db, ["os"])
    _seed_importers(data.graph_db, ["jobs/JGLOBAL_FORECAST"])

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "find_dependencies", {"target": "scripts/x.py"}
    )
    assert "# Dependency Analysis: scripts/x.py" in text
    assert "## Upstream Dependencies (What scripts/x.py imports)" in text
    assert "- `os`" in text
    assert "## Downstream Dependencies (What imports scripts/x.py)" in text
    assert "- `jobs/JGLOBAL_FORECAST`" in text
    assert "## Circular Dependency Check" in text


async def test_find_dependencies_respects_direction_upstream_only() -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_imports(data.graph_db, ["os"])
    _seed_importers(data.graph_db, ["must_not_appear"])

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "find_dependencies",
        {"target": "x.py", "direction": "upstream"},
    )
    assert "Upstream Dependencies" in text
    assert "Downstream Dependencies" not in text
    assert "must_not_appear" not in text


async def test_find_dependencies_skips_circular_check_when_depth_one() -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_imports(data.graph_db, [])
    _seed_importers(data.graph_db, [])

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "find_dependencies", {"target": "x.py", "max_depth": 1}
    )
    assert "Circular Dependency Check" not in text


async def test_find_dependencies_clamps_max_depth_to_five() -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)

    mcp = _make_server(data=data)
    # max_depth=42 should be clamped; no crash, section still emitted.
    text = await _call_tool(
        mcp,
        "find_dependencies",
        {"target": "x.py", "max_depth": 42},
    )
    assert "Circular Dependency Check" in text


# ── trace_execution_path ─────────────────────────────────────────────


async def test_trace_execution_path_reports_entity_not_found() -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "trace_execution_path", {"function_name": "nope"}
    )
    assert 'Entity "nope" not found' in text


async def test_trace_execution_path_renders_call_chain_for_function() -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["Function"])
    _seed_call_chain(
        data.graph_db,
        "CALLS*1..",
        [
            {"callee": "alpha", "file": "a.py", "depth": 1},
            {"callee": "beta", "file": "b.py", "depth": 2},
            {"callee": "gamma", "file": "c.py", "depth": 2},
        ],
    )

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "trace_execution_path", {"function_name": "foo"}
    )
    assert "# Execution Path Trace: foo" in text
    assert "*Entity type: Function*" in text
    assert "## Call Chain (What foo calls)" in text
    # Numeric prefix indicates ordered rendering; depth controls indent.
    assert "1. `alpha`" in text
    assert "  2. `beta`" in text
    assert "(in a.py)" in text


async def test_trace_execution_path_includes_callers_when_requested() -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["Function"])
    _seed_call_chain(
        data.graph_db,
        "CALLS*1..",
        [{"callee": "alpha", "depth": 1}],
    )
    _seed_callers(
        data.graph_db,
        [{"name": "caller_one", "file": "x.py"}],
    )

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "trace_execution_path",
        {"function_name": "foo", "include_callers": True},
    )
    assert "## Callers (What calls foo)" in text
    assert "- `caller_one`" in text


async def test_trace_execution_path_omits_ggsr_when_weights_false() -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["Function"])
    _seed_call_chain(
        data.graph_db,
        "CALLS*1..",
        [{"callee": "alpha", "depth": 1}],
    )

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "trace_execution_path",
        {"function_name": "foo", "include_weights": False},
    )
    assert "## GGSR" not in text


async def test_trace_execution_path_picks_shell_edges_for_script() -> None:
    """Shell-language entities follow SOURCES/INVOKES/EXECUTES — not CALLS."""
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["ShellScript"])
    _seed_call_chain(
        data.graph_db,
        "SOURCES|INVOKES|EXECUTES*1..",
        [
            {"callee": "exglobal_forecast.sh", "file": "scripts/exglobal_forecast.sh", "depth": 1}
        ],
    )

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "trace_execution_path",
        {"function_name": "JGLOBAL_FORECAST"},
    )
    assert "*Entity type: Shell Script*" in text
    assert "exglobal_forecast.sh" in text
    assert "script invocations" in text


async def test_trace_execution_path_clamps_max_depth_to_five() -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["Function"])
    # Seed an empty call-chain response keyed on the clamped depth
    # string (``CALLS*1..5``) so the invocation produces the "leaf"
    # fallback without crashing.
    data.graph_db.add_response("CALLS*1..5", [])

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "trace_execution_path",
        {"function_name": "foo", "max_depth": 99, "include_weights": False},
    )
    assert "# Execution Path Trace: foo" in text
    # No crash, leaf fallback emitted.
    assert "*No " in text or "## Call Chain" in text


# ── find_callers_callees ─────────────────────────────────────────────


async def test_find_callers_callees_renders_fan_in_fan_out() -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["Function"])
    _seed_callers(
        data.graph_db,
        [{"name": "caller_one"}, {"name": "caller_two"}],
    )
    _seed_call_chain(
        data.graph_db,
        "CALLS*1..",
        [{"callee": "callee_one"}, {"callee": "callee_two"}],
    )

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "find_callers_callees", {"function_name": "foo"}
    )
    assert "# Function Analysis: foo" in text
    assert "## Callers (2)" in text
    assert "- **`caller_one`**" in text
    assert "- **`caller_two`**" in text
    assert "## Callees" in text
    assert "- **`callee_one`**" in text
    assert "## Complexity Analysis" in text
    assert "**Fan-in:** 2" in text
    assert "**Fan-out:** 2" in text
    assert "**Complexity Score:** 4" in text


async def test_find_callers_callees_flags_high_complexity() -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["Function"])
    _seed_callers(
        data.graph_db,
        [{"name": f"c{i}"} for i in range(8)],
    )
    _seed_call_chain(
        data.graph_db,
        "CALLS*1..",
        [{"callee": f"x{i}"} for i in range(8)],
    )
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "find_callers_callees", {"function_name": "foo"}
    )
    assert "**Complexity Score:** 64" in text
    assert "High complexity" in text


async def test_find_callers_callees_emits_cross_language_section_when_flag_true() -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["ShellScript"])
    _seed_callers(data.graph_db, [])
    _seed_call_chain(
        data.graph_db,
        "SOURCES|INVOKES|EXECUTES*1..",
        [{"callee": "exgfs.sh", "depth": 1}],
    )
    # The cross-language section requests 5 hops, which exceeds the BFS
    # activation depth of 3, so the strategy selector always routes it to
    # the BFS_Walker (R3.2) — there is no single-query variable-length
    # pattern to seed here. The walker resolves the anchor, then expands
    # one relationship type per query, so the canned rows are keyed on the
    # per-type expansion patterns instead of the six-type edge union.
    # Rendering is shared by both strategies; BFS-path coverage of the
    # callers/callees sections lands in task 5.5.
    data.graph_db.add_response("RETURN id(n) AS nid", [{"nid": "anchor-1"}])
    data.graph_db.add_response(
        "MATCH (a)-[:EXECUTES]->(b)",
        [
            {
                "nid": "gsi-1",
                "name": "gsi",
                "path": None,
                "labels": ["FortranProgram"],
            }
        ],
    )
    data.graph_db.add_response(
        "MATCH (a)-[:DEFINES]->(b)",
        [
            {
                "nid": "pygfs-1",
                "name": "pygfs.task.gfs_forecast",
                "path": None,
                "labels": ["PythonModule"],
            }
        ],
    )
    # Seed-node lookup for cross_language_nodes helper.
    data.graph_db.add_response(
        "RETURN n.name AS name, labels(n) AS labels LIMIT 1",
        [{"name": "exglobal_forecast.sh", "labels": ["ShellScript"]}],
    )

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "find_callers_callees",
        {"function_name": "exglobal_forecast.sh", "cross_language": True},
    )
    assert "## Cross-Language Callees" in text
    assert "### Fortran Layer" in text
    assert "`gsi`" in text
    assert "### Python Layer" in text


async def test_find_callers_callees_omits_cross_language_by_default() -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["Function"])
    _seed_callers(data.graph_db, [])
    _seed_call_chain(data.graph_db, "CALLS*1..", [])

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "find_callers_callees", {"function_name": "foo"}
    )
    assert "Cross-Language Callees" not in text


async def test_find_callers_callees_response_carries_bfs_header() -> None:
    """R8.4 at the tool boundary: the walk that produced the response is
    labelled, on line 2, after the title.

    The cross-language section requests 5 hops, which exceeds the BFS
    activation depth of 3, so switching it on routes this response through
    the BFS_Walker (R3.2) — and the indicator is the only thing in the
    response that says so. Asserted alongside the negative case below,
    because R8.4 is a *pair* of claims: present when a walk ran, absent
    when it did not.
    """
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["ShellScript"])
    _seed_callers(data.graph_db, [])
    _seed_call_chain(
        data.graph_db,
        "SOURCES|INVOKES|EXECUTES*1..",
        [{"callee": "exgfs.sh", "depth": 1}],
    )
    data.graph_db.add_response("RETURN id(n) AS nid", [{"nid": "anchor-1"}])
    data.graph_db.add_response(
        "MATCH (a)-[:EXECUTES]->(b)",
        [
            {
                "nid": "gsi-1",
                "name": "gsi",
                "path": None,
                "labels": ["FortranProgram"],
            }
        ],
    )
    data.graph_db.add_response(
        "RETURN n.name AS name, labels(n) AS labels LIMIT 1",
        [{"name": "exglobal_forecast.sh", "labels": ["ShellScript"]}],
    )

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "find_callers_callees",
        {"function_name": "exglobal_forecast.sh", "cross_language": True},
    )
    # The indicator sits immediately after the markdown title, which is
    # itself preceded by the tenant attribution block, so the title is
    # located rather than assumed to be line 0.
    lines = text.splitlines()
    title = next(i for i, ln in enumerate(lines) if ln.startswith("# "))
    assert lines[title + 1].startswith("[optimized: BFS walker, ")
    assert lines[title + 1].endswith("]")
    assert lines[title + 2] == ""
    # Anti-vacuity: the walk really did contribute the rendered content.
    assert "`gsi`" in text


async def test_find_callers_callees_single_query_has_no_bfs_header() -> None:
    """The other half of R8.4: with ``cross_language`` off and a
    low-degree anchor no walk runs, so the response carries no indicator
    and is byte-identical to its pre-8.2 shape (R5.1)."""
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["Function"])
    _seed_callers(data.graph_db, [{"name": "caller_one"}])
    _seed_call_chain(
        data.graph_db, "CALLS*1..", [{"callee": "callee_one"}]
    )

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "find_callers_callees", {"function_name": "foo"}
    )
    assert "[optimized: BFS walker" not in text
    lines = text.splitlines()
    title = next(i for i, ln in enumerate(lines) if ln.startswith("# "))
    assert lines[title] == "# Function Analysis: foo"
    assert lines[title + 1] == ""


async def test_trace_full_execution_chain_response_carries_bfs_header(
) -> None:
    """R8.4 at the tool boundary for the full chain.

    This tool has no single-query arm to distinguish from: its
    Cross_Language_Edge_Set is walked at depth 5, which exceeds the BFS
    activation depth unconditionally (R3.2), so every response it renders
    is walker-produced and carries the indicator.
    """
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    data.graph_db.add_response(
        "RETURN n.name AS name, labels(n) AS labels LIMIT 1",
        [{"name": "exglobal_forecast.sh", "labels": ["ShellScript"]}],
    )
    data.graph_db.add_response("RETURN id(n) AS nid", [{"nid": "anchor-1"}])
    data.graph_db.add_response(
        "MATCH (a)-[:EXECUTES]->(b)",
        [
            {
                "nid": "gsi-1",
                "name": "gsi",
                "path": None,
                "labels": ["FortranProgram"],
            }
        ],
    )

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "trace_full_execution_chain",
        {"start": "exglobal_forecast.sh"},
    )
    lines = text.splitlines()
    title = lines.index("# Full Execution Chain: exglobal_forecast.sh")
    assert lines[title + 1].startswith("[optimized: BFS walker, ")
    assert lines[title + 1].endswith("]")
    assert lines[title + 2] == ""
    assert "`gsi`" in text


async def test_cross_language_rescore_applies_bridge_decay() -> None:
    """When ``apply_bridge_decay=True``, EXECUTES/INVOKES hops use the
    ``BRIDGE_DECAY_OVERRIDE`` factor instead of the base ``HOP_DECAY``.

    Asserted directly on :pyfunc:`code_analysis._apply_bridge_decay`
    so the math is covered without depending on end-to-end rendering."""
    from src.graphrag.ggsr_traversal import GGSRScoredResult, HOP_DECAY

    # A hop-1 EXECUTES result: the base engine would have scored
    # ``weight * HOP_DECAY^1`` — bridge decay re-scores to
    # ``weight * BRIDGE_DECAY_OVERRIDE^1`` which is strictly higher.
    r = GGSRScoredResult(
        name="gsi",
        relationship="EXECUTES",
        hop_distance=1,
        weight=1.0,
        score=1.0 * (HOP_DECAY ** 1),
    )
    out = code_analysis._apply_bridge_decay([r])
    assert len(out) == 1
    assert out[0].score == pytest.approx(1.0 * BRIDGE_DECAY_OVERRIDE)
    assert out[0].score > 1.0 * (HOP_DECAY ** 1)


async def test_cross_language_rescore_leaves_regular_edges_untouched() -> None:
    """Only EXECUTES/INVOKES hops get the bridge override; CALLS / USES
    / IMPORTS keep the :data:`HOP_DECAY` scoring."""
    from src.graphrag.ggsr_traversal import GGSRScoredResult, HOP_DECAY

    base_score = 1.0 * (HOP_DECAY ** 1)
    r = GGSRScoredResult(
        name="helper",
        relationship="CALLS",
        hop_distance=1,
        weight=1.0,
        score=base_score,
    )
    out = code_analysis._apply_bridge_decay([r])
    assert out[0].score == pytest.approx(base_score)


# ── trace_full_execution_chain ───────────────────────────────────────


async def test_trace_full_execution_chain_reports_empty_when_no_nodes() -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "trace_full_execution_chain", {"start": "nowhere"}
    )
    assert 'No execution chain found for "nowhere"' in text


async def test_trace_full_execution_chain_renders_forward_tree() -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    data.graph_db.add_response(
        "RETURN n.name AS name, labels(n) AS labels LIMIT 1",
        [{"name": "JGLOBAL_FORECAST", "labels": ["ShellScript"]}],
    )
    data.graph_db.add_response(
        "SOURCES|INVOKES|EXECUTES|CALLS|USES|DEFINES",
        [
            {
                "name": "exglobal_forecast.sh",
                "labels": ["ShellScript"],
                "hop": 1,
                "relType": "SOURCES",
            },
            {
                "name": "gsi",
                "labels": ["FortranProgram"],
                "hop": 2,
                "relType": "EXECUTES",
            },
        ],
    )
    mcp = _make_server(data=data)
    # ``max_depth=3`` keeps this on the single-query variable-length
    # path: the default (5) exceeds the BFS activation depth of 3, so it
    # would route to the BFS_Walker instead (R3.2). Rendering is shared
    # by both strategies; BFS-path coverage lands in task 5.5.
    text = await _call_tool(
        mcp,
        "trace_full_execution_chain",
        {"start": "JGLOBAL_FORECAST", "max_depth": 3},
    )
    assert "# Full Execution Chain: JGLOBAL_FORECAST" in text
    assert "### Forward Direction" in text
    assert "[Shell] `JGLOBAL_FORECAST`" in text
    assert "[Fortran] `gsi`" in text
    # Bridge marker for EXECUTES hop (hop > 0).
    assert "═══" in text
    assert "### Statistics" in text
    assert "Languages traversed:" in text


async def test_trace_full_execution_chain_languages_filter() -> None:
    """``languages`` filter drops nodes whose language isn't whitelisted."""
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    data.graph_db.add_response(
        "RETURN n.name AS name, labels(n) AS labels LIMIT 1",
        [{"name": "JGLOBAL_FORECAST", "labels": ["ShellScript"]}],
    )
    data.graph_db.add_response(
        "SOURCES|INVOKES|EXECUTES|CALLS|USES|DEFINES",
        [
            {
                "name": "exglobal_forecast.sh",
                "labels": ["ShellScript"],
                "hop": 1,
                "relType": "SOURCES",
            },
            {
                "name": "pygfs.task.gfs_forecast",
                "labels": ["PythonModule"],
                "hop": 2,
                "relType": "DEFINES",
            },
            {
                "name": "gsi",
                "labels": ["FortranProgram"],
                "hop": 3,
                "relType": "EXECUTES",
            },
        ],
    )
    mcp = _make_server(data=data)
    # ``max_depth=3`` pins the single-query path (see the rendering test
    # above); the ``languages`` filter runs after either strategy.
    text = await _call_tool(
        mcp,
        "trace_full_execution_chain",
        {
            "start": "JGLOBAL_FORECAST",
            "languages": ["fortran"],
            "max_depth": 3,
        },
    )
    assert "`gsi`" in text
    # Shell / Python nodes should be filtered out entirely.
    assert "exglobal_forecast.sh" not in text
    assert "pygfs.task.gfs_forecast" not in text


async def test_trace_full_execution_chain_clamps_max_depth_to_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Asking for 99 hops is silently clamped to FULL_CHAIN_DEPTH (5).

    R2.2 reduces the cross-language full-chain ceiling from the historical
    10 to a conservative 5, and the historical ``*1..10`` / ``*1..99``
    pattern must never be emitted.

    A 99-hop request exceeds the BFS activation depth of 3, so the
    strategy selector routes it to the BFS_Walker rather than a
    variable-length pattern; the clamp is therefore asserted on the depth
    budget handed to the walker (R3.2).
    """
    from src.tools._traversal_bounds import FULL_CHAIN_DEPTH

    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    data.graph_db.add_response(
        "RETURN n.name AS name, labels(n) AS labels LIMIT 1",
        [{"name": "X", "labels": ["ShellScript"]}],
    )
    # Track any variable-length pattern that reaches the graph.
    captured: list[str] = []
    original_query = data.graph_db.query

    async def _recording_query(cypher: str, params: dict[str, Any] | None = None, **kwargs):
        if "*1.." in cypher:
            captured.append(cypher)
        return await original_query(cypher, params, **kwargs)

    data.graph_db.query = _recording_query  # type: ignore[method-assign]

    # Capture the depth budget the walker was given.
    walk_depths: list[int] = []
    original_walk = code_analysis.bfs_walk

    async def _recording_walk(graph_db: Any, **kwargs: Any):
        walk_depths.append(kwargs["max_depth"])
        return await original_walk(graph_db, **kwargs)

    monkeypatch.setattr(code_analysis, "bfs_walk", _recording_walk)

    mcp = _make_server(data=data)
    await _call_tool(
        mcp,
        "trace_full_execution_chain",
        {"start": "X", "max_depth": 99},
    )
    # The clamp applied: the walker got the ceiling, not 99 or 10.
    assert walk_depths == [FULL_CHAIN_DEPTH]
    assert not any("*1..10" in c for c in captured)
    assert not any("*1..99" in c for c in captured)


async def test_trace_full_execution_chain_direction_both_runs_two_queries() -> None:
    """``direction='both'`` triggers forward *and* reverse traversal."""
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    data.graph_db.add_response(
        "RETURN n.name AS name, labels(n) AS labels LIMIT 1",
        [{"name": "gsi", "labels": ["FortranProgram"]}],
    )
    data.graph_db.add_response(
        "SOURCES|INVOKES|EXECUTES|CALLS|USES|DEFINES",
        [
            {
                "name": "neighbour",
                "labels": ["FortranSubroutine"],
                "hop": 1,
                "relType": "CALLS",
            },
        ],
    )
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "trace_full_execution_chain",
        {"start": "gsi", "direction": "both"},
    )
    assert "### Forward Direction" in text
    assert "### Reverse Direction" in text


# ── find_env_dependencies ────────────────────────────────────────────


async def test_find_env_dependencies_renders_summary_block() -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    data.graph_db.add_response(
        "DEPENDS_ON_ENV",
        [
            {
                "script": "exglobal_forecast.sh",
                "path": "scripts/exglobal_forecast.sh",
                "type": "ex-script",
            },
            {
                "script": "forecast_postdet.sh",
                "path": "ush/forecast_postdet.sh",
                "type": "ush",
            },
        ],
    )
    data.graph_db.add_response(
        "EXPORTS",
        [
            {
                "script": "config.base",
                "path": "parm/config/gfs/config.base",
                "type": "config",
                "line": 10,
                "value": "/home/gfs",
            }
        ],
    )
    data.graph_db.add_response(
        "RETURN e.is_ee2_standard",
        [{"isEE2": True, "isHome": False, "firstSeen": "parm/config/gfs/config.base"}],
    )

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "find_env_dependencies",
        {"variable_name": "HOMEgfs"},
    )
    assert "# Environment Variable Analysis: HOMEgfs" in text
    assert "## Scripts Depending on `HOMEgfs` (2)" in text
    assert "### ex-script (1)" in text
    assert "- **`exglobal_forecast.sh`** - `scripts/exglobal_forecast.sh`" in text
    assert "### ush (1)" in text
    assert "## Scripts Exporting `HOMEgfs` (1)" in text
    assert "(line 10) = `/home/gfs`" in text
    assert "## Summary" in text
    assert "EE2 Standard" in text
    assert "Total dependencies:** 2" in text
    assert "Impact level:** LOW" in text


async def test_find_env_dependencies_suppresses_exports_when_flag_off() -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    data.graph_db.add_response("DEPENDS_ON_ENV", [])
    data.graph_db.add_response(
        "EXPORTS",
        [{"script": "should_not_appear", "path": "x.sh"}],
    )

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "find_env_dependencies",
        {"variable_name": "HOMEgfs", "show_exports": False},
    )
    assert "Scripts Exporting" not in text
    assert "should_not_appear" not in text


async def test_find_env_dependencies_clamps_limit_between_one_and_500() -> None:
    """``limit`` is clamped to [1, 500]. The clamped value is embedded
    in the cypher query so we inspect it via the mock call log.

    Parity note: Node.js uses ``parseInt(limit, 10) || 50`` so a
    ``limit=0`` request falls back to the default 50 (0 is falsy) —
    the Python port mirrors this quirk. The actual clamping only
    bites when ``limit`` is a truthy out-of-range value (negative or
    above 500)."""
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    data.graph_db.add_response("DEPENDS_ON_ENV", [])

    mcp = _make_server(data=data)
    # Way above upper bound → 500.
    await _call_tool(
        mcp,
        "find_env_dependencies",
        {"variable_name": "X", "limit": 99_999},
    )
    queries = [c[1][0] for c in data.graph_db.call_log if c[0] == "query"]
    assert any("LIMIT 500" in q for q in queries)
    assert not any("LIMIT 99999" in q for q in queries)

    # Negative (truthy) → clamped to lower bound 1.
    data.graph_db.call_log.clear()
    await _call_tool(
        mcp,
        "find_env_dependencies",
        {"variable_name": "X", "limit": -5},
    )
    queries = [c[1][0] for c in data.graph_db.call_log if c[0] == "query"]
    assert any(" LIMIT 1\n" in q or q.rstrip().endswith("LIMIT 1") for q in queries)

    # Zero → Node.js falsy-fallback to default 50 (parity).
    data.graph_db.call_log.clear()
    await _call_tool(
        mcp,
        "find_env_dependencies",
        {"variable_name": "X", "limit": 0},
    )
    queries = [c[1][0] for c in data.graph_db.call_log if c[0] == "query"]
    assert any("LIMIT 50" in q for q in queries)


async def test_find_env_dependencies_flags_high_impact_variable() -> None:
    """>50 dependents → HIGH impact + wide-use warning."""
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    data.graph_db.add_response(
        "DEPENDS_ON_ENV",
        [
            {"script": f"s{i}.sh", "path": f"ush/s{i}.sh", "type": "ush"}
            for i in range(60)
        ],
    )

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "find_env_dependencies",
        {"variable_name": "DATAROOT"},
    )
    assert "Impact level:** HIGH" in text
    assert "widely used" in text


# ── token_budget clamping ────────────────────────────────────────────


async def test_token_budget_zero_suppresses_ggsr_section() -> None:
    """``token_budget=0`` produces an empty GGSR trim — no section is
    rendered (matches the ``token_budget <= 0 → []`` short-circuit in
    :pyfunc:`code_analysis._render_ggsr_section`)."""
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["Function"])
    _seed_call_chain(
        data.graph_db,
        "CALLS*1..",
        [{"callee": "alpha", "depth": 1}],
    )

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "trace_execution_path",
        {"function_name": "foo", "token_budget": 0},
    )
    assert "## GGSR" not in text


async def test_token_budget_negative_is_clamped_to_zero() -> None:
    """Negative budgets are silently clamped to 0 rather than raising."""
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["Function"])
    _seed_call_chain(data.graph_db, "CALLS*1..", [])

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "trace_execution_path",
        {"function_name": "foo", "token_budget": -500},
    )
    # No crash and no GGSR section.
    assert "# Execution Path Trace: foo" in text
    assert "## GGSR" not in text


async def test_render_ggsr_section_trims_to_token_budget(
    mock_graph_db: MockGraphDB,
) -> None:
    """Direct exercise of :pyfunc:`code_analysis._render_ggsr_section`
    confirms the GGSR engine is wired in and its budget-trimming is
    applied before markdown rendering (guards the B3→B6 integration
    seam). With a 15-token budget and 20-token rows the renderer
    returns zero rows and no header."""
    _seed_empty_graph(mock_graph_db)
    # Seed 1-hop neighbour query with several candidates.
    long_name = "x" * 40  # estimate_row_tokens → 15 + ceil(40/4) = 25
    mock_graph_db.add_response(
        "MATCH (n)-[r]-(hop1)",
        [
            {
                "source": "foo",
                "relationship": "CALLS",
                "name": long_name,
                "labels": ["Function"],
                "path": "x.py",
                "hop_distance": 1,
            }
        ],
    )
    lines = await code_analysis._render_ggsr_section(
        mock_graph_db,
        entity="foo",
        token_budget=10,
        hops=1,
        heading="GGSR Test",
    )
    # Budget of 10 is below one row's 25-ish tokens → nothing kept.
    assert lines == []


async def test_render_ggsr_section_emits_header_and_table_rows(
    mock_graph_db: MockGraphDB,
) -> None:
    _seed_empty_graph(mock_graph_db)
    mock_graph_db.add_response(
        "MATCH (n)-[r]-(hop1)",
        [
            {
                "source": "foo",
                "relationship": "CALLS",
                "name": "alpha",
                "labels": ["Function"],
                "path": "a.py",
                "hop_distance": 1,
            }
        ],
    )
    lines = await code_analysis._render_ggsr_section(
        mock_graph_db,
        entity="foo",
        token_budget=4000,
        hops=1,
        heading="GGSR Test",
    )
    assert any("## GGSR Test" in line for line in lines)
    assert any("| `alpha` | CALLS |" in line for line in lines)


# ── graph error propagation ──────────────────────────────────────────


async def test_analyze_code_structure_handles_graph_error_gracefully() -> None:
    data = MockUnifiedDataAccess()
    data.graph_db.raise_on_query = RuntimeError("neptune unreachable")
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "analyze_code_structure", {"file_path": "x.py"}
    )
    assert "[ERROR]" in text
    assert "neptune unreachable" in text


async def test_find_env_dependencies_handles_graph_error_gracefully() -> None:
    data = MockUnifiedDataAccess()
    data.graph_db.raise_on_query = RuntimeError("timeout")
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "find_env_dependencies", {"variable_name": "HOMEgfs"}
    )
    assert "[ERROR]" in text
    assert "timeout" in text


# ── helpers / direct unit tests ──────────────────────────────────────


def test_label_to_language_maps_known_prefixes() -> None:
    assert code_analysis._label_to_language(["PythonFunction"]) == "python"
    assert code_analysis._label_to_language(["FortranSubroutine"]) == "fortran"
    assert code_analysis._label_to_language(["ShellScript"]) == "shell"
    assert code_analysis._label_to_language(["RocotoTask"]) == "shell"
    assert code_analysis._label_to_language(["JJob"]) == "shell"
    assert code_analysis._label_to_language(["File"]) == "other"
    assert code_analysis._label_to_language([]) == "other"


def test_clamp_respects_bounds() -> None:
    assert code_analysis._clamp(5, 1, 10) == 5
    assert code_analysis._clamp(-3, 1, 10) == 1
    assert code_analysis._clamp(99, 1, 10) == 10
    assert code_analysis._clamp(1, 1, 1) == 1


# ── bounded-graph-traversal: degree gate / timeout / tenant scoping ─────
# (Wave 1, Task 3.1 — Validates R1.2, R3.4, R4.1, R4.4, R5.3, R7.5)


def _seed_degree(graph: MockGraphDB, deg: int) -> None:
    """Seed the single-hop degree probe (`count(r) AS deg`)."""
    graph.add_response("count(r) AS deg", [{"deg": deg}])


def _seed_one_hop(graph: MockGraphDB, rows: list[dict[str, Any]]) -> None:
    """Seed the one-hop Degraded_Result neighbor query."""
    graph.add_response(
        "RETURN DISTINCT x.name AS name, coalesce(x.filepath, x.path) AS file",
        rows,
    )


def _graph_cyphers(data: MockUnifiedDataAccess) -> list[str]:
    return [c[1][0] for c in data.graph_db.call_log if c[0] == "query"]


async def test_trace_execution_path_hub_returns_degraded_no_expansion() -> None:
    """A hub anchor (degree > threshold) returns a labeled, one-hop
    Degraded_Result and issues no variable-length expansion (R1.2, R4.1)."""
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["ShellScript"])
    _seed_degree(data.graph_db, 512)
    _seed_one_hop(
        data.graph_db,
        [{"name": "exglobal_forecast.sh", "file": "scripts/exglobal_forecast.sh"}],
    )

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "trace_execution_path", {"function_name": "JGLOBAL_FORECAST"}
    )
    # Successful Degraded_Result, not [ERROR].
    assert not text.startswith("[ERROR]")
    assert "Highly connected node" in text
    assert "512" in text          # measured degree
    assert "100" in text          # threshold
    assert "Direct Neighbors" in text
    assert "exglobal_forecast.sh" in text
    # No variable-length expansion query was ever issued.
    assert not any("*1.." in q for q in _graph_cyphers(data))


async def test_find_callers_callees_hub_returns_degraded_no_expansion() -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["Function"])
    _seed_degree(data.graph_db, 250)
    _seed_one_hop(data.graph_db, [{"name": "callee_a", "file": "a.py"}])

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "find_callers_callees", {"function_name": "hub_fn"}
    )
    assert not text.startswith("[ERROR]")
    assert "Highly connected node" in text
    assert "250" in text
    assert "callee_a" in text
    assert not any("*1.." in q for q in _graph_cyphers(data))


async def test_trace_full_execution_chain_hub_returns_degraded() -> None:
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_degree(data.graph_db, 999)
    _seed_one_hop(data.graph_db, [{"name": "exgfs.sh", "file": "scripts/exgfs.sh"}])

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "trace_full_execution_chain", {"start": "JGLOBAL_FORECAST"}
    )
    assert not text.startswith("[ERROR]")
    assert "Highly connected node" in text
    assert "999" in text
    assert "exgfs.sh" in text
    assert not any("*1.." in q for q in _graph_cyphers(data))


async def test_probe_failure_treated_as_hub_fail_safe() -> None:
    """If the degree probe errors, the anchor is treated as a hub (R1.5)."""
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["Function"])
    # Probe raises -> anchor_degree returns None -> hub.
    data.graph_db.add_raise("count(r) AS deg", RuntimeError("probe boom"))
    _seed_one_hop(data.graph_db, [{"name": "n1", "file": "n.py"}])

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "trace_execution_path", {"function_name": "foo"}
    )
    assert not text.startswith("[ERROR]")
    assert "Highly connected node" in text
    assert "could not be measured" in text
    assert not any("*1.." in q for q in _graph_cyphers(data))


async def test_non_hub_issues_bounded_expansion_with_cap_and_limit() -> None:
    """A non-hub anchor proceeds with the bounded ``*1..N`` expansion
    (capped depth + RESULT_LIMIT), preserving today's behaviour (R3.4)."""
    from src.tools._traversal_bounds import CALL_CHAIN_DEPTH, RESULT_LIMIT

    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["Function"])
    _seed_degree(data.graph_db, 3)  # under threshold -> non-hub
    _seed_call_chain(
        data.graph_db, "CALLS*1..", [{"callee": "alpha", "file": "a.py", "depth": 1}]
    )

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "trace_execution_path", {"function_name": "foo", "max_depth": 99}
    )
    assert "1. `alpha`" in text
    cyphers = _graph_cyphers(data)
    expected = f"CALLS*1..{CALL_CHAIN_DEPTH}"
    assert any(expected in q for q in cyphers)
    assert any(f"LIMIT {RESULT_LIMIT}" in q for q in cyphers)
    # Never an unbounded pattern: every ``*1..`` carries a digit bound.
    import re as _re
    for q in cyphers:
        for seg in q.split("*1..")[1:]:
            assert seg[:1].isdigit(), f"unbounded variable-length pattern in {q!r}"


async def test_expansion_timeout_returns_degraded_not_error() -> None:
    """A statement-timeout on the expansion yields a Degraded_Result with a
    timeout notice, never an unhandled exception or [ERROR] (R5.3)."""
    from src.data.neptune_adapter import NeptuneAdapterError

    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["Function"])
    _seed_degree(data.graph_db, 3)  # non-hub, so expansion is attempted
    _seed_one_hop(data.graph_db, [{"name": "neighbor_a", "file": "n.py"}])
    # The variable-length expansion times out.
    data.graph_db.add_raise(
        "CALLS*1..",
        NeptuneAdapterError("query exceeded 30.0s statement timeout"),
    )

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "trace_execution_path", {"function_name": "foo"}
    )
    assert not text.startswith("[ERROR]")
    assert "statement timeout" in text
    assert "neighbor_a" in text


async def test_all_emitted_queries_carry_tenant_and_expansion_carries_timeout() -> None:
    """Every emitted query carries tenant= (Property 5) and the
    variable-length expansion carries the statement-timeout (R5.2)."""
    from src.tools._traversal_bounds import TIMEOUT_S

    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["Function"])
    _seed_degree(data.graph_db, 2)
    _seed_call_chain(data.graph_db, "CALLS*1..", [{"callee": "a", "depth": 1}])

    mcp = _make_server(data=data)
    await _call_tool(
        mcp,
        "trace_execution_path",
        {"function_name": "foo", "include_weights": False},
    )
    query_calls = [c for c in data.graph_db.call_log if c[0] == "query"]
    assert query_calls, "expected at least one graph query"
    # tenant kwarg present (resolved gw tenant, not None) on every query.
    for c in query_calls:
        assert c[3]["tenant"] is not None
    # The degree probe and the variable-length expansion carry the timeout.
    probe = [c for c in query_calls if "count(r) AS deg" in c[1][0]]
    assert probe and probe[0][3]["timeout"] == TIMEOUT_S
    expansion = [c for c in query_calls if "CALLS*1.." in c[1][0]]
    assert expansion and expansion[0][3]["timeout"] == TIMEOUT_S


async def test_degree_probe_is_single_hop_never_variable_length() -> None:
    """The degree probe itself must never be a variable-length pattern
    (R1.4) — it is a plain single-hop count."""
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["Function"])
    _seed_degree(data.graph_db, 5)
    _seed_call_chain(data.graph_db, "CALLS*1..", [])

    mcp = _make_server(data=data)
    await _call_tool(mcp, "trace_execution_path", {"function_name": "foo"})
    probe = [
        c[1][0]
        for c in data.graph_db.call_log
        if c[0] == "query" and "count(r) AS deg" in c[1][0]
    ]
    assert probe
    assert "*" not in probe[0]


# ══ Task 2.5 — UNION ALL Decomposition of the _one_hop_neighbors anchor ═
# Validates R1.1 (UNION ALL replaces the OR anchor predicate), R1.2 (the
# decomposition is applied to this anchor), R1.3 (set-equivalent,
# deduplicated output), R1.4 (scope predicate + Statement_Timeout carried).


def _anchor_graph(rows: list[dict[str, Any]] | None = None) -> MockGraphDB:
    """Fresh mock with the one-hop neighbor query seeded with ``rows``."""
    graph = MockGraphDB()
    graph.canned_rows = []
    _seed_one_hop(graph, list(rows or []))
    return graph


def _sole_cypher(graph: MockGraphDB) -> str:
    cyphers = [c[1][0] for c in graph.call_log if c[0] == "query"]
    assert len(cyphers) == 1, f"expected exactly one query, got {len(cyphers)}"
    return cyphers[0]


def _v17_catalog() -> Any:
    """Two-tenant catalog so a non-default label prefix is available."""
    from src.config.tenants import CatalogDefaults, Tenant, TenantCatalog

    gw = Tenant(
        tenant_id="gw",
        repo_ref="NOAA-EMC/global-workflow",
        branch="develop",
        index_prefix="",
        label_prefix="",
        workflow_subdir="global-workflow",
        lifecycle="production",
    )
    gw_v17 = Tenant(
        tenant_id="gw_v17",
        repo_ref="NOAA-EMC/global-workflow",
        branch="dev/gfs.v17",
        index_prefix="gw_v17_",
        label_prefix="GW_V17_",
        workflow_subdir="global-workflow-v17",
        lifecycle="staging",
    )
    return TenantCatalog(
        schema_version=1,
        defaults=CatalogDefaults(tenant_id="gw"),
        tenants=(gw, gw_v17),
    )


async def test_one_hop_neighbors_emits_union_all_not_or() -> None:
    """The anchor is matched by ``a.name`` on one branch and ``a.path`` on
    another, joined by ``UNION ALL`` — never the index-defeating
    disjunction (R1.1)."""
    graph = _anchor_graph([{"name": "n1", "file": "n.py"}])
    await code_analysis._one_hop_neighbors(graph, "setuprad", "CALLS")
    cypher = _sole_cypher(graph)
    assert cypher.count("UNION ALL") == 1
    assert "WHERE a.name = $name" in cypher
    assert "WHERE a.path = $name" in cypher
    assert " OR " not in cypher
    assert "a.name = $name OR a.path = $name" not in cypher


async def test_one_hop_repeats_pattern_and_limit_per_branch() -> None:
    """``LIMIT`` applies within each ``UNION ALL`` branch, so both branches
    carry the match pattern and the server-side row cap (R1.2)."""
    from src.tools._traversal_bounds import RESULT_LIMIT

    graph = _anchor_graph([])
    await code_analysis._one_hop_neighbors(graph, "setuprad", "CALLS|USES")
    cypher = _sole_cypher(graph)
    assert cypher.count("MATCH (a)-[r:CALLS|USES]->(x)") == 2
    assert cypher.count(f"LIMIT {RESULT_LIMIT}") == 2
    assert cypher.count("RETURN DISTINCT x.name AS name") == 2


async def test_one_hop_neighbors_reverse_direction_on_both_branches() -> None:
    """Direction is part of the shared pattern, so it is identical on both
    branches."""
    graph = _anchor_graph([])
    await code_analysis._one_hop_neighbors(
        graph, "setuprad", "CALLS", direction="reverse"
    )
    cypher = _sole_cypher(graph)
    assert cypher.count("MATCH (x)-[r:CALLS]->(a)") == 2
    assert "MATCH (a)-[r:CALLS]->(x)" not in cypher


async def test_one_hop_neighbors_branches_are_symmetric() -> None:
    """The two branches differ only in the anchored property — a compact
    way of asserting every other clause (pattern, scope, return, limit) is
    present on both (R1.4)."""
    graph = _anchor_graph([])
    await code_analysis._one_hop_neighbors(graph, "setuprad", "CALLS")
    head, sep, tail = _sole_cypher(graph).partition(" UNION ALL ")
    assert sep
    assert head == tail.replace("a.path = $name", "a.name = $name")


async def test_one_hop_neighbors_scopes_both_branches_for_v17_tenant() -> None:
    """A non-default tenant's Label_Scope_Predicate appears on both
    branches (R1.4, R4.4).

    Task 7.2 added a *second* predicate per branch — on the expanded
    neighbor ``x``, not just the anchor ``a`` (R4.2) — so the prefix now
    appears four times, twice per branch. Asserting per-variable counts
    instead of a bare total keeps the original "once per branch" intent
    legible and pins which variable each predicate scopes.
    """
    from src.tenancy.resolver import tenant_scope

    graph = _anchor_graph([])
    async with tenant_scope("gw_v17", _v17_catalog()):
        await code_analysis._one_hop_neighbors(graph, "setuprad", "CALLS")
    cypher = _sole_cypher(graph)
    assert cypher.count("labels(a)") == 2, "anchor scoped once per branch"
    assert cypher.count("labels(x)") == 2, "neighbor scoped once per branch"
    assert cypher.count("GW_V17_") == 4
    head, _, tail = cypher.partition("UNION ALL")
    for branch in (head, tail):
        assert "labels(a)" in branch and "labels(x)" in branch


async def test_one_hop_neighbors_dedupes_overlapping_branch_rows() -> None:
    """``UNION ALL`` does not dedupe, so an anchor matched by both ``name``
    and ``path`` contributes its neighbors twice; they are folded on
    ``(name, file)`` here, which is set-equivalent to the ``DISTINCT`` the
    ``OR`` form gave (R1.3)."""
    graph = _anchor_graph(
        [
            # name branch
            {"name": "alpha", "file": "a.py"},
            {"name": "beta", "file": "b.py"},
            # path branch — fully overlapping
            {"name": "alpha", "file": "a.py"},
            {"name": "beta", "file": "b.py"},
        ]
    )
    rows = await code_analysis._one_hop_neighbors(graph, "setuprad", "CALLS")
    assert [(r["name"], r["file"]) for r in rows] == [
        ("alpha", "a.py"),
        ("beta", "b.py"),
    ]


async def test_one_hop_neighbors_keeps_same_name_in_different_file() -> None:
    """The dedup key is ``(name, file)``, so a same-named symbol in another
    file is not a duplicate."""
    graph = _anchor_graph(
        [
            {"name": "alpha", "file": "a.py"},
            {"name": "alpha", "file": "other.py"},
        ]
    )
    rows = await code_analysis._one_hop_neighbors(graph, "setuprad", "CALLS")
    assert len(rows) == 2


async def test_one_hop_neighbors_recaps_merged_rows_at_result_limit() -> None:
    """Both branches can each return up to RESULT_LIMIT rows, so the cap is
    re-applied across the merged set (R1.3)."""
    from src.tools._traversal_bounds import RESULT_LIMIT

    graph = _anchor_graph(
        [
            {"name": f"n{i:04d}", "file": f"f{i}.py"}
            for i in range(RESULT_LIMIT * 2 + 5)
        ]
    )
    rows = await code_analysis._one_hop_neighbors(graph, "setuprad", "CALLS")
    assert len(rows) == RESULT_LIMIT


async def test_one_hop_neighbors_drops_unnamed_rows() -> None:
    graph = _anchor_graph(
        [
            {"name": "keep", "file": "k.py"},
            {"name": "", "file": "e.py"},
            {"name": None, "file": "n.py"},
            {"file": "missing.py"},
        ]
    )
    rows = await code_analysis._one_hop_neighbors(graph, "setuprad", "CALLS")
    assert [r["name"] for r in rows] == ["keep"]


async def test_one_hop_neighbors_passes_tenant_and_timeout() -> None:
    """The Statement_Timeout and tenant object are carried on the
    decomposed query exactly as before (R1.4)."""
    from src.tenancy.resolver import tenant_scope
    from src.tools._traversal_bounds import TIMEOUT_S

    graph = _anchor_graph([])
    async with tenant_scope("gw_v17", _v17_catalog()) as ctx:
        await code_analysis._one_hop_neighbors(graph, "setuprad", "CALLS")
    call = [c for c in graph.call_log if c[0] == "query"][0]
    assert call[2] == {"name": "setuprad"}
    assert call[3]["timeout"] == TIMEOUT_S
    assert call[3]["tenant"] is ctx.tenant


async def test_one_hop_neighbors_timeout_returns_empty_not_raise() -> None:
    """A statement-timeout still degrades to ``[]`` so the Degraded_Result
    render never raises (R4.4) — unchanged by the decomposition."""
    from src.data.neptune_adapter import NeptuneAdapterError

    graph = _anchor_graph([{"name": "n1", "file": "n.py"}])
    graph.add_raise(
        "UNION ALL",
        NeptuneAdapterError("query exceeded 30.0s statement timeout"),
    )
    assert await code_analysis._one_hop_neighbors(
        graph, "setuprad", "CALLS"
    ) == []


async def test_one_hop_neighbors_non_timeout_error_still_raises() -> None:
    """Only timeouts are swallowed; a real fault surfaces to the caller."""
    graph = _anchor_graph([])
    graph.add_raise("UNION ALL", RuntimeError("boom"))
    with pytest.raises(RuntimeError, match="boom"):
        await code_analysis._one_hop_neighbors(graph, "setuprad", "CALLS")


async def test_degraded_result_anchor_query_uses_union_all() -> None:
    """End-to-end through a Hub_Node Degraded_Result: the one-hop anchor
    query the tool emits is decomposed, and duplicated branch rows render
    once (R1.1, R1.3)."""
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["Function"])
    _seed_degree(data.graph_db, 512)
    _seed_one_hop(
        data.graph_db,
        [
            {"name": "callee_a", "file": "a.py"},
            {"name": "callee_a", "file": "a.py"},
        ],
    )

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "find_callers_callees", {"function_name": "hub_fn"}
    )
    assert not text.startswith("[ERROR]")
    one_hop = [
        q
        for q in _graph_cyphers(data)
        if "RETURN DISTINCT x.name AS name" in q
    ]
    assert one_hop
    for q in one_hop:
        assert "UNION ALL" in q
        assert "a.name = $name OR" not in q
    assert text.count("callee_a") == 1


# ══ Task 2.7 — UNION ALL Decomposition of the _cross_language_seed_row ══
# The hop-0 Anchor_Node lookup shared by both cross-language traversal
# strategies. Validates R1.1 (UNION ALL replaces the OR anchor
# predicate), R1.2 (applied to this anchor), R1.3 (set-equivalent, one
# seed row even when both branches match), R1.4 (scope predicate on both
# branches + Statement_Timeout carried).


_SEED_FRAGMENT = "RETURN n.name AS name, labels(n) AS labels LIMIT 1"


def _seed_row_graph(rows: list[dict[str, Any]] | None = None) -> MockGraphDB:
    """Fresh mock with the cross-language seed lookup seeded."""
    graph = MockGraphDB()
    graph.canned_rows = []
    graph.add_response(
        _SEED_FRAGMENT,
        [{"name": "exglobal_forecast.sh", "labels": ["ShellScript"]}]
        if rows is None
        else list(rows),
    )
    return graph


async def test_cross_language_seed_row_emits_union_all_not_or() -> None:
    """The seed anchor is matched by ``n.name`` on one branch and
    ``n.path`` on another, joined by ``UNION ALL`` — never the
    index-defeating disjunction (R1.1)."""
    graph = _seed_row_graph()
    await code_analysis._cross_language_seed_row(
        graph, "exglobal_forecast.sh", "forward"
    )
    cyphers = [c[1][0] for c in graph.call_log if c[0] == "query"]
    assert len(cyphers) == 1
    cypher = cyphers[0]
    assert cypher.count("UNION ALL") == 1
    assert "MATCH (n) WHERE n.name = $name" in cypher
    assert "MATCH (n) WHERE n.path = $name" in cypher
    assert " OR " not in cypher
    assert "n.name = $name OR n.path = $name" not in cypher


async def test_cross_language_seed_row_limits_each_branch() -> None:
    """``LIMIT 1`` sits inside each branch, so neither branch can return
    an unbounded row set (the pre-decomposition bound, per branch)."""
    graph = _seed_row_graph()
    await code_analysis._cross_language_seed_row(graph, "anchor", "forward")
    cypher = [c[1][0] for c in graph.call_log if c[0] == "query"][0]
    head, sep, tail = cypher.partition("UNION ALL")
    assert sep
    assert "LIMIT 1" in head
    assert "LIMIT 1" in tail
    assert cypher.count("LIMIT 1") == 2


async def test_cross_language_seed_row_branches_are_identical_but_property(
) -> None:
    """The two branches differ only in the anchored property, so the
    decomposition is set-equivalent to the ``OR`` form (R1.3)."""
    graph = _seed_row_graph()
    await code_analysis._cross_language_seed_row(graph, "anchor", "forward")
    cypher = [c[1][0] for c in graph.call_log if c[0] == "query"][0]
    head, _, tail = cypher.partition("UNION ALL")
    assert head.strip() == tail.replace("n.path =", "n.name =").strip()


async def test_cross_language_seed_row_dual_match_yields_one_seed() -> None:
    """A node whose ``name`` AND ``path`` both equal the anchor is
    returned by *both* branches, because ``UNION ALL`` does not dedupe.
    Exactly one hop-0 seed row must reach the caller — a doubled seed
    would render the anchor twice at the head of the chain (R1.3)."""
    graph = _seed_row_graph(
        [
            {"name": "exglobal_forecast.sh", "labels": ["ShellScript"]},
            {"name": "exglobal_forecast.sh", "labels": ["ShellScript"]},
        ]
    )
    rows = await code_analysis._cross_language_seed_row(
        graph, "exglobal_forecast.sh", "forward"
    )
    assert len(rows) == 1
    assert rows[0]["name"] == "exglobal_forecast.sh"
    assert rows[0]["hop"] == 0
    assert rows[0]["language"] == "shell"


async def test_cross_language_seed_row_prefers_the_name_branch() -> None:
    """With a match on each branch the ``name`` branch's row wins, which
    makes the seed deterministic where the ``OR`` form left the choice to
    the planner."""
    graph = _seed_row_graph(
        [
            {"name": "by_name", "labels": ["ShellScript"]},
            {"name": "by_path", "labels": ["FortranProgram"]},
        ]
    )
    rows = await code_analysis._cross_language_seed_row(
        graph, "anchor", "reverse"
    )
    assert len(rows) == 1
    assert rows[0]["name"] == "by_name"
    assert rows[0]["direction"] == "reverse"


async def test_cross_language_seed_row_no_match_returns_empty() -> None:
    """An unresolvable anchor still yields ``[]`` (unchanged contract)."""
    graph = _seed_row_graph([])
    assert await code_analysis._cross_language_seed_row(
        graph, "nowhere", "forward"
    ) == []


async def test_cross_language_seed_row_carries_timeout_and_params() -> None:
    """The Statement_Timeout is carried on the decomposed query and the
    anchor stays a bound parameter (R1.4)."""
    from src.tools._traversal_bounds import TIMEOUT_S

    graph = _seed_row_graph()
    await code_analysis._cross_language_seed_row(graph, "anchor", "forward")
    call = [c for c in graph.call_log if c[0] == "query"][0]
    assert call[2] == {"name": "anchor"}
    assert call[3]["timeout"] == TIMEOUT_S


async def test_cross_language_seed_row_scopes_both_branches_for_tenant(
) -> None:
    """A non-default tenant's Label_Scope_Predicate appears on *both*
    branches, so the seed lookup is scoped exactly as before (R1.4)."""
    from src.tenancy.resolver import tenant_scope

    catalog = _v17_catalog()
    graph = _seed_row_graph()
    async with tenant_scope("gw_v17", catalog):
        await code_analysis._cross_language_seed_row(
            graph, "anchor", "forward"
        )
    cypher = [c[1][0] for c in graph.call_log if c[0] == "query"][0]
    assert cypher.count("GW_V17_") == 2
    # ``labels(n)`` also appears in each branch's projection, so count the
    # predicate's own comprehension rather than the bare call.
    assert cypher.count("size([__lbl IN labels(n)") == 2
    head, _, tail = cypher.partition("UNION ALL")
    assert "GW_V17_" in head
    assert "GW_V17_" in tail


async def test_cross_language_seed_row_propagates_query_errors() -> None:
    """Errors are not absorbed here: the BFS fallback distinguishes a
    timed-out seed lookup from an empty one, so it must still raise."""
    graph = _seed_row_graph()
    graph.add_raise(_SEED_FRAGMENT, RuntimeError("boom"))
    with pytest.raises(RuntimeError, match="boom"):
        await code_analysis._cross_language_seed_row(
            graph, "anchor", "forward"
        )


async def test_trace_full_execution_chain_seed_lookup_is_decomposed(
) -> None:
    """End-to-end: the seed lookup the tool emits is decomposed, and a
    dual-match anchor renders once at hop 0 (R1.1, R1.2, R1.3)."""
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    data.graph_db.add_response(
        _SEED_FRAGMENT,
        [
            {"name": "JGLOBAL_FORECAST", "labels": ["ShellScript"]},
            {"name": "JGLOBAL_FORECAST", "labels": ["ShellScript"]},
        ],
    )
    data.graph_db.add_response(
        "SOURCES|INVOKES|EXECUTES|CALLS|USES|DEFINES",
        [
            {
                "name": "exglobal_forecast.sh",
                "labels": ["ShellScript"],
                "hop": 1,
                "relType": "SOURCES",
            }
        ],
    )
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "trace_full_execution_chain",
        {"start": "JGLOBAL_FORECAST", "max_depth": 3},
    )
    assert not text.startswith("[ERROR]")
    seed = [q for q in _graph_cyphers(data) if _SEED_FRAGMENT in q]
    assert seed
    for q in seed:
        assert "UNION ALL" in q
        assert "n.name = $name OR" not in q
    # One seed entry, not two, despite both branches matching.
    assert text.count("[Shell] `JGLOBAL_FORECAST`") == 1

# ══ Task 5.5 — tool-level strategy routing matrix ══════════════════════
# The pure selector `_use_bfs` is already covered exhaustively (Property 5
# in tests/properties/test_bfs_walker_props.py over the full int range,
# plus the truth-table grid in tests/unit/test_traversal_bounds.py), and
# the fallback chain end-to-end (Property 7). What neither reaches is the
# *routing* decision at the tool boundary: that a degree in the BFS band
# actually reaches `bfs_walk`, and that a hub degree still degrades,
# per-tool. That is what this section asserts.
#
# Routing is observed through the EMITTED QUERIES rather than by
# monkeypatching `bfs_walk`, because the query shapes are what reach
# Neptune and they are unambiguous here:
#
#   walker expansion  ``... WHERE id(a) IN $ids ... RETURN DISTINCT
#                     id(b) AS nid ...``      (`_expand_one_hop`)
#   single query      ``[:A|B|C*1..N]``       (variable-length pattern)
#   Degraded_Result   ``RETURN DISTINCT x.name AS name, coalesce(...)``
#                     plus the "Highly connected node" notice
#
# Validates R3.1 (low degree + shallow keeps the single query), R3.2
# (degree >= BFS_ACTIVATION_THRESHOLD, or depth > 3, selects the walk),
# R3.3 / R5.5 (single-query timeout -> BFS attempt -> Degraded_Result),
# R5.1 (the single-query path is unchanged where it is kept).


#: Degrees that land in each arm of the strategy selector. Derived from
#: the live tunables rather than hardcoded, so an env override
#: (MCP_BFS_ACTIVATION_THRESHOLD / MCP_TRAVERSAL_FANOUT_THRESHOLD) moves
#: these tests with the implementation (R6.1, R6.2).
_DEG_SINGLE = BFS_ACTIVATION_THRESHOLD - 1
_DEG_BFS = BFS_ACTIVATION_THRESHOLD
#: The last degree that is still NOT a hub: `is_hub` is a strict
#: ``degree > threshold``, so FAN_OUT_THRESHOLD itself walks.
_DEG_BFS_TOP = FAN_OUT_THRESHOLD
_DEG_HUB = FAN_OUT_THRESHOLD + 1

#: Projection unique to `_bfs_walker._expand_one_hop`.
_WALK_EXPANSION = "RETURN DISTINCT id(b) AS nid"
#: The walker's own anchor resolution (``var="n"``). The degree probe
#: resolves with ``var="a"``, so this fragment cannot be confused with it.
_WALK_ANCHOR = "RETURN id(n) AS nid"


def _walk_expansions(data: MockUnifiedDataAccess) -> list[str]:
    """Cyphers that only `_expand_one_hop` emits (i.e. the walk ran)."""
    return [q for q in _graph_cyphers(data) if _WALK_EXPANSION in q]


def _varlen_queries(data: MockUnifiedDataAccess) -> list[str]:
    """Cyphers carrying a variable-length pattern (the single query)."""
    return [q for q in _graph_cyphers(data) if "*1.." in q]


def _seed_walk_anchor(graph: MockGraphDB, nid: str = "anchor-1") -> None:
    """Seed the walker's UNION ALL anchor resolution with one id."""
    graph.add_response(_WALK_ANCHOR, [{"nid": nid}])


def _seed_expansion(
    graph: MockGraphDB,
    edge_type: str,
    rows: list[dict[str, Any]],
    direction: str = "forward",
) -> None:
    """Seed one per-type single-hop walker expansion with ``rows``."""
    if direction == "reverse":
        pattern = f"MATCH (b)-[:{edge_type}]->(a)"
    else:
        pattern = f"MATCH (a)-[:{edge_type}]->(b)"
    graph.add_response(pattern, rows)


def _node_row(nid: str, name: str, label: str) -> dict[str, Any]:
    """A walker expansion row in `_expand_one_hop`'s projection shape."""
    return {"nid": nid, "name": name, "path": None, "labels": [label]}


# ── find_callers_callees (one walk per direction, plus cross_language) ──


async def test_find_callers_callees_below_threshold_uses_single_query(
) -> None:
    """degree < BFS_ACTIVATION_THRESHOLD and depth 1 -> the historical
    single-query pair, and no walk is attempted (R3.1, R5.1).

    Both sections of this tool are direct-relationship sections, so
    `_CALLERS_CALLEES_DEPTH` is 1 and the depth arm of the selector can
    never fire here — the measured degree alone decides.
    """
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["Function"])
    _seed_degree(data.graph_db, _DEG_SINGLE)
    _seed_callers(data.graph_db, [{"name": "caller_one", "file": "c.py"}])
    _seed_call_chain(
        data.graph_db, "CALLS*1..", [{"callee": "callee_one", "depth": 1}]
    )
    # Seeded but unreachable: if the walk ran anyway, these rows would
    # surface and the assertions below would catch it.
    _seed_walk_anchor(data.graph_db)
    _seed_expansion(
        data.graph_db, "CALLS", [_node_row("x1", "walked_node", "Function")]
    )

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "find_callers_callees", {"function_name": "foo"}
    )
    assert _walk_expansions(data) == []
    assert _varlen_queries(data), "expected the single-query expansion"
    assert any("(caller)-[:CALLS]->(f)" in q for q in _graph_cyphers(data))
    assert "[optimized: BFS walker" not in text
    assert "`caller_one`" in text
    assert "`callee_one`" in text
    assert "walked_node" not in text


async def test_find_callers_callees_at_threshold_routes_to_walker() -> None:
    """degree == BFS_ACTIVATION_THRESHOLD -> the walk runs, and the
    single-query variable-length pattern is not emitted at all (R3.2).

    The exact boundary is pinned rather than a comfortable mid-band value,
    because ``>=`` versus ``>`` in the selector is the one thing a
    mid-band degree cannot distinguish.
    """
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["Function"])
    _seed_degree(data.graph_db, _DEG_BFS)
    _seed_walk_anchor(data.graph_db)
    _seed_expansion(
        data.graph_db,
        "CALLS",
        [_node_row("callee-1", "walked_callee", "Function")],
        "forward",
    )
    _seed_expansion(
        data.graph_db,
        "CALLS",
        [_node_row("caller-1", "walked_caller", "Function")],
        "reverse",
    )

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "find_callers_callees", {"function_name": "foo"}
    )
    assert _walk_expansions(data), "expected the BFS walker to expand"
    assert _varlen_queries(data) == []
    # Anti-vacuity: the walk's rows are what the response renders.
    assert "`walked_caller`" in text
    assert "`walked_callee`" in text
    assert "[optimized: BFS walker" in text


async def test_find_callers_callees_walks_once_per_direction_per_type(
) -> None:
    """The two sections are two walks — one per direction — over the same
    edge set, so a shell anchor's three-type set yields exactly six
    single-hop expansions and no interleaved pattern (R2.2, R3.2)."""
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["ShellScript"])
    _seed_degree(data.graph_db, _DEG_BFS)
    _seed_walk_anchor(data.graph_db)

    mcp = _make_server(data=data)
    await _call_tool(
        mcp,
        "find_callers_callees",
        {"function_name": "exglobal_forecast.sh"},
    )
    emitted = set()
    for q in _walk_expansions(data):
        for edge in ("SOURCES", "INVOKES", "EXECUTES"):
            if f"MATCH (a)-[:{edge}]->(b)" in q:
                emitted.add((edge, "forward"))
            if f"MATCH (b)-[:{edge}]->(a)" in q:
                emitted.add((edge, "reverse"))
    assert emitted == {
        (edge, direction)
        for edge in ("SOURCES", "INVOKES", "EXECUTES")
        for direction in ("forward", "reverse")
    }
    # Never the three types inside one variable-length pattern.
    assert _varlen_queries(data) == []


async def test_find_callers_callees_fanout_threshold_still_walks() -> None:
    """degree == FAN_OUT_THRESHOLD is the last non-hub degree, so it walks
    rather than degrading — `is_hub` is a strict ``>`` (R1.2, R3.2)."""
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["Function"])
    _seed_degree(data.graph_db, _DEG_BFS_TOP)
    _seed_walk_anchor(data.graph_db)
    _seed_expansion(
        data.graph_db,
        "CALLS",
        [_node_row("callee-1", "walked_callee", "Function")],
    )

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "find_callers_callees", {"function_name": "borderline"}
    )
    assert _walk_expansions(data)
    assert "Highly connected node" not in text
    assert "`walked_callee`" in text


async def test_find_callers_callees_hub_degrades_without_any_walk() -> None:
    """A hub degree short-circuits to the Degraded_Result *before* the
    strategy selector, so no walk is attempted (R3.1 ordering, R5.1).

    The guard order is hub -> BFS -> single-query: a node with more than
    FAN_OUT_THRESHOLD edges gets no walk, because the walker's per-type
    Fan_Out_Limit is FAN_OUT_THRESHOLD too and would still be expensive.
    """
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["Function"])
    _seed_degree(data.graph_db, _DEG_HUB)
    _seed_one_hop(data.graph_db, [{"name": "neighbor_a", "file": "n.py"}])
    _seed_walk_anchor(data.graph_db)
    _seed_expansion(
        data.graph_db, "CALLS", [_node_row("x1", "walked_node", "Function")]
    )

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "find_callers_callees", {"function_name": "hub_fn"}
    )
    assert "Highly connected node" in text
    assert str(_DEG_HUB) in text
    assert "`neighbor_a`" in text
    assert _walk_expansions(data) == []
    assert _varlen_queries(data) == []
    assert "[optimized: BFS walker" not in text
    assert "walked_node" not in text


async def test_find_callers_callees_cross_language_walks_below_threshold(
) -> None:
    """The ``cross_language`` section is a depth-5 expansion, so its own
    routing is depth-driven: it walks even when the anchor's degree keeps
    the callers/callees sections on the single query (R3.2).

    The two strategies therefore coexist inside one response. ``DEFINES``
    is in the Cross_Language_Edge_Set but not in a function anchor's
    call-chain edge set (``CALLS``), so a ``DEFINES`` expansion can only
    have come from the cross-language walk.
    """
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["Function"])
    _seed_degree(data.graph_db, _DEG_SINGLE)
    _seed_callers(data.graph_db, [])
    _seed_call_chain(data.graph_db, "CALLS*1..", [])
    _seed_walk_anchor(data.graph_db)
    data.graph_db.add_response(
        _SEED_FRAGMENT, [{"name": "foo", "labels": ["Function"]}]
    )
    _seed_expansion(
        data.graph_db,
        "DEFINES",
        [_node_row("py-1", "pygfs.task.gfs_forecast", "PythonModule")],
    )

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "find_callers_callees",
        {"function_name": "foo", "cross_language": True},
    )
    assert any("[:DEFINES]->(b)" in q for q in _walk_expansions(data))
    # The callers/callees sections kept their single queries.
    assert any("CALLS*1.." in q for q in _varlen_queries(data))
    assert "## Cross-Language Callees" in text
    assert "`pygfs.task.gfs_forecast`" in text


# ── trace_full_execution_chain (depth 5 -> always walker by default) ────


@pytest.mark.parametrize(
    "degree", [_DEG_SINGLE, _DEG_BFS, _DEG_BFS_TOP], ids=[
        "below-activation", "at-activation", "at-fanout-ceiling",
    ]
)
async def test_trace_full_chain_default_depth_always_walks(
    degree: int,
) -> None:
    """At the tool's default ``max_depth`` of 5 the depth arm of the
    selector fires unconditionally (5 > 3), so *every* non-hub degree is
    walker-produced — there is no single-query arm to compare against at
    this depth (R3.2).

    Parametrized across the whole non-hub range precisely to show the
    measured degree cannot change the outcome here.
    """
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_degree(data.graph_db, degree)
    _seed_walk_anchor(data.graph_db)
    data.graph_db.add_response(
        _SEED_FRAGMENT,
        [{"name": "exglobal_forecast.sh", "labels": ["ShellScript"]}],
    )
    _seed_expansion(
        data.graph_db,
        "EXECUTES",
        [_node_row("gsi-1", "gsi", "FortranProgram")],
    )

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "trace_full_execution_chain", {"start": "exglobal_forecast.sh"}
    )
    assert _walk_expansions(data)
    assert _varlen_queries(data) == []
    assert "`gsi`" in text
    assert "[optimized: BFS walker" in text


async def test_trace_full_chain_shallow_low_degree_keeps_single_query(
) -> None:
    """The one place this tool does keep the single query: an explicit
    ``max_depth`` of 3 with a below-threshold degree satisfies *both*
    negative arms of the selector (R3.1, R5.1)."""
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_degree(data.graph_db, _DEG_SINGLE)
    _seed_walk_anchor(data.graph_db)
    data.graph_db.add_response(
        _SEED_FRAGMENT,
        [{"name": "JGLOBAL_FORECAST", "labels": ["ShellScript"]}],
    )
    data.graph_db.add_response(
        "SOURCES|INVOKES|EXECUTES|CALLS|USES|DEFINES",
        [
            {
                "name": "exglobal_forecast.sh",
                "labels": ["ShellScript"],
                "hop": 1,
                "relType": "SOURCES",
            }
        ],
    )
    _seed_expansion(
        data.graph_db,
        "SOURCES",
        [_node_row("w-1", "walked_node", "ShellScript")],
    )

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "trace_full_execution_chain",
        {"start": "JGLOBAL_FORECAST", "max_depth": 3},
    )
    assert _walk_expansions(data) == []
    assert _varlen_queries(data)
    assert "`exglobal_forecast.sh`" in text
    assert "walked_node" not in text
    assert "[optimized: BFS walker" not in text


async def test_trace_full_chain_depth_four_walks_despite_low_degree(
) -> None:
    """One hop deeper flips the strategy with the degree held constant:
    ``max_depth=4`` exceeds the activation depth, so the walk is selected
    regardless of how low the measured degree is (R3.2).

    Paired with the ``max_depth=3`` case above, this isolates the depth
    arm — the two tests differ only in the requested depth.
    """
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_degree(data.graph_db, _DEG_SINGLE)
    _seed_walk_anchor(data.graph_db)
    data.graph_db.add_response(
        _SEED_FRAGMENT,
        [{"name": "JGLOBAL_FORECAST", "labels": ["ShellScript"]}],
    )
    data.graph_db.add_response(
        "SOURCES|INVOKES|EXECUTES|CALLS|USES|DEFINES",
        [
            {
                "name": "single_query_node",
                "labels": ["ShellScript"],
                "hop": 1,
                "relType": "SOURCES",
            }
        ],
    )
    _seed_expansion(
        data.graph_db,
        "SOURCES",
        [_node_row("w-1", "walked_node", "ShellScript")],
    )

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "trace_full_execution_chain",
        {"start": "JGLOBAL_FORECAST", "max_depth": 4},
    )
    assert _walk_expansions(data)
    assert _varlen_queries(data) == []
    assert "`walked_node`" in text
    assert "single_query_node" not in text


async def test_trace_full_chain_hub_degrades_without_any_walk() -> None:
    """A hub anchor degrades before the selector runs, so neither the
    walk nor the variable-length pattern is emitted — unchanged from
    ``bounded-graph-traversal`` [8.36.0] (R5.1)."""
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_degree(data.graph_db, _DEG_HUB)
    _seed_one_hop(data.graph_db, [{"name": "exgfs.sh", "file": "x.sh"}])
    _seed_walk_anchor(data.graph_db)
    _seed_expansion(
        data.graph_db,
        "EXECUTES",
        [_node_row("gsi-1", "walked_node", "FortranProgram")],
    )

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "trace_full_execution_chain", {"start": "JGLOBAL_FORECAST"}
    )
    assert "Highly connected node" in text
    assert str(_DEG_HUB) in text
    assert _walk_expansions(data) == []
    assert _varlen_queries(data) == []
    assert "walked_node" not in text


# ── trace_execution_path (walker reachable only via the fallback) ───────


async def test_trace_execution_path_bfs_band_degree_keeps_single_query(
) -> None:
    """This tool has no strategy selector: a degree squarely inside the
    BFS band still issues the single variable-length pattern (R5.1).

    Task 5.4 wired only the *timeout fallback* here, deliberately — the
    walk is the retry, not the first choice. Asserted so a future change
    that adds a selector to this site has to update the test that records
    the current contract.
    """
    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["Function"])
    _seed_degree(data.graph_db, _DEG_BFS)
    _seed_call_chain(
        data.graph_db, "CALLS*1..", [{"callee": "alpha", "depth": 1}]
    )
    _seed_walk_anchor(data.graph_db)
    _seed_expansion(
        data.graph_db, "CALLS", [_node_row("x1", "walked_node", "Function")]
    )

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "trace_execution_path",
        {"function_name": "foo", "include_weights": False},
    )
    assert _walk_expansions(data) == []
    assert any("CALLS*1.." in q for q in _varlen_queries(data))
    assert "`alpha`" in text
    assert "walked_node" not in text
    assert "[optimized: BFS walker" not in text


async def test_trace_execution_path_timeout_falls_back_to_walker() -> None:
    """Link 2 of the fallback chain, at the tool boundary: the single
    query times out, the walk is attempted, and its rows answer the
    request (R3.3, R5.5).

    Property 7 covers the chain's terminal shapes over injected timeouts;
    what is asserted here is that the middle link really is a *walk* — the
    per-type single-hop expansion query reaches the graph — and that the
    response is labelled as salvaged rather than presented as complete.
    """
    from src.data.neptune_adapter import NeptuneAdapterError

    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["Function"])
    _seed_degree(data.graph_db, _DEG_SINGLE)
    data.graph_db.add_raise(
        "CALLS*1..",
        NeptuneAdapterError("query exceeded 30.0s statement timeout"),
    )
    _seed_walk_anchor(data.graph_db)
    _seed_expansion(
        data.graph_db,
        "CALLS",
        [_node_row("s-1", "salvaged_callee", "Function")],
    )

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "trace_execution_path",
        {"function_name": "foo", "include_weights": False},
    )
    assert not text.startswith("[ERROR]")
    # The single query was attempted first, then the walk retried it.
    assert any("CALLS*1.." in q for q in _graph_cyphers(data))
    assert _walk_expansions(data)
    assert "`salvaged_callee`" in text
    assert "[optimized: BFS walker" in text
    # Not presented as an exhaustive answer.
    assert "statement timeout" in text
    # The Degraded_Result's one-hop probe was never needed.
    assert not any(
        "RETURN DISTINCT x.name AS name" in q for q in _graph_cyphers(data)
    )


async def test_trace_execution_path_timeout_then_empty_walk_degrades(
) -> None:
    """Link 3 of the fallback chain: the walk is attempted and salvages
    nothing, so the tool falls through to the one-hop Degraded_Result
    rather than raising or rendering an empty chain (R3.3, R5.5)."""
    from src.data.neptune_adapter import NeptuneAdapterError

    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    _seed_entity_type(data.graph_db, ["Function"])
    _seed_degree(data.graph_db, _DEG_SINGLE)
    data.graph_db.add_raise(
        "CALLS*1..",
        NeptuneAdapterError("query exceeded 30.0s statement timeout"),
    )
    _seed_walk_anchor(data.graph_db)
    # The walk resolves its anchor but the hop finds nothing.
    _seed_expansion(data.graph_db, "CALLS", [])
    _seed_one_hop(data.graph_db, [{"name": "neighbor_a", "file": "n.py"}])

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "trace_execution_path",
        {"function_name": "foo", "include_weights": False},
    )
    assert not text.startswith("[ERROR]")
    # The walk really was attempted before degrading.
    assert any(_WALK_ANCHOR in q for q in _graph_cyphers(data))
    assert _walk_expansions(data)
    # ... and the Degraded_Result is what the caller got.
    assert "statement timeout" in text
    assert "Direct Neighbors" in text
    assert "`neighbor_a`" in text
    assert "[optimized: BFS walker" not in text
