# Requirements Document

## Introduction

Systematic validation of the AWS-native MCP server (`mdc-mcp-rag-aws`) running on EC2 with `DB_BACKEND=aws`. The server connects to OpenSearch (vector search) and Neptune (graph queries) via the adapter pattern built in Phase 48. All 51 tools across 9 modules must be validated against the AWS backends, with results compared to the legacy `eib-mcp-gateway` system to confirm functional parity before cutover.

## Glossary

- **MCP_Server**: The `mdc-mcp-rag-aws` MCP server instance running via stdio from Kiro with `DB_BACKEND=aws`, executing `UnifiedMCPServer.js` in full mode
- **Legacy_Server**: The `eib-mcp-gateway` MCP server running on the original Parallel Works VM, accessible via dev tunnel HTTP transport
- **NeptuneAdapter**: The `NeptuneAdapter.js` module that implements `GraphDatabaseAdapter` for AWS Neptune using the Bolt protocol with openCypher
- **OpenSearchAdapter**: The `OpenSearchAdapter.js` module that implements `VectorDatabaseAdapter` for AWS OpenSearch Service using k-NN search with SigV4 auth
- **Backend_Selector**: The `backend-selector.js` module that routes database construction to the appropriate adapter based on `DB_BACKEND` environment variable
- **APOC_Transform**: The `apoc-transform.js` module that rewrites Neo4j APOC procedure calls into Neptune-compatible openCypher
- **Tool_Module**: One of the 9 tool registration classes (WorkflowInfoTools, SemanticSearchTools, CodeAnalysisTools, GraphRAGTools, OperationalTools, GitHubTools, SDDWorkflowTools, EE2ComplianceTools, plus utility tools)
- **Health_Check**: The `mcp_health_check` tool that reports connection status and data counts for both vector and graph backends
- **Validation_Script**: A Node.js script that invokes each MCP tool programmatically and records pass/fail results

## Requirements

### Requirement 1: Adapter Import Resolution

**User Story:** As a developer, I want all adapter module imports to resolve correctly at startup, so that the MCP server can initialize without module path errors.

#### Acceptance Criteria

1. WHEN the MCP_Server starts with `DB_BACKEND=aws`, THE Backend_Selector SHALL instantiate OpenSearchAdapter and NeptuneAdapter without throwing import errors
2. WHEN NeptuneAdapter imports `apoc-transform.js`, THE NeptuneAdapter SHALL resolve the module path relative to the adapters directory
3. WHEN NeptuneAdapter imports `withRetry` from `HealthChecker.js`, THE NeptuneAdapter SHALL resolve the path `../../health/HealthChecker.js` without errors
4. WHEN OpenSearchAdapter imports `@opensearch-project/opensearch` and `@aws-sdk/credential-provider-node`, THE OpenSearchAdapter SHALL resolve both npm packages without errors
5. IF any adapter import fails, THEN THE MCP_Server SHALL log the failing module path and the error message to stderr

### Requirement 2: Neptune Connection Establishment

**User Story:** As a developer, I want the NeptuneAdapter to connect to the Neptune cluster via Bolt protocol, so that graph queries can execute against the AWS backend.

#### Acceptance Criteria

1. WHEN NeptuneAdapter receives the endpoint `wss://mdc-mcp-rag-neptune.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182`, THE NeptuneAdapter SHALL convert it to `bolt+s://` and establish a connection
2. WHEN the initial connection attempt fails, THE NeptuneAdapter SHALL retry up to 4 times with exponential backoff delays of 5s, 10s, 20s, and 60s
3. WHEN the connection succeeds, THE NeptuneAdapter SHALL execute `MATCH (n) RETURN count(n) AS nodeCount LIMIT 1` and return a node count greater than 0
4. IF all 4 connection attempts fail, THEN THE NeptuneAdapter SHALL throw an error containing the last failure message

### Requirement 3: OpenSearch Connection Establishment

