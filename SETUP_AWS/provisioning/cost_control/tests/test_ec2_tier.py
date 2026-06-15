"""Unit tests for cost_control.tiers.ec2_tier (Task 6.1).

botocore Stubber only. Asserts hibernate stops the instance, wake starts it,
the destructive stop is NOT issued before the EBS snapshot reaches completed,
and is_asleep() correctness.

Requirements: 4.3.
"""

from __future__ import annotations

from datetime import datetime, timezone

import boto3
import pytest
from botocore.stub import Stubber

from cost_control.config import resolve_config
from cost_control.snapshots import SnapshotFailure
from cost_control.tiers.ec2_tier import EC2Tier

INSTANCE = "i-0abc123"
VOLUME = "vol-0root"


def _cfg():
    return resolve_config("dev", env={"COST_CONTROL_EC2_INSTANCE_ID": INSTANCE})


class _Clock:
    def __init__(self):
        self.t = 0.0

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += s


def _instance(state, with_volume=True):
    inst = {
        "InstanceId": INSTANCE,
        "State": {"Name": state},
        "RootDeviceName": "/dev/xvda",
        "BlockDeviceMappings": [],
    }
    if with_volume:
        inst["BlockDeviceMappings"] = [
            {"DeviceName": "/dev/xvda", "Ebs": {"VolumeId": VOLUME}}
        ]
    return {"Reservations": [{"Instances": [inst]}]}


def _tier(client, **kw):
    clk = _Clock()
    return EC2Tier(_cfg(), client, operation_id="op1234",
                   sleep_fn=clk.sleep, time_fn=clk.time, **kw)


def test_is_asleep_true_when_stopped():
    client = boto3.client("ec2", region_name="us-east-1")
    with Stubber(client) as stub:
        stub.add_response("describe_instances", _instance("stopped"),
                          {"InstanceIds": [INSTANCE]})
        assert _tier(client).is_asleep() is True


def test_is_asleep_false_when_running():
    client = boto3.client("ec2", region_name="us-east-1")
    with Stubber(client) as stub:
        stub.add_response("describe_instances", _instance("running"),
                          {"InstanceIds": [INSTANCE]})
        assert _tier(client).is_asleep() is False


def test_capture_manifest():
    client = boto3.client("ec2", region_name="us-east-1")
    with Stubber(client) as stub:
        stub.add_response("describe_instances", _instance("running"),
                          {"InstanceIds": [INSTANCE]})
        m = _tier(client).capture_manifest()
    assert m == {"instance_id": INSTANCE, "root_volume_id": VOLUME, "state": "running"}


def test_hibernate_snapshots_then_stops_when_stale():
    client = boto3.client("ec2", region_name="us-east-1")
    old = datetime(2026, 6, 1, tzinfo=timezone.utc)
    now_epoch = datetime(2026, 6, 15, tzinfo=timezone.utc).timestamp()
    t = _tier(client, now_epoch=now_epoch, snapshot_max_age_s=24 * 3600)
    with Stubber(client) as stub:
        # is_asleep check
        stub.add_response("describe_instances", _instance("running"),
                          {"InstanceIds": [INSTANCE]})
        # describe for manifest/volume
        stub.add_response("describe_instances", _instance("running"),
                          {"InstanceIds": [INSTANCE]})
        # snapshot: existing is stale -> create + wait completed
        stub.add_response(
            "describe_snapshots",
            {"Snapshots": [{"SnapshotId": "snap-old", "State": "completed",
                            "StartTime": old}]},
            {"Filters": [{"Name": "volume-id", "Values": [VOLUME]}],
             "OwnerIds": ["self"]},
        )
        stub.add_response("create_snapshot",
                          {"SnapshotId": "snap-new", "State": "pending"})
        stub.add_response(
            "describe_snapshots",
            {"Snapshots": [{"SnapshotId": "snap-new", "State": "completed"}]},
            {"SnapshotIds": ["snap-new"]},
        )
        # destructive stop LAST
        stub.add_response("stop_instances",
                          {"StoppingInstances": []}, {"InstanceIds": [INSTANCE]})
        actions = t.hibernate()
        stub.assert_no_pending_responses()
    assert any(a.action == "stop_instances" and a.destructive for a in actions)


def test_hibernate_does_not_stop_before_snapshot_success():
    """If the EBS snapshot fails, stop_instances must never be reached."""
    client = boto3.client("ec2", region_name="us-east-1")
    now_epoch = datetime(2026, 6, 15, tzinfo=timezone.utc).timestamp()
    t = _tier(client, now_epoch=now_epoch, snapshot_max_age_s=24 * 3600)
    with Stubber(client) as stub:
        stub.add_response("describe_instances", _instance("running"),
                          {"InstanceIds": [INSTANCE]})
        stub.add_response("describe_instances", _instance("running"),
                          {"InstanceIds": [INSTANCE]})
        stub.add_response(
            "describe_snapshots", {"Snapshots": []},
            {"Filters": [{"Name": "volume-id", "Values": [VOLUME]}],
             "OwnerIds": ["self"]},
        )
        stub.add_response("create_snapshot",
                          {"SnapshotId": "snap-new", "State": "pending"})
        stub.add_response(
            "describe_snapshots",
            {"Snapshots": [{"SnapshotId": "snap-new", "State": "error"}]},
            {"SnapshotIds": ["snap-new"]},
        )
        # NOTE: no stop_instances queued -> if it were called, Stubber raises.
        with pytest.raises(SnapshotFailure):
            t.hibernate()
        stub.assert_no_pending_responses()


def test_hibernate_noop_when_already_stopped():
    client = boto3.client("ec2", region_name="us-east-1")
    with Stubber(client) as stub:
        stub.add_response("describe_instances", _instance("stopped"),
                          {"InstanceIds": [INSTANCE]})
        actions = _tier(client).hibernate()
        stub.assert_no_pending_responses()
    assert actions == []


def test_wake_starts_instance():
    client = boto3.client("ec2", region_name="us-east-1")
    with Stubber(client) as stub:
        stub.add_response("describe_instances", _instance("stopped"),
                          {"InstanceIds": [INSTANCE]})
        stub.add_response("start_instances",
                          {"StartingInstances": []}, {"InstanceIds": [INSTANCE]})
        actions = _tier(client).wake()
        stub.assert_no_pending_responses()
    assert any(a.action == "start_instances" for a in actions)


def test_wake_noop_when_running():
    client = boto3.client("ec2", region_name="us-east-1")
    with Stubber(client) as stub:
        stub.add_response("describe_instances", _instance("running"),
                          {"InstanceIds": [INSTANCE]})
        assert _tier(client).wake() == []
        stub.assert_no_pending_responses()


def test_plan_marks_stop_destructive():
    client = boto3.client("ec2", region_name="us-east-1")
    plan = _tier(client).plan("hibernate")
    stop = [a for a in plan if a.action == "stop_instances"][0]
    assert stop.destructive is True
