# Requirements Document

## Introduction

This document specifies the requirements for porting the MDC MCP/RAG Server from Node.js/JavaScript to Python using the Strands Agents SDK and FastMCP framework. The current system comprises ~9,000 lines of JavaScript across 9 tool modules with 51 tools, backed by Amazon OpenSearch (vector search) and Amazon Neptune (graph queries). The port follows a module-by-module strategy (phases B1–B14, ~16 weeks) where the Node.js server continues serving production during the transition. Each ported module is validated against the existing Node.js baseline before cutover.

The Python port transforms the platform from a passive MCP tool server into an active agent ecosystem with multi-agent orchestration (Strands Agents), persistent cross-session memory (AgentCore Memory), Cedar-based policy enforcement (AgentCore Policy), and OpenTelemetry observability (AgentCore Observability).

## Glossary

- **MCP_Server**: The Python MCP server application built on FastMCP that registers and serves all 51 tools over Streamable HTTP
- **FastMCP**: The Python framework for building MCP-compliant servers with decorator-based tool registration
- **Strands_Agent**: An autonomous AI agent built with the Strands Agents SDK that consumes MCP tools and orchestrates multi-step workflows
- **OpenSearch_Adapter**: The Python module that provides SigV4-authenticated access to Amazon OpenSearch for vector and hybrid search operations
- **Neptune_Adapter**: The Python module that provides SigV4-authenticated HTTP access to Amazon Neptune for openCypher graph queries
- **GGSR**: Graph-Guided Semantic Retrieval — the hybrid retrieval algorithm that combines graph traversal with vector search using relationship weights and hop decay
- **Parity_Test**: An automated test that executes the same query against both the Node.js and Python implementations and asserts equivalent results
- **Tool_Module**: A logical grouping of related MCP tools (e.g., SemanticSearchTools, CodeAnalysisTools) that share database adapters and domain logic
- **AgentCore_Memory**: Amazon Bedrock AgentCore's managed memory service providing short-term memory (STM) within sessions and long-term memory (LTM) across sessions
- **AgentCore_Gateway**: Amazon Bedrock AgentCore's managed gateway service that routes tool invocations with OAuth authentication and rate limiting
- **Cedar_Policy**: A deterministic access control policy written in the Cedar policy language that governs per-tool and per-user permissions
- **Cutover**: The process of switching production traffic from the Node.js MCP server to the Python MCP server for a specific tool module
- **SDD_Framework**: The Spec-Driven Development methodology used for session tracking, workflow management, and step recording
- **Baseline**: The validated Node.js MCP server (v8.3.0, 45/45 tools passing) used as the reference for parity testing

## Requirements

### Requirement 1: FastMCP Server Scaffolding

**User Story:** As a developer, I want a Python MCP server built on FastMCP that registers tools via decorators and serves them over Streamable HTTP on port 8000, so that the server is compatible with AgentCore Runtime deployment.

#### Acceptance Criteria

1. THE MCP_Server SHALL expose a Streamable HTTP endpoint at `0.0.0.0:8000/mcp` compatible with the MCP specification
2. WHEN a client sends a `tools/list` request, THE MCP_Server SHALL return the complete list of registered tools with their names, descriptions, and input schemas
3. WHEN a client sends a `tools/call` request for a registered tool, THE MCP_Server SHALL route the call to the corresponding Python function and return the result
4. THE MCP_Server SHALL support decorator-based tool registration using FastMCP's `@mcp.tool()` pattern
5. THE MCP_Server SHALL organize tools into logical modules matching the Node.js module structure: SemanticSearchTools, CodeAnalysisTools, GraphRAGTools, EE2ComplianceTools, OperationalTools, SDDWorkflowTools, WorkflowInfoTools, and GitHubTools
6. WHEN the MCP_Server starts, THE MCP_Server SHALL initialize database adapters (OpenSearch_Adapter and Neptune_Adapter) and inject them into tool modules
7. IF a database adapter fails to initialize, THEN THE MCP_Server SHALL log the error and start in degraded mode with only tools that do not require the failed adapter
8. THE MCP_Server SHALL support a `DB_BACKEND` environment variable with values `aws` or `legacy` to select between AWS managed services and legacy Docker-based backends

### Requirement 2: OpenSearch Adapter (Python)

