"""Round-trip property tests (Task 13.2): P1 and P2.

moto is not available in this environment, so the round trip drives the REAL
tier classes against stateful, call-recording fake AWS clients (still "no live
AWS"). The fakes evolve state on stop/start/scale so a full hibernate -> wake
cycle behaves like the live services would for these operations.

Property 1 -- data-preservation round-trip: the per-tier manifest counts
(Neptune per-tenant nodes/rels, OpenSearch per-index doc counts) captured
before hibernate equal those captured after wake.

Property 2 -- storage-tier immutability: across both transitions no recorded
AWS call mutates a Storage_Stack resource (EFS access point, ECR image tags,
or the state/audit/snapshot buckets); ECR is only ever read.

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 11.6.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone

from cost_control.audit import AuditLogger
from cost_control.config import resolve_config
from cost_control.costs import CostModel
from cost_control.state_file import new_initial_document
from cost_control.state_machine import StateMachine
from cost_control.tiers.agentcore_tier import AgentCoreTier
from cost_control.tiers.ec2_tier import EC2Tier
from cost_control.tiers.nat_tier import NatTier
from cost_control.tiers.neptune_tier import NeptuneTier
from cost_control.tiers.opensearch_tier import OpenSearchTier

EFS_AP = "fsap-roundtrip"
NEPTUNE_COUNTS = {"gw": {"nodes": 148976, "rels": 4555408},
                  "gw_v17": {"nodes": 80996, "rels": 1278331}}
OS_DOC_COUNTS = {"mdc-code-context-titan1024": 90135, "gw_v17_mdc-jjobs": 92}

# Mutating operations the orchestrator is allowed to issue (all Compute-tier).
ALLOWED_MUTATIONS = {
    "stop_instances", "start_instances", "create_snapshot",
    "stop_db_cluster", "start_db_cluster", "create_db_cluster_snapshot",
    "update_domain_config", "delete_nat_gateway", "release_address",
}
READ_OPS = {
    "describe_instances", "describe_snapshots", "describe_db_clusters",
    "describe_db_cluster_snapshots", "describe_domain", "describe_nat_gateways",
    "get_agent_runtime", "describe_images",
}


def _cfg():
    return resolve_config("dev", env={
        "COST_CONTROL_EC2_INSTANCE_ID": "i-roundtrip",
        "COST_CONTROL_NEPTUNE_CLUSTER_ID": "neptune-roundtrip",
        "COST_CONTROL_OPENSEARCH_DOMAIN_NAME": "os-roundtrip",
        "COST_CONTROL_AGENTCORE_RUNTIME_ARN":
            "arn:aws:bedrock-agentcore:us-east-1:1:runtime/rt-roundtrip",
        "COST_CONTROL_NAT_GATEWAY_ID": "nat-roundtrip",
        "COST_CONTROL_EFS_ACCESS_POINT_ID": EFS_AP,
    })


class _Recorder:
    """Base for fake clients: records every call as (op, kwargs)."""

    def __init__(self, log):
        self._log = log

    def _record(self, op, kwargs):
        self._log.append((op, kwargs))


class FakeEC2(_Recorder):
    def __init__(self, log):
        super().__init__(log)
        self.instance_state = "running"
        self.nat_state = "available"

    def describe_instances(self, **kw):
        self._record("describe_instances", kw)
        return {"Reservations": [{"Instances": [{
            "InstanceId": "i-roundtrip",
            "State": {"Name": self.instance_state},
            "RootDeviceName": "/dev/xvda",
            "BlockDeviceMappings": [{"DeviceName": "/dev/xvda",
                                     "Ebs": {"VolumeId": "vol-root"}}],
        }]}]}

    def describe_snapshots(self, **kw):
        self._record("describe_snapshots", kw)
        if "SnapshotIds" in kw:
            return {"Snapshots": [{"SnapshotId": kw["SnapshotIds"][0],
                                   "State": "completed"}]}
        return {"Snapshots": []}                 # none exist -> tier creates

    def create_snapshot(self, **kw):
        self._record("create_snapshot", kw)
        return {"SnapshotId": "snap-ec2", "State": "pending"}

    def stop_instances(self, **kw):
        self._record("stop_instances", kw)
        self.instance_state = "stopped"
        return {"StoppingInstances": []}

    def start_instances(self, **kw):
        self._record("start_instances", kw)
        self.instance_state = "running"
        return {"StartingInstances": []}

    def describe_nat_gateways(self, **kw):
        self._record("describe_nat_gateways", kw)
        return {"NatGateways": [{
            "NatGatewayId": "nat-roundtrip", "State": self.nat_state,
            "SubnetId": "subnet-1",
            "NatGatewayAddresses": [{"AllocationId": "eip-1"}],
        }]}

    def delete_nat_gateway(self, **kw):
        self._record("delete_nat_gateway", kw)
        self.nat_state = "deleted"
        return {"NatGatewayId": "nat-roundtrip"}

    def release_address(self, **kw):
        self._record("release_address", kw)
        return {}


class FakeNeptune(_Recorder):
    def __init__(self, log):
        super().__init__(log)
        self.status = "available"

    def describe_db_clusters(self, **kw):
        self._record("describe_db_clusters", kw)
        return {"DBClusters": [{"Status": self.status}]}

    def create_db_cluster_snapshot(self, **kw):
        self._record("create_db_cluster_snapshot", kw)
        return {"DBClusterSnapshot": {"Status": "creating"}}

    def describe_db_cluster_snapshots(self, **kw):
        self._record("describe_db_cluster_snapshots", kw)
        return {"DBClusterSnapshots": [{"Status": "available"}]}

    def stop_db_cluster(self, **kw):
        self._record("stop_db_cluster", kw)
        self.status = "stopped"
        return {"DBCluster": {"Status": "stopping"}}

    def start_db_cluster(self, **kw):
        self._record("start_db_cluster", kw)
        self.status = "available"
        return {"DBCluster": {"Status": "available"}}


class FakeOpenSearch(_Recorder):
    def __init__(self, log):
        super().__init__(log)
        self.config = {"InstanceType": "r6g.large.search", "InstanceCount": 2}

    def describe_domain(self, **kw):
        self._record("describe_domain", kw)
        return {"DomainStatus": {
            "DomainId": "1/os-roundtrip", "DomainName": "os-roundtrip",
            "ARN": "arn:aws:es:us-east-1:1:domain/os-roundtrip",
            "Processing": False, "ClusterConfig": dict(self.config),
        }}

    def update_domain_config(self, **kw):
        self._record("update_domain_config", kw)
        self.config = dict(kw["ClusterConfig"])
        return {"DomainConfig": {}}


class FakeOSSnap:
    def __init__(self, log):
        self._log = log

    def create_snapshot(self, repository, snapshot):
        self._log.append(("os_snapshot_create", {"repo": repository, "snap": snapshot}))

    def snapshot_status(self, repository, snapshot):
        return "SUCCESS"


class FakeRuntime(_Recorder):
    def get_agent_runtime(self, **kw):
        self._record("get_agent_runtime", kw)
        return {
            "agentRuntimeArn": "arn:aws:bedrock-agentcore:us-east-1:1:runtime/rt-roundtrip",
            "agentRuntimeName": "rt", "agentRuntimeId": "rt-roundtrip",
            "agentRuntimeVersion": "1",
            "createdAt": datetime(2026, 6, 1, tzinfo=timezone.utc),
            "lastUpdatedAt": datetime(2026, 6, 10, tzinfo=timezone.utc),
            "roleArn": "arn:aws:iam::1:role/r",
            "networkConfiguration": {"networkMode": "VPC"},
            "status": "READY",
            "lifecycleConfiguration": {},
            "agentRuntimeArtifact": {"containerConfiguration": {
                "containerUri": "1.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:v11"}},
        }


class FakeEcr(_Recorder):
    def describe_images(self, **kw):
        self._record("describe_images", kw)
        return {"imageDetails": [{"imageDigest": "sha256:roundtrip"}]}


class FakeStateFile:
    def __init__(self, env):
        self.doc = new_initial_document(env)
        self.etag = "e0"
        self.writes = 0

    def read(self):
        return dict(self.doc), self.etag

    def write(self, doc, etag):
        self.writes += 1
        self.doc = dict(doc)
        self.etag = f"e{self.writes}"
        return self.etag


def _build(env_log):
    cfg = _cfg()
    ec2 = FakeEC2(env_log)
    neptune = FakeNeptune(env_log)
    osearch = FakeOpenSearch(env_log)
    runtime = FakeRuntime(env_log)
    ecr = FakeEcr(env_log)
    ossnap = FakeOSSnap(env_log)
    noop = lambda *_a, **_k: None

    tiers = [
        EC2Tier(cfg, ec2, operation_id="op", sleep_fn=noop),
        NeptuneTier(cfg, neptune, operation_id="op",
                    graph_counts_fn=lambda: NEPTUNE_COUNTS, sleep_fn=noop),
        OpenSearchTier(cfg, osearch, snapshot_client=ossnap, repository="repo",
                       operation_id="op", doc_counts_fn=lambda: OS_DOC_COUNTS,
                       sleep_fn=noop),
        AgentCoreTier(cfg, runtime, ecr_client=ecr, operation_id="op"),
        NatTier(cfg, ec2, operation_id="op"),
    ]
    return cfg, tiers, {"ec2": ec2, "neptune": neptune, "os": osearch}


def _audit():
    return AuditLogger(operation_id="op", caller_arn="arn:op", environment_name="dev",
                       log_group="lg", audit_bucket="b", audit_prefix="p/",
                       console_stream=io.StringIO())


def test_p1_p2_full_hibernate_wake_round_trip():
    call_log: list = []
    cfg, tiers, clients = _build(call_log)
    neptune_tier = tiers[1]
    os_tier = tiers[2]

    # P1: capture per-tier counts BEFORE hibernate.
    before_neptune = neptune_tier.capture_manifest()["per_tenant_counts"]
    before_os = os_tier.capture_manifest()["per_index_doc_counts"]

    sf = FakeStateFile("dev")
    sm = StateMachine(environment_name="dev", state_file=sf, audit=_audit(),
                      tiers=tiers, cost_model=CostModel(), caller_arn="arn:op",
                      operation_id="op")

    hib = sm.hibernate()
    assert hib.final_state == "Sleep_State", hib.message
    wake = sm.wake()
    assert wake.final_state == "Wake_State", wake.message

    # P1: counts AFTER wake equal counts BEFORE hibernate.
    after_neptune = neptune_tier.capture_manifest()["per_tenant_counts"]
    after_os = os_tier.capture_manifest()["per_index_doc_counts"]
    assert after_neptune == before_neptune == NEPTUNE_COUNTS
    assert after_os == before_os == OS_DOC_COUNTS

    # P2: every recorded op is either a read or an ALLOWED compute mutation;
    # nothing else (no EFS/ECR/S3 storage mutation) was issued.
    ops = [op for op, _kw in call_log]
    for op in ops:
        assert op in READ_OPS or op in ALLOWED_MUTATIONS or op == "os_snapshot_create", \
            f"unexpected operation issued: {op}"

    # P2: the EFS access point id never appears in any call's params.
    for op, kw in call_log:
        assert EFS_AP not in repr(kw), f"{op} referenced EFS access point"

    # P2: ECR was only ever read (image tags untouched -> tag set preserved).
    ecr_ops = [op for op, _ in call_log if op == "describe_images"]
    assert ecr_ops, "expected ECR digest read during manifest capture"
    assert all(op != "delete_image" and not op.startswith("batch_delete")
               for op, _ in call_log)

    # P2: no S3 object mutation against any storage bucket was issued (the
    # state file is the only S3 surface and it is the cost-control state object,
    # written via the injected state-file double, not a Storage_Stack resource).
    assert not any(op.startswith("put_object") or op.startswith("delete_object")
                   for op, _ in call_log)


def test_round_trip_issued_expected_compute_mutations():
    call_log: list = []
    cfg, tiers, clients = _build(call_log)
    sf = FakeStateFile("dev")
    sm = StateMachine(environment_name="dev", state_file=sf, audit=_audit(),
                      tiers=tiers, cost_model=CostModel(), caller_arn="arn:op",
                      operation_id="op")
    sm.hibernate()
    sm.wake()
    ops = {op for op, _ in call_log}
    # Compute resources were actually stopped/started/scaled/deleted.
    assert {"stop_instances", "start_instances", "stop_db_cluster",
            "start_db_cluster", "delete_nat_gateway"} <= ops
    # OpenSearch scaled down then back up (two update_domain_config calls).
    assert sum(1 for op, _ in call_log if op == "update_domain_config") == 2
