"""Unit tests for src/auth/tool_scope_guard.py — tool-scope authorization guard.

Validates Requirements R5.3 (tool denied when outside Allowed_Tool_Set) and
R5.4 (default-deny on unrecognized scope).
"""
from __future__ import annotations

import pytest

from src.auth.middleware import PrincipalContext
from src.auth.tool_scope_guard import (
    ALLOWED_TOOL_SETS,
    CI_READONLY,
    HPC_USER,
    HPC_USER_ADDITIONS,
    MUTATION_TOOL_SET,
    ToolAccessDeniedError,
    check_tool_access,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(scope: str, principal: str = "test") -> PrincipalContext:
    """Build a PrincipalContext with the given scope."""
    return PrincipalContext(principal=principal, scope=scope, broker_request_id=None)


# ---------------------------------------------------------------------------
# Developer scope — allows ALL tools (R5.2, R5.5)
# ---------------------------------------------------------------------------


class TestDeveloperScope:
    """developer-sigv4 has access to every tool."""

    def test_allows_ci_tool(self):
        check_tool_access(_ctx("developer-sigv4"), "search_documentation")

    def test_allows_mutation_tool(self):
        check_tool_access(_ctx("developer-sigv4"), "mark_as_modified")

    def test_allows_github_tool(self):
        check_tool_access(_ctx("developer-sigv4"), "search_issues")

    def test_allows_arbitrary_tool_name(self):
        """Developer scope permits even unknown tool names — it is ALL."""
        check_tool_access(_ctx("developer-sigv4"), "totally_invented_tool_name")


# ---------------------------------------------------------------------------
# CI scope (mcp/ci-readonly) — R5.3
# ---------------------------------------------------------------------------


class TestCIReadonlyScope:
    """CI scope allows read-only tools and denies mutation/GitHub tools."""

    def test_allows_search_documentation(self):
        check_tool_access(_ctx("mcp/ci-readonly"), "search_documentation")

    def test_allows_analyze_code_structure(self):
        check_tool_access(_ctx("mcp/ci-readonly"), "analyze_code_structure")

    def test_allows_extract_ci_error_signal(self):
        """Python-only tool, added post-Node split."""
        check_tool_access(_ctx("mcp/ci-readonly"), "extract_ci_error_signal")

    def test_allows_get_server_info(self):
        check_tool_access(_ctx("mcp/ci-readonly"), "get_server_info")

    def test_denies_mutation_tool_mark_as_modified(self):
        with pytest.raises(ToolAccessDeniedError) as exc_info:
            check_tool_access(_ctx("mcp/ci-readonly"), "mark_as_modified")
        assert exc_info.value.scope == "mcp/ci-readonly"
        assert exc_info.value.tool_name == "mark_as_modified"

    def test_denies_mutation_tool_start_sdd_session(self):
        with pytest.raises(ToolAccessDeniedError):
            check_tool_access(_ctx("mcp/ci-readonly"), "start_sdd_session")

    def test_denies_github_tool_search_issues(self):
        with pytest.raises(ToolAccessDeniedError):
            check_tool_access(_ctx("mcp/ci-readonly"), "search_issues")

    def test_denies_github_tool_get_pull_requests(self):
        with pytest.raises(ToolAccessDeniedError):
            check_tool_access(_ctx("mcp/ci-readonly"), "get_pull_requests")

    def test_denies_session_context(self):
        """get_session_context is an HPC addition, not CI."""
        with pytest.raises(ToolAccessDeniedError):
            check_tool_access(_ctx("mcp/ci-readonly"), "get_session_context")

    def test_denies_unknown_tool(self):
        with pytest.raises(ToolAccessDeniedError):
            check_tool_access(_ctx("mcp/ci-readonly"), "nonexistent_tool")


# ---------------------------------------------------------------------------
# HPC scope (mcp/hpc-user)
# ---------------------------------------------------------------------------


class TestHPCUserScope:
    """HPC scope allows CI tools + GitHub + session-state, denies SDD mutations."""

    def test_allows_ci_tool(self):
        """HPC is a superset of CI — all CI tools are available."""
        check_tool_access(_ctx("mcp/hpc-user"), "search_documentation")

    def test_allows_github_search_issues(self):
        check_tool_access(_ctx("mcp/hpc-user"), "search_issues")

    def test_allows_github_get_pull_requests(self):
        check_tool_access(_ctx("mcp/hpc-user"), "get_pull_requests")

    def test_allows_github_analyze_workflow_dependencies(self):
        check_tool_access(_ctx("mcp/hpc-user"), "analyze_workflow_dependencies")

    def test_allows_github_analyze_repository_structure(self):
        check_tool_access(_ctx("mcp/hpc-user"), "analyze_repository_structure")

    def test_allows_session_state_mark_as_modified(self):
        check_tool_access(_ctx("mcp/hpc-user"), "mark_as_modified")

    def test_allows_session_state_get_session_context(self):
        check_tool_access(_ctx("mcp/hpc-user"), "get_session_context")

    def test_allows_session_state_checkpoint_state(self):
        check_tool_access(_ctx("mcp/hpc-user"), "checkpoint_state")

    def test_allows_session_state_restore_checkpoint(self):
        check_tool_access(_ctx("mcp/hpc-user"), "restore_checkpoint")

    def test_denies_sdd_mutation_start_sdd_session(self):
        """SDD session mutations are in MUTATION_TOOL_SET but NOT in HPC_USER_ADDITIONS."""
        with pytest.raises(ToolAccessDeniedError):
            check_tool_access(_ctx("mcp/hpc-user"), "start_sdd_session")

    def test_denies_sdd_mutation_record_sdd_step(self):
        with pytest.raises(ToolAccessDeniedError):
            check_tool_access(_ctx("mcp/hpc-user"), "record_sdd_step")

    def test_denies_sdd_mutation_complete_sdd_session(self):
        with pytest.raises(ToolAccessDeniedError):
            check_tool_access(_ctx("mcp/hpc-user"), "complete_sdd_session")

    def test_denies_unknown_tool(self):
        with pytest.raises(ToolAccessDeniedError):
            check_tool_access(_ctx("mcp/hpc-user"), "nonexistent_tool")


# ---------------------------------------------------------------------------
# Unknown scope — default-deny (R5.4)
# ---------------------------------------------------------------------------


class TestUnknownScope:
    """An unrecognized scope is rejected for any tool — defense in depth."""

    def test_unknown_scope_raises(self):
        with pytest.raises(ToolAccessDeniedError) as exc_info:
            check_tool_access(_ctx("mcp/admin-all"), "search_documentation")
        assert exc_info.value.scope == "mcp/admin-all"
        assert exc_info.value.tool_name == "search_documentation"

    def test_empty_scope_raises(self):
        with pytest.raises(ToolAccessDeniedError):
            check_tool_access(_ctx(""), "get_server_info")

    def test_scope_with_typo_raises(self):
        with pytest.raises(ToolAccessDeniedError):
            check_tool_access(_ctx("mcp/ci-readnoly"), "get_server_info")


# ---------------------------------------------------------------------------
# Set invariants
# ---------------------------------------------------------------------------


class TestSetInvariants:
    """Structural properties of the tool sets that must hold."""

    def test_ci_readonly_and_mutation_are_disjoint(self):
        """No mutation tool appears in CI_READONLY."""
        overlap = CI_READONLY & MUTATION_TOOL_SET
        assert overlap == frozenset(), f"overlap: {overlap}"

    def test_all_mutation_tools_excluded_from_ci(self):
        """Every tool in MUTATION_TOOL_SET is absent from CI_READONLY."""
        for tool in MUTATION_TOOL_SET:
            assert tool not in CI_READONLY, f"{tool} should not be in CI_READONLY"

    def test_hpc_user_is_superset_of_ci_readonly(self):
        """HPC_USER contains every tool in CI_READONLY."""
        assert CI_READONLY <= HPC_USER

    def test_hpc_user_equals_ci_plus_additions(self):
        """HPC_USER is exactly CI_READONLY ∪ HPC_USER_ADDITIONS."""
        assert HPC_USER == CI_READONLY | HPC_USER_ADDITIONS

    def test_hpc_additions_not_empty(self):
        assert len(HPC_USER_ADDITIONS) > 0

    def test_ci_readonly_not_empty(self):
        assert len(CI_READONLY) > 0

    def test_mutation_tool_set_not_empty(self):
        assert len(MUTATION_TOOL_SET) > 0

    def test_allowed_tool_sets_keys(self):
        """ALLOWED_TOOL_SETS contains exactly the two JWT scopes."""
        assert set(ALLOWED_TOOL_SETS.keys()) == {"mcp/ci-readonly", "mcp/hpc-user"}

    def test_sdd_read_only_in_ci_but_mutations_not(self):
        """SDD read-only tools are in CI, but SDD mutation tools are not."""
        sdd_readonly = {
            "list_sdd_workflows", "get_sdd_workflow", "get_sdd_session",
            "get_sdd_execution_history", "validate_sdd_compliance",
            "get_sdd_framework_status",
        }
        sdd_mutations = {"start_sdd_session", "record_sdd_step", "complete_sdd_session"}
        assert sdd_readonly <= CI_READONLY
        assert sdd_mutations.isdisjoint(CI_READONLY)

    def test_sdd_mutations_excluded_from_both_jwt_scopes(self):
        """SDD session management tools are excluded from BOTH JWT scopes (R5.5, §10.4).

        Path B §10.4 specifies MUTATION_TOOL_SET (6 tools) is excluded from CI.
        Path B §10.2 further specifies SDD session management tools are excluded from HPC.
        Session-state tools (mark_as_modified, checkpoint_state, restore_checkpoint) ARE
        intentionally in HPC_USER via HPC_USER_ADDITIONS (§10.2), so the full
        MUTATION_TOOL_SET is not disjoint from HPC_USER — only the SDD subset is.
        """
        sdd_mutations = frozenset({
            "start_sdd_session", "record_sdd_step", "complete_sdd_session",
        })
        # SDD mutations must be absent from CI_READONLY
        assert sdd_mutations.isdisjoint(CI_READONLY), (
            f"SDD mutations in CI_READONLY: {sdd_mutations & CI_READONLY}"
        )
        # SDD mutations must be absent from HPC_USER
        assert sdd_mutations.isdisjoint(HPC_USER), (
            f"SDD mutations in HPC_USER: {sdd_mutations & HPC_USER}"
        )
        # SDD mutations must be a subset of MUTATION_TOOL_SET
        assert sdd_mutations <= MUTATION_TOOL_SET

    def test_path_b_section_10_structure_preserved(self):
        """Path B §10 C-IMPACT-2 structural contract (R5.5).

        Validates all three structural properties carried from Path B §10:
        1. Explicit enumeration — sets are frozenset literals, not dynamic.
        2. Default-deny — ALLOWED_TOOL_SETS has exactly the two JWT scopes.
        3. MUTATION_TOOL_SET SDD tools excluded from both JWT scopes.
        """
        # Property 1: sets are frozenset (compile-time, not dynamic)
        assert isinstance(CI_READONLY, frozenset)
        assert isinstance(HPC_USER, frozenset)
        assert isinstance(MUTATION_TOOL_SET, frozenset)
        assert isinstance(HPC_USER_ADDITIONS, frozenset)

        # Property 2: only two JWT scopes in the lookup table
        assert set(ALLOWED_TOOL_SETS.keys()) == {"mcp/ci-readonly", "mcp/hpc-user"}

        # Property 3: SDD session management excluded from both
        sdd_mutations = frozenset({
            "start_sdd_session", "record_sdd_step", "complete_sdd_session",
        })
        for scope_name, tool_set in ALLOWED_TOOL_SETS.items():
            overlap = sdd_mutations & tool_set
            assert overlap == frozenset(), (
                f"SDD mutations leak into {scope_name}: {overlap}"
            )


# ---------------------------------------------------------------------------
# ToolAccessDeniedError properties
# ---------------------------------------------------------------------------


class TestPythonRuntimeReDerivation:
    """Task 5.3a / R5.6: verify per-scope counts match the live Python runtime.

    Path B's "CI 40 / HPC 48 / developer 51" was derived against the retired Node
    runtime (51 tools).  The active runtime is Python with 53 tools.  These tests
    pin the re-derived counts and ensure every tool is classified in at least one
    scope, leaving none unclassified.

    The RUNTIME_TOOL_COUNT constant is the single source of truth for the expected
    tool count.  If the runtime gains or loses tools, update it — the test will
    surface the drift immediately.
    """

    # Pinned against the Python runtime (verified live 2026-08-13 via get_server_info).
    RUNTIME_TOOL_COUNT = 53

    # The complete set of 53 tools in the Python runtime, enumerated from
    # mcp_server_python/src/tools/*.py (Task 5.3a source-of-truth scan).
    ALL_RUNTIME_TOOLS: frozenset[str] = frozenset({
        # Workflow Info (3)
        "get_workflow_structure", "get_system_configs", "describe_component",
        # Code Analysis (6)
        "analyze_code_structure", "find_dependencies", "trace_execution_path",
        "find_callers_callees", "trace_full_execution_chain", "find_env_dependencies",
        # Semantic Search (8)
        "search_documentation", "find_related_files", "explain_with_context",
        "get_knowledge_base_status", "check_knowledge_integrity",
        "list_ingested_urls", "get_ingested_urls_array", "list_all_sources",
        # EE2 Compliance (5)
        "search_ee2_standards", "analyze_ee2_compliance", "generate_compliance_report",
        "scan_repository_compliance", "extract_code_for_analysis",
        # Operational (4)
        "get_operational_guidance", "explain_workflow_component",
        "list_job_scripts", "get_job_details",
        # GraphRAG (9)
        "get_code_context", "search_architecture", "find_similar_code",
        "get_change_impact", "trace_data_flow",
        "mark_as_modified", "get_session_context", "checkpoint_state",
        "restore_checkpoint",
        # SDD Workflow (9)
        "list_sdd_workflows", "get_sdd_workflow", "start_sdd_session",
        "record_sdd_step", "get_sdd_session", "complete_sdd_session",
        "get_sdd_execution_history", "validate_sdd_compliance",
        "get_sdd_framework_status",
        # GitHub Integration (4)
        "search_issues", "get_pull_requests",
        "analyze_workflow_dependencies", "analyze_repository_structure",
        # Utility (4)
        "get_server_info", "mcp_health_check", "get_health_trend",
        "get_quality_metrics",
        # Error Analysis (1)
        "extract_ci_error_signal",
    })

    def test_all_runtime_tools_count(self):
        """The enumerated tool list has exactly RUNTIME_TOOL_COUNT entries."""
        assert len(self.ALL_RUNTIME_TOOLS) == self.RUNTIME_TOOL_COUNT

    def test_ci_readonly_count(self):
        """CI_READONLY has 42 tools (re-derived from Python runtime)."""
        assert len(CI_READONLY) == 42

    def test_hpc_user_count(self):
        """HPC_USER has 50 tools (42 CI + 8 additions, re-derived)."""
        assert len(HPC_USER) == 50

    def test_hpc_user_additions_count(self):
        """HPC_USER_ADDITIONS has 8 tools (re-derived)."""
        assert len(HPC_USER_ADDITIONS) == 8

    def test_mutation_tool_set_count(self):
        """MUTATION_TOOL_SET has 6 tools (re-derived)."""
        assert len(MUTATION_TOOL_SET) == 6

    def test_developer_covers_all_53_tools(self):
        """developer-sigv4 has access to ALL 53 tools (special case, no set)."""
        # HPC_USER | MUTATION_TOOL_SET must equal the full runtime tool set.
        all_classified = HPC_USER | MUTATION_TOOL_SET
        assert all_classified == self.ALL_RUNTIME_TOOLS

    def test_zero_unclassified_tools(self):
        """Every tool in the runtime is in at least one scope (R5.6)."""
        all_classified = HPC_USER | MUTATION_TOOL_SET
        unclassified = self.ALL_RUNTIME_TOOLS - all_classified
        assert unclassified == frozenset(), (
            f"Unclassified tools: {unclassified}"
        )

    def test_no_phantom_tools_in_ci(self):
        """CI_READONLY does not contain tools absent from the runtime."""
        phantom = CI_READONLY - self.ALL_RUNTIME_TOOLS
        assert phantom == frozenset(), f"Phantom tools in CI_READONLY: {phantom}"

    def test_no_phantom_tools_in_hpc(self):
        """HPC_USER does not contain tools absent from the runtime."""
        phantom = HPC_USER - self.ALL_RUNTIME_TOOLS
        assert phantom == frozenset(), f"Phantom tools in HPC_USER: {phantom}"

    def test_no_phantom_tools_in_mutation(self):
        """MUTATION_TOOL_SET does not contain tools absent from the runtime."""
        phantom = MUTATION_TOOL_SET - self.ALL_RUNTIME_TOOLS
        assert phantom == frozenset(), (
            f"Phantom tools in MUTATION_TOOL_SET: {phantom}"
        )

    def test_sdd_mutation_only_count(self):
        """Exactly 3 SDD-only mutation tools are in neither CI nor HPC."""
        sdd_only = MUTATION_TOOL_SET - HPC_USER
        assert len(sdd_only) == 3
        assert sdd_only == frozenset({
            "start_sdd_session", "record_sdd_step", "complete_sdd_session",
        })

    def test_union_equals_runtime_tool_count(self):
        """HPC_USER | MUTATION_TOOL_SET has exactly RUNTIME_TOOL_COUNT tools."""
        assert len(HPC_USER | MUTATION_TOOL_SET) == self.RUNTIME_TOOL_COUNT


# ---------------------------------------------------------------------------
# ToolAccessDeniedError properties
# ---------------------------------------------------------------------------


class TestToolAccessDeniedError:
    """Verify the exception carries the expected fields."""

    def test_fields(self):
        err = ToolAccessDeniedError("mcp/ci-readonly", "mark_as_modified")
        assert err.scope == "mcp/ci-readonly"
        assert err.tool_name == "mark_as_modified"

    def test_message_contains_scope_and_tool(self):
        err = ToolAccessDeniedError("mcp/ci-readonly", "mark_as_modified")
        msg = str(err)
        assert "mcp/ci-readonly" in msg
        assert "mark_as_modified" in msg
