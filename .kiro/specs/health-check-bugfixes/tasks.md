# Implementation Plan — `health-check-bugfixes`

## Overview

Two narrowly-scoped tool-layer bug fixes that share one runtime image and one
deploy. Bug 1: tz-naive datetime in `_parse_iso_ts` crashes
`check_knowledge_integrity`. Bug 2: `_smoke_workflow_info` raises on a missing
EFS mount when it should SKIP (matching the `github_tools` no-token path).
Total production change is small (~10 lines + harness wiring), but each bug has
an explicit Bug-Condition exploration test that must fail on the unfixed code
and pass on the fixed code (the Bugfix Workflow contract).

Delivered in five waves: investigation of the existing SKIP mechanism, then the
two fixes in parallel, then their tests, then CHANGELOG, then the gated deploy.

## Tasks

- [ ] 1. Investigate the existing `github_tools` SKIP mechanism
  - Read `src/tools/smoke_queries.py` (and the harness in `mcp_server.py` /
    wherever the functional-validation table is rendered) to identify the
    exact mechanism `_smoke_github_tools` uses to report SKIP when
    `GITHUB_TOKEN` is unset (sentinel return value, exception subclass,
    tuple, or dataclass).
  - Document the mechanism in a one-paragraph note that the Bug 2 fix
    (Task 4) will reuse verbatim. If no clean mechanism exists today
    (i.e. github_tools only happens to work because it's a different code
    path), capture that and design one — see Task 4 for the refactor.
  - _Requirements: 4.1, 4.2_

- [ ] 2. Bug 1 fix — `_parse_iso_ts` UTC fallback
  - In `src/tools/semantic_search.py`, modify `_parse_iso_ts` to return a
    tz-aware datetime: parse the ISO string, then if the result's `tzinfo`
    is `None`, set it to `timezone.utc` via `dt.replace(tzinfo=timezone.utc)`.
    Treat empty / non-string inputs as `None` (already the case; preserve).
  - In `_check_stale_embeddings`, add the per-document defensive guard:
    `if mod_time is None or mod_time.tzinfo is None: continue` so a future
    bypass cannot reach the subtraction.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3_

  - [ ]* 2.1 Bug 1 unit + bug-condition exploration tests
    - Parametrised tests for `_parse_iso_ts` over: tz-aware (`+00:00`, `+05:30`,
      `Z`), tz-naive (`2026-06-10T22:30:00`), `None`, empty, garbage.
    - `_check_stale_embeddings` test with mocked metadata mixing tz-naive and
      tz-aware timestamps → returns a `_Check`, no TypeError.
    - Bug-condition exploration test (Bugfix Workflow): a single test that
      raises `TypeError: can't subtract offset-naive and offset-aware datetimes`
      on the unfixed code (using a fixture with tz-naive metadata and a
      `_check_stale_embeddings` invocation) and passes on the fixed code.
      Confirm both directions before checking it in.
    - File: `mcp_server_python/tests/unit/test_semantic_search_integrity.py`
      (extend or new — match the existing project convention).
    - _Validates: 1.1, 1.2, 1.3, 2.1, 2.2, 6.1, 6.2_

- [ ] 3. Define / adopt the SmokeResult three-state shape
  - Based on Task 1's findings, either:
    (a) reuse the existing SKIP mechanism unchanged for both probes, or
    (b) introduce a small, named result type — preferred shape: a `dataclass`
        union (`SmokePass`, `SmokeSkip(reason: str)`, with `RuntimeError` still
        meaning fail) — and refactor `_smoke_github_tools` to use it.
  - Keep the change to the harness rendering minimal: one new `SKIP` row state
    in the table and one new `skipped` counter in the summary line.
  - _Requirements: 3.4, 3.5, 4.1, 4.2_

  - [ ]* 3.1 Harness rendering tests
    - Test that a list of mixed `[Pass, Pass, Skip(reason="x"), Pass, Fail]`
      renders one SKIP row with the reason and one FAIL row, summary line
      `3/5 passed, 1 failed, 1 skipped`.
    - Test that the persisted `health_history.jsonl` snapshot includes
      `passed`, `failed`, and `skipped` integer counts (R3.5).
    - File: extend the existing harness test file (locate via the existing
      `test_health_check` or `test_smoke_queries` in `tests/unit/`).
    - _Validates: 3.4, 3.5_

