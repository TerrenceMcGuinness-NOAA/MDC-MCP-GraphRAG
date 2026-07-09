# Requirements Document — COTS Re-Ingest via the Ralph-Loop Framework

## Introduction

This is the **third iteration** of the COTS full re-ingest effort. The first two
iterations lived in `.kiro/specs/cots-reingest-ralph-loop/` (a hand-rolled
`(tenant, stage)` matrix State_Manager + a bespoke `ralph_reingest_loop.sh`
Loop_Driver). That PoC **proved the ingest pipeline works end-to-end on the COTS
host** (ChromaDB + Neo4j, `DB_BACKEND=cots`, `mpnet768`) and surfaced a precise
set of gaps. This iteration **replaces the bespoke loop** with the community
**Ralph-Loop-for-Kiro-Specs framework** (`mreferre/ralph-loop-kiro-specs`,
Apache-2.0) and **productizes the PoC fixes**, so a fresh, version-tagged
collection (vector + GraphRAG) can be built across all tenants by a disciplined,
self-correcting agent loop.

The external framework is **not installed yet**. Installing/vendoring it and
adapting this repo to its conventions is part of this spec.

### Why adopt the external framework

The bespoke Loop_Driver worked but re-implemented what `mreferre/ralph-loop-kiro-specs`
already provides in a maintained, general form:

- A `kiro-cli chat --trust-all-tools --no-interactive` iteration wrapper with a
  strict **six-phase** cycle (load context → pick ONE task → understand →
  implement → verify exit criteria → update tracking).
- A **self-correction memory** (`progress.md` "Corrections" ❌→✅ table +
  "Codebase Patterns") re-read every iteration so a mistake is never repeated.
- A `<promise>COMPLETE</promise>` completion sentinel, `specs_time.md` timing,
  and a self-contained `summary.html` dashboard on completion.
- Automatic vs manual iteration modes.

Adopting it lets us delete bespoke loop code, gain the self-correction memory
(which directly addresses the "same gotcha hit repeatedly" risk), and align with
a documented, shareable pattern.

## Glossary

- **Framework**: `mreferre/ralph-loop-kiro-specs` — the two-file Ralph loop
  (`ralph-loop-kiro-specs-prompt.md`, `ralph-loop-kiro-specs-script.sh`).
- **Prior_Spec**: `.kiro/specs/cots-reingest-ralph-loop/` — iterations 1-2
  (matrix State_Manager, bespoke loop, COTS reset, version threading). Retained.
- **State_Manager**: `mcp_server_python/scripts/reingest_state.py` — the
  `(tenant, stage)` work-matrix engine built in Prior_Spec. Reused as the
  dependency-DAG backend, driven *by* the Framework rather than the bespoke loop.
- **Corrections_Seed**: the concrete ❌→✅ correction entries derived from the
  PoC session (see Requirement 8), pre-loaded into this spec's `progress.md`.
- **Fresh_Collection**: the `v9-0-0` (or operator-chosen) version-tagged
  vector + graph set, built alongside the serving `v8-0-0` set.
- **Slurm_Cluster**: the minicluster behind the COTS head node — Slurm 23.11.9,
  partition `emcmcpminicluster`, 8 cloud-burst compute nodes (4 CPUs each,
  auto-resume from `idle~` on submit), GPU-capable if provisioned. The head node
  hosts ChromaDB (`:8080`) and Neo4j (`:7687`); compute nodes reach them over the
  cluster network (NOT `localhost`).
- **Head_Node**: the node running the Ralph loop, ChromaDB, and Neo4j.
- **Compute_Node**: a Slurm-scheduled worker that runs `sbatch`-dispatched heavy
  ingest stages (embedding, Fortran parse).

## Concerns carried forward from the PoC (the reason this iteration exists)

Every item below was observed live on the COTS host during the Prior_Spec PoC and
MUST be addressed here (as a requirement) and pre-seeded as a Correction (R8):