**User Story:** As a developer, I want the OpenSearchAdapter to connect to the OpenSearch domain with SigV4 authentication, so that vector queries can execute against the AWS backend.

#### Acceptance Criteria

1. WHEN OpenSearchAdapter receives the endpoint `https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com`, THE OpenSearchAdapter SHALL create a client with SigV4 signing using the EC2 instance IAM role credentials
2. WHEN the connection succeeds, THE OpenSearchAdapter SHALL load the `Xenova/all-mpnet-base-v2` embedding model as a singleton
3. WHEN the OpenSearchAdapter lists collections, THE OpenSearchAdapter SHALL return at least 5 indices matching the expected names: `mdc-code-context`, `mdc-workflow-docs`, `mdc-jjobs`, `mdc-community-summaries`, `mdc-ee2-standards`
4. IF the OpenSearch endpoint is unreachable, THEN THE OpenSearchAdapter SHALL return a health status of `unhealthy` with the error message

### Requirement 4: Health Check Validation

**User Story:** As a developer, I want the health check tool to report HEALTHY for all components on the AWS backend, so that I can confirm the system is operational.

#### Acceptance Criteria

1. WHEN the `mcp_health_check` tool is invoked on the MCP_Server, THE Health_Check SHALL return `status: healthy` for both vector and graph components
2. WHEN the Health_Check queries OpenSearch, THE Health_Check SHALL report a cluster status of `green` or `yellow` and an index count of at least 5
3. WHEN the Health_Check queries Neptune, THE Health_Check SHALL report a node count greater than 50,000
4. WHEN the `get_knowledge_base_status` tool is invoked, THE MCP_Server SHALL return collection counts matching the migration parity numbers: approximately 85,921 total vector documents and approximately 59,759 graph nodes

### Requirement 5: WorkflowInfoTools Validation

**User Story:** As a developer, I want the 3 WorkflowInfoTools to return correct results from the AWS backend, so that static workflow queries work after migration.

#### Acceptance Criteria

1. WHEN `get_workflow_structure` is invoked, THE MCP_Server SHALL return the workflow directory structure without errors
2. WHEN `get_system_configs` is invoked with `platform: hera`, THE MCP_Server SHALL return configuration data for the Hera HPC platform
3. WHEN `describe_component` is invoked with `component: jobs`, THE MCP_Server SHALL return a description of the jobs directory

### Requirement 6: SemanticSearchTools Validation

**User Story:** As a developer, I want the SemanticSearchTools to return meaningful results from OpenSearch, so that semantic search works against the migrated vector data.

#### Acceptance Criteria

1. WHEN `search_documentation` is invoked with query `data assimilation`, THE MCP_Server SHALL return at least 3 results with similarity scores above 0.3
2. WHEN `explain_with_context` is invoked with topic `forecast model`, THE MCP_Server SHALL return an explanation containing graph-enriched context
3. WHEN `find_similar_code` is invoked with `code_or_symbol: setuprad`, THE MCP_Server SHALL return at least 2 code patterns with similarity scores above 0.5
4. WHEN `search_ee2_standards` is invoked with query `error handling`, THE MCP_Server SHALL return results from the `mdc-ee2-standards` index
5. WHEN `find_related_files` is invoked with a valid file path, THE MCP_Server SHALL return related files with documentation references
6. WHEN `search_documentation` is invoked with `collection: jjobs-v8-0-0`, THE MCP_Server SHALL query the `mdc-jjobs` index via the collection-to-index mapping

### Requirement 7: CodeAnalysisTools Validation

**User Story:** As a developer, I want the 4 CodeAnalysisTools to return correct results from Neptune, so that graph-based code analysis works after migration.

#### Acceptance Criteria

1. WHEN `analyze_code_structure` is invoked with `file_path: scripts/exglobal_forecast.py`, THE MCP_Server SHALL return dependency information from Neptune
2. WHEN `find_dependencies` is invoked with a valid target module, THE MCP_Server SHALL return upstream and downstream dependency chains
3. WHEN `find_callers_callees` is invoked with `function_name: setuprad`, THE MCP_Server SHALL return caller and callee lists from the Neptune graph
4. WHEN `trace_execution_path` is invoked with a valid function name, THE MCP_Server SHALL return a call chain with relationship types

