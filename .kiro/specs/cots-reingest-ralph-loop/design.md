# Design Document

## Overview

This feature adds a **Ralph-loop-driven full re-ingest** of a fresh RAG
collection — vector *and* GraphRAG — across all tenants on the Parallel Works
**COTS host** (ChromaDB + Neo4j, `DB_BACKEND=cots`, `mpnet768`). It reflects the
Phase 67 `supported_repos/` rename and the updated unified manifest.

The design is deliberately thin on new *pipeline* code: the existing v8 ingesters
already do the heavy lifting and are tenant-aware (they resolve
`tenant.workflow_root = ${MCP_WORKFLOW_MOUNT}/<workflow_subdir>` and prefix graph
labels / collection names by tenant). What this feature adds is an **orchestration
layer** around them:

1. A **State_Manager** (`reingest_state.py`) — the durable, atomic single source
   of truth for a `(tenant, stage)` work matrix.
2. A **Loop_Driver** (`ralph_reingest_loop.sh`) — the outer Ralph loop that
   re-invokes the CLI once per iteration until done/stopped/capped.
3. An **Iteration_Prompt** (`ralph_reingest_prompt.md`) — the fixed instruction
   that bounds each CLI iteration to exactly one unit: run → validate → adapt →
   record → stop.
4. Two small pipeline touch-points: **thread a Collection_Version parameter**
   through the ingesters (replacing the hardcoded `v8-0-0`), and add a
   **COTS-aware reset** path (ChromaDB collections + Neo4j labels for a tenant).

The result: a single CLI session can complete a multi-hour, disconnect-prone
ingest by checkpointing after every unit, and can *test and adapt* — validate a
unit via the MCP tools, and on failure diagnose/fix/re-queue — without human
babysitting, while all destructive actions stay behind explicit gates.

### What changes

- **New** `mcp_server_python/scripts/reingest_state.py` — State_Manager CLI.
- **New** `scripts/ralph_reingest_loop.sh` — Loop_Driver.
- **New** `scripts/ralph_reingest_prompt.md` — Iteration_Prompt.
- **New** `mcp_server_python/scripts/reingest_stages.yaml` — the stage catalog
  (stage → script, kind, `depends_on`, source-precondition, validation probe).
- **Modified** the v8 ingesters' collection-version source: thread a
  `--collection-version` (env `REINGEST_COLLECTION_VERSION`) through
  `CollectionNamer` in place of the hardcoded `v8-0-0`.
- **Modified/extended** `delete_tenant_indices.py` (or a sibling
  `reset_tenant_cots.py`) — add a COTS (ChromaDB + Neo4j) reset path.
- **New** unit tests for `reingest_state.py` (matrix build, `next` dependency +
  attempt-cap logic, atomic write, `is-complete`).
- **No change** to AWS/Neptune/OpenSearch, the AgentCore runtime, embedding
  models, or ingester parsing/graph-construction logic.

## Architecture

```
                        ┌────────────────────────────────────────────────┐
  nohup, detached  ───► │  Loop_Driver  scripts/ralph_reingest_loop.sh   │
                        │  while not is-complete and not STOP and i<MAX: │
                        │    kiro-cli --prompt ralph_reingest_prompt.md  │──┐
                        └────────────────────────────────────────────────┘  │ one
                                        ▲                                   │ iteration
                    is-complete? (0/1)  │                                   ▼
                        ┌───────────────┴──────────────────┐   ┌──────────────────────────┐
                        │  State_Manager reingest_state    │◄──│  Kiro CLI (this agent)   │
                        │ .reingest_state/<ver>/state.json │   │ 1. next → one (tenant,stage)
                        │  init·next·start·done·fail·skip  │   │  2. run stage ingester   │
                        │  report·is-complete (atomic)     │──►│     (COTS env, --tenant) │
                        └──────────────────────────────────┘   │  3. Validation_Probe     │
                                        │                      │     (MCP tools)          │
                                        │ PROGRESS.md          │  4. done | fail | skip   │
                                        ▼                      │  5. adapt+re-queue?      │
                              human-readable mirror            │  6. STOP (one unit only) │
                                                               └───────────┬──────────────┘
                                                                           │ runs
                          ┌────────────────────────────────────────────────┴───────────┐
                          │  v8 ingesters (COTS: ChromaDB + Neo4j, mpnet768)           │
                          │  documentation·code·jjobs·config·expdir·rocoto·shell_graph │
                          │  ·fortran_graph·bridge   +  reset (COTS-aware)             │
                          │  target Collection_Version (fresh, alongside serving set)  │
                          └────────────────────────────────────────────────────────────┘
```

