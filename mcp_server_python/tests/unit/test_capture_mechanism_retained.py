"""Retention of the Baseline_Capture_Mechanism (Task 6.4).

default-tenant-freeze-retirement Requirement 13 criterion 1.

Task 6.3 retired Byte_Equivalence as a *standing rule* for the three
reporting tools. Requirement 13 keeps the capture *machinery* as an
instrument available to the next high-surface refactor. These assertions
pin that retention so a later cleanup cannot delete the instrument on the
grounds that the freeze it once enforced is gone:

* ``capture.py`` is still present,
* every recorded backend scenario is still present, and
* the earned-mask helpers ``derive_masks`` / ``verify_masks_earned`` /
  ``matches_baseline`` are all still callable.

This is a small dedicated module rather than an addition to
``tests/unit/test_freeze_retirement_records.py``, which a later step (10.3)
owns and which has not landed yet.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.baselines import capture

pytestmark = pytest.mark.unit

_BASELINE_DIR = Path(capture.__file__).resolve().parent

# The seven scenarios the capture harness records. Naming them explicitly
# rather than globbing means deleting a scenario file fails this test rather
# than silently shrinking the recorded set.
_RECORDED_SCENARIOS = {
    "search_documentation",
    "search_ee2_standards",
    "search_architecture",
    "get_operational_guidance",
    "get_knowledge_base_status",
    "check_knowledge_integrity",
    "mcp_health_check",
}


def test_capture_module_is_retained() -> None:
    """R13.1: ``capture.py`` remains present in the repository."""
    assert (_BASELINE_DIR / "capture.py").is_file(), (
        "capture.py must be retained as an instrument (R13.1)"
    )


def test_every_recorded_backend_scenario_is_retained() -> None:
    """R13.1: every ``recorded_backend/*.json`` scenario remains present."""
    recorded_dir = _BASELINE_DIR / "recorded_backend"
    present = {p.stem for p in recorded_dir.glob("*.json")}
    missing = _RECORDED_SCENARIOS - present
    assert not missing, f"recorded backend scenario(s) removed: {missing}"
    # The mechanism must not shed scenarios silently either.
    assert _RECORDED_SCENARIOS <= present


def test_earned_mask_helpers_are_retained() -> None:
    """R13.1: the earned-mask helpers remain present and callable."""
    for name in ("derive_masks", "verify_masks_earned", "matches_baseline"):
        helper = getattr(capture, name, None)
        assert callable(helper), f"capture.{name} must be retained (R13.1)"

    # A minimal end-to-end exercise, so "present" also means "working": a
    # real volatile span yields an earned mask, and the mask tolerates the
    # volatile span but nothing outside it.
    run_a = "latency 5ms done"
    run_b = "latency 9ms done"
    masks = capture.derive_masks(run_a, run_b)
    assert masks
    assert capture.verify_masks_earned(masks, run_a, run_b) == []
    assert capture.matches_baseline(run_a, masks, "latency 7ms done")
    assert not capture.matches_baseline(run_a, masks, "latency 5ms FAIL")
