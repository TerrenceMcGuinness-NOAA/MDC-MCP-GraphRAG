"""Parity tests for ``src.tools.github_tools`` (Task 16.3, Phase B11).

Compares the 4 GitHub tools against the Node.js production AgentCore
Runtime (``mdc_mcp_rag_server-TMXDllG2Wi``) and the Python staging
AgentCore Runtime (``mdc_mcp_rag_server_python-v5K2F8BGrN``). The
20 live cases (5 per tool × 4 tools) are gated on both
``RUN_PARITY=1`` and a non-empty ``GITHUB_TOKEN`` — without a token
the live cases skip cleanly because every tool degrades to
"GitHub integration not available - no API access" without
authentication.

Per-tool parity projections
---------------------------

* ``search_issues`` — SET_EQUALITY on issue numbers (``- **Number**:
  #N`` lines). Issue numbers are stable identifiers; titles and
  bodies may legitimately drift between runtimes if either rendering
  layer truncates differently, but the *set* of returned issue IDs
  is the parity invariant.
* ``get_pull_requests`` — SET_EQUALITY on PR numbers, same reasoning.
* ``analyze_workflow_dependencies`` — SET_EQUALITY on the dependency
  names rendered under Upstream / Downstream / External sections.
* ``analyze_repository_structure`` — SET_EQUALITY on the top-level
  directory names rendered in the ``Top-level directories`` field.

Hermetic smoke + schema parity always run.
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
GITHUB_TOKEN_PRESENT = bool(os.environ.get("GITHUB_TOKEN", "").strip())

requires_live_servers = pytest.mark.skipif(
    not RUN_PARITY_FLAG,
    reason=(
        "live-server parity tests skipped — set RUN_PARITY=1 to "
        "enable (requires AWS credentials)"
    ),
)
requires_runtime_ids = pytest.mark.skipif(
    RUN_PARITY_FLAG
    and (not NODEJS_RUNTIME_ID or not PYTHON_RUNTIME_ID),
    reason=(
        "RUN_PARITY=1 is set but NODEJS_RUNTIME_ID / "
        "PYTHON_RUNTIME_ID are missing"
    ),
)
requires_github_token = pytest.mark.skipif(
    RUN_PARITY_FLAG and not GITHUB_TOKEN_PRESENT,
    reason=(
        "RUN_PARITY=1 is set but GITHUB_TOKEN is missing — both "
        "runtimes degrade without it, so live parity is uninformative"
    ),
)


# ── projection helpers ─────────────────────────────────────────────────


_ISSUE_NUMBER_RE = re.compile(r"^\*\*Number\*\*:\s*#(\d+)\s*$", re.MULTILINE)
_DASH_BULLET_RE = re.compile(r"^-\s+(.+?)\s*$")
_TOPLEVEL_RE = re.compile(
    r"^\*\*Top-level directories\*\*:\s*(.+?)\s*$", re.MULTILINE
)
_HEADING_RE_2 = re.compile(r"^##\s+(.+?)\s*$")
_DEP_BULLET_RE = re.compile(r"^-\s+(?:\*\*)?(.+?)(?:\*\*)?(?:\:.*)?\s*$")


def _extract_issue_numbers(raw: Any) -> list[str]:
    """Return all ``#N`` numbers from issue/PR rendering blocks."""
    text = _result_text(raw)
    return _ISSUE_NUMBER_RE.findall(text)


def _extract_pr_numbers(raw: Any) -> list[str]:
    """PR numbers use the same ``- **Number**: #N`` rendering shape."""
    return _extract_issue_numbers(raw)


def _extract_dependency_names(raw: Any) -> list[str]:
    """Pull dependency names from the Upstream / Downstream / External
    bullet lists rendered by ``analyze_workflow_dependencies``.

    Each section uses ``- name`` or ``- **path**: count`` shapes; we
    extract the leading slug or path token.
    """
    text = _result_text(raw)
    out: list[str] = []
    in_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            heading = stripped[3:].strip().lower()
            in_section = (
                "upstream" in heading
                or "downstream" in heading
                or "external" in heading
            )
            continue
        if not in_section:
            continue
        match = _DEP_BULLET_RE.match(stripped)
        if not match:
            continue
        token = match.group(1).strip()
        # Drop trailing description (e.g. "5 references") and bold marks
        token = token.split("**:")[0].strip("*").strip()
        if token and token != "No clear upstream dependencies found in search results":
            out.append(token)
    return out