**User Story:** As a developer, I want a Python OpenSearch adapter that reuses the existing `aws_backend.py` SigV4 authentication code, so that the Python server can perform vector search, hybrid search, and BM25 queries against the same OpenSearch indices used by the Node.js server.

#### Acceptance Criteria

1. THE OpenSearch_Adapter SHALL authenticate to Amazon OpenSearch using SigV4 request signing, reusing the credential logic from `aws_backend.py`
2. THE OpenSearch_Adapter SHALL support k-NN vector search with configurable `k` and similarity threshold parameters
3. THE OpenSearch_Adapter SHALL support hybrid search combining BM25 text search with k-NN vector search using Reciprocal Rank Fusion (RRF)
4. THE OpenSearch_Adapter SHALL support querying all five production indices: `mdc-code-context-mpnet768`, `mdc-workflow-docs-mpnet768`, `mdc-jjobs-mpnet768`, `mdc-community-summaries-mpnet768`, and `mdc-ee2-standards-mpnet768`
5. WHEN a query is executed, THE OpenSearch_Adapter SHALL return results in the same document schema (id, content, metadata, score) as the Node.js `OpenSearchAdapter.js`
6. IF an OpenSearch request fails with a transient error (HTTP 429 or 5xx), THEN THE OpenSearch_Adapter SHALL retry with exponential backoff up to 3 attempts
7. THE OpenSearch_Adapter SHALL support embedding model selection via the embedding registry, defaulting to MPNet 768-dimensional vectors
8. FOR ALL valid search queries, executing the query through the Python OpenSearch_Adapter and the Node.js OpenSearchAdapter SHALL return documents with the same IDs in the same rank order (round-trip parity property)

### Requirement 3: Neptune Adapter (Python)

**User Story:** As a developer, I want a Python Neptune adapter that executes openCypher queries over SigV4-authenticated HTTPS, so that the Python server can perform graph traversals against the same Neptune database used by the Node.js server.

#### Acceptance Criteria

1. THE Neptune_Adapter SHALL authenticate to Amazon Neptune using SigV4 request signing over the HTTPS openCypher endpoint, reusing the `NeptuneHTTPAdapter` class from `aws_backend.py`
2. THE Neptune_Adapter SHALL support parameterized openCypher queries with named parameters
3. WHEN a query returns results, THE Neptune_Adapter SHALL parse Neptune's JSON response into Python dictionaries with the same field names and types as the Node.js `NeptuneAdapter.js` output
4. THE Neptune_Adapter SHALL support session-based query execution with context manager (`with adapter.session() as session`) for connection pooling
5. IF a Neptune query fails with a transient error (HTTP 429, 500, or 503), THEN THE Neptune_Adapter SHALL retry with exponential backoff up to 3 attempts
6. IF a Neptune query fails with a ConcurrentModificationException, THEN THE Neptune_Adapter SHALL retry the query after a brief delay
7. THE Neptune_Adapter SHALL support the `NEPTUNE_ENDPOINT` and `AWS_REGION` environment variables for configuration
8. FOR ALL valid openCypher queries, executing the query through the Python Neptune_Adapter and the Node.js NeptuneAdapter SHALL return equivalent result sets (round-trip parity property)

### Requirement 4: SemanticSearchTools Port

**User Story:** As a developer, I want the 7 SemanticSearchTools ported to Python with identical tool signatures and equivalent query results, so that semantic search capabilities are available in the Python server.

#### Acceptance Criteria

1. THE MCP_Server SHALL register all 7 SemanticSearchTools: `search_documentation`, `find_related_files`, `explain_with_context`, `get_knowledge_base_status`, `list_ingested_urls`, `get_ingested_urls_array`, and `check_knowledge_integrity`
2. WHEN `search_documentation` is called with a query string, THE MCP_Server SHALL execute a hybrid search (BM25 + vector + RRF) across OpenSearch indices and return ranked results with graph enrichment from Neptune
3. WHEN `find_related_files` is called with a file path, THE MCP_Server SHALL find files with similar dependency and import relationships using both vector similarity and graph neighborhood
4. WHEN `explain_with_context` is called with a topic, THE MCP_Server SHALL combine semantic search results with graph context to produce a comprehensive explanation
5. WHEN `get_knowledge_base_status` is called, THE MCP_Server SHALL return document counts, index health, and graph statistics from both OpenSearch and Neptune
6. WHEN `check_knowledge_integrity` is called, THE MCP_Server SHALL verify path consistency, detect orphaned nodes, check for stale embeddings, and report coverage gaps
7. FOR ALL SemanticSearchTools, the Python tool input schemas SHALL match the Node.js tool input schemas exactly (same parameter names, types, and descriptions)
8. FOR ALL valid `search_documentation` queries, the Python implementation SHALL return the same top-5 document IDs as the Node.js implementation (parity property)

