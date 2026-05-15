"""Parity tests for ``src.tools.operational`` (Task 13.2, Phase B9).

Runs each of the 4 operational tools against the Node.js production
AgentCore Runtime (``mdc_mcp_rag_server-TMXDllG2Wi``) and the Python
staging AgentCore Runtime (``mdc_mcp_rag_server_python-v5K2F8BGrN``)
and compares the results under the comparison mode appropriate for
each tool's response shape.

Per-tool parity projections (per task description):

* ``get_operational_guidance`` — SET_EQUALITY on section headings +
  TOLERANCE ±10 % on guidance-item counts (numbered list entries
  under the Procedure block).
* ``explain_workflow_component`` — SET_EQUALITY on section headings.
* ``list_job_scripts`` — SET_EQUALITY on the J-Job name list (per
  category).
* ``get_job_details`` — SET_EQUALITY on the set of metadata field
  names rendered in the response (## Configuration Files, ##
  Sourced Scripts, ## Inputs, etc.). The actual values may legitimately
  drift between the two runtimes because the Node.js port reads the
  script from disk whereas the Python port assembles metadata from
  the graph store; set-equality on which *categories* of metadata
  are available is the stable invariant.

Hermetic smoke + schema parity always run. 20 live cases (5 × 4
tools) are gated on ``RUN_PARITY=1 NODEJS_RUNTIME_ID=...
PYTHON_RUNTIME_ID=...``.

Example invocations::

    # Default hermetic run (no AWS credentials needed)
    pytest mcp_server_python/tests/parity/test_operational_parity.py

    # Full live parity
    RUN_PARITY=1 AWS_REGION=us-east-1 \\
        NODEJS_RUNTIME_ID=arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/mdc_mcp_rag_server-TMXDllG2Wi \\
        PYTHON_RUNTIME_ID=arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/mdc_mcp_rag_server_python-v5K2F8BGrN \\
        pytest mcp_server_python/tests/parity/test_operational_parity.py -v
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


RUN_PARITY_FLAG = os.environ.get("RUN_PARITY", "").strip() in (
    "1",
    "true",
    "yes",
)
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


_HEADING_RE_2 = re.compile(r"^##\s+(.+?)\s*$")
_NUMBERED_ITEM_RE = re.compile(r"^\d+\.\s+\S")
_DASH_ITEM_RE = re.compile(r"^-\s+\S")


def _extract_h2_headings(raw: Any) -> list[str]:
    """Return all level-2 (##) headings in the response."""
    text = _result_text(raw)
    out: list[str] = []
    for line in text.splitlines():
        match = _HEADING_RE_2.match(line.strip())
        if match:
            out.append(match.group(1).strip())
    return out


def _extract_guidance_items(raw: Any) -> list[float]:
    """Count numbered + dash list items under the Procedure block.

    Used under TOLERANCE mode: Node.js and Python may return different
    verbiage but the item count should be within ±10 %. Returned as a
    single-element list so the parity runner can diff a scalar.
    """
    text = _result_text(raw)
    lines = text.splitlines()
    in_procedure = False
    count = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## Procedure"):
            in_procedure = True
            continue
        if stripped.startswith("## ") and in_procedure:
            break
        if not in_procedure:
            continue
        if _NUMBERED_ITEM_RE.match(stripped) or _DASH_ITEM_RE.match(stripped):
            count += 1
    return [float(count)]


def _extract_job_names(raw: Any) -> list[str]:
    """Return the job names listed by ``list_job_scripts``.

    Handles both the summary format (``- JNAME`` bullet list under
    ``## Job List``) and the JSON format (``"jobs": [...]``).
    """
    text = _result_text(raw)
    # JSON format first — try to find the embedded json block.
    import json

    if '"jobs":' in text:
        try:
            start = text.index("```json\n") + len("```json\n")
            end = text.index("\n```", start)
            body = json.loads(text[start:end])
            jobs = body.get("jobs") or []
            return [j for j in jobs if isinstance(j, str)]
        except (ValueError, json.JSONDecodeError):
            pass

    # Summary format — look for `- JNAME` lines under `## Job List`.
    lines = text.splitlines()
    in_list = False
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## Job List"):
            in_list = True
            continue
        if stripped.startswith("## ") and in_list:
            break
        if not in_list:
            continue
        if stripped.startswith("- ") and len(stripped) > 2:
            name = stripped[2:].strip()
            if name.startswith("J"):
                out.append(name)
    return out


def _extract_metadata_fields(raw: Any) -> list[str]:
    """Return the set of metadata field headings present in a
    ``get_job_details`` response.

    A ``get_job_details`` response has a stable set of H2 sections
    (Configuration Files, Sourced Scripts, Inputs, Outputs, Environment
    Variables, ...) driven by what the J-Job actually uses. The *set*
    of sections present is the parity invariant — not their values,
    which may differ between the Node.js (filesystem parse) and Python
    (graph query) implementations.
    """
    return _extract_h2_headings(raw)


# ── hermetic smoke tests ────────────────────────────────────────────────


def _make_mock_caller(
    table: dict[tuple[str, str], Any],
) -> ToolCaller:
    """Build a ToolCaller keyed by (tool_name, primary_arg)."""

    async def _call(tool_name: str, arguments: dict[str, Any]) -> Any:
        key = (
            arguments.get("operation")
            or arguments.get("component")
            or arguments.get("job_name")
            or arguments.get("category")
            or ""
        )
        if not key:
            jl = arguments.get("job_list") or []
            if jl:
                key = jl[0] if isinstance(jl[0], str) else ""
        return table.get((tool_name, key)) or table.get((tool_name, ""))

    return _call


async def test_framework_wires_against_mock_callers() -> None:
    """Sanity-check: the framework returns PASS for identical responses."""
    shared = {
        "content": [
            {
                "type": "text",
                "text": (
                    "# Operational Guidance: foo\n\n"
                    "## Procedure\n\n"
                    "1. Step one\n"
                    "2. Step two\n"
                    "## Platform-Specific Notes\n\n"
                    "- note\n"
                ),
            }
        ]
    }
    runner = ParityRunner(
        _make_mock_caller({("get_operational_guidance", "foo"): shared}),
        _make_mock_caller({("get_operational_guidance", "foo"): shared}),
    )
    result = await runner.assert_parity(
        "get_operational_guidance",
        {"operation": "foo"},
        comparison=ComparisonMode.SET_EQUALITY,
        name_extractor=_extract_h2_headings,
    )
    assert result.passed, result.describe()
    assert "Procedure" in result.nodejs_result
    assert "Platform-Specific Notes" in result.nodejs_result


async def test_framework_detects_heading_set_divergence() -> None:
    """SET_EQUALITY flags a missing section heading."""
    node_resp = {
        "content": [
            {
                "type": "text",
                "text": "## Procedure\n## Platform-Specific Notes\n",
            }
        ]
    }
    py_resp = {
        "content": [{"type": "text", "text": "## Procedure\n"}]
    }
    runner = ParityRunner(
        _make_mock_caller({("get_operational_guidance", "x"): node_resp}),
        _make_mock_caller({("get_operational_guidance", "x"): py_resp}),
    )
    result = await runner.assert_parity(
        "get_operational_guidance",
        {"operation": "x"},
        comparison=ComparisonMode.SET_EQUALITY,
        name_extractor=_extract_h2_headings,
    )
    assert not result.passed
    assert result.divergence is not None


async def test_guidance_item_count_tolerance_accepts_small_drift() -> None:
    """TOLERANCE accepts ±10 % drift on guidance-item count."""
    node_resp = {
        "content": [
            {
                "type": "text",
                "text": (
                    "## Procedure\n\n"
                    "1. a\n2. b\n3. c\n4. d\n5. e\n"
                    "## Platform-Specific Notes\n"
                ),
            }
        ]
    }
    py_resp = {
        "content": [
            {
                "type": "text",
                "text": (
                    "## Procedure\n\n"
                    "1. a\n2. b\n3. c\n4. d\n5. e\n"
                    "## Platform-Specific Notes\n"
                ),
            }
        ]
    }
    runner = ParityRunner(
        _make_mock_caller({("get_operational_guidance", ""): node_resp}),
        _make_mock_caller({("get_operational_guidance", ""): py_resp}),
    )
    result = await runner.assert_parity(
        "get_operational_guidance",
        {"operation": "x"},
        comparison=ComparisonMode.TOLERANCE,
        score_extractor=_extract_guidance_items,
        tolerance=0.10,
    )
    assert result.passed, result.describe()


def test_extractor_h2_headings() -> None:
    raw = {
        "content": [
            {
                "type": "text",
                "text": (
                    "# H1 ignored\n"
                    "## Procedure\n"
                    "body\n"
                    "## Platform-Specific Notes\n"
                    "### H3 ignored\n"
                    "## Other\n"
                ),
            }
        ]
    }
    assert _extract_h2_headings(raw) == [
        "Procedure",
        "Platform-Specific Notes",
        "Other",
    ]


def test_extractor_guidance_items_scopes_to_procedure_block() -> None:
    raw = {
        "content": [
            {
                "type": "text",
                "text": (
                    "## Procedure\n"
                    "1. step one\n"
                    "2. step two\n"
                    "- bullet\n"
                    "## Platform-Specific Notes\n"
                    "- ignored bullet\n"
                    "1. ignored numbered\n"
                ),
            }
        ]
    }
    assert _extract_guidance_items(raw) == [3.0]


def test_extractor_job_names_summary_format() -> None:
    raw = {
        "content": [
            {
                "type": "text",
                "text": (
                    "## Categories\n\n"
                    "- **Analysis:** 2 jobs\n"
                    "## Job List\n"
                    "- JGLOBAL_FORECAST\n"
                    "- JGDAS_FIT2OBS\n"
                ),
            }
        ]
    }
    assert _extract_job_names(raw) == ["JGLOBAL_FORECAST", "JGDAS_FIT2OBS"]


def test_extractor_job_names_json_format() -> None:
    raw = {
        "content": [
            {
                "type": "text",
                "text": (
                    "```json\n"
                    '{"category": "all", "jobs": ["JGLOBAL_FORECAST", '
                    '"JGDAS_FIT2OBS"]}\n'
                    "```\n"
                ),
            }
        ]
    }
    assert _extract_job_names(raw) == ["JGLOBAL_FORECAST", "JGDAS_FIT2OBS"]


# ── schema parity ──────────────────────────────────────────────────────


def test_schema_parity_with_nodejs_source() -> None:
    """The Python registered schemas match the Node.js source 1:1.

    Drives parity against the authoritative ``OperationalTools.js``
    ``registerWith`` block without needing a live server."""
    import asyncio

    from fastmcp import FastMCP

    from src.tools import operational

    async def _run() -> None:
        mcp = FastMCP("parity-schema-check", version="1.0.0")
        operational.register(mcp, data=None)
        tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}

        expected: dict[str, dict[str, Any]] = {
            "get_operational_guidance": {
                "params": {"operation", "platform", "urgency"},
                "required": {"operation"},
                "defaults": {"platform": "generic", "urgency": "routine"},
                "enums": {
                    "platform": {
                        "hera",
                        "hercules",
                        "orion",
                        "wcoss2",
                        "gaea",
                        "generic",
                    },
                    "urgency": {"routine", "urgent", "emergency"},
                },
            },
            "explain_workflow_component": {
                "params": {"component", "detail_level"},
                "required": {"component"},
                "defaults": {"detail_level": "detailed"},
                "enums": {
                    "detail_level": {"basic", "detailed", "expert"},
                },
            },
            "list_job_scripts": {
                "params": {
                    "category",
                    "search",
                    "format",
                    "job_list",
                    "files",
                },
                "required": set(),
                "defaults": {"format": "summary"},
                "enums": {
                    "category": {
                        "analysis",
                        "forecast",
                        "post",
                        "archive",
                        "verification",
                        "all",
                    },
                    "format": {"summary", "detailed", "json"},
                },
            },
            "get_job_details": {
                "params": {
                    "job_name",
                    "include_content",
                    "include_config",
                    "include_chromadb",
                },
                "required": {"job_name"},
                "defaults": {
                    "include_content": False,
                    "include_config": True,
                    "include_chromadb": True,
                },
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
                # Support plain enum, anyOf-with-enum, array-of-enum,
                # and anyOf-array-of-enum shapes.
                enum_list = props[enum_key].get("enum")
                if enum_list is None:
                    for branch in props[enum_key].get("anyOf", []):
                        if "enum" in branch:
                            enum_list = branch["enum"]
                            break
                if enum_list is None:
                    items = props[enum_key].get("items") or {}
                    enum_list = items.get("enum")
                if enum_list is None:
                    for branch in props[enum_key].get("anyOf", []):
                        items = branch.get("items") or {}
                        if "enum" in items:
                            enum_list = items["enum"]
                            break
                assert enum_list is not None, (
                    f"{tool_name}.{enum_key} no enum found"
                )
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
    extractor_kind: str = "name"  # "id" | "name" | "score"
    description: str = ""
    tolerance: float | None = None

    @property
    def pytest_id(self) -> str:
        short = (
            self.description
            or self.arguments.get("operation")
            or self.arguments.get("component")
            or self.arguments.get("job_name")
            or self.arguments.get("category")
            or "default"
        )[:60]
        return f"{self.tool_name}::{short}"


# Sample J-Job names used by list_job_scripts cases so the two
# runtimes receive identical inputs (the Python port has no
# filesystem; the Node.js port reads disk).
_SAMPLE_JOB_NAMES = [
    "JGLOBAL_FORECAST",
    "JGFS_ATMOS_POST",
    "JGDAS_ENKF_ANAL",
    "JGDAS_FIT2OBS",
    "JGLOBAL_ARCHIVE",
    "JGFS_ATMOS_AWIPS",
    "JGDAS_VERFOZN",
]

# get_operational_guidance — section heading SET_EQUALITY +
# guidance-item TOLERANCE.
GUIDANCE_CASES: list[ToolCase] = [
    ToolCase(
        "get_operational_guidance",
        {"operation": "submit forecast job", "platform": "wcoss2"},
        ComparisonMode.SET_EQUALITY,
        _extract_h2_headings,
        description="wcoss2-submit",
    ),
    ToolCase(
        "get_operational_guidance",
        {"operation": "restart from checkpoint", "platform": "hera"},
        ComparisonMode.SET_EQUALITY,
        _extract_h2_headings,
        description="hera-restart",
    ),
    ToolCase(
        "get_operational_guidance",
        {
            "operation": "diagnose failed job",
            "platform": "orion",
            "urgency": "urgent",
        },
        ComparisonMode.SET_EQUALITY,
        _extract_h2_headings,
        description="orion-diagnose-urgent",
    ),
    ToolCase(
        "get_operational_guidance",
        {
            "operation": "system outage recovery",
            "platform": "gaea",
            "urgency": "emergency",
        },
        ComparisonMode.SET_EQUALITY,
        _extract_h2_headings,
        description="gaea-emergency",
    ),
    ToolCase(
        "get_operational_guidance",
        {"operation": "load module dependencies", "platform": "hercules"},
        ComparisonMode.TOLERANCE,
        _extract_guidance_items,
        extractor_kind="score",
        description="hercules-item-count",
    ),
]

# explain_workflow_component — section heading SET_EQUALITY.
EXPLAIN_CASES: list[ToolCase] = [
    ToolCase(
        "explain_workflow_component",
        {"component": "exgfs_forecast.sh"},
        ComparisonMode.SET_EQUALITY,
        _extract_h2_headings,
        description="exgfs-forecast",
    ),
    ToolCase(
        "explain_workflow_component",
        {"component": "JGLOBAL_FORECAST"},
        ComparisonMode.SET_EQUALITY,
        _extract_h2_headings,
        description="jglobal-forecast",
    ),
    ToolCase(
        "explain_workflow_component",
        {"component": "config.fcst", "detail_level": "expert"},
        ComparisonMode.SET_EQUALITY,
        _extract_h2_headings,
        description="config-fcst-expert",
    ),
    ToolCase(
        "explain_workflow_component",
        {"component": "preamble.sh", "detail_level": "basic"},
        ComparisonMode.SET_EQUALITY,
        _extract_h2_headings,
        description="preamble-basic",
    ),
    ToolCase(
        "explain_workflow_component",
        {"component": "ush"},
        ComparisonMode.SET_EQUALITY,
        _extract_h2_headings,
        description="ush-directory",
    ),
]

# list_job_scripts — job-name SET_EQUALITY (per category). Both
# runtimes get identical job_list inputs so the test isolates the
# regex / categorization logic from environmental drift.
LIST_CASES: list[ToolCase] = [
    ToolCase(
        "list_job_scripts",
        {"job_list": _SAMPLE_JOB_NAMES},
        ComparisonMode.SET_EQUALITY,
        _extract_job_names,
        description="all-default",
    ),
    ToolCase(
        "list_job_scripts",
        {"job_list": _SAMPLE_JOB_NAMES, "category": "forecast"},
        ComparisonMode.SET_EQUALITY,
        _extract_job_names,
        description="forecast-only",
    ),
    ToolCase(
        "list_job_scripts",
        {"job_list": _SAMPLE_JOB_NAMES, "category": "post"},
        ComparisonMode.SET_EQUALITY,
        _extract_job_names,
        description="post-only",
    ),
    ToolCase(
        "list_job_scripts",
        {"job_list": _SAMPLE_JOB_NAMES, "category": "verification"},
        ComparisonMode.SET_EQUALITY,
        _extract_job_names,
        description="verification-only",
    ),
    ToolCase(
        "list_job_scripts",
        {
            "job_list": _SAMPLE_JOB_NAMES,
            "search": "gdas",
            "format": "json",
        },
        ComparisonMode.SET_EQUALITY,
        _extract_job_names,
        description="gdas-search-json",
    ),
]

# get_job_details — metadata-field SET_EQUALITY. Field *names* are
# stable; values legitimately drift between Node.js (filesystem read)
# and Python (graph query).
DETAILS_CASES: list[ToolCase] = [
    ToolCase(
        "get_job_details",
        {"job_name": "JGLOBAL_FORECAST"},
        ComparisonMode.SET_EQUALITY,
        _extract_metadata_fields,
        description="jglobal-forecast-default",
    ),
    ToolCase(
        "get_job_details",
        {"job_name": "JGDAS_FIT2OBS", "include_chromadb": False},
        ComparisonMode.SET_EQUALITY,
        _extract_metadata_fields,
        description="fit2obs-no-chromadb",
    ),
    ToolCase(
        "get_job_details",
        {
            "job_name": "JGDAS_ENKF_ANAL",
            "include_config": False,
            "include_chromadb": False,
        },
        ComparisonMode.SET_EQUALITY,
        _extract_metadata_fields,
        description="enkf-anal-minimal",
    ),
    ToolCase(
        "get_job_details",
        {"job_name": "JGFS_ATMOS_POST", "include_content": True},
        ComparisonMode.SET_EQUALITY,
        _extract_metadata_fields,
        description="atmos-post-content",
    ),
    ToolCase(
        "get_job_details",
        {"job_name": "JGLOBAL_ARCHIVE", "include_chromadb": True},
        ComparisonMode.SET_EQUALITY,
        _extract_metadata_fields,
        description="archive-default",
    ),
]


ALL_CASES: list[ToolCase] = (
    GUIDANCE_CASES + EXPLAIN_CASES + LIST_CASES + DETAILS_CASES
)


def _build_parity_case(case: ToolCase) -> ParityCase:
    kwargs: dict[str, Any] = {
        "tool_name": case.tool_name,
        "arguments": dict(case.arguments),
        "comparison": case.comparison,
        "module": "operational",
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
    """Require exactly 5 cases per tool and 20+ cases total."""
    by_tool: dict[str, int] = {}
    for case in ALL_CASES:
        by_tool[case.tool_name] = by_tool.get(case.tool_name, 0) + 1
    expected_tools = {
        "get_operational_guidance",
        "explain_workflow_component",
        "list_job_scripts",
        "get_job_details",
    }
    assert set(by_tool) == expected_tools, (
        f"missing tool coverage: {expected_tools - set(by_tool)}"
    )
    for tool, count in by_tool.items():
        assert count >= 5, f"{tool} has only {count} cases; need >= 5"
    assert len(ALL_CASES) >= 20, (
        f"{len(ALL_CASES)} cases total; need >= 20"
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
