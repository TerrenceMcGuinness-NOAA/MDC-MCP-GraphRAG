"""Tenant tool exposure tests — bug condition exploration + fix validation.

Task 1 (exploration): Cases 1-2 MUST FAIL on unfixed code.
Tasks 10-12 (fix checking): pass after the fix is applied.
Task 13 (flip): task 1 tests now pass on fixed code.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from fastmcp import FastMCP

from src.config.tenants import CatalogDefaults, Tenant, TenantCatalog
from src.tenancy.resolver import _ctx_var


# ── test fixtures ───────────────────────────────────────────────────────


def _make_catalog() -> TenantCatalog:
    """Build a minimal two-tenant catalog for tests."""
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
        lifecycle="experimental",
    )
    return TenantCatalog(
        schema_version=1,
        defaults=CatalogDefaults(tenant_id="gw"),
        tenants=(gw, gw_v17),
    )


class RecordingVectorDB:
    """Stub VectorDB that records queries for inspection."""

    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    async def query(self, collection, query, *, k=8, **kwargs):
        self.calls.append({"collection": collection, "query": query, "k": k, **kwargs})
        return [{"id": "hit1", "content": "test result", "score": 0.9, "metadata": {}}]

    async def multi_collection_query(self, collections, query, *, k=8, **kwargs):
        self.calls.append({"collections": collections, "query": query, "k": k, **kwargs})
        return [{"id": "hit1", "content": "test result", "score": 0.9, "metadata": {}}]

    async def health_check(self, deep=False):
        return {"status": "healthy", "indices": {}, "total_documents": 100}

    async def sample_metadata(self, n):
        return [{"file_path": "test.f90"}]


class RecordingGraphDB:
    """Stub GraphDB that records queries."""

    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    async def query(self, cypher, params=None, **kwargs):
        self.calls.append({"cypher": cypher, "params": params, **kwargs})
        return [{"count": 0}]

    async def health_check(self):
        return {"status": "healthy", "nodes": 10, "relationships": 5}


class StubData:
    """Mimics UnifiedDataAccess."""

    def __init__(self):
        self.vector_db = RecordingVectorDB()
        self.graph_db = RecordingGraphDB()


async def _call_tool(mcp: FastMCP, name: str, arguments: dict[str, Any]) -> str:
    """Call a registered tool and return the text result."""
    tool = await mcp.get_tool(name)
    result = await tool.run(arguments)
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text is not None:
            return text
    return str(result)


# ── Task 1: Exploration test (MUST FAIL on current code) ────────────────


class TestBugConditionExploration:
    """These tests assert the bug EXISTS — they FAIL on unfixed code.

    The failure is the success criterion for Task 1.
    """

    @pytest.mark.asyncio
    async def test_schema_exposes_tenant_id(self):
        """Case 1: search_documentation MUST have tenant_id in its schema."""
        mcp = FastMCP(name="test", version="0.0.1")
        data = StubData()

        from src.tools import semantic_search
        semantic_search.register(mcp, data)

        tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
        tool = tools.get("search_documentation")
        assert tool is not None, "search_documentation not registered"
        props = tool.parameters.get("properties", {})
        assert "tenant_id" in props, (
            f"Bug condition confirmed: search_documentation schema has no "
            f"tenant_id. Properties: {list(props.keys())}"
        )

    @pytest.mark.asyncio
    async def test_routing_to_non_default_tenant(self):
        """Case 2: calling with tenant_id='gw_v17' routes to gw_v17_ prefix."""
        mcp = FastMCP(name="test", version="0.0.1")
        data = StubData()
        catalog = _make_catalog()

        from src.tools import semantic_search
        semantic_search.register(mcp, data)

        with patch("src.tenancy.runtime.get_catalog", return_value=catalog):
            result = await _call_tool(
                mcp, "search_documentation",
                {"query": "test query", "tenant_id": "gw_v17"},
            )

        # The tool should have routed to gw_v17 and attributed
        assert "*Tenant: gw_v17*" in result, (
            f"Bug condition confirmed: routing did not produce gw_v17 "
            f"attribution. Got: {result[:200]}"
        )


# ── Task 10: Fix Checking property tests ────────────────────────────────


class TestFixChecking:
    """Property 1: Tenant routing works for all wired modules."""

    @pytest.mark.asyncio
    async def test_search_documentation_routes_to_gw_v17(self):
        """search_documentation with tenant_id='gw_v17' returns attributed output."""
        mcp = FastMCP(name="test", version="0.0.1")
        data = StubData()
        catalog = _make_catalog()

        from src.tools import semantic_search
        semantic_search.register(mcp, data, catalog=catalog)

        result = await _call_tool(
            mcp, "search_documentation",
            {"query": "test", "tenant_id": "gw_v17"},
        )
        assert "*Tenant: gw_v17*" in result
        assert "*Branch: dev/gfs.v17*" in result

    @pytest.mark.asyncio
    async def test_find_dependencies_routes_to_gw_v17(self):
        """code_analysis tool routes correctly."""
        mcp = FastMCP(name="test", version="0.0.1")
        data = StubData()
        catalog = _make_catalog()

        from src.tools import code_analysis
        code_analysis.register(mcp, data, catalog=catalog)

        result = await _call_tool(
            mcp, "find_dependencies",
            {"target": "test.py", "tenant_id": "gw_v17"},
        )
        assert "*Tenant: gw_v17*" in result

    @pytest.mark.asyncio
    async def test_get_code_context_routes_to_gw_v17(self):
        """graph_rag data tool routes correctly."""
        mcp = FastMCP(name="test", version="0.0.1")
        data = StubData()
        catalog = _make_catalog()

        from src.tools import graph_rag
        graph_rag.register(mcp, data, catalog=catalog)

        result = await _call_tool(
            mcp, "get_code_context",
            {"symbol": "test_fn", "tenant_id": "gw_v17"},
        )
        assert "*Tenant: gw_v17*" in result

    @pytest.mark.asyncio
    async def test_get_operational_guidance_routes_to_gw_v17(self):
        """operational tool routes correctly."""
        mcp = FastMCP(name="test", version="0.0.1")
        data = StubData()
        catalog = _make_catalog()

        from src.tools import operational
        operational.register(mcp, data, catalog=catalog)

        result = await _call_tool(
            mcp, "get_operational_guidance",
            {"operation": "restart", "tenant_id": "gw_v17"},
        )
        assert "*Tenant: gw_v17*" in result

    @pytest.mark.asyncio
    async def test_search_ee2_standards_routes_to_gw_v17(self):
        """ee2_compliance tool routes correctly."""
        mcp = FastMCP(name="test", version="0.0.1")
        data = StubData()
        catalog = _make_catalog()

        from src.tools import ee2_compliance
        ee2_compliance.register(mcp, data, catalog=catalog)

        result = await _call_tool(
            mcp, "search_ee2_standards",
            {"query": "error handling", "tenant_id": "gw_v17"},
        )
        assert "*Tenant: gw_v17*" in result


# ── Task 11: Schema-preservation + Server-global-untouched tests ────────


#: Authoritative inventory of tenant-scoped tools (from design).
TENANT_SCOPED_TOOLS = frozenset({
    "search_documentation", "find_related_files", "explain_with_context",
    "get_knowledge_base_status", "check_knowledge_integrity",
    "analyze_code_structure", "find_dependencies", "trace_execution_path",
    "find_callers_callees", "trace_full_execution_chain", "find_env_dependencies",
    "get_code_context", "search_architecture", "find_similar_code",
    "get_change_impact", "trace_data_flow",
    "get_operational_guidance", "explain_workflow_component",
    "list_job_scripts", "get_job_details",
    "search_ee2_standards",
    "describe_component", "get_workflow_structure", "get_system_configs",
})

#: Server-global tools that must NOT have tenant_id.
SERVER_GLOBAL_TOOLS = frozenset({
    "get_server_info", "mcp_health_check", "get_health_trend",
    "get_quality_metrics",
    # SDD workflow tools
    "start_sdd_session", "record_sdd_step", "complete_sdd_session",
    "get_sdd_session", "get_sdd_framework_status", "get_sdd_workflow",
    "list_sdd_workflows", "get_sdd_execution_history", "validate_sdd_compliance",
    # Graph RAG session tools
    "mark_as_modified", "get_session_context", "checkpoint_state",
    "restore_checkpoint",
    # EE2 content-analysis tools
    "analyze_ee2_compliance", "generate_compliance_report",
    "scan_repository_compliance", "extract_code_for_analysis",
    # GitHub tools
    "search_issues", "get_pull_requests",
    # Manifest tools (non-tenant)
    "list_ingested_urls", "get_ingested_urls_array", "list_all_sources",
})


class TestSchemaPreservation:
    """Property 2: Tenant-scoped tools have original params + tenant_id.
    Property 4: Server-global tools have NO tenant_id.
    """

    @pytest.mark.asyncio
    async def test_semantic_search_tools_have_tenant_id(self):
        mcp = FastMCP(name="test", version="0.0.1")
        data = StubData()
        catalog = _make_catalog()
        from src.tools import semantic_search
        semantic_search.register(mcp, data, catalog=catalog)
        tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
        for name in ("search_documentation", "find_related_files",
                     "explain_with_context", "get_knowledge_base_status",
                     "check_knowledge_integrity"):
            if name not in tools:
                continue
            props = tools[name].parameters.get("properties", {})
            assert "tenant_id" in props, f"{name} missing tenant_id"

    @pytest.mark.asyncio
    async def test_search_documentation_preserves_original_params(self):
        mcp = FastMCP(name="test", version="0.0.1")
        data = StubData()
        catalog = _make_catalog()
        from src.tools import semantic_search
        semantic_search.register(mcp, data, catalog=catalog)
        tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
        props = set(tools["search_documentation"].parameters.get("properties", {}).keys())
        # Must have ALL original params + tenant_id
        expected = {"query", "collection", "max_results", "include_graph",
                    "similarity_threshold", "tenant_id"}
        assert expected.issubset(props), f"Missing params: {expected - props}"

    @pytest.mark.asyncio
    async def test_server_global_tools_no_tenant_id(self):
        """Utility and SDD tools must NOT have tenant_id in schema."""
        mcp = FastMCP(name="test", version="0.0.1")
        from src.tools import utility
        utility.register(mcp, None)
        tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
        for name in ("get_server_info", "mcp_health_check",
                     "get_health_trend", "get_quality_metrics"):
            if name not in tools:
                continue
            props = tools[name].parameters.get("properties", {})
            assert "tenant_id" not in props, (
                f"Server-global tool {name} should NOT have tenant_id"
            )

    @pytest.mark.asyncio
    async def test_graph_rag_session_tools_no_tenant_id(self):
        """Session tools must NOT have tenant_id."""
        mcp = FastMCP(name="test", version="0.0.1")
        data = StubData()
        catalog = _make_catalog()
        from src.tools import graph_rag
        graph_rag.register(mcp, data, catalog=catalog)
        tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
        for name in ("mark_as_modified", "get_session_context",
                     "checkpoint_state", "restore_checkpoint"):
            if name not in tools:
                continue
            props = tools[name].parameters.get("properties", {})
            assert "tenant_id" not in props, (
                f"Session tool {name} should NOT have tenant_id"
            )


# ── Task 12: Default-preservation + Unknown-tenant tests ────────────────


class TestDefaultPreservation:
    """Property 3: No tenant_id → gw default, same as pre-fix."""

    @pytest.mark.asyncio
    async def test_no_tenant_id_resolves_gw(self):
        mcp = FastMCP(name="test", version="0.0.1")
        data = StubData()
        catalog = _make_catalog()
        from src.tools import semantic_search
        semantic_search.register(mcp, data, catalog=catalog)

        result = await _call_tool(
            mcp, "search_documentation", {"query": "test"},
        )
        assert "*Tenant: gw*" in result
        assert "*Branch: develop*" in result

    @pytest.mark.asyncio
    async def test_explicit_gw_same_as_no_tenant(self):
        mcp = FastMCP(name="test", version="0.0.1")
        data = StubData()
        catalog = _make_catalog()
        from src.tools import semantic_search
        semantic_search.register(mcp, data, catalog=catalog)

        result = await _call_tool(
            mcp, "search_documentation",
            {"query": "test", "tenant_id": "gw"},
        )
        assert "*Tenant: gw*" in result


class TestUnknownTenant:
    """Property 5: Unknown tenant_id returns clear error."""

    @pytest.mark.asyncio
    async def test_unknown_tenant_returns_error(self):
        mcp = FastMCP(name="test", version="0.0.1")
        data = StubData()
        catalog = _make_catalog()
        from src.tools import semantic_search
        semantic_search.register(mcp, data, catalog=catalog)

        result = await _call_tool(
            mcp, "search_documentation",
            {"query": "test", "tenant_id": "nonexistent"},
        )
        assert "[ERROR]" in result
        assert "nonexistent" in result
        # Should name known tenant ids
        assert "gw" in result
        assert "gw_v17" in result

    @pytest.mark.asyncio
    async def test_unknown_tenant_no_vector_calls(self):
        """On unknown tenant, no adapter queries should be made."""
        mcp = FastMCP(name="test", version="0.0.1")
        data = StubData()
        catalog = _make_catalog()
        from src.tools import semantic_search
        semantic_search.register(mcp, data, catalog=catalog)

        # Clear any existing calls
        data.vector_db.calls.clear()

        await _call_tool(
            mcp, "search_documentation",
            {"query": "test", "tenant_id": "bad_id"},
        )
        assert data.vector_db.calls == [], (
            "Vector DB was queried despite unknown tenant"
        )
