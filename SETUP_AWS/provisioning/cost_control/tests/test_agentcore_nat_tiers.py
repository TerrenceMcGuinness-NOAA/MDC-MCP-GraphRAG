"""Unit tests for cost_control.tiers.agentcore_tier and nat_tier (Task 10.1).

botocore Stubber for bedrock-agentcore-control / ecr / ec2. Asserts AgentCore
hibernate mutates nothing, manifest captures runtime ARN + image digest, wake
re-points only on drift; NAT delete + EIP release issued on hibernate with
manifest capture, and wake is a no-op.

Requirements: 3.3.
"""

from __future__ import annotations

from datetime import datetime, timezone

import boto3
from botocore.stub import Stubber

from cost_control.config import resolve_config
from cost_control.tiers.agentcore_tier import AgentCoreTier
from cost_control.tiers.nat_tier import NatTier

RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-east-1:903050880929:"
    "runtime/mdc_mcp_rag_server_python-v5K2F8BGrN"
)
RUNTIME_ID = "mdc_mcp_rag_server_python-v5K2F8BGrN"
NAT_ID = "nat-0abc123"


# ── AgentCore ──────────────────────────────────────────────────────────────

def _ac_cfg():
    return resolve_config("dev", env={"COST_CONTROL_AGENTCORE_RUNTIME_ARN": RUNTIME_ARN})


def _runtime(tag, digest_uri="123456789012.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag"):
    return {
        "agentRuntimeArn": RUNTIME_ARN,
        "agentRuntimeName": "mdc_mcp_rag_server_python",
        "agentRuntimeId": RUNTIME_ID,
        "agentRuntimeVersion": "1",
        "createdAt": datetime(2026, 6, 1, tzinfo=timezone.utc),
        "lastUpdatedAt": datetime(2026, 6, 10, tzinfo=timezone.utc),
        "roleArn": "arn:aws:iam::903050880929:role/mdc-mcp-rag-ecs-task-role",
        "networkConfiguration": {"networkMode": "VPC"},
        "lifecycleConfiguration": {"idleRuntimeSessionTimeout": 900, "maxLifetime": 28800},
        "status": "READY",
        "agentRuntimeArtifact": {
            "containerConfiguration": {"containerUri": f"{digest_uri}:{tag}"}
        },
    }


def test_agentcore_hibernate_is_noop():
    rt = boto3.client("bedrock-agentcore-control", region_name="us-east-1")
    with Stubber(rt) as stub:
        # No calls expected at all on hibernate.
        tier = AgentCoreTier(_ac_cfg(), rt)
        assert tier.hibernate() == []
        assert tier.is_asleep() is True
        stub.assert_no_pending_responses()


def test_agentcore_runtime_id_parsed_from_arn():
    rt = boto3.client("bedrock-agentcore-control", region_name="us-east-1")
    assert AgentCoreTier(_ac_cfg(), rt).runtime_id == RUNTIME_ID


def test_agentcore_capture_manifest_with_ecr_digest():
    rt = boto3.client("bedrock-agentcore-control", region_name="us-east-1")
    ecr = boto3.client("ecr", region_name="us-east-1")
    with Stubber(rt) as rt_stub, Stubber(ecr) as ecr_stub:
        rt_stub.add_response("get_agent_runtime", _runtime("python-tenants-v11"),
                             {"agentRuntimeId": RUNTIME_ID})
        ecr_stub.add_response(
            "describe_images",
            {"imageDetails": [{"imageDigest": "sha256:15802a0e"}]},
            {"repositoryName": "mdc-mcp-rag",
             "imageIds": [{"imageTag": "python-tenants-v11"}]},
        )
        m = AgentCoreTier(_ac_cfg(), rt, ecr_client=ecr).capture_manifest()
    assert m["runtime_arn"] == RUNTIME_ARN
    assert m["runtime_id"] == RUNTIME_ID
    assert m["container_uri"].endswith(":python-tenants-v11")
    assert m["image_digest"] == "sha256:15802a0e"


def test_agentcore_wake_noop_without_expected_manifest():
    rt = boto3.client("bedrock-agentcore-control", region_name="us-east-1")
    with Stubber(rt) as stub:
        assert AgentCoreTier(_ac_cfg(), rt).wake() == []
        stub.assert_no_pending_responses()


def test_agentcore_wake_noop_when_digest_unchanged():
    rt = boto3.client("bedrock-agentcore-control", region_name="us-east-1")
    ecr = boto3.client("ecr", region_name="us-east-1")
    expected = {"image_digest": "sha256:same", "container_uri": "repo:v11"}
    with Stubber(rt) as rt_stub, Stubber(ecr) as ecr_stub:
        rt_stub.add_response("get_agent_runtime", _runtime("v11"),
                             {"agentRuntimeId": RUNTIME_ID})
        ecr_stub.add_response(
            "describe_images",
            {"imageDetails": [{"imageDigest": "sha256:same"}]},
            {"repositoryName": "mdc-mcp-rag", "imageIds": [{"imageTag": "v11"}]},
        )
        tier = AgentCoreTier(_ac_cfg(), rt, ecr_client=ecr, expected_manifest=expected)
        assert tier.wake() == []
        rt_stub.assert_no_pending_responses()


