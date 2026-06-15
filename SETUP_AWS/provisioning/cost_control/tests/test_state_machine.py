"""State machine + CLI property tests (Task 13.1).

Covers every legal/illegal transition, Property 3 (terminal no-op),
Property 4 (kill-mid-transition leaves a defined state + --resume continues),
Property 6 (no destructive call before confirmation / --yes), and that
--dry-run and status mutate nothing and acquire no lock.

Uses fake tiers (Tier protocol) and an in-memory fake state file so the
orchestration logic is exercised without any AWS.

Requirements: 1.5, 2.5, 7.1, 7.2, 7.3, 7.4, 15.3.
"""

from __future__ import annotations

import io

import pytest

from cost_control import cli
from cost_control.costs import CostModel
from cost_control.state_file import (
    ConcurrentOperationError,
    MissingStateError,
    VALID_STATES,
    new_initial_document,
)
from cost_control.state_machine import (
    EXIT_OK,
    ILLEGAL,
    NOOP,
    PROCEED,
    REFUSE_CONCURRENT,
    REQUIRE_RESUME,
    OperationResult,
    StateMachine,
    plan_transition,
)
from cost_control.tiers import PlannedAction


# ── fakes ───────────────────────────────────────────────────────────────────

class FakeTier:
    def __init__(self, name, asleep=False, fail_on=None):
        self.name = name
        self._asleep = asleep
        self.fail_on = fail_on
        self.hibernate_calls = 0
        self.wake_calls = 0

    def plan(self, mode):
        return [PlannedAction(self.name, "act", "desc",
                              destructive=(mode == "hibernate"))]

    def hibernate(self):
        self.hibernate_calls += 1
        if self.fail_on == "hibernate":
            raise RuntimeError("hibernate boom")
        self._asleep = True
        return [PlannedAction(self.name, "stop", "stopped", destructive=True)]

    def wake(self):
        self.wake_calls += 1
        if self.fail_on == "wake":
            raise RuntimeError("wake boom")
        self._asleep = False
        return [PlannedAction(self.name, "start", "started")]

    def is_asleep(self):
        return self._asleep

    def capture_manifest(self):
        return {"counts": {self.name: 1}}


class FakeStateFile:
    def __init__(self, doc=None, etag="e0", missing=False):
        self.doc = doc
        self.etag = etag
        self.missing = missing
        self.writes = []
        self.reads = 0
        self.conflict_on_states = set()

    def read(self):
        self.reads += 1
        if self.missing:
            raise MissingStateError("absent")
        return dict(self.doc), self.etag

    def write(self, doc, etag):
        if doc["current_state"] in self.conflict_on_states:
            raise ConcurrentOperationError("stale etag")
        self.writes.append(dict(doc))
        self.doc = dict(doc)
        self.etag = f"e{len(self.writes)}"
        return self.etag


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 1.0
        return self.t


def _audit():
    from cost_control.audit import AuditLogger
    return AuditLogger(
        operation_id="op-test", caller_arn="arn:op:terry",
        environment_name="dev", log_group="lg", audit_bucket="b",
        audit_prefix="cost-control/dev/", console_stream=io.StringIO(),
    )


def _doc(state):
    d = new_initial_document("dev")
    d["current_state"] = state
    d["previous_state"] = "Active_Mode"
    return d


def _sm(doc, tiers, *, audit=None, **kw):
    sf = FakeStateFile(doc=doc)
    audit = audit or _audit()
    sm = StateMachine(
        environment_name="dev", state_file=sf, audit=audit, tiers=tiers,
        cost_model=CostModel(), caller_arn="arn:op:terry", operation_id="op-test",
        time_fn=_Clock(), **kw,
    )
    return sm, sf, audit


def _events(audit):
    return [r["event_type"] for r in audit.records]


# ── transition table (every legal/illegal) ──────────────────────────────────

