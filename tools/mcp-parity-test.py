#!/usr/bin/env python3
"""
MCP Tool Parity & Performance Test
====================================
Calls every shared tool on both the legacy (eib-mcp-gateway) and AgentCore
(agentcore-mcp-rag) MCP servers, measures latency, compares response quality,
and generates a markdown report.

Usage:
  python3 tools/mcp-parity-test.py [--output reports/mcp-parity-YYYY-MM-DD.md]
  python3 tools/mcp-parity-test.py --server legacy   # test only legacy
  python3 tools/mcp-parity-test.py --server agentcore # test only agentcore

Requires: requests (pip install requests)
"""

import argparse
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

try:
    import boto3
    from botocore.exceptions import ClientError as BotoClientError
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False

# ── Server Configuration ─────────────────────────────────────────────────────

SERVERS = {
    "legacy": {
        "label": "EIB Gateway (Neo4j+ChromaDB)",
        "transport": "http",
        "url": os.environ.get(
            "LEGACY_MCP_URL",
            "https://xpjldqf6-18888.use.devtunnels.ms/mcp",
        ),
        "headers": {
            "Authorization": "Bearer eib-mcp-gateway-token-2025",
            "Content-Type": "application/json",
        },
    },
    "agentcore": {
        "label": "AgentCore (Neptune+OpenSearch)",
        "transport": "agentcore",
        "runtime_arn": os.environ.get(
            "AGENTCORE_RUNTIME_ARN",
            "arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/mdc_mcp_rag_server-TMXDllG2Wi",
        ),
        "region": os.environ.get("AWS_REGION", "us-east-1"),
    },
}

# ── Test Definitions ─────────────────────────────────────────────────────────
# Each test: (tool_name, args, category, description, quality_checks)
# quality_checks is a list of lambdas that receive the result text and return
# (passed: bool, reason: str).

def _has_text(result: str, needle: str) -> tuple:
    ok = needle.lower() in result.lower()
    return (ok, f"contains '{needle}'" if ok else f"missing '{needle}'")

def _min_length(result: str, n: int) -> tuple:
    ok = len(result) >= n
    return (ok, f"len={len(result)} >= {n}" if ok else f"len={len(result)} < {n}")

def _has_table(result: str) -> tuple:
    ok = "|" in result and "---" in result
    return (ok, "has markdown table" if ok else "no markdown table")

def _no_error(result: str) -> tuple:
    markers = ["error", "failed", "timed out", "exception"]
    for m in markers:
        if m in result.lower() and "error_handling" not in result.lower():
            return (False, f"contains error marker: '{m}'")
    return (True, "no error markers")