### Requirement 5: CodeAnalysisTools Port

**User Story:** As a developer, I want the 6 CodeAnalysisTools ported to Python with identical tool signatures and equivalent graph traversal results, so that code structure analysis capabilities are available in the Python server.

#### Acceptance Criteria

1. THE MCP_Server SHALL register all 6 CodeAnalysisTools: `analyze_code_structure`, `find_dependencies`, `trace_execution_path`, `find_callers_callees`, `trace_full_execution_chain`, and `find_env_dependencies`
2. WHEN `analyze_code_structure` is called with a file path, THE MCP_Server SHALL return the file's code structure, relationships, and dependency tree up to the specified depth using Neptune graph queries
3. WHEN `find_callers_callees` is called with a function name, THE MCP_Server SHALL return all functions that call the target (callers) and all functions the target calls (callees), including cross-language boundaries when requested
4. WHEN `trace_full_execution_chain` is called with a starting node, THE MCP_Server SHALL trace the complete execution chain across Shell, Python, and Fortran language boundaries following SOURCES, INVOKES, EXECUTES, CALLS, USES, and DEFINES edges
5. WHEN `find_env_dependencies` is called with a variable name, THE MCP_Server SHALL return all scripts that depend on or export the specified environment variable using Neptune graph queries
6. THE MCP_Server SHALL support the `token_budget` parameter for GGSR-weighted context limiting on all CodeAnalysisTools that return graph context
7. FOR ALL CodeAnalysisTools, the Python tool input schemas SHALL match the Node.js tool input schemas exactly
8. FOR ALL valid `find_callers_callees` queries, the Python implementation SHALL return the same set of caller and callee function names as the Node.js implementation (parity property)

### Requirement 6: GraphRAGTools and GGSR Port

**User Story:** As a developer, I want the 9 GraphRAGTools including the GGSR traversal engine ported to Python, so that graph-guided semantic retrieval and session tracking capabilities are available in the Python server.

#### Acceptance Criteria

1. THE MCP_Server SHALL register all 9 GraphRAGTools: `get_code_context`, `search_architecture`, `find_similar_code`, `get_change_impact`, `trace_data_flow`, `mark_as_modified`, `get_session_context`, `checkpoint_state`, and `restore_checkpoint`
2. WHEN `get_code_context` is called with a symbol name, THE MCP_Server SHALL return the symbol's graph neighborhood, community summary, and semantic snippets using GGSR traversal with relationship weights and hop decay scoring
3. WHEN `search_architecture` is called with a query, THE MCP_Server SHALL search community summaries using vector similarity and return matching subsystem descriptions
4. WHEN `get_change_impact` is called with a symbol name, THE MCP_Server SHALL analyze the blast radius by traversing direct and indirect dependents in the Neptune graph and computing a risk score
5. WHEN `trace_data_flow` is called with a source symbol, THE MCP_Server SHALL trace downstream execution paths through the graph, including cross-language boundaries
6. THE GGSR traversal engine SHALL implement relationship weight scoring, hop decay, and token budget limiting equivalent to the Node.js `GGSRTraversalPrototypes.js` and `GraphGuidedRetrieval.js`
7. THE MCP_Server SHALL maintain session state (examined symbols, file modifications, checkpoints) in memory during a session, with the same state model as the Node.js implementation
8. FOR ALL valid `get_code_context` queries, the Python GGSR implementation SHALL produce context snippets with the same symbols and comparable relevance scores as the Node.js implementation (parity property within 10% score tolerance)
9. FOR ALL GraphRAGTools, the Python tool input schemas SHALL match the Node.js tool input schemas exactly

### Requirement 7: EE2ComplianceTools Port

**User Story:** As a developer, I want the 5 EE2ComplianceTools ported to Python, so that EE2/NCO compliance scanning and reporting capabilities are available in the Python server.

#### Acceptance Criteria