1. **Vector write path was OpenSearch-only.** The v8 vector ingesters wrote via
   `raw_os_client.index(...)`; `ChromaDBAdapter` has no `_raw_client`, so they
   crashed on COTS (`'NoneType' object has no attribute 'index'`). The PoC added
   `ChromaDBAdapter.upsert_document` + `_ingest_common.write_vector_doc`
   (backend-agnostic). This must be productized + tested.
2. **Graph version-isolation is partial.** Only `code`/`jjobs` stamp
   `n.collection_version`; `shell_graph`/`fortran_graph`/`config`/`rocoto`/`bridge`
   do NOT — so running them MERGEs into the LIVE serving labels rather than an
   isolated fresh-version graph. All graph ingesters must version-stamp for a true
   build-alongside.
3. **Validation backend mismatch.** The `agentcore-mcp-rag` MCP targets AWS, not
   the COTS stores being written. COTS validation must use direct ChromaDB/Neo4j
   checks (or a COTS-configured MCP such as `eib-mcp-gateway`).
4. **Collection-name mismatch on COTS.** Ingesters write `mdc-*-titan1024[-ver]`
   while COTS queries resolve `mdc-*-mpnet768`. Fresh collections are therefore
   not reachable by the serving query path until cutover reconciles names. The
   ingesters should derive the profile-correct physical name (`mpnet768` on COTS).
5. **Long-stage vs LLM-iteration timeout.** `documentation` (~2,500+ docs, 20 min+),
   `code`, and `fortran_graph` (~29k files) exceed a short per-iteration timeout;
   a killed iteration left the unit `running` (never re-selected by `next`). The
   loop's per-iteration timeout must exceed the longest stage, or long stages must
   run detached with the iteration polling for completion.
6. **`mpnet768` provider warning is misleading.** `sentence-transformers` (5.1.2)
   imports and the provider produces real 768-dim vectors, but a "not installed"
   warning is emitted regardless — it caused a wrong "embeddings unavailable"
   conclusion. Silence/clarify it.
7. **Per-tenant source variance is normal.** `dev-v17` has no `parm/config` tree
   (→ `config` skip); only `gw`/`gw_v17` have EXPDIR trees (→ others skip
   `expdir`/`rocoto`); `gefs-v12` `sorc` has 265 files (<1000 → `fortran_graph`
   skip). Skips with reasons are correct, not failures.
8. **The COTS stores hold LIVE data** (Neo4j 343k nodes / 4.2M rels; 15 ChromaDB
   collections). Even in a PoC, destructive actions stay behind
   `CONFIRM_DESTRUCTIVE=yes`; the default posture is build-alongside a fresh
   version, cutover human-gated.

## Requirements

### Requirement 1: Vendor and wire the external Framework

**User Story:** As an operator, I want the maintained Ralph-Loop framework
installed in this repo so the re-ingest is driven by it, not by bespoke loop code.

#### Acceptance Criteria
1. THE repo SHALL vendor `ralph-loop-kiro-specs-prompt.md` and
   `ralph-loop-kiro-specs-script.sh` from `mreferre/ralph-loop-kiro-specs`
   (Apache-2.0) at a documented path, preserving the LICENSE/attribution.
2. THE Framework SHALL be invocable as
   `./ralph-loop-kiro-specs-script.sh <max_iterations> <specs_name>` against
   `this` spec directory.
3. THE bespoke `scripts/ralph_reingest_loop.sh` SHALL be deprecated (kept for
   reference, marked superseded) once the Framework drives the run.
4. THE Framework's expectations SHALL be satisfied without modifying its two
   vendored files (adapt the repo to the Framework, not vice-versa) except for a
   clearly-marked local patch if strictly required (documented in `design.md`).

### Requirement 2: Provide the steering files the Framework loads

**User Story:** As the Framework, I need `product.md`, `structure.md`, `tech.md`
so Phase 1 context-load works.

#### Acceptance Criteria
1. THE repo SHALL provide `.kiro/steering/product.md`, `structure.md`, and
   `tech.md` (new, or thin adapters pointing at the existing numbered steering
   files) describing the MDC MCP-RAG product, repo structure, and COTS tech stack.
