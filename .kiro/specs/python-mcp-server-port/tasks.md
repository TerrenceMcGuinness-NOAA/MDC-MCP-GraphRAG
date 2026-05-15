# Implementation Plan: Python MCP Server Port

## Overview

Port the MDC MCP/RAG Server from Node.js/JavaScript (~9,000 lines, 9 tool modules, 51 tools) to Python using FastMCP and Strands Agents SDK. The implementation follows a module-by-module strategy across 14 phases (B1–B14, ~16 weeks), validating each module against the Node.js baseline via parity tests before cutover. All code lives under `mcp_server_python/`.

## Tasks

- [ ] 1. Project scaffolding and configuration (Phase B1)
  - [ ] 1.1 Create project structure and `pyproject.toml`
    - Create `mcp_server_python/` directory with the full module structure from the design: `src/`, `src/config/`, `src/data/`, `src/graphrag/`, `src/tools/`, `src/sdd/`, `src/agents/`, `tests/`, `tests/parity/`, `tests/properties/`, `tests/unit/`
    - Create `pyproject.toml` with pinned dependencies: `fastmcp`, `opensearch-py`, `boto3`, `hypothesis`, `pytest`, `pytest-asyncio`, `httpx`, `strands-agents`, `strands-agents-tools`, `opentelemetry-api`, `opentelemetry-sdk`
    - Create `Dockerfile` for AgentCore Runtime (Python 3.12, port 8000)
    - Create `.bedrock_agentcore.yaml` deployment config
    - Add all `__init__.py` files for every package
    - _Requirements: 1.1, 1.4, 18.5, 18.6_

  - [ ] 1.2 Implement environment configuration module
    - Create `src/config/environment.py` with `load_config()` returning a `ServerConfig` dataclass
    - Load all env vars: `DB_BACKEND`, `NEPTUNE_ENDPOINT`, `OPENSEARCH_ENDPOINT`, `AWS_REGION`, `GITHUB_TOKEN`, `SDD_STATE_DIR`, `HOST`, `PORT`
    - Create `src/config/aws_config.py` for AWS region and endpoint defaults
    - _Requirements: 1.8, 3.7_

  - [ ]* 1.3 Write unit tests for environment configuration
    - Test `load_config()` with various env var combinations
    - Test defaults when env vars are missing
    - Test `DB_BACKEND` routing (`aws` vs `legacy`)
    - _Requirements: 1.8_

  - [ ] 1.4 Implement FastMCP server entrypoint
    - Create `src/mcp_server.py` with FastMCP initialization, `initialize()` async function, and `mcp.run()` on port 8000
    - Implement module-based tool registration loop with `enabled_modules` filtering
    - Implement degraded mode: catch adapter init failures, log error, continue with available tools
    - Support `--modules` CLI flag for selective module enablement
    - _Requirements: 1.1, 1.3, 1.4, 1.6, 1.7, 18.3_

