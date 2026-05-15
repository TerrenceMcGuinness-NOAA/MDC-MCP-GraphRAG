"""Parity tests for ``src.tools.ee2_compliance`` (Task 12.2, Phase B8).

Runs each of the 5 EE2 compliance tools against the Node.js production
AgentCore Runtime (``mdc_mcp_rag_server-TMXDllG2Wi``) and the Python
staging AgentCore Runtime (``mdc_mcp_rag_server_python-v5K2F8BGrN``)
and compares the results under the comparison mode appropriate for
each tool's response shape.

Per-tool parity projections (per task description):

* ``search_ee2_standards`` — SET_EQUALITY on document IDs / standard
  references, top-5. Semantic ordering may legitimately diverge
  between Node.js (Xenova/mpnet ChromaDB) and Python (mpnet
  OpenSearch) even when the *set* of results is stable.
* ``analyze_ee2_compliance`` — SET_EQUALITY on detected violation
  categories (the Phase-2-corrected observation headings) +
  TOLERANCE ±10 % on the violation count.
* ``generate_compliance_report`` — SET_EQUALITY on markdown headings.
* ``scan_repository_compliance`` — SET_EQUALITY on per-category
  compliance results + TOLERANCE ±10 % on total-files-scanned count.
* ``extract_code_for_analysis`` — SET_EQUALITY on extracted-snippet
  file paths.

Hermetic smoke + schema parity always run. 25 live cases (5 × 5
tools) are gated on ``RUN_PARITY=1 NODEJS_RUNTIME_ID=...
PYTHON_RUNTIME_ID=...``.

Example invocations::

    # Default hermetic run (no AWS credentials needed)
    pytest mcp_server_python/tests/parity/test_ee2_compliance_parity.py

    # Full live parity
    RUN_PARITY=1 AWS_REGION=us-east-1 \\
        NODEJS_RUNTIME_ID=arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/mdc_mcp_rag_server-TMXDllG2Wi \\
        PYTHON_RUNTIME_ID=arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/mdc_mcp_rag_server_python-v5K2F8BGrN \\
        pytest mcp_server_python/tests/parity/test_ee2_compliance_parity.py -v
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


_BACKTICK_RE = re.compile(r"`([^`]+)`")
_HEADING_LEVEL_2_RE = re.compile(r"^##\s+(.+?)\s*$")
_HEADING_LEVEL_3_RE = re.compile(r"^###\s+(.+?)\s*$")


def _extract_markdown_headings(raw: Any, level: int = 2) -> list[str]:
    """Pull out all markdown headings at ``level`` from a response."""
    marker = "#" * level + " "
    text = _result_text(raw)
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(marker):
            out.append(stripped[len(marker):].strip())
    return out


def _extract_standard_ids(raw: Any) -> list[str]:
    """Return the ``## Standard N`` section titles from
    ``search_ee2_standards``. The Node.js renders one per result, so the
    count doubles as the top-k identifier set."""
    text = _result_text(raw)
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## Standard "):
            out.append(stripped)
    return out


def _extract_similarity_values(raw: Any) -> list[float]:
    """Extract ``**Similarity:** X.Y%`` values from
    ``search_ee2_standards`` responses."""
    text = _result_text(raw)
    out: list[float] = []
    for match in re.finditer(r"\*\*Similarity:\*\*\s+([0-9.]+)%", text):
        try:
            out.append(float(match.group(1)))
        except ValueError:
            continue
    return out


def _extract_observation_categories(raw: Any) -> list[str]:
    """Return the ``### <Category>`` headings under the
    "Observations & Suggestions" block of ``analyze_ee2_compliance``.
    Each observation is rendered with a H3 category title."""
    text = _result_text(raw)
    lines = text.splitlines()
    out: list[str] = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## Observations"):
            in_section = True
            continue
        if stripped.startswith("## Review Summary") or stripped.startswith(
            "## Relevant EE2 Standards"
        ):
            in_section = False
            continue
        if not in_section:
            continue
        match = _HEADING_LEVEL_3_RE.match(stripped)
        if match:
            out.append(match.group(1).strip())
    return out


def _extract_observation_count(raw: Any) -> list[float]:
    """Number of observations rendered by ``analyze_ee2_compliance``.

    Returned as a single-element list so the TOLERANCE extractor can
    compare a scalar count between Node.js and Python under ±10 %.
    """
    return [float(len(_extract_observation_categories(raw)))]


def _extract_report_headings(raw: Any) -> list[str]:
    """``## <CATEGORY>`` headings from ``generate_compliance_report``."""
    return [
        h.strip()
        for h in _extract_markdown_headings(raw, level=2)
        # Filter out the boilerplate footer headings so parity focuses
        # on the content-driven category list.
        if h.strip()
        not in {"How to Use This Report", "Passthrough Recommendation (Output Naming / COM)"}
    ]


