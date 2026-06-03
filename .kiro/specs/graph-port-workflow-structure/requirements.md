# Requirements Document

## Introduction

This feature ports three legacy graph-building ingestion scripts (`ingest_config_files.py`, `ingest_expdir_configs.py`, and `ingest_rocoto_xml.py`) from the Node.js codebase to the Python tenant-aware pipeline. The port enables the Neptune graph to capture the workflow structure that Neo4j has but Neptune currently lacks — the Rocoto job-dependency DAG, the config/parm environment-variable lineage, and the experiment-directory config resolution chain — all scoped per tenant via label-prefix isolation. After this feature lands, Neptune can answer workflow task-ordering queries ("what runs before JGFS_ATMOS_ANALYSIS?"), config lineage queries ("where does $COMROOT get its value?"), and Rocoto metatask hierarchy traversals for any tenant.

This is Spec 2 of the gap-B graph-relationship-parity series. It depends on `graph-port-shell-ops` (Spec 1), which creates ShellScript and EnvironmentVariable nodes that Spec 2 cross-references via RUNS_SCRIPT and SETS_ENV edges.

## Glossary

- **Config_File_Ingester**: The Python ingestion script that discovers and parses `parm/config/*` shell bash fragments, extracts environment-variable exports, and writes ConfigFile nodes plus SETS_ENV edges to Neptune and config embeddings to OpenSearch
- **EXPDIR_Ingester**: The Python ingestion script that discovers materialized experiment-directory configs and writes Experiment, EXPDIRConfig nodes plus RESOLVES_FROM, PART_OF, and SETS_ENV edges to Neptune
- **Rocoto_Ingester**: The Python ingestion script that parses Rocoto workflow XML definitions and writes RocotoTask, RocotoMetatask, RocotoCycledef, and DataDependency nodes plus DEPENDS_ON, DEPENDS_ON_DATA, MEMBER_OF, RUNS_ON, RUNS_SCRIPT, and USES_ENV edges to Neptune
- **ConfigFileParser**: A class that performs regex-based extraction of environment-variable exports (name, default_value, is_default), source chains, and bare exports from shell config file content
- **RocotoXMLParser**: A class that resolves DOCTYPE entity definitions, parses metatask recursion, extracts task elements with resources and environment variables, and builds compound dependency trees from Rocoto XML
- **Tenant**: A worktree configuration entry from `tenants.yaml` with properties `tenant_id`, `index_prefix`, `label_prefix`, `branch`, `workflow_root`, and `lifecycle`
- **Neptune_Adapter**: The existing `NeptuneAdapter` class that executes openCypher queries against Neptune with optional tenant-aware label rewriting
- **Label_Prefix**: A tenant-scoped string (e.g. `GW_V17_`) prepended to graph node labels so each tenant's nodes occupy a distinct namespace in the shared Neptune cluster
- **Worktree_Root**: The EFS-backed directory containing a tenant's checked-out workflow repository (e.g. `/efs/worktrees/gw_v17/global-workflow`)
- **IngestionReportWriter**: The existing telemetry class that accumulates counters (files processed, nodes created by label, relationships created by type, embedding calls) and writes a JSON report at script finalization
- **MERGE_Semantics**: Neptune's openCypher MERGE statement which creates a node/relationship only if it does not already exist, providing idempotent graph writes
- **EXPDIR**: An experiment directory containing materialized (resolved) configuration files and a Rocoto XML workflow definition generated from template configs with experiment-specific values filled in
- **Metatask**: A Rocoto XML grouping construct that expands a task template across variable combinations (e.g. ensemble members), producing multiple concrete tasks via a mode (parallel or serial)
- **Dependency_Tree**: A recursive structure parsed from Rocoto `<dependency>` blocks containing logical operators (and, or, not) and leaf dependencies (taskdep, metataskdep, datadep, cycleexistdep)

## Requirements

### Requirement 1: Config File Discovery and Parsing

**User Story:** As an ingestion operator, I want the config file ingester to discover and parse all shell config fragments in a tenant's worktree, so that environment-variable lineage is extracted for graph and semantic search.

