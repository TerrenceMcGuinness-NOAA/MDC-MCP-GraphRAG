# Implementation Plan

## Overview

Wire the existing tenancy stack to the tool surface so MCP clients can target
non-default tenants. The resolution machinery (`resolve_tenant`, `_ctx_var`,
adapter prefix-scoping, attribution) is complete; this fix exposes
`tenant_id` on the ~21 tenant-scoped tools and routes it into the ContextVar,
leaving server-global tools untouched.

- **Change 1** — `tenant_scope` async context manager in `resolver.py`.
- **Change 2** — `run_tenant_scoped` helper in a new `_tenant_helper.py`.
- **Change 3** — thread `catalog` into each `register(...)`; add explicit
  `tenant_id` param + `run_tenant_scoped(...)` wrap to each tenant-scoped tool.

TDD ordering (bug-condition methodology): exploration test (1, FAILS on current
code) → helpers (2, 3) → per-module wiring (4–9) → Fix/Preservation/property
tests (10–12) → exploration flips fail→pass (13) → gated live verification (14)
→ checkpoint (15). Pure-test tasks are `[ ]*`. All paths relative to
`/mdc-mcp-rag/eib-mcp-rag-server/`.

References:
- Bugfix: `.kiro/specs/tenant-id-tool-exposure/bugfix.md` (C(X), Fix/Preservation)
- Design: `.kiro/specs/tenant-id-tool-exposure/design.md` (Changes 1–3, Properties 1–5, tool inventory)
- Unblocks: `omd-tenants-2-v17-pilot` Phase C branch-isolation smoke probe

## Tasks

- [ ]* 1. Write the bug condition exploration test (BEFORE any fix)
  - **Property 1: Bug Condition** — Tools Do Not Expose tenant_id / Route to Tenant
  - **CRITICAL**: MUST FAIL on current code — the failure confirms the defect
  - **DO NOT fix the test or code when it fails** — the failure is the success criterion
  - New file `mcp_server_python/tests/unit/test_tenant_tool_exposure.py`
  - **Case 1 — schema**: register tools on a FastMCP test instance; introspect `search_documentation`'s input schema; assert a `tenant_id` field exists. FAILS today (no such field)
  - **Case 2 — routing**: drive a tenant-scoped tool with a stub `UnifiedDataAccess` recording the index/labels requested, call with `tenant_id="gw_v17"`, assert the recorded index startswith `gw_v17_`. FAILS today (always resolves to gw / unprefixed)
  - Run on current code → **EXPECTED: FAILS**. Document the counterexample
  - If it PASSES unexpectedly, STOP — re-derive the root cause
  - _Requirements: 1.1, 1.2, 1.3, 1.5_

- [ ] 2. Add `tenant_scope` async context manager
  - Per design Change 1. File: `mcp_server_python/src/tenancy/resolver.py`
  - `@asynccontextmanager async def tenant_scope(tenant_id, catalog)`: calls `resolve_tenant(request_tenant_id=tenant_id, catalog=catalog)`, sets `_ctx_var`, yields the ctx, resets in `finally`
  - Raises `UnknownTenantError` on unknown id (caller renders) — do NOT swallow here
  - Keep the existing `tenant_aware` decorator in place (unused by Approach B, retained for compatibility)
  - _Requirements: 2.2, 2.6_

- [ ] 3. Add the `run_tenant_scoped` helper
  - Per design Change 3. New file: `mcp_server_python/src/tools/_tenant_helper.py`
  - `async def run_tenant_scoped(tenant_id, catalog, coro_factory)`: enters `tenant_scope`, awaits `coro_factory()`, returns `attribute(body, ctx.tenant)`; on `UnknownTenantError` returns `f"[ERROR] {e}"` (R2.5, no fallback)
  - _Requirements: 2.2, 2.4, 2.5_

  - [ ]* 3.1 Unit tests for `tenant_scope` and `run_tenant_scoped`
    - `tenant_scope` sets `_ctx_var` to the resolved ctx inside, resets to prior outside
    - `run_tenant_scoped` returns attributed body for a valid tenant; returns `[ERROR] ...` naming known ids for an unknown tenant; makes no adapter calls on the unknown path
    - File: `mcp_server_python/tests/unit/test_tenant_helper.py` (new)
    - _Requirements: 2.2, 2.4, 2.5_

- [ ] 4. Thread `catalog` into `register(...)` across tool modules
  - Per design Change 2. Add `catalog: TenantCatalog | None = None` to the `register(mcp, data, ...)` signature of each module that has tenant-scoped tools; default via `get_catalog()` (from `src/tenancy/runtime.py`)
  - Files: `semantic_search.py`, `code_analysis.py`, `graph_rag.py`, `operational.py`, `ee2_compliance.py`, `workflow_info.py`
  - Update `src/mcp_server.py` to pass the loaded catalog to each `register_*` call (explicit threading)
  - _Requirements: 2.2_

- [ ] 5. Wire `semantic_search` tenant-scoped tools
  - Add `tenant_id: str | None = None` + `run_tenant_scoped(...)` wrap to: search_documentation, find_related_files, explain_with_context, get_knowledge_base_status, check_knowledge_integrity
  - File: `mcp_server_python/src/tools/semantic_search.py`
  - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [ ] 6. Wire `code_analysis` tenant-scoped tools
  - Add `tenant_id` + wrap to all 6: analyze_code_structure, find_dependencies, trace_execution_path, find_callers_callees, trace_full_execution_chain, find_env_dependencies
  - File: `mcp_server_python/src/tools/code_analysis.py`
  - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [ ] 7. Wire `graph_rag` tenant-scoped tools (data tools only)
  - Add `tenant_id` + wrap to: get_code_context, search_architecture, find_similar_code, get_change_impact, trace_data_flow
  - Do NOT modify the session tools: mark_as_modified, get_session_context, checkpoint_state, restore_checkpoint (Server_Global per design inventory)
  - File: `mcp_server_python/src/tools/graph_rag.py`
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.2_

