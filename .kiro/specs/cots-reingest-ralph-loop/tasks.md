# Implementation Plan: COTS Full Re-Ingest via Ralph Loop

## Overview

Direct the Kiro CLI on the Parallel Works **COTS host** (ChromaDB + Neo4j,
`DB_BACKEND=cots`, `mpnet768`) to perform a full, resumable re-ingest of a
**fresh, version-tagged collection (vector + GraphRAG) across all tenants**,
reflecting the Phase 67 `supported_repos/` rename and the updated manifest.

Execution is a **Ralph loop**: an outer driver re-invokes the CLI once per
iteration; each iteration does exactly one `(tenant, stage)` unit — run →
validate → adapt → record → stop — checkpointing to a durable state file so the
run survives disconnects and completes over many hours.

Two groups build the orchestration (Tasks 1–3) and thread the small pipeline
touch-points (Task 4); the loop then runs the matrix (Tasks 5–7); cutover and
docs close it out (Tasks 8–9). Tasks 1–4 need no destructive action and no live
ingest. Tasks 5+ are gated on the kickoff decisions (Collection_Version,
`CONFIRM_DESTRUCTIVE`) and run on the COTS host.

Sub-tasks marked `*` are test-only and may be skipped to ship faster.

## Tasks

- [ ] 1. Stage catalog + State_Manager
  - [ ] 1.1 Author the stage catalog `mcp_server_python/scripts/reingest_stages.yaml`
    - Encode per-tenant stages (`worktree`, `reset`, `documentation`, `code`,
      `jjobs`, `config`, `shell_graph`, `fortran_graph`, `expdir`, `rocoto`,
      `bridge`, `validate`) and global stages (`ee2_standards`,
      `community_summaries`) with `script`, `kind`, `depends_on`,
      `source_precondition`, and `probe` fields per the design stage table
    - _Requirements: 7.2, 8.1, 8.2, 8.3, 8.4, 8.5, 13.1_
  - [ ] 1.2 Implement `reingest_state.py` (init / next / start / done / fail / skip / report / is-complete)
    - Build the Work_Matrix from `tenants.yaml` × `reingest_stages.yaml`; record
      self-describing tenant fields per unit; atomic write (temp + `os.replace`);
      regenerate `PROGRESS.md` on every mutation; `next` enforces `depends_on`
      terminality + attempt cap; `is-complete` exit codes; idempotent `init`
      preserves statuses and adds new tenants; record catalog/stages SHA drift
    - _Requirements: 1.1, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4, 4.5, 8.6, 11.1, 11.2_
  - [ ]* 1.3 Unit-test `reingest_state.py`
    - `tmp_path` fixtures: matrix build, `next` dependency gating + attempt-cap →
      `blocked`, idempotent re-`init`, atomic write survives simulated crash,
      `is-complete` exit codes
    - _Requirements: 4.5_

- [ ] 2. Loop_Driver + Iteration_Prompt
  - [ ] 2.1 Write `scripts/ralph_reingest_prompt.md` (one-unit discipline)
    - The fixed per-iteration prompt: `next` → `start` → run the stage → validate
      via MCP tools → `done`/`fail`/`skip`(/`fail --requeue`) → STOP; forbid more
      than one unit; exit promptly on the no-work sentinel
    - _Requirements: 6.1, 6.2, 6.3, 10.1, 10.2, 10.3, 11.3_
  - [ ] 2.2 Write `scripts/ralph_reingest_loop.sh` (bounded, detached, resumable)
    - Loop until `is-complete` (0) / STOP file / `MAX_ITERATIONS`; per-iteration
      `timeout`; sleep between; source the COTS env block from `run_mcp_stdio.sh`;
      continue on non-zero iteration exit; append to a timestamped `logs/` file;
      final `report`. Confirm the installed Kiro CLI's non-interactive
      prompt-feeding flags before wiring
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