- [ ] 2. Database adapter protocols and backend selector (Phase B2)
  - [ ] 2.1 Define database adapter protocols
    - Create `src/data/protocols.py` with `VectorDBProtocol` and `GraphDBProtocol` as Python `Protocol` classes matching the design interfaces exactly
    - Include all method signatures: `connect`, `query`, `multi_collection_query`, `health_check`, `close` for VectorDB; `connect`, `query`, `health_check`, `close` for GraphDB
    - _Requirements: 2.1, 3.1_

  - [ ] 2.2 Implement OpenSearch adapter
    - Create `src/data/opensearch_adapter.py` implementing `VectorDBProtocol`
    - Wrap existing `aws_backend.OpenSearchVectorClient` with async query interface
    - Implement hybrid BM25 + k-NN query construction with RRF fusion
    - Implement `_format_hits()` to return `DocumentResult`-compatible dicts (id, content, metadata, score)
    - Support all 5 production indices: `mdc-code-context-mpnet768`, `mdc-workflow-docs-mpnet768`, `mdc-jjobs-mpnet768`, `mdc-community-summaries-mpnet768`, `mdc-ee2-standards-mpnet768`
    - Implement retry with exponential backoff (max 3 retries, 1s → 2s → 4s) for HTTP 429/5xx
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [ ]* 2.3 Write property tests for OpenSearch adapter (Properties 2, 3, 4)
    - **Property 2: OpenSearch Query Construction** — For any valid (query_text, k, similarity_threshold), the constructed query body contains both BM25 `match` and k-NN `knn` clauses with correct parameters
    - **Validates: Requirements 2.2, 2.3**
    - **Property 3: OpenSearch Result Schema Preservation** — For any valid OpenSearch response hits, `_format_hits` returns dicts with `id`, `content`, `metadata`, `score` keys with correct values
    - **Validates: Requirements 2.5**
    - **Property 4: OpenSearch Retry on Transient Errors** — For 0 ≤ N ≤ 3 transient errors followed by success, adapter retries exactly N times; for N > 3, raises error
    - **Validates: Requirements 2.6**

  - [ ] 2.4 Implement Neptune adapter
    - Create `src/data/neptune_adapter.py` implementing `GraphDBProtocol`
    - Wrap existing `aws_backend.NeptuneHTTPAdapter` with async query interface
    - Implement `_convert_record()` to parse Neptune JSON into Python dicts matching Node.js `_recordToObject` output format
    - Support parameterized openCypher queries with JSON-serialized parameters in POST body
    - Support session-based execution with context manager
    - Implement retry with exponential backoff (max 3 retries, 1s → 2s → 4s) for HTTP 429/500/503 and ConcurrentModificationException
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

  - [ ]* 2.5 Write property tests for Neptune adapter (Properties 5, 6, 7)
    - **Property 5: Neptune Parameter Serialization** — For any valid query string and param dict (str/int/float/bool/list values), parameters are serialized as JSON in POST body accepted by Neptune
    - **Validates: Requirements 3.2**
    - **Property 6: Neptune Result Parsing** — For any valid Neptune JSON response, `_convert_record` produces dicts matching Node.js `_recordToObject` output format
    - **Validates: Requirements 3.3**
    - **Property 7: Neptune Retry on Transient Errors** — For 0 ≤ N ≤ 3 transient errors followed by success, adapter retries exactly N times; for N > 3, raises `NeptuneQueryError`
    - **Validates: Requirements 3.5**

  - [ ] 2.6 Implement UnifiedDataAccess facade and backend selector
    - Create `src/data/unified_data_access.py` as facade over both adapters, exposing `hybrid_search()`, `graph_query()`, `health_check()` methods
    - Create `src/data/backend_selector.py` with `create_data_access(config)` that routes to AWS or legacy backends based on `DB_BACKEND` env var
    - _Requirements: 1.6, 1.8_

  - [ ]* 2.7 Write unit tests for backend selector
    - Test `create_data_access` routes correctly for `aws` and `legacy` backends
    - Test degraded mode when one adapter fails to initialize
    - _Requirements: 1.7, 1.8_

