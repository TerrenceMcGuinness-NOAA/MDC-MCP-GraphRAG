---
applyWhen: hasActiveMCPServer("eib-mcp-rag-full") || hasActiveMCPServer("eib-mcp-gateway")
---

# EIB MCP Tool Usage Instructions (48 tools / 9 modules)

## MCP-First Policy

When an EIB MCP server is connected (`eib-mcp-rag-full` or `eib-mcp-gateway`), **always prefer MCP tools over shell commands** for code analysis, documentation search, and compliance checking.

### When to Use MCP Tools vs Direct File Access

| Scenario | Use MCP Tool | Use read_file/grep |
|----------|--------------|-------------------|
| "What does this file do?" | `analyze_code_structure` | ❌ |
| "What calls this function?" | `find_callers_callees` | ❌ |
| "How does X subsystem work?" | `search_architecture` | ❌ |
| "Find files related to X" | `find_related_files` | ❌ |
| "Show me line 45-100 of file.py" | ❌ | `read_file` |
| "What's the exact syntax here?" | ❌ | `read_file` |
| "Search for literal string 'FOO'" | ❌ | `grep_search` |

**Best practice**: Start with MCP tools for discovery, then use `read_file` for specific line-level details.

## Quick Reference: Required Parameters (auto-generated)

<!-- Regenerate with: cd mcp_server_node && node scripts/generate-tool-docs.js -->

These are the **exact parameter names** — using wrong names will fail:

| Tool | Required Param | Optional Params |
|------|----------------|-----------------|
| **Workflow Info (3 — Filesystem)** | | |
| `get_workflow_structure` | *(none)* | `component`, `structure_data` |
| `get_system_configs` | *(none)* | `platform`, `config_type`, `content` |
| `describe_component` | `component` | `show_content`, `content`, `file_type` |
| **Code Analysis (6 — Neo4j)** | | |
| `analyze_code_structure` | `file_path` | `include_dependencies`, `depth`, `token_budget` |
| `find_dependencies` | `target` | `direction`, `max_depth`, `token_budget` |
| `trace_execution_path` | `function_name` | `file_path`, `max_depth`, `include_callers`, `include_weights`, `token_budget` |
| `find_callers_callees` | `function_name` | `file_path`, `include_source`, `token_budget`, `cross_language` |
| `trace_full_execution_chain` | `start` | `direction`, `max_depth`, `languages` |
| `find_env_dependencies` | `variable_name` | `show_exports`, `limit`, `token_budget` |
| **Semantic Search (6 — ChromaDB + Neo4j)** | | |
| `search_documentation` | `query` | `collection`, `max_results`, `include_graph`, `similarity_threshold` |
| `find_related_files` | `file_path` | `max_results`, `include_documentation` |
| `explain_with_context` | `topic` | `context_type`, `detail_level` |
| `get_knowledge_base_status` | *(none)* | `include_graph`, `include_vector` |
| `list_ingested_urls` | *(none)* | `format`, `source_filter` |
| `get_ingested_urls_array` | *(none)* | `include_failed` |
| **EE2 Compliance (5 — ChromaDB)** | | |
| `search_ee2_standards` | `query` | `category`, `max_results`, `include_examples` |
| `analyze_ee2_compliance` | `content` | `analysis_type`, `include_recommendations` |
| `generate_compliance_report` | *(none)* | `scope`, `categories`, `format` |
| `scan_repository_compliance` | `name`, `content` | `files`, `path`, `repository_path`, `file_patterns`, `sample_size`, `categories` |
| `extract_code_for_analysis` | `name`, `content` | `files`, `path`, `content_type`, `categories`, `file_pattern`, `max_files` |
| **Operational (4 — ChromaDB)** | | |
| `get_operational_guidance` | `operation` | `platform`, `urgency` |
| `explain_workflow_component` | `component` | `detail_level` |
| `list_job_scripts` | *(none)* | `category`, `search`, `format`, `job_list`, `files`, `name`, `content` |
| `get_job_details` | `job_name` | `include_content`, `include_config`, `include_chromadb` |
| **GraphRAG (9 — ChromaDB + Neo4j)** | | |
| `get_code_context` | `symbol` | `depth`, `include_community`, `token_budget` |
| `search_architecture` | `query` | `max_results` |
| `find_similar_code` | `code_or_symbol` | `similarity_threshold`, `max_results` |
| `get_change_impact` | `symbol` | `change_type`, `include_indirect` |
| `trace_data_flow` | `from_symbol` | `to_symbol`, `max_depth` |
| `mark_as_modified` | `file_path` | `change_type`, `description` |
| `get_session_context` | *(none)* | `include_dirty` |
| `checkpoint_state` | `name` | `description` |
| `restore_checkpoint` | `checkpoint_id` | *(none)* |
| **GitHub (4 — GitHub API)** | | |
| `analyze_workflow_dependencies` | `component` | `analysis_type`, `include_external` |
| `search_issues` | `query` | `repository`, `state`, `labels` |
| `get_pull_requests` | *(none)* | `repository`, `state`, `limit` |
| `analyze_repository_structure` | *(none)* | `repositories`, `analysis_depth` |
| **SDD Workflows (9 — Filesystem)** | | |
| `list_sdd_workflows` | *(none)* | `include_metadata` |
| `get_sdd_workflow` | `workflow_name` | *(none)* |
| `start_sdd_session` | `phase` | `notes`, `total_steps` |
| `record_sdd_step` | `step`, `name` | `tag`, `notes` |
| `get_sdd_session` | *(none)* | `resume` |
| `complete_sdd_session` | *(none)* | `summary`, `abandon`, `reason` |
| `get_sdd_execution_history` | *(none)* | `limit`, `workflow_name` |
| `validate_sdd_compliance` | *(none)* | `content`, `target`, `framework_version`, `content_type` |
| `get_sdd_framework_status` | *(none)* | `detailed` |
| **Utility (2 — Built-in)** | | |
| `get_server_info` | *(none)* | `include_capabilities` |
| `mcp_health_check` | *(none)* | `detailed`, `deep`, `functional` |

