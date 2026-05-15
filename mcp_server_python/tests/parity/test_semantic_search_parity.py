"""Parity tests for ``src.tools.semantic_search`` (Task 8.2, Phase B5).

Runs each of the 7 semantic-search tools against the Node.js production
AgentCore Runtime (``mdc_mcp_rag_server-TMXDllG2Wi``) and the Python
staging AgentCore Runtime (``mdc_mcp_rag_server_python-v5K2F8BGrN``) and
compares the results under the comparison modes appropriate for each
tool.

Live-server tests are gated behind the ``RUN_PARITY=1`` environment
variable so the default ``pytest`` run stays hermetic and does not
require AWS credentials. When ``RUN_PARITY=1`` is set the test suite
also expects ``NODEJS_RUNTIME_ID`` / ``PYTHON_RUNTIME_ID`` env vars and
valid AWS credentials for ``bedrock-agentcore:InvokeAgentRuntime``.

Test layout:

* A handful of *hermetic* smoke tests (no env var required) exercise
  the comparison framework against mock callers that return identical
  / divergent payloads. These validate that the parity-runner wiring
  is correct without touching a live server.
* The *live* parity cases (35+ queries across 7 tools) use the real
  ``AgentCoreToolCaller`` and only run when ``RUN_PARITY=1``.

Example invocations::

    # Default hermetic run — 4-5 assertions, no AWS calls
    pytest mcp_server_python/tests/parity/test_semantic_search_parity.py

    # Full parity against live runtimes
    RUN_PARITY=1 AWS_REGION=us-east-1 \
        NODEJS_RUNTIME_ID=arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/mdc_mcp_rag_server-TMXDllG2Wi \
        PYTHON_RUNTIME_ID=arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/mdc_mcp_rag_server_python-v5K2F8BGrN \
        pytest mcp_server_python/tests/parity/test_semantic_search_parity.py -v

The suite uses ``pytest.mark.parametrize`` so every query case shows
up as its own pytest node — a divergence in one case does not abort
the rest.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Callable

import pytest

from tests.parity.parity_runner import (
    ComparisonMode,
    HTTPJSONRPCToolCaller,
    ParityCase,
    ParityResult,
    ParityRunner,
    ToolCaller,
)

# Marker applied to every test in this module — makes it straightforward
# to run ``pytest -m parity`` or ``pytest -m "not parity"``.
pytestmark = pytest.mark.parity


# ── test parameters ─────────────────────────────────────────────────────

RUN_PARITY_FLAG = os.environ.get("RUN_PARITY", "").strip() in ("1", "true", "yes")
NODEJS_RUNTIME_ID = os.environ.get("NODEJS_RUNTIME_ID", "").strip()
PYTHON_RUNTIME_ID = os.environ.get("PYTHON_RUNTIME_ID", "").strip()
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1").strip() or "us-east-1"

# Skip decorators applied to every live-server test.
requires_live_servers = pytest.mark.skipif(
    not RUN_PARITY_FLAG,
    reason=(
        "live-server parity tests skipped — set RUN_PARITY=1 "
        "to enable (requires AWS credentials)"
    ),
)
requires_runtime_ids = pytest.mark.skipif(
    RUN_PARITY_FLAG
    and (not NODEJS_RUNTIME_ID or not PYTHON_RUNTIME_ID),
    reason=(
        "RUN_PARITY=1 is set but NODEJS_RUNTIME_ID / PYTHON_RUNTIME_ID "
        "are missing"
    ),
)


# ── AgentCore transport ─────────────────────────────────────────────────


class AgentCoreToolCaller:
    """``ToolCaller`` that invokes an AgentCore Runtime via boto3.

    Mirrors the transport used by ``tools/agentcore-kiro-proxy.py`` so
    test invocations behave identically to how Kiro reaches the
    servers. Each call issues a ``tools/call`` JSON-RPC payload, parses
    the SSE response, and returns the inner ``result`` dict.

    Kept as a small local class rather than imported from
    ``tools/agentcore-kiro-proxy.py`` (which lives outside
    ``mcp_server_python/``) to avoid pulling that file into the Python
    port's test dependency surface.
    """

    def __init__(self, runtime_id: str, *, region: str = AWS_REGION) -> None:
        if not runtime_id:
            raise ValueError("runtime_id is required")
        import boto3  # Lazy — keeps hermetic tests free of boto3.
        from botocore.config import Config

        self._runtime_id = runtime_id
        self._client = boto3.client(
            "bedrock-agentcore",
            region_name=region,
            config=Config(
                read_timeout=300,
                connect_timeout=10,
                retries={"max_attempts": 2},
            ),
        )
        self._session_id = f"parity-test-{uuid.uuid4().hex}"
        self._request_id = 0

    async def __call__(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> Any:
        import asyncio

        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }

        def _invoke() -> str:
            response = self._client.invoke_agent_runtime(
                agentRuntimeArn=self._runtime_id,
                runtimeSessionId=self._session_id,
                contentType="application/json",
                accept="application/json, text/event-stream",
                payload=json.dumps(payload).encode("utf-8"),
                qualifier="DEFAULT",
            )
            return response["response"].read().decode("utf-8")

        raw = await asyncio.to_thread(_invoke)
        frames = _parse_sse(raw)
        # The MCP tools/call spec returns one JSON-RPC response; when
        # SSE buffers multiple events we pick the one with our request ID.
        for frame in frames:
            if frame.get("id") == self._request_id:
                if "error" in frame:
                    raise RuntimeError(
                        f"{tool_name} returned MCP error: {frame['error']}"
                    )
                return frame.get("result")
        if not frames:
            raise RuntimeError(
                f"{tool_name}: AgentCore returned empty response body"
            )
        return frames[-1].get("result")


def _parse_sse(body: str) -> list[dict[str, Any]]:
    """Tiny SSE parser — extracts ``data:`` payloads and JSON-parses them."""
    out: list[dict[str, Any]] = []
    for frame in body.split("\n\n"):
        frame = frame.strip()
        if not frame:
            continue
        data_parts: list[str] = []
        for line in frame.split("\n"):
            if line.startswith("data:"):
                data_parts.append(line[5:].strip())
            elif data_parts:
                data_parts.append(line.strip())
        if not data_parts:
            continue
        try:
            out.append(json.loads("".join(data_parts)))
        except json.JSONDecodeError:
            continue
    return out


# ── shared extractors ───────────────────────────────────────────────────


def _result_text(raw: Any) -> str:
    """Pull the first text content block out of an MCP tools/call result.

    MCP ``tools/call`` returns ``{"content": [{"type": "text", "text": ...}]}``.
    This helper tolerates a handful of shapes so hermetic tests that pass
    raw strings and live SSE responses both work.
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        content = raw.get("content") or raw.get("result", {}).get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    return block.get("text") or ""
        text = raw.get("text")
        if isinstance(text, str):
            return text
    return str(raw)