#### Acceptance Criteria

1. WHEN `--mode full` is specified, THE Config_File_Ingester SHALL enumerate all files under `parm/config/{gfs,gefs,gcafs,sfs}/` in the Worktree_Root, excluding Jinja2 templates (`.j2`), YAML files (`.yaml`, `.yml`), and hidden files
2. WHEN a config file contains `export VAR=value`, `export VAR="${VAR:-default}"`, or `VAR=value` statements, THE ConfigFileParser SHALL extract the variable name, resolved value, and an `is_default` flag indicating whether the assignment uses the `${VAR:-default}` pattern
3. WHEN a config file contains `. <path>` or `source <path>` statements, THE ConfigFileParser SHALL extract the sourced path as a source-chain entry
4. THE ConfigFileParser SHALL skip comment lines (lines starting with `#`) and empty lines during extraction
5. THE Config_File_Ingester SHALL classify each config file into a category (forecast, analysis, archive, verification, ocean, ensemble, resources, other) based on the filename stem using a deterministic category map
6. THE Config_File_Ingester SHALL classify each config file by system (`gfs`, `gefs`, `gcafs`, `sfs`) based on its parent directory path

### Requirement 2: Config File Neptune Writes

**User Story:** As a graph consumer, I want config file data written to Neptune with tenant-scoped labels, so that config-to-environment-variable lineage is queryable per tenant.

#### Acceptance Criteria

1. THE Config_File_Ingester SHALL create ConfigFile nodes with properties `name`, `file_path`, `system`, `category`, `env_var_count`, `line_count`, `filename`, `tenant_id`, `version`, and `updated_at`, using the tenant's Label_Prefix
2. THE Config_File_Ingester SHALL create SETS_ENV relationships from ConfigFile nodes to EnvironmentVariable nodes, with properties `value` and `is_default`, for each extracted environment variable
3. THE Config_File_Ingester SHALL use MERGE_Semantics for all node and relationship creation so that re-runs are idempotent
4. WHEN the tenant is not the default (`gw`), THE Config_File_Ingester SHALL prepend the Label_Prefix to all node labels (e.g. `ConfigFile` becomes `GW_V17_ConfigFile`)
5. THE Config_File_Ingester SHALL use the GFS system's short name (e.g. `fcst`) as the ConfigFile node name for GFS configs, and a system-qualified name (e.g. `gefs/fcst`) for non-GFS configs, to avoid cross-system name collisions

### Requirement 3: Config File OpenSearch Writes

**User Story:** As a semantic search user, I want config file content embedded in OpenSearch, so that I can find configs by natural-language queries about the variables they set.

#### Acceptance Criteria

1. THE Config_File_Ingester SHALL generate embeddings for each config file's content using the Bedrock Titan embedding model and write the resulting document to the tenant's OpenSearch code collection
2. THE Config_File_Ingester SHALL include structured metadata on each OpenSearch document: `file_type` (set to `config`), `system`, `category`, `file_path`, `filename`, `env_var_count`, and a JSON-encoded list of variable names
3. THE Config_File_Ingester SHALL prepend a context header to the embedded content containing the filename, system, category, path, and top environment variable names
4. THE Config_File_Ingester SHALL use the SHAIndex for content-addressed deduplication so that unchanged config files are not re-embedded on subsequent runs
5. IF a config file's content hash already exists in the SHAIndex for the target collection, THEN THE Config_File_Ingester SHALL skip the Bedrock embedding call for that file

### Requirement 4: EXPDIR Discovery and Parsing

**User Story:** As an ingestion operator, I want the EXPDIR ingester to discover all experiment directories and their materialized configs, so that resolved configuration lineage is captured.

#### Acceptance Criteria

