"""Bug-fix tests for the ``check_knowledge_integrity`` tz-mismatch bug.

Spec: ``.kiro/specs/health-check-bugfixes/`` — Bug 1.

Covers Requirements 1.1–1.4 (``_parse_iso_ts`` always returns a tz-aware
datetime or ``None``) and 2.1–2.3 (``_check_stale_embeddings`` tolerates
mixed-source timestamps without raising). Includes the mandatory
bug-condition exploration test (R6.1, R6.2): a single test that raises
``TypeError: can't subtract offset-naive and offset-aware datetimes`` on
the unfixed code and passes on the fixed code.

Uses real ``tmp_path`` directories (pyfakefs is not installed in this
environment, and the integrity check only needs a non-git directory so
``_git_head_time`` returns ``None`` and the age-threshold subtraction
path — where the bug lives — is exercised). No live AWS calls.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from src.tools import semantic_search

pytestmark = pytest.mark.unit


# ── _parse_iso_ts (R1) ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        "2026-06-10T22:30:00+00:00",
        "2026-06-10T22:30:00Z",
        "2026-06-10T22:30:00+05:30",
        "2026-06-10T22:30:00",  # tz-naive → must become UTC-aware
    ],
)
def test_parse_iso_ts_returns_tz_aware(raw: str) -> None:
    """R1.1, R1.2, R1.4: every parseable ISO timestamp yields a tz-aware
    datetime (Property 1)."""
    dt = semantic_search._parse_iso_ts(raw)
    assert dt is not None
    assert dt.tzinfo is not None


def test_parse_iso_ts_naive_input_is_utc() -> None:
    """R1.2: a tz-naive ISO string is interpreted as UTC by convention."""
    dt = semantic_search._parse_iso_ts("2026-06-10T22:30:00")
    assert dt is not None
    assert dt.utcoffset() == timezone.utc.utcoffset(None)


def test_parse_iso_ts_preserves_offset() -> None:
    """R1.1: an explicit offset is preserved, not coerced to UTC."""
    dt = semantic_search._parse_iso_ts("2026-06-10T22:30:00+05:30")
    assert dt is not None
    assert dt.utcoffset().total_seconds() == 5.5 * 3600


def test_parse_iso_ts_z_suffix_is_utc() -> None:
    """R1.4: the ``Z`` → ``+00:00`` normalisation is preserved."""
    dt = semantic_search._parse_iso_ts("2026-06-10T22:30:00Z")
    assert dt is not None
    assert dt.utcoffset().total_seconds() == 0


@pytest.mark.parametrize(
    "raw",
    [None, "", "not a date", 12345, 3.14, object()],
)
def test_parse_iso_ts_unparseable_returns_none(raw: Any) -> None:
    """R1.3: non-string / empty / garbage inputs return ``None``, never a
    tz-naive datetime and never a raised exception."""
    assert semantic_search._parse_iso_ts(raw) is None


# ── _check_stale_embeddings (R2) ────────────────────────────────────────


class _StaleData:
    """Minimal ``data`` double exposing a ``vector_db.sample_metadata``."""

    def __init__(self, metadatas: list[dict[str, Any]]) -> None:
        self.vector_db = _StaleVectorDB(metadatas)
        self.graph_db = None


class _StaleVectorDB:
    def __init__(self, metadatas: list[dict[str, Any]]) -> None:
        self._metadatas = metadatas

    async def sample_metadata(self, n: int) -> list[dict[str, Any]]:
        return list(self._metadatas[:n])


async def test_check_stale_embeddings_mixed_timestamps_no_raise(
    tmp_path: Path,
) -> None:
    """R2.1, R2.3: a sample mixing tz-naive and tz-aware metadata returns a
    ``_Check`` without propagating a TypeError (Property 2)."""
    metas = [
        {"timestamp": "2026-06-10T22:30:00", "file_path": "a.py"},
        {"timestamp": "2026-06-10T22:30:00+00:00", "file_path": "b.py"},
        {"ingestedAt": "2026-06-10T22:30:00Z", "file_path": "c.py"},
    ]
    check = await semantic_search._check_stale_embeddings(
        _StaleData(metas), sample_size=10, repo_base=tmp_path
    )
    assert isinstance(check, semantic_search._Check)
    assert check.name == "Stale Embeddings"
    assert isinstance(check.passed, bool)
    assert isinstance(check.details, str)


async def test_check_stale_embeddings_skips_documents_without_timestamps(
    tmp_path: Path,
) -> None:
    """R2.2: documents without a usable timestamp are skipped, not fatal."""
    metas = [{"file_path": "a.py"}, {"timestamp": None, "file_path": "b.py"}]
    check = await semantic_search._check_stale_embeddings(
        _StaleData(metas), sample_size=10, repo_base=tmp_path
    )
    assert check.passed is True
    assert "0 sampled docs had usable timestamps" in check.details


# ── bug-condition exploration test (R6.1, R6.2) ─────────────────────────


async def test_bug1_exploration_tz_naive_metadata_does_not_raise(
    tmp_path: Path,
) -> None:
    """Bug-condition exploration (Bug 1).

    On the UNFIXED code, ``_parse_iso_ts`` returns a tz-naive datetime for
    a metadata timestamp lacking a tz designator. With ``repo_base`` a
    non-git directory, ``_check_stale_embeddings`` reaches the
    ``(now - mod_time).days`` subtraction against the tz-aware
    ``datetime.now(timezone.utc)`` and raises
    ``TypeError: can't subtract offset-naive and offset-aware datetimes``.

    On the FIXED code the parser returns a UTC-aware datetime and the
    subtraction succeeds, so this test completes without raising.

    Both directions were demonstrated before commit (see CHANGELOG
    [8.36.1]): reverting the ``_parse_iso_ts`` UTC fallback makes this
    test raise the TypeError above; re-applying it makes it pass.
    """
    # Sanity: confirm the parser produces a tz-aware value on the fixed code.
    parsed = semantic_search._parse_iso_ts("2026-06-10T22:30:00")
    assert parsed is not None and parsed.tzinfo is not None

    metas = [{"timestamp": "2026-06-10T22:30:00", "file_path": "stale.py"}]
    # The assertion is simply that no TypeError escapes.
    check = await semantic_search._check_stale_embeddings(
        _StaleData(metas), sample_size=5, repo_base=tmp_path
    )
    assert check.name == "Stale Embeddings"
