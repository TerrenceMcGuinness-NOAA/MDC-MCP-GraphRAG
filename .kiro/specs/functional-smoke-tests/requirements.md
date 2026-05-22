# Requirements Document

## Introduction

The Python MCP/RAG server (52 tools across 9 modules) deployed on AWS Bedrock AgentCore currently has a placeholder for functional validation in its `mcp_health_check(functional=True)` tool. This feature implements per-tool-module smoke queries that prove each module can execute against live data backends (OpenSearch vector DB and Neptune graph DB). It also provides a standalone script for post-deploy and post-ingestion validation. The feature addresses the "tool registered but data layer broken" failure mode — exemplified by the recent MPAS ingestion bug where `doc_count=0` went undetected because no functional query validated the data path.

## Glossary

- **Smoke_Query**: A single lightweight query executed against a live backend to validate that a tool module's data path is functional; designed to complete in under 2 seconds.
- **Functional_Validation_Suite**: The collection of all 9 module Smoke_Queries executed as a group, reporting per-module pass/fail with latency and error details.
- **Health_Check_Tool**: The existing `mcp_health_check` tool in `src/tools/utility.py` that reports server component health status.
- **Standalone_Script**: The independently runnable script at `mcp_server_python/scripts/smoke_test_tools.py` that executes the Functional_Validation_Suite outside the MCP server process.
- **Module_Result**: A structured record containing module name, pass/fail status, latency in milliseconds, and error details (if any) for a single Smoke_Query execution.
- **Data_Path**: The full execution chain from tool function through the data access layer to the live backend (OpenSearch or Neptune) and back.
- **Graceful_Degradation**: The behaviour where a module's Smoke_Query is skipped (rather than failed) when a required external credential or service is unavailable by design (e.g., GITHUB_TOKEN not set).

## Requirements

### Requirement 1: Functional Validation Suite Core

**User Story:** As a platform operator, I want the health check to fire one representative query per tool module against live backends, so that I can detect "tool registered but data layer broken" failures before users encounter them.

#### Acceptance Criteria

1. WHEN `mcp_health_check` is called with `functional=True` and the data access layer is available, THE Health_Check_Tool SHALL execute exactly one Smoke_Query per tool module (9 modules total).
2. THE Functional_Validation_Suite SHALL produce one Module_Result per module containing: module name, status (pass/fail/skip), latency in milliseconds, and error message (empty string on pass).
3. WHEN a Smoke_Query returns at least one valid result (or a valid structure for structure-based checks), THE Functional_Validation_Suite SHALL mark that module as "pass".
4. WHEN a Smoke_Query raises an exception or returns zero results where results are expected, THE Functional_Validation_Suite SHALL mark that module as "fail" and capture the error message.
5. WHEN a module requires an external credential that is not configured (e.g., GITHUB_TOKEN), THE Functional_Validation_Suite SHALL mark that module as "skip" with a reason indicating the missing dependency.
6. WHEN `mcp_health_check` is called with `functional=True` but the data access layer is unavailable, THE Health_Check_Tool SHALL report that functional tests were skipped due to missing data layer.

### Requirement 2: Per-Module Smoke Query Definitions

**User Story:** As a platform operator, I want each module's smoke query to exercise the actual data path (not just tool registration), so that ingestion failures and backend connectivity issues are caught.

#### Acceptance Criteria

1. THE Functional_Validation_Suite SHALL execute `search_documentation("global workflow forecast")` for the semantic_search module and expect at least 1 result.
2. THE Functional_Validation_Suite SHALL execute `find_dependencies("jobs/JGFS_FORECAST")` for the code_analysis module and expect at least 1 upstream or downstream dependency. (Note: `JGFS_FORECAST` is a File-label node guaranteed to exist in Neptune; shell script names like `exglobal_forecast` are not stored as Function nodes.)
3. THE Functional_Validation_Suite SHALL execute `get_code_context("JGFS_FORECAST")` for the graph_rag module and expect a non-empty context response containing at least one graph neighbor or community summary.
4. THE Functional_Validation_Suite SHALL execute `search_ee2_standards("error handling")` for the ee2_compliance module and expect at least 1 result.
5. THE Functional_Validation_Suite SHALL execute `get_operational_guidance("running forecast on hera")` for the operational module and expect a non-empty response.
6. THE Functional_Validation_Suite SHALL execute `get_sdd_framework_status()` for the sdd_workflow module and expect a non-empty markdown response containing at least one section header (the tool returns markdown, not JSON).
7. THE Functional_Validation_Suite SHALL execute `get_workflow_structure()` for the workflow_info module and expect a non-empty structure.
8. THE Functional_Validation_Suite SHALL skip the github_tools module Smoke_Query when GITHUB_TOKEN is not set, applying Graceful_Degradation.
9. THE Functional_Validation_Suite SHALL execute `get_server_info()` for the utility module and expect the tool count to be at least 50.