1. THE EXPDIR_Ingester SHALL enumerate all subdirectories of the EXPDIR artifacts base path as experiment directories
2. THE EXPDIR_Ingester SHALL extract the experiment name by stripping the hash suffix (pattern `_[0-9a-f]{6,12}-[0-9a-f]{3,6}`) from the directory name
3. THE EXPDIR_Ingester SHALL extract the resolution identifier (e.g. `C48`, `C96`, `C384`) from the experiment directory name
4. THE EXPDIR_Ingester SHALL discover all `config.*` files within each experiment directory, excluding non-config files
5. THE EXPDIR_Ingester SHALL locate the Rocoto XML workflow definition file (`.xml` extension) within each experiment directory for downstream Rocoto ingestion
6. WHEN an `--experiment-filter` argument is provided, THE EXPDIR_Ingester SHALL process only experiment directories whose names contain the filter substring

### Requirement 5: EXPDIR Neptune Writes

**User Story:** As a graph consumer, I want experiment and resolved-config data written to Neptune, so that config resolution chains are traversable per tenant.

#### Acceptance Criteria

1. THE EXPDIR_Ingester SHALL create Experiment nodes with properties `name`, `pslot`, `resolution`, `config_count`, `has_xml`, `tenant_id`, `version`, and `updated_at`, using the tenant's Label_Prefix
2. THE EXPDIR_Ingester SHALL create EXPDIRConfig nodes with properties `name`, `experiment`, `category`, `env_var_count`, `file_path`, `tenant_id`, `version`, and `updated_at`, using the tenant's Label_Prefix
3. THE EXPDIR_Ingester SHALL create PART_OF relationships from EXPDIRConfig nodes to their parent Experiment node
4. THE EXPDIR_Ingester SHALL create RESOLVES_FROM relationships from EXPDIRConfig nodes to the corresponding template ConfigFile node (matched by config short name), enabling resolution-chain traversal
5. THE EXPDIR_Ingester SHALL create SETS_ENV relationships from EXPDIRConfig nodes to EnvironmentVariable nodes for each resolved environment variable, with properties `value` and `is_default`
6. THE EXPDIR_Ingester SHALL use MERGE_Semantics for all node and relationship creation so that re-runs are idempotent

### Requirement 6: Rocoto XML Discovery and Parsing

**User Story:** As a graph consumer, I want Rocoto workflow XML fully parsed including entity resolution and metatask recursion, so that the complete job-dependency DAG is available.

#### Acceptance Criteria

1. THE RocotoXMLParser SHALL resolve all DOCTYPE entity definitions (pattern `<!ENTITY name "value">`) before XML parsing, replacing `&name;` references with their resolved values throughout the document
2. THE RocotoXMLParser SHALL parse `<cycledef>` elements extracting the group name and cycle definition string
3. THE RocotoXMLParser SHALL parse `<task>` elements extracting: name, cycledefs, maxtries, is_final, command, resources (walltime, queue, nodes_spec, cores, memory), environment variables (envar name/value pairs), dependency tree, and log path
4. THE RocotoXMLParser SHALL parse `<metatask>` elements recursively, extracting: name, mode (parallel/serial), variable definitions, child tasks, and nested metatasks
5. THE RocotoXMLParser SHALL parse compound dependency trees supporting logical operators (`<and>`, `<or>`, `<not>`) and leaf dependency types (`<taskdep>`, `<metataskdep>`, `<datadep>`, `<cycleexistdep>`, `<taskvalid>`, `<streq>`, `<strneq>`, `<sh>`)
6. THE RocotoXMLParser SHALL extract cycle_offset attributes from task dependencies to represent cross-cycle dependency relationships

### Requirement 7: Rocoto Neptune Writes

**User Story:** As a graph consumer, I want the full Rocoto job-dependency DAG in Neptune with tenant-scoped labels, so that workflow ordering and task hierarchy are queryable.

#### Acceptance Criteria

