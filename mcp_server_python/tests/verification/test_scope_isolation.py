"""Task 6.3 — Scope Isolation (inherited Path B Property 3).

Verifies that CI-scoped and HPC-scoped principals are denied access to tools
outside their respective Allowed_Tool_Sets.  This is the complement of
Property 6 (developer gets all 53): here we prove the JWT scopes are properly
*bounded*.

Concrete assertions
-------------------
- CI (``mcp/ci-readonly``) is denied on all 6 ``MUTATION_TOOL_SET`` tools.
- CI is denied on exactly 11 tools total (53 − 42 = 11).
- HPC (``mcp/hpc-user``) is denied on exactly 3 tools (the SDD-only mutations).
- Cross-scope spot checks: CI cannot call ``search_issues`` (GitHub/HPC-only);
  HPC cannot call ``start_sdd_session`` (SDD mutation, developer-only).

Run::

    cd /mdc-mcp-rag/eib-mcp-rag-server
    python -m pytest mcp_server_python/tests/verification/test_scope_isolation.py -v

Requirements: R5.3; inherited Path B Property 3.
"""
from __future__ import annotations

import pytest

from src.auth.middleware import PrincipalContext
from src.auth.tool_scope_guard import (
    CI_READONLY,
    HPC_USER,
    MUTATION_TOOL_SET,
    ToolAccessDeniedError,
    check_tool_access,
)

# Re-use the canonical 53-tool enumeration from the unit tests (Task 5.3a).
from tests.unit.test_tool_scope_guard import TestPythonRuntimeReDerivation

ALL_RUNTIME_TOOLS: frozenset[str] = TestPythonRuntimeReDerivation.ALL_RUNTIME_TOOLS
RUNTIME_TOOL_COUNT: int = TestPythonRuntimeReDerivation.RUNTIME_TOOL_COUNT

# ---------------------------------------------------------------------------
# Derived sets — computed once at module level for parametrize
# ---------------------------------------------------------------------------

# Tools outside CI_READONLY (53 − 42 = 11 expected).
CI_DENIED_TOOLS: frozenset[str] = ALL_RUNTIME_TOOLS - CI_READONLY

# Tools outside HPC_USER (53 − 50 = 3 expected — the SDD-only mutations).
HPC_DENIED_TOOLS: frozenset[str] = ALL_RUNTIME_TOOLS - HPC_USER


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ci_ctx() -> PrincipalContext:
    """Build a CI-scoped principal context."""
    return PrincipalContext(
        principal="ci-readonly",
        scope="mcp/ci-readonly",
        broker_request_id="br-scope-isolation-ci",
    )


def _hpc_ctx() -> PrincipalContext:
    """Build an HPC-scoped principal context."""
    return PrincipalContext(
        principal="hpc-user",
        scope="mcp/hpc-user",
        broker_request_id="br-scope-isolation-hpc",
    )


# ---------------------------------------------------------------------------
# CI scope — denied on all 6 MUTATION_TOOL_SET tools (R5.3, R5.5)
# ---------------------------------------------------------------------------


class TestCIDeniedOnMutationToolSet:
    """CI-scoped principal is denied on every tool in MUTATION_TOOL_SET."""

    @pytest.mark.parametrize("tool_name", sorted(MUTATION_TOOL_SET))
    def test_ci_denied_mutation_tool(self, tool_name: str):
        """check_tool_access(ci_ctx, {tool_name}) raises ToolAccessDeniedError."""
        with pytest.raises(ToolAccessDeniedError) as exc_info:
            check_tool_access(_ci_ctx(), tool_name)
        assert exc_info.value.scope == "mcp/ci-readonly"
        assert exc_info.value.tool_name == tool_name

    def test_all_6_mutation_tools_denied_for_ci(self):
        """Bulk assertion: all 6 mutation tools are denied for CI scope."""
        denied = set()
        for tool_name in MUTATION_TOOL_SET:
            try:
                check_tool_access(_ci_ctx(), tool_name)
            except ToolAccessDeniedError:
                denied.add(tool_name)
        assert denied == MUTATION_TOOL_SET, (
            f"Expected all 6 mutation tools denied; "
            f"allowed: {MUTATION_TOOL_SET - denied}"
        )


# ---------------------------------------------------------------------------
# CI scope — denied on all tools outside CI_READONLY (11 tools)
# ---------------------------------------------------------------------------


