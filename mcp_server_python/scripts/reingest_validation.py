#!/usr/bin/env python3
"""reingest_validation.py — Codified Validation_Probe for the Phase 81 re-ingest.

Runs the four MCP tool calls from Requirement 5.1 against the local COTS
gateway at ``http://localhost:18888/mcp`` and writes the full request/response
payload to ``.reingest_state/<target_version>/validation/<tenant>.json``.

Transport: raw JSON-RPC 2.0 over HTTP via ``httpx``. Does NOT import the MCP
Python SDK — keeps the dependency footprint minimal (the only non-stdlib dep
is ``httpx``, already in the container).

Usage
-----
Per-tenant probe (tenant-scope + shared-once collections via that tenant):

.. code-block:: bash

    python3 mcp_server_python/scripts/reingest_validation.py \\
        --target-version v9-0-0 --tenant gw

Global (shared-once) probe (no tenant — validates shared collections):

.. code-block:: bash

    python3 mcp_server_python/scripts/reingest_validation.py \\
        --target-version v9-0-0 --global

Exit codes:
  0 — all probes returned non-zero, non-empty hit sets.
  1 — one or more probes returned zero hits or an error.
  2 — configuration error (missing secrets file, bad endpoint, etc.).

Spec: .kiro/specs/mpnet768-tenant-reingest-aug2026/ (Task 4).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default MCP gateway endpoint on the COTS host.
DEFAULT_MCP_ENDPOINT = "http://localhost:18888/mcp"

# Default secrets file location.
DEFAULT_SECRETS_FILE = os.path.expanduser("~/.config/eib-mcp/secrets.env")

# Default bearer token (used if not overridden by secrets file).
DEFAULT_BEARER_TOKEN = "eib-mcp-gateway-token-2025"

# Ground-truth phrases per tenant for the Requirement 5.1 probe.
# This is a documented iteration point — the phrases may be refined
# between runs without changing the script's logic.
TENANT_GROUND_TRUTH: dict[str, dict[str, str]] = {
    "gw": {
        "search_documentation_phrase": "wave initialization step",
        "get_code_context_symbol": "GFS_wave_init",
    },
    "gw_sfs": {
        "search_documentation_phrase": "SFS ensemble driver",
        "get_code_context_symbol": "sfs_driver",
    },
    "gw_jedi_gfs": {
        "search_documentation_phrase": "JEDI atmosphere increment",
        "get_code_context_symbol": "jedi_atmos_incr",
    },
    "gw_v17": {
        "search_documentation_phrase": "v17 gfs_forecast",
        "get_code_context_symbol": "gfs_forecast_v17",
    },
    "gw_gefs_v12": {
        "search_documentation_phrase": "GEFS ensemble forecast",
        "get_code_context_symbol": "gefs_forecast_v12",
    },
}

# Shared-once probes (constant across all tenants).
SHARED_PROBES = {
    "search_ee2_standards": {
        "query": "err_chk err_exit",
    },
    "search_architecture": {
        "query": "workflow driver",
    },
}

# ---------------------------------------------------------------------------
# Secrets loading
# ---------------------------------------------------------------------------


def _load_bearer_token(secrets_file: str | None = None) -> str:
    """Load bearer token from secrets env file or return the default.

    Parameters
    ----------
    secrets_file : str | None
        Path to the secrets .env file. If None, uses DEFAULT_SECRETS_FILE.

    Returns
    -------
    str
        The bearer token string.
    """
    path = secrets_file or DEFAULT_SECRETS_FILE
    token = os.environ.get("MCP_BEARER_TOKEN")
    if token:
        return token

    if os.path.isfile(path):
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or not line:
                    continue
                # Handle both `export KEY=VALUE` and `KEY=VALUE`
                if line.startswith("export "):
                    line = line[len("export "):]
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("'\"")
                if key == "MCP_BEARER_TOKEN":
                    return value

    return DEFAULT_BEARER_TOKEN


# ---------------------------------------------------------------------------
# MCP JSON-RPC transport
# ---------------------------------------------------------------------------


def _mcp_call(
    client: httpx.Client,
    endpoint: str,
    token: str,
    tool_name: str,
    arguments: dict[str, Any],
    request_id: int = 1,
) -> dict[str, Any]:
    """Execute a single MCP tool call via JSON-RPC 2.0 over HTTP.

    Parameters
    ----------
    client : httpx.Client
        Reusable HTTP client.
    endpoint : str
        The MCP gateway URL.
    token : str
        Bearer token for authentication.
    tool_name : str
        The MCP tool name (e.g. ``search_documentation``).
    arguments : dict
        The tool arguments as a dict.
    request_id : int
        JSON-RPC request id.

    Returns
    -------
    dict
        The full JSON-RPC response as a dict.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments,
        },
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    response = client.post(endpoint, json=payload, headers=headers, timeout=120.0)
    response.raise_for_status()
    return response.json()


