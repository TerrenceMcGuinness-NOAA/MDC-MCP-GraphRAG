---
applyWhen: hasActiveMCPServer("eib-mcp-rag-full") || hasActiveMCPServer("eib-mcp-gateway")
---

<!-- Regenerate tool tables with: cd mcp_server_node && node scripts/generate-tool-docs.js -->
# EIB MCP Tool Usage Instructions (51 tools / 9 modules, v7.28.0)

## MCP-First Policy

When an EIB MCP server is connected (`eib-mcp-rag-full` or `eib-mcp-gateway`), **always prefer MCP tools over shell commands** for code analysis, documentation search, and compliance checking. Use `read_file`/`grep_search` only for exact line-level reads or literal string searches.

### When to Use MCP Tools vs Direct File Access

| Task | Use MCP Tool | Use read_file/grep |
|------|-------------|-------------------|
| "What does this file do?" | `analyze_code_structure` | No |
| "What calls this function?" | `find_callers_callees` | No |
| "How does X subsystem work?" | `search_architecture` | No |
| "Find files related to X" | `find_related_files` | No |
| "Is this code EE2-compliant?" | `analyze_ee2_compliance` | No |
| "Show me line 45-100" | No | `read_file` |
| "Search for literal 'FOO'" | No | `grep_search` |

**Best practice**: MCP tools for discovery, then `read_file` for specific line-level details.

## Tool Modules (51 tools / 9 modules)

### 1. Workflow Info (3 tools — Filesystem)

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `get_workflow_structure` | — | `component`, `structure_data` | Get the structure and overview of the global workflow system |
| `get_system_configs` | — | `platform`, `config_type`, `content` | Get system configuration information for different HPC platforms |
| `describe_component` | `component` | `show_content`, `content`, `file_type` | Get basic description of a workflow component (file system only) |

### 2. Code Analysis (6 tools — Neo4j)

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `analyze_code_structure` | `file_path` | `include_dependencies`, `depth`, `token_budget` | Analyze code structure, relationships, and dependencies for a specific file |
| `find_dependencies` | `target` | `direction`, `max_depth`, `token_budget` | Find all dependencies (imports) and dependents (importers) for a file or module |
| `trace_execution_path` | `function_name` | `file_path`, `max_depth`, `include_callers`, `include_weights`, `token_budget` | Trace the execution path from a starting function through call chains |
| `find_callers_callees` | `function_name` | `file_path`, `include_source`, `token_budget`, `cross_language` | Find all functions that call a target function and functions it calls |
| `trace_full_execution_chain` | `start` | `direction`, `max_depth`, `languages` | Trace complete execution chain across Shell, Python, and Fortran language boundaries |
| `find_env_dependencies` | `variable_name` | `show_exports`, `limit`, `token_budget` | Find all scripts that depend on or export a specific environment variable |

### 3. Semantic Search (7 tools — ChromaDB + Neo4j)

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `search_documentation` | `query` | `collection`, `max_results`, `include_graph`, `similarity_threshold` | Hybrid semantic + graph search across workflow documentation and code |
| `find_related_files` | `file_path` | `max_results`, `include_documentation` | Find files with similar dependencies and import relationships |
| `explain_with_context` | `topic` | `context_type`, `detail_level` | Provide comprehensive explanations using hybrid search |
| `get_knowledge_base_status` | — | `include_graph`, `include_vector` | Get comprehensive knowledge base statistics |
| `list_ingested_urls` | — | `format`, `source_filter` | List all URLs that have been ingested into the RAG knowledge base |
| `get_ingested_urls_array` | — | `include_failed` | Get a structured array of all ingested URLs for programmatic access |
| `check_knowledge_integrity` | — | `sample_size` | Check knowledge base integrity: path consistency (random-offset sampling), orphaned nodes, stale embeddings (git-aware comparison), coverage gaps |

### 4. EE2 Compliance (5 tools — ChromaDB)

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `search_ee2_standards` | `query` | `category`, `max_results`, `include_examples` | Search EE2 compliance standards and documentation |
| `analyze_ee2_compliance` | `content` | `analysis_type`, `include_recommendations` | Analyze code or documentation for EE2 compliance |
| `generate_compliance_report` | — | `scope`, `categories`, `format` | Generate comprehensive EE2 compliance report |
| `scan_repository_compliance` | `name`, `content` | `files`, `path`, `repository_path`, `file_patterns`, `sample_size`, `categories` | Scan repository for EE2 compliance (Phase 2 SME-corrected) |
| `extract_code_for_analysis` | `name`, `content` | `files`, `path`, `content_type`, `categories`, `file_pattern`, `max_files` | Extract code snippets from files for EE2 compliance analysis |

**Note**: `set -eu` is NOT required (80% false positive). Uses `err_chk`/`err_exit` utilities.