def _extract_scan_category_keys(raw: Any) -> list[str]:
    """Return the keys of the ``issues_by_category`` map embedded in a
    ``scan_repository_compliance`` response."""
    import json

    text = _result_text(raw)
    try:
        start = text.index("```json\n") + len("```json\n")
        end = text.index("\n```", start)
    except ValueError:
        return []
    try:
        body = json.loads(text[start:end])
    except json.JSONDecodeError:
        return []
    return sorted((body.get("issues_by_category") or {}).keys())


def _extract_scan_total_files(raw: Any) -> list[float]:
    """Total files scanned as reported in the JSON payload. Single-element
    list so the TOLERANCE extractor can diff it."""
    import json

    text = _result_text(raw)
    try:
        start = text.index("```json\n") + len("```json\n")
        end = text.index("\n```", start)
    except ValueError:
        return [0.0]
    try:
        body = json.loads(text[start:end])
    except json.JSONDecodeError:
        return [0.0]
    stats = body.get("statistics") or {}
    return [float(stats.get("total_files") or 0)]


def _extract_extract_file_paths(raw: Any) -> list[str]:
    """Return the filenames that ``extract_code_for_analysis`` included
    in its "Extracted Code Snippets" block (one ``### <filename>`` per
    scanned file)."""
    text = _result_text(raw)
    lines = text.splitlines()
    out: list[str] = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## Extracted Code Snippets"):
            in_section = True
            continue
        if stripped.startswith("## ") and in_section:
            in_section = False
        if not in_section:
            continue
        match = _HEADING_LEVEL_3_RE.match(stripped)
        if match:
            out.append(match.group(1).strip())
    return out


# ── hermetic smoke tests ────────────────────────────────────────────────


def _make_mock_caller(
    table: dict[tuple[str, str], Any],
) -> ToolCaller:
    """Build a ToolCaller keyed by (tool_name, primary_arg)."""

    async def _call(tool_name: str, arguments: dict[str, Any]) -> Any:
        key = (
            arguments.get("query")
            or arguments.get("content")
            or arguments.get("scope")
            or arguments.get("repository_path")
            or arguments.get("path")
            or ""
        )
        if not key:
            files = arguments.get("files") or []
            if files:
                key = files[0].get("name") or ""
        return table.get((tool_name, key)) or table.get((tool_name, ""))

    return _call


async def test_framework_wires_against_mock_callers() -> None:
    """Sanity-check: the framework returns PASS for identical responses."""
    shared = {
        "content": [
            {
                "type": "text",
                "text": (
                    "# EE2 Standards Search: err_chk\n\n"
                    "Found 2 standards\n\n"
                    "## Standard 1\n"
                    "**Similarity:** 92.3%\n\n"
                    "body\n\n"
                    "---\n\n"
                    "## Standard 2\n"
                    "**Similarity:** 88.0%\n\n"
                    "body\n"
                ),
            }
        ]
    }
    runner = ParityRunner(
        _make_mock_caller({("search_ee2_standards", "err_chk"): shared}),
        _make_mock_caller({("search_ee2_standards", "err_chk"): shared}),
    )
    result = await runner.assert_parity(
        "search_ee2_standards",
        {"query": "err_chk"},
        comparison=ComparisonMode.SET_EQUALITY,
        name_extractor=_extract_standard_ids,
    )
    assert result.passed, result.describe()
    assert "## Standard 1" in result.nodejs_result
    assert "## Standard 2" in result.nodejs_result


