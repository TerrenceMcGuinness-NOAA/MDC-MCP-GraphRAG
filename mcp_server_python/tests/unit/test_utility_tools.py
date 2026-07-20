"""Unit tests for :mod:`src.tools.utility` (Requirements 12.1 – 12.6).

Covers tool-schema parity with the Node.js version, degraded-mode
behaviour, health snapshot persistence, trend analysis, and quality
metric rendering. Uses the ``MockUnifiedDataAccess`` fixture from
``tests/conftest.py`` — no live AWS calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastmcp import FastMCP

from src.tools import utility
from tests.conftest import MockUnifiedDataAccess

pytestmark = pytest.mark.unit


# ── helpers ─────────────────────────────────────────────────────────────


def _make_server(
    *, data: Any = None, state_dir: Path | None = None, version: str | None = None
) -> FastMCP:
    mcp = FastMCP("mdc-mcp-rag-test", version=version or "1.0.0")
    utility.register(
        mcp, data=data, state_dir=state_dir, server_version=version
    )
    return mcp


async def _call_tool(mcp: FastMCP, name: str, arguments: dict[str, Any]) -> str:
    tool = await mcp.get_tool(name)
    result = await tool.run(arguments)
    # FunctionTool.run returns a ToolResult with .content; grab the text.
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text is not None:
            return text
    # Fallback — stringify whatever came back.
    return str(result)


# ── registration parity ────────────────────────────────────────────────


async def test_register_exposes_four_tools_with_matching_names() -> None:
    mcp = _make_server()
    tools = await mcp.list_tools(run_middleware=False)
    names = sorted(t.name for t in tools)
    assert names == sorted(
        [
            "get_server_info",
            "mcp_health_check",
            "get_health_trend",
            "get_quality_metrics",
        ]
    )


async def test_tool_schemas_match_nodejs_parameter_names() -> None:
    mcp = _make_server()
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    expected = {
        "get_server_info": {"include_capabilities"},
        "mcp_health_check": {"detailed", "deep", "functional"},
        "get_health_trend": {"limit"},
        "get_quality_metrics": {"category", "compare"},
    }
    for name, params in expected.items():
        schema = tools[name].parameters
        actual = set(schema.get("properties", {}).keys())
        assert actual == params, f"{name}: expected {params}, got {actual}"


async def test_bool_params_default_to_false() -> None:
    mcp = _make_server()
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    info = tools["get_server_info"].parameters["properties"]
    assert info["include_capabilities"]["default"] is False
    health = tools["mcp_health_check"].parameters["properties"]
    assert health["detailed"]["default"] is False
    assert health["deep"]["default"] is False
    assert health["functional"]["default"] is False
    quality = tools["get_quality_metrics"].parameters["properties"]
    assert quality["compare"]["default"] is False


async def test_get_health_trend_default_limit_is_ten() -> None:
    mcp = _make_server()
    tool = await mcp.get_tool("get_health_trend")
    assert tool.parameters["properties"]["limit"]["default"] == 10


async def test_get_quality_metrics_category_enum_matches_nodejs() -> None:
    mcp = _make_server()
    tool = await mcp.get_tool("get_quality_metrics")
    category_schema = tool.parameters["properties"]["category"]
    # ``Literal[...] | None`` yields ``anyOf: [{enum: [...]}, {type: null}]``.
    enum = None
    for branch in category_schema.get("anyOf", []):
        if "enum" in branch:
            enum = branch["enum"]
            break
    if enum is None:
        # Fallback: some FastMCP versions flatten to a top-level enum.
        enum = category_schema.get("enum")
    assert enum is not None, f"no enum found in {category_schema}"
    assert sorted(enum) == sorted(
        [
            "code_structure",
            "semantic_search",
            "architecture",
            "ee2_compliance",
            "operational",
            "cross_language",
        ]
    )


# ── get_server_info ─────────────────────────────────────────────────────


async def test_get_server_info_reports_version_and_tool_count() -> None:
    mcp = _make_server(version="9.9.9")
    text = await _call_tool(mcp, "get_server_info", {})
    assert "v9.9.9" in text
    assert "Total Tools" in text
    # Utility module registers 4 tools; with no other modules that's the
    # whole count.
    assert "**Total Tools**: 4" in text


async def test_get_server_info_lists_registered_tools() -> None:
    mcp = _make_server()
    text = await _call_tool(mcp, "get_server_info", {})
    for name in (
        "get_server_info",
        "mcp_health_check",
        "get_health_trend",
        "get_quality_metrics",
    ):
        assert f"`{name}`" in text


async def test_get_server_info_infers_active_utility_module() -> None:
    mcp = _make_server()
    text = await _call_tool(mcp, "get_server_info", {})
    assert "- `utility`" in text


async def test_get_server_info_capability_block_shows_degraded_without_data() -> None:
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp, "get_server_info", {"include_capabilities": True}
    )
    assert "## Capabilities" in text
    assert "degraded" in text.lower()


async def test_get_server_info_capability_block_shows_connected_with_data() -> None:
    data = MockUnifiedDataAccess()
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "get_server_info", {"include_capabilities": True}
    )
    assert "## Capabilities" in text
    assert "connected" in text


# ── mcp_health_check ───────────────────────────────────────────────────


async def test_health_check_healthy_when_all_components_ok() -> None:
    data = MockUnifiedDataAccess()
    mcp = _make_server(data=data)
    text = await _call_tool(mcp, "mcp_health_check", {})
    assert "**Overall Status**: HEALTHY" in text
    assert "Vector Database" in text
    assert "Graph Database" in text


async def test_health_check_degraded_when_graph_empty() -> None:
    data = MockUnifiedDataAccess()
    data.graph_db.statistics = {"nodes": 0, "relationships": 0}
    mcp = _make_server(data=data)
    text = await _call_tool(mcp, "mcp_health_check", {"detailed": True})
    assert "DEGRADED" in text
    assert "graph database has 0 nodes" in text


async def test_health_check_degraded_without_data() -> None:
    mcp = _make_server(data=None)
    text = await _call_tool(mcp, "mcp_health_check", {"detailed": True})
    # No data-access → component row labelled "disabled" — overall is
    # still HEALTHY because Base Server + Utility Tools are fine and
    # 'disabled' is not a degraded-inducing status.
    assert "Data Access Layer" in text
    assert "disabled" in text


async def test_health_check_unhealthy_when_data_raises() -> None:
    class _BrokenDA:
        async def health_check(self, *, deep: bool = False) -> dict[str, Any]:
            raise RuntimeError("backend offline")

    mcp = _make_server(data=_BrokenDA())
    text = await _call_tool(mcp, "mcp_health_check", {"detailed": True})
    assert "UNHEALTHY" in text
    assert "backend offline" in text


async def test_health_check_deep_persists_snapshot(
    tmp_state_dir: Path,
) -> None:
    data = MockUnifiedDataAccess()
    mcp = _make_server(data=data, state_dir=tmp_state_dir)
    await _call_tool(mcp, "mcp_health_check", {"deep": True})

    history_file = tmp_state_dir / "health_history.jsonl"
    assert history_file.is_file()
    lines = history_file.read_text().splitlines()
    assert len(lines) == 1
    snap = json.loads(lines[0])
    # Schema parity with Node.js writer.
    assert snap["source"] == "tool_call"
    assert "timestamp" in snap and snap["timestamp"].endswith("Z")
    assert "neo4j" in snap and "chromadb" in snap and "drift" in snap
    assert snap["neo4j"]["nodes"] == data.graph_db.statistics["nodes"]
    assert snap["chromadb"]["collections"] == len(data.vector_db.collections)


async def test_health_check_deep_computes_drift_vs_prior(
    tmp_state_dir: Path,
) -> None:
    # Seed prior snapshot with lower node/doc counts.
    history_file = tmp_state_dir / "health_history.jsonl"
    prior = {
        "timestamp": "2026-05-12T22:00:00.000Z",
        "source": "tool_call",
        "neo4j": {"status": "ok", "nodes": 50000, "relationships": 0, "latency_ms": None},
        "chromadb": {"status": "healthy", "collections": 5, "total_docs": 100, "latency_ms": None},
        "drift": {"neo4j_node_delta": 0, "chromadb_doc_delta": 0},
    }
    history_file.write_text(json.dumps(prior) + "\n")

    data = MockUnifiedDataAccess()  # 59759 nodes, 3 hits by default
    mcp = _make_server(data=data, state_dir=tmp_state_dir)
    await _call_tool(mcp, "mcp_health_check", {"deep": True})

    lines = history_file.read_text().splitlines()
    assert len(lines) == 2
    latest = json.loads(lines[-1])
    assert latest["drift"]["neo4j_node_delta"] == 59759 - 50000
    assert latest["drift"]["chromadb_doc_delta"] == 3 - 100


async def test_health_check_non_deep_does_not_write_history(
    tmp_state_dir: Path,
) -> None:
    data = MockUnifiedDataAccess()
    mcp = _make_server(data=data, state_dir=tmp_state_dir)
    await _call_tool(mcp, "mcp_health_check", {"deep": False})
    assert not (tmp_state_dir / "health_history.jsonl").exists()


async def test_health_check_functional_flag_message_when_no_data() -> None:
    mcp = _make_server(data=None)
    text = await _call_tool(mcp, "mcp_health_check", {"functional": True})
    assert "Functional Validation" in text
    assert "no data access layer" in text.lower()


async def test_health_check_annotates_graph_node_scope() -> None:
    """Phase 73 (graph-node-count-scope-documentation R2.1): the Graph Database
    line names its scope so the count is not confused with the tenant-scoped
    (get_knowledge_base_status) or whole-graph counts."""
    data = MockUnifiedDataAccess()
    mcp = _make_server(data=data)
    text = await _call_tool(mcp, "mcp_health_check", {"detailed": True})
    assert "(health-check scope)" in text


# ── get_health_trend ────────────────────────────────────────────────────


async def test_health_trend_no_history_file(tmp_state_dir: Path) -> None:
    mcp = _make_server(state_dir=tmp_state_dir)
    text = await _call_tool(mcp, "get_health_trend", {})
    assert "No health history found" in text


async def test_health_trend_empty_file(tmp_state_dir: Path) -> None:
    (tmp_state_dir / "health_history.jsonl").write_text("")
    mcp = _make_server(state_dir=tmp_state_dir)
    text = await _call_tool(mcp, "get_health_trend", {})
    assert "Health history file is empty" in text


def _write_snapshots(path: Path, snapshots: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for s in snapshots:
            fh.write(json.dumps(s) + "\n")


async def test_health_trend_table_contains_latest_snapshots(
    tmp_state_dir: Path,
) -> None:
    history = tmp_state_dir / "health_history.jsonl"
    snapshots = [
        {
            "timestamp": f"2026-05-12T12:0{i}:00.000Z",
            "source": "tool_call",
            "neo4j": {"status": "ok", "nodes": 50000 + i * 1000, "relationships": 2_000_000, "latency_ms": 10 + i},
            "chromadb": {"status": "healthy", "collections": 5, "total_docs": 80000 + i * 1000, "latency_ms": 5 + i},
            "drift": {"neo4j_node_delta": 1000 if i else 0, "chromadb_doc_delta": 1000 if i else 0},
        }
        for i in range(3)
    ]
    _write_snapshots(history, snapshots)

    mcp = _make_server(state_dir=tmp_state_dir)
    text = await _call_tool(mcp, "get_health_trend", {"limit": 2})
    assert "Health Trend (last 2 snapshots)" in text
    # Latest two timestamps (12:01, 12:02) are present; 12:00 is not.
    assert "2026-05-12 12:01:00" in text
    assert "2026-05-12 12:02:00" in text
    assert "2026-05-12 12:00:00" not in text


async def test_health_trend_detects_anomaly_when_delta_exceeds_10pct(
    tmp_state_dir: Path,
) -> None:
    history = tmp_state_dir / "health_history.jsonl"
    snapshots = [
        {
            "timestamp": "2026-05-12T12:00:00.000Z",
            "source": "tool_call",
            "neo4j": {"status": "ok", "nodes": 100, "relationships": 0, "latency_ms": None},
            "chromadb": {"status": "healthy", "collections": 5, "total_docs": 1000, "latency_ms": None},
            "drift": {"neo4j_node_delta": 0, "chromadb_doc_delta": 0},
        },
        {
            "timestamp": "2026-05-12T12:01:00.000Z",
            "source": "tool_call",
            "neo4j": {"status": "ok", "nodes": 150, "relationships": 0, "latency_ms": None},  # +50%
            "chromadb": {"status": "healthy", "collections": 5, "total_docs": 1050, "latency_ms": None},  # +5%
            "drift": {"neo4j_node_delta": 50, "chromadb_doc_delta": 50},
        },
    ]
    _write_snapshots(history, snapshots)

    mcp = _make_server(state_dir=tmp_state_dir)
    text = await _call_tool(mcp, "get_health_trend", {"limit": 10})
    assert "## Anomalies Detected" in text
    assert "Neo4j node count jumped from 100 to 150" in text
    # ChromaDB delta is 5% — not an anomaly.
    assert "ChromaDB doc count jumped" not in text


async def test_health_trend_reports_stable_when_no_anomalies(
    tmp_state_dir: Path,
) -> None:
    history = tmp_state_dir / "health_history.jsonl"
    snapshots = [
        {
            "timestamp": "2026-05-12T12:00:00.000Z",
            "source": "tool_call",
            "neo4j": {"status": "ok", "nodes": 1000, "relationships": 0, "latency_ms": 10},
            "chromadb": {"status": "healthy", "collections": 5, "total_docs": 10000, "latency_ms": 5},
            "drift": {"neo4j_node_delta": 0, "chromadb_doc_delta": 0},
        },
        {
            "timestamp": "2026-05-12T12:01:00.000Z",
            "source": "tool_call",
            "neo4j": {"status": "ok", "nodes": 1010, "relationships": 0, "latency_ms": 11},  # +1%
            "chromadb": {"status": "healthy", "collections": 5, "total_docs": 10100, "latency_ms": 5},
            "drift": {"neo4j_node_delta": 10, "chromadb_doc_delta": 100},
        },
    ]
    _write_snapshots(history, snapshots)

    mcp = _make_server(state_dir=tmp_state_dir)
    text = await _call_tool(mcp, "get_health_trend", {})
    assert "## Anomalies" in text
    assert "No anomalies detected" in text
    assert "within 10% threshold" in text


async def test_health_trend_single_snapshot_skips_trend_section(
    tmp_state_dir: Path,
) -> None:
    history = tmp_state_dir / "health_history.jsonl"
    _write_snapshots(
        history,
        [
            {
                "timestamp": "2026-05-12T12:00:00.000Z",
                "source": "tool_call",
                "neo4j": {"status": "ok", "nodes": 100, "relationships": 0, "latency_ms": 10},
                "chromadb": {"status": "healthy", "collections": 5, "total_docs": 100, "latency_ms": 5},
                "drift": {"neo4j_node_delta": 0, "chromadb_doc_delta": 0},
            }
        ],
    )
    mcp = _make_server(state_dir=tmp_state_dir)
    text = await _call_tool(mcp, "get_health_trend", {})
    # Trend/anomaly sections are 2+ snapshot features.
    assert "## Trends" not in text
    assert "## Anomalies" not in text


async def test_health_trend_invalid_limit_rejected(
    tmp_state_dir: Path,
) -> None:
    mcp = _make_server(state_dir=tmp_state_dir)
    text = await _call_tool(mcp, "get_health_trend", {"limit": 0})
    assert "Invalid limit" in text


# ── get_quality_metrics ─────────────────────────────────────────────────


async def test_quality_metrics_file_missing_message(tmp_state_dir: Path) -> None:
    mcp = _make_server(state_dir=tmp_state_dir)
    text = await _call_tool(mcp, "get_quality_metrics", {})
    assert "No benchmark results found" in text
    assert "quality_metrics.jsonl" in text


async def test_quality_metrics_empty_file_message(tmp_state_dir: Path) -> None:
    (tmp_state_dir / "quality_metrics.jsonl").write_text("")
    mcp = _make_server(state_dir=tmp_state_dir)
    text = await _call_tool(mcp, "get_quality_metrics", {})
    assert "is empty" in text


def _write_quality(path: Path, snapshots: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for s in snapshots:
            fh.write(json.dumps(s) + "\n")


async def test_quality_metrics_renders_overall_and_categories(
    tmp_state_dir: Path,
) -> None:
    snapshot = {
        "timestamp": "2026-05-12T12:00:00.000Z",
        "corpus_version": "v2",
        "total_queries": 120,
        "overall": {
            "precision_at_k": 0.82,
            "recall_at_k": 0.74,
            "mrr": 0.71,
            "coverage": 0.95,
            "latency_p50_ms": 38,
            "latency_p95_ms": 120,
        },
        "categories": {
            "code_structure": {
                "precision_at_k": 0.85,
                "recall_at_k": 0.80,
                "mrr": 0.77,
                "coverage": 0.99,
                "latency_p50_ms": 30,
            },
            "semantic_search": {
                "precision_at_k": 0.80,
                "recall_at_k": 0.70,
                "mrr": 0.65,
                "coverage": 0.90,
                "latency_p50_ms": 45,
            },
        },
    }
    _write_quality(tmp_state_dir / "quality_metrics.jsonl", [snapshot])

    mcp = _make_server(state_dir=tmp_state_dir)
    text = await _call_tool(mcp, "get_quality_metrics", {})
    assert "**Benchmark**: 2026-05-12T12:00:00.000Z" in text
    assert "v2" in text and "120 queries" in text
    # Overall table values.
    assert "| Precision@5 | 0.82 |" in text
    assert "| Coverage | 95% |" in text
    assert "| Latency P50 | 38ms |" in text
    # Category table.
    assert "Code Structure" in text
    assert "Semantic Search" in text


async def test_quality_metrics_category_filter_narrows_output(
    tmp_state_dir: Path,
) -> None:
    snapshot = {
        "timestamp": "2026-05-12T12:00:00.000Z",
        "categories": {
            "code_structure": {"precision_at_k": 0.9},
            "semantic_search": {"precision_at_k": 0.7},
        },
    }
    _write_quality(tmp_state_dir / "quality_metrics.jsonl", [snapshot])

    mcp = _make_server(state_dir=tmp_state_dir)
    text = await _call_tool(
        mcp, "get_quality_metrics", {"category": "semantic_search"}
    )
    assert "Semantic Search" in text
    assert "Code Structure" not in text
    assert "## Category: Semantic Search" in text


async def test_quality_metrics_category_filter_with_no_match(
    tmp_state_dir: Path,
) -> None:
    snapshot = {
        "timestamp": "2026-05-12T12:00:00.000Z",
        "categories": {"code_structure": {"precision_at_k": 0.9}},
    }
    _write_quality(tmp_state_dir / "quality_metrics.jsonl", [snapshot])

    mcp = _make_server(state_dir=tmp_state_dir)
    text = await _call_tool(
        mcp, "get_quality_metrics", {"category": "semantic_search"}
    )
    assert "No results found for category `semantic_search`" in text


async def test_quality_metrics_compare_without_previous_snapshot(
    tmp_state_dir: Path,
) -> None:
    snapshot = {
        "timestamp": "2026-05-12T12:00:00.000Z",
        "categories": {"code_structure": {"precision_at_k": 0.9}},
    }
    _write_quality(tmp_state_dir / "quality_metrics.jsonl", [snapshot])

    mcp = _make_server(state_dir=tmp_state_dir)
    text = await _call_tool(mcp, "get_quality_metrics", {"compare": True})
    assert "Only one benchmark snapshot" in text


async def test_quality_metrics_compare_shows_regression_table(
    tmp_state_dir: Path,
) -> None:
    snapshots = [
        {
            "timestamp": "2026-05-12T11:00:00.000Z",
            "categories": {
                "code_structure": {"precision_at_k": 0.80, "latency_p50_ms": 50},
            },
        },
        {
            "timestamp": "2026-05-12T12:00:00.000Z",
            "categories": {
                "code_structure": {"precision_at_k": 0.90, "latency_p50_ms": 40},
            },
        },
    ]
    _write_quality(tmp_state_dir / "quality_metrics.jsonl", snapshots)

    mcp = _make_server(state_dir=tmp_state_dir)
    text = await _call_tool(mcp, "get_quality_metrics", {"compare": True})
    assert "## Regression" in text
    # P@5 improved (higher is better) → [IMPROVED]
    assert "[IMPROVED]" in text
    # Latency went down (40 < 50) → also improved.
    # Sanity: the report contains both rows.
    assert "P@5" in text and "P50" in text


# ── state-dir resolution ───────────────────────────────────────────────


def test_resolve_state_dir_explicit_wins(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SDD_STATE_DIR", str(tmp_path / "env"))
    resolved = utility._resolve_state_dir(str(tmp_path / "explicit"))
    assert resolved == (tmp_path / "explicit").resolve()


def test_resolve_state_dir_env_var_wins_over_default(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SDD_STATE_DIR", str(tmp_path / "env"))
    resolved = utility._resolve_state_dir(None)
    assert resolved == (tmp_path / "env").resolve()


def test_resolve_state_dir_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.delenv("SDD_STATE_DIR", raising=False)
    resolved = utility._resolve_state_dir(None)
    assert resolved == Path(utility.DEFAULT_STATE_DIR).resolve()


# ── _infer_active_modules ──────────────────────────────────────────────


def test_infer_active_modules_detects_known_tools() -> None:
    names = ["search_documentation", "get_server_info"]
    active = utility._infer_active_modules(names)
    assert "semantic_search" in active
    assert "utility" in active


def test_infer_active_modules_empty_when_no_markers() -> None:
    assert utility._infer_active_modules(["my_custom_tool"]) == []


# ── _default_server_version fallback ───────────────────────────────────


def test_default_server_version_returns_string() -> None:
    v = utility._default_server_version()
    assert isinstance(v, str) and v


# ── functional-validation harness rendering (health-check-bugfixes) ─────


def _module_result(module: str, status: str, *, error: str = "", latency_ms: int = 0):
    """Build a ``ModuleResult`` for harness-rendering tests."""
    from src.tools.smoke_queries import ModuleResult

    return ModuleResult(
        module=module, status=status, latency_ms=latency_ms, error=error
    )


def test_render_functional_results_renders_skip_row_and_summary() -> None:
    """Task 3.1: a mixed [pass, pass, skip, pass, fail] list renders one
    SKIP row + one FAIL row and the summary reads
    '3/5 passed, 1 failed, 1 skipped' (R3.4)."""
    results = [
        _module_result("semantic_search", "pass"),
        _module_result("code_analysis", "pass"),
        _module_result("workflow_info", "skip", error="workflow_root=/x not mounted"),
        _module_result("graph_rag", "pass"),
        _module_result("ee2_compliance", "fail", error="0 hits"),
    ]
    lines = utility._render_functional_results(results)
    text = "\n".join(lines)

    # SKIP row present with its reason and the [SKIP] marker.
    assert "| workflow_info | [SKIP] skip |" in text
    assert "workflow_root=/x not mounted" in text
    # FAIL row present with the [ERROR] marker.
    assert "| ee2_compliance | [ERROR] fail |" in text
    # Summary distinguishes skips from failures.
    assert "**Summary**: 3/5 passed, 1 failed, 1 skipped" in text


def test_render_functional_results_all_pass_summary_byte_equivalent() -> None:
    """Property 4: when nothing skips or fails, the summary is the same
    'N/N passed, 0 failed, 0 skipped' line as before the fix."""
    results = [
        _module_result("semantic_search", "pass"),
        _module_result("utility", "pass"),
    ]
    text = "\n".join(utility._render_functional_results(results))
    assert "**Summary**: 2/2 passed, 0 failed, 0 skipped" in text


def test_functional_summary_counts() -> None:
    """The shared tally helper counts pass/fail/skip and total."""
    results = [
        _module_result("a", "pass"),
        _module_result("b", "skip"),
        _module_result("c", "fail"),
        _module_result("d", "pass"),
    ]
    assert utility._functional_summary(results) == {
        "passed": 2,
        "failed": 1,
        "skipped": 1,
        "total": 4,
    }


def test_append_health_snapshot_carries_functional_counts(
    tmp_state_dir: Path,
) -> None:
    """R3.5: the persisted snapshot carries passed/failed/skipped integer
    counts so a downstream trend tool can distinguish skips from fails."""
    payload = {
        "vector": {"ok": True, "indexCount": 5, "totalDocuments": 100},
        "graph": {"ok": True, "nodeCount": 10, "relationshipCount": 20},
    }
    utility._append_health_snapshot(
        tmp_state_dir,
        payload,
        functional={"passed": 8, "failed": 0, "skipped": 1},
    )
    snap = json.loads(
        (tmp_state_dir / "health_history.jsonl").read_text().splitlines()[-1]
    )
    assert snap["functional"] == {"passed": 8, "failed": 0, "skipped": 1}
    assert all(
        isinstance(snap["functional"][k], int)
        for k in ("passed", "failed", "skipped")
    )


def test_append_health_snapshot_omits_functional_when_absent(
    tmp_state_dir: Path,
) -> None:
    """Forward-compatible: without functional counts the key is omitted, so
    old readers see the unchanged schema."""
    payload = {
        "vector": {"ok": True, "indexCount": 5, "totalDocuments": 100},
        "graph": {"ok": True, "nodeCount": 10, "relationshipCount": 20},
    }
    utility._append_health_snapshot(tmp_state_dir, payload)
    snap = json.loads(
        (tmp_state_dir / "health_history.jsonl").read_text().splitlines()[-1]
    )
    assert "functional" not in snap
