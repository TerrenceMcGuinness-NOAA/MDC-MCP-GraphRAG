"""Default-tenant reporting-vs-query regression tests.

shared-scope-query-routing Requirements 6.2, 6.5, 13.3; and
default-tenant-freeze-retirement Requirements 10.5, 10.6, 13.4 (Task 6.3).

Each test renders a tool through the hermetic capture harness
(:mod:`tests.baselines.capture`) against the baseline captured from the
revision immediately preceding the Phase 79 read-path routing change. The
seven scenarios split by tool into two groups, compared under two relations:

* **Three reporting tools** -- ``get_knowledge_base_status``,
  ``check_knowledge_integrity``, ``mcp_health_check`` -- are compared under
  **Structural_Equivalence** (:mod:`tests.baselines.structural`): the same
  set of Physical_Collections, the same per-collection document count, and
  the same per-check verdict, with wording, line order, and whitespace free
  to change. Task 6.3 retires Byte_Equivalence for these three (Phase 79
  R6.3 superseded by default-tenant-freeze-retirement), so a correction to
  the ``gw`` status total or the integrity sampler is expressible rather
  than blocked. Masks are not consulted here -- the relation reads
  structure, not bytes.
* **Four query tools** -- ``search_documentation``, ``search_ee2_standards``,
  ``search_architecture``, ``get_operational_guidance`` -- **stay
  byte-frozen** against the masked pre-change baseline until Task 8.3 pairs a
  structural addressed-set check with the benchmark comparison (Phase 79
  R6.2). Their comparison is unchanged from Task 6.3's original form.

The two groups are derived from each scenario's own tool name (the reporting
set below, and its complement) rather than from a second hardcoded list, so a
scenario added later cannot land in neither group and silently escape both
comparisons.

Before a Follow_Up_Sequence change actually moves default-tenant reporter
output, the reporter scenarios pass under Structural_Equivalence exactly as
they passed under Byte_Equivalence: the same recorded responses render the
same bytes, so the same structure. A fifth suite failure at this stage is
therefore attributable, not expected -- it becomes expected only when a
follow-up changes the output and re-records the baseline in the same change.

This file also enforces the Task 6.2 earned-mask invariant (all five checks
retained): every committed mask must trace back to a recorded double-run
difference, so the mask mechanism cannot be misused to hide a real regression.
The masks still govern the four query-tool scenarios; retiring byte-equality
for the three reporters does not retire the earned-mask guarantee.
"""

from __future__ import annotations

import pytest

from tests.baselines import capture, structural

pytestmark = pytest.mark.unit

SCENARIO_IDS = capture.scenario_ids()

# The four tool modules Requirement 13.3 requires a regression for, mapped to
# the scenario that covers each, so a dropped scenario fails loudly here rather
# than silently shrinking coverage.
_REQUIRED_MODULES = {
    "semantic_search",
    "ee2_compliance",
    "graph_rag",
    "operational",
}
# Phase 79 R6.3 names these three reporting tools explicitly. Task 6.3 moves
# them to Structural_Equivalence; they are also the reporting/query partition
# key below.
_REQUIRED_R63_TOOLS = {
    "get_knowledge_base_status",
    "check_knowledge_integrity",
    "mcp_health_check",
}

# Partition the scenarios by their own tool name -- not by a second hardcoded
# list -- so a scenario added later cannot land in neither group. The three
# reporting tools move to Structural_Equivalence (Task 6.3); every other
# scenario is a Query_Tool and stays byte-frozen until Task 8.3.
_REPORTING_SCENARIO_IDS = [
    s
    for s in SCENARIO_IDS
    if capture.load_scenario_by_id(s).tool in _REQUIRED_R63_TOOLS
]
_QUERY_SCENARIO_IDS = [
    s
    for s in SCENARIO_IDS
    if capture.load_scenario_by_id(s).tool not in _REQUIRED_R63_TOOLS
]


# ── coverage guards ────────────────────────────────────────────────────────


def test_required_modules_are_covered() -> None:
    """R13.3: a regression scenario exists for each of the four modules."""
    covered = {capture.load_scenario_by_id(s).module for s in SCENARIO_IDS}
    missing = _REQUIRED_MODULES - covered
    assert not missing, f"no regression scenario for module(s) {missing}"


