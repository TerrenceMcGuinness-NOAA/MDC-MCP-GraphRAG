"""Property tests for the SDD session manager.

Feature: python-mcp-server-port

Property 10: Session State Consistency (Requirement 6.7)
    For any sequence of session operations (examine_symbol, mark_modified,
    checkpoint, restore_checkpoint) applied to an initially empty session,
    the session state SHALL be consistent:
      (a) examined reflects exactly the symbols examined,
      (b) modifications reflects exactly the files marked modified,
      (c) restoring a checkpoint restores state to the checkpoint's snapshot.

Property 11: SDD Session Lifecycle Round-Trip (Requirements 9.5, 9.7)
    For any valid lifecycle (start → record N steps → complete/abandon),
    serialize/deserialize produces an equivalent session object.
"""

from __future__ import annotations

import copy
import json
import tempfile
from dataclasses import asdict
from itertools import count
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.sdd import (
    STATUS_ACTIVE,
    STATUS_ABANDONED,
    STATUS_COMPLETED,
    VALID_CHANGE_TYPES,
    VALID_TAGS,
    SDDSession,
    SessionManager,
)

pytestmark = pytest.mark.property


# ── deterministic clock + id factory for reproducible tests ─────────────


class _FakeClock:
    """Strictly monotonic ISO-8601 clock starting at a fixed base date."""

    def __init__(self, start: str = "2026-01-01T00:00:00.000Z") -> None:
        # Stored as a parseable datetime-ish string but incremented by
        # seconds. Encodes the monotonicity Property 10 relies on.
        self._base = start
        self._tick = 0

    def __call__(self) -> str:
        self._tick += 1
        hours = self._tick // 3600
        minutes = (self._tick // 60) % 60
        seconds = self._tick % 60
        return (
            f"2026-01-01T{hours:02d}:{minutes:02d}:{seconds:02d}.000Z"
        )


def _id_factory_for_tests() -> "callable":
    counter = count(1)

    def factory() -> str:
        return f"test{next(counter):06d}"

    return factory


def _fresh_manager() -> tuple[SessionManager, tempfile.TemporaryDirectory]:
    """Build a SessionManager backed by a *new* temp directory.

    Hypothesis re-enters each ``@given`` test many times with new inputs;
    a function-scoped fixture would be shared across those entries and
    leak an ``active_session.json`` from one iteration into the next.
    This helper guarantees each iteration gets a clean state dir. The
    caller owns the ``TemporaryDirectory`` and MUST close it when done
    (we do so in a ``try/finally`` in every test below).
    """
    td = tempfile.TemporaryDirectory()
    manager = SessionManager(
        state_dir=td.name,
        clock=_FakeClock(),
        id_factory=_id_factory_for_tests(),
    )
    return manager, td


# ── strategies ───────────────────────────────────────────────────────────


_symbol_strategy = st.text(
    alphabet=st.characters(
        min_codepoint=0x21, max_codepoint=0x7E, blacklist_characters='"\\'
    ),
    min_size=1,
    max_size=30,
)

_filepath_strategy = st.text(
    alphabet=st.characters(
        min_codepoint=0x21, max_codepoint=0x7E, blacklist_characters='"\\'
    ),
    min_size=1,
    max_size=60,
)

_tag_strategy = st.sampled_from(sorted(VALID_TAGS))
_change_type_strategy = st.sampled_from(sorted(VALID_CHANGE_TYPES))

_step_notes_strategy = st.text(
    alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E),
    max_size=80,
)


# Operations for Property 10 — each is a ``(op, payload)`` tuple.
_operation_strategy = st.one_of(
    st.tuples(st.just("examine"), _symbol_strategy),
    st.tuples(
        st.just("modify"),
        st.tuples(_filepath_strategy, _change_type_strategy),
    ),
    st.tuples(st.just("checkpoint"), st.just(None)),
)


# ── Property 10a: examined reflects unique symbols examined ─────────────


@settings(
    max_examples=60,
    deadline=None,
)
@given(symbols=st.lists(_symbol_strategy, min_size=0, max_size=15))
def test_examined_list_reflects_unique_examinations(
    symbols: list[str],
) -> None:
    """After N examine_symbol calls, examined == unique(symbols) in order."""
    manager, td = _fresh_manager()
    try:
        manager.start_session("test_phase", total_steps=0)
        for sym in symbols:
            manager.examine_symbol(sym)

        state = manager.get_session_state()
        assert state is not None
        recorded = [e["symbol"] for e in state.examined]

        # De-duplication should preserve first-seen order.
        seen: list[str] = []
        for s in symbols:
            if s not in seen:
                seen.append(s)
        assert recorded == seen
    finally:
        td.cleanup()


# ── Property 10b: modifications reflect every mark_modified call ────────


@settings(
    max_examples=60,
    deadline=None,
)
@given(
    mods=st.lists(
        st.tuples(_filepath_strategy, _change_type_strategy),
        min_size=0,
        max_size=15,
    )
)
def test_modifications_list_reflects_all_mark_modified(
    mods: list[tuple[str, str]],
) -> None:
    """modifications is the ordered list of every file marked modified.

    Unlike examined, duplicates are *preserved* — the same file may be
    legitimately modified multiple times.
    """
    manager, td = _fresh_manager()
    try:
        manager.start_session("test_phase", total_steps=0)
        for path, change_type in mods:
            manager.mark_modified(path, change_type)

        state = manager.get_session_state()
        assert state is not None
        assert len(state.modifications) == len(mods)
        for recorded, (path, change_type) in zip(state.modifications, mods):
            assert recorded["filePath"] == path
            assert recorded["changeType"] == change_type
    finally:
        td.cleanup()


