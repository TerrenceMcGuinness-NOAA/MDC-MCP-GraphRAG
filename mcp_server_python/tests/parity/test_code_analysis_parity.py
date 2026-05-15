"""Parity tests for ``src.tools.code_analysis`` (Task 9.2, Phase B6).

Runs each of the 6 code-analysis tools against the Node.js production
AgentCore Runtime (``mdc_mcp_rag_server-TMXDllG2Wi``) and the Python
staging AgentCore Runtime (``mdc_mcp_rag_server_python-v5K2F8BGrN``)
and compares the results under the comparison modes appropriate for
each tool's response shape.

Live-server tests are gated behind the ``RUN_PARITY=1`` environment
variable so the default ``pytest`` run stays hermetic and does not
require AWS credentials. When ``RUN_PARITY=1`` is set the test suite
also expects ``NODEJS_RUNTIME_ID`` / ``PYTHON_RUNTIME_ID`` env vars
and valid AWS credentials for ``bedrock-agentcore:InvokeAgentRuntime``.

Test layout:

* A handful of *hermetic* smoke tests (catalogue coverage, schema
  parity assertion, comparison-framework sanity) always run. These
  validate that the parity-runner wiring is correct without touching
  a live server.
* The *live* parity cases (30 = 5 per tool × 6 tools) use the real
  ``AgentCoreToolCaller`` (lifted from the B5 module via direct
  import) and only run when ``RUN_PARITY=1``.

Example invocations::

    # Default hermetic run — a handful of assertions, no AWS calls
    pytest mcp_server_python/tests/parity/test_code_analysis_parity.py

    # Full parity against live runtimes
    RUN_PARITY=1 AWS_REGION=us-east-1 \
        NODEJS_RUNTIME_ID=arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/mdc_mcp_rag_server-TMXDllG2Wi \
        PYTHON_RUNTIME_ID=arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/mdc_mcp_rag_server_python-v5K2F8BGrN \
        pytest mcp_server_python/tests/parity/test_code_analysis_parity.py -v

The suite uses ``pytest.mark.parametrize`` so every query case shows
up as its own pytest node — a divergence in one case does not abort
the rest.
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

# Marker applied to every test in this module — makes ``pytest -m parity``
# / ``pytest -m "not parity"`` straightforward.
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
_BULLET_PATH_RE = re.compile(r"^-\s+`([^`]+)`")
_BULLET_BOLD_PATH_RE = re.compile(r"^-\s+\*\*`([^`]+)`\*\*")


def _extract_markdown_headings(raw: Any, level: int = 2) -> list[str]:
    """Return the heading texts at ``level`` from a markdown response."""
    marker = "#" * level
    text = _result_text(raw)
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(marker + " ") or stripped == marker:
            out.append(stripped)
    return out


def _count_section_entries(raw: Any, heading: str) -> int:
    """Count bulleted / numbered entries under the first ``heading`` section.

    Walks from the first heading that matches ``heading`` (any level)
    until the next heading of equal or higher level and counts lines
    that look like list entries (``- ...`` or ``N. ...``).
    """
    text = _result_text(raw)
    lines = text.splitlines()
    count = 0
    in_section = False
    section_level: int | None = None
    for line in lines:
        match = _HEADING_RE.match(line)
        if match:
            level = len(match.group(1))
            title = match.group(2)
            if heading.lower() in title.lower():
                in_section = True
                section_level = level
                continue
            # Leaving the section on any heading at same or higher level.
            if in_section and section_level is not None and level <= section_level:
                break
            continue
        if not in_section:
            continue
        stripped = line.strip()
        if stripped.startswith("- ") or re.match(r"^\d+\.\s", stripped):
            count += 1
    return count


def _extract_bulleted_paths(raw: Any) -> list[str]:
    """Extract backtick-wrapped paths from markdown list items.

    Accepts both ``- `x` `` and ``- **`x`** `` shapes — the Node.js
    code_analysis tools use the bold variant for heavy-traffic sections.
    """
    text = _result_text(raw)
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        match = _BULLET_BOLD_PATH_RE.match(stripped) or _BULLET_PATH_RE.match(
            stripped
        )
        if match:
            out.append(match.group(1))
    return out


def _extract_function_sequence(raw: Any) -> list[str]:
    r"""Extract the ordered list of function names from a call-chain tree.

    Matches lines like ``1. `foo` `` / ``  2. `bar` `` — strips
    indentation and the numeric prefix and returns just the names in
    traversal order. Used for ``trace_execution_path`` EXACT comparisons.
    """
    text = _result_text(raw)
    out: list[str] = []
    pat = re.compile(r"^\s*\d+\.\s+`([^`]+)`")
    for line in text.splitlines():
        match = pat.match(line)
        if match:
            out.append(match.group(1))
    return out


def _extract_chain_node_names(raw: Any) -> list[str]:
    """Extract node names from a trace_full_execution_chain tree.

    Matches tree lines regardless of indent / bullet characters by
    picking the first backtick-wrapped token on each line that follows
    the chain-tree formatting (``[Lang]`` tag optional).
    """
    text = _result_text(raw)
    out: list[str] = []
    pat = re.compile(r"`([^`]+)`")
    # Only walk the "Forward Direction" / "Reverse Direction" sections
    # so the extractor doesn't pick up the Statistics block.
    in_tree = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("### "):
            in_tree = "Direction" in stripped
            continue
        if not in_tree:
            continue
        match = pat.search(stripped)
        if match:
            out.append(match.group(1))
    return out


def _extract_script_paths(raw: Any) -> list[str]:
    """Extract script paths from a find_env_dependencies response.

    Picks up the `path` value from bulleted entries of the form
    ``- **`script`** - `path` ...`` so divergent script *names* but
    matching *paths* still compare equal.
    """
    text = _result_text(raw)
    out: list[str] = []
    pat = re.compile(
        r"^-\s+\*\*`[^`]+`\*\*\s+-\s+`([^`]+)`"
    )
    for line in text.splitlines():
        match = pat.match(line.strip())
        if match:
            out.append(match.group(1))
    return out


def _extract_caller_callee_union(raw: Any) -> list[str]:
    """Union of names in the Callers + Callees sections.

    Used by ``find_callers_callees`` under SET_EQUALITY — the Node.js
    and Python runtimes may sort each list differently but the union
    should match.
    """
    text = _result_text(raw)
    lines = text.splitlines()
    out: list[str] = []
    section: str | None = None
    pat = re.compile(r"^-\s+\*\*`([^`]+)`\*\*")
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## Callers"):
            section = "callers"
            continue
        if stripped.startswith("## Callees"):
            section = "callees"
            continue
        if stripped.startswith("## "):
            section = None
            continue
        if section is None:
            continue
        match = pat.match(stripped)
        if match:
            out.append(match.group(1))
    return out


def _extract_dependencies_entry_count(raw: Any) -> list[float]:
    """Return [bucket] — entry count of the Dependencies section.

    Packaged as a 1-element numeric list so TOLERANCE mode
    compares it with ±10%. Matches the task description's
    'Dependencies section entry count (TOLERANCE ±10%)' requirement
    for ``analyze_code_structure``.
    """
    return [float(_count_section_entries(raw, "Dependencies"))]


def _is_error_response(raw: Any) -> bool:
    text = _result_text(raw)
    return text.strip().startswith("[ERROR]")


# ── hermetic smoke tests ────────────────────────────────────────────────


def _make_mock_caller(
    table: dict[tuple[str, str], Any],
) -> ToolCaller:
    """Build a ToolCaller keyed by (tool_name, primary arg) for tight assertions."""

    async def _call(tool_name: str, arguments: dict[str, Any]) -> Any:
        key = (
            arguments.get("file_path")
            or arguments.get("target")
            or arguments.get("function_name")
            or arguments.get("start")
            or arguments.get("variable_name")
            or ""
        )
        return table.get((tool_name, key)) or table.get((tool_name, ""))

    return _call


async def test_framework_wires_against_mock_callers() -> None:
    """Sanity-check: the framework itself returns PASS/FAIL correctly.

    Without this baseline a green ``test_live_parity`` run could mean
    "runtimes agree" or "our comparison logic is broken".
    """
    shared_response = {
        "content": [
            {
                "type": "text",
                "text": (
                    "# Execution Path Trace: foo\n\n"
                    "*Entity type: Function*\n\n"
                    "## Call Chain (What foo calls)\n\n"
                    "Traced 3 function calls:\n\n"
                    "1. `alpha`\n"
                    "2. `beta`\n"
                    "3. `gamma`\n"
                ),
            }
        ]
    }
    node = _make_mock_caller({("trace_execution_path", "foo"): shared_response})
    python = _make_mock_caller({("trace_execution_path", "foo"): shared_response})

    runner = ParityRunner(node, python)
    result = await runner.assert_parity(
        "trace_execution_path",
        {"function_name": "foo"},
        comparison=ComparisonMode.EXACT,
        id_extractor=_extract_function_sequence,
    )
    assert result.passed, result.describe()
    assert result.nodejs_result == ["alpha", "beta", "gamma"]


async def test_framework_detects_sequence_divergence() -> None:
    """Confirms EXACT mode flags ordering differences (required for
    ``trace_execution_path`` where sequence is the parity key)."""
    node_resp = {
        "content": [
            {
                "type": "text",
                "text": (
                    "## Call Chain (What foo calls)\n\n"
                    "1. `a`\n2. `b`\n3. `c`\n"
                ),
            }
        ]
    }
    python_resp = {
        "content": [
            {
                "type": "text",
                "text": (
                    "## Call Chain (What foo calls)\n\n"
                    "1. `a`\n2. `c`\n3. `b`\n"
                ),
            }
        ]
    }
    runner = ParityRunner(
        _make_mock_caller({("trace_execution_path", "foo"): node_resp}),
        _make_mock_caller({("trace_execution_path", "foo"): python_resp}),
    )
    result = await runner.assert_parity(
        "trace_execution_path",
        {"function_name": "foo"},
        comparison=ComparisonMode.EXACT,
        id_extractor=_extract_function_sequence,
    )
    assert not result.passed
    assert "b" in (result.divergence or "") or "c" in (result.divergence or "")


async def test_bulleted_path_extractor_accepts_bold_variant() -> None:
    """``_extract_bulleted_paths`` handles both plain and bold-wrapped bullets."""
    text = (
        "## Upstream Dependencies\n\n"
        "- `os`\n"
        "- `pathlib`\n"
        "\n## Downstream\n\n"
        "- **`x.py`**\n"
        "- **`y.py`**\n"
    )
    raw = {"content": [{"type": "text", "text": text}]}
    assert set(_extract_bulleted_paths(raw)) == {
        "os",
        "pathlib",
        "x.py",
        "y.py",
    }


async def test_caller_callee_union_splits_on_section_headings() -> None:
    """``_extract_caller_callee_union`` respects ## section boundaries."""
    text = (
        "# Function Analysis: foo\n\n"
        "## Callers (2)\n\n"
        "- **`a`**\n"
        "- **`b`**\n\n"
        "## Callees\n\n"
        "- **`c`**\n"
        "- **`d`**\n\n"
        "## Complexity Analysis\n\n"
        "- **`ignored`**\n"
    )
    raw = {"content": [{"type": "text", "text": text}]}
    assert sorted(_extract_caller_callee_union(raw)) == ["a", "b", "c", "d"]


