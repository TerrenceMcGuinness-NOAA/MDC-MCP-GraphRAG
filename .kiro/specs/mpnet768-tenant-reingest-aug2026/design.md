# Design Document

## Overview

This spec **inherits and extends** the design of
`.kiro/specs/cots-reingest-ralph-loop/design.md`. That predecessor established
the Ralph-loop orchestration on the COTS host — State_Manager
(`reingest_state.py`), Loop_Driver (`ralph_reingest_loop.sh`), Iteration_Prompt
(`ralph_reingest_prompt.md`), the per-tenant stage catalog, the COTS-aware
reset path, and the validation-probe / adaptation policy. That machinery is
in place today and is **reused verbatim** for this run.

What this spec adds sits on top of that machinery in five contained deltas:

1. **Shared-once discipline** in the work matrix, threaded through the
   State_Manager and Iteration_Prompt so shared-scope stages run **once**
   tenant-blind rather than five times.
2. **Hybrid_Fan_Out** for `workflow_docs` and `code_with_context` so the
   external portion writes unprefixed and the repo-local portion writes
   per-tenant prefixed, consistent with Phase 79's authority table.
3. **Neo4j drop-and-rebuild of indexes and constraints** as an explicit
   Stage that gates the tenant graph re-parses, implemented by a new
   `neo4j_index_rebuild.py` script.
4. **Nine missing sources added to the stage catalog** — the five
   `never-ingested` sources (`fortran-code-context`, `shell-code-context`,
   `python-code-context`, `rocoto-config`, `expdir-configs`), the three
   external doc crawls (`rocoto`, `cmeps`, `nceplibs-sfcio`), and the hybrid
   `global-workflow-rst` — plus a re-crawl of the five stale PDF sources.
5. **Per-tenant Phase-79 read-path Validation_Probe** run after each
   tenant reaches `validate`, plus a global Validation_Probe run once the
   shared-once stages are `done`, plus a **manifest writeback** on every
   `done` transition so a post-run `list_all_sources(include_gaps=True)`
   reports v9-0-0 coverage.

The Requirement 12 cutover is deliberately **outside the Ralph loop** — a
separate human-invoked script that flips the manifest's `collection:` fields
and reloads the gateway.

### What this spec does not change

- The State_Manager CLI surface (`init`/`next`/`start`/`done`/`fail`/`skip`/
  `report`/`is-complete`) is unchanged; a backwards-compatible field is added.
- The Loop_Driver's non-interactive Kiro CLI invocation is unchanged.
- No ingester algorithm changes — only stage-catalog additions.
- No embedding model change — `mpnet768` throughout.
- No AWS/Neptune/OpenSearch touch.

### What this spec adds concretely

| Path | Kind | Purpose |
|---|---|---|
| `mcp_server_python/scripts/reingest_stages.yaml` | **modified** | Add nine sources, mark shared-once stages, mark hybrid fan-out sub-stages, add `neo4j_drop_indexes` / `neo4j_rebuild_indexes` stages |
| `mcp_server_python/scripts/neo4j_index_rebuild.py` | **new** | Enumerate, drop, snapshot, and re-create Neo4j indexes and constraints; JSON snapshot of pre-drop schema for rollback |
| `mcp_server_python/scripts/reingest_state.py` | **modified** | Additive schema fields: `scope: shared\|tenant\|hybrid_external\|hybrid_local`, `shared_once: bool`, `tenancy_precheck: {expected_prefix, expected_tenant}` |
| `scripts/ralph_reingest_prompt.md` | **modified** | Add Shared_Once_Rule and Hybrid_Fan_Out preamble; extend step 3 with the tenancy precheck; extend step 5 with the Phase-79 read-path probe |
| `mcp_server_python/scripts/reingest_validation.py` | **new** | Codified Validation_Probe callable from the Iteration_Prompt; wraps MCP tool calls and writes `validation/<tenant>.json` |
| `scripts/reingest_cutover.sh` | **new** | Human-invoked cutover: flips `unified_manifest.json` collections, restarts `mcp-gateway.service`, runs the post-cutover Validation_Probe suite, records the cutover report |
| `prompts/mpnet768-tenant-reingest-aug2026/` | **new** | Per-step SDD authoring prompts + `run-step.sh` following the Phase 79 / Phase 80 pattern |
| `tests/unit/test_reingest_stages_shared_once.py` | **new** | Assert shared-once stages appear exactly once in the Work_Matrix |
| `tests/unit/test_reingest_stages_hybrid_fan_out.py` | **new** | Assert the two hybrid domains split into external/local sub-stages with the right scope |
| `tests/unit/test_neo4j_index_rebuild.py` | **new** | Assert drop/create round-trip preserves the schema |
| `tests/unit/test_reingest_validation_tenancy.py` | **new** | Assert the tenancy precheck refuses the wrong prefix |

