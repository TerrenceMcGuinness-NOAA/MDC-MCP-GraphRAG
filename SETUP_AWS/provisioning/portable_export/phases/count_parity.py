"""Count_Parity_Check (Task 12).

Compares source counts (captured in the Export_Manifest) with destination
counts (probed after a transfer) per collection, per Model_Profile, and per
tenant (R10.1). Any mismatch beyond the tolerance is reported and the check
reports failure so the CLI can exit non-zero (R10.2); all-match reports success
(R10.3). The parity report is JSON and is written to S3 with a timestamp
(R10.5).

Requirements: 10.1, 10.2, 10.3, 10.4, 10.5.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from portable_export.manifest import ExportManifest


@dataclass
class Mismatch:
    """A single source-vs-destination count discrepancy."""

    dimension: str          # "collection" | "model_profile" | "tenant"
    key: str
    source: int
    destination: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "key": self.key,
            "source": self.source,
            "destination": self.destination,
            "delta": self.destination - self.source,
        }


@dataclass
class ParityReport:
    """The outcome of a Count_Parity_Check."""

    passed: bool
    mismatches: list[Mismatch] = field(default_factory=list)
    tolerance: float = 0.0
    produced_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "tolerance": self.tolerance,
            "produced_at": self.produced_at,
            "mismatches": [m.as_dict() for m in self.mismatches],
        }

    @property
    def exit_status(self) -> int:
        """0 when all counts match, 1 on any mismatch (R10.2, R10.3)."""
        return 0 if self.passed else 1


def _within_tolerance(source: int, destination: int, tolerance: float) -> bool:
    if source == destination:
        return True
    if tolerance <= 0:
        return False
    if source == 0:
        return destination == 0
    return abs(destination - source) / source <= tolerance


def source_counts(manifest: ExportManifest) -> dict[str, dict[str, int]]:
    """Derive per-collection / per-profile / per-tenant source counts."""
    per_collection: dict[str, int] = {}
    per_profile: dict[str, int] = {}
    per_tenant: dict[str, int] = {}
    for ve in manifest.vector_exports:
        per_collection[ve.collection_name] = (
            per_collection.get(ve.collection_name, 0) + ve.record_count
        )
        per_profile[ve.model_profile] = (
            per_profile.get(ve.model_profile, 0) + ve.record_count
        )
        per_tenant[ve.tenant_id] = per_tenant.get(ve.tenant_id, 0) + ve.record_count
    # graph nodes contribute to per-tenant totals under a distinct dimension
    per_tenant_nodes: dict[str, int] = {}
    per_tenant_rels: dict[str, int] = {}
    for ge in manifest.graph_exports:
        per_tenant_nodes[ge.tenant_id] = ge.node_count
        per_tenant_rels[ge.tenant_id] = ge.relationship_count
    return {
        "collection": per_collection,
        "model_profile": per_profile,
        "tenant_vectors": per_tenant,
        "tenant_nodes": per_tenant_nodes,
        "tenant_rels": per_tenant_rels,
    }


def compare_counts(
    source: dict[str, dict[str, int]],
    destination: dict[str, dict[str, int]],
    *,
    tolerance: float = 0.0,
) -> ParityReport:
    """Compare ``source`` and ``destination`` count maps across dimensions."""
    mismatches: list[Mismatch] = []
    for dimension, src_map in source.items():
        dst_map = destination.get(dimension, {})
        keys = set(src_map) | set(dst_map)
        for key in sorted(keys):
            s = int(src_map.get(key, 0))
            d = int(dst_map.get(key, 0))
            if not _within_tolerance(s, d, tolerance):
                mismatches.append(Mismatch(dimension, key, s, d))
    return ParityReport(passed=not mismatches, mismatches=mismatches,
                        tolerance=tolerance)


def run_parity_check(
    manifest: ExportManifest,
    destination: dict[str, dict[str, int]],
    *,
    tolerance: float = 0.0,
    s3_client: Optional[Any] = None,
    bucket: Optional[str] = None,
    prefix: Optional[str] = None,
) -> ParityReport:
    """Run a Count_Parity_Check and optionally write the report to S3 (R10.5)."""
    report = compare_counts(source_counts(manifest), destination,
                            tolerance=tolerance)
    if s3_client is not None and bucket and prefix:
        ts = report.produced_at.replace(":", "").replace("-", "")
        key = f"{prefix.rstrip('/')}/parity/parity-{ts}.json"
        s3_client.put_object(
            Bucket=bucket, Key=key,
            Body=json.dumps(report.as_dict(), ensure_ascii=True,
                            sort_keys=True, indent=2).encode("utf-8"),
            ContentType="application/json",
        )
    return report


__all__ = [
    "Mismatch",
    "ParityReport",
    "source_counts",
    "compare_counts",
    "run_parity_check",
]