1. THE MCP_Server SHALL register all 5 EE2ComplianceTools: `search_ee2_standards`, `analyze_ee2_compliance`, `generate_compliance_report`, `scan_repository_compliance`, and `extract_code_for_analysis`
2. WHEN `analyze_ee2_compliance` is called with code content, THE MCP_Server SHALL analyze the content against EE2 compliance categories: error_handling, environment_variables, file_naming, shebang_compliance, and production_utilities
3. WHEN `scan_repository_compliance` is called, THE MCP_Server SHALL scan files matching the specified patterns and return per-category compliance results with recommendations
4. WHEN `generate_compliance_report` is called, THE MCP_Server SHALL produce a formatted compliance report in markdown, checklist, or summary format
5. WHEN `extract_code_for_analysis` is called with file content, THE MCP_Server SHALL extract code snippets categorized by analysis type (output_file_naming, error_handling, shebang_compliance, env_var_validation) with LLM prompts
6. FOR ALL EE2ComplianceTools, the Python tool input schemas SHALL match the Node.js tool input schemas exactly
7. FOR ALL valid `analyze_ee2_compliance` inputs, the Python implementation SHALL detect the same compliance violations as the Node.js implementation (parity property)

### Requirement 8: OperationalTools Port

**User Story:** As a developer, I want the 4 OperationalTools ported to Python, so that operational guidance and job information capabilities are available in the Python server.

#### Acceptance Criteria

1. THE MCP_Server SHALL register all 4 OperationalTools: `get_operational_guidance`, `explain_workflow_component`, `list_job_scripts`, and `get_job_details`
2. WHEN `get_operational_guidance` is called with an operation name and platform, THE MCP_Server SHALL return operational guidance and best practices using hybrid semantic and graph search
3. WHEN `get_job_details` is called with a J-Job name, THE MCP_Server SHALL return comprehensive job details including inputs, outputs, dependencies, config content, and related semantic search results
4. WHEN `list_job_scripts` is called, THE MCP_Server SHALL return categorized job scripts with optional filtering by category (analysis, forecast, post, archive, verification) and search term
5. FOR ALL OperationalTools, the Python tool input schemas SHALL match the Node.js tool input schemas exactly
6. FOR ALL valid `get_job_details` queries, the Python implementation SHALL return the same job metadata fields as the Node.js implementation (parity property)

### Requirement 9: SDDWorkflowTools Port

**User Story:** As a developer, I want the 9 SDDWorkflowTools ported to Python, so that SDD session tracking and workflow management capabilities are available in the Python server.

#### Acceptance Criteria

1. THE MCP_Server SHALL register all 9 SDDWorkflowTools: `list_sdd_workflows`, `get_sdd_workflow`, `start_sdd_session`, `record_sdd_step`, `get_sdd_session`, `complete_sdd_session`, `get_sdd_execution_history`, `validate_sdd_compliance`, and `get_sdd_framework_status`
2. WHEN `start_sdd_session` is called with a phase name, THE MCP_Server SHALL create a new session with tracking state and persist it to the SDD execution state directory
3. WHEN `record_sdd_step` is called, THE MCP_Server SHALL record the step completion with name, notes, and semantic tag in the active session
4. WHEN `complete_sdd_session` is called, THE MCP_Server SHALL archive the session state and record completion in the execution history JSONL file
5. THE MCP_Server SHALL read and write SDD state files in the same format and directory structure as the Node.js implementation (`sdd_framework/execution_state/`)
6. FOR ALL SDDWorkflowTools, the Python tool input schemas SHALL match the Node.js tool input schemas exactly
7. FOR ALL valid session lifecycle sequences (start → record steps → complete), the Python implementation SHALL produce state files parseable by the Node.js implementation and vice versa (round-trip property)

### Requirement 10: WorkflowInfoTools Port

**User Story:** As a developer, I want the 3 WorkflowInfoTools ported to Python, so that workflow structure and system configuration queries are available in the Python server.

#### Acceptance Criteria

1. THE MCP_Server SHALL register all 3 WorkflowInfoTools: `get_workflow_structure`, `get_system_configs`, and `describe_component`
2. WHEN `get_workflow_structure` is called, THE MCP_Server SHALL return the directory structure and overview of the global workflow system, optionally focused on a specific component (jobs, scripts, parm, ush, sorc, docs, env)
3. WHEN `get_system_configs` is called with a platform name, THE MCP_Server SHALL return system configuration information (modules, resources, paths) for the specified HPC platform
4. WHEN `describe_component` is called with a component name, THE MCP_Server SHALL return a description of the workflow component based on filesystem analysis
5. FOR ALL WorkflowInfoTools, the Python tool input schemas SHALL match the Node.js tool input schemas exactly

