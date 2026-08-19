# Task 1 — scoring core, shared generators, and the one-shot corpus digest

Implement **Task 1 (sub-tasks 1.1, 1.2, 1.3, 1.4, 1.5, and optional 1.6) from
tasks.md.**

Stage 1 foundations. Nothing here touches the corpus, the wrapper, or any freeze
criterion, so all 28 byte-equivalence tests stay in force throughout your step.

## Files you own

- MODIFY `mcp_server_python/tests/properties/conftest.py`                    (1.1)
- NEW    `mcp_server_python/tests/baselines/expected/corpus_categories_digest.json` (1.2)
- NEW    `mcp_server_python/scripts/run_benchmark.py`                        (1.3)
- NEW    `mcp_server_python/tests/properties/test_benchmark_scoring.py`      (1.4)
- NEW    `mcp_server_python/tests/unit/test_benchmark_node_parity.py`        (1.5)
- NEW    `mcp_server_python/tests/properties/test_benchmark_fixture_meta.py` (1.6, optional)

Do NOT modify `mcp_server_node/test/benchmark/ground_truth.json` — Task 2 owns
it, and see the ordering trap below. Do NOT modify the nightly wrapper, any file
under `src/`, or `tests/baselines/capture.py`.

## Do 1.2 FIRST, and understand why before you touch anything

**The corpus digest is one-shot in the same sense Phase 79's baselines were.** It
records the canonical-JSON digest of the Ground_Truth_Corpus `categories` object
*as it stands now*, at corpus `version` `1.0.0`, before Task 2 adds the
`tenant_categories` sibling container.

Recorded after that container lands, the digest certifies the post-change bytes
and Property 8's strongest clause becomes a tautology — it would prove that the
corpus equals itself. There is no way to recover the pre-change digest once the
file has moved, short of reading git history, and a digest sourced from history is
not obviously the one the test should pin.

So: compute and record it before you write anything else. Canonicalise with
`json.dumps(obj, sort_keys=True, separators=(",", ":"))` and record the algorithm
name alongside the digest so a future reader can recompute it without guessing.
Also pin the per-category case count (10 each) and the field values for all 60
Corpus_Baseline_Set cases.

Verified present state to pin against: six categories, 10 cases each, 13 distinct
tool names, corpus `version` `1.0.0`.

## 1.1 — the five generators, and why the weighting is load-bearing

Extend `tests/properties/conftest.py` alongside the existing Phase 79 set
(`logical_collections`, `tenants`, `prefixed_tenants`, `profiles`, `adapters`).
Do not duplicate those.

This lands in wave 0 because five later tasks consume it: 1.4, 3.4, 3.5, 6.2,
and 8.2.

- `case_shapes()` — `(matched_count, expected_length, k)` triples, **weighted** to
  include `expected_length` of 0, 1, exactly `k`, and above `k`. The zero draw is
  Requirement 4 criterion 6's input and must not be reached incidentally; an
  unweighted generator would hit it rarely and the property would pass while the
  corner was broken. The above-`k` draw exercises the precision clamp.
- `benchmark_cases()` — synthetic Benchmark_Cases over the corpus's 15 tool names,
  with `tenant_id` present or absent, and with **non-ASCII text in `question` and
  in `expected_results`** so Property 14's ASCII clause has something to catch.
- `structural_views()` — `StructuralView` values with generated collection names,
  counts **including `None`** for unprovisioned, and verdicts across
  `PASS`/`FAIL`/`SKIP`. The type does not exist until step 6 builds
  `structural.py`; define the generator against the shape design.md specifies and
  import lazily, or defer just this generator to step 6 and say so in your report.
- `render_perturbations()` — line permutation, heading rewrite, caption rewrite,
  whitespace expansion, and insertion of a line naming no collection, no count,
  and no verdict.
- `triple_perturbations()` — the dual: drop a collection, add a collection, change
  one count, flip one verdict. **Exactly one per generated pair**, because
  Property 3 asserts that exactly one finding names the perturbed element.

## 1.3 — the harness module, arithmetic only

New `mcp_server_python/scripts/run_benchmark.py`. **This sub-task lands the data
model and the pure arithmetic only** — no closure collection, no invocation, no
CLI. Those are step 3 and step 4.

Module docstring per the design: state that it mirrors
`mcp_server_node/scripts/run_benchmark.js` and name the three deliberate
differences — a Python Tool_Closure returns `str` so text extraction is the
identity; tenant cases come from `tenant_categories` and report separately;
`categories` is computed from Default_Tenant cases only.

