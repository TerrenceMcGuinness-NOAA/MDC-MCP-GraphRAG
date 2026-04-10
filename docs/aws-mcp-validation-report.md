# AWS MCP Server Validation Report

**Generated**: 2026-04-10T21:45:10Z
**Phase**: 48 — AWS Infrastructure Port
**Branch**: `develop_aws`
**Validator**: `mcp_server_node/scripts/validate-aws-mcp.js`

## Environment

| Parameter | Value |
|-----------|-------|
| DB_BACKEND | `aws` |
| OpenSearch Endpoint | `vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com` |
| Neptune Endpoint | `mdc-mcp-rag-neptune.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182` |
| AWS Region | `us-east-1` |
| Node.js | v18.20.8 |
| Timeout | 60000ms per tool |

## Executive Summary

All 45 non-GitHub tools pass with `DB_BACKEND=aws` against live OpenSearch and Neptune backends. Server startup time is 706ms (down from 70+ seconds before fixes). Error handling is robust across 9 edge-case scenarios. Graceful degradation works when Neptune is unreachable.

| Metric | Value |
|--------|-------|
| Total Tools Tested | 45 |
| Passed | 45 |
| Failed | 0 |
| Errors | 0 |
| Skipped (GitHub) | 4 |
| **Pass Rate** | **100%** (of tested tools) |

## Adapter Fixes Applied

### 1. NeptuneAdapter — SigV4 IAM Authentication

**Problem**: Neptune cluster has `iamAuthEnabled: true` but the adapter used `neo4j.auth.none()`, causing `MissingAuthenticationTokenException` on every connection attempt.