- [ ] 3. Checkpoint — Validate foundation
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. GGSR traversal engine (Phase B3)
  - [ ] 4.1 Implement GGSR traversal engine
    - Create `src/graphrag/ggsr_traversal.py` with `GGSRTraversal` class
    - Implement `WEIGHT_MATRIX` dict by copying `RELATIONSHIP_WEIGHTS` verbatim from Node.js `mcp_server_node/src/graphrag/GGSRTraversalPrototypes.js`. Authoritative values: CALLS=1.0, EXECUTES=1.0, SOURCES=0.95, INVOKES=0.9, CALLED_BY=0.9, DEPENDS_ON=0.8, DEPENDS_ON_ENV=0.8, IMPORTS=0.7, USES=0.7, INHERITS=0.7, DEFINES=0.65, PROVIDED_BY=0.6, EXPORTS=0.6, DOC_REFERENCES=0.6, DOC_DESCRIBES=0.55, TRANSITIVELY_DEPENDS=0.5, HAS_METHOD=0.5, CONTAINS=0.5, SETS=0.5, DOCUMENTED_BY=0.4, SAME_DIRECTORY=0.4, BUILT_BY=0.35, BUILD_ORCHESTRATES=0.35, REQUIRES_VERSION=0.3, AUTHORED=0.3, AUTHORED_BY=0.3, CONTRIBUTED_TO=0.3. Any divergence breaks Task 7 parity tests.
    - Implement `HOP_DECAY = 0.5` (matching Node.js)
    - Implement `BRIDGE_DECAY_OVERRIDE = 0.8` for cross-language bridges (Shell↔Fortran↔Python)
    - Implement `DEFAULT_WEIGHT = 0.3` fallback for unknown relationship types
    - Implement `budget_aware_neighborhood()` with multi-hop query, weight scoring, hop decay, and token budget trimming
    - Implement `_score_results()`: score = WEIGHT_MATRIX[rel] × HOP_DECAY^hop_distance, sorted descending
    - Implement `_trim_to_budget()`: accumulate tokens until budget exceeded
    - _Requirements: 6.6_

  - [ ] 4.2 Implement GraphGuidedRetrieval
    - Create `src/graphrag/graph_guided_retrieval.py` with `GraphGuidedRetrieval` class
    - Combine GGSR graph traversal with OpenSearch vector search for hybrid retrieval
    - Support `get_code_context` workflow: graph neighborhood → weight scoring → semantic enrichment
    - _Requirements: 6.2, 6.8_

  - [ ]* 4.3 Write property tests for GGSR (Property 9)
    - **Property 9: GGSR Scoring Correctness** — For any set of results with relationship types from WEIGHT_MATRIX and hop distances ≥ 1, scoring computes weight × decay^hop, sorts descending, and trims to token budget
    - **Validates: Requirements 6.6**

- [ ] 5. SDD session manager (Phase B3)
  - [ ] 5.1 Implement SDD session manager
    - Create `src/sdd/session_manager.py` with `SessionManager` class
    - Implement all data models: `SDDSession`, `SDDStep`, `FileModification`, `Checkpoint`
    - Implement session lifecycle: `start_session()`, `record_step()`, `complete_session()`, `abandon_session()`
    - Implement state tracking: `examine_symbol()`, `mark_modified()`, `checkpoint_state()`, `restore_checkpoint()`
    - Implement JSONL persistence to `sdd_framework/execution_state/` matching Node.js file format
    - _Requirements: 6.7, 9.2, 9.3, 9.4, 9.5_

  - [ ]* 5.2 Write property tests for SDD session (Properties 10, 11)
    - **Property 10: Session State Consistency** — For any sequence of session operations (examine_symbol, mark_modified, checkpoint, restore_checkpoint), state is consistent: examined_symbols and modifications reflect operations, checkpoint restore reverts state
    - **Validates: Requirements 6.7**
    - **Property 11: SDD Session Lifecycle Round-Trip** — For any valid lifecycle (start → record N steps → complete), JSONL serialize/deserialize produces equivalent session object
    - **Validates: Requirements 9.5, 9.7**

  - [ ]* 5.3 Write unit tests for session manager
    - Test session start with phase name
    - Test step recording with tags
    - Test checkpoint create and restore
    - Test JSONL file format compatibility
    - _Requirements: 9.2, 9.3, 9.4, 9.5_

- [ ] 6. Checkpoint — Validate core engine
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Parity testing framework (Phase B4)
  - [ ] 7.1 Implement parity test runner
    - Create `tests/parity/parity_runner.py` with `ParityRunner` class
    - Implement dual-server MCP client: Node.js at port 3000, Python at port 8000
    - Implement comparison modes: `exact` (document IDs), `set_equality` (graph node names), `tolerance` (relevance scores within 10%)
    - Implement `assert_parity()` method that runs tool on both servers and compares
    - Support `--module` flag for per-module parity testing
    - Generate summary report: per-tool pass/fail, total queries, divergences with both results
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7_

  - [ ] 7.2 Create shared test fixtures
    - Create `tests/conftest.py` with mock adapters, sample data fixtures, and async test helpers
    - Create mock `VectorDBProtocol` and `GraphDBProtocol` implementations for unit testing
    - _Requirements: 13.1_

