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
    # Cross-language cypher uses the expanded edge set.
    data.graph_db.add_response(
        "SOURCES|INVOKES|EXECUTES|CALLS|USES|DEFINES",
        [
            {
                "name": "gsi",
                "labels": ["FortranProgram"],
                "hop": 2,
                "relType": "EXECUTES",
            },
            {
                "name": "pygfs.task.gfs_forecast",
                "labels": ["PythonModule"],
                "hop": 3,
                "relType": "DEFINES",
            },
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
    text = await _call_tool(
        mcp,
        "trace_full_execution_chain",
        {"start": "JGLOBAL_FORECAST"},
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
    text = await _call_tool(
        mcp,
        "trace_full_execution_chain",
        {"start": "JGLOBAL_FORECAST", "languages": ["fortran"]},
    )
    assert "`gsi`" in text
    # Shell / Python nodes should be filtered out entirely.
    assert "exglobal_forecast.sh" not in text
    assert "pygfs.task.gfs_forecast" not in text


async def test_trace_full_execution_chain_clamps_max_depth_to_full_chain_ceiling() -> None:
    """Asking for 99 hops is silently clamped to FULL_CHAIN_DEPTH (5).

    R2.2 reduces the cross-language full-chain ceiling from the historical
    10 to a conservative 5; the emitted pattern must be ``*1..5`` and
    never the old ``*1..10`` / ``*1..99``.
    """
    from src.tools._traversal_bounds import FULL_CHAIN_DEPTH

    data = MockUnifiedDataAccess()
    _seed_empty_graph(data.graph_db)
    data.graph_db.add_response(
        "RETURN n.name AS name, labels(n) AS labels LIMIT 1",
        [{"name": "X", "labels": ["ShellScript"]}],
    )
    # Track which depth the variable-length pattern was rendered with.
    captured: list[str] = []
    original_query = data.graph_db.query

    async def _recording_query(cypher: str, params: dict[str, Any] | None = None, **kwargs):
        if "*1.." in cypher:
            captured.append(cypher)
        return await original_query(cypher, params, **kwargs)

    data.graph_db.query = _recording_query  # type: ignore[method-assign]

    mcp = _make_server(data=data)
    await _call_tool(
        mcp,
        "trace_full_execution_chain",
        {"start": "X", "max_depth": 99},
    )
    expected = f"*1..{FULL_CHAIN_DEPTH}"
    # Confirm the rendered cypher used the capped depth, not 99 or 10.
    assert any(expected in c for c in captured)
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
