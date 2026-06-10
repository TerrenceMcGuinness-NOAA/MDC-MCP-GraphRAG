# Requirements Document

## Introduction

The `mcp_health_check` and `check_knowledge_integrity` tools each fail in a way
the v32 runtime exposed: `check_knowledge_integrity` raises
`can't subtract offset-naive and offset-aware datetimes` and
`mcp_health_check(functional=True)` reports `workflow_info` as **fail** when no
EFS workflow mount is present.

Both are small, narrowly-scoped tool-layer bugs unrelated to the multi-tenant
gap closure work. They share a single deploy, so they share one bugfix spec.

### Bug 1 — `check_knowledge_integrity` raises on tz-naive timestamps

**Bug condition C(X).** `check_knowledge_integrity` is invoked. The vector
store returns at least one document whose timestamp metadata is an ISO-8601
string without a timezone designator. Inside `_check_stale_embeddings`, the
helper `_parse_iso_ts` returns a tz-naive `datetime`. The comparison
`(now - mod_time).days` — where `now = datetime.now(timezone.utc)` is tz-aware
— raises `TypeError: can't subtract offset-naive and offset-aware datetimes`
and the entire integrity check fails.

### Bug 2 — `workflow_info` smoke probe fails on missing mount

**Bug condition C(X).** `mcp_health_check(functional=True)` is invoked. The
runtime's `MCP_WORKFLOW_ROOT` points at a path (`/mnt/workflow` on the
AgentCore microVM) that does not exist or contains neither `jobs/` nor
`dev/jobs/` under any candidate root. The `_smoke_workflow_info` probe raises
`RuntimeError`, and the functional-validation table reports `workflow_info` as
FAIL even though the absence of a workflow mount is a known, deliberate
Phase-0 deferral. The probe should report SKIP (like `github_tools` does on
missing `GITHUB_TOKEN`) so the health table distinguishes "broken" from
"not provisioned".

## Glossary

- **Tz_Aware_Datetime**: a `datetime` whose `tzinfo` attribute is not `None`.
- **Tz_Naive_Datetime**: a `datetime` whose `tzinfo` attribute is `None`.
- **ISO_Timestamp**: any string accepted by `datetime.fromisoformat` (with the
  one Python 3.10 nicety that a trailing `Z` is normalised to `+00:00` before
  parsing).
- **Stale_Check**: the `_check_stale_embeddings` function in
  `src/tools/semantic_search.py` that compares each embedded document's
  recorded modification time to either git-HEAD time or `STALE_EMBEDDING_DAYS`
  ago.
- **Iso_Parser**: the `_parse_iso_ts(raw) -> datetime | None` helper in
  `src/tools/semantic_search.py` that every datetime path (vector metadata,
  git `--format=%aI`) flows through.
- **Workflow_Mount**: the EFS-backed directory at `MCP_WORKFLOW_ROOT` that,
  when populated, contains either `jobs/` or `dev/jobs/`.
- **Smoke_Probe_Result**: the value a smoke-query function returns to the
  health-check harness — currently a `bool` (`True` = pass) with raise == fail.
- **Skip_Result**: a third smoke-probe outcome indicating the probe ran but its
  preconditions were not met (analogous to the `github_tools` "no token" path).

## Requirements

### Requirement 1: Iso_Parser returns Tz_Aware_Datetime or None

**User Story:** As a tool caller, I want every `datetime` returned by
`_parse_iso_ts` to be tz-aware (or `None`), so that downstream arithmetic
between it and `datetime.now(timezone.utc)` cannot raise a tz-mismatch
TypeError.

#### Acceptance Criteria

1. WHEN `_parse_iso_ts` is called with an ISO_Timestamp that includes a
   timezone designator, THE Iso_Parser SHALL return a Tz_Aware_Datetime
   preserving that designator's offset.
2. WHEN `_parse_iso_ts` is called with an ISO_Timestamp that omits any
   timezone designator, THE Iso_Parser SHALL return a Tz_Aware_Datetime whose
   `tzinfo` is UTC, treating the input as UTC by convention (every persisted
   timestamp in this codebase is stored as UTC).
3. WHEN `_parse_iso_ts` is called with `None`, a non-string value, an empty
   string, or a string that `datetime.fromisoformat` cannot parse, THE
   Iso_Parser SHALL return `None`, never a Tz_Naive_Datetime and never a
   raised exception.
4. THE Iso_Parser SHALL preserve the existing `Z` → `+00:00` normalisation so
   pre-Python-3.11 fromisoformat callers continue to succeed on Z-suffixed
   inputs.

### Requirement 2: Stale_Check tolerates mixed-source timestamps

