"""Unit tests for ``LocalProvider`` import-fail behavior (Phase C-2c, Req 11.4).

The Python runtime image deliberately excludes ``sentence-transformers``
(Requirement 10), so ``LocalProvider.__init__`` must:

1. Raise :class:`EmbeddingError` with a "sentence-transformers is not
   installed" message (Requirement 9.1).
2. Emit exactly one ``[ERROR]`` log line identifying the active
   profile (Requirement 9.2).

These tests mask ``sentence_transformers`` from ``sys.modules`` so the
behavior is observable even on hosts that happen to have the package
installed (e.g. a developer laptop).
"""

from __future__ import annotations

import logging
import sys

import pytest

from src.data.embedding_provider import EmbeddingError, LocalProvider
from src.data.embedding_registry import EmbeddingModelRegistry


@pytest.fixture()
def mpnet_profile():
    return EmbeddingModelRegistry().get_profile("mpnet768")


# ── construction error path (Req 9.1) ─────────────────────────────────


def test_construction_raises_embedding_error_when_dependency_missing(
    monkeypatch: pytest.MonkeyPatch, mpnet_profile
) -> None:
    """Mask ``sentence_transformers`` and assert EmbeddingError."""

    # Remove any cached real module, then force the next import to fail.
    monkeypatch.delitem(sys.modules, "sentence_transformers", raising=False)
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def _block(name, *args, **kwargs):
        if name == "sentence_transformers":
            raise ImportError("No module named 'sentence_transformers'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _block)

    with pytest.raises(EmbeddingError) as exc:
        LocalProvider(mpnet_profile)

    assert "sentence-transformers is not installed" in str(exc.value)
    assert "mpnet768 is parity-debug-only" in str(exc.value)


# ── one-shot [ERROR] log line (Req 9.2) ───────────────────────────────


def test_construction_emits_exactly_one_error_log_line(
    monkeypatch: pytest.MonkeyPatch,
    mpnet_profile,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``LocalProvider.__init__`` emits one ``[ERROR]`` log line
    naming the active profile before raising (Req 9.2)."""
    monkeypatch.delitem(sys.modules, "sentence_transformers", raising=False)
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def _block(name, *args, **kwargs):
        if name == "sentence_transformers":
            raise ImportError("No module named 'sentence_transformers'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _block)

    caplog.set_level(logging.ERROR, logger="src.data.embedding_provider")

    with pytest.raises(EmbeddingError):
        LocalProvider(mpnet_profile)

    error_records = [
        r for r in caplog.records if r.levelno == logging.ERROR
    ]
    assert len(error_records) == 1
    message = error_records[0].getMessage()
    assert "[ERROR]" in message
    assert "mpnet768" in message


# ── exception chaining ───────────────────────────────────────────────


def test_embedding_error_chains_underlying_import_error(
    monkeypatch: pytest.MonkeyPatch, mpnet_profile
) -> None:
    """The raised ``EmbeddingError`` must chain the underlying
    ``ImportError`` so post-mortem diagnostics show the root cause."""
    monkeypatch.delitem(sys.modules, "sentence_transformers", raising=False)
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def _block(name, *args, **kwargs):
        if name == "sentence_transformers":
            raise ImportError("No module named 'sentence_transformers'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _block)

    with pytest.raises(EmbeddingError) as exc:
        LocalProvider(mpnet_profile)

    assert isinstance(exc.value.__cause__, ImportError)
