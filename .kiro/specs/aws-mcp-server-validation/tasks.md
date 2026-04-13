# Implementation Plan: AWS MCP Server Validation

## Overview

Systematic validation of the AWS-native MCP server (`mdc-mcp-rag-aws`) running with `DB_BACKEND=aws`. The implementation creates a validation script that programmatically invokes all 51 tools against OpenSearch and Neptune backends, APOC transform property tests via vitest + fast-check, and a parity comparison against the legacy `eib-mcp-gateway`. All work is in JavaScript, executed from `mcp_server_node/`.

## Tasks

- [ ] 1. Create validation script scaffold and test manifest
  - [ ] 1.1 Create `mcp_server_node/scripts/validate-aws-mcp.js` with CLI argument parsing (`--skip-legacy`, `--skip-github`, `--verbose`, `--timeout`)
    - Import `UnifiedMCPServer` and instantiate with `DB_BACKEND=aws`, `OPENSEARCH_ENDPOINT`, `NEPTUNE_ENDPOINT` from env
    - Implement the `runValidation()` orchestrator that iterates the test manifest, invokes each tool via `server.server.callTool()`, wraps each call in try/catch with per-tool timeout, and collects `ToolValidationResult` objects
    - Implement `classifyResult(toolName, response, validateFn)` that returns `{ status: 'pass'|'fail'|'error', details, durationMs }`
    - _Requirements: 15.1, 15.2_

  - [ ] 1.2 Define the full test manifest array covering all 51 tools organized by module
    - Each entry: `{ toolName, args, module, validate }` where `validate` is a function inspecting the response text
    - WorkflowInfoTools (3): `get_workflow_structure`, `get_system_configs { platform: 'hera' }`, `describe_component { component: 'jobs' }`
    - SemanticSearchTools (6): `search_documentation { query: 'data assimilation' }`, `explain_with_context { topic: 'forecast model' }`, `find_similar_code { code_or_symbol: 'setuprad' }`, `search_ee2_standards { query: 'error handling' }`, `find_related_files { file_path: 'scripts/exglobal_forecast.py' }`, `get_knowledge_base_status`
    - CodeAnalysisTools (5): `analyze_code_structure { file_path: 'scripts/exglobal_forecast.py' }`, `find_dependencies { target: 'exglobal_forecast.py' }`, `find_callers_callees { function_name: 'setuprad' }`, `trace_execution_path { function_name: 'setuprad' }`, `find_env_dependencies { variable_name: 'HOMEgfs' }`
    - GraphRAGTools (9): `get_code_context { symbol: 'setuprad' }`, `search_architecture { query: 'data assimilation' }`, `get_change_impact { symbol: 'setuprad' }`, `trace_data_flow { from_symbol: 'exglobal_atmos_analysis' }`, `trace_full_execution_chain { start: 'JGLOBAL_FORECAST' }`, `find_env_dependencies { variable_name: 'HOMEgfs' }`, `get_session_context`, `checkpoint_state { name: 'validation-test' }`, `mark_as_modified { file_path: 'test.txt' }`
    - OperationalTools (3): `get_operational_guidance { operation: 'forecast' }`, `explain_workflow_component { component: 'JGLOBAL_FORECAST' }`, `list_job_scripts`
    - GitHubTools (4): `search_issues { query: 'forecast' }`, `get_pull_requests`, `analyze_workflow_dependencies { component: 'forecast' }`, `analyze_repository_structure`
    - SDDWorkflowTools (9): `list_sdd_workflows`, `get_sdd_workflow { workflow_name: 'data_ingestion_workflow' }`, `start_sdd_session / get_sdd_session / complete_sdd_session` cycle, `record_sdd_step`, `get_sdd_execution_history`, `validate_sdd_compliance`, `get_sdd_framework_status`
    - EE2ComplianceTools (4): `analyze_ee2_compliance { content: '#!/bin/bash\nset -eu\n...' }`, `generate_compliance_report`, `scan_repository_compliance { files: [...] }`, `extract_code_for_analysis { content: '#!/bin/bash\n...' }`
    - Utility (7): `get_server_info`, `mcp_health_check { detailed: true }`, `get_health_trend`, `get_quality_metrics`, `list_ingested_urls`, `get_ingested_urls_array`, `get_job_details { job_name: 'JGLOBAL_FORECAST' }`
    - _Requirements: 5.1–5.3, 6.1–6.6, 7.1–7.4, 8.1–8.6, 9.1–9.3, 10.1–10.4, 11.1–11.5, 12.1–12.4, 15.1_

