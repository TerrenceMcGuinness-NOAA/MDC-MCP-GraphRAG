"""Unit tests for :mod:`src.sdd.session_manager` (Requirements 9.2 – 9.5).

Concrete example-based tests complementing the Hypothesis properties in
``tests/properties/test_sdd_session_props.py``. Focus areas:

* session lifecycle (start / record / complete / abandon / resume)
* examined / modifications / checkpoint / restore state tracking
* JSONL on-disk format compatibility with Node.js SessionManager.js
* error paths (double-start, missing session, unknown checkpoint, duplicate
  step)
"""

from __future__ import annotations

import json
import threading
from itertools import count
from pathlib import Path

import pytest

from src.sdd import (
    STATUS_ABANDONED,
    STATUS_ACTIVE,
    STATUS_COMPLETED,
    SessionError,
    SessionManager,
)

pytestmark = pytest.mark.unit


# ── fixtures ─────────────────────────────────────────────────────────────


class _MonotonicClock:
    def __init__(self) -> None:
        self._tick = 0

    def __call__(self) -> str:
        self._tick += 1
        return f"2026-05-12T00:00:{self._tick:02d}.000Z"


def _deterministic_ids() -> "callable":
    counter = count(1)

    def factory() -> str:
        return f"id{next(counter):04d}"

    return factory


@pytest.fixture()
def sm(tmp_path: Path) -> SessionManager:
    return SessionManager(
        state_dir=tmp_path,
        clock=_MonotonicClock(),
        id_factory=_deterministic_ids(),
    )


# ── initialization ──────────────────────────────────────────────────────


