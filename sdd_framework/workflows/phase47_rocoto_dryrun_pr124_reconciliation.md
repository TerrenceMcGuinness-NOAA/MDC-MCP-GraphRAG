# Phase 47: Rocoto Dryrun PR #124 Comment Reconciliation and Hardening

**Version**: 1.0.0  
**Status**: Implemented  
**Created**: 2026-03-27  
**Author**: GitHub Copilot (GPT-5.3-Codex) + Terry McGuinness  
**Primary Target Repo**: `supported_repos/rocoto` (`feature/dryrun_nodaemon`)  
**Upstream Review Context**: PR #124 (`feature/dryrun_nodaemon` → `develop`)

---

## 1. Executive Summary

This phase reconciles all review feedback on PR #124 for restoring and hardening Rocoto dryrun mode.  
The review contains **7 inline comments** and **1 suppressed low-confidence suggestion** from Copilot review metadata.

Current assessment: **all 8 suggestions are valid** against the current branch state and warrant implementation.

Primary defects cluster into three areas:
1. **Proxy rescue cleanup mismatch**: dryrun skips daemon launch, but rescue still calls `stop!` on in-process objects.
2. **Submission result classification mismatch**: dryrun outputs are mis-routed into failure paths due to `output.nil?` assumptions.
3. **WorkflowReport DRb assumptions**: dryrun paths still call `__drburi` and `stop!` under daemon-only assumptions.

---

## 2. Source-of-Truth Inputs

### 2.1 GitHub Review Corpus
- PR URL: `https://github.com/christopherwharrop/rocoto/pull/124`
- Inline review comments: 7
- Review summaries: 1
- Suppressed low-confidence findings in summary: 1

### 2.2 Local Branch Validated
- Branch: `feature/dryrun_nodaemon`
- HEAD commit at analysis time: `abba59a`

### 2.3 Files Reviewed for Validity
- `lib/workflowmgr/bqsproxy.rb`
- `lib/workflowmgr/dbproxy.rb`
- `lib/workflowmgr/workflowioproxy.rb`
- `lib/workflowmgr/workflowengine.rb`
- `lib/workflowmgr/workflowreport.rb`
- `lib/workflowmgr/slurmbatchsystem.rb`
- `lib/workflowmgr/bqs.rb`

---

## 3. Comment-by-Comment Validity and Follow-Up Affirmations

## 3.1 Inline Comment C1 — `bqsproxy.rb` rescue `stop!`
**Reviewer concern**: in dryrun, `@bqServer` is in-process `BQS`, but rescue still executes `@bqServer.stop!` under `@config.BatchQueueServer`.  
**Validity**: **Valid**. Current rescue cleanup condition does not mirror daemon launch condition.  
**Risk**: masks original exception with `NoMethodError` during rescue.

**Follow-up affirmation text**:
> Confirmed and accepted. In dryrun, `BQSProxy` assigns in-process `BQS`, so rescue cleanup must not unconditionally call `stop!`. We will align rescue shutdown conditions with daemon launch (`BatchQueueServer && !dryrun_mode?`) and add method-safety guarding as a defensive fallback.

## 3.2 Inline Comment C2 — `dbproxy.rb` rescue `stop!`
**Reviewer concern**: dryrun leaves `@dbServer` as in-process DB object; rescue still calls `stop!` when `DatabaseServer` is true.  
**Validity**: **Valid**.  
**Risk**: rescue-time masking of original failure.

**Follow-up affirmation text**:
> Confirmed and accepted. We will update `DBProxy` rescue cleanup to match daemon-start conditions in dryrun-aware form and avoid calling `stop!` on non-daemon instances.

## 3.3 Inline Comment C3 — `workflowioproxy.rb` rescue `stop!`
**Reviewer concern**: dryrun keeps in-process `WorkflowIO`, but rescue still calls `stop!` whenever `WorkflowIOServer` is enabled.  
**Validity**: **Valid**.  
**Risk**: exception masking during failure handling.

