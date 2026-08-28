# Task 4 — the nightly wrapper, and proving the harness slots in behind it

Implement **Task 4 (sub-tasks 4.1 and 4.2) from tasks.md.**

The harness is finished. This step connects it to the thing that runs nightly, and
tests the connection without waiting for nights.

## Files you own

- MODIFY `mcp_server_python/scripts/run_benchmark_nightly.sh`                     (4.1)
- NEW    `mcp_server_python/tests/unit/test_benchmark_wrapper_integration.py`     (4.2)

## 4.1 is a comment change, and that is the whole point

The threshold this feature settles on is **10 percent, relative, against the median
of the trailing 7 runs, with a strict `<` so a drop of exactly 10.00 percent
passes.** The comparison is at line 171:

```
if med > 0 and cur_v < med * (1 - pct / 100.0):
```

**The wrapper's default is already 10** (line 50). So there is no functional edit to
make. Your change is comment text only, and that is the strongest available reading
of the requirement that the wrapper differ from its pre-change form only in that
default and in comments.

Record in the header comment: that 10 is the threshold the final report names, that
it is relative against the 7-run median rather than an absolute point drop, and that
the corpus config's own numbers — 5 for a warning, 15 for critical — govern the
*Node* harness's separate in-process check and its exit code, and are untouched by
this feature.

That last clause matters. Reconciling the numbers means naming which one governs a
change to default-tenant output. It does not mean reaching inside the Node harness
and altering its gate.

**Change nothing else in this file.** The snapshot rotation, the per-category
regression check, and the structured error output all stay exactly as they are. 4.2
asserts this by comparing the comment-stripped content to its pre-change form, so an
accidental functional edit will show up as a test failure rather than a surprise
later.

## 4.2 — four groups of tests

New `mcp_server_python/tests/unit/test_benchmark_wrapper_integration.py`, marker
`unit`.

### Reading a log the wrapper produced, without a live log

`get_quality_metrics` reads its file from a state directory, and `utility.register`
takes that directory explicitly:

```
register(mcp, data=None, *, state_dir=None, server_version=None)
```

Precedence is the explicit argument, then `SDD_STATE_DIR`, then a default. So the
hermetic path needs no new production code:

1. Write a synthetic two-line log of Python-shaped records into a temp directory.
2. Register the utility module against **the same shim the harness uses**, with
   `state_dir` pointed at that directory.
3. Call the collected `get_quality_metrics` function with comparison off, then on.
4. Assert the overall block and all six category blocks render, that the comparison
   block appears when asked for, and that no placeholder like `Unknown` or `N/A`
   shows up for a field the record actually carries.

Reuse the harness's shim rather than importing the renderer directly. That way the
integration test and the harness cannot drift apart in how they reach a tool — if
the shim ever stops collecting correctly, this test fails too instead of quietly
testing a path nothing uses.

### One appended line, and this is the only subprocess test

Run the wrapper once, with the benchmark command pointed at the harness in
injected-data mode and both the results directory and the state directory redirected
under a temp path. Assert the log grew by **exactly one** line and that the line
parses as the record.

One invocation, not a sweep. Nothing varies with input here and every iteration
costs a subprocess.

### The log-history table, including a trap worth understanding

The regression check is an inline Python heredoc inside the wrapper, so you can
extract that block and drive it against synthetic logs. Four inputs:

| lines in log | what happens |
|---|---|
| 0 | reports insufficient history, exits 0, no error line |
| 1 | same |
| 2 | **outer guard passes and it reports ok — but no metric is actually evaluated** |
| 8 | live median over the trailing window |

**Row 3 is the trap.** Line 146 is `if len(rows) < 2:` which handles the first two
rows. But line 168 is a *per-metric* `if len(vals) < 2: continue`, so with exactly
two lines the check reports a status of ok while skipping every metric. "The check
reported ok" and "the gate is armed" are different statements on the second night
after a history reset, and someone citing the benchmark then would be citing
nothing.

Assert that explicitly and comment it. It is the kind of thing that reads as a
passing test until you look closely.

For the 8-line case, engineer the numbers so one input sits at **exactly** 10.00
percent below the median and one sits just below that. The first must pass and the
second must fire. That is what pins the strict `<` at line 171 — an off-by-one in
that operator would otherwise only ever show up in production.

Also worth knowing: line 181 is an unconditional `sys.exit(0)`, so a detected
regression writes a structured error line and changes no exit status. The wrapper
treats a poor score as a signal, not a failure.

### The wrapper is functionally unchanged

Compare the comment-stripped content of the wrapper to its pre-change form and
assert equality. Since 4.1 changes only comments, this should hold exactly.

Record how you strip comments, so the next reader knows what the assertion does and
does not cover.

## Context you may want

Rotation only fires above 90 retained runs (lines 49, 104-110) and the log holds 21,
so no code path reaches it. That matters later — the history reset this feature
needs is therefore a one-time manual step rather than something the wrapper does,
and the final report records the command. Nothing for you to build here; noted so
the rotation code's apparent inertness does not look like a defect.

The suite currently sits at **1843 passed, 4 failed, 0 skipped**. A fifth failure is
yours.

_Requirements: 5.5, 6.3, 7.1, 7.2, 7.3, 7.4, 7.5_