def _extract_markdown_headings(raw: Any, level: int = 2) -> list[str]:
    """Return the ``##``-level headings from a markdown response.

    Useful for comparing the *shape* of two markdown outputs: tools
    that return different body text but the same section structure will
    still match under SET_EQUALITY.
    """
    marker = "#" * level
    text = _result_text(raw)
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(marker + " ") or stripped == marker:
            out.append(stripped)
    return out


_BULLET_PATH_RE = re.compile(r"^-\s+`([^`]+)`")


def _extract_bulleted_paths(raw: Any) -> list[str]:
    r"""Extract file/module names from markdown list items like ``- `x` ``.

    Used by the ``find_related_files`` parity projection — the actual
    file paths returned by the graph must agree between the two runtimes
    (order does not matter, so this is paired with SET_EQUALITY).
    """
    text = _result_text(raw)
    out: list[str] = []
    for line in text.splitlines():
        match = _BULLET_PATH_RE.match(line.strip())
        if match:
            out.append(match.group(1))
    return out


_SIM_RE = re.compile(r"\*\*Similarity:\*\*\s+([0-9.]+)%")
_SOURCE_RE = re.compile(r"\*\*Source:\*\*\s+(\S+)")


def _extract_top_sources(raw: Any, limit: int = 5) -> list[str]:
    """Return the first N ``Source:`` fields from search results.

    Matches the "top-5 document ID match" requirement from the task
    description — since the rendered markdown doesn't expose raw
    document IDs, the source file field is the next-best stable key.
    """
    text = _result_text(raw)
    out: list[str] = []
    for line in text.splitlines():
        match = _SOURCE_RE.search(line)
        if match:
            out.append(match.group(1).rstrip(","))
            if len(out) >= limit:
                break
    return out