### Requirement 11: GitHubTools Port

**User Story:** As a developer, I want the 4 GitHubTools ported to Python, so that GitHub issue search and repository analysis capabilities are available in the Python server.

#### Acceptance Criteria

1. THE MCP_Server SHALL register all 4 GitHubTools: `search_issues`, `get_pull_requests`, `analyze_workflow_dependencies`, and `analyze_repository_structure`
2. WHEN `search_issues` is called with a query, THE MCP_Server SHALL search GitHub issues in the specified repository using the GitHub API
3. WHEN `get_pull_requests` is called, THE MCP_Server SHALL return pull request information filtered by state (open, closed, all) and limited by count
4. THE MCP_Server SHALL authenticate to the GitHub API using the `GITHUB_TOKEN` environment variable
5. FOR ALL GitHubTools, the Python tool input schemas SHALL match the Node.js tool input schemas exactly

### Requirement 12: Utility Tools Port

**User Story:** As a developer, I want the 4 utility tools ported to Python, so that server health monitoring and quality metrics are available in the Python server.

#### Acceptance Criteria

1. THE MCP_Server SHALL register all 4 utility tools: `get_server_info`, `mcp_health_check`, `get_health_trend`, and `get_quality_metrics`
2. WHEN `mcp_health_check` is called, THE MCP_Server SHALL verify connectivity to OpenSearch and Neptune, run optional deep validation with sample queries, and return component health status
3. WHEN `get_health_trend` is called, THE MCP_Server SHALL read persisted health snapshots and return count trends, latency trends, and anomaly detection results
4. WHEN `get_quality_metrics` is called, THE MCP_Server SHALL read benchmark results and return formatted quality metrics with optional regression comparison
5. WHEN `get_server_info` is called, THE MCP_Server SHALL return server version, tool count, active modules, and capability information
6. FOR ALL utility tools, the Python tool input schemas SHALL match the Node.js tool input schemas exactly

### Requirement 13: Parity Testing Framework

**User Story:** As a developer, I want an automated parity testing framework that validates each ported Python tool produces equivalent results to the Node.js implementation, so that I can confidently cut over modules without regression.

#### Acceptance Criteria

1. THE Parity_Test framework SHALL execute the same query against both the Node.js server (port 3000) and the Python server (port 8000) and compare results
2. THE Parity_Test framework SHALL support per-tool parity assertions: exact match for document IDs, set equality for graph node names, and tolerance-based comparison for relevance scores
3. WHEN a parity test is run for a tool module, THE Parity_Test framework SHALL execute a minimum of 5 representative queries per tool and report pass/fail with detailed diffs
4. THE Parity_Test framework SHALL support a `--module` flag to run parity tests for a specific tool module (e.g., `--module SemanticSearchTools`)
5. THE Parity_Test framework SHALL produce a summary report showing per-tool pass/fail status, total queries tested, and any result divergences
6. IF a parity test detects a result divergence beyond the configured tolerance, THEN THE Parity_Test framework SHALL report the divergence with both the Node.js and Python results for debugging
7. THE Parity_Test framework SHALL be executable as a CI step with exit code 0 for all-pass and non-zero for any failure

### Requirement 14: Strands Agents Integration Layer

**User Story:** As a developer, I want a Strands Agents orchestration layer that consumes the Python MCP tools and enables multi-agent workflows, so that specialized agents can autonomously perform complex tasks like impact analysis and compliance auditing.

#### Acceptance Criteria

1. THE Strands_Agent layer SHALL consume all 51 MCP tools from the Python MCP_Server via the MCP client protocol
2. THE Strands_Agent layer SHALL support creating specialized agents with system prompts, tool subsets, and Bedrock model selection (Claude Opus, Sonnet, Haiku, Nova)
3. WHEN a multi-agent workflow is initiated, THE Strands_Agent layer SHALL support agent-to-agent handoffs using the Strands GraphBuilder for directed workflow orchestration
4. THE Strands_Agent layer SHALL support at least three predefined agent profiles: Code Analyst (code analysis + graph tools), Compliance Auditor (EE2 tools), and Knowledge Curator (semantic search + health tools)
5. WHEN an agent executes a multi-step workflow, THE Strands_Agent layer SHALL record each step (tool calls, reasoning, results) for observability
6. THE Strands_Agent layer SHALL support model routing based on task complexity: Haiku for high-volume low-cost operations, Sonnet for standard tool-calling, and Opus for complex reasoning

