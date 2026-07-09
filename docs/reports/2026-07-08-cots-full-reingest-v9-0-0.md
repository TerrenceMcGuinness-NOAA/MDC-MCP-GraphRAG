# COTS Full Re-Ingest via Ralph Loop — Build & Kickoff Report (v9-0-0)

**Date**: 2026-07-08
**Spec**: `.kiro/specs/cots-reingest-ralph-loop/`
**Collection_Version (recommended)**: `v9-0-0` (build alongside the serving `v8-0-0`)
**Host**: Parallel Works COTS (ChromaDB + Neo4j, `DB_BACKEND=cots`, `mpnet768`)
**Status**: Orchestration layer (Tasks 1–4) **built + verified**. Live run
(Tasks 6–8) **operator-gated** and **blocked** on one upstream ingester gap —
see [Live-run blocker](#live-run-blocker).

## Executive summary

This feature adds a resumable, self-continuing **Ralph loop** that re-ingests a
fresh, version-tagged RAG collection (vector + GraphRAG) across all five tenants
on the COTS host, checkpointing after every `(tenant, stage)` unit so a
multi-hour run survives disconnects. The orchestration layer — State_Manager,
stage catalog, Loop_Driver, Iteration_Prompt, COTS-aware reset, and a
Collection_Version parameter threaded through the ingesters — is complete,
unit-tested, and dry-run-verified against the live COTS backend. The destructive
multi-hour live run and the human-gated cutover remain operator steps; a
confirmed upstream gap (the COTS vector-ingest path) must be closed by a
follow-up spec before the vector stages can run.

## What was built (Tasks 1–4) and how it was verified

| Artifact | Path | Verification |
|---|---|---|
| Stage catalog | `mcp_server_python/scripts/reingest_stages.yaml` | 12 per-tenant + 2 global stages; drives a 62-unit matrix (5×12 + 2). |
| State_Manager | `mcp_server_python/scripts/reingest_state.py` | 16 unit tests pass; live init = 62 units; atomic write + PROGRESS.md mirror. |
| State_Manager tests | `mcp_server_python/tests/unit/test_reingest_state.py` | `16 passed`. |
| Iteration_Prompt | `scripts/ralph_reingest_prompt.md` | One-unit discipline; `python3`; MCP validation probes; STOP after one unit. |
| Loop_Driver | `scripts/ralph_reingest_loop.sh` | `bash -n` clean; bounded/detached/resumable; confirmed `kiro-cli` headless invocation. |
| COTS reset | `mcp_server_python/scripts/reset_tenant_cots.py` | Live dry-run verified; 4 guards proven (see below). |
| Version threading | `_ingest_common.py` + 4 ingesters | Naming helpers asserted; 32 existing ingester tests still pass. |
| Runtime-state ignore | `.gitignore` (`+ .reingest_state/`) | `git check-ignore` confirms `state.json` is ignored. |

### Verification evidence (commands run)

- `python3 -m pytest tests/unit/test_reingest_state.py -q` → **16 passed**.
- `python3 -m pytest tests/unit/test_ingest_dedupe.py test_ingest_cost_model.py test_ingest_cli_v17.py test_ingestion_report_shape.py -q` → **32 passed** (no regression from the shared-parser change).
- Live reset dry-runs against ChromaDB (:8080) + Neo4j (:7687):
  - `gw_v17 v9-0-0` → 3 version-tagged targets (all absent → no-op) + `GW_V17_` label scope.
  - `gw v9-0-0` → version-stamped nodes only; **serving baseline never touched**.
  - `gw v8-0-0` (in-place default on empty-prefix baseline) → **REFUSED (exit 2)**.
  - real reset without `CONFIRM_DESTRUCTIVE=yes` → **REFUSED (exit 2)**.
- Naming helper: default version returns names **unchanged** (serving preserved);
  fresh version yields isolated `…-v9-0-0` names; precedence flag > env > default.

## Open Questions — resolved (Task 5.1)

| # | Question | Resolution (evidence) |
|---|---|---|
| 1 | Collection_Version value | **`v9-0-0` (build alongside)** — safest; the serving `v8-0-0` set is never mutated during the run; cutover is a separate human step. In-place `v8-0-0` is supported but gated behind `--allow-inplace-default` + `CONFIRM_DESTRUCTIVE`. |
| 2 | Neo4j GDS on COTS | **GDS 2.13.7 IS present** (Neo4j Kernel 5.26.20, Community). This removes Gap-J *Blocker 1* on COTS. However `community_summaries` still **skips**: the pipeline is Node-only (Gap-J Blocker 2) and not tenant-aware (Blocker 3) — no runnable Python/tenant pipeline exists yet. It is optional and non-blocking (Req 13). |
| 3 | EXPDIR per tenant | Only `supported_repos/EXPDIR` (gw) and `EXPDIR_v17` (gw_v17) exist. → `gw` and `gw_v17` run `expdir`/`rocoto`; **`gw_sfs`, `gw_jedi_gfs`, `gw_gefs_v12` skip** those stages (Req 7.4). |
| 4 | Non-interactive Kiro CLI flags | **Confirmed** (`kiro-cli 2.11.1`): `kiro-cli chat --no-interactive --trust-all-tools --agent <agent> "<prompt contents>"`. The prompt is the positional `INPUT` argument (there is no `--prompt-file`). |

## Work matrix (initialized, Task 5.2)

`reingest_state.py init --collection-version v9-0-0 --attempt-cap 3` created
**62 units** at `.reingest_state/v9-0-0/state.json` (gitignored):
5 tenants × 12 per-tenant stages + 2 global stages. `next` returns
`gw:worktree` (order 10). Re-init is idempotent (0 added / 62 preserved).

Per-tenant stage order: `worktree → reset → documentation → code → jjobs →
config → shell_graph → fortran_graph → expdir → rocoto → bridge → validate`;
globals: `ee2_standards`, `community_summaries`.

## Live-run blocker

**The COTS vector-ingest path is not implemented in the v8 ingesters.**
Empirically confirmed:

```
build_ingestion_data_access()  # with DB_BACKEND=cots
  -> AttributeError: 'ChromaDBAdapter' object has no attribute '_raw_client'
```

The vector stages (`documentation`, `code`, `jjobs`, `config`) call
`uda.vector_db._raw_client()` and then write via the OpenSearch client API,
hardcoding `mdc-*-titan1024` physical names. On COTS the vector adapter is
`ChromaDBAdapter`, which has no `_raw_client()` and a different (collection-based)
write API; COTS queries also resolve `…-mpnet768`, not `…-titan1024`. Adding a
ChromaDB write path to the ingesters is **out of scope** for this spec
(Requirement 14.4 forbids changing ingester logic beyond threading the
Collection_Version parameter + the reset path), so it must land as a **follow-up
spec** before the vector stages can run on COTS.

Impact on the matrix: the **graph** stages (`shell_graph`, `fortran_graph`,
`expdir`, `rocoto`, `bridge`) write via the Neo4j adapter and are not affected by
this gap. The `worktree`/`reset`/`validate` stages are unaffected. Until the
follow-up lands, the loop will drive vector units to `blocked` (attempt cap) and
proceed with the rest — which is exactly the designed "test-and-adapt, surface
for a human" behaviour.

## Additional host prerequisites (operator, before Task 6)

1. **Worktree mount permissions (Task 5.3).** `.pw_workflow_mount/` is
   root-owned, so `setup_pw_workflow_mount.sh` cannot create the tenant symlinks
   as the run user (`ln: … Permission denied`). Fix once:
   `sudo chown -R "$(id -un)":"$(id -gn)" .pw_workflow_mount` (or run the setup
   script as the directory owner). The five checkouts already exist under
   `supported_repos/`.
2. **Embeddings.** `sentence-transformers` imports (5.1.2) but the `mpnet768`
   embedding **provider is non-functional** on this host (the adapter sets
   `_provider_error`, so `_generate_embedding` raises) — required for any real
   vector embedding.
3. **`sorc/` submodules.** `fortran_graph` needs >1000 files under a tenant's
   `sorc/`; tenants without initialized submodules will `skip` `fortran_graph`
   (and `bridge` degrades to shell-only), per the stage precondition.

## Runbook (operator, host-gated)

```bash
# 0. One-time host prep
sudo chown -R "$(id -un)":"$(id -gn)" .pw_workflow_mount
bash mcp_server_python/scripts/setup_pw_workflow_mount.sh   # build the symlink farm

# 1. (already done) initialize run state
python3 mcp_server_python/scripts/reingest_state.py \
  --collection-version v9-0-0 init --attempt-cap 3

# 2. Dry-run the reset for one tenant (no deletion)
python3 mcp_server_python/scripts/reset_tenant_cots.py \
  --tenant gw_v17 --collection-version v9-0-0 --dry-run

# 3. Launch the Ralph loop detached (DESTRUCTIVE; survives disconnect)
CONFIRM_DESTRUCTIVE=yes REINGEST_COLLECTION_VERSION=v9-0-0 \
  nohup bash scripts/ralph_reingest_loop.sh \
    > logs/reingest_$(date +%Y%m%dT%H%M%S).log 2>&1 &

# Monitor / pause / resume
tail -f logs/reingest_*.log
cat .reingest_state/v9-0-0/PROGRESS.md
touch .reingest_state/STOP      # graceful halt after current iteration
# resume: re-run the same launch command — state is durable
```

## Cutover (human-gated, Task 8 — NOT automatic)

1. `reingest_state.py report` shows all units terminal + per-tenant fresh-vs-old counts.
2. Spot-check the fresh `v9-0-0` vs serving `v8-0-0` in the search UI comparison mode.
3. On acceptance, re-point the serving version (`run_mcp_stdio.sh` / `mcp-env.sh` /
   `CollectionNamer` default) to `v9-0-0`.
4. Retire the old collection as a **separately confirmed** destructive action.

## Scope boundary (per spec)

- COTS host only — **no** AWS/Neptune/OpenSearch/AgentCore changes.
- **No** embedding-model change (`mpnet768` stays).
- **No** ingester parsing/graph-construction changes beyond threading the
  Collection_Version parameter and adding the COTS reset path (Req 14.4).
- **No** auto-commit / auto-cutover; both remain human-gated
  (`.kiro/steering/08-git-operation-policy.md`, Req 12.3, 14.5).

## Task status

| Task | Status |
|---|---|
| 1. Stage catalog + State_Manager (+tests) | **Done, verified** |
| 2. Loop_Driver + Iteration_Prompt | **Done, verified** |
| 3. COTS-aware reset (+backup, +dry-run, +safe version-scoped default) | **Done, verified** |
| 4. Thread Collection_Version | **Done, verified** |
| 5. Kickoff (decisions, init, worktrees) | **Done** — 5.1 resolved; 5.2 init; **5.3 worktrees now mounted** (sudo chown) |
| 6. Run the Ralph loop | **Safe prefix executed live** (worktree×5 + no-op reset×5 done); ingest **blocked** (see below) — 62/62 terminal, `is-complete`=0 |
| 7. GraphRAG completeness verification | Serving baseline documented; **fresh v9-0-0 graph = 0 nodes** (ingest blocked) |
| 8. Cutover | **NOT READY** — fresh set empty; serving retirement refused |
| 9. Reporting + docs | This report + CHANGELOG; **staged, not committed** |

## Live execution attempt & outcome (2026-07-09)

Passing the destructive gate (operator authorization), I executed the loop as far
as is **provably safe against the LIVE serving stores** and captured the blockers
empirically. New evidence gathered this session:

- **The COTS stores are LIVE serving data**: Neo4j = **343,363 nodes / 4,220,211
  rels** (serving `File`/`FortranSubroutine`… + tenant `GW_V17_*` labels);
  ChromaDB = **15 collections** (`code-with-context-v8-0-0`=60,574,
  `global-workflow-docs-v8-0-0/1/2`, `community-summaries`=2,113, `mdc-*-mpnet768`…).
- `sentence-transformers` imports (5.1.2) but the `mpnet768` provider is
  non-functional (adapter `_provider_error`).

### Fixes applied this session (safe, verified)

- **`_ingest_common.build_ingestion_data_access` made COTS-tolerant**: returns
  `raw_os_client=None` when the vector adapter has no `_raw_client` (ChromaDB), so
  the graph-only ingesters can connect on COTS. AWS (OpenSearchAdapter) unchanged.
  Verified: `(uda, None)` + graph query returns 343,363 nodes.
- **`reset_tenant_cots.py` safe default corrected**: for a **fresh** version, graph
  deletes are now **version-scoped by default** (only `collection_version=<ver>`
  nodes), so a non-`gw` reset never wipes the serving graph. Full-prefix wipe now
  requires explicit `--full-prefix-wipe` (warns). Verified via dry-run + a real
  `gw_v17 v9-0-0` reset that **deleted 0 nodes**.
- **Task 5.3**: `sudo chown` + `setup_pw_workflow_mount.sh` → all 5 tenant
  worktrees mounted (`develop/dev-sfs/dev-jedi-gfs/dev-v17` sorc≈29k each;
  `gefs-v12` sorc=265 → its `fortran_graph` correctly skips).

### What ran (safe) vs what is blocked

| Outcome | Units |
|---|---|
| **Done (executed live)** | `worktree` ×5 (mount verified, sorc metrics), `reset` ×5 (real, version-scoped **no-op** — serving untouched) = **10 units** |
| **Blocked → skipped with reason** | vector (`documentation`/`code`/`jjobs`/`config`), graph (`shell_graph`/`fortran_graph`/`expdir`/`rocoto`/`bridge`), `validate`, `ee2_standards`, `community_summaries` = **52 units** |

`is-complete` → exit 0 (all 62 units terminal). PROGRESS.md lists every blocked
unit with its reason.

### Why the ingest stages are blocked (two independent, out-of-scope gaps)

1. **Vector stages** — empirically proven on `gw_v17:documentation`: with
   `raw_os_client=None`, every file logs `'NoneType' object has no attribute
   'index'` and **0 docs are written** (nothing mutated). The v8 vector ingesters
   need a ChromaDB write path (they use the OpenSearch client API + `titan1024`
   names; COTS is collection-based + `mpnet768`) **and** a working embedding
   provider.
2. **Graph stages** — the graph ingesters (`shell_graph`/`fortran_graph`/…) do
   **not** version-stamp their nodes, so running them would `MERGE` into the
   **live serving labels** (e.g. `GW_V17_ShellScript`=1,401, `ShellScript`=589,
   `FortranSubroutine`=80,745) — mutating serving data and violating the
   build-alongside guarantee (Req 1.3). Not run.

Both are explicitly out of scope here (Req 14.4: no ingester logic changes beyond
the Collection_Version parameter + the reset path) and require a **follow-up spec**.

### Task 7 — GraphRAG verification (read-only)

Serving baseline (target the fresh build must reach): CALLS 3,306,540 · USES
679,698 · SETS_ENV 11,988 · DEPENDS_ON_ENV 27,933 · EXPORTS 7,271; per-tenant
`ShellScript` 589 / `GW_V17_ShellScript` 1,401, `FortranSubroutine` 80,745 /
`GW_V17_FortranSubroutine` 36,156, `ConfigFile` 373 / `GW_V17_ConfigFile` 109,
`GW_V17_JJob` 92. **Fresh v9-0-0 graph = 0 nodes** (`collection_version=v9-0-0`
returns 0) — fresh-graph completeness verification is pending the follow-up.

### Task 8 — Cutover verdict: NOT READY

Fresh `v9-0-0` = **0 ChromaDB collections + 0 graph nodes**; serving = 15
collections + 343,363 nodes. Re-pointing serving at an empty set, or retiring the
live collections, is **refused** — it would break the operational legacy system
and destroy live data (Req 12.3 human-gated; guardrails). Cutover reopens only
after the fresh set is built + validated.

### Follow-up spec scope (to actually complete Tasks 6–8)

1. Add a **backend-agnostic vector write path** (a `write_document` method on both
   vector adapters) so the ingesters write to ChromaDB on COTS; fix the `mpnet768`
   provider so embeddings work.
2. Add **per-version graph isolation** (version-stamp all graph ingesters +
   version-scoped reads) so an alongside graph build never touches serving labels.
3. Then re-run the loop (`CONFIRM_DESTRUCTIVE=yes … ralph_reingest_loop.sh`) to
   build + validate v9-0-0, and perform the human-gated cutover.
