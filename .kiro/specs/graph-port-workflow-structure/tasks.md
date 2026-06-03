# Implementation Plan: graph-port-workflow-structure

## Overview

Port the three legacy workflow-structure graph-building scripts
(`ingest_config_files.py`, `ingest_expdir_configs.py`, `ingest_rocoto_xml.py`)
to the Python tenant-aware pipeline. Produces ConfigFile nodes + SETS_ENV edges
+ OpenSearch embeddings (config ingester only), Experiment + EXPDIRConfig nodes
+ RESOLVES_FROM/PART_OF/SETS_ENV edges (EXPDIR ingester), and the full Rocoto
DAG — RocotoTask, RocotoMetatask, RocotoCycledef, DataDependency nodes +
DEPENDS_ON, DEPENDS_ON_DATA, MEMBER_OF, RUNS_ON, RUNS_SCRIPT, USES_ENV edges
(Rocoto ingester). All scoped per tenant via label-prefix isolation.

TDD ordering: parser modules + tests first (pure/deterministic), then entry
scripts with unit-tested write helpers, then property tests, then gated live
runs. Pure-test tasks are `[ ]*`. All paths relative to
`/mdc-mcp-rag/eib-mcp-rag-server/`.

References:
- Requirements: `.kiro/specs/graph-port-workflow-structure/requirements.md` (R1–R13)
- Design: `.kiro/specs/graph-port-workflow-structure/design.md` (components 1–8, Properties P1–P7)
- Legacy reference: `mcp_server_node/scripts/ingest_config_files.py`, `ingest_expdir_configs.py`, `ingest_rocoto_xml.py`
- Depends on: `graph-port-shell-ops` having created `{prefix}ShellScript` + `{prefix}EnvironmentVariable` nodes (for RUNS_SCRIPT and USES_ENV cross-links)

## Tasks

- [ ] 1. Implement `_config_parser.py` (ConfigFileParser)
  - Per design §1. New file: `mcp_server_python/scripts/_config_parser.py`
  - `ConfigFileParser` class with 4 regex patterns: `ENV_PATTERN_QUOTED`, `ENV_SIMPLE`, `ENV_PATTERN`, `BARE_EXPORT`, plus `SOURCE_PATTERN`
  - `parse_config_file(file_path) -> dict` (env_vars, sources, raw_content, line_count)
  - `categorize_config(filename) -> str` using the `CATEGORY_MAP` table
  - `config_short_name(filename) -> str` — strips `config.` prefix
  - Priority-ordered matching: quoted-with-default → simple → general → bare export → source
  - Skip `#` comment lines and empty lines; dedupe by var name (first-wins)
  - **Implements: R1.2, R1.3, R1.4, R1.5, R1.6**

  - [ ]* 1.1 Unit tests for ConfigFileParser
    - Synthetic shell config content exercising each extraction: `export VAR="${VAR:-default}"` (is_default=True), `export VAR="literal"` (simple), `VAR=value` (general), bare `export VAR`, `. path/source.sh` and `source path/source.sh`
    - Edge cases: comment lines skipped, empty lines skipped, duplicate vars first-wins, nested quotes, multi-line values truncated, category classification per filename, short-name extraction
    - File: `mcp_server_python/tests/unit/test_config_parser.py` (new)
    - **Validates: R1.2–R1.6**

