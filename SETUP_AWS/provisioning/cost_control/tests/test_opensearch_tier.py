"""Unit tests for cost_control.tiers.opensearch_tier (Task 9.1).

botocore Stubber for the opensearch client + a fake REST snapshot client.
Asserts snapshot-before-scale ordering, scale-down/up config deltas,
doc-count manifest capture, wait-for-processing gating, and the deep-sleep
stub.

Requirements: 3.2, 4.2.
"""

from __future__ import annotations

import boto3
import pytest
from botocore.stub import Stubber

from cost_control.config import resolve_config
from cost_control.snapshots import SnapshotFailure
from cost_control.tiers.opensearch_tier import (
    SLEEP_CLUSTER_CONFIG,
    OpenSearchTier,
)

DOMAIN = "mdc-mcp-rag-search"
PROD_CFG = {"InstanceType": "r6g.large.search", "InstanceCount": 2,
            "DedicatedMasterEnabled": False, "ZoneAwarenessEnabled": True}


def _cfg():
    return resolve_config("dev", env={"COST_CONTROL_OPENSEARCH_DOMAIN_NAME": DOMAIN})


class _Clock:
    def __init__(self):
        self.t = 0.0

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += s


class _FakeOSSnap:
    def __init__(self, statuses):
        self._statuses = list(statuses)
        self.created = None

    def create_snapshot(self, repository, snapshot):
        self.created = (repository, snapshot)

    def snapshot_status(self, repository, snapshot):
        return self._statuses.pop(0)


def _domain(instance_type, count, processing=False):
    return {"DomainStatus": {
        "DomainId": "123456789012/" + DOMAIN,
        "DomainName": DOMAIN,
        "ARN": f"arn:aws:es:us-east-1:123456789012:domain/{DOMAIN}",
        "Processing": processing,
        "ClusterConfig": {"InstanceType": instance_type, "InstanceCount": count},
    }}


def _tier(client, snap, **kw):
    clk = _Clock()
    return OpenSearchTier(_cfg(), client, snapshot_client=snap,
                          repository="cc-repo", operation_id="op8f3a",
                          production_cluster_config=PROD_CFG,
                          sleep_fn=clk.sleep, time_fn=clk.time, **kw)


def test_is_asleep_true_for_single_small_node():
    client = boto3.client("opensearch", region_name="us-east-1")
    with Stubber(client) as stub:
        stub.add_response("describe_domain", _domain("t3.small.search", 1),
                          {"DomainName": DOMAIN})
        assert _tier(client, None).is_asleep() is True


def test_is_asleep_false_for_production():
    client = boto3.client("opensearch", region_name="us-east-1")
    with Stubber(client) as stub:
        stub.add_response("describe_domain", _domain("r6g.large.search", 2),
                          {"DomainName": DOMAIN})
        assert _tier(client, None).is_asleep() is False


def test_capture_manifest_records_doc_counts():
    client = boto3.client("opensearch", region_name="us-east-1")
    counts = {"mdc-code-context-titan1024": 90135, "gw_v17_mdc-jjobs-titan1024": 92}
    with Stubber(client) as stub:
        stub.add_response("describe_domain", _domain("r6g.large.search", 2),
                          {"DomainName": DOMAIN})
        m = _tier(client, None, doc_counts_fn=lambda: counts).capture_manifest()
    assert m["domain_name"] == DOMAIN
    assert m["per_index_doc_counts"] == counts
    assert m["cluster_config"]["InstanceType"] == "r6g.large.search"


def test_hibernate_snapshots_then_scales_down():
    client = boto3.client("opensearch", region_name="us-east-1")
    snap = _FakeOSSnap(["IN_PROGRESS", "SUCCESS"])
    with Stubber(client) as stub:
        # is_asleep -> production
        stub.add_response("describe_domain", _domain("r6g.large.search", 2),
                          {"DomainName": DOMAIN})
        # scale-down config call
        stub.add_response("update_domain_config", {"DomainConfig": {}},
                          {"DomainName": DOMAIN, "ClusterConfig": SLEEP_CLUSTER_CONFIG})
        # wait Processing==false
        stub.add_response("describe_domain", _domain("t3.small.search", 1, processing=True),
                          {"DomainName": DOMAIN})
        stub.add_response("describe_domain", _domain("t3.small.search", 1, processing=False),
                          {"DomainName": DOMAIN})
        actions = _tier(client, snap).hibernate()
        stub.assert_no_pending_responses()
    # snapshot was taken before the scale-down
    assert snap.created == ("cc-repo", actions[0].description.split()[-1])
    kinds = [a.action for a in actions]
    assert kinds.index("create_snapshot") < kinds.index("update_domain_config")


def test_hibernate_aborts_before_scaledown_on_snapshot_failure():
    client = boto3.client("opensearch", region_name="us-east-1")
    snap = _FakeOSSnap(["IN_PROGRESS", "FAILED"])
    with Stubber(client) as stub:
        stub.add_response("describe_domain", _domain("r6g.large.search", 2),
                          {"DomainName": DOMAIN})
        # no update_domain_config queued -> would raise if reached
        with pytest.raises(SnapshotFailure):
            _tier(client, snap).hibernate()
        stub.assert_no_pending_responses()


def test_wake_scales_up_to_production():
    client = boto3.client("opensearch", region_name="us-east-1")
    with Stubber(client) as stub:
        # is_asleep -> single node
        stub.add_response("describe_domain", _domain("t3.small.search", 1),
                          {"DomainName": DOMAIN})
        stub.add_response("update_domain_config", {"DomainConfig": {}},
                          {"DomainName": DOMAIN, "ClusterConfig": PROD_CFG})
        stub.add_response("describe_domain", _domain("r6g.large.search", 2, processing=False),
                          {"DomainName": DOMAIN})
        actions = _tier(client, None).wake()
        stub.assert_no_pending_responses()
    assert any(a.action == "update_domain_config" for a in actions)


def test_wake_noop_when_already_production():
    client = boto3.client("opensearch", region_name="us-east-1")
    with Stubber(client) as stub:
        stub.add_response("describe_domain", _domain("r6g.large.search", 2),
                          {"DomainName": DOMAIN})
        assert _tier(client, None).wake() == []
        stub.assert_no_pending_responses()


def test_deep_sleep_mode_raises_not_implemented():
    client = boto3.client("opensearch", region_name="us-east-1")
    snap = _FakeOSSnap([])
    tier = _tier(client, snap, deep_sleep=True)
    with pytest.raises(NotImplementedError):
        tier.hibernate()


def test_plan_marks_scaledown_destructive():
    client = boto3.client("opensearch", region_name="us-east-1")
    plan = _tier(client, None).plan("hibernate")
    sd = [a for a in plan if a.action == "update_domain_config"][0]
    assert sd.destructive is True
