"""Tool-scope authorization guard — Path C (design §5, AD-C3).

Enforces default-deny tool scoping: every tool invocation must be checked
against the caller's scope before execution.  The Allowed_Tool_Set is an
explicit enumeration per scope; any tool not listed is denied, and any
unrecognized scope is denied.

Per-scope counts (re-derived from Python runtime, Task 5.3a / R5.6)
--------------------------------------------------------------------
Enumerated against mcp_server_python/src/tools/*.py (53 tools, 10 modules).
Path B baseline (Node runtime): CI 40, HPC 48, DEV 51.
Path C counts   (Python runtime): CI 42, HPC 50, DEV 53.
Delta vs Node: +list_all_sources (Semantic Search), +extract_ci_error_signal
(Error Analysis).

::

    CI_READONLY:      42 tools  — read-only, safe for CI automation
    HPC_USER:         50 tools  — 42 CI + 8 additions (GitHub + session-state)
    MUTATION_TOOL_SET: 6 tools  — 3 session-state (in HPC) + 3 SDD-only (neither)
    developer-sigv4:  53 tools  — ALL (special case, no set)
    Unclassified:      0

Verification: ``HPC_USER | MUTATION_TOOL_SET`` == 53 (full runtime coverage).
Tests: ``TestPythonRuntimeReDerivation`` in ``tests/unit/test_tool_scope_guard.py``.

Structure inherited from Path B §10 (C-IMPACT-2)
-------------------------------------------------
This module preserves the three structural properties established in Path B
design §10 and carried forward by Path C requirement R5.5:

1. **Explicit enumeration** — every tool in each scope is listed by name in a
   ``frozenset`` literal.  The sets are never derived dynamically from the
   runtime's ``tools/list`` output; additions require a reviewed code change.
2. **Default-deny** — ``check_tool_access`` rejects any tool not in the
   caller's Allowed_Tool_Set *and* any unrecognized scope.  There is no
   "open" fallback.
3. **MUTATION_TOOL_SET excluded from both JWT scopes** — the six mutation
   tools (SDD session management: ``start_sdd_session``, ``record_sdd_step``,
   ``complete_sdd_session``; session-state: ``mark_as_modified``,
   ``checkpoint_state``, ``restore_checkpoint``) are never in CI_READONLY.
   Session-state tools *are* intentionally in HPC_USER (via
   HPC_USER_ADDITIONS, per §10.2), while SDD session management tools are
   excluded from *both* JWT scopes.  Only ``developer-sigv4`` has access to
   all tools, and it is handled as a special case without consulting any set.

Implements Requirements R5.3, R5.4, R5.5, R5.6.
"""
from __future__ import annotations

from .middleware import PrincipalContext

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ToolAccessDeniedError(Exception):
    """Raised when a principal's scope does not permit the requested tool.

    Parameters
    ----------
    scope : str
        The caller's scope.
    tool_name : str
        The tool the caller attempted to invoke.
    """

    def __init__(self, scope: str, tool_name: str) -> None:
        self.scope = scope
        self.tool_name = tool_name
        super().__init__(
            f"scope {scope!r} is not permitted to invoke tool {tool_name!r}"
        )


# ---------------------------------------------------------------------------
# Allowed Tool Sets
# ---------------------------------------------------------------------------

# Re-derived against the live Python runtime (53 tools) per R5.6 / Task 5.3a.
# Path B baseline: CI 40, HPC 48, DEV 51 (Node runtime).
# Path C counts:   CI 42, HPC 50, DEV 53 (Python runtime).
# Delta: +list_all_sources (Semantic Search), +extract_ci_error_signal (Error Analysis).

CI_READONLY: frozenset[str] = frozenset({
    # Workflow Info (3)
    "get_workflow_structure", "get_system_configs", "describe_component",
    # Code Analysis (6)
    "analyze_code_structure", "find_dependencies", "trace_execution_path",
    "find_callers_callees", "trace_full_execution_chain", "find_env_dependencies",
    # Semantic Search (8) — list_all_sources added in Python (was missing in Node baseline)
    "search_documentation", "find_related_files", "explain_with_context",
    "get_knowledge_base_status", "list_ingested_urls", "get_ingested_urls_array",
    "check_knowledge_integrity", "list_all_sources",
    # EE2 Compliance (5)
    "search_ee2_standards", "analyze_ee2_compliance", "generate_compliance_report",
    "scan_repository_compliance", "extract_code_for_analysis",
    # Operational (4)
    "get_operational_guidance", "explain_workflow_component", "list_job_scripts",
    "get_job_details",
    # GraphRAG — read-only subset (5)
    "get_code_context", "search_architecture", "find_similar_code",
    "get_change_impact", "trace_data_flow",
    # SDD Workflows — read-only subset (6)
    "list_sdd_workflows", "get_sdd_workflow", "get_sdd_session",
    "get_sdd_execution_history", "validate_sdd_compliance", "get_sdd_framework_status",
    # Utility (4)
    "get_server_info", "mcp_health_check", "get_health_trend", "get_quality_metrics",
    # Error Analysis (1) — new Python-only module
    "extract_ci_error_signal",
})

MUTATION_TOOL_SET: frozenset[str] = frozenset({
    "mark_as_modified", "checkpoint_state", "restore_checkpoint",
    "start_sdd_session", "record_sdd_step", "complete_sdd_session",
})

HPC_USER_ADDITIONS: frozenset[str] = frozenset({
    # GraphRAG session-state tools (HPC users need session continuity)
    "mark_as_modified", "get_session_context", "checkpoint_state", "restore_checkpoint",
    # GitHub Integration (4) — excluded from CI, available to HPC
    "search_issues", "get_pull_requests", "analyze_workflow_dependencies",
    "analyze_repository_structure",
})

HPC_USER: frozenset[str] = CI_READONLY | HPC_USER_ADDITIONS

ALLOWED_TOOL_SETS: dict[str, frozenset[str]] = {
    "mcp/ci-readonly": CI_READONLY,
    "mcp/hpc-user": HPC_USER,
}

# The developer-sigv4 scope is NOT in this dict — it is handled as a special
# case in check_tool_access (all tools allowed, no enumeration needed).
_DEVELOPER_SCOPE = "developer-sigv4"


# ---------------------------------------------------------------------------
# Guard function
# ---------------------------------------------------------------------------


def check_tool_access(ctx: PrincipalContext, tool_name: str) -> None:
    """Check whether the principal is permitted to invoke the named tool.

    Implements default-deny: if the scope is not recognized or the tool is not
    in the scope's Allowed_Tool_Set, the call is rejected.

    Parameters
    ----------
    ctx : PrincipalContext
        The request-scoped principal identity (from ``derive_principal``).
    tool_name : str
        The MCP tool name being invoked.

    Raises
    ------
    ToolAccessDeniedError
        If the principal's scope does not permit the tool.
    """
    # Developer-sigv4 has access to ALL tools (R5.2, R5.5).
    if ctx.scope == _DEVELOPER_SCOPE:
        return

    allowed = ALLOWED_TOOL_SETS.get(ctx.scope)
    if allowed is None:
        # Unrecognized scope — defense in depth.  The middleware should have
        # already rejected this, but we enforce here as well (R5.4).
        raise ToolAccessDeniedError(ctx.scope, tool_name)

    if tool_name not in allowed:
        # Tool not in this scope's Allowed_Tool_Set (R5.3).
        raise ToolAccessDeniedError(ctx.scope, tool_name)