async def test_chain_node_extractor_ignores_statistics_section() -> None:
    """``_extract_chain_node_names`` only reads Direction subsections."""
    text = (
        "# Full Execution Chain: x\n\n"
        "### Forward Direction\n\n"
        "[Shell] `JGLOBAL_FORECAST` (SOURCES)\n"
        "  ├── [Fortran] `gsi` ═══ (EXECUTES)\n\n"
        "### Statistics\n"
        "- Languages: shell, fortran\n"
        "- Total nodes: `should_not_appear`\n"
    )
    raw = {"content": [{"type": "text", "text": text}]}
    names = _extract_chain_node_names(raw)
    assert "JGLOBAL_FORECAST" in names
    assert "gsi" in names
    assert "should_not_appear" not in names


async def test_section_entry_counter_respects_section_boundary() -> None:
    """``_count_section_entries`` stops counting at the next heading."""
    text = (
        "# Code Structure Analysis: x.py\n\n"
        "## Dependencies\n\n"
        "### Imports (3)\n"
        "- `a`\n- `b`\n- `c`\n\n"
        "### Imported By (2)\n"
        "- `d`\n- `e`\n\n"
        "## Related Queries\n"
        "- `ignored`\n"
    )
    raw = {"content": [{"type": "text", "text": text}]}
    assert _count_section_entries(raw, "Dependencies") == 5


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
            or (self.arguments.get("file_path") or "")
            or (self.arguments.get("target") or "")
            or (self.arguments.get("function_name") or "")
            or (self.arguments.get("start") or "")
            or (self.arguments.get("variable_name") or "")
            or "default"
        )[:60]
        return f"{self.tool_name}::{short}"