- [ ] 2. Implement `_rocoto_parser.py` (RocotoXMLParser)
  - Per design §2. New file: `mcp_server_python/scripts/_rocoto_parser.py`
  - `resolve_entities(xml_text) -> (clean_xml, entity_map)` — regex-extract `<!ENTITY name "value">`, strip DOCTYPE block, replace all `&name;` references
  - `parse_dependency_tree(dep_element) -> dict` — recursive: handles `<and>`, `<or>`, `<not>` operators + leaf types (`<taskdep>`, `<metataskdep>`, `<datadep>`, `<cycleexistdep>`, `<taskvalid>`, `<streq>`, `<strneq>`, `<sh>`)
  - `extract_task_deps_flat(dep_tree) -> List[str]` — flatten tree to task/metatask names
  - `extract_data_deps_flat(dep_tree) -> List[dict]` — flatten tree to data dep dicts
  - `parse_task_element(task_el) -> dict` — name, cycledefs, maxtries, is_final, command, resources, envars, dependency_tree, log_path
  - `parse_metatask_element(metatask_el) -> dict` — recursive: name, mode, variables, child tasks, nested metatasks
  - `parse_rocoto_xml(xml_path) -> dict` — full file parse: entities, workflow, cycledefs, tasks, metatasks
  - **Implements: R6.1–R6.6**

  - [ ]* 2.1 Unit tests for RocotoXMLParser
    - `resolve_entities`: synthetic XML with DOCTYPE + multiple entity defs → verify all `&entity;` resolved and DOCTYPE stripped
    - `parse_dependency_tree`: nested `<and>/<or>/<not>` with various leaf types → verify recursive dict structure, cycle_offset extraction
    - `parse_metatask_element`: nested metatasks (depth 3) with variable definitions → verify all levels extracted
    - `parse_task_element`: task with resources, envars, complex dependency tree → verify complete extraction
    - `parse_rocoto_xml`: minimal valid Rocoto XML → verify end-to-end parse
    - Edge cases: empty dependency blocks, tasks with no envars, metatasks with no nested children, entity references inside attribute values
    - File: `mcp_server_python/tests/unit/test_rocoto_parser.py` (new)
    - **Validates: R6.1–R6.6**

- [ ] 3. Implement config file discovery function
  - Per design §4. In `mcp_server_python/scripts/ingest_config_files_v8.py` (or importable helper)
  - `discover_config_files(worktree_root) -> list[dict]`: enumerate `parm/config/{gfs,gefs,gcafs,sfs}/`, exclude `.j2`, `.yaml`, `.yml`, hidden files; return `{abs_path, rel_path, filename, system}`
  - Deterministic sort order (sorted by path)
  - **Implements: R1.1**

  - [ ]* 3.1 Unit test for config file discovery
    - Mock filesystem (tmp_path) with valid configs, `.j2` templates, `.yaml`, hidden files across multiple system dirs → verify correct inclusion/exclusion and system assignment
    - File: `mcp_server_python/tests/unit/test_config_discovery.py` (new)
    - **Validates: R1.1**

- [ ] 4. Implement `ingest_config_files_v8.py` entry script
  - Per design §3/§5. New file: `mcp_server_python/scripts/ingest_config_files_v8.py`
  - The ONLY dual-writer: Neptune graph + OpenSearch embeddings
  - `build_ingestion_parser`, `resolve_tenant_and_mode`, `resolve_worktree_root` from `_ingest_common.py`
  - Add `COLLECTION_CONFIG = "config"` constant to `_ingest_common.py` (alongside `COLLECTION_CODE`, `COLLECTION_DOCUMENTATION`, `COLLECTION_JJOBS`)
  - Uses `_ingest_dedupe.py` (`SHAIndex`) for content-addressed deduplication — skip Bedrock embedding if SHA already in registry for `COLLECTION_CONFIG`
  - Neptune: `_write_config_node()`, `_write_sets_env_edges()` — f-string-interpolated cypher with `tenant=None`
  - OpenSearch: `_build_context_header()`, `_embed_text()` (Bedrock Titan), `_build_os_metadata()`, `_write_os_document()` → target index `{tenant.index_prefix}code`
  - GFS configs use short name; non-GFS use system-qualified name (`gefs/fcst`) per R2.5
  - `--dry-run`: parse + summarize without writes; no `build_ingestion_data_access()` call
  - Per-file error resilience (OSError/Neptune/OpenSearch → WARN + continue); startup connection failure → exit 1
  - `IngestionReportWriter`: total_files_processed, ConfigFile nodes, SETS_ENV edges, OS docs, Bedrock calls, estimated tokens
  - **Implements: R2.1–R2.5, R3.1–R3.5, R9.1–R9.6, R10.1, R11.1, R11.3–R11.5, R12.1**

  - [ ]* 4.1 Unit tests for config ingester write helpers
    - `_write_config_node`: verify cypher string has correct back-tick-quoted prefix label, param dict matches expected shape; empty prefix → unprefixed label
    - `_write_sets_env_edges`: verify one MERGE call per env_var; empty var names skipped
    - `_build_context_header`: verify header contains filename, system, category, top vars
    - `_build_os_metadata`: verify all required metadata fields present (file_type=config, system, category, etc.)
    - Stub `graph_db` + `raw_os_client` recording calls (cypher, params, tenant)
    - File: `mcp_server_python/tests/unit/test_config_file_writes.py` (new)
    - **Validates: R2.1–R2.5, R3.2–R3.3**

