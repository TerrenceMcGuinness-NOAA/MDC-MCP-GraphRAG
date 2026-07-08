# Requirements Document

## Introduction

This feature directs the **Kiro CLI on the Parallel Works COTS host** to perform
a full, resumable, autonomous **re-ingest of a fresh RAG collection — vector
*and* GraphRAG — across all tenants**, reflecting the renamed `supported_repos/`
checkouts and the updated unified manifest (Phase 67).

The re-ingest is driven by a **Ralph loop**: a long-running outer process that
repeatedly invokes the CLI, where each invocation (an *iteration*) does exactly
**one unit of work** — run one ingester for one tenant, validate it, adapt on
failure — then records the outcome to a durable state file and exits. The loop
re-invokes until every unit reaches a terminal state. This lets a single CLI
session complete a many-hour ingest across a disconnect-prone host without
holding all the work in one context window, and lets the agent *test and adapt*
(diagnose a failed unit, fix a parser/config/path issue, re-queue) between units.

The COTS backend is **ChromaDB (vectors) + Neo4j (graph)** on Rocky 9, selected
via `DB_BACKEND=cots`, embedded with `mpnet768` (local `all-mpnet-base-v2`),
launched via `mcp_server_python/scripts/run_mcp_stdio.sh`. Each tenant's source
tree is resolved through `${MCP_WORKFLOW_MOUNT}/<workflow_subdir>` — the
`.pw_workflow_mount` symlink farm built by `setup_pw_workflow_mount.sh`, whose
`SUBDIR_TO_CHECKOUT` table already maps to the renamed physical checkouts.

The tenant catalog (`mcp_server_python/src/config/tenants.yaml`) currently
defines five tenants: `gw` (develop), `gw_sfs` (dev/sfs), `gw_jedi_gfs`
(dev/jedi-gfs), `gw_v17` (dev/gfs.v17), `gw_gefs_v12` (release/gefs_v12). The
re-ingest covers all of them and stays catalog-driven (adding a tenant to the
YAML adds it to the work matrix on the next `init`).

**Why a fresh collection.** The rename changed on-disk source paths
(`supported_repos/global-workflow` → `…_develop`, etc.). Documents and graph
nodes keyed by the old paths would otherwise linger. Building a fresh,
version-tagged collection set **alongside** the existing one lets us validate and
compare (search-UI comparison mode) before retiring the old collection — no
in-place mutation of the serving data until cutover.

Non-goals: no AWS/Neptune/OpenSearch changes (this is the COTS host only); no
ingester algorithm changes beyond threading a collection-version parameter; no
new embedding model (COTS stays `mpnet768`).

## Glossary

- **COTS_Host**: The Parallel Works Rocky 9 host running the on-prem stack
  (ChromaDB at `localhost:8080`, Neo4j at `bolt://localhost:7687`),
  `DB_BACKEND=cots`, `MCP_EMBEDDING_PROFILE=mpnet768`.
- **Tenant_Catalog**: `mcp_server_python/src/config/tenants.yaml` — the source of
  truth for the tenant list, branches, `workflow_subdir`, `label_prefix`,
  `index_prefix`, and `lifecycle`.
- **Collection_Version**: The version suffix applied to every target collection
  (e.g. `v9-0-0`), carried in the State_File and threaded to the ingesters so the
  run builds a fresh, isolated collection set.
- **Stage**: One ingestion/validation step for one tenant, mapped 1:1 to an
  ingester script (or the validation probe). Example stages: `worktree`,
  `reset`, `documentation`, `code`, `jjobs`, `config`, `shell_graph`,
  `fortran_graph`, `expdir`, `rocoto`, `bridge`, `validate`.
- **Reingest_Unit**: A `(tenant, stage)` pair — the atomic unit of work the
  Ralph loop processes one at a time.
- **Work_Matrix**: The full set of Reingest_Units — Tenant_Catalog × ordered
  Stages, plus the non-per-tenant global stages (`ee2_standards`,
  `community_summaries`).
- **State_File**: `.reingest_state/<Collection_Version>/state.json` — the durable,
  single-source-of-truth record of every Reingest_Unit's status, attempts, last
  error, and metrics.