# analyze_code_structure — headings SET_EQUALITY + Dependencies entry count
# TOLERANCE.
ANALYZE_CASES: list[ToolCase] = [
    ToolCase(
        "analyze_code_structure",
        {"file_path": "scripts/exglobal_forecast.py"},
        ComparisonMode.SET_EQUALITY,
        lambda r: _extract_markdown_headings(r, 2),
        extractor_kind="name",
        description="exglobal-forecast-headings",
    ),
    ToolCase(
        "analyze_code_structure",
        {"file_path": "scripts/exglobal_forecast.py"},
        ComparisonMode.TOLERANCE,
        _extract_dependencies_entry_count,
        extractor_kind="score",
        description="exglobal-forecast-dep-count",
    ),
    ToolCase(
        "analyze_code_structure",
        {"file_path": "jobs/JGLOBAL_FORECAST"},
        ComparisonMode.SET_EQUALITY,
        lambda r: _extract_markdown_headings(r, 2),
        extractor_kind="name",
        description="jglobal-forecast",
    ),
    ToolCase(
        "analyze_code_structure",
        {
            "file_path": "ush/forecast_postdet.sh",
            "include_dependencies": False,
        },
        ComparisonMode.SET_EQUALITY,
        lambda r: _extract_markdown_headings(r, 2),
        extractor_kind="name",
        description="forecast-postdet-no-deps",
    ),
    ToolCase(
        "analyze_code_structure",
        {"file_path": "parm/config/gfs/config.base", "depth": 3},
        ComparisonMode.TOLERANCE,
        _extract_dependencies_entry_count,
        extractor_kind="score",
        description="config-base-dep-count",
    ),
]