@pytest.mark.parametrize("state,expected", [
    ("Active_Mode", PROCEED),
    ("Wake_State", PROCEED),
    ("Sleep_State", NOOP),
    ("Sleeping", REFUSE_CONCURRENT),
    ("Waking", REFUSE_CONCURRENT),
    ("Active_Mode_Degraded", REQUIRE_RESUME),   # no resume
    ("Sleep_State_Degraded", ILLEGAL),
])
def test_plan_transition_hibernate(state, expected):
    assert plan_transition("hibernate", state, resume=False) == expected


@pytest.mark.parametrize("state,expected", [
    ("Sleep_State", PROCEED),
    ("Wake_State", NOOP),
    ("Active_Mode", NOOP),
    ("Sleeping", REFUSE_CONCURRENT),
    ("Waking", REFUSE_CONCURRENT),
    ("Sleep_State_Degraded", REQUIRE_RESUME),   # no resume
    ("Active_Mode_Degraded", ILLEGAL),
])
def test_plan_transition_wake(state, expected):
    assert plan_transition("wake", state, resume=False) == expected


def test_plan_transition_resume_promotes_degraded_to_proceed():
    assert plan_transition("hibernate", "Active_Mode_Degraded", resume=True) == PROCEED
    assert plan_transition("wake", "Sleep_State_Degraded", resume=True) == PROCEED


# ── Property 3: terminal no-op ───────────────────────────────────────────────

def test_p3_hibernate_noop_in_sleep_state():
    t = FakeTier("ec2")
    sm, sf, audit = _sm(_doc("Sleep_State"), [t])
    result = sm.hibernate()
    assert result.exit_code == EXIT_OK and result.success
    assert t.hibernate_calls == 0
    assert sf.writes == []                       # no mutation
    assert "Sleep_NoOp" in _events(audit)


@pytest.mark.parametrize("state", ["Wake_State", "Active_Mode"])
def test_p3_wake_noop_in_awake_states(state):
    t = FakeTier("ec2")
    sm, sf, audit = _sm(_doc(state), [t])
    result = sm.wake()
    assert result.exit_code == EXIT_OK and result.success
    assert t.wake_calls == 0
    assert sf.writes == []
    assert "Wake_NoOp" in _events(audit)


# ── Property 7: concurrency refusal ──────────────────────────────────────────

@pytest.mark.parametrize("state", ["Sleeping", "Waking"])
def test_concurrency_refused_in_transient_state(state):
    t = FakeTier("ec2")
    sm, sf, audit = _sm(_doc(state), [t])
    result = sm.hibernate()
    assert result.exit_code != EXIT_OK and not result.success
    assert t.hibernate_calls == 0
    assert sf.writes == []
    assert "Concurrent_Operation_Refused" in _events(audit)


def test_concurrency_refused_on_stale_etag():
    t = FakeTier("ec2")
    sm, sf, audit = _sm(_doc("Active_Mode"), [t])
    sf.conflict_on_states = {"Sleeping"}          # lock write loses the race
    result = sm.hibernate()
    assert result.exit_code != EXIT_OK
    assert t.hibernate_calls == 0
    assert "Concurrent_Operation_Refused" in _events(audit)


# ── require-resume / illegal ─────────────────────────────────────────────────

def test_require_resume_without_resume_flag():
    sm, sf, audit = _sm(_doc("Active_Mode_Degraded"), [FakeTier("ec2")])
    result = sm.hibernate(resume=False)
    assert result.exit_code != EXIT_OK
    assert sf.writes == []


def test_illegal_transition_hibernate_from_sleep_degraded():
    sm, sf, audit = _sm(_doc("Sleep_State_Degraded"), [FakeTier("ec2")])
    result = sm.hibernate()
    assert result.exit_code != EXIT_OK
    assert sf.writes == []


# ── Property 4: kill mid-transition -> defined state, --resume continues ─────

