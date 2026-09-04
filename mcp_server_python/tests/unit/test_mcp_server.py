"""Unit tests for ``src.mcp_server`` CLI + registration (R1.3, R1.7, R18.3).

These exercise the orchestration logic — module discovery, degraded-mode
startup, ``--modules`` parsing — without actually binding the network
socket or invoking a real database adapter.
"""

from __future__ import annotations

import asyncio
import os
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


def test_register_module_catches_session_manager_permission_error():
    """Regression test for Phase C-1 Issue B (Dockerfile chown bug).

    On the AgentCore staging deploy of ``python-all-tools-v1``, the
    container's ``WORKDIR /app`` was root-owned while the runtime
    process ran as user ``app``. ``SessionManager._ensure_state_dir()``
    tried to create ``/app/sdd_framework/execution_state/`` and got
    ``PermissionError``, which propagated out of the
    ``register()`` calls in ``graph_rag`` and ``sdd_workflow`` (both
    default-construct a ``SessionManager()`` with no explicit
    ``state_dir``). The result was 7 of 9 modules registered (33 of
    51 tools) instead of 51/51.

    The hot-fix is in ``mcp_server_python/Dockerfile`` (``chown -R
    app:app /app`` after ``useradd``). This regression test
    documents the failure mode and asserts that
    ``_register_module`` catches the ``PermissionError`` and reports
    it as a clean ``ModuleLoadResult(registered=False, ...)`` rather
    than letting the whole server bootstrap crash.

    The test simulates the production failure mode by monkey-patching
    ``Path.mkdir`` to raise ``PermissionError`` for any path under
    ``sdd_framework/`` — exactly the path SessionManager targets by
    default. The unit-test suite at commit ``e325e61`` (Phase B11
    baseline) missed this issue because every test injects
    ``SessionManager(state_dir=tmp_path)``; the default-state-dir
    path was uncovered.

    See ``docs/reports/2026-05-14-phase-c1-parity-assessment.md``
    Issue B for full root-cause analysis.
    """
    import pathlib

    real_mkdir = pathlib.Path.mkdir

    def selectively_blocked_mkdir(self, *args, **kwargs):
        # Only fail on the SessionManager default state path —
        # other mkdir calls in the test stack (tmp_path setup, etc.)
        # must continue to work normally.
        if "sdd_framework" in self.as_posix():
            raise PermissionError(
                f"[Errno 13] Permission denied: '{self.as_posix()}'"
            )
        return real_mkdir(self, *args, **kwargs)

    mcp = mcp_server.build_server()

    # graph_rag and sdd_workflow are the two modules that
    # default-construct ``SessionManager()`` during register().
    # If the chown is missing, both fail; if the chown is in place,
    # both register successfully (covered by
    # ``test_initialize_degraded_mode_when_data_access_missing``).
    # Here we explicitly inject the failure to verify the catch path.
    failures: list[str] = []
    with patch.object(
        pathlib.Path, "mkdir", selectively_blocked_mkdir
    ):
        for module_name in ("graph_rag", "sdd_workflow"):
            result = mcp_server._register_module(
                mcp, module_name, data=None
            )
            if result.registered:
                failures.append(
                    f"{module_name} registered=True despite injected "
                    f"PermissionError — _register_module did not catch it"
                )
            elif "Permission denied" not in (result.error or ""):
                failures.append(
                    f"{module_name} error did not surface the "
                    f"PermissionError text; got: {result.error!r}"
                )

    assert not failures, "; ".join(failures)


# ── initialize() end-to-end ──────────────────────────────────────────────


def test_initialize_degraded_mode_when_data_access_missing():
    """When ``_create_data_access`` returns None, initialize() runs in
    degraded mode.

    Phase C-2b shipped the previously-missing ``src.data.backend_selector``
    module, so the import-time fallback that was the original degraded
    path is no longer reachable. This test forces the same outcome by
    patching ``_create_data_access`` to return None directly — it
    documents the contract that any failure inside the data-access
    layer (missing backend_selector, unreachable backends, network
    errors during ``connect``) must NOT prevent tool-module registration.

    As of Phase B11 ALL 9 tool modules are ported. Every module
    registers successfully even without a data-access layer — that
    is the point of the graceful-degrade contract (Requirement 1.7).
    Per-module degraded-mode behaviour:

    * ``utility`` / ``sdd_workflow`` / ``workflow_info`` — fully
      data-access-free; work with no Neptune/OpenSearch reachable.
    * ``semantic_search`` / ``code_analysis`` / ``graph_rag`` /
      ``ee2_compliance`` / ``operational`` — register successfully
      without the data layer and return ``[ERROR]`` markdown at
      call time when the layer is missing.
    * ``github_tools`` — also data-access-free; needs ``GITHUB_TOKEN``
      at call time. Registration always succeeds; tool calls return
      "GitHub integration not available - no API access" when the
      token is unset.

    There are no longer any "still-unported" modules — Phase B is
    complete and the Python port has 51/51 tool parity with the
    Node.js server.
    """
    # Use the canonical KNOWN_MODULES tuple to ensure every registered
    # module is exercised; if a future port adds a module, this test
    # picks it up automatically.
    cfg = load_config(env={"MCP_ENABLED_MODULES": ",".join(KNOWN_MODULES)})
    mcp = mcp_server.build_server()

    async def _no_data(_cfg):
        return None

    with patch.object(mcp_server, "_create_data_access", side_effect=_no_data):
        data, results = asyncio.run(mcp_server.initialize(mcp, cfg))

    assert data is None
    names = [r.name for r in results]
    # All 9 modules in KNOWN_MODULES order.
    assert names == list(KNOWN_MODULES)
    by_name = {r.name: r for r in results}
    # Every module registers successfully in degraded mode.
    for module_name in KNOWN_MODULES:
        assert by_name[module_name].registered is True, (
            f"{module_name} should register successfully in degraded "
            f"mode (Phase B11 contract)"
        )
        assert by_name[module_name].error is None, (
            f"{module_name} surfaced unexpected error: "
            f"{by_name[module_name].error}"
        )


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