- [ ] 3. COTS-aware reset path
  - [ ] 3.1 Add the COTS reset (ChromaDB collections + Neo4j labels for a tenant)
    - Extend `delete_tenant_indices.py` with a `--backend cots` branch (or a
      sibling `reset_tenant_cots.py`): delete the tenant-prefixed ChromaDB
      collections and Neo4j labelled nodes **scoped to the target
      Collection_Version**; clear only this tenant's `(collection, sha)` dedupe
      keys; never touch other tenants or the serving set
    - Guards: require `CONFIRM_DESTRUCTIVE=yes`; support `--dry-run`
    - _Requirements: 9.1, 9.2, 9.4, 11.4_
  - [ ] 3.2 Pre-reset backup hook
    - Before any real reset, snapshot the ChromaDB data dir and take a Neo4j dump;
      record paths in the run log
    - _Requirements: 9.3_
  - [ ]* 3.3 Dry-run test of the COTS reset for one tenant
    - `--dry-run` prints a coherent, correctly-scoped plan and touches nothing
    - _Requirements: 9.4, 11.4_

- [ ] 4. Thread the Collection_Version through the ingesters
  - [ ] 4.1 Replace the hardcoded `v8-0-0` with a Collection_Version parameter
    - Add `--collection-version` (env `REINGEST_COLLECTION_VERSION`, default keeps
      current behavior) to the v8 ingesters and route it through `CollectionNamer`
      and the graph version stamp, so one value drives all target names
    - _Requirements: 1.1, 1.2, 14.4_
  - [ ]* 4.2 Confirm collection naming for a throwaway version
    - Dry-run one ingester with a scratch `--collection-version` and confirm the
      derived collection names are fresh and isolated from the serving set
    - _Requirements: 1.3_

- [ ] 5. Kickoff — decisions, init, and preconditions (host)
  - [ ] 5.1 Resolve the Open Questions with the operator
    - Collection_Version (new `v9-0-0` alongside vs in-place `v8-0-0`); Neo4j GDS
      availability (→ `community_summaries` run vs skip); per-tenant EXPDIR
      availability; confirmed non-interactive CLI flags
    - _Requirements: 1.1, 1.4, 13.2_
    - _Tag: research_
  - [ ] 5.2 Initialize the run state
    - `reingest_state.py init --collection-version <ver> --attempt-cap 3`; verify
      the Work_Matrix covers all tenants × stages + globals; review `PROGRESS.md`
    - _Requirements: 2.1, 2.2, 3.1_
    - _Tag: configure_
  - [ ] 5.3 Provision worktrees + capture backups
    - Run `setup_pw_workflow_mount.sh`; confirm each tenant's `.pw_workflow_mount`
      symlink resolves and `sorc/` submodules are initialized where graph stages
      need them; capture the pre-reset ChromaDB + Neo4j backups (Task 3.2)
    - _Requirements: 8.1, 9.3_
    - _Tag: configure_

- [ ] 6. Run the Ralph loop across the matrix (host, long-running)
  - [ ] 6.1 Launch the loop detached
    - `CONFIRM_DESTRUCTIVE=yes nohup bash scripts/ralph_reingest_loop.sh > logs/reingest_<ts>.log 2>&1 &`;
      the loop drives iterations until all units are terminal / STOP / cap
    - _Requirements: 5.1, 5.4, 5.6, 7.1, 7.3, 11.5_
    - _Tag: ingest_
  - [ ] 6.2 Per-unit execution + validation (performed by each iteration)
    - Each iteration runs one stage ingester under the COTS env with
      `--tenant/--mode/--collection-version`, skips unmet-source stages, and runs
      the Validation_Probe (vector counts + smoke query; graph traversal on the
      tenant ground-truth symbol); records `done`/`skip`/`fail`
    - _Requirements: 7.1, 7.3, 7.4, 8.6, 10.1, 10.2, 10.3, 10.4_
    - _Tag: ingest_
  - [ ] 6.3 Adaptation + retries (performed across iterations)
    - Transient failures retry with backoff; systematic failures get a bounded
      fix + `fail --requeue` (recorded in `adaptations[]`); attempt-cap → `blocked`
      and the loop proceeds with other units
    - _Requirements: 11.1, 11.2, 11.3_
    - _Tag: implement_
  - [ ] 6.4 Monitor + steer
    - Tail `logs/` and `PROGRESS.md`; `touch .reingest_state/STOP` to pause; fix
      any `blocked` unit's root cause, `fail --requeue` it, and relaunch to resume
    - _Requirements: 3.2, 5.3, 11.2_
    - _Tag: validate_

