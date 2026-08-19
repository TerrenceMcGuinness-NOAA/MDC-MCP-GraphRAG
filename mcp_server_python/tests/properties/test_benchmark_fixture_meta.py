"""Generator meta-tests for the benchmark shared generators (optional).

Feature: default-tenant-freeze-retirement, Task 1.6.

Defense-in-depth against future generator drift, not an acceptance
criterion -- Phase 79 marked its equivalent fixture meta-test the same way.
Asserts that ``case_shapes()`` actually reaches its four weighted corners
and that ``benchmark_cases()`` produces both scoped and unscoped cases and
at least one non-ASCII string, each within a bounded draw budget.

``hypothesis.find`` is the right instrument here: it searches the strategy's
space for one example satisfying a predicate within a bounded budget and
raises if none exists, so "the generator can reach corner X" is a direct,
deterministic assertion -- unlike a ``@given`` batch, whose first example is
deliberately degenerate.

The ``triple_perturbations()`` "exactly one mutation per pair" assertion
named in the task is intentionally NOT included here: it requires the
``StructuralView`` type built by step 6 (``tests/baselines/structural.py``),
which does not exist yet. Adding it now would either error at draw time (a
disallowed fifth failure) or require a conditional skip (forbidden by
R15.5). It belongs with step 6, where the type and this generator's first
consumer (Property 3) live.
"""

from __future__ import annotations

import pytest
from hypothesis import find

from tests.properties.conftest import benchmark_cases, case_shapes

pytestmark = pytest.mark.property


def _has_non_ascii(text: str) -> bool:
    return any(ord(ch) > 127 for ch in text)


# Feature: default-tenant-freeze-retirement, Task 1.6: case_shapes corners
def test_case_shapes_reaches_all_four_corners() -> None:
    """``case_shapes()`` can reach ``expected_length`` of 0, 1, ``k``, > k.

    The zero and above-``k`` corners are the load-bearing ones (Requirement
    4 criterion 6's empty expectation and finding 5's precision clamp); an
    unweighted generator would hit them too rarely for the consuming
    properties to exercise them. ``find`` raises if a corner is
    unreachable, which fails this test with a clear cause.
    """
    assert find(case_shapes(), lambda t: t[1] == 0)[1] == 0
    assert find(case_shapes(), lambda t: t[1] == 1)[1] == 1
    equal_k = find(case_shapes(), lambda t: t[1] == t[2])
    assert equal_k[1] == equal_k[2]
    above_k = find(case_shapes(), lambda t: t[1] > t[2])
    assert above_k[1] > above_k[2]
    # matched_count is always a reachable count for its expected_length.
    any_shape = find(case_shapes(), lambda t: True)
    assert 0 <= any_shape[0] <= any_shape[1]


# Feature: default-tenant-freeze-retirement, Task 1.6: benchmark_cases spread
def test_benchmark_cases_span_scope_and_non_ascii() -> None:
    """``benchmark_cases()`` reaches scoped, unscoped, and non-ASCII cases."""
    scoped = find(benchmark_cases(), lambda c: c.tenant_scoped)
    assert "tenant_id" in scoped.tool_args

    unscoped = find(benchmark_cases(), lambda c: not c.tenant_scoped)
    assert "tenant_id" not in unscoped.tool_args

    non_ascii = find(
        benchmark_cases(),
        lambda c: _has_non_ascii(c.question)
        or any(_has_non_ascii(entry) for entry in c.expected_results),
    )
    assert _has_non_ascii(non_ascii.question) or any(
        _has_non_ascii(entry) for entry in non_ascii.expected_results
    )