- [ ] 8. SemanticSearchTools port (Phase B5)
  - [ ] 8.1 Implement SemanticSearchTools module
    - Create `src/tools/semantic_search.py` with `register(mcp, data)` function
    - Port all 7 tools: `search_documentation`, `find_related_files`, `explain_with_context`, `get_knowledge_base_status`, `list_ingested_urls`, `get_ingested_urls_array`, `check_knowledge_integrity`
    - Ensure tool input schemas (parameter names, types, descriptions, required flags) match Node.js exactly
    - `search_documentation`: hybrid BM25 + vector + RRF with graph enrichment from Neptune
    - `find_related_files`: vector similarity + graph neighborhood for dependency relationships
    - `check_knowledge_integrity`: path consistency, orphaned nodes, stale embeddings, coverage gaps
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_

  - [ ]* 8.2 Write parity tests for SemanticSearchTools
    - Create `tests/parity/test_semantic_search_parity.py`
    - Minimum 5 representative queries per tool
    - Validate top-5 document ID match for `search_documentation`
    - _Requirements: 4.8, 13.3_

- [ ] 9. CodeAnalysisTools port (Phase B6)
  - [ ] 9.1 Implement CodeAnalysisTools module
    - Create `src/tools/code_analysis.py` with `register(mcp, data)` function
    - Port all 6 tools: `analyze_code_structure`, `find_dependencies`, `trace_execution_path`, `find_callers_callees`, `trace_full_execution_chain`, `find_env_dependencies`
    - Ensure tool input schemas match Node.js exactly
    - `find_callers_callees`: support `cross_language` flag for Shell↔Fortran↔Python boundaries
    - `trace_full_execution_chain`: follow SOURCES, INVOKES, EXECUTES, CALLS, USES, DEFINES edges across languages
    - Support `token_budget` parameter for GGSR-weighted context limiting
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_

  - [ ]* 9.2 Write parity tests for CodeAnalysisTools
    - Create `tests/parity/test_code_analysis_parity.py`
    - Minimum 5 representative queries per tool
    - Validate same caller/callee function names for `find_callers_callees`
    - _Requirements: 5.8, 13.3_

- [ ] 10. GraphRAGTools port (Phase B7)
  - [ ] 10.1 Implement GraphRAGTools module
    - Create `src/tools/graph_rag.py` with `register(mcp, data)` function
    - Port all 9 tools: `get_code_context`, `search_architecture`, `find_similar_code`, `get_change_impact`, `trace_data_flow`, `mark_as_modified`, `get_session_context`, `checkpoint_state`, `restore_checkpoint`
    - Ensure tool input schemas match Node.js exactly
    - `get_code_context`: use GGSR traversal for graph neighborhood + community summary + semantic snippets
    - `get_change_impact`: traverse direct/indirect dependents, compute risk score
    - Session tools (`mark_as_modified`, `get_session_context`, `checkpoint_state`, `restore_checkpoint`): delegate to `SessionManager`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.7, 6.8, 6.9_

  - [ ]* 10.2 Write parity tests for GraphRAGTools
    - Create `tests/parity/test_graph_rag_parity.py`
    - Minimum 5 representative queries per tool
    - Validate same symbols and scores within 10% tolerance for `get_code_context`
    - _Requirements: 6.8, 13.3_

- [ ] 11. Checkpoint — Validate core tool modules
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 12. EE2ComplianceTools port (Phase B8)
  - [ ] 12.1 Implement EE2ComplianceTools module
    - Create `src/tools/ee2_compliance.py` with `register(mcp, data)` function
    - Port all 5 tools: `search_ee2_standards`, `analyze_ee2_compliance`, `generate_compliance_report`, `scan_repository_compliance`, `extract_code_for_analysis`
    - Ensure tool input schemas match Node.js exactly
    - `analyze_ee2_compliance`: analyze against categories: error_handling, environment_variables, file_naming, shebang_compliance, production_utilities
    - `extract_code_for_analysis`: extract snippets by category with LLM prompts
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

  - [ ]* 12.2 Write parity tests for EE2ComplianceTools
    - Create `tests/parity/test_ee2_compliance_parity.py`
    - Minimum 5 representative queries per tool
    - Validate same compliance violations detected
    - _Requirements: 7.7, 13.3_

  - [ ]* 12.3 Write property test for EE2 compliance detection (Property 12)
    - **Property 12: EE2 Compliance Detection Consistency** — For any code snippet with known compliance patterns (missing `set -eu`, unvalidated env vars, non-standard file naming), Python detects same violation categories as Node.js
    - **Validates: Requirements 7.7**

