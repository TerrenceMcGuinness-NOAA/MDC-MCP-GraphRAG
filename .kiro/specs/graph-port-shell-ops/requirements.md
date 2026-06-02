# Requirements Document

## Introduction

This feature ports two legacy graph-building ingestion scripts (`ingest_shell_graph_v8.py` and `create_shell_fortran_bridge.py`) from the Node.js codebase to the Python tenant-aware pipeline. The port enables the Neptune graph to match the Neo4j relationship taxonomy for shell operational semantics — SOURCES, INVOKES, EXPORTS, DEPENDS_ON_ENV, READS_CONFIG, DEFINES, and EXECUTES edges — scoped per tenant via the existing label-prefix infrastructure. After this feature lands, `trace_full_execution_chain` can follow a J-Job shell script through its sourced scripts, invoked executables, and into the Fortran programs it launches.

## Glossary

- **Shell_Graph_Ingester**: The Python ingestion script that parses shell scripts and writes ShellScript, EnvironmentVariable, ConfigFile, and ShellFunction nodes plus their relationships to Neptune
- **Fortran_Bridge_Ingester**: The Python ingestion script that creates EXECUTES edges linking ShellScript nodes to existing FortranProgram nodes in Neptune
- **ShellScriptParser**: A class that performs regex-based extraction of source statements, invocations, exports, environment variable reads, config reads, and function definitions from shell script content
- **Tenant**: A worktree configuration entry from `tenants.yaml` with properties `tenant_id`, `index_prefix`, `label_prefix`, `branch`, `workflow_root`, and `lifecycle`
- **Neptune_Adapter**: The existing `NeptuneAdapter` class that executes openCypher queries against Neptune with optional tenant-aware label rewriting
- **Label_Prefix**: A tenant-scoped string (e.g. `GW_V17_`) prepended to graph node labels so each tenant's nodes occupy a distinct namespace in the shared Neptune cluster
- **Worktree_Root**: The EFS-backed directory containing a tenant's checked-out workflow repository (e.g. `/efs/worktrees/gw_v17/global-workflow`)
- **IngestionReportWriter**: The existing telemetry class that accumulates counters and writes a JSON report at script finalization
- **SHAIndex**: The cross-tenant content-addressed deduplication registry in OpenSearch, keyed by `(collection, sha)`
- **MERGE_Semantics**: Neptune's openCypher MERGE statement which creates a node/relationship only if it does not already exist, providing idempotent graph writes

## Requirements

### Requirement 1: Shell Script Discovery

**User Story:** As an ingestion operator, I want the shell graph ingester to discover all shell scripts in a tenant's worktree, so that the full call tree is captured in Neptune.

#### Acceptance Criteria

1. WHEN `--mode full` is specified, THE Shell_Graph_Ingester SHALL enumerate all files under the Worktree_Root matching shell script patterns (`.sh`, `.bash`, `.ksh` extensions and extensionless J-Job files starting with `J`)
2. WHEN `--mode diff` is specified, THE Shell_Graph_Ingester SHALL enumerate only shell script files changed between the tenant's baseline branch and HEAD
3. THE Shell_Graph_Ingester SHALL classify each discovered script by type (`jjob`, `exscript`, `ush`, `config`, `other`) based on its directory path
4. THE Shell_Graph_Ingester SHALL classify each discovered script by operational category (`analysis`, `forecast`, `post`, `archive`, `verification`, `other`) based on filename patterns

### Requirement 2: Shell Script Parsing

**User Story:** As a graph consumer, I want the parser to extract all operational relationships from shell script content, so that Neptune captures the complete call-tree semantics.

#### Acceptance Criteria