class TestCIDeniedOutsideCIReadonly:
    """CI-scoped principal is denied on every tool NOT in CI_READONLY.

    53 total − 42 CI_READONLY = 11 denied tools.
    """

    @pytest.mark.parametrize("tool_name", sorted(CI_DENIED_TOOLS))
    def test_ci_denied_excluded_tool(self, tool_name: str):
        """check_tool_access(ci_ctx, {tool_name}) raises ToolAccessDeniedError."""
        with pytest.raises(ToolAccessDeniedError) as exc_info:
            check_tool_access(_ci_ctx(), tool_name)
        assert exc_info.value.scope == "mcp/ci-readonly"
        assert exc_info.value.tool_name == tool_name

    def test_ci_denied_count_is_11(self):
        """Exactly 11 tools are denied for CI scope (53 − 42 = 11)."""
        assert len(CI_DENIED_TOOLS) == 11, (
            f"Expected 11 denied tools for CI, got {len(CI_DENIED_TOOLS)}: "
            f"{sorted(CI_DENIED_TOOLS)}"
        )

    def test_ci_denied_tools_exhaustive(self):
        """Bulk assertion: iterate all 53 tools, count denied, assert 11."""
        denied = set()
        for tool_name in ALL_RUNTIME_TOOLS:
            try:
                check_tool_access(_ci_ctx(), tool_name)
            except ToolAccessDeniedError:
                denied.add(tool_name)
        assert denied == CI_DENIED_TOOLS
        assert len(denied) == 11


# ---------------------------------------------------------------------------
# HPC scope — denied on tools outside HPC_USER (3 tools)
# ---------------------------------------------------------------------------


class TestHPCDeniedOutsideHPCUser:
    """HPC-scoped principal is denied on every tool NOT in HPC_USER.

    53 total − 50 HPC_USER = 3 denied tools (the SDD-only mutations).
    """

    @pytest.mark.parametrize("tool_name", sorted(HPC_DENIED_TOOLS))
    def test_hpc_denied_excluded_tool(self, tool_name: str):
        """check_tool_access(hpc_ctx, {tool_name}) raises ToolAccessDeniedError."""
        with pytest.raises(ToolAccessDeniedError) as exc_info:
            check_tool_access(_hpc_ctx(), tool_name)
        assert exc_info.value.scope == "mcp/hpc-user"
        assert exc_info.value.tool_name == tool_name

    def test_hpc_denied_count_is_3(self):
        """Exactly 3 tools are denied for HPC scope (53 − 50 = 3)."""
        assert len(HPC_DENIED_TOOLS) == 3, (
            f"Expected 3 denied tools for HPC, got {len(HPC_DENIED_TOOLS)}: "
            f"{sorted(HPC_DENIED_TOOLS)}"
        )

    def test_hpc_denied_tools_are_sdd_mutations(self):
        """The 3 HPC-denied tools are exactly the SDD session management mutations."""
        expected_sdd_only = frozenset({
            "start_sdd_session", "record_sdd_step", "complete_sdd_session",
        })
        assert HPC_DENIED_TOOLS == expected_sdd_only

    def test_hpc_denied_exhaustive(self):
        """Bulk assertion: iterate all 53 tools, count denied, assert 3."""
        denied = set()
        for tool_name in ALL_RUNTIME_TOOLS:
            try:
                check_tool_access(_hpc_ctx(), tool_name)
            except ToolAccessDeniedError:
                denied.add(tool_name)
        assert denied == HPC_DENIED_TOOLS
        assert len(denied) == 3


# ---------------------------------------------------------------------------
# Cross-scope spot checks (Task 6.3 item 4)
# ---------------------------------------------------------------------------