- [ ] 13. OperationalTools port (Phase B9)
  - [ ] 13.1 Implement OperationalTools module
    - Create `src/tools/operational.py` with `register(mcp, data)` function
    - Port all 4 tools: `get_operational_guidance`, `explain_workflow_component`, `list_job_scripts`, `get_job_details`
    - Ensure tool input schemas match Node.js exactly
    - `get_job_details`: return inputs, outputs, dependencies, config content, semantic search results
    - `list_job_scripts`: support category filtering and search term
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [ ]* 13.2 Write parity tests for OperationalTools
    - Create `tests/parity/test_operational_parity.py`
    - Minimum 5 representative queries per tool
    - Validate same job metadata fields for `get_job_details`
    - _Requirements: 8.6, 13.3_

- [ ] 14. SDDWorkflowTools port (Phase B10)
  - [ ] 14.1 Implement SDDWorkflowTools module
    - Create `src/tools/sdd_workflow.py` with `register(mcp, data)` function
    - Port all 9 tools: `list_sdd_workflows`, `get_sdd_workflow`, `start_sdd_session`, `record_sdd_step`, `get_sdd_session`, `complete_sdd_session`, `get_sdd_execution_history`, `validate_sdd_compliance`, `get_sdd_framework_status`
    - Ensure tool input schemas match Node.js exactly
    - Delegate session operations to `SessionManager`
    - Read/write SDD state files in same format and directory structure as Node.js
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

  - [ ]* 14.2 Write unit tests for SDDWorkflowTools
    - Test session lifecycle: start → record steps → complete
    - Test state file format compatibility with Node.js
    - _Requirements: 9.5, 9.7_

- [ ] 15. WorkflowInfoTools port (Phase B10)
  - [ ] 15.1 Implement WorkflowInfoTools module
    - Create `src/tools/workflow_info.py` with `register(mcp, data)` function
    - Port all 3 tools: `get_workflow_structure`, `get_system_configs`, `describe_component`
    - Ensure tool input schemas match Node.js exactly
    - `get_workflow_structure`: return directory structure with optional component focus (jobs, scripts, parm, ush, sorc, docs, env)
    - `get_system_configs`: return platform-specific config (modules, resources, paths) for hera, hercules, orion, wcoss2, gaea
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

- [ ] 16. GitHubTools port (Phase B11)
  - [ ] 16.1 Implement GitHubTools module
    - Create `src/tools/github_tools.py` with `register(mcp, data)` function
    - Port all 4 tools: `search_issues`, `get_pull_requests`, `analyze_workflow_dependencies`, `analyze_repository_structure`
    - Ensure tool input schemas match Node.js exactly
    - Authenticate via `GITHUB_TOKEN` environment variable
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

- [ ] 17. Utility tools port (Phase B11)
  - [ ] 17.1 Implement utility tools module
    - Create `src/tools/utility.py` with `register(mcp, data)` function
    - Port all 4 tools: `get_server_info`, `mcp_health_check`, `get_health_trend`, `get_quality_metrics`
    - Ensure tool input schemas match Node.js exactly
    - `mcp_health_check`: verify OpenSearch and Neptune connectivity, optional deep validation with sample queries
    - `get_server_info`: return version, tool count, active modules, capabilities
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

- [ ] 18. Tool schema parity validation (Phase B11)
  - [ ]* 18.1 Write property test for tool schema parity (Properties 1, 8)
    - **Property 1: Tool Routing Correctness** — For any registered tool name with valid arguments, server routes to correct handler and returns non-error result
    - **Validates: Requirements 1.3**
    - **Property 8: Tool Schema Parity** — For all 51 tools, Python input schema (parameter names, types, required flags, description) is identical to Node.js input schema
    - **Validates: Requirements 4.7, 5.7, 6.9, 7.6, 8.5, 9.6, 10.5, 11.5, 12.6**

