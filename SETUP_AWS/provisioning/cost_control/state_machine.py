"""Sleep/wake state machine (Task 13).

Composes the per-tier sleep/wake logic (Wave 2) under the authoritative
State_File (Wave 1) into the two operator commands. It owns:

* the legal transition table (R7 idempotency + concurrency refusal),
* the fixed hibernate order EC2 -> Neptune -> OpenSearch -> AgentCore -> NAT
  and its reverse on wake,
* ``--resume`` from a degraded state using each tier's idempotent
  ``is_asleep()`` skip,
* the confirmation gate result (the interactive prompt itself lives in the
  CLI; the machine refuses to issue any destructive call unless ``confirmed``
  -- Property 6),
* drift evaluation and the wake validation probe wiring,
* savings figures on ``Sleep_Completed`` / ``Wake_Completed`` and the wake
  wall-clock budget with per-tier progress records (R6.2, R6.3).

State writes go through a state-file object exposing ``read() ->
(doc, etag)`` and ``write(doc, etag) -> etag`` (the Wave 1 ``StateFile`` or an
in-memory test double). A stale-ETag :class:`ConcurrentOperationError` maps to
``Concurrent_Operation_Refused`` (Property 7).

ASCII-only console output via the audit logger.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from cost_control.state_file import (
    ConcurrentOperationError,
    MissingStateError,
    bump,
    new_initial_document,
)
from cost_control.tiers import PlannedAction

# -- transition decisions ----------------------------------------------------
PROCEED = "proceed"
NOOP = "noop"
REFUSE_CONCURRENT = "refuse_concurrent"
REQUIRE_RESUME = "require_resume"
ILLEGAL = "illegal"

# -- exit codes --------------------------------------------------------------
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_REFUSED = 2

_TRANSIENT = ("Sleeping", "Waking")
_DEGRADED = ("Active_Mode_Degraded", "Sleep_State_Degraded")

#: Default wake wall-clock budget (R6.3 default 90 min) and progress cadence
#: (R6.2 every <= 5 min).
DEFAULT_WAKE_BUDGET_S: float = 90 * 60.0
DEFAULT_PROGRESS_INTERVAL_S: float = 5 * 60.0


def plan_transition(command: str, current_state: str, resume: bool = False) -> str:
    """Classify a (command, current_state, resume) request.

    Returns one of :data:`PROCEED`, :data:`NOOP`, :data:`REFUSE_CONCURRENT`,
    :data:`REQUIRE_RESUME`, :data:`ILLEGAL`. This is the single source of truth
    for transition legality and is unit-tested across every combination.
    """
    if current_state in _TRANSIENT:
        return REFUSE_CONCURRENT

    if command == "hibernate":
        if current_state == "Sleep_State":
            return NOOP
        if current_state in ("Active_Mode", "Wake_State"):
            return PROCEED
        if current_state == "Active_Mode_Degraded":
            return PROCEED if resume else REQUIRE_RESUME
        return ILLEGAL  # Sleep_State_Degraded -> wrong command

    if command == "wake":
        if current_state in ("Wake_State", "Active_Mode"):
            return NOOP
        if current_state == "Sleep_State":
            return PROCEED
        if current_state == "Sleep_State_Degraded":
            return PROCEED if resume else REQUIRE_RESUME
        return ILLEGAL  # Active_Mode_Degraded -> wrong command

    return ILLEGAL


@dataclass
class OperationResult:
    """Outcome of a hibernate/wake/status invocation."""

    success: bool
    final_state: str
    exit_code: int
    message: str


def _utcnow_iso(now: datetime) -> str:
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class StateMachine:
    """Orchestrates hibernate / wake across the ordered tiers."""

    def __init__(
        self,
        *,
        environment_name: str,
        state_file: Any,
        audit: Any,
        tiers: list[Any],
        cost_model: Any,
        caller_arn: str,
        operation_id: str,
        wake_probe_fn: Optional[Callable[[dict[str, Any]], Any]] = None,
        drift_fn: Optional[Callable[[dict[str, Any], bool], tuple[bool, Any]]] = None,
        wake_budget_s: float = DEFAULT_WAKE_BUDGET_S,
        progress_interval_s: float = DEFAULT_PROGRESS_INTERVAL_S,
        time_fn: Callable[[], float] = time.monotonic,
        utcnow_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._env = environment_name
        self._sf = state_file
        self._audit = audit
        self._tiers = list(tiers)
        self._cost = cost_model
        self._caller = caller_arn
        self._op = operation_id
        self._wake_probe_fn = wake_probe_fn
        self._drift_fn = drift_fn
        self._budget = wake_budget_s
        self._progress_interval = progress_interval_s
        self._time = time_fn
        self._utcnow = utcnow_fn

    # -- helpers -----------------------------------------------------------

    def _read_or_init(self) -> tuple[dict[str, Any], Optional[str]]:
        try:
            return self._sf.read()
        except MissingStateError:
            return new_initial_document(self._env), None

    def _lock(self) -> dict[str, Any]:
        return {
            "holder": self._caller,
            "operation_id": self._op,
            "acquired_at": _utcnow_iso(self._utcnow()),
        }

    def _write_state(
        self,
        doc: dict[str, Any],
        etag: Optional[str],
        new_state: str,
        **fields: Any,
    ) -> tuple[dict[str, Any], str]:
        new_doc = bump(doc)
        new_doc["previous_state"] = doc["current_state"]
        new_doc["current_state"] = new_state
        new_doc["last_transition_at"] = _utcnow_iso(self._utcnow())
        new_doc["last_caller_arn"] = self._caller
        new_doc["environment_name"] = self._env
        new_doc.setdefault("manifest", doc.get("manifest", {}))
        new_doc.setdefault("latest_snapshots", doc.get("latest_snapshots", {}))
        new_doc["lock"] = fields.pop("lock", None)
        for key, value in fields.items():
            new_doc[key] = value
        new_etag = self._sf.write(new_doc, etag)
        return new_doc, new_etag

    def _collect_snapshots(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for rec in self._audit.records:
            if rec.get("event_type") == "Snapshot_Created" and rec.get("snapshot_ids"):
                tier = rec.get("tier") or "unknown"
                out.setdefault(tier, []).extend(rec["snapshot_ids"])
        return out

    @staticmethod
    def _failure_event(exc: Exception) -> str:
        name = type(exc).__name__
        if name == "SnapshotTimeout":
            return "Snapshot_Timeout"
        if name == "SnapshotFailure":
            return "Snapshot_Failure"
        return "Sleep_Failed"

    # -- read-only status (no lock, no mutation) ---------------------------

    def status(self) -> dict[str, Any]:
        """Return the parsed State_File without acquiring the lock (R8.5).

        Never writes. Returns a synthetic ``Active_Mode`` document if the
        State_File does not yet exist.
        """
        doc, _etag = self._read_or_init()
        return doc

    def plan_all(self, mode: str) -> list[PlannedAction]:
        """Aggregate every tier's ``plan(mode)`` -- pure, no mutation."""
        order = self._tiers if mode == "hibernate" else list(reversed(self._tiers))
        plans: list[PlannedAction] = []
        for tier in order:
            plans.extend(tier.plan(mode))
        return plans

    # -- hibernate ---------------------------------------------------------

    def hibernate(self, *, resume: bool = False, confirmed: bool = True) -> OperationResult:
        doc, etag = self._read_or_init()
        state = doc["current_state"]
        decision = plan_transition("hibernate", state, resume)

        if decision == NOOP:
            self._audit.emit("Sleep_NoOp", state_before=state, state_after=state)
            return OperationResult(True, state, EXIT_OK, "already in Sleep_State")
        if decision == REFUSE_CONCURRENT:
            self._refuse_concurrent(doc)
            return OperationResult(False, state, EXIT_REFUSED, "concurrent operation")
        if decision == REQUIRE_RESUME:
            self._audit.emit("Sleep_Failed", state_before=state, state_after=state,
                             error={"code": "ResumeRequired",
                                    "message": "degraded state requires --resume"})
            return OperationResult(False, state, EXIT_ERROR, "resume required")
        if decision == ILLEGAL:
            self._audit.emit("Sleep_Failed", state_before=state, state_after=state,
                             error={"code": "IllegalTransition",
                                    "message": f"cannot hibernate from {state}"})
            return OperationResult(False, state, EXIT_ERROR, "illegal transition")

        # PROCEED -- confirmation must precede any destructive call (Property 6).
        if not confirmed:
            self._audit.emit("Confirmation_Declined", state_before=state, state_after=state)
            return OperationResult(True, state, EXIT_OK, "confirmation declined")

        fresh_start = state in ("Active_Mode", "Wake_State")
        try:
            doc, etag = self._write_state(doc, etag, "Sleeping", lock=self._lock())
        except ConcurrentOperationError:
            self._refuse_concurrent(doc)
            return OperationResult(False, state, EXIT_REFUSED, "concurrent operation")

        if fresh_start:
            doc["manifest"] = {t.name: t.capture_manifest() for t in self._tiers}

        op_start = self._time()
        self._audit.emit("Sleep_Started", state_before=state, state_after="Sleeping")

        destructive_began = False
        for tier in self._tiers:
            try:
                if resume and tier.is_asleep():
                    self._audit.emit("Tier_Skipped", tier=tier.name,
                                     state_before="Sleeping", state_after="Sleeping")
                    continue
                actions = tier.hibernate()
                if any(a.destructive for a in actions):
                    destructive_began = True
            except Exception as exc:  # noqa: BLE001 -- map any tier failure
                target = "Active_Mode_Degraded" if destructive_began else "Active_Mode"
                doc, etag = self._write_state(doc, etag, target, lock=None)
                self._audit.emit(self._failure_event(exc), tier=tier.name,
                                 state_before="Sleeping", state_after=target,
                                 error={"code": type(exc).__name__, "message": str(exc)})
                return OperationResult(False, target, EXIT_ERROR,
                                       f"hibernate failed at {tier.name}")

        latest = self._collect_snapshots()
        doc, etag = self._write_state(doc, etag, "Sleep_State", lock=None,
                                      latest_snapshots=latest, manifest=doc["manifest"])
        elapsed = self._time() - op_start
        self._audit.emit("Sleep_Completed", state_before="Sleeping",
                         state_after="Sleep_State", elapsed_seconds=elapsed,
                         estimated_savings_usd_per_hour=self._cost.estimated_savings_usd_per_hour(),
                         snapshot_ids=[s for ids in latest.values() for s in ids])
        return OperationResult(True, "Sleep_State", EXIT_OK, "platform asleep")

    # -- wake --------------------------------------------------------------

    def wake(self, *, resume: bool = False, force_drift: bool = False,
             confirmed: bool = True) -> OperationResult:
        doc, etag = self._read_or_init()
        state = doc["current_state"]
        decision = plan_transition("wake", state, resume)

        if decision == NOOP:
            self._audit.emit("Wake_NoOp", state_before=state, state_after=state)
            return OperationResult(True, state, EXIT_OK, "already awake")
        if decision == REFUSE_CONCURRENT:
            self._refuse_concurrent(doc)
            return OperationResult(False, state, EXIT_REFUSED, "concurrent operation")
        if decision == REQUIRE_RESUME:
            self._audit.emit("Wake_Failed", state_before=state, state_after=state,
                             error={"code": "ResumeRequired",
                                    "message": "degraded state requires --resume"})
            return OperationResult(False, state, EXIT_ERROR, "resume required")
        if decision == ILLEGAL:
            self._audit.emit("Wake_Failed", state_before=state, state_after=state,
                             error={"code": "IllegalTransition",
                                    "message": f"cannot wake from {state}"})
            return OperationResult(False, state, EXIT_ERROR, "illegal transition")

        if not confirmed:
            self._audit.emit("Confirmation_Declined", state_before=state, state_after=state)
            return OperationResult(True, state, EXIT_OK, "confirmation declined")

        manifest = doc.get("manifest", {})

        # Drift evaluation BEFORE any compute is created (R10.3).
        if self._drift_fn is not None:
            proceed, result = self._drift_fn(manifest, force_drift)
            if getattr(result, "preserving", None):
                self._audit.emit("Drift_Reconciled", state_before=state, state_after=state)
            if not proceed:
                self._audit.emit("Drift_Detected", state_before=state, state_after="Sleep_State",
                                 error={"code": "DriftDetected",
                                        "message": "destructive drift; rerun with --force-drift"})
                return OperationResult(False, "Sleep_State", EXIT_ERROR, "drift detected")

        sleep_started = _parse_iso(doc.get("last_transition_at"))
        try:
            doc, etag = self._write_state(doc, etag, "Waking", lock=self._lock())
        except ConcurrentOperationError:
            self._refuse_concurrent(doc)
            return OperationResult(False, state, EXIT_REFUSED, "concurrent operation")

        op_start = self._time()
        self._audit.emit("Wake_Started", state_before=state, state_after="Waking")

        for tier in reversed(self._tiers):
            elapsed = self._time() - op_start
            if elapsed > self._budget:
                doc, etag = self._write_state(doc, etag, "Sleep_State_Degraded", lock=None)
                self._audit.emit("Wake_Timeout", tier=tier.name, state_before="Waking",
                                 state_after="Sleep_State_Degraded", elapsed_seconds=elapsed,
                                 error={"code": "WakeTimeout",
                                        "message": f"exceeded {self._budget:.0f}s budget"})
                return OperationResult(False, "Sleep_State_Degraded", EXIT_ERROR,
                                       "wake exceeded budget")
            self._audit.emit("Wake_Progress", tier=tier.name, state_before="Waking",
                             state_after="Waking", elapsed_seconds=elapsed)
            try:
                if resume and not tier.is_asleep():
                    self._audit.emit("Tier_Skipped", tier=tier.name,
                                     state_before="Waking", state_after="Waking")
                    continue
                tier.wake()
            except Exception as exc:  # noqa: BLE001
                doc, etag = self._write_state(doc, etag, "Sleep_State_Degraded", lock=None)
                self._audit.emit("Wake_Failed", tier=tier.name, state_before="Waking",
                                 state_after="Sleep_State_Degraded",
                                 error={"code": type(exc).__name__, "message": str(exc)})
                return OperationResult(False, "Sleep_State_Degraded", EXIT_ERROR,
                                       f"wake failed at {tier.name}")

        # Wake validation probe (R12.4).
        if self._wake_probe_fn is not None:
            try:
                self._wake_probe_fn(manifest)
            except Exception as exc:  # noqa: BLE001 -- WakeProbeError et al.
                doc, etag = self._write_state(doc, etag, "Sleep_State_Degraded", lock=None)
                self._audit.emit("Wake_Failed", state_before="Waking",
                                 state_after="Sleep_State_Degraded",
                                 error={"code": type(exc).__name__, "message": str(exc)})
                return OperationResult(False, "Sleep_State_Degraded", EXIT_ERROR,
                                       "wake validation probe failed")

        elapsed = self._time() - op_start
        window_savings = self._window_savings(sleep_started)
        doc, etag = self._write_state(doc, etag, "Wake_State", lock=None)
        # For Wake_Completed the savings field carries the TOTAL accumulated
        # USD over the sleep window (R5.4 = per-hour * sleep duration);
        # elapsed_seconds is the wake wall-clock (R2.4).
        self._audit.emit("Wake_Completed", state_before="Waking", state_after="Wake_State",
                         elapsed_seconds=elapsed,
                         estimated_savings_usd_per_hour=window_savings)
        return OperationResult(True, "Wake_State", EXIT_OK, "platform awake")

    # -- shared ------------------------------------------------------------

    def _window_savings(self, sleep_started: Optional[datetime]) -> float:
        if sleep_started is None:
            return 0.0
        now = self._utcnow()
        if sleep_started.tzinfo is None:
            sleep_started = sleep_started.replace(tzinfo=timezone.utc)
        seconds = (now - sleep_started).total_seconds()
        return self._cost.window_savings_usd(max(seconds, 0.0))

    def _refuse_concurrent(self, doc: dict[str, Any]) -> None:
        self._audit.emit(
            "Concurrent_Operation_Refused",
            state_before=doc["current_state"],
            state_after=doc["current_state"],
            error={"code": "ConcurrentOperation",
                   "message": f"operation in progress (state={doc['current_state']}, "
                              f"holder={doc.get('last_caller_arn')})"},
        )