## The work matrix

`init` builds the Work_Matrix from `tenants.yaml` × the ordered per-tenant stages,
plus two global (non-per-tenant) stages. Current tenants: `gw`, `gw_sfs`,
`gw_jedi_gfs`, `gw_v17`, `gw_gefs_v12`.

### Per-tenant stages (ordered; `depends_on` within the same tenant)

| Stage | Script | Kind | depends_on | Source precondition |
|---|---|---|---|---|
| `worktree` | `setup_pw_workflow_mount.sh` + `sorc/` count check | prep | — | — |
| `reset` | COTS reset path (Req 9) | destructive | `worktree` | — |
| `documentation` | `ingest_documentation_v8.py` | vector | `reset` | `docs/` present |
| `code` | `ingest_code_v8.py` | vector (+File nodes) | `reset` | tree present |
| `jjobs` | `ingest_jjobs_v8.py` | vector | `reset` | `jobs/` or `dev/jobs/` |
| `config` | `ingest_config_files_v8.py` | dual (Neo4j+Chroma) | `reset` | `parm/config/` |
| `shell_graph` | `ingest_shell_graph_v8.py` | graph | `reset` | shell scripts present |
| `fortran_graph` | `ingest_fortran_graph_v8.py` | graph | `reset` | `sorc/` submodules (>1000 files) |
| `expdir` | `ingest_expdir_configs_v8.py` | graph | `reset` | materialized `supported_repos/EXPDIR*` |
| `rocoto` | `ingest_rocoto_xml_v8.py` | graph | `config`,`shell_graph`,`expdir` | EXPDIR `*.xml` |
| `bridge` | `create_shell_fortran_bridge.py` | graph | `shell_graph`,`fortran_graph` | — |
| `validate` | Validation_Probe + `check_knowledge_integrity` | validate | all above | — |

### Global stages (once, not per-tenant)

| Stage | Script | Notes |
|---|---|---|
| `ee2_standards` | EE2 ingester | Branch-agnostic NCO/EE2 standards from `supported_repos/nws-hpc-standards`; ingested once into the shared collection (not tenant-prefixed). |
| `community_summaries` | (Gap J) | Optional, non-blocking. Neo4j GDS Leiden + Node pipeline; `skipped` with rationale where GDS/port unavailable. See `.kiro/steering/12-multi-tenant-gap-tracker.md` Gap J. |

Stages whose source precondition is unmet for a tenant are `skipped` (not
`failed`) — e.g. a tenant with no materialized EXPDIR skips `expdir`/`rocoto`; a
tenant whose `sorc/` submodules are not initialized skips `fortran_graph`
(and `bridge` degrades to shell-only).

## State_File schema

Path: `.reingest_state/<collection_version>/state.json` (gitignored). Written
atomically (temp + `os.replace`). `PROGRESS.md` mirror regenerated on each write.

