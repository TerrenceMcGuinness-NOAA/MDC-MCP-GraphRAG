"""Unit tests for :mod:`src.tools.ee2_compliance` (Task 12.3, Phase B8).

Covers tool-schema parity with Node.js (parameter names, defaults,
required flags, enum values); degraded-mode behaviour (1 vector-backed
tool returns ``[ERROR]`` when ``data`` is missing + 4 content-
scanning tools work without ``data``); the Phase 2 SME-corrected
analysis logic (``set -eu`` flagged as anti-pattern, ``err_chk`` /
``preamble.sh`` as positive, file ops without ``err_chk`` flagged);
scan-tool category filtering and content-abstraction gates; extract-
tool category filtering, file_pattern regex, content-type detection,
max_files clamp; search_ee2_standards max_results clamping.

No live AWS calls — ``MockUnifiedDataAccess`` stands in for the
data-access layer and the scan / extract tool paths are pure Python
content operations.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastmcp import FastMCP

from src.tools import ee2_compliance
from tests.conftest import MockUnifiedDataAccess

pytestmark = pytest.mark.unit


# ── helpers ────────────────────────────────────────────────────────────


def _make_server(*, data: Any = None) -> FastMCP:
    mcp = FastMCP("mdc-mcp-rag-test", version="1.0.0")
    ee2_compliance.register(mcp, data=data)
    return mcp


async def _call_tool(
    mcp: FastMCP, name: str, arguments: dict[str, Any]
) -> str:
    tool = await mcp.get_tool(name)
    result = await tool.run(arguments)
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text is not None:
            return text
    return str(result)


def _enum_of(schema: dict[str, Any]) -> set[str]:
    """Extract the enum set from either a plain ``enum`` schema or
    one wrapped in ``anyOf`` (the shape FastMCP emits for
    ``Literal[...] | None = None``)."""
    enum = schema.get("enum")
    if enum is None:
        for branch in schema.get("anyOf") or []:
            if "enum" in branch:
                enum = branch["enum"]
                break
    if enum is None:
        # Array-of-enum shape (``list[Literal[...]] | None = None``).
        items = schema.get("items") or {}
        enum = items.get("enum")
        if enum is None:
            for branch in schema.get("anyOf") or []:
                items = branch.get("items") or {}
                if "enum" in items:
                    enum = items["enum"]
                    break
    return set(enum or [])


# ── registration parity ───────────────────────────────────────────────


async def test_register_exposes_five_tools_with_matching_names() -> None:
    mcp = _make_server()
    tools = await mcp.list_tools(run_middleware=False)
    names = sorted(t.name for t in tools)
    assert names == sorted(
        [
            "search_ee2_standards",
            "analyze_ee2_compliance",
            "generate_compliance_report",
            "scan_repository_compliance",
            "extract_code_for_analysis",
        ]
    )


async def test_tool_schemas_match_nodejs_parameter_names() -> None:
    mcp = _make_server()
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    expected = {
        "search_ee2_standards": {
            "query",
            "category",
            "max_results",
            "include_examples", "tenant_id"},
        "analyze_ee2_compliance": {
            "content",
            "analysis_type",
            "include_recommendations",
        },
        "generate_compliance_report": {"scope", "categories", "format"},
        "scan_repository_compliance": {
            "files",
            "repository_path",
            "file_patterns",
            "sample_size",
            "categories",
        },
        "extract_code_for_analysis": {
            "content",
            "files",
            "path",
            "content_type",
            "categories",
            "file_pattern",
            "max_files",
        },
    }
    for name, params in expected.items():
        props = set(
            tools[name].parameters.get("properties", {}).keys()
        )
        assert props == params, (
            f"{name}: expected {params}, got {props}"
        )


async def test_required_fields_match_nodejs() -> None:
    mcp = _make_server()
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    required = {
        "search_ee2_standards": {"query"},
        "analyze_ee2_compliance": {"content"},
        "generate_compliance_report": set(),
        "scan_repository_compliance": set(),
        "extract_code_for_analysis": set(),
    }
    for name, want in required.items():
        got = set(tools[name].parameters.get("required") or [])
        assert got == want, f"{name}: required {got} vs {want}"


async def test_defaults_match_nodejs() -> None:
    mcp = _make_server()
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    checks: dict[str, dict[str, Any]] = {
        "search_ee2_standards": {
            "max_results": 8,
            "include_examples": True,
        },
        "analyze_ee2_compliance": {
            "analysis_type": "comprehensive",
            "include_recommendations": True,
        },
        "generate_compliance_report": {
            "scope": "summary",
            "format": "markdown",
        },
        "scan_repository_compliance": {
            "sample_size": 10_000,
        },
        "extract_code_for_analysis": {
            "content_type": "auto",
            "file_pattern": r"\.(sh|py)$",
            "max_files": 50,
        },
    }
    for name, defaults in checks.items():
        props = tools[name].parameters["properties"]
        for key, want in defaults.items():
            assert props[key]["default"] == want, (
                f"{name}.{key} default {props[key].get('default')!r} != {want!r}"
            )


async def test_enum_values_match_nodejs() -> None:
    mcp = _make_server()
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}

    # search_ee2_standards.category (7 values, optional)
    cat_schema = (
        tools["search_ee2_standards"].parameters["properties"]["category"]
    )
    assert _enum_of(cat_schema) == {
        "environment_variables",
        "workflow_structure",
        "error_handling",
        "file_naming",
        "production_utilities",
        "code_standards",
        "directory_structure",
    }

    # analyze_ee2_compliance.analysis_type (8 values including comprehensive)
    at_schema = (
        tools["analyze_ee2_compliance"]
        .parameters["properties"]["analysis_type"]
    )
    assert _enum_of(at_schema) == {
        "comprehensive",
        "environment_variables",
        "workflow_structure",
        "error_handling",
        "file_naming",
        "production_utilities",
        "code_standards",
        "directory_structure",
    }

    # generate_compliance_report.scope (3 values)
    scope_schema = (
        tools["generate_compliance_report"].parameters["properties"]["scope"]
    )
    assert _enum_of(scope_schema) == {"summary", "detailed", "checklist"}

    # generate_compliance_report.format (3 values)
    fmt_schema = (
        tools["generate_compliance_report"].parameters["properties"]["format"]
    )
    assert _enum_of(fmt_schema) == {"markdown", "checklist", "summary"}

    # scan_repository_compliance.categories (5-value enum array)
    scan_cat_schema = (
        tools["scan_repository_compliance"]
        .parameters["properties"]["categories"]
    )
    assert _enum_of(scan_cat_schema) == {
        "error_handling",
        "environment_variables",
        "file_naming",
        "shebang_compliance",
        "production_utilities",
    }

    # extract_code_for_analysis.content_type (3 values)
    ct_schema = (
        tools["extract_code_for_analysis"]
        .parameters["properties"]["content_type"]
    )
    assert _enum_of(ct_schema) == {"bash", "python", "auto"}

    # extract_code_for_analysis.categories (4-value enum array)
    ext_cat_schema = (
        tools["extract_code_for_analysis"]
        .parameters["properties"]["categories"]
    )
    assert _enum_of(ext_cat_schema) == {
        "output_file_naming",
        "error_handling",
        "shebang_compliance",
        "env_var_validation",
    }


# ── degraded mode ─────────────────────────────────────────────────────


async def test_search_returns_error_when_data_missing() -> None:
    """``search_ee2_standards`` is the only vector-backed tool; it must
    surface ``[ERROR]`` when booted without a data-access layer
    (Requirement 1.7)."""
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp, "search_ee2_standards", {"query": "error handling"}
    )
    assert "[ERROR]" in text, text
    assert "unavailable" in text


@pytest.mark.parametrize(
    "tool_name,arguments",
    [
        (
            "analyze_ee2_compliance",
            {"content": "#!/bin/bash\nset -x\nerr_chk\n"},
        ),
        ("generate_compliance_report", {"scope": "summary"}),
        (
            "scan_repository_compliance",
            {
                "files": [
                    {"name": "ok.sh", "content": "#!/bin/bash\nset -x\nerr_chk\n"}
                ]
            },
        ),
        (
            "extract_code_for_analysis",
            {"content": "#!/bin/bash\nset -x\necho $COMOUT/foo.txt\n"},
        ),
    ],
)
async def test_content_scanners_work_without_data(
    tool_name: str, arguments: dict[str, Any]
) -> None:
    """The 4 content-scanning tools operate on caller-supplied content
    and must not require a data-access layer."""
    mcp = _make_server(data=None)
    text = await _call_tool(mcp, tool_name, arguments)
    assert "[ERROR]" not in text, text


async def test_analyze_footer_notes_degraded_standards() -> None:
    """When ``data`` is missing, ``analyze_ee2_compliance`` should flag
    the missing standards context rather than omit it silently."""
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "analyze_ee2_compliance",
        {"content": "#!/bin/bash\nset -x\nerr_chk\n"},
    )
    assert "[INFO] Standards context unavailable" in text


async def test_report_footer_notes_degraded_standards() -> None:
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "generate_compliance_report",
        {"scope": "summary", "categories": ["error_handling"]},
    )
    assert "[INFO] Standards context unavailable" in text


# ── empty-argument validation ─────────────────────────────────────────


async def test_search_rejects_empty_query() -> None:
    data = MockUnifiedDataAccess()
    mcp = _make_server(data=data)
    text = await _call_tool(mcp, "search_ee2_standards", {"query": " "})
    assert "[ERROR]" in text
    assert "query" in text


async def test_analyze_rejects_empty_content() -> None:
    mcp = _make_server(data=None)
    text = await _call_tool(mcp, "analyze_ee2_compliance", {"content": ""})
    assert "[ERROR]" in text
    assert "content" in text


async def test_scan_rejects_repository_path() -> None:
    """The hosted Python port does not read from disk — callers who
    pass ``repository_path`` should see a clear rejection."""
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "scan_repository_compliance",
        {"repository_path": "/tmp/nonexistent"},
    )
    assert "[ERROR]" in text
    assert "repository_path" in text
    assert "files" in text


async def test_scan_rejects_empty_files_array() -> None:
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp, "scan_repository_compliance", {"files": []}
    )
    assert "[ERROR]" in text
    assert "files" in text


async def test_extract_rejects_path_only_mode() -> None:
    """Same content-abstraction gate for ``extract_code_for_analysis``."""
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "extract_code_for_analysis",
        {"path": "/tmp/scripts"},
    )
    assert "[ERROR]" in text
    assert "path" in text


async def test_extract_rejects_when_nothing_provided() -> None:
    mcp = _make_server(data=None)
    text = await _call_tool(mcp, "extract_code_for_analysis", {})
    assert "[ERROR]" in text


# ── search_ee2_standards ──────────────────────────────────────────────


async def test_search_queries_correct_collection_and_renders_results() -> None:
    data = MockUnifiedDataAccess()
    # Seed the mock with EE2-shaped hits.
    data.vector_db.hits = [
        {
            "id": "ee2-001",
            "content": (
                "Use err_chk after every file operation. "
                "Do not use set -eu."
            ),
            "document": (
                "Use err_chk after every file operation. "
                "Do not use set -eu."
            ),
            "metadata": {
                "category": "error_handling",
                "example": "err_chk",
            },
            "score": 0.91,
            "distance": 0.82,
        }
    ]
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "search_ee2_standards",
        {
            "query": "error handling",
            "category": "error_handling",
            "max_results": 3,
            "include_examples": True,
        },
    )
    # Vector adapter should have been called with the EE2 collection.
    calls = [c for c in data.vector_db.call_log if c[0] == "query"]
    assert calls, "query() should have been invoked"
    (collection, query_text), kwargs = calls[-1][1], calls[-1][2]
    assert collection == ee2_compliance.EE2_COLLECTION
    assert "EE2 compliance" in query_text
    assert "error_handling" in query_text
    assert kwargs["k"] == 3

    # Rendered output carries the standard headers + example block.
    assert "# EE2 Standards Search: error handling" in text
    assert "**Category:** error_handling" in text
    assert "## Standard 1" in text
    assert "Use err_chk after every file operation" in text
    assert "**Example:**" in text


async def test_search_no_results_renders_empty_body() -> None:
    data = MockUnifiedDataAccess()
    data.vector_db.hits = []
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "search_ee2_standards", {"query": "zzz"}
    )
    assert "Found 0 standards" in text
    assert "No EE2 standards found" in text


async def test_search_max_results_clamped_to_ceiling() -> None:
    """``max_results=999`` must clamp to the Node.js ``maximum`` of 20."""
    data = MockUnifiedDataAccess()
    data.vector_db.hits = []
    mcp = _make_server(data=data)
    await _call_tool(
        mcp,
        "search_ee2_standards",
        {"query": "anything", "max_results": 999},
    )
    (_, _), kwargs = (
        [c for c in data.vector_db.call_log if c[0] == "query"][-1][1],
        [c for c in data.vector_db.call_log if c[0] == "query"][-1][2],
    )
    assert kwargs["k"] == ee2_compliance.SEARCH_RESULTS_MAX


async def test_search_max_results_clamped_to_floor() -> None:
    """``max_results=0`` must clamp to the Node.js ``minimum`` of 1."""
    data = MockUnifiedDataAccess()
    data.vector_db.hits = []
    mcp = _make_server(data=data)
    await _call_tool(
        mcp,
        "search_ee2_standards",
        {"query": "anything", "max_results": 0},
    )
    kwargs = [c for c in data.vector_db.call_log if c[0] == "query"][-1][2]
    assert kwargs["k"] == ee2_compliance.SEARCH_RESULTS_MIN


async def test_search_optional_category_omitted() -> None:
    """When the caller does not pass ``category`` the enhanced query
    still includes the 'EE2 compliance' anchor but not a category token."""
    data = MockUnifiedDataAccess()
    data.vector_db.hits = []
    mcp = _make_server(data=data)
    await _call_tool(
        mcp, "search_ee2_standards", {"query": "style"}
    )
    (_, query_text) = [
        c for c in data.vector_db.call_log if c[0] == "query"
    ][-1][1]
    assert "EE2 compliance" in query_text
    # No category name should appear in the query.
    assert "error_handling" not in query_text
    assert "file_naming" not in query_text


# ── analyze_ee2_compliance (SME-corrected behaviour) ──────────────────


_BASH_SET_EU_SCRIPT = (
    "#!/bin/bash\n"
    "set -eu\n"
    "cp /path/a /path/b\n"
    "echo done\n"
)

_BASH_COMPLIANT_SCRIPT = (
    "#!/bin/bash\n"
    "set -x\n"
    "source preamble.sh\n"
    "cp /path/a /path/b\n"
    "export err=$?; err_chk\n"
    'echo "done"\n'
)

_BASH_SET_E_ONLY_SCRIPT = (
    "#!/bin/sh\n"
    "set -e\n"
    "cp /path/a /path/b\n"
)

_BASH_FILE_OPS_NO_ERRCHK = (
    "#!/bin/bash\n"
    "cp /path/a /path/b\n"
    "mv /path/c /path/d\n"
    "ln -s /path/e /path/f\n"
)

_BASH_UNQUOTED_VARS = (
    "#!/bin/bash\n"
    "set -x\n"
    'export "${COMOUT}"\n'
    "echo $FOO\n"
    "echo $BAR\n"
    "echo $BAZ\n"
    "err_chk\n"
)


async def test_analyze_flags_set_eu_as_anti_pattern_sme_corrected() -> None:
    """Phase 2 SME correction: ``set -eu`` is NOT required by EE2 and
    must be flagged, not left alone."""
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "analyze_ee2_compliance",
        {"content": _BASH_SET_EU_SCRIPT},
    )
    assert "set -eu" in text
    assert "not required by EE2 standards" in text
    assert "HIGH" in text


async def test_analyze_flags_set_e_as_anti_pattern() -> None:
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "analyze_ee2_compliance",
        {"content": _BASH_SET_E_ONLY_SCRIPT},
    )
    assert "set -e" in text
    assert "not required by EE2 standards" in text


async def test_analyze_praises_err_chk_preamble_scripts() -> None:
    """A script using ``preamble.sh`` + ``err_chk`` and *not* using
    ``set -eu`` should receive the positive observation."""
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "analyze_ee2_compliance",
        {"content": _BASH_COMPLIANT_SCRIPT},
    )
    assert "EE2-compliant error handling" in text
    # And should NOT also flag set -eu on the same script.
    assert "set -eu" not in text


async def test_analyze_flags_file_ops_without_err_chk() -> None:
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "analyze_ee2_compliance",
        {"content": _BASH_FILE_OPS_NO_ERRCHK},
    )
    assert "file operation" in text
    assert "err_chk" in text


async def test_analyze_flags_unquoted_variables() -> None:
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "analyze_ee2_compliance",
        {"content": _BASH_UNQUOTED_VARS},
    )
    assert "unquoted variable" in text
    assert "${VARIABLE}" in text


async def test_analyze_trivially_compliant_script_reports_no_concerns() -> None:
    """A bash script without any of the SME-corrected observation
    triggers (no set -eu/set -e, no preamble/err_chk, no file ops, no
    unquoted vars) should render the clean Review Summary block.

    Note: a script that DOES use preamble/err_chk triggers the
    positive 'EE2-compliant error handling' observation — that is a
    separate test (``test_analyze_praises_err_chk_preamble_scripts``).
    """
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "analyze_ee2_compliance",
        {
            "content": (
                '#!/bin/bash\nset -x\necho "hello world"\n'
            )
        },
    )
    assert "## Review Summary" in text
    assert "align well with EE2 guidelines" in text


async def test_analyze_respects_non_bash_content() -> None:
    """Non-bash content should skip the bash-specific observations."""
    python_src = (
        "#!/usr/bin/env python3\n"
        "import os\n"
        "os.environ['FOO'] = 'bar'\n"
    )
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "analyze_ee2_compliance",
        {"content": python_src},
    )
    # No bash pattern flags.
    assert "set -eu" not in text
    assert "set -e" not in text
    # Should render the Review Summary block.
    assert "## Review Summary" in text or "Observations" in text


async def test_analyze_analysis_type_narrows_categories() -> None:
    """``analysis_type=environment_variables`` should not produce error-
    handling observations even on a script with ``set -eu``."""
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "analyze_ee2_compliance",
        {
            "content": _BASH_SET_EU_SCRIPT,
            "analysis_type": "environment_variables",
        },
    )
    assert "set -eu" not in text
    assert "Error Handling" not in text


# ── generate_compliance_report ────────────────────────────────────────


async def test_report_renders_all_categories_by_default() -> None:
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp, "generate_compliance_report", {"scope": "summary"}
    )
    assert "# EE2 Implementation Standards Reference" in text
    for category in ee2_compliance.SEARCH_CATEGORY_VALUES:
        assert f"## {category.replace('_', ' ').upper()}" in text, category


async def test_report_filters_by_categories() -> None:
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "generate_compliance_report",
        {"scope": "summary", "categories": ["error_handling"]},
    )
    assert "## ERROR HANDLING" in text
    assert "## WORKFLOW STRUCTURE" not in text


async def test_report_passthrough_notice_when_file_naming_requested() -> None:
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "generate_compliance_report",
        {"scope": "summary", "categories": ["file_naming"]},
    )
    assert "Passthrough Recommendation" in text
    assert "extract_code_for_analysis" in text


async def test_report_detailed_scope_with_data_uses_extended_excerpt() -> None:
    data = MockUnifiedDataAccess()
    data.vector_db.hits = [
        {
            "document": "A" * 500,
            "score": 0.9,
            "metadata": {"section_headers": "§4.2.1"},
        },
        {"document": "B" * 500, "score": 0.8, "metadata": {}},
    ]
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "generate_compliance_report",
        {"scope": "detailed", "categories": ["error_handling"]},
    )
    assert "**Reference:** §4.2.1" in text
    assert "### Additional Context" in text


async def test_report_checklist_scope_renders_bullets() -> None:
    data = MockUnifiedDataAccess()
    data.vector_db.hits = [
        {
            "document": (
                "- Use err_chk after every cp\n"
                "- Never use set -eu\n"
                "- Always include set -x\n"
            ),
            "score": 0.9,
            "metadata": {},
        }
    ]
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "generate_compliance_report",
        {"scope": "checklist", "categories": ["error_handling"]},
    )
    assert "- [ ] Use err_chk after every cp" in text
    assert "- [ ] Never use set -eu" in text


# ── scan_repository_compliance ────────────────────────────────────────


async def test_scan_categorizes_files_by_type() -> None:
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "scan_repository_compliance",
        {
            "files": [
                {"name": "exfoo.sh", "path": "scripts/exfoo.sh",
                 "content": "#!/bin/bash\nerr_chk\n"},
                {"name": "bar.py", "path": "ush/bar.py",
                 "content": "import os\n"},
                {"name": "JEVS_ATMOS", "path": "jobs/JEVS_ATMOS",
                 "content": "#!/bin/bash\nset -x\n"},
                {"name": "config.config", "path": "parm/config.config",
                 "content": "SENDCOM=YES\n"},
            ]
        },
    )
    import json

    # The JSON block in the response has the per-type counts.
    start = text.index("```json\n") + len("```json\n")
    end = text.index("\n```", start)
    body = json.loads(text[start:end])
    counts = body["statistics"]["files_by_type"]
    assert counts["shell_scripts"] == 1
    assert counts["python_scripts"] == 1
    assert counts["job_cards"] == 1
    assert counts["config_files"] == 1
    assert body["statistics"]["total_files"] == 4


async def test_scan_file_naming_category_flags_uppercase_com_output() -> None:
    """The Node.js COM regex matches when the COM variable mention and
    a quoted ``.ext`` filename appear on the same line in two
    separate quoted segments (e.g. ``cp "${COMOUT}" "BAD.NC"``)."""
    bad_script = (
        "#!/bin/bash\n"
        "set -x\n"
        'cp "${COMOUT}/subdir" "GFS.T00Z.ATMF006.NC"\n'
        "err_chk\n"
    )
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "scan_repository_compliance",
        {
            "files": [
                {
                    "name": "exgfs_forecast.sh",
                    "path": "scripts/exgfs_forecast.sh",
                    "content": bad_script,
                }
            ],
            "categories": ["file_naming"],
        },
    )
    assert "Uppercase characters in output filename" in text
    assert "gfs.t00z.atmf006.nc" in text  # lowercase fix suggested


async def test_scan_shebang_compliance_detects_line_shift() -> None:
    """A shebang on line 2 (blank line above) must be flagged."""
    content = "\n#!/bin/bash\nset -x\n"
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "scan_repository_compliance",
        {
            "files": [
                {
                    "name": "bad.sh",
                    "path": "scripts/bad.sh",
                    "content": content,
                }
            ],
            "categories": ["shebang_compliance"],
        },
    )
    assert "Shebang on line 2, must be line 1" in text


async def test_scan_shebang_compliance_detects_non_standard_shell() -> None:
    content = "#!/usr/bin/env node\nconsole.log('oops');\n"
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "scan_repository_compliance",
        {
            "files": [
                {
                    "name": "weird.sh",
                    "path": "scripts/weird.sh",
                    "content": content,
                }
            ],
            "categories": ["shebang_compliance"],
        },
    )
    assert "Non-standard shebang" in text


async def test_scan_production_utilities_flags_explicit_exit() -> None:
    content = (
        "#!/bin/bash\nset -x\n"
        "if [ -z \"$FOO\" ]; then\n"
        "  echo FATAL ERROR: missing FOO\n"
        "  exit 1\n"
        "fi\n"
    )
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "scan_repository_compliance",
        {
            "files": [
                {
                    "name": "exfoo.sh",
                    "path": "scripts/exfoo.sh",
                    "content": content,
                }
            ],
            "categories": ["production_utilities"],
        },
    )
    assert "err_exit" in text
    assert "explicit exit" in text.lower() or "Using explicit exit" in text


async def test_scan_category_filter_applies_strictly() -> None:
    """Passing only ``error_handling`` must not trigger file-naming or
    shebang categories."""
    content = (
        "\n#!/bin/bash\n"  # shebang on line 2 would normally trigger
        'cp "${COMIN}/UPPERCASE.TXT" .\n'  # uppercase output would trigger
    )
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "scan_repository_compliance",
        {
            "files": [
                {
                    "name": "bad.sh",
                    "path": "scripts/bad.sh",
                    "content": content,
                }
            ],
            "categories": ["error_handling"],
        },
    )
    import json

    start = text.index("```json\n") + len("```json\n")
    end = text.index("\n```", start)
    body = json.loads(text[start:end])
    # Only error_handling should appear as an input category.
    assert body["input_categories"] == ["error_handling"]
    # The unused categories must not appear in the issues_by_category map.
    assert "file_naming" not in body["issues_by_category"]
    assert "shebang_compliance" not in body["issues_by_category"]


async def test_scan_skips_entries_missing_name_or_content() -> None:
    """Malformed file entries (missing ``name`` or ``content``) must
    be silently skipped — they do not count towards statistics."""
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "scan_repository_compliance",
        {
            "files": [
                {"name": "ok.sh",
                 "content": "#!/bin/bash\nset -x\nerr_chk\n"},
                # Missing content — skipped
                {"name": "broken.sh"},
                # Missing name — skipped
                {"content": "orphan"},
            ]
        },
    )
    import json

    start = text.index("```json\n") + len("```json\n")
    end = text.index("\n```", start)
    body = json.loads(text[start:end])
    assert body["statistics"]["samples_analyzed"] == 1


async def test_scan_sample_size_truncates_large_batches() -> None:
    mcp = _make_server(data=None)
    files = [
        {"name": f"script_{i}.sh", "content": "#!/bin/bash\nset -x\n"}
        for i in range(50)
    ]
    text = await _call_tool(
        mcp,
        "scan_repository_compliance",
        {"files": files, "sample_size": 10},
    )
    import json

    start = text.index("```json\n") + len("```json\n")
    end = text.index("\n```", start)
    body = json.loads(text[start:end])
    assert body["statistics"]["samples_analyzed"] == 10


# ── extract_code_for_analysis ─────────────────────────────────────────


async def test_extract_direct_content_finds_com_patterns() -> None:
    content = (
        "#!/bin/bash\n"
        "set -x\n"
        'cp "${FOO}" "${COMOUT_ATMOS_GRIB_0p25}/gfs.t00z.atmf006.grib2"\n'
        'cp "${BAR}" $COMOUT/extra.nc\n'
        "err_chk\n"
    )
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "extract_code_for_analysis",
        {
            "content": content,
            "categories": ["output_file_naming"],
        },
    )
    assert "OUTPUT_FILE_NAMING" in text.upper() or "output_file_naming" in text.lower()
    assert "output patterns:" in text
    # At least one line-anchored match should appear in the snippet
    # ledger. Node.js renders as ``Line N: `...` ``.
    assert "Line " in text


async def test_extract_files_array_filters_by_pattern() -> None:
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "extract_code_for_analysis",
        {
            "files": [
                {"name": "foo.sh", "content": "#!/bin/bash\nset -x\n"},
                {"name": "bar.py", "content": "import os\n"},
                {"name": "readme.md", "content": "# README\n"},
                {"name": "config.yml", "content": "key: value\n"},
            ],
            "file_pattern": r"\.(sh|py)$",
            "categories": ["shebang_compliance"],
        },
    )
    # README and config.yml should be skipped.
    assert "readme.md" not in text
    assert "config.yml" not in text
    assert "foo.sh" in text
    assert "bar.py" in text


async def test_extract_rejects_unknown_categories() -> None:
    """Bypass FastMCP schema validation by calling the internal
    helper — at the tool-layer boundary pydantic rejects unknown
    enum values before our code runs, but the helper must also
    validate because the scan + extract tool code paths share the
    ``categories`` parameter in some downstream call sites."""
    text = await ee2_compliance._tool_extract_code_for_analysis(
        content="#!/bin/bash\n",
        files=[],
        path=None,
        content_type="auto",
        categories=["nonsense_category"],
        file_pattern=ee2_compliance.EXTRACT_FILE_PATTERN_DEFAULT,
        max_files=50,
    )
    assert "[ERROR]" in text
    assert "nonsense_category" in text


async def test_extract_invalid_file_pattern_returns_error() -> None:
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "extract_code_for_analysis",
        {
            "files": [{"name": "x.sh", "content": "#!/bin/bash\n"}],
            "file_pattern": "[",  # invalid regex
        },
    )
    assert "[ERROR]" in text
    assert "file_pattern" in text


async def test_extract_max_files_truncates() -> None:
    mcp = _make_server(data=None)
    files = [
        {"name": f"f{i}.sh", "content": "#!/bin/bash\nset -x\n"}
        for i in range(30)
    ]
    text = await _call_tool(
        mcp,
        "extract_code_for_analysis",
        {
            "files": files,
            "max_files": 5,
            "categories": ["shebang_compliance"],
        },
    )
    # Files Scanned line reflects the truncated count (direct content +
    # first 5 files).
    assert "**Files Scanned:** 5" in text


async def test_extract_content_type_auto_detects_python() -> None:
    mcp = _make_server(data=None)
    python_src = (
        "#!/usr/bin/env python3\n"
        "import os\n"
        "def main():\n"
        "    os.environ['FOO']\n"
    )
    text = await _call_tool(
        mcp,
        "extract_code_for_analysis",
        {
            "content": python_src,
            "categories": ["env_var_validation"],
        },
    )
    assert "**Content Type:** auto" in text
    assert "**Type:** python" in text


async def test_extract_emits_sme_correction_guidance() -> None:
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "extract_code_for_analysis",
        {
            "content": "#!/bin/bash\nset -x\n",
            "categories": ["error_handling"],
        },
    )
    # SME corrections (the Phase 2 guardrail text) must be in the prompt.
    assert "set -eu is NOT in EE2 standards" in text


# ── helper functions ──────────────────────────────────────────────────


def test_build_standards_query_maps_known_categories() -> None:
    assert "err_chk" not in ee2_compliance._build_standards_query(
        "unknown"
    )
    # All 7 known categories map to a non-empty multi-word query.
    for category in ee2_compliance.SEARCH_CATEGORY_VALUES:
        query = ee2_compliance._build_standards_query(category)
        assert query and len(query.split()) >= 2


def test_extract_checklist_items_dedups_and_limits() -> None:
    items = ee2_compliance._extract_checklist_items(
        "- item one\n"
        "- item two\n"
        "1. numbered\n"
        "Use the err_chk utility\n"
        "Random prose that should not match\n"
        + "\n".join(f"- filler {i}" for i in range(20))
    )
    assert len(items) <= 8
    assert "item one" in items
    assert "numbered" in items


def test_detect_content_type_respects_hint() -> None:
    assert ee2_compliance._detect_content_type("anything", "bash") == "bash"
    assert ee2_compliance._detect_content_type("anything", "python") == "python"


def test_detect_content_type_auto_shell() -> None:
    assert (
        ee2_compliance._detect_content_type("#!/bin/bash\nset -x\n", "auto")
        == "bash"
    )


def test_detect_content_type_auto_python() -> None:
    assert (
        ee2_compliance._detect_content_type(
            "#!/usr/bin/env python3\nimport os\n", "auto"
        )
        == "python"
    )


def test_snippet_patterns_cover_all_extract_categories() -> None:
    """Every category accepted by ``extract_code_for_analysis`` must
    map to a non-empty snippet-pattern list."""
    for category in ee2_compliance.EXTRACT_CATEGORY_VALUES:
        mapped = ee2_compliance._EXTRACT_CATEGORY_MAP[category]
        assert ee2_compliance._SNIPPET_PATTERNS[mapped], category


def test_ee2_analysis_prompts_cover_all_extract_categories() -> None:
    """Every extract category has an LLM prompt template."""
    assert set(ee2_compliance.EE2_ANALYSIS_PROMPTS) == set(
        ee2_compliance.EXTRACT_CATEGORY_VALUES
    )
    for prompt in ee2_compliance.EE2_ANALYSIS_PROMPTS.values():
        assert prompt["context"]
        assert prompt["instruction"]
        assert prompt["sme_corrections"]