### Requirement 8: GraphRAGTools Validation

**User Story:** As a developer, I want the GraphRAGTools to return correct results from Neptune, so that advanced graph-based retrieval works after migration.

#### Acceptance Criteria

1. WHEN `get_code_context` is invoked with `symbol: setuprad`, THE MCP_Server SHALL return graph neighborhood data including community summaries
2. WHEN `search_architecture` is invoked with query `data assimilation`, THE MCP_Server SHALL return community/subsystem summaries
3. WHEN `get_change_impact` is invoked with a valid symbol, THE MCP_Server SHALL return a blast radius analysis with risk score
4. WHEN `trace_data_flow` is invoked with `from_symbol: exglobal_atmos_analysis`, THE MCP_Server SHALL return cross-language execution paths
5. WHEN `trace_full_execution_chain` is invoked with `start: JGLOBAL_FORECAST`, THE MCP_Server SHALL return a multi-language execution tree spanning Shell, Python, and Fortran nodes
6. WHEN `find_env_dependencies` is invoked with `variable_name: HOMEgfs`, THE MCP_Server SHALL return scripts that use or export the variable

### Requirement 9: OperationalTools Validation

**User Story:** As a developer, I want the 3 OperationalTools to return correct results, so that operational guidance and job details work after migration.

#### Acceptance Criteria

1. WHEN `get_operational_guidance` is invoked with `operation: forecast`, THE MCP_Server SHALL return operational guidance text
2. WHEN `explain_workflow_component` is invoked with `component: JGLOBAL_FORECAST`, THE MCP_Server SHALL return a detailed explanation with graph context
3. WHEN `get_job_details` is invoked with `job_name: JGLOBAL_FORECAST`, THE MCP_Server SHALL return job inputs, outputs, dependencies, and ChromaDB semantic context

### Requirement 10: GitHubTools Validation

**User Story:** As a developer, I want the 4 GitHubTools to function correctly, so that GitHub integration works independently of the database backend.

#### Acceptance Criteria

1. WHEN `search_issues` is invoked with a valid query, THE MCP_Server SHALL return GitHub issue results
2. WHEN `get_pull_requests` is invoked, THE MCP_Server SHALL return pull request data from the global-workflow repository
3. WHEN `list_job_scripts` is invoked, THE MCP_Server SHALL return categorized job script listings
4. WHEN `get_job_details` is invoked with `job_name: JGDAS_FIT2OBS`, THE MCP_Server SHALL return job details including config file content

### Requirement 11: SDDWorkflowTools Validation

**User Story:** As a developer, I want the 9 SDDWorkflowTools to function correctly, so that SDD session tracking works independently of the database backend.

#### Acceptance Criteria

1. WHEN `list_sdd_workflows` is invoked, THE MCP_Server SHALL return available SDD workflow definitions
2. WHEN `get_sdd_framework_status` is invoked, THE MCP_Server SHALL return framework integration status
3. WHEN `get_sdd_execution_history` is invoked, THE MCP_Server SHALL return past session execution records
4. WHEN `get_sdd_session` is invoked, THE MCP_Server SHALL return the current active session state or null
5. WHEN `get_sdd_workflow` is invoked with `workflow_name: data_ingestion_workflow`, THE MCP_Server SHALL return the workflow definition

### Requirement 12: EE2ComplianceTools Validation

**User Story:** As a developer, I want the EE2ComplianceTools to return correct results from OpenSearch, so that EE2 compliance analysis works after migration.

#### Acceptance Criteria

