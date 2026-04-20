# Phase 47a: Rocoto Dryrun PR #125 Log Semantics & Upstream Reconcile

**Version**: 1.0.0
**Status**: Implemented (local; commit pending push)
**Created**: 2026-04-20
**Author**: GitHub Copilot (Claude Opus 4.7) + Terry McGuinness
**Primary Target Repo**: `supported_repos/rocoto` (`feature/dryrun_nodaemon_final`)
**Upstream Review Context**: PR #125 (`feature/dryrun_nodaemon_final` → `develop`)

---

## 1. Executive Summary

Final close-out of the Rocoto `--dryrun` PR after upstream collaborator
@christopherwharrop-noaa's second review pass. The implementation is accepted
on architecture; the remaining feedback is **all about clarity of logging and
terminal output**, plus a trivial merge conflict introduced by upstream PR #126
(removal of `RUBY_VERSION < "1.9.0"` guards).

This phase delivers:
1. Merge of upstream `develop` into `feature/dryrun_nodaemon_final` (1 conflict).
2. Single-line dryrun workflow-log semantics (no more contradictory
   `Submitting … / Dryrun: would submit …` pairs).
3. Per-invocation `Dryrun Mode: no new jobs would be submitted` startup banner.
4. Audit confirming no in-tree string claims dryrun is a "validation tool";
   wording-softening is therefore PR-description-only (no code change required).

---

## 2. Source-of-Truth Inputs

### 2.1 GitHub Review Corpus (PR #125)
- PR URL: `https://github.com/christopherwharrop/rocoto/pull/125`
- Reviewer: `christopherwharrop-noaa` (Collaborator)
- Comment thread distilled to 4 actionable items:
  - **R1** — Add a "you are in dryrun" notice outside of submit moments
    (suggested wording: `Dryrun Mode: no new jobs would be submitted`).
  - **R2** — Disambiguate the dual-line `Submitting <task>` / `Dryrun: would
    submit <task>` pattern. Preferred form:
    `Dryrun Mode: would submit <task>` as the single source of truth.
  - **R3** — Trivial merge conflict in `lib/workflowmgr/utilities.rb` from
    upstream PR #126.
  - **R4** — Caveat about feature framing: dryrun reports `y = f(x)` for the
    current state `x`; "validation" overstates what the feature does.

### 2.2 Local Branch Validated
- Branch: `feature/dryrun_nodaemon_final`
- HEAD before this phase: `304669d`
- HEAD after this phase (uncommitted log edits): `9424352` (merge) + 1
  pending commit for log semantics.

### 2.3 Files Reviewed / Touched
- `lib/workflowmgr/workflowengine.rb`
- `lib/workflowmgr/workflowreport.rb`
- `lib/workflowmgr/lsfbatchsystem.rb`
- `lib/workflowmgr/lsfcraybatchsystem.rb`
- `lib/workflowmgr/utilities.rb` (merge conflict only)
- `lib/workflowmgr/workflowoption.rb` (audit only — no change)
- `lib/workflowmgr/reportoption.rb` (audit only — no change)
- `lib/workflowmgr/workflowsubsetoptions.rb` (audit only — no change)

---

## 3. Comment-by-Comment Resolution

### 3.1 R1 — Startup banner
**Reviewer ask**: "Perhaps it is also worth alerting users that they are in
dryrun mode at other times as well? Something like
`Dryrun Mode: no new jobs would be submitted`."

**Implementation**: Added a one-line stdout banner at the top of
`WorkflowEngine#run` and `WorkflowEngine#boot` in `lib/workflowmgr/workflowengine.rb`,
guarded by `WorkflowMgr.dryrun_mode?`. Fires once per `rocotorun` /
`rocotoboot` invocation. Smoke tests confirm the banner appears for every
invocation in the `dryrun`, `status`, and `threads` cases.

### 3.2 R2 — Single-line workflow-log semantics
**Reviewer ask**:
> When a job is not submitted due to dryrun mode, logs indicate this like:
> ```
> Submitting foo_3
> Dryrun: would submit foo_3
> ```
> Consider modifying the dryrun log message slightly to emphasize that the
> job it said it was submitting did not actually get submitted… `Dryrun Mode:
> would submit foo_3`.

**Implementation** (two-part):

1. **Suppress the leading `"Submitting"` / `"Forcibly submitting"` workflow-log
   line in dryrun mode** — `lib/workflowmgr/workflowengine.rb` `submit_new_jobs`
   path and `boot` path. The per-job `Dryrun Mode: would submit …` line
   immediately below is now the single source of truth in the workflow log.
   Per-scheduler `WorkflowMgr.stderr("Submitting …", 4)` debug-verbose lines
   are deliberately retained — they fire only at verbosity level 4 and are not
   in the workflow log Chris was reading.
