"""Property tests for the Structural_Equivalence relation.

Feature: default-tenant-freeze-retirement (SDD Phase 80), Task 6.2.

Three properties over ``tests.baselines.structural``:

* Property 1 -- the relation is an equivalence relation (reflexive,
  symmetric, transitive).
* Property 2 -- it is blind to non-identifying variation (rewording, line
  order, whitespace, inserted noise lines).
* Property 3 -- it is sensitive to the identifying triple (collection set,
  document count, check verdict) with attribution.

Properties 2 and 3 exist as a PAIR and neither is sufficient alone: a relation
that ignores everything passes Property 2, and byte-equality passes Property 3.
Only both together establish that the relation is loose in the right place and
tight in the right place -- which is the whole reason it can replace
byte-equivalence without degrading into permitting any change at all.

The shared generators (``structural_views``, ``render_perturbations``,
``triple_perturbations``) live in ``tests/properties/conftest.py``; this file
is their first consumer. Two inputs are pinned alongside the generators because
each is a real observed shape a plausible extractor gets wrong and a random
generator would not construct: a ``[SKIP]`` token in an integrity table's
details cell while the status cell reads ``[OK]`` (a silent skip a
status-column-only reader scores as a pass), and a bare collection name that is
a substring of its prefixed form (which bare-substring extraction would pass).

Hermetic: standard-library parsing over recorded baselines and generated
values; no network, no backend, no credentials.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings

from tests.baselines.structural import (
    StructuralView,
    compare_structural,
    parse_structural,
)
from tests.properties.conftest import (
    render_perturbations,
    structural_views,
    triple_perturbations,
)

#: The three reporter scenarios whose recorded baselines Property 2 perturbs.
#: Query-tool baselines are not reporters -- they list no collection lines and
#: report no verdicts -- so they are deliberately excluded.
_REPORTERS = (
    "get_knowledge_base_status",
    "check_knowledge_integrity",
    "mcp_health_check",
)

#: ``structural_views`` can generate the empty view; ``compare_structural``
#: rejects an empty baseline by design, so the equivalence-relation and
#: attribution properties draw from the non-empty subset. The empty-baseline
#: guard is exercised directly by ``test_empty_baseline_raises`` instead.
_NON_EMPTY_VIEWS = structural_views().filter(
    lambda v: bool(v.collections) or bool(v.verdicts)
)


def _load_reporter(name: str) -> str:
    """Return the recorded pre-change text for reporter ``name``."""
    path = (
        Path(__file__).resolve().parents[1]
        / "baselines"
        / "pre_change"
        / f"{name}.md"
    )
    return path.read_text()


# Feature: default-tenant-freeze-retirement, Property 1: Structural_Equivalence
# is an equivalence relation (reflexivity)
@pytest.mark.property
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.filter_too_much],
)
@given(view=_NON_EMPTY_VIEWS)
def test_p1_reflexive(view: StructuralView) -> None:
    """Reflexivity is what makes a re-recorded baseline a valid reference."""
    assert compare_structural(view, view) == []


# Feature: default-tenant-freeze-retirement, Property 1: Structural_Equivalence
# is an equivalence relation (symmetry)
@pytest.mark.property
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.filter_too_much],
)
@given(a=_NON_EMPTY_VIEWS, b=_NON_EMPTY_VIEWS)
def test_p1_symmetric(a: StructuralView, b: StructuralView) -> None:
    """Symmetry makes the two-directional collection finding well defined.

    A relation whose verdict depended on argument order would report a
    dropped collection one way and nothing the other.
    """
    assert (compare_structural(a, b) == []) == (
        compare_structural(b, a) == []
    )


# Feature: default-tenant-freeze-retirement, Property 1: Structural_Equivalence
# is an equivalence relation (transitivity)
@pytest.mark.property
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.filter_too_much],
)
@given(a=_NON_EMPTY_VIEWS, b=_NON_EMPTY_VIEWS, c=_NON_EMPTY_VIEWS)
def test_p1_transitive(
    a: StructuralView, b: StructuralView, c: StructuralView
) -> None:
    """Transitivity lets the follow-up sequence re-record three times.

    Without it the third re-record could silently diverge from the first.
    """
    if compare_structural(a, b) == [] and compare_structural(b, c) == []:
        assert compare_structural(a, c) == []


# Feature: default-tenant-freeze-retirement, Property 2: Insensitivity to
# non-identifying variation
@pytest.mark.property
@pytest.mark.parametrize("reporter", _REPORTERS)
@settings(max_examples=200, deadline=None)
@given(perturb=render_perturbations())
def test_p2_insensitive_to_non_identifying_variation(reporter, perturb):
    """Rewording, line order, whitespace, and noise lines change nothing.

    ``max_examples=200`` because the perturbation space is small and discrete
    and the interesting draws -- a permutation that moves a table row across
    its header, an inserted line naming nothing -- are individually unlikely.
    This is the half that permits the follow-ups to reword a report; it is
    also the half a broken relation passes trivially, which is why Property 3
    is not optional.
    """
    text = _load_reporter(reporter)
    baseline = parse_structural(text)
    candidate = parse_structural(perturb(text))
    assert compare_structural(baseline, candidate) == []


# Feature: default-tenant-freeze-retirement, Property 3: Sensitivity to the
# identifying triple, with attribution
@pytest.mark.property
@settings(max_examples=200, deadline=None)
@given(view=_NON_EMPTY_VIEWS, mutate=triple_perturbations())
def test_p3_single_perturbation_is_detected_and_named(view, mutate):
    """A single triple mutation yields exactly one finding naming it.

    ``triple_perturbations`` applies exactly one of: drop a collection, add a
    collection, change one count, flip one verdict -- so a correct relation
    reports exactly one divergence, and that finding names the perturbed
    element.
    """
    mutated, name = mutate(view)
    findings = compare_structural(view, mutated)
    assert len(findings) == 1
    assert name in findings[0]


# Feature: default-tenant-freeze-retirement, Property 3: Sensitivity to the
# identifying triple, with attribution (pinned input -- [SKIP] in details)
@pytest.mark.property
def test_p3_skip_in_details_cell_is_detected() -> None:
    """A skip hidden in the details cell must not read as a pass.

    Both rows carry ``[OK]`` in the status column, so an extractor reading
    only that column scores a real pass and a silent skip as equal. The
    recorded baseline contains no such shape, so this is pinned rather than
    generated (finding 8).
    """
    baseline_text = (
        "| Check | Status | Details |\n"
        "|-------|--------|---------|\n"
        "| Path Consistency | [OK] | [OK] 0/3 sampled docs ok |\n"
    )
    candidate_text = (
        "| Check | Status | Details |\n"
        "|-------|--------|---------|\n"
        "| Path Consistency | [OK] | [SKIP] sampler not exposed |\n"
    )
    findings = compare_structural(
        parse_structural(baseline_text),
        parse_structural(candidate_text),
    )
    assert findings == [
        "structural: check Path Consistency verdict PASS != SKIP"
    ]


# Feature: default-tenant-freeze-retirement, Property 3: Sensitivity to the
# identifying triple, with attribution (pinned input -- name containment)
@pytest.mark.property
def test_p3_collection_name_containment_is_detected() -> None:
    """A bare collection name inside its prefixed form is not a match.

    ``mdc-workflow-docs-titan1024`` is a substring of
    ``gw_v17_mdc-workflow-docs-titan1024``; a bare-substring extractor would
    find the short name inside the long one and pass. Keying on the exact
    name catches the swap as two findings (finding 6).
    """
    baseline_text = "  - mdc-workflow-docs-titan1024: 100 documents\n"
    candidate_text = (
        "  - gw_v17_mdc-workflow-docs-titan1024 (tenant): 100 documents\n"
    )
    findings = compare_structural(
        parse_structural(baseline_text),
        parse_structural(candidate_text),
    )
    assert findings == [
        "structural: collection present only in baseline: "
        "mdc-workflow-docs-titan1024",
        "structural: collection present only in candidate: "
        "gw_v17_mdc-workflow-docs-titan1024",
    ]


@pytest.mark.property
def test_empty_baseline_raises() -> None:
    """An empty baseline view must not compare equivalent to anything.

    A comparison that passes because it found nothing to check is the one
    failure a reviewer never sees, so the guard raises rather than returning
    an empty finding list.
    """
    empty = StructuralView(collections={}, verdicts={})
    with pytest.raises(ValueError):
        compare_structural(empty, empty)


@pytest.mark.property
def test_malformed_count_raises() -> None:
    """A collection line whose count does not parse must raise, not default.

    ``None`` already means unprovisioned and ``0`` already means
    provisioned-empty; folding a third meaning into either would blind the
    relation to the transition it exists to watch.
    """
    with pytest.raises(ValueError):
        parse_structural("  - foo: abc documents\n")


# ---------------------------------------------------------------------------
# Regression guard: the collapsed Status key must not mask a failure.
#
# Found by probing after this module landed, not by a test -- which is why the
# guard is here now. The two ``- **Status:**`` lines are byte-identical and
# collapse under one key (see structural.py's module note on why no
# perturbation-stable key can distinguish them). The original collapse was a
# plain dict assignment, so it was last-write-wins: a FAIL on the vector store
# followed by a PASS on the graph store yielded PASS and the regression
# vanished. A graph-only failure was caught purely because that line happens
# to come second in the render.
#
# An order-dependent gate is not a gate, so the collapse now keeps the most
# severe verdict. These cases pin all three failure directions plus the two
# no-op directions, so a future simplification back to assignment fails here.
# ---------------------------------------------------------------------------


def _two_store_status(vector: str, graph: str) -> str:
    return (
        "## Vector Database (OpenSearch)\n"
        f"- **Status:** {vector}\n"
        "## Graph Database (Neptune)\n"
        f"- **Status:** {graph}\n"
    )


_HEALTHY = "[OK] Healthy"
_BROKEN = "[ERROR] unreachable"


@pytest.mark.parametrize(
    "vector,graph",
    [
        (_BROKEN, _HEALTHY),   # vector only -- the direction that was masked
        (_HEALTHY, _BROKEN),   # graph only
        (_BROKEN, _BROKEN),    # both
    ],
    ids=["vector-only", "graph-only", "both"],
)
def test_collapsed_status_key_never_masks_a_failure(
    vector: str, graph: str
) -> None:
    """A failure in either store is caught regardless of render order."""
    baseline = parse_structural(_two_store_status(_HEALTHY, _HEALTHY))
    candidate = parse_structural(_two_store_status(vector, graph))
    findings = compare_structural(baseline, candidate)
    assert findings, (
        "a store reported a failure and the comparison found nothing -- the "
        "collapsed Status key is masking it, which is the last-write-wins "
        "defect this guard exists to prevent"
    )


def test_collapsed_status_key_is_still_order_insensitive() -> None:
    """Severity precedence must not cost R9.2 order-insensitivity.

    Swapping the two store sections is a pure reordering and must remain
    equivalent -- the fix keeps the worst verdict, it does not make the
    comparison sensitive to which line came first.
    """
    baseline = parse_structural(_two_store_status(_HEALTHY, _HEALTHY))
    swapped = parse_structural(
        "## Graph Database (Neptune)\n"
        f"- **Status:** {_HEALTHY}\n"
        "## Vector Database (OpenSearch)\n"
        f"- **Status:** {_HEALTHY}\n"
    )
    assert compare_structural(baseline, swapped) == []