# find_dependencies — bulleted path list SET_EQUALITY.
FIND_DEPS_CASES: list[ToolCase] = [
    ToolCase(
        "find_dependencies",
        {"target": "scripts/exglobal_forecast.py"},
        ComparisonMode.SET_EQUALITY,
        _extract_bulleted_paths,
        extractor_kind="name",
        description="exglobal-forecast",
    ),
    ToolCase(
        "find_dependencies",
        {"target": "jobs/JGLOBAL_FORECAST", "direction": "upstream"},
        ComparisonMode.SET_EQUALITY,
        _extract_bulleted_paths,
        extractor_kind="name",
        description="jglobal-upstream",
    ),
    ToolCase(
        "find_dependencies",
        {"target": "ush/forecast_postdet.sh", "direction": "downstream"},
        ComparisonMode.SET_EQUALITY,
        _extract_bulleted_paths,
        extractor_kind="name",
        description="forecast-postdet-downstream",
    ),
    ToolCase(
        "find_dependencies",
        {"target": "parm/config/gfs/config.base", "max_depth": 2},
        ComparisonMode.SET_EQUALITY,
        _extract_bulleted_paths,
        extractor_kind="name",
        description="config-base-depth-2",
    ),
    ToolCase(
        "find_dependencies",
        {"target": "scripts/exgfs_atmos_post.sh", "direction": "both", "max_depth": 4},
        ComparisonMode.SET_EQUALITY,
        _extract_bulleted_paths,
        extractor_kind="name",
        description="exgfs-atmos-post-both",
    ),
]

