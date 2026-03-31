# Phase 49: Rocoto Dryrun Thread Pool Guard

**Version**: 0.1.0  
**Status**: In Progress  
**Created**: 2026-03-31  
**Author**: GitHub Copilot (GPT-5.2-Codex) + Terry McGuinness  
**Primary Target Repo**: `supported_repos/rocoto` (`feature/dryrun_nodaemon`)  
**Related Phase**: Phase 47 (dryrun PR124 reconciliation)

---

## 1. Executive Summary

When `BatchQueueServer=false`, Rocoto uses an in-process thread pool for job submission. In dryrun mode, this still spawns pool threads and can deadlock when the engine joins all threads. The goal is to prevent thread pool creation during `--dryrun` while preserving job card output.

This is a baseline-safe change: no new dependencies, no scheduler behavior changes, and no Gaea-specific pool implementation changes.

---

## 2. Problem Statement

- Dryrun should not submit jobs, but it still spawns pool threads via `BQS#submit`.
- `Thread.list.join` (or equivalent) can deadlock because the pool workers never terminate in dryrun.
- Users still need job card output from batch system submitters during dryrun.

---

## 3. Proposed Design

### 3.1 Behavior Changes

1. **Short-circuit thread pool creation in dryrun** within `BQS#submit`:
   - Run `@batchsystem.submit(task)` synchronously to emit job card output.
   - Record `@status` and `@running` for the task and cycle.
   - Do not create a thread pool or spawn worker threads.

2. **Keep existing dryrun guards** in engine paths.
   - No changes to `BatchQueueServer` logic.
   - No changes to scheduler submitters beyond their current dryrun behavior.

### 3.2 Non-Goals

- No switch to `Concurrent::FixedThreadPool`.
- No changes to daemon startup/shutdown behavior.
- No change to non-dryrun submission flow.

---

## 4. Implementation Plan

### 4.1 Files to Modify

- `supported_repos/rocoto/lib/workflowmgr/bqs.rb`

### 4.2 Implementation Steps

1. In `BQS#submit`, initialize per-task hashes as today.
2. If `WorkflowMgr.dryrun_mode?`:
   - Set `@harvested[task][cycle]=false`.
   - Set `@running[task][cycle]=false`.
   - Assign `@status[task][cycle]=@batchsystem.submit(task)`.
   - Return without creating the pool.
3. Otherwise, fall through to current pool-based submission.

---

## 5. Acceptance Criteria

1. `rocotoboot -n` and `rocotorun -n` produce job card output without spawning pool threads.
2. No deadlock when `BatchQueueServer=false` and dryrun is enabled.
3. Non-dryrun behavior is unchanged.
4. `get_submit_status` still returns dryrun status for the job.

---

## 6. Validation Plan

1. Run dryrun on a minimal workflow with `BatchQueueServer=false`:
   - `rocotoboot -n -c <cycle> -t <task> -w <workflow> -d <db>`
2. Confirm:
   - Job card output appears.
   - No deadlock occurs.
   - No new warnings or errors.
3. Smoke test a non-dryrun submission path to ensure no regression.

---

## 7. Risks and Mitigations

- **Risk**: Divergent behavior between dryrun and non-dryrun submission logic.
  - **Mitigation**: Keep dryrun short-circuit limited to pool creation, reuse existing submit path for output.

- **Risk**: Status tracking mismatch in dryrun.
  - **Mitigation**: Explicitly set `@status`, `@running`, and `@harvested` in dryrun to mirror the normal flow.

---

## 8. Rollback Plan

Revert the changes in `lib/workflowmgr/bqs.rb` and restore the original pool-based submission path for all modes.

---

## 9. Execution Log

- 2026-03-31: Drafted spec and began implementation in `BQS#submit` to short-circuit pool creation during dryrun.