def test_required_r63_reporting_tools_are_covered() -> None:
    """R10.6: status, integrity, and health each have a no-tenant scenario.

    Relaxing the comparison to Structural_Equivalence must not become an
    opportunity to quietly shrink what is compared, so the coverage guard for
    the three reporting tools stays exactly as it was under byte-equivalence.
    """
    tools = {capture.load_scenario_by_id(s).tool for s in SCENARIO_IDS}
    missing = _REQUIRED_R63_TOOLS - tools
    assert not missing, f"missing R6.3 reporting scenario(s): {missing}"


def test_scenario_partition_is_total_and_disjoint() -> None:
    """Every scenario is compared under exactly one relation.

    Deriving the Query_Tool group as the complement of the reporting group
    guarantees a newly added scenario lands in exactly one partition rather
    than silently escaping both comparisons.
    """
    reporting = set(_REPORTING_SCENARIO_IDS)
    query = set(_QUERY_SCENARIO_IDS)
    assert reporting.isdisjoint(query)
    assert reporting | query == set(SCENARIO_IDS)
    assert reporting, "no reporting scenario found to compare structurally"
    assert query, "no query scenario found to compare byte-for-byte"


def test_no_scenario_declares_a_tenant_id() -> None:
    """R6.2/R6.3 compare the *default*-tenant response: no tenant_id set."""
    for scenario_id in SCENARIO_IDS:
        scenario = capture.load_scenario_by_id(scenario_id)
        assert "tenant_id" not in scenario.args, (
            f"{scenario_id}: default-tenant baseline must freeze no tenant_id"
        )


# ── reporting tools: Structural_Equivalence (Task 6.3) ───────────────────────


@pytest.mark.parametrize("scenario_id", _REPORTING_SCENARIO_IDS)
async def test_reporting_tools_structural_equivalence(
    scenario_id: str,
) -> None:
    """R10.5: reporter output is Structurally_Equivalent to the baseline.

    Task 6.3 supersedes Byte_Equivalence for the Status_Reporter, the
    Integrity_Checker, and the Health_Reporter (Phase 79 R6.3). Each of the
    three reporter scenarios is compared under the Requirement 9 relation --
    equal set of Physical_Collection names, equal per-collection document
    count, equal per-check verdict -- and is free to reword, reorder, and
    re-space. The masks are irrelevant to a structural comparison, so the
    reporting scenarios do not consult them.
    """
    scenario = capture.load_scenario_by_id(scenario_id)
    baseline = capture.load_baseline(scenario_id)

    candidate = await capture.render(scenario)

    findings = structural.compare_structural(
        structural.parse_structural(baseline),
        structural.parse_structural(candidate),
    )

    assert findings == [], (
        f"{scenario_id}: rendered output is not Structurally_Equivalent to "
        f"the pre-change baseline. Each finding names the diverging "
        f"Physical_Collection or check:\n" + "\n".join(findings)
    )


# ── query tools: byte-equivalence (stays until Task 8.3) ─────────────────────


@pytest.mark.parametrize("scenario_id", _QUERY_SCENARIO_IDS)
async def test_query_tools_byte_equivalence(scenario_id: str) -> None:
    """R6.2/R6.5: Query_Tool output matches the masked pre-change baseline.

    The four Query_Tool scenarios stay byte-frozen until Task 8.3 pairs a
    structural addressed-set check with the benchmark comparison. Task 6.3
    moved only the three reporter scenarios to Structural_Equivalence.
    """
    scenario = capture.load_scenario_by_id(scenario_id)
    baseline = capture.load_baseline(scenario_id)
    masks = capture.load_masks(scenario_id)

    candidate = await capture.render(scenario)

    assert capture.matches_baseline(baseline, masks, candidate), (
        f"{scenario_id}: rendered output diverges from the pre-change "
        f"baseline outside the {len(masks)} earned volatility mask(s). Any "
        f"span that differs and is not an earned mask is a regression, not a "
        f"mask candidate.\n--- baseline ---\n{baseline!r}\n--- candidate ---\n"
        f"{candidate!r}"
    )


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_attribution_header_is_part_of_the_baseline(scenario_id: str) -> None:
    """R6.2: the ``*Tenant: gw*`` header is included in the compared bytes.

    Tenant-scoped tools carry it; the server-global ``mcp_health_check``
    does not. The header is retained in the comparison rather than stripped,
    so a change to the attribution lines is caught. This guard stays for
    every scenario it currently covers -- both the byte-frozen query tools
    and the now-structural reporters -- since the attribution header is a
    property of the recorded baseline regardless of the comparison relation.
    """
    scenario = capture.load_scenario_by_id(scenario_id)
    baseline = capture.load_baseline(scenario_id)
    if scenario.tenant_scoped:
        assert baseline.startswith("*Tenant: gw*\n"), (
            f"{scenario_id}: tenant-scoped baseline missing gw header"
        )
    else:
        assert not baseline.startswith("*Tenant:"), (
            f"{scenario_id}: server-global tool must carry no header"
        )


