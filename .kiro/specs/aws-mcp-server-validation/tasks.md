# Implementation Plan: AWS MCP Server Validation

## Overview

Systematic validation of the AWS-native MCP server (`mdc-mcp-rag-aws`) running with `DB_BACKEND=aws`. The implementation creates a validation script that programmatically invokes all 51 tools against OpenSearch and Neptune backends, APOC transform property tests via vitest + fast-check, and a parity comparison against the legacy `eib-mcp-gateway`. All work is in JavaScript, executed from `mcp_server_node/`.

## Tasks

- [x] 1. Create validation script scaffold and test manifest
  - [x] 1.1 Create `mcp_server_node/scripts/validate-aws-mcp.js` — DONE (CLI commit e2703ac)
  - [x] 1.2 Define the full test manifest — DONE (45 tools tested, 4 GitHub skipped)
    - _Results: 45/45 pass, report at docs/aws-mcp-validation-report.md_

- [x] 2. Implement connection and health check validation
  - [x] 2.1 Adapter import resolution — DONE (4 fixes applied: NeptuneAdapter SigV4, OpenSearch index mapping, shared dataAccess, health check compat)
  - [x] 2.2 Neptune connection — DONE (SigV4 IAM auth, Bolt+s, retry with backoff)
  - [x] 2.3 OpenSearch connection — DONE (SigV4 client, 5 indices verified)
  - [x] 2.4 Health check — DONE (9/9 HEALTHY on AWS MCP, verified live April 13)

- [x] 3. Checkpoint — connection validation passes
  - _All connections verified, 45/45 tools pass_
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
  - [ ] 4.1 Create vitest test file — DEFERRED (tools work without APOC transforms on Neptune)

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

- [ ] 5. Checkpoint — APOC property tests — DEFERRED

- [x] 6. Parity comparison — AWS vs Legacy
  - [x] 6.1 search_documentation "data assimilation" — DONE (same 3 CICE docs, same order, scores within tolerance)
  - [x] 6.2 get_knowledge_base_status — DONE (legacy 85,995 docs / AWS 85,921 docs, 2,633,374 rels)
  - [x] 6.3 find_env_dependencies "HOMEgfs" — DONE (AWS returns 5 J-Jobs via Neptune, legacy uses GGSR path)
  - [x] 6.4 mcp_health_check — DONE (legacy 8/9, AWS 9/9 HEALTHY)
  - [ ] 6.5 trace_full_execution_chain "JGLOBAL_FORECAST" — NOT YET TESTED
  - _Note: Parity confirmed via live MCP tool calls April 13, 2026_

- [x] 7. Implement report generator
  - [x] 7.1 Report generated at `docs/aws-mcp-validation-report.md` — DONE (CLI commit 3b3e8c1)
  - [x] 7.2 Report includes per-module breakdown, adapter fixes, performance metrics — DONE

- [x] 8. Checkpoint — validation script runs end-to-end — DONE (45/45 pass)

- [x] 9. Documentation and wrap-up
  - [x] 9.1 CHANGELOG updated to v8.3.0 — DONE
  - [x] 9.2 Steering files updated — DONE
  - [x] 9.3 SDD history updated — DONE

- [x] 10. Final checkpoint
  - 45/45 tools pass via CLI validation script
  - 9/9 HEALTHY via live Kiro MCP health check
  - Parity confirmed on 4/5 key queries via live side-by-side testing
  - Report at docs/aws-mcp-validation-report.md

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
  - **RESOLVED**: Stateless HTTP transport via mcp-http-server.js works. Root cause was SSH double-hop latency killing stdio handshake. Production fix: deploy via AgentCore Runtime (Phase 51b).

- [ ] 12. Deploy MCP server via AWS Bedrock AgentCore Runtime
  - **PRIORITY**: Replace mcp-http-server.js development bridge with managed AWS deployment
  - See SDD: `sdd_framework/workflows/phase51b_agentcore_mcp_deployment.md`
  - [ ] 12.1 Install AgentCore toolkit: `pip install bedrock-agentcore-starter-toolkit`
  - [ ] 12.2 Wrap UnifiedMCPServer with BedrockAgentCoreApp entrypoint
  - [ ] 12.3 Configure: `agentcore configure --entrypoint agentcore-entrypoint --non-interactive`
  - [ ] 12.4 Test locally: `agentcore dev` + `agentcore invoke --dev`
  - [ ] 12.5 Deploy: `agentcore launch`
  - [ ] 12.6 Update Kiro mcp.json with AgentCore endpoint URL
  - [ ] 12.7 Configure AgentCore Gateway for multi-user auth
  - [ ] 12.8 Remove development bridge (mcp-http-server.js, port 3000 SG rule)

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation against live AWS backends
- Property tests validate APOC transform correctness properties using fast-check
- The validation script is designed to be re-runnable and produces a fresh report each time
- Legacy parity comparison requires the dev tunnel to be active (`--skip-legacy` if unavailable)