- [ ] 2. Implement connection and health check validation
  - [ ] 2.1 Add adapter import resolution checks at the top of the validation script
    - Verify `backend-selector.js` instantiates `OpenSearchAdapter` and `NeptuneAdapter` without import errors when `DB_BACKEND=aws`
    - Verify `NeptuneAdapter` resolves `apoc-transform.js` and `HealthChecker.js` imports
    - Verify `OpenSearchAdapter` resolves `@opensearch-project/opensearch` and `@aws-sdk/credential-provider-node`
    - Log any import failures to stderr with module path and error message
    - _Requirements: 1.1–1.5_

  - [ ] 2.2 Add Neptune connection validation logic
    - Verify endpoint `wss://...` is converted to `bolt+s://` and connection succeeds
    - Verify `MATCH (n) RETURN count(n) AS nodeCount LIMIT 1` returns nodeCount > 0
    - Verify retry behavior (up to 4 attempts with exponential backoff)
    - _Requirements: 2.1–2.4_

  - [ ] 2.3 Add OpenSearch connection validation logic
    - Verify SigV4 client creation with EC2 IAM role credentials
    - Verify `Xenova/all-mpnet-base-v2` embedding model loads as singleton
    - Verify `listCollections()` returns at least 5 indices: `mdc-code-context`, `mdc-workflow-docs`, `mdc-jjobs`, `mdc-community-summaries`, `mdc-ee2-standards`
    - _Requirements: 3.1–3.4_

  - [ ] 2.4 Add health check validation assertions
    - Verify `mcp_health_check` returns `status: healthy` for vector and graph
    - Verify OpenSearch cluster status is `green` or `yellow` with index count ≥ 5
    - Verify Neptune node count > 50,000
    - Verify `get_knowledge_base_status` returns ~85,921 vector docs and ~59,759 graph nodes
    - _Requirements: 4.1–4.4_

- [ ] 3. Checkpoint — Ensure connection validation passes
  - Ensure all connection and health check tests pass, ask the user if questions arise.

- [ ] 4. Implement APOC transform property tests
  - [ ] 4.1 Create `mcp_server_node/scripts/test-apoc-transform-properties.js` as a vitest test file using fast-check
    - Import `transformApoc` and `UnsupportedQueryError` from `../src/data/adapters/apoc-transform.js`
    - Configure vitest `describe` block for APOC transform properties
    - _Requirements: 13.1–13.4_

  - [ ]* 4.2 Write property test: APOC path.expand transform produces valid variable-length path
    - **Property 1: APOC path.expand transform**
    - Generate arbitrary valid start node names (alphanumeric), min/max depth (non-negative integers where min ≤ max), and path variable names
    - Construct `CALL apoc.path.expand(startNode, 'REL', 'Label', minDepth, maxDepth) YIELD path AS pathVar`
    - Assert result contains `MATCH pathVar = (startNode)-[*minDepth..maxDepth]->()`
    - Assert result does NOT contain `apoc.`
    - **Validates: Requirements 13.1**

  - [ ]* 4.3 Write property test: APOC merge.node transform produces valid MERGE statement
    - **Property 2: APOC merge.node transform**
    - Generate arbitrary label names, identity/onCreate/onMatch property objects, and alias names
    - Construct `CALL apoc.merge.node(['Label'], {identProps}, {onCreateProps}, {onMatchProps}) YIELD node AS alias`
    - Assert result contains `MERGE`, `ON CREATE SET`, and `ON MATCH SET` with the alias
    - Assert result does NOT contain `apoc.`
    - **Validates: Requirements 13.2**

  - [ ]* 4.4 Write property test: Non-APOC query passthrough
    - **Property 3: Non-APOC passthrough**
    - Generate arbitrary strings that do NOT contain `apoc.`
    - Assert `transformApoc(query) === query` (identity)
    - **Validates: Requirements 13.3**

  - [ ]* 4.5 Write property test: Unsupported APOC procedure error
    - **Property 4: Unsupported APOC error**
    - Generate arbitrary procedure names that are NOT one of the 5 supported (`path.expand`, `algo.dijkstra`, `periodic.iterate`, `create.node`, `merge.node`)
    - Construct `CALL apoc.<procedure>(...) YIELD ...`
    - Assert `transformApoc` throws `UnsupportedQueryError` with the procedure name
    - **Validates: Requirements 13.4**

  - [ ]* 4.6 Write property test: Report generation correctness
    - **Property 5: Report generation correctness**
    - Generate arbitrary arrays of `{ suite, status: 'pass'|'fail'|'error', name }` objects
    - Pass to the report generator function (extracted from validate-aws-mcp.js)
    - Assert `total === array.length`, `passed === count(status==='pass')`, `failed === count(status==='fail')`
    - Assert every unique `suite` value appears as a section heading
    - **Validates: Requirements 15.3, 15.4**