def _extract_hit_count(response: dict[str, Any]) -> int:
    """Extract a hit count from an MCP tool response.

    Heuristic: looks for the ``result`` field, iterates its ``content``
    blocks, and counts non-empty text responses. Returns 0 if the
    response is an error or contains only empty/placeholder text.

    Parameters
    ----------
    response : dict
        The JSON-RPC response dict.

    Returns
    -------
    int
        Estimated hit count (>0 means success).
    """
    result = response.get("result")
    if result is None:
        # Check for JSON-RPC error
        error = response.get("error")
        if error:
            return 0
        return 0

    content = result.get("content", [])
    if not content:
        return 0

    hit_count = 0
    for block in content:
        text = block.get("text", "")
        if not text:
            continue
        # Common zero-hit patterns in MCP tool output
        if any(marker in text for marker in [
            "[INFO] No results",
            "[INFO] Skip_Block",
            "No matching",
            "0 results",
            "No documents found",
        ]):
            continue
        # Non-empty, non-zero-hit text counts as a hit
        if len(text.strip()) > 20:
            hit_count += 1

    return hit_count


# ---------------------------------------------------------------------------
# Probe execution
# ---------------------------------------------------------------------------


def _run_tenant_probes(
    client: httpx.Client,
    endpoint: str,
    token: str,
    tenant_id: str,
) -> list[dict[str, Any]]:
    """Run the four Requirement 5.1 probes for a single tenant.

    Parameters
    ----------
    client : httpx.Client
    endpoint : str
    token : str
    tenant_id : str

    Returns
    -------
    list[dict]
        List of probe records (each contains tool_name, arguments,
        response, hit_count, passed).
    """
    ground_truth = TENANT_GROUND_TRUTH.get(tenant_id)
    if ground_truth is None:
        return [{
            "tool_name": "__error__",
            "arguments": {"tenant_id": tenant_id},
            "response": {"error": f"No ground truth defined for tenant {tenant_id}"},
            "hit_count": 0,
            "passed": False,
        }]

    probes = []
    request_id = 1

    # Probe 1: search_documentation (tenant-scope workflow docs)
    args_1 = {
        "query": ground_truth["search_documentation_phrase"],
        "tenant_id": tenant_id,
    }
    resp_1 = _mcp_call(client, endpoint, token, "search_documentation", args_1, request_id)
    hits_1 = _extract_hit_count(resp_1)
    probes.append({
        "tool_name": "search_documentation",
        "arguments": args_1,
        "response": resp_1,
        "hit_count": hits_1,
        "passed": hits_1 > 0,
    })
    request_id += 1

    # Probe 2: search_ee2_standards (shared-once EE2, via tenant)
    args_2 = {
        "query": SHARED_PROBES["search_ee2_standards"]["query"],
        "tenant_id": tenant_id,
    }
    resp_2 = _mcp_call(client, endpoint, token, "search_ee2_standards", args_2, request_id)
    hits_2 = _extract_hit_count(resp_2)
    probes.append({
        "tool_name": "search_ee2_standards",
        "arguments": args_2,
        "response": resp_2,
        "hit_count": hits_2,
        "passed": hits_2 > 0,
    })
    request_id += 1

    # Probe 3: search_architecture (shared-once community summaries, via tenant)
    args_3 = {
        "query": SHARED_PROBES["search_architecture"]["query"],
        "tenant_id": tenant_id,
    }
    resp_3 = _mcp_call(client, endpoint, token, "search_architecture", args_3, request_id)
    hits_3 = _extract_hit_count(resp_3)
    probes.append({
        "tool_name": "search_architecture",
        "arguments": args_3,
        "response": resp_3,
        "hit_count": hits_3,
        "passed": hits_3 > 0,
    })
    request_id += 1

    # Probe 4: get_code_context (tenant-scope code + graph)
    args_4 = {
        "symbol": ground_truth["get_code_context_symbol"],
        "tenant_id": tenant_id,
    }
    resp_4 = _mcp_call(client, endpoint, token, "get_code_context", args_4, request_id)
    hits_4 = _extract_hit_count(resp_4)
    probes.append({
        "tool_name": "get_code_context",
        "arguments": args_4,
        "response": resp_4,
        "hit_count": hits_4,
        "passed": hits_4 > 0,
    })

    return probes