def test_p4_failure_leaves_defined_state_and_resume_completes():
    t_ec2 = FakeTier("ec2")
    t_nep = FakeTier("neptune")
    t_os = FakeTier("opensearch", fail_on="hibernate")   # 3rd tier explodes
    sm, sf, audit = _sm(_doc("Active_Mode"), [t_ec2, t_nep, t_os])

    result = sm.hibernate()
    # destructive began (ec2 + neptune stopped) -> degraded, a DEFINED state.
    assert result.final_state == "Active_Mode_Degraded"
    assert result.final_state in VALID_STATES
    assert sf.doc["current_state"] in VALID_STATES
    assert t_ec2.is_asleep() and t_nep.is_asleep() and not t_os.is_asleep()
    assert "Sleep_Failed" in _events(audit)

    # Resume: the two already-asleep tiers are skipped, the failed one retried.
    t_os.fail_on = None
    r2 = sm.hibernate(resume=True)
    assert r2.final_state == "Sleep_State"
    assert t_ec2.hibernate_calls == 1          # skipped on resume
    assert t_nep.hibernate_calls == 1          # skipped on resume
    assert t_os.is_asleep()                    # retried + succeeded
    assert sf.doc["current_state"] == "Sleep_State"


# ── Property 6: no destructive call before confirmation ──────────────────────

def test_p6_unconfirmed_hibernate_touches_nothing():
    t = FakeTier("ec2")
    sm, sf, audit = _sm(_doc("Active_Mode"), [t])
    result = sm.hibernate(confirmed=False)
    assert result.exit_code == EXIT_OK          # decline exits 0 (R15.3)
    assert t.hibernate_calls == 0               # no destructive call
    assert sf.writes == []                      # no state mutation
    assert "Confirmation_Declined" in _events(audit)


def test_p6_unconfirmed_wake_touches_nothing():
    t = FakeTier("ec2", asleep=True)
    sm, sf, audit = _sm(_doc("Sleep_State"), [t])
    result = sm.wake(confirmed=False)
    assert result.exit_code == EXIT_OK
    assert t.wake_calls == 0
    assert sf.writes == []
    assert "Confirmation_Declined" in _events(audit)


# ── successful hibernate / wake + savings wiring ─────────────────────────────

def test_hibernate_success_emits_savings():
    tiers = [FakeTier("ec2"), FakeTier("neptune")]
    sm, sf, audit = _sm(_doc("Active_Mode"), tiers)
    result = sm.hibernate()
    assert result.final_state == "Sleep_State"
    completed = [r for r in audit.records if r["event_type"] == "Sleep_Completed"]
    assert completed and completed[0]["estimated_savings_usd_per_hour"] > 0


def test_wake_success_emits_window_savings_and_progress():
    import datetime as _dt
    doc = _doc("Sleep_State")
    doc["last_transition_at"] = "2026-06-15T18:00:00Z"
    tiers = [FakeTier("ec2", asleep=True), FakeTier("neptune", asleep=True)]
    sm, sf, audit = _sm(
        doc, tiers,
        utcnow_fn=lambda: _dt.datetime(2026, 6, 15, 19, 0, 0, tzinfo=_dt.timezone.utc),
    )
    result = sm.wake()
    assert result.final_state == "Wake_State"
    completed = [r for r in audit.records if r["event_type"] == "Wake_Completed"]
    assert completed and completed[0]["estimated_savings_usd_per_hour"] > 0
    assert "Wake_Progress" in _events(audit)     # per-tier progress (R6.2)


def test_wake_budget_exceeded_yields_timeout_degraded():
    tiers = [FakeTier("ec2", asleep=True), FakeTier("neptune", asleep=True)]
    sm, sf, audit = _sm(_doc("Sleep_State"), tiers, wake_budget_s=-1.0)
    result = sm.wake()
    assert result.final_state == "Sleep_State_Degraded"
    assert result.exit_code != EXIT_OK
    assert "Wake_Timeout" in _events(audit)


# ── drift wiring ─────────────────────────────────────────────────────────────

