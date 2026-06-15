"""Unit tests for cost_control.config (Task 1.1).

Covers Requirements 13.1 (Environment_Name resolution) and 13.4
(valid_environments allow-list): valid env resolves, invalid env is
rejected, and env-var override precedence over per-env defaults.
"""

from __future__ import annotations

import pytest

from cost_control import config
from cost_control.config import ConfigError, EnvironmentConfig, resolve_config


def test_valid_env_resolves_prod_defaults():
    cfg = resolve_config("prod", env={})
    assert isinstance(cfg, EnvironmentConfig)
    assert cfg.environment_name == "prod"
    assert cfg.aws_region == "us-east-1"
    assert cfg.neptune_cluster_id == "mdc-mcp-graprag-neptune-1"
    assert cfg.opensearch_domain_name == "mdc-mcp-rag-search"
    assert cfg.efs_access_point_id == "fsap-03e641f056b341f29"
    assert cfg.subnet_ids == (
        "subnet-0e13af6b3a9a6416f",
        "subnet-04447750c61bd7e06",
    )
    assert cfg.security_group_ids == ("sg-096489a0876cc78c1",)


def test_valid_env_dev_has_empty_compute_and_derived_buckets():
    cfg = resolve_config("dev", env={})
    assert cfg.environment_name == "dev"
    # No compute ids by default for dev.
    assert cfg.ec2_instance_id is None
    assert cfg.neptune_cluster_id is None
    assert cfg.nat_gateway_id is None
    assert cfg.subnet_ids == ()
    # Buckets always have a derived, env-suffixed home.
    assert cfg.state_bucket == "mdc-mcp-rag-cost-control-state-dev"
    assert cfg.audit_bucket == "mdc-mcp-rag-cost-control-audit-dev"
    assert cfg.snapshot_bucket == "mdc-mcp-rag-cost-control-snapshots-dev"


@pytest.mark.parametrize("bad", ["production", "qa", "DEV", "", "test"])
def test_invalid_env_rejected(bad):
    with pytest.raises(ConfigError) as exc:
        resolve_config(bad, env={})
    assert "valid_environments" in str(exc.value)


def test_custom_allow_list_rejects_default_member():
    # prod is normally valid, but an explicit allow-list excludes it.
    with pytest.raises(ConfigError):
        resolve_config("prod", env={}, valid_environments=("dev",))


def test_env_var_override_takes_precedence_over_default():
    env = {
        "COST_CONTROL_NEPTUNE_CLUSTER_ID": "neptune-override",
        "COST_CONTROL_EC2_INSTANCE_ID": "i-0override",
    }
    cfg = resolve_config("prod", env=env)
    # Override wins over the prod default.
    assert cfg.neptune_cluster_id == "neptune-override"
    # Override supplies a value dev would otherwise lack.
    assert cfg.ec2_instance_id == "i-0override"
    # Untouched prod default still present.
    assert cfg.opensearch_domain_name == "mdc-mcp-rag-search"


def test_env_var_override_for_buckets():
    env = {"COST_CONTROL_STATE_BUCKET": "my-state-bucket"}
    cfg = resolve_config("dev", env=env)
    assert cfg.state_bucket == "my-state-bucket"
    # Other buckets keep the derived default.
    assert cfg.audit_bucket == "mdc-mcp-rag-cost-control-audit-dev"


def test_list_override_is_comma_split_and_trimmed():
    env = {"COST_CONTROL_SUBNET_IDS": " subnet-a , subnet-b ,subnet-c "}
    cfg = resolve_config("dev", env=env)
    assert cfg.subnet_ids == ("subnet-a", "subnet-b", "subnet-c")


def test_region_resolution_precedence():
    # COST_CONTROL_AWS_REGION wins over AWS_REGION.
    env = {"AWS_REGION": "us-west-2", "COST_CONTROL_AWS_REGION": "eu-west-1"}
    assert resolve_config("dev", env=env).aws_region == "eu-west-1"
    # AWS_REGION used when no explicit override.
    assert resolve_config("dev", env={"AWS_REGION": "us-west-2"}).aws_region == "us-west-2"
    # Default when neither set.
    assert resolve_config("dev", env={}).aws_region == "us-east-1"


def test_derived_properties():
    cfg = resolve_config("staging", env={})
    assert cfg.state_key == "cost-control/staging/state.json"
    assert cfg.audit_prefix == "cost-control/staging/"
    assert cfg.log_group == "mdc-mcp-rag-cost-control-staging"
    assert cfg.environment_tag == {"mdc-mcp-rag:environment": "staging"}


def test_config_is_frozen():
    cfg = resolve_config("dev", env={})
    with pytest.raises(Exception):
        cfg.environment_name = "prod"  # type: ignore[misc]


def test_build_session_uses_region(monkeypatch):
    captured = {}

    class _FakeSession:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(config, "boto3", type("M", (), {"Session": _FakeSession}))
    config.build_session(region_name="ap-south-1")
    assert captured["region_name"] == "ap-south-1"