### 5. Operational (4 tools — ChromaDB)

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `get_operational_guidance` | `operation` | `platform`, `urgency` | Get operational guidance and best practices for HPC operations |
| `explain_workflow_component` | `component` | `detail_level` | Get detailed explanation of a workflow component with graph context |
| `list_job_scripts` | — | `category`, `search`, `format`, `job_list`, `files`, `name`, `content` | List and categorize job scripts in the workflow |
| `get_job_details` | `job_name` | `include_content`, `include_config`, `include_chromadb` | Get comprehensive details about a J-Job including inputs, outputs, dependencies |

### 6. GraphRAG (9 tools — ChromaDB + Neo4j)

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `get_code_context` | `symbol` | `depth`, `include_community`, `token_budget` | Get comprehensive context for a code symbol including graph neighborhood and community summaries |
| `search_architecture` | `query` | `max_results` | Search the codebase architecture for high-level understanding via community summaries |
| `find_similar_code` | `code_or_symbol` | `similarity_threshold`, `max_results` | Find code patterns semantically similar to a given symbol or description |
| `get_change_impact` | `symbol` | `change_type`, `include_indirect` | Analyze the blast radius of changing a code symbol with risk scoring |
| `trace_data_flow` | `from_symbol` | `to_symbol`, `max_depth` | Trace execution flow from a source symbol through the codebase |
| `mark_as_modified` | `file_path` | `change_type`, `description` | Record a file modification in the active session |
| `get_session_context` | — | `include_dirty` | Get aggregated view of the active session: examined symbols, file modifications |
| `checkpoint_state` | `name` | `description` | Snapshot current session state to a checkpoint for recovery |
| `restore_checkpoint` | `checkpoint_id` | — | Roll back session state to a previously created checkpoint |

### 7. GitHub Integration (4 tools — GitHub API)

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `search_issues` | `query` | `repository`, `state`, `labels` | Search GitHub issues across workflow repositories |
| `get_pull_requests` | — | `repository`, `state`, `limit` | Get pull request information and changes |
| `analyze_workflow_dependencies` | `component` | `analysis_type`, `include_external` | Analyze dependencies and relationships between workflow components |
| `analyze_repository_structure` | — | `repositories`, `analysis_depth` | Analyze structure and components across multiple repositories |

### 8. SDD Workflows (9 tools — Filesystem)

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `list_sdd_workflows` | — | `include_metadata` | List all SDD workflow phase specs |
| `get_sdd_workflow` | `workflow_name` | — | Get specific phase details |
| `start_sdd_session` | `phase` | `notes`, `total_steps` | Start a tracked session for a phase |
| `record_sdd_step` | `step`, `name` | `tag`, `notes` | Record step completion (tags: research, design, implement, configure, validate, document, ingest) |
| `get_sdd_session` | — | `resume` | Get current active session state (resume across conversations) |
| `complete_sdd_session` | — | `summary`, `abandon`, `reason` | Complete session, archive to history |
| `get_sdd_execution_history` | — | `limit`, `workflow_name` | View execution history |
| `validate_sdd_compliance` | — | `content`, `target`, `framework_version`, `content_type` | Validate code against SDD framework |
| `get_sdd_framework_status` | — | `detailed` | Framework status and metrics |

**Session lifecycle**: `start_sdd_session` → `record_sdd_step` (repeat) → `complete_sdd_session`

**State persistence**: Active session in `sdd_framework/execution_state/active_session.json` (survives server restarts). All events append to `sdd_framework/execution_state/history.jsonl` for audit trail. Use `get_sdd_session` to resume an in-progress session in a new conversation.

### 9. Utility (4 tools — Built-in)

| Tool | Required | Optional | Description |
|------|----------|----------|-------------|
| `get_server_info` | — | `include_capabilities` | Get information about the MCP server and available tools |
| `mcp_health_check` | — | `detailed`, `deep`, `functional` | Check the health status of all MCP server components |
| `get_health_trend` | — | `limit` | Get health trend data from persisted snapshots with anomaly detection |
| `get_quality_metrics` | — | `category`, `compare` | Get RAG quality benchmark metrics with optional regression comparison |

## RAG Knowledge Base Tiers

| Tier | Sources | Purpose |
|------|---------|---------|
| 1 | global-workflow RTD, EE2 Standards | Core workflow docs |
| 2 | Rocoto, ecFlow, wxflow, PyFlow | Workflow engines |
| 3 | UFS Weather Model, JEDI, FV3 | Forecast models |
| 4 | Spack, spack-stack, hpc-stack | Build systems |
| 5 | Shell Style Guide, PEP8, NumPy | Coding standards |

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
- `check_knowledge_integrity()` — knowledge base integrity: path consistency (random-offset sampling), orphaned nodes, stale embeddings (git-aware source comparison), coverage gaps
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
- `mcp_health_check()` — full server + database health (deep mode persists snapshots)
- `get_health_trend()` — health trending over time with anomaly detection
- `check_knowledge_integrity()` — knowledge base integrity monitoring (random sampling, git-aware staleness)
- `get_server_info()` — server version and tool count
- `get_quality_metrics()` — RAG quality benchmark results and regression detection

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