- [ ] 5. Checkpoint — Ensure APOC property tests pass
  - Ensure all property tests pass with `npx vitest run mcp_server_node/scripts/test-apoc-transform-properties.js`, ask the user if questions arise.

- [ ] 6. Implement parity comparison module
  - [ ] 6.1 Add parity comparison logic to the validation script
    - Implement `runParityComparison(awsServer, legacyUrl, token)` that calls 5 key queries on both servers
    - Query 1: `search_documentation` with "data assimilation" — compare document ID overlap and score deltas within 0.1
    - Query 2: `get_code_context` with "setuprad" — compare graph neighborhood node names
    - Query 3: `trace_full_execution_chain` with "JGLOBAL_FORECAST" — compare chain nodes and relationship types
    - Query 4: `get_knowledge_base_status` — compare vector counts within 1% and graph counts (59,759 AWS vs 98,813 legacy dedup difference)
    - Query 5: `find_env_dependencies` with "HOMEgfs" — compare dependent script name sets
    - _Requirements: 14.1–14.5_

  - [ ] 6.2 Implement legacy server HTTP caller
    - POST to `https://27gs01wv-18888.use.devtunnels.ms/mcp` with `Authorization: Bearer eib-mcp-gateway-token-2025`
    - Handle connection failures gracefully — skip parity if legacy unreachable
    - Parse MCP JSON-RPC response to extract tool result
    - _Requirements: 14.1_

- [ ] 7. Implement report generator
  - [ ] 7.1 Implement `generateReport(results, parityResults, environment)` function
    - Produce markdown with summary table: total/passed/failed/error counts
    - Group results by `module` with per-module breakdown table
    - Include detailed error logs for each failure (error message + stack trace)
    - Include parity comparison results section (or "skipped" note)
    - Include timestamp and environment info (DB_BACKEND, endpoints, Node version)
    - Write output to `docs/aws-mcp-validation-report.md`
    - _Requirements: 15.3, 15.4, 15.5_

  - [ ] 7.2 Export `generateReport` as a standalone function for property testing
    - Extract the report generation logic into a testable pure function
    - Accept `results[]` and return markdown string
    - This enables Property 5 to test report correctness independently
    - _Requirements: 15.3, 15.4_

- [ ] 8. Checkpoint — Ensure validation script runs end-to-end
  - Run `node mcp_server_node/scripts/validate-aws-mcp.js --skip-legacy --skip-github --timeout 60000` and ensure it completes without crashes, ask the user if questions arise.

- [ ] 9. Wire everything together and update documentation
  - [ ] 9.1 Add npm script entry for validation
    - Add `"validate:aws"` script to `mcp_server_node/package.json` pointing to `node scripts/validate-aws-mcp.js`
    - Add `"test:apoc-props"` script for `npx vitest run scripts/test-apoc-transform-properties.js`
    - _Requirements: 15.1_

  - [ ] 9.2 Update `CHANGELOG.md` with validation entry
    - Add entry documenting the AWS MCP server validation script, APOC property tests, and parity comparison
    - Document any adapter fixes applied during validation (file path, error, resolution)
    - _Requirements: 16.1, 16.2_

  - [ ] 9.3 Update Phase 48 progress steering file
    - Update `.kiro/steering/04-phase48-progress.md` with validation completion status
    - _Requirements: 16.3_