def _extract_top_level_dirs(raw: Any) -> list[str]:
    """For ``analyze_repository_structure``: pull the directory names
    out of the ``**Top-level directories**: a, b, c`` line. Multiple
    repos in one response → flatten into one set."""
    text = _result_text(raw)
    out: list[str] = []
    for match in _TOPLEVEL_RE.finditer(text):
        names = [n.strip() for n in match.group(1).split(",")]
        out.extend(name for name in names if name)
    return out


# ── hermetic smoke tests ────────────────────────────────────────────────


def _make_mock_caller(table: dict[str, Any]) -> ToolCaller:
    """Build a ToolCaller keyed by tool name."""

    async def _call(tool_name: str, arguments: dict[str, Any]) -> Any:
        return table.get(tool_name)

    return _call


async def test_framework_passes_when_issue_numbers_match() -> None:
    body = (
        "# GitHub Issues for: \"x\"\n\n"
        "Found 2 issues:\n\n"
        "## 1. Bug A\n\n"
        "**Number**: #100\n\n"
        "## 2. Bug B\n\n"
        "**Number**: #101\n"
    )
    resp = {"content": [{"type": "text", "text": body}]}
    runner = ParityRunner(
        _make_mock_caller({"search_issues": resp}),
        _make_mock_caller({"search_issues": resp}),
    )
    result = await runner.assert_parity(
        "search_issues",
        {"query": "x"},
        comparison=ComparisonMode.SET_EQUALITY,
        name_extractor=_extract_issue_numbers,
    )
    assert result.passed, result.describe()


async def test_framework_detects_missing_issue_number() -> None:
    full = (
        "## 1. A\n\n**Number**: #100\n\n"
        "## 2. B\n\n**Number**: #101\n"
    )
    short = "## 1. A\n\n**Number**: #100\n"
    runner = ParityRunner(
        _make_mock_caller(
            {"search_issues": {"content": [{"type": "text", "text": full}]}}
        ),
        _make_mock_caller(
            {"search_issues": {"content": [{"type": "text", "text": short}]}}
        ),
    )
    result = await runner.assert_parity(
        "search_issues",
        {"query": "x"},
        comparison=ComparisonMode.SET_EQUALITY,
        name_extractor=_extract_issue_numbers,
    )
    assert not result.passed
    assert result.divergence is not None


def test_extractor_issue_numbers() -> None:
    raw = {
        "content": [
            {
                "type": "text",
                "text": (
                    "## 1. Title (PR)\n\n"
                    "**Number**: #42\n"
                    "## 2. Title\n\n"
                    "**Number**: #100\n"
                    "## 3. Other\n\n"
                    "**Number**: #999\n"
                ),
            }
        ]
    }
    assert _extract_issue_numbers(raw) == ["42", "100", "999"]


def test_extractor_top_level_dirs_flattens_multi_repo() -> None:
    raw = {
        "content": [
            {
                "type": "text",
                "text": (
                    "## global-workflow\n"
                    "**Top-level directories**: jobs, scripts, parm\n"
                    "## GSI\n"
                    "**Top-level directories**: src, scripts\n"
                ),
            }
        ]
    }
    assert sorted(set(_extract_top_level_dirs(raw))) == sorted(
        ["jobs", "scripts", "parm", "src"]
    )


def test_extractor_dependency_names() -> None:
    raw = {
        "content": [
            {
                "type": "text",
                "text": (
                    "# Dependency Analysis: FOO\n\n"
                    "## Upstream Dependencies\n\n"
                    "Components that FOO depends on:\n"
                    "- alpha\n"
                    "- beta\n\n"
                    "## Downstream Dependencies\n\n"
                    "- **scripts/x.sh**: 3 references\n"
                    "## Circular Dependency Check\n\n"
                    "(Manual review.)\n"
                    "## External Dependencies\n\n"
                    "- **GSI**: 5 references\n"
                ),
            }
        ]
    }
    deps = _extract_dependency_names(raw)
    assert "alpha" in deps
    assert "beta" in deps
    assert "scripts/x.sh" in deps
    assert "GSI" in deps


# ── schema parity ──────────────────────────────────────────────────────


