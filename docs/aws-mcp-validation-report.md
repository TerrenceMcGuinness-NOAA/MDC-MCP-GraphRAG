# AWS MCP Server Validation Report

**Generated**: 2026-04-10T21:45:10.240Z
**DB_BACKEND**: aws
**OpenSearch**: https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com
**Neptune**: wss://mdc-mcp-rag-neptune.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182
**Node.js**: v18.20.8
**Timeout**: 60000ms per tool

## Summary

| Metric | Count |
|--------|-------|
| Total Tools | 49 |
| Passed | 45 |
| Failed | 0 |
| Errors | 0 |
| Skipped | 4 |
| **Pass Rate** | **91.8%** |

## Results by Module

| Module | Total | Passed | Failed | Errors | Skipped |
|--------|-------|--------|--------|--------|--------|
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
|---|------|--------|--------|----------|--------|
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

## Parity Comparison

Legacy server not available — parity comparison skipped.

## Performance

| Metric | Value |
|--------|-------|
| Avg Latency | 686ms |
| P50 Latency | 7ms |
| P95 Latency | 9155ms |
| Max Latency | 9753ms |
| Total Duration | 30891ms |

