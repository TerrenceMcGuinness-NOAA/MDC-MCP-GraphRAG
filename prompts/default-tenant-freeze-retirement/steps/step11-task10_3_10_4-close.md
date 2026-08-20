# Tasks 10.3 + 10.4 — assert the documents say it, and close the phase

Implement **sub-tasks 10.3 and 10.4 of Task 10 from tasks.md.** That is the whole step,
and it is the last one. Task 11 is a checkpoint, not work.

Step 10 wrote the Retirement_Record. This step asserts the record and the amended
specs actually contain what the requirements demand, then reconciles the suite.

Follow the task text clause by clause. This prompt carries what it cannot: a
contradiction in 10.4 that you must not implement as written, and the identification
trick that makes 10.3's history assertion tractable.

## Files you own

- NEW `mcp_server_python/tests/unit/test_freeze_retirement_records.py` (10.3)
- 10.4 writes **no file.** It is a verification action you run and report.

Nothing under `src/` changes. Neither sub-task is atomic.

The record to assert against is
`docs/reports/2026-08-19-default-tenant-freeze-retirement.md`, 383 lines, ASCII.

## 10.4 contradicts itself, and you must resolve it, not implement it

The task says run `cd mcp_server_python && python3.12 -m pytest -q`, assert the
failing set is exactly the four pre-existing failures, and assert skips remain zero.
**Those three cannot all hold.**

`pyproject.toml` sets `testpaths = ["tests"]`, so a bare `pytest -q` collects **2,191**
tests: 1,684 unit, 205 properties, 1 integration, and **301 parity**. The parity suite
is skip-guarded on `RUN_PARITY` and live-server availability. Without live servers
those skip, so bare `pytest -q` reports hundreds of skips and the zero-skip assertion
fails for reasons that have nothing to do with this feature.

Every prior step verified over `tests/unit tests/properties` — 1,889 collected, and
the scope R15.4's four-failure baseline was established against. **Use that scope.**
Report the deviation from the task text and the reason, and report the parity skip
count under the wider scope so the number is on record rather than hidden by a
narrower command.

This is worth understanding rather than just working around, because it confirms
something: 10.1's skip assertion is scoped to tests *this feature adds* that skip on
credentials or backend availability. A broader reading — no conditional skips anywhere
— would fail against 301 pre-existing parity skips that are entirely correct, since
you cannot run dual-server parity without two servers. The narrow scope is not a
loophole, it is the only coherent reading.

While you are there: the only conditional skip in any file this feature added is the
`bash`-availability skip in `test_benchmark_wrapper_integration.py`. That is a tool
axis, not credentials or backend, so it is out of 10.1's scope — and 10.4's zero-skip
assertion is what stops it being silent, because if `bash` ever went missing the count
would go to one and 10.4 would fail. Say this in your report; it belongs in the record
as a composition, so a later reader who finds that skip does not conclude the
no-skip claim was false.

## 10.3 — identify the commits by their replacement, not by the marker

R8.1, R8.2, and R8.3 constrain the *sequence of revisions*, so no sampled code state
demonstrates them. You walk history instead. The obvious approach is to search commits
for the supersession marker text — **do not.** Both supersessions carry the identical
marker, `Superseded 2026-08-19 by default-tenant-freeze-retirement`, so the marker
cannot tell you which criterion a commit amended.

Invert it. Each supersession has a distinctive replacement symbol in the test module:

- the R6.3 (reporting) commit introduces the structural comparison — `parse_structural`
  and `compare_structural`
- the R6.2 (query) commit introduces `addressed_set` and `check_hit_provenance`

Find the commit that added each symbol, then assert that same commit also added a
supersession marker to the Phase 79 `requirements.md`. That is unambiguous, and it is
the same claim read from the other end.

Verified values, so you do not have to rediscover them:

- reporting supersession: **`9d638d3`**
- query supersession: **`b623644`**
- `run_benchmark.py` first exists at **`f0dd4a9`**, which precedes both, satisfying R8.1
- phase base: **`c5b2ea7`**

Assert the ordering, not the literal hashes. A test pinned to hashes is worthless the
moment history is rewritten, which brings us to the reason the fallback matters.

## The working-tree fallback is not dead code

The task says do not reach for `pytest.skip` when no supersession commit exists, and
fall back to a working-tree equivalent: for each relaxed criterion present in the
Phase 79 requirements, assert its replacement check is also present in the test module.

Both commits exist right now, so that path looks unreachable. It is not. **If this
branch is squash-merged, every Phase 80 commit collapses into one** and the separation
R8.1 through R8.3 describe becomes unverifiable from history — the merged commit
contains the supersessions and their replacements simultaneously, which is not the same
evidence as having landed them together. The fallback is the path that will actually
run after merge. Write it as the primary contract and the history walk as the stronger
check available while the branch is intact. Both must be meaningful, and neither may
skip.

Same bind as 10.1: a history-dependent test that skips when git is unavailable
violates 10.3's own no-skip constraint. Fail loudly.

## What else 10.3 asserts

Per the task text: the record exists, is ASCII, and carries each element R5, R6, R8.4,
R8.5, R12, R13.5, R14, and R15.7 require, **one assertion per criterion naming that
criterion in its failure message** — so a failure says which clause is missing, not
that a document is short. Then the Phase 79 `requirements.md` amendments, the
`design.md` Property 8 restoration, and the `README.md` instrument status.

These are unit assertions. Nothing varies; one content check per clause is complete.
Do not reach for Hypothesis.

## A caution on writing assertions against a document you did not write

You are checking someone else's record against the requirements. Read the requirements
first and derive each assertion from the criterion, then check the record satisfies it.
Do not read the record and write assertions shaped to what it happens to say — that
produces a test which passes by construction and would not notice a missing clause.
If a required element is genuinely absent from the record, **report it rather than
weakening the assertion to fit.** That is the finding this sub-task exists to surface.

## Verification

Your new tests pass. Over `tests/unit tests/properties`, the failing node-id **set**
equals exactly R15.4's four — a set, not a count, because a count passes if one
pre-existing failure were fixed while a new one appeared, which is the substitution
R15.4 exists to catch. Skips zero. `pycodestyle` over every Python file this feature
added or modified, no finding (R15.6) — enumerate base-vs-disk as 10.1 did, filtered
to `.py`, since `run_benchmark_nightly.sh` was modified but is bash.
`git diff --stat mcp_server_python/src/` empty.

_Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 10.1, 10.2, 10.3, 10.4, 11.1, 11.4, 12.1,
12.2, 12.3, 13.2, 13.3, 13.6, 15.4, 15.6_