def _extract_enabled_urls(raw: Any) -> list[str]:
    """Parse the ``get_ingested_urls_array`` JSON block out of markdown."""
    text = _result_text(raw)
    # The tool renders the enabled URLs inside a ```json ... ``` block.
    fence_start = text.find("## Enabled URLs")
    if fence_start < 0:
        return []
    snippet = text[fence_start:]
    json_block_start = snippet.find("```json")
    if json_block_start < 0:
        return []
    json_block_end = snippet.find("```", json_block_start + 7)
    if json_block_end < 0:
        return []
    raw_json = snippet[json_block_start + 7 : json_block_end].strip()
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list):
        return [str(u) for u in parsed]
    return []


_NUMBER_RE = re.compile(r"\*\*([A-Za-z ]+):\*\*\s+([0-9,]+)")


def _extract_status_counts(raw: Any) -> list[float]:
    """Extract numeric values from ``get_knowledge_base_status`` markdown."""
    text = _result_text(raw)
    counts: list[float] = []
    for line in text.splitlines():
        match = _NUMBER_RE.search(line)
        if match:
            try:
                counts.append(float(match.group(2).replace(",", "")))
            except ValueError:
                continue
    return counts


def _is_error_response(raw: Any) -> bool:
    text = _result_text(raw)
    return text.strip().startswith("[ERROR]")


# ── hermetic smoke tests ────────────────────────────────────────────────


def _make_mock_caller(
    table: dict[tuple[str, str], Any],
) -> ToolCaller:
    """Build a ToolCaller keyed by (tool_name, query) for tight assertions."""

    async def _call(tool_name: str, arguments: dict[str, Any]) -> Any:
        key_q = (
            arguments.get("query")
            or arguments.get("file_path")
            or arguments.get("topic")
            or ""
        )
        return table.get((tool_name, key_q)) or table.get((tool_name, ""))

    return _call


async def test_framework_wires_against_mock_callers() -> None:
    """Sanity-check: the framework itself returns PASS/FAIL correctly.

    This is the canary that fires before any real parity failure —
    without this baseline, a green ``test_live_parity`` could mean
    "runtimes agree" or "our comparison logic is broken".
    """
    shared_response = {
        "content": [
            {
                "type": "text",
                "text": (
                    "# Search Results: test\n\nFound 3 results\n\n"
                    "## alpha\n**Similarity:** 90.0%\n**Source:** file_a.py\n\n"
                    "## beta\n**Similarity:** 80.0%\n**Source:** file_b.py\n\n"
                    "## gamma\n**Similarity:** 70.0%\n**Source:** file_c.py\n"
                ),
            }
        ]
    }
    node = _make_mock_caller({("search_documentation", "q"): shared_response})
    python = _make_mock_caller({("search_documentation", "q"): shared_response})

    runner = ParityRunner(node, python)
    result = await runner.assert_parity(
        "search_documentation",
        {"query": "q"},
        comparison=ComparisonMode.EXACT,
        id_extractor=lambda r: _extract_top_sources(r, 5),
    )
    assert result.passed, result.describe()
    assert result.nodejs_result == ["file_a.py", "file_b.py", "file_c.py"]


async def test_framework_detects_divergence() -> None:
    """Confirms the framework flags genuine divergences."""
    node_resp = {
        "content": [
            {
                "type": "text",
                "text": (
                    "## A\n**Source:** file_a.py\n\n"
                    "## B\n**Source:** file_b.py\n"
                ),
            }
        ]
    }
    python_resp = {
        "content": [
            {
                "type": "text",
                "text": (
                    "## A\n**Source:** file_a.py\n\n"
                    "## C\n**Source:** file_c.py\n"
                ),
            }
        ]
    }
    runner = ParityRunner(
        _make_mock_caller({("search_documentation", "q"): node_resp}),
        _make_mock_caller({("search_documentation", "q"): python_resp}),
    )
    result = await runner.assert_parity(
        "search_documentation",
        {"query": "q"},
        comparison=ComparisonMode.EXACT,
        id_extractor=lambda r: _extract_top_sources(r, 5),
    )
    assert not result.passed
    assert "file_b.py" in (result.divergence or "")
    assert "file_c.py" in (result.divergence or "")


