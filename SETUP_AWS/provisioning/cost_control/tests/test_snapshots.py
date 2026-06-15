"""Unit tests for cost_control.snapshots (Task 5.1).

Uses botocore Stubber for the boto3-backed tiers (Neptune, EC2) and a fake
client for the OpenSearch REST surface. Asserts: success path reaches the
terminal status; timeout aborts before the destructive call; failure status
aborts; ID convention; retention tag applied; EBS max-age skip.

Requirements: 4.1, 4.2, 4.3, 4.5.
"""

from __future__ import annotations

from datetime import datetime, timezone

import boto3
import pytest
from botocore.stub import Stubber

from cost_control import snapshots
from cost_control.snapshots import (
    SnapshotFailure,
    SnapshotTimeout,
    create_neptune_snapshot,
    create_opensearch_snapshot,
    ensure_ec2_root_snapshot,
    make_snapshot_id,
    retention_tags,
)

OP_ID = "8f3a1c2e-0000-0000-0000-000000000000"


class _Clock:
    """Deterministic monotonic clock advanced by sleep()."""

    def __init__(self) -> None:
        self.t = 0.0

    def time(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


# ── ID convention + tags ──────────────────────────────────────────────────

def test_snapshot_id_convention():
    now = datetime(2026, 6, 15, 20, 12, 1, tzinfo=timezone.utc)
    sid = make_snapshot_id("prod", OP_ID, "neptune", now=now)
    assert sid == "cc-prod-op8f3a-20260615T201201-neptune"


def test_retention_tags_include_environment_and_retain_until():
    tags = retention_tags("dev", 30)
    keys = {t["Key"]: t["Value"] for t in tags}
    assert keys["mdc-mcp-rag:environment"] == "dev"
    assert "mdc-mcp-rag:retain-until" in keys
    assert keys["mdc-mcp-rag:cost-control"] == "snapshot"


# ── Neptune ────────────────────────────────────────────────────────────────

def test_neptune_success_path():
    client = boto3.client("neptune", region_name="us-east-1")
    sid = make_snapshot_id("dev", OP_ID, "neptune",
                           now=datetime(2026, 6, 15, tzinfo=timezone.utc))
    clk = _Clock()
    with Stubber(client) as stub:
        stub.add_response("create_db_cluster_snapshot",
                          {"DBClusterSnapshot": {"Status": "creating"}})
        stub.add_response(
            "describe_db_cluster_snapshots",
            {"DBClusterSnapshots": [{"Status": "creating"}]},
            {"DBClusterSnapshotIdentifier": sid},
        )
        stub.add_response(
            "describe_db_cluster_snapshots",
            {"DBClusterSnapshots": [{"Status": "available"}]},
            {"DBClusterSnapshotIdentifier": sid},
        )
        out = create_neptune_snapshot(
            client, cluster_id="mdc-mcp-graprag-neptune-1", snapshot_id=sid,
            environment_name="dev", poll_interval_s=30,
            sleep_fn=clk.sleep, time_fn=clk.time,
        )
        stub.assert_no_pending_responses()
    assert out == sid


def test_neptune_failure_status_aborts():
    client = boto3.client("neptune", region_name="us-east-1")
    sid = "cc-dev-op8f3a-x-neptune"
    clk = _Clock()
    with Stubber(client) as stub:
        stub.add_response("create_db_cluster_snapshot",
                          {"DBClusterSnapshot": {"Status": "creating"}})
        stub.add_response(
            "describe_db_cluster_snapshots",
            {"DBClusterSnapshots": [{"Status": "failed"}]},
            {"DBClusterSnapshotIdentifier": sid},
        )
        with pytest.raises(SnapshotFailure) as exc:
            create_neptune_snapshot(
                client, cluster_id="c", snapshot_id=sid,
                environment_name="dev", sleep_fn=clk.sleep, time_fn=clk.time,
            )
    assert exc.value.tier == "neptune"
    assert exc.value.status == "failed"


def test_neptune_timeout_aborts():
    client = boto3.client("neptune", region_name="us-east-1")
    sid = "cc-dev-op8f3a-x-neptune"
    clk = _Clock()
    with Stubber(client) as stub:
        stub.add_response("create_db_cluster_snapshot",
                          {"DBClusterSnapshot": {"Status": "creating"}})
        # Always "creating"; the clock advances past the timeout.
        for _ in range(5):
            stub.add_response(
                "describe_db_cluster_snapshots",
                {"DBClusterSnapshots": [{"Status": "creating"}]},
                {"DBClusterSnapshotIdentifier": sid},
            )
        with pytest.raises(SnapshotTimeout) as exc:
            create_neptune_snapshot(
                client, cluster_id="c", snapshot_id=sid,
                environment_name="dev",
                timeout_s=60, poll_interval_s=30,
                sleep_fn=clk.sleep, time_fn=clk.time,
            )
    assert exc.value.tier == "neptune"


# ── EC2 root EBS ──────────────────────────────────────────────────────────

def test_ec2_fresh_snapshot_skips_creation():
    client = boto3.client("ec2", region_name="us-east-1")
    recent = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    now_epoch = datetime(2026, 6, 15, 13, 0, 0, tzinfo=timezone.utc).timestamp()
    with Stubber(client) as stub:
        stub.add_response(
            "describe_snapshots",
            {"Snapshots": [
                {"SnapshotId": "snap-recent", "State": "completed",
                 "StartTime": recent},
            ]},
            {"Filters": [{"Name": "volume-id", "Values": ["vol-0"]}],
             "OwnerIds": ["self"]},
        )
        out = ensure_ec2_root_snapshot(
            client, volume_id="vol-0", snapshot_id="cc-dev-x-ec2_root_ebs",
            environment_name="dev", max_age_s=24 * 3600, now_epoch=now_epoch,
        )
        stub.assert_no_pending_responses()
    assert out == "snap-recent"


def test_ec2_stale_snapshot_creates_and_waits():
    client = boto3.client("ec2", region_name="us-east-1")
    old = datetime(2026, 6, 10, tzinfo=timezone.utc)
    now_epoch = datetime(2026, 6, 15, tzinfo=timezone.utc).timestamp()
    clk = _Clock()
    with Stubber(client) as stub:
        stub.add_response(
            "describe_snapshots",
            {"Snapshots": [
                {"SnapshotId": "snap-old", "State": "completed", "StartTime": old},
            ]},
            {"Filters": [{"Name": "volume-id", "Values": ["vol-0"]}],
             "OwnerIds": ["self"]},
        )
        stub.add_response("create_snapshot",
                          {"SnapshotId": "snap-new", "State": "pending"})
        stub.add_response(
            "describe_snapshots",
            {"Snapshots": [{"SnapshotId": "snap-new", "State": "completed"}]},
            {"SnapshotIds": ["snap-new"]},
        )
        out = ensure_ec2_root_snapshot(
            client, volume_id="vol-0", snapshot_id="cc-dev-x-ec2_root_ebs",
            environment_name="dev", max_age_s=24 * 3600, now_epoch=now_epoch,
            sleep_fn=clk.sleep, time_fn=clk.time,
        )
        stub.assert_no_pending_responses()
    assert out == "snap-new"


def test_ec2_no_existing_snapshot_creates():
    client = boto3.client("ec2", region_name="us-east-1")
    clk = _Clock()
    with Stubber(client) as stub:
        stub.add_response(
            "describe_snapshots", {"Snapshots": []},
            {"Filters": [{"Name": "volume-id", "Values": ["vol-0"]}],
             "OwnerIds": ["self"]},
        )
        stub.add_response("create_snapshot",
                          {"SnapshotId": "snap-new", "State": "pending"})
        stub.add_response(
            "describe_snapshots",
            {"Snapshots": [{"SnapshotId": "snap-new", "State": "completed"}]},
            {"SnapshotIds": ["snap-new"]},
        )
        out = ensure_ec2_root_snapshot(
            client, volume_id="vol-0", snapshot_id="x",
            environment_name="dev", now_epoch=0.0,
            sleep_fn=clk.sleep, time_fn=clk.time,
        )
        stub.assert_no_pending_responses()
    assert out == "snap-new"


# ── OpenSearch (fake REST client) ──────────────────────────────────────────

class _FakeOSClient:
    def __init__(self, statuses):
        self._statuses = list(statuses)
        self.created = None
        self.calls = 0

    def create_snapshot(self, repository, snapshot):
        self.created = (repository, snapshot)

    def snapshot_status(self, repository, snapshot):
        self.calls += 1
        return self._statuses.pop(0)


def test_opensearch_success_path():
    fake = _FakeOSClient(["IN_PROGRESS", "SUCCESS"])
    clk = _Clock()
    out = create_opensearch_snapshot(
        fake, repository="cc-repo", snapshot_id="cc-dev-x-os",
        poll_interval_s=30, sleep_fn=clk.sleep, time_fn=clk.time,
    )
    assert out == "cc-dev-x-os"
    assert fake.created == ("cc-repo", "cc-dev-x-os")


def test_opensearch_failure_aborts():
    fake = _FakeOSClient(["IN_PROGRESS", "FAILED"])
    clk = _Clock()
    with pytest.raises(SnapshotFailure) as exc:
        create_opensearch_snapshot(
            fake, repository="r", snapshot_id="s",
            sleep_fn=clk.sleep, time_fn=clk.time,
        )
    assert exc.value.tier == "opensearch"
    assert exc.value.status == "FAILED"


def test_opensearch_timeout_aborts():
    fake = _FakeOSClient(["IN_PROGRESS"] * 10)
    clk = _Clock()
    with pytest.raises(SnapshotTimeout):
        create_opensearch_snapshot(
            fake, repository="r", snapshot_id="s",
            timeout_s=60, poll_interval_s=30,
            sleep_fn=clk.sleep, time_fn=clk.time,
        )
