"""Parity tests for ``src.tools.workflow_info`` (Task 15.3, Phase B10b).

Compares the 3 workflow-info tools against the Node.js production
AgentCore Runtime (``mdc_mcp_rag_server-TMXDllG2Wi``) and the Python
staging AgentCore Runtime (``mdc_mcp_rag_server_python-v5K2F8BGrN``).

Per-tool parity projections
---------------------------

* ``get_workflow_structure`` — SET_EQUALITY on the listed component
  names (the ``### key/`` headings rendered in the System Components
  block, or the ``## Component: <name>`` heading when focused).
* ``get_system_configs`` — SET_EQUALITY on the rendered config-block
  H2 headings (Available Platforms, Module Configuration, Resource
  Configuration, Path Configuration, plus per-platform Environment
  blocks). The actual env file body diverges legitimately between
  the runtimes (the Node.js port reads from disk while the Python
  port may read from a different bind-mount), so the *set* of
  rendered sections is the stable invariant.
* ``describe_component`` — SET_EQUALITY on the listed entity names
  in directory mode (the ``- name`` bullet list under
  ``### Files/Directories``). For the show_content=True case use
  EXACT comparison on the component-summary block (Path / Type /
  Size / Language) which is byte-identical when both runtimes hit
  the same file.

Hermetic smoke + schema parity always run. The 15 live cases are
gated on ``RUN_PARITY=1 NODEJS_RUNTIME_ID=... PYTHON_RUNTIME_ID=...``.
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
_HEADING_RE_3 = re.compile(r"^###\s+(.+?)\s*$")


def _extract_h2_headings(raw: Any) -> list[str]:
    """All level-2 (##) headings."""
    text = _result_text(raw)
    out: list[str] = []
    for line in text.splitlines():
        match = _HEADING_RE_2.match(line.strip())
        if match:
            out.append(match.group(1).strip())
    return out


def _extract_h3_headings(raw: Any) -> list[str]:
    """All level-3 (###) headings, normalized."""
    text = _result_text(raw)
    out: list[str] = []
    for line in text.splitlines():
        match = _HEADING_RE_3.match(line.strip())
        if match:
            title = match.group(1).strip()
            # Strip trailing slash on component names like ``### jobs/``
            if title.endswith("/"):
                title = title[:-1]
            out.append(title)
    return out


def _extract_component_listing(raw: Any) -> list[str]:
    """For ``get_workflow_structure``: extract the System Components
    listing (each component rendered as ``### key/`` heading).

    When ``component=...`` is passed the rendering takes the focused
    branch which has a single ``## Component: <name>`` heading instead
    — so we fall back to that under SET_EQUALITY.
    """
    text = _result_text(raw)
    components: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        m3 = _HEADING_RE_3.match(line)
        if m3 and m3.group(1).rstrip("/") in {
            "jobs", "scripts", "parm", "ush", "sorc", "docs", "env"
        }:
            components.append(m3.group(1).rstrip("/"))
            continue
        m2 = _HEADING_RE_2.match(line)
        if m2:
            head = m2.group(1).strip()
            if head.startswith("Component: "):
                components.append(head[len("Component: "):])
    return components


def _extract_directory_entries(raw: Any) -> list[str]:
    """For ``describe_component`` in directory-listing mode: extract
    the ``- name`` bullet list under ``### Files/Directories``.
    """
    text = _result_text(raw)
    in_listing = False
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("### Files/Directories"):
            in_listing = True
            continue
        if in_listing and stripped.startswith("### "):
            break
        if in_listing and stripped.startswith("## "):
            break
        if in_listing and stripped.startswith("- ") and len(stripped) > 2:
            name = stripped[2:].strip()
            if name and not name.startswith("("):
                out.append(name)
    return out


def _extract_summary_block(raw: Any) -> str:
    """Return the bold-field summary block (Path / Type / Size /
    Language / Lines) from a ``describe_component`` response.

    Used under EXACT comparison for show_content=True cases where
    both runtimes hit the same file with identical content.
    """
    text = _result_text(raw)
    fields: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        for prefix in (
            "**Path:**",
            "**Type:**",
            "**Size:**",
            "**Language:**",
            "**Lines:**",
        ):
            if line.startswith(prefix):
                fields.append(line)
                break
    return "\n".join(fields)


# ── hermetic smoke tests ────────────────────────────────────────────────


def _make_mock_caller(table: dict[str, Any]) -> ToolCaller:
    """Build a ToolCaller keyed by tool name."""

    async def _call(tool_name: str, arguments: dict[str, Any]) -> Any:
        return table.get(tool_name)

    return _call


async def test_framework_passes_when_components_match() -> None:
    body = (
        "# Global Workflow Structure\n\n"
        "## System Components\n\n"
        "### jobs/\n- a\n"
        "### scripts/\n- b\n"
        "### env/\n- c\n"
    )
    resp = {"content": [{"type": "text", "text": body}]}
    runner = ParityRunner(
        _make_mock_caller({"get_workflow_structure": resp}),
        _make_mock_caller({"get_workflow_structure": resp}),
    )
    result = await runner.assert_parity(
        "get_workflow_structure",
        {},
        comparison=ComparisonMode.SET_EQUALITY,
        name_extractor=_extract_component_listing,
    )
    assert result.passed, result.describe()


async def test_framework_detects_missing_component() -> None:
    full = (
        "## System Components\n\n"
        "### jobs/\n### scripts/\n### env/\n"
    )
    short = "## System Components\n\n### jobs/\n### scripts/\n"
    runner = ParityRunner(
        _make_mock_caller(
            {"get_workflow_structure": {"content": [{"type": "text", "text": full}]}}
        ),
        _make_mock_caller(
            {"get_workflow_structure": {"content": [{"type": "text", "text": short}]}}
        ),
    )
    result = await runner.assert_parity(
        "get_workflow_structure",
        {},
        comparison=ComparisonMode.SET_EQUALITY,
        name_extractor=_extract_component_listing,
    )
    assert not result.passed
    assert result.divergence is not None


def test_extractor_component_listing() -> None:
    raw = {
        "content": [
            {
                "type": "text",
                "text": (
                    "## System Components\n"
                    "### jobs/\n"
                    "### scripts/\n"
                    "### env/\n"
                    "### sorc/\n"
                    "### somethingelse\n"  # not a known component, ignore
                ),
            }
        ]
    }
    assert _extract_component_listing(raw) == [
        "jobs",
        "scripts",
        "env",
        "sorc",
    ]


def test_extractor_component_listing_focused_form() -> None:
    raw = {
        "content": [
            {
                "type": "text",
                "text": (
                    "# Global Workflow Structure\n\n"
                    "## Component: env\n"
                    "**Description:** ...\n"
                ),
            }
        ]
    }
    assert _extract_component_listing(raw) == ["env"]


def test_extractor_directory_entries_filters_to_listing_block() -> None:
    raw = {
        "content": [
            {
                "type": "text",
                "text": (
                    "**Type:** Directory\n"
                    "**Contents:** 3 items\n\n"
                    "### Files/Directories\n\n"
                    "- alpha\n"
                    "- beta\n"
                    "- gamma\n"
                    "## Some Other Section\n"
                    "- not_part_of_listing\n"
                ),
            }
        ]
    }
    assert _extract_directory_entries(raw) == ["alpha", "beta", "gamma"]


def test_extractor_summary_block() -> None:
    raw = {
        "content": [
            {
                "type": "text",
                "text": (
                    "# Component: tool.py\n\n"
                    "**Path:** ${HOMEgfs}/dev/jobs/tool.py\n"
                    "**Type:** File\n"
                    "**Size:** 120 bytes\n"
                    "**Language:** Python\n"
                    "**Lines:** 5\n"
                    "Some body text\n"
                ),
            }
        ]
    }
    summary = _extract_summary_block(raw)
    assert "**Path:** ${HOMEgfs}/dev/jobs/tool.py" in summary
    assert "**Language:** Python" in summary


# ── schema parity ──────────────────────────────────────────────────────


def test_schema_parity_with_nodejs_source() -> None:
    """Python-registered schemas match the Node.js source 1:1."""
    import asyncio
    import tempfile

    from fastmcp import FastMCP

    from src.tools import workflow_info

    async def _run() -> None:
        with tempfile.TemporaryDirectory() as td:
            mcp = FastMCP("parity-schema-check", version="1.0.0")
            workflow_info.register(mcp, data=None, workflow_root=td)
            tools = {
                t.name: t
                for t in await mcp.list_tools(run_middleware=False)
            }

        expected: dict[str, dict[str, Any]] = {
            "get_workflow_structure": {
                "params": {"component", "structure_data"},
                "required": set(),
                "defaults": {},
                "enums": {
                    "component": {
                        "jobs",
                        "scripts",
                        "parm",
                        "ush",
                        "sorc",
                        "docs",
                        "env",
                    },
                },
            },
            "get_system_configs": {
                "params": {"platform", "config_type", "content"},
                "required": set(),
                "defaults": {},
                "enums": {
                    "platform": {
                        "hera",
                        "hercules",
                        "orion",
                        "wcoss2",
                        "gaea",
                        "all",
                    },
                    "config_type": {
                        "modules",
                        "resources",
                        "paths",
                        "all",
                    },
                },
            },
            "describe_component": {
                "params": {
                    "component",
                    "show_content",
                    "content",
                    "file_type",
                },
                "required": {"component"},
                "defaults": {"show_content": False},
                "enums": {
                    "file_type": {"file", "directory"},
                },
            },
        }

        for tool_name, spec in expected.items():
            assert tool_name in tools, f"{tool_name} not registered"
            schema = tools[tool_name].parameters
            props = schema.get("properties", {})
            assert set(props) == spec["params"], (
                f"{tool_name}: params mismatch "
                f"{set(props) ^ spec['params']}"
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
            or self.arguments.get("component")
            or self.arguments.get("platform")
            or "default"
        )[:60]
        return f"{self.tool_name}::{short}"


# ``get_workflow_structure`` — SET_EQUALITY on rendered components.
STRUCTURE_CASES: list[ToolCase] = [
    ToolCase(
        "get_workflow_structure",
        {},
        ComparisonMode.SET_EQUALITY,
        _extract_component_listing,
        description="full-overview",
    ),
    ToolCase(
        "get_workflow_structure",
        {"component": "jobs"},
        ComparisonMode.SET_EQUALITY,
        _extract_component_listing,
        description="focus-jobs",
    ),
    ToolCase(
        "get_workflow_structure",
        {"component": "env"},
        ComparisonMode.SET_EQUALITY,
        _extract_component_listing,
        description="focus-env",
    ),
    ToolCase(
        "get_workflow_structure",
        {"component": "sorc"},
        ComparisonMode.SET_EQUALITY,
        _extract_component_listing,
        description="focus-sorc",
    ),
    ToolCase(
        "get_workflow_structure",
        {"component": "ush"},
        ComparisonMode.SET_EQUALITY,
        _extract_component_listing,
        description="focus-ush",
    ),
]

# ``get_system_configs`` — SET_EQUALITY on rendered H2 headings. The
# section structure (Available Platforms / Module Configuration /
# Path Configuration / Resource Configuration / per-platform
# Environment) is stable across both runtimes; the env-file body
# may legitimately differ.
SYSTEM_CASES: list[ToolCase] = [
    ToolCase(
        "get_system_configs",
        {},
        ComparisonMode.SET_EQUALITY,
        _extract_h2_headings,
        description="list-all",
    ),
    ToolCase(
        "get_system_configs",
        {"platform": "hera"},
        ComparisonMode.SET_EQUALITY,
        _extract_h2_headings,
        description="hera",
    ),
    ToolCase(
        "get_system_configs",
        {"platform": "wcoss2", "config_type": "modules"},
        ComparisonMode.SET_EQUALITY,
        _extract_h2_headings,
        description="wcoss2-modules",
    ),
    ToolCase(
        "get_system_configs",
        {"platform": "orion", "config_type": "all"},
        ComparisonMode.SET_EQUALITY,
        _extract_h2_headings,
        description="orion-all-config",
    ),
    ToolCase(
        "get_system_configs",
        {"config_type": "paths"},
        ComparisonMode.SET_EQUALITY,
        _extract_h2_headings,
        description="paths-only",
    ),
]

# ``describe_component`` — mix of directory-listing SET_EQUALITY and
# show_content=True summary-block EXACT compare. Components selected
# from real global-workflow paths so both runtimes can find them.
DESCRIBE_CASES: list[ToolCase] = [
    ToolCase(
        "describe_component",
        {"component": "JGFS_FORECAST"},
        ComparisonMode.SET_EQUALITY,
        _extract_directory_entries,
        description="jgfs-forecast",
    ),
    ToolCase(
        "describe_component",
        {"component": "ush"},
        ComparisonMode.SET_EQUALITY,
        _extract_directory_entries,
        description="ush-directory",
    ),
    ToolCase(
        "describe_component",
        {"component": "env"},
        ComparisonMode.SET_EQUALITY,
        _extract_directory_entries,
        description="env-directory",
    ),
    ToolCase(
        "describe_component",
        {"component": "exgfs_forecast.sh", "show_content": True},
        ComparisonMode.EXACT,
        _extract_summary_block,
        extractor_kind="id",
        description="exgfs-show-content",
    ),
    ToolCase(
        "describe_component",
        {
            "component": "tool.py",
            "content": (
                "#!/usr/bin/env python3\n"
                "# Description: hermetic\n"
                "import sys\n"
                "print(1)\n"
            ),
            "show_content": True,
        },
        ComparisonMode.EXACT,
        _extract_summary_block,
        extractor_kind="id",
        description="content-driven-python",
    ),
]


ALL_CASES: list[ToolCase] = (
    STRUCTURE_CASES + SYSTEM_CASES + DESCRIBE_CASES
)


def _build_parity_case(case: ToolCase) -> ParityCase:
    kwargs: dict[str, Any] = {
        "tool_name": case.tool_name,
        "arguments": dict(case.arguments),
        "comparison": case.comparison,
        "module": "workflow_info",
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
    """Require exactly 5 cases per tool and 15+ cases total."""
    by_tool: dict[str, int] = {}
    for case in ALL_CASES:
        by_tool[case.tool_name] = by_tool.get(case.tool_name, 0) + 1
    expected_tools = {
        "get_workflow_structure",
        "get_system_configs",
        "describe_component",
    }
    assert set(by_tool) == expected_tools, (
        f"missing tool coverage: {expected_tools - set(by_tool)}"
    )
    for tool, count in by_tool.items():
        assert count >= 5, f"{tool} has only {count} cases; need >= 5"
    assert len(ALL_CASES) >= 15, (
        f"{len(ALL_CASES)} cases total; need >= 15"
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