- [ ] 5. Implement `ingest_expdir_configs_v8.py` entry script
  - Per design §6. New file: `mcp_server_python/scripts/ingest_expdir_configs_v8.py`
  - Graph-only (no OpenSearch, no SHAIndex)
  - `resolve_expdir_base(tenant) -> Path` — new resolver function; EXPDIR base is adjacent to worktree root (e.g. `/efs/worktrees/gw_v17/EXPDIR/`); respects `MCP_EXPDIR_BASE_OVERRIDE` env var
  - `discover_experiments(expdir_base, filter) -> list[dict]` — enumerate subdirs, extract experiment name (strip hash suffix `_[0-9a-f]{6,12}-[0-9a-f]{3,6}`), resolution, discover `config.*` files + XML
  - `--experiment-filter` argument for substring matching
  - Reuses `ConfigFileParser` for parsing individual experiment config files
  - `_ingest_experiment()`: Experiment node + per-config: EXPDIRConfig node, PART_OF edge, RESOLVES_FROM edge (matched by `config_short_name`, graceful if ConfigFile missing), SETS_ENV edges (capped at 50 per config)
  - RESOLVES_FROM skips `config.resources.*` files
  - `--dry-run`, per-file error resilience, `IngestionReportWriter`
  - **Implements: R4.1–R4.6, R5.1–R5.6, R8.4, R9.1–R9.6, R10.2, R11.1, R11.3–R11.4, R12.2, R13.2, R13.4**

  - [ ]* 5.1 Unit tests for EXPDIR ingester write helpers
    - `resolve_expdir_base`: verify default path derivation + override env var
    - `discover_experiments`: mock filesystem with experiment dirs (hash suffixes, config files, XML) → verify correct name/resolution extraction, filter works
    - `_ingest_experiment`: stub graph_db → verify Experiment MERGE, EXPDIRConfig MERGE, PART_OF, RESOLVES_FROM, SETS_ENV call sequences
    - Edge case: missing ConfigFile for RESOLVES_FROM → no error, edge skipped; `config.resources.*` excluded from RESOLVES_FROM
    - File: `mcp_server_python/tests/unit/test_expdir_writes.py` (new)
    - **Validates: R4.1–R4.6, R5.1–R5.6, R8.4**