1. WHEN `analyze_ee2_compliance` is invoked with valid shell script content, THE MCP_Server SHALL return compliance analysis results
2. WHEN `generate_compliance_report` is invoked, THE MCP_Server SHALL return a formatted compliance report
3. WHEN `scan_repository_compliance` is invoked with file content, THE MCP_Server SHALL return compliance scan results across all categories
4. WHEN `extract_code_for_analysis` is invoked with valid code content, THE MCP_Server SHALL return structured extraction data with analysis prompts

### Requirement 13: APOC Transform Compatibility

**User Story:** As a developer, I want all Neptune queries containing APOC procedure calls to be transformed into valid openCypher, so that graph queries execute without errors on Neptune.

#### Acceptance Criteria

1. WHEN a Cypher query contains `apoc.path.expand`, THE APOC_Transform SHALL rewrite it to a variable-length path pattern
2. WHEN a Cypher query contains `apoc.merge.node`, THE APOC_Transform SHALL rewrite it to a MERGE with ON CREATE SET and ON MATCH SET clauses
3. WHEN a Cypher query contains no APOC calls, THE APOC_Transform SHALL return the query unchanged
4. IF a Cypher query contains an unsupported APOC procedure, THEN THE APOC_Transform SHALL throw an UnsupportedQueryError with the procedure name
5. FOR ALL Cypher queries used by the 51 tools, THE APOC_Transform SHALL produce valid openCypher that Neptune accepts without syntax errors

### Requirement 14: Legacy vs AWS Parity Comparison

**User Story:** As a developer, I want to compare results between the legacy and AWS servers for key queries, so that I can confirm functional equivalence before cutover.

#### Acceptance Criteria

1. WHEN `search_documentation` is invoked with query `data assimilation` on both MCP_Server and Legacy_Server, THE results SHALL contain overlapping document IDs with similarity scores within 0.1 of each other
2. WHEN `get_code_context` is invoked with `symbol: setuprad` on both servers, THE results SHALL contain the same graph neighborhood nodes
3. WHEN `trace_full_execution_chain` is invoked with `start: JGLOBAL_FORECAST` on both servers, THE results SHALL contain the same execution chain nodes and relationship types
4. WHEN `get_knowledge_base_status` is invoked on both servers, THE vector document counts SHALL match within 1% and the graph node counts SHALL reflect the known deduplication difference (59,759 AWS vs 98,813 legacy)
5. WHEN `find_env_dependencies` is invoked with `variable_name: HOMEgfs` on both servers, THE results SHALL contain the same set of dependent scripts

### Requirement 15: Validation Script and Reporting

**User Story:** As a developer, I want an automated validation script that tests all 51 tools and produces a pass/fail report, so that validation is repeatable and documented.

#### Acceptance Criteria

1. THE Validation_Script SHALL invoke each of the 51 registered tools with representative arguments and record the response status (pass, fail, error)
2. WHEN a tool invocation returns an error, THE Validation_Script SHALL capture the error message and stack trace
3. WHEN all tool invocations complete, THE Validation_Script SHALL produce a summary report listing: total tools tested, passed count, failed count, and error details for each failure
4. THE Validation_Script SHALL categorize results by Tool_Module (WorkflowInfoTools, SemanticSearchTools, CodeAnalysisTools, GraphRAGTools, OperationalTools, GitHubTools, SDDWorkflowTools, EE2ComplianceTools, utility)
5. WHEN the Validation_Script completes, THE Validation_Script SHALL write the report to `docs/aws-mcp-validation-report.md`

### Requirement 16: Documentation and Changelog Update

**User Story:** As a developer, I want the validation results documented in the SDD and changelog, so that the team has a record of the AWS migration validation.

#### Acceptance Criteria

1. WHEN all 51 tools pass validation, THE developer SHALL update `CHANGELOG.md` with a new entry documenting the validation results and any fixes applied
2. WHEN adapter fixes are required during validation, THE developer SHALL document each fix with the file path, error encountered, and resolution applied
3. THE developer SHALL update the Phase 48 progress steering file (`.kiro/steering/04-phase48-progress.md`) with the validation completion status