- **State_Manager**: `mcp_server_python/scripts/reingest_state.py` — the CLI that
  atomically initializes, queries (`next`), and mutates (`start`/`done`/`fail`/
  `skip`) the State_File and renders the progress report. Agents mutate state
  ONLY through this tool (never by hand-editing JSON).
- **Loop_Driver**: `scripts/ralph_reingest_loop.sh` — the outer Ralph loop that
  re-invokes the CLI once per Iteration until the run is complete or a stop
  condition is hit.
- **Iteration**: One invocation of the CLI by the Loop_Driver, fed the
  Iteration_Prompt, doing exactly one Reingest_Unit.
- **Iteration_Prompt**: `scripts/ralph_reingest_prompt.md` — the fixed
  per-iteration instruction that constrains the agent to one unit.
- **Validation_Probe**: The post-ingest check for a unit, run through the
  `agentcore-mcp-rag` MCP tools (vector counts + a smoke query; graph traversal
  on a ground-truth symbol).
- **Ground_Truth**: Per-tenant expected symbols/relationships from
  `mcp_server_python/scripts/branch_ground_truth.py`, used to assert GraphRAG
  completeness.
- **Ralph_Loop**: The overall pattern — Loop_Driver + Iteration_Prompt +
  State_Manager — that yields a resumable, self-continuing, test-and-adapt run.
- **Terminal_State**: A Reingest_Unit status from which the loop will not retry:
  `done`, `skipped`, or `blocked` (attempts exhausted / needs human).

## Requirements

### Requirement 1: Fresh, version-tagged collection built alongside the existing set

**User Story:** As an operator, I want the re-ingest to build a brand-new,
version-tagged collection set (vector + graph) without mutating the currently
serving collections, so I can validate and compare before cutover.

#### Acceptance Criteria

1. THE re-ingest SHALL target a Collection_Version distinct from the currently
   serving version, carried as a single field in the State_File and applied to
   every target collection name and graph-node version stamp.
2. THE ingesters SHALL accept the Collection_Version via a parameter (CLI flag or
   env var) rather than the hardcoded `v8-0-0`, threaded through `CollectionNamer`
   so all collection names derive from the one value.
3. THE re-ingest SHALL NOT delete or overwrite the existing serving collections
   until an explicit, human-gated cutover step (Requirement 12).
4. WHERE the operator sets the Collection_Version equal to the existing serving
   version, THE re-ingest SHALL treat it as an in-place rebuild and SHALL require
   the destructive-confirmation gate (Requirement 11) before any reset.

### Requirement 2: Catalog-driven all-tenant work matrix

**User Story:** As an operator, I want the work matrix generated from the tenant
catalog so every tenant is covered and new tenants are picked up automatically.

#### Acceptance Criteria

1. WHEN the State_Manager initializes the Work_Matrix, THE State_Manager SHALL
   enumerate every tenant in the Tenant_Catalog and create the ordered Stages for
   each, plus the non-per-tenant global stages.
2. THE Work_Matrix SHALL record, per Reingest_Unit, the resolved tenant fields
   (`tenant_id`, `branch`, `workflow_subdir`, `label_prefix`, `lifecycle`) so a
   unit is self-describing without re-reading the catalog.
3. IF a tenant is added to or removed from the Tenant_Catalog, THEN re-running
   `init` (idempotently) SHALL add the new tenant's units and SHALL NOT discard
   the recorded status of pre-existing units.
4. THE per-tenant ingestion mode SHALL default from the tenant's `lifecycle`
   (experimental→`diff`, staging/production→`full`) per the existing
   `_ingest_common.derive_mode_from_lifecycle`, overridable per run to `full`.

### Requirement 3: Durable, resumable state as the single source of truth

**User Story:** As an operator, I want progress persisted durably so the loop
survives CLI restarts, host disconnects, and multi-day runs.

#### Acceptance Criteria

1. THE State_File SHALL persist, per Reingest_Unit: `status`
   (`pending`/`running`/`done`/`failed`/`skipped`/`blocked`), `attempts`,
   `last_error`, `metrics` (e.g. counts), and start/end timestamps.
