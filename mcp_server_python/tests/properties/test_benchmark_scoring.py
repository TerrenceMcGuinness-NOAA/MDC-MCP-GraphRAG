"""Property tests for the benchmark scoring core.

Feature: default-tenant-freeze-retirement, Task 1.4.

Covers Property 5 (metric bounds, including the empty expectation) and
Property 6 (``mrr`` equals ``coverage`` at every aggregation). Both drive
``score_case`` and ``aggregate`` from ``scripts.run_benchmark`` over the
weighted ``case_shapes()`` generator, which reaches the ``expected_length``
corners -- ``0``, ``1``, exactly ``k``, and above ``k`` -- that a naive
implementation gets wrong.

Hermetic: no corpus, no closures, no backend. The synthetic
``(case, response)`` pairs are built in-process so a triple's match count is
exact.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from scripts.run_benchmark import BenchmarkCase, aggregate, score_case
from tests.properties.conftest import case_shapes

pytestmark = pytest.mark.property


def _make_case_and_response(
    matched_count: int, expected_length: int
) -> tuple[BenchmarkCase, str]:
    """Build a case whose scoring yields exactly ``matched_count`` matches.

    Expected entries are mutually non-overlapping tokens, so none is a
    substring of another; the response is the first ``matched_count`` of them
    joined by newlines. An unmatched entry therefore never appears as a
    substring of the response, making the realised match count exactly
    ``matched_count``.
    """
    expected = [f"EXPECTED-{i}-TOKEN" for i in range(expected_length)]
    response = "\n".join(expected[:matched_count])
    case = BenchmarkCase(
        id=f"synthetic_{matched_count}_{expected_length}",
        question="synthetic question",
        tool="search_documentation",
        tool_args={},
        expected_results=expected,
        expected_min_results=expected_length,
        category="operational",
        notes="",
        tenant_scoped=False,
    )
    return case, response


# Feature: default-tenant-freeze-retirement, Property 5: Metric bounds,
# including the empty expectation
@settings(max_examples=100, deadline=None)
@given(shape=case_shapes())
def test_p5_per_case_bounds_and_empty_expectation(
    shape: tuple[int, int, int],
) -> None:
    """Per-case metrics stay in ``[0, 1]``; an empty expectation scores 0.

    The above-``k`` corner exercises finding 5's precision clamp (a case
    with more matches than ``k`` would otherwise exceed 1); the zero corner
    exercises Requirement 4 criterion 6 (no ``ZeroDivisionError``, no
    ``nan``).
    """
    matched_count, expected_length, k = shape
    case, response = _make_case_and_response(matched_count, expected_length)
    result = score_case(case, response, k)

    # Realised match count is exactly the triple's matched_count.
    assert len(result.matched_results) == matched_count

    for value in (result.precision, result.recall, result.mrr):
        assert 0.0 <= value <= 1.0

    if expected_length == 0:
        assert result.precision == 0.0
        assert result.recall == 0.0


# Feature: default-tenant-freeze-retirement, Property 5: Metric bounds,
# including the empty expectation
@settings(max_examples=100, deadline=None)
@given(shapes=st.lists(case_shapes(), min_size=1, max_size=12))
def test_p5_aggregate_bounds(shapes: list[tuple[int, int, int]]) -> None:
    """Every aggregated quality metric stays in ``[0, 1]`` inclusive."""
    results = [
        score_case(*_make_case_and_response(m, n), k)
        for (m, n, k) in shapes
    ]
    scope = aggregate(results)
    for value in (
        scope.precision_at_k,
        scope.recall_at_k,
        scope.mrr,
        scope.coverage,
    ):
        assert 0.0 <= value <= 1.0
    assert scope.latency_p50_ms >= 0
    assert scope.latency_p95_ms >= 0


# Feature: default-tenant-freeze-retirement, Property 6: mrr equals coverage
# at every aggregation
#
# This is an identity, not a range, and is kept separate from Property 5
# because it carries a consequence a bounds property hides: a Python
# Tool_Closure returns a single response text, so per-case mrr is the covered
# flag (0 or 1). The aggregate mean of that flag is exactly coverage.
# Consequence: the Gated_Metric triple {mrr, precision_at_k, coverage} has
# RANK TWO -- the Regression_Check evaluates two independent signals
# ({coverage, precision_at_k}), not three. A reviewer counting three would
# overestimate the gate.
@settings(max_examples=100, deadline=None)
@given(shape=case_shapes())
def test_p6_per_case_mrr_is_the_covered_flag(
    shape: tuple[int, int, int],
) -> None:
    """Per-case ``mrr`` is ``1.0`` when anything matched, ``0.0`` otherwise."""
    matched_count, expected_length, k = shape
    case, response = _make_case_and_response(matched_count, expected_length)
    result = score_case(case, response, k)

    matched_any = matched_count > 0
    assert result.covered is matched_any
    assert result.mrr == (1.0 if matched_any else 0.0)


# Feature: default-tenant-freeze-retirement, Property 6: mrr equals coverage
# at every aggregation
@settings(max_examples=100, deadline=None)
@given(shapes=st.lists(case_shapes(), min_size=1, max_size=12))
def test_p6_aggregate_mrr_equals_coverage(
    shapes: list[tuple[int, int, int]],
) -> None:
    """Aggregate ``mrr`` equals aggregate ``coverage`` exactly."""
    results = [
        score_case(*_make_case_and_response(m, n), k)
        for (m, n, k) in shapes
    ]
    scope = aggregate(results)
    assert scope.mrr == scope.coverage
