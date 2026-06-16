"""Unit tests for portable_export.config (Task 1.1).

Covers Requirements 7.1 (tenant enumeration) and 11.1 (source endpoints in
manifest): valid env resolves, invalid env rejected, tenant catalog parsed
from tenants.yaml, env-var override precedence, and model-profile registry.
"""

from __future__ import annotations

import pytest

from portable_export import config
from portable_export.config import (
    ConfigError,
    EnvironmentConfig,
    TenantCatalog,
    load_tenant_catalog,
    model_profile,
    model_profile_dimensions,
    resolve_config,
)


def test_valid_env_resolves_prod_defaults(tenants_yaml_path):
    cfg = resolve_config("prod", env={}, tenants_path=tenants_yaml_path)
    assert isinstance(cfg, EnvironmentConfig)
    assert cfg.environment_name == "prod"
    assert cfg.aws_region == "us-east-1"
    assert cfg.opensearch_endpoint and "es.amazonaws.com" in cfg.opensearch_endpoint
    assert cfg.neptune_endpoint and "neptune.amazonaws.com" in cfg.neptune_endpoint
    assert cfg.dedupe_table == "mdc-content-sha-registry"


def test_default_bucket_used_when_unset(tenants_yaml_path):
    cfg = resolve_config("dev", env={}, tenants_path=tenants_yaml_path)
    assert cfg.portable_export_bucket == "mdc-mcp-rag-snapshots-903050880929"
    # dev has no source endpoints by default.
    assert cfg.opensearch_endpoint is None
    assert cfg.neptune_endpoint is None


@pytest.mark.parametrize("bad", ["production", "qa", "DEV", "", "test"])
def test_invalid_env_rejected(bad, tenants_yaml_path):
    with pytest.raises(ConfigError) as exc:
        resolve_config(bad, env={}, tenants_path=tenants_yaml_path)
    assert "valid_environments" in str(exc.value)


def test_bare_platform_vars_honoured(tenants_yaml_path):
    env = {
        "AWS_REGION": "us-west-2",
        "PORTABLE_EXPORT_BUCKET": "my-bucket",
        "OPENSEARCH_ENDPOINT": "https://os.example",
        "NEPTUNE_ENDPOINT": "https://neptune.example:8182",
    }
    cfg = resolve_config("dev", env=env, tenants_path=tenants_yaml_path)
    assert cfg.aws_region == "us-west-2"
    assert cfg.portable_export_bucket == "my-bucket"
    assert cfg.opensearch_endpoint == "https://os.example"
    assert cfg.neptune_endpoint == "https://neptune.example:8182"


def test_prefixed_override_beats_bare_var(tenants_yaml_path):
    env = {
        "AWS_REGION": "us-west-2",
        "PORTABLE_EXPORT_AWS_REGION": "eu-west-1",
        "PORTABLE_EXPORT_BUCKET": "bare",
        # there is no distinct prefixed bucket var; bucket uses PORTABLE_EXPORT_BUCKET
    }
    cfg = resolve_config("dev", env=env, tenants_path=tenants_yaml_path)
    assert cfg.aws_region == "eu-west-1"


def test_kms_key_override(tenants_yaml_path):
    env = {"PORTABLE_EXPORT_KMS_KEY_ARN": "arn:aws:kms:us-east-1:1:key/abc"}
    cfg = resolve_config("dev", env=env, tenants_path=tenants_yaml_path)
    assert cfg.kms_key_arn == "arn:aws:kms:us-east-1:1:key/abc"


def test_derived_prefix_and_log_group(tenants_yaml_path):
    cfg = resolve_config("staging", env={}, tenants_path=tenants_yaml_path)
    assert cfg.audit_log_group == "mdc-mcp-rag-portable-export-staging"
    assert cfg.default_prefix("abc123") == "portable-export/staging/abc123/"
    assert cfg.environment_tag == {"mdc-mcp-rag:environment": "staging"}


def test_config_is_frozen(tenants_yaml_path):
    cfg = resolve_config("dev", env={}, tenants_path=tenants_yaml_path)
    with pytest.raises(Exception):
        cfg.environment_name = "prod"  # type: ignore[misc]


# ── Tenant catalog ─────────────────────────────────────────────────────────


def test_tenant_catalog_parsed(tenants_yaml_path):
    catalog = load_tenant_catalog(tenants_yaml_path)
    assert isinstance(catalog, TenantCatalog)
    assert catalog.default_tenant_id == "gw"
    # All five known tenants present (R7.1).
    assert set(catalog.tenant_ids) == {
        "gw",
        "gw_sfs",
        "gw_jedi_gfs",
        "gw_v17",
        "gw_gefs_v12",
    }


def test_default_tenant_is_unprefixed(tenants_yaml_path):
    catalog = load_tenant_catalog(tenants_yaml_path)
    gw = catalog.by_id("gw")
    assert gw is not None
    assert gw.is_default is True
    assert gw.index_prefix == ""
    assert gw.label_prefix == ""


def test_non_default_tenant_prefixes(tenants_yaml_path):
    catalog = load_tenant_catalog(tenants_yaml_path)
    v17 = catalog.by_id("gw_v17")
    assert v17 is not None
    assert v17.is_default is False
    assert v17.index_prefix == "gw_v17_"
    assert v17.label_prefix == "GW_V17_"


def test_unknown_tenant_returns_none(tenants_yaml_path):
    catalog = load_tenant_catalog(tenants_yaml_path)
    assert catalog.by_id("nope") is None


def test_missing_catalog_raises(tmp_path):
    with pytest.raises(ConfigError) as exc:
        load_tenant_catalog(tmp_path / "absent.yaml")
    assert "not found" in str(exc.value)


def test_catalog_without_tenants_key_raises(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("schema_version: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_tenant_catalog(bad)
    assert "no 'tenants'" in str(exc.value)


# ── Model profiles ───────────────────────────────────────────────────────


def test_model_profile_dimensions():
    assert model_profile_dimensions("titan1024") == 1024
    assert model_profile_dimensions("mpnet768") == 768
    assert model_profile_dimensions("nova3072") == 3072


def test_unknown_model_profile_raises():
    with pytest.raises(ConfigError):
        model_profile("titan9999")


def test_infer_model_profile():
    assert config.infer_model_profile("mdc-code-context-titan1024") == "titan1024"
    assert config.infer_model_profile("gw_v17_mdc-jjobs-mpnet768") == "mpnet768"
    assert config.infer_model_profile("legacy-collection") is None


def test_build_session_uses_region(monkeypatch):
    captured = {}

    class _FakeSession:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(config, "boto3", type("M", (), {"Session": _FakeSession}))
    config.build_session(region_name="ap-south-1")
    assert captured["region_name"] == "ap-south-1"
