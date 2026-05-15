"""Unit tests for ``MCP_EMBEDDING_PROFILE`` parsing in
``src.config.environment`` (Phase C-2c, Requirements 7, 11).

Covers:

* unset → ``"titan1024"`` (Req 7.1)
* each of the six accepted values → that value preserved (Req 7.2)
* bogus value → :class:`ConfigError` listing all six accepted names
  (Req 7.3)
* selecting ``mpnet768`` triggers exactly one ``[WARN]`` log line per
  process (Req 7.4)
"""

from __future__ import annotations

import logging

import pytest

from src.config import ConfigError, ServerConfig, load_config
from src.config import environment as env_mod


@pytest.fixture(autouse=True)
def _reset_warn_guard() -> None:
    """Reset the one-shot mpnet warn guard before each test so the
    "exactly one warn" assertions are reproducible."""
    env_mod._reset_embedding_warn()
    yield
    env_mod._reset_embedding_warn()


# ── default (Requirement 7.1) ─────────────────────────────────────────


def test_unset_defaults_to_titan1024() -> None:
    cfg = load_config(env={})
    assert cfg.embedding_profile == "titan1024"
    assert isinstance(cfg, ServerConfig)


def test_empty_string_defaults_to_titan1024() -> None:
    cfg = load_config(env={"MCP_EMBEDDING_PROFILE": ""})
    assert cfg.embedding_profile == "titan1024"


# ── accepted values (Requirement 7.2) ─────────────────────────────────


@pytest.mark.parametrize(
    "value",
    ["titan1024", "mpnet768", "nova256", "nova512", "nova1024", "nova3072"],
)
def test_each_accepted_value_preserved(value: str) -> None:
    cfg = load_config(env={"MCP_EMBEDDING_PROFILE": value})
    assert cfg.embedding_profile == value


# ── invalid value (Requirement 7.3) ───────────────────────────────────


def test_bogus_value_raises_config_error_listing_six_accepted_names() -> None:
    with pytest.raises(ConfigError) as exc:
        load_config(env={"MCP_EMBEDDING_PROFILE": "not-a-profile"})

    message = str(exc.value)
    for name in (
        "titan1024",
        "mpnet768",
        "nova256",
        "nova512",
        "nova1024",
        "nova3072",
    ):
        assert name in message
    # Bad value also surfaces in the diagnostic.
    assert "not-a-profile" in message


def test_bogus_value_short_circuits_before_warn(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A ``ConfigError`` must short-circuit before any warn fires
    (Requirement 7.4 — only ``mpnet768`` triggers the warn line)."""
    caplog.set_level(logging.WARNING, logger="src.config.environment")
    with pytest.raises(ConfigError):
        load_config(env={"MCP_EMBEDDING_PROFILE": "garbage"})
    warn_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warn_records == []


# ── one-shot mpnet warn (Requirement 7.4) ─────────────────────────────


def test_mpnet768_emits_exactly_one_warn_log_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A single ``[WARN]`` line is emitted on the first ``mpnet768``
    selection (Requirement 7.4)."""
    caplog.set_level(logging.WARNING, logger="src.config.environment")
    cfg = load_config(env={"MCP_EMBEDDING_PROFILE": "mpnet768"})
    assert cfg.embedding_profile == "mpnet768"

    warn_records = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "MCP_EMBEDDING_PROFILE" in r.getMessage()
    ]
    assert len(warn_records) == 1
    message = warn_records[0].getMessage()
    assert "[WARN]" in message
    assert "mpnet768" in message
    assert "sentence-transformers" in message


def test_mpnet768_warn_is_one_shot_across_repeated_load_config_calls(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A second ``load_config`` call with ``mpnet768`` must NOT
    re-emit the warn — the guard makes it one-shot per process
    (Requirement 7.4)."""
    caplog.set_level(logging.WARNING, logger="src.config.environment")
    load_config(env={"MCP_EMBEDDING_PROFILE": "mpnet768"})
    load_config(env={"MCP_EMBEDDING_PROFILE": "mpnet768"})
    load_config(env={"MCP_EMBEDDING_PROFILE": "mpnet768"})

    warn_records = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "MCP_EMBEDDING_PROFILE" in r.getMessage()
    ]
    assert len(warn_records) == 1


def test_titan1024_does_not_emit_warn(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="src.config.environment")
    load_config(env={"MCP_EMBEDDING_PROFILE": "titan1024"})
    warn_records = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "MCP_EMBEDDING_PROFILE" in r.getMessage()
    ]
    assert warn_records == []


@pytest.mark.parametrize("nova", ["nova256", "nova512", "nova1024", "nova3072"])
def test_nova_profiles_do_not_emit_warn(
    caplog: pytest.LogCaptureFixture, nova: str
) -> None:
    caplog.set_level(logging.WARNING, logger="src.config.environment")
    load_config(env={"MCP_EMBEDDING_PROFILE": nova})
    warn_records = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "MCP_EMBEDDING_PROFILE" in r.getMessage()
    ]
    assert warn_records == []


# ── ServerConfig field shape ─────────────────────────────────────────


def test_server_config_has_embedding_profile_attribute() -> None:
    cfg = ServerConfig()
    assert hasattr(cfg, "embedding_profile")
    assert cfg.embedding_profile == "titan1024"
