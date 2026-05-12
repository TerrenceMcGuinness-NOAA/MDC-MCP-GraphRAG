"""SDD session-tracking package.

Re-exports the public surface of :mod:`src.sdd.session_manager`.
"""

from __future__ import annotations

from .session_manager import (
    STATUS_ABANDONED,
    STATUS_ACTIVE,
    STATUS_COMPLETED,
    VALID_CHANGE_TYPES,
    VALID_TAGS,
    Checkpoint,
    ExaminedSymbol,
    FileModification,
    SDDSession,
    SDDStep,
    SessionError,
    SessionManager,
)

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
