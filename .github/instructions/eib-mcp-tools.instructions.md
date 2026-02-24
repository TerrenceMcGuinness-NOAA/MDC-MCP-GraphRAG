---
applyWhen: hasActiveMCPServer("eib-mcp-rag-full")
---

# EIB MCP Tool Usage Instructions (44 tools / 9 modules)

## MCP-First Policy

When the `eib-mcp-rag-full` server is connected, **always prefer MCP tools over shell commands** for code analysis, documentation search, and compliance checking.

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

## Quick Reference: Required Parameters

These are the **exact parameter names** — using wrong names will fail:

| Tool | Required Param | Optional Params |
|------|----------------|-----------------|
| **Code Analysis (Neo4j)** | | |
| `analyze_code_structure` | `file_path` | `include_dependencies`, `depth` |
| `find_dependencies` | `target` | `direction`, `max_depth` |
| `find_callers_callees` | `function_name` | `file_path`, `include_source` |
| `find_env_dependencies` | `variable_name` | |
| `trace_execution_path` | `function_name` | `file_path`, `max_depth`, `include_callers` |
| `trace_full_execution_chain` | `start` | `direction`, `max_depth`, `languages` |
| **GraphRAG (Neo4j + ChromaDB)** | | |
| `get_code_context` | `symbol` | `depth`, `include_source` |
| `search_architecture` | `query` | `max_results` |
| `find_similar_code` | `code_or_symbol` | `max_results` |
| `get_change_impact` | `symbol` | `change_type`, `include_indirect` |
| `trace_data_flow` | `from_symbol` | `max_depth` |
| **Semantic Search & RAG** | | |
| `search_documentation` | `query` | `max_results`, `collection` |
| `explain_with_context` | `topic` | `context_type`, `detail_level` |
| `find_related_files` | `file_path` | `max_results`, `threshold` |
| **EE2 Compliance** | | |
| `analyze_ee2_compliance` | `content` | `analysis_type` |
| `scan_repository_compliance` | `name`, `content` | `repository_path`, `file_patterns` |
| `search_ee2_standards` | `query` | |
| `extract_code_for_analysis` | `name`, `content` | `content_type`, `categories` |
| **Operational** | | |
| `get_operational_guidance` | `operation` | `platform`, `urgency` |
| `explain_workflow_component` | `component` | `detail_level` |
| `get_job_details` | `job_name` | `include_dependencies` |
| **Workflow Info** | | |
| `describe_component` | `component` | `show_content` |
| **GitHub** | | |
| `search_issues` | `query` | |
| `analyze_workflow_dependencies` | `component` | `analysis_type`, `include_external` |
| **SDD** | | |
| `get_sdd_workflow` | `workflow_name` | |
| `start_sdd_session` | `phase` | `totalSteps`, `notes` |
| `record_sdd_step` | `step`, `name` | `tag`, `notes` |
| `validate_sdd_compliance` | *(none)* | `content`, `target` |
| `complete_sdd_session` | *(none)* | `summary`, `abandon` |
| `get_sdd_execution_history` | *(none)* | `limit` |

Tools with no required params: `get_workflow_structure`, `get_system_configs`, `list_job_scripts`, `list_ingested_urls`, `get_ingested_urls_array`, `get_knowledge_base_status`, `list_sdd_workflows`, `get_sdd_session`, `get_sdd_framework_status`, `generate_compliance_report`, `get_pull_requests`, `analyze_repository_structure`, `mcp_health_check`, `get_server_info`

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