### Requirement 3: Performance Constraints

**User Story:** As a platform operator, I want the functional validation to complete quickly, so that it can run as part of routine health checks without impacting server responsiveness.

#### Acceptance Criteria

1. THE Functional_Validation_Suite SHALL complete each individual Smoke_Query within 2 seconds (2000 milliseconds).
2. THE Functional_Validation_Suite SHALL complete all Smoke_Queries within 20 seconds total.
3. WHEN a Smoke_Query exceeds the 2-second per-module timeout, THE Functional_Validation_Suite SHALL mark that module as "fail" with a timeout error message including the elapsed time.
4. THE Functional_Validation_Suite SHALL execute Smoke_Queries sequentially to avoid overloading the backends during a health check.

### Requirement 4: Output Formatting

**User Story:** As a platform operator, I want health check results in both machine-readable and human-readable formats, so that I can integrate them into monitoring dashboards and also read them directly.

#### Acceptance Criteria

1. WHEN `mcp_health_check(functional=True)` completes, THE Health_Check_Tool SHALL append a "Functional Validation" section to the health check output containing a markdown table with columns: Module, Status, Latency, and Error.
2. THE Health_Check_Tool SHALL include a summary line showing the count of passed, failed, and skipped modules (e.g., "7/9 passed, 1 failed, 1 skipped").
3. THE Standalone_Script SHALL output results as a JSON object containing: timestamp, total_duration_ms, summary (passed/failed/skipped counts), and a results array of Module_Result objects.
4. THE Standalone_Script SHALL also print a human-readable markdown table to stdout after the JSON output.
5. THE Standalone_Script SHALL exit with code 0 when all non-skipped modules pass, and exit with code 1 when any module fails.

### Requirement 5: Standalone Script

**User Story:** As a DevOps engineer, I want a standalone script that validates all tools work end-to-end against live backends, so that I can run it after deployments and ingestion runs to catch regressions.

#### Acceptance Criteria

1. THE Standalone_Script SHALL be located at `mcp_server_python/scripts/smoke_test_tools.py` and be executable with `python3.12 mcp_server_python/scripts/smoke_test_tools.py`.
2. THE Standalone_Script SHALL read backend configuration from environment variables: `DB_BACKEND`, `OPENSEARCH_ENDPOINT`, `NEPTUNE_ENDPOINT`, and `AWS_REGION`.
3. THE Standalone_Script SHALL initialize the data access layer independently (without starting the full MCP server) and execute the same Functional_Validation_Suite used by the Health_Check_Tool.
4. IF a required environment variable (`OPENSEARCH_ENDPOINT` or `NEPTUNE_ENDPOINT`) is missing when `DB_BACKEND=aws`, THEN THE Standalone_Script SHALL exit with code 2 and print a descriptive error message listing the missing variables.
5. THE Standalone_Script SHALL support a `--json-only` flag that suppresses the markdown table and outputs only the JSON result object.
6. THE Standalone_Script SHALL support a `--module <name>` flag that runs the Smoke_Query for only the specified module.

### Requirement 6: Shared Smoke Query Implementation

**User Story:** As a developer, I want the smoke query logic to be defined once and shared between the health check tool and the standalone script, so that both paths validate the same behaviour without code duplication.

#### Acceptance Criteria

1. THE Functional_Validation_Suite SHALL be implemented as a reusable module (e.g., `src/tools/smoke_queries.py`) that both the Health_Check_Tool and the Standalone_Script import.
2. THE Functional_Validation_Suite SHALL accept the data access layer and the MCP server instance as parameters, decoupling it from any specific invocation context.
3. WHEN a new tool module is added to the server, THE Functional_Validation_Suite SHALL be extensible by adding a single Smoke_Query definition without modifying the runner logic.