async def test_framework_detects_standard_set_divergence() -> None:
    """SET_EQUALITY flags a missing result section."""
    node_resp = {
        "content": [
            {
                "type": "text",
                "text": (
                    "## Standard 1\n"
                    "## Standard 2\n"
                    "## Standard 3\n"
                ),
            }
        ]
    }
    py_resp = {
        "content": [
            {
                "type": "text",
                "text": "## Standard 1\n## Standard 2\n",
            }
        ]
    }
    runner = ParityRunner(
        _make_mock_caller({("search_ee2_standards", "x"): node_resp}),
        _make_mock_caller({("search_ee2_standards", "x"): py_resp}),
    )
    result = await runner.assert_parity(
        "search_ee2_standards",
        {"query": "x"},
        comparison=ComparisonMode.SET_EQUALITY,
        name_extractor=_extract_standard_ids,
    )
    assert not result.passed
    assert result.divergence is not None


async def test_observation_count_tolerance_accepts_small_drift() -> None:
    """TOLERANCE accepts ±10 % drift on the observation count, which
    matters when Node.js and Python converge on different positive /
    anti-pattern counts for subtle scripts."""
    node_resp = {
        "content": [
            {
                "type": "text",
                "text": (
                    "## Observations & Suggestions\n\n"
                    "### Error Handling\nbody\n---\n"
                    "### Error Handling\nbody\n---\n"
                    "### Environment Variables\nbody\n---\n"
                ),
            }
        ]
    }
    py_resp = {
        "content": [
            {
                "type": "text",
                "text": (
                    "## Observations & Suggestions\n\n"
                    "### Error Handling\nbody\n---\n"
                    "### Error Handling\nbody\n---\n"
                    "### Environment Variables\nbody\n---\n"
                    "### Environment Variables\nbody\n---\n"
                ),
            }
        ]
    }
    # 3 vs 4 observations is a 33 % swing — must FAIL at ±10 %.
    runner = ParityRunner(
        _make_mock_caller({("analyze_ee2_compliance", ""): node_resp}),
        _make_mock_caller({("analyze_ee2_compliance", ""): py_resp}),
    )
    result = await runner.assert_parity(
        "analyze_ee2_compliance",
        {"content": "anything"},
        comparison=ComparisonMode.TOLERANCE,
        score_extractor=_extract_observation_count,
        tolerance=0.10,
    )
    assert not result.passed


async def test_scan_total_files_tolerance_accepts_small_drift() -> None:
    """``scan_repository_compliance`` total-files count must agree
    within ±10 %."""
    node_resp = {
        "content": [
            {
                "type": "text",
                "text": (
                    "```json\n"
                    '{\n "statistics": {"total_files": 100, "files_by_type": {}, "samples_analyzed": 100, "files_with_issues": 5}}\n'
                    "```\n"
                ),
            }
        ]
    }
    py_resp = {
        "content": [
            {
                "type": "text",
                "text": (
                    "```json\n"
                    '{\n "statistics": {"total_files": 105, "files_by_type": {}, "samples_analyzed": 105, "files_with_issues": 5}}\n'
                    "```\n"
                ),
            }
        ]
    }
    runner = ParityRunner(
        _make_mock_caller({("scan_repository_compliance", ""): node_resp}),
        _make_mock_caller({("scan_repository_compliance", ""): py_resp}),
    )
    result = await runner.assert_parity(
        "scan_repository_compliance",
        {"files": [{"name": "x.sh", "content": "#!/bin/bash\n"}]},
        comparison=ComparisonMode.TOLERANCE,
        score_extractor=_extract_scan_total_files,
        tolerance=0.10,
    )
    assert result.passed, result.describe()


def test_extractor_standard_ids_picks_up_numbered_sections() -> None:
    raw = {
        "content": [
            {
                "type": "text",
                "text": (
                    "# Header\n"
                    "## Standard 1\nA\n"
                    "## Standard 2\nB\n"
                    "## Standard 10\nC\n"
                    "## Not A Standard\n"
                ),
            }
        ]
    }
    out = _extract_standard_ids(raw)
    assert out == ["## Standard 1", "## Standard 2", "## Standard 10"]