- [ ] 19. Checkpoint — Validate all tool modules ported
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 20. Strands Agents integration layer (Phase B12)
  - [ ] 20.1 Implement agent profiles
    - Create `src/agents/profiles.py` with predefined agent profiles
    - Define Code Analyst profile: code analysis + graph tools, Sonnet model
    - Define Compliance Auditor profile: EE2 tools, Sonnet model
    - Define Knowledge Curator profile: semantic search + health tools, Haiku model
    - Support model routing: Haiku for high-volume, Sonnet for standard, Opus for complex reasoning
    - _Requirements: 14.2, 14.4, 14.6_

  - [ ] 20.2 Implement multi-agent orchestrator
    - Create `src/agents/orchestrator.py` with Strands `GraphBuilder` for directed workflow orchestration
    - Implement agent-to-agent handoffs
    - Consume all 51 MCP tools via MCP client protocol
    - Record each step (tool calls, reasoning, results) for observability
    - _Requirements: 14.1, 14.3, 14.5_

- [ ] 21. AgentCore Memory integration (Phase B12)
  - [ ] 21.1 Implement memory integration
    - Create `src/agents/memory.py` with AgentCore Memory client
    - Implement STM: create/resume short-term memory store on session start
    - Implement LTM: extract key insights and persist to long-term memory on session end
    - Support shared memory stores for multi-agent access
    - Implement fallback to local file-based persistence when AgentCore Memory is unavailable
    - Migrate SDD session state persistence from JSONL to AgentCore Memory (with JSONL fallback)
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5_

- [ ] 22. AgentCore Gateway and Cedar policy integration (Phase B13)
  - [ ] 22.1 Implement Cedar policy enforcement
    - Add Cedar policy evaluation middleware to FastMCP server
    - Implement per-tool and per-user access control
    - Return structured error with policy decision reason on denial
    - Implement three Cedar policy patterns: role-based tool access, per-user rate limiting, collection-level data restrictions on `search_documentation`
    - _Requirements: 16.2, 16.3, 16.4_

  - [ ] 22.2 Configure AgentCore Gateway deployment
    - Configure MCP server as AgentCore Gateway target exposing all 51 tools
    - Implement OAuth 2.0 authentication via AgentCore Identity (Cognito)
    - _Requirements: 16.1, 16.5_

- [ ] 23. Observability integration (Phase B13)
  - [ ] 23.1 Implement OpenTelemetry instrumentation
    - Add OpenTelemetry tracing to every tool call: tool name, latency, input parameters, result size, error status
    - Add OpenTelemetry tracing to every database operation: query type, latency
    - Implement parent trace spanning for multi-step Strands Agent workflows with child spans per step
    - Configure trace export to CloudWatch via OpenTelemetry Collector
    - Implement configurable latency threshold warning logs
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.6_

  - [ ] 23.2 Integrate AgentCore Evaluations
    - Replace custom `benchmark_runner.py` with AgentCore Evaluations for automated quality assessment
    - _Requirements: 17.5_

- [ ] 24. Checkpoint — Validate advanced features
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 25. Deployment and cutover (Phase B14)
  - [ ] 25.1 Finalize Dockerfile and deployment config
    - Finalize `Dockerfile` with production optimizations (multi-stage build, minimal image)
    - Finalize `.bedrock_agentcore.yaml` with production settings
    - Verify `agentcore deploy` works end-to-end
    - Ensure `--modules` flag enables incremental module deployment
    - _Requirements: 18.1, 18.3, 18.5_

  - [ ] 25.2 Implement rollback support
    - Implement per-module rollback capability: if Python server encounters unrecoverable error for a module, route that module back to Node.js
    - Document cutover procedure: parity tests pass → enable module in Python → monitor → confirm or rollback
    - _Requirements: 18.4, 18.7_

  - [ ]* 25.3 Run full parity test suite
    - Execute parity tests for all 9 tool modules against both servers
    - Verify all 51 tools pass parity with Node.js baseline
    - Generate final parity report
    - _Requirements: 13.3, 13.5, 13.7, 18.2_

- [ ] 26. Final checkpoint — All tests pass, port complete
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation at phase boundaries
- Property tests (Hypothesis, ≥100 iterations) validate universal correctness properties from the design
- Parity tests validate each module against the Node.js baseline before cutover
- The implementation language is Python throughout (FastMCP, pytest, Hypothesis)
- All code lives under `mcp_server_python/` following the directory structure in the design