# ── Property 10c: restore_checkpoint rewinds examined + modifications ──


@settings(
    max_examples=40,
    deadline=None,
)
@given(
    pre=st.lists(_operation_strategy, min_size=1, max_size=8),
    post=st.lists(_operation_strategy, min_size=0, max_size=8),
)
def test_restore_checkpoint_reverts_state(
    pre: list[tuple[str, Any]],
    post: list[tuple[str, Any]],
) -> None:
    """Creating a checkpoint then mutating then restoring rewinds state."""
    manager, td = _fresh_manager()
    try:
        manager.start_session("test_phase", total_steps=0)
        _apply_ops(manager, pre)

        checkpoint = manager.checkpoint_state("midway", "capture pre state")
        before = manager.get_session_state()
        assert before is not None
        before_examined = copy.deepcopy(before.examined)
        before_modifications = copy.deepcopy(before.modifications)

        _apply_ops(manager, post)

        manager.restore_checkpoint(checkpoint.checkpointId)
        after = manager.get_session_state()
        assert after is not None

        # examined and modifications must match the pre-checkpoint snapshot.
        assert after.examined == before_examined
        assert after.modifications == before_modifications
    finally:
        td.cleanup()


# ── Property 11: lifecycle round-trip ───────────────────────────────────


@st.composite
def _step_records(draw, step_number: int) -> dict[str, Any]:
    return {
        "step": step_number,
        "name": draw(
            st.text(
                alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E),
                min_size=1,
                max_size=30,
            )
        ),
        "tag": draw(_tag_strategy),
        "notes": draw(_step_notes_strategy),
    }


@st.composite
def _session_scenario(draw):
    """Generate a (phase, total_steps, [step_records], terminal) tuple."""
    phase = draw(
        st.text(
            alphabet=st.characters(
                min_codepoint=ord("a"),
                max_codepoint=ord("z"),
                whitelist_characters="0123456789_",
            ),
            min_size=1,
            max_size=30,
        )
    )
    n = draw(st.integers(min_value=0, max_value=6))
    # steps are sequential and unique per the record_step invariant.
    steps = [draw(_step_records(step_number=i + 1)) for i in range(n)]
    total_steps = draw(st.integers(min_value=n, max_value=max(n, 10)))
    terminal = draw(st.sampled_from(["complete", "abandon", "active"]))
    terminal_note = draw(_step_notes_strategy)
    return phase, total_steps, steps, terminal, terminal_note


@settings(
    max_examples=40,
    deadline=None,
)
@given(scenario=_session_scenario())
def test_lifecycle_serialize_deserialize_round_trip(
    scenario,
) -> None:
    """start → record N steps → terminal → serialize / deserialize == original."""
    phase, total_steps, steps, terminal, terminal_note = scenario

    manager, td = _fresh_manager()
    try:
        manager.start_session(phase, total_steps=total_steps)
        for s in steps:
            manager.record_step(s["step"], s["name"], s["tag"], s["notes"])

        if terminal == "complete":
            final = manager.complete_session(terminal_note)
            assert final.status == STATUS_COMPLETED
        elif terminal == "abandon":
            final = manager.abandon_session(terminal_note)
            assert final.status == STATUS_ABANDONED
        else:
            final = manager.get_session_state()
            assert final is not None
            assert final.status == STATUS_ACTIVE

        payload = SessionManager.serialize_session(final)
        restored = SessionManager.deserialize_session(payload)

        # Dataclass equality would require frozen=True; compare dicts instead.
        assert restored.to_dict() == final.to_dict()

        # Phase, status, totalSteps, and step records all survive.
        assert restored.phase == phase
        assert restored.totalSteps == total_steps
        assert len(restored.completedSteps) == len(steps)
        for recorded, original in zip(restored.completedSteps, steps):
            assert recorded["step"] == original["step"]
            assert recorded["name"] == original["name"]
            assert recorded["tag"] == original["tag"]
            assert recorded["notes"] == original["notes"]
    finally:
        td.cleanup()


# ── Property 11b: the on-disk JSONL format is itself round-trippable ────


@settings(max_examples=20, deadline=None)
@given(scenario=_session_scenario())
def test_serialized_form_is_valid_json(scenario) -> None:
    """serialize_session always emits parseable JSON."""
    phase, total_steps, _steps, _terminal, _note = scenario
    session = SDDSession(
        sessionId="session_2026-01-01_abc123",
        phase=phase,
        startedAt="2026-01-01T00:00:00.000Z",
        lastActivityAt="2026-01-01T00:00:00.000Z",
        totalSteps=total_steps,
    )
    payload = SessionManager.serialize_session(session)
    # Parseable as JSON and yields a dict with at least the required keys.
    parsed = json.loads(payload)
    assert isinstance(parsed, dict)
    for required in ("sessionId", "phase", "startedAt", "status"):
        assert required in parsed


# ── helpers ─────────────────────────────────────────────────────────────


def _apply_ops(manager: SessionManager, ops: list[tuple[str, Any]]) -> None:
    """Apply a Hypothesis-generated sequence of state ops to ``manager``."""
    for op, payload in ops:
        if op == "examine":
            manager.examine_symbol(payload)
        elif op == "modify":
            path, change_type = payload
            manager.mark_modified(path, change_type)
        elif op == "checkpoint":
            # Intermediate checkpoints just exercise the code path; the
            # one Property 10c restores is created separately.
            manager.checkpoint_state("intermediate", "hypothesis op")
