"""FastMCP entrypoint for the Python MCP server (Requirement 1.1 – 1.7, 18.3).

Registers all available tool modules, supports per-module enablement via the
``--modules`` CLI flag or ``MCP_ENABLED_MODULES`` env var, and falls back to
"degraded mode" when a database adapter or tool module is unavailable
(Requirement 1.7).

Running locally:
    python -m src.mcp_server                   # full
    python -m src.mcp_server --modules utility,workflow_info
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import logging
import os
import sys
from dataclasses import dataclass
from typing import Any

from fastmcp import FastMCP

from src.config import KNOWN_MODULES, ConfigError, ServerConfig, load_config

log = logging.getLogger("src.mcp_server")

# Server identity — surfaced in tools/list and server_info.
SERVER_NAME = "mdc-mcp-rag"
SERVER_VERSION = "1.0.0"


# ── module registration plumbing ───────────────────────────────────────────


@dataclass
class ModuleLoadResult:
    """Outcome of attempting to import + register one tool module."""

    name: str
    registered: bool
    error: str | None = None


def _import_tool_module(name: str) -> Any:
    """Import ``src.tools.<name>`` (used by ``_register_module`` and tests)."""
    return importlib.import_module(f"src.tools.{name}")


def _register_module(mcp: FastMCP, name: str, data: Any) -> ModuleLoadResult:
    """Import and register a single tool module.

    Returns a :class:`ModuleLoadResult` rather than raising so one broken
    module cannot take the whole server down (Requirement 1.7).
    """
    try:
        mod = _import_tool_module(name)
    except ModuleNotFoundError as exc:
        # Expected during the module-by-module port — tool modules come
        # online incrementally as phases B5–B11 land.
        log.warning("[WARN] tool module %r not yet ported: %s", name, exc.msg)
        return ModuleLoadResult(name, registered=False, error=str(exc))
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("[ERROR] tool module %r failed to import", name)
        return ModuleLoadResult(name, registered=False, error=str(exc))

    register = getattr(mod, "register", None)
    if not callable(register):
        log.error("[ERROR] tool module %r has no register(mcp, data) function", name)
        return ModuleLoadResult(
            name,
            registered=False,
            error="missing register(mcp, data) function",
        )

    try:
        register(mcp, data)
    except Exception as exc:
        log.exception("[ERROR] tool module %r register() failed", name)
        return ModuleLoadResult(name, registered=False, error=str(exc))

    log.info("[OK] registered tool module %r", name)
    return ModuleLoadResult(name, registered=True)


def _modules_to_register(config: ServerConfig) -> tuple[str, ...]:
    """Return the ordered list of modules to attempt registration for.

    Honors ``config.enabled_modules``; falls back to every module in
    :data:`KNOWN_MODULES` when no whitelist is set.
    """
    return config.enabled_modules or KNOWN_MODULES


# ── data-access bootstrap (degraded mode) ──────────────────────────────────


async def _create_data_access(config: ServerConfig) -> Any | None:
    """Initialize UnifiedDataAccess, returning None if the adapters fail.

    Graceful-fail is part of Requirement 1.7: when an adapter cannot be
    initialized (VPC connectivity, credential expiry, network partition…)
    the server should still come up and serve tools that do not depend
    on that adapter.
    """
    try:
        # Late import — keeps the boto3/opensearch-py chain out of the
        # ``mcp_server`` import graph so unit tests can exercise the
        # CLI / registration layer without the heavy AWS deps. The
        # module is shipped as of Phase C-2b; the ModuleNotFoundError
        # branch below is preserved for backwards compatibility with
        # older container images that have ``mcp_server.py`` but not
        # the data layer (e.g. ``python-utility-v1`` and
        # ``python-all-tools-v1`` pre-C-2b rollback targets).
        from src.data.backend_selector import create_data_access
    except ModuleNotFoundError:
        log.warning(
            "[WARN] src.data.backend_selector not available — "
            "starting in no-data-access mode (legacy image?)"
        )
        return None

    try:
        data = await create_data_access(config)
    except Exception as exc:
        log.exception(
            "[ERROR] data-access initialization failed — entering degraded mode: %s",
            exc,
        )
        return None

    log.info("[OK] data-access initialized (backend=%s)", config.db_backend)
    return data


# ── server factory ─────────────────────────────────────────────────────────


def build_server() -> FastMCP:
    """Construct an unconfigured FastMCP server.

    Kept as a separate factory so unit tests can create a fresh instance
    without triggering registration side-effects.
    """
    return FastMCP(name=SERVER_NAME, version=SERVER_VERSION)


async def initialize(
    mcp: FastMCP,
    config: ServerConfig,
) -> tuple[Any | None, list[ModuleLoadResult]]:
    """Initialize data access and register every enabled tool module.

    Returns the (possibly ``None``) data-access handle and the per-module
    load results, which the caller can use for logging or readiness
    reporting.
    """
    data = await _create_data_access(config)
    results = [
        _register_module(mcp, name, data)
        for name in _modules_to_register(config)
    ]

    total = len(results)
    ok = sum(1 for r in results if r.registered)
    log.info("[OK] registered %d/%d tool modules", ok, total)

    if data is None:
        log.warning(
            "[WARN] running in degraded mode — tools requiring Neptune or "
            "OpenSearch will return errors"
        )

    return data, results


# ── CLI ────────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse ``--modules`` and logging flags (Requirement 18.3)."""
    parser = argparse.ArgumentParser(
        prog="mdc-mcp-rag",
        description=(
            "MDC MCP/RAG Python server (FastMCP). Registers up to 9 tool "
            "modules and serves them over Streamable HTTP on port 8000."
        ),
    )
    parser.add_argument(
        "--modules",
        default=None,
        help=(
            "Comma-separated list of tool modules to enable (e.g. "
            "`--modules semantic_search,code_analysis`). Overrides the "
            "MCP_ENABLED_MODULES env var. Known modules: "
            + ", ".join(KNOWN_MODULES)
        ),
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO).",
    )
    return parser.parse_args(argv)