# trace_execution_path — function-name sequence EXACT.
TRACE_EXEC_CASES: list[ToolCase] = [
    ToolCase(
        "trace_execution_path",
        {"function_name": "forecast"},
        ComparisonMode.EXACT,
        _extract_function_sequence,
        description="forecast",
    ),
    ToolCase(
        "trace_execution_path",
        {"function_name": "gsi", "max_depth": 4},
        ComparisonMode.EXACT,
        _extract_function_sequence,
        description="gsi-depth-4",
    ),
    ToolCase(
        "trace_execution_path",
        {"function_name": "execute", "include_callers": True},
        ComparisonMode.EXACT,
        _extract_function_sequence,
        description="execute-with-callers",
    ),
    ToolCase(
        "trace_execution_path",
        {"function_name": "run_forecast", "max_depth": 2, "include_weights": False},
        ComparisonMode.EXACT,
        _extract_function_sequence,
        description="run-forecast-no-weights",
    ),
    ToolCase(
        "trace_execution_path",
        {
            "function_name": "main",
            "file_path": "scripts/exglobal_forecast.py",
            "max_depth": 3,
        },
        ComparisonMode.EXACT,
        _extract_function_sequence,
        description="main-scoped",
    ),
]

# find_callers_callees — union of callers + callees, SET_EQUALITY.
FIND_CC_CASES: list[ToolCase] = [
    ToolCase(
        "find_callers_callees",
        {"function_name": "forecast"},
        ComparisonMode.SET_EQUALITY,
        _extract_caller_callee_union,
        extractor_kind="name",
        description="forecast",
    ),
    ToolCase(
        "find_callers_callees",
        {"function_name": "write_restart"},
        ComparisonMode.SET_EQUALITY,
        _extract_caller_callee_union,
        extractor_kind="name",
        description="write-restart",
    ),
    ToolCase(
        "find_callers_callees",
        {"function_name": "exglobal_forecast.sh", "cross_language": True},
        ComparisonMode.SET_EQUALITY,
        _extract_caller_callee_union,
        extractor_kind="name",
        description="exglobal-cross-language",
    ),
    ToolCase(
        "find_callers_callees",
        {"function_name": "gsi", "cross_language": True},
        ComparisonMode.SET_EQUALITY,
        _extract_caller_callee_union,
        extractor_kind="name",
        description="gsi-cross-language",
    ),
    ToolCase(
        "find_callers_callees",
        {"function_name": "run_ufs", "include_source": False},
        ComparisonMode.SET_EQUALITY,
        _extract_caller_callee_union,
        extractor_kind="name",
        description="run-ufs",
    ),
]

