"""SDD session manager (Requirements 6.7, 9.2 – 9.5).

Python port of ``mcp_server_node/src/sdd/SessionManager.js``. Tracks the
lifecycle of a single active Spec-Driven-Development session on disk via

* ``<state_dir>/active_session.json`` — the one-and-only live session,
* ``<state_dir>/history.jsonl`` — append-only event log (audit trail),
* ``<state_dir>/checkpoints/<checkpoint_id>.json`` — saved state snapshots.

The on-disk formats are byte-compatible with the Node.js implementation
so the two runtimes can share ``sdd_framework/execution_state/`` during
the Python port's phased cutover. Where the Node.js version used
``camelCase`` keys we keep camelCase — this is a data-compatibility
module, not the place to reshape field names.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import random
import string
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger(__name__)


# ── constants ─────────────────────────────────────────────────────────────

# Semantic step tags allowed by the SDD framework. Mirrors
# ``VALID_TAGS`` in SessionManager.js; an unknown tag is a warning, not
# an error, so pipelines don't break when a new tag is added.
VALID_TAGS: frozenset[str] = frozenset(
    {
        "research",
        "design",
        "implement",
        "configure",
        "validate",
        "document",
        "ingest",
    }
)

# File-modification change types the Node.js ``markAsModified`` accepts.
VALID_CHANGE_TYPES: frozenset[str] = frozenset(
    {"content", "signature", "delete", "rename"}
)

# Status values for an SDDSession.
STATUS_ACTIVE: str = "in_progress"
STATUS_COMPLETED: str = "completed"
STATUS_ABANDONED: str = "abandoned"


# ── data models ──────────────────────────────────────────────────────────


@dataclass
class SDDStep:
    """One completed SDD step (Requirement 9.3).

    Matches the Node.js ``stepRecord`` pushed onto ``completedSteps``.
    """

    step: int
    name: str
    tag: str = "implement"
    completedAt: str = ""
    notes: str = ""


@dataclass
class FileModification:
    """A file touched during the active session (Requirement 6.7).

    ``change_type`` is validated against :data:`VALID_CHANGE_TYPES` but
    unknown values are accepted with a warning to match Node.js
    behaviour (forward-compatibility with future change types).
    """

    filePath: str
    changeType: str = "content"
    description: str = ""
    modifiedAt: str = ""


@dataclass
class ExaminedSymbol:
    """Record of a symbol looked up during the session.

    Used by tools like ``get_code_context`` to mark a function/class as
    examined so downstream tools can see coverage.
    """

    symbol: str
    examinedAt: str = ""
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class Checkpoint:
    """A frozen snapshot of session state.

    The snapshot stores the fields ``restore_checkpoint`` needs to rewind
    (``modifications``, ``examined``, ``currentStep``, ``completedSteps``)
    — not the entire session object, matching Node.js semantics.
    """

    checkpointId: str
    name: str
    description: str
    createdAt: str
    modifications: list[dict[str, Any]] = field(default_factory=list)
    examined: list[dict[str, Any]] = field(default_factory=list)
    currentStep: int = 0
    completedSteps: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SDDSession:
    """Live SDD session state persisted to ``active_session.json``.

    Field names are deliberately camelCase to keep JSON round-trip
    parity with the Node.js SessionManager. See Property 11 for the
    round-trip invariant.
    """

    sessionId: str
    phase: str
    startedAt: str
    lastActivityAt: str
    status: str = STATUS_ACTIVE
    currentStep: int = 0
    totalSteps: int = 0
    completedSteps: list[dict[str, Any]] = field(default_factory=list)
    skippedSteps: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[dict[str, Any]] = field(default_factory=list)
    notes: str | None = None
    modifications: list[dict[str, Any]] = field(default_factory=list)
    examined: list[dict[str, Any]] = field(default_factory=list)
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    # Optional end-of-lifecycle fields — present only after the session
    # transitions out of ``in_progress``.
    completedAt: str | None = None
    abandonedAt: str | None = None
    summary: str | None = None
    abandonReason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-ready dict, dropping unset optional fields.

        The Node.js writer only adds optional fields *after* the matching
        lifecycle transition, so the JSON for an active session does not
        include ``completedAt``/``abandonedAt``/etc. We follow the same
        convention for byte-compat.
        """
        raw = asdict(self)
        for optional in (
            "completedAt",
            "abandonedAt",
            "summary",
            "abandonReason",
        ):
            if raw.get(optional) is None:
                raw.pop(optional)
        # ``notes`` may legitimately be null in the JS output — keep it.
        return raw


