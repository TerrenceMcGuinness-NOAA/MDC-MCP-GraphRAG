"""Property tests for the GGSR traversal engine.

Feature: python-mcp-server-port
Property 9: GGSR Scoring Correctness (Requirement 6.6)

For any set of graph traversal results where each result has a
relationship type from ``WEIGHT_MATRIX`` and a hop distance ≥ 1, the
scoring function SHALL compute each result's score as
``WEIGHT_MATRIX[relationship] × HOP_DECAY^hop_distance``, sort results
by score descending, and trim the list so total estimated tokens do
not exceed the specified token budget.
"""

from __future__ import annotations

import math
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.graphrag.ggsr_traversal import (
    DEFAULT_WEIGHT,
    HOP_DECAY,
    WEIGHT_MATRIX,
    GGSRTraversal,
    estimate_row_tokens,
)

pytestmark = pytest.mark.property


# ── Hypothesis strategies ────────────────────────────────────────────────


# Relationship types the engine knows about. Property 9 explicitly says
# the set is drawn from WEIGHT_MATRIX, so we draw from its keys.
_KNOWN_RELATIONSHIPS = st.sampled_from(sorted(WEIGHT_MATRIX.keys()))

# A relationship type *not* in WEIGHT_MATRIX exercises the DEFAULT_WEIGHT
# fallback path and is kept separate so the "known-only" property can
# assert exact scores without flakiness.
_UNKNOWN_RELATIONSHIPS = st.sampled_from(["UNHEARD_OF", "FOO_BAR", "RANDOM_EDGE"])

_HOPS = st.integers(min_value=1, max_value=2)
_NAMES = st.text(
    alphabet=st.characters(
        min_codepoint=0x20,
        max_codepoint=0x7E,
        blacklist_characters="|`\n\r",
    ),
    min_size=1,
    max_size=40,
)


def _record(name: str, rel: str, hop: int) -> dict[str, Any]:
    """Shape of a raw graph row fed to ``_score_results``."""
    return {"name": name, "relationship": rel, "hop_distance": hop}


_KNOWN_RECORDS = st.lists(
    st.builds(_record, _NAMES, _KNOWN_RELATIONSHIPS, _HOPS),
    min_size=0,
    max_size=30,
)

_MIXED_RECORDS = st.lists(
    st.builds(
        _record,
        _NAMES,
        st.one_of(_KNOWN_RELATIONSHIPS, _UNKNOWN_RELATIONSHIPS),
        _HOPS,
    ),
    min_size=0,
    max_size=30,
)

_BUDGETS = st.integers(min_value=0, max_value=10_000)


# ── fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture()
def engine() -> GGSRTraversal:
    """The scoring / trim helpers don't touch the graph, so ``None`` works.

    We only exercise ``_score_results`` / ``_trim_to_budget``; the
    graph_db handle is never accessed on those paths.
    """
    return GGSRTraversal(graph_db=None)  # type: ignore[arg-type]


# ── Property 9a: exact score formula for known relationship types ───────