2. WHEN the Loop_Driver or CLI restarts, THE run SHALL resume from the State_File
   with no loss of completed-unit status and no re-execution of `done`/`skipped`
   units.
3. THE State_Manager SHALL write the State_File atomically (temp file + rename)
   so a crash mid-write cannot corrupt it.
4. THE State_Manager SHALL emit a human-readable `PROGRESS.md` mirror alongside
   the State_File on every mutation.

### Requirement 4: State-manager CLI with a single mutation path

**User Story:** As an agent iteration, I want a reliable CLI to read and update
state so I never hand-edit JSON.

#### Acceptance Criteria

1. THE State_Manager SHALL provide subcommands: `init`, `next`, `start`, `done`,
   `fail`, `skip`, `report`, and `is-complete`.
2. WHEN `next` is invoked, THE State_Manager SHALL return the single
   highest-priority actionable Reingest_Unit — one whose `depends_on` stages for
   the same tenant are all `done`/`skipped`, whose `attempts` are below the cap,
   and whose `status` is `pending` or `failed` — as machine-readable JSON, or a
   sentinel when none remain.
3. WHEN `done`/`fail`/`skip` is invoked for a unit, THE State_Manager SHALL update
   only that unit, increment `attempts` on `fail`, and persist atomically.
4. WHEN `is-complete` is invoked, THE State_Manager SHALL exit `0` iff every
   Reingest_Unit is in a Terminal_State, else non-zero.
5. THE State_Manager SHALL be pure state I/O (no ingestion, no network) and SHALL
   be unit-testable against a `tmp_path` State_File.

### Requirement 5: Ralph loop driver (long-running, bounded, resumable)

**User Story:** As an operator, I want a loop that keeps invoking the CLI until
the ingest is complete, safely and unattended.

#### Acceptance Criteria

1. THE Loop_Driver SHALL, on each pass, exit the loop when `is-complete` returns
   `0`, and otherwise invoke the CLI once with the Iteration_Prompt.
2. THE Loop_Driver SHALL enforce a configurable maximum iteration count and a
   per-iteration wall-clock timeout, and SHALL sleep a configurable interval
   between iterations.
3. WHILE a stop-file (e.g. `.reingest_state/STOP`) exists, THE Loop_Driver SHALL
   halt gracefully after the current iteration without starting a new one.
4. THE Loop_Driver SHALL run detached (survive terminal disconnect, e.g. `nohup`)
   and append per-iteration output to a timestamped log under `logs/`.
5. IF the CLI iteration exits non-zero, THEN THE Loop_Driver SHALL continue to the
   next iteration (the failed unit's state is recorded by the CLI, not the loop)
   rather than aborting the whole run.
6. THE Loop_Driver SHALL terminate when every unit is terminal, when the stop-file
   appears, or when the max-iteration cap is reached — whichever comes first.

### Requirement 6: One-unit-per-iteration prompt discipline

**User Story:** As the loop designer, I want each iteration bounded to one unit so
context stays small and progress is checkpointed after every unit.

#### Acceptance Criteria

1. THE Iteration_Prompt SHALL instruct the agent to obtain exactly one unit via
   `reingest_state.py next`, execute only that unit, update its state, then stop.
2. THE Iteration_Prompt SHALL forbid processing more than one Reingest_Unit per
   Iteration.
3. WHEN `next` returns the no-work sentinel, THE Iteration SHALL exit promptly
   without side effects.

### Requirement 7: Correct COTS-backed ingester invocation per stage

**User Story:** As an operator, I want each stage to run the right ingester
against the COTS backend with the right tenant and environment.

#### Acceptance Criteria

1. WHEN a unit executes, THE Iteration SHALL run under the COTS environment
   (`DB_BACKEND=cots`, `MCP_EMBEDDING_PROFILE=mpnet768`, Neo4j + ChromaDB
   endpoints, `MCP_WORKFLOW_MOUNT` = the `.pw_workflow_mount` farm) as established
   by `run_mcp_stdio.sh`'s env block.
2. THE stage→script mapping SHALL be: `documentation`→`ingest_documentation_v8.py`,
   `code`→`ingest_code_v8.py`, `jjobs`→`ingest_jjobs_v8.py`,
   `config`→`ingest_config_files_v8.py`, `expdir`→`ingest_expdir_configs_v8.py`,
   `rocoto`→`ingest_rocoto_xml_v8.py`, `shell_graph`→`ingest_shell_graph_v8.py`,
   `fortran_graph`→`ingest_fortran_graph_v8.py`,
   `bridge`→`create_shell_fortran_bridge.py`; `ee2_standards`→the EE2 ingester
   (global/once).
3. THE Iteration SHALL pass `--tenant <tenant_id>`, the resolved `--mode`, and the
   Collection_Version parameter to each ingester.
4. WHERE a stage's source tree is absent for a tenant (e.g. no materialized EXPDIR,
   no `sorc/` submodules), THE Iteration SHALL mark that unit `skipped` with a
   reason rather than `failed`.