class TestCrossScopeSpotChecks:
    """Explicit cross-scope assertions for representative tools."""

    def test_ci_cannot_call_search_issues(self):
        """search_issues is GitHub/HPC-only — CI is denied."""
        with pytest.raises(ToolAccessDeniedError) as exc_info:
            check_tool_access(_ci_ctx(), "search_issues")
        assert exc_info.value.tool_name == "search_issues"

    def test_ci_cannot_call_get_pull_requests(self):
        """get_pull_requests is GitHub/HPC-only — CI is denied."""
        with pytest.raises(ToolAccessDeniedError):
            check_tool_access(_ci_ctx(), "get_pull_requests")

    def test_ci_cannot_call_analyze_workflow_dependencies(self):
        """analyze_workflow_dependencies is GitHub/HPC-only — CI is denied."""
        with pytest.raises(ToolAccessDeniedError):
            check_tool_access(_ci_ctx(), "analyze_workflow_dependencies")

    def test_ci_cannot_call_analyze_repository_structure(self):
        """analyze_repository_structure is GitHub/HPC-only — CI is denied."""
        with pytest.raises(ToolAccessDeniedError):
            check_tool_access(_ci_ctx(), "analyze_repository_structure")

    def test_ci_cannot_call_get_session_context(self):
        """get_session_context is an HPC addition — CI is denied."""
        with pytest.raises(ToolAccessDeniedError):
            check_tool_access(_ci_ctx(), "get_session_context")

    def test_hpc_cannot_call_start_sdd_session(self):
        """start_sdd_session is SDD mutation, developer-only — HPC is denied."""
        with pytest.raises(ToolAccessDeniedError) as exc_info:
            check_tool_access(_hpc_ctx(), "start_sdd_session")
        assert exc_info.value.tool_name == "start_sdd_session"

    def test_hpc_cannot_call_record_sdd_step(self):
        """record_sdd_step is SDD mutation, developer-only — HPC is denied."""
        with pytest.raises(ToolAccessDeniedError):
            check_tool_access(_hpc_ctx(), "record_sdd_step")

    def test_hpc_cannot_call_complete_sdd_session(self):
        """complete_sdd_session is SDD mutation, developer-only — HPC is denied."""
        with pytest.raises(ToolAccessDeniedError):
            check_tool_access(_hpc_ctx(), "complete_sdd_session")

    def test_hpc_can_call_search_issues(self):
        """Positive control: HPC CAN call search_issues (contrast with CI)."""
        check_tool_access(_hpc_ctx(), "search_issues")

    def test_ci_can_call_search_documentation(self):
        """Positive control: CI CAN call search_documentation."""
        check_tool_access(_ci_ctx(), "search_documentation")

    def test_ci_can_call_extract_ci_error_signal(self):
        """Positive control: CI CAN call the Python-only error analysis tool."""
        check_tool_access(_ci_ctx(), "extract_ci_error_signal")


# ---------------------------------------------------------------------------
# Count assertions — summary (Task 6.3 item 5)
# ---------------------------------------------------------------------------


class TestScopeIsolationCountSummary:
    """Pin the exact denied-tool counts for both JWT scopes as documented in
    Task 6.3: CI denied exactly 11, HPC denied exactly 3."""

    def test_ci_denied_exactly_11(self):
        """CI scope: 53 total − 42 allowed = 11 denied."""
        ctx = _ci_ctx()
        denied_count = sum(
            1 for t in ALL_RUNTIME_TOOLS
            if _is_denied(ctx, t)
        )
        assert denied_count == 11, f"CI denied {denied_count}, expected 11"

    def test_hpc_denied_exactly_3(self):
        """HPC scope: 53 total − 50 allowed = 3 denied."""
        ctx = _hpc_ctx()
        denied_count = sum(
            1 for t in ALL_RUNTIME_TOOLS
            if _is_denied(ctx, t)
        )
        assert denied_count == 3, f"HPC denied {denied_count}, expected 3"

    def test_ci_allowed_exactly_42(self):
        """Complement check: CI scope allows exactly 42 tools."""
        ctx = _ci_ctx()
        allowed_count = sum(
            1 for t in ALL_RUNTIME_TOOLS
            if not _is_denied(ctx, t)
        )
        assert allowed_count == 42, f"CI allowed {allowed_count}, expected 42"

    def test_hpc_allowed_exactly_50(self):
        """Complement check: HPC scope allows exactly 50 tools."""
        ctx = _hpc_ctx()
        allowed_count = sum(
            1 for t in ALL_RUNTIME_TOOLS
            if not _is_denied(ctx, t)
        )
        assert allowed_count == 50, f"HPC allowed {allowed_count}, expected 50"

    def test_total_runtime_tools_is_53(self):
        """Sanity: the full runtime has 53 tools."""
        assert len(ALL_RUNTIME_TOOLS) == 53


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _is_denied(ctx: PrincipalContext, tool_name: str) -> bool:
    """Return True if check_tool_access raises ToolAccessDeniedError."""
    try:
        check_tool_access(ctx, tool_name)
        return False
    except ToolAccessDeniedError:
        return True