async def test_set_equality_projection_picks_up_bullets() -> None:
    """``_extract_bulleted_paths`` + SET_EQUALITY handles unordered lists."""
    node_resp = {
        "content": [
            {
                "type": "text",
                "text": (
                    "## Files with Similar Dependencies\n\n"
                    "- `a.py`\n- `b.py`\n- `c.py`\n"
                ),
            }
        ]
    }
    # Different order should still pass.
    python_resp = {
        "content": [
            {
                "type": "text",
                "text": (
                    "## Files with Similar Dependencies\n\n"
                    "- `c.py`\n- `a.py`\n- `b.py`\n"
                ),
            }
        ]
    }
    runner = ParityRunner(
        _make_mock_caller({("find_related_files", "x"): node_resp}),
        _make_mock_caller({("find_related_files", "x"): python_resp}),
    )
    result = await runner.assert_parity(
        "find_related_files",
        {"file_path": "x"},
        comparison=ComparisonMode.SET_EQUALITY,
        name_extractor=_extract_bulleted_paths,
    )
    assert result.passed, result.describe()


async def test_enabled_urls_parser_round_trips_markdown() -> None:
    """``_extract_enabled_urls`` recovers the JSON block emitted by the tool."""
    text = (
        "# Ingested URLs Array\n\n**Version**: 8.1.0\n\n"
        "## Enabled URLs (2)\n\n"
        "```json\n"
        + json.dumps(["https://a", "https://b"], indent=2)
        + "\n```\n\n"
        "## Source Details\n\n```json\n[]\n```\n"
    )
    raw = {"content": [{"type": "text", "text": text}]}
    assert _extract_enabled_urls(raw) == ["https://a", "https://b"]


# ── live parity query catalogue ─────────────────────────────────────────


@dataclass
class ToolCase:
    """One parity assertion (wraps :class:`ParityCase` with a pytest id)."""

    tool_name: str
    arguments: dict[str, Any]
    comparison: ComparisonMode
    extractor: Callable[[Any], Iterable[Any]] | None = None
    extractor_kind: str = "id"  # "id" | "name" | "score"
    description: str = ""

    @property
    def pytest_id(self) -> str:
        short = (
            self.description
            or (self.arguments.get("query") or "")
            or (self.arguments.get("file_path") or "")
            or (self.arguments.get("topic") or "")
            or "default"
        )[:60]
        return f"{self.tool_name}::{short}"


# Top-5 source match for search_documentation (Task 8.2 requirement).
SEARCH_CASES: list[ToolCase] = [
    ToolCase(
        "search_documentation",
        {"query": "GFS forecast job configuration", "max_results": 5},
        ComparisonMode.EXACT,
        lambda r: _extract_top_sources(r, 5),
        description="gfs-forecast-job",
    ),
    ToolCase(
        "search_documentation",
        {"query": "exglobal forecast python script", "max_results": 5},
        ComparisonMode.EXACT,
        lambda r: _extract_top_sources(r, 5),
        description="exglobal-forecast-script",
    ),
    ToolCase(
        "search_documentation",
        {"query": "EE2 compliance standards NCO", "max_results": 5},
        ComparisonMode.EXACT,
        lambda r: _extract_top_sources(r, 5),
        description="ee2-compliance",
    ),
    ToolCase(
        "search_documentation",
        {
            "query": "rocoto workflow XML task",
            "max_results": 5,
            "collection": "global-workflow-docs-v8-0-0",
        },
        ComparisonMode.EXACT,
        lambda r: _extract_top_sources(r, 5),
        description="rocoto-single-collection",
    ),
    ToolCase(
        "search_documentation",
        {"query": "ESMF NUOPC coupling mediator", "max_results": 5},
        ComparisonMode.EXACT,
        lambda r: _extract_top_sources(r, 5),
        description="esmf-nuopc",
    ),
    ToolCase(
        "search_documentation",
        {
            "query": "spack environment module load",
            "max_results": 8,
            "similarity_threshold": 0.15,
        },
        ComparisonMode.EXACT,
        lambda r: _extract_top_sources(r, 5),
        description="spack-env-threshold",
    ),
]