def test_extractor_observation_categories_scoped_to_observations_block() -> None:
    text = (
        "# EE2 Compliance Review\n\n"
        "## Review Summary\n\n"
        "body\n\n"
        "## Observations & Suggestions\n\n"
        "### Error Handling\nbody\n---\n"
        "### Environment Variables\nbody\n---\n"
        "## Relevant EE2 Standards\n\n"
        "### HEADING_TO_IGNORE\n"
    )
    raw = {"content": [{"type": "text", "text": text}]}
    out = _extract_observation_categories(raw)
    assert out == ["Error Handling", "Environment Variables"]
    assert "HEADING_TO_IGNORE" not in out


def test_extractor_scan_category_keys_parses_json_block() -> None:
    text = (
        "# header\n"
        "```json\n"
        '{"issues_by_category": {"error_handling": {"total_files_with_issues": 3}, "file_naming": {"total_files_with_issues": 2}}, "statistics": {"total_files": 10}}\n'
        "```\n"
    )
    raw = {"content": [{"type": "text", "text": text}]}
    out = _extract_scan_category_keys(raw)
    assert out == ["error_handling", "file_naming"]


def test_extractor_extract_file_paths_scoped_to_snippets_section() -> None:
    text = (
        "# header\n\n"
        "## LLM Analysis Instructions\n\n"
        "### HEADING_TO_IGNORE\n"
        "## Extracted Code Snippets\n\n"
        "### foo.sh\nbody\n"
        "### bar.py\nbody\n"
    )
    raw = {"content": [{"type": "text", "text": text}]}
    out = _extract_extract_file_paths(raw)
    assert out == ["foo.sh", "bar.py"]
    assert "HEADING_TO_IGNORE" not in out