`BenchmarkCase` frozen dataclass with the eight corpus fields plus
`tenant_scoped`, **derived** as `"tenant_id" in tool_args` rather than stored.
Deriving it makes the R2.8 partition a function of the case data, so a case filed
in the wrong container is still classified correctly.

`load_corpus(path)` reads both containers and tags each case with its origin.
Two asymmetric conditions, and the asymmetry is deliberate:

- **An absent `tenant_categories` is NOT an error** — treat it as empty so a
  corpus predating this feature still runs. That is what keeps the Node corpus and
  the Python harness independently versionable.
- **A present-but-malformed case IS an error**, exit 1, naming the case `id` and
  the field. Scoring an authoring mistake as zero buries it inside a
  plausible-looking number.

`score_case(case, response, k)`: case-insensitive substring match of each
`expected_results` entry; `precision = matched / min(k, len(expected))` clamped to
`[0, 1]`; `recall = matched / len(expected)` clamped; `mrr` as the reciprocal of
the 1-based position of the first response text containing a match, else 0.

**Empty `expected_results` yields `precision` 0 and `recall` 0** — not
`ZeroDivisionError`, not `nan`. `nan` serializes as invalid JSON and would take
the wrapper's normalisation step down with it.

`aggregate(results)`: means for `precision_at_k`, `recall_at_k`, `mrr`;
`coverage` as covered-count over case-count; integer `latency_p50_ms` and
`latency_p95_ms`. Round the four quality metrics to 4 places.

`expected_min_results` is carried for schema conformance and **read by neither
harness** — confirmed absent from `computeQueryMetrics`, `aggregateMetrics`, and
`detectRegressions`. Do not gate on it. A docstring line recording that it is
documentary is enough.

## 1.4 — P5 and P6, and the rank-two consequence

New `tests/properties/test_benchmark_scoring.py`, marker `property`, Hypothesis
at `max_examples=100`, `deadline=None`, each test tagged
`# Feature: default-tenant-freeze-retirement, Property N: <title>`.

- **Property 5 — metric bounds including the empty expectation.**
- **Property 6 — `mrr` equals `coverage` at every aggregation**, and per-case
  `mrr` is `1.0` when at least one entry matched, `0.0` otherwise.

Keep them separate. Property 6 is an identity, not a range, and it carries a
consequence a bounds property hides: **the Gated_Metric triple
`{mrr, precision_at_k, coverage}` has rank two, so the Regression_Check evaluates
two independent signals and not three.** Put that in a comment on the test. A
reviewer counting three would overestimate the gate, and this is the cheapest
place to prevent that.

## 1.5 — Property 7, sequenced here on purpose

New `tests/unit/test_benchmark_node_parity.py`, marker `unit`.

Model-based against the incumbent: for every per-case row in
`sdd_framework/execution_state/quality_metrics.jsonl`, recompute `precision`,
`recall`, and `mrr` from
`(len(matched_results), len(expected_results), k=5)` and assert exact equality
with the recorded Node value. For every aggregate scope — `overall` plus each of
the six `categories` — re-aggregate that run's cases and assert every recorded
`precision_at_k`, `recall_at_k`, `mrr`, `coverage`, `latency_p50_ms`, and
`latency_p95_ms`.

**Assert the sample sizes too: 21 runs, 1,260 per-case rows, 147 aggregate
scopes.** Without that, a truncated or rotated log degrades the test into passing
over three rows while looking green.

Also assert the R5.2 identity empirically: all 147 scope observations report
`mrr == coverage`.

**Why this is at wave 1 rather than the end:** it needs no corpus, no closures,
and no backend — only `score_case` and `aggregate` from 1.3. It is the cheapest
available check that the scoring arithmetic is right, and deferring it would let a
formula error propagate through every later task before anything caught it.

It does not subsume Property 5. The log is a fixed sample containing no case with
an empty `expected_results`, so it cannot reach the corner that breaks a naive
implementation.

## 1.6 — optional, and marked so deliberately

Generator meta-test asserting `case_shapes()` actually reaches its four weighted
corners within a bounded draw budget, `benchmark_cases()` produces both scoped and
unscoped cases plus at least one non-ASCII string, and `triple_perturbations()`
applies exactly one mutation per pair.

Defense-in-depth against future generator drift, not an acceptance criterion —
Phase 79 marked its equivalent fixture meta-test the same way. Skip it only if you
are out of room, and say so.

_Requirements: 1.1, 2.2, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 5.1, 5.2, 9.1, 9.2, 9.5_