2. THESE files SHALL NOT contradict the existing numbered steering files; where
   overlap exists they SHALL summarize + cross-reference.

### Requirement 3: Express the re-ingest as a Framework-native `tasks.md`

**User Story:** As the Framework, I pick the lowest-numbered incomplete task each
iteration; I need the re-ingest expressed as numbered tasks with exit criteria.

#### Acceptance Criteria
1. THIS spec's `tasks.md` SHALL enumerate the re-ingest as numbered tasks with
   `[ ]`/`[X]`/`[F]` markers, each referencing the requirement(s) it fulfils and
   stating explicit **exit criteria** (Framework Phase 5).
2. THE task list SHALL either (a) drive the existing `reingest_state.py` matrix as
   the per-task backend, or (b) encode the `(tenant, stage)` units directly as
   tasks — the choice SHALL be made in `design.md` (Requirement 7) and be
   consistent with dependency ordering (nodes before edges; reset before ingest).
3. EACH ingest task's exit criteria SHALL be COTS-truthful (direct ChromaDB
   `count()` rose / Neo4j edge count non-empty), per Concern 3.

### Requirement 4: Productize the vector write path (Concern 1)

#### Acceptance Criteria
1. `ChromaDBAdapter.upsert_document` and `_ingest_common.write_vector_doc` (added
   in the PoC) SHALL be retained, unit-tested, and used by all four vector
   ingesters (`documentation`/`code`/`jjobs`/`config`).
2. AWS behaviour (OpenSearch `raw_os_client.index`) SHALL remain byte-for-byte
   unchanged (the helper branches on `raw_os_client is None`).
3. Metadata SHALL be sanitized to ChromaDB-legal scalars.

### Requirement 5: Version-stamp all graph ingesters (Concern 2)

#### Acceptance Criteria
1. `shell_graph`, `fortran_graph`, `config`, `rocoto`, and `bridge` ingesters
   SHALL set `n.collection_version = <version>` on the nodes/edges they create
   (matching `code`/`jjobs`).
2. `reset_tenant_cots.py --version-scoped-labels` (the safe default for a fresh
   version) SHALL then correctly isolate the fresh graph from the serving graph
   for ALL stages, not just `code`/`jjobs`.
3. A build-alongside run SHALL leave the serving (unversioned / non-fresh) graph
   node counts unchanged (verified before/after).

### Requirement 6: Reconcile COTS collection naming (Concern 4)

#### Acceptance Criteria
1. ON COTS, the vector ingesters SHALL write to the profile-correct physical
   collection base (`mdc-{domain}-mpnet768`), so the Fresh_Collection is reachable
   by the COTS query path (`resolve_index` for `mpnet768`), version-suffixed.
2. THE default (serving) version SHALL keep resolving to the existing serving
   collection names (no regression to the live query path).

### Requirement 7: Long-stage handling via Slurm compute dispatch (Concern 5)

#### Acceptance Criteria
1. Heavy stages (`documentation`, `code` embedding; `fortran_graph`,
   `shell_graph` parse) SHALL be dispatched to the Slurm_Cluster via `sbatch`
   (per-tenant or sharded array jobs) rather than run in the head-node LLM
   iteration. The Ralph iteration submits the job, records the job id, and polls
   (`squeue`/`sacct`) for completion — so no unit is left stuck `running`.
2. WHERE a heavy stage is small enough (e.g. `jjobs`, or a tenant whose `sorc`
   has <1000 files), it MAY run inline on the head node instead of via `sbatch`
   (a per-stage size threshold decides).
3. IF a task cannot complete after the Framework's 3 attempts (or its Slurm job
   fails), it SHALL be marked `[F]` with the blocker logged as an `UNRESOLVED`
   Correction (Framework Phase 4).
4. Every stage SHALL be idempotent (ChromaDB upsert-by-SHA `_id` + Neo4j `MERGE`
   + `collection_version` stamp) so an interrupted / re-queued stage resumes
   cleanly — critical because Slurm jobs may be pre-empted on cloud-burst nodes.

### Requirement 8: Pre-seed `progress.md` with the Corrections_Seed