def _run_global_probes(
    client: httpx.Client,
    endpoint: str,
    token: str,
) -> list[dict[str, Any]]:
    """Run the two shared-once probes with no tenant override.

    Parameters
    ----------
    client : httpx.Client
    endpoint : str
    token : str

    Returns
    -------
    list[dict]
        List of probe records.
    """
    probes = []
    request_id = 1

    # Shared probe 1: search_ee2_standards (no tenant_id)
    args_1 = {"query": SHARED_PROBES["search_ee2_standards"]["query"]}
    resp_1 = _mcp_call(client, endpoint, token, "search_ee2_standards", args_1, request_id)
    hits_1 = _extract_hit_count(resp_1)
    probes.append({
        "tool_name": "search_ee2_standards",
        "arguments": args_1,
        "response": resp_1,
        "hit_count": hits_1,
        "passed": hits_1 > 0,
    })
    request_id += 1

    # Shared probe 2: search_architecture (no tenant_id)
    args_2 = {"query": SHARED_PROBES["search_architecture"]["query"]}
    resp_2 = _mcp_call(client, endpoint, token, "search_architecture", args_2, request_id)
    hits_2 = _extract_hit_count(resp_2)
    probes.append({
        "tool_name": "search_architecture",
        "arguments": args_2,
        "response": resp_2,
        "hit_count": hits_2,
        "passed": hits_2 > 0,
    })

    return probes


# ---------------------------------------------------------------------------
# Result writing
# ---------------------------------------------------------------------------


