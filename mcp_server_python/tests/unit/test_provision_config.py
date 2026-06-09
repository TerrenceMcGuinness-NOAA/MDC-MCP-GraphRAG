"""Unit tests for ``ConfigResolver`` (Requirements 2, 10, 13; Task 4.1)."""

from __future__ import annotations

import io
import os
import tempfile

import pytest

from tests.unit._provision_loader import prov


def _logger():
    return prov.Logger(prov.SecretRedactor(), stream=io.StringIO())


def _parse(argv):
    return prov.ConfigResolver.build_parser().parse_args(argv)


def _resolve(argv, environ=None, files=None):
    """Resolve with a fake proxy filesystem (files = set of existing files)."""
    files = files if files is not None else {prov.DEFAULT_PROXY_PATH}
    return prov.ConfigResolver.resolve(
        _parse(argv),
        _logger(),
        environ=environ if environ is not None else {},
        isfile=lambda p: p in files,
        access=lambda p, m: p in files,
        realpath=lambda p: p,
    )


# --- precedence -----------------------------------------------------------

def test_defaults_used_when_no_cli_or_env():
    cfg = _resolve(["--all"])
    assert cfg.runtime_arn == prov.DEFAULT_RUNTIME_ARN
    assert cfg.region == prov.DEFAULT_REGION
    assert cfg.proxy_path == prov.DEFAULT_PROXY_PATH
    assert cfg.runtime_arn_source == "default"
    assert cfg.region_source == "default"
    assert cfg.proxy_path_source == "default"


def test_env_overrides_default():
    env = {
        "AGENTCORE_RUNTIME_ARN": "arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/foo_bar-1",
        "AWS_REGION": "us-west-2",
        "AGENTCORE_PROXY_PATH": "/opt/proxy.py",
    }
    cfg = _resolve(["--all"], environ=env, files={"/opt/proxy.py"})
    assert cfg.region == "us-west-2" and cfg.region_source == "env"
    assert cfg.proxy_path == "/opt/proxy.py" and cfg.proxy_path_source == "env"
    assert cfg.runtime_arn_source == "env"


def test_cli_overrides_env_and_default():
    env = {"AWS_REGION": "us-west-2"}
    cfg = _resolve(["--all", "--region", "eu-central-1"], environ=env)
    assert cfg.region == "eu-central-1" and cfg.region_source == "cli"


def test_empty_env_value_falls_back_to_default():
    cfg = _resolve(["--all"], environ={"AWS_REGION": ""})
    assert cfg.region == prov.DEFAULT_REGION and cfg.region_source == "default"


# --- regex validation -----------------------------------------------------

def test_bad_arn_rejected():
    with pytest.raises(prov.ProvisioningError) as exc:
        _resolve(["--all", "--runtime-arn", "not-an-arn"])
    assert exc.value.code == prov.EXIT_CONFIG


def test_good_arn_accepted():
    arn = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/my.runtime_v1-2"
    cfg = _resolve(["--all", "--runtime-arn", arn])
    assert cfg.runtime_arn == arn


def test_bad_region_rejected():
    with pytest.raises(prov.ProvisioningError) as exc:
        _resolve(["--all", "--region", "US-EAST-1"])
    assert exc.value.code == prov.EXIT_CONFIG


def test_good_region_accepted():
    cfg = _resolve(["--all", "--region", "ap-southeast-2"])
    assert cfg.region == "ap-southeast-2"


# --- proxy path -----------------------------------------------------------

def test_proxy_path_missing_rejected():
    with pytest.raises(prov.ProvisioningError) as exc:
        _resolve(["--all", "--proxy-path", "/nope.py"], files=set())
    assert exc.value.code == prov.EXIT_CONFIG


def test_proxy_path_symlink_to_regular_file_accepted():
    # realpath resolves the symlink to a real file present in `files`.
    cfg = prov.ConfigResolver.resolve(
        _parse(["--all", "--proxy-path", "/link.py"]),
        _logger(),
        environ={},
        isfile=lambda p: p == "/real.py",
        access=lambda p, m: p == "/real.py",
        realpath=lambda p: "/real.py",
    )
    assert cfg.proxy_path == "/real.py"


def test_proxy_path_symlink_to_missing_target_rejected():
    with pytest.raises(prov.ProvisioningError) as exc:
        prov.ConfigResolver.resolve(
            _parse(["--all", "--proxy-path", "/link.py"]),
            _logger(),
            environ={},
            isfile=lambda p: False,
            access=lambda p, m: False,
            realpath=lambda p: "/dangling.py",
        )
    assert exc.value.code == prov.EXIT_CONFIG


# --- mode mutual-exclusion -------------------------------------------------

def test_all_and_user_conflict_exits_2():
    with pytest.raises(prov.ProvisioningError) as exc:
        _resolve(["--all", "--user", "alice"])
    assert exc.value.code == prov.EXIT_ARG


def test_neither_all_nor_user_exits_2():
    with pytest.raises(prov.ProvisioningError) as exc:
        _resolve([])
    assert exc.value.code == prov.EXIT_ARG


def test_user_mode_sets_single_mode():
    cfg = _resolve(["--user", "alice"])
    assert cfg.mode == "single" and cfg.target_user == "alice"


# --- exclude-file ----------------------------------------------------------

def test_exclude_file_round_trip_with_comments_and_blanks():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "exclude.txt")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("# comment\n\n  alice  \nbob\n   # indented comment\n")
        cfg = _resolve(["--all", "--exclude-file", p])
    assert "alice" in cfg.exclusions
    assert "bob" in cfg.exclusions
    assert not any(x.startswith("#") for x in cfg.exclusions)
    assert "" not in cfg.exclusions


def test_exclude_file_missing_exits_config():
    with pytest.raises(prov.ProvisioningError) as exc:
        _resolve(["--all", "--exclude-file", "/no/such/file.txt"])
    assert exc.value.code == prov.EXIT_CONFIG
