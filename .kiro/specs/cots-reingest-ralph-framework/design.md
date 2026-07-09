# Design Document — COTS Re-Ingest via the Ralph-Loop Framework

## Overview

Iteration 3 keeps the **valuable engine** from the PoC (`reingest_state.py` — the
`(tenant, stage)` dependency-DAG work matrix, the COTS-aware reset, the version
threading, the ChromaDB write path) and swaps the **driver** from the bespoke
`ralph_reingest_loop.sh` to the community **`mreferre/ralph-loop-kiro-specs`**
framework, adding a **Slurm compute-dispatch** layer so heavy stages run on the
minicluster instead of the head-node LLM iteration.

```
                 mreferre/ralph-loop-kiro-specs (VENDORED, unmodified)
   ┌───────────────────────────────────────────────────────────────────────┐
   │  ralph-loop-kiro-specs-script.sh  <max_iter> cots-reingest-ralph-framework│
   │    └─ pipes ralph-loop-kiro-specs-prompt.md → kiro-cli chat              │
   │         --trust-all-tools --no-interactive  (6-phase self-correcting)    │
   └───────────────────────────────────────────────────────────────────────┘
        │ Phase 2: pick lowest-numbered incomplete task in tasks.md
        ▼
   ┌───────────────────────────────┐     reads/writes     ┌───────────────────┐
   │ tasks.md  (this spec)         │◄────────────────────►│ progress.md        │
   │  T-nn: (tenant, stage) unit   │                      │  Corrections ❌→✅  │
   │  exit criteria = COTS-truthful│                      │  Codebase Patterns │
   └──────────────┬────────────────┘                      │  progress log      │
                  │ implement                             └───────────────────┘
                  ▼
   ┌───────────────────────────────────────────────────────────────────────┐
   │ per task the agent:                                                    │
   │  • reingest_state.py start/done/fail  (matrix state — REUSED)          │
   │  • light stage (jjobs/reset/expdir/rocoto/bridge) → run inline (head)   │
   │  • heavy stage (documentation/code/shell_graph/fortran_graph) →         │
   │      sbatch scripts/slurm/reingest_stage.sbatch  → Compute_Node         │
   │      poll squeue/sacct → validate direct-DB → done | [F]                │
   └───────────────────────────────┬───────────────────────────────────────┘
                                    ▼
   Head_Node: ChromaDB :8080 + Neo4j :7687     Slurm: emcmcpminicluster (8×4cpu, GPU-opt)
   (fresh v9-0-0 collections + version-stamped graph, ALONGSIDE serving)
```

## Two paradigms, reconciled

| | PoC bespoke loop | mreferre Framework |
|---|---|---|
| Unit selection | `reingest_state.py next` (DAG, deps + attempt cap) | lowest-numbered incomplete task in `tasks.md` |
| Memory | state.json + PROGRESS.md | progress.md (Corrections + Patterns) + specs_time.md |
| Completion | `is-complete` exit 0 | `<promise>COMPLETE</promise>` sentinel |
| Dashboard | PROGRESS.md table | `summary.html` |

**Decision (Requirement 3.2 → option a):** keep `reingest_state.py` as the
matrix backend and express `tasks.md` as a **thin ordered task list that drives
it**. Each `tasks.md` task calls `reingest_state.py next` to obtain the next
actionable `(tenant, stage)` unit, runs it (inline or via Slurm), validates, and
marks it — then the Framework moves to the next task. This preserves the
dependency DAG (nodes-before-edges, reset-before-ingest) that a flat task list
cannot express, while gaining the Framework's self-correction + dashboard.

A small number of "meta" tasks bracket the matrix drain:
- `T-01` install/vendor the Framework + steering files.
- `T-02` productize the vector write path (Req 4) + version-stamp all graph
  ingesters (Req 5) + naming reconcile (Req 6) + Slurm job scripts (Req 11).
- `T-03` verify Compute_Node → Head_Node DB reachability + shared FS + model cache.
- `T-10..` "drain the matrix" tasks (one per tenant, or one that loops the matrix
  to completion) that dispatch/monitor stages.
- `T-90` GraphRAG completeness verification. `T-95` cutover readiness (human-gated).

## Slurm compute dispatch

### Job script (`scripts/slurm/reingest_stage.sbatch`)

