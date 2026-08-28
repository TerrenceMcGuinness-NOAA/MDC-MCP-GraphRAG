# Tasks 10.1 + 10.2 — the no-runtime-change gate, and the Retirement_Record

Implement **sub-tasks 10.1 and 10.2 of Task 10 from tasks.md.** That is the whole
step. Tasks 10.3 and 10.4 are a separate step and are not yours.

The two freezes are retired. This step proves the retirement changed no runtime
behaviour, and writes the document that explains what replaced them.

The task text in tasks.md is detailed and you should follow it clause by clause. This
prompt carries only what the task text cannot: values verified against the tree this
session, and the places where following the instruction literally produces something
wrong.

## Files you own

- NEW `mcp_server_python/tests/unit/test_no_runtime_change.py` (10.1)
- NEW `docs/reports/2026-08-19-default-tenant-freeze-retirement.md` (10.2)

That filename is fixed, because the next step asserts against it.

10.1 and 10.2 are independent. Neither is atomic. Nothing under `src/` changes.

## 10.1 — three things the task text does not tell you

**The git assertion as written is weaker than the claim it stands for.** The task
says assert `git diff --stat mcp_server_python/src/` returns empty. That proves only
that nothing under `src/` is *uncommitted*. R15.3's claim is that this feature changed
nothing under `src/` at all, which is a statement about the whole phase, not the
working tree. Phase 80's base revision is **`c5b2ea7`** (the commit before
`8516da5 docs(sdd): Phase 80`). Assert the range as well as the working tree, so the
test says what the requirement means.

**This test cannot skip, and that bites itself.** 10.1 asserts that no test this
feature adds is conditionally skipped. A git-dependent test that skips when git is
unavailable violates the very assertion it is making. So do not reach for
`pytest.skip` when `git` or the revision will not resolve — fail loudly and treat it
as a broken environment. Naming this because the obvious defensive reflex here is
also the one thing the sub-task forbids.

**The registered markers are exactly `{property, parity, unit}`** in
`pyproject.toml`, and `--strict-markers` is already on. So the meta-test earns its
place only against a *well-intentioned new registration* — someone adding
`benchmark` or `slow` to that list and marking the harness tests with it. A typo is
already caught. Write the assertion for the case it actually defends against.

One more thing to say plainly rather than let a reader infer strength that is not
there: R15.1 and R15.3 are close to **vacuously true by construction**, because
`structural.py` and `addressing.py` were deliberately placed under `tests/` rather
than `src/`. Assert them anyway. They are what catches a future move into `src/`,
which is the only way they would ever fail. Say so in the docstring so nobody reads a
passing test as evidence of more than it is.

## 10.2 — the record

Follow the task text's section list. These are the values and the traps.

### The archive command is not a call to `rotate()`

`rotate()` fires only when the log exceeds `KEEP_RUNS`, which defaults to **90**,
against a log of **21 lines**. Invoking it archives nothing. The operator step is a
hand-run equivalent that archives the **whole** log and truncates it, reusing
`rotate()`'s own directory, filename pattern, and timestamp format:

- directory `${MCP_BENCHMARK_ARCHIVE_DIR:-${HOST_STATE_DIR}/benchmark-archive}`
- filename `quality_metrics_${stamp}.jsonl.gz`
- stamp `date -u +%Y%m%dT%H%M%SZ`
- compression `gzip -c`

Record it verbatim and say it is one-time and operator-run, and that R7.3 forbids
adding a code path to do it.

### Two sections that must be written as one consequence

The task lists the archive and the arming subtlety separately. Written separately
they understate what they jointly mean, so connect them:

after the archive the log is empty; run 1 leaves one line and the outer `len(rows) < 2`
guard blocks evaluation; run 2 leaves two lines, which satisfies the outer guard, so
the wrapper logs two lines and reports `status: ok` — while the per-metric
`len(vals) < 2` guard still means **no metric is evaluated**; run 3 is the first real
comparison.

So the gate is blind for the first two Python runs and *announces success* on the
second. State the arming date as the **third** run. A reader who takes `status: ok`
on run 2 as a passing gate has been misled by a true statement, which is the worst
kind, and it is the single most consequential sentence in the record.

### Where the record must admit a limit rather than round up

Three places. Each is a finding, not a gap to paper over.

- **Score comparability was not demonstrated.** Say what *was* established — the
  formulas agree, Property 7 establishes it over 1,260 per-case rows and 147
  aggregate scopes, and `mrr == coverage` holds in all 147 because a Python tool
  closure returns exactly one response text, making the identity a property of both
  harnesses rather than a coincidence of one. Then say comparability itself was not
  shown, because scores depend on store content and there is no live backend here.
  That is what triggers R5.4 and the archive.
- **The consumer audit is bounded.** The six in-repo files are enumerable and you
  must name each with the element it matches on. Out-of-repo consumers — Kiro
  sessions, CI pipelines, Tier B and Tier C wrappers — **cannot be enumerated from
  this repository.** Record that as a bounded finding, not a completed audit.
- **The calibration section is deliberately empty.** A named placeholder for each of
  the eight tenant cases (`cs_t01`, `ss_t01`, `ar_t01`, `ee_t01`, `op_t01`, `kb_t01`,
  `ki_t01`, `cl_t01`), and the instruction that the operator distinguishes an
  expected zero — `ar_t01`, pending Gap J — from a miscalibration.

### Two things a reviewer will otherwise overestimate

- **The gated metric triple has rank two.** `mrr` equals `coverage` by construction
  in both harnesses, so the check evaluates `{coverage, precision_at_k}`. Someone
  counting three independent signals overestimates the gate.
- **Query-tool output formatting is now ungated.** Carry step 9's recorded
  reduction into this document: neither replacement gates rendered bytes, so a
  relabelled field or changed separator passes both halves. This is the finding the
  consumer audit exists to bound, so put them near each other rather than in
  unrelated sections.

### One reconciliation that must not quietly change a gate

Naming 10 percent as governing does **not** retire the corpus values. 5 and 15 remain
in force for the Node harness's own check and exit code, against the previous single
run, via `run_benchmark.js::detectRegressions`. Three thresholds over two comparison
bases, and the record has to keep them distinct.

### Provenance and the four failures

The record names the revision baselines were captured from. Phase 80's base is
`c5b2ea7`; the two supersessions are the commits touching
`test_default_tenant_byte_equivalence.py`. State that a baseline recorded before a
default-tenant output change is void as a reference after it — which is exactly why
the follow-up sequence runs one at a time.

The four permanently-failing tests are pre-existing and named in R15.4. They are not
this feature's to fix and the record should not imply otherwise.

## Verification

The record is ASCII only: no emoji, no smart quotes, no en or em dashes. Your
new test passes. Suite
stays at **1876 passed, 4 failed, 0 skipped**, the four being R15.4's set. A fifth
failure is yours. `pycodestyle` clean on the new Python file.
`git diff --stat mcp_server_python/src/` empty.

_Requirements: 5.1, 5.2, 5.3, 5.4, 5.6, 6.1, 6.2, 6.4, 6.5, 6.6, 8.4, 8.5, 12.1,
12.2, 12.3, 12.4, 12.5, 13.5, 14.1, 14.2, 14.3, 14.4, 14.5, 15.1, 15.2, 15.3, 15.5,
15.7_