- [ ] 7. GraphRAG completeness verification
  - [ ] 7.1 Per-tenant GraphRAG assertions
    - For each tenant, confirm non-zero shell / Fortran / config / bridge
      relationships consistent with `branch_ground_truth.py` (allowing documented
      per-tenant absences); record results in the state `metrics`
    - _Requirements: 12.1_
    - _Tag: validate_
  - [ ] 7.2 (Optional) community summaries
    - If Neo4j GDS is available on COTS, run the community-summaries stage;
      otherwise `skip` with the Gap-J rationale (non-blocking)
    - _Requirements: 13.1, 13.2, 13.3_
    - _Tag: ingest_

- [ ] 8. Cutover (human-gated)
  - [ ] 8.1 Fresh-vs-old comparison
    - `reingest_state.py report` (all terminal); present per-tenant fresh-vs-old
      counts; spot-check in the search UI comparison mode
    - _Requirements: 12.2_
    - _Tag: validate_
  - [ ] 8.2 Re-point serving config to the fresh Collection_Version
    - On operator acceptance, update the serving collection version
      (`run_mcp_stdio.sh` / `mcp-env.sh` / `CollectionNamer` default)
    - _Requirements: 12.3_
    - _Tag: configure_
  - [ ] 8.3 Retire the old collection (separately confirmed)
    - Only after a validated cutover, delete the old collection as an explicit,
      separately-confirmed destructive action
    - _Requirements: 12.4, 11.4_

- [ ] 9. Reporting + documentation
  - [ ] 9.1 Final run report
    - `docs/reports/<date>-cots-full-reingest-<ver>.md`: per-tenant/stage status,
      counts, retries, adaptations, blocked units, cutover outcome
    - _Requirements: 14.1_
    - _Tag: document_
  - [ ] 9.2 CHANGELOG entry
    - Dated entry: the re-ingest, Collection_Version, tenants covered, GraphRAG
      outcome, and cutover status
    - _Requirements: 14.2_
    - _Tag: document_
  - [ ] 9.3 Final checkpoint + commit (no push)
    - Confirm state complete/blocked-surfaced and docs written; stage the new
      scripts, the ingester version-param edits, the report, and the CHANGELOG;
      commit referencing this spec; do NOT push (operator handles the push)
    - _Requirements: 14.5_

## Notes

- `.reingest_state/` is runtime state — add to `.gitignore` (mirrors
  `.remediation_state/`); the durable state file, not chat memory, is the source
  of truth for resumption.
- Idempotency (ChromaDB upsert-by-SHA + Neo4j `MERGE` + per-`(collection, sha)`
  dedupe) makes every unit safely re-runnable; `reset` exists to purge stale
  old-path artifacts, not to enable re-runs.
- The Ralph loop is intentionally single-unit-per-iteration: it keeps each CLI
  context small and checkpoints after every unit so a disconnect loses at most one
  in-flight unit (which is `running` in state and re-selected on resume).
- Destructive actions (`reset`, in-place rebuild, old-collection retirement)
  require `CONFIRM_DESTRUCTIVE=yes`, support `--dry-run`, and are preceded by
  backups. Commits/pushes remain human-gated (`08-git-operation-policy.md`).
- This spec touches the COTS host only — no AWS/Neptune/OpenSearch/AgentCore
  changes, no embedding-model change (`mpnet768` stays).
- Gap J (community summaries: Neo4j GDS Leiden, Node-only pipeline) is tracked in
  `.kiro/steering/12-multi-tenant-gap-tracker.md`; here it is optional and
  non-blocking.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1"] },
    { "id": 2, "tasks": ["1.3", "2.2", "3.1", "4.1"] },
    { "id": 3, "tasks": ["3.2", "3.3", "4.2"] },
    { "id": 4, "tasks": ["5.1"] },
    { "id": 5, "tasks": ["5.2", "5.3"] },
    { "id": 6, "tasks": ["6.1"] },
    { "id": 7, "tasks": ["6.2", "6.3", "6.4"] },
    { "id": 8, "tasks": ["7.1", "7.2"] },
    { "id": 9, "tasks": ["8.1"] },
    { "id": 10, "tasks": ["8.2", "8.3"] },
    { "id": 11, "tasks": ["9.1", "9.2"] },
    { "id": 12, "tasks": ["9.3"] }
  ]
}
```