# trace_full_execution_chain — node name list SET_EQUALITY.
TRACE_FULL_CASES: list[ToolCase] = [
    ToolCase(
        "trace_full_execution_chain",
        {"start": "JGLOBAL_FORECAST"},
        ComparisonMode.SET_EQUALITY,
        _extract_chain_node_names,
        extractor_kind="name",
        description="jglobal-forecast",
    ),
    ToolCase(
        "trace_full_execution_chain",
        {"start": "exglobal_forecast.sh", "direction": "forward"},
        ComparisonMode.SET_EQUALITY,
        _extract_chain_node_names,
        extractor_kind="name",
        description="exglobal-forward",
    ),
    ToolCase(
        "trace_full_execution_chain",
        {"start": "gsi", "direction": "reverse", "max_depth": 6},
        ComparisonMode.SET_EQUALITY,
        _extract_chain_node_names,
        extractor_kind="name",
        description="gsi-reverse",
    ),
    ToolCase(
        "trace_full_execution_chain",
        {
            "start": "JGLOBAL_FORECAST",
            "direction": "both",
            "languages": ["shell", "fortran"],
        },
        ComparisonMode.SET_EQUALITY,
        _extract_chain_node_names,
        extractor_kind="name",
        description="jglobal-filter-shell-fortran",
    ),
    ToolCase(
        "trace_full_execution_chain",
        {"start": "pygfs.task.gfs_forecast", "languages": ["python"]},
        ComparisonMode.SET_EQUALITY,
        _extract_chain_node_names,
        extractor_kind="name",
        description="pygfs-forecast-python-only",
    ),
]

# find_env_dependencies — list of script paths SET_EQUALITY.
FIND_ENV_CASES: list[ToolCase] = [
    ToolCase(
        "find_env_dependencies",
        {"variable_name": "HOMEgfs"},
        ComparisonMode.SET_EQUALITY,
        _extract_script_paths,
        extractor_kind="name",
        description="homegfs",
    ),
    ToolCase(
        "find_env_dependencies",
        {"variable_name": "DATAROOT"},
        ComparisonMode.SET_EQUALITY,
        _extract_script_paths,
        extractor_kind="name",
        description="dataroot",
    ),
    ToolCase(
        "find_env_dependencies",
        {"variable_name": "RUN", "show_exports": False},
        ComparisonMode.SET_EQUALITY,
        _extract_script_paths,
        extractor_kind="name",
        description="run-no-exports",
    ),
    ToolCase(
        "find_env_dependencies",
        {"variable_name": "CDATE", "limit": 25},
        ComparisonMode.SET_EQUALITY,
        _extract_script_paths,
        extractor_kind="name",
        description="cdate-limit-25",
    ),
    ToolCase(
        "find_env_dependencies",
        {"variable_name": "COMIN", "limit": 100},
        ComparisonMode.SET_EQUALITY,
        _extract_script_paths,
        extractor_kind="name",
        description="comin-limit-100",
    ),
]


ALL_CASES: list[ToolCase] = (
    ANALYZE_CASES
    + FIND_DEPS_CASES
    + TRACE_EXEC_CASES
    + FIND_CC_CASES
    + TRACE_FULL_CASES
    + FIND_ENV_CASES
)