# ── earned-mask enforcement (Task 6.2, retained per R13.4) ───────────────────


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_every_committed_mask_is_earned(scenario_id: str) -> None:
    """R6.5/R13.4: each committed mask traces to a double-run difference.

    Re-derives the mask set from the two recorded runs (the ``.md``
    baseline and the ``.b.md`` evidence) and rejects any committed mask
    that does not match. A hand-added mask cannot survive this check. The
    guarantee is retained over every scenario -- retiring byte-equality for
    the three reporters does not retire the earned-mask guarantee that stops
    a mask being used to paper over a real regression.
    """
    run_a = capture.load_baseline(scenario_id)
    run_b = capture.load_evidence(scenario_id)
    masks = capture.load_masks(scenario_id)

    findings = capture.verify_masks_earned(masks, run_a, run_b)

    assert findings == [], (
        f"{scenario_id}: {len(findings)} unearned mask finding(s): {findings}"
    )


def test_hand_added_mask_over_identical_runs_is_rejected() -> None:
    """A fabricated mask with no underlying volatility must be rejected."""
    run_a = "Total Documents: 129013\nStatus: OK\n"
    run_b = "Total Documents: 129013\nStatus: OK\n"  # identical: no volatility
    bogus = [{"a": [0, 5], "b": [0, 5], "a_text": "Total", "b_text": "Total"}]

    findings = capture.verify_masks_earned(bogus, run_a, run_b)

    assert findings, "a mask over identical runs must fail the earned check"


def test_over_broad_hand_added_mask_is_rejected() -> None:
    """Masking a whole line when only a substring is volatile is rejected."""
    run_a = "latency 5ms done"
    run_b = "latency 9ms done"
    over_broad = [
        {
            "a": [0, len(run_a)],
            "b": [0, len(run_b)],
            "a_text": run_a,
            "b_text": run_b,
        }
    ]

    findings = capture.verify_masks_earned(over_broad, run_a, run_b)

    assert findings, "an over-broad line mask must fail the earned check"


# ── mask machinery sanity (real volatile span) ───────────────────────────────


def test_earned_mask_tolerates_only_the_volatile_span() -> None:
    """A correctly-earned substring mask passes and bounds its wildcard.

    Our seven scenarios are deterministic, so their mask sets are empty and
    the query-tool comparison is exact. This exercises the mask machinery on
    a genuine volatile span to prove it (a) accepts an earned mask, (b)
    tolerates a change inside the masked span, and (c) still rejects a change
    outside it.
    """
    run_a = "latency 5ms done"
    run_b = "latency 9ms done"

    masks = capture.derive_masks(run_a, run_b)

    assert masks, "a real character difference must yield at least one mask"
    assert capture.verify_masks_earned(masks, run_a, run_b) == []
    # Tolerates a different value in the volatile span ...
    assert capture.matches_baseline(run_a, masks, "latency 7ms done")
    # ... but not a change outside it.
    assert not capture.matches_baseline(run_a, masks, "latency 5ms FAIL")


def test_matches_baseline_is_exact_without_masks() -> None:
    """With no masks the comparison is exact string equality."""
    assert capture.matches_baseline("abc\n", [], "abc\n")
    assert not capture.matches_baseline("abc\n", [], "abd\n")
