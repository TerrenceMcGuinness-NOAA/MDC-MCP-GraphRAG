# Requirements Document

## Introduction

This feature ports the legacy Fortran graph ingestion script (`ingest_fortran_graph.py`, 1108 lines) from the Node.js codebase to the Python tenant-aware pipeline. The port uses fparser2 to parse Fortran source files and creates a comprehensive graph of Fortran code structure — FortranModule, FortranSubroutine, FortranFunction, and FortranProgram nodes plus CALLS, USES, and CONTAINS relationships — all scoped per tenant via label-prefix isolation in Neptune.

After this feature lands:
- `trace_full_execution_chain` can traverse Shell→Fortran→Fortran deep call chains
- The Shell→Fortran EXECUTES bridge (`create_shell_fortran_bridge.py`, already coded) can run for `gw_v17` because FortranProgram nodes will exist
- Queries such as "What subroutines does the forecast model call?" become answerable for any tenant

This is Spec 3 of the gap-B graph-relationship-parity series. It does NOT depend on `graph-port-shell-ops` (Spec 1) or `graph-port-workflow-structure` (Spec 2) — Fortran nodes are independent. However, the Shell→Fortran bridge (already in Spec 1) requires FortranProgram nodes to exist before it can create EXECUTES edges.

Baseline reference (unprefixed `gw` tenant): 671 FortranProgram, 27,941 FortranSubroutine, 5,744 FortranFunction, 4,800 FortranModule nodes + 2,216,985 CALLS + 487,061 USES edges.

## Glossary

- **Fortran_AST_Ingester**: The Python ingestion script that discovers, preprocesses, and parses Fortran source files, then writes FortranModule, FortranSubroutine, FortranFunction, and FortranProgram nodes plus CALLS, USES, and CONTAINS relationships to Neptune
- **FortranParser**: A class that wraps fparser2's ParserFactory and FortranFileReader, handles C preprocessor preprocessing and source sanitization, and extracts modules, subroutines, functions, programs, call statements, and use statements from Fortran ASTs
- **Tenant**: A worktree configuration entry from `tenants.yaml` with properties `tenant_id`, `index_prefix`, `label_prefix`, `branch`, `workflow_root`, and `lifecycle`
- **Neptune_Adapter**: The existing `NeptuneAdapter` class that executes openCypher queries against Neptune with optional tenant-aware label rewriting
- **Label_Prefix**: A tenant-scoped string (e.g. `GW_V17_`) prepended to graph node labels so each tenant's nodes occupy a distinct namespace in the shared Neptune cluster
- **Worktree_Root**: The EFS-backed directory containing a tenant's checked-out workflow repository (e.g. `/efs/worktrees/gw_v17/global-workflow`)
- **IngestionReportWriter**: The existing telemetry class that accumulates counters (files processed, nodes by label, relationships by type, parse errors) and writes a JSON report at script finalization
- **MERGE_Semantics**: Neptune's openCypher MERGE statement which creates a node/relationship only if it does not already exist, providing idempotent graph writes
- **fparser2**: The Fortran 2003/2008 parser library (`fparser` package) that produces an AST from Fortran source files via `ParserFactory` and `FortranFileReader`
- **CPP_Preprocessing**: Running `cpp -traditional-cpp -nostdinc` on Fortran files that contain C preprocessor directives (`#ifdef`, `#include`, `#define`) to resolve conditional compilation before parsing
- **Source_Sanitization**: Fixing non-standard Fortran patterns (dangling continuations, merge conflict markers, non-standard write commas) that cause fparser2 to fail, prior to parsing
- **Include_Directory**: A directory containing `.h`, `.inc`, or `.fh` files referenced by `#include` directives in Fortran sources, discovered by walking the `sorc/` tree

## Requirements

### Requirement 1: Fortran Source File Discovery

**User Story:** As an ingestion operator, I want the Fortran AST ingester to discover all Fortran source files in a tenant's worktree, so that the complete Fortran code structure is captured.

#### Acceptance Criteria

1. WHEN `--mode full` is specified, THE Fortran_AST_Ingester SHALL recursively enumerate all files under the `sorc/` directory in the Worktree_Root matching Fortran extensions `.F90`, `.f90`, `.F`, `.f`, `.F95`, `.f95`, `.F03`, `.f03`, `.F08`, and `.f08`
2. THE Fortran_AST_Ingester SHALL exclude files within `.git` directories, `build` directories, and `test` directories during discovery
3. THE Fortran_AST_Ingester SHALL traverse into submodule directories (e.g. `sorc/ufs_model.fd`, `sorc/gsi_enkf.fd`, `sorc/gdas.cd`) when they are checked out
4. IF a submodule directory does not exist or is empty (shallow checkout not fetched), THEN THE Fortran_AST_Ingester SHALL log an informational message and continue discovery in remaining directories without error
5. THE Fortran_AST_Ingester SHALL report the total count of discovered Fortran files before parsing begins

