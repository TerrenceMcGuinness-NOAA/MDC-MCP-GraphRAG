"""Unit tests for cost_control.tiers.neptune_tier (Task 7.1).

botocore Stubber only. Asserts snapshot-before-stop ordering, per-tenant
count manifest capture, wake start + wait available, idempotent is_asleep(),
and that the destructive stop is not issued before the snapshot succeeds.

Snapshot create/describe calls carry a time-based id and retain-until tag, so
their expected params are left unconstrained; the ordering of queued Stubber
responses is what enforces "snapshot before stop".

Requirements: 3.1, 4.1.
"""

from __future__ import annotations

import boto3
import pytest
from botocore.stub import Stubber

from cost_control.config import resolve_config
from cost_control.snapshots import SnapshotFailure
from cost_control.tiers.neptune_tier import NeptuneTier

CLUSTER = "mdc-mcp-graprag-neptune-1"


def _cfg():
    return resolve_config("dev", env={"COST_CONTROL_NEPTUNE_CLUSTER_ID": CLUSTER})


class _Clock:
    def __init__(self):
        self.t = 0.0

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += s


def _tier(client, **kw):
    clk = _Clock()
    return NeptuneTier(_cfg(), client, operation_id="op8f3a",
                       sleep_fn=clk.sleep, time_fn=clk.time, **kw)


def _clusters(status):
    return {"DBClusters": [{"Status": status}]}


def test_is_asleep_true_when_stopped():
    client = boto3.client("neptune", region_name="us-east-1")
    with Stubber(client) as stub:
        stub.add_response("describe_db_clusters", _clusters("stopped"),
                          {"DBClusterIdentifier": CLUSTER})
        assert _tier(client).is_asleep() is True


def test_is_asleep_false_when_available():
    client = boto3.client("neptune", region_name="us-east-1")
    with Stubber(client) as stub:
        stub.add_response("describe_db_clusters", _clusters("available"),
                          {"DBClusterIdentifier": CLUSTER})
        assert _tier(client).is_asleep() is False


def test_capture_manifest_records_counts():
    client = boto3.client("neptune", region_name="us-east-1")
    counts = {"gw": {"nodes": 148976, "rels": 4555408},
              "gw_v17": {"nodes": 80996, "rels": 1278331}}
    with Stubber(client) as stub:
        stub.add_response("describe_db_clusters", _clusters("available"),
                          {"DBClusterIdentifier": CLUSTER})
        m = _tier(client, graph_counts_fn=lambda: counts).capture_manifest()
    assert m["cluster_id"] == CLUSTER
    assert m["status"] == "available"
    assert m["per_tenant_counts"] == counts


def test_hibernate_snapshots_then_stops():
    client = boto3.client("neptune", region_name="us-east-1")
    with Stubber(client) as stub:
        # is_asleep
        stub.add_response("describe_db_clusters", _clusters("available"),
                          {"DBClusterIdentifier": CLUSTER})
        # snapshot create + wait available (params unconstrained)
        stub.add_response("create_db_cluster_snapshot",
                          {"DBClusterSnapshot": {"Status": "creating"}})
        stub.add_response("describe_db_cluster_snapshots",
                          {"DBClusterSnapshots": [{"Status": "available"}]})
        # destructive stop LAST
        stub.add_response("stop_db_cluster", {"DBCluster": {"Status": "stopping"}},
                          {"DBClusterIdentifier": CLUSTER})
        actions = _tier(client).hibernate()
        stub.assert_no_pending_responses()
    kinds = [a.action for a in actions]
    assert kinds.index("create_db_cluster_snapshot") < kinds.index("stop_db_cluster")
    assert any(a.action == "stop_db_cluster" and a.destructive for a in actions)


def test_hibernate_does_not_stop_before_snapshot_success():
    """Snapshot failure must abort before stop_db_cluster is reached."""
    client = boto3.client("neptune", region_name="us-east-1")
    with Stubber(client) as stub:
        stub.add_response("describe_db_clusters", _clusters("available"),
                          {"DBClusterIdentifier": CLUSTER})
        stub.add_response("create_db_cluster_snapshot",
                          {"DBClusterSnapshot": {"Status": "creating"}})
        stub.add_response("describe_db_cluster_snapshots",
                          {"DBClusterSnapshots": [{"Status": "failed"}]})
        # no stop_db_cluster queued -> would raise if called
        with pytest.raises(SnapshotFailure):
            _tier(client).hibernate()
        stub.assert_no_pending_responses()


def test_hibernate_noop_when_already_stopped():
    client = boto3.client("neptune", region_name="us-east-1")
    with Stubber(client) as stub:
        stub.add_response("describe_db_clusters", _clusters("stopped"),
                          {"DBClusterIdentifier": CLUSTER})
        assert _tier(client).hibernate() == []
        stub.assert_no_pending_responses()


def test_wake_starts_and_waits_available():
    client = boto3.client("neptune", region_name="us-east-1")
    with Stubber(client) as stub:
        # status check (not available)
        stub.add_response("describe_db_clusters", _clusters("stopped"),
                          {"DBClusterIdentifier": CLUSTER})
        stub.add_response("start_db_cluster", {"DBCluster": {"Status": "starting"}},
                          {"DBClusterIdentifier": CLUSTER})
        # wait loop: starting -> available
        stub.add_response("describe_db_clusters", _clusters("starting"),
                          {"DBClusterIdentifier": CLUSTER})
        stub.add_response("describe_db_clusters", _clusters("available"),
                          {"DBClusterIdentifier": CLUSTER})
        actions = _tier(client).wake()
        stub.assert_no_pending_responses()
    assert any(a.action == "start_db_cluster" for a in actions)


def test_wake_noop_when_available():
    client = boto3.client("neptune", region_name="us-east-1")
    with Stubber(client) as stub:
        stub.add_response("describe_db_clusters", _clusters("available"),
                          {"DBClusterIdentifier": CLUSTER})
        assert _tier(client).wake() == []
        stub.assert_no_pending_responses()
