# Rocoto `--dryrun` Mode: Side-Effect-Free Workflow Validation

**PR**: `feature/dryrun_nodaemon` → `develop`
**Repository**: [christopherwharrop/rocoto](https://github.com/christopherwharrop/rocoto)
**Author**: Terrence McGuinness ([@TerrenceMcGuinness-NOAA](https://github.com/TerrenceMcGuinness-NOAA))
**AI Assist**: Claude Opus 4.6 (Anthropic) via GitHub Copilot
**Rocoto Version**: 1.3.7
**Files Changed**: 21 (+730, -97)

---

## Summary

Adds a `--dryrun` (`-n`) flag to `rocotorun` and `rocotoboot` that performs full workflow parsing, cycle evaluation, task dependency resolution, and job card rendering — **without launching the daemon, submitting jobs, or touching the database state**. This enables operators and CI pipelines to validate Rocoto workflow XML end-to-end before committing to a real submission.

## Motivation

On NOAA HPC platforms (Hera, WCOSS2, Orion, Hercules, Gaea), a misconfigured Rocoto XML currently has no safe pre-flight check. The first indication of an error is a failed job submission or a corrupted workflow database. For production forecast systems like GFS/GEFS, this means:

- Wasted compute allocation from partial/failed submissions
- Manual database cleanup after aborted runs
- No CI-testable validation path for workflow XML changes

The `--dryrun` flag solves this by making Rocoto's full execution path observable and verifiable without side effects.

## What `--dryrun` Does

```
rocotorun -n -d workflow.db -w workflow.xml       # validate full run cycle
rocotoboot -n -d workflow.db -w workflow.xml -c CYCLE -t TASK   # validate boot
```

The `-n` flag is defined in `WorkflowOption` and inherited by `WorkflowSubsetOptions`, so it is parsed by all 5 subset commands: `rocotorun`, `rocotoboot`, `rocotocheck`, `rocotocomplete`, and `rocotorewind`. The primary use cases are `rocotorun` and `rocotoboot`; `rocotocomplete` and `rocotorewind` also benefit since they mutate state. `rocotocheck` is already read-only so `-n` is a no-op there. The smoke tests currently validate `rocotorun` and `rocotoboot` paths.

When `-n` (or `--dryrun`) is passed:

1. **Parses** the workflow XML (entities, metatasks, cycledefs)
2. **Evaluates** cycle/task dependencies and throttle constraints
3. **Resolves** `<cyclestr>` templates and metatask variable substitution
4. **Reports** which tasks *would* be submitted, with full job parameters
5. **Skips** daemon launch (no DRb server, no background process)
6. **Skips** batch queue submission (no `sbatch`/`qsub`/`bsub` calls)
7. **Skips** database state mutations (no cycle/task state changes)

## Changes by Component

### Core Dryrun Infrastructure

| File | Change |
|------|--------|
| `lib/workflowmgr/workflowoption.rb` | Add `--dryrun` / `-n` option parsing |
| `lib/workflowmgr/utilities.rb` | Add `WorkflowMgr.dryrun_mode` singleton accessor |
| `lib/workflowmgr/workflowengine.rb` | Guard submission, daemon launch, and DB writes behind `dryrun_mode` check |
| `sbin/rocotoserver` | Add `DRYRUN` constant so non-dryrun daemon still works |

### Batch Queue System Guards (All Schedulers)

Each scheduler's `submit` method returns `nil` (no-op) when `dryrun_mode` is true:

| File | Scheduler |
|------|-----------|
| `lib/workflowmgr/slurmbatchsystem.rb` | Slurm |
| `lib/workflowmgr/pbsprobatchsystem.rb` | PBS Pro |
| `lib/workflowmgr/torquebatchsystem.rb` | Torque |
| `lib/workflowmgr/moabbatchsystem.rb` | Moab |
| `lib/workflowmgr/lsfbatchsystem.rb` | LSF |
| `lib/workflowmgr/lsfcraybatchsystem.rb` | LSF (Cray) |
| `lib/workflowmgr/cobaltbatchsystem.rb` | Cobalt |

### Proxy / Daemon Layer Guards

| File | Change |
|------|--------|
| `lib/workflowmgr/bqs.rb` | Guard thread pool creation in `BatchQueueServer=true` mode |
| `lib/workflowmgr/bqsproxy.rb` | Skip DRb proxy connection in dryrun |
| `lib/workflowmgr/dbproxy.rb` | Skip database proxy in dryrun |
| `lib/workflowmgr/workflowioproxy.rb` | Skip workflow I/O proxy in dryrun |

### Thread Pool Deadlock Fix

The `bqs.rb` thread pool (`BatchQueueServer=true` path) previously launched worker threads that would block indefinitely in dryrun mode since no jobs were submitted. The fix guards thread pool creation behind `dryrun_mode`, preventing the deadlock while still exercising the full BQS code path up to the submit boundary.

### Reporting

| File | Change |
|------|--------|
| `lib/workflowmgr/workflowreport.rb` | Clean up report output formatting |
| `lib/workflowmgr/reportoption.rb` | Report option adjustments |
| `lib/workflowmgr/workflowsubsetoptions.rb` | Subset option fix |

### Test Harness

| File | Description |
|------|-------------|
| `test/rocoto_full_smoke.sh` | Dryrun smoke test exercising both `BatchQueueServer=false` and `BatchQueueServer=true` paths with inline workflow XML |
| `test/run_smoke.sh` | **New** — test runner with Slurm auto-detection, named test cases (`dryrun`, `status`, `real`, `full`, `threads`, `all`), interactive menu, header report showing build path vs system install, and per-test PASS/FAIL summary with elapsed time |
| `test/bin/test.ksh` | Changed shebang from `#!/bin/ksh` to `#!/bin/bash` (removes ksh dependency) |

## Test Results

All tests pass on Rocky 9 with Slurm 23.11.9, Ruby 3.0.7:

```
================================================================
  Rocoto Smoke Test Report
================================================================
  Date:       2026-04-02 15:15:52 UTC
  Host:       emcmcpawsrocky9-mgmt
  Branch:     feature/dryrun_nodaemon
  Rocoto:     1.3.7
  Build:      /path/to/rocoto/sbin
  System:     /apps/rocoto/1.3.7/bin/rocotorun
  Ruby:       3.0.7p220
  Slurm:      partition=emcmcpminicluster  account=root
  Test case:  all
================================================================

  [PASS]  dryrun
  [PASS]  status
  [PASS]  threads

  Tests:  3 passed, 0 failed, 3 total
  Time:   12s elapsed
  Result: OVERALL PASS
```

### Test Coverage

| Test Case | What It Validates |
|-----------|-------------------|
| `dryrun` | `BatchQueueServer=false` and `=true` paths with `-n` flag — no jobs submitted, no daemon, no DB mutations |
| `status` | `rocotostat -n` reports cycle/task state without side effects |
| `threads` | Thread pool guard under `BatchQueueServer=true` — verifies no deadlock |

## Commit History

| Commit | Description |
|--------|-------------|
| `738c28a` | test: add smoke test runner with PASS/FAIL reporting |
| `206fb09` | Fixed bqserver's DRYRUN constant so non-dryrun submit still works |
| `6c95a22` | Dryrun: avoid thread pool in BQS submit |
| `e989b70` | PR suggestions: hardening dryrun option state |
| `444f1ac` | Restored arg parsing for `--dryrun` |
| `37a8d6f` | Address PR review: make dryrun truly side-effect-free |
| `1866571` | Fix dryrun daemon/DRb handling per PR124 review |
| `abba59a` | Fix NameError crash in daemon: add DRYRUN constant to rocotoserver |
| `b99acfa` | Fix: prevent thread pool deadlock in `--dryrun` with `BatchQueueServer=false` |
| `9b42eb3` | Fix: guard `__drburi` calls with `dryrun_mode` check |
| `bdc88d2` | Fix: skip daemon launch in `--dryrun` mode |
| `b977798` | Moved `DRYRUN > 0` into utilities as `WorkflowMgr.dryrun_mode`; updated all schedulers |
| `5e18d70` | Initial dryrun implementation |

*Merge commits and intermediate fixes omitted for clarity. Full history: 37 commits.*

## Compatibility

- **No breaking changes** — the `-n` flag is additive; all existing behavior is unchanged when not passed
- **All 7 batch schedulers** updated (Slurm, PBS Pro, Torque, Moab, LSF, LSF Cray, Cobalt)
- **Ruby 2.7+** compatible (tested on 3.0.7)
- **No new gem dependencies**

## How to Test

```bash
cd test/
./run_smoke.sh          # interactive menu
./run_smoke.sh dryrun   # quick validation
./run_smoke.sh all      # full suite
```

Or manually:
```bash
ruby sbin/rocotorun.rb -n -d /tmp/test.db -w test/workflow.xml
```

## Why `DRYRUN` Is an Integer (Not a Boolean)

**Mirrors the `VERBOSE` convention.** In `workflowoption.rb`, `@verbose` is already an integer (`0`, `1`, `2+`) propagated via `const_set`. `DRYRUN` follows the same pattern for consistency.

**Environment variable safety.** In `utilities.rb`, `DRYRUN` is initialized from env vars via `.to_i`:
```ruby
DRYRUN = (ENV['WORKFLOWMGR_DRYRUN'] || ENV['DRYRUN'] || '0').to_i unless const_defined?(:DRYRUN)
```
If this were a Ruby boolean, the string `"0"` from the environment would be truthy — a subtle bug. The helper `dryrun_mode?` checks `DRYRUN.to_i > 0`, which works correctly with the integer representation.

**3-way CLI/env precedence.** The parse block uses `if @dryrun != 0` to distinguish: (1) CLI explicitly passed `-n` → override, (2) env var already loaded by `utilities.rb` → preserve, (3) neither → default to `0`. A boolean collapses cases 1 and 2, requiring an extra sentinel to tell them apart.

**Cross-process propagation.** The integer representation enables correct flow across process boundaries — parent process → forked DRb daemons (`rocotoserver`) — where the constant must be explicitly initialized to `0` in non-dryrun daemon processes to prevent `NameError`.