## Architecture (delta view)

The base architecture is the predecessor's diagram (Loop_Driver → Kiro CLI →
State_Manager + ingesters). The delta:

```
                       ┌──────────────────────────────────────────────────┐
    Work_Matrix.init   │  reingest_stages.yaml                            │
                       │    per-tenant stages (unchanged)                 │
                       │    + shared-once stages (NEW, once total)        │
                       │    + hybrid domains split external/local (NEW)   │
                       │    + neo4j_drop_indexes (NEW, once, first)       │
                       │    + neo4j_rebuild_indexes (NEW, once, after     │
                       │      all per-tenant graph stages done)           │
                       │    + manifest_writeback (implicit on `done`)     │
                       └──────────────────────────────────────────────────┘
                                          │
                                          ▼
                       ┌──────────────────────────────────────────────────┐
                       │  State_File (additive fields)                    │
                       │    unit.scope: shared|tenant|hybrid_external|    │
                       │                hybrid_local                      │
                       │    unit.shared_once: bool                        │
                       │    unit.tenancy_precheck: {…}                    │
                       │    unit.validation_path: .../<tenant>.json       │
                       └──────────────────────────────────────────────────┘
                                          │
                                          ▼
                       ┌──────────────────────────────────────────────────┐
                       │  Iteration_Prompt (extended)                     │
                       │    step 0 preamble: Shared_Once_Rule +           │
                       │                     Hybrid_Fan_Out               │
                       │    step 3 tenancy precheck (fail-fast)           │
                       │    step 5 Validation_Probe →                     │
                       │           reingest_validation.py                 │
                       │    (steps 1/2/4/6/7 unchanged)                   │
                       └──────────────────────────────────────────────────┘
```

## Delta 1 — Shared-once discipline

**Problem.** The predecessor's stage catalog had two "global" stages
(`ee2_standards`, `community_summaries`) marked as non-per-tenant. That model
worked but was ad-hoc: it did not distinguish scope authority from execution
order, and the State_File carried no scope field, so a post-hoc audit could
not tell whether a completed stage had honoured the shared-once contract.

**Design.** The State_File adds a `scope` field to every unit, populated at
`init` time from the stage catalog. The Work_Matrix generator refuses to emit
more than one unit whose `stage` is shared-once and whose `scope` is
`shared`. The State_Manager's `next` picker enforces `MCP_DEFAULT_TENANT=""`
(unset) as a precondition for shared-scope units and refuses to hand out the
unit otherwise; the Iteration_Prompt's step 3 tenancy precheck verifies the
same thing at runtime as a belt-and-braces guard.

**Enumerated shared-once stages** (this spec):

| Stage | source_type in manifest | Physical collection (unprefixed) |
|---|---|---|
| `ee2_standards` | `standards` | `ee2-standards-mpnet768-v9-0-0` |
| `community_summaries` | `community_summary` | `community-summaries-mpnet768-v9-0-0` |
| `ci_test_cases` | (embedded in the manifest under `ci_test_cases`) | `ci-test-cases-mpnet768-v9-0-0` |
| `external_docs` | `url_crawl` (nine sources: existing 3 + new `rocoto`, `cmeps`, `nceplibs-sfcio` + five PDFs) | `workflow-docs-external-mpnet768-v9-0-0` |
| `pdf_sources` | `url_crawl` (five stale PDFs re-crawled) | rolls into `external_docs` collection; distinct stage for the `Last-Modified` writeback |

Note: `pdf_sources` and `external_docs` write to the **same** physical
collection but are separate stages so gap detection can distinguish "URL
crawls current" from "PDFs current".

## Delta 2 — Hybrid_Fan_Out for `workflow_docs` and `code_with_context`

**Problem (Phase 79 Finding 3, still current).** The `global-workflow-rst`
source is declared `scope: shared` yet its content is repo-local `.rst` that
varies per branch. Under the predecessor's model this either writes to the
shared unprefixed collection (silently overwritten between tenants) or to a
tenant-prefixed collection with no shared counterpart (correct data, but the
gap detection cannot tell the shared portion from the tenant portion). The
`code_with_context` domain does not currently have external URL sources but
the design has to leave room for one (e.g. Sphinx-published API docs for a
supported library).