def test_agentcore_wake_repoints_on_drift():
    rt = boto3.client("bedrock-agentcore-control", region_name="us-east-1")
    ecr = boto3.client("ecr", region_name="us-east-1")
    expected = {"image_digest": "sha256:OLD", "container_uri": "repo:v10"}
    with Stubber(rt) as rt_stub, Stubber(ecr) as ecr_stub:
        # live runtime now points at a different digest
        rt_stub.add_response("get_agent_runtime", _runtime("v11"),
                             {"agentRuntimeId": RUNTIME_ID})
        ecr_stub.add_response(
            "describe_images",
            {"imageDetails": [{"imageDigest": "sha256:NEW"}]},
            {"repositoryName": "mdc-mcp-rag", "imageIds": [{"imageTag": "v11"}]},
        )
        rt_stub.add_response(
            "update_agent_runtime",
            {"agentRuntimeArn": RUNTIME_ARN, "agentRuntimeId": RUNTIME_ID,
             "agentRuntimeVersion": "2",
             "createdAt": datetime(2026, 6, 1, tzinfo=timezone.utc),
             "lastUpdatedAt": datetime(2026, 6, 15, tzinfo=timezone.utc),
             "status": "UPDATING"},
        )
        tier = AgentCoreTier(_ac_cfg(), rt, ecr_client=ecr, expected_manifest=expected)
        actions = tier.wake()
        rt_stub.assert_no_pending_responses()
    assert any(a.action == "update_agent_runtime" for a in actions)


# ── NAT ──────────────────────────────────────────────────────────────────

def _nat_cfg():
    return resolve_config("dev", env={"COST_CONTROL_NAT_GATEWAY_ID": NAT_ID})


def _nat(state, allocs=("eipalloc-1",)):
    return {"NatGateways": [{
        "NatGatewayId": NAT_ID,
        "State": state,
        "SubnetId": "subnet-0e13af6b3a9a6416f",
        "NatGatewayAddresses": [{"AllocationId": a} for a in allocs],
    }]}


def test_nat_is_asleep_when_absent():
    ec2 = boto3.client("ec2", region_name="us-east-1")
    with Stubber(ec2) as stub:
        stub.add_response("describe_nat_gateways", {"NatGateways": []},
                          {"NatGatewayIds": [NAT_ID]})
        assert NatTier(_nat_cfg(), ec2).is_asleep() is True


def test_nat_capture_manifest():
    ec2 = boto3.client("ec2", region_name="us-east-1")
    with Stubber(ec2) as stub:
        stub.add_response("describe_nat_gateways", _nat("available", ("a1", "a2")),
                          {"NatGatewayIds": [NAT_ID]})
        m = NatTier(_nat_cfg(), ec2).capture_manifest()
    assert m["nat_gateway_id"] == NAT_ID
    assert m["allocation_ids"] == ["a1", "a2"]
    assert m["subnet_id"] == "subnet-0e13af6b3a9a6416f"


def test_nat_hibernate_deletes_and_releases():
    ec2 = boto3.client("ec2", region_name="us-east-1")
    with Stubber(ec2) as stub:
        stub.add_response("describe_nat_gateways", _nat("available", ("a1", "a2")),
                          {"NatGatewayIds": [NAT_ID]})
        stub.add_response("delete_nat_gateway", {"NatGatewayId": NAT_ID},
                          {"NatGatewayId": NAT_ID})
        stub.add_response("release_address", {}, {"AllocationId": "a1"})
        stub.add_response("release_address", {}, {"AllocationId": "a2"})
        actions = NatTier(_nat_cfg(), ec2).hibernate()
        stub.assert_no_pending_responses()
    kinds = [a.action for a in actions]
    assert kinds.count("release_address") == 2
    assert "delete_nat_gateway" in kinds


def test_nat_hibernate_noop_when_already_deleted():
    ec2 = boto3.client("ec2", region_name="us-east-1")
    with Stubber(ec2) as stub:
        stub.add_response("describe_nat_gateways", _nat("deleted"),
                          {"NatGatewayIds": [NAT_ID]})
        assert NatTier(_nat_cfg(), ec2).hibernate() == []
        stub.assert_no_pending_responses()


def test_nat_wake_is_noop():
    ec2 = boto3.client("ec2", region_name="us-east-1")
    with Stubber(ec2) as stub:
        assert NatTier(_nat_cfg(), ec2).wake() == []
        stub.assert_no_pending_responses()