### Requirement 8: Stage ordering and dependencies

**User Story:** As the pipeline designer, I want stages ordered so nodes exist
before edges and cross-links resolve.

#### Acceptance Criteria

1. THE `worktree` stage (ensure the tenant's checkout + submodules present via
   `setup_pw_workflow_mount.sh` and a `sorc/` file-count check) SHALL precede all
   other stages for that tenant.
2. THE `reset` stage SHALL run after `worktree` and before any ingest stage for
   that tenant.
3. THE `fortran_graph` and `shell_graph` stages SHALL both complete before the
   `bridge` stage (which creates Shell→Fortran `EXECUTES` edges).
4. THE `shell_graph` and `config` stages SHALL complete before `rocoto` (whose DAG
   cross-links to `ShellScript`, `EnvironmentVariable`, and `ConfigFile` nodes),
   and `expdir` SHALL precede `rocoto` (which reads EXPDIR XML).
5. THE `validate` stage SHALL be last for each tenant.
6. THE State_Manager `next` selection SHALL never return a unit whose declared
   `depends_on` stages (same tenant) are not all in a Terminal_State.

### Requirement 9: COTS-aware clean reset before rebuild

**User Story:** As an operator, I want stale, old-path documents and graph nodes
purged from the target collection so the fresh collection is clean.

#### Acceptance Criteria

1. THE `reset` stage SHALL remove, for the target Collection_Version and tenant,
   the tenant-prefixed ChromaDB collections and the tenant-prefixed Neo4j labels,
   WITHOUT touching the cross-tenant dedupe registry beyond that tenant's
   `(collection, sha)` keys and WITHOUT touching other tenants or the existing
   serving collections.
2. THE reset path SHALL operate against the COTS backend (ChromaDB + Neo4j); IF
   the existing `delete_tenant_indices.py` supports only the AWS backend, THEN a
   COTS-aware reset path SHALL be added (extending that tool or a sibling) as a
   prerequisite.
3. BEFORE any `reset` runs, THE run SHALL capture a backup/snapshot of the COTS
   ChromaDB data dir and a Neo4j dump, recorded in the run log.
4. THE `reset` stage SHALL be idempotent (re-running on an already-clean target is
   a no-op success).

### Requirement 10: Per-unit validation probe (test-and-adapt)

**User Story:** As an operator, I want every unit validated immediately after it
runs so failures are caught at the unit boundary, not at the end.

#### Acceptance Criteria

1. WHEN a vector stage (`documentation`/`code`/`jjobs`/`config`) completes, THE
   Validation_Probe SHALL confirm via `get_knowledge_base_status(tenant_id=…)`
   that the tenant's target collection doc count increased and SHALL run one smoke
   query (`search_documentation` / `find_similar_code`, `tenant_id` set) returning
   at least one relevant hit.
2. WHEN a graph stage (`shell_graph`/`fortran_graph`/`config`/`rocoto`/`bridge`)
   completes, THE Validation_Probe SHALL run a traversal
   (`find_callers_callees` / `find_dependencies` / `trace_full_execution_chain` /
   `find_env_dependencies`, `tenant_id` set) on a Ground_Truth symbol for that
   tenant and SHALL confirm a non-empty, expected result.