1. THE Rocoto_Ingester SHALL create RocotoTask nodes with properties `name`, `experiment`, `command`, `cycledefs`, `maxtries`, `walltime`, `nodes_spec`, `cores`, `queue`, `memory`, `is_final`, `dependency_tree_json`, `log_path`, `tenant_id`, `version`, and `updated_at`, using the tenant's Label_Prefix
2. THE Rocoto_Ingester SHALL create RocotoMetatask nodes with properties `name`, `experiment`, `mode`, `variables` (JSON-encoded), `member_count`, `tenant_id`, `version`, and `updated_at`, using the tenant's Label_Prefix
3. THE Rocoto_Ingester SHALL create RocotoCycledef nodes with properties `group`, `experiment`, `definition`, `tenant_id`, `version`, and `updated_at`, using the tenant's Label_Prefix
4. THE Rocoto_Ingester SHALL create DataDependency nodes with property `path_pattern`, using the tenant's Label_Prefix
5. THE Rocoto_Ingester SHALL create DEPENDS_ON relationships from a RocotoTask to each RocotoTask it depends on, with properties `dep_type`, `cycle_offset`, and `condition` (the logical operator context)
6. THE Rocoto_Ingester SHALL create DEPENDS_ON_DATA relationships from a RocotoTask to DataDependency nodes, with property `age`
7. THE Rocoto_Ingester SHALL create MEMBER_OF relationships from each RocotoTask to its parent RocotoMetatask
8. THE Rocoto_Ingester SHALL create RUNS_ON relationships from each RocotoTask to the RocotoCycledef nodes matching the task's cycledefs attribute
9. THE Rocoto_Ingester SHALL use MERGE_Semantics for all node and relationship creation so that re-runs are idempotent

### Requirement 8: Cross-Linking to Shell-Ops Nodes

**User Story:** As a graph consumer, I want Rocoto tasks linked to their shell scripts and config files linked to their environment variables, so that cross-layer traversal (Rocoto → Shell → Fortran) works end-to-end.

#### Acceptance Criteria

1. THE Rocoto_Ingester SHALL create RUNS_SCRIPT relationships from RocotoTask nodes to existing ShellScript nodes by matching the task's command basename against ShellScript node paths (using an `ENDS WITH` match on the basename)
2. THE Rocoto_Ingester SHALL create USES_ENV relationships from RocotoTask nodes to EnvironmentVariable nodes for each `<envar>` declared in the task's XML definition
3. THE Config_File_Ingester SHALL link ConfigFile SETS_ENV edges to the same EnvironmentVariable nodes that `graph-port-shell-ops` creates, using MERGE_Semantics so that a single EnvironmentVariable node accumulates both SETS_ENV (from configs) and EXPORTS/DEPENDS_ON_ENV (from shell scripts) relationships
4. THE EXPDIR_Ingester SHALL create RESOLVES_FROM edges from EXPDIRConfig nodes to ConfigFile nodes, cross-referencing the template configs that the EXPDIR resolved configs derive from
5. IF a RUNS_SCRIPT match finds no existing ShellScript node for a task command, THEN THE Rocoto_Ingester SHALL log the unmatched command and continue without error

### Requirement 9: Tenant Awareness

**User Story:** As an operator managing multiple workflow versions, I want all three ingesters to respect tenant isolation, so that each branch's workflow structure graph is independently maintained.

#### Acceptance Criteria

1. THE Config_File_Ingester, EXPDIR_Ingester, and Rocoto_Ingester SHALL each accept a `--tenant` argument that resolves to a Tenant entry from the tenant catalog
2. WHEN `--tenant` is not specified, THE ingesters SHALL default to the catalog's default tenant
3. THE ingesters SHALL derive the ingestion mode from the tenant's lifecycle when `--mode` is not explicitly specified
4. THE ingesters SHALL resolve the Worktree_Root from the tenant's configuration, respecting the `MCP_WORKTREE_ROOT_OVERRIDE` environment variable
5. THE ingesters SHALL use the shared `build_ingestion_parser`, `resolve_tenant_and_mode`, and `resolve_worktree_root` helpers from `_ingest_common.py`
6. WHEN the tenant's Label_Prefix is non-empty, THE Neptune_Adapter SHALL rewrite all node labels in MERGE queries to include the prefix (e.g. `RocotoTask` becomes `GW_V17_RocotoTask`)

### Requirement 10: Telemetry and Reporting

**User Story:** As an operator, I want ingestion telemetry from all three scripts, so that I can monitor graph build health and detect regressions.

#### Acceptance Criteria

