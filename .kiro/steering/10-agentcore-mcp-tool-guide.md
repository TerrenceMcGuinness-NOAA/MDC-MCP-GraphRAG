---
inclusion: always
---

# AgentCore MCP — Tool Guide for Global Workflow

Tool-selection guide for the AWS Bedrock AgentCore MCP-RAG server
(`agentcore-mcp-rag`): **53 tools across 10 modules**, backed by Amazon Neptune
(openCypher graph) and Amazon OpenSearch (k-NN + BM25 vector), with Amazon
Bedrock Titan + baked-in MPNet embeddings.

This is the AWS-native companion to the global-workflow repo's
`.github/instructions/mcp.instructions.md`. It documents the live AgentCore tool
surface — **not** any Docker / Neo4j / ChromaDB system. For *how to consume* the
service and the full multi-tenant model, see
`.kiro/steering/09-agentcore-mcp-for-global-workflow.md`.

> Source of truth: `mcp_server_python/src/tools/*.py`. Tenant scoping is the
> explicit `tenant_id: str | None = None` parameter on a tool's signature.

## MCP-First Policy

**Prefer MCP tools over shell commands** for code analysis, documentation search,
architecture questions, and EE2 compliance. Use `read` for exact line ranges and
`grep` for literal string searches. Best practice: MCP tool for discovery, then
`read` for the precise lines.

## Tenant Scoping Legend

The **Tenant?** column marks whether a tool accepts the optional `tenant_id`
parameter:

- **yes** — data-plane tool. Omit `tenant_id` → default `gw` (`develop`, unprefixed).
  Pass e.g. `tenant_id="gw_v17"` to target another branch. Unknown id → `[ERROR]`.
- **no** — server-global tool (session state, catalog/registry, GitHub, SDD,
  health). `tenant_id` does not apply.

24 of 53 tools are tenant-scoped. Valid ids: `gw`, `gw_sfs`, `gw_jedi_gfs`,
`gw_v17`, `gw_gefs_v12` (see file 09 for the catalog).

## Tool Modules (53 tools / 10 modules)

### 1. Workflow Info (3 tools — Neptune + filesystem)

| Tool | Tenant? | Required | Description |
|------|---------|----------|-------------|
| `get_workflow_structure` | yes | — | Structure and overview of the global-workflow system |
| `get_system_configs` | yes | — | System configuration for HPC platforms (Hera, Hercules, Orion, WCOSS2, Gaea) |
| `describe_component` | yes | `component` | Basic description of a workflow component (file/dir) |

### 2. Code Analysis (6 tools — Neptune) — all tenant-scoped

| Tool | Tenant? | Required | Description |
|------|---------|----------|-------------|
| `analyze_code_structure` | yes | `file_path` | Structure, relationships, dependencies for a file |
| `find_dependencies` | yes | `target` | Imports (upstream) and importers (downstream) for a file/module |
| `trace_execution_path` | yes | `function_name` | Execution path from a function through call chains |
| `find_callers_callees` | yes | `function_name` | Callers of, and functions called by, a target function |
| `trace_full_execution_chain` | yes | `start` | Full chain across Shell → Fortran → Python boundaries |
| `find_env_dependencies` | yes | `variable_name` | Scripts that depend on / export an environment variable |

> Note (Gap B): for non-`gw` tenants, graph relationships are still being ingested
> via the `graph-port-*` series. These tools may return sparse/empty results for
> `gw_v17` and friends until that lands; the `gw` baseline is fully populated.

### 3. Semantic Search (8 tools — OpenSearch + Neptune)

| Tool | Tenant? | Required | Description |
|------|---------|----------|-------------|
| `search_documentation` | yes | `query` | Hybrid semantic + graph search across docs and code |
| `find_related_files` | yes | `file_path` | Files with similar dependencies / import relationships |
| `explain_with_context` | yes | `topic` | Comprehensive explanation via hybrid search |
| `get_knowledge_base_status` | yes | — | OpenSearch + Neptune counts and health |
| `check_knowledge_integrity` | yes | — | Path consistency, orphaned nodes, stale embeddings, coverage gaps |
| `list_ingested_urls` | no | — | URLs ingested into the RAG knowledge base |
| `get_ingested_urls_array` | no | — | Structured array of ingested URLs |
| `list_all_sources` | no | — | Every ingestion source in the unified manifest |

### 4. EE2 Compliance (5 tools — OpenSearch)

| Tool | Tenant? | Required | Description |
|------|---------|----------|-------------|
| `search_ee2_standards` | yes | `query` | Search EE2 compliance standards / docs |
| `analyze_ee2_compliance` | no | `content` | Analyze supplied code/docs for EE2 compliance |
| `generate_compliance_report` | no | — | EE2 compliance report (summary / detailed / checklist) |
| `scan_repository_compliance` | no | — | Batch-scan supplied files for EE2 issues |
| `extract_code_for_analysis` | no | — | Extract bash/python snippets for compliance analysis |

**Note**: `set -eu` / `set -e` are NOT required (Phase 2 SME-corrected); the
correct pattern is `err_chk` / `err_exit`.

### 5. Operational (4 tools — OpenSearch + Neptune) — all tenant-scoped