```bash
#!/usr/bin/env bash
#SBATCH --partition=emcmcpminicluster
#SBATCH --cpus-per-task=4
#SBATCH --time=08:00:00
#SBATCH --output=logs/slurm/%x_%j.out
# optional (when GPU nodes exist):  #SBATCH --gres=gpu:1
set -uo pipefail
# COTS env — DBs live on the HEAD NODE, not localhost on a compute node.
export DB_BACKEND=cots MCP_EMBEDDING_PROFILE=mpnet768
export CHROMADB_HOST="${HEAD_NODE_HOST:?}" CHROMADB_PORT=8080
export NEO4J_URI="bolt://${HEAD_NODE_HOST:?}:7687" NEO4J_USER=neo4j NEO4J_PASSWORD="${NEO4J_PASSWORD}"
export MCP_WORKFLOW_MOUNT="${REPO_ROOT}/.pw_workflow_mount"
export REINGEST_COLLECTION_VERSION="${REINGEST_COLLECTION_VERSION}"
source "${SPACK_SETUP}"; module load python/3.11.14 py-* >/dev/null 2>&1
cd "${REPO_ROOT}/mcp_server_python"
exec python3 "scripts/${SCRIPT}" --tenant "${TENANT}" \
     --collection-version "${REINGEST_COLLECTION_VERSION}" --mode full --delay 0
```

Dispatch: `sbatch --job-name=reingest_${TENANT}_${STAGE} --export=ALL,SCRIPT=...,TENANT=...
scripts/slurm/reingest_stage.sbatch`; the task records the job id and polls
`sacct -j <id> -o State` until terminal, then validates direct-DB.

### Key infra facts (verified 2026-07-09) and open checks
- Slurm 23.11.9; partition `emcmcpminicluster`; 8 nodes × 4 CPU, `idle~`
  (cloud-burst, auto-resume on submit). No GPU gres advertised yet (addable).
- **OPEN (T-03 verifies):** is `/mcp_rag_eib` on a shared FS visible to compute
  nodes? Can compute nodes reach the head node's `:8080`/`:7687`? Is the mpnet
  model cached on compute nodes? These gate the Slurm path; fallback is inline
  head-node execution (Req 7.6).
- Concurrency: cap simultaneous jobs (start with ≤4) — one ChromaDB + one Neo4j
  on the head node are the shared write bottleneck.

## Productized code changes (carried from the PoC, to be finalized + tested)

1. **Vector write path (Req 4)** — DONE in PoC, keep + unit-test:
   `ChromaDBAdapter.upsert_document` + `_ingest_common.write_vector_doc`
   (branches on `raw_os_client is None`; AWS unchanged; metadata sanitized).
2. **Graph version-stamp (Req 5)** — extend `shell_graph`, `fortran_graph`,
   `config`, `rocoto`, `bridge` node/edge MERGEs with `SET … .collection_version
   = $cv` (as `code`/`jjobs` already do). Then `reset_tenant_cots.py`
   version-scoped default isolates the fresh graph for every stage.
3. **Naming reconcile (Req 6)** — on COTS the vector ingesters should target
   `mdc-{domain}-mpnet768` (profile-correct), version-suffixed, so the fresh
   collection is reachable by `resolve_index(..., "mpnet768")`. Today they hardcode
   `mdc-{domain}-titan1024`; make the physical base profile-derived. Default
   version keeps serving names intact.
4. **Provider warning (Concern 6)** — downgrade/clarify the misleading
   "sentence-transformers is not installed" line (it imports; embeddings work).

## Seeded self-correction (`progress.md` Corrections)

The Corrections table is pre-loaded from PoC learnings (Requirement 8) so
iteration 1 already knows the gotchas — see `progress.md` in this spec dir.

## Safety & cutover (unchanged)

Build-alongside a fresh version; `reset`/retirement gated on
`CONFIRM_DESTRUCTIVE=yes` + backup + `--dry-run`; version-scoped reset is the
default for a fresh version (never full-prefix-wipe unless explicit). Cutover
(re-point serving `resolve_index`/`run_mcp_stdio.sh` + retire old) is human-gated.
No AWS/AgentCore changes; `mpnet768` stays. No auto-commit/push.

## Testing strategy

- Unit: `write_vector_doc` backend branch + metadata sanitize; graph
  version-stamp cypher; naming reconcile (default vs fresh, titan1024→mpnet768 on
  cots). Reuse the 16 `reingest_state` tests.
- Integration (head node): one small tenant/stage inline (e.g. `jjobs`) → fresh
  ChromaDB collection count rose + version-stamped nodes (PoC already proved this).
- Slurm smoke (T-03): submit a trivial `sbatch` that writes 1 doc from a compute
  node to the head-node ChromaDB and reads it back — proves reachability + shared
  FS + model cache before draining the matrix.

## Open questions (resolve at kickoff)
1. Head-node hostname/IP that compute nodes use for `:8080`/`:7687` (T-03).
2. Is `/mcp_rag_eib` shared to compute nodes, or must the repo be staged per node?
3. GPU nodes provisioned? If yes, `--gres=gpu:1` on embedding jobs.
4. Collection_Version (`v9-0-0` default) and whether to continue the PoC's
   partial `v9-0-0` state or re-init fresh.