```jsonc
{
  "schema_version": 1,
  "collection_version": "v9-0-0",
  "backend": "cots",
  "embedding_profile": "mpnet768",
  "created_at": "2026-07-08T22:00:00Z",
  "updated_at": "…",
  "attempt_cap": 3,
  "config": {
    "tenants_yaml_sha": "…",          // detect catalog drift across re-init
    "stages_yaml_sha": "…"
  },
  "units": [
    {
      "id": "gw_v17:fortran_graph",
      "tenant_id": "gw_v17",
      "branch": "dev/gfs.v17",
      "workflow_subdir": "dev-v17",
      "label_prefix": "GW_V17_",
      "lifecycle": "staging",
      "stage": "fortran_graph",
      "kind": "graph",
      "script": "ingest_fortran_graph_v8.py",
      "mode": "full",
      "depends_on": ["code"],
      "status": "pending",          // pending|running|done|failed|skipped|blocked
      "attempts": 0,
      "last_error": null,
      "adaptations": [],            // free-text notes when the agent fixes+re-queues
      "metrics": {},                // {nodes:…, rels:…, docs:…, probe:…}
      "started_at": null,
      "ended_at": null
    }
    // … one per (tenant, stage) + global stages
  ]
}
```

`next` ordering: pick the actionable unit (status ∈ {`pending`,`failed`},
`attempts < attempt_cap`, all same-tenant `depends_on` terminal) with the lowest
`(stage_order, tenant_order)`; prefer `reset`/`worktree` early; return
`{"unit": null}` when none remain.

## State_Manager CLI (`reingest_state.py`)

Pure state I/O — no ingestion, no network. Subcommands:

```
reingest_state.py init   --collection-version v9-0-0 [--attempt-cap 3]
                         [--catalog …/tenants.yaml] [--stages …/reingest_stages.yaml]
reingest_state.py next   [--json]           # → one actionable unit, or {"unit": null}
reingest_state.py start  --id gw_v17:code
reingest_state.py done   --id gw_v17:code   --metrics '{"docs": 26316}'
reingest_state.py fail   --id gw_v17:code   --error "…" [--requeue]   # --requeue → pending, not attempt++
reingest_state.py skip   --id gw_v17:expdir --reason "no materialized EXPDIR"
reingest_state.py report                     # rewrite PROGRESS.md, print summary table
reingest_state.py is-complete                # exit 0 iff all units terminal
```

- `init` is idempotent: existing unit statuses are preserved; only missing units
  (new tenants/stages) are added; catalog/stages SHA drift is recorded and warned.
- All mutating subcommands write atomically and regenerate `PROGRESS.md`.
- Unit-tested against a `tmp_path` state file (matrix build, dependency gating in
  `next`, attempt-cap → `blocked`, atomic write, `is-complete`).

## Loop_Driver (`ralph_reingest_loop.sh`)

```bash
# nohup detached; env: COLLECTION_VERSION, MAX_ITERATIONS, ITER_TIMEOUT,
# SLEEP_BETWEEN, CONFIRM_DESTRUCTIVE. Sources run_mcp_stdio.sh's COTS env block.
i=0
while :; do
  [[ -f "${STATE_DIR}/STOP" ]] && { log "STOP file present — halting"; break; }
  python3 …/reingest_state.py is-complete && { log "all units terminal"; break; }
  (( i++ >= MAX_ITERATIONS )) && { log "max iterations reached"; break; }
  log "=== iteration ${i} ==="
  timeout "${ITER_TIMEOUT}" \
    kiro-cli chat --no-interactive --prompt-file "${PROMPT}" \
    >> "${LOG}" 2>&1 || log "iteration ${i} exited non-zero (unit state recorded by CLI)"
  sleep "${SLEEP_BETWEEN}"
done
python3 …/reingest_state.py report
```

- The exact non-interactive CLI invocation (flag names) is confirmed against the
  installed Kiro CLI build on the COTS host (`SETUP/update-kiro-cli-musl.sh`) at
  implementation time; the contract is "feed the prompt, run headless, exit".
- Detached run: `CONFIRM_DESTRUCTIVE=yes nohup bash scripts/ralph_reingest_loop.sh
  > logs/reingest_$(date +%Y%m%dT%H%M%S).log 2>&1 &`.
- Graceful stop: `touch .reingest_state/STOP`. Resume: just re-launch — state is
  durable.

## Iteration_Prompt (`ralph_reingest_prompt.md`) — shape

Fixed, small, one-unit discipline:

