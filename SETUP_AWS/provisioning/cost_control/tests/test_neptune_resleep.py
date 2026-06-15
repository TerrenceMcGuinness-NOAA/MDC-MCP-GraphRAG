"""Unit tests for cost_control.lambdas.neptune_resleep (Task 8.1).

botocore Stubber for Neptune + an injected fake state file and in-memory
audit. Asserts the guard re-stops only when the State_File says Sleep_State
AND the cluster is found available; otherwise it is a no-op.

Requirements: 3.1.
"""

from __future__ import annotations

import io

import boto3
from botocore.stub import Stubber

from cost_control.audit import AuditLogger
from cost_control.lambdas.neptune_resleep import resleep
from cost_control.state_file import (
    CorruptStateError,
    MissingStateError,
    new_initial_document,
)

CLUSTER = "mdc-mcp-graprag-neptune-1"


class _FakeStateFile:
    """Returns a canned (doc, etag) or raises a configured error."""

    def __init__(self, doc=None, error=None):
        self._doc = doc
        self._error = error

    def read(self):
        if self._error is not None:
            raise self._error
        return self._doc, "etag-1"


def _audit():
    return AuditLogger(
        operation_id="resleep-test",
        caller_arn="eventbridge-resleep",
        environment_name="dev",
        log_group="mdc-mcp-rag-cost-control-dev",
        audit_bucket="b",
        audit_prefix="cost-control/dev/",
        console_stream=io.StringIO(),
    )


def _doc(state):
    d = new_initial_document("dev")
    d["current_state"] = state
    return d


def test_restops_when_sleep_state_and_available():
    client = boto3.client("neptune", region_name="us-east-1")
    audit = _audit()
    with Stubber(client) as stub:
        stub.add_response("describe_db_clusters",
                          {"DBClusters": [{"Status": "available"}]},
                          {"DBClusterIdentifier": CLUSTER})
        stub.add_response("stop_db_cluster", {"DBCluster": {"Status": "stopping"}},
                          {"DBClusterIdentifier": CLUSTER})
        out = resleep(state_file=_FakeStateFile(_doc("Sleep_State")),
                      neptune_client=client, cluster_id=CLUSTER, audit=audit)
        stub.assert_no_pending_responses()
    assert out is True
    assert any(r["event_type"] == "Resleep_Triggered" for r in audit.records)


def test_noop_when_sleep_state_but_already_stopped():
    client = boto3.client("neptune", region_name="us-east-1")
    audit = _audit()
    with Stubber(client) as stub:
        stub.add_response("describe_db_clusters",
                          {"DBClusters": [{"Status": "stopped"}]},
                          {"DBClusterIdentifier": CLUSTER})
        # no stop_db_cluster queued
        out = resleep(state_file=_FakeStateFile(_doc("Sleep_State")),
                      neptune_client=client, cluster_id=CLUSTER, audit=audit)
        stub.assert_no_pending_responses()
    assert out is False
    assert any(r["event_type"] == "Resleep_Skipped" for r in audit.records)


def test_noop_when_not_sleep_state():
    client = boto3.client("neptune", region_name="us-east-1")
    audit = _audit()
    with Stubber(client) as stub:
        # cluster is never described because state gate fails first
        out = resleep(state_file=_FakeStateFile(_doc("Wake_State")),
                      neptune_client=client, cluster_id=CLUSTER, audit=audit)
        stub.assert_no_pending_responses()
    assert out is False


def test_noop_on_missing_state_file():
    client = boto3.client("neptune", region_name="us-east-1")
    audit = _audit()
    with Stubber(client):
        out = resleep(
            state_file=_FakeStateFile(error=MissingStateError("gone")),
            neptune_client=client, cluster_id=CLUSTER, audit=audit,
        )
    assert out is False
    skip = [r for r in audit.records if r["event_type"] == "Resleep_Skipped"]
    assert skip and skip[0]["error"]["code"] == "MissingStateError"


def test_noop_on_corrupt_state_file():
    client = boto3.client("neptune", region_name="us-east-1")
    audit = _audit()
    with Stubber(client):
        out = resleep(
            state_file=_FakeStateFile(error=CorruptStateError("bad")),
            neptune_client=client, cluster_id=CLUSTER, audit=audit,
        )
    assert out is False
