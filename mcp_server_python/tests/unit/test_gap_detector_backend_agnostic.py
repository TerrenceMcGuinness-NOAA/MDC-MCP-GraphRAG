"""GapDetector backend-agnostic actual-count resolution.

cots-backend-observability-parity R5 — the gap detector's "actual" side must
report real coverage on ChromaDB (``DB_BACKEND=cots``), not 0% across the board.
ChromaDB's ``health_check(deep=True)`` exposes per-collection counts under
``collections_detail`` (OpenSearch uses ``indices_detail``); when neither map is
present the detector dispatches through the backend-abstract
``count_documents(collection)``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.manifest.gap_detector import GapDetector

pytestmark = pytest.mark.unit


class _HealthOnly:
    """Vector-db double that only returns a health payload."""

    def __init__(self, health: dict[str, Any]):
        self._health = health

    async def health_check(self, *, deep: bool = False) -> dict[str, Any]:  # noqa: ARG002
        return dict(self._health)


class _NamesWithCount:
    """Vector-db double whose health returns only names (no count map),
    plus a backend-abstract count_documents."""

    def __init__(self, names: list[str], counts: dict[str, int]):
        self._names = names
        self._counts = counts

    async def health_check(self, *, deep: bool = False) -> dict[str, Any]:  # noqa: ARG002
        return {"status": "healthy", "collections": list(self._names)}

    async def count_documents(self, collection: str) -> int:
        return self._counts.get(collection, 0)


def test_recognizes_chromadb_collections_detail() -> None:
    """R5: ChromaDB's collections_detail yields real per-collection counts."""
    vd = _HealthOnly(
        {
            "status": "healthy",
            "collections_detail": {
                "mdc-workflow-docs-mpnet768": 100,
                "mdc-code-context-mpnet768": 50,
            },
        }
    )
    got = asyncio.run(GapDetector()._get_actual_counts(vd))
    assert got == {
        "mdc-workflow-docs-mpnet768": 100,
        "mdc-code-context-mpnet768": 50,
    }


def test_opensearch_indices_detail_still_recognized() -> None:
    """R5.3 / no-regression: OpenSearch's indices_detail path is unchanged."""
    vd = _HealthOnly(
        {
            "status": "healthy",
            "indices_detail": {"mdc-workflow-docs-titan1024": 200},
        }
    )
    got = asyncio.run(GapDetector()._get_actual_counts(vd))
    assert got == {"mdc-workflow-docs-titan1024": 200}


def test_falls_back_to_count_documents_when_no_detail_map() -> None:
    """R5.1: names-only health payload dispatches through count_documents."""
    vd = _NamesWithCount(
        ["mdc-workflow-docs-mpnet768", "mdc-jjobs-mpnet768"],
        {"mdc-workflow-docs-mpnet768": 100, "mdc-jjobs-mpnet768": 92},
    )
    got = asyncio.run(GapDetector()._get_actual_counts(vd))
    assert got == {
        "mdc-workflow-docs-mpnet768": 100,
        "mdc-jjobs-mpnet768": 92,
    }


def test_indices_detail_preferred_over_collections_detail() -> None:
    """When both maps are present (shouldn't happen, but be deterministic),
    indices_detail wins."""
    vd = _HealthOnly(
        {
            "status": "healthy",
            "indices_detail": {"a": 1},
            "collections_detail": {"b": 2},
        }
    )
    got = asyncio.run(GapDetector()._get_actual_counts(vd))
    assert got == {"a": 1}