1. WHEN a shell script contains a `. <path>` or `source <path>` statement, THE ShellScriptParser SHALL extract the sourced path as a SOURCES relationship target
2. WHEN a shell script contains a `${VAR}/script.sh` or direct `./script.sh` pattern, THE ShellScriptParser SHALL extract the invoked script as an INVOKES relationship target
3. WHEN a shell script contains an `export VAR=value` statement, THE ShellScriptParser SHALL extract the variable name and truncated value (maximum 200 characters) as an EXPORTS relationship target
4. WHEN a shell script references `$VAR` or `${VAR}` without exporting it, THE ShellScriptParser SHALL extract the variable name as a DEPENDS_ON_ENV relationship target
5. WHEN a shell script references `config.<name>` patterns, THE ShellScriptParser SHALL extract the config name as a READS_CONFIG relationship target
6. WHEN a shell script defines a function via `function name() {` or `name() {` syntax, THE ShellScriptParser SHALL extract the function name as a DEFINES relationship target
7. THE ShellScriptParser SHALL skip comment lines (lines starting with `#`) when extracting relationships
8. THE ShellScriptParser SHALL filter shell builtins and single-character variable names from DEPENDS_ON_ENV extraction

### Requirement 3: Neptune Graph Writes — Shell Graph

**User Story:** As a graph consumer, I want shell script data written to Neptune with tenant-scoped labels, so that each tenant's shell graph is isolated and queryable.

#### Acceptance Criteria

1. THE Shell_Graph_Ingester SHALL create ShellScript nodes with properties `name`, `path`, `type`, `category`, `tenant_id`, `version`, and `updated_at`, using the tenant's Label_Prefix
2. THE Shell_Graph_Ingester SHALL create EnvironmentVariable nodes with properties `name` and `default_value`, using the tenant's Label_Prefix
3. THE Shell_Graph_Ingester SHALL create ConfigFile nodes with properties `name` and `path`, using the tenant's Label_Prefix
4. THE Shell_Graph_Ingester SHALL create ShellFunction nodes with properties `name`, `script`, and `line`, using the tenant's Label_Prefix
5. THE Shell_Graph_Ingester SHALL use MERGE_Semantics for all node and relationship creation so that re-runs are idempotent
6. THE Shell_Graph_Ingester SHALL create SOURCES, INVOKES, EXPORTS, DEPENDS_ON_ENV, READS_CONFIG, and DEFINES relationships between the appropriate node types
7. WHEN the Neptune_Adapter receives a query with a tenant parameter, THE Neptune_Adapter SHALL rewrite node labels to include the tenant's Label_Prefix (e.g. `ShellScript` becomes `GW_V17_ShellScript`)

### Requirement 4: Fortran Bridge — EXECUTES Edges

**User Story:** As a graph consumer, I want EXECUTES edges from shell scripts to Fortran programs, so that `trace_full_execution_chain` can traverse the Shell→Fortran language boundary.

#### Acceptance Criteria

1. WHEN a shell script references an executable via `${EXECgfs}/name.x`, `${HOMEgfs}/exec/name.x`, `export pgm="name.x"`, or similar patterns, THE Fortran_Bridge_Ingester SHALL extract the executable name
2. THE Fortran_Bridge_Ingester SHALL match extracted executable names to existing FortranProgram nodes in Neptune using a multi-strategy matching algorithm (exact match, `_main` suffix, prefix match, progressive suffix stripping)
3. WHEN a match is found, THE Fortran_Bridge_Ingester SHALL create an EXECUTES relationship from the ShellScript node to the FortranProgram node using MERGE_Semantics
4. THE Fortran_Bridge_Ingester SHALL maintain a known-mappings table for executables whose compiled name differs from the Fortran PROGRAM statement name (e.g. `enkf` → `enkf_main`)
5. IF no FortranProgram node exists for an executable reference, THEN THE Fortran_Bridge_Ingester SHALL log the unmatched reference and continue without error

### Requirement 5: Tenant Awareness

**User Story:** As an operator managing multiple workflow versions, I want the ingestion to respect tenant isolation, so that each branch's shell graph is independently maintained.

#### Acceptance Criteria

1. THE Shell_Graph_Ingester SHALL accept a `--tenant` argument that resolves to a Tenant entry from the tenant catalog
2. WHEN `--tenant` is not specified, THE Shell_Graph_Ingester SHALL default to the catalog's default tenant
3. THE Shell_Graph_Ingester SHALL derive the ingestion mode from the tenant's lifecycle when `--mode` is not explicitly specified
4. THE Shell_Graph_Ingester SHALL resolve the Worktree_Root from the tenant's configuration, respecting the `MCP_WORKTREE_ROOT_OVERRIDE` environment variable
5. THE Fortran_Bridge_Ingester SHALL use the same `--tenant` resolution and Label_Prefix as the Shell_Graph_Ingester

