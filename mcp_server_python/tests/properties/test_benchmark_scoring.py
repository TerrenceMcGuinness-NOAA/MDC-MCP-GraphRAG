"""Property tests for the benchmark scoring core.

Feature: default-tenant-freeze-retirement, Task 1.4, Task 3.4.

Covers Property 5 (metric bounds, including the empty expectation) and
Property 6 (``mrr`` equals ``coverage`` at every aggregation), both driving
``score_case`` and ``aggregate`` from ``scripts.run_benchmark`` over the
weighted ``case_shapes()`` generator, which reaches the ``expected_length``
corners -- ``0``, ``1``, exactly ``k``, and above ``k`` -- that a naive
implementation gets wrong.

Task 3.4 adds Property 4 (scoring determinism), Property 9 (selection and
scope partition), Property 10 (total accounting under failure), and
Property 14 (emitted artefact conformance). These four drive
``run_benchmark`` itself rather than the scoring core alone, and they do so
with a synthetic tool map -- ``build_tool_map`` is patched to return
closures built directly from the generated cases, independent of the real
``src.tools.*`` modules. That keeps them hermetic in the way that matters
for *this* file: real closure identity and real tenancy-ContextVar binding
are Property 12's job (``test_benchmark_hermetic.py``); this file's job is
the orchestration layer above the closure boundary -- selection, partition,
accounting, determinism, and artefact shape -- which does not need a real
tool to exercise.

Hermetic throughout: no corpus file, no network, no Bedrock, no real
``src.tools`` closure. The synthetic ``(case, response)`` pairs and the
synthetic tool maps are built in-process so every count is exact.
"""

from __future__ import annotations

import json
import tempfile
from typing import Any
from unittest.mock import patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import scripts.run_benchmark as run_benchmark_module
from scripts.run_benchmark import (
    CATEGORY_NAMES,
    BenchmarkCase,
    Corpus,
    aggregate,
    run_benchmark,
    score_case,
)
from src.config.tenants import load_catalog
from tests.properties.conftest import (
    _TENANTS_YAML,
    benchmark_cases,
    case_shapes,
)

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


# ---------------------------------------------------------------------------
# Task 3.4 -- Properties 4, 9, 10, 14 (run_benchmark orchestration)
# ---------------------------------------------------------------------------


def _corpus_of(cases: list[BenchmarkCase], version: str = "1.1.0") -> Corpus:
    """Build a minimal :class:`Corpus` around ``cases`` for these tests."""
    return Corpus(
        version=version,
        metrics_config={"k": 5},
        cases=tuple(cases),
        origins={c.id: (
            "tenant_categories" if c.tenant_scoped else "categories"
        ) for c in cases},
    )


def _sync_closure(
    case_id: str,
    responses: dict[str, str],
    raising: frozenset[str],
    tenant_probe: dict[str, str | None] | None,
):
    """Build one synthetic ``async def`` closure for ``case_id``.

    Returns the canned ``responses[case_id]`` text, raises when
    ``case_id`` is in ``raising``, and records the ``tenant_id`` keyword
    it was called with into ``tenant_probe`` when given -- a weaker
    stand-in for Property 12's real ContextVar assertion, adequate here
    because these four properties are about the orchestration layer
    above the closure boundary, not the binding itself.
    """

    async def _closure(**kwargs: Any) -> str:
        if tenant_probe is not None:
            tenant_probe[case_id] = kwargs.get("tenant_id")
        if case_id in raising:
            raise RuntimeError(f"synthetic failure for {case_id}")
        return responses.get(case_id, f"RESPONSE-FOR-{case_id}")

    return _closure


def _synthetic_tool_map_factory(
    responses: dict[str, str] | None = None,
    raising: frozenset[str] = frozenset(),
    tenant_probe: dict[str, str | None] | None = None,
):
    """Build a fake ``build_tool_map`` closing over canned responses.

    ``responses`` maps a case id to the response text its tool should
    "return" (default: a placeholder response, which will not cover any
    ``expected_results`` unless the caller supplied one that does).
    ``raising`` is a set of case ids whose closure raises instead of
    returning.

    The returned map is keyed by *case id*, not by a shared tool name --
    callers set ``case.tool == case.id`` on each synthetic case so each
    one gets its own dedicated closure and cross-case interference is
    impossible.
    """
    responses = responses or {}

    def _fake_build_tool_map(data, catalog, *, tool_names, state_dir):
        return {
            name: _sync_closure(name, responses, raising, tenant_probe)
            for name in tool_names
        }

    return _fake_build_tool_map