## Tool Selection by Task

### Code Structure & Dependencies (Neo4j-backed)
- `analyze_code_structure({ file_path })` — AST-level analysis of any file
- `find_dependencies({ target })` — upstream/downstream import graph
- `find_callers_callees({ function_name })` — call graph traversal
- `find_env_dependencies({ variable_name })` — environment variable lineage
- `trace_execution_path({ function_name })` — execution flow tracing
- `trace_full_execution_chain({ start })` — end-to-end execution chain across files

### Semantic Search & RAG (ChromaDB-backed)
- `search_documentation({ query })` — semantic search across ingested docs
- `explain_with_context({ topic })` — RAG-powered explanations with citations
- `find_related_files({ file_path })` — vector similarity for related code/docs
- `get_knowledge_base_status()` — DB health and collection stats
- `list_ingested_urls()` — documentation sources ingested into RAG
- `get_ingested_urls_array()` — structured URL array for programmatic access

### GraphRAG (Combined Neo4j + ChromaDB)
- `get_code_context({ symbol })` — GGSR neighborhood + community summary
- `search_architecture({ query })` — semantic search over community summaries
- `find_similar_code({ code_or_symbol })` — vector similarity + graph enrichment
- `get_change_impact({ symbol })` — blast radius with risk scoring
- `trace_data_flow({ from_symbol })` — data flow across codebase

### Session State (Phase 24H-3 — registered in GraphRAGTools)
- `mark_as_modified({ file_path })` — track file changes in active session + flag Neo4j nodes dirty
- `get_session_context()` — aggregated view of session work (modifications, examined, checkpoints)
- `checkpoint_state({ name })` — snapshot session state for recovery
- `restore_checkpoint({ checkpoint_id })` — roll back to a named checkpoint

### EE2 Compliance
- `analyze_ee2_compliance({ content })` — check code content against NCO standards
- `scan_repository_compliance({ name, content })` — bulk compliance scan (pass file content directly)
- `search_ee2_standards({ query })` — search EE2 standards document
- `generate_compliance_report()` — formatted compliance report (scope, categories, format optional)
- `extract_code_for_analysis({ name, content })` — extract code snippets for LLM passthrough analysis

### Operational Guidance
- `get_operational_guidance({ operation })` — HPC procedures for Hera, WCOSS2, etc.
- `list_job_scripts()` — inventory of workflow job scripts
- `explain_workflow_component({ component })` — deep component explanation
- `get_job_details({ job_name })` — detailed job script analysis

### Workflow Info (Filesystem only — always available)
- `get_workflow_structure()` — system architecture overview
- `get_system_configs()` — HPC platform-specific configurations
- `describe_component({ component })` — component documentation

### SDD Workflows (Filesystem only — Phase 31 session model)
- `list_sdd_workflows()` — all workflow phase specs
- `get_sdd_workflow({ workflow_name })` — specific phase details
- `start_sdd_session({ phase, totalSteps, notes })` — start a tracked session for a phase
- `record_sdd_step({ step, name, tag, notes })` — record step completion (tags: research, design, implement, configure, validate, document, ingest)
- `get_sdd_session()` — get current active session state (resume across conversations)
- `complete_sdd_session({ summary })` — complete session, archive to history
- `get_sdd_execution_history()` — view execution history
- `validate_sdd_compliance()` — validate code against SDD framework (pass content or target optionally)
- `get_sdd_framework_status()` — framework status and metrics