- [ ] 6. Implement `ingest_rocoto_xml_v8.py` entry script
  - Per design §7/§8. New file: `mcp_server_python/scripts/ingest_rocoto_xml_v8.py`
  - Graph-only, most complex — creates the full Rocoto DAG + cross-links
  - `discover_xml_experiments(expdir_base, filter)` — reuses discover pattern but for XML files
  - Two-pass write strategy: Phase 1 creates nodes (cycledefs, tasks, metatasks); Phase 2 creates edges (all target nodes already exist)
  - `_write_task()`, `_write_metatask()` (recursive), `_write_cycledef()`
  - `_walk_deps()` — recursive dependency tree walker → DEPENDS_ON edges with dep_type, cycle_offset, condition
  - `_write_data_dependencies()` → DEPENDS_ON_DATA edges with age property
  - `_write_runs_script()` — MATCH ShellScript by `ENDS WITH basename`; graceful if no match (log unmatched, continue per R8.5/R13.5)
  - `_write_uses_env()` → USES_ENV edges from task envars to EnvironmentVariable
  - `_write_runs_on()` → RUNS_ON edges from task to RocotoCycledef
  - `--dry-run`, per-experiment error resilience, `IngestionReportWriter` with comprehensive counters (R10.3)
  - **Implements: R6.1–R6.6, R7.1–R7.9, R8.1–R8.3, R8.5, R9.1–R9.6, R10.3, R11.2–R11.4, R12.3, R13.3, R13.5**

  - [ ]* 6.1 Unit tests for Rocoto ingester write helpers
    - `_write_task`: verify cypher has composite MERGE key `{name, experiment}`, all SET properties correct
    - `_write_metatask`: verify recursive handling with nested child tasks → correct MEMBER_OF edges
    - `_walk_deps`: synthetic dependency tree (nested and/or/not) → verify correct DEPENDS_ON edge count and params (dep_type, cycle_offset, condition)
    - `_write_data_dependencies`: synthetic data deps → verify DEPENDS_ON_DATA edges with path_pattern and age
    - `_write_runs_script`: stub ShellScript MATCH → verify ENDS WITH query; no match → no edge, no error
    - `_write_uses_env`: verify USES_ENV MERGE per envar name
    - `_write_runs_on`: verify RUNS_ON per cycledef group (comma-split)
    - Two-pass ordering: verify nodes created before edges
    - Stub graph_db recording all calls
    - File: `mcp_server_python/tests/unit/test_rocoto_xml_writes.py` (new)
    - **Validates: R7.1–R7.9, R8.1–R8.3, R8.5**

- [ ] 7. Checkpoint — all parsers + entry scripts importable, all unit tests green
  - `python3.12 -c "import sys; sys.path.insert(0,'mcp_server_python'); from scripts._config_parser import ConfigFileParser; from scripts._rocoto_parser import RocotoXMLParser; from scripts.ingest_config_files_v8 import main; from scripts.ingest_expdir_configs_v8 import main; from scripts.ingest_rocoto_xml_v8 import main"`
  - `pytest mcp_server_python/tests/unit/test_config_parser.py test_rocoto_parser.py test_config_discovery.py test_config_file_writes.py test_expdir_writes.py test_rocoto_xml_writes.py`
  - Ensure all pass; ask the user if questions arise

- [ ]* 8. Write property test P1 — config file completeness
  - **Property 1: Config file completeness**
  - Generate random worktree structures (tmp dirs with N valid config files + excluded types) via Hypothesis; drive `discover_config_files` + the config write logic against a stub graph_db; assert exactly N `{prefix}ConfigFile` MERGE calls
  - File: `mcp_server_python/tests/properties/test_workflow_structure_props.py` (new)
  - **Validates: R1.1, R2.1**

- [ ]* 9. Write property test P2 — SETS_ENV correctness
  - **Property 2: SETS_ENV correctness**
  - Generate random `ConfigFileParser.parse_config_file` results with K env vars (name/value/is_default tuples); drive `_write_sets_env_edges` against a stub graph_db; assert exactly K SETS_ENV MERGE calls each referencing the correct variable name and value
  - File: `mcp_server_python/tests/properties/test_workflow_structure_props.py`
  - **Validates: R2.2, R5.5**

- [ ]* 10. Write property test P3 — EXPDIR resolution chain correctness
  - **Property 3: EXPDIR resolution chain correctness**
  - Generate random EXPDIRConfig filenames → derive short names via `config_short_name()`; stub graph_db; assert RESOLVES_FROM edges target the correct short name; verify `config.resources.*` files are excluded from RESOLVES_FROM
  - File: `mcp_server_python/tests/properties/test_workflow_structure_props.py`
  - **Validates: R5.4, R8.4**

