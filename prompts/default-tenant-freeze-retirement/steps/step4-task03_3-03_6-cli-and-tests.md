# Task 3.3-3.6 — the command line, and the tests for everything step 3 built

Implement **sub-tasks 3.3, 3.4, 3.5, and 3.6 of Task 3 from tasks.md.**

Step 3 landed the working harness but no entry point and no tests. You add both.

## Files you own

- MODIFY `mcp_server_python/scripts/run_benchmark.py`                    (3.3 only)
- MODIFY `mcp_server_python/tests/properties/test_benchmark_scoring.py`  (3.4)
- NEW    `mcp_server_python/tests/properties/test_benchmark_hermetic.py` (3.5)
- NEW    `mcp_server_python/tests/unit/test_benchmark_harness.py`        (3.6)
- MODIFY `mcp_server_python/tests/baselines/capture.py`                  (3.5, additive only)

`test_benchmark_scoring.py` already exists — step 1 put Properties 5 and 6 there.
Add to it; do not rewrite it.

Your only production change is adding `main()`. Do not otherwise alter what step 3
built. If a test fails, the first question is whether your test is right.

## What already exists, so you test real names

Landed in `scripts/run_benchmark.py`:

```
classes    CorpusError  BenchmarkCase  CaseResult  ScopeMetrics  Corpus
           _ToolShim  BenchmarkRun
public     score_counts  score_case  aggregate  load_corpus
           build_tool_map  run_benchmark
constants  CATEGORY_NAMES  CORPUS_TOOL_NAMES  HARNESS_VERSION
           _MODULE_TOOLS  _TOOL_TO_MODULE  _TENANT_SCOPED_MODULES
internals  _run_benchmark_async  _invoke_case  _select_cases  _build_record
           _resolve_results_dir  _write_record  _detect_regressions
           _js_round  _round4  _clamp01  _percentile
```

`run_benchmark` is synchronous and drives its own event loop; `_run_benchmark_async`
is the async core. There is no `main()` — that is yours.

Generators in `tests/properties/conftest.py` from step 1: `case_shapes`,
`benchmark_cases`, `render_perturbations`, plus `structural_views` and
`triple_perturbations`, which lazily import a type step 6 has not built yet. **Do
not draw the last two** — nothing in your step needs them and they will fail.

## 3.3 — the command line

Add `main(argv=None) -> int`.

- `--dry-run` — validate the corpus, print the per-category plan and the tool names
  required, invoke nothing, write nothing, exit 0.
- `--category NAME` — run only that category's cases. An unknown value prints a
  message **naming all six** valid names and exits 1. A valid but empty category is
  a warning plus a record reporting zero coverage over zero cases, exit 0 — nothing
  failed, which is a different situation from everything failing.
- `--tenant-only` / `--default-only` — include only if they cost nothing.

Exit codes, and the asymmetry behind them:

| situation | exit | record written |
|---|---|---|
| normal run, any score | 0 | yes |
| some cases errored | 0 | yes |
| **every** case errored | 1 | **yes**, zero coverage |
| unknown `--category` | 1 | no |
| corpus missing or malformed | 1 | no |
| catalog fails to load | 1 | no |
| `--dry-run` | 0 | no |

The all-errored row looks self-contradictory and is not. The nightly wrapper logs a
non-zero exit as a warning and **carries on**, but logs a missing result file as an
error and **stops**. So writing the record means one failure produces one signal,
and a backend outage becomes a visible zero-coverage line in the history rather
than a gap in it. Four of the 21 recorded runs are exactly that, which is what let
the threshold analysis account for them.

All console output ASCII, prefixed `[OK]` / `[WARN]` / `[ERROR]`.

## 3.4 — four properties, added to the existing file

Hypothesis, `deadline=None`, at least 100 examples, each tagged
`# Feature: default-tenant-freeze-retirement, Property N: <title>`.

**Property 4 — determinism.** Two runs over the same cases and the same injected
data layer produce records equal everywhere except the timestamp, the per-case
elapsed times, and the two derived latency figures.

No requirement states this outright. It is here because every comparison the gate
performs assumes it. If two identical runs can differ in coverage, then a
regression alert is noise and the threshold is calibrated against nothing.

**Property 9 — selection and partition.** `--category` runs exactly the cases
carrying that category. And for any two runs sharing their default-tenant cases but
differing arbitrarily in their tenant cases *and in those cases' scores*, the
overall and per-category figures are identical, with exactly the six category names
as keys.

That second half is what makes step 2's deliberately-failing case safe. Without it
that zero would drag down the number a gate reads for unrelated changes.

**Property 10 — total accounting.** For any mix of cases naming missing tools and
cases that raise: exactly one entry per selected case, every failed entry carrying
zeros, an elapsed time, and an error naming the cause, every other case scored
normally, and the run completing. At the boundary where all of them error, coverage
is zero and the exit code is 1.