TOOL_TESTS = [
    # ── Static / Info tools ──────────────────────────────────────────────
    {
        "tool": "get_server_info",
        "args": {"include_capabilities": True},
        "category": "info",
        "desc": "Server info + capabilities",
        "checks": [
            lambda r: _has_text(r, "tools"),
            lambda r: _min_length(r, 200),
        ],
    },
    {
        "tool": "get_workflow_structure",
        "args": {"component": "jobs"},
        "category": "info",
        "desc": "Workflow structure (jobs)",
        "checks": [
            lambda r: _has_text(r, "job"),
            lambda r: _min_length(r, 100),
        ],
    },
    {
        "tool": "describe_component",
        "args": {"component": "scripts/exglobal_forecast.sh"},
        "category": "info",
        "desc": "Describe component",
        "checks": [
            lambda r: _has_text(r, "forecast"),
            lambda r: _no_error(r),
        ],
    },
    # ── Code Analysis (graph DB) ─────────────────────────────────────────
    {
        "tool": "get_code_context",
        "args": {"symbol": "exglobal_forecast", "depth": 1, "token_budget": 2000},
        "category": "graph",
        "desc": "Code context (graph neighborhood)",
        "checks": [
            lambda r: _min_length(r, 100),
            lambda r: _no_error(r),
        ],
    },
    {
        "tool": "find_callers_callees",
        "args": {"function_name": "setup_expt", "cross_language": True},
        "category": "graph",
        "desc": "Callers/callees (cross-language)",
        "checks": [
            lambda r: _has_text(r, "caller") or _has_text(r, "callee"),
            lambda r: _no_error(r),
        ],
    },
    {
        "tool": "trace_full_execution_chain",
        "args": {"start": "JGLOBAL_FORECAST", "direction": "forward", "max_depth": 3},
        "category": "graph",
        "desc": "Full execution chain trace",
        "checks": [
            lambda r: _has_text(r, "JGLOBAL_FORECAST"),
            lambda r: _has_text(r, "shell") or _has_text(r, "fortran"),
            lambda r: _no_error(r),
        ],
    },
    {
        "tool": "find_env_dependencies",
        "args": {"variable_name": "HOMEgfs"},
        "category": "graph",
        "desc": "Env var dependencies",
        "checks": [
            lambda r: _has_text(r, "HOMEgfs") or _has_text(r, "homegfs"),
            lambda r: _no_error(r),
        ],
    },
    {
        "tool": "trace_execution_path",
        "args": {"function_name": "exglobal_forecast", "max_depth": 2},
        "category": "graph",
        "desc": "Execution path trace",
        "checks": [
            lambda r: _min_length(r, 50),
            lambda r: _no_error(r),
        ],
    },
    {
        "tool": "find_dependencies",
        "args": {"target": "scripts/exglobal_forecast.sh", "direction": "downstream"},
        "category": "graph",
        "desc": "File dependencies (downstream)",
        "checks": [
            lambda r: _min_length(r, 50),
            lambda r: _no_error(r),
        ],
    },
    {
        "tool": "analyze_code_structure",
        "args": {"file_path": "scripts/exglobal_forecast.sh"},
        "category": "graph",
        "desc": "Code structure analysis",
        "checks": [
            lambda r: _min_length(r, 100),
            lambda r: _no_error(r),
        ],
    },
    # ── Semantic Search (vector + graph hybrid) ──────────────────────────
    {
        "tool": "search_documentation",
        "args": {"query": "forecast model configuration", "max_results": 3},
        "category": "semantic",
        "desc": "Hybrid doc search",
        "checks": [
            lambda r: _has_text(r, "result") or _has_text(r, "similarity"),
            lambda r: _min_length(r, 100),
            lambda r: _no_error(r),
        ],
    },
    {
        "tool": "search_architecture",
        "args": {"query": "data assimilation subsystem", "max_results": 3},
        "category": "semantic",
        "desc": "Architecture search",
        "checks": [
            lambda r: _has_text(r, "community") or _has_text(r, "subsystem"),
            lambda r: _no_error(r),
        ],
    },
    {
        "tool": "explain_with_context",
        "args": {"topic": "UFS model coupling", "detail_level": "basic"},
        "category": "semantic",
        "desc": "RAG explanation",
        "checks": [
            lambda r: _min_length(r, 200),
            lambda r: _no_error(r),
        ],
    },
    {
        "tool": "find_similar_code",
        "args": {"code_or_symbol": "error handling pattern", "max_results": 3},
        "category": "semantic",
        "desc": "Similar code search",
        "checks": [
            lambda r: _min_length(r, 50),
            lambda r: _no_error(r),
        ],
    },
    {
        "tool": "get_knowledge_base_status",
        "args": {"include_graph": True, "include_vector": True},
        "category": "semantic",
        "desc": "Knowledge base status",
        "checks": [
            lambda r: _has_text(r, "collections") or _has_text(r, "vector"),
            lambda r: _has_text(r, "graph") or _has_text(r, "files"),
            lambda r: _no_error(r),
        ],
    },
    # ── EE2 Compliance ───────────────────────────────────────────────────
    {
        "tool": "search_ee2_standards",
        "args": {"query": "error handling requirements", "max_results": 3},
        "category": "ee2",
        "desc": "EE2 standards search",
        "checks": [
            lambda r: _has_text(r, "error") or _has_text(r, "handling"),
            lambda r: _no_error(r),
        ],
    },
    # ── Operational ──────────────────────────────────────────────────────
    {
        "tool": "explain_workflow_component",
        "args": {"component": "JGLOBAL_FORECAST", "detail_level": "basic"},
        "category": "operational",
        "desc": "Workflow component explanation",
        "checks": [
            lambda r: _has_text(r, "forecast") or _has_text(r, "JGLOBAL"),
            lambda r: _min_length(r, 100),
            lambda r: _no_error(r),
        ],
    },
    {
        "tool": "list_job_scripts",
        "args": {"category": "forecast", "format": "summary"},
        "category": "operational",
        "desc": "List forecast job scripts",
        "checks": [
            lambda r: _has_text(r, "forecast") or _has_text(r, "job"),
            lambda r: _no_error(r),
        ],
    },
    {
        "tool": "get_job_details",
        "args": {"job_name": "JGLOBAL_FORECAST"},
        "category": "operational",
        "desc": "Job details",
        "checks": [
            lambda r: _has_text(r, "JGLOBAL_FORECAST") or _has_text(r, "forecast"),
            lambda r: _no_error(r),
        ],
    },
    # ── Impact Analysis ──────────────────────────────────────────────────
    {
        "tool": "get_change_impact",
        "args": {"symbol": "exglobal_forecast", "change_type": "behavior"},
        "category": "graph",
        "desc": "Change impact analysis",
        "checks": [
            lambda r: _min_length(r, 100),
            lambda r: _no_error(r),
        ],
    },
    {
        "tool": "trace_data_flow",
        "args": {"from_symbol": "exglobal_forecast", "max_depth": 3},
        "category": "graph",
        "desc": "Data flow trace",
        "checks": [
            lambda r: _min_length(r, 50),
            lambda r: _no_error(r),
        ],
    },
    # ── Health / Utility ─────────────────────────────────────────────────
    {
        "tool": "mcp_health_check",
        "args": {"deep": True, "detailed": True},
        "category": "utility",
        "desc": "Deep health check",
        "checks": [
            lambda r: _has_text(r, "healthy") or _has_text(r, "degraded"),
            lambda r: _has_text(r, "tools"),
            lambda r: _no_error(r),
        ],
    },
]



# ── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class ToolResult:
    tool: str
    server: str
    category: str
    desc: str
    latency_ms: float
    success: bool
    error: Optional[str] = None
    response_length: int = 0
    quality_checks: List[tuple] = field(default_factory=list)  # [(passed, reason)]
    quality_score: float = 0.0  # 0.0 - 1.0


@dataclass
class ParityResult:
    tool: str
    category: str
    desc: str
    legacy: Optional[ToolResult] = None
    agentcore: Optional[ToolResult] = None
    latency_ratio: Optional[float] = None  # agentcore / legacy
    response_length_ratio: Optional[float] = None
    both_succeeded: bool = False
    quality_match: Optional[str] = None  # "match", "partial", "mismatch"


# ── MCP Transport Clients ────────────────────────────────────────────────────

class MCPHttpClient:
    """MCP-over-HTTP client using JSON-RPC 2.0 (Streamable HTTP)."""

    def __init__(self, url: str, headers: dict, label: str):
        self.url = url
        self.headers = headers
        self.label = label
        self.session = requests.Session()
        self.session.headers.update(headers)
        self._initialized = False
        self._mcp_session_id = None

    def _init_session(self):
        """Send initialize + initialized notifications (MCP handshake)."""
        if self._initialized:
            return
        resp = self._raw_call("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "mcp-parity-test", "version": "1.0.0"},
        }, capture_session=True)
        if resp and "result" in resp:
            self._initialized = True
            self._raw_notify("notifications/initialized", {})

    def _raw_call(self, method: str, params: dict, capture_session: bool = False) -> Optional[dict]:
        msg_id = str(uuid.uuid4())[:8]
        payload = {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params}
        headers = {}
        if self._mcp_session_id:
            headers["mcp-session-id"] = self._mcp_session_id
        try:
            resp = self.session.post(self.url, json=payload, timeout=120, headers=headers)
            # Capture session ID from initialize response
            if capture_session and "mcp-session-id" in resp.headers:
                self._mcp_session_id = resp.headers["mcp-session-id"]
            if "text/event-stream" in resp.headers.get("content-type", ""):
                return self._parse_sse(resp.text, msg_id)
            return resp.json()
        except Exception as e:
            return {"error": {"message": str(e)}}

    def _raw_notify(self, method: str, params: dict):
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        headers = {}
        if self._mcp_session_id:
            headers["mcp-session-id"] = self._mcp_session_id
        try:
            self.session.post(self.url, json=payload, timeout=10, headers=headers)
        except Exception:
            pass

    def _parse_sse(self, text: str, expected_id: str) -> Optional[dict]:
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                    if isinstance(data, dict) and data.get("id") == expected_id:
                        return data
                    if isinstance(data, dict) and "result" in data:
                        return data
                except json.JSONDecodeError:
                    continue
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"error": {"message": f"Could not parse SSE response (len={len(text)})"}}

    def call_tool(self, tool_name: str, args: dict) -> tuple:
        """Call an MCP tool. Returns (result_text, latency_ms, error)."""
        self._init_session()
        t0 = time.monotonic()
        resp = self._raw_call("tools/call", {"name": tool_name, "arguments": args})
        latency_ms = (time.monotonic() - t0) * 1000

        if resp is None:
            return ("", latency_ms, "No response")
        if "error" in resp:
            err_msg = resp["error"].get("message", str(resp["error"]))
            return ("", latency_ms, err_msg)

        result = resp.get("result", {})
        content = result.get("content", [])
        text_parts = [item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text"]
        text = "\n".join(text_parts)
        error = text[:200] if result.get("isError") else None
        return (text, latency_ms, error)


class AgentCoreClient:
    """MCP client that calls tools via AgentCore invoke_agent_runtime API."""

    def __init__(self, runtime_arn: str, region: str, label: str):
        if not HAS_BOTO3:
            raise RuntimeError("boto3 required for AgentCore transport (pip install boto3)")
        self.runtime_arn = runtime_arn
        self.region = region
        self.label = label
        from botocore.config import Config
        self.client = boto3.client(
            "bedrock-agentcore",
            region_name=region,
            config=Config(read_timeout=300, connect_timeout=10, retries={"max_attempts": 0}),
        )
        self.session_id = f"parity-test-{uuid.uuid4().hex[:24]}"
        self._initialized = False

    def _invoke(self, payload: dict) -> str:
        """Send JSON-RPC payload to AgentCore, return raw SSE body text."""
        resp = self.client.invoke_agent_runtime(
            agentRuntimeArn=self.runtime_arn,
            runtimeSessionId=self.session_id,
            contentType="application/json",
            accept="application/json, text/event-stream",
            payload=json.dumps(payload).encode("utf-8"),
            qualifier="DEFAULT",
        )
        body = resp["response"].read().decode("utf-8")
        return body

    def _parse_sse(self, raw: str) -> Optional[dict]:
        """Parse SSE event stream for the JSON-RPC response."""
        for line in raw.split("\n"):
            line = line.strip()
            if line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                    if isinstance(data, dict) and ("result" in data or "error" in data):
                        return data
                except json.JSONDecodeError:
                    continue
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def _init_session(self):
        """Send MCP initialize handshake via AgentCore."""
        if self._initialized:
            return
        try:
            raw = self._invoke({
                "jsonrpc": "2.0", "id": "init-1", "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "mcp-parity-test", "version": "1.0.0"},
                },
            })
            self._parse_sse(raw)
            # Send initialized notification
            self._invoke({
                "jsonrpc": "2.0", "method": "notifications/initialized", "params": {},
            })
            self._initialized = True
        except Exception as e:
            print(f"  [WARN] AgentCore init failed: {e}", file=sys.stderr)

    def call_tool(self, tool_name: str, args: dict) -> tuple:
        """Call an MCP tool via AgentCore. Returns (result_text, latency_ms, error)."""
        self._init_session()
        msg_id = str(uuid.uuid4())[:8]
        payload = {
            "jsonrpc": "2.0", "id": msg_id, "method": "tools/call",
            "params": {"name": tool_name, "arguments": args},
        }

        t0 = time.monotonic()
        try:
            raw = self._invoke(payload)
            data = self._parse_sse(raw)
            latency_ms = (time.monotonic() - t0) * 1000
        except Exception as e:
            latency_ms = (time.monotonic() - t0) * 1000
            return ("", latency_ms, str(e))

        if data is None:
            return ("", latency_ms, "No parseable response from AgentCore")
        if "error" in data:
            err_msg = data["error"].get("message", str(data["error"]))
            return ("", latency_ms, err_msg)

        result = data.get("result", {})
        content = result.get("content", [])
        text_parts = [item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text"]
        text = "\n".join(text_parts)
        error = text[:200] if result.get("isError") else None
        return (text, latency_ms, error)

    def stop_session(self):
        """Stop the AgentCore session to release the microVM and its Neptune connections.

        This prevents connection pool exhaustion on Neptune (1000 connection limit)
        when running repeated test sessions. Without this, timed-out or abandoned
        sessions leave dangling Bolt connections until Neptune's idle timeout reaps them.
        """
        if not self._initialized:
            return
        try:
            self.client.stop_runtime_session(
                agentRuntimeArn=self.runtime_arn,
                runtimeSessionId=self.session_id,
                qualifier="DEFAULT",
            )
            print(f"  [OK] AgentCore session stopped: {self.session_id[:20]}...", file=sys.stderr)
        except Exception as e:
            print(f"  [WARN] Failed to stop session: {e}", file=sys.stderr)


def create_client(server_name: str):
    """Factory: create the right client based on server transport type."""
    cfg = SERVERS[server_name]
    if cfg["transport"] == "http":
        return MCPHttpClient(cfg["url"], cfg["headers"], cfg["label"])
    elif cfg["transport"] == "agentcore":
        return AgentCoreClient(cfg["runtime_arn"], cfg["region"], cfg["label"])
    else:
        raise ValueError(f"Unknown transport: {cfg['transport']}")


# ── Test Runner ──────────────────────────────────────────────────────────────

class ParityTestRunner:
    """Runs all tool tests against one or both servers."""

    def __init__(self, servers: List[str]):
        self.clients = {}
        for name in servers:
            self.clients[name] = create_client(name)
        self.results: List[ParityResult] = []

    def run_all(self) -> List[ParityResult]:
        total = len(TOOL_TESTS)
        for i, test in enumerate(TOOL_TESTS, 1):
            tool = test["tool"]
            args = test["args"]
            category = test["category"]
            desc = test["desc"]
            checks = test.get("checks", [])

            print(f"[{i}/{total}] {tool}: {desc}")

            parity = ParityResult(tool=tool, category=category, desc=desc)

            for server_name, client in self.clients.items():
                print(f"  → {server_name}...", end=" ", flush=True)
                text, latency_ms, error = client.call_tool(tool, args)

                # Run quality checks
                quality_results = []
                if text and not error:
                    for check_fn in checks:
                        try:
                            passed, reason = check_fn(text)
                            quality_results.append((passed, reason))
                        except Exception as e:
                            quality_results.append((False, f"check error: {e}"))

                passed_count = sum(1 for p, _ in quality_results if p)
                total_checks = len(quality_results)
                quality_score = passed_count / total_checks if total_checks > 0 else (1.0 if not error else 0.0)

                result = ToolResult(
                    tool=tool,
                    server=server_name,
                    category=category,
                    desc=desc,
                    latency_ms=round(latency_ms, 1),
                    success=error is None,
                    error=error[:200] if error else None,
                    response_length=len(text),
                    quality_checks=quality_results,
                    quality_score=round(quality_score, 2),
                )

                if server_name == "legacy":
                    parity.legacy = result
                else:
                    parity.agentcore = result

                status = "✅" if not error else "❌"
                print(f"{status} {latency_ms:.0f}ms, {len(text)} chars, quality={quality_score:.0%}")

            # Compute parity metrics
            if parity.legacy and parity.agentcore:
                parity.both_succeeded = parity.legacy.success and parity.agentcore.success
                if parity.legacy.latency_ms > 0:
                    parity.latency_ratio = round(parity.agentcore.latency_ms / parity.legacy.latency_ms, 2)
                if parity.legacy.response_length > 0:
                    parity.response_length_ratio = round(
                        parity.agentcore.response_length / parity.legacy.response_length, 2
                    )
                # Quality match assessment
                if parity.both_succeeded:
                    lq = parity.legacy.quality_score
                    aq = parity.agentcore.quality_score
                    if lq == aq == 1.0:
                        parity.quality_match = "match"
                    elif abs(lq - aq) <= 0.2:
                        parity.quality_match = "partial"
                    else:
                        parity.quality_match = "mismatch"
                else:
                    parity.quality_match = "n/a"

            self.results.append(parity)

        return self.results

    def generate_report(self, output_path: Optional[str] = None) -> str:
        """Generate a markdown report."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        servers_tested = list(self.clients.keys())

        md = f"# MCP Tool Parity & Performance Report\n\n"
        md += f"**Date**: {now}  \n"
        md += f"**Servers**: {', '.join(SERVERS[s]['label'] for s in servers_tested)}  \n"
        md += f"**Tests**: {len(self.results)}  \n\n"

        # ── Summary table ────────────────────────────────────────────────
        if len(servers_tested) == 2:
            md += "## Summary\n\n"
            both_ok = sum(1 for r in self.results if r.both_succeeded)
            legacy_only = sum(1 for r in self.results if r.legacy and r.legacy.success and r.agentcore and not r.agentcore.success)
            ac_only = sum(1 for r in self.results if r.agentcore and r.agentcore.success and r.legacy and not r.legacy.success)
            both_fail = sum(1 for r in self.results if r.legacy and not r.legacy.success and r.agentcore and not r.agentcore.success)

            md += f"| Metric | Value |\n|--------|-------|\n"
            md += f"| Both succeeded | {both_ok}/{len(self.results)} |\n"
            md += f"| Legacy only | {legacy_only} |\n"
            md += f"| AgentCore only | {ac_only} |\n"
            md += f"| Both failed | {both_fail} |\n\n"

        # ── Per-tool comparison table ────────────────────────────────────
        md += "## Tool Results\n\n"

        if len(servers_tested) == 2:
            md += "| Tool | Category | Legacy ms | AC ms | Ratio | Legacy Q | AC Q | Match |\n"
            md += "|------|----------|-----------|-------|-------|----------|------|-------|\n"
            for r in self.results:
                l_ms = f"{r.legacy.latency_ms:.0f}" if r.legacy else "—"
                a_ms = f"{r.agentcore.latency_ms:.0f}" if r.agentcore else "—"
                ratio = f"{r.latency_ratio:.1f}x" if r.latency_ratio else "—"
                l_q = f"{r.legacy.quality_score:.0%}" if r.legacy else "—"
                a_q = f"{r.agentcore.quality_score:.0%}" if r.agentcore else "—"
                l_status = "✅" if r.legacy and r.legacy.success else "❌"
                a_status = "✅" if r.agentcore and r.agentcore.success else "❌"
                match = r.quality_match or "—"
                match_icon = {"match": "✅", "partial": "⚠️", "mismatch": "❌", "n/a": "—"}.get(match, match)
                md += f"| {r.tool} | {r.category} | {l_status} {l_ms} | {a_status} {a_ms} | {ratio} | {l_q} | {a_q} | {match_icon} |\n"
        else:
            server = servers_tested[0]
            md += f"| Tool | Category | Status | Latency (ms) | Response Len | Quality |\n"
            md += f"|------|----------|--------|-------------|-------------|--------|\n"
            for r in self.results:
                tr = r.legacy if server == "legacy" else r.agentcore
                if tr:
                    status = "✅" if tr.success else "❌"
                    md += f"| {tr.tool} | {tr.category} | {status} | {tr.latency_ms:.0f} | {tr.response_length} | {tr.quality_score:.0%} |\n"

        # ── Category summary ─────────────────────────────────────────────
        md += "\n## Category Summary\n\n"
        categories = sorted(set(r.category for r in self.results))
        for server in servers_tested:
            md += f"\n### {SERVERS[server]['label']}\n\n"
            md += "| Category | Tests | Passed | Avg Latency (ms) | Avg Quality |\n"
            md += "|----------|-------|--------|-------------------|-------------|\n"
            for cat in categories:
                cat_results = [
                    (r.legacy if server == "legacy" else r.agentcore)
                    for r in self.results if r.category == cat
                ]
                cat_results = [tr for tr in cat_results if tr is not None]
                if not cat_results:
                    continue
                total = len(cat_results)
                passed = sum(1 for tr in cat_results if tr.success)
                avg_lat = sum(tr.latency_ms for tr in cat_results) / total
                avg_q = sum(tr.quality_score for tr in cat_results) / total
                md += f"| {cat} | {total} | {passed}/{total} | {avg_lat:.0f} | {avg_q:.0%} |\n"

        # ── Failures detail ──────────────────────────────────────────────
        failures = []
        for r in self.results:
            for server in servers_tested:
                tr = r.legacy if server == "legacy" else r.agentcore
                if tr and not tr.success:
                    failures.append((server, tr))

        if failures:
            md += "\n## Failures\n\n"
            for server, tr in failures:
                md += f"- **{tr.tool}** ({server}): {tr.error}\n"

        # ── Quality check details ────────────────────────────────────────
        md += "\n## Quality Check Details\n\n"
        for r in self.results:
            for server in servers_tested:
                tr = r.legacy if server == "legacy" else r.agentcore
                if tr and tr.quality_checks:
                    failed_checks = [(p, reason) for p, reason in tr.quality_checks if not p]
                    if failed_checks:
                        md += f"- **{tr.tool}** ({server}): "
                        md += ", ".join(reason for _, reason in failed_checks)
                        md += "\n"

        md += f"\n---\n*Generated by `tools/mcp-parity-test.py` at {now}*\n"

        if output_path:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "w") as f:
                f.write(md)
            print(f"\n[OK] Report written to {output_path}")

        return md


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="MCP Tool Parity & Performance Test")
    parser.add_argument(
        "--server",
        choices=["legacy", "agentcore", "both"],
        default="both",
        help="Which server(s) to test (default: both)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output markdown file path (default: reports/mcp-parity-YYYY-MM-DD.md)",
    )
    parser.add_argument(
        "--tools",
        nargs="*",
        help="Only run specific tools (by name)",
    )
    parser.add_argument(
        "--category",
        choices=["info", "graph", "semantic", "ee2", "operational", "utility"],
        help="Only run tools in this category",
    )
    args = parser.parse_args()

    # Filter tests
    global TOOL_TESTS
    if args.tools:
        TOOL_TESTS = [t for t in TOOL_TESTS if t["tool"] in args.tools]
    if args.category:
        TOOL_TESTS = [t for t in TOOL_TESTS if t["category"] == args.category]

    if not TOOL_TESTS:
        print("[ERROR] No tests match the filter criteria", file=sys.stderr)
        sys.exit(1)

    # Select servers
    if args.server == "both":
        servers = ["legacy", "agentcore"]
    else:
        servers = [args.server]

    # Default output path
    output = args.output or f"reports/mcp-parity-{datetime.now().strftime('%Y-%m-%d')}.md"

    print(f"MCP Parity Test — {len(TOOL_TESTS)} tools × {len(servers)} server(s)\n")

    runner = ParityTestRunner(servers)
    try:
        runner.run_all()
    finally:
        # Always clean up AgentCore sessions to release Neptune connections.
        # Without this, timed-out tests leave dangling connections that accumulate
        # toward Neptune's 1000-connection limit.
        for name, client in runner.clients.items():
            if hasattr(client, 'stop_session'):
                client.stop_session()

    report = runner.generate_report(output)

    # Print summary to stdout
    print(report)


if __name__ == "__main__":
    main()