def test_state_directory_is_created_on_init(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "state"
    sm = SessionManager(state_dir=target)
    assert target.is_dir()
    assert (target / "checkpoints").is_dir()
    assert sm.get_session_state() is None


def test_reading_active_session_before_start_returns_none(
    sm: SessionManager,
) -> None:
    assert sm.get_session_state() is None


def test_get_session_context_when_no_active_session(
    sm: SessionManager,
) -> None:
    ctx = sm.get_session_context()
    assert ctx == {"active": False, "message": "No active session."}


# ── start_session ───────────────────────────────────────────────────────


def test_start_session_creates_active_session_file(
    sm: SessionManager, tmp_path: Path
) -> None:
    session = sm.start_session("phase_test", total_steps=5, notes="hello")
    assert session.phase == "phase_test"
    assert session.totalSteps == 5
    assert session.notes == "hello"
    assert session.status == STATUS_ACTIVE
    assert session.sessionId.startswith("session_2026-05-12_")

    # Persisted to disk in the same JSON shape the Node.js server writes.
    active = json.loads((tmp_path / "active_session.json").read_text())
    assert active["phase"] == "phase_test"
    assert active["sessionId"] == session.sessionId
    assert active["status"] == STATUS_ACTIVE
    assert "completedSteps" in active


def test_start_session_appends_started_event(
    sm: SessionManager, tmp_path: Path
) -> None:
    sm.start_session("phase_test")
    line = (tmp_path / "history.jsonl").read_text().strip().splitlines()[-1]
    entry = json.loads(line)
    assert entry["event"] == "started"
    assert entry["phase"] == "phase_test"
    assert entry["sessionId"].startswith("session_2026-05-12_")


def test_start_session_rejects_concurrent_active_session(
    sm: SessionManager,
) -> None:
    sm.start_session("first")
    with pytest.raises(SessionError, match="Active session already exists"):
        sm.start_session("second")


def test_start_session_requires_phase_name(sm: SessionManager) -> None:
    with pytest.raises(SessionError, match="phase_name"):
        sm.start_session("")


# ── record_step ─────────────────────────────────────────────────────────


def test_record_step_appends_completed_step(sm: SessionManager) -> None:
    sm.start_session("phase_test", total_steps=3)
    sm.record_step(1, "first", "research", "done")
    sm.record_step(2, "second", "implement")

    state = sm.get_session_state()
    assert state is not None
    assert state.currentStep == 2
    assert [s["step"] for s in state.completedSteps] == [1, 2]
    assert state.completedSteps[0]["tag"] == "research"
    assert state.completedSteps[0]["notes"] == "done"


def test_record_step_duplicate_raises(sm: SessionManager) -> None:
    sm.start_session("phase_test")
    sm.record_step(1, "first", "research")
    with pytest.raises(SessionError, match="already recorded"):
        sm.record_step(1, "dup", "research")


def test_record_step_without_active_session_raises(
    sm: SessionManager,
) -> None:
    with pytest.raises(SessionError, match="No active session"):
        sm.record_step(1, "nope", "research")


def test_record_step_with_unknown_tag_is_accepted_with_warning(
    sm: SessionManager, caplog: pytest.LogCaptureFixture
) -> None:
    sm.start_session("phase_test")
    with caplog.at_level("WARNING"):
        sm.record_step(1, "odd", "not_a_real_tag")
    state = sm.get_session_state()
    assert state is not None
    assert state.completedSteps[0]["tag"] == "not_a_real_tag"
    assert any("Unknown step tag" in r.message for r in caplog.records)


def test_record_step_empty_tag_defaults_to_implement(sm: SessionManager) -> None:
    sm.start_session("phase_test")
    sm.record_step(1, "no-tag", "")
    state = sm.get_session_state()
    assert state is not None
    assert state.completedSteps[0]["tag"] == "implement"


def test_record_step_appends_history_event(
    sm: SessionManager, tmp_path: Path
) -> None:
    sm.start_session("phase_test")
    sm.record_step(1, "first", "research", "ok")

    lines = (tmp_path / "history.jsonl").read_text().strip().splitlines()
    step_event = json.loads(lines[-1])
    assert step_event["event"] == "step_completed"
    assert step_event["step"] == 1
    assert step_event["name"] == "first"
    assert step_event["tag"] == "research"
    assert step_event["notes"] == "ok"


# ── examine_symbol / mark_modified ──────────────────────────────────────


def test_examine_symbol_deduplicates(sm: SessionManager) -> None:
    sm.start_session("phase_test")
    sm.examine_symbol("foo.bar")
    sm.examine_symbol("foo.bar")  # dup — should be a no-op
    sm.examine_symbol("baz")

    state = sm.get_session_state()
    assert state is not None
    assert [e["symbol"] for e in state.examined] == ["foo.bar", "baz"]


def test_examine_symbol_without_session_is_silent(
    sm: SessionManager, caplog: pytest.LogCaptureFixture
) -> None:
    # Matches Node.js behaviour: tool layer opportunistically calls this
    # and must not crash when there's no active session.
    assert sm.examine_symbol("orphan") is None


def test_mark_modified_appends_every_call(sm: SessionManager) -> None:
    sm.start_session("phase_test")
    sm.mark_modified("a.py", "content", "first edit")
    sm.mark_modified("a.py", "content", "second edit")
    sm.mark_modified("b.py", "rename")

    state = sm.get_session_state()
    assert state is not None
    assert len(state.modifications) == 3
    assert state.modifications[0]["description"] == "first edit"
    assert state.modifications[2]["changeType"] == "rename"


def test_mark_modified_requires_file_path(sm: SessionManager) -> None:
    sm.start_session("phase_test")
    with pytest.raises(SessionError, match="file_path"):
        sm.mark_modified("")


def test_mark_modified_warns_on_unknown_change_type(
    sm: SessionManager, caplog: pytest.LogCaptureFixture
) -> None:
    sm.start_session("phase_test")
    with caplog.at_level("WARNING"):
        sm.mark_modified("x.py", "whatever")
    assert any("Unknown changeType" in r.message for r in caplog.records)


# ── checkpoint / restore ────────────────────────────────────────────────


def test_checkpoint_state_creates_file_and_updates_session(
    sm: SessionManager, tmp_path: Path
) -> None:
    sm.start_session("phase_test")
    sm.examine_symbol("foo")
    sm.mark_modified("a.py", "content")

    checkpoint = sm.checkpoint_state("c1", "halfway")
    assert checkpoint.checkpointId.startswith("chk_2026-05-12_")

    # Checkpoint file written with the stored snapshot.
    cp_file = tmp_path / "checkpoints" / f"{checkpoint.checkpointId}.json"
    assert cp_file.is_file()
    data = json.loads(cp_file.read_text())
    assert data["name"] == "c1"
    assert [e["symbol"] for e in data["examined"]] == ["foo"]
    assert [m["filePath"] for m in data["modifications"]] == ["a.py"]

    # Session gained a checkpoint summary entry.
    state = sm.get_session_state()
    assert state is not None
    assert len(state.checkpoints) == 1
    assert state.checkpoints[0]["checkpointId"] == checkpoint.checkpointId


def test_restore_checkpoint_reverts_examined_and_modifications(
    sm: SessionManager,
) -> None:
    sm.start_session("phase_test")
    sm.examine_symbol("before")
    sm.mark_modified("a.py", "content")

    checkpoint = sm.checkpoint_state("snap", "")
    sm.examine_symbol("after")
    sm.mark_modified("b.py", "content")

    sm.restore_checkpoint(checkpoint.checkpointId)
    state = sm.get_session_state()
    assert state is not None
    assert [e["symbol"] for e in state.examined] == ["before"]
    assert [m["filePath"] for m in state.modifications] == ["a.py"]


def test_restore_unknown_checkpoint_raises(sm: SessionManager) -> None:
    sm.start_session("phase_test")
    with pytest.raises(SessionError, match="not found"):
        sm.restore_checkpoint("chk_does_not_exist")


# ── complete / abandon ──────────────────────────────────────────────────


def test_complete_session_writes_history_and_removes_active_file(
    sm: SessionManager, tmp_path: Path
) -> None:
    sm.start_session("phase_test", total_steps=2)
    sm.record_step(1, "a", "research")
    final = sm.complete_session("wrap-up")

    assert final.status == STATUS_COMPLETED
    assert final.summary == "wrap-up"
    assert not (tmp_path / "active_session.json").exists()

    last = (tmp_path / "history.jsonl").read_text().strip().splitlines()[-1]
    event = json.loads(last)
    assert event["event"] == "completed"
    assert event["summary"] == "wrap-up"
    assert event["completedSteps"] == 1
    assert "duration" in event


def test_abandon_session_marks_abandoned_and_removes_file(
    sm: SessionManager, tmp_path: Path
) -> None:
    sm.start_session("phase_test")
    final = sm.abandon_session("blocked")

    assert final.status == STATUS_ABANDONED
    assert final.abandonReason == "blocked"
    assert not (tmp_path / "active_session.json").exists()

    last = (tmp_path / "history.jsonl").read_text().strip().splitlines()[-1]
    event = json.loads(last)
    assert event["event"] == "abandoned"
    assert event["reason"] == "blocked"


def test_complete_without_active_session_raises(sm: SessionManager) -> None:
    with pytest.raises(SessionError, match="No active session"):
        sm.complete_session()


def test_abandon_without_active_session_raises(sm: SessionManager) -> None:
    with pytest.raises(SessionError, match="No active session"):
        sm.abandon_session()


# ── resume ──────────────────────────────────────────────────────────────


def test_resume_session_updates_last_activity(
    sm: SessionManager, tmp_path: Path
) -> None:
    sm.start_session("phase_test")
    # Simulate a server restart: create a fresh SessionManager, read state.
    sm2 = SessionManager(
        state_dir=tmp_path,
        clock=_MonotonicClock(),
        id_factory=_deterministic_ids(),
    )
    resumed = sm2.resume_session()
    assert resumed.status == STATUS_ACTIVE

    # Last event should be 'resumed'.
    lines = (tmp_path / "history.jsonl").read_text().strip().splitlines()
    event = json.loads(lines[-1])
    assert event["event"] == "resumed"


def test_resume_without_active_session_raises(sm: SessionManager) -> None:
    with pytest.raises(SessionError, match="No active session to resume"):
        sm.resume_session()


# ── JSONL format parity with Node.js ────────────────────────────────────


def test_history_jsonl_events_are_one_object_per_line(
    sm: SessionManager, tmp_path: Path
) -> None:
    sm.start_session("phase_test")
    sm.record_step(1, "a", "research")
    sm.mark_modified("x.py", "content")
    sm.examine_symbol("sym")
    chk = sm.checkpoint_state("cp1", "")
    sm.restore_checkpoint(chk.checkpointId)
    sm.complete_session("done")

    lines = (tmp_path / "history.jsonl").read_text().splitlines()
    events = [json.loads(line) for line in lines if line.strip()]
    event_names = [e["event"] for e in events]
    assert event_names == [
        "started",
        "step_completed",
        "file_modified",
        "symbol_examined",
        "checkpoint_created",
        "checkpoint_restored",
        "completed",
    ]
    # Every event carries sessionId + phase + timestamp, matching the
    # Node.js writer.
    for e in events:
        assert "sessionId" in e
        assert "phase" in e
        assert "timestamp" in e
        assert e["timestamp"].endswith("Z")


def test_active_session_json_has_expected_top_level_keys(
    sm: SessionManager, tmp_path: Path
) -> None:
    sm.start_session("phase_test", total_steps=2)
    sm.record_step(1, "a", "research")
    active = json.loads((tmp_path / "active_session.json").read_text())
    required = {
        "sessionId",
        "phase",
        "startedAt",
        "lastActivityAt",
        "status",
        "currentStep",
        "totalSteps",
        "completedSteps",
        "modifications",
        "examined",
        "checkpoints",
    }
    assert required.issubset(active.keys())
    # Optional lifecycle fields absent until transition happens.
    for optional in ("completedAt", "abandonedAt", "summary", "abandonReason"):
        assert optional not in active


# ── get_history filtering ──────────────────────────────────────────────


def test_get_history_filters_by_event(sm: SessionManager) -> None:
    sm.start_session("phase_test", total_steps=3)
    sm.record_step(1, "a", "research")
    sm.record_step(2, "b", "implement")
    sm.record_step(3, "c", "validate")
    completed = sm.get_history(event="step_completed")
    assert len(completed) == 3
    assert all(e["event"] == "step_completed" for e in completed)


def test_get_history_filters_by_phase_substring(
    sm: SessionManager,
) -> None:
    sm.start_session("phase_foo")
    sm.complete_session()
    sm.start_session("phase_bar")
    matched = sm.get_history(phase="foo")
    assert matched
    assert all("foo" in (e.get("phase") or "") for e in matched)


def test_get_history_limit_returns_tail(sm: SessionManager) -> None:
    sm.start_session("phase_test", total_steps=5)
    for i in range(1, 6):
        sm.record_step(i, f"step{i}", "implement")
    tail = sm.get_history(limit=2)
    assert len(tail) == 2
    # Should be the last two history entries (step 4 and 5).
    assert tail[-1]["event"] == "step_completed"
    assert tail[-1]["step"] == 5


# ── serialize / deserialize ────────────────────────────────────────────


def test_serialize_deserialize_round_trip_preserves_fields(
    sm: SessionManager,
) -> None:
    session = sm.start_session("phase_test", total_steps=4, notes="n")
    sm.record_step(1, "first", "research", "r")
    sm.mark_modified("a.py", "content", "d")
    sm.examine_symbol("sym")

    current = sm.get_session_state()
    assert current is not None
    payload = SessionManager.serialize_session(current)
    restored = SessionManager.deserialize_session(payload)
    assert restored.to_dict() == current.to_dict()


def test_deserialize_ignores_unknown_keys(sm: SessionManager) -> None:
    payload = json.dumps(
        {
            "sessionId": "session_2099_test",
            "phase": "future_phase",
            "startedAt": "2099-01-01T00:00:00.000Z",
            "lastActivityAt": "2099-01-01T00:00:00.000Z",
            "status": STATUS_ACTIVE,
            "futureField": "ignored",
        }
    )
    restored = SessionManager.deserialize_session(payload)
    assert restored.sessionId == "session_2099_test"
    assert restored.phase == "future_phase"


def test_deserialize_rejects_non_object() -> None:
    with pytest.raises(ValueError):
        SessionManager.deserialize_session("[]")


# ── thread safety smoke test ───────────────────────────────────────────


def test_concurrent_record_step_is_serialized(sm: SessionManager) -> None:
    """Running record_step from multiple threads should not corrupt state.

    Thread safety isn't a strict requirement from the spec but it is a
    property the Python port explicitly advertises via ``threading.Lock``,
    so we guard the guarantee.
    """
    sm.start_session("phase_test", total_steps=20)
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            sm.record_step(i, f"step{i}", "implement")
        except BaseException as exc:  # pragma: no cover - diagnostic
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(1, 11)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    state = sm.get_session_state()
    assert state is not None
    assert len(state.completedSteps) == 10
    steps = sorted(s["step"] for s in state.completedSteps)
    assert steps == list(range(1, 11))
