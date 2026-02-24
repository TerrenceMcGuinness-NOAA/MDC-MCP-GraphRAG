# Phase 32: AI Instruction File Architecture

| Field | Value |
|-------|-------|
| **Version** | v1.0.0 |
| **Status** | ACTIVE |
| **Date** | 2026-02-24 |
| **Execution Mode** | SDD Session (Phase 31 model) |
| **GitHub Issue** | [NOAA-EMC/global-workflow#4578](https://github.com/NOAA-EMC/global-workflow/issues/4578) |
| **Branch** | `update_copilot_instructions` (global-workflow) |

## 1. Problem Statement

The project spans two repositories with five instruction files that overlap, contradict, and fail to gate on MCP availability. AI agents waste context window on irrelevant MCP tool catalogs when no MCP server is connected, and miss critical tool guidance when it is.

### Current State (Problems)

| # | Problem | File | Impact |
|---|---------|------|--------|
| P1 | MCP instructions load unconditionally | `global-workflow/.github/instructions/mcp.instructions.md` | 217 lines of MCP tool docs injected even when no MCP server connected — wastes ~3K tokens |
| P2 | Base instructions reference MCP at top | `global-workflow/.github/copilot-instructions.md` (lines 3-9) | Agent told to "check for MCP tools" even in standalone checkout |
| P3 | Tool counts stale | `mcp.instructions.md` | Says 34 tools / 7 modules; actual is 42 tools / 9 modules |
| P4 | Non-existent tools listed | `mcp.instructions.md` SDD section | `execute_sdd_workflow`, `execute_sdd_workflow_supervised` don't exist |
| P5 | `applyWhen` not in YAML front matter | `eib-mcp-tools.instructions.md` | Copilot may not honor the gate — it's in a comment, not front matter |
| P6 | 8 tools undocumented | `eib-mcp-tools.instructions.md` | Missing: `trace_full_execution_chain`, `extract_code_for_analysis`, `get_job_details`, `analyze_workflow_dependencies`, `get_sdd_execution_history`, `validate_sdd_compliance`, `get_sdd_framework_status`, `list_ingested_urls`/`get_ingested_urls_array` |
| P7 | No instruction file for standalone global-workflow | N/A | When global-workflow is checked out independently (no MCP), no guidance exists for using standard Copilot capabilities |

## 2. Target Architecture

### Design Principles

1. **Conditional loading**: MCP-specific instructions MUST only load when an MCP server is active
2. **Context budget**: Base instructions ≤ 500 lines; MCP overlay ≤ 250 lines; tool reference ≤ 200 lines
3. **SPOT**: Each concern documented in exactly one file — no duplication
4. **Graceful degradation**: Agent must function well without MCP, better with it
5. **Schema compliance**: All front matter uses the [GitHub Copilot instructions schema](https://aka.ms/github-copilot-instructions-schema)

### File Inventory (Target State)

#### In `global-workflow/.github/` (ships with the repo)

| File | Purpose | Loading | Target Lines |
|------|---------|---------|-------------|
| `copilot-instructions.md` | Base global-workflow development guidance | Always (Copilot default) | ~430 |
| `instructions/mcp.instructions.md` | MCP tool catalog & usage patterns | `applyWhen: hasActiveMCPServer("eib-mcp-rag-full")` | ~200 |

#### In `eib-mcp-rag-server/.github/` (MCP dev environment only)

| File | Purpose | Loading | Target Lines |
|------|---------|---------|-------------|
| `copilot-instructions.md` | MCP platform development instructions | Always (Copilot default) | ~220 |
| `instructions/eib-mcp-tools.instructions.md` | Detailed tool parameter reference & workflows | `applyWhen: hasActiveMCPServer("eib-mcp-rag-full")` | ~200 |

### Separation of Concerns

```
┌─────────────────────────────────────────────────────────────────┐
│ Use Case A: global-workflow standalone (GitHub / local clone)   │
│                                                                 │
│  Loaded: copilot-instructions.md ONLY                          │
│  Content: Architecture, code style, patterns, HPC platforms     │
│  MCP content: NONE                                              │
│  Agent behavior: Standard Copilot — read_file, grep, terminal  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ Use Case B: global-workflow + MCP server connected              │
│                                                                 │
│  Loaded: copilot-instructions.md + mcp.instructions.md          │
│  Content: Base + tool catalog, usage patterns, RAG tiers        │
│  Agent behavior: MCP-first for discovery, read_file for detail  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ Use Case C: eib-mcp-rag-server development environment          │
│                                                                 │
│  Loaded: copilot-instructions.md + eib-mcp-tools.instructions   │
│  Content: Platform dev + detailed tool params & SDD session API │
│  Agent behavior: Developing/testing the MCP tools themselves    │
└─────────────────────────────────────────────────────────────────┘
```

## 3. Implementation Steps

### Step 1: Update `global-workflow/.github/copilot-instructions.md`
- **Remove** MCP references from lines 3-9 (the "check for MCP" preamble)
- **Add** a brief note: "If an MCP server is connected, additional tool guidance loads automatically"
- **Keep** all global-workflow-specific content (architecture, patterns, code style, platforms)
- **Verify** line count stays ≤ 500

### Step 2: Update `global-workflow/.github/instructions/mcp.instructions.md`
- **Change** front matter from `applyTo: "**"` to `applyWhen: hasActiveMCPServer("eib-mcp-rag-full")`
- **Update** tool count: 34 → 42, modules: 7 → 9
- **Fix** SDD tools section: remove `execute_sdd_workflow` / `execute_sdd_workflow_supervised`, add actual tools (`start_sdd_session`, `record_sdd_step`, `get_sdd_session`, `complete_sdd_session`, `get_sdd_execution_history`, `validate_sdd_compliance`, `get_sdd_framework_status`)
- **Add** missing tools to their respective module sections
- **Update** version tag from v3.6.2 to v7.20.0
- **Verify** line count stays ≤ 250

### Step 3: Update `eib-mcp-rag-server/.github/instructions/eib-mcp-tools.instructions.md`
- **Convert** `applyWhen` from comment to YAML front matter block
- **Add** 8 missing tools to Quick Reference table and Tool Selection sections
- **Verify** line count stays ≤ 200

### Step 4: Update `eib-mcp-rag-server/.github/copilot-instructions.md`
- **Update** tool count references to 42
- **Update** Tool Modules → Database Dependencies table to include all 9 modules with complete tool lists
- **Update** SDDWorkflowTools entry to reflect actual tools (not the old `execute_sdd_workflow` names)

### Step 5: Validate & Commit
- Verify all `applyWhen` / `applyTo` front matter is correct YAML
- Verify no MCP content leaks into base copilot-instructions files
- Line count audit: each file within budget
- Commit to `update_copilot_instructions` branch in global-workflow
- Commit to `develop` branch in eib-mcp-rag-server
- Record SDD session history

## 4. Validation Criteria

| Check | Expected |
|-------|----------|
| `copilot-instructions.md` (global-workflow) contains zero MCP tool names | Pass |
| `mcp.instructions.md` has `applyWhen` in YAML front matter | Pass |
| `eib-mcp-tools.instructions.md` has `applyWhen` in YAML front matter | Pass |
| All 42 tools documented across mcp.instructions.md + eib-mcp-tools.instructions.md | Pass |
| No tool listed that doesn't exist in `server.registerTool()` calls | Pass |
| `copilot-instructions.md` (global-workflow) ≤ 500 lines | Pass |
| `mcp.instructions.md` ≤ 250 lines | Pass |
| `eib-mcp-tools.instructions.md` ≤ 200 lines | Pass |
| Version references updated to v7.20.0 | Pass |
| GitHub Issue #4578 Definition of Done addressed | Pass |

## 5. Context Window Budget Analysis

| Use Case | Files Loaded | Estimated Tokens |
|----------|-------------|------------------|
| A: Standalone global-workflow | copilot-instructions.md (430 lines) | ~5.5K |
| B: global-workflow + MCP | copilot-instructions.md + mcp.instructions.md (~630 lines) | ~8K |
| C: MCP dev environment | copilot-instructions.md + eib-mcp-tools.instructions.md (~420 lines) | ~5.5K |

**Current state (Use Case A)**: 434 + 217 = 651 lines (~8.5K tokens) loaded even without MCP — **35% waste**.
**Target state (Use Case A)**: 430 lines (~5.5K tokens) — **36% reduction**.

## 6. Dependency: Phase 29 Calling Surface

**Phase 29 Steps 3-4** (Tool Usability — calling surface) may add, rename, or remove MCP tools. If the tool surface changes (tool count ≠ 42, module count ≠ 9, or tool names change), the following files require a corresponding update:

| File | What to update |
|------|----------------|
| `global-workflow/.github/instructions/mcp.instructions.md` | Tool tables per module, total count in header |
| `eib-mcp-rag-server/.github/instructions/eib-mcp-tools.instructions.md` | Quick Reference table, Tool Selection sections |
| `eib-mcp-rag-server/.github/copilot-instructions.md` | Tool Modules → Database Dependencies table |

**Rule**: After any `server.registerTool()` change in `mcp_server_node/src/tools/*.js`, re-run the tool coverage check and update all three files. The ground truth is always the source code.
