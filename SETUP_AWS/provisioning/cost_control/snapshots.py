"""Pre-destruction snapshot manager (Task 5).

Each destructive Hibernate_Operation step is preceded by a verified snapshot
of the affected data tier. This module creates a snapshot, waits for its
terminal success status with a per-tier timeout and polling cadence, and
verifies it -- raising a typed error (and therefore NOT proceeding to the
destructive API call) on timeout or failure status.

Tiers:
* Neptune  -- ``create_db_cluster_snapshot`` -> wait ``available`` (boto3).
* EC2 EBS  -- ``create_snapshot`` of the root volume -> wait ``completed``,
              only when the latest existing snapshot is older than the max age
              (R4.3) (boto3).
* OpenSearch -- manual snapshot to the registered S3 repo -> wait ``SUCCESS``
              (the OpenSearch ``_snapshot`` REST API is not a boto3 call, so it
              is driven through an injected client protocol).

Snapshot ID convention: ``cc-{env}-{op_short}-{utc_compact}-{tier}`` where
``op_short`` is ``op`` + the first four hex chars of the operation id and
``utc_compact`` is ``%Y%m%dT%H%M%S`` (design "Snapshot ID convention").

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Protocol

#: Default minimum retention window for created snapshots, in days (R4.4).
DEFAULT_RETENTION_DAYS: int = 30

#: Default poll interval between status checks, in seconds.
DEFAULT_POLL_INTERVAL_S: float = 30.0

# Per-tier wait timeouts (seconds). Snapshot creation that does not reach a
# terminal success status within the tier timeout aborts the operation (R4.5).
NEPTUNE_SNAPSHOT_TIMEOUT_S: float = 1800.0
OPENSEARCH_SNAPSHOT_TIMEOUT_S: float = 2700.0
EBS_SNAPSHOT_TIMEOUT_S: float = 1800.0

#: Default max age before a fresh EBS root snapshot is required (R4.3).
DEFAULT_EBS_MAX_AGE_S: float = 24 * 3600.0


class SnapshotError(Exception):
    """Base class for snapshot-manager errors."""


class SnapshotTimeout(SnapshotError):
    """A snapshot did not reach its terminal success status in time (R4.5)."""

    def __init__(self, tier: str, elapsed_seconds: float) -> None:
        self.tier = tier
        self.elapsed_seconds = elapsed_seconds
        super().__init__(
            f"{tier} snapshot did not reach terminal success within "
            f"{elapsed_seconds:.0f}s"
        )


class SnapshotFailure(SnapshotError):
    """A snapshot reached a terminal failure status."""

    def __init__(self, tier: str, status: str) -> None:
        self.tier = tier
        self.status = status
        super().__init__(f"{tier} snapshot entered failure status {status!r}")


def make_snapshot_id(
    environment_name: str,
    operation_id: str,
    tier: str,
    *,
    now: Optional[datetime] = None,
) -> str:
    """Build a snapshot id ``cc-{env}-{op_short}-{utc_compact}-{tier}``."""
    op_hex = operation_id.replace("-", "")[:4]
    op_short = f"op{op_hex}"
    ts = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%S")
    return f"cc-{environment_name}-{op_short}-{ts}-{tier}"


def retention_tags(environment_name: str, retention_days: int) -> list[dict[str, str]]:
    """Return the standard tag set applied to every created snapshot.

    Includes the environment tag (R13.2) and a retain-until marker that the
    Snapshot_Lifecycle policy reads to honour the minimum retention window
    (R4.4).
    """
    retain_until = (
        datetime.now(timezone.utc).timestamp() + retention_days * 86400.0
    )
    retain_until_iso = datetime.fromtimestamp(
        retain_until, tz=timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [
        {"Key": "mdc-mcp-rag:environment", "Value": environment_name},
        {"Key": "mdc-mcp-rag:cost-control", "Value": "snapshot"},
        {"Key": "mdc-mcp-rag:retain-until", "Value": retain_until_iso},
    ]


def _wait_for_status(
    *,
    tier: str,
    poll_status: Callable[[], str],
    success_status: str,
    failure_statuses: frozenset[str],
    timeout_s: float,
    poll_interval_s: float,
    sleep_fn: Callable[[float], None],
    time_fn: Callable[[], float],
) -> None:
    """Poll ``poll_status`` until success, raising on failure/timeout.

    The first status read happens immediately; the elapsed clock is measured
    against ``time_fn`` so tests inject a deterministic clock and a no-op
    ``sleep_fn``.
    """
    start = time_fn()
    while True:
        status = poll_status()
        if status == success_status:
            return
        if status in failure_statuses:
            raise SnapshotFailure(tier, status)
        elapsed = time_fn() - start
        if elapsed >= timeout_s:
            raise SnapshotTimeout(tier, elapsed)
        sleep_fn(poll_interval_s)


# ── Neptune ─────────────────────────────────────────────────────────────────

def create_neptune_snapshot(
    neptune_client: Any,
    *,
    cluster_id: str,
    snapshot_id: str,
    environment_name: str,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    timeout_s: float = NEPTUNE_SNAPSHOT_TIMEOUT_S,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    sleep_fn: Callable[[float], None] = time.sleep,
    time_fn: Callable[[], float] = time.monotonic,
) -> str:
    """Create a Neptune cluster snapshot and wait for ``available`` (R4.1).

    Returns the snapshot id on success. Raises :class:`SnapshotTimeout` or
    :class:`SnapshotFailure` before any destructive call would be issued.
    """
    neptune_client.create_db_cluster_snapshot(
        DBClusterSnapshotIdentifier=snapshot_id,
        DBClusterIdentifier=cluster_id,
        Tags=retention_tags(environment_name, retention_days),
    )

    def _poll() -> str:
        resp = neptune_client.describe_db_cluster_snapshots(
            DBClusterSnapshotIdentifier=snapshot_id
        )
        snaps = resp.get("DBClusterSnapshots", [])
        if not snaps:
            return "pending"
        return snaps[0].get("Status", "pending")

    _wait_for_status(
        tier="neptune",
        poll_status=_poll,
        success_status="available",
        failure_statuses=frozenset({"failed", "deleting", "deleted"}),
        timeout_s=timeout_s,
        poll_interval_s=poll_interval_s,
        sleep_fn=sleep_fn,
        time_fn=time_fn,
    )
    return snapshot_id


# ── EC2 root EBS ──────────────────────────────────────────────────────────

def _parse_start_time(value: Any) -> float:
    """Return an epoch-seconds float from a boto3 StartTime value."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    # ISO string fallback.
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()


