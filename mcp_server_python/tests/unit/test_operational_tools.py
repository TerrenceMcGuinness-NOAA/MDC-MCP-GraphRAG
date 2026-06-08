"""Unit tests for :mod:`src.tools.operational` (Task 13.3, Phase B9).

Covers tool-schema parity with Node.js, degraded-mode behaviour
(all 4 tools require ``data``), and happy paths against
``MockUnifiedDataAccess``. Specific tests exercise:

- platform enum routing in ``get_operational_guidance``
- urgency flag behaviour (emergency block rendering)
- detail_level enum in ``explain_workflow_component``
- category filtering + search filter + format routing in
  ``list_job_scripts``
- include_content / include_config / include_chromadb flags in
  ``get_job_details``
- content-abstraction: ``list_job_scripts`` graph fallback;
  ``get_job_details`` "not found" path when the graph node is absent.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastmcp import FastMCP

from src.tools import operational
from tests.conftest import MockUnifiedDataAccess

pytestmark = pytest.mark.unit


def _make_server(*, data: Any = None) -> FastMCP:
    mcp = FastMCP("mdc-mcp-rag-test", version="1.0.0")
    operational.register(mcp, data=data)
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
    enum = schema.get("enum")
    if enum is None:
        for branch in schema.get("anyOf") or []:
            if "enum" in branch:
                enum = branch["enum"]
                break
    if enum is None:
        items = schema.get("items") or {}
        enum = items.get("enum")
        if enum is None:
            for branch in schema.get("anyOf") or []:
                items = branch.get("items") or {}
                if "enum" in items:
                    enum = items["enum"]
                    break
    return set(enum or [])


# ── registration parity ──────────────────────────────────────────────


async def test_register_exposes_four_tools_with_matching_names() -> None:
    mcp = _make_server()
    names = sorted(t.name for t in await mcp.list_tools(run_middleware=False))
    assert names == sorted(
        [
            "get_operational_guidance",
            "explain_workflow_component",
            "list_job_scripts",
            "get_job_details",
        ]
    )


async def test_tool_schemas_match_nodejs_parameter_names() -> None:
    mcp = _make_server()
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    expected = {
        "get_operational_guidance": {"operation", "platform", "urgency", "tenant_id"},
        "explain_workflow_component": {"component", "detail_level", "tenant_id"},
        "list_job_scripts": {
            "category",
            "search",
            "format",
            "job_list",
            "files", "tenant_id"},
        "get_job_details": {
            "job_name",
            "include_content",
            "include_config",
            "include_chromadb", "tenant_id"},
    }
    for name, params in expected.items():
        props = set(tools[name].parameters.get("properties", {}).keys())
        assert props == params, (
            f"{name}: expected {params}, got {props}"
        )


async def test_required_fields_match_nodejs() -> None:
    mcp = _make_server()
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    required = {
        "get_operational_guidance": {"operation"},
        "explain_workflow_component": {"component"},
        "list_job_scripts": set(),
        "get_job_details": {"job_name"},
    }
    for name, want in required.items():
        got = set(tools[name].parameters.get("required") or [])
        assert got == want, f"{name}: required {got} vs {want}"


async def test_defaults_match_nodejs() -> None:
    mcp = _make_server()
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    checks: dict[str, dict[str, Any]] = {
        "get_operational_guidance": {
            "platform": "generic",
            "urgency": "routine",
        },
        "explain_workflow_component": {"detail_level": "detailed"},
        "list_job_scripts": {"format": "summary"},
        "get_job_details": {
            "include_content": False,
            "include_config": True,
            "include_chromadb": True,
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

    platform = (
        tools["get_operational_guidance"].parameters["properties"]["platform"]
    )
    assert _enum_of(platform) == {
        "hera",
        "hercules",
        "orion",
        "wcoss2",
        "gaea",
        "generic",
    }

    urgency = (
        tools["get_operational_guidance"].parameters["properties"]["urgency"]
    )
    assert _enum_of(urgency) == {"routine", "urgent", "emergency"}

    detail = (
        tools["explain_workflow_component"].parameters["properties"]["detail_level"]
    )
    assert _enum_of(detail) == {"basic", "detailed", "expert"}

    category = (
        tools["list_job_scripts"].parameters["properties"]["category"]
    )
    assert _enum_of(category) == {
        "analysis",
        "forecast",
        "post",
        "archive",
        "verification",
        "all",
    }

    fmt = tools["list_job_scripts"].parameters["properties"]["format"]
    assert _enum_of(fmt) == {"summary", "detailed", "json"}


# ── degraded mode ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "tool_name,arguments",
    [
        ("get_operational_guidance", {"operation": "submit forecast"}),
        ("explain_workflow_component", {"component": "exgfs_forecast"}),
        ("list_job_scripts", {}),
        ("get_job_details", {"job_name": "JGLOBAL_FORECAST"}),
    ],
)
async def test_all_tools_return_error_when_data_missing(
    tool_name: str, arguments: dict[str, Any]
) -> None:
    """Requirement 1.7: every operational tool requires a data-access
    layer and surfaces ``[ERROR]`` in degraded-mode boot."""
    mcp = _make_server(data=None)
    text = await _call_tool(mcp, tool_name, arguments)
    assert "[ERROR]" in text, text
    assert "unavailable" in text or "degraded" in text


async def test_list_job_scripts_with_remote_list_works_without_data() -> None:
    """The Node.js ``remote mode`` (job_list param) bypasses the
    data-access layer entirely — confirm parity in the Python port.

    With a caller-supplied job_list, the tool renders the output
    without touching ``data``. This is the only degraded-mode-OK
    path in the operational module.
    """
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "list_job_scripts",
        {"job_list": ["JGLOBAL_FORECAST", "JGDAS_FIT2OBS"]},
    )
    assert "[ERROR]" not in text, text
    assert "JGLOBAL_FORECAST" in text
    assert "JGDAS_FIT2OBS" in text


# ── empty-argument validation ────────────────────────────────────────


async def test_get_operational_guidance_rejects_empty_operation() -> None:
    mcp = _make_server(data=MockUnifiedDataAccess())
    text = await _call_tool(
        mcp, "get_operational_guidance", {"operation": " "}
    )
    assert "[ERROR]" in text
    assert "operation" in text


async def test_explain_workflow_component_rejects_empty_component() -> None:
    mcp = _make_server(data=MockUnifiedDataAccess())
    text = await _call_tool(
        mcp, "explain_workflow_component", {"component": ""}
    )
    assert "[ERROR]" in text
    assert "component" in text


async def test_get_job_details_rejects_empty_job_name() -> None:
    mcp = _make_server(data=MockUnifiedDataAccess())
    text = await _call_tool(mcp, "get_job_details", {"job_name": "  "})
    assert "[ERROR]" in text
    assert "job_name" in text


# ── get_operational_guidance ─────────────────────────────────────────


async def test_guidance_renders_procedure_from_vector_hits() -> None:
    data = MockUnifiedDataAccess()
    data.vector_db.hits = [
        {
            "id": "doc-1",
            "document": "1. Load HERA.env module\n2. Submit via sbatch",
            "score": 0.9,
            "metadata": {},
        }
    ]
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "get_operational_guidance",
        {"operation": "submit forecast", "platform": "hera"},
    )
    assert "# Operational Guidance: submit forecast" in text
    assert "**Platform:** HERA" in text
    assert "**Urgency:** ROUTINE" in text
    assert "Load HERA.env module" in text
    # Platform notes block always appears.
    assert "## Platform-Specific Notes" in text
    assert "NOAA RDHPCS system" in text


async def test_guidance_queries_correct_collection() -> None:
    data = MockUnifiedDataAccess()
    mcp = _make_server(data=data)
    await _call_tool(
        mcp,
        "get_operational_guidance",
        {"operation": "restart job", "platform": "wcoss2"},
    )
    calls = [c for c in data.vector_db.call_log if c[0] == "query"]
    assert calls, "expected vector_db.query call"
    (collection, query_text), kwargs = calls[-1][1], calls[-1][2]
    assert collection == operational.WORKFLOW_DOCS_COLLECTION
    assert "restart job" in query_text
    assert "wcoss2" in query_text
    assert kwargs["k"] == 5
    assert kwargs["include_graph"] is True


@pytest.mark.parametrize(
    "platform,expected",
    [
        ("hera", "NOAA RDHPCS"),
        ("hercules", "MSU research system"),
        ("orion", "MSU research system"),
        ("wcoss2", "PBS scheduler"),
        ("gaea", "GAEA.env"),
        ("generic", "Platform-agnostic"),
    ],
)
async def test_guidance_platform_notes_match_nodejs(
    platform: str, expected: str
) -> None:
    data = MockUnifiedDataAccess()
    data.vector_db.hits = []
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "get_operational_guidance",
        {"operation": "restart", "platform": platform},
    )
    assert expected in text, (platform, expected, text)


async def test_guidance_urgency_emergency_renders_warning_block() -> None:
    data = MockUnifiedDataAccess()
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "get_operational_guidance",
        {"operation": "restart forecast", "urgency": "emergency"},
    )
    assert "[WARN]" in text
    assert "EMERGENCY PROCEDURE" in text
    assert "Contact on-call staff" in text


async def test_guidance_urgency_routine_suppresses_warning_block() -> None:
    data = MockUnifiedDataAccess()
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "get_operational_guidance",
        {"operation": "restart forecast", "urgency": "routine"},
    )
    assert "EMERGENCY PROCEDURE" not in text


async def test_guidance_no_hits_falls_back_to_general_guidance() -> None:
    data = MockUnifiedDataAccess()
    data.vector_db.hits = []
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "get_operational_guidance",
        {"operation": "submit job", "platform": "hera"},
    )
    assert "### General Guidance" in text
    assert "env/HERA.env" in text
    assert "job scripts in jobs/ directory" in text


# ── explain_workflow_component ───────────────────────────────────────


async def test_explain_renders_documentation_and_graph_sections() -> None:
    data = MockUnifiedDataAccess()
    data.vector_db.hits = [
        {
            "document": "exgfs_forecast.sh runs the GFS model forecast.",
            "score": 0.9,
            "metadata": {},
        }
    ]
    data.graph_db.add_response(
        "n.name = $component OR n.absolutePath CONTAINS $component",
        [
            {
                "name": "exgfs_forecast.sh",
                "type": "ShellScript",
                "path": "scripts/exgfs_forecast.sh",
                "language": "shell",
            }
        ],
    )
    data.graph_db.add_response(
        "(f)-[:IMPORTS|SOURCES|USES]->(dep)",
        [{"importedFile": "preamble.sh", "path": "ush/preamble.sh"}],
    )

    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "explain_workflow_component",
        {"component": "exgfs_forecast.sh"},
    )
    assert "# Workflow Component: exgfs_forecast.sh" in text
    assert "**Detail Level:** detailed" in text
    assert "## Documentation" in text
    assert "runs the GFS model forecast" in text
    assert "## Code Structure" in text
    assert "### exgfs_forecast.sh" in text
    assert "- **Type:** ShellScript" in text
    assert "- **Path:** scripts/exgfs_forecast.sh" in text
    assert "- **Language:** shell" in text
    assert "## Dependencies" in text
    assert "preamble.sh" in text


async def test_explain_expert_detail_level_adds_expert_notes() -> None:
    data = MockUnifiedDataAccess()
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "explain_workflow_component",
        {"component": "forecast", "detail_level": "expert"},
    )
    assert "## Expert Notes" in text
    assert "Check source in repository" in text
    assert "workflow XML definitions" in text


async def test_explain_basic_detail_level_omits_expert_notes() -> None:
    data = MockUnifiedDataAccess()
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "explain_workflow_component",
        {"component": "forecast", "detail_level": "basic"},
    )
    assert "## Expert Notes" not in text


async def test_explain_reports_missing_component() -> None:
    """With empty vector + graph results, render the 'not found' hint."""
    data = MockUnifiedDataAccess()
    data.vector_db.hits = []
    data.graph_db.canned_rows = []
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "explain_workflow_component",
        {"component": "zzz_unknown"},
    )
    assert "No documentation or graph hits found" in text
    assert "zzz_unknown" in text


async def test_explain_queries_workflow_docs_collection() -> None:
    data = MockUnifiedDataAccess()
    mcp = _make_server(data=data)
    await _call_tool(
        mcp,
        "explain_workflow_component",
        {"component": "forecast"},
    )
    calls = [c for c in data.vector_db.call_log if c[0] == "query"]
    assert calls
    (collection, query_text), kwargs = calls[-1][1], calls[-1][2]
    assert collection == operational.WORKFLOW_DOCS_COLLECTION
    assert query_text == "forecast"
    assert kwargs["include_graph"] is False


# ── list_job_scripts ─────────────────────────────────────────────────


_SAMPLE_JOB_LIST = [
    "JGLOBAL_FORECAST",
    "JGDAS_FIT2OBS",
    "JGDAS_ENKF_ANAL",
    "JGFS_ATMOS_POST",
    "JGLOBAL_ARCHIVE",
    "JGDAS_VERFOZN",
    "not-a-j-job",  # filtered out (doesn't start with J)
]


async def test_list_from_job_list_filters_to_j_prefix() -> None:
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "list_job_scripts",
        {"job_list": _SAMPLE_JOB_LIST},
    )
    assert "**Total:** 6 jobs" in text  # 6 J-jobs, 1 filtered out
    assert "JGLOBAL_FORECAST" in text
    assert "not-a-j-job" not in text


async def test_list_category_filter_forecast() -> None:
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "list_job_scripts",
        {"job_list": _SAMPLE_JOB_LIST, "category": "forecast"},
    )
    assert "**Category:** forecast" in text
    assert "JGLOBAL_FORECAST" in text
    # analysis / archive jobs should be absent from the job list.
    assert "- JGDAS_ENKF_ANAL" not in text
    assert "- JGLOBAL_ARCHIVE" not in text


@pytest.mark.parametrize(
    "category,expected_jobs",
    [
        ("analysis", {"JGDAS_ENKF_ANAL"}),
        ("forecast", {"JGLOBAL_FORECAST"}),
        ("post", {"JGFS_ATMOS_POST"}),
        ("archive", {"JGLOBAL_ARCHIVE"}),
        ("verification", {"JGDAS_FIT2OBS", "JGDAS_VERFOZN"}),
    ],
)
async def test_list_category_regexes_match_nodejs(
    category: str, expected_jobs: set[str]
) -> None:
    """Per-category filter regexes match the Node.js ``categories``
    object — a verification case for the ported regex table."""
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "list_job_scripts",
        {"job_list": _SAMPLE_JOB_LIST, "category": category},
    )
    for job in expected_jobs:
        assert f"- {job}" in text, (category, job, text)


async def test_list_search_filter_case_insensitive() -> None:
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "list_job_scripts",
        {"job_list": _SAMPLE_JOB_LIST, "search": "fit2obs"},
    )
    assert "JGDAS_FIT2OBS" in text
    assert "JGLOBAL_FORECAST" not in text
    assert "**Total:** 1 jobs" in text


async def test_list_format_json() -> None:
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "list_job_scripts",
        {
            "job_list": ["JGLOBAL_FORECAST", "JGDAS_FIT2OBS"],
            "format": "json",
        },
    )
    import json as _json

    start = text.index("```json\n") + len("```json\n")
    end = text.index("\n```", start)
    body = _json.loads(text[start:end])
    assert body["category"] == "all"
    assert body["jobs"] == ["JGDAS_FIT2OBS", "JGLOBAL_FORECAST"]


async def test_list_format_detailed_uses_file_content_when_provided() -> None:
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "list_job_scripts",
        {
            "files": [
                {
                    "name": "JGLOBAL_FORECAST",
                    "content": (
                        "#!/bin/bash\n"
                        "# Description: Global forecast job\n"
                    ),
                },
                {
                    "name": "JGDAS_FIT2OBS",
                    "content": "#!/bin/bash\n",
                },
            ],
            "format": "detailed",
        },
    )
    assert "## JGLOBAL_FORECAST" in text
    assert "Description: Global forecast job" in text
    # File with no description line → fallback text.
    assert "## JGDAS_FIT2OBS" in text
    assert "content provided" in text


async def test_list_falls_back_to_graph_query_when_no_input_given() -> None:
    data = MockUnifiedDataAccess()
    data.graph_db.add_response(
        "j.name STARTS WITH 'J'",
        [
            {"name": "JGLOBAL_FORECAST"},
            {"name": "JGDAS_FIT2OBS"},
            {"name": "JGDAS_ENKF_ANAL"},
        ],
    )
    mcp = _make_server(data=data)
    text = await _call_tool(mcp, "list_job_scripts", {})
    assert "*Source: graph_db J-Job query*" in text
    assert "JGLOBAL_FORECAST" in text
    assert "**Total:** 3 jobs" in text


async def test_list_summary_format_shows_category_breakdown() -> None:
    mcp = _make_server(data=None)
    text = await _call_tool(
        mcp,
        "list_job_scripts",
        {"job_list": _SAMPLE_JOB_LIST},
    )
    assert "## Categories" in text
    assert "**Analysis:**" in text
    assert "**Forecast:**" in text
    assert "**Post-Processing:**" in text
    assert "**Archive:**" in text
    assert "**Verification:**" in text
    assert "## Job List" in text


# ── pure-function helpers ────────────────────────────────────────────


@pytest.mark.parametrize(
    "name,expected",
    [
        ("JGDAS_ENKF_ANAL", "analysis"),
        ("JGLOBAL_FORECAST", "forecast"),
        ("JGFS_ATMOS_POST", "post-processing"),
        ("JGLOBAL_ARCHIVE", "archive"),
        ("JGDAS_VERFOZN", "verification"),
        ("JGFS_WAVE_POST", "post-processing"),  # 'post' wins over 'wave'
        ("JGLOBAL_WAVE_INIT", "wave"),
        ("JGLOBAL_OCEAN_PREP", "ocean"),
        ("JGLOBAL_AERO_ANAL", "analysis"),  # 'anal' wins over 'aero'
        ("JUNKNOWN_FOO", "general"),
    ],
)
def test_categorize_job_matches_nodejs(name: str, expected: str) -> None:
    assert operational._categorize_job(name) == expected


@pytest.mark.parametrize(
    "name,expected",
    [
        ("JGDAS_FIT2OBS", "gdas"),
        ("JGFS_FORECAST", "gfs"),
        ("JGLOBAL_ARCHIVE", "global"),
        ("JGEFS_ENS", "gefs"),
        ("JGLOBAL", "global"),
        ("FOOBAR", "unknown"),
    ],
)
def test_extract_system_matches_nodejs(name: str, expected: str) -> None:
    assert operational._extract_system(name) == expected


# ── get_job_details ──────────────────────────────────────────────────


def _seed_jjob_node(data: MockUnifiedDataAccess, **overrides: Any) -> None:
    row = {
        "name": "JGLOBAL_FORECAST",
        "path": "jobs/JGLOBAL_FORECAST",
        "lineCount": 142,
        "jobTask": "fcst",
        "labels": ["ShellScript"],
    }
    row.update(overrides)
    # Register for the label-based fallback chain (JJob, RocotoTask, ShellScript)
    data.graph_db.add_response(
        "MATCH (j:JJob) WHERE j.name = $name",
        [row],
    )


async def test_get_job_details_reports_not_found() -> None:
    data = MockUnifiedDataAccess()
    # Override the default canned rows so node lookup returns empty.
    data.graph_db.canned_rows = []
    data.graph_db.add_response("MATCH (j:JJob) WHERE j.name = $name", [])
    data.graph_db.add_response("MATCH (j:RocotoTask) WHERE j.name = $name", [])
    data.graph_db.add_response("MATCH (j:ShellScript) WHERE j.name = $name", [])
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "get_job_details", {"job_name": "JFAKE_MISSING"}
    )
    assert "[ERROR]" in text
    assert "JFAKE_MISSING" in text
    assert "not found" in text.lower()


async def test_get_job_details_renders_metadata_header() -> None:
    data = MockUnifiedDataAccess()
    data.graph_db.canned_rows = []
    _seed_jjob_node(data)
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "get_job_details", {"job_name": "JGLOBAL_FORECAST"}
    )
    assert "# J-Job Details: JGLOBAL_FORECAST" in text
    assert "**Path:** jobs/JGLOBAL_FORECAST" in text
    assert "**Lines:** 142" in text
    assert "**Category:** forecast" in text
    assert "**System:** global" in text
    assert "**Task:** fcst" in text


async def test_get_job_details_renders_relationship_blocks() -> None:
    data = MockUnifiedDataAccess()
    data.graph_db.canned_rows = []
    _seed_jjob_node(data)
    data.graph_db.add_response(
        "(j:ShellScript {name: $name})-[:USES_CONFIG|DEPENDS_ON]->(c:ConfigFile)",
        [
            {"name": "config.fcst", "path": "parm/config/gfs/config.fcst"},
            {"name": "config.resources", "path": "parm/config/gfs/config.resources"},
        ],
    )
    data.graph_db.add_response(
        "(j:ShellScript {name: $name})-[r:SOURCES]->(s)",
        [{"script": "preamble.sh", "path": "ush/preamble.sh", "line": 10}],
    )
    data.graph_db.add_response(
        "(j:ShellScript {name: $name})-[r:CALLS|INVOKES|EXECUTES]->(s)",
        [{"script": "exgfs_forecast.sh", "variable": "SCRIPTgfs", "line": 50}],
    )
    data.graph_db.add_response(
        "(j:ShellScript {name: $name})-[:CONSUMES|READS]->(i)",
        [{"variable": "COMIN_ATMOS", "pattern": "*.atmf*.nc"}],
    )
    data.graph_db.add_response(
        "(j:ShellScript {name: $name})-[:PRODUCES|WRITES]->(o)",
        [{"variable": "COMOUT", "path": "${COMOUT}/output.nc"}],
    )
    data.graph_db.add_response(
        "(j:ShellScript {name: $name})-[:DEPENDS_ON_ENV|EXPORTS]->(e:EnvironmentVariable)",
        [
            {"name": "HOMEgfs", "value": "/path/to/gfs"},
            {"name": "PDY", "value": "${YMD}"},
        ],
    )
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp, "get_job_details", {"job_name": "JGLOBAL_FORECAST"}
    )
    assert "## Configuration Files" in text
    assert "`config.fcst`" in text
    assert "## Sourced Scripts" in text
    assert "preamble.sh" in text
    assert "line 10" in text
    assert "## External Script Calls" in text
    assert "`exgfs_forecast.sh`" in text
    assert "`SCRIPTgfs`" in text
    assert "## Inputs" in text
    assert "**COMIN_ATMOS**" in text
    assert "`*.atmf*.nc`" in text
    assert "## Outputs" in text
    assert "**COMOUT**" in text
    assert "## Environment Variables" in text
    assert "| HOMEgfs |" in text
    assert "| PDY |" in text


async def test_get_job_details_include_chromadb_true_queries_jjobs() -> None:
    data = MockUnifiedDataAccess()
    data.graph_db.canned_rows = []
    _seed_jjob_node(data)
    data.vector_db.hits = [
        {
            "content": (
                "JGLOBAL_FORECAST runs the global atmospheric forecast."
            ),
            "score": 0.91,
            "metadata": {"source_file": "jjobs-v8-0-0"},
        }
    ]
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "get_job_details",
        {"job_name": "JGLOBAL_FORECAST", "include_chromadb": True},
    )
    calls = [c for c in data.vector_db.call_log if c[0] == "query"]
    assert calls
    collection = calls[-1][1][0]
    assert collection == operational.JJOBS_COLLECTION
    assert "## Related Documentation" in text
    assert "runs the global atmospheric forecast" in text
    assert "relevance:" in text


async def test_get_job_details_include_chromadb_false_skips_vector_call() -> None:
    data = MockUnifiedDataAccess()
    data.graph_db.canned_rows = []
    _seed_jjob_node(data)
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "get_job_details",
        {"job_name": "JGLOBAL_FORECAST", "include_chromadb": False},
    )
    calls = [c for c in data.vector_db.call_log if c[0] == "query"]
    assert not calls, "vector_db.query should NOT be called when include_chromadb=False"
    assert "## Related Documentation" not in text


async def test_get_job_details_include_content_surfaces_info_note() -> None:
    """include_content=True on the hosted Python port renders the
    [INFO] 'not available' notice — the script body is only reachable
    on the legacy Node.js filesystem."""
    data = MockUnifiedDataAccess()
    data.graph_db.canned_rows = []
    _seed_jjob_node(data)
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "get_job_details",
        {"job_name": "JGLOBAL_FORECAST", "include_content": True},
    )
    assert "## Full Script Content" in text
    assert "[INFO]" in text
    assert "not available on the hosted" in text


async def test_get_job_details_include_config_false_suppresses_fallback_block() -> None:
    """With include_config=False, the 'no config relationships' fallback
    block is suppressed even when the graph has no config rows."""
    data = MockUnifiedDataAccess()
    data.graph_db.canned_rows = []
    _seed_jjob_node(data)
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "get_job_details",
        {
            "job_name": "JGLOBAL_FORECAST",
            "include_config": False,
            "include_chromadb": False,
        },
    )
    assert "## Configuration Files" not in text


async def test_get_job_details_env_var_truncation() -> None:
    """More than 15 env vars → table shows first 15 + '...and N more'."""
    data = MockUnifiedDataAccess()
    data.graph_db.canned_rows = []
    _seed_jjob_node(data)
    data.graph_db.add_response(
        "(j:ShellScript {name: $name})-[:DEPENDS_ON_ENV|EXPORTS]->(e:EnvironmentVariable)",
        [{"name": f"VAR{i}", "value": f"v{i}"} for i in range(20)],
    )
    mcp = _make_server(data=data)
    text = await _call_tool(
        mcp,
        "get_job_details",
        {"job_name": "JGLOBAL_FORECAST", "include_chromadb": False},
    )
    assert "| VAR0 |" in text
    assert "| VAR14 |" in text
    # VAR15..VAR19 should be truncated.
    assert "| VAR15 |" not in text
    assert "...and 5 more" in text