1. THE Config_File_Ingester SHALL use the IngestionReportWriter to report: total config files processed, ConfigFile nodes created, SETS_ENV edges created, OpenSearch documents created, Bedrock embedding calls made, and estimated token usage
2. THE EXPDIR_Ingester SHALL use the IngestionReportWriter to report: experiments discovered, EXPDIRConfig nodes created, PART_OF edges created, RESOLVES_FROM edges created, and SETS_ENV edges created
3. THE Rocoto_Ingester SHALL use the IngestionReportWriter to report: XML files parsed, RocotoTask nodes created, RocotoMetatask nodes created, RocotoCycledef nodes created, DataDependency nodes created, DEPENDS_ON edges created, DEPENDS_ON_DATA edges created, MEMBER_OF edges created, RUNS_ON edges created, RUNS_SCRIPT edges created, USES_ENV edges created, and unmatched commands
4. WHEN ingestion completes, each ingester SHALL write a JSON report to `scripts/ingestion_reports/` with the tenant ID and timestamp in the filename

### Requirement 11: Error Handling and Resilience

**User Story:** As an operator, I want ingestion to be resilient to individual file and entity failures, so that one bad config or XML parse error does not abort the entire run.

#### Acceptance Criteria

1. IF a config file cannot be read (encoding error, permission error, or I/O error), THEN THE Config_File_Ingester SHALL log a warning and continue processing remaining files
2. IF a Rocoto XML file cannot be parsed (malformed XML, missing DOCTYPE entities, or schema violations), THEN THE Rocoto_Ingester SHALL log the error with the experiment name and continue processing remaining experiments
3. IF a Neptune query fails for an individual entity's node or relationship creation, THEN the ingester SHALL log the error and continue processing remaining entities
4. IF the Neptune connection cannot be established at startup, THEN the ingester SHALL exit with a non-zero return code and a descriptive error message
5. IF the OpenSearch connection cannot be established at startup (Config_File_Ingester only), THEN THE Config_File_Ingester SHALL exit with a non-zero return code and a descriptive error message
6. THE ingesters SHALL report the total error count and a list of failed entities in their final summary output

### Requirement 12: Dry-Run Mode

**User Story:** As an operator, I want a dry-run mode that parses and reports without writing to Neptune or OpenSearch, so that I can validate parser output before committing changes.

#### Acceptance Criteria

1. WHEN `--dry-run` is specified, THE Config_File_Ingester SHALL parse all config files and produce a summary report without writing data to Neptune or OpenSearch
2. WHEN `--dry-run` is specified, THE EXPDIR_Ingester SHALL discover and parse all experiment configs and produce a summary report without writing data to Neptune
3. WHEN `--dry-run` is specified, THE Rocoto_Ingester SHALL parse all XML workflow definitions and produce a summary report without writing data to Neptune
4. THE dry-run summary SHALL include counts of: files/experiments/XMLs discovered, nodes that would be created (by label), relationships that would be created (by type), and OpenSearch documents that would be embedded (Config_File_Ingester only)

### Requirement 13: Execution Ordering

**User Story:** As an operator, I want clear execution ordering between the three ingesters, so that cross-linking edges find their target nodes already present.

#### Acceptance Criteria

1. THE Config_File_Ingester SHALL be executable independently (ConfigFile nodes and SETS_ENV edges do not depend on other workflow-structure nodes)
2. THE EXPDIR_Ingester SHALL depend on the Config_File_Ingester having run first, because RESOLVES_FROM edges reference ConfigFile nodes
3. THE Rocoto_Ingester SHALL depend on `graph-port-shell-ops` having run first, because RUNS_SCRIPT edges reference ShellScript nodes created by that spec
4. IF the EXPDIR_Ingester cannot find any ConfigFile nodes for a RESOLVES_FROM cross-link, THEN THE EXPDIR_Ingester SHALL log a warning indicating that the Config_File_Ingester should run first, and skip the RESOLVES_FROM edge without aborting
5. IF the Rocoto_Ingester cannot find any ShellScript nodes for RUNS_SCRIPT cross-links, THEN THE Rocoto_Ingester SHALL log a warning indicating that `graph-port-shell-ops` should run first, and record unmatched commands in the report
