"""Unit tests for :mod:`src.tools.semantic_search` (Task 8.1, Phase B5).

Covers tool-schema parity with Node.js (parameter names, defaults,
enums), degraded-mode behaviour, tool-layer rendering, and the
``check_knowledge_integrity`` Phase-43 check battery. Uses the
``MockUnifiedDataAccess`` fixture from ``tests/conftest.py`` — no live
AWS calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastmcp import FastMCP

from src.tools import semantic_search
from tests.conftest import MockUnifiedDataAccess, MockVectorDB, MockGraphDB

pytestmark = pytest.mark.unit


# ── helpers ────────────────────────────────────────────────────────────


def _make_server(
    *,
    data: Any = None,
    documentation_sources_path: Path | None = None,
    repo_base: Path | None = None,
) -> FastMCP:
    mcp = FastMCP("mdc-mcp-rag-test", version="1.0.0")
    semantic_search.register(
        mcp,
        data=data,
        documentation_sources_path=documentation_sources_path,
        repo_base=repo_base,
    )
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


# ── registration parity ───────────────────────────────────────────────


async def test_register_exposes_eight_tools_with_matching_names() -> None:
    mcp = _make_server()
    tools = await mcp.list_tools(run_middleware=False)
    names = sorted(t.name for t in tools)
    assert names == sorted(
        [
            "search_documentation",
            "find_related_files",
            "explain_with_context",
            "get_knowledge_base_status",
            "list_ingested_urls",
            "get_ingested_urls_array",
            "list_all_sources",
            "check_knowledge_integrity",
        ]
    )


async def test_tool_schemas_match_nodejs_parameter_names() -> None:
    mcp = _make_server()
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    expected = {
        "search_documentation": {
            "query",
            "collection",
            "max_results",
            "include_graph",
            "similarity_threshold", "tenant_id"},
        "find_related_files": {
            "file_path",
            "max_results",
            "include_documentation", "tenant_id"},
        "explain_with_context": {"topic", "context_type", "detail_level", "tenant_id"},
        "get_knowledge_base_status": {
            "include_graph", "include_vector", "all_tenants", "tenant_id"},
        "list_ingested_urls": {"format", "source_filter"},
        "get_ingested_urls_array": {"include_failed"},
        "list_all_sources": {
            "source_type",
            "collection",
            "format",
            "include_gaps",
        },
        "check_knowledge_integrity": {"sample_size", "tenant_id"},
    }
    for name, params in expected.items():
        schema = tools[name].parameters
        actual = set(schema.get("properties", {}).keys())
        assert actual == params, f"{name}: expected {params}, got {actual}"


async def test_required_fields_match_nodejs() -> None:
    mcp = _make_server()
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    assert set(tools["search_documentation"].parameters.get("required") or []) == {"query"}
    assert set(tools["find_related_files"].parameters.get("required") or []) == {"file_path"}
    assert set(tools["explain_with_context"].parameters.get("required") or []) == {"topic"}
    # Remaining tools have all-optional params.
    for opt_tool in (
        "get_knowledge_base_status",
        "list_ingested_urls",
        "get_ingested_urls_array",
        "list_all_sources",
        "check_knowledge_integrity",
    ):
        req = tools[opt_tool].parameters.get("required") or []
        assert req == [] or req is None, f"{opt_tool} should have no required params"


async def test_search_documentation_defaults_match_nodejs() -> None:
    mcp = _make_server()
    tool = await mcp.get_tool("search_documentation")
    props = tool.parameters["properties"]
    assert props["max_results"]["default"] == 8
    assert props["include_graph"]["default"] is True
    assert props["similarity_threshold"]["default"] == 0.1


async def test_find_related_files_defaults_match_nodejs() -> None:
    mcp = _make_server()
    tool = await mcp.get_tool("find_related_files")
    props = tool.parameters["properties"]
    assert props["max_results"]["default"] == 10
    assert props["include_documentation"]["default"] is True


async def test_explain_with_context_enums_match_nodejs() -> None:
    mcp = _make_server()
    tool = await mcp.get_tool("explain_with_context")
    props = tool.parameters["properties"]
    # Literal[...] yields ``enum``; older fastmcp may nest in anyOf.
    for key, expected in [
        ("context_type", {"technical", "operational", "configuration", "all"}),
        ("detail_level", {"basic", "intermediate", "advanced"}),
    ]:
        schema = props[key]
        enum = schema.get("enum")
        if enum is None:
            for branch in schema.get("anyOf", []):
                if "enum" in branch:
                    enum = branch["enum"]
                    break
        assert enum is not None, f"{key}: no enum in {schema}"
        assert set(enum) == expected
        assert schema.get("default") in expected


async def test_get_knowledge_base_status_bool_defaults_are_true() -> None:
    mcp = _make_server()
    tool = await mcp.get_tool("get_knowledge_base_status")
    props = tool.parameters["properties"]
    assert props["include_graph"]["default"] is True
    assert props["include_vector"]["default"] is True
    # Phase 73: all_tenants is additive and defaults to False (tenant scope).
    assert props["all_tenants"]["default"] is False


async def test_list_ingested_urls_format_enum_matches_nodejs() -> None:
    mcp = _make_server()
    tool = await mcp.get_tool("list_ingested_urls")
    props = tool.parameters["properties"]
    schema = props["format"]
    enum = schema.get("enum")
    if enum is None:
        for branch in schema.get("anyOf", []):
            if "enum" in branch:
                enum = branch["enum"]
                break
    assert set(enum) == {"detailed", "summary", "urls_only"}
    assert schema.get("default") == "detailed"


async def test_check_knowledge_integrity_sample_size_default_is_50() -> None:
    mcp = _make_server()
    tool = await mcp.get_tool("check_knowledge_integrity")
    assert tool.parameters["properties"]["sample_size"]["default"] == 50


# ── degraded mode ─────────────────────────────────────────────────────


async def test_search_documentation_returns_error_when_data_missing() -> None:
    mcp = _make_server(data=None)
    text = await _call_tool(mcp, "search_documentation", {"query": "x"})
    assert "[ERROR]" in text
    assert "Vector database unavailable" in text


async def test_find_related_files_returns_error_when_data_missing() -> None:
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp, "find_related_files", {"file_path": "x.py"}
    )
    assert "[ERROR]" in text
    assert "Graph database unavailable" in text


async def test_explain_with_context_returns_error_when_data_missing() -> None:
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp, "explain_with_context", {"topic": "forecast"}
    )
    assert "[ERROR]" in text


async def test_get_knowledge_base_status_returns_error_when_data_missing() -> None:
    mcp = _make_server(data=None)
    text = await _call_tool(mcp, "get_knowledge_base_status", {})
    assert "[ERROR]" in text
    assert "Data access layer unavailable" in text


async def test_check_knowledge_integrity_returns_error_when_data_missing() -> None:
    mcp = _make_server(data=None)
    text = await _call_tool(mcp, "check_knowledge_integrity", {})
    assert "[ERROR]" in text


async def test_list_ingested_urls_works_without_data() -> None:
    """The URL-listing tools read from the bundled JSON — they do NOT
    require a live data layer. Matches Node.js behaviour."""
    mcp = _make_server(data=None)
    text = await _call_tool(mcp, "list_ingested_urls", {})
    assert "# RAG Knowledge Base Ingested URLs" in text
    assert "Configured Documentation Sources" in text


async def test_get_ingested_urls_array_works_without_data() -> None:
    mcp = _make_server(data=None)
    text = await _call_tool(mcp, "get_ingested_urls_array", {})
    assert "# Ingested URLs Array" in text
    assert "## Enabled URLs" in text


# ── empty-argument validation ─────────────────────────────────────────


async def test_search_documentation_rejects_empty_query() -> None:
    data = MockUnifiedDataAccess()
    mcp = _make_server(data=data)
    text = await _call_tool(mcp, "search_documentation", {"query": "  "})
    assert "[ERROR]" in text
    assert "Query is required" in text


async def test_find_related_files_rejects_empty_path() -> None:
    data = MockUnifiedDataAccess()
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "find_related_files", {"file_path": ""}
    )
    assert "[ERROR]" in text


async def test_explain_with_context_rejects_empty_topic() -> None:
    data = MockUnifiedDataAccess()
    mcp = _make_server(data=data)
    text = await _call_tool(mcp, "explain_with_context", {"topic": "   "})
    assert "[ERROR]" in text


# ── happy path with mock data ─────────────────────────────────────────


async def test_search_documentation_renders_multi_collection_by_default() -> None:
    data = MockUnifiedDataAccess()
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "search_documentation", {"query": "forecast", "max_results": 3}
    )
    assert "# Search Results: forecast" in text
    assert "multi-collection search" in text
    # Vector call was made with the right arguments.
    vec_calls = [c for c in data.vector_db.call_log if c[0] == "multi_collection_query"]
    assert len(vec_calls) == 1


async def test_search_documentation_clamps_max_results_to_20() -> None:
    data = MockUnifiedDataAccess()
    mcp = _make_server(data=data)
    await _call_tool(
        mcp,
        "search_documentation",
        {"query": "forecast", "max_results": 999},
    )
    # The clamp should have capped k at 20.
    vec_calls = [
        c for c in data.vector_db.call_log if c[0] == "multi_collection_query"
    ]
    assert vec_calls, "vector_db.multi_collection_query was not called"
    assert vec_calls[0][2].get("k") == 20


async def test_search_documentation_clamps_similarity_threshold_to_0_1() -> None:
    data = MockUnifiedDataAccess()
    mcp = _make_server(data=data)
    await _call_tool(
        mcp,
        "search_documentation",
        {"query": "x", "similarity_threshold": 5.0},
    )
    vec_calls = [
        c for c in data.vector_db.call_log if c[0] == "multi_collection_query"
    ]
    assert vec_calls[0][2]["similarity_threshold"] == 1.0


async def test_search_documentation_single_collection_uses_query() -> None:
    data = MockUnifiedDataAccess()
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "search_documentation",
        {"query": "test", "collection": "jjobs-v8-0-0"},
    )
    assert "collection: jjobs-v8-0-0" in text
    calls = [c for c in data.vector_db.call_log if c[0] == "query"]
    assert any(c[1][0] == "jjobs-v8-0-0" for c in calls)


async def test_search_documentation_no_results_returns_plain_message() -> None:
    data = MockUnifiedDataAccess()
    data.vector_db.hits = []
    mcp = _make_server(data=data)
    text = await _call_tool(mcp, "search_documentation", {"query": "zzz"})
    assert "No results found" in text


async def test_search_documentation_handles_adapter_error_gracefully() -> None:
    data = MockUnifiedDataAccess()
    data.vector_db.raise_on_query = RuntimeError("boom")
    mcp = _make_server(data=data)
    text = await _call_tool(mcp, "search_documentation", {"query": "x"})
    assert "[ERROR]" in text
    assert "boom" in text


async def test_find_related_files_reports_imports_and_related() -> None:
    data = MockUnifiedDataAccess()
    # Seed the graph mock to return two imports and one related file.
    data.graph_db.add_response(
        "MATCH (f:File)",  # matches the imports-cypher prefix
        [
            {"moduleName": "os"},
            {"moduleName": "pathlib"},
        ],
    )
    # Second query (related-cypher) will hit canned_rows which maps to
    # SAMPLE_GRAPH_ROWS — use a more specific fragment to override.
    data.graph_db.add_response(
        "AND NOT",
        [{"filePath": "sibling.py"}],
    )
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "find_related_files", {"file_path": "scripts/x.py"}
    )
    assert "# Related Files by Dependencies" in text
    assert "Shared Dependencies" in text
    assert "`os`" in text
    assert "`pathlib`" in text
    assert "`sibling.py`" in text


async def test_find_related_files_handles_graph_error() -> None:
    data = MockUnifiedDataAccess()
    data.graph_db.raise_on_query = RuntimeError("neptune unreachable")
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "find_related_files", {"file_path": "x.py"}
    )
    assert "[ERROR]" in text
    assert "neptune unreachable" in text


async def test_explain_with_context_combines_vector_and_graph() -> None:
    data = MockUnifiedDataAccess()
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "explain_with_context",
        {
            "topic": "forecast",
            "context_type": "technical",
            "detail_level": "advanced",
        },
    )
    assert "# Explanation: forecast" in text
    assert "Documentation Context" in text
    assert "Code Structure Context" in text
    assert "Summary" in text


async def test_explain_with_context_picks_collections_by_context_type() -> None:
    data = MockUnifiedDataAccess()
    mcp = _make_server(data=data)
    await _call_tool(
        mcp,
        "explain_with_context",
        {"topic": "jglobal forecast", "context_type": "operational"},
    )
    multi_calls = [
        c for c in data.vector_db.call_log
        if c[0] == "multi_collection_query"
    ]
    collections = multi_calls[0][1] if multi_calls else ()
    assert "jjobs-v8-0-0" in collections


async def test_explain_with_context_applies_detail_level_limit() -> None:
    data = MockUnifiedDataAccess()
    mcp = _make_server(data=data)
    await _call_tool(
        mcp,
        "explain_with_context",
        {"topic": "x", "detail_level": "basic"},
    )
    call = [
        c for c in data.vector_db.call_log if c[0] == "multi_collection_query"
    ][0]
    assert call[2]["k"] == 3


async def test_get_knowledge_base_status_renders_both_sections() -> None:
    data = MockUnifiedDataAccess()
    mcp = _make_server(data=data)
    text = await _call_tool(mcp, "get_knowledge_base_status", {})
    assert "# Knowledge Base Status" in text
    assert "## Vector Database" in text
    assert "## Graph Database" in text
    assert "[OK] Healthy" in text


async def test_get_knowledge_base_status_suppresses_graph_when_disabled() -> None:
    data = MockUnifiedDataAccess()
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "get_knowledge_base_status", {"include_graph": False}
    )
    assert "## Vector Database" in text
    assert "## Graph Database" not in text


async def test_get_knowledge_base_status_suppresses_vector_when_disabled() -> None:
    data = MockUnifiedDataAccess()
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "get_knowledge_base_status", {"include_vector": False}
    )
    assert "## Vector Database" not in text
    assert "## Graph Database" in text


async def test_get_knowledge_base_status_handles_vector_health_failure() -> None:
    data = MockUnifiedDataAccess()
    data.vector_db.raise_on_query = None  # query not involved
    # Force health_check to throw.
    async def _raise(**kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("opensearch down")
    data.vector_db.health_check = _raise  # type: ignore[method-assign]
    mcp = _make_server(data=data)
    text = await _call_tool(mcp, "get_knowledge_base_status", {})
    assert "[ERROR]" in text
    assert "opensearch down" in text


# ── list_ingested_urls / get_ingested_urls_array ──────────────────────


async def test_list_ingested_urls_urls_only_returns_newline_list(
    tmp_path: Path,
) -> None:
    sources_file = tmp_path / "doc_sources.json"
    sources_file.write_text(
        json.dumps(
            {
                "version": "9.9.9",
                "sources": [
                    {"name": "alpha", "url": "https://a", "enabled": True},
                    {"name": "beta", "url": "https://b", "enabled": False},
                    {"name": "gamma", "url": "https://c", "enabled": True},
                ],
            }
        )
    )
    mcp = _make_server(documentation_sources_path=sources_file)
    text = await _call_tool(
        mcp, "list_ingested_urls", {"format": "urls_only"}
    )
    urls = [line for line in text.splitlines() if line.strip()]
    assert urls == ["https://a", "https://c"]


async def test_list_ingested_urls_source_filter_narrows_output(
    tmp_path: Path,
) -> None:
    sources_file = tmp_path / "doc_sources.json"
    sources_file.write_text(
        json.dumps(
            {
                "version": "1.0.0",
                "sources": [
                    {"name": "global-workflow", "url": "https://gw", "enabled": True},
                    {"name": "rocoto", "url": "https://r", "enabled": True},
                ],
            }
        )
    )
    mcp = _make_server(documentation_sources_path=sources_file)
    text = await _call_tool(
        mcp,
        "list_ingested_urls",
        {"format": "detailed", "source_filter": "rocoto"},
    )
    assert "rocoto" in text
    assert "global-workflow" not in text


async def test_get_ingested_urls_array_respects_include_failed(
    tmp_path: Path,
) -> None:
    sources_file = tmp_path / "doc_sources.json"
    sources_file.write_text(
        json.dumps(
            {
                "version": "3.0.0",
                "sources": [
                    {"name": "a", "url": "https://a", "enabled": True},
                    {"name": "b", "url": "https://b", "enabled": False},
                ],
            }
        )
    )
    mcp = _make_server(documentation_sources_path=sources_file)
    text = await _call_tool(
        mcp, "get_ingested_urls_array", {"include_failed": False}
    )
    assert "## Enabled URLs (1)" in text
    assert "## Disabled URLs" not in text

    text_full = await _call_tool(
        mcp, "get_ingested_urls_array", {"include_failed": True}
    )
    assert "## Enabled URLs (1)" in text_full
    assert "## Disabled URLs (1)" in text_full
    assert "https://b" in text_full


async def test_get_ingested_urls_array_includes_version_metadata(
    tmp_path: Path,
) -> None:
    sources_file = tmp_path / "doc_sources.json"
    sources_file.write_text(
        json.dumps({"version": "7.7.7", "sources": []})
    )
    mcp = _make_server(documentation_sources_path=sources_file)
    text = await _call_tool(mcp, "get_ingested_urls_array", {})
    assert "**Version**: 7.7.7" in text
    assert "**Total Sources**: 0" in text


async def test_list_ingested_urls_handles_missing_config(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "does-not-exist.json"
    mcp = _make_server(documentation_sources_path=missing)
    text = await _call_tool(mcp, "list_ingested_urls", {})
    # Should still produce a well-formed markdown doc (with a graceful
    # "no sources" notice), rather than erroring out.
    assert "# RAG Knowledge Base Ingested URLs" in text


# ── check_knowledge_integrity ─────────────────────────────────────────


async def test_check_knowledge_integrity_renders_four_checks(
    tmp_path: Path,
) -> None:
    data = MockUnifiedDataAccess()
    # Give the graph mock a responsive answer for file-count query.
    data.graph_db.add_response(
        "MATCH (f:File) RETURN count(f)", [{"total": 10}]
    )
    data.graph_db.add_response(
        "MATCH (n) WHERE n:FortranSubroutine",
        [{"total": 100}],
    )
    mcp = _make_server(data=data, repo_base=tmp_path)
    text = await _call_tool(mcp, "check_knowledge_integrity", {})
    assert "# Knowledge Base Integrity Report" in text
    # All four check rows should appear in the table.
    for check_name in (
        "Path Consistency",
        "Orphaned Graph Nodes",
        "Stale Embeddings",
        "Coverage Gap",
    ):
        assert check_name in text


async def test_check_knowledge_integrity_flags_bad_paths(
    tmp_path: Path,
) -> None:
    vector = MockVectorDB()

    # Inject a sample_metadata hook the tool discovers via hasattr.
    async def _sample(n: int) -> list[dict[str, Any]]:
        return [
            {"file_path": "/home/user/checkout/forecast.F90"},
            {"file_path": "/scratch/tmp/x.py"},
            {"file_path": "sorc/clean.py"},
        ]
    vector.sample_metadata = _sample  # type: ignore[attr-defined]

    graph = MockGraphDB()
    graph.add_response("MATCH (f:File)", [{"total": 5}])
    graph.add_response("MATCH (n) WHERE n:FortranSubroutine", [{"total": 0}])

    data = MockUnifiedDataAccess(vector_db=vector, graph_db=graph)
    mcp = _make_server(data=data, repo_base=tmp_path)
    text = await _call_tool(mcp, "check_knowledge_integrity", {})
    # 2 of 3 samples start with bad prefixes — the path row is [WARN].
    path_row = [
        line for line in text.splitlines()
        if "Path Consistency" in line
    ]
    assert path_row and "[WARN]" in path_row[0]


async def test_check_knowledge_integrity_coverage_uses_graph_fallback_when_repo_missing(
    tmp_path: Path,
) -> None:
    """Phase 72 (fortran-coverage-gap-path-fix): when the workflow mount is
    absent, the Coverage Gap check falls back to a graph-only count instead of
    the old ``[SKIP] no Fortran files found``."""
    data = MockUnifiedDataAccess()
    data.graph_db.add_response(
        "MATCH (n) WHERE n:FortranSubroutine",
        [{"total": 5}],
    )
    missing_repo = tmp_path / "nope"
    mcp = _make_server(data=data, repo_base=missing_repo)
    text = await _call_tool(mcp, "check_knowledge_integrity", {})
    assert "[SKIP] no Fortran files found" not in text
    assert "Coverage Gap (Fortran)" in text
    assert "graph-only" in text


async def test_check_knowledge_integrity_uses_custom_sample_size(
    tmp_path: Path,
) -> None:
    vector = MockVectorDB()
    captured: dict[str, int] = {}

    async def _sample(n: int) -> list[dict[str, Any]]:
        captured["n"] = n
        return []
    vector.sample_metadata = _sample  # type: ignore[attr-defined]

    graph = MockGraphDB()
    graph.add_response("MATCH (f:File)", [{"total": 0}])
    graph.add_response("MATCH (n) WHERE n:FortranSubroutine", [{"total": 0}])

    data = MockUnifiedDataAccess(vector_db=vector, graph_db=graph)
    mcp = _make_server(data=data, repo_base=tmp_path)
    await _call_tool(mcp, "check_knowledge_integrity", {"sample_size": 7})
    assert captured["n"] == 7


# ── Bug 2: tenant-scoped vector status block ───────────────────────────
# (opensearch-tenant-resolution-fix)


class _FakeStatusTenant:
    def __init__(self, index_prefix: str, tenant_id: str = "t") -> None:
        self.index_prefix = index_prefix
        self.tenant_id = tenant_id


def _mixed_health() -> dict[str, Any]:
    """health_check(deep=True) payload mixing base + gw_v17_ indices."""
    detail = {
        "mdc-code-context-titan1024": 100,
        "mdc-workflow-docs-titan1024": 200,
        "gw_v17_mdc-code-titan1024": 11,
        "gw_v17_mdc-workflow-docs-titan1024": 22,
    }
    return {
        "status": "healthy",
        "indices": list(detail.keys()),
        "indices_detail": detail,
        "total_documents": sum(detail.values()),
    }


class _FakeStatusVectorDB:
    def __init__(self, health: dict[str, Any]) -> None:
        self._health = health

    async def health_check(self, *, deep: bool = False) -> dict[str, Any]:
        return dict(self._health)


def _collection_rows(lines: list[str]) -> list[str]:
    """Index names rendered in the Collections Detail block."""
    out: list[str] = []
    for ln in lines:
        s = ln.strip()
        if s.startswith("- ") and ":" in s and "documents" in s:
            out.append(s[2:].split(":", 1)[0].strip())
    return out


# ── _default_scope_indices + router-scoped listing (unit) ─────────────
# shared-scope-query-routing Task 10.2 removed _filter_indices_by_tenant
# and _index_in_tenant_scope: a name-shape prefix test cannot distinguish a
# shared collection from another tenant's, so it cannot express "the
# unprefixed shared collection belongs to gw_v17 too". The default path
# keeps a name-shape filter (correct there, byte-equivalent); the
# non-default path routes through tenant_collection_set instead.


def test_default_scope_indices_excludes_other_prefixes() -> None:
    names, detail, total = semantic_search._default_scope_indices(
        _mixed_health(), others=("gw_v17_",)
    )
    assert set(names) == {
        "mdc-code-context-titan1024",
        "mdc-workflow-docs-titan1024",
    }
    assert total == 300
    assert "gw_v17_mdc-code-titan1024" not in names


def test_default_scope_indices_preserves_bookkeeping_overcount() -> None:
    """R6.3: the default gw total keeps the pre-existing bookkeeping-index
    over-count. A name-shape default filter does not exclude it, and the
    default block must stay byte-equivalent -- a follow-up spec converges
    the two paths."""
    health = {
        "status": "healthy",
        "indices_detail": {
            "mdc-code-context-titan1024": 100,
            "mdc-content-sha-registry": 5,
        },
    }
    names, _detail, total = semantic_search._default_scope_indices(
        health, others=("gw_v17_",)
    )
    assert "mdc-content-sha-registry" in names
    assert total == 105


def test_tenant_collection_set_nondefault_excludes_foreign_prefix() -> None:
    """Re-expressed intent of the removed non-default name-shape filter: a
    prefixed tenant's router-derived collection set carries only its own
    prefix or the unprefixed shared collections, never another tenant's,
    and reaches BOTH its own prefixed content and the shared corpora."""
    from src.config.tenants import Tenant
    from src.data.read_router import tenant_collection_set

    tenant = Tenant(
        tenant_id="gw_v17", repo_ref="R", branch="b",
        index_prefix="gw_v17_", label_prefix="GW_V17_",
        workflow_subdir="dev-v17", lifecycle="staging",
    )
    tcs = tenant_collection_set(tenant, profile="titan1024")
    for name in tcs.physical_names:
        # own prefix, or an unprefixed shared collection (never gw_sfs_ etc.)
        assert name.startswith("gw_v17_") or not name.startswith("gw_")
    assert any(n.startswith("gw_v17_") for n in tcs.physical_names)
    assert any(not n.startswith("gw_v17_") for n in tcs.physical_names)


# ── _render_vector_status_block scoping ────────────────────────────────


async def test_vector_status_block_gw_lists_only_base_indices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(semantic_search, "_tenant", lambda: _FakeStatusTenant(""))
    monkeypatch.setattr(
        semantic_search, "_other_index_prefixes", lambda t: ("gw_v17_",)
    )
    lines = await semantic_search._render_vector_status_block(
        _FakeStatusVectorDB(_mixed_health())
    )
    rows = _collection_rows(lines)
    assert all(not r.startswith("gw_v17_") for r in rows)
    assert set(rows) == {
        "mdc-code-context-titan1024",
        "mdc-workflow-docs-titan1024",
    }
    # Property 4: no tenant-prefix header line for the default tenant.
    assert not any("Tenant prefix" in ln for ln in lines)
    assert "- **Total Documents:** 300" in lines


async def test_vector_status_block_v17_lists_router_resolved_collections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-default tenant: the block lists exactly the Read_Router's
    resolved collection set, scope-labelled, with counts from health and an
    absent member marked ``unprovisioned`` (Task 10.1, R9.1-R9.6)."""
    from src.config.tenants import Tenant
    from src.data.read_router import tenant_collection_set

    monkeypatch.setenv("MCP_EMBEDDING_PROFILE", "titan1024")
    tenant = Tenant(
        tenant_id="gw_v17", repo_ref="R", branch="b",
        index_prefix="gw_v17_", label_prefix="GW_V17_",
        workflow_subdir="dev-v17", lifecycle="staging",
    )
    monkeypatch.setattr(semantic_search, "_tenant", lambda: tenant)

    tcs = tenant_collection_set(tenant, profile="titan1024")
    members = list(tcs.physical_names)
    # Provision every member but the last, so both the count-rendering and
    # the unprovisioned-rendering paths are exercised.
    detail = {name: (i + 1) * 10 for i, name in enumerate(members[:-1])}
    health = {
        "status": "healthy",
        "indices": list(detail.keys()),
        "indices_detail": detail,
        "total_documents": sum(detail.values()),
    }
    lines = await semantic_search._render_vector_status_block(
        _FakeStatusVectorDB(health)
    )
    text = "\n".join(lines)

    # Tenant-prefix header present for a non-default tenant.
    assert any(ln == "- **Tenant prefix:** gw_v17_" for ln in lines)
    # Six members for five logical collections (hybrid contributes two).
    assert "- **Collections:** 6" in text
    # Every router member is listed and scope-labelled.
    for target in tcs.targets:
        assert f"{target.physical} ({target.scope})" in text
    # The last member is unprovisioned and rendered distinctly from empty.
    assert (
        f"{members[-1]} ({tcs.targets[-1].scope}): unprovisioned" in text
    )
    # Total is the arithmetic sum over provisioned members only (R9.3).
    assert f"- **Total Documents:** {sum(detail.values())}" in text
    # No bookkeeping / foreign-prefixed index can leak into the listing.
    assert "mdc-content-sha-registry" not in text