# ── exceptions ───────────────────────────────────────────────────────────


class SessionError(RuntimeError):
    """Raised for invalid session state transitions."""


# ── manager ──────────────────────────────────────────────────────────────


class SessionManager:
    """File-backed SDD session manager.

    Parameters
    ----------
    state_dir
        Directory holding ``active_session.json``, ``history.jsonl``, and
        the ``checkpoints/`` subdirectory. Created on init if missing.
        Defaults to :data:`DEFAULT_STATE_DIR` (the project convention
        used by Node.js).
    clock
        Zero-arg callable returning an ISO-8601 UTC timestamp. Injecting
        it lets tests freeze time without monkey-patching ``datetime``.
    id_factory
        Zero-arg callable returning a short random token for session
        / checkpoint IDs. Injectable so property tests produce stable
        output.

    Notes
    -----
    All on-disk mutations are guarded by an internal ``threading.Lock``
    so concurrent ``record_step`` calls from different threads don't
    race on ``active_session.json``. (The Node.js server is single-
    threaded; Python needs this because FastMCP can run handlers on a
    thread pool.)
    """

    # Default path relative to the project root — resolved lazily so the
    # manager can be instantiated from any cwd.
    DEFAULT_STATE_DIR: str = "sdd_framework/execution_state"

    ACTIVE_FILENAME: str = "active_session.json"
    HISTORY_FILENAME: str = "history.jsonl"
    CHECKPOINTS_DIRNAME: str = "checkpoints"

    def __init__(
        self,
        state_dir: str | os.PathLike[str] | None = None,
        *,
        clock: "callable | None" = None,
        id_factory: "callable | None" = None,
    ) -> None:
        self._state_dir = Path(state_dir or self.DEFAULT_STATE_DIR).resolve()
        self._active_file = self._state_dir / self.ACTIVE_FILENAME
        self._history_file = self._state_dir / self.HISTORY_FILENAME
        self._checkpoints_dir = self._state_dir / self.CHECKPOINTS_DIRNAME
        self._clock = clock or _utc_now_iso
        self._id_factory = id_factory or _short_random_id
        self._lock = threading.Lock()
        self._ensure_state_dir()

    # ── lifecycle ────────────────────────────────────────────────────

    def start_session(
        self,
        phase_name: str,
        *,
        total_steps: int = 0,
        notes: str | None = None,
    ) -> SDDSession:
        """Start a new session for ``phase_name`` (Requirement 9.2).

        Raises
        ------
        SessionError
            If an active session already exists. Complete or abandon it
            before starting a new one.
        """
        if not phase_name:
            raise SessionError("phase_name is required")

        with self._lock:
            existing = self._read_active()
            if existing is not None:
                raise SessionError(
                    f'Active session already exists for "{existing.phase}". '
                    f"Complete or abandon it before starting a new one."
                )

            now = self._clock()
            session_id = self._make_session_id(now)
            session = SDDSession(
                sessionId=session_id,
                phase=phase_name,
                startedAt=now,
                lastActivityAt=now,
                totalSteps=max(int(total_steps), 0),
                notes=notes,
            )
            self._write_active(session)
            self._append_history(
                {
                    "sessionId": session_id,
                    "phase": phase_name,
                    "event": "started",
                    "timestamp": now,
                }
            )
            return session

    def record_step(
        self,
        step_number: int,
        name: str,
        tag: str = "implement",
        notes: str = "",
    ) -> SDDSession:
        """Record completion of step ``step_number`` (Requirement 9.3).

        Raises
        ------
        SessionError
            If no active session exists or the step was already recorded.
        """
        with self._lock:
            session = self._read_active_or_raise(
                "No active session. Call start_session first."
            )

            tag = tag or "implement"
            if tag not in VALID_TAGS:
                log.warning(
                    'Unknown step tag "%s". Valid tags: %s',
                    tag,
                    ", ".join(sorted(VALID_TAGS)),
                )

            if any(
                s.get("step") == step_number for s in session.completedSteps
            ):
                raise SessionError(
                    f"Step {step_number} already recorded as complete."
                )

            now = self._clock()
            step_record = {
                "step": int(step_number),
                "name": name,
                "tag": tag,
                "completedAt": now,
                "notes": notes,
            }
            session.completedSteps.append(step_record)
            session.currentStep = max(session.currentStep, int(step_number))
            session.lastActivityAt = now

            self._write_active(session)
            self._append_history(
                {
                    "sessionId": session.sessionId,
                    "phase": session.phase,
                    "event": "step_completed",
                    "step": int(step_number),
                    "name": name,
                    "tag": tag,
                    "notes": notes,
                    "timestamp": now,
                }
            )
            return session

    def complete_session(self, summary: str = "") -> SDDSession:
        """Mark the active session completed and remove the active file.

        The final state is preserved in ``history.jsonl`` via a
        ``completed`` event; the in-memory return value is the pre-removal
        snapshot so callers can render a summary without re-reading disk.
        """
        with self._lock:
            session = self._read_active_or_raise(
                "No active session to complete."
            )
            now = self._clock()
            session.status = STATUS_COMPLETED
            session.completedAt = now
            session.lastActivityAt = now
            session.summary = summary

            self._append_history(
                {
                    "sessionId": session.sessionId,
                    "phase": session.phase,
                    "event": "completed",
                    "summary": summary,
                    "completedSteps": len(session.completedSteps),
                    "skippedSteps": len(session.skippedSteps),
                    "totalSteps": session.totalSteps,
                    "duration": _duration_str(session.startedAt, now),
                    "timestamp": now,
                }
            )
            self._remove_active_file()
            return session

    def abandon_session(self, reason: str = "") -> SDDSession:
        """Abandon the active session without completing it."""
        with self._lock:
            session = self._read_active_or_raise(
                "No active session to abandon."
            )
            now = self._clock()
            session.status = STATUS_ABANDONED
            session.abandonedAt = now
            session.lastActivityAt = now
            session.abandonReason = reason

            self._append_history(
                {
                    "sessionId": session.sessionId,
                    "phase": session.phase,
                    "event": "abandoned",
                    "reason": reason,
                    "completedSteps": len(session.completedSteps),
                    "timestamp": now,
                }
            )
            self._remove_active_file()
            return session

    def resume_session(self) -> SDDSession:
        """Re-read the active session and bump ``lastActivityAt``.

        Raises ``SessionError`` when no active session exists or when the
        session's status is not ``in_progress``.
        """
        with self._lock:
            session = self._read_active_or_raise("No active session to resume.")
            if session.status != STATUS_ACTIVE:
                raise SessionError(
                    f'Session "{session.sessionId}" has status '
                    f'"{session.status}" and cannot be resumed.'
                )
            now = self._clock()
            session.lastActivityAt = now
            self._write_active(session)
            self._append_history(
                {
                    "sessionId": session.sessionId,
                    "phase": session.phase,
                    "event": "resumed",
                    "timestamp": now,
                }
            )
            return session

    # ── state tracking (Phase 24H-3) ─────────────────────────────────

    def examine_symbol(
        self, symbol: str, context: dict[str, Any] | None = None
    ) -> SDDSession | None:
        """Record that ``symbol`` was examined (Requirement 6.7).

        Deduplicated by symbol name — a repeat examination is a no-op
        so callers don't need to check first. Returns ``None`` silently
        when no active session exists, matching the Node.js behaviour
        (the tool layer calls this opportunistically).
        """
        with self._lock:
            session = self._read_active()
            if session is None:
                return None

            if any(e.get("symbol") == symbol for e in session.examined):
                return session

            now = self._clock()
            entry: dict[str, Any] = {"symbol": symbol, "examinedAt": now}
            if context:
                entry.update(context)
            session.examined.append(entry)
            session.lastActivityAt = now

            self._write_active(session)
            self._append_history(
                {
                    "sessionId": session.sessionId,
                    "phase": session.phase,
                    "event": "symbol_examined",
                    "symbol": symbol,
                    "timestamp": now,
                }
            )
            return session

    def mark_modified(
        self,
        file_path: str,
        change_type: str = "content",
        description: str = "",
    ) -> SDDSession:
        """Record a file modification (Requirement 6.7)."""
        if not file_path:
            raise SessionError("file_path is required")
        if change_type not in VALID_CHANGE_TYPES:
            log.warning(
                'Unknown changeType "%s"; accepted: %s',
                change_type,
                ", ".join(sorted(VALID_CHANGE_TYPES)),
            )

        with self._lock:
            session = self._read_active_or_raise(
                "No active session. Call start_session first."
            )
            now = self._clock()
            session.modifications.append(
                {
                    "filePath": file_path,
                    "changeType": change_type,
                    "description": description,
                    "modifiedAt": now,
                }
            )
            session.lastActivityAt = now

            self._write_active(session)
            self._append_history(
                {
                    "sessionId": session.sessionId,
                    "phase": session.phase,
                    "event": "file_modified",
                    "filePath": file_path,
                    "changeType": change_type,
                    "description": description,
                    "timestamp": now,
                }
            )
            return session

    def checkpoint_state(
        self, name: str, description: str = ""
    ) -> Checkpoint:
        """Create a named snapshot of the current session state."""
        with self._lock:
            session = self._read_active_or_raise(
                "No active session. Call start_session first."
            )
            now = self._clock()
            checkpoint_id = self._make_checkpoint_id(now)
            checkpoint = Checkpoint(
                checkpointId=checkpoint_id,
                name=name,
                description=description,
                createdAt=now,
                modifications=copy.deepcopy(session.modifications),
                examined=copy.deepcopy(session.examined),
                currentStep=session.currentStep,
                completedSteps=copy.deepcopy(session.completedSteps),
            )
            self._checkpoints_dir.mkdir(parents=True, exist_ok=True)
            self._write_json(
                self._checkpoints_dir / f"{checkpoint_id}.json",
                asdict(checkpoint),
            )

            session.checkpoints.append(
                {
                    "checkpointId": checkpoint_id,
                    "name": name,
                    "description": description,
                    "createdAt": now,
                }
            )
            session.lastActivityAt = now
            self._write_active(session)

            self._append_history(
                {
                    "sessionId": session.sessionId,
                    "phase": session.phase,
                    "event": "checkpoint_created",
                    "checkpointId": checkpoint_id,
                    "name": name,
                    "description": description,
                    "timestamp": now,
                }
            )
            return checkpoint

    def restore_checkpoint(self, checkpoint_id: str) -> SDDSession:
        """Restore session state from a previously created checkpoint."""
        with self._lock:
            session = self._read_active_or_raise(
                "No active session. Call start_session first."
            )
            checkpoint_path = self._checkpoints_dir / f"{checkpoint_id}.json"
            if not checkpoint_path.is_file():
                raise SessionError(
                    f'Checkpoint "{checkpoint_id}" not found.'
                )
            try:
                data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise SessionError(
                    f'Failed to load checkpoint "{checkpoint_id}": {exc}'
                ) from exc

            now = self._clock()
            session.modifications = list(data.get("modifications") or [])
            session.examined = list(data.get("examined") or [])
            session.lastActivityAt = now
            self._write_active(session)
            self._append_history(
                {
                    "sessionId": session.sessionId,
                    "phase": session.phase,
                    "event": "checkpoint_restored",
                    "checkpointId": checkpoint_id,
                    "name": data.get("name", ""),
                    "timestamp": now,
                }
            )
            return session

    # ── readers ──────────────────────────────────────────────────────

    def get_session_state(self) -> SDDSession | None:
        """Return the current active session or ``None`` if unset."""
        with self._lock:
            return self._read_active()

    def get_session_context(self) -> dict[str, Any]:
        """Aggregated view for agent workflows (Requirement 9.4).

        Matches ``SessionManager.getSessionContext`` in Node.js.
        """
        session = self.get_session_state()
        if session is None:
            return {"active": False, "message": "No active session."}
        return {
            "active": True,
            "sessionId": session.sessionId,
            "phase": session.phase,
            "startedAt": session.startedAt,
            "lastActivityAt": session.lastActivityAt,
            "currentStep": session.currentStep,
            "totalSteps": session.totalSteps,
            "stepsCompleted": len(session.completedSteps),
            "examined": list(session.examined),
            "modifications": list(session.modifications),
            "checkpoints": list(session.checkpoints),
            "summary": {
                "filesModified": len(session.modifications),
                "symbolsExamined": len(session.examined),
                "checkpointsCreated": len(session.checkpoints),
                "stepsCompleted": len(session.completedSteps),
                "stepsRemaining": max(
                    session.totalSteps - len(session.completedSteps), 0
                ),
            },
        }

    def get_history(
        self,
        *,
        phase: str | None = None,
        event: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Read filtered entries from ``history.jsonl`` (tail-first)."""
        if not self._history_file.is_file():
            return []
        try:
            with self._history_file.open("r", encoding="utf-8") as fh:
                entries: list[dict[str, Any]] = []
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        # Bad line → skip, same as Node.js filter(Boolean).
                        continue
        except OSError as exc:  # pragma: no cover - defensive
            log.warning("Failed to read history: %s", exc)
            return []

        if phase is not None:
            entries = [e for e in entries if phase in (e.get("phase") or "")]
        if event is not None:
            entries = [e for e in entries if e.get("event") == event]

        if limit and len(entries) > limit:
            entries = entries[-limit:]
        return entries

    # ── serialization helpers (Property 11) ──────────────────────────

    @staticmethod
    def serialize_session(session: SDDSession) -> str:
        """Serialize an :class:`SDDSession` to JSON (stable key order).

        Round-trip counterpart of :pymeth:`deserialize_session`. Used by
        Property 11 tests to guarantee lossless on-disk encoding.
        """
        return json.dumps(session.to_dict(), ensure_ascii=False, sort_keys=False)

    @staticmethod
    def deserialize_session(payload: str) -> SDDSession:
        """Rebuild an :class:`SDDSession` from its JSON form.

        Ignores unknown keys (forward-compat with newer on-disk schemas).
        """
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise ValueError("Serialized session must be a JSON object")
        known = {f for f in SDDSession.__dataclass_fields__}  # type: ignore[attr-defined]
        init_kwargs = {k: v for k, v in data.items() if k in known}
        return SDDSession(**init_kwargs)  # type: ignore[arg-type]

    # ── internals ────────────────────────────────────────────────────

    def _ensure_state_dir(self) -> None:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._checkpoints_dir.mkdir(parents=True, exist_ok=True)

    def _read_active(self) -> SDDSession | None:
        if not self._active_file.is_file():
            return None
        try:
            data = json.loads(self._active_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Failed to read active session: %s", exc)
            return None
        if not isinstance(data, dict):
            return None
        known = {f for f in SDDSession.__dataclass_fields__}  # type: ignore[attr-defined]
        return SDDSession(**{k: v for k, v in data.items() if k in known})

    def _read_active_or_raise(self, error_msg: str) -> SDDSession:
        session = self._read_active()
        if session is None:
            raise SessionError(error_msg)
        return session

    def _write_active(self, session: SDDSession) -> None:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(self._active_file, session.to_dict())

    def _remove_active_file(self) -> None:
        try:
            self._active_file.unlink()
        except FileNotFoundError:
            pass

    def _append_history(self, entry: dict[str, Any]) -> None:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        # Use append mode; single write is atomic for small payloads on
        # POSIX file systems, matching Node.js fs.appendFileSync semantics.
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with self._history_file.open("a", encoding="utf-8") as fh:
            fh.write(line)

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _make_session_id(self, now_iso: str) -> str:
        date_part = now_iso.split("T", 1)[0]
        return f"session_{date_part}_{self._id_factory()}"

    def _make_checkpoint_id(self, now_iso: str) -> str:
        date_part = now_iso.split("T", 1)[0]
        return f"chk_{date_part}_{self._id_factory()}"


# ── module-level helpers ─────────────────────────────────────────────────


def _utc_now_iso() -> str:
    """Default clock — UTC ISO-8601 with millisecond precision.

    Matches the JS output of ``new Date().toISOString()`` (``...Z``
    suffix, not ``+00:00``).
    """
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    return ts.replace("+00:00", "Z")


def _short_random_id(length: int = 6) -> str:
    """Node.js uses ``Math.random().toString(36).substr(2, 6)``.

    We emit the same character class (lowercase alnum) at the same
    length so session IDs match the pattern used by Node.js tooling.
    """
    alphabet = string.ascii_lowercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(length))


def _duration_str(start_iso: str, end_iso: str) -> str:
    """Human-readable duration between two ISO timestamps."""
    try:
        start = _parse_iso(start_iso)
        end = _parse_iso(end_iso)
    except (TypeError, ValueError):
        return ""
    delta_sec = max((end - start).total_seconds(), 0.0)
    minutes = int(delta_sec // 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _parse_iso(value: str) -> datetime:
    # ``datetime.fromisoformat`` on 3.12 accepts trailing ``Z`` natively.
    return datetime.fromisoformat(value)


__all__ = [
    "SessionManager",
    "SessionError",
    "SDDSession",
    "SDDStep",
    "FileModification",
    "ExaminedSymbol",
    "Checkpoint",
    "VALID_TAGS",
    "VALID_CHANGE_TYPES",
    "STATUS_ACTIVE",
    "STATUS_COMPLETED",
    "STATUS_ABANDONED",
]