def ensure_ec2_root_snapshot(
    ec2_client: Any,
    *,
    volume_id: str,
    snapshot_id: str,
    environment_name: str,
    max_age_s: float = DEFAULT_EBS_MAX_AGE_S,
    now_epoch: Optional[float] = None,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    timeout_s: float = EBS_SNAPSHOT_TIMEOUT_S,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    sleep_fn: Callable[[float], None] = time.sleep,
    time_fn: Callable[[], float] = time.monotonic,
) -> str:
    """Ensure a fresh EBS root snapshot exists (R4.3).

    If the newest existing ``completed`` snapshot of ``volume_id`` is no older
    than ``max_age_s``, that snapshot id is returned without creating a new
    one. Otherwise a fresh snapshot is created and waited to ``completed``.
    """
    now = now_epoch if now_epoch is not None else time.time()
    existing = ec2_client.describe_snapshots(
        Filters=[{"Name": "volume-id", "Values": [volume_id]}],
        OwnerIds=["self"],
    ).get("Snapshots", [])
    completed = [s for s in existing if s.get("State") == "completed"]
    if completed:
        newest = max(completed, key=lambda s: _parse_start_time(s["StartTime"]))
        age = now - _parse_start_time(newest["StartTime"])
        if age <= max_age_s:
            return newest["SnapshotId"]

    created = ec2_client.create_snapshot(
        VolumeId=volume_id,
        Description=f"cost-control {environment_name} root snapshot",
        TagSpecifications=[
            {
                "ResourceType": "snapshot",
                "Tags": retention_tags(environment_name, retention_days)
                + [{"Key": "Name", "Value": snapshot_id}],
            }
        ],
    )
    new_id = created["SnapshotId"]

    def _poll() -> str:
        resp = ec2_client.describe_snapshots(SnapshotIds=[new_id])
        snaps = resp.get("Snapshots", [])
        if not snaps:
            return "pending"
        return snaps[0].get("State", "pending")

    _wait_for_status(
        tier="ec2_root_ebs",
        poll_status=_poll,
        success_status="completed",
        failure_statuses=frozenset({"error"}),
        timeout_s=timeout_s,
        poll_interval_s=poll_interval_s,
        sleep_fn=sleep_fn,
        time_fn=time_fn,
    )
    return new_id


# ── OpenSearch manual snapshot ──────────────────────────────────────────────

class OpenSearchSnapshotClient(Protocol):
    """Minimal protocol for the OpenSearch ``_snapshot`` REST surface.

    The OpenSearch manual-snapshot API is HTTP, not a boto3 call, so the
    snapshot manager depends on this small protocol; the orchestrator supplies
    a concrete signed-HTTP implementation and tests supply a fake.
    """

    def create_snapshot(self, repository: str, snapshot: str) -> None: ...

    def snapshot_status(self, repository: str, snapshot: str) -> str: ...


def create_opensearch_snapshot(
    os_client: OpenSearchSnapshotClient,
    *,
    repository: str,
    snapshot_id: str,
    timeout_s: float = OPENSEARCH_SNAPSHOT_TIMEOUT_S,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    sleep_fn: Callable[[float], None] = time.sleep,
    time_fn: Callable[[], float] = time.monotonic,
) -> str:
    """Create an OpenSearch manual snapshot and wait for ``SUCCESS`` (R4.2).

    Returns the snapshot id on success. Raises :class:`SnapshotTimeout` or
    :class:`SnapshotFailure` (on ``FAILED`` / ``PARTIAL``) before any
    destructive domain call would be issued.
    """
    os_client.create_snapshot(repository, snapshot_id)

    def _poll() -> str:
        return os_client.snapshot_status(repository, snapshot_id)

    _wait_for_status(
        tier="opensearch",
        poll_status=_poll,
        success_status="SUCCESS",
        failure_statuses=frozenset({"FAILED", "PARTIAL"}),
        timeout_s=timeout_s,
        poll_interval_s=poll_interval_s,
        sleep_fn=sleep_fn,
        time_fn=time_fn,
    )
    return snapshot_id