**Design.** The stage catalog splits each hybrid domain into two sub-stages
with distinct scope:

| Domain | Sub-stage | Scope | Sources |
|---|---|---|---|
| `workflow_docs` | `workflow_docs_external` | shared_once | `rocoto`, `cmeps`, `nceplibs-sfcio`, `esmf-ref-pdf`, `esmc-ref-pdf`, `nuopc-ref-pdf`, `esmpy-pdf`, `nuopc-layer-reference` |
| `workflow_docs` | `workflow_docs_local` | per-tenant | `global-workflow-rst` (materializes from `${MCP_WORKFLOW_MOUNT}/<workflow_subdir>/docs/**/*.rst`) |
| `code_with_context` | `code_with_context_local` | per-tenant | `fortran-code-context`, `shell-code-context`, `python-code-context`, `rocoto-config`, `expdir-configs` |
| `code_with_context` | `code_with_context_external` | (none today, reserved) | future URL-crawled API references |

The **physical collection naming** follows Phase 79's authority table:

| Sub-stage | Physical collection |
|---|---|
| `workflow_docs_external` | `workflow-docs-external-mpnet768-v9-0-0` (unprefixed) |
| `workflow_docs_local` | `<index_prefix>workflow-docs-local-mpnet768-v9-0-0` |
| `code_with_context_local` | `<index_prefix>code-with-context-mpnet768-v9-0-0` |

The logical collection name the read path resolves to is `workflow-docs` (a
`shared_scope: hybrid` in the manifest) and `code-with-context`; Phase 79's
Read_Router already fans a hybrid read across the external + local
collections, so a query under any tenant reaches both.

## Delta 3 — Neo4j drop-and-rebuild of indexes

**Problem.** The graph today carries index definitions built for the
APOC-based name predicate (`apoc.text.join(apoc.convert.toList(n.name), ' ')`)
that is no longer executed. The new predicate is
`toLower(toString(n.name)) CONTAINS toLower($baseName)` — a substring scan on
the stringified value. If the old indexes covered `n.name` as an exact-match
range index only, the new predicate cannot use them and the planner will fall
back to `NodeByLabelScan`. Dropping and recreating the index set — matched to
the current predicates — is the only option that leaves the planner
consistent with the code.

**Design.** A new script,
`mcp_server_python/scripts/neo4j_index_rebuild.py`, enumerates the
Index_Rebuild_Set, snapshots it to
`.reingest_state/v9-0-0/neo4j_pre_drop.json`, drops the set, and (after all
per-tenant graph stages complete) recreates the set.

Index_Rebuild_Set contents (initial):

| Index | Type | Node label | Property | Purpose |
|---|---|---|---|---|
| `file_path_uniq` | UNIQUENESS constraint | `File` | `path` | idempotent `MERGE` on file path |
| `function_qname_uniq` | UNIQUENESS constraint | `Function` | `qname` | idempotent `MERGE` on qualified name |
| `function_name_text` | TEXT index | `Function` | `name` | supports the new `CONTAINS toString(n.name)` predicate |
| `fortran_sub_name_text` | TEXT index | `FortranSubroutine` | `name` | same predicate, Fortran labels |
| `fortran_fn_name_text` | TEXT index | `FortranFunction` | `name` | same predicate |
| `python_fn_name_text` | TEXT index | `PythonFunction` | `name` | same predicate |
| `shell_script_path_uniq` | UNIQUENESS constraint | `ShellScript` | `path` | idempotent MERGE |

Per-tenant labels (`GW_V17_Function`, `GW_V17_File`, …) use the **same**
property schema; the script parametrises label by tenant `label_prefix` at
create-time so the whole set is rebuilt for the currently-populated label
families.

CLI surface (matches Req 8.1 confirmation-token contract):

```
neo4j_index_rebuild.py list
neo4j_index_rebuild.py drop    --i-mean-it Target_Version=v9-0-0
                                --snapshot .reingest_state/v9-0-0/neo4j_pre_drop.json
neo4j_index_rebuild.py create  --target-version v9-0-0
neo4j_index_rebuild.py restore --snapshot <path>   # rollback
```

The drop and create phases become explicit Stages in the Work_Matrix:

| Stage | Kind | depends_on | Notes |
|---|---|---|---|
| `neo4j_drop_indexes` | prep | — (runs before any per-tenant graph stage) | shared-once, first-in-order after `worktree` |
| `neo4j_rebuild_indexes` | prep | all per-tenant `fortran_graph`, `python_graph`, `shell_graph`, `bridge`, `rocoto`, `expdir` for every tenant | shared-once, gates the tenant `validate` stages |