### Requirement 2: C Preprocessor Handling

**User Story:** As an ingestion operator, I want Fortran files with C preprocessor directives to be preprocessed before parsing, so that UFS, MOM6, and CMEPS sources with `#ifdef` blocks are parseable by fparser2.

#### Acceptance Criteria

1. WHEN a discovered Fortran file contains C preprocessor directives (`#ifdef`, `#ifndef`, `#if`, `#include`, `#define`, `#else`, `#endif`, `#undef`, `#elif`), THE FortranParser SHALL preprocess the file using `cpp -traditional-cpp -nostdinc -P` before passing it to fparser2
2. THE Fortran_AST_Ingester SHALL discover Include_Directories by walking the `sorc/` tree for directories containing `.h`, `.inc`, or `.fh` files, and pass them as `-I` flags to the cpp invocation
3. IF the cpp command fails or times out (30-second limit), THEN THE FortranParser SHALL fall back to a directive-stripping mode that comments out all lines starting with `#` and attempts parsing of the stripped content
4. THE FortranParser SHALL use the original file path (not the temporary preprocessed path) for all node metadata properties (file_path, relative_path)
5. THE FortranParser SHALL clean up all temporary preprocessed files after parsing completes, regardless of success or failure

### Requirement 3: Source Sanitization

**User Story:** As an ingestion operator, I want non-standard Fortran patterns automatically fixed before parsing, so that files with dangling continuations or merge conflict markers do not cause parse failures.

#### Acceptance Criteria

1. WHEN a Fortran file contains a dangling continuation (`&` at end of line followed by blank or comment lines before a new statement), THE FortranParser SHALL repair the continuation by removing the `&` or providing a placeholder value
2. WHEN a Fortran file contains git merge conflict markers (`<<<<<<<`, `>>>>>>>`, `=======`), THE FortranParser SHALL comment them out before parsing
3. THE FortranParser SHALL apply sanitization before CPP_Preprocessing so that both fixes compose correctly
4. THE FortranParser SHALL clean up all temporary sanitized files after parsing completes, regardless of success or failure

### Requirement 4: Fortran AST Parsing

**User Story:** As a graph consumer, I want the parser to extract all modules, subroutines, functions, programs, call statements, and use statements from Fortran source files, so that the complete Fortran code structure is available for graph construction.

#### Acceptance Criteria

1. THE FortranParser SHALL use fparser2's `ParserFactory` with `std='f2003'` and `FortranFileReader` with `ignore_comments=True` to parse each Fortran source file
2. WHEN a Fortran file contains `MODULE <name>` statements, THE FortranParser SHALL extract the module name and source line number
3. WHEN a Fortran file contains `SUBROUTINE <name>` statements, THE FortranParser SHALL extract the subroutine name, source line number, and parent module name (if the subroutine is contained within a module)
4. WHEN a Fortran file contains `FUNCTION <name>` statements, THE FortranParser SHALL extract the function name, source line number, return type (if declared), and parent module name (if the function is contained within a module)
5. WHEN a Fortran file contains `PROGRAM <name>` statements, THE FortranParser SHALL extract the program name and infer an executable name from the file path (pattern: `sorc/<name>.fd` maps to `<name>.x`)
6. WHEN a Fortran file contains `CALL <name>` statements, THE FortranParser SHALL extract the callee subroutine name and source line number
7. WHEN a Fortran file contains `USE <module_name>` statements, THE FortranParser SHALL extract the used module name and the ONLY clause contents (if present)

### Requirement 5: Neptune Graph Writes — Nodes

**User Story:** As a graph consumer, I want all four Fortran node types written to Neptune with tenant-scoped labels, so that the Fortran code structure is queryable per tenant.

#### Acceptance Criteria

