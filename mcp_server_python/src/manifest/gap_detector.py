"""Gap detection: declared manifest sources vs. actual OpenSearch reality
(Requirements 6.1 – 6.6).

The :class:`GapDetector` compares :class:`ManifestRegistry`
declarations (``collection_target`` × ``doc_count``) against live
OpenSearch index stats and reports per-collection gaps. It also
flags stale and never-ingested sources via ``last_ingested``.

Usage::

    detector = GapDetector()
    reports = await detector.detect(registry, vector_db)

The vector_db argument is expected to be a ``VectorDBProtocol``-shaped
adapter — :meth:`detect` only calls ``health_check(deep=True)`` and
the ``indices_detail`` field added to that response in Phase C-2c.
Mocks in ``tests/conftest.py`` already populate the right shape.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from .models import SourceEntry
from .registry import ManifestRegistry

log = logging.getLogger(__name__)


GapStatus = Literal["healthy", "gap", "stale", "missing"]


@dataclass
class GapReport:
    """One gap-detection result, scoped to a single ``collection_target``.

    ``status`` is the most severe condition observed across all
    declared sources for the collection:

    * ``healthy`` — actual ≥ 90 % of declared and no stale/never sources
    * ``gap``     — actual < 90 % of declared
    * ``stale``   — coverage healthy but ≥1 source not ingested in 30 d
    * ``missing`` — coverage healthy but ≥1 source never ingested
    """

    collection: str
    declared_count: int
    actual_count: int
    coverage_pct: float
    stale_sources: list[str] = field(default_factory=list)
    never_ingested: list[str] = field(default_factory=list)
    status: GapStatus = "healthy"

    def to_dict(self) -> dict[str, Any]:
        return {
            "collection": self.collection,
            "declared_count": self.declared_count,
            "actual_count": self.actual_count,
            "coverage_pct": round(self.coverage_pct, 4),
            "stale_sources": list(self.stale_sources),
            "never_ingested": list(self.never_ingested),
            "status": self.status,
        }


class GapDetector:
    """Compares manifest declarations against OpenSearch reality."""

    #: Below this fraction of declared docs the collection is flagged
    #: as a coverage gap (Requirement 6.2).
    COVERAGE_THRESHOLD: float = 0.90

    #: Sources whose ``last_ingested`` is older than this many days are
    #: flagged as stale (Requirement 6.3).
    STALE_DAYS: int = 30

    async def detect(
        self,
        registry: ManifestRegistry,
        vector_db: Any,
    ) -> list[GapReport]:
        """Run gap detection across every declared collection.

        Returns an empty list (no crash) when ``vector_db`` is None or
        unreachable — Requirement 6 explicitly calls this out as
        "best-effort". Callers should render a "gap detection
        unavailable" placeholder when the result is empty AND there
        are declared sources.
        """
        if vector_db is None:
            log.debug("GapDetector.detect: vector_db is None; returning []")
            return []

        actual_counts = await self._get_actual_counts(vector_db)
        if actual_counts is None:
            return []

        # Group enabled sources by collection_target so we can sum
        # declared docs per collection. Sources are ``enabled=False``
        # do not contribute to the declared total.
        by_collection: dict[str, list[SourceEntry]] = {}
        for entry in registry.get_sources(enabled_only=False):
            by_collection.setdefault(entry.collection_target, []).append(entry)

        # Resolve each collection's actual count via the production
        # index map so the comparison uses the same logical → physical
        # translation the runtime does at query time.
        from src.config.aws_config import resolve_index

        reports: list[GapReport] = []
        for collection, entries in sorted(by_collection.items()):
            declared = sum(e.doc_count for e in entries if e.enabled)

            actual = self._lookup_actual_count(
                collection, entries, actual_counts, resolve_index
            )
            coverage_pct = (actual / declared) if declared > 0 else 1.0

            stale: list[str] = []
            never: list[str] = []
            now = datetime.now(timezone.utc)
            stale_cutoff = now - timedelta(days=self.STALE_DAYS)
            for entry in entries:
                if not entry.enabled:
                    continue
                if entry.last_ingested is None:
                    never.append(entry.name)
                    continue
                ingested_at = _parse_iso8601(entry.last_ingested)
                if ingested_at is not None and ingested_at < stale_cutoff:
                    stale.append(entry.name)

            status = self._classify(
                declared=declared,
                coverage_pct=coverage_pct,
                stale=stale,
                never=never,
            )

            reports.append(
                GapReport(
                    collection=collection,
                    declared_count=declared,
                    actual_count=actual,
                    coverage_pct=coverage_pct,
                    stale_sources=stale,
                    never_ingested=never,
                    status=status,
                )
            )
        return reports

    # ── internals ────────────────────────────────────────────────────

    async def _get_actual_counts(
        self, vector_db: Any
    ) -> dict[str, int] | None:
        """Return ``{index_name: doc_count}`` from the adapter health check.

        Returns ``None`` when the adapter is unreachable so the caller
        can short-circuit to an empty report list. Returns an empty
        dict when the adapter is reachable but has no indices (a
        legitimate "fresh deployment" case the caller should still
        report on).
        """
        try:
            health = await vector_db.health_check(deep=True)
        except Exception as exc:
            log.warning(
                "GapDetector._get_actual_counts: health_check failed: %s",
                exc,
            )
            return None

        if not isinstance(health, dict):
            log.warning(
                "GapDetector._get_actual_counts: health_check returned %s, "
                "expected dict",
                type(health).__name__,
            )
            return {}

        detail = health.get("indices_detail")
        if isinstance(detail, dict):
            return {str(k): int(v) for k, v in detail.items()}
        # Older adapter shapes returned only ``indices`` + ``total_documents``
        # — no per-index breakdown. Treat as empty (no actual counts) so
        # the gap detector cannot misreport zero coverage.
        return {}

    def _lookup_actual_count(
        self,
        collection: str,
        entries: list[SourceEntry],
        actual_counts: dict[str, int],
        resolve_index_fn: Any,
    ) -> int:
        """Resolve the OpenSearch index for ``collection`` and look it up.

        The production index map is profile-keyed, so the same logical
        collection maps to a different physical index per embedding
        profile. We use the embedding profile of the first declared
        entry — manifests SHOULD declare a single profile per
        collection, but if multiple profiles are present we use the
        first to keep the report deterministic.
        """
        # Fast path: collection is already a physical index name.
        if collection in actual_counts:
            return actual_counts[collection]

        for entry in entries:
            try:
                index_name = resolve_index_fn(
                    collection, entry.embedding_profile
                )
            except Exception as exc:  # pragma: no cover - defensive
                log.debug(
                    "resolve_index(%s, %s) failed: %s",
                    collection,
                    entry.embedding_profile,
                    exc,
                )
                continue
            if index_name in actual_counts:
                return actual_counts[index_name]

        # No mapping resolved to a known index — actual is unknown,
        # report 0 so the gap surfaces.
        return 0

    def _classify(
        self,
        *,
        declared: int,
        coverage_pct: float,
        stale: list[str],
        never: list[str],
    ) -> GapStatus:
        """Apply Requirements 6.2 / 6.3 / 6.4 priority ordering.

        Priority (most severe first):
            gap > missing > stale > healthy
        """
        if declared > 0 and coverage_pct < self.COVERAGE_THRESHOLD:
            return "gap"
        if never:
            return "missing"
        if stale:
            return "stale"
        return "healthy"


# ── helpers ────────────────────────────────────────────────────────────


def _parse_iso8601(value: str) -> datetime | None:
    """Parse an ISO-8601 timestamp; return ``None`` on failure.

    Accepts the trailing-Z form (``"2026-04-14T21:02:29Z"``) which
    Python's ``fromisoformat`` did not handle until 3.11; we are on
    3.12 so this works directly, but the Z → +00:00 normalization is
    kept for older test fixtures.
    """
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    # Treat naive datetimes as UTC so comparisons against
    # ``datetime.now(timezone.utc)`` don't raise.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


__all__ = ["GapDetector", "GapReport"]
