"""Model-based formula parity against the committed metrics log.

Feature: default-tenant-freeze-retirement, Task 1.5 (Property 7).

The Node harness's committed output is the reference implementation. For
every per-case row in ``sdd_framework/execution_state/quality_metrics.jsonl``
this recomputes ``precision``, ``recall``, and ``mrr`` from
``(len(matched_results), len(expected_results), k=5)`` with the Python
``score_counts`` arithmetic and asserts exact equality with the recorded Node
value; for every aggregate scope it re-aggregates that run's cases with
``aggregate`` and asserts every recorded metric.

Sequenced immediately after the scoring core (Task 1.3) rather than at the
end: it needs no corpus, no closures, and no backend -- only ``score_counts``
and ``aggregate`` -- so it is the cheapest early check that the arithmetic is
right, and a formula error fails here before it can propagate through every
later task.

It does not subsume Property 5: the log is a fixed sample with no case whose
``expected_results`` is empty, so it cannot reach the corner that breaks a
naive implementation. The bounds property covers the input space; this one
covers agreement with the incumbent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.run_benchmark import CaseResult, aggregate, score_counts

pytestmark = pytest.mark.unit

#: The corpus ``metrics_config`` k for the recorded Node runs.
_K = 5

#: Verified sample sizes for the committed log. Asserted so a truncated or
#: rotated log degrades this test loudly rather than passing over a handful
#: of rows while looking green.
_EXPECTED_RUNS = 21
_EXPECTED_CASE_ROWS = 1260
_EXPECTED_SCOPES = 147

_REPO_ROOT = Path(__file__).resolve().parents[3]
_METRICS_LOG = (
    _REPO_ROOT / "sdd_framework" / "execution_state" / "quality_metrics.jsonl"
)
_CORPUS = (
    _REPO_ROOT
    / "mcp_server_node"
    / "test"
    / "benchmark"
    / "ground_truth.json"
)


def _load_runs() -> list[dict]:
    """Read every non-blank JSONL line of the committed metrics log."""
    with open(_METRICS_LOG, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _id_to_category() -> dict[str, str]:
    """Map each Corpus_Baseline_Set case id to its Benchmark_Category."""
    raw = json.loads(_CORPUS.read_text(encoding="utf-8"))
    mapping: dict[str, str] = {}
    for category, cases in raw["categories"].items():
        for case in cases:
            mapping[case["id"]] = category
    return mapping


def _case_result_from_row(row: dict) -> CaseResult:
    """Rebuild a ``CaseResult`` from one recorded per-case row.

    ``covered`` is recovered as ``len(matched_results) > 0`` (the recorded
    row does not carry the flag); the metric fields and ``latency_ms`` are
    taken verbatim so re-aggregation is over the values Node itself
    aggregated.
    """
    return CaseResult(
        id=row["id"],
        precision=row["precision"],
        recall=row["recall"],
        mrr=row["mrr"],
        covered=len(row["matched_results"]) > 0,
        matched_results=row["matched_results"],
        expected_results=row["expected_results"],
        latency_ms=row["latency_ms"],
    )


def test_metrics_log_sample_sizes() -> None:
    """The committed log has 21 runs, 1,260 case rows, and 147 scopes."""
    runs = _load_runs()
    assert len(runs) == _EXPECTED_RUNS
    assert sum(len(r["queries"]) for r in runs) == _EXPECTED_CASE_ROWS
    assert (
        sum(1 + len(r["categories"]) for r in runs) == _EXPECTED_SCOPES
    )


def test_per_case_formula_parity_with_node() -> None:
    """Every recorded per-case metric matches ``score_counts`` exactly."""
    runs = _load_runs()
    checked = 0
    for run in runs:
        for row in run["queries"]:
            matched = len(row["matched_results"])
            expected = len(row["expected_results"])
            precision, recall, mrr = score_counts(matched, expected, _K)
            assert precision == row["precision"], row["id"]
            assert recall == row["recall"], row["id"]
            assert mrr == row["mrr"], row["id"]
            checked += 1
    assert checked == _EXPECTED_CASE_ROWS


def test_aggregate_parity_with_node() -> None:
    """Re-aggregating each scope reproduces every recorded Node metric."""
    runs = _load_runs()
    id2cat = _id_to_category()
    scopes_checked = 0

    for run in runs:
        results = [_case_result_from_row(row) for row in run["queries"]]

        # Overall: all cases, in recorded order.
        _assert_scope_equal(aggregate(results), run["overall"])
        scopes_checked += 1

        # Per category: cases carrying that category, in recorded order.
        for category, recorded in run["categories"].items():
            cat_results = [
                r for r in results if id2cat[r.id] == category
            ]
            _assert_scope_equal(aggregate(cat_results), recorded)
            scopes_checked += 1

    assert scopes_checked == _EXPECTED_SCOPES


def _assert_scope_equal(computed, recorded: dict) -> None:
    """Assert a computed ``ScopeMetrics`` equals a recorded scope object."""
    assert computed.precision_at_k == recorded["precision_at_k"]
    assert computed.recall_at_k == recorded["recall_at_k"]
    assert computed.mrr == recorded["mrr"]
    assert computed.coverage == recorded["coverage"]
    assert computed.latency_p50_ms == recorded["latency_p50_ms"]
    assert computed.latency_p95_ms == recorded["latency_p95_ms"]


def test_r5_2_mrr_equals_coverage_empirically() -> None:
    """All 147 recorded scope observations report ``mrr == coverage``.

    The structural reason (a single response text makes per-case ``mrr`` the
    covered flag) is asserted as Property 6; this is the empirical half of
    Requirement 5 criterion 2 over the incumbent's own history.
    """
    runs = _load_runs()
    observed = 0
    for run in runs:
        for scope in [run["overall"], *run["categories"].values()]:
            assert scope["mrr"] == scope["coverage"]
            observed += 1
    assert observed == _EXPECTED_SCOPES
