# Implementation Plan — COTS Re-Ingest via the Ralph-Loop Framework

Tasks are picked lowest-numbered-first by `ralph-loop-kiro-specs-script.sh`. Mark
`[X]` complete or `[F]` failed. Each task lists its **exit criteria** (verified in
Framework Phase 5) and the requirement(s) it fulfils. Run with:

```
./ralph-loop-kiro-specs-script.sh <max_iterations> cots-reingest-ralph-framework
```

- [ ] 1. Vendor + wire the Ralph-Loop framework
  - [ ] 1.1 Add `ralph-loop-kiro-specs-prompt.md` + `ralph-loop-kiro-specs-script.sh`
    from `mreferre/ralph-loop-kiro-specs` (Apache-2.0) at a documented path with
    LICENSE/attribution; make the script executable.
  - [ ] 1.2 Add `.kiro/steering/{product,structure,tech}.md` (thin, cross-
    referencing the existing numbered steering) so Phase 1 context-load works.
  - _Requirements: 1, 2_
  - _Exit: `./ralph-loop-kiro-specs-script.sh 1 cots-reingest-ralph-framework`
    loads context + prints the prompt without error; steering files present._

- [ ] 2. Productize the PoC code fixes
  - [ ] 2.1 Keep + unit-test `ChromaDBAdapter.upsert_document` +
    `_ingest_common.write_vector_doc`; confirm all 4 vector ingesters use it and
    AWS path is unchanged. _(Req 4)_
  - [ ] 2.2 Version-stamp `shell_graph`, `fortran_graph`, `config`, `rocoto`,
    `bridge` node/edge MERGEs with `collection_version`. _(Req 5)_
  - [ ] 2.3 Reconcile COTS collection naming: vector ingesters target
    `mdc-{domain}-mpnet768` (profile-derived), version-suffixed; default version
    keeps serving names. _(Req 6)_
  - [ ] 2.4 Silence/clarify the misleading `mpnet768` "not installed" warning. _(Concern 6)_
  - _Exit: `pytest` green (incl. the 16 reingest_state tests + new write-path +
    version-stamp tests); a fresh-version vector ingest lands in an
    `mdc-*-mpnet768-<ver>` collection; a version-scoped reset on a fresh version
    leaves serving graph counts unchanged._

- [ ] 3. Slurm compute-dispatch enablement
  - [ ] 3.1 Add `scripts/slurm/reingest_stage.sbatch` (head-node DB host, Spack
    env, one `(tenant,stage,version)` ingester; optional `--gres=gpu:1`). _(Req 11)_
  - [ ] 3.2 Verify Compute_Node → Head_Node reachability (`:8080`/`:7687`),
    shared FS visibility of repo + `.pw_workflow_mount`, and mpnet model
    availability on nodes (submit a trivial 1-doc write-and-read `sbatch` smoke). _(Req 11.3)_
  - [ ] 3.3 Add the dispatcher glue: task submits `sbatch`, records job id, polls
    `sacct`, bounds concurrency (≤4), logs to `logs/slurm/`. _(Req 11.4, 11.5)_
  - _Exit: the smoke job writes 1 doc from a compute node to the head-node
    ChromaDB and reads it back; job id + `sacct` state recorded in `progress.md`._

- [ ] 4. Kickoff — decisions + init
  - [ ] 4.1 Resolve Open Questions (head-node host, shared FS, GPU, whether to
    continue the PoC `v9-0-0` state or re-init). _(Req 9)_
  - [ ] 4.2 `reingest_state.py init --collection-version <ver>` (or reuse the
    PoC's `.reingest_state/v9-0-0`, which already has worktree×5 + reset×5 +
    gw_v17 jjobs/shell_graph/expdir/rocoto/bridge done). _(Req 3)_
  - _Exit: matrix present; `report` shows the carried-over done units._

- [ ] 5. Drain the matrix (per-tenant), Slurm-dispatched
  - [ ] 5.1 gw  — documentation, code, jjobs, config, shell_graph, fortran_graph,
    expdir, rocoto, bridge, validate (heavy → `sbatch`; light → inline).
  - [ ] 5.2 gw_v17 — remaining stages (documentation, code, fortran_graph, validate).
  - [ ] 5.3 gw_sfs — full stack.
  - [ ] 5.4 gw_jedi_gfs — full stack.
  - [ ] 5.5 gw_gefs_v12 — full stack (fortran_graph skips: sorc=265<1000).
  - _Requirements: 7, 5, 4, 6, 11_
  - _Exit per tenant: every stage terminal (done/skip[F]); fresh
    `mdc-*-mpnet768-<ver>` collections' `count()` rose; version-stamped graph
    edges non-empty where ground truth expects (branch_ground_truth.py)._

- [ ] 6. GraphRAG completeness verification
  - [ ] 6.1 Per tenant, confirm non-zero shell/Fortran/config/bridge relationships
    (version-stamped) consistent with ground truth; record counts. _(Req 5, 10)_
  - _Exit: counts recorded in `progress.md`; documented per-tenant absences only._

- [ ] 7. Cutover readiness (human-gated — do NOT auto-execute)
  - [ ] 7.1 Fresh-vs-serving comparison per tenant/collection; present verdict.
  - [ ] 7.2 On explicit operator approval only: re-point serving (`resolve_index` /
    `run_mcp_stdio.sh`) to `<ver>`; retire old as a separately-confirmed action. _(Req 9.2)_
  - _Exit: comparison presented; no serving mutation without explicit approval._

- [ ] 8. Reporting + closeout
  - [ ] 8.1 Framework `summary.html` + `specs_time.md` generated on completion;
    dated `docs/reports/` entry summarizing the PoC→Framework migration + outcome. _(Req 10)_
  - [ ] 8.2 CHANGELOG dated entry; stage all changes (no push). _(Req 9.4, 10.2)_
  - _Exit: report + CHANGELOG written; `git status` shows staged, uncommitted._

## Notes
- Long stages go to Slurm (Req 7/11); the head-node iteration stays light.
- Idempotent (upsert-by-SHA + MERGE + version stamp) → Slurm pre-emption safe.
- `.reingest_state/` remains gitignored runtime state; `progress.md` is the
  Framework's durable memory and IS committed with the spec.