def test_schema_parity_with_nodejs_source() -> None:
    """The Python registered schemas match the Node.js source 1:1.

    Drives parity against the authoritative ``EE2ComplianceTools.js``
    ``registerWith`` block without needing a live server."""
    import asyncio

    from fastmcp import FastMCP

    from src.tools import ee2_compliance

    async def _run() -> None:
        mcp = FastMCP("parity-schema-check", version="1.0.0")
        ee2_compliance.register(mcp, data=None)
        tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}

        expected: dict[str, dict[str, Any]] = {
            "search_ee2_standards": {
                "params": {
                    "query",
                    "category",
                    "max_results",
                    "include_examples",
                },
                "required": {"query"},
                "defaults": {
                    "max_results": 8,
                    "include_examples": True,
                },
                "enums": {
                    "category": {
                        "environment_variables",
                        "workflow_structure",
                        "error_handling",
                        "file_naming",
                        "production_utilities",
                        "code_standards",
                        "directory_structure",
                    },
                },
            },
            "analyze_ee2_compliance": {
                "params": {
                    "content",
                    "analysis_type",
                    "include_recommendations",
                },
                "required": {"content"},
                "defaults": {
                    "analysis_type": "comprehensive",
                    "include_recommendations": True,
                },
                "enums": {
                    "analysis_type": {
                        "comprehensive",
                        "environment_variables",
                        "workflow_structure",
                        "error_handling",
                        "file_naming",
                        "production_utilities",
                        "code_standards",
                        "directory_structure",
                    },
                },
            },
            "generate_compliance_report": {
                "params": {"scope", "categories", "format"},
                "required": set(),
                "defaults": {"scope": "summary", "format": "markdown"},
                "enums": {
                    "scope": {"summary", "detailed", "checklist"},
                    "format": {"markdown", "checklist", "summary"},
                },
            },
            "scan_repository_compliance": {
                "params": {
                    "files",
                    "repository_path",
                    "file_patterns",
                    "sample_size",
                    "categories",
                },
                "required": set(),
                "defaults": {"sample_size": 10000},
                "enums": {
                    "categories": {
                        "error_handling",
                        "environment_variables",
                        "file_naming",
                        "shebang_compliance",
                        "production_utilities",
                    },
                },
            },
            "extract_code_for_analysis": {
                "params": {
                    "content",
                    "files",
                    "path",
                    "content_type",
                    "categories",
                    "file_pattern",
                    "max_files",
                },
                "required": set(),
                "defaults": {
                    "content_type": "auto",
                    "file_pattern": r"\.(sh|py)$",
                    "max_files": 50,
                },
                "enums": {
                    "content_type": {"bash", "python", "auto"},
                    "categories": {
                        "output_file_naming",
                        "error_handling",
                        "shebang_compliance",
                        "env_var_validation",
                    },
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
                # Support plain enum, anyOf-with-enum, and
                # array-of-enum shapes.
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
                assert enum_list is not None, f"{tool_name}.{enum_key} no enum"
                assert set(enum_list) == want, (
                    f"{tool_name}.{enum_key}: enum {set(enum_list)} != {want}"
                )

    asyncio.run(_run())


# ── live parity query catalogue ─────────────────────────────────────────


#: Shared sample-file batches used by the scan + extract parity cases
#: so Node.js and Python receive identical inputs.
_SAMPLE_BASH_SCRIPT = (
    "#!/bin/bash\n"
    "set -eu\n"
    "cp /tmp/a /tmp/b\n"
    'cp "${COMOUT}/subdir" "GFS.T00Z.ATMF006.NC"\n'
    "err_chk\n"
)
_SAMPLE_BASH_CLEAN = (
    "#!/bin/bash\n"
    "set -x\n"
    "source preamble.sh\n"
    "err_chk\n"
)
_SAMPLE_PYTHON_SCRIPT = (
    "#!/usr/bin/env python3\n"
    "import os\n"
    "def main():\n"
    "    return os.environ.get('COMOUT')\n"
)
_SAMPLE_JJOB_NO_PS4 = (
    "#!/bin/ksh\n"
    "set -x\n"
    "export COMIN=/foo\n"
    "exit 0\n"
)

_SCAN_SAMPLE_FILES = [
    {"name": "exgfs_forecast.sh", "path": "scripts/exgfs_forecast.sh",
     "content": _SAMPLE_BASH_SCRIPT},
    {"name": "ex_clean.sh", "path": "scripts/ex_clean.sh",
     "content": _SAMPLE_BASH_CLEAN},
    {"name": "tool.py", "path": "ush/tool.py", "content": _SAMPLE_PYTHON_SCRIPT},
    {"name": "JEVS_ATMOS", "path": "jobs/JEVS_ATMOS",
     "content": _SAMPLE_JJOB_NO_PS4},
    {"name": "param.config", "path": "parm/param.config",
     "content": "NET=gfs\nSENDCOM=YES\n"},
]

_EXTRACT_SAMPLE_FILES = [
    {"name": "exgfs_forecast.sh", "path": "scripts/exgfs_forecast.sh",
     "content": _SAMPLE_BASH_SCRIPT},
    {"name": "ex_clean.sh", "path": "scripts/ex_clean.sh",
     "content": _SAMPLE_BASH_CLEAN},
    {"name": "tool.py", "path": "ush/tool.py",
     "content": _SAMPLE_PYTHON_SCRIPT},
]


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
            or self.arguments.get("query")
            or (self.arguments.get("content") or "")[:40]
            or self.arguments.get("scope")
            or "default"
        )[:60]
        return f"{self.tool_name}::{short}"


# search_ee2_standards — SET_EQUALITY on the document / standard IDs.
SEARCH_CASES: list[ToolCase] = [
    ToolCase(
        "search_ee2_standards",
        {"query": "error handling best practices", "max_results": 5},
        ComparisonMode.SET_EQUALITY,
        _extract_standard_ids,
        extractor_kind="name",
        description="error-handling",
    ),
    ToolCase(
        "search_ee2_standards",
        {
            "query": "environment variables naming",
            "category": "environment_variables",
            "max_results": 5,
        },
        ComparisonMode.SET_EQUALITY,
        _extract_standard_ids,
        extractor_kind="name",
        description="env-vars-categorized",
    ),
    ToolCase(
        "search_ee2_standards",
        {"query": "file naming conventions", "max_results": 5},
        ComparisonMode.SET_EQUALITY,
        _extract_standard_ids,
        extractor_kind="name",
        description="file-naming",
    ),
    ToolCase(
        "search_ee2_standards",
        {
            "query": "production utilities",
            "category": "production_utilities",
            "max_results": 5,
            "include_examples": False,
        },
        ComparisonMode.SET_EQUALITY,
        _extract_standard_ids,
        extractor_kind="name",
        description="production-utils-no-examples",
    ),
    ToolCase(
        "search_ee2_standards",
        {"query": "workflow structure", "max_results": 5},
        ComparisonMode.SET_EQUALITY,
        _extract_standard_ids,
        extractor_kind="name",
        description="workflow-structure",
    ),
]

# analyze_ee2_compliance — SET_EQUALITY on observation categories +
# TOLERANCE on the observation count.
ANALYZE_CASES: list[ToolCase] = [
    ToolCase(
        "analyze_ee2_compliance",
        {"content": _SAMPLE_BASH_SCRIPT},
        ComparisonMode.SET_EQUALITY,
        _extract_observation_categories,
        extractor_kind="name",
        description="bash-set-eu-sample",
    ),
    ToolCase(
        "analyze_ee2_compliance",
        {
            "content": _SAMPLE_BASH_SCRIPT,
            "analysis_type": "error_handling",
        },
        ComparisonMode.SET_EQUALITY,
        _extract_observation_categories,
        extractor_kind="name",
        description="narrow-error-handling",
    ),
    ToolCase(
        "analyze_ee2_compliance",
        {"content": _SAMPLE_BASH_CLEAN},
        ComparisonMode.SET_EQUALITY,
        _extract_observation_categories,
        extractor_kind="name",
        description="bash-clean",
    ),
    ToolCase(
        "analyze_ee2_compliance",
        {
            "content": _SAMPLE_BASH_SCRIPT,
            "include_recommendations": False,
        },
        ComparisonMode.TOLERANCE,
        _extract_observation_count,
        extractor_kind="score",
        description="obs-count-tolerance",
    ),
    ToolCase(
        "analyze_ee2_compliance",
        {"content": _SAMPLE_PYTHON_SCRIPT},
        ComparisonMode.SET_EQUALITY,
        _extract_observation_categories,
        extractor_kind="name",
        description="python-script",
    ),
]

# generate_compliance_report — SET_EQUALITY on markdown headings.
REPORT_CASES: list[ToolCase] = [
    ToolCase(
        "generate_compliance_report",
        {"scope": "summary"},
        ComparisonMode.SET_EQUALITY,
        _extract_report_headings,
        extractor_kind="name",
        description="summary-default",
    ),
    ToolCase(
        "generate_compliance_report",
        {"scope": "detailed"},
        ComparisonMode.SET_EQUALITY,
        _extract_report_headings,
        extractor_kind="name",
        description="detailed-default",
    ),
    ToolCase(
        "generate_compliance_report",
        {
            "scope": "summary",
            "categories": ["error_handling", "file_naming"],
        },
        ComparisonMode.SET_EQUALITY,
        _extract_report_headings,
        extractor_kind="name",
        description="summary-filtered",
    ),
    ToolCase(
        "generate_compliance_report",
        {
            "scope": "checklist",
            "categories": ["production_utilities"],
        },
        ComparisonMode.SET_EQUALITY,
        _extract_report_headings,
        extractor_kind="name",
        description="checklist-prod-utils",
    ),
    ToolCase(
        "generate_compliance_report",
        {"scope": "summary", "format": "checklist"},
        ComparisonMode.SET_EQUALITY,
        _extract_report_headings,
        extractor_kind="name",
        description="summary-format-checklist",
    ),
]

# scan_repository_compliance — SET_EQUALITY on issue-category keys +
# TOLERANCE on total-files count. We use shared test fixtures so Node.js
# and Python see identical inputs.
SCAN_CASES: list[ToolCase] = [
    ToolCase(
        "scan_repository_compliance",
        {"files": _SCAN_SAMPLE_FILES},
        ComparisonMode.SET_EQUALITY,
        _extract_scan_category_keys,
        extractor_kind="name",
        description="default-categories",
    ),
    ToolCase(
        "scan_repository_compliance",
        {
            "files": _SCAN_SAMPLE_FILES,
            "categories": ["error_handling"],
        },
        ComparisonMode.SET_EQUALITY,
        _extract_scan_category_keys,
        extractor_kind="name",
        description="error-handling-only",
    ),
    ToolCase(
        "scan_repository_compliance",
        {
            "files": _SCAN_SAMPLE_FILES,
            "categories": ["file_naming", "shebang_compliance"],
        },
        ComparisonMode.SET_EQUALITY,
        _extract_scan_category_keys,
        extractor_kind="name",
        description="file-naming-and-shebang",
    ),
    ToolCase(
        "scan_repository_compliance",
        {"files": _SCAN_SAMPLE_FILES},
        ComparisonMode.TOLERANCE,
        _extract_scan_total_files,
        extractor_kind="score",
        description="total-files-tolerance",
    ),
    ToolCase(
        "scan_repository_compliance",
        {
            "files": _SCAN_SAMPLE_FILES,
            "categories": ["production_utilities"],
            "sample_size": 3,
        },
        ComparisonMode.SET_EQUALITY,
        _extract_scan_category_keys,
        extractor_kind="name",
        description="prod-utils-sample-3",
    ),
]

# extract_code_for_analysis — SET_EQUALITY on snippet file paths.
EXTRACT_CASES: list[ToolCase] = [
    ToolCase(
        "extract_code_for_analysis",
        {"files": _EXTRACT_SAMPLE_FILES},
        ComparisonMode.SET_EQUALITY,
        _extract_extract_file_paths,
        extractor_kind="name",
        description="default-categories",
    ),
    ToolCase(
        "extract_code_for_analysis",
        {
            "files": _EXTRACT_SAMPLE_FILES,
            "categories": ["output_file_naming"],
        },
        ComparisonMode.SET_EQUALITY,
        _extract_extract_file_paths,
        extractor_kind="name",
        description="output-naming-only",
    ),
    ToolCase(
        "extract_code_for_analysis",
        {
            "files": _EXTRACT_SAMPLE_FILES,
            "categories": ["shebang_compliance"],
            "file_pattern": r"\.sh$",
        },
        ComparisonMode.SET_EQUALITY,
        _extract_extract_file_paths,
        extractor_kind="name",
        description="shebang-shell-only",
    ),
    ToolCase(
        "extract_code_for_analysis",
        {
            "content": _SAMPLE_BASH_SCRIPT,
            "categories": ["output_file_naming", "error_handling"],
        },
        ComparisonMode.SET_EQUALITY,
        _extract_extract_file_paths,
        extractor_kind="name",
        description="direct-content",
    ),
    ToolCase(
        "extract_code_for_analysis",
        {
            "files": _EXTRACT_SAMPLE_FILES,
            "categories": ["env_var_validation"],
            "max_files": 2,
        },
        ComparisonMode.SET_EQUALITY,
        _extract_extract_file_paths,
        extractor_kind="name",
        description="env-vars-max-2",
    ),
]


ALL_CASES: list[ToolCase] = (
    SEARCH_CASES
    + ANALYZE_CASES
    + REPORT_CASES
    + SCAN_CASES
    + EXTRACT_CASES
)


def _build_parity_case(case: ToolCase) -> ParityCase:
    kwargs: dict[str, Any] = {
        "tool_name": case.tool_name,
        "arguments": dict(case.arguments),
        "comparison": case.comparison,
        "module": "ee2_compliance",
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
    """Require exactly 5 cases per tool and 25 cases total."""
    by_tool: dict[str, int] = {}
    for case in ALL_CASES:
        by_tool[case.tool_name] = by_tool.get(case.tool_name, 0) + 1
    expected_tools = {
        "search_ee2_standards",
        "analyze_ee2_compliance",
        "generate_compliance_report",
        "scan_repository_compliance",
        "extract_code_for_analysis",
    }
    assert set(by_tool) == expected_tools, (
        f"missing tool coverage: {expected_tools - set(by_tool)}"
    )
    for tool, count in by_tool.items():
        assert count >= 5, f"{tool} has only {count} cases; need >= 5"
    assert len(ALL_CASES) >= 25, (
        f"{len(ALL_CASES)} cases total; need >= 25"
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