def _build_parity_case(case: ToolCase) -> ParityCase:
    """Translate a ``ToolCase`` into the framework's :class:`ParityCase`."""
    kwargs: dict[str, Any] = {
        "tool_name": case.tool_name,
        "arguments": dict(case.arguments),
        "comparison": case.comparison,
        "module": "code_analysis",
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
    """Require at least 5 cases per tool and 30+ cases total."""
    by_tool: dict[str, int] = {}
    for case in ALL_CASES:
        by_tool[case.tool_name] = by_tool.get(case.tool_name, 0) + 1
    expected_tools = {
        "analyze_code_structure",
        "find_dependencies",
        "trace_execution_path",
        "find_callers_callees",
        "trace_full_execution_chain",
        "find_env_dependencies",
    }
    assert set(by_tool) == expected_tools, (
        f"missing tool coverage: {expected_tools - set(by_tool)}"
    )
    for tool, count in by_tool.items():
        assert count >= 5, f"{tool} has only {count} cases; need >= 5"
    assert len(ALL_CASES) >= 30, (
        f"{len(ALL_CASES)} cases total; need >= 30"
    )


def test_schema_parity_with_nodejs_source() -> None:
    """The Python registered schemas match the Node.js source 1:1.

    Drives parity against the authoritative ``CodeAnalysisTools.js``
    ``registerWith`` block without needing a live server. Verifies
    parameter names, required fields, defaults, and enum values for
    every tool — the unit-test suite adds the same assertion but
    scoping it here makes the parity contract explicit alongside the
    live-query catalogue.
    """
    import asyncio

    from fastmcp import FastMCP

    from src.tools import code_analysis

    async def _run() -> None:
        mcp = FastMCP("parity-schema-check", version="1.0.0")
        code_analysis.register(mcp, data=None)
        tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}

        expected: dict[str, dict[str, Any]] = {
            "analyze_code_structure": {
                "params": {
                    "file_path",
                    "include_dependencies",
                    "depth",
                    "token_budget",
                },
                "required": {"file_path"},
                "defaults": {
                    "include_dependencies": True,
                    "depth": 2,
                    "token_budget": 4000,
                },
            },
            "find_dependencies": {
                "params": {"target", "direction", "max_depth", "token_budget"},
                "required": {"target"},
                "defaults": {
                    "direction": "both",
                    "max_depth": 3,
                    "token_budget": 4000,
                },
                "enums": {
                    "direction": {"upstream", "downstream", "both"},
                },
            },
            "trace_execution_path": {
                "params": {
                    "function_name",
                    "file_path",
                    "max_depth",
                    "include_callers",
                    "include_weights",
                    "token_budget",
                },
                "required": {"function_name"},
                "defaults": {
                    "max_depth": 3,
                    "include_callers": False,
                    "include_weights": True,
                    "token_budget": 4000,
                },
            },
            "find_callers_callees": {
                "params": {
                    "function_name",
                    "file_path",
                    "include_source",
                    "token_budget",
                    "cross_language",
                },
                "required": {"function_name"},
                "defaults": {
                    "include_source": False,
                    "token_budget": 4000,
                    "cross_language": False,
                },
            },
            "trace_full_execution_chain": {
                "params": {"start", "direction", "max_depth", "languages"},
                "required": {"start"},
                "defaults": {"direction": "forward", "max_depth": 5},
                "enums": {
                    "direction": {"forward", "reverse", "both"},
                    "languages_items": {"shell", "fortran", "python"},
                },
            },
            "find_env_dependencies": {
                "params": {"variable_name", "show_exports", "limit", "token_budget"},
                "required": {"variable_name"},
                "defaults": {
                    "show_exports": True,
                    "limit": 50,
                    "token_budget": 4000,
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
                if enum_key.endswith("_items"):
                    real = enum_key.removesuffix("_items")
                    branches = props[real].get("anyOf") or [props[real]]
                    items_enum: set[str] = set()
                    for branch in branches:
                        items = branch.get("items") or {}
                        if "enum" in items:
                            items_enum.update(items["enum"])
                    assert items_enum == want, (
                        f"{tool_name}.{real} items enum {items_enum} != {want}"
                    )
                    continue
                enum_list = props[enum_key].get("enum")
                if enum_list is None:
                    for branch in props[enum_key].get("anyOf", []):
                        if "enum" in branch:
                            enum_list = branch["enum"]
                            break
                assert enum_list is not None, f"{tool_name}.{enum_key} no enum"
                assert set(enum_list) == want, (
                    f"{tool_name}.{enum_key} enum {set(enum_list)} != {want}"
                )

    asyncio.run(_run())


# ── live parity tests ───────────────────────────────────────────────────


@pytest.fixture(scope="module")
def parity_runner() -> ParityRunner:
    """Construct a ParityRunner wired to the live AgentCore runtimes."""
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
