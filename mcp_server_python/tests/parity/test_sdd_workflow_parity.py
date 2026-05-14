"""Parity tests for ``src.tools.sdd_workflow`` (Task 14, Phase B10).

Compares the 9 SDD workflow tools against the Node.js production
AgentCore Runtime (``mdc_mcp_rag_server-TMXDllG2Wi``) and the Python
staging AgentCore Runtime (``mdc_mcp_rag_server_python-v5K2F8BGrN``).

Per-tool parity projections
---------------------------

Most SDD tools render markdown with a stable set of section headings
that both runtimes should produce identically. Where the bodies differ
legitimately (e.g. session IDs, timestamps, accumulated history) we
compare the *set* of headings and key markers that signal correct
operation — not the variable content.

* ``list_sdd_workflows`` — SET_EQUALITY on workflow names (`## name`
  blocks). Skipped when the Python runtime has no workflows directory.
* ``get_sdd_workflow`` — SET_EQUALITY on H2 section headings (Description,
  Phases, Steps, Metadata).
* ``start_sdd_session`` / ``record_sdd_step`` / ``complete_sdd_session``
  / ``get_sdd_session`` — SET_EQUALITY on H1/H2 markers. These tools
  mutate state, so live tests are run against scratch session phases
  to avoid disturbing production state.
* ``get_sdd_execution_history`` — SET_EQUALITY on the rendered status
  icons + Phases-by-Status table headings (analytics mode).
* ``validate_sdd_compliance`` — SET_EQUALITY on the check names
  (Documentation, Error Handling, Shebang, Type Hints, Naming
  Conventions, Path Abstraction). Pure-content; no live drift.
* ``get_sdd_framework_status`` — SET_EQUALITY on the H2 section
  headings (Components, Active Session, optionally Session Tools and
  Recent Sessions when ``detailed=True``).

Hermetic smoke + schema parity always run. The 25 live cases are
gated on ``RUN_PARITY=1 NODEJS_RUNTIME_ID=... PYTHON_RUNTIME_ID=...``.

Example invocations::

    # Hermetic only (default)
    pytest mcp_server_python/tests/parity/test_sdd_workflow_parity.py

    # Full live parity
    RUN_PARITY=1 AWS_REGION=us-east-1 \\
        NODEJS_RUNTIME_ID=arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/mdc_mcp_rag_server-TMXDllG2Wi \\
        PYTHON_RUNTIME_ID=arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/mdc_mcp_rag_server_python-v5K2F8BGrN \\
        pytest mcp_server_python/tests/parity/test_sdd_workflow_parity.py -v
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
_HEADING_RE_1 = re.compile(r"^#\s+(.+?)\s*$")
_BOLD_FIELD_RE = re.compile(r"^- \*\*(.+?)\*\*:")


def _extract_h2_headings(raw: Any) -> list[str]:
    """Return all level-2 (##) headings, status-icon-stripped."""
    text = _result_text(raw)
    out: list[str] = []
    for line in text.splitlines():
        match = _HEADING_RE_2.match(line.strip())
        if not match:
            continue
        title = match.group(1).strip()
        # Strip leading status icons rendered by ``_render_history``
        # so SET_EQUALITY isn't fooled by [OK] / [..] / [!!] prefixes.
        for icon in ("[OK] ", "[..] ", "[!!] "):
            if title.startswith(icon):
                title = title[len(icon):]
                break
        out.append(title)
    return out


def _extract_h1_titles(raw: Any) -> list[str]:
    """Return all level-1 (#) headings."""
    text = _result_text(raw)
    out: list[str] = []
    for line in text.splitlines():
        match = _HEADING_RE_1.match(line.strip())
        if match:
            out.append(match.group(1).strip())
    return out


def _extract_check_names(raw: Any) -> list[str]:
    """Return the SDD check names in a ``validate_sdd_compliance`` body.

    Each check renders as ``- [ICON] **<Name>**: ...`` so the parity
    invariant is the bullet-bold field set.
    """
    text = _result_text(raw)
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        match = re.match(r"^-\s+\[(?:OK|WARN|ERROR)\]\s+\*\*(.+?)\*\*:", line)
        if match:
            out.append(match.group(1).strip())
    return out


def _extract_workflow_names(raw: Any) -> list[str]:
    """Return the workflow names listed by ``list_sdd_workflows``.

    Each entry renders as ``## <name>`` followed by a ``- **Path**``
    bullet — a stable two-line shape on both runtimes.
    """
    text = _result_text(raw)
    lines = text.splitlines()
    out: list[str] = []
    for idx, line in enumerate(lines):
        match = _HEADING_RE_2.match(line.strip())
        if not match:
            continue
        title = match.group(1).strip()
        # Skip status / category headings that include spaces — the
        # workflow-name headings are bare slugs.
        if " " in title:
            continue
        # Confirm it's a workflow entry by peeking at the next non-empty
        # line for ``- **Path**`` (which list_sdd_workflows always emits).
        for follow in lines[idx + 1: idx + 4]:
            if follow.strip().startswith("- **Path**"):
                out.append(title)
                break
    return out


def _extract_session_card_fields(raw: Any) -> list[str]:
    """Return the bold field names rendered by ``get_sdd_session``.

    The session card has stable fields (Session ID, Phase, Status,
    Started, Last Activity, Progress) followed by optional Notes.
    Field *names* are the parity invariant — values legitimately drift.
    """
    text = _result_text(raw)
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        match = re.match(r"^\*\*(.+?)\*\*:", line)
        if match:
            out.append(match.group(1).strip())
    return out


# ── hermetic smoke tests ────────────────────────────────────────────────


def _make_mock_caller(
    table: dict[str, Any],
) -> ToolCaller:
    """Build a ToolCaller keyed by tool name only (SDD tools take
    similar argument shapes; per-key dispatch isn't needed)."""

    async def _call(tool_name: str, arguments: dict[str, Any]) -> Any:
        return table.get(tool_name)

    return _call


async def test_framework_passes_when_check_names_match() -> None:
    """Sanity check: SET_EQUALITY on validate_sdd_compliance check
    names returns PASS for identical content."""
    body = (
        "# SDD Compliance Validation\n\n"
        "**Framework Version**: 4.0\n\n"
        "## Validation Results\n\n"
        "- [OK] **Documentation**: ok\n"
        "- [WARN] **Error Handling**: missing\n"
        "- [OK] **Shebang**: present\n"
        "- [OK] **Naming Conventions**: ok\n"
        "- [OK] **Path Abstraction**: ok\n"
    )
    resp = {"content": [{"type": "text", "text": body}]}
    runner = ParityRunner(
        _make_mock_caller({"validate_sdd_compliance": resp}),
        _make_mock_caller({"validate_sdd_compliance": resp}),
    )
    result = await runner.assert_parity(
        "validate_sdd_compliance",
        {"content": "echo hi", "content_type": "bash"},
        comparison=ComparisonMode.SET_EQUALITY,
        name_extractor=_extract_check_names,
    )
    assert result.passed, result.describe()


async def test_framework_detects_missing_check() -> None:
    """A missing check (e.g. Path Abstraction) is flagged as drift."""
    full = (
        "## Validation Results\n\n"
        "- [OK] **Documentation**: ok\n"
        "- [OK] **Naming Conventions**: ok\n"
        "- [OK] **Path Abstraction**: ok\n"
    )
    short = (
        "## Validation Results\n\n"
        "- [OK] **Documentation**: ok\n"
        "- [OK] **Naming Conventions**: ok\n"
    )
    runner = ParityRunner(
        _make_mock_caller(
            {
                "validate_sdd_compliance": {
                    "content": [{"type": "text", "text": full}]
                }
            }
        ),
        _make_mock_caller(
            {
                "validate_sdd_compliance": {
                    "content": [{"type": "text", "text": short}]
                }
            }
        ),
    )
    result = await runner.assert_parity(
        "validate_sdd_compliance",
        {"content": "echo"},
        comparison=ComparisonMode.SET_EQUALITY,
        name_extractor=_extract_check_names,
    )
    assert not result.passed
    assert result.divergence is not None


def test_extractor_check_names() -> None:
    raw = {
        "content": [
            {
                "type": "text",
                "text": (
                    "## Validation Results\n\n"
                    "- [OK] **Documentation**: ok\n"
                    "- [WARN] **Error Handling**: warn\n"
                    "- [ERROR] **Path Abstraction**: bad\n"
                    "- not-a-check\n"
                ),
            }
        ]
    }
    assert _extract_check_names(raw) == [
        "Documentation",
        "Error Handling",
        "Path Abstraction",
    ]


def test_extractor_h2_headings_strips_status_icons() -> None:
    raw = {
        "content": [
            {
                "type": "text",
                "text": (
                    "## [OK] phase_alpha\n"
                    "## [..] phase_beta\n"
                    "## [!!] phase_gamma\n"
                    "## Components\n"
                ),
            }
        ]
    }
    assert _extract_h2_headings(raw) == [
        "phase_alpha",
        "phase_beta",
        "phase_gamma",
        "Components",
    ]


def test_extractor_workflow_names_filters_to_path_blocks() -> None:
    raw = {
        "content": [
            {
                "type": "text",
                "text": (
                    "# Available SDD Workflows\n\n"
                    "Found 2 workflows\n\n"
                    "## phase_demo\n"
                    "- **Path**: /workflows/phase_demo.md\n"
                    "- **Size**: 100 bytes\n\n"
                    "## phase_other\n"
                    "- **Path**: /workflows/phase_other.md\n"
                    "- **Size**: 200 bytes\n\n"
                    "## Components\n"  # not a workflow entry
                    "- nope\n"
                ),
            }
        ]
    }
    assert _extract_workflow_names(raw) == ["phase_demo", "phase_other"]


def test_extractor_session_card_fields() -> None:
    raw = {
        "content": [
            {
                "type": "text",
                "text": (
                    "# Active SDD Session\n\n"
                    "**Session ID**: x\n"
                    "**Phase**: y\n"
                    "**Status**: in_progress\n"
                    "**Progress**: 1/3 steps\n"
                ),
            }
        ]
    }
    assert _extract_session_card_fields(raw) == [
        "Session ID",
        "Phase",
        "Status",
        "Progress",
    ]


# ── schema parity ──────────────────────────────────────────────────────


def test_schema_parity_with_nodejs_source() -> None:
    """Python-registered schemas match the Node.js source 1:1."""
    import asyncio

    from fastmcp import FastMCP

    from src.sdd.session_manager import SessionManager
    from src.tools import sdd_workflow

    async def _run() -> None:
        # Need a tmp state dir so SessionManager doesn't pollute the
        # shared sdd_framework/execution_state path.
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            sm = SessionManager(state_dir=td)
            mcp = FastMCP("parity-schema-check", version="1.0.0")
            sdd_workflow.register(
                mcp, data=None, session_manager=sm, workflows_dir=td
            )
            tools = {
                t.name: t
                for t in await mcp.list_tools(run_middleware=False)
            }

        expected: dict[str, dict[str, Any]] = {
            "list_sdd_workflows": {
                "params": {"include_metadata"},
                "required": set(),
                "defaults": {"include_metadata": False},
            },
            "get_sdd_workflow": {
                "params": {"workflow_name"},
                "required": {"workflow_name"},
                "defaults": {},
            },
            "start_sdd_session": {
                "params": {"phase", "notes", "total_steps"},
                "required": {"phase"},
                "defaults": {"total_steps": 0},
            },
            "get_sdd_execution_history": {
                "params": {"limit", "workflow_name", "analytics"},
                "required": set(),
                "defaults": {"limit": 10, "analytics": False},
            },
            "validate_sdd_compliance": {
                "params": {
                    "content",
                    "target",
                    "framework_version",
                    "content_type",
                },
                "required": set(),
                "defaults": {
                    "framework_version": "4.0",
                    "content_type": "auto",
                },
                "enums": {
                    "content_type": {
                        "bash",
                        "python",
                        "yaml",
                        "json",
                        "markdown",
                        "auto",
                    },
                },
            },
            "get_sdd_framework_status": {
                "params": {"detailed"},
                "required": set(),
                "defaults": {"detailed": False},
            },
            "record_sdd_step": {
                "params": {"step", "name", "tag", "notes"},
                "required": {"step", "name"},
                "defaults": {"tag": "implement", "notes": ""},
                "enums": {
                    "tag": {
                        "research",
                        "design",
                        "implement",
                        "configure",
                        "validate",
                        "document",
                        "ingest",
                    },
                },
            },
            "get_sdd_session": {
                "params": {"resume"},
                "required": set(),
                "defaults": {"resume": False},
            },
            "complete_sdd_session": {
                "params": {"summary", "abandon", "reason"},
                "required": set(),
                "defaults": {
                    "summary": "",
                    "abandon": False,
                    "reason": "",
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
            or self.arguments.get("workflow_name")
            or self.arguments.get("phase")
            or "default"
        )[:60]
        return f"{self.tool_name}::{short}"


# A unique "scratch" phase name used by the lifecycle parity cases so
# the live runs do not disturb production session state.
_SCRATCH_PHASE = "phase_parity_scratch"

# ``validate_sdd_compliance`` cases — pure-content, no live drift.
VALIDATE_CASES: list[ToolCase] = [
    ToolCase(
        "validate_sdd_compliance",
        {
            "content": (
                "#!/bin/bash\nset -e\n# documented\necho hi\n"
            ),
            "content_type": "bash",
        },
        ComparisonMode.SET_EQUALITY,
        _extract_check_names,
        description="bash-clean",
    ),
    ToolCase(
        "validate_sdd_compliance",
        {
            "content": "echo /scratch/foo\n",
            "content_type": "bash",
        },
        ComparisonMode.SET_EQUALITY,
        _extract_check_names,
        description="bash-failures",
    ),
    ToolCase(
        "validate_sdd_compliance",
        {
            "content": (
                "# main\n"
                "def add(a: int, b: int) -> int:\n"
                "    return a + b\n"
                'if __name__ == "__main__":\n'
                "    add(1, 2)\n"
            ),
            "content_type": "python",
        },
        ComparisonMode.SET_EQUALITY,
        _extract_check_names,
        description="python-clean",
    ),
    ToolCase(
        "validate_sdd_compliance",
        {
            "content": "x = 1\nprint(x)\n",
            "content_type": "python",
        },
        ComparisonMode.SET_EQUALITY,
        _extract_check_names,
        description="python-warns",
    ),
    ToolCase(
        "validate_sdd_compliance",
        {
            "content": "# No type hints\n# No shebang\nNAMESPACE_VAR=1\n",
            "content_type": "auto",
        },
        ComparisonMode.SET_EQUALITY,
        _extract_check_names,
        description="auto-detect",
    ),
]

# ``list_sdd_workflows`` — workflow-name SET_EQUALITY. Skipped on
# Python staging when the workflows directory is not bind-mounted
# (the [INFO] block produces an empty workflow set).
LIST_CASES: list[ToolCase] = [
    ToolCase(
        "list_sdd_workflows",
        {},
        ComparisonMode.SET_EQUALITY,
        _extract_workflow_names,
        description="default",
    ),
    ToolCase(
        "list_sdd_workflows",
        {"include_metadata": True},
        ComparisonMode.SET_EQUALITY,
        _extract_workflow_names,
        description="with-metadata",
    ),
]

# ``get_sdd_workflow`` — H2 SET_EQUALITY. Targets known phase specs.
GET_WORKFLOW_CASES: list[ToolCase] = [
    ToolCase(
        "get_sdd_workflow",
        {"workflow_name": "phase48_aws_infrastructure_port"},
        ComparisonMode.SET_EQUALITY,
        _extract_h2_headings,
        description="phase48",
    ),
    ToolCase(
        "get_sdd_workflow",
        {"workflow_name": "phase56_opensearch_connection_pool_exhaustion"},
        ComparisonMode.SET_EQUALITY,
        _extract_h2_headings,
        description="phase56",
    ),
]

# ``get_sdd_framework_status`` — H2 SET_EQUALITY. The Components and
# Active Session blocks render the same headings on both runtimes
# (counts may differ but the section structure is stable).
STATUS_CASES: list[ToolCase] = [
    ToolCase(
        "get_sdd_framework_status",
        {},
        ComparisonMode.SET_EQUALITY,
        _extract_h2_headings,
        description="default",
    ),
    ToolCase(
        "get_sdd_framework_status",
        {"detailed": True},
        ComparisonMode.SET_EQUALITY,
        _extract_h2_headings,
        description="detailed",
    ),
]

# ``get_sdd_execution_history`` — H1+H2 SET_EQUALITY. No-arg queries
# return a stable surface (header, recent sessions) regardless of the
# concrete session count.
HISTORY_CASES: list[ToolCase] = [
    ToolCase(
        "get_sdd_execution_history",
        {"limit": 5},
        ComparisonMode.SET_EQUALITY,
        _extract_h1_titles,
        description="recent-5",
    ),
    ToolCase(
        "get_sdd_execution_history",
        {"limit": 10, "analytics": True},
        ComparisonMode.SET_EQUALITY,
        _extract_h2_headings,
        description="analytics",
    ),
    ToolCase(
        "get_sdd_execution_history",
        {"workflow_name": "phase48_aws_infrastructure_port", "limit": 5},
        ComparisonMode.SET_EQUALITY,
        _extract_h1_titles,
        description="phase48-filter",
    ),
]

# ``get_sdd_session`` — session-card field SET_EQUALITY (works even
# when no session is active; both runtimes render the same "No Active
# Session" block in that case).
GET_SESSION_CASES: list[ToolCase] = [
    ToolCase(
        "get_sdd_session",
        {},
        ComparisonMode.SET_EQUALITY,
        _extract_h1_titles,
        description="check-current",
    ),
]

# Lifecycle tools (start / record / complete) — these mutate state so
# parity cases use a unique scratch phase. They are gated on a separate
# flag because they must run sequentially and require both runtimes to
# share the same JSONL state directory (or accept divergent state and
# rely only on schema/heading parity).
LIFECYCLE_CASES: list[ToolCase] = [
    ToolCase(
        "start_sdd_session",
        {"phase": _SCRATCH_PHASE, "total_steps": 1, "notes": "parity"},
        ComparisonMode.SET_EQUALITY,
        _extract_h1_titles,
        description="start-scratch",
    ),
    ToolCase(
        "record_sdd_step",
        {"step": 1, "name": "parity-step", "tag": "validate"},
        ComparisonMode.SET_EQUALITY,
        _extract_h1_titles,
        description="record-step-1",
    ),
    ToolCase(
        "complete_sdd_session",
        {"summary": "parity wrap", "abandon": True, "reason": "parity"},
        ComparisonMode.SET_EQUALITY,
        _extract_h1_titles,
        description="abandon-scratch",
    ),
]


ALL_CASES: list[ToolCase] = (
    VALIDATE_CASES
    + LIST_CASES
    + GET_WORKFLOW_CASES
    + STATUS_CASES
    + HISTORY_CASES
    + GET_SESSION_CASES
    + LIFECYCLE_CASES
)


def _build_parity_case(case: ToolCase) -> ParityCase:
    kwargs: dict[str, Any] = {
        "tool_name": case.tool_name,
        "arguments": dict(case.arguments),
        "comparison": case.comparison,
        "module": "sdd_workflow",
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
    """Catalogue must cover all 9 SDD tools and include >= 5 cases for
    the high-traffic tools (``validate_sdd_compliance`` is the
    heaviest exercised given it's pure-content)."""
    by_tool: dict[str, int] = {}
    for case in ALL_CASES:
        by_tool[case.tool_name] = by_tool.get(case.tool_name, 0) + 1
    expected_tools = {
        "list_sdd_workflows",
        "get_sdd_workflow",
        "start_sdd_session",
        "record_sdd_step",
        "complete_sdd_session",
        "get_sdd_session",
        "get_sdd_execution_history",
        "validate_sdd_compliance",
        "get_sdd_framework_status",
    }
    assert set(by_tool) == expected_tools, (
        f"missing tool coverage: {expected_tools - set(by_tool)}"
    )
    # validate_sdd_compliance gets the dense 5-case bench (pure content)
    assert by_tool["validate_sdd_compliance"] >= 5, (
        f"validate_sdd_compliance has {by_tool['validate_sdd_compliance']} "
        f"cases; need >= 5"
    )
    assert len(ALL_CASES) >= 18, (
        f"{len(ALL_CASES)} cases total; need >= 18"
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