**Follow-up affirmation text**:
> Confirmed and accepted. `WorkflowIOProxy` rescue cleanup will be guarded with the same dryrun-aware daemon condition used for launch and method-safe shutdown checks.

## 3.4 Inline Comment C4 — `workflowengine.rb` dryrun under `if output.nil?`
**Reviewer concern**: dryrun from batch systems usually returns `[nil, "This is a dryrun"]`, so dryrun logic inside `if output.nil?` is not reached.  
**Validity**: **Valid**. Verified behavior contract in `BQS#get_submit_status` and submission branches.  
**Risk**: dryrun execution falls into `jobid.nil?` failure logic.

**Follow-up affirmation text**:
> Confirmed and accepted. Dryrun is currently classified by `output.nil?` in places where dryrun output is non-nil. We will introduce explicit dryrun-first classification (`WorkflowMgr.dryrun_mode?` and standardized dryrun output handling) before failure branching.

## 3.5 Inline Comment C5 — `workflowengine.rb` nil jobid treated as failure in dryrun
**Reviewer concern**: dryrun intentionally yields nil jobid, but code logs submission failure and emits stderr.  
**Validity**: **Valid**.  
**Risk**: false-negative operational signals and noisy logs.

**Follow-up affirmation text**:
> Confirmed and accepted. We will add explicit dryrun success-semantic handling so `nil jobid` in dryrun is not logged or surfaced as failure.

## 3.6 Inline Comment C6 — `workflowengine.rb` duplicate bug in `submit_new_jobs` path
**Reviewer concern**: same `output.nil?`/`jobid.nil?` classification flaw exists in later submission flow.  
**Validity**: **Valid**.  
**Risk**: inconsistent dryrun behavior between boot and regular submission paths.

**Follow-up affirmation text**:
> Confirmed and accepted. We will normalize submission result handling across both boot and regular submission paths with shared dryrun classification semantics.

## 3.7 Inline Comment C7 — `workflowreport.rb` DRb URI and shutdown assumptions
**Reviewer concern**: dryrun paths still use `__drburi` and `stop!` and bqserver registration logic assuming daemon-backed objects.  
**Validity**: **Valid**.  
**Risk**: `NoMethodError` in `rocotostat -n` and report-mode dryrun paths.

**Follow-up affirmation text**:
> Confirmed and accepted. `WorkflowReport` will receive the same dryrun guards already introduced in engine code for DRb URI access, bqserver registration, and daemon shutdown.

## 3.8 Suppressed Suggestion S1 — `slurmbatchsystem.rb` warning emitted on dryrun
**Reviewer concern**: dryrun sets output string then falls into generic failure warning branch.  
**Validity**: **Valid** (despite low-confidence suppression).  
**Risk**: dryrun appears as scheduler submission failure.

**Follow-up affirmation text**:
> Confirmed and accepted. Even though this was low-confidence in the review summary, the branch behavior is reproducible. We will add an explicit dryrun return path in `slurmbatchsystem.submit()` to prevent false failure warnings.

---

## 4. Root-Cause Analysis

1. **Daemon/in-process mode duality is not consistently encoded in shutdown paths**.
2. **Dryrun semantics are represented as output strings, but control flow still assumes nil output semantics for pending states**.
3. **Engine and report components diverged in dryrun hardening; report path lags behind engine path**.
4. **Batch system adapters are only partially dryrun-normalized; Slurm retains failure-style fallback for dryrun output**.

---

## 5. Technical Design and Remediation Plan

## 5.1 Design Principle A: Mirror Launch and Cleanup Conditions
For proxy classes (`BQSProxy`, `DBProxy`, `WorkflowIOProxy`), rescue cleanup of server daemons must be gated by the exact daemon-launch predicate:

`config.<ServerFlag> && !WorkflowMgr.dryrun_mode?`

Add method-safety fallback where appropriate:
- `server.respond_to?(:stop!)`