| Tool | Tenant? | Required | Description |
|------|---------|----------|-------------|
| `get_operational_guidance` | yes | `operation` | HPC operations guidance + platform notes |
| `explain_workflow_component` | yes | `component` | Detailed component explanation with graph context |
| `list_job_scripts` | yes | — | List/categorize J-Job scripts |
| `get_job_details` | yes | `job_name` | Inputs, outputs, configs, env vars for a J-Job |

### 6. GraphRAG (9 tools — Neptune + OpenSearch)

| Tool | Tenant? | Required | Description |
|------|---------|----------|-------------|
| `get_code_context` | yes | `symbol` | Graph neighborhood + community summary + snippets for a symbol |
| `search_architecture` | yes | `query` | High-level subsystem / community summaries |
| `find_similar_code` | yes | `code_or_symbol` | Semantically similar code patterns |
| `get_change_impact` | yes | `symbol` | Blast radius / risk of changing a symbol |
| `trace_data_flow` | yes | `from_symbol` | Execution flow from a source symbol (cross-language) |
| `mark_as_modified` | no | `file_path` | Record a file modification in the active session |
| `get_session_context` | no | — | Examined symbols, file modifications, checkpoints |
| `checkpoint_state` | no | `name` | Snapshot session state to a checkpoint |
| `restore_checkpoint` | no | `checkpoint_id` | Roll back session state to a checkpoint |

### 7. SDD Workflow (9 tools — session state) — none tenant-scoped

| Tool | Tenant? | Required | Description |
|------|---------|----------|-------------|
| `list_sdd_workflows` | no | — | List available SDD framework workflows |
| `get_sdd_workflow` | no | `workflow_name` | Details of a specific SDD workflow |
| `start_sdd_session` | no | `phase` | Start a new SDD session for a phase |
| `record_sdd_step` | no | `step`, `name` | Record completion of a step |
| `get_sdd_session` | no | — | Current active SDD session state |
| `complete_sdd_session` | no | — | Complete (or abandon) the active session |
| `get_sdd_execution_history` | no | — | History / analytics of SDD executions |
| `validate_sdd_compliance` | no | — | Validate content against SDD framework standards |
| `get_sdd_framework_status` | no | — | SDD framework integration status |

### 8. GitHub Integration (4 tools — GitHub API) — none tenant-scoped

| Tool | Tenant? | Required | Description |
|------|---------|----------|-------------|
| `search_issues` | no | `query` | Search GitHub issues across workflow repos |
| `get_pull_requests` | no | — | Pull request information and changes |
| `analyze_workflow_dependencies` | no | `component` | Dependencies/relationships between components |
| `analyze_repository_structure` | no | — | Structure/components across repositories |

### 9. Utility (4 tools — built-in) — none tenant-scoped

| Tool | Tenant? | Required | Description |
|------|---------|----------|-------------|
| `get_server_info` | no | — | Server version, tool count, active modules |
| `mcp_health_check` | no | — | Health of all components (Base, Vector, Graph) |
| `get_health_trend` | no | — | Health trend data from persisted snapshots |
| `get_quality_metrics` | no | — | RAG quality benchmark metrics |

### 10. Error Analysis (1 tool — built-in) — not tenant-scoped

| Tool | Tenant? | Required | Description |
|------|---------|----------|-------------|
| `extract_ci_error_signal` | no | `log_path` | Distill a large raw CI log into an 8 KB high-entropy ErrorRecord and classify it against the CI failure taxonomy |

Source: `mcp_server_python/src/tools/error_analysis.py`. See
`.kiro/steering/13-ci-error-reporting-policy.md` for the required report format when using it.

## When to Use MCP vs Direct Access

| Task | Use MCP Tool | Use read/grep |
|------|-------------|---------------|
| "What does this file do?" | `analyze_code_structure` | no |
| "What calls this function?" | `find_callers_callees` | no |
| "How does X subsystem work?" | `search_architecture` | no |
| "Find docs about Y" | `search_documentation` | no |
| "Is this code EE2-compliant?" | `analyze_ee2_compliance` | no |
| "What breaks if I change Z?" | `get_change_impact` | no |
| "Show me lines 45–100" | no | `read` |
| "Find the literal string 'FOO'" | no | `grep` |
| "Find files named `*.fd`" | no | `glob` |

## RAG Knowledge Base Tiers (gw baseline)

The default `gw` tenant's documentation collection is organized in tiers; query
them via `search_documentation`. Non-`gw` tenants have their own prefixed
collections (e.g. `gw_v17_documentation`) populated per branch.

| Tier | Sources | Purpose |
|------|---------|---------|
| 1 | global-workflow RTD, EE2 standards | Core workflow docs |
| 2 | Rocoto, ecFlow, wxflow, PyFlow | Workflow engines |
| 3 | UFS Weather Model, JEDI, FV3, MPAS | Forecast models |
| 4 | Spack, spack-stack, hpc-stack | Build systems |
| 5 | Shell Style Guide, PEP 8, NumPy | Coding standards |

---
Remember: Global Workflow is a production forecasting system. Use these tools to
understand and analyze it; verify against the source tree and test real changes
through the operational process.