- [ ]* 11. Write property test P4 + P5 — Rocoto DAG completeness + metatask hierarchy
  - **Property 4: Rocoto DAG completeness** — generate random Rocoto parse results with T tasks and D task dependencies (flattened); drive `_ingest_rocoto_workflow` against a stub graph_db; assert T RocotoTask MERGE calls and D DEPENDS_ON edge calls
  - **Property 5: Metatask hierarchy correctness** — generate random nested metatask structures; drive `_write_metatask` against a stub; assert every child task has exactly one MEMBER_OF edge to its parent metatask
  - File: `mcp_server_python/tests/properties/test_workflow_structure_props.py`
  - **Validates: R6.3, R6.4, R7.1, R7.5, R7.7**

- [ ]* 12. Write property tests P6 + P7 — idempotence + tenant isolation
  - **Property 6: Idempotence** — run the config/EXPDIR/Rocoto write logic twice against a stub graph_db that models MERGE semantics (dict keyed by node identity); assert the node/edge set after run 2 == after run 1
  - **Property 7: Tenant isolation** — two tenants with distinct prefixes (e.g. `GW_V17_`, `GW_SFS_`) over the same synthetic content; assert all labels produced for tenant A are disjoint from tenant B
  - File: `mcp_server_python/tests/properties/test_workflow_structure_props.py`
  - **Validates: R2.3, R2.4, R5.6, R7.9, R9.6**

- [ ] 13. Phase A — Operational: run config + EXPDIR + Rocoto for gw_v17 (GATED)

  - [ ] 13.1 Pre-flight
    - EFS mounted; `{prefix}ShellScript` and `{prefix}EnvironmentVariable` nodes exist for gw_v17 (from `graph-port-shell-ops` Phase A — **REQUIRED** for RUNS_SCRIPT cross-links)
    - `{prefix}ConfigFile` nodes do NOT yet exist (this script creates them)
    - `opensearchpy`/data layer importable as the run-as user
    - Verify worktree has `parm/config/{gfs,gefs,gcafs,sfs}/` populated
    - Verify EXPDIR artifacts path contains experiment directories with `config.*` files and `.xml` workflow definitions

  - [ ] 13.2 STOP-AND-CONFIRM before Neptune + OpenSearch writes
    - Config ingester writes `GW_V17_ConfigFile` + `GW_V17_EnvironmentVariable` nodes + SETS_ENV edges to Neptune AND embeds config content to `gw_v17_code` OpenSearch index
    - EXPDIR ingester writes `GW_V17_Experiment` + `GW_V17_EXPDIRConfig` nodes + PART_OF/RESOLVES_FROM/SETS_ENV edges to Neptune
    - Rocoto ingester writes `GW_V17_RocotoTask` + `GW_V17_RocotoMetatask` + `GW_V17_RocotoCycledef` + `GW_V17_DataDependency` nodes + DEPENDS_ON/DEPENDS_ON_DATA/MEMBER_OF/RUNS_ON/RUNS_SCRIPT/USES_ENV edges to Neptune
    - Reversible via `delete_tenant_indices.py --tenant gw_v17` (per-label DETACH DELETE covers these labels)
    - Confirm with the user

  - [ ] 13.3 Run config file ingestion
    - `python3.12 mcp_server_python/scripts/ingest_config_files_v8.py --tenant gw_v17 --mode full` with AWS env vars + `MCP_WORKTREE_ROOT_OVERRIDE`
    - Expect ~200+ ConfigFile nodes, thousands of SETS_ENV edges, ~200 OpenSearch documents in `gw_v17_code`
    - **Implements: R1, R2, R3 (live)**

  - [ ] 13.4 Run EXPDIR config ingestion
    - `python3.12 mcp_server_python/scripts/ingest_expdir_configs_v8.py --tenant gw_v17 --mode full` (dry-run first to review counts)
    - Expect Experiment nodes, EXPDIRConfig nodes, PART_OF + RESOLVES_FROM + SETS_ENV edges
    - **Implements: R4, R5 (live)**

  - [ ] 13.5 Run Rocoto XML ingestion
    - `python3.12 mcp_server_python/scripts/ingest_rocoto_xml_v8.py --tenant gw_v17` (dry-run first to review DAG shape)
    - Expect RocotoTask nodes (100+), DEPENDS_ON edges forming the DAG, RUNS_SCRIPT edges linking to ShellScript nodes, USES_ENV edges
    - **Implements: R6, R7, R8 (live)**

  - [ ] 13.6 Verify
    - Neptune: `GW_V17_ConfigFile` count > 0; `GW_V17_RocotoTask` count > 0; SETS_ENV/DEPENDS_ON/RUNS_SCRIPT edge counts non-zero
    - OpenSearch: `gw_v17_code` index has config-type documents
    - `trace_full_execution_chain("JGLOBAL_FORECAST", tenant_id="gw_v17")` — verify Rocoto→Shell→Fortran traversal works end-to-end
    - Config lineage: `MATCH (c:GW_V17_ConfigFile {name:'fcst'})-[:SETS_ENV]->(e) RETURN e.name LIMIT 10` returns expected env vars
    - **Implements: R1–R8 (live verification)**