## Delta 4 — Missing sources added to the stage catalog

The nine sources enumerated in Req 3.1 are added to
`reingest_stages.yaml` under the sub-stages defined in Delta 2. Each entry
carries the `depends_on`, `source_precondition`, `ingester_script`, and
`validation_probe` fields the predecessor's catalog already uses. Missing
ingester scripts are declared with a `blocked: needs_ingester` sentinel per
Req 3.2 — the State_Manager will surface them as `blocked` rather than
failing the run, and the pre-flight `list` subcommand will report them.

Concrete catalog delta (yaml sketch):

```yaml
stages:

  # ─── shared-once, first-in-order ──────────────────────────────────
  - name: neo4j_drop_indexes
    kind: prep
    scope: shared
    shared_once: true
    script: neo4j_index_rebuild.py
    args: ["drop", "--i-mean-it", "Target_Version=v9-0-0",
           "--snapshot", ".reingest_state/v9-0-0/neo4j_pre_drop.json"]
    depends_on: [worktree]

  # ─── shared-once vector stages ────────────────────────────────────
  - name: ee2_standards
    kind: vector
    scope: shared
    shared_once: true
    script: ingest_ee2_standards_v9.py
    depends_on: [neo4j_drop_indexes]

  - name: community_summaries
    kind: vector
    scope: shared
    shared_once: true
    script: ingest_community_summaries_v9.py
    depends_on: [neo4j_drop_indexes]

  - name: ci_test_cases
    kind: vector
    scope: shared
    shared_once: true
    script: ingest_ci_test_cases_v9.py
    depends_on: [neo4j_drop_indexes]

  - name: workflow_docs_external
    kind: vector
    scope: shared
    shared_once: true
    script: ingest_documentation_v9.py
    args: ["--sources", "rocoto,cmeps,nceplibs-sfcio,esmf-ref-pdf,esmc-ref-pdf,nuopc-ref-pdf,esmpy-pdf,nuopc-layer-reference"]
    depends_on: [neo4j_drop_indexes]

  - name: pdf_sources
    kind: vector
    scope: shared
    shared_once: true
    script: ingest_documentation_v9.py
    args: ["--sources", "esmf-ref-pdf,esmc-ref-pdf,nuopc-ref-pdf,esmpy-pdf,nuopc-layer-reference",
           "--writeback-last-modified"]
    depends_on: [workflow_docs_external]

  # ─── per-tenant vector stages ─────────────────────────────────────
  - name: workflow_docs_local
    kind: vector
    scope: tenant
    script: ingest_documentation_v9.py
    args: ["--sources", "global-workflow-rst"]
    depends_on: [neo4j_drop_indexes]

  - name: code_with_context_local
    kind: vector
    scope: tenant
    script: ingest_code_v9.py
    args: ["--sources", "fortran-code-context,shell-code-context,python-code-context,rocoto-config,expdir-configs"]
    depends_on: [neo4j_drop_indexes]

  # ─── per-tenant graph stages (existing, unchanged) ────────────────
  # fortran_graph / python_graph / shell_graph / bridge / rocoto / expdir

  # ─── shared-once graph rebuild ────────────────────────────────────
  - name: neo4j_rebuild_indexes
    kind: prep
    scope: shared
    shared_once: true
    script: neo4j_index_rebuild.py
    args: ["create", "--target-version", "v9-0-0"]
    depends_on: [fortran_graph, python_graph, shell_graph, bridge, rocoto, expdir]
    depends_on_all_tenants: true   # all tenants' graph stages must be done

  # ─── per-tenant validate (last per tenant) ────────────────────────
  - name: validate
    kind: validate
    scope: tenant
    script: reingest_validation.py
    depends_on: [neo4j_rebuild_indexes]
```

The `depends_on_all_tenants: true` field is the one true schema addition on
the catalog side (backwards-compatible: defaults to `false`). The
State_Manager's dependency resolver already computes per-tenant terminality;
this flag flips the semantics to "every tenant's listed stages are terminal".

## Delta 5 — Per-tenant Phase-79 Validation_Probe and manifest writeback