#: A real, cheap-to-load :class:`TenantCatalog` (bundled YAML, no I/O),
#: loaded once at import time. Not a fixture -- Hypothesis's
#: function-scoped-fixture health check flags any fixture used alongside
#: ``@given``, even a read-only one, so a plain module constant is used
#: instead. The catalog is immutable after load, so sharing one instance
#: across every generated example is safe.
_REAL_CATALOG = load_catalog(_TENANTS_YAML)


# Feature: default-tenant-freeze-retirement, Property 4: Scoring determinism
#
# Uses ``unittest.mock.patch`` as a context manager rather than the
# ``monkeypatch`` fixture: ``monkeypatch`` is function-scoped and Hypothesis
# reuses one test invocation's fixtures across every generated example,
# which is unsafe for a mutable patch. A context manager entered fresh
# inside the test body has no such lifetime mismatch.
@settings(max_examples=100, deadline=None)
@given(
    cases=st.lists(
        benchmark_cases(), min_size=1, max_size=8, unique_by=lambda c: c.id
    )
)
def test_p4_scoring_determinism(cases) -> None:
    """Two runs over identical inputs agree everywhere but timestamp/latency.

    No acceptance criterion states this directly -- every comparison the
    gate performs presupposes it. If two runs over identical inputs could
    differ in ``coverage``, a Regression_Check exceedance would be noise.
    """
    responses = {
        c.id: f"RESPONSE-FOR-{c.id} " + " ".join(c.expected_results)
        for c in cases
    }
    fake_map = _synthetic_tool_map_factory(responses=responses)

    corpus = _corpus_of(cases)
    with patch.object(run_benchmark_module, "build_tool_map", fake_map), \
            tempfile.TemporaryDirectory() as d1, \
            tempfile.TemporaryDirectory() as d2:
        run1 = run_benchmark(
            corpus, data=object(), catalog=_REAL_CATALOG, results_dir=d1
        )
        run2 = run_benchmark(
            corpus, data=object(), catalog=_REAL_CATALOG, results_dir=d2
        )

    ignore = {"timestamp"}
    rec1 = {k: v for k, v in run1.record.items() if k not in ignore}
    rec2 = {k: v for k, v in run2.record.items() if k not in ignore}

    # Per-case latency_ms is volatile; strip it from the queries[]
    # entries before comparing, along with the two derived latency
    # percentiles in every scope block.
    def _strip_latency(d: dict[str, Any]) -> dict[str, Any]:
        out = json.loads(json.dumps(d))
        for entry in out.get("queries", []):
            entry.pop("latency_ms", None)
        for scope_key in ("overall", "tenant_overall"):
            out.get(scope_key, {}).pop("latency_p50_ms", None)
            out.get(scope_key, {}).pop("latency_p95_ms", None)
        for scope_map_key in ("categories", "tenant_categories"):
            for scope in out.get(scope_map_key, {}).values():
                scope.pop("latency_p50_ms", None)
                scope.pop("latency_p95_ms", None)
        return out

    assert _strip_latency(rec1) == _strip_latency(rec2)