FIND_RELATED_CASES: list[ToolCase] = [
    ToolCase(
        "find_related_files",
        {"file_path": "scripts/exglobal_forecast.py"},
        ComparisonMode.SET_EQUALITY,
        _extract_bulleted_paths,
        extractor_kind="name",
        description="exglobal-forecast",
    ),
    ToolCase(
        "find_related_files",
        {"file_path": "jobs/JGLOBAL_FORECAST"},
        ComparisonMode.SET_EQUALITY,
        _extract_bulleted_paths,
        extractor_kind="name",
        description="jglobal-forecast",
    ),
    ToolCase(
        "find_related_files",
        {"file_path": "ush/forecast_postdet.sh"},
        ComparisonMode.SET_EQUALITY,
        _extract_bulleted_paths,
        extractor_kind="name",
        description="forecast-postdet",
    ),
    ToolCase(
        "find_related_files",
        {"file_path": "parm/config/gfs/config.base", "max_results": 15},
        ComparisonMode.SET_EQUALITY,
        _extract_bulleted_paths,
        extractor_kind="name",
        description="config-base",
    ),
    ToolCase(
        "find_related_files",
        {
            "file_path": "scripts/exgfs_atmos_post.sh",
            "include_documentation": False,
        },
        ComparisonMode.SET_EQUALITY,
        _extract_bulleted_paths,
        extractor_kind="name",
        description="exgfs-atmos-post",
    ),
]

EXPLAIN_CASES: list[ToolCase] = [
    ToolCase(
        "explain_with_context",
        {"topic": "forecast", "context_type": "technical"},
        ComparisonMode.SET_EQUALITY,
        lambda r: _extract_markdown_headings(r, 2),
        extractor_kind="name",
        description="forecast-technical",
    ),
    ToolCase(
        "explain_with_context",
        {"topic": "rocoto task dependency", "context_type": "operational"},
        ComparisonMode.SET_EQUALITY,
        lambda r: _extract_markdown_headings(r, 2),
        extractor_kind="name",
        description="rocoto-operational",
    ),
    ToolCase(
        "explain_with_context",
        {
            "topic": "ESMF coupling",
            "context_type": "all",
            "detail_level": "advanced",
        },
        ComparisonMode.SET_EQUALITY,
        lambda r: _extract_markdown_headings(r, 2),
        extractor_kind="name",
        description="esmf-advanced",
    ),
    ToolCase(
        "explain_with_context",
        {
            "topic": "environment variable HOMEgfs",
            "context_type": "configuration",
        },
        ComparisonMode.SET_EQUALITY,
        lambda r: _extract_markdown_headings(r, 2),
        extractor_kind="name",
        description="env-var-homegfs",
    ),
    ToolCase(
        "explain_with_context",
        {"topic": "GFS atmos post job", "detail_level": "basic"},
        ComparisonMode.SET_EQUALITY,
        lambda r: _extract_markdown_headings(r, 2),
        extractor_kind="name",
        description="gfs-atmos-post-basic",
    ),
]

STATUS_CASES: list[ToolCase] = [
    ToolCase(
        "get_knowledge_base_status",
        {},
        ComparisonMode.TOLERANCE,
        _extract_status_counts,
        extractor_kind="score",
        description="full-status",
    ),
    ToolCase(
        "get_knowledge_base_status",
        {"include_vector": True, "include_graph": False},
        ComparisonMode.TOLERANCE,
        _extract_status_counts,
        extractor_kind="score",
        description="vector-only",
    ),
    ToolCase(
        "get_knowledge_base_status",
        {"include_vector": False, "include_graph": True},
        ComparisonMode.TOLERANCE,
        _extract_status_counts,
        extractor_kind="score",
        description="graph-only",
    ),
    ToolCase(
        "get_knowledge_base_status",
        {"include_vector": True, "include_graph": True},
        ComparisonMode.TOLERANCE,
        _extract_status_counts,
        extractor_kind="score",
        description="both-included",
    ),
    ToolCase(
        "get_knowledge_base_status",
        {"include_vector": False, "include_graph": False},
        ComparisonMode.EXACT,
        _extract_markdown_headings,
        extractor_kind="id",
        description="both-excluded",
    ),
]

