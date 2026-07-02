"""Unit tests for ``src.config.environment`` (Requirement 1.8)."""

from __future__ import annotations

import pytest

from src.config import (
    DEFAULT_AWS_REGION,
    DEFAULT_HOST,
    DEFAULT_PORT,
    KNOWN_MODULES,
    ConfigError,
    ServerConfig,
    load_config,
)


# ── defaults ───────────────────────────────────────────────────────────────


def test_defaults_with_empty_env():
    """An empty env dict should yield the documented defaults."""
    cfg = load_config(env={})
    assert cfg.db_backend == "aws"
    assert cfg.aws_region == DEFAULT_AWS_REGION
    assert cfg.host == DEFAULT_HOST
    assert cfg.port == DEFAULT_PORT
    assert cfg.neptune_endpoint == ""
    assert cfg.opensearch_endpoint == ""
    assert cfg.github_token is None
    assert cfg.sdd_state_dir == "sdd_framework/execution_state"
    assert cfg.enabled_modules == ()


def test_defaults_are_frozen():
    """ServerConfig is immutable (frozen dataclass)."""
    cfg = load_config(env={})
    with pytest.raises((AttributeError, Exception)):
        cfg.db_backend = "cots"  # type: ignore[misc]


# ── DB_BACKEND routing (Requirement 1.8) ──────────────────────────────────


@pytest.mark.parametrize("backend", ["aws", "cots"])
def test_valid_db_backends(backend):
    cfg = load_config(env={"DB_BACKEND": backend})
    assert cfg.db_backend == backend
    assert cfg.is_aws() is (backend == "aws")
    assert cfg.is_cots() is (backend == "cots")
    # is_legacy() is a deprecated alias for is_cots() through Phase 64
    assert cfg.is_legacy() is cfg.is_cots()


def test_db_backend_case_insensitive():
    assert load_config(env={"DB_BACKEND": "AWS"}).db_backend == "aws"
    assert load_config(env={"DB_BACKEND": " Cots "}).db_backend == "cots"


def test_db_backend_invalid_raises():
    with pytest.raises(ConfigError, match="DB_BACKEND"):
        load_config(env={"DB_BACKEND": "neo4j"})


# ── endpoint loading ──────────────────────────────────────────────────────


def test_endpoints_loaded_from_env():
    env = {
        "DB_BACKEND": "aws",
        "NEPTUNE_ENDPOINT": "wss://example.neptune.amazonaws.com:8182",
        "OPENSEARCH_ENDPOINT": "vpc-example.us-east-1.es.amazonaws.com",
        "AWS_REGION": "us-west-2",
    }
    cfg = load_config(env=env)
    assert cfg.neptune_endpoint == "wss://example.neptune.amazonaws.com:8182"
    assert cfg.opensearch_endpoint == "vpc-example.us-east-1.es.amazonaws.com"
    assert cfg.aws_region == "us-west-2"


def test_empty_aws_region_falls_back_to_default():
    cfg = load_config(env={"AWS_REGION": "   "})
    assert cfg.aws_region == DEFAULT_AWS_REGION


# ── PORT parsing ──────────────────────────────────────────────────────────


def test_port_parsed_as_int():
    cfg = load_config(env={"PORT": "9000"})
    assert cfg.port == 9000
    assert isinstance(cfg.port, int)


def test_port_empty_uses_default():
    cfg = load_config(env={"PORT": ""})
    assert cfg.port == DEFAULT_PORT


def test_port_non_numeric_raises():
    with pytest.raises(ConfigError, match="PORT"):
        load_config(env={"PORT": "not-a-number"})


@pytest.mark.parametrize("bad", ["0", "65536", "-1", "99999"])
def test_port_out_of_range_raises(bad):
    with pytest.raises(ConfigError, match="PORT"):
        load_config(env={"PORT": bad})


# ── GITHUB_TOKEN optionality ──────────────────────────────────────────────


def test_github_token_none_when_unset():
    assert load_config(env={}).github_token is None


def test_github_token_empty_string_is_none():
    # Empty string should map to None so auth checks can use truthiness.
    assert load_config(env={"GITHUB_TOKEN": ""}).github_token is None


def test_github_token_preserved():
    assert load_config(env={"GITHUB_TOKEN": "ghp_abc"}).github_token == "ghp_abc"


