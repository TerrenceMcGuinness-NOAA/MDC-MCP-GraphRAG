"""Unit tests for ``src.mcp_server`` CLI + registration (R1.3, R1.7, R18.3).

These exercise the orchestration logic — module discovery, degraded-mode
startup, ``--modules`` parsing — without actually binding the network
socket or invoking a real database adapter.
"""

from __future__ import annotations

import asyncio
import types
from unittest.mock import patch

import pytest

from src import mcp_server
from src.config import KNOWN_MODULES, ConfigError, load_config


# ── CLI parsing ────────────────────────────────────────────────────────────


def test_parse_modules_flag_none_returns_none():
    assert mcp_server._parse_modules_flag(None) is None


def test_parse_modules_flag_parses_comma_separated():
    result = mcp_server._parse_modules_flag("semantic_search,code_analysis")
    assert result == ("semantic_search", "code_analysis")


def test_parse_modules_flag_strips_whitespace():
    result = mcp_server._parse_modules_flag(" semantic_search , utility ")
    assert result == ("semantic_search", "utility")


def test_parse_modules_flag_rejects_unknown():
    with pytest.raises(ConfigError, match="Unknown module"):
        mcp_server._parse_modules_flag("nonsense")


def test_parse_args_accepts_modules_and_log_level():
    args = mcp_server._parse_args(
        ["--modules", "semantic_search,utility", "--log-level", "DEBUG"]
    )
    assert args.modules == "semantic_search,utility"
    assert args.log_level == "DEBUG"


def test_parse_args_defaults():
    args = mcp_server._parse_args([])
    assert args.modules is None
    assert args.log_level == "INFO"


# ── module enumeration ────────────────────────────────────────────────────


def test_modules_to_register_defaults_to_known():
    cfg = load_config(env={})
    assert mcp_server._modules_to_register(cfg) == KNOWN_MODULES


def test_modules_to_register_honors_whitelist():
    cfg = load_config(env={"MCP_ENABLED_MODULES": "semantic_search,utility"})
    assert mcp_server._modules_to_register(cfg) == ("semantic_search", "utility")


# ── registration with a stubbed module ────────────────────────────────────


def _make_fake_module(name: str, register_fn) -> types.ModuleType:
    mod = types.ModuleType(f"src.tools.{name}")
    mod.register = register_fn
    return mod


def test_register_module_invokes_register_function():
    """A well-formed module has ``register(mcp, data)`` called exactly once."""
    calls: list[tuple] = []

    def register(mcp, data):
        calls.append((mcp, data))

    fake = _make_fake_module("fake_module", register)
    mcp = mcp_server.build_server()

    with patch.object(mcp_server, "_import_tool_module", return_value=fake):
        result = mcp_server._register_module(mcp, "fake_module", data="DATA")

    assert result.registered is True
    assert result.error is None
    assert calls == [(mcp, "DATA")]


def test_register_module_missing_module_returns_failure():
    """Missing tool modules are expected during the module-by-module port."""
    mcp = mcp_server.build_server()

    def _raise(_name):
        raise ModuleNotFoundError("No module named 'src.tools.ghost'")

    with patch.object(mcp_server, "_import_tool_module", side_effect=_raise):
        result = mcp_server._register_module(mcp, "ghost", data=None)

    assert result.registered is False
    assert "ghost" in result.error


def test_register_module_missing_register_fn():
    """A module without ``register()`` is skipped but doesn't crash."""
    mod = types.ModuleType("src.tools.broken")
    mcp = mcp_server.build_server()

    with patch.object(mcp_server, "_import_tool_module", return_value=mod):
        result = mcp_server._register_module(mcp, "broken", data=None)

    assert result.registered is False
    assert "register" in result.error


def test_register_module_register_fn_raises():
    """An exception inside ``register()`` is captured, not propagated."""

    def boom(mcp, data):
        raise RuntimeError("kaboom")

    fake = _make_fake_module("exploding", boom)
    mcp = mcp_server.build_server()

    with patch.object(mcp_server, "_import_tool_module", return_value=fake):
        result = mcp_server._register_module(mcp, "exploding", data=None)

    assert result.registered is False
    assert "kaboom" in result.error


# ── initialize() end-to-end ──────────────────────────────────────────────


def test_initialize_degraded_mode_when_data_access_missing():
    """Without a backend_selector module, initialize() runs in degraded mode.

    As of Phase B10b the ``utility``, ``semantic_search``,
    ``code_analysis``, ``graph_rag``, ``ee2_compliance``,
    ``operational``, ``sdd_workflow``, and ``workflow_info`` tool
    modules are all ported and register successfully even without a
    data-access layer — that is the point of the graceful-degrade
    contract (Requirement 1.7). Only ``github_tools`` remains
    unported.
    """
    cfg = load_config(
        env={
            "MCP_ENABLED_MODULES": (
                "semantic_search,utility,code_analysis,graph_rag,"
                "ee2_compliance,operational,sdd_workflow,workflow_info,"
                "github_tools"
            )
        },
    )
    mcp = mcp_server.build_server()

    async def _no_data(_cfg):
        return None

    with patch.object(mcp_server, "_create_data_access", side_effect=_no_data):
        data, results = asyncio.run(mcp_server.initialize(mcp, cfg))

    assert data is None
    names = [r.name for r in results]
    assert names == [
        "semantic_search",
        "utility",
        "code_analysis",
        "graph_rag",
        "ee2_compliance",
        "operational",
        "sdd_workflow",
        "workflow_info",
        "github_tools",
    ]
    by_name = {r.name: r for r in results}
    # github_tools is the only remaining unported module.
    assert by_name["github_tools"].registered is False
    assert "No module named" in (by_name["github_tools"].error or "")
    # All other 8 modules register successfully in degraded mode.
    for module_name in (
        "utility",
        "semantic_search",
        "code_analysis",
        "graph_rag",
        "ee2_compliance",
        "operational",
        "sdd_workflow",
        "workflow_info",
    ):
        assert by_name[module_name].registered is True, (
            f"{module_name} should register successfully in degraded mode"
        )
        assert by_name[module_name].error is None


def test_initialize_registers_modules_when_data_access_available():
    """With data access + a fake module import, register() is invoked."""
    cfg = load_config(env={"MCP_ENABLED_MODULES": "utility"})
    mcp = mcp_server.build_server()

    observed: list = []

    def register(_mcp, data):
        observed.append(data)

    fake = _make_fake_module("utility", register)

    async def _with_data(_cfg):
        return {"hello": "world"}

    with (
        patch.object(mcp_server, "_create_data_access", side_effect=_with_data),
        patch.object(mcp_server, "_import_tool_module", return_value=fake),
    ):
        data, results = asyncio.run(mcp_server.initialize(mcp, cfg))

    assert data == {"hello": "world"}
    assert len(results) == 1
    assert results[0].registered is True
    assert observed == [{"hello": "world"}]


# ── server factory ────────────────────────────────────────────────────────


def test_build_server_returns_fastmcp_instance():
    from fastmcp import FastMCP

    mcp = mcp_server.build_server()
    assert isinstance(mcp, FastMCP)
    assert mcp.name == mcp_server.SERVER_NAME