**Codified probe.**
`mcp_server_python/scripts/reingest_validation.py` — a thin CLI that runs the
four MCP tool calls from Req 5.1 against the local gateway
(`http://localhost:18888/mcp` with the bearer token from
`~/.config/eib-mcp/secrets.env`) and writes the request/response payload to
`.reingest_state/v9-0-0/validation/<tenant>.json`. The script uses the same
JSON-RPC transport the gateway already speaks; it does not import the MCP
Python SDK to keep the dependency footprint small.

Ground-truth phrases per tenant (initial, iterable):

| Tenant | search_documentation phrase | get_code_context symbol |
|---|---|---|
| `gw` | "wave initialization step" | `GFS_wave_init` |
| `gw_sfs` | "SFS ensemble driver" | `sfs_driver` |
| `gw_jedi_gfs` | "JEDI atmosphere increment" | `jedi_atmos_incr` |
| `gw_v17` | "v17 gfs_forecast" | `gfs_forecast_v17` |
| `gw_gefs_v12` | "GEFS ensemble forecast" | `gefs_forecast_v12` |

`search_ee2_standards("err_chk err_exit", tenant_id=<tenant>)` and
`search_architecture("workflow driver", tenant_id=<tenant>)` are constant
across tenants (they exercise the shared-once collections from a non-default
tenant).

**Manifest writeback.** On every `done` transition the State_Manager
appends an entry to
`mcp_server_python/src/config/unified_manifest.json` at the source level,
recording:

```jsonc
"ingest_status": {
  "collection_version": "v9-0-0",
  "actual_docs": 60598,
  "ingested_at": "2026-08-29T04:12:07Z",
  "sha": "…",
  "backend": "cots",
  "embedding_profile": "mpnet768"
}
```

`list_all_sources(include_gaps=True)` already reads `ingest_status.actual_docs`
if present, falling back to a live count; the writeback ensures a
post-run gap report reflects the run's actual outcome without a fresh
count query per source.

## Delta 6 — Cutover script (deferred, out-of-loop)

`scripts/reingest_cutover.sh` is a **separate** invocation the operator runs
after the Ralph loop reports `is-complete`. It:

1. Reads `.reingest_state/v9-0-0/state.json` and refuses to run if any unit
   is not in a Terminal_State.
2. Reads `.reingest_state/v9-0-0/validation/*.json` and refuses to run if any
   tenant's Validation_Probe recorded a failure or a missing file.
3. Backs up `unified_manifest.json` to
   `docs/reports/2026-XX-XX-mpnet768-tenant-reingest-cutover.manifest.bak`.
4. Rewrites every `collection:` field in `unified_manifest.json` to the
   `v9-0-0` name (following the naming table from Delta 2).
5. Restarts `mcp-gateway.service` and waits for `mcp_health_check` via the
   HTTP endpoint to return 4/4 healthy.
6. Re-runs the Req 5.1 probe suite against the post-cutover manifest and
   aborts the cutover (restoring the manifest backup) if any tenant's probes
   regress.
7. Writes the cutover report to
   `docs/reports/2026-XX-XX-mpnet768-tenant-reingest-cutover.md` and pins
   the 7-day v8 retention window.

Rollback: `git checkout <sha>~1 -- mcp_server_python/src/config/unified_manifest.json`
followed by `sudo systemctl restart mcp-gateway.service`. The v8 collections
are still populated because Req 1.2 protected them through the run.

## Design decisions and trade-offs

**One shared-once flag on the Work_Matrix vs. two catalogs.** The predecessor
had two catalogs (`per_tenant_stages`, `global_stages`) which forced the
State_Manager to know which was which. A single stage catalog with a
`shared_once: bool` per stage is a smaller, more auditable schema — the
Work_Matrix builder decides "emit once vs. emit-per-tenant" from the flag,
and the State_File's `scope` field records the outcome for downstream
audits. Trade-off: a stage that changes from per-tenant to shared-once (or
back) is a catalog edit that the State_Manager's `init` idempotency must
detect and refuse; recorded as `catalog_scope_drift`.

**Sub-stage explosion for hybrid domains.** The alternative — one stage
that internally fans out — would keep the catalog smaller but hide the
scope authority inside ingester code. Splitting the stage matches Phase
79's authority table 1:1 and keeps gap detection able to report
"external portion current, local portion behind" without decoding
ingester internals.

**Neo4j index drop as an explicit Stage, not an implicit reset.** The
predecessor's `reset` stage handled ChromaDB collections and Neo4j labels
per-tenant. Neo4j indexes are global (not per-tenant), so folding them
into `reset` would misplace them in the dependency graph. A distinct
`neo4j_drop_indexes` stage keeps the dependency semantics clean.