@settings(
    max_examples=150,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(records=_KNOWN_RECORDS)
def test_score_matches_weight_times_decay(
    records: list[dict[str, Any]], engine: GGSRTraversal
) -> None:
    """score == WEIGHT_MATRIX[rel] × HOP_DECAY^hop for every known edge.

    Property 9, first clause. Floating-point tolerance is tight because
    the implementation is a direct multiply of the same literals.
    """
    scored = engine._score_results(records)
    assert len(scored) == len(records)

    for original, got in zip(records, scored_to_by_raw_order(scored, records)):
        expected_weight = WEIGHT_MATRIX[original["relationship"]]
        expected_score = expected_weight * (HOP_DECAY ** original["hop_distance"])
        assert got.weight == pytest.approx(expected_weight)
        assert got.score == pytest.approx(expected_score, rel=1e-9, abs=1e-12)


# ── Property 9b: sort is non-increasing by score ─────────────────────────


@settings(max_examples=150, deadline=None)
@given(records=_MIXED_RECORDS)
def test_scored_results_are_sorted_descending(
    records: list[dict[str, Any]],
) -> None:
    """Scoring output is sorted by score descending (Property 9, clause 2)."""
    engine = GGSRTraversal(graph_db=None)  # type: ignore[arg-type]
    scored = engine._score_results(records)
    for a, b in zip(scored, scored[1:]):
        assert a.score >= b.score


# ── Property 9c: unknown relationships fall back to DEFAULT_WEIGHT ───────


@settings(max_examples=50, deadline=None)
@given(name=_NAMES, rel=_UNKNOWN_RELATIONSHIPS, hop=_HOPS)
def test_unknown_relationship_uses_default_weight(
    name: str, rel: str, hop: int
) -> None:
    """Novel edge types score at ``DEFAULT_WEIGHT × HOP_DECAY^hop``."""
    engine = GGSRTraversal(graph_db=None)  # type: ignore[arg-type]
    scored = engine._score_results([_record(name, rel, hop)])
    assert len(scored) == 1
    row = scored[0]
    assert row.weight == pytest.approx(DEFAULT_WEIGHT)
    assert row.score == pytest.approx(DEFAULT_WEIGHT * HOP_DECAY ** hop)


# ── Property 9d: hop-2 score is strictly ≤ hop-1 score (same rel) ────────


@settings(max_examples=60, deadline=None)
@given(rel=_KNOWN_RELATIONSHIPS, name=_NAMES)
def test_deeper_hops_decay_score(rel: str, name: str) -> None:
    """Hop decay is monotonic: score(hop=2) ≤ score(hop=1) for same rel."""
    engine = GGSRTraversal(graph_db=None)  # type: ignore[arg-type]
    scored = engine._score_results(
        [_record(name, rel, 1), _record(name, rel, 2)]
    )
    # Find each by hop_distance; score at hop 1 must >= score at hop 2.
    by_hop = {r.hop_distance: r.score for r in scored}
    assert by_hop[1] >= by_hop[2]
    # And the ratio equals HOP_DECAY exactly.
    assert by_hop[2] == pytest.approx(by_hop[1] * HOP_DECAY)


# ── Property 9e: token-budget trim never exceeds budget ─────────────────


@settings(max_examples=100, deadline=None)
@given(records=_MIXED_RECORDS, budget=_BUDGETS)
def test_trim_never_exceeds_budget(
    records: list[dict[str, Any]], budget: int
) -> None:
    """Property 9, clause 3: sum(estimated_tokens) ≤ token_budget."""
    engine = GGSRTraversal(graph_db=None)  # type: ignore[arg-type]
    scored = engine._score_results(records)
    trimmed = engine._trim_to_budget(scored, budget)

    total_tokens = sum(r.estimated_tokens for r in trimmed)
    assert total_tokens <= budget

    # Every kept row had its estimated_tokens populated.
    for row in trimmed:
        assert row.estimated_tokens == estimate_row_tokens(row)


# ── Property 9f: trim is a prefix of the sorted list ────────────────────


@settings(max_examples=100, deadline=None)
@given(records=_MIXED_RECORDS, budget=_BUDGETS)
def test_trim_is_prefix_of_sorted(
    records: list[dict[str, Any]], budget: int
) -> None:
    """Trimming only drops the tail — never reorders kept rows."""
    engine = GGSRTraversal(graph_db=None)  # type: ignore[arg-type]
    scored = engine._score_results(records)
    trimmed = engine._trim_to_budget(scored, budget)

    # Identity-wise prefix check (order preserved, no substitutions).
    assert len(trimmed) <= len(scored)
    for kept, original in zip(trimmed, scored):
        assert kept is original


# ── Property 9g: trim is monotonic in budget ────────────────────────────


@settings(max_examples=60, deadline=None)
@given(records=_MIXED_RECORDS, small=_BUDGETS, big=_BUDGETS)
def test_larger_budget_keeps_at_least_as_many(
    records: list[dict[str, Any]], small: int, big: int
) -> None:
    """A bigger budget never keeps fewer rows."""
    if small > big:
        small, big = big, small
    engine = GGSRTraversal(graph_db=None)  # type: ignore[arg-type]
    scored = engine._score_results(records)
    assert len(engine._trim_to_budget(scored, small)) <= len(
        engine._trim_to_budget(scored, big)
    )


# ── Property 9h: empty input yields empty output ────────────────────────


def test_empty_inputs_are_well_defined() -> None:
    engine = GGSRTraversal(graph_db=None)  # type: ignore[arg-type]
    assert engine._score_results([]) == []
    assert engine._trim_to_budget([], 1000) == []
    assert engine._trim_to_budget([], 0) == []


# ── budget edge cases surfaced by Hypothesis shrinks ────────────────────


def test_zero_budget_returns_nothing() -> None:
    engine = GGSRTraversal(graph_db=None)  # type: ignore[arg-type]
    scored = engine._score_results(
        [_record("a", "CALLS", 1), _record("b", "USES", 2)]
    )
    assert engine._trim_to_budget(scored, 0) == []


def test_hop_distance_below_one_is_clamped_to_one() -> None:
    """Defensive: a malformed hop of 0 should behave like hop=1."""
    engine = GGSRTraversal(graph_db=None)  # type: ignore[arg-type]
    scored = engine._score_results([_record("x", "CALLS", 0)])
    assert scored[0].hop_distance == 1
    assert scored[0].score == pytest.approx(WEIGHT_MATRIX["CALLS"] * HOP_DECAY)


def test_finite_scores_for_all_known_edges() -> None:
    """No NaN/inf for any known edge at either legal hop distance."""
    engine = GGSRTraversal(graph_db=None)  # type: ignore[arg-type]
    for rel in WEIGHT_MATRIX:
        for hop in (1, 2):
            scored = engine._score_results([_record("n", rel, hop)])
            assert math.isfinite(scored[0].score)
            assert 0.0 < scored[0].score <= 1.0


# ── helpers ─────────────────────────────────────────────────────────────


def scored_to_by_raw_order(scored, records):
    """Restore original input order so we can pair each record to its score.

    ``_score_results`` sorts output, so we need a stable way to line up
    records[i] with its scored row. We match on (name, relationship,
    hop_distance) which together uniquely identify an input record
    Hypothesis generated (ties are fine — any matching row has the
    right score by construction).
    """
    remaining = list(scored)
    out = []
    for rec in records:
        for i, got in enumerate(remaining):
            if (
                got.name == rec["name"]
                and got.relationship == rec["relationship"]
                and got.hop_distance == rec["hop_distance"]
            ):
                out.append(got)
                remaining.pop(i)
                break
    return out