async def test_vector_status_block_v17_reaches_shared_and_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fix (Task 10.1): a prefixed tenant's status lists BOTH its own
    prefixed collections AND the unprefixed shared collections, so shared
    content stops reading as invisible to a non-default tenant."""
    from src.config.tenants import Tenant
    from src.data.read_router import tenant_collection_set

    monkeypatch.setenv("MCP_EMBEDDING_PROFILE", "titan1024")
    tenant = Tenant(
        tenant_id="gw_v17", repo_ref="R", branch="b",
        index_prefix="gw_v17_", label_prefix="GW_V17_",
        workflow_subdir="dev-v17", lifecycle="staging",
    )
    monkeypatch.setattr(semantic_search, "_tenant", lambda: tenant)

    tcs = tenant_collection_set(tenant, profile="titan1024")
    detail = {name: 7 for name in tcs.physical_names}
    health = {
        "status": "healthy",
        "indices": list(detail.keys()),
        "indices_detail": detail,
        "total_documents": sum(detail.values()),
    }
    lines = await semantic_search._render_vector_status_block(
        _FakeStatusVectorDB(health)
    )
    rows = _collection_rows(lines)
    # Own prefixed collections are present ...
    assert any(r.startswith("gw_v17_") for r in rows)
    # ... and so are the unprefixed shared corpora (the blind spot closed).
    assert any(not r.startswith("gw_v17_") for r in rows)


# ── graceful-missing-index-handling: search_documentation ──────────────


def _notfound_exc_sd():
    from opensearchpy.exceptions import NotFoundError

    return NotFoundError(
        404,
        "index_not_found_exception",
        {"error": {"type": "index_not_found_exception"}},
    )


async def test_search_documentation_explicit_collection_missing_index_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R3.4: explicit collection + missing index -> [INFO] Skip_Block."""
    data = MockUnifiedDataAccess()
    data.vector_db.raise_on_query = _notfound_exc_sd()
    monkeypatch.setattr(semantic_search, "_tenant_id_or_none", lambda: "gw_v17")
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "search_documentation",
        {"query": "EE2 file naming", "collection": "ee2-standards-v5-0-0-enhanced"},
    )
    assert "[INFO]" in text and "[ERROR]" not in text
    assert "gw_v17" in text
    assert "ee2-standards-v5-0-0-enhanced" in text
    assert "index_not_found_exception" not in text