## 5.2 Design Principle B: Introduce Dryrun-First Submission Classification
In engine/report submission-harvest paths, classify outcomes in this precedence:
1. `dryrun?` (explicit mode and/or normalized dryrun marker)
2. `pending?` (`output.nil?`)
3. `failure?` (`jobid.nil?` in non-dryrun)
4. `success?` (jobid present)

## 5.3 Design Principle C: Normalize `WorkflowReport` with Engine Guards
Apply explicit dryrun guards for:
- `@bqServer.__drburi` reads
- DB `add_bqservers/delete_bqservers` operations tied to daemon URIs
- daemon `stop!` calls in `ensure`
- any logic that assumes DRb-backed job IDs when dryrun mode is active

## 5.4 Design Principle D: Dryrun Must Not Emit Failure Warnings
Batchsystem submit methods should return dryrun state without warning text that implies scheduler failure.

---

## 6. Implementation Scope

## 6.1 Files to Modify
- `supported_repos/rocoto/lib/workflowmgr/bqsproxy.rb`
- `supported_repos/rocoto/lib/workflowmgr/dbproxy.rb`
- `supported_repos/rocoto/lib/workflowmgr/workflowioproxy.rb`
- `supported_repos/rocoto/lib/workflowmgr/workflowengine.rb`
- `supported_repos/rocoto/lib/workflowmgr/workflowreport.rb`
- `supported_repos/rocoto/lib/workflowmgr/slurmbatchsystem.rb`

## 6.2 Optional Refactor (if low risk)
- Introduce a small helper utility in `utilities.rb` for submission outcome classification to avoid duplicated branch logic between engine/report.

---

## 7. Acceptance Criteria

1. No rescue path in proxy classes can call `stop!` on in-process objects during dryrun.
2. Dryrun submissions in engine/report are not logged as failures solely due to nil jobid.
3. `rocotostat -n` and report-mode dryrun do not invoke `__drburi`/`stop!` on non-daemon instances.
4. Slurm dryrun path does not emit `job submission failed` warning.
5. Non-dryrun behavior remains unchanged for true failure and success cases.

---

## 8. Validation Plan

## 8.1 Static Validation
- Ruby syntax check for all touched files (`ruby -c`).
- Grep audit for `__drburi` and `stop!` usage lacking dryrun guard in report/engine/proxies.

## 8.2 Functional Validation (targeted)
- Run dryrun workflows for `rocotorun -n` and `rocotostat -n` on representative test XML.
- Confirm no false submission failure logs in dryrun mode.
- Confirm no `NoMethodError` from `stop!` or `__drburi` in dryrun paths.

## 8.3 Regression Validation
- Run non-dryrun submission path smoke test (single small workflow).
- Ensure genuine scheduler submission failures still log and surface as errors.

---

## 9. Risk Assessment

### 9.1 Primary Risks
- Over-guarding may suppress legitimate cleanup in daemon mode.
- Dryrun classification changes could accidentally alter pending behavior.

### 9.2 Mitigations
- Preserve daemon-mode branches unchanged except for precise condition alignment.
- Keep dryrun-first logic explicit and narrowly scoped.
- Add targeted tests for all four submission outcomes: dryrun, pending, failure, success.

---

## 10. SDD Execution Steps (ISD-compatible)

1. Capture PR comments and map each to code region and symbol.
2. Implement proxy rescue condition alignment.
3. Implement engine boot submission classification fix.
4. Implement engine regular submission classification fix.
5. Apply report-mode dryrun DRb/cleanup guards.
6. Add Slurm dryrun explicit return branch.
7. Run syntax and targeted dryrun/non-dryrun validation.
8. Document behavioral deltas and close PR review threads with affirmation responses.

---

## 11. Completion Definition

This phase is complete when:
- All 8 reviewed suggestions are either implemented or explicitly dispositioned with rationale (expected: all implemented).
- Dryrun mode no longer emits false submission failures.
- Dryrun report path is free of daemon-only method calls.
- Validation evidence is recorded and PR comments are responded to with affirmative closure notes.