3. IF a Validation_Probe fails, THEN the unit SHALL be recorded `failed` (not
   `done`) with the probe output captured in `last_error`.
4. THE `validate` stage SHALL run `check_knowledge_integrity(tenant_id=…)` for the
   tenant and record its findings in the unit `metrics`.

### Requirement 11: Bounded adaptation and safety

**User Story:** As an operator, I want the loop to retry and adapt within safe
bounds, and to require explicit confirmation before destructive actions.

#### Acceptance Criteria

1. IF a unit `fail`s, THEN the loop SHALL retry it on a later Iteration with
   exponential backoff, up to a configurable per-unit attempt cap.
2. WHEN a unit reaches the attempt cap, THE State_Manager SHALL mark it `blocked`
   (a Terminal_State) so the loop makes progress on other units and surfaces the
   blocked unit for a human.
3. WHERE a failure has a systematic root cause (parser bug, path mismatch, wrong
   flag), THE Iteration MAY apply a code/config fix, record an adaptation note in
   the unit, and re-queue the unit (resetting it to `pending`).
4. THE `reset` stage and any in-place rebuild SHALL refuse to run unless
   `CONFIRM_DESTRUCTIVE=yes` is set, and SHALL support a `--dry-run` that prints
   the plan without deleting.
5. THE re-ingest SHALL rely on ChromaDB upsert-by-SHA `_id` and Neo4j `MERGE`
   (plus the per-`(collection, sha)` dedupe registry) so any unit is safely
   re-runnable.

### Requirement 12: GraphRAG completeness and cutover

**User Story:** As an operator, I want proof that the fresh collection's GraphRAG
is complete for every tenant before I retire the old collection.

#### Acceptance Criteria

1. WHEN all per-tenant stages for a tenant are terminal, THE run SHALL verify that
   the tenant's fresh GraphRAG contains non-zero shell, Fortran, config, and
   bridge relationships consistent with its Ground_Truth (allowing documented
   per-tenant absences, e.g. a tenant with few Fortran sources).
2. WHEN every tenant is terminal and verified, THE run SHALL present a cutover
   summary comparing fresh vs existing collection counts per tenant.
3. THE cutover (re-point the serving config / search UI to the fresh
   Collection_Version and retire the old) SHALL be a human-gated step, not
   automatic.
4. AFTER a validated cutover, THE old collection retirement SHALL be an explicit,
   separately-confirmed action.

### Requirement 13: Community-summaries (Gap J) as an optional, caveated stage

**User Story:** As an operator, I want the graph-derived community summaries
built if feasible on COTS, without blocking the core re-ingest.

#### Acceptance Criteria

1. THE `community_summaries` stage SHALL be optional and non-blocking: its failure
   or absence SHALL NOT prevent the run from reaching completion.
2. THE stage SHALL be marked `skipped` with the Gap-J rationale (the pipeline is
   Node-only and depends on Neo4j GDS Leiden) WHERE GDS is unavailable on the COTS
   Neo4j Community instance or the Python port does not yet exist.
3. THE spec SHALL cross-reference Gap J in `.kiro/steering/12-multi-tenant-gap-tracker.md`.

### Requirement 14: Observability, reporting, and out-of-scope constraints

**User Story:** As a maintainer, I want the run auditable and its boundaries
codified.

#### Acceptance Criteria

1. THE run SHALL produce a final report under `docs/reports/` summarizing, per
   tenant and stage: status, counts, retries, adaptations, and blocked units.
2. THE CHANGELOG.md SHALL gain a dated entry describing the re-ingest, the
   Collection_Version, and the outcome.
3. THE feature SHALL NOT modify the AWS/Neptune/OpenSearch deployment or the
   AgentCore runtime.
4. THE feature SHALL NOT change ingester parsing/graph-construction logic beyond
   threading the Collection_Version parameter and adding the COTS reset path.
5. THE feature SHALL NOT commit or push automatically; commits/pushes remain
   human-gated per `.kiro/steering/08-git-operation-policy.md`.
6. THE feature SHALL NOT alter the embedding model on COTS (stays `mpnet768`).
