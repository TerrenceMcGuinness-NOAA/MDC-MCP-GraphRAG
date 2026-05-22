#!/usr/bin/env python3.12
"""Standalone smoke-test CLI for the MDC MCP/RAG Python server.

Runs the same per-tool-module smoke queries as
``mcp_health_check(functional=True)`` but without starting the full
MCP server — initialises only the data-access layer, fires the
queries, and emits structured JSON.

Usage
-----
.. code-block:: bash

    DB_BACKEND=aws \\
      OPENSEARCH_ENDPOINT=https://vpc-mdc-mcp-rag-search-...es.amazonaws.com \\
      NEPTUNE_ENDPOINT=https://mdc-mcp-graprag-neptune-1...:8182 \\
      AWS_REGION=us-east-1 \\
      MCP_WORKFLOW_ROOT=/mdc-mcp-rag/eib-mcp-rag-server/supported_repos/global-workflow \\
      python3.12 mcp_server_python/scripts/smoke_test_tools.py

Flags
-----
``--json-only``
    Suppress the human-readable markdown table on stderr; emit only
    the JSON object on stdout.

``--module <name>``
    Run only the named module's smoke query (one of:
    ``semantic_search``, ``code_analysis``, ``graph_rag``,
    ``ee2_compliance``, ``operational``, ``sdd_workflow``,
    ``workflow_info``, ``github_tools``, ``utility``).

Exit codes
----------
* ``0`` — every non-skipped module passed.
* ``1`` — at least one module failed.
* ``2`` — required environment variables are missing in ``aws``
  mode, or the data-access layer failed to initialise.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Make ``src.*`` importable when this script is run directly.
_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent  # mcp_server_python/
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ── argparse ─────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse ``--json-only`` and ``--module`` flags."""
    parser = argparse.ArgumentParser(
        prog="smoke_test_tools",
        description=(
            "Run functional smoke queries for all 9 MDC MCP/RAG tool "
            "modules against the configured AWS backends. Emits a "
            "JSON result on stdout and (unless --json-only) a "
            "markdown summary on stderr."
        ),
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Emit only the JSON result; suppress the markdown table.",
    )
    parser.add_argument(
        "--module",
        default=None,
        help=(
            "Run only the named module's smoke query "
            "(default: run all 9)."
        ),
    )
    return parser.parse_args(argv)


# ── env-var validation (R5.4) ────────────────────────────────────────


_AWS_REQUIRED_VARS: tuple[str, ...] = (
    "OPENSEARCH_ENDPOINT",
    "NEPTUNE_ENDPOINT",
)


def _validate_env() -> list[str]:
    """Return a list of missing required env vars (R5.4).

    ``DB_BACKEND`` defaults to ``aws`` (matching ``load_config``); in
    that mode both ``OPENSEARCH_ENDPOINT`` and ``NEPTUNE_ENDPOINT``
    must be set. ``AWS_REGION`` defaults to ``us-east-1`` and is not
    treated as a hard requirement.
    """
    backend = (os.environ.get("DB_BACKEND") or "aws").strip().lower()
    if backend != "aws":
        return []
    return [v for v in _AWS_REQUIRED_VARS if not os.environ.get(v)]


# ── data-layer bootstrap ─────────────────────────────────────────────


async def _bootstrap_data() -> Any:
    """Initialise :pyclass:`UnifiedDataAccess` from the environment.

    Late-imports the heavy modules (``boto3``, ``opensearch-py``, etc.)
    so ``--help`` and env-var validation stay fast.
    """
    # Late imports keep startup snappy when we only need ``--help``.
    from src.config.environment import load_config
    from src.data.backend_selector import create_data_access

    config = load_config()
    return await create_data_access(config)


# ── orchestration ────────────────────────────────────────────────────