- [ ] 10. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Fix Kiro MCP stdio connection for mdc-mcp-rag-aws
  - **FOCUSED DEBUGGING TASK** — The AWS MCP server works perfectly via CLI (45/45 tools pass) but crashes ~48ms after Kiro spawns it via stdio transport.
  - **Findings from investigation (April 9-13, 2026):**
    - The server loads modules, prints `[OK] EE2ComplianceTools: Loaded Phase 2 config` to stderr, then the process exits before the MCP handshake completes
    - Manual MCP handshake via piped stdin works perfectly: `initialize` → `initialized` → `tools/list` returns all 51 tools
    - The server stays alive indefinitely when run manually (`node src/UnifiedMCPServer.js full`)
    - No uncaught exceptions or unhandled rejections detected with `--trace-uncaught`
    - stdout is clean (0 bytes) — no protocol corruption from console output
    - `quiet-console.js` correctly redirects all console.log to log file
    - The EE2 config line uses `console.error` (stderr), not stdout
    - Friday's "successful connection" was a false positive — Kiro attributed the IAM Policy Autopilot's startup message to our server
    - The server has NEVER successfully completed a Kiro stdio connection
  - **Attempted fixes that did NOT resolve the issue:**
    - Transport-first startup: moved `this.server.start()` before `dataAccess.connect()` — still crashes
    - setTimeout(2000) deferred connect: wrapped background connect in 2s delay — still crashes (process exits before timeout fires)
    - Absolute path in mcp.json: `/mdc-mcp-rag-server/mcp_server_node/src/UnifiedMCPServer.js` — fixed MODULE_NOT_FOUND but didn't fix the handshake crash
    - Removed IAM Policy Autopilot to eliminate resource contention — no effect
  - **Hypotheses to investigate:**
    - [ ] 11.1 **SSH double-hop latency (MOST LIKELY)** — Kiro IDE connects via SSH through a jump box (laptop → SSH → jump box → SSH → EC2). The MCP stdio transport sends every byte through this double-hop tunnel. The handshake requires multiple rapid request/response exchanges — if any round-trip exceeds the SDK's internal timeout (~50ms?), the connection drops. This explains why: (a) manual stdin piping works (local to EC2), (b) CLI validation works (local to EC2), (c) the 48ms crash gap matches SSH RTT, (d) the IAM autopilot connects (tiny handshake). **Fix: use HTTP transport instead of stdio** — HTTP is designed for latency and works over the same SSH tunnel that the legacy eib-mcp-gateway uses successfully.
    - [ ] 11.2 Check if the MCP SDK v1.26.0 StdioServerTransport has a known issue with Node.js v18.20.8 — try downgrading to SDK v1.24.3 or upgrading Node.js
    - [ ] 11.3 Check if the `quiet-console.js` top-level await import is interfering with the stdio transport setup
    - [ ] 11.4 Add a minimal MCP wrapper script that imports ONLY BaseServer with zero tools, test if that connects — isolate whether the issue is in tool registration or transport latency
    - [ ] 11.5 **Implement HTTP/SSE transport (recommended workaround)** — run the server with `express` or the MCP SDK's `StreamableHTTPServerTransport` on a local port (e.g., 3000), forward via SSH tunnel (`-L 3000:localhost:3000`), configure Kiro with `"type": "http", "url": "http://localhost:3000/mcp"`. This matches how the legacy eib-mcp-gateway works and avoids the stdio latency problem entirely.
    - [ ] 11.6 Capture the exact bytes Kiro sends on stdin during the handshake — add a tee/logging layer
    - [ ] 11.7 Check if Kiro's stdio spawner sets a connection timeout shorter than the SSH RTT
  - **Config**: `.kiro/settings/mcp.json` — currently `"disabled": true` to prevent crash loops
  - **Acceptance**: `mdc-mcp-rag-aws` shows `Connected (51 tools)` in Kiro MCP panel and stays connected for >60 seconds

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation against live AWS backends
- Property tests validate APOC transform correctness properties using fast-check
- The validation script is designed to be re-runnable and produces a fresh report each time
- Legacy parity comparison requires the dev tunnel to be active (`--skip-legacy` if unavailable)