# ── module whitelist (Requirement 18.3) ───────────────────────────────────


def test_enabled_modules_default_is_empty_tuple():
    cfg = load_config(env={})
    assert cfg.enabled_modules == ()
    # Empty tuple means "all enabled"
    for name in KNOWN_MODULES:
        assert cfg.module_enabled(name)


def test_enabled_modules_parsed_from_env():
    cfg = load_config(
        env={"MCP_ENABLED_MODULES": "semantic_search,code_analysis"}
    )
    assert cfg.enabled_modules == ("semantic_search", "code_analysis")
    assert cfg.module_enabled("semantic_search")
    assert cfg.module_enabled("code_analysis")
    assert not cfg.module_enabled("graph_rag")


def test_enabled_modules_strips_whitespace():
    cfg = load_config(
        env={"MCP_ENABLED_MODULES": " semantic_search , code_analysis "}
    )
    assert cfg.enabled_modules == ("semantic_search", "code_analysis")


def test_unknown_module_raises():
    with pytest.raises(ConfigError, match="Unknown module"):
        load_config(env={"MCP_ENABLED_MODULES": "nonsense"})


def test_module_override_beats_env_var():
    # The --modules CLI flag (passed as ``enabled_modules`` kwarg) wins.
    cfg = load_config(
        env={"MCP_ENABLED_MODULES": "semantic_search"},
        enabled_modules=("code_analysis",),
    )
    assert cfg.enabled_modules == ("code_analysis",)


def test_module_override_empty_means_all():
    # Passing an empty tuple explicitly still means "all modules".
    cfg = load_config(
        env={"MCP_ENABLED_MODULES": "semantic_search"},
        enabled_modules=(),
    )
    assert cfg.enabled_modules == ()
    for name in KNOWN_MODULES:
        assert cfg.module_enabled(name)


def test_known_modules_covers_nine_tool_modules():
    # Sanity — the README + requirements call out 9 modules.
    assert len(KNOWN_MODULES) == 9


# ── cots backend config ───────────────────────────────────────────────────


def test_cots_backend_neo4j_defaults():
    cfg = load_config(env={"DB_BACKEND": "cots"})
    assert cfg.neo4j_uri == "bolt://localhost:7687"
    assert cfg.chromadb_host == "localhost"
    assert cfg.chromadb_port == 8080


def test_cots_backend_neo4j_overrides():
    cfg = load_config(
        env={
            "DB_BACKEND": "cots",
            "NEO4J_URI": "bolt://remote:7687",
            "NEO4J_USER": "admin",
            "NEO4J_PASSWORD": "s3cr3t",
            "CHROMADB_HOST": "chromadb.internal",
            "CHROMADB_PORT": "9000",
        }
    )
    assert cfg.neo4j_uri == "bolt://remote:7687"
    assert cfg.neo4j_user == "admin"
    assert cfg.neo4j_password == "s3cr3t"
    assert cfg.chromadb_host == "chromadb.internal"
    assert cfg.chromadb_port == 9000


def test_chromadb_port_non_numeric_raises():
    with pytest.raises(ConfigError, match="PORT"):
        load_config(env={"CHROMADB_PORT": "nope"})


# ── SDD state dir ─────────────────────────────────────────────────────────


def test_sdd_state_dir_override():
    cfg = load_config(env={"SDD_STATE_DIR": "/tmp/sdd"})
    assert cfg.sdd_state_dir == "/tmp/sdd"


# ── env=None uses os.environ ──────────────────────────────────────────────


def test_env_none_reads_os_environ(monkeypatch):
    monkeypatch.setenv("DB_BACKEND", "cots")
    monkeypatch.setenv("PORT", "4242")
    cfg = load_config()  # no env arg -> real os.environ
    assert cfg.db_backend == "cots"
    assert cfg.port == 4242


# ── dataclass shape ───────────────────────────────────────────────────────


def test_server_config_is_a_dataclass_with_expected_fields():
    cfg = ServerConfig()
    for attr in (
        "db_backend",
        "neptune_endpoint",
        "opensearch_endpoint",
        "aws_region",
        "github_token",
        "sdd_state_dir",
        "host",
        "port",
        "enabled_modules",
    ):
        assert hasattr(cfg, attr)