# Feature: default-tenant-freeze-retirement, Property 9: Case selection and
# scope partition
@settings(max_examples=100, deadline=None)
@given(
    default_cases=st.lists(
        benchmark_cases().filter(lambda c: not c.tenant_scoped),
        min_size=1, max_size=6, unique_by=lambda c: c.id,
    ),
    tenant_cases_a=st.lists(
        benchmark_cases().filter(lambda c: c.tenant_scoped),
        min_size=0, max_size=4,
    ),
    tenant_cases_b=st.lists(
        benchmark_cases().filter(lambda c: c.tenant_scoped),
        min_size=0, max_size=4,
    ),
)
def test_p9_selection_and_partition(
    default_cases, tenant_cases_a, tenant_cases_b
) -> None:
    """``--category`` selects exactly that category; tenant scores never
    move ``overall``/``categories``.

    Two runs share the same default-tenant cases but differ arbitrarily in
    their tenant-scoped cases (including in whether those cases' synthetic
    tools raise, so their scores differ too). ``overall`` and
    ``categories`` must be identical across both runs regardless.
    """
    # Re-id the tenant cases so the two runs' tenant sets do not collide
    # with each other or with the shared default set.
    def _reid(cases, suffix):
        out = []
        for i, c in enumerate(cases):
            new_id = f"{c.id}_{suffix}_{i}"
            out.append(BenchmarkCase(
                id=new_id,
                question=c.question,
                tool=new_id,
                tool_args=c.tool_args,
                expected_results=c.expected_results,
                expected_min_results=c.expected_min_results,
                category=c.category,
                notes=c.notes,
                tenant_scoped=True,
            ))
        return out

    tenant_a = _reid(tenant_cases_a, "a")
    tenant_b = _reid(tenant_cases_b, "b")

    default_retooled = [
        BenchmarkCase(
            id=c.id, question=c.question, tool=c.id, tool_args=c.tool_args,
            expected_results=c.expected_results,
            expected_min_results=c.expected_min_results,
            category=c.category, notes=c.notes, tenant_scoped=False,
        )
        for c in default_cases
    ]

    cases_a = default_retooled + tenant_a
    cases_b = default_retooled + tenant_b

    responses_a = {c.id: " ".join(c.expected_results) for c in cases_a}
    # Tenant cases in run B always fail; default cases match fully.
    responses_b = {
        c.id: " ".join(c.expected_results) for c in default_retooled
    }
    raising_b = frozenset(c.id for c in tenant_b)

    corpus_a = _corpus_of(cases_a)
    with patch.object(
        run_benchmark_module, "build_tool_map",
        _synthetic_tool_map_factory(responses=responses_a),
    ), tempfile.TemporaryDirectory() as d:
        run_a = run_benchmark(
            corpus_a, data=object(), catalog=_REAL_CATALOG, results_dir=d
        )

    corpus_b = _corpus_of(cases_b)
    with patch.object(
        run_benchmark_module, "build_tool_map",
        _synthetic_tool_map_factory(
            responses=responses_b, raising=raising_b
        ),
    ), tempfile.TemporaryDirectory() as d:
        run_b = run_benchmark(
            corpus_b, data=object(), catalog=_REAL_CATALOG, results_dir=d
        )

    assert run_a.record["overall"] == run_b.record["overall"]
    assert run_a.record["categories"] == run_b.record["categories"]
    assert set(run_a.record["categories"].keys()) == set(CATEGORY_NAMES)
    assert set(run_b.record["categories"].keys()) == set(CATEGORY_NAMES)

    # --category selects exactly the cases carrying that category.
    for cat in CATEGORY_NAMES:
        with patch.object(
            run_benchmark_module, "build_tool_map",
            _synthetic_tool_map_factory(responses=responses_a),
        ), tempfile.TemporaryDirectory() as d:
            run_cat = run_benchmark(
                _corpus_of(cases_a), data=object(), catalog=_REAL_CATALOG,
                category=cat, results_dir=d,
            )
        selected_ids = {q["id"] for q in run_cat.record["queries"]}
        expected_ids = {c.id for c in cases_a if c.category == cat}
        assert selected_ids == expected_ids


# Feature: default-tenant-freeze-retirement, Property 10: Total accounting
# under failure
@settings(max_examples=100, deadline=None)
@given(
    cases=st.lists(
        benchmark_cases(), min_size=1, max_size=10, unique_by=lambda c: c.id
    ),
    fail_mask=st.lists(st.booleans(), min_size=0, max_size=10),
    missing_mask=st.lists(st.booleans(), min_size=0, max_size=10),
)
def test_p10_total_accounting_under_failure(
    cases, fail_mask, missing_mask
) -> None:
    """Every selected case yields exactly one entry; failures never shrink
    the denominator; all-errored implies coverage 0 and exit signal.
    """
    retooled = [
        BenchmarkCase(
            id=c.id, question=c.question, tool=c.id, tool_args=c.tool_args,
            expected_results=c.expected_results,
            expected_min_results=c.expected_min_results,
            category=c.category, notes=c.notes, tenant_scoped=c.tenant_scoped,
        )
        for c in cases
    ]
    n = len(retooled)
    fail_mask = (fail_mask + [False] * n)[:n]
    missing_mask = (missing_mask + [False] * n)[:n]

    raising = frozenset(
        c.id for c, f in zip(retooled, fail_mask) if f
    )
    # A "missing" case is simply omitted from the synthetic tool map, so
    # build_tool_map's lookup misses and the harness records an
    # absent-tool error for it.
    present_ids = {
        c.id for c, m in zip(retooled, missing_mask) if not m
    }

    responses = {c.id: " ".join(c.expected_results) for c in retooled}

    def _fake_build_tool_map(data, catalog, *, tool_names, state_dir):
        return {
            name: _sync_closure(name, responses, raising, None)
            for name in tool_names
            if name in present_ids
        }

    corpus = _corpus_of(retooled)
    with patch.object(
        run_benchmark_module, "build_tool_map", _fake_build_tool_map
    ), tempfile.TemporaryDirectory() as d:
        run = run_benchmark(
            corpus, data=object(), catalog=_REAL_CATALOG, results_dir=d
        )

    # Exactly one entry per selected case.
    assert len(run.results) == n
    result_ids = {r.id for r in run.results}
    assert result_ids == {c.id for c in retooled}

    any_failed = False
    for result in run.results:
        should_fail = (
            result.id in raising or result.id not in present_ids
        )
        if should_fail:
            any_failed = True
            assert result.precision == 0.0
            assert result.recall == 0.0
            assert result.mrr == 0.0
            assert result.covered is False
            assert result.error is not None
            assert result.latency_ms >= 0
        else:
            # Every non-failing case is scored normally: fully covered,
            # since its response echoes every expected token.
            if result.expected_results:
                assert result.covered is True

    all_errored = all(
        (r.id in raising or r.id not in present_ids) for r in retooled
    )
    assert run.all_errored == all_errored
    if all_errored and any_failed:
        default_scope = run.record["overall"]
        tenant_scope = run.record["tenant_overall"]
        # Whichever scope actually holds cases must report zero coverage.
        default_ids = {c.id for c in retooled if not c.tenant_scoped}
        tenant_ids = {c.id for c in retooled if c.tenant_scoped}
        if default_ids:
            assert default_scope["coverage"] == 0.0
        if tenant_ids:
            assert tenant_scope["coverage"] == 0.0


