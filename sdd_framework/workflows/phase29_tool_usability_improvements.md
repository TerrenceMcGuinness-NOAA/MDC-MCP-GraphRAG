# Phase 29: MCP Tool Usability Improvements
**Version**: 1.1
**Date**: February 24, 2026
**Status**: IN PROGRESS (Steps 1-2 complete, Steps 3-5 actionable)
**Execution Mode**: SDD Session (Phase 31 model — replaces ISD)
**Last Reviewed**: 2026-02-24

---

## Problem Statement

AI agents (including Copilot) frequently fail to use MCP tools correctly due to:
1. **Parameter name mismatches** between instructions and actual tool schemas
2. **Lack of decision guidance** on when to use MCP vs direct file access
3. **No quick reference** for required parameters
4. **Habit bias** toward familiar tools (grep, read_file) over MCP tools

## Objectives

1. Synchronize instruction documentation with actual tool parameter names
2. Add decision tables for tool selection scenarios
3. Create quick-reference parameter tables
4. Optionally: Add parameter aliases in tool code for common mistakes
5. Optionally: Auto-generate documentation from tool schemas

---

## Roadmap Alignment

| Vision Reference | Implementation |
|------------------|----------------|
| SDD Core §Tool Development Pattern | Aligns with health-integrated tool standards |
| Week 2 Tool Consolidation | Extends documentation layer |
| ADVANCED_FUTURE_WORK.md §Developer Experience | New contribution |

**Upstream Dependencies**: Phase 24 (tool architecture), Phase 28 (GraphRAG)
**Downstream Consumers**: All AI agent interactions with MCP server

---

## Implementation Steps

### Step 1: Audit Current Parameter Names ✅ COMPLETE
**Action**: Compare `eib-mcp-tools.instructions.md` against actual tool schemas
**Files**: 
- `mcp_server_node/src/tools/CodeAnalysisTools.js`
- `mcp_server_node/src/tools/GraphRAGTools.js`
- `mcp_server_node/src/tools/WorkflowInfoTools.js`

**Findings**:
| Tool | Instructions Said | Actual Parameter |
|------|-------------------|------------------|
| `find_dependencies` | `file_path` | `target` |
| `get_code_context` | `file_path` | `symbol` |
| `describe_component` | `component_name` | `component` |
| `trace_execution_path` | `entry_point` | `function_name` |
| `get_sdd_workflow` | `phase` | `workflow_id` |

### Step 2: Update Instructions File ✅ COMPLETE (executed before SDD approval)
**Action**: Fix parameter names and add decision tables
**File**: `.github/instructions/eib-mcp-tools.instructions.md`
**Changes**:
- Added "When to Use" decision table
- Added "Quick Reference: Required Parameters" table
- Fixed all tool examples with correct parameter names
- Added "Parameter Naming Conventions" section
- Improved error handling documentation

**NOTE**: This step was executed BEFORE SDD workflow was created. Violated SDD protocol.

### Step 3: Add Parameter Aliases (Optional) ⬜ ACTIONABLE
**Action**: Accept common parameter aliases in tool handlers
**Rationale**: Non-breaking change that improves usability
**Note**: ISD approval gates no longer apply (replaced by Phase 31 SDD sessions). Proceed when prioritized.
**Example**:
```javascript
// In GraphRAGTools.js get_code_context handler
const symbol = args.symbol || args.function_name || args.file_path;
```

**Affected Tools**:
- `find_dependencies`: Accept `file_path` as alias for `target`
- `get_code_context`: Accept `function_name` as alias for `symbol`
- `describe_component`: Accept `component_name` as alias for `component`

### Step 4: Auto-Generate Documentation Script (Optional) ⬜ ACTIONABLE
**Action**: Create script to extract parameter docs from tool schemas
**Output**: Markdown table that can be pasted into instructions
**File**: `mcp_server_node/scripts/generate-tool-docs.js`
**Note**: ISD approval gates no longer apply. This step is especially valuable now — 8 of 42 registered tools are missing from `eib-mcp-tools.instructions.md`:
- `trace_full_execution_chain` (CodeAnalysisTools, added Phase 24F)
- `extract_code_for_analysis` (EE2ComplianceTools)
- `get_job_details` (OperationalTools)
- `analyze_workflow_dependencies` (GitHubTools)
- `get_sdd_execution_history` (SDDWorkflowTools)
- `validate_sdd_compliance` (SDDWorkflowTools)
- `get_sdd_framework_status` (SDDWorkflowTools)
- `list_ingested_urls` / `get_ingested_urls_array` (SemanticSearchTools)

### Step 5: Validate Changes ⬜ PENDING
**Action**: Test that AI agents correctly use tools with updated instructions
**Validation**:
- [ ] MCP tools load successfully (42 tools confirmed registered)
- [ ] Instructions file loads in Copilot context
- [ ] Agent correctly calls tools on first attempt
- [ ] All 42 tools documented in instructions file (currently 34/42)

---

## Execution Log

| Step | Status | Date | Notes |
|------|--------|------|-------|
| 1 | ✅ Complete | 2026-02-11 | Audit completed |
| 2 | ✅ Complete | 2026-02-11 | Executed before SDD spec (pre-Phase 31) |
| 3 | ⬜ Actionable | - | Parameter aliases — ready to implement when prioritized |
| 4 | ⬜ Actionable | - | Auto-gen docs — 8/42 tools missing from instructions |
| 5 | ⬜ Pending | - | Blocked on Step 3/4 completion |

---

## SDD Session Gates

> **Note:** The original ISD Approval Gates (Phase 4B) were replaced by Phase 31's session model. Steps 3-5 no longer require formal gate approval — they are tracked via `start_sdd_session` / `record_sdd_step` / `complete_sdd_session` when executed.

- [x] **Gate 1**: Step 2 changes delivered (retrospective)
- [ ] **Gate 2**: Step 3 (parameter aliases) — implement via SDD session
- [ ] **Gate 3**: Step 4 (auto-generation script) — implement via SDD session
- [ ] **Gate 4**: Final validation sign-off

---

## Rollback Plan

If changes cause issues:
1. Revert `.github/instructions/eib-mcp-tools.instructions.md` to previous version
2. Remove any parameter aliases added to tool handlers
3. Delete `generate-tool-docs.js` if created

---

## Success Criteria

1. AI agents successfully use MCP tools without parameter errors
2. Instructions accurately reflect actual tool schemas
3. Decision guidance reduces fallback to grep/read_file
4. (If Step 4 approved) Documentation stays synchronized with code
