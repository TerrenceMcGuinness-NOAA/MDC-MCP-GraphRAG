"""Default-tenant byte-equivalence regression tests (Task 6.3).

shared-scope-query-routing Requirements 6.2, 6.3, 6.5, 13.3.

Each test renders a tool through the hermetic capture harness
(:mod:`tests.baselines.capture`) and compares the complete rendered
response -- attribution header included -- against the baseline captured
from the revision immediately preceding the read-path routing change,
tolerating only the volatility masks earned in Task 6.2.

Coverage spans at least one tool from each of ``semantic_search``,
``ee2_compliance``, ``graph_rag``, and ``operational`` (R13.3), plus the
no-``tenant_id`` responses of ``get_knowledge_base_status``,
``check_knowledge_integrity``, and ``mcp_health_check`` (R6.3).

Before Task 7 lands these pass trivially: the read-path routing collapses
to the identity for the default ``gw`` tenant, so a stubbed adapter feeds
the tool the same hits and the rendered bytes are unchanged. That is
intended -- these tests are the guard Task 7 is measured against, not a
demonstration that anything has moved yet. This file also enforces the
Task 6.2 invariant that every committed mask traces back to a recorded
double-run difference, so the mask mechanism cannot be misused to hide a
real regression.
"""

from __future__ import annotations

import pytest

from tests.baselines import capture

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
# Requirement 6.3 names these three reporting tools explicitly.
_REQUIRED_R63_TOOLS = {
    "get_knowledge_base_status",
    "check_knowledge_integrity",
    "mcp_health_check",
}


# ── coverage guards ────────────────────────────────────────────────────────


def test_required_modules_are_covered() -> None:
    """R13.3: a regression scenario exists for each of the four modules."""
    covered = {capture.load_scenario_by_id(s).module for s in SCENARIO_IDS}
    missing = _REQUIRED_MODULES - covered
    assert not missing, f"no byte-equivalence scenario for module(s) {missing}"


def test_required_r63_reporting_tools_are_covered() -> None:
    """R6.3: status, integrity, and health each have a no-tenant scenario."""
    tools = {capture.load_scenario_by_id(s).tool for s in SCENARIO_IDS}
    missing = _REQUIRED_R63_TOOLS - tools
    assert not missing, f"missing R6.3 reporting scenario(s): {missing}"


def test_no_scenario_declares_a_tenant_id() -> None:
    """R6.2/R6.3 compare the *default*-tenant response: no tenant_id set."""
    for scenario_id in SCENARIO_IDS:
        scenario = capture.load_scenario_by_id(scenario_id)
        assert "tenant_id" not in scenario.args, (
            f"{scenario_id}: default-tenant baseline must freeze no tenant_id"
        )


# ── byte-equivalence ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
async def test_default_tenant_byte_equivalence(scenario_id: str) -> None:
    """R6.2/R6.3/R6.5: output matches the masked pre-change baseline."""
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
    does not. The header is retained in the byte-equivalence comparison
    rather than stripped, so a change to the attribution lines is caught.
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


# ── earned-mask enforcement (Task 6.2) ───────────────────────────────────────


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_every_committed_mask_is_earned(scenario_id: str) -> None:
    """R6.5: each committed mask traces to a recorded double-run difference.

    Re-derives the mask set from the two recorded runs (the ``.md``
    baseline and the ``.b.md`` evidence) and rejects any committed mask
    that does not match. A hand-added mask cannot survive this check.
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
    the comparison is exact. This exercises the mask machinery on a genuine
    volatile span to prove it (a) accepts an earned mask, (b) tolerates a
    change inside the masked span, and (c) still rejects a change outside
    it.
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