**Session lifecycle**: `start_sdd_session` → `record_sdd_step` (repeat) → `complete_sdd_session`

**State persistence**: Active session in `sdd_framework/execution_state/active_session.json` (survives server restarts). All events append to `sdd_framework/execution_state/history.jsonl` for audit trail. Use `get_sdd_session` to resume an in-progress session in a new conversation.

### GitHub Integration
- `search_issues({ query })` — search issues across repos
- `get_pull_requests()` — list and filter PRs
- `analyze_repository_structure()` — repo structure analysis
- `analyze_workflow_dependencies({ component })` — cross-repo dependency analysis

### Health & Diagnostics
- `mcp_health_check()` — full server + database health
- `get_server_info()` — server version and tool count

## Common Workflows

### "What does this code do?"
```
1. analyze_code_structure({ file_path: "sorc/model/src/module.f90" })
2. get_code_context({ symbol: "module_name" })  # Note: 'symbol', not 'file_path'
3. explain_with_context({ topic: "What is the purpose of <module>?" })
```

### "What calls this function?"
```
1. find_callers_callees({ function_name: "compute_forcing" })  # Required: function_name
2. trace_execution_path({ function_name: "compute_forcing" })  # Required: function_name
```

### "What are the dependencies of this module?"
```
1. find_dependencies({ target: "workflow_tasks" })  # Note: 'target', not 'file_path'
2. describe_component({ component: "dev/workflow/rocoto" })  # Note: 'component', not 'component_name'
```

### "Is this code production-ready?"
```
1. analyze_ee2_compliance({ content: "<paste file content or use read_file first>" })
2. find_dependencies({ target: "scripts/exgfs_forecast.sh" })
3. get_change_impact({ symbol: "exgfs_forecast" })
```

### "Help me understand this subsystem"
```
1. search_architecture({ query: "data assimilation cycling" })
2. search_documentation({ query: "data assimilation" })
3. get_operational_guidance({ operation: "running DA on Hera" })
```

### "Execute a tracked SDD phase"
```
1. get_sdd_workflow({ workflow_name: "phase27_jjob_script_rag_enhancement" })  # Read the spec
2. start_sdd_session({ phase: "phase27_jjob_script_rag_enhancement", totalSteps: 8 })
3. record_sdd_step({ step: 1, name: "Fix password default", tag: "implement", notes: "Changed to SPOT-compliant value" })
4. record_sdd_step({ step: 2, name: "Validate dry-run", tag: "validate", notes: "235 scripts parsed, 0 errors" })
   ... (repeat for each step)
5. complete_sdd_session({ summary: "Phase 27F-G complete: 383 nodes, 9155 rels" })
```

### "Resume an interrupted session"
```
1. get_sdd_session()  # Returns active session with completed steps
2. record_sdd_step({ step: N, ... })  # Continue from where you left off
```

### "Refactoring with session tracking" (Phase 24H-3)
```
1. get_code_context({ symbol: "config.resources" })          # Auto-records in examined[]
2. get_change_impact({ symbol: "config.resources" })          # Assess risk
3. checkpoint_state({ name: "pre-refactor", description: "Before YAML conversion" })
4. mark_as_modified({ file_path: "parm/config/config.resources", change_type: "content", description: "Converted to YAML" })
5. get_session_context()                                       # Review progress
6. restore_checkpoint({ checkpoint_id: "chk_..." })           # Roll back if needed
```

## Error Handling

| Error Message | Actual Cause | Fix |
|---------------|--------------|-----|
| "must have required property 'X'" | Wrong parameter name used | Check Quick Reference table above |
| "Tool is currently disabled by the user" | Tool threw an exception | Check `mcp_server_node/logs/mcp-server.log` |
| Timeout on graph queries | GGSR hit 15s guard | Results still return; retry with smaller scope |
| Empty ChromaDB results | Collection missing or empty | Run `get_knowledge_base_status()` to verify |

## Parameter Naming Conventions

The tools use these patterns — learn them to avoid errors:

| Concept | Neo4j/Graph Tools | Vector/RAG Tools | EE2/Operational Tools |
|---------|-------------------|------------------|-----------------------|
| File to analyze | `file_path` | `file_path` | `content` (pass content directly) |
| Function/symbol | `function_name`, `symbol`, or `from_symbol` | N/A | N/A |
| Code or symbol | N/A | `code_or_symbol` | N/A |
| Module/component | `target` or `component` | N/A | `component` |
| Search text | N/A | `query` or `topic` | `query` or `operation` |
| Number of results | `max_depth` | `max_results` | N/A |
| Change analysis | `symbol` + `change_type` | N/A | N/A |
| File identity | N/A | N/A | `name`, `content` (for content-abstracted tools) |
