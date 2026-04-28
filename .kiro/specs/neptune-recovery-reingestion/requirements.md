# Requirements Document

## Introduction

Phase 53 Track B: Re-ingest the global-workflow source tree into the recovered Neptune cluster (`mdc-mcp-graprag-neptune-1`) to capture code changes since the April 7 S3 dump. Track A (bulk load recovery from S3) is complete — Neptune has ~59,759 nodes and ~2,633,374 relationships restored. This track brings the graph current with the source tree and validates full GGSR pipeline operation.

## Context

- Track A (S3 bulk load recovery) — COMPLETE. Neptune `mdc-mcp-graprag-neptune-1` has the April 7 graph snapshot restored.
- OpenSearch — INTACT. 85,921+ docs across 17 indices (mpnet768 + titan1024), including Phase 52 Bedrock Titan re-ingestion.
- The S3 dump is from April 7. Any source tree changes merged between April 7 and today are not in the graph.
- All ingestion scripts use MERGE (idempotent upsert) — re-running is safe, no duplicates.
- CDK remediation (removalPolicy guardrails) — PARTIALLY COMPLETE. Steering rule and CDK test added; MdcDataStack needs explicit RETAIN on any future Neptune resources.

## Requirements

### Requirement 1: Assess Source Tree Drift

**User Story:** As a knowledge base maintainer, I want to know how much the source tree changed since the last graph snapshot, so that I can scope the re-ingestion effort.

#### Acceptance Criteria

1. THE drift assessment SHALL report the number of commits since April 7 in the global-workflow repo
2. THE assessment SHALL identify which subsystems changed (sorc/, ush/, jobs/, parm/, scripts/)
3. THE assessment SHALL estimate the number of new/modified files by type (Fortran, Shell, Python)

### Requirement 2: Fortran Graph Re-Ingestion

**User Story:** As a code analyst, I want Fortran subroutines, functions, and modules updated in the graph, so that cross-language tracing reflects the current codebase.

#### Acceptance Criteria

1. THE Fortran ingestion SHALL run `ingest_fortran_graph.py --backend aws` against Neptune
2. THE ingestion SHALL use MERGE semantics (no duplicate nodes)
3. THE ingestion SHALL capture new/changed subroutines, functions, and modules

### Requirement 3: Shell Script Graph Re-Ingestion

**User Story:** As a workflow analyst, I want J-Jobs, ex-scripts, and ush scripts updated in the graph, so that SOURCES, INVOKES, and DEPENDS_ON_ENV relationships are current.

#### Acceptance Criteria

1. THE Shell ingestion SHALL run `ingest_shell_graph_v8.py --backend aws` against Neptune
2. THE ingestion SHALL update SOURCES, INVOKES, and DEPENDS_ON_ENV relationships
3. THE ingestion SHALL capture new/changed J-Jobs and execution scripts

### Requirement 4: Cross-Language Bridge Re-Ingestion

**User Story:** As a cross-language analyst, I want Shell→Fortran and Shell→Python execution bridges rebuilt, so that `trace_full_execution_chain` works end-to-end.

#### Acceptance Criteria

1. THE bridge ingestion SHALL run `ingest_cross_language_bridges.py --backend aws`
2. THE ingestion SHALL rebuild EXECUTES (Shell→Fortran) and INVOKES (Shell→Python) edges

### Requirement 5: Python Graph Re-Ingestion

**User Story:** As a code analyst, I want Python module, function, and class nodes updated, so that the graph reflects the current Python codebase.

#### Acceptance Criteria

1. THE Python ingestion SHALL run `ingest_code_v8.py --backend aws --model mpnet768`
2. THE ingestion SHALL update module, function, and class nodes with MERGE semantics

### Requirement 6: Post-Ingestion Validation

**User Story:** As a platform operator, I want verified node/relationship counts and tool parity after re-ingestion, so that I can confirm the graph is current and tools work correctly.

#### Acceptance Criteria

1. THE validation SHALL compare node/relationship counts before and after re-ingestion
2. THE validation SHALL run a representative set of graph-dependent tools (`get_code_context`, `trace_full_execution_chain`, `find_callers_callees`, `search_architecture`)
3. THE validation SHALL verify results against the legacy eib-mcp-gateway for parity
4. ALL graph-dependent tools SHALL return non-empty results for known entities

### Requirement 7: MCP Server Endpoint Update

**User Story:** As a developer, I want the MCP server configured to use the recovered Neptune cluster endpoint, so that all tools route to the correct database.

#### Acceptance Criteria

1. THE Neptune endpoint SHALL be updated to `mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182`
2. THE MCP server health check SHALL report Neptune as HEALTHY after the endpoint update