The invariant is the denominator. A run that dropped a failing case would average
over a smaller set and report a better score for a worse system.

**Property 14 — artifact shape.** Every figure rounded to at most four places, both
latency values integers, the record carrying a harness identifier and a corpus
version matching the loaded file, and every string written to the console encoding
to ASCII.

The ASCII half is a property rather than a smoke check because it varies with input:
a case whose text carries a non-ASCII character, or an exception whose message
does, flows straight to a console line. Step 1's `benchmark_cases` generator draws
non-ASCII into both for this reason.

## 3.5 — hermeticity, closure binding, and the token check

**Property 11 — hermeticity.** Under a socket guard that raises on connect and a
filesystem guard that raises on write outside the results directory, a run with an
injected data layer attempts no connection, builds no Bedrock client, and writes
nothing stray.

The no-traffic guarantee is structural first — step 3 confirmed the real builder is
never entered when a layer is injected. This is the backstop for something
constructed incidentally at import time or per case. The write half matters
separately: the harness hands a scratch directory to two modules for their state,
and a path bug there would write into the repository.

**Property 12 — closure collection and tenant binding.** For any subset of the tool
names the cases use, `build_tool_map` returns a mapping including every one, each
value being the same function object the module registered. And for any
tenant-scoped case, the tenant active inside the running function is the one the
case named.

That second half is the only way to confirm the harness reaches tenancy the way a
real caller does rather than the way a test double would.

### The token check, and the correction you need before writing it

The design's negative half for Property 12 was originally worded as "contains no
`_tool_` and no `run_tenant_scoped` token". **As a substring search that cannot
pass**, because `build_tool_map` — the mandated function name — contains `_tool_`
inside it. The design was amended for this; read the amendment note under
Property 12 before writing the assertion.

Measured against the landed file:

```
raw substring "_tool_"           4 matches, ALL of them build_tool_map
boundary-anchored \b_tool_       0 matches
call-shaped (^|[^A-Za-z0-9])_tool_[a-z]   0 matches
"run_tenant_scoped"              0 occurrences
"DB_BACKEND"                     0 occurrences
```

Use the boundary-anchored or call-shaped form. In `build_tool_map` the underscore
follows a word character, so no word boundary exists there and the anchored pattern
correctly ignores it. Write the assertion so it expresses the real invariant — that
no internal implementation is *called* — and put a comment saying why a substring
search would be wrong, so nobody simplifies it back later.

Also assert no backend-selection variable is read.

### Extending the stub, additively

`tests/baselines/capture.py` already has `_StubDataAccess`, `_StubVectorDB`, and
`_StubGraphDB`, the last dispatching on a cypher-substring `fragments` override.
Supply fragments for the graph shapes the cases reach — call graphs, dependency
edges, traversal chains — rather than adding new dispatch logic.

**Reuse that stub instead of writing a second one.** Its recorded responses are the
same frozen content the comparison baselines are built from, so a benchmark test and
a baseline test that disagree are disagreeing about rendering, not about data. Two
stubs would lose that.

Additive changes only. Do not alter existing recorded behaviour — other tests depend
on it.

## 3.6 — the failure tables as unit tests

New `tests/unit/test_benchmark_harness.py`, marker `unit`. Fixed inputs, no
generators.

Corpus and selection: file missing; not valid JSON, with the message naming the path
and the decoder's position; the case container absent or not an object; **an absent
tenant container is not an error** and the run scores default cases only; a case
missing a required field errors naming the case and the field; unknown category
lists all six and exits 1; valid-but-empty category warns and writes a zero-coverage
record at exit 0.

The last two rows point opposite ways deliberately. An absent tenant container means
a corpus predating this work, which must still run — that is what keeps the two
corpora independently versionable. A malformed case is a mistake someone just made,
and scoring it zero would bury it inside a plausible number.

Each command-line mode's observable: dry run writes nothing and invokes nothing; the
all-errored path writes a record *and* exits 1; a scored run with a bad score exits
0.

All four per-case failure shapes, including an unknown tenant name in a case's
arguments surfacing as **one bad case** rather than a run-wide failure.

Runs with no credentials and nothing reachable.

## One thing to expect

The suite currently sits at 1812 passed, 4 failed, 0 skipped. Your tests will raise
the passed count. If you see a fifth failure, it is yours — with one exception
worth knowing: `test_write_path_frozen.py` guards the scripts directory by digest,
and `run_benchmark.py` is explicitly excluded from that guard. If a write-path test
fails after you add `main()`, read that exclusion before assuming you broke
something.

_Requirements: 1.6, 1.7, 1.8, 1.9, 1.10, 2.7, 2.8, 2.9, 3.1, 3.2, 3.3, 3.4, 3.6, 3.7, 4.7, 4.8, 4.9, 4.10_