class _DriftNS:
    def __init__(self, preserving):
        self.preserving = preserving


def test_wake_refuses_on_destructive_drift_before_compute():
    tiers = [FakeTier("ec2", asleep=True)]
    sm, sf, audit = _sm(_doc("Sleep_State"), tiers,
                        drift_fn=lambda manifest, force: (False, _DriftNS([])))
    result = sm.wake()
    assert result.final_state == "Sleep_State"        # left untouched
    assert result.exit_code != EXIT_OK
    assert tiers[0].wake_calls == 0                    # no compute created
    assert "Drift_Detected" in _events(audit)
    assert sf.writes == []                             # no Waking write


def test_wake_reconciles_preserving_drift_and_proceeds():
    tiers = [FakeTier("ec2", asleep=True)]
    sm, sf, audit = _sm(_doc("Sleep_State"), tiers,
                        drift_fn=lambda manifest, force: (True, _DriftNS(["delta"])))
    result = sm.wake()
    assert result.final_state == "Wake_State"
    assert "Drift_Reconciled" in _events(audit)


# ── wake validation probe failure ───────────────────────────────────────────

def test_wake_probe_failure_degrades():
    def _boom(manifest):
        raise RuntimeError("probe failed")
    tiers = [FakeTier("ec2", asleep=True)]
    sm, sf, audit = _sm(_doc("Sleep_State"), tiers, wake_probe_fn=_boom)
    result = sm.wake()
    assert result.final_state == "Sleep_State_Degraded"
    assert "Wake_Failed" in _events(audit)


# ── status / dry-run mutate nothing ──────────────────────────────────────────

def test_status_does_not_lock_or_mutate():
    sm, sf, audit = _sm(_doc("Sleep_State"), [FakeTier("ec2")])
    doc = sm.status()
    assert doc["current_state"] == "Sleep_State"
    assert sf.writes == []                       # no lock, no write


def _cli_deps(doc, tiers):
    sm, sf, audit = _sm(doc, tiers)
    out = []
    deps = cli.CliDeps(
        environment_name="dev", state_machine=sm, audit=audit, plan_tiers=tiers,
        input_fn=lambda prompt: "",              # would decline if prompted
        output_fn=out.append,
    )
    return deps, sf, tiers, out


def test_cli_dry_run_mutates_nothing():
    deps, sf, tiers, out = _cli_deps(_doc("Active_Mode"), [FakeTier("ec2")])
    args = cli.build_parser().parse_args(["hibernate", "--env", "dev", "--dry-run"])
    code = cli.run(args, deps)
    assert code == EXIT_OK
    assert tiers[0].hibernate_calls == 0
    assert sf.writes == []
    assert any("Dry-run plan" in line for line in out)


def test_cli_status_mutates_nothing():
    deps, sf, tiers, out = _cli_deps(_doc("Sleep_State"), [FakeTier("ec2")])
    args = cli.build_parser().parse_args(["status", "--env", "dev"])
    code = cli.run(args, deps)
    assert code == EXIT_OK
    assert sf.writes == []


# ── confirmation gate unit ───────────────────────────────────────────────────

def test_confirm_gate_exact_phrase_accepts():
    out = []
    assert cli.confirm_gate(command="hibernate", environment_name="dev", yes=False,
                            input_fn=lambda p: "hibernate dev", output_fn=out.append)


def test_confirm_gate_wrong_phrase_declines():
    out = []
    assert not cli.confirm_gate(command="hibernate", environment_name="dev", yes=False,
                                input_fn=lambda p: "yes", output_fn=out.append)


def test_confirm_gate_yes_flag_bypasses_prompt():
    out = []
    called = {"n": 0}

    def _input(p):
        called["n"] += 1
        return ""

    assert cli.confirm_gate(command="wake", environment_name="prod", yes=True,
                            input_fn=_input, output_fn=out.append)
    assert called["n"] == 0                       # never prompted
    assert any("recorded confirmation token" in line for line in out)