1. THE Fortran_AST_Ingester SHALL create FortranModule nodes with properties `name`, `file_path`, `line_start`, `tenant_id`, `version`, and `updated_at`, using the tenant's Label_Prefix
2. THE Fortran_AST_Ingester SHALL create FortranSubroutine nodes with properties `name`, `file_path`, `line_start`, `parent_module`, `tenant_id`, `version`, and `updated_at`, using the tenant's Label_Prefix
3. THE Fortran_AST_Ingester SHALL create FortranFunction nodes with properties `name`, `file_path`, `line_start`, `parent_module`, `return_type`, `tenant_id`, `version`, and `updated_at`, using the tenant's Label_Prefix
4. THE Fortran_AST_Ingester SHALL create FortranProgram nodes with properties `name`, `file_path`, `executable_name`, `tenant_id`, `version`, and `updated_at`, using the tenant's Label_Prefix
5. THE Fortran_AST_Ingester SHALL use MERGE_Semantics keyed on `name` for FortranModule and FortranProgram nodes, and keyed on `(name, file_path)` for FortranSubroutine and FortranFunction nodes, so that re-runs are idempotent
6. WHEN the tenant's Label_Prefix is non-empty, THE Neptune_Adapter SHALL rewrite all node labels in MERGE queries to include the prefix (e.g. `FortranModule` becomes `GW_V17_FortranModule`)

### Requirement 6: Neptune Graph Writes — Relationships

**User Story:** As a graph consumer, I want CALLS, USES, and CONTAINS relationships written to Neptune, so that Fortran call graphs and module dependency chains are traversable.

#### Acceptance Criteria

1. THE Fortran_AST_Ingester SHALL create CALLS relationships from the containing FortranSubroutine, FortranFunction, or FortranProgram node to the target FortranSubroutine node, with properties `line` and `source_file`
2. THE Fortran_AST_Ingester SHALL create USES relationships from the using entity (FortranSubroutine, FortranFunction, FortranModule, or FortranProgram) to the target FortranModule node, with an `only` property containing the ONLY clause text (or null if no ONLY clause)
3. THE Fortran_AST_Ingester SHALL create CONTAINS relationships from FortranModule nodes to their contained FortranSubroutine and FortranFunction nodes
4. THE Fortran_AST_Ingester SHALL use MERGE_Semantics for all relationship creation so that re-runs are idempotent
5. WHEN a CALLS relationship references a callee that has no existing node, THE Fortran_AST_Ingester SHALL create a placeholder FortranSubroutine node with `name` only (no file_path) to serve as the CALLS target

### Requirement 7: Graph-Only Ingestion (No Embeddings)

**User Story:** As a system architect, I want the Fortran AST ingester to write only to Neptune without generating OpenSearch embeddings, so that ingestion is fast and avoids unnecessary Bedrock costs.

#### Acceptance Criteria

1. THE Fortran_AST_Ingester SHALL NOT call the Bedrock embedding API during Fortran graph ingestion
2. THE Fortran_AST_Ingester SHALL NOT write documents to OpenSearch indices during Fortran graph ingestion
3. THE Fortran_AST_Ingester SHALL NOT use the SHAIndex for content-addressed deduplication (Neptune MERGE_Semantics provides idempotency for graph-only writes)
4. THE Fortran_AST_Ingester SHALL rely exclusively on Neptune MERGE_Semantics to prevent duplicate nodes and relationships across re-runs

### Requirement 8: Tenant Awareness

**User Story:** As an operator managing multiple workflow versions, I want the Fortran AST ingester to respect tenant isolation, so that each branch's Fortran graph is independently maintained.

#### Acceptance Criteria

1. THE Fortran_AST_Ingester SHALL accept a `--tenant` argument that resolves to a Tenant entry from the tenant catalog
2. WHEN `--tenant` is not specified, THE Fortran_AST_Ingester SHALL default to the catalog's default tenant
3. THE Fortran_AST_Ingester SHALL derive the ingestion mode from the tenant's lifecycle when `--mode` is not explicitly specified
4. THE Fortran_AST_Ingester SHALL resolve the Worktree_Root from the tenant's configuration, respecting the `MCP_WORKTREE_ROOT_OVERRIDE` environment variable
5. THE Fortran_AST_Ingester SHALL use the shared `build_ingestion_parser`, `resolve_tenant_and_mode`, and `resolve_worktree_root` helpers from `_ingest_common.py`

### Requirement 9: Telemetry and Reporting

**User Story:** As an operator, I want ingestion telemetry from the Fortran AST ingester, so that I can monitor graph build health, detect parse regressions, and compare against the baseline.

#### Acceptance Criteria