- [ ] 4. Bug 2 fix — `_smoke_workflow_info` returns Skip_Result
  - Change `_smoke_workflow_info` to return a `SmokeSkip` (per Task 3's shape)
    when (a) the resolved `workflow_root` does not exist, or (b) it exists but
    contains neither `jobs/` nor `dev/jobs/`. Replace the `RuntimeError` raise
    with the skip return.
  - Preserve the existing pass behaviour for populated mounts byte-for-byte
    (R3.3, R5.1).
  - _Requirements: 3.1, 3.2, 3.3_

  - [ ]* 4.1 Bug 2 unit + bug-condition exploration tests
    - `_smoke_workflow_info` over a `pyfakefs` filesystem:
      - Empty tmp_path workflow_root → returns SKIP with the documented reason.
      - `tmp_path / "jobs"` exists → PASS.
      - `tmp_path / "dev" / "jobs"` exists → PASS.
      - Non-existent path → SKIP with "not mounted" reason.
    - Bug-condition exploration test (Bugfix Workflow): asserts the probe
      `RuntimeError` is raised on the unfixed code (with a
      missing-path fixture) and that the fixed code returns SKIP without
      raising. Confirm both directions before checking it in.
    - File: extend `tests/unit/test_smoke_queries.py`.
    - _Validates: 3.1, 3.2, 3.3, 6.3, 6.4_

- [ ] 5. CHANGELOG and full-suite gate
  - CHANGELOG entry under a new version header (latest on the branch is
    [8.36.0]; use [8.36.1] since this is a small bugfix).
  - `cd mcp_server_python && python3.12 -m pytest tests/unit/ tests/properties/ -q`
    must be green; report the count vs the current 1315 baseline (expect
    +6–10 from the new tests).
  - `python3.12 -m py_compile src/tools/semantic_search.py src/tools/smoke_queries.py`
    clean.
  - _Requirements: 5.1, 5.2, 5.3, 6.1, 6.2, 6.3, 6.4_

- [ ] 6. Phase A — gated build + deploy + live validation
  - STOP-AND-CONFIRM before ECR push and `update-agent-runtime` (AWS write-safety).
  - Build the image (`python-tenants-v9`), push, cut runtime v32 → v33.
    Carry the full lossless deploy payload (env vars, VPC subnets, SG, EFS
    access point, MMDSv2/S3-endpoint flags) — same shape as the v32 deploy.
  - Live validation:
    - `mcp_health_check(deep=True, functional=True)` — `workflow_info` row now
      reads SKIP, summary reads `9/10 passed, 0 failed, 1 skipped` (or
      `10/10 passed, 0 failed, 0 skipped` if the EFS mount is restored
      between now and the deploy).
    - `check_knowledge_integrity()` — completes without the
      "offset-naive and offset-aware" error and renders its sub-checks.
    - All other probes unchanged.
  - Record the runtime version + image tag in the gap tracker / CHANGELOG.
    Rollback target: `python-tenants-v8` (v32).
  - _Requirements: 3.4, 3.5, 5.1 (live)_

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2", "2.1", "3", "3.1"] },
    { "id": 2, "tasks": ["4", "4.1"] },
    { "id": 3, "tasks": ["5"] },
    { "id": 4, "tasks": ["6"] }
  ]
}
```

Wave 0 is the read-only investigation of how `github_tools` currently signals
SKIP — the answer determines the shape of Task 3 and therefore Task 4. Wave 1
runs the Bug 1 fix and the SmokeResult shape definition in parallel (independent
files). Wave 2 applies the SmokeResult shape to `_smoke_workflow_info`. Wave 3
is the CHANGELOG + suite gate. Wave 4 is the gated build/deploy/live validation.

## Notes

- **Bug-Condition Exploration tests are the contract.** Both 2.1 and 4.1
  require a test that **fails** on the unfixed code and **passes** on the
  fixed code, demonstrated before commit. This is the workspace's Bugfix
  Workflow standard (see `rollback-cli-real-adapters` and
  `ingest-dedupe-and-graph-fix` for the same pattern).
- **No PBT.** Both bugs have small, finite input domains fully covered by
  parametrised unit tests. Hypothesis would not add coverage here.
- **The SKIP rendering is a small harness change.** The summary line goes from
  `9/10 passed, 1 failed` to `9/10 passed, 0 failed, 1 skipped`. That single
  formatting change is the only externally-visible difference for already-
  healthy probes.
- **No environment variable changes, no infra changes.** This deploy carries
  exactly the same env vars, VPC config, and EFS access point as v32 — only
  the image tag changes.
- **Deploy is required.** Same path as Gaps C/D/E/G. Operator-gated at Task 6.