- [ ] 8. Wire `operational` tenant-scoped tools
  - Add `tenant_id` + wrap to: get_operational_guidance, explain_workflow_component, list_job_scripts, get_job_details
  - File: `mcp_server_python/src/tools/operational.py`
  - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [ ] 9. Wire `ee2_compliance` + `workflow_info` tenant-scoped tools
  - `ee2_compliance`: add `tenant_id` + wrap to search_ee2_standards ONLY. Do NOT modify analyze_ee2_compliance / generate_compliance_report / scan_repository_compliance / extract_code_for_analysis (operate on passed-in content — Server_Global per inventory)
  - `workflow_info`: add `tenant_id` + wrap to describe_component, get_workflow_structure, get_system_configs (they read `tenant.workflow_root`)
  - Files: `mcp_server_python/src/tools/ee2_compliance.py`, `mcp_server_python/src/tools/workflow_info.py`
  - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [ ]* 10. Write the Fix Checking property/unit test
  - **Property 1: Expected Behavior** — Tenant Routing
  - For a tenant-scoped tool driven with `tenant_id="gw_v17"` against a stub data layer: assert resolved tenant == gw_v17, OpenSearch query used `gw_v17_` index prefix, Neptune query used `GW_V17_` label prefix, attribution header == `*Tenant: gw_v17*`
  - Parametrize across a representative tool from each wired module
  - File: `mcp_server_python/tests/unit/test_tenant_tool_exposure.py`
  - Run on FIXED code → **EXPECTED: PASSES**
  - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [ ]* 11. Write the Schema-Preservation + Server-Global property tests
  - **Property 2 + Property 4**
  - Schema preservation: for each wired tool, assert its input schema contains ALL original params PLUS `tenant_id` (no param lost/renamed)
  - Server-global untouched: for utility/sdd/session/github/content-analysis tools, assert NO `tenant_id` in schema
  - File: `mcp_server_python/tests/unit/test_tenant_tool_exposure.py`
  - Run on FIXED code → **EXPECTED: PASSES**
  - _Requirements: 2.1, 3.2_

- [ ]* 12. Write the Default-Preservation + Unknown-Tenant tests
  - **Property 3 + Property 5**
  - Default preservation: call a tenant-scoped tool WITHOUT `tenant_id` → resolves gw, unprefixed index/labels, `*Tenant: gw*` header (identical to pre-fix)
  - Unknown tenant: call with `tenant_id="nope"` → returns `[ERROR]` naming the unknown id + known ids; zero adapter calls
  - File: `mcp_server_python/tests/unit/test_tenant_tool_exposure.py`
  - Run on FIXED code → **EXPECTED: PASSES**
  - _Requirements: 2.5, 2.6, 3.1, 3.3, 3.4_

- [ ] 13. Verify the exploration test now passes on fixed code
  - **Property 1: Expected Behavior** — tenant_id Exposed and Routing Works
  - Re-run the SAME test from task 1 — do NOT write a new one
  - Run on FIXED code → **EXPECTED: PASSES** (fail→pass flip)
  - Run tasks 10, 11, 12, 3.1 + the existing resolver/adapter/attribution suites; confirm no regressions
  - _Requirements: 2.1, 2.2, 2.3_

- [ ] 14. Gated live verification (OPERATOR-RUN, after image rebuild)
  - This requires the fixed code deployed to the runtime (image rebuild + update-agent-runtime) — a separate gated step
  - **STOP-AND-CONFIRM** before the AWS deploy
  - After deploy: from the MCP client, call `search_documentation("MPAS Voronoi", tenant_id="gw_v17")` → confirm `*Tenant: gw_v17*` and `gw_v17_*` collection hits; call without `tenant_id` → confirm `*Tenant: gw*`
  - Then run `mcp_health_check(functional=True)` → the `branch_isolation` probe can now issue tenant-scoped calls (R2.7)
  - _Requirements: 2.3, 2.4, 2.7_

- [ ] 15. Checkpoint — Ensure all tests pass
  - Confirm task 1 (now passing) + tasks 3.1, 10, 11, 12 pass on fixed code, no regressions
  - Ask the user if questions arise

## Notes

- **One missing wiring step, surgically applied.** The decorator/ContextVar/
  adapter machinery all exist; this fix only attaches `tenant_id` to the tool
  surface and routes it. No change to `resolve_tenant`'s precedence chain.
- **Approach B (explicit param + helper), not the `*args/**kwargs` decorator** —
  preserves each tool's FastMCP schema (design Approach decision).
- **Authoritative tool inventory in the design** governs which tools get
  `tenant_id`. Tasks 5–9 follow it exactly; server-global tools are untouched.
- **Unblocks Gap B validation indirectly**: once tenant_id is reachable, the
  v17-pilot branch-isolation probe (Phase C) can finally exercise gw_v17.
  But graph-traversal tools return nodes-only for gw_v17 until the
  `graph-port-*` series lands (Gap B — separate specs).

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2", "3"] },
    { "id": 2, "tasks": ["3.1", "4"] },
    { "id": 3, "tasks": ["5", "6", "7", "8", "9"] },
    { "id": 4, "tasks": ["10", "11", "12"] },
    { "id": 5, "tasks": ["13"] },
    { "id": 6, "tasks": ["14"] },
    { "id": 7, "tasks": ["15"] }
  ]
}
```