LIST_URLS_CASES: list[ToolCase] = [
    ToolCase(
        "list_ingested_urls",
        {},
        ComparisonMode.EXACT,
        _extract_markdown_headings,
        description="default-format",
    ),
    ToolCase(
        "list_ingested_urls",
        {"format": "summary"},
        ComparisonMode.EXACT,
        _extract_markdown_headings,
        description="summary-format",
    ),
    ToolCase(
        "list_ingested_urls",
        {"format": "urls_only"},
        ComparisonMode.EXACT,
        # Raw URL list — compare line counts via a simple transform.
        lambda r: sorted(
            u.strip() for u in _result_text(r).splitlines() if u.strip()
        ),
        description="urls-only",
    ),
    ToolCase(
        "list_ingested_urls",
        {"format": "detailed", "source_filter": "global-workflow"},
        ComparisonMode.EXACT,
        _extract_markdown_headings,
        description="filter-global-workflow",
    ),
    ToolCase(
        "list_ingested_urls",
        {"format": "summary", "source_filter": "rocoto"},
        ComparisonMode.EXACT,
        _extract_markdown_headings,
        description="filter-rocoto-summary",
    ),
]

GET_URLS_ARRAY_CASES: list[ToolCase] = [
    ToolCase(
        "get_ingested_urls_array",
        {},
        ComparisonMode.SET_EQUALITY,
        _extract_enabled_urls,
        extractor_kind="name",
        description="enabled-only",
    ),
    ToolCase(
        "get_ingested_urls_array",
        {"include_failed": False},
        ComparisonMode.SET_EQUALITY,
        _extract_enabled_urls,
        extractor_kind="name",
        description="include-failed-false",
    ),
    ToolCase(
        "get_ingested_urls_array",
        {"include_failed": True},
        ComparisonMode.SET_EQUALITY,
        _extract_enabled_urls,
        extractor_kind="name",
        description="include-failed-true",
    ),
    ToolCase(
        "get_ingested_urls_array",
        {},
        ComparisonMode.EXACT,
        _extract_markdown_headings,
        description="headings-match",
    ),
    ToolCase(
        "get_ingested_urls_array",
        {"include_failed": True},
        ComparisonMode.EXACT,
        _extract_markdown_headings,
        description="headings-with-disabled",
    ),
]

INTEGRITY_CASES: list[ToolCase] = [
    ToolCase(
        "check_knowledge_integrity",
        {},
        ComparisonMode.SET_EQUALITY,
        lambda r: [
            row.split("|")[1].strip()
            for row in _result_text(r).splitlines()
            if row.startswith("|") and "---" not in row
            and len(row.split("|")) >= 4
        ][1:],  # skip header row
        extractor_kind="name",
        description="default-sample-50",
    ),
    ToolCase(
        "check_knowledge_integrity",
        {"sample_size": 25},
        ComparisonMode.SET_EQUALITY,
        lambda r: [
            row.split("|")[1].strip()
            for row in _result_text(r).splitlines()
            if row.startswith("|") and "---" not in row
            and len(row.split("|")) >= 4
        ][1:],
        extractor_kind="name",
        description="sample-25",
    ),
    ToolCase(
        "check_knowledge_integrity",
        {"sample_size": 100},
        ComparisonMode.SET_EQUALITY,
        lambda r: [
            row.split("|")[1].strip()
            for row in _result_text(r).splitlines()
            if row.startswith("|") and "---" not in row
            and len(row.split("|")) >= 4
        ][1:],
        extractor_kind="name",
        description="sample-100",
    ),
    ToolCase(
        "check_knowledge_integrity",
        {"sample_size": 10},
        ComparisonMode.SET_EQUALITY,
        _extract_markdown_headings,
        description="sample-10-headings",
    ),
    ToolCase(
        "check_knowledge_integrity",
        {},
        # Only compare that both succeeded (no [ERROR] prefix) — the
        # actual pass/fail flags may differ because the data stores are
        # in different states.
        ComparisonMode.EXACT,
        lambda r: [_is_error_response(r)],
        description="no-error-smoke",
    ),
]