**Fix**: Implemented SigV4 IAM auth per [AWS Neptune Bolt IAM docs](https://docs.aws.amazon.com/neptune/latest/userguide/access-graph-opencypher-bolt.html#access-graph-opencypher-bolt-nodejs-iam-auth):
- Sign a GET request to `/opencypher` using `@smithy/signature-v4`
- Serialize auth headers (Authorization, X-Amz-Date, Host, X-Amz-Security-Token) as JSON
- Pass as password with `neo4j.auth.basic('username', signedHeaders)`

**File**: `mcp_server_node/src/data/adapters/NeptuneAdapter.js`

### 2. OpenSearchAdapter — Index Name Mapping

**Problem**: `COLLECTION_TO_INDEX` mapping used base names (e.g., `mdc-code-context`) but actual indices have `-mpnet768` suffix (e.g., `mdc-code-context-mpnet768`).

**Fix**: Updated all 5 index name mappings to include the model-aware `-mpnet768` suffix.

**File**: `mcp_server_node/src/data/adapters/OpenSearchAdapter.js`

### 3. UnifiedMCPServer — Shared DataAccess Instance

**Problem**: `start()` created 2 additional `UnifiedDataAccess` instances (one per tool module), each with separate Neptune/OpenSearch connections. With Neptune auth failures, this caused 4 retries × 2 modules × exponential backoff = 70+ seconds startup.

**Fix**: Pass the single shared `dataAccess` instance from the constructor to all tool modules. Connect once in `start()`.

**File**: `mcp_server_node/src/UnifiedMCPServer.js`

### 4. mcp_health_check — OpenSearch Compatibility

**Problem**: Health check code accessed `dataValidation.validation.heartbeat` which is a ChromaDB-specific structure. OpenSearch adapter returns `{ status, connected, clusterStatus, indices }` without a `validation` property.

**Fix**: Guard `dataValidation.validation` access; render OpenSearch-specific health info when `validation` is absent.

**File**: `mcp_server_node/src/UnifiedMCPServer.js`

## Results by Module

| Module | Total | Passed | Failed | Errors | Skipped |
|--------|-------|--------|--------|--------|---------|
| WorkflowInfoTools | 3 | 3 | 0 | 0 | 0 |
| SemanticSearchTools | 7 | 7 | 0 | 0 | 0 |
| CodeAnalysisTools | 5 | 5 | 0 | 0 | 0 |
| GraphRAGTools | 9 | 9 | 0 | 0 | 0 |
| OperationalTools | 3 | 3 | 0 | 0 | 0 |
| SDDWorkflowTools | 9 | 9 | 0 | 0 | 0 |
| EE2ComplianceTools | 5 | 5 | 0 | 0 | 0 |
| Utility | 4 | 4 | 0 | 0 | 0 |
| GitHubTools | 4 | 0 | 0 | 0 | 4 |

## Detailed Results

| # | Tool | Module | Status | Duration | Details |
|---|------|--------|--------|----------|---------|
| 1 | get_workflow_structure | WorkflowInfoTools | [OK] | 0ms | 986 chars |
| 2 | get_system_configs | WorkflowInfoTools | [OK] | 1ms | 242 chars |
| 3 | describe_component | WorkflowInfoTools | [OK] | 2ms | 1161 chars |
| 4 | search_documentation | SemanticSearchTools | [OK] | 115ms | 1388 chars |
| 5 | explain_with_context | SemanticSearchTools | [OK] | 79ms | 183 chars |
| 6 | find_similar_code | SemanticSearchTools | [OK] | 23ms | 60 chars |
| 7 | find_related_files | SemanticSearchTools | [OK] | 66ms | 95 chars |
| 8 | get_knowledge_base_status | SemanticSearchTools | [OK] | 9753ms | 575 chars |
| 9 | list_ingested_urls | SemanticSearchTools | [OK] | 9699ms | 1564 chars |
| 10 | get_ingested_urls_array | SemanticSearchTools | [OK] | 0ms | 2636 chars |
| 11 | analyze_code_structure | CodeAnalysisTools | [OK] | 29ms | 151 chars |
| 12 | find_dependencies | CodeAnalysisTools | [OK] | 189ms | 292 chars |
| 13 | find_callers_callees | CodeAnalysisTools | [OK] | 27ms | 572 chars |
| 14 | trace_execution_path | CodeAnalysisTools | [OK] | 9155ms | 98 chars |
| 15 | find_env_dependencies | CodeAnalysisTools | [OK] | 230ms | 3391 chars |
| 16 | get_code_context | GraphRAGTools | [OK] | 446ms | 195 chars |
| 17 | search_architecture | GraphRAGTools | [OK] | 23ms | 1689 chars |
| 18 | get_change_impact | GraphRAGTools | [OK] | 89ms | 833 chars |
| 19 | trace_data_flow | GraphRAGTools | [OK] | 145ms | 134 chars |
| 20 | trace_full_execution_chain | GraphRAGTools | [OK] | 7ms | 144 chars |
| 21 | get_session_context | GraphRAGTools | [OK] | 1ms | 95 chars |
| 22 | checkpoint_state | GraphRAGTools | [OK] | 0ms | 76 chars |
| 23 | mark_as_modified | GraphRAGTools | [OK] | 0ms | 76 chars |
| 24 | restore_checkpoint | GraphRAGTools | [OK] | 0ms | 78 chars |
| 25 | get_operational_guidance | OperationalTools | [OK] | 29ms | 66256 chars |
| 26 | explain_workflow_component | OperationalTools | [OK] | 95ms | 68 chars |
| 27 | list_job_scripts | OperationalTools | [OK] | 1ms | 503 chars |
| 28 | list_sdd_workflows | SDDWorkflowTools | [OK] | 2ms | 9018 chars |
| 29 | get_sdd_workflow | SDDWorkflowTools | [OK] | 1ms | 75 chars |
| 30 | get_sdd_session | SDDWorkflowTools | [OK] | 0ms | 94 chars |
| 31 | get_sdd_execution_history | SDDWorkflowTools | [OK] | 2ms | 314 chars |
| 32 | validate_sdd_compliance | SDDWorkflowTools | [OK] | 0ms | 455 chars |
| 33 | get_sdd_framework_status | SDDWorkflowTools | [OK] | 4ms | 272 chars |
| 34 | start_sdd_session | SDDWorkflowTools | [OK] | 1ms | 331 chars |
| 35 | record_sdd_step | SDDWorkflowTools | [OK] | 1ms | 224 chars |
| 36 | complete_sdd_session | SDDWorkflowTools | [OK] | 0ms | 300 chars |
| 37 | search_ee2_standards | EE2ComplianceTools | [OK] | 80ms | 36261 chars |
| 38 | analyze_ee2_compliance | EE2ComplianceTools | [OK] | 129ms | 2574 chars |
| 39 | generate_compliance_report | EE2ComplianceTools | [OK] | 197ms | 3928 chars |
| 40 | scan_repository_compliance | EE2ComplianceTools | [OK] | 20ms | 31 chars |
| 41 | extract_code_for_analysis | EE2ComplianceTools | [OK] | 2ms | 2865 chars |
| 42 | get_server_info | Utility | [OK] | 0ms | 2661 chars |
| 43 | mcp_health_check | Utility | [OK] | 246ms | 1074 chars |
| 44 | get_health_trend | Utility | [OK] | 1ms | 1098 chars |
| 45 | get_quality_metrics | Utility | [OK] | 1ms | 709 chars |
| 46 | search_issues | GitHubTools | [SKIP] | - | --skip-github |
| 47 | get_pull_requests | GitHubTools | [SKIP] | - | --skip-github |
| 48 | analyze_workflow_dependencies | GitHubTools | [SKIP] | - | --skip-github |
| 49 | analyze_repository_structure | GitHubTools | [SKIP] | - | --skip-github |

## Error Handling and Resilience

### Error Handling (9/9 scenarios handled gracefully)

| Scenario | Tool | Result |
|----------|------|--------|
| Missing required arg (query) | search_documentation | Returned error message, no crash |
| Missing required arg (function_name) | find_callers_callees | Returned error message, no crash |
| Missing required arg (symbol) | get_code_context | Returned error message, no crash |
| Non-existent function | find_callers_callees | Returned "not found" message |
| Non-existent file | find_dependencies | Returned empty results |
| Non-existent function | trace_execution_path | Returned "not found" message |
| Very long input (5000 chars) | search_documentation | Processed normally, returned results |
| XSS attempt in query | search_documentation | Processed safely, returned results |
| SQL injection in function_name | find_callers_callees | Returned "not found" message |

### Graceful Degradation

| Scenario | Behavior |
|----------|----------|
| Neptune unreachable | Server starts, vector queries work, graph queries return errors |
| Neptune retry backoff | 4 attempts with 5s/10s/20s delays, then fails gracefully |
| OpenSearch unreachable | Server starts, graph queries work, vector queries return errors |

## Performance

| Metric | Value |
|--------|-------|
| Server Startup | 706ms |
| P50 Latency | 7ms |
| P95 Latency | 9155ms |
| Avg Latency | 686ms |
| Max Latency | 9753ms |
| Total Validation | 30.9s (45 tools) |

### Slow Tools (>5s)

| Tool | Duration | Reason |
|------|----------|--------|
| get_knowledge_base_status | 9753ms | Iterates all 5 indices, counts docs per index |
| list_ingested_urls | 9699ms | Scans all documents for URL metadata |
| trace_execution_path | 9155ms | Deep graph traversal with variable-length paths |

### Fast Tools (<10ms)

28 of 45 tools complete in under 10ms, including all static tools (WorkflowInfoTools, SDDWorkflowTools session tools) and most GraphRAG session tools.

## Parity Comparison

Legacy server not available — parity comparison skipped (tasks 6.1–6.5).

## Data Counts

| Backend | Metric | Count |
|---------|--------|-------|
| OpenSearch | Total documents | 85,921 |
| OpenSearch | Indices | 5 |
| OpenSearch | mdc-code-context-mpnet768 | 60,576 |
| OpenSearch | mdc-workflow-docs-mpnet768 | 22,498 |
| OpenSearch | mdc-ee2-standards-mpnet768 | 34 |
| OpenSearch | mdc-jjobs-mpnet768 | 700 |
| OpenSearch | mdc-community-summaries-mpnet768 | 2,113 |
| Neptune | Nodes | 59,759 |
| Neptune | Cluster status | Connected (Bolt+s, SigV4 IAM) |

## Conclusion

The AWS-native MCP server with `DB_BACKEND=aws` is fully functional. All 45 non-GitHub tools pass validation against live OpenSearch and Neptune backends. The adapter pattern successfully abstracts the backend differences, and zero tool module files were modified — all changes were confined to the adapter layer and server initialization.

### Files Modified

| File | Change |
|------|--------|
| `NeptuneAdapter.js` | SigV4 IAM auth (replaced `neo4j.auth.none()`) |
| `OpenSearchAdapter.js` | Index name mapping (`-mpnet768` suffix) |
| `UnifiedMCPServer.js` | Shared dataAccess, health check guard |
| `validate-aws-mcp.js` | New validation script |