> You are ONE iteration of the COTS re-ingest Ralph loop. Do exactly one unit.
> 1. `unit = reingest_state.py next --json`. If `unit is null`, stop now.
> 2. `reingest_state.py start --id <unit.id>`.
> 3. Ensure the COTS env is active (source the env block). If `unit.stage` is a
>    prep/`reset` stage, run its command (reset requires `CONFIRM_DESTRUCTIVE=yes`);
>    else run `python3.12 mcp_server_python/scripts/<unit.script> --tenant
>    <unit.tenant_id> --mode <unit.mode> --collection-version <ver> --delay <d>`.
> 4. If the source precondition is unmet, `reingest_state.py skip` with the reason
>    and stop.
> 5. Run the Validation_Probe for `unit.kind` via the `agentcore-mcp-rag` MCP
>    tools (vector: `get_knowledge_base_status` + one smoke query; graph:
>    a traversal on the tenant's ground-truth symbol). Capture counts.
> 6. On success: `reingest_state.py done --metrics '{…}'`.
>    On failure: diagnose. If a bounded retry may fix it, `fail --error …`
>    (the loop retries with backoff). If you identify a systematic fix (parser,
>    path, flag) and apply it, record it and `fail --requeue`. Do NOT exceed the
>    attempt cap — the state manager will mark it `blocked`.
> 7. STOP. Do not pick up another unit.

## COTS-aware reset (Requirement 9)

`delete_tenant_indices.py` today drives OpenSearch (`raw_os_client.indices.*`) +
Neptune — AWS only. For COTS, add a reset path (extend the tool via a
`--backend`-aware branch, or a sibling `reset_tenant_cots.py`) that:

- **ChromaDB**: delete the tenant-prefixed collections for the target
  Collection_Version via the Chroma client (`list_collections` → filter by
  `<index_prefix>…<collection_version>` → `delete_collection`). The default `gw`
  tenant has an empty index prefix, so scope by the exact target collection names
  derived from `CollectionNamer(collection_version)` to avoid touching the serving
  set.
- **Neo4j**: delete the tenant-prefixed labelled nodes for the target version.
  Because `MERGE` re-creates nodes on re-ingest, reset is only needed to purge
  *stale* (old-path) nodes; scope by `label_prefix` (`GW_V17_…`) and, for the
  default `gw` tenant, by unprefixed base labels **restricted to the target
  version stamp** so the serving graph is untouched when building a new version.
- **Dedupe registry**: clear only this tenant's `(collection, sha)` keys for the
  target version (never the cross-tenant registry wholesale).
- **Guards**: `CONFIRM_DESTRUCTIVE=yes` required; `--dry-run` prints the plan;
  a ChromaDB data-dir backup + `neo4j-admin dump` (or an online backup) captured
  first and logged.

When building a *new* Collection_Version alongside the serving set, `reset` is
largely a no-op (the new collections don't exist yet) — it exists to make
re-runs and in-place rebuilds clean and idempotent.

## Validation probes (via `agentcore-mcp-rag` MCP tools)

| Unit kind | Probe | Pass condition |
|---|---|---|
| vector (`documentation`/`code`/`jjobs`) | `get_knowledge_base_status(tenant_id)` + `search_documentation`/`find_similar_code(tenant_id)` | target-collection doc count rose; ≥1 relevant hit |
| dual (`config`) | above + `find_env_dependencies(var, tenant_id)` | doc count rose AND `SETS_ENV` edges present |
| graph shell (`shell_graph`) | `find_callers_callees` / `trace_full_execution_chain(tenant_id)` on a ground-truth J-Job/script | non-empty expected edges |
| graph fortran (`fortran_graph`) | `find_callers_callees("setuprad", tenant_id)` (or tenant ground truth) | non-empty CALLS/USES |
| graph bridge (`bridge`) | `trace_full_execution_chain` crossing Shell→Fortran | ≥1 `EXECUTES` edge |
| graph rocoto (`rocoto`) | `explain_workflow_component` / dependency query | DAG nodes/edges present |
| `validate` | `check_knowledge_integrity(tenant_id)` | no critical integrity gaps |

Ground-truth symbols per tenant come from `branch_ground_truth.py` (e.g. `gw`
baseline vs `gw_v17`). For non-`gw` tenants the graph may legitimately be sparser
(documented in the gap tracker) — the probe asserts "non-empty where ground truth
says it should be non-empty", not parity with `gw`.

## Adaptation policy (test-and-adapt)

- **Transient** (timeout, Neo4j/Chroma connection blip, rate limit): `fail`
  (attempt++) → loop retries with exponential backoff (attempt-indexed sleep in
  the driver / a per-unit `next_eligible_at`).
- **Systematic** (parser exception on a file class, wrong path after rename, a
  missing flag): the iteration applies the smallest fix (edit the ingester/config,
  or correct the stage catalog), records an `adaptations[]` note, and `fail
  --requeue` (status → `pending`, attempts unchanged) so the fix is exercised next
  iteration. If the fix touches shared code, the `validate` stages re-exercise it.
- **Unrecoverable** within the cap: `blocked` — the loop moves on; blocked units
  are listed in `PROGRESS.md` and the final report for a human.

## Safety and rollback

- **Build-alongside default**: a new Collection_Version means the serving
  collections are never mutated during the run; cutover is a separate human step.
- **Destructive gate**: `reset` / in-place rebuild require `CONFIRM_DESTRUCTIVE=yes`
  and support `--dry-run`; a ChromaDB + Neo4j backup precedes any reset.
- **Idempotent re-runs**: upsert-by-SHA + `MERGE` + per-`(collection, sha)`
  dedupe make every unit safely repeatable.
- **Bounded loop**: max iterations, per-iteration timeout, stop-file.
- **No auto-commit / no auto-cutover**: per `08-git-operation-policy.md` and
  Requirement 12.3.

## Cutover (human-gated, Requirement 12)

1. `reingest_state.py report` shows all units terminal + per-tenant fresh-vs-old
   counts.
2. Operator spot-checks via the search UI in **comparison mode** (existing
   `set_search_comparison`-style baseline-vs-improved) — old vs fresh
   Collection_Version.
3. On acceptance, re-point the serving config (`run_mcp_stdio.sh` /
   `mcp-env.sh` collection version, and any `CollectionNamer` default) to the
   fresh version.
4. Retire the old collection as a separate, separately-confirmed destructive
   action.

## Testing strategy

- **Unit** (`reingest_state.py`): matrix build from a fixture catalog + stages;
  `next` respects `depends_on` and the attempt cap (→ `blocked`); idempotent
  `init` preserves statuses and adds new tenants; atomic write survives a
  simulated crash; `is-complete` exit codes.
- **Dry-run integration** (no writes): `--dry-run` on `reset` and each ingester
  for one tenant on the COTS host prints a coherent plan; the Loop_Driver runs a
  bounded number of iterations against a throwaway Collection_Version and reaches
  a consistent terminal state.
- **Probe wiring**: the Validation_Probe calls resolve real MCP tools with
  `tenant_id` and interpret results correctly (mocked tool responses in unit
  scope; live smoke on the COTS host for one tenant).
- Property-based testing is not the fit here (the value is orchestration + live
  side effects); targeted unit tests + dry-run integration mirror the
  `ingest-dedupe-and-graph-fix` / `remediate_v17_reingest.sh` precedent.

## Open questions (resolve at kickoff)

1. **Collection_Version value** — bump to `v9-0-0` (build alongside; safest,
   default) vs in-place rebuild of `v8-0-0` (requires the destructive gate). The
   design supports both; pick one before `init`.
2. **Neo4j GDS on COTS** — is the GDS plugin present on the COTS Neo4j Community
   instance? Determines whether `community_summaries` runs or is `skipped`
   (Gap J).
3. **EXPDIR availability per tenant** — which tenants have materialized
   `supported_repos/EXPDIR*` trees on the COTS host? Determines `expdir`/`rocoto`
   coverage vs `skipped`.
4. **Non-interactive Kiro CLI invocation** — confirm the exact headless
   prompt-feeding flags for the installed CLI build before wiring the Loop_Driver.