### Requirement 6: Graph-Only Ingestion (No Vector Embeddings)

**User Story:** As a system architect, I want the shell graph ingester to write only to Neptune without generating OpenSearch embeddings, so that ingestion is fast and avoids unnecessary Bedrock costs.

#### Acceptance Criteria

1. THE Shell_Graph_Ingester SHALL NOT call the Bedrock embedding API during shell graph ingestion
2. THE Shell_Graph_Ingester SHALL NOT write documents to OpenSearch indices during shell graph ingestion
3. THE Shell_Graph_Ingester SHALL NOT use the SHAIndex for content-addressed deduplication (Neptune MERGE_Semantics provides idempotency for graph-only writes)
4. THE Shell_Graph_Ingester SHALL rely exclusively on Neptune MERGE_Semantics to prevent duplicate nodes and relationships across re-runs

### Requirement 7: Execution Ordering

**User Story:** As an operator, I want the bridge script to run after code ingestion, so that FortranProgram nodes exist before the bridge attempts to match them.

#### Acceptance Criteria

1. THE Fortran_Bridge_Ingester SHALL verify that FortranProgram nodes exist in Neptune for the target tenant before creating EXECUTES edges
2. IF no FortranProgram nodes are found, THEN THE Fortran_Bridge_Ingester SHALL exit with a warning indicating that code ingestion must run first
3. THE Shell_Graph_Ingester SHALL be executable independently of the Fortran_Bridge_Ingester (shell graph nodes do not depend on Fortran nodes)

### Requirement 8: Telemetry and Reporting

**User Story:** As an operator, I want ingestion telemetry, so that I can monitor graph build health and detect regressions.

#### Acceptance Criteria

1. THE Shell_Graph_Ingester SHALL use the IngestionReportWriter to report: total files processed, nodes created by label, and relationships created by type
2. THE Fortran_Bridge_Ingester SHALL use the IngestionReportWriter to report: shell scripts scanned, executable references found, matches created, and unmatched references
3. WHEN ingestion completes, THE Shell_Graph_Ingester SHALL write a JSON report to `scripts/ingestion_reports/` with the tenant ID and timestamp in the filename
4. WHEN ingestion completes, THE Fortran_Bridge_Ingester SHALL write a JSON report to `scripts/ingestion_reports/` with the tenant ID and timestamp in the filename

### Requirement 9: Error Handling and Resilience

**User Story:** As an operator, I want ingestion to be resilient to individual file failures, so that one bad script does not abort the entire ingestion run.

#### Acceptance Criteria

1. IF a shell script file cannot be read (encoding error, permission error, or I/O error), THEN THE Shell_Graph_Ingester SHALL log a warning and continue processing remaining files
2. IF a Neptune query fails for an individual script's relationships, THEN THE Shell_Graph_Ingester SHALL log the error and continue processing remaining files
3. IF the Neptune connection cannot be established at startup, THEN THE Shell_Graph_Ingester SHALL exit with a non-zero return code and a descriptive error message
4. THE Shell_Graph_Ingester SHALL report the total error count in its final summary output

### Requirement 10: Dry-Run Mode

**User Story:** As an operator, I want a dry-run mode that parses and reports without writing to Neptune, so that I can validate the parser's output before committing changes.

#### Acceptance Criteria

1. WHEN `--dry-run` is specified, THE Shell_Graph_Ingester SHALL parse all shell scripts and produce a summary report without writing any data to Neptune
2. WHEN `--dry-run` is specified, THE Fortran_Bridge_Ingester SHALL scan for executable references and report matches without creating EXECUTES relationships
3. THE dry-run summary SHALL include counts of: scripts found, SOURCES edges, INVOKES edges, EXPORTS edges, DEPENDS_ON_ENV edges, READS_CONFIG edges, DEFINES edges, and EXECUTES edges (for the bridge)