async def test_search_documentation_explicit_collection_non_404_error() -> None:
    data = MockUnifiedDataAccess()
    data.vector_db.raise_on_query = RuntimeError("transport boom")
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "search_documentation",
        {"query": "x", "collection": "ee2-standards-v5-0-0-enhanced"},
    )
    assert "[ERROR]" in text
    assert "transport boom" in text


async def test_search_documentation_multi_collection_empty_unchanged() -> None:
    """R3.5 / R5.4: multi-collection mode with an empty merged result still
    renders the legacy 'No results found for: ...' line — NOT a Skip_Block.
    This path is intentionally unchanged (Property 4)."""
    data = MockUnifiedDataAccess()
    data.vector_db.hits = []  # multi_collection_query returns []
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "search_documentation", {"query": "GEMPAK"}
    )
    assert text.endswith('No results found for: "GEMPAK"\n')
    assert "[INFO]" not in text


async def test_bug_exploration_search_documentation_missing_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bug-Condition Exploration (search_documentation explicit collection).

    Unfixed: [ERROR] ... index_not_found_exception. Fixed: [INFO] Skip_Block
    with tenant + collection. Both directions demonstrated before commit.
    """
    data = MockUnifiedDataAccess()
    data.vector_db.raise_on_query = _notfound_exc_sd()
    monkeypatch.setattr(semantic_search, "_tenant_id_or_none", lambda: "gw_v17")
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "search_documentation",
        {"query": "x", "collection": "ee2-standards-v5-0-0-enhanced"},
    )
    assert "[INFO]" in text and "[ERROR]" not in text
    assert "gw_v17" in text and "ee2-standards-v5-0-0-enhanced" in text