# ── stdio transport path ─────────────────────────────────────────────────


def test_stdio_transport_does_not_pass_json_response():
    """The stdio local-dev path must not forward ``json_response`` (R3.5).

    ``json_response`` is a Gateway-interceptor concern for the Streamable
    HTTP transport (R3.1 / AD-C4). The stdio path is used for native
    local development where the MCP client spawns this process directly;
    it has no Gateway in the loop and ``FastMCP.run(transport="stdio")``
    does not accept ``json_response``.

    This test captures the kwargs passed to ``FastMCP.run()`` when
    ``--transport stdio`` is selected and asserts that ``json_response``
    is absent — confirming R3.5 ("the stdio transport path SHALL be
    unaffected by criteria 1–4").
    """
    captured_kwargs: dict = {}

    def fake_run(**kwargs):
        captured_kwargs.update(kwargs)

    cfg = load_config(env={"MCP_ENABLED_MODULES": "utility"})

    with (
        patch.object(mcp_server, "load_config", return_value=cfg),
        patch.object(mcp_server, "build_server") as mock_build,
        patch.object(mcp_server, "initialize", return_value=(None, [])),
        patch("asyncio.run"),
    ):
        mock_mcp = mock_build.return_value
        mock_mcp.run = fake_run

        exit_code = mcp_server.main(["--transport", "stdio"])

    assert exit_code == 0
    assert captured_kwargs.get("transport") == "stdio"
    assert "json_response" not in captured_kwargs, (
        "stdio transport must not pass json_response to FastMCP.run() — "
        "it is a Streamable HTTP / Gateway concern only (R3.5)"
    )
    # Also confirm show_banner is disabled (suppresses ASCII banner on stdio).
    assert captured_kwargs.get("show_banner") is False


# ── json_response env-var resolution (R3.1, R3.2) ────────────────────────


@pytest.mark.parametrize(
    "env_value, expected_json_response",
    [
        pytest.param(None, True, id="default-no-env-var"),
        pytest.param("true", True, id="MCP_JSON_RESPONSE=true"),
        pytest.param("false", False, id="MCP_JSON_RESPONSE=false"),
        pytest.param("0", False, id="MCP_JSON_RESPONSE=0"),
        pytest.param("no", False, id="MCP_JSON_RESPONSE=no"),
        pytest.param("off", False, id="MCP_JSON_RESPONSE=off"),
    ],
)
def test_json_response_follows_env_var_and_defaults_true(
    env_value, expected_json_response
):
    """The resolved ``json_response`` kwarg passed to ``mcp.run()`` SHALL
    default to ``True`` (R3.1) and SHALL be overridable via the
    ``MCP_JSON_RESPONSE`` env var (R3.2), mirroring the existing
    ``MCP_STATELESS_HTTP`` pattern.

    Validates: Requirements R3.1, R3.2.
    """
    captured_kwargs: dict = {}

    def fake_run(**kwargs):
        captured_kwargs.update(kwargs)

    cfg = load_config(env={"MCP_ENABLED_MODULES": "utility"})

    # Build the env dict: remove MCP_JSON_RESPONSE if testing the absent case,
    # otherwise set it to the parametrized value.  Also ensure the transport
    # resolves to streamable-http (the default) and not stdio.
    env_patch: dict[str, str] = {}
    if env_value is not None:
        env_patch["MCP_JSON_RESPONSE"] = env_value

    with (
        patch.dict(os.environ, env_patch, clear=False),
        patch.dict(os.environ, {}, clear=False),
        patch.object(mcp_server, "load_config", return_value=cfg),
        patch.object(mcp_server, "build_server") as mock_build,
        patch.object(mcp_server, "initialize", return_value=(None, [])),
        patch("asyncio.run"),
    ):
        # Ensure MCP_JSON_RESPONSE is absent when testing the default case.
        os.environ.pop("MCP_JSON_RESPONSE", None)
        os.environ.pop("MCP_TRANSPORT", None)
        if env_value is not None:
            os.environ["MCP_JSON_RESPONSE"] = env_value

        mock_mcp = mock_build.return_value
        mock_mcp.run = fake_run

        exit_code = mcp_server.main([])

    assert exit_code == 0
    assert captured_kwargs.get("transport") == "streamable-http", (
        "expected streamable-http transport for this test"
    )
    assert captured_kwargs.get("json_response") is expected_json_response, (
        f"MCP_JSON_RESPONSE={env_value!r} should resolve json_response to "
        f"{expected_json_response}, got {captured_kwargs.get('json_response')!r}"
    )
