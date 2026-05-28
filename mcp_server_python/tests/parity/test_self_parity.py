"""Self-parity tests for omd-tenants-1-foundation Phase C.

Validates that the multi-tenant runtime (v21, python-tenants-v1) produces
deterministic, consistent output for the gw tenant:

1. tenant_id=gw explicit == no tenant_id (resolution determinism)
2. Output is stable across repeated calls (no non-determinism)
3. The *Tenant: gw* header is the ONLY observable difference from
   pre-tenancy output (empty prefixes = identity on all adapters)
4. Golden baseline comparison for regression testing

Gate: MCP_TEST_AGAINST_LIVE=1 environment variable must be set.
These tests call the live AgentCore runtime via the agentcore-mcp-rag
MCP proxy (same path Kiro uses).

Run: MCP_TEST_AGAINST_LIVE=1 pytest tests/parity/test_self_parity.py -v
Capture golden: MCP_TEST_AGAINST_LIVE=1 python -m tests.parity.test_self_parity
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests.parity.parity_runner import strip_tenant_header

# Skip entire module unless live testing is enabled
pytestmark = pytest.mark.skipif(
    os.environ.get("MCP_TEST_AGAINST_LIVE") != "1",
    reason="MCP_TEST_AGAINST_LIVE=1 not set — skipping live parity tests",
)

# ── Fixed query corpus ──────────────────────────────────────────────────

CORPUS = [
    {"tool": "search_documentation", "args": {"query": "FV3 dynamical core", "max_results": 3}},
    {"tool": "find_related_files", "args": {"file_path": "jobs/JGLOBAL_FORECAST"}},
    {"tool": "get_code_context", "args": {"symbol": "JGLOBAL_FORECAST"}},
    {"tool": "search_ee2_standards", "args": {"query": "error handling err_chk"}},
    {"tool": "get_operational_guidance", "args": {"operation": "forecast"}},
    {"tool": "get_workflow_structure", "args": {"component": "jobs"}},
    {"tool": "describe_component", "args": {"component": "JGLOBAL_FORECAST"}},
]


def _query_hash(tool: str, args: dict) -> str:
    """Stable short hash for a query (used in golden filenames)."""
    key = json.dumps({"tool": tool, "args": args}, sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def _golden_filename(tool: str, args: dict) -> str:
    return f"{tool}_{_query_hash(tool, args)}.txt"


# ── MCP tool caller ─────────────────────────────────────────────────────

# The proxy script translates stdio JSON-RPC into AgentCore SSE calls.
# We use a helper that invokes the tool via the kiro proxy subprocess.

_PROXY_SCRIPT = Path(__file__).parents[3] / "tools" / "agentcore-kiro-proxy.py"


def _call_mcp_tool(tool_name: str, args: dict) -> str:
    """Call an MCP tool via the agentcore proxy and return the text result.

    Uses a JSON-RPC call_tool request over the proxy's stdio interface.
    """
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": args},
    }

    result = subprocess.run(
        [sys.executable, str(_PROXY_SCRIPT)],
        input=json.dumps(request) + "\n",
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Proxy failed: {result.stderr[:500]}")

    # Parse the JSON-RPC response
    for line in result.stdout.strip().splitlines():
        try:
            resp = json.loads(line)
            if "result" in resp:
                content = resp["result"].get("content", [])
                for block in content:
                    if block.get("type") == "text":
                        return block["text"]
        except json.JSONDecodeError:
            continue

    raise RuntimeError(f"No text result from {tool_name}: {result.stdout[:500]}")


def _call_tool_text(tool_name: str, args: dict, tenant_id: str | None = None) -> str:
    """Call a tool with optional tenant_id, return raw text response."""
    call_args = dict(args)
    if tenant_id is not None:
        call_args["tenant_id"] = tenant_id
    return _call_mcp_tool(tool_name, call_args)


# ── Self-parity tests ───────────────────────────────────────────────────


class TestResolutionDeterminism:
    """Validate that explicit tenant_id=gw == implicit (no tenant_id).

    Property P4 (Resolution determinism) + P7 (Backward-compat):
    For the gw tenant with empty prefixes, the output with and without
    explicit tenant_id must be byte-equal after stripping the attribution
    header.
    """

    @pytest.mark.parametrize("query", CORPUS, ids=[q["tool"] for q in CORPUS])
    def test_explicit_vs_implicit_tenant(self, query):
        """Output with tenant_id=gw == output without tenant_id."""
        tool, args = query["tool"], query["args"]

        result_implicit = _call_tool_text(tool, args, tenant_id=None)
        result_explicit = _call_tool_text(tool, args, tenant_id="gw")

        assert result_implicit.startswith("*Tenant: gw*\n\n"), (
            f"{tool}: implicit call missing *Tenant: gw* header"
        )
        assert result_explicit.startswith("*Tenant: gw*\n\n"), (
            f"{tool}: explicit call missing *Tenant: gw* header"
        )

        body_implicit = strip_tenant_header(result_implicit)
        body_explicit = strip_tenant_header(result_explicit)

        assert body_implicit == body_explicit, (
            f"{tool}: implicit vs explicit produced different output.\n"
            f"Implicit (first 200): {body_implicit[:200]}\n"
            f"Explicit (first 200): {body_explicit[:200]}"
        )


class TestOutputStability:
    """Validate that repeated calls produce identical output."""

    @pytest.mark.parametrize("query", CORPUS, ids=[q["tool"] for q in CORPUS])
    def test_repeated_calls_stable(self, query):
        """Two consecutive calls produce identical output."""
        tool, args = query["tool"], query["args"]
        result_1 = _call_tool_text(tool, args)
        result_2 = _call_tool_text(tool, args)
        assert result_1 == result_2, (
            f"{tool}: output not stable across repeated calls."
        )


class TestAttributionHeader:
    """Validate that every tool response has the *Tenant: gw* header."""

    @pytest.mark.parametrize("query", CORPUS, ids=[q["tool"] for q in CORPUS])
    def test_attribution_present(self, query):
        """Every tool response starts with *Tenant: gw* header."""
        result = _call_tool_text(query["tool"], query["args"])
        assert result.startswith("*Tenant: gw*\n\n"), (
            f"{query['tool']}: missing attribution header. Got: {result[:80]}"
        )


# ── Golden baseline tests ───────────────────────────────────────────────

GOLDEN_DIR = Path(__file__).parent / "golden"


class TestGoldenBaseline:
    """Compare live output against captured golden baseline files.

    Marked xfail — golden files are the v21 baseline; future versions
    may legitimately change output format.
    """

    @pytest.mark.xfail(reason="Golden baseline — future versions may change format")
    @pytest.mark.parametrize("query", CORPUS, ids=[q["tool"] for q in CORPUS])
    def test_matches_golden(self, query):
        """Live output matches the captured golden baseline."""
        tool, args = query["tool"], query["args"]
        golden_file = GOLDEN_DIR / _golden_filename(tool, args)

        if not golden_file.exists():
            pytest.skip(f"Golden file not captured: {golden_file.name}")

        golden_text = golden_file.read_text()
        live_body = strip_tenant_header(_call_tool_text(tool, args))
        assert live_body == golden_text, (
            f"{tool}: output differs from golden baseline {golden_file.name}"
        )


# ── Golden capture utility ──────────────────────────────────────────────


def capture_golden_baseline():
    """Capture golden baseline files for all corpus queries.

    Run: MCP_TEST_AGAINST_LIVE=1 python -m tests.parity.test_self_parity
    """
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    manifest_entries = []

    for query in CORPUS:
        tool, args = query["tool"], query["args"]
        filename = _golden_filename(tool, args)
        print(f"  Capturing {tool} -> {filename} ...", end=" ", flush=True)

        result = _call_tool_text(tool, args)
        body = strip_tenant_header(result)
        (GOLDEN_DIR / filename).write_text(body)
        print(f"OK ({len(body)} bytes)")

        manifest_entries.append({
            "tool": tool,
            "args": args,
            "golden_file": filename,
            "size_bytes": len(body),
        })

    manifest = {
        "runtime_version": 21,
        "image": "python-tenants-v1",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "queries": manifest_entries,
    }
    (GOLDEN_DIR / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"\n  MANIFEST.json written ({len(manifest_entries)} queries)")


if __name__ == "__main__":
    if os.environ.get("MCP_TEST_AGAINST_LIVE") != "1":
        print("Set MCP_TEST_AGAINST_LIVE=1 to capture golden baseline")
        raise SystemExit(1)
    capture_golden_baseline()
