# Separate MCP Instructions from Copilot Instructions

## Summary

This PR refactors the GitHub Copilot instructions by separating MCP-specific guidance into its own file with conditional loading. MCP tool execution instructions are only available to development agents — not exposed to PR review agents.

Since the original PR was opened, the MCP server has evolved significantly: tool count grew from 35 → 48, the knowledge base expanded 4×, and a full GraphRAG layer with session state tracking was added. This PR now includes all instruction file updates through **v7.21.0**.

## Key Design Decision: Separation of MCP Instructions

MCP-specific instructions live in `.github/instructions/mcp.instructions.md` with:
- `applyWhen: hasActiveMCPServer("eib-mcp-rag-full")` — only loads when the MCP server is connected
- `excludeAgent: "code-review"` — PR review agents never see MCP tool guidance

This ensures:
- **PR Review Agents** (GitHub Copilot code review) are NOT exposed to MCP tool execution guidance
- **Development Agents** (VS Code Copilot, Copilot CLI, Claude Desktop) GET full MCP tool access with correct parameter names
- ~35% context window reduction for standalone global-workflow use (no MCP server)
- Prevents PR review agents from attempting to invoke MCP tools they don't have access to

## Changes

- **New**: `.github/instructions/mcp.instructions.md` — MCP server tool guide (v7.21.0, 48 tools, excluded from code-review agent)
- **Updated**: `.github/copilot-instructions.md` — Removed MCP details, added guidance to check for MCP tool availability

## What's Included

### MCP Server Integration (v7.21.0)
- **9 tool modules** with **48 total tools**
- RAG-powered semantic search across **63,837 indexed documents** (5 ChromaDB collections)
- Neo4j code graph analysis (**41,355 nodes**, **589,396 relationships**)
- GraphRAG with Graph-Guided Semantic Retrieval (GGSR) and hierarchical communities (1,036 nodes across 4 levels)
- Session state tracking for agent workflows (checkpoints, modification tracking, examined symbol deduplication)
- EE2 compliance validation with Phase 2 SME-corrected anti-patterns
- SDD workflow execution framework (38 phase specs, 12 completed sessions)

### Tool Categories

| Category | Tools | Purpose |
|----------|-------|---------|
| Workflow Info | 3 | Static filesystem analysis (structure, configs, components) |
| Code Analysis | 6 | Neo4j graph traversal (dependencies, callers, execution chains) |
| Semantic Search | 6 | ChromaDB vector + graph hybrid queries |
| EE2 Compliance | 5 | NOAA NCO standards validation (SME-corrected) |
| Operational | 4 | HPC platform guidance and job script analysis |
| GraphRAG + Session State | 9 | GGSR context, architecture search, impact analysis, session tracking |
| GitHub Integration | 4 | Cross-repo issue/PR/dependency analysis |
| SDD Workflows | 9 | Spec-driven development session orchestration |
| Utility | 2 | Health check and server info |

### Parameter Naming Conventions

The instruction file documents **exact required parameter names** for each tool to prevent `"must have required property"` errors. Common patterns:
- Graph tools use `symbol` (not `node_name`, `function_name`, etc.)
- Search tools use `query` (not `search_term`, `keyword`, etc.)
- Aliases supported for backward compatibility (e.g., `node_name` → `symbol`)

## Commit History

| Commit | Description |
|--------|-------------|
| `8b597625` | Initial: Add MCP server integration instructions |
| `c309c32f` | Refactor for conditional MCP loading (`applyWhen` + `excludeAgent`) |
| `2c9c8060` | Fix GraphRAG tool parameter names in Required Param column |
| `35bec79d` | Sync with v7.21.0 — add 4 Phase 24H-3 session state tools (48 total) |

## Benefits

- AI agents can search **63,837 indexed documents** across 5 collections (15/16 SPOT documentation sources)
- Code dependency analysis across **41,355 graph nodes** with **589,396 relationships**
- **1,036 hierarchical community nodes** enable multi-resolution architecture queries
- Automated EE2 compliance checking before commits (SME-validated, 85% false positive reduction)
- Session state tracking enables cross-modality handoff between IDE and CLI agents
- Context-aware explanations using Graph-Guided Semantic Retrieval (GGSR)

## Testing

- MCP health check: **7/7 components healthy**
- `generate-tool-docs.js --check`: **48/48 tools documented, 0 warnings**
- All tool modules operational across full/core/rag/github scenarios
- Knowledge base validated with targeted GraphRAG queries
- Instruction file aligned across all 3 locations (copilot-instructions.md, eib-mcp-tools.instructions.md, mcp.instructions.md)