**Same physical collection for `pdf_sources` and `external_docs`.**
Splitting them at the physical-collection level would create a small
non-searchable collection just for PDFs. Since the read path treats them
identically, keeping them in one collection and distinguishing them at
the stage level lets gap detection report on PDF freshness without
splitting the search index.

**Validation_Probe as a Python CLI, not an inline MCP call.** The
Iteration_Prompt is meant to bound the agent's actions; asking the
agent to reach into the MCP tool namespace directly for the probe
would blur that boundary. A CLI wrapper the agent invokes as a shell
command keeps the probe deterministic and the prompt small.

## Testing strategy

**Unit tests** (fast, deterministic, no live backend):

| Test | Asserts |
|---|---|
| `test_reingest_stages_shared_once.py` | Every stage with `shared_once: true` produces exactly one Work_Matrix unit regardless of tenant count |
| `test_reingest_stages_hybrid_fan_out.py` | `workflow_docs` splits into external (shared) + local (per-tenant × N); `code_with_context` splits identically |
| `test_reingest_stages_dependency_closure.py` | `neo4j_rebuild_indexes` transitively depends on every tenant's graph stages |
| `test_neo4j_index_rebuild.py` | `drop` + `snapshot` round-trips with `restore`; `list` matches the Index_Rebuild_Set |
| `test_reingest_validation_tenancy.py` | Tenancy precheck refuses `MCP_DEFAULT_TENANT=gw_v17` for a shared-once unit; refuses `MCP_DEFAULT_TENANT=""` for a tenant unit |
| `test_reingest_state_scope_drift.py` | Changing a stage from `shared_once: false` to `true` between `init`s is detected and reported |

**Integration tests** (live COTS backend, marked `@pytest.mark.integration`):

| Test | Asserts |
|---|---|
| `test_reingest_stages_end_to_end_dry_run.py` | Full Work_Matrix `init` + `next` walk with every ingester in `--dry-run` mode reaches `is-complete` without a real write |
| `test_reingest_shared_once_write_path.py` | An `ee2_standards` write lands in the unprefixed physical collection regardless of `MCP_DEFAULT_TENANT` |
| `test_reingest_hybrid_read_path.py` | Post-run, a `search_documentation(tenant_id="gw_v17")` reaches both the external (shared) and local (v17-prefixed) portions |

**Verification against the Requirements** (recorded in
`docs/reports/2026-XX-XX-mpnet768-tenant-reingest-verification.md` after the
first live run):

Every Requirement 1-12 has a numbered row citing the test, log line, or
tool call that proves the criterion. Missing rows mean the run is not
verified.

## Rollout / rollback

**Rollout.**
1. Land the spec (`requirements.md` + `design.md` + `tasks.md`) — no
   runtime change.
2. Land the code deltas (State_Manager scope field, stage catalog,
   `neo4j_index_rebuild.py`, `reingest_validation.py`, extended
   Iteration_Prompt, cutover script) behind unit tests — still no
   runtime change.
3. Dry-run the Ralph loop with every ingester in `--dry-run` mode; confirm
   the Work_Matrix contains the expected units in the expected order.
4. Kick off the live loop under `nohup` with `CONFIRM_DESTRUCTIVE=yes`
   and `MAX_ITERATIONS` set to the estimated wall-clock horizon.
5. Monitor `PROGRESS.md` and `loop.log`; adapt any blocked units through
   the iteration's adapt-and-requeue path.
6. Once `is-complete`, review `.reingest_state/v9-0-0/validation/*.json`
   and manually inspect the coverage numbers via `list_all_sources`.
7. Human-invoke the cutover script when satisfied.

**Rollback (pre-cutover).**
- Delete `.reingest_state/v9-0-0/` and the v9-0-0 physical collections
  (`neo4j_index_rebuild.py restore --snapshot .reingest_state/v9-0-0/neo4j_pre_drop.json`
  + `python -c "import chromadb; …"` to drop the v9-0-0 collections).
- Serving path is untouched by Req 1.2.

**Rollback (post-cutover).**
- `git checkout <cutover-commit>~1 -- mcp_server_python/src/config/unified_manifest.json`
- `sudo systemctl restart mcp-gateway.service`
- Verify with `mcp_health_check`.

**Rollback (image-level).**
```
docker tag eib-mcp-rag-python:pre-shared-scope eib-mcp-rag-python:latest
sudo systemctl restart mcp-gateway.service
```
Pinned by Req 8.4 — the `pre-shared-scope` tag is preserved through the run.