### Requirement 15: AgentCore Memory Integration

**User Story:** As a developer, I want the Python server to integrate with AgentCore Memory for persistent short-term and long-term memory, so that agents can maintain context within sessions and learn from past interactions across sessions.

#### Acceptance Criteria

1. WHEN a Strands_Agent session starts, THE MCP_Server SHALL create or resume a short-term memory (STM) store in AgentCore Memory for conversation context
2. WHEN a Strands_Agent session ends, THE MCP_Server SHALL extract key insights and persist them to long-term memory (LTM) in AgentCore Memory
3. THE MCP_Server SHALL support shared memory stores that allow multiple agents to access the same long-term memory
4. WHEN SDD session state is created or updated, THE MCP_Server SHALL persist the state to AgentCore Memory instead of local JSONL files
5. IF AgentCore Memory is unavailable, THEN THE MCP_Server SHALL fall back to local file-based persistence and log a warning

### Requirement 16: AgentCore Gateway and Cedar Policy Integration

**User Story:** As a developer, I want the Python MCP tools published through AgentCore Gateway with Cedar policy enforcement, so that per-tool access control and rate limiting are available.

#### Acceptance Criteria

1. THE MCP_Server SHALL be deployable as an AgentCore Gateway target, exposing all 51 tools as individually addressable endpoints
2. THE MCP_Server SHALL support Cedar policy evaluation on every tool call, enforcing per-tool and per-user access control
3. WHEN a tool call is denied by Cedar policy, THE MCP_Server SHALL return a structured error with the policy decision reason
4. THE MCP_Server SHALL support at least three Cedar policy patterns: role-based tool access (e.g., EE2 tools restricted to auditors), per-user rate limiting, and collection-level data restrictions on `search_documentation`
5. THE MCP_Server SHALL authenticate users via OAuth 2.0 through AgentCore Identity (Cognito integration)

### Requirement 17: Observability and Evaluations Integration

**User Story:** As a developer, I want OpenTelemetry-based observability for every tool call and automated quality evaluations, so that I can monitor performance, detect anomalies, and catch regressions in production.

#### Acceptance Criteria

1. THE MCP_Server SHALL emit OpenTelemetry traces for every tool call, including tool name, latency, input parameters, result size, and error status
2. THE MCP_Server SHALL emit OpenTelemetry traces for every database operation (OpenSearch queries, Neptune queries) with query type and latency
3. WHEN a Strands_Agent executes a multi-step workflow, THE MCP_Server SHALL emit a parent trace spanning all tool calls with child spans for each step
4. THE MCP_Server SHALL export traces to CloudWatch via the OpenTelemetry Collector
5. THE MCP_Server SHALL support AgentCore Evaluations for automated quality assessment, replacing the custom `benchmark_runner.py` and `get_quality_metrics` tool
6. IF a tool call latency exceeds a configurable threshold, THEN THE MCP_Server SHALL emit a warning-level log with the tool name and latency

### Requirement 18: Deployment and Cutover Strategy

**User Story:** As a developer, I want a deployment strategy where the Python server can run alongside the Node.js server during the port, with per-module cutover capability, so that production traffic is never disrupted.

#### Acceptance Criteria

1. THE MCP_Server SHALL be deployable to AgentCore Runtime as a container listening on port 8000
2. WHILE the port is in progress, THE Node.js server SHALL continue serving production traffic on its existing endpoint
3. THE MCP_Server SHALL support a `--modules` flag to selectively enable only ported tool modules, allowing incremental deployment
4. WHEN a tool module passes all parity tests, THE deployment process SHALL support cutting over that module's traffic from Node.js to Python without restarting either server
5. THE MCP_Server SHALL include a Dockerfile and `agentcore deploy` configuration for AgentCore Runtime deployment
6. THE MCP_Server SHALL include a `pyproject.toml` with all Python dependencies pinned to specific versions for reproducible builds
7. IF the Python server encounters an unrecoverable error for a tool module, THEN THE deployment process SHALL support rolling back that module to the Node.js implementation
