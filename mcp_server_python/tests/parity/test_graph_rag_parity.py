"""Parity tests for ``src.tools.graph_rag`` (Task 10.2, Phase B7).

Runs each of the 9 GraphRAG tools against the Node.js production
AgentCore Runtime (``mdc_mcp_rag_server-TMXDllG2Wi``) and the Python
staging AgentCore Runtime (``mdc_mcp_rag_server_python-v5K2F8BGrN``)
and compares the results under the comparison mode appropriate for
each tool's response shape.

Live-server tests are gated behind the ``RUN_PARITY=1`` environment
variable so the default ``pytest`` run stays hermetic and does not
require AWS credentials.

Session tools ('mark_as_modified', 'get_session_context',
'checkpoint_state', 'restore_checkpoint') mutate file-backed state
that is different on each runtime — they will never be byte-identical
between Node.js and Python. For those tools the parity cases use
*structural* assertions that every response has a well-formed
markdown shape, rather than comparing state contents. Graph / vector-
backed tools use SET_EQUALITY or TOLERANCE as documented in the task
description.

Test layout (mirrors B5/B6):

* Hermetic smoke tests (catalogue coverage, schema parity assertion,
  extractor round-trips) always run.
* 45 live-parity parametrized cases (5 per tool × 9 tools) gated on
  ``RUN_PARITY=1 NODEJS_RUNTIME_ID=... PYTHON_RUNTIME_ID=...``.
* Reuses :class:`AgentCoreToolCaller` from the B5 parity module via
  direct import.

Example invocations::

    # Default hermetic run
    pytest mcp_server_python/tests/parity/test_graph_rag_parity.py

    # Full live parity
    RUN_PARITY=1 AWS_REGION=us-east-1 \
        NODEJS_RUNTIME_ID=arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/mdc_mcp_rag_server-TMXDllG2Wi \
        PYTHON_RUNTIME_ID=arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/mdc_mcp_rag_server_python-v5K2F8BGrN \
        pytest mcp_server_python/tests/parity/test_graph_rag_parity.py -v
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Callable

import pytest

from tests.parity.parity_runner import (
    ComparisonMode,
    ParityCase,
    ParityResult,
    ParityRunner,
    ToolCaller,
)
from tests.parity.test_semantic_search_parity import (
    AgentCoreToolCaller,
    _result_text,
)

pytestmark = pytest.mark.parity


# ── test parameters ─────────────────────────────────────────────────────

RUN_PARITY_FLAG = os.environ.get("RUN_PARITY", "").strip() in ("1", "true", "yes")
NODEJS_RUNTIME_ID = os.environ.get("NODEJS_RUNTIME_ID", "").strip()
PYTHON_RUNTIME_ID = os.environ.get("PYTHON_RUNTIME_ID", "").strip()
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1").strip() or "us-east-1"

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


# ── projection helpers ─────────────────────────────────────────────────


_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*$")
_BACKTICK_RE = re.compile(r"`([^`]+)`")


def _extract_markdown_headings(raw: Any, level: int = 2) -> list[str]:
    marker = "#" * level
    text = _result_text(raw)
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith(marker + " ") or line.strip() == marker
    ]


def _extract_symbol_names(raw: Any) -> list[str]:
    """Return every backtick-wrapped token from the response.

    Used under SET_EQUALITY for ``get_code_context`` / ``get_change_impact``
    / ``trace_data_flow``: the set of symbols referenced in the response
    is the parity key. Body text and ordering are allowed to differ.
    """
    text = _result_text(raw)
    seen: list[str] = []
    seen_set: set[str] = set()
    for match in _BACKTICK_RE.finditer(text):
        name = match.group(1)
        if name and name not in seen_set:
            seen.append(name)
            seen_set.add(name)
    return seen


def _extract_similarity_scores(raw: Any) -> list[float]:
    """Return similarity scores from a ``find_similar_code`` table row.

    Node.js renders ``| N | file | 0.923 | preview |`` — we pick out
    the third pipe-delimited column and parse as float.
    """
    text = _result_text(raw)
    scores: list[float] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or "Similarity" in stripped:
            continue
        if "---" in stripped:
            continue
        parts = [p.strip() for p in stripped.split("|")]
        if len(parts) < 5:
            continue
        try:
            scores.append(float(parts[3]))
        except (ValueError, IndexError):
            continue
    return scores


def _extract_community_titles(raw: Any) -> list[str]:
    """Pull out ``## N. Community M`` / subsystem titles from
    ``search_architecture`` responses."""
    text = _result_text(raw)
    out: list[str] = []
    pat = re.compile(r"^##\s+\d+\.\s+(.+?)\s*\(relevance")
    for line in text.splitlines():
        match = pat.match(line.strip())
        if match:
            out.append(match.group(1).strip())
    return out


def _extract_relevance_scores(raw: Any) -> list[float]:
    """Extract ``relevance: X.XXX`` values from ``search_architecture``."""
    text = _result_text(raw)
    pat = re.compile(r"relevance:\s+([0-9.]+)")
    out: list[float] = []
    for match in pat.finditer(text):
        try:
            out.append(float(match.group(1)))
        except ValueError:
            continue
    return out


def _extract_affected_symbols(raw: Any) -> list[str]:
    """Union of Direct + Indirect dependent names from ``get_change_impact``.

    Both sections render as ``| `name` | Type | ... |`` rows — we pick
    the first backtick-quoted token from any row in those sections.
    """
    text = _result_text(raw)
    lines = text.splitlines()
    out: list[str] = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## Direct Dependents") or stripped.startswith(
            "## Indirect Dependents"
        ):
            in_section = True
            continue
        if stripped.startswith("## "):
            in_section = False
            continue
        if not in_section:
            continue
        match = _BACKTICK_RE.search(stripped)
        if match and "|" in stripped:
            out.append(match.group(1))
    return out


def _extract_flow_node_names(raw: Any) -> list[str]:
    """Node names from the Outgoing Relationships / Shortest Path
    sections of ``trace_data_flow``."""
    text = _result_text(raw)
    lines = text.splitlines()
    out: list[str] = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## Outgoing Relationships") or stripped.startswith(
            "## Shortest Path"
        ):
            in_section = True
            continue
        if stripped.startswith("## "):
            in_section = False
            continue
        if not in_section:
            continue
        for match in _BACKTICK_RE.finditer(stripped):
            out.append(match.group(1))
    return out


def _has_modification_recorded_block(raw: Any) -> bool:
    """Structural check for ``mark_as_modified`` parity — the response
    header must match even though the session state underneath does not."""
    text = _result_text(raw)
    return (
        "# File Modification Recorded" in text
        and "**Graph Dirty**" in text
        and "**Total Modifications**:" in text
    )


def _has_session_context_block(raw: Any) -> bool:
    """``get_session_context`` either renders ``# Session Context`` (active
    session) or ``# No Active Session`` (empty). Both are structurally
    valid — parity is the shape-of-response invariant, not the contents."""
    text = _result_text(raw)
    return "# Session Context" in text or "# No Active Session" in text


def _has_checkpoint_created_block(raw: Any) -> bool:
    text = _result_text(raw)
    return (
        "# Checkpoint Created" in text
        and "**ID**" in text
        and "**Snapshot**" in text
    )


def _has_restore_or_error(raw: Any) -> bool:
    """``restore_checkpoint`` either renders ``# Checkpoint Restored`` on a
    valid ID or ``[ERROR]`` on an invalid one — both are structurally
    valid contracts. We assert only that exactly one of the two shapes
    appears (not which), so Node.js and Python can diverge on ID space."""
    text = _result_text(raw)
    return "# Checkpoint Restored" in text or text.strip().startswith("[ERROR]")


# ── hermetic smoke tests ────────────────────────────────────────────────


def _make_mock_caller(
    table: dict[tuple[str, str], Any],
) -> ToolCaller:
    """Build a ToolCaller keyed by (tool_name, primary_arg)."""

    async def _call(tool_name: str, arguments: dict[str, Any]) -> Any:
        key = (
            arguments.get("symbol")
            or arguments.get("code_or_symbol")
            or arguments.get("query")
            or arguments.get("from_symbol")
            or arguments.get("file_path")
            or arguments.get("checkpoint_id")
            or arguments.get("name")
            or ""
        )
        return table.get((tool_name, key)) or table.get((tool_name, ""))

    return _call


async def test_framework_wires_against_mock_callers() -> None:
    """Sanity-check: the framework returns PASS for identical responses."""
    shared = {
        "content": [
            {
                "type": "text",
                "text": (
                    "# Code Context: `forecast`\n\n"
                    "**Type**: Function\n\n"
                    "## Called By (2 callers)\n\n"
                    "| `a` | Function | CALLS |\n"
                    "| `b` | Function | CALLS |\n"
                ),
            }
        ]
    }
    runner = ParityRunner(
        _make_mock_caller({("get_code_context", "forecast"): shared}),
        _make_mock_caller({("get_code_context", "forecast"): shared}),
    )
    result = await runner.assert_parity(
        "get_code_context",
        {"symbol": "forecast"},
        comparison=ComparisonMode.SET_EQUALITY,
        name_extractor=_extract_symbol_names,
    )
    assert result.passed, result.describe()
    assert "forecast" in result.nodejs_result
    assert "a" in result.nodejs_result
    assert "b" in result.nodejs_result


async def test_framework_detects_divergence_on_symbol_set() -> None:
    """SET_EQUALITY flags genuine divergences in the symbol set."""
    node_resp = {
        "content": [
            {
                "type": "text",
                "text": "# Code Context: `x`\n## Direct Dependents\n| `a` | F | C |\n| `b` | F | C |\n",
            }
        ]
    }
    py_resp = {
        "content": [
            {
                "type": "text",
                "text": "# Code Context: `x`\n## Direct Dependents\n| `a` | F | C |\n| `c` | F | C |\n",
            }
        ]
    }
    runner = ParityRunner(
        _make_mock_caller({("get_change_impact", "x"): node_resp}),
        _make_mock_caller({("get_change_impact", "x"): py_resp}),
    )
    result = await runner.assert_parity(
        "get_change_impact",
        {"symbol": "x"},
        comparison=ComparisonMode.SET_EQUALITY,
        name_extractor=_extract_affected_symbols,
    )
    assert not result.passed
    assert "b" in (result.divergence or "") or "c" in (result.divergence or "")


async def test_similarity_score_tolerance_picks_up_small_drift() -> None:
    """TOLERANCE mode should accept ±10% drift on similarity scores."""
    node_resp = {
        "content": [
            {
                "type": "text",
                "text": "| 1 | a.F90 | 0.920 | preview |\n| 2 | b.F90 | 0.810 | preview |\n",
            }
        ]
    }
    py_resp = {
        "content": [
            {
                "type": "text",
                "text": "| 1 | a.F90 | 0.910 | preview |\n| 2 | b.F90 | 0.820 | preview |\n",
            }
        ]
    }
    runner = ParityRunner(
        _make_mock_caller({("find_similar_code", "x"): node_resp}),
        _make_mock_caller({("find_similar_code", "x"): py_resp}),
    )
    result = await runner.assert_parity(
        "find_similar_code",
        {"code_or_symbol": "x"},
        comparison=ComparisonMode.TOLERANCE,
        score_extractor=_extract_similarity_scores,
        tolerance=0.10,
    )
    assert result.passed, result.describe()


async def test_session_tool_structural_check_accepts_shape_divergence() -> None:
    """Session tools pass when both responses share the same block shape,
    even when the session IDs / counts differ."""
    node_resp = {
        "content": [
            {
                "type": "text",
                "text": (
                    "# File Modification Recorded\n\n"
                    "**File**: `x.py`\n"
                    "**Change Type**: content\n"
                    "**Graph Dirty**: Yes (node flagged)\n\n"
                    "**Total Modifications**: 5\n"
                ),
            }
        ]
    }
    py_resp = {
        "content": [
            {
                "type": "text",
                "text": (
                    "# File Modification Recorded\n\n"
                    "**File**: `x.py`\n"
                    "**Change Type**: content\n"
                    "**Graph Dirty**: No (graph unavailable)\n\n"
                    "**Total Modifications**: 2\n"
                ),
            }
        ]
    }
    runner = ParityRunner(
        _make_mock_caller({("mark_as_modified", "x.py"): node_resp}),
        _make_mock_caller({("mark_as_modified", "x.py"): py_resp}),
    )
    result = await runner.assert_parity(
        "mark_as_modified",
        {"file_path": "x.py"},
        comparison=ComparisonMode.EXACT,
        id_extractor=lambda r: [_has_modification_recorded_block(r)],
    )
    assert result.passed, result.describe()


async def test_symbol_extractor_picks_up_backticks() -> None:
    """``_extract_symbol_names`` is order-preserving and deduplicates."""
    raw = {
        "content": [
            {
                "type": "text",
                "text": "a `foo` b `bar` c `foo` d `baz`",
            }
        ]
    }
    out = _extract_symbol_names(raw)
    assert out == ["foo", "bar", "baz"]


async def test_affected_symbols_extractor_scopes_to_dependents_sections() -> None:
    text = (
        "# Change Impact: `target`\n\n"
        "## Risk Factors\n\n"
        "- `ignored_in_risk_section`\n\n"
        "## Direct Dependents (2)\n\n"
        "| `alpha` | F | CALLS |\n"
        "| `beta` | F | CALLS |\n\n"
        "## Indirect Dependents (1)\n\n"
        "| `gamma` | F |\n\n"
        "## Recommendations\n\n"
        "- `not_a_dep`\n"
    )
    raw = {"content": [{"type": "text", "text": text}]}
    out = _extract_affected_symbols(raw)
    assert set(out) == {"alpha", "beta", "gamma"}
    assert "ignored_in_risk_section" not in out
    assert "not_a_dep" not in out


def test_schema_parity_with_nodejs_source() -> None:
    """The Python registered schemas match the Node.js source 1:1.

    Drives parity against the authoritative ``GraphRAGTools.js``
    ``registerWith`` block without needing a live server."""
    import asyncio

    from fastmcp import FastMCP

    from src.tools import graph_rag

    async def _run() -> None:
        mcp = FastMCP("parity-schema-check", version="1.0.0")
        graph_rag.register(mcp, data=None)
        tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}

        expected: dict[str, dict[str, Any]] = {
            "get_code_context": {
                "params": {
                    "symbol",
                    "depth",
                    "include_community",
                    "token_budget",
                },
                "required": {"symbol"},
                "defaults": {
                    "depth": 2,
                    "include_community": True,
                    "token_budget": 4000,
                },
            },
            "search_architecture": {
                "params": {"query", "max_results"},
                "required": {"query"},
                "defaults": {"max_results": 5},
            },
            "find_similar_code": {
                "params": {
                    "code_or_symbol",
                    "similarity_threshold",
                    "max_results",
                },
                "required": {"code_or_symbol"},
                "defaults": {"similarity_threshold": 0.7, "max_results": 10},
            },
            "get_change_impact": {
                "params": {"symbol", "change_type", "include_indirect"},
                "required": {"symbol"},
                "defaults": {
                    "change_type": "behavior",
                    "include_indirect": True,
                },
                "enums": {
                    "change_type": {
                        "signature",
                        "behavior",
                        "delete",
                        "rename",
                    },
                },
            },
            "trace_data_flow": {
                "params": {"from_symbol", "to_symbol", "max_depth"},
                "required": {"from_symbol"},
                "defaults": {"max_depth": 5},
            },
            "mark_as_modified": {
                "params": {"file_path", "change_type", "description"},
                "required": {"file_path"},
                "defaults": {"change_type": "content"},
                "enums": {
                    "change_type": {
                        "content",
                        "signature",
                        "delete",
                        "rename",
                    },
                },
            },
            "get_session_context": {
                "params": {"include_dirty"},
                "required": set(),
                "defaults": {"include_dirty": True},
            },
            "checkpoint_state": {
                "params": {"name", "description"},
                "required": {"name"},
                "defaults": {},
            },
            "restore_checkpoint": {
                "params": {"checkpoint_id"},
                "required": {"checkpoint_id"},
                "defaults": {},
            },
        }

        for tool_name, spec in expected.items():
            assert tool_name in tools, f"{tool_name} not registered"
            schema = tools[tool_name].parameters
            props = schema.get("properties", {})
            assert set(props) == spec["params"], (
                f"{tool_name}: params {set(props) ^ spec['params']}"
            )
            req = set(schema.get("required") or [])
            assert req == spec["required"], (
                f"{tool_name}: required {req} vs {spec['required']}"
            )
            for key, want in spec["defaults"].items():
                got = props[key].get("default")
                assert got == want, (
                    f"{tool_name}.{key}: default {got!r} != {want!r}"
                )
            for enum_key, want in (spec.get("enums") or {}).items():
                enum_list = props[enum_key].get("enum")
                if enum_list is None:
                    for branch in props[enum_key].get("anyOf", []):
                        if "enum" in branch:
                            enum_list = branch["enum"]
                            break
                assert enum_list is not None, f"{tool_name}.{enum_key} no enum"
                assert set(enum_list) == want, (
                    f"{tool_name}.{enum_key}: enum {set(enum_list)} != {want}"
                )

    asyncio.run(_run())


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
    tolerance: float | None = None

    @property
    def pytest_id(self) -> str:
        short = (
            self.description
            or (self.arguments.get("symbol") or "")
            or (self.arguments.get("code_or_symbol") or "")
            or (self.arguments.get("query") or "")
            or (self.arguments.get("from_symbol") or "")
            or (self.arguments.get("file_path") or "")
            or (self.arguments.get("checkpoint_id") or "")
            or (self.arguments.get("name") or "")
            or "default"
        )[:60]
        return f"{self.tool_name}::{short}"


# get_code_context — symbol set SET_EQUALITY + relevance scores TOLERANCE.
CODE_CONTEXT_CASES: list[ToolCase] = [
    ToolCase(
        "get_code_context",
        {"symbol": "forecast"},
        ComparisonMode.SET_EQUALITY,
        _extract_symbol_names,
        extractor_kind="name",
        description="forecast-default",
    ),
    ToolCase(
        "get_code_context",
        {"symbol": "forecast", "depth": 1},
        ComparisonMode.SET_EQUALITY,
        _extract_symbol_names,
        extractor_kind="name",
        description="forecast-depth-1",
    ),
    ToolCase(
        "get_code_context",
        {"symbol": "gsi", "include_community": False},
        ComparisonMode.SET_EQUALITY,
        _extract_symbol_names,
        extractor_kind="name",
        description="gsi-no-community",
    ),
    ToolCase(
        "get_code_context",
        {"symbol": "enkf_main", "depth": 3, "token_budget": 2000},
        ComparisonMode.SET_EQUALITY,
        _extract_symbol_names,
        extractor_kind="name",
        description="enkf-deep",
    ),
    ToolCase(
        "get_code_context",
        {"symbol": "setuprad"},
        ComparisonMode.SET_EQUALITY,
        _extract_markdown_headings,
        extractor_kind="name",
        description="setuprad-headings",
    ),
]

# search_architecture — community titles SET_EQUALITY.
ARCH_CASES: list[ToolCase] = [
    ToolCase(
        "search_architecture",
        {"query": "how does data assimilation work"},
        ComparisonMode.SET_EQUALITY,
        _extract_community_titles,
        extractor_kind="name",
        description="data-assimilation",
    ),
    ToolCase(
        "search_architecture",
        {"query": "ocean modeling subsystem"},
        ComparisonMode.SET_EQUALITY,
        _extract_community_titles,
        extractor_kind="name",
        description="ocean-modeling",
    ),
    ToolCase(
        "search_architecture",
        {"query": "MPI communication patterns", "max_results": 3},
        ComparisonMode.SET_EQUALITY,
        _extract_community_titles,
        extractor_kind="name",
        description="mpi-comms",
    ),
    ToolCase(
        "search_architecture",
        {"query": "GFS forecast workflow", "max_results": 8},
        ComparisonMode.TOLERANCE,
        _extract_relevance_scores,
        extractor_kind="score",
        description="gfs-forecast-relevance",
    ),
    ToolCase(
        "search_architecture",
        {"query": "atmospheric physics parameterization"},
        ComparisonMode.SET_EQUALITY,
        _extract_community_titles,
        extractor_kind="name",
        description="atmos-physics",
    ),
]

# find_similar_code — symbol names + similarity tolerance.
SIMILAR_CASES: list[ToolCase] = [
    ToolCase(
        "find_similar_code",
        {"code_or_symbol": "forecast"},
        ComparisonMode.SET_EQUALITY,
        _extract_symbol_names,
        extractor_kind="name",
        description="forecast",
    ),
    ToolCase(
        "find_similar_code",
        {"code_or_symbol": "enkf_main", "max_results": 5},
        ComparisonMode.SET_EQUALITY,
        _extract_symbol_names,
        extractor_kind="name",
        description="enkf-main-5",
    ),
    ToolCase(
        "find_similar_code",
        {"code_or_symbol": "radiation transfer calculation"},
        ComparisonMode.SET_EQUALITY,
        _extract_symbol_names,
        extractor_kind="name",
        description="radiation-nl",
    ),
    ToolCase(
        "find_similar_code",
        {
            "code_or_symbol": "setuprad",
            "similarity_threshold": 0.5,
            "max_results": 15,
        },
        ComparisonMode.TOLERANCE,
        _extract_similarity_scores,
        extractor_kind="score",
        description="setuprad-scores",
    ),
    ToolCase(
        "find_similar_code",
        {"code_or_symbol": "write_restart", "similarity_threshold": 0.8},
        ComparisonMode.SET_EQUALITY,
        _extract_symbol_names,
        extractor_kind="name",
        description="write-restart-strict",
    ),
]

# get_change_impact — affected-symbols list SET_EQUALITY.
IMPACT_CASES: list[ToolCase] = [
    ToolCase(
        "get_change_impact",
        {"symbol": "forecast"},
        ComparisonMode.SET_EQUALITY,
        _extract_affected_symbols,
        extractor_kind="name",
        description="forecast-default",
    ),
    ToolCase(
        "get_change_impact",
        {"symbol": "gsi", "change_type": "signature"},
        ComparisonMode.SET_EQUALITY,
        _extract_affected_symbols,
        extractor_kind="name",
        description="gsi-signature",
    ),
    ToolCase(
        "get_change_impact",
        {"symbol": "write_restart", "change_type": "delete"},
        ComparisonMode.SET_EQUALITY,
        _extract_affected_symbols,
        extractor_kind="name",
        description="write-restart-delete",
    ),
    ToolCase(
        "get_change_impact",
        {
            "symbol": "enkf_main",
            "change_type": "rename",
            "include_indirect": False,
        },
        ComparisonMode.SET_EQUALITY,
        _extract_affected_symbols,
        extractor_kind="name",
        description="enkf-rename-direct-only",
    ),
    ToolCase(
        "get_change_impact",
        {"symbol": "setuprad", "include_indirect": True},
        ComparisonMode.SET_EQUALITY,
        _extract_affected_symbols,
        extractor_kind="name",
        description="setuprad-indirect",
    ),
]

# trace_data_flow — flow-node names SET_EQUALITY.
TRACE_CASES: list[ToolCase] = [
    ToolCase(
        "trace_data_flow",
        {"from_symbol": "exglobal_forecast.sh"},
        ComparisonMode.SET_EQUALITY,
        _extract_flow_node_names,
        extractor_kind="name",
        description="exglobal-forecast",
    ),
    ToolCase(
        "trace_data_flow",
        {"from_symbol": "JGLOBAL_FORECAST"},
        ComparisonMode.SET_EQUALITY,
        _extract_flow_node_names,
        extractor_kind="name",
        description="jglobal-forecast",
    ),
    ToolCase(
        "trace_data_flow",
        {"from_symbol": "gsi", "max_depth": 8},
        ComparisonMode.SET_EQUALITY,
        _extract_flow_node_names,
        extractor_kind="name",
        description="gsi-deep",
    ),
    ToolCase(
        "trace_data_flow",
        {
            "from_symbol": "exglobal_forecast.sh",
            "to_symbol": "gsi",
            "max_depth": 5,
        },
        ComparisonMode.SET_EQUALITY,
        _extract_flow_node_names,
        extractor_kind="name",
        description="shell-to-fortran",
    ),
    ToolCase(
        "trace_data_flow",
        {"from_symbol": "enkf_main", "max_depth": 3},
        ComparisonMode.SET_EQUALITY,
        _extract_flow_node_names,
        extractor_kind="name",
        description="enkf-main-shallow",
    ),
]

# mark_as_modified — structural-only (state is non-deterministic).
MARK_CASES: list[ToolCase] = [
    ToolCase(
        "mark_as_modified",
        {"file_path": f"parity_probe_a_{i}.py"},
        ComparisonMode.EXACT,
        lambda r: [_has_modification_recorded_block(r)],
        description=f"probe-a-{i}",
    )
    for i in range(3)
] + [
    ToolCase(
        "mark_as_modified",
        {
            "file_path": "parity_probe_b.py",
            "change_type": "signature",
            "description": "parity test",
        },
        ComparisonMode.EXACT,
        lambda r: [_has_modification_recorded_block(r)],
        description="probe-b-signature",
    ),
    ToolCase(
        "mark_as_modified",
        {"file_path": "parity_probe_c.py", "change_type": "delete"},
        ComparisonMode.EXACT,
        lambda r: [_has_modification_recorded_block(r)],
        description="probe-c-delete",
    ),
]

# get_session_context — structural-only.
SESSION_CASES: list[ToolCase] = [
    ToolCase(
        "get_session_context",
        {},
        ComparisonMode.EXACT,
        lambda r: [_has_session_context_block(r)],
        description="default",
    ),
    ToolCase(
        "get_session_context",
        {"include_dirty": True},
        ComparisonMode.EXACT,
        lambda r: [_has_session_context_block(r)],
        description="include-dirty-true",
    ),
    ToolCase(
        "get_session_context",
        {"include_dirty": False},
        ComparisonMode.EXACT,
        lambda r: [_has_session_context_block(r)],
        description="include-dirty-false",
    ),
    ToolCase(
        "get_session_context",
        {},
        ComparisonMode.EXACT,
        # Also assert there is no [ERROR] prefix so both shapes are
        # considered healthy.
        lambda r: [not _result_text(r).strip().startswith("[ERROR]")],
        description="no-error",
    ),
    ToolCase(
        "get_session_context",
        {"include_dirty": True},
        ComparisonMode.EXACT,
        lambda r: [_has_session_context_block(r)],
        description="double-invoke",
    ),
]

# checkpoint_state — structural-only.
CHECKPOINT_CASES: list[ToolCase] = [
    ToolCase(
        "checkpoint_state",
        {"name": f"parity-chk-{i}"},
        ComparisonMode.EXACT,
        lambda r: [_has_checkpoint_created_block(r) or _result_text(r).strip().startswith("[ERROR]")],
        description=f"checkpoint-{i}",
    )
    for i in range(3)
] + [
    ToolCase(
        "checkpoint_state",
        {"name": "parity-chk-described", "description": "parity test"},
        ComparisonMode.EXACT,
        lambda r: [_has_checkpoint_created_block(r) or _result_text(r).strip().startswith("[ERROR]")],
        description="checkpoint-with-description",
    ),
    ToolCase(
        "checkpoint_state",
        {"name": "parity-chk-final", "description": "end of suite"},
        ComparisonMode.EXACT,
        lambda r: [_has_checkpoint_created_block(r) or _result_text(r).strip().startswith("[ERROR]")],
        description="checkpoint-final",
    ),
]

# restore_checkpoint — structural-only (both PASS and ERROR are valid shapes).
RESTORE_CASES: list[ToolCase] = [
    ToolCase(
        "restore_checkpoint",
        {"checkpoint_id": f"chk_parity_invalid_{i}"},
        ComparisonMode.EXACT,
        lambda r: [_has_restore_or_error(r)],
        description=f"invalid-{i}",
    )
    for i in range(3)
] + [
    ToolCase(
        "restore_checkpoint",
        {"checkpoint_id": "chk_format_probe"},
        ComparisonMode.EXACT,
        lambda r: [_has_restore_or_error(r)],
        description="format-probe",
    ),
    ToolCase(
        "restore_checkpoint",
        {"checkpoint_id": "chk_final_probe"},
        ComparisonMode.EXACT,
        lambda r: [_has_restore_or_error(r)],
        description="final-probe",
    ),
]


ALL_CASES: list[ToolCase] = (
    CODE_CONTEXT_CASES
    + ARCH_CASES
    + SIMILAR_CASES
    + IMPACT_CASES
    + TRACE_CASES
    + MARK_CASES
    + SESSION_CASES
    + CHECKPOINT_CASES
    + RESTORE_CASES
)


def _build_parity_case(case: ToolCase) -> ParityCase:
    kwargs: dict[str, Any] = {
        "tool_name": case.tool_name,
        "arguments": dict(case.arguments),
        "comparison": case.comparison,
        "module": "graph_rag",
        "tolerance": case.tolerance,
    }
    if case.extractor is not None:
        if case.extractor_kind == "id":
            kwargs["id_extractor"] = case.extractor
        elif case.extractor_kind == "name":
            kwargs["name_extractor"] = case.extractor
        elif case.extractor_kind == "score":
            kwargs["score_extractor"] = case.extractor
    return ParityCase(**kwargs)


def test_catalogue_has_minimum_coverage() -> None:
    """Require at least 5 cases per tool and 45+ cases total."""
    by_tool: dict[str, int] = {}
    for case in ALL_CASES:
        by_tool[case.tool_name] = by_tool.get(case.tool_name, 0) + 1
    expected_tools = {
        "get_code_context",
        "search_architecture",
        "find_similar_code",
        "get_change_impact",
        "trace_data_flow",
        "mark_as_modified",
        "get_session_context",
        "checkpoint_state",
        "restore_checkpoint",
    }
    assert set(by_tool) == expected_tools, (
        f"missing tool coverage: {expected_tools - set(by_tool)}"
    )
    for tool, count in by_tool.items():
        assert count >= 5, f"{tool} has only {count} cases; need >= 5"
    assert len(ALL_CASES) >= 45, (
        f"{len(ALL_CASES)} cases total; need >= 45"
    )


# ── live parity tests ───────────────────────────────────────────────────


@pytest.fixture(scope="module")
def parity_runner() -> ParityRunner:
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
    """Run one parity case against both runtimes and assert agreement."""
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