# Feature: default-tenant-freeze-retirement, Property 14: Emitted artefact
# conformance
#
# ``capsys`` is a function-scoped fixture too, and Hypothesis flags any
# such fixture used with ``@given``. Suppressed deliberately here: the
# property only needs the console output produced *within this call* of
# the test body to be ASCII, and ``capsys.readouterr()`` drains its
# buffer on every call, so accumulation across examples sharing one
# fixture instance is not a hazard for what is being asserted.
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    cases=st.lists(
        benchmark_cases(), min_size=1, max_size=8, unique_by=lambda c: c.id
    )
)
def test_p14_artefact_conformance(
    cases, capsys
) -> None:
    """Every metric rounded to <=4 places, latencies are ints, harness and
    corpus_version present, and console output is ASCII even with
    non-ASCII case text.

    ``benchmark_cases()`` draws non-ASCII characters into ``question`` and
    ``expected_results`` for exactly this reason -- a case whose text
    carries one flows into an exception message when its (synthetic)
    tool raises, and that message must still print as ASCII-safe text
    wherever the harness echoes it.
    """
    retooled = [
        BenchmarkCase(
            id=c.id, question=c.question, tool=c.id, tool_args=c.tool_args,
            expected_results=c.expected_results,
            expected_min_results=c.expected_min_results,
            category=c.category, notes=c.notes, tenant_scoped=c.tenant_scoped,
        )
        for c in cases
    ]
    # Half the cases raise with a message containing their own (possibly
    # non-ASCII) question text, so the error field itself may carry
    # non-ASCII content; that content must never be blindly echoed to the
    # console as non-ASCII (the harness's own prints stay ASCII regardless
    # of what is embedded in a data field it does not print verbatim).
    raising = frozenset(c.id for i, c in enumerate(retooled) if i % 2 == 0)
    responses = {c.id: " ".join(c.expected_results) for c in retooled}

    corpus = _corpus_of(retooled)
    with patch.object(
        run_benchmark_module, "build_tool_map",
        _synthetic_tool_map_factory(responses=responses, raising=raising),
    ), tempfile.TemporaryDirectory() as d:
        run = run_benchmark(
            corpus, data=object(), catalog=_REAL_CATALOG, results_dir=d
        )

    record = run.record
    assert record["harness"]
    assert record["corpus_version"] == corpus.version

    for scope in (record["overall"], record["tenant_overall"]):
        for key in ("precision_at_k", "recall_at_k", "mrr", "coverage"):
            value = scope[key]
            assert round(value, 4) == value
        assert isinstance(scope["latency_p50_ms"], int)
        assert isinstance(scope["latency_p95_ms"], int)

    for scope_map in (record["categories"], record["tenant_categories"]):
        for scope in scope_map.values():
            for key in ("precision_at_k", "recall_at_k", "mrr", "coverage"):
                value = scope[key]
                assert round(value, 4) == value
            assert isinstance(scope["latency_p50_ms"], int)
            assert isinstance(scope["latency_p95_ms"], int)

    # The harness's own console output (captured here) stays ASCII, even
    # though the record itself may carry non-ASCII case data.
    captured = capsys.readouterr()
    (captured.out + captured.err).encode("ascii")