1. THE Fortran_AST_Ingester SHALL use the IngestionReportWriter to report: total Fortran files discovered, files successfully parsed, files failed, files requiring CPP_Preprocessing, files requiring Source_Sanitization, FortranModule nodes created, FortranSubroutine nodes created, FortranFunction nodes created, FortranProgram nodes created, CALLS relationships created, USES relationships created, and CONTAINS relationships created
2. WHEN ingestion completes, THE Fortran_AST_Ingester SHALL write a JSON report to `scripts/ingestion_reports/` with the tenant ID and timestamp in the filename
3. THE Fortran_AST_Ingester SHALL log a per-file progress summary every 50 files including: files processed, files failed, nodes created, relationships created, elapsed time, and estimated time remaining
4. THE Fortran_AST_Ingester SHALL report the parse success rate as a percentage in the final summary, enabling comparison against the baseline (the legacy script achieved approximately 95% success rate on the gw worktree)

### Requirement 10: Error Handling and Resilience

**User Story:** As an operator, I want ingestion to be resilient to individual file parse failures, so that one unparseable Fortran file does not abort the entire ingestion run.

#### Acceptance Criteria

1. IF a Fortran file cannot be read (encoding error, permission error, or I/O error), THEN THE Fortran_AST_Ingester SHALL log a warning with the file path and continue processing remaining files
2. IF fparser2 raises an exception or returns None for a file, THEN THE FortranParser SHALL log the error with the file path and error message, and continue processing remaining files
3. IF fparser2 triggers a SystemExit (known fparser2 behavior on certain malformed files), THEN THE FortranParser SHALL catch the SystemExit and continue processing remaining files
4. IF a Neptune query fails for an individual file's node or relationship creation, THEN THE Fortran_AST_Ingester SHALL log the error and continue processing remaining files
5. IF the Neptune connection cannot be established at startup, THEN THE Fortran_AST_Ingester SHALL exit with a non-zero return code and a descriptive error message
6. THE Fortran_AST_Ingester SHALL report the total error count and save the first 200 error details (file path and error message) to the ingestion report

### Requirement 11: Dry-Run Mode

**User Story:** As an operator, I want a dry-run mode that parses all files and reports what would be written without actually writing to Neptune, so that I can validate parser output and estimate graph size before committing changes.

#### Acceptance Criteria

1. WHEN `--dry-run` is specified, THE Fortran_AST_Ingester SHALL parse all discovered Fortran files and produce a summary report without writing any data to Neptune
2. THE dry-run summary SHALL include counts of: files discovered, files successfully parsed, files failed, nodes that would be created (broken down by FortranModule, FortranSubroutine, FortranFunction, FortranProgram), and relationships that would be created (broken down by CALLS, USES, CONTAINS)
3. WHEN `--dry-run` is specified, THE Fortran_AST_Ingester SHALL NOT establish a Neptune connection

### Requirement 12: Execution Ordering

**User Story:** As an operator, I want clear execution ordering so that the Fortran AST ingester runs at the correct point in the pipeline and downstream scripts find the nodes they need.

#### Acceptance Criteria

1. THE Fortran_AST_Ingester SHALL be executable independently of `graph-port-shell-ops` and `graph-port-workflow-structure` (Fortran nodes do not depend on ShellScript, ConfigFile, or Rocoto nodes)
2. THE Fortran_AST_Ingester SHALL run BEFORE the Shell→Fortran bridge (`create_shell_fortran_bridge.py`), because the bridge requires FortranProgram nodes to exist for EXECUTES edge creation
3. THE Fortran_AST_Ingester SHALL run AFTER code ingestion (`ingest_code.py`), because code ingestion creates the File nodes that provide the file-system context (though Fortran nodes do not directly reference File nodes, temporal ordering ensures consistent worktree state)
4. IF `--dry-run` is not specified and the Neptune connection succeeds, THEN THE Fortran_AST_Ingester SHALL proceed with graph writes regardless of whether other graph-port scripts have previously run

### Requirement 13: Shallow Submodule Handling

**User Story:** As an operator, I want the ingester to handle shallow submodule checkouts gracefully, so that incomplete source trees (common with `--depth 1` clones) do not cause ingestion failures.

#### Acceptance Criteria

1. IF a submodule directory listed in the discovery configuration exists but contains no Fortran source files, THEN THE Fortran_AST_Ingester SHALL log an informational message noting the empty submodule and continue
2. IF the `sorc/` directory does not exist in the Worktree_Root, THEN THE Fortran_AST_Ingester SHALL exit with a descriptive error message indicating that source files are not available
3. THE Fortran_AST_Ingester SHALL not fail if the total discovered file count is lower than the baseline expectation (shallow clones may have fewer files than a full checkout)