2. **Rename `Dryrun:` → `Dryrun Mode:`** at every emit site:
   - `lib/workflowmgr/workflowengine.rb` (boot job-result line + run job-result
     line — 2 sites).
   - `lib/workflowmgr/workflowreport.rb` (1 site).
   - `lib/workflowmgr/lsfbatchsystem.rb` (log + stderr — 2 strings).
   - `lib/workflowmgr/lsfcraybatchsystem.rb` (log + stderr — 2 strings).

Workflow log produced by smoke run after the change:
```
2026-04-20 20:22:52 +0000 :: <host> :: Dryrun Mode: would submit dryrun_task for cycle 202001010000
2026-04-20 20:22:52 +0000 :: <host> :: Dryrun Mode: would submit dryrun_task
```
No `Submitting …` line precedes the `Dryrun Mode: would submit …` line.

### 3.3 R3 — Upstream merge conflict
**Conflict location**: `lib/workflowmgr/utilities.rb` lines 8–29 (HEAD).
**Cause**: Upstream PR #126 removed the `RUBY_VERSION < "1.9.0"` /
`system_timer` fallback. Our branch had inserted the `DRYRUN` constant and
`self.dryrun_mode?` helper *immediately above* that block, so git could not
auto-merge the two adjacent edits.
**Resolution**: Keep the `DRYRUN` constant + `dryrun_mode?` helper from this
branch; adopt upstream's simplified `require 'timeout'` (drop the
`RUBY_VERSION` conditional and the `system_timer` branch entirely). No
residual `system_timer` references in the tree after the merge. Result:
GitHub reports `mergeable: MERGEABLE` (was `CONFLICTING`).

### 3.4 R4 — "Validation" wording
**Audit result**: The repository's user-facing dryrun help text in
`workflowoption.rb:80` and `reportoption.rb:78` already reads
`"Show Workflow Manager commands, but do not execute"` — neutral, no
"validate"/"pre-flight" claim. No README/TESTING.md mention of dryrun. The
only `validat*` hits in `lib/` are internal method names (`validate_opts`)
and pre-existing XML/cycledef validation comments, none of which describe
dryrun. **No code change required.**

The "validation" framing lives only in the GitHub PR #125 description body.
Suggested PR-description tweak (to be applied at push time):
- Replace "validate Rocoto workflow XML end-to-end" → "exercise full
  workflow parsing without committing to a real submission".
- Replace "safe pre-flight check" → "preview of the next state transition".
- Add Chris's caveat verbatim: *"dryrun reports the state transition
  `y = f(x)` for the current workflow state `x`. It is a preview of what the
  next `rocotorun` would do — not a general workflow-XML validator."*

---

## 4. Validation

### 4.1 Syntax
`ruby -c` clean on all 5 modified files
(`workflowengine.rb`, `workflowreport.rb`, `lsfbatchsystem.rb`,
`lsfcraybatchsystem.rb`, `utilities.rb`).

### 4.2 Smoke Tests (local EC2, Rocky 9, Ruby 3.2.3, Slurm 23.11.x)

Bootstrap (one-time):
```bash
module load ruby/3.2.3
cd supported_repos/rocoto
bundle config set --local path 'bundle'
bundle install --standalone --local
```

Results:

| Case      | Result | Notes |
|-----------|--------|-------|
| `dryrun`  | PASS   | both `BatchQueueServer=false` and `=true` paths |
| `status`  | PASS   | `rocotostat` / `rocotocheck` alongside dryrun  |
| `threads` | PASS   | thread pool sizes 1, 4, 8, 16 — no deadlocks   |

(`real` and `full` not run — they perform actual `sbatch` calls; out of scope
for this local close-out.)

### 4.3 Workflow-log inspection
Confirmed single-line `Dryrun Mode: would submit …` semantics in
`/tmp/.../log/workflow_<cycle>.log`. No leading `Submitting …` line.

---

## 5. Acceptance Criteria

- [x] Upstream `develop` merged; `mergeable: MERGEABLE` on GitHub.
- [x] Startup banner fires once per `rocotorun` / `rocotoboot` invocation in
      dryrun mode.
- [x] No `Submitting <task>` line in workflow log when `dryrun_mode?` is true.
- [x] All `Dryrun:` workflow-log strings renamed to `Dryrun Mode:`.
- [x] All modified files pass `ruby -c`.
- [x] Smoke tests `dryrun`, `status`, `threads` all PASS.
- [x] No remaining "validation" / "pre-flight" wording in Rocoto code or
      in-tree docs.

---

## 6. Out of Scope (deferred)

- PR #125 description rewording — to be done in the GitHub UI at push time.
- `real` / `full` smoke test cases — require live Slurm submission; not part
  of this no-side-effects local close-out.
- Smoke-harness README note that the new upstream `Gemfile` requires
  Ruby ≥ 3.2 + a populated `bundle/` (one-time bootstrap). Upstream-driven;
  belongs in a separate PR against upstream `develop`, not in this dryrun PR.