def _parse_modules_flag(raw: str | None) -> tuple[str, ...] | None:
    """Translate ``--modules foo,bar`` to the tuple ``load_config`` expects."""
    if raw is None:
        return None
    names = tuple(n.strip() for n in raw.split(",") if n.strip())
    unknown = [n for n in names if n not in KNOWN_MODULES]
    if unknown:
        raise ConfigError(
            f"Unknown module(s) in --modules: {unknown}. "
            f"Known: {list(KNOWN_MODULES)}"
        )
    return names


def main(argv: list[str] | None = None) -> int:
    """Console-script entrypoint. Returns a POSIX exit code."""
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    try:
        cli_modules = _parse_modules_flag(args.modules)
        config = load_config(enabled_modules=cli_modules)
    except ConfigError as exc:
        log.error("[ERROR] invalid configuration: %s", exc)
        return 2

    mcp = build_server()
    asyncio.run(initialize(mcp, config))

    log.info(
        "[OK] starting FastMCP Streamable HTTP listener on %s:%d",
        config.host,
        config.port,
    )
    # Synchronous — FastMCP.run() manages its own event loop.
    # ``stateless_http=True`` is REQUIRED for AgentCore Runtime MCP protocol
    # mode (per runtime-mcp-protocol-contract):
    #   * AgentCore generates its own ``Mcp-Session-Id`` header per request
    #     and expects the server to accept it instead of generating its own.
    #   * Stateful mode rejects the platform-provided ID with HTTP 400, which
    #     AgentCore surfaces to the client as a 500-class runtime error.
    #   * Load balancing / microVM affinity is handled by the platform, so
    #     stateless on the server side is the correct default.
    # Set ``MCP_STATELESS_HTTP=false`` to opt into stateful mode for local
    # development when you want multi-turn elicitation / sampling.
    stateless = os.environ.get("MCP_STATELESS_HTTP", "true").strip().lower() not in (
        "false", "0", "no", "off"
    )
    mcp.run(
        transport="streamable-http",
        host=config.host,
        port=config.port,
        stateless_http=stateless,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