def _write_result(
    target_version: str,
    filename: str,
    probes: list[dict[str, Any]],
    state_root: str | None = None,
) -> Path:
    """Write probe results atomically to the validation directory.

    Parameters
    ----------
    target_version : str
        e.g. ``v9-0-0``.
    filename : str
        e.g. ``gw.json`` or ``_shared_once.json``.
    probes : list[dict]
        The probe records to persist.
    state_root : str | None
        Override for the ``.reingest_state`` root (for testing).

    Returns
    -------
    Path
        The path of the written file.
    """
    if state_root is None:
        state_root = str(Path.cwd())

    validation_dir = Path(state_root) / ".reingest_state" / target_version / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    out_path = validation_dir / filename

    payload = {
        "target_version": target_version,
        "filename": filename,
        "probes": probes,
        "all_passed": all(p["passed"] for p in probes),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    # Atomic write
    fd, tmp_path = tempfile.mkstemp(
        dir=str(validation_dir), suffix=".tmp", prefix=".val_"
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2, default=str)
            f.write("\n")
        os.replace(tmp_path, str(out_path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="reingest_validation",
        description=(
            "Run the Phase 81 Validation_Probe suite against the local "
            "COTS MCP gateway and write results to the state directory."
        ),
    )
    parser.add_argument(
        "--target-version",
        required=True,
        help="Target collection version (e.g. v9-0-0).",
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--tenant",
        help="Run the four per-tenant probes for this tenant_id.",
    )
    group.add_argument(
        "--global",
        dest="global_mode",
        action="store_true",
        default=False,
        help="Run the two shared-once probes (no tenant override).",
    )

    parser.add_argument(
        "--endpoint",
        default=None,
        help=(
            "Override MCP gateway endpoint "
            f"(default: {DEFAULT_MCP_ENDPOINT})."
        ),
    )
    parser.add_argument(
        "--secrets-file",
        default=None,
        help=(
            "Override secrets .env file path "
            f"(default: {DEFAULT_SECRETS_FILE})."
        ),
    )
    parser.add_argument(
        "--state-root",
        default=None,
        help=(
            "Override the state root directory "
            "(default: current working directory)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print what would be done without calling the MCP gateway.",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the validation probe CLI.

    Parameters
    ----------
    argv : list[str] | None
        CLI arguments (defaults to sys.argv[1:]).

    Returns
    -------
    int
        Exit code (0=pass, 1=fail, 2=config error).
    """
    args = _parse_args(argv)

    endpoint = args.endpoint or os.environ.get("MCP_ENDPOINT", DEFAULT_MCP_ENDPOINT)
    token = _load_bearer_token(args.secrets_file)
    target_version = args.target_version
    state_root = args.state_root

    # Determine mode and validate
    if args.global_mode:
        mode = "global"
        filename = "_shared_once.json"
        label = "shared-once (global)"
    else:
        mode = "tenant"
        tenant_id = args.tenant
        if tenant_id not in TENANT_GROUND_TRUTH:
            print(
                f"[ERROR] Unknown tenant_id '{tenant_id}'. "
                f"Known: {sorted(TENANT_GROUND_TRUTH.keys())}",
                file=sys.stderr,
            )
            return 2
        filename = f"{tenant_id}.json"
        label = f"tenant={tenant_id}"

    # Dry-run: just print what would be done
    if args.dry_run:
        print(f"[DRY-RUN] Mode: {mode} ({label})")
        print(f"[DRY-RUN] Endpoint: {endpoint}")
        print(f"[DRY-RUN] Target version: {target_version}")
        print(f"[DRY-RUN] Output: .reingest_state/{target_version}/validation/{filename}")
        if mode == "tenant":
            gt = TENANT_GROUND_TRUTH[args.tenant]
            print(f"[DRY-RUN] Probes:")
            print(f"  1. search_documentation(query={gt['search_documentation_phrase']!r}, tenant_id={args.tenant!r})")
            print(f"  2. search_ee2_standards(query='err_chk err_exit', tenant_id={args.tenant!r})")
            print(f"  3. search_architecture(query='workflow driver', tenant_id={args.tenant!r})")
            print(f"  4. get_code_context(symbol={gt['get_code_context_symbol']!r}, tenant_id={args.tenant!r})")
        else:
            print(f"[DRY-RUN] Probes:")
            print(f"  1. search_ee2_standards(query='err_chk err_exit')")
            print(f"  2. search_architecture(query='workflow driver')")
        return 0

    # Execute probes
    print(f"[INFO] Running validation probes: {label}")
    print(f"[INFO] Endpoint: {endpoint}")
    print(f"[INFO] Target version: {target_version}")

    try:
        with httpx.Client() as client:
            start_time = time.perf_counter()

            if mode == "global":
                probes = _run_global_probes(client, endpoint, token)
            else:
                probes = _run_tenant_probes(client, endpoint, token, args.tenant)

            elapsed = time.perf_counter() - start_time
    except httpx.ConnectError as exc:
        print(
            f"[ERROR] Cannot connect to MCP gateway at {endpoint}: {exc}",
            file=sys.stderr,
        )
        return 2
    except httpx.HTTPStatusError as exc:
        print(
            f"[ERROR] MCP gateway returned HTTP {exc.response.status_code}: "
            f"{exc.response.text[:200]}",
            file=sys.stderr,
        )
        return 2

    # Write results
    out_path = _write_result(target_version, filename, probes, state_root)
    print(f"[INFO] Results written to {out_path}")

    # Report
    total = len(probes)
    passed = sum(1 for p in probes if p["passed"])
    failed = total - passed

    for p in probes:
        status = "[PASS]" if p["passed"] else "[FAIL]"
        print(
            f"  {status} {p['tool_name']}"
            f"({', '.join(f'{k}={v!r}' for k, v in p['arguments'].items())})"
            f" -> {p['hit_count']} hits"
        )

    print(f"[INFO] {passed}/{total} probes passed ({elapsed:.1f}s)")

    if failed > 0:
        print(f"[FAIL] {failed} probe(s) returned zero hits.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