- [ ] 14. Checkpoint — code phase complete
  - All unit + property tests green; config + EXPDIR + Rocoto ingesters ran clean for gw_v17; Rocoto→Shell→Fortran trace traversal confirmed
  - Ask the user if questions arise

## Notes

- **Config ingester is the only dual-writer** — Neptune + OpenSearch + SHAIndex
  dedupe. EXPDIR and Rocoto are graph-only (Neptune MERGE is the idempotency
  mechanism for those two).
- **Execution ordering (R13)** — config runs first (independent), EXPDIR
  depends on config (RESOLVES_FROM), Rocoto depends on `graph-port-shell-ops`
  (RUNS_SCRIPT cross-links to ShellScript nodes).
- **`COLLECTION_CONFIG = "config"`** must be added to `_ingest_common.py` as a
  new constant (used by the SHAIndex for the config ingester's dedupe key).
- **`resolve_expdir_base(tenant)`** is a new resolver function — EXPDIR
  artifacts live adjacent to the worktree root (not inside it). Respects
  `MCP_EXPDIR_BASE_OVERRIDE` env var.
- **Label prefixing** uses f-string interpolation + `tenant=None` (the proven
  pattern from `graph-port-shell-ops` and `delete_tenant_indices.py`), NOT
  `_rewrite_cypher`.
- **RUNS_SCRIPT cross-link** uses `ENDS WITH basename` matching against
  pre-existing ShellScript nodes from `graph-port-shell-ops`. If no match,
  the MATCH returns empty — graceful degradation, not failure.
- **Phase A (task 13) depends on `graph-port-shell-ops` Phase A having run**
  — ShellScript + EnvironmentVariable nodes must exist for RUNS_SCRIPT and
  USES_ENV edges to find their targets.
- **Live trace verification (13.6)** depends on `tenant-id-tool-exposure` being
  deployed so the `tenant_id` parameter is reachable — verify via direct
  Neptune queries in the interim if not yet deployed.
- This is Spec 2 (Gap B) of the graph-relationship-parity series;
  `graph-port-python-community` follows.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["3.1"] },
    { "id": 3, "tasks": ["4.1"] },
    { "id": 4, "tasks": ["5.1"] },
    { "id": 5, "tasks": ["6.1"] },
    { "id": 6, "tasks": ["8", "9", "10", "11", "12"] },
    { "id": 7, "tasks": ["13.1"] },
    { "id": 8, "tasks": ["13.2"] },
    { "id": 9, "tasks": ["13.3"] },
    { "id": 10, "tasks": ["13.4"] },
    { "id": 11, "tasks": ["13.5"] },
    { "id": 12, "tasks": ["13.6"] }
  ]
}
```