**User Story:** As the loop, I re-read Corrections before every task so I never
repeat a known mistake.

#### Acceptance Criteria
1. THIS spec's `progress.md` SHALL be pre-seeded with a Corrections table encoding
   the PoC learnings, at minimum:
   - `python3` not `python3.12` on the COTS host.
   - Validate COTS writes via direct ChromaDB/Neo4j, NOT `agentcore-mcp-rag` (AWS).
   - `reset` needs `CONFIRM_DESTRUCTIVE=yes`; fresh version → version-scoped reset
     (never `--full-prefix-wipe` on a fresh version).
   - Vector ingest on COTS uses `write_vector_doc` (ChromaDB), not `raw_os_client`.
   - `dev-v17` has no `parm/config` → `config` skip is correct.
   - Only `gw`/`gw_v17` have EXPDIR → other tenants skip `expdir`/`rocoto`.
   - `gefs-v12` `sorc`=265 (<1000) → `fortran_graph` skip.
   - The `mpnet768` "not installed" warning is cosmetic; embeddings work (768-dim).
2. THE Corrections_Seed SHALL be a lookup table in the exact ❌→✅ format the
   Framework consumes.

### Requirement 9: Safety, scope, and cutover (unchanged posture)

#### Acceptance Criteria
1. `reset` / in-place rebuild / old-collection retirement SHALL require
   `CONFIRM_DESTRUCTIVE=yes` and support `--dry-run`; a backup precedes any reset.
2. THE Fresh_Collection SHALL be built alongside the serving set; cutover
   (re-point serving + retire old) remains a human-gated step.
3. NO AWS/Neptune/OpenSearch/AgentCore changes; `mpnet768` stays on COTS.
4. NO auto-commit / auto-push (`.kiro/steering/08-git-operation-policy.md`).

### Requirement 10: Reporting

#### Acceptance Criteria
1. THE Framework's `summary.html` + `specs_time.md` SHALL be the primary run
   artifacts; a dated `docs/reports/` entry SHALL summarize the outcome and the
   PoC→Framework migration.
2. THE CHANGELOG SHALL gain a dated entry.

### Requirement 11: Slurm compute-dispatch enablement

**User Story:** As an operator, I want heavy ingest stages to run on the Slurm
minicluster so the head node stays responsive and the ingest parallelizes.

#### Acceptance Criteria
1. THE repo SHALL provide `sbatch` job scripts (e.g.
   `scripts/slurm/reingest_stage.sbatch`) that, on a Compute_Node: set the COTS
   env with `CHROMADB_HOST`/`NEO4J_URI` pointed at the **Head_Node** address (not
   `localhost`), activate the Spack/python env, and run one
   `(tenant, stage, collection-version)` ingester.
2. THE job scripts SHALL request the `emcmcpminicluster` partition and reasonable
   resources (CPUs/mem/time), and SHALL support an optional GPU request
   (`--gres=gpu:N`) for embedding stages when GPU nodes are provisioned; embedding
   stages SHALL use the GPU when `CUDA` is available (sentence-transformers device
   auto-select) and fall back to CPU otherwise.
3. THE design SHALL confirm (and the tasks SHALL verify) that Compute_Nodes can
   reach the Head_Node's ChromaDB (`:8080`) and Neo4j (`:7687`), that the repo +
   `.pw_workflow_mount` worktrees are on a **shared filesystem** visible to
   Compute_Nodes, and that the `all-mpnet-base-v2` model is available on
   Compute_Nodes (shared cache or per-node download).
4. THE dispatcher SHALL bound concurrency (max simultaneous jobs / array width)
   to protect the Head_Node's single ChromaDB + Neo4j from write contention, and
   SHALL prefer per-tenant sharding so tenant graphs stay isolated by label prefix.
5. Slurm job stdout/stderr SHALL land under `logs/slurm/` and the job id + final
   state (`sacct`) SHALL be recorded in the task's `progress.md` entry.
6. IF the Slurm_Cluster is unavailable, heavy stages SHALL fall back to bounded
   inline execution on the Head_Node (Requirement 7.2), never silently skipping.