def test_schema_parity_with_nodejs_source() -> None:
    """Python-registered schemas match the Node.js source 1:1."""
    import asyncio

    from fastmcp import FastMCP

    from src.tools import github_tools

    async def _run() -> None:
        mcp = FastMCP("parity-schema-check", version="1.0.0")
        github_tools.register(mcp, data=None, github_token="fake")
        tools = {
            t.name: t
            for t in await mcp.list_tools(run_middleware=False)
        }

        expected: dict[str, dict[str, Any]] = {
            "analyze_workflow_dependencies": {
                "params": {
                    "component",
                    "analysis_type",
                    "include_external",
                },
                "required": {"component"},
                "defaults": {
                    "analysis_type": "all",
                    "include_external": False,
                },
                "enums": {
                    "analysis_type": {
                        "upstream",
                        "downstream",
                        "circular",
                        "all",
                    },
                },
            },
            "search_issues": {
                "params": {"query", "repository", "state", "labels"},
                "required": {"query"},
                "defaults": {
                    "repository": "global-workflow",
                    "state": "open",
                },
                "enums": {
                    "state": {"open", "closed", "all"},
                },
            },
            "get_pull_requests": {
                "params": {"repository", "state", "limit"},
                "required": set(),
                "defaults": {
                    "repository": "global-workflow",
                    "state": "open",
                    "limit": 10,
                },
                "enums": {
                    "state": {"open", "closed", "all"},
                },
            },
            "analyze_repository_structure": {
                "params": {"repositories", "analysis_depth"},
                "required": set(),
                "defaults": {"analysis_depth": "shallow"},
                "enums": {
                    "analysis_depth": {"shallow", "deep"},
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
            or self.arguments.get("query")
            or self.arguments.get("component")
            or self.arguments.get("repository")
            or "default"
        )[:60]
        return f"{self.tool_name}::{short}"


# ``search_issues`` — SET_EQUALITY on issue numbers (top 20). Queries
# pick stable, well-known terms in NOAA-EMC/global-workflow so both
# runtimes return the same recent-by-update set.
SEARCH_CASES: list[ToolCase] = [
    ToolCase(
        "search_issues",
        {"query": "forecast", "state": "all"},
        ComparisonMode.SET_EQUALITY,
        _extract_issue_numbers,
        description="forecast-all",
    ),
    ToolCase(
        "search_issues",
        {"query": "build", "state": "open"},
        ComparisonMode.SET_EQUALITY,
        _extract_issue_numbers,
        description="build-open",
    ),
    ToolCase(
        "search_issues",
        {"query": "config", "state": "closed"},
        ComparisonMode.SET_EQUALITY,
        _extract_issue_numbers,
        description="config-closed",
    ),
    ToolCase(
        "search_issues",
        {
            "query": "rocoto",
            "labels": ["bug"],
            "state": "all",
        },
        ComparisonMode.SET_EQUALITY,
        _extract_issue_numbers,
        description="rocoto-bug-label",
    ),
    ToolCase(
        "search_issues",
        {"query": "wcoss2", "repository": "global-workflow"},
        ComparisonMode.SET_EQUALITY,
        _extract_issue_numbers,
        description="wcoss2-default-repo",
    ),
]

# ``get_pull_requests`` — SET_EQUALITY on PR numbers. The endpoint
# returns the most-recently-updated PRs sorted desc, capped at 50.
PR_CASES: list[ToolCase] = [
    ToolCase(
        "get_pull_requests",
        {},
        ComparisonMode.SET_EQUALITY,
        _extract_pr_numbers,
        description="default",
    ),
    ToolCase(
        "get_pull_requests",
        {"state": "closed", "limit": 5},
        ComparisonMode.SET_EQUALITY,
        _extract_pr_numbers,
        description="closed-5",
    ),
    ToolCase(
        "get_pull_requests",
        {"state": "all", "limit": 20},
        ComparisonMode.SET_EQUALITY,
        _extract_pr_numbers,
        description="all-20",
    ),
    ToolCase(
        "get_pull_requests",
        {"repository": "GSI"},
        ComparisonMode.SET_EQUALITY,
        _extract_pr_numbers,
        description="GSI-default",
    ),
    ToolCase(
        "get_pull_requests",
        {"repository": "UFS_UTILS", "state": "open", "limit": 10},
        ComparisonMode.SET_EQUALITY,
        _extract_pr_numbers,
        description="UFS_UTILS-open",
    ),
]

# ``analyze_workflow_dependencies`` — SET_EQUALITY on dependency
# names. Components selected from real global-workflow J-Jobs.
DEPS_CASES: list[ToolCase] = [
    ToolCase(
        "analyze_workflow_dependencies",
        {"component": "JGFS_FORECAST"},
        ComparisonMode.SET_EQUALITY,
        _extract_dependency_names,
        extractor_kind="name",
        description="jgfs-forecast",
    ),
    ToolCase(
        "analyze_workflow_dependencies",
        {"component": "JGDAS_ENKF_ANAL", "analysis_type": "upstream"},
        ComparisonMode.SET_EQUALITY,
        _extract_dependency_names,
        extractor_kind="name",
        description="enkf-anal-upstream",
    ),
    ToolCase(
        "analyze_workflow_dependencies",
        {"component": "exgfs_forecast.sh", "analysis_type": "downstream"},
        ComparisonMode.SET_EQUALITY,
        _extract_dependency_names,
        extractor_kind="name",
        description="exgfs-fcst-downstream",
    ),
    ToolCase(
        "analyze_workflow_dependencies",
        {"component": "config.fcst", "analysis_type": "all"},
        ComparisonMode.SET_EQUALITY,
        _extract_dependency_names,
        extractor_kind="name",
        description="config-fcst-all",
    ),
    ToolCase(
        "analyze_workflow_dependencies",
        {
            "component": "JGFS_ATMOS_POST",
            "include_external": True,
            "analysis_type": "all",
        },
        ComparisonMode.SET_EQUALITY,
        _extract_dependency_names,
        extractor_kind="name",
        description="atmos-post-include-external",
    ),
]

# ``analyze_repository_structure`` — SET_EQUALITY on top-level dirs.
STRUCT_CASES: list[ToolCase] = [
    ToolCase(
        "analyze_repository_structure",
        {},
        ComparisonMode.SET_EQUALITY,
        _extract_top_level_dirs,
        extractor_kind="name",
        description="default-trio",
    ),
    ToolCase(
        "analyze_repository_structure",
        {"repositories": ["global-workflow"]},
        ComparisonMode.SET_EQUALITY,
        _extract_top_level_dirs,
        extractor_kind="name",
        description="single-global-workflow",
    ),
    ToolCase(
        "analyze_repository_structure",
        {"repositories": ["GSI"], "analysis_depth": "deep"},
        ComparisonMode.SET_EQUALITY,
        _extract_top_level_dirs,
        extractor_kind="name",
        description="GSI-deep",
    ),
    ToolCase(
        "analyze_repository_structure",
        {"repositories": ["UFS_UTILS"], "analysis_depth": "shallow"},
        ComparisonMode.SET_EQUALITY,
        _extract_top_level_dirs,
        extractor_kind="name",
        description="UFS_UTILS-shallow",
    ),
    ToolCase(
        "analyze_repository_structure",
        {"repositories": ["global-workflow", "GSI"], "analysis_depth": "deep"},
        ComparisonMode.SET_EQUALITY,
        _extract_top_level_dirs,
        extractor_kind="name",
        description="multi-deep",
    ),
]


ALL_CASES: list[ToolCase] = (
    SEARCH_CASES + PR_CASES + DEPS_CASES + STRUCT_CASES
)


def _build_parity_case(case: ToolCase) -> ParityCase:
    kwargs: dict[str, Any] = {
        "tool_name": case.tool_name,
        "arguments": dict(case.arguments),
        "comparison": case.comparison,
        "module": "github_tools",
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
    """Require exactly 5 cases per tool and 20 cases total."""
    by_tool: dict[str, int] = {}
    for case in ALL_CASES:
        by_tool[case.tool_name] = by_tool.get(case.tool_name, 0) + 1
    expected_tools = {
        "search_issues",
        "get_pull_requests",
        "analyze_workflow_dependencies",
        "analyze_repository_structure",
    }
    assert set(by_tool) == expected_tools, (
        f"missing tool coverage: {expected_tools - set(by_tool)}"
    )
    for tool, count in by_tool.items():
        assert count == 5, f"{tool} has {count} cases; need exactly 5"
    assert len(ALL_CASES) == 20, (
        f"{len(ALL_CASES)} cases total; need exactly 20"
    )


# ── live parity tests ───────────────────────────────────────────────────


@pytest.fixture(scope="module")
def parity_runner() -> ParityRunner:
    if not RUN_PARITY_FLAG:
        pytest.skip("live parity disabled (RUN_PARITY not set)")
    if not NODEJS_RUNTIME_ID or not PYTHON_RUNTIME_ID:
        pytest.skip("runtime IDs not configured")
    if not GITHUB_TOKEN_PRESENT:
        pytest.skip(
            "GITHUB_TOKEN not set — both runtimes degrade without it"
        )
    node = AgentCoreToolCaller(NODEJS_RUNTIME_ID, region=AWS_REGION)
    python = AgentCoreToolCaller(PYTHON_RUNTIME_ID, region=AWS_REGION)
    return ParityRunner(node, python)


@requires_live_servers
@requires_runtime_ids
@requires_github_token
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