async def _run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    """Run the smoke suite and return ``(json_payload, exit_code)``.

    Splitting orchestration from CLI plumbing makes the function
    testable in isolation and keeps :func:`main` purely for I/O.
    """
    from src.tools.smoke_queries import SmokeQueryRegistry

    started_perf = time.perf_counter()
    started_iso = datetime.now(timezone.utc).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")

    try:
        data = await _bootstrap_data()
    except Exception as exc:
        return (
            {
                "timestamp": started_iso,
                "total_duration_ms": int(
                    (time.perf_counter() - started_perf) * 1000
                ),
                "summary": {
                    "passed": 0,
                    "failed": 0,
                    "skipped": 0,
                    "total": 0,
                },
                "results": [],
                "error": (
                    f"data-access initialisation failed: "
                    f"{type(exc).__name__}: {exc}"
                ),
            },
            2,
        )

    registry = SmokeQueryRegistry()

    try:
        if args.module is not None:
            try:
                result = await registry.run_one(args.module, data)
            except KeyError as exc:
                return (
                    {
                        "timestamp": started_iso,
                        "total_duration_ms": int(
                            (time.perf_counter() - started_perf) * 1000
                        ),
                        "summary": {
                            "passed": 0,
                            "failed": 0,
                            "skipped": 0,
                            "total": 0,
                        },
                        "results": [],
                        "error": str(exc).strip("'\""),
                    },
                    2,
                )
            results = [result]
        else:
            results = await registry.run_all(data)
    finally:
        # Best-effort close so the script doesn't leak sockets.
        close = getattr(data, "close", None)
        if callable(close):
            try:
                await close()
            except Exception:
                pass

    elapsed_ms = int((time.perf_counter() - started_perf) * 1000)
    passed = sum(1 for r in results if r.status == "pass")
    failed = sum(1 for r in results if r.status == "fail")
    skipped = sum(1 for r in results if r.status == "skip")
    total = len(results)

    payload = {
        "timestamp": started_iso,
        "total_duration_ms": elapsed_ms,
        "summary": {
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "total": total,
        },
        "results": [r.as_dict() for r in results],
    }

    # Exit 0 only when every non-skipped module passed.
    exit_code = 0 if failed == 0 else 1
    return payload, exit_code


# ── rendering ────────────────────────────────────────────────────────


def _render_markdown(payload: dict[str, Any]) -> str:
    """Render the JSON payload as a human-readable markdown table.

    Goes to stderr per the spec (R4.4) so stdout stays JSON-clean for
    downstream tooling.
    """
    status_marker = {"pass": "[OK]", "fail": "[ERROR]", "skip": "[SKIP]"}
    lines: list[str] = ["# MDC MCP/RAG Smoke Test", ""]
    summary = payload.get("summary", {})
    lines.append(
        f"**Run at**: {payload.get('timestamp', '?')}  "
        f"**Total duration**: {payload.get('total_duration_ms', '?')}ms"
    )
    lines.append("")
    if "error" in payload:
        lines.append(f"**Error**: {payload['error']}")
        lines.append("")
        return "\n".join(lines)

    lines.append("| Module | Status | Latency | Description | Error |")
    lines.append("|--------|--------|---------|-------------|-------|")
    for r in payload.get("results", []):
        marker = status_marker.get(r.get("status", "?"), "[?]")
        err = (r.get("error") or "").replace("|", "/")
        if len(err) > 140:
            err = err[:137] + "..."
        desc = (r.get("description") or "").replace("|", "/")
        if len(desc) > 80:
            desc = desc[:77] + "..."
        lines.append(
            f"| {r.get('module', '?')} | {marker} {r.get('status', '?')} "
            f"| {r.get('latency_ms', '?')}ms | {desc} | {err} |"
        )
    lines.append("")
    lines.append(
        f"**Summary**: {summary.get('passed', 0)}/{summary.get('total', 0)} "
        f"passed, {summary.get('failed', 0)} failed, "
        f"{summary.get('skipped', 0)} skipped"
    )
    lines.append("")
    return "\n".join(lines)


# ── entrypoint ───────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint. Returns a POSIX exit code."""
    args = _parse_args(argv)

    missing = _validate_env()
    if missing:
        sys.stderr.write(
            "[ERROR] missing required environment variables for "
            f"DB_BACKEND=aws: {', '.join(missing)}\n"
            "Set them before invoking this script. Example:\n"
            "  export DB_BACKEND=aws\n"
            "  export OPENSEARCH_ENDPOINT=https://vpc-...es.amazonaws.com\n"
            "  export NEPTUNE_ENDPOINT=https://mdc-...neptune.amazonaws.com:8182\n"
            "  export AWS_REGION=us-east-1\n"
        )
        return 2

    try:
        payload, exit_code = asyncio.run(_run(args))
    except KeyboardInterrupt:
        sys.stderr.write("[WARN] interrupted by user\n")
        return 130

    # JSON to stdout (always).
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    sys.stdout.flush()

    # Markdown to stderr unless --json-only.
    if not args.json_only:
        sys.stderr.write(_render_markdown(payload))
        sys.stderr.flush()

    return exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