ALL_CASES: list[ToolCase] = (
    SEARCH_CASES
    + FIND_RELATED_CASES
    + EXPLAIN_CASES
    + STATUS_CASES
    + LIST_URLS_CASES
    + GET_URLS_ARRAY_CASES
    + INTEGRITY_CASES
)


def _build_parity_case(case: ToolCase) -> ParityCase:
    """Translate a ``ToolCase`` into the framework's :class:`ParityCase`."""
    kwargs: dict[str, Any] = {
        "tool_name": case.tool_name,
        "arguments": dict(case.arguments),
        "comparison": case.comparison,
        "module": "semantic_search",
    }
    if case.extractor is not None:
        if case.extractor_kind == "id":
            kwargs["id_extractor"] = case.extractor
        elif case.extractor_kind == "name":
            kwargs["name_extractor"] = case.extractor
        elif case.extractor_kind == "score":
            kwargs["score_extractor"] = case.extractor
    return ParityCase(**kwargs)


# Quick sanity — the catalogue really has the promised coverage.
def test_catalogue_has_minimum_coverage() -> None:
    """Require at least 5 cases per tool and 35+ cases total."""
    by_tool: dict[str, int] = {}
    for case in ALL_CASES:
        by_tool[case.tool_name] = by_tool.get(case.tool_name, 0) + 1
    expected_tools = {
        "search_documentation",
        "find_related_files",
        "explain_with_context",
        "get_knowledge_base_status",
        "list_ingested_urls",
        "get_ingested_urls_array",
        "check_knowledge_integrity",
    }
    assert set(by_tool) == expected_tools, (
        f"missing tool coverage: {expected_tools - set(by_tool)}"
    )
    for tool, count in by_tool.items():
        assert count >= 5, f"{tool} has only {count} cases; need >= 5"
    assert len(ALL_CASES) >= 35, (
        f"{len(ALL_CASES)} cases total; need >= 35"
    )


# ── live parity tests ───────────────────────────────────────────────────


@pytest.fixture(scope="module")
def parity_runner() -> ParityRunner:
    """Construct a ParityRunner wired to the live AgentCore runtimes.

    Raises if called while ``RUN_PARITY`` / runtime IDs are unset — the
    caller should have been skipped by :data:`requires_live_servers`
    before reaching this fixture.
    """
    if not RUN_PARITY_FLAG:
        pytest.skip("live parity disabled (RUN_PARITY not set)")
    if not NODEJS_RUNTIME_ID or not PYTHON_RUNTIME_ID:
        pytest.skip("runtime IDs not configured")
    node = AgentCoreToolCaller(NODEJS_RUNTIME_ID, region=AWS_REGION)
    python = AgentCoreToolCaller(PYTHON_RUNTIME_ID, region=AWS_REGION)
    return ParityRunner(node, python)


@requires_live_servers
@requires_runtime_ids
@pytest.mark.parametrize(
    "case", ALL_CASES, ids=[c.pytest_id for c in ALL_CASES]
)
async def test_live_parity(parity_runner: ParityRunner, case: ToolCase) -> None:
    """Run one parity case against both runtimes and assert agreement.

    Each case is an independent pytest node so a divergence in one
    query does not abort the whole batch. The failure message is the
    full :pymeth:`ParityResult.describe` output.
    """
    parity_case = _build_parity_case(case)
    result: ParityResult = await parity_runner.assert_parity(
        parity_case.tool_name,
        parity_case.arguments,
        comparison=parity_case.comparison,
        tolerance=parity_case.effective_tolerance(),
        id_extractor=parity_case.id_extractor,
        name_extractor=parity_case.name_extractor,
        score_extractor=parity_case.score_extractor,
    )
    assert result.passed, result.describe()


# Smoke test: ``HTTPJSONRPCToolCaller`` is wired but unused; this test
# just verifies the class is importable and exposes the ToolCaller
# shape, so adding it to the suite counts as defensive coverage for
# when a future phase wants to bypass AgentCore in favour of a
# Streamable-HTTP endpoint.
def test_http_caller_is_importable() -> None:
    caller = HTTPJSONRPCToolCaller("http://localhost:8000/mcp")
    assert callable(caller)
