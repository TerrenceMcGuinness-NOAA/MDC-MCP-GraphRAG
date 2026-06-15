"""Drift detection on wake (Task 11).

At hibernate the orchestrator records a storage-tier manifest in the
State_File. At wake, :func:`classify_drift` diffs that manifest against the
current storage-tier reality and classifies each delta as **data-preserving**
(auto-reconcile and continue) or **data-destructive** (refuse and exit before
any compute is created, unless the operator passes ``--force-drift``).

Classification rules (R10.2, R10.3):

* preserving  -- an additional ECR image tag appeared; a new OpenSearch index
                 appeared (extra data, nothing lost).
* destructive -- a required snapshot is missing; an ECR image referenced by
                 the runtime manifest was deleted; a previously-present
                 OpenSearch index disappeared; a storage bucket's retention
                 policy changed.

Requirements: 10.1, 10.2, 10.3, 10.4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Delta classification tokens.
PRESERVING: str = "preserving"
DESTRUCTIVE: str = "destructive"


@dataclass(frozen=True)
class DriftDelta:
    """One detected difference between the manifest and current reality."""

    category: str          # e.g. "ecr_image", "opensearch_index", "snapshot"
    classification: str    # PRESERVING or DESTRUCTIVE
    description: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class DriftResult:
    """The classified set of drift deltas for one wake operation."""

    deltas: list[DriftDelta] = field(default_factory=list)

    @property
    def preserving(self) -> list[DriftDelta]:
        return [d for d in self.deltas if d.classification == PRESERVING]

    @property
    def destructive(self) -> list[DriftDelta]:
        return [d for d in self.deltas if d.classification == DESTRUCTIVE]

    @property
    def has_destructive(self) -> bool:
        return any(d.classification == DESTRUCTIVE for d in self.deltas)

    def should_refuse(self, force_drift: bool = False) -> bool:
        """True when wake must refuse: destructive drift and no override."""
        return self.has_destructive and not force_drift


def _as_set(value: Any) -> set:
    if value is None:
        return set()
    if isinstance(value, dict):
        return set(value.keys())
    return set(value)


def classify_drift(previous: dict[str, Any], current: dict[str, Any]) -> DriftResult:
    """Diff the previous hibernate manifest against current reality.

    Both ``previous`` and ``current`` are storage-tier observation dicts with
    (all optional) keys:

    * ``ecr_image_tags``       -- iterable / mapping of image tags present.
    * ``referenced_image_tags``-- tags the runtime manifest depends on.
    * ``opensearch_indices``   -- iterable / mapping of index names present.
    * ``required_snapshots``   -- mapping ``tier -> snapshot_id`` expected.
    * ``available_snapshots``  -- iterable of snapshot ids in ``available``
                                  status.
    * ``bucket_retention``     -- mapping ``bucket -> retention marker``.
    """
    result = DriftResult()

    # -- ECR images -----------------------------------------------------
    prev_tags = _as_set(previous.get("ecr_image_tags"))
    cur_tags = _as_set(current.get("ecr_image_tags"))
    for added in sorted(cur_tags - prev_tags):
        result.deltas.append(DriftDelta(
            "ecr_image", PRESERVING,
            f"new ECR image tag appeared while asleep: {added}",
            {"tag": added}))
    referenced = _as_set(current.get("referenced_image_tags")) or _as_set(
        previous.get("referenced_image_tags"))
    for removed in sorted(prev_tags - cur_tags):
        # A removed tag is destructive only if the runtime references it.
        classification = DESTRUCTIVE if removed in referenced else PRESERVING
        result.deltas.append(DriftDelta(
            "ecr_image", classification,
            f"ECR image tag disappeared while asleep: {removed}"
            + (" (referenced by runtime)" if classification == DESTRUCTIVE else ""),
            {"tag": removed}))

    # -- OpenSearch indices --------------------------------------------
    prev_idx = _as_set(previous.get("opensearch_indices"))
    cur_idx = _as_set(current.get("opensearch_indices"))
    for added in sorted(cur_idx - prev_idx):
        result.deltas.append(DriftDelta(
            "opensearch_index", PRESERVING,
            f"new OpenSearch index appeared while asleep: {added}",
            {"index": added}))
    for removed in sorted(prev_idx - cur_idx):
        result.deltas.append(DriftDelta(
            "opensearch_index", DESTRUCTIVE,
            f"OpenSearch index disappeared while asleep: {removed}",
            {"index": removed}))

    # -- required snapshots --------------------------------------------
    required = previous.get("required_snapshots") or {}
    available = _as_set(current.get("available_snapshots"))
    for tier, snap_id in sorted(required.items()):
        if snap_id not in available:
            result.deltas.append(DriftDelta(
                "snapshot", DESTRUCTIVE,
                f"required {tier} snapshot missing/unavailable: {snap_id}",
                {"tier": tier, "snapshot_id": snap_id}))

    # -- bucket retention ----------------------------------------------
    prev_ret = previous.get("bucket_retention") or {}
    cur_ret = current.get("bucket_retention") or {}
    for bucket, marker in sorted(prev_ret.items()):
        if bucket in cur_ret and cur_ret[bucket] != marker:
            result.deltas.append(DriftDelta(
                "bucket_retention", DESTRUCTIVE,
                f"retention policy changed on bucket {bucket}",
                {"bucket": bucket, "was": marker, "now": cur_ret[bucket]}))

    return result


def evaluate(
    previous: dict[str, Any],
    current: dict[str, Any],
    *,
    force_drift: bool = False,
) -> tuple[bool, DriftResult]:
    """Classify drift and decide whether wake may proceed.

    Returns ``(proceed, result)``. ``proceed`` is ``False`` when destructive
    drift was detected and ``force_drift`` was not supplied (R10.3); otherwise
    ``True`` (preserving deltas auto-reconcile, R10.2).
    """
    result = classify_drift(previous, current)
    return (not result.should_refuse(force_drift)), result