**User Story:** As an operator, I want the integrity check to compare embedded-
document times to git-HEAD times without crashing on a tz mismatch from any
single document, so that one stray timestamp does not abort the whole check.

#### Acceptance Criteria

1. WHEN Stale_Check subtracts `mod_time` from `now` for any document in the
   sample, THE arithmetic SHALL succeed for every Tz_Aware_Datetime that
   `_parse_iso_ts` returns under Requirement 1.
2. IF a sample document yields a `mod_time` that is somehow still tz-naive
   (for example because `_parse_iso_ts` is bypassed in the future), THEN
   Stale_Check SHALL skip that document and continue with the next one rather
   than abort the entire check.
3. WHEN Stale_Check completes, THE return value SHALL remain a `_Check` whose
   `passed` flag and `details` string match the existing contract (no signature
   change).

### Requirement 3: Workflow_info probe degrades to Skip_Result when mount absent

**User Story:** As an operator running a healthy runtime without the EFS
Workflow_Mount populated, I want the `workflow_info` functional probe to
report SKIP (not FAIL), so that the health table accurately distinguishes
"broken" from "not provisioned".

#### Acceptance Criteria

1. WHEN `_smoke_workflow_info` resolves a `workflow_root` whose parent
   directory does not exist on the runtime filesystem, THE probe SHALL return
   a Skip_Result with a clear reason (e.g. `"workflow_root=<path> not
   mounted"`), not raise.
2. WHEN `_smoke_workflow_info` resolves a `workflow_root` that exists but
   contains neither `jobs/` nor `dev/jobs/`, THE probe SHALL return a
   Skip_Result with a clear reason (e.g. `"workflow_root=<path> contains
   neither jobs/ nor dev/jobs/"`), not raise.
3. WHEN `_smoke_workflow_info` resolves a `workflow_root` that contains
   `jobs/` or `dev/jobs/`, THE probe SHALL pass exactly as it does today (no
   behaviour change for the populated case).
4. THE health-check harness SHALL render a Skip_Result row with status SKIP
   (not FAIL) and SHALL NOT count Skip_Results toward the failure tally in
   the summary line.
5. THE Skip_Result SHALL be carried through the JSON snapshot persisted to
   `health_history.jsonl` so a downstream trend tool can distinguish skips
   from failures.

### Requirement 4: Other probes' SKIP path remains the model

**User Story:** As a maintainer, I want the `workflow_info` SKIP behaviour to
match the existing `github_tools` SKIP path, so that the health-check harness
has one consistent skip mechanism, not two.

#### Acceptance Criteria

1. THE Skip_Result mechanism `_smoke_workflow_info` uses SHALL be the same
   mechanism `github_tools` uses to report SKIP when no `GITHUB_TOKEN` is set
   (whatever its current shape — sentinel return, exception subclass, or
   tuple), so the harness has a single skip code path.
2. IF the existing `github_tools` SKIP path is not a clean reusable mechanism,
   THEN this spec SHALL refactor it into one and apply it uniformly.

### Requirement 5: No new warnings, no behaviour change for healthy paths

**User Story:** As a maintainer, I want the bugfixes to be invisible on a
fully-provisioned runtime, so that the only observable change is on the broken
paths the bugs exposed.

#### Acceptance Criteria

1. WHEN every probe in the functional-validation table is run against a fully-
   provisioned runtime (mount present, token set, all data layers reachable),
   THE summary SHALL report the same `N/N passed, 0 failed, 0 skipped` line as
   it would today (apart from any other unrelated probes).
2. THE fixes SHALL NOT introduce any new dependency, configuration knob, or
   environment variable.
3. THE fixes SHALL NOT alter any unrelated tool's behaviour.

### Requirement 6: Regression tests (Fix-Checking property)

**User Story:** As a maintainer, I want explicit regression tests for both
bugs so they cannot return silently in a future change.

#### Acceptance Criteria

1. THE bugfix SHALL include a unit test that fails on the unfixed code and
   passes on the fixed code for `_parse_iso_ts` over a tz-naive input
   (Bug 1's bug-condition exploration test).
2. THE bugfix SHALL include a unit test for `_check_stale_embeddings` that
   exercises the tz-naive metadata path and asserts no exception, with the
   `_Check` returned having a sensible `passed`/`details` outcome.
3. THE bugfix SHALL include a unit test for `_smoke_workflow_info` that
   exercises the missing-mount and missing-jobs cases and asserts a
   Skip_Result, plus the existing-mount case still passing (Bug 2's
   bug-condition exploration test).
4. THE bugfix SHALL include a unit test that the health-check harness
   summarises SKIPs separately from failures and does not count them as
   failures in the exit code.
