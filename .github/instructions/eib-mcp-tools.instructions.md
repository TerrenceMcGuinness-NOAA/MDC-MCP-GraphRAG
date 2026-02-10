# EIB MCP Tool Usage Instructions
#
# These instructions are loaded when the eib-mcp-rag-full MCP server is available.
# They guide AI agents on how to use the custom MCP toolset effectively.
#
# applyWhen: hasActiveMCPServer("eib-mcp-rag-full")

## MCP-First Policy

When the `eib-mcp-rag-full` server is connected, **always prefer MCP tools over shell commands** for code analysis, documentation search, and compliance checking.

```javascript
// DO: Use MCP tools
analyze_code_structure({ file_path: "path/to/file" })
scan_repository_compliance({ repository_path: "/path" })
search_documentation({ query: "how does GFS cycling work" })

// DON'T: Fall back to grep/shell when MCP tools can answer the question
```

## Tool Selection by Task

### Code Structure & Dependencies (Neo4j-backed)
- `analyze_code_structure({ file_path })` — AST-level analysis of any file in the workflow
- `find_dependencies({ file_path })` — upstream/downstream dependency graph
- `find_callers_callees({ function_name, file_path })` — call graph traversal
- `find_env_dependencies({ variable_name })` — environment variable lineage across scripts
- `trace_execution_path({ entry_point })` — execution flow from entry to completion

### Semantic Search & RAG (ChromaDB-backed)
- `search_documentation({ query, n_results })` — semantic search across all ingested docs
- `explain_with_context({ query })` — RAG-powered explanations with source citations
- `find_related_files({ file_path })` — vector similarity to find related code/docs
- `get_knowledge_base_status({ include_graph, include_vector })` — DB health and stats

### GraphRAG (Combined Neo4j + ChromaDB)
- `get_code_context({ file_path })` — single-call full context: GGSR neighborhood + community summary + callers/callees
- `search_architecture({ query })` — semantic search over community summaries for holistic queries
- `find_similar_code({ code_snippet, threshold })` — vector similarity + graph enrichment
- `get_change_impact({ file_path })` — blast radius analysis with risk scoring
- `trace_data_flow({ variable, file_path })` — data flow across the codebase

### EE2 Compliance
- `analyze_ee2_compliance({ file_path })` — check a file against NCO standards
- `scan_repository_compliance({ repository_path })` — bulk compliance scan
- `search_ee2_standards({ query })` — search the EE2 standards document
- `generate_compliance_report({ scope })` — formatted compliance report

### Operational Guidance
- `get_operational_guidance({ topic })` — HPC procedures for Hera, WCOSS2, etc.
- `list_job_scripts({ filter })` — inventory of workflow job scripts
- `explain_workflow_component({ component })` — deep component explanation

### Workflow Info (Filesystem only — always available)
- `get_workflow_structure({ detail_level })` — system architecture overview
- `get_system_configs({ platform })` — HPC platform-specific configurations
- `describe_component({ component_name })` — component documentation

### SDD Workflows (Filesystem only)
- `list_sdd_workflows()` — all workflow phase specs
- `get_sdd_workflow({ phase })` — specific phase details
- `execute_sdd_workflow_supervised({ phase, step })` — ISD execution with approval gates

### GitHub Integration
- `search_issues({ query, repo })` — search issues across repos
- `get_pull_requests({ state, repo })` — list and filter PRs
- `analyze_repository_structure({ repo })` — repo structure analysis

### Health & Diagnostics
- `mcp_health_check({ detailed: true })` — full server + database health
- `get_server_info({ include_capabilities: true })` — server version and tool count

## Common Workflows

### "What does this code do?"
```
1. analyze_code_structure({ file_path: "sorc/model/src/module.f90" })
2. get_code_context({ file_path: "sorc/model/src/module.f90" })
3. explain_with_context({ query: "What is the purpose of <module>?" })
```

### "Is this code production-ready?"
```
1. analyze_ee2_compliance({ file_path: "scripts/exgfs_forecast.sh" })
2. find_dependencies({ file_path: "scripts/exgfs_forecast.sh" })
3. get_change_impact({ file_path: "scripts/exgfs_forecast.sh" })
```

### "Help me understand this subsystem"
```
1. search_architecture({ query: "data assimilation cycling" })
2. search_documentation({ query: "data assimilation", n_results: 5 })
3. get_operational_guidance({ topic: "running DA on Hera" })
```

## Error Handling

- **"Tool is currently disabled by the user"** — the tool errored, not actually disabled. Check `mcp_server_node/logs/mcp-server.log` for the real error.
- **Timeout on graph queries** — GGSR has a 15s timeout guard. Core graph results still return.
- **Empty ChromaDB results** — verify collections exist with `get_knowledge_base_status()`.
