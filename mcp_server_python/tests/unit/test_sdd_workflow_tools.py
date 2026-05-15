"""Unit tests for :mod:`src.tools.sdd_workflow` (Task 14.2, Phase B10).

Covers tool-schema parity with Node.js, the session lifecycle (start
→ record → resume → complete / abandon), state-file format compat,
degraded-mode behaviour (the module needs no data-access layer), and
the validate_sdd_compliance content-checks battery.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastmcp import FastMCP

from src.sdd.session_manager import (
    STATUS_ABANDONED,
    STATUS_COMPLETED,
    SessionManager,
)
from src.tools import sdd_workflow

pytestmark = pytest.mark.unit


# ── helpers ──────────────────────────────────────────────────────


def _make_session(tmp_path: Path) -> SessionManager:
    """Fresh tmp-dir-backed session manager for an isolated lifecycle."""
    return SessionManager(state_dir=tmp_path / "state")


def _make_server(
    *,
    session: SessionManager | None = None,
    workflows_dir: Path | str | None = None,
    data: Any = None,
) -> FastMCP:
    mcp = FastMCP("mdc-mcp-rag-test", version="1.0.0")
    sdd_workflow.register(
        mcp,
        data=data,
        session_manager=session,
        workflows_dir=workflows_dir,
    )
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
    return set(enum or [])


# ── registration parity ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_exposes_nine_tools(tmp_path: Path) -> None:
    mcp = _make_server(session=_make_session(tmp_path))
    names = sorted(t.name for t in await mcp.list_tools(run_middleware=False))
    assert names == sorted(
        [
            "list_sdd_workflows",
            "get_sdd_workflow",
            "start_sdd_session",
            "get_sdd_execution_history",
            "validate_sdd_compliance",
            "get_sdd_framework_status",
            "record_sdd_step",
            "get_sdd_session",
            "complete_sdd_session",
        ]
    )


@pytest.mark.asyncio
async def test_tool_schemas_match_nodejs_parameter_names(
    tmp_path: Path,
) -> None:
    mcp = _make_server(session=_make_session(tmp_path))
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    expected = {
        "list_sdd_workflows": {"include_metadata"},
        "get_sdd_workflow": {"workflow_name"},
        "start_sdd_session": {"phase", "notes", "total_steps"},
        "get_sdd_execution_history": {"limit", "workflow_name", "analytics"},
        "validate_sdd_compliance": {
            "content",
            "target",
            "framework_version",
            "content_type",
        },
        "get_sdd_framework_status": {"detailed"},
        "record_sdd_step": {"step", "name", "tag", "notes"},
        "get_sdd_session": {"resume"},
        "complete_sdd_session": {"summary", "abandon", "reason"},
    }
    for name, expected_props in expected.items():
        schema = tools[name].parameters
        actual = set((schema.get("properties") or {}).keys())
        assert actual == expected_props, name


@pytest.mark.asyncio
async def test_record_sdd_step_required_and_enum(tmp_path: Path) -> None:
    mcp = _make_server(session=_make_session(tmp_path))
    tool = (await mcp.list_tools(run_middleware=False))
    record = next(t for t in tool if t.name == "record_sdd_step")
    schema = record.parameters
    assert set(schema.get("required") or []) == {"step", "name"}
    tag_schema = schema["properties"]["tag"]
    assert tag_schema["default"] == "implement"
    assert _enum_of(tag_schema) == set(sdd_workflow.TAG_VALUES)


@pytest.mark.asyncio
async def test_validate_sdd_compliance_content_type_enum(
    tmp_path: Path,
) -> None:
    mcp = _make_server(session=_make_session(tmp_path))
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    schema = tools["validate_sdd_compliance"].parameters
    ct_schema = schema["properties"]["content_type"]
    assert ct_schema["default"] == "auto"
    assert _enum_of(ct_schema) == set(sdd_workflow.CONTENT_TYPE_VALUES)
    fv_schema = schema["properties"]["framework_version"]
    assert fv_schema["default"] == "4.0"


@pytest.mark.asyncio
async def test_get_sdd_workflow_workflow_name_required(
    tmp_path: Path,
) -> None:
    mcp = _make_server(session=_make_session(tmp_path))
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    schema = tools["get_sdd_workflow"].parameters
    assert schema.get("required") == ["workflow_name"]


# ── degraded mode (data=None) ────────────────────────────────────


@pytest.mark.asyncio
async def test_module_registers_in_degraded_mode_without_data(
    tmp_path: Path,
) -> None:
    """The whole module is data-access-free — registration with
    ``data=None`` must succeed and every tool must still respond.
    """
    sm = _make_session(tmp_path)
    mcp = _make_server(session=sm, data=None)
    names = {t.name for t in await mcp.list_tools(run_middleware=False)}
    assert len(names) == 9


@pytest.mark.asyncio
async def test_validate_sdd_compliance_works_without_data(
    tmp_path: Path,
) -> None:
    mcp = _make_server(session=_make_session(tmp_path), data=None)
    output = await _call_tool(
        mcp,
        "validate_sdd_compliance",
        {
            "content": '#!/bin/bash\nset -e\n# example\necho "hi"',
            "content_type": "bash",
        },
    )
    assert "[OK]" in output
    assert "Documentation" in output
    assert "Shebang" in output
    assert "Error Handling" in output


# ── session lifecycle ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_session_lifecycle(tmp_path: Path) -> None:
    sm = _make_session(tmp_path)
    mcp = _make_server(session=sm)

    started = await _call_tool(
        mcp,
        "start_sdd_session",
        {"phase": "phase42_demo", "total_steps": 3, "notes": "smoke"},
    )
    assert "SDD Session Started" in started
    assert "phase42_demo" in started
    assert "Total Steps" in started

    assert sm.get_session_state() is not None

    rec1 = await _call_tool(
        mcp,
        "record_sdd_step",
        {
            "step": 1,
            "name": "Research",
            "tag": "research",
            "notes": "audit done",
        },
    )
    assert "Step 1 Recorded" in rec1
    assert "1/3 steps" in rec1

    rec2 = await _call_tool(
        mcp,
        "record_sdd_step",
        {"step": 2, "name": "Implement", "tag": "implement"},
    )
    assert "2/3 steps" in rec2

    got = await _call_tool(mcp, "get_sdd_session", {})
    assert "Active SDD Session" in got
    assert "phase42_demo" in got
    assert "Step 1: Research" in got
    assert "Step 2: Implement" in got

    completed = await _call_tool(
        mcp,
        "complete_sdd_session",
        {"summary": "all good"},
    )
    assert "Session Completed" in completed
    assert "all good" in completed

    # No longer active.
    assert sm.get_session_state() is None
    after = await _call_tool(mcp, "get_sdd_session", {})
    assert "No Active Session" in after


@pytest.mark.asyncio
async def test_abandon_session(tmp_path: Path) -> None:
    sm = _make_session(tmp_path)
    mcp = _make_server(session=sm)
    await _call_tool(
        mcp, "start_sdd_session", {"phase": "phase42_abandon"}
    )
    out = await _call_tool(
        mcp,
        "complete_sdd_session",
        {"abandon": True, "reason": "user halted"},
    )
    assert "Session Abandoned" in out
    assert "user halted" in out
    assert sm.get_session_state() is None


@pytest.mark.asyncio
async def test_resume_session_emits_resumed_event(tmp_path: Path) -> None:
    sm = _make_session(tmp_path)
    mcp = _make_server(session=sm)
    await _call_tool(mcp, "start_sdd_session", {"phase": "phase42_resume"})
    out = await _call_tool(mcp, "get_sdd_session", {"resume": True})
    assert "Active SDD Session" in out

    history_path = sm._history_file  # noqa: SLF001  - direct check
    text = history_path.read_text(encoding="utf-8")
    assert '"event": "resumed"' in text


@pytest.mark.asyncio
async def test_record_step_when_no_active_session(tmp_path: Path) -> None:
    sm = _make_session(tmp_path)
    mcp = _make_server(session=sm)
    out = await _call_tool(
        mcp,
        "record_sdd_step",
        {"step": 1, "name": "Will fail"},
    )
    assert out.startswith("[ERROR]")


@pytest.mark.asyncio
async def test_complete_when_no_active_session(tmp_path: Path) -> None:
    sm = _make_session(tmp_path)
    mcp = _make_server(session=sm)
    out = await _call_tool(mcp, "complete_sdd_session", {})
    assert out.startswith("[ERROR]")


@pytest.mark.asyncio
async def test_start_session_rejects_when_active_exists(
    tmp_path: Path,
) -> None:
    sm = _make_session(tmp_path)
    mcp = _make_server(session=sm)
    await _call_tool(mcp, "start_sdd_session", {"phase": "phase_a"})
    out = await _call_tool(mcp, "start_sdd_session", {"phase": "phase_b"})
    assert out.startswith("[ERROR]")
    assert "already exists" in out.lower()


# ── state file format compat with Node.js ───────────────────────


@pytest.mark.asyncio
async def test_active_session_json_uses_camelcase_keys(tmp_path: Path) -> None:
    sm = _make_session(tmp_path)
    mcp = _make_server(session=sm)
    await _call_tool(
        mcp,
        "start_sdd_session",
        {"phase": "phase42_compat", "total_steps": 2},
    )
    await _call_tool(
        mcp,
        "record_sdd_step",
        {"step": 1, "name": "Audit", "tag": "research"},
    )

    active_file = sm._active_file  # noqa: SLF001
    payload = json.loads(active_file.read_text(encoding="utf-8"))
    # Node.js field names — these must NOT drift.
    for key in (
        "sessionId",
        "phase",
        "startedAt",
        "lastActivityAt",
        "totalSteps",
        "completedSteps",
        "currentStep",
        "skippedSteps",
    ):
        assert key in payload, key
    assert payload["phase"] == "phase42_compat"
    step = payload["completedSteps"][0]
    assert {"step", "name", "tag", "completedAt", "notes"} <= step.keys()


@pytest.mark.asyncio
async def test_history_jsonl_event_shape_matches_nodejs(
    tmp_path: Path,
) -> None:
    sm = _make_session(tmp_path)
    mcp = _make_server(session=sm)
    await _call_tool(
        mcp,
        "start_sdd_session",
        {"phase": "phase42_jsonl", "total_steps": 2, "notes": "n"},
    )
    await _call_tool(
        mcp,
        "record_sdd_step",
        {"step": 1, "name": "First", "tag": "implement"},
    )
    await _call_tool(
        mcp,
        "complete_sdd_session",
        {"summary": "done"},
    )

    history_lines = sm._history_file.read_text(encoding="utf-8").splitlines()  # noqa: SLF001
    events = [json.loads(line) for line in history_lines if line.strip()]
    event_types = [e["event"] for e in events]
    assert event_types == ["started", "step_completed", "completed"]

    started = events[0]
    assert {"sessionId", "phase", "event", "timestamp"} <= started.keys()
    step_event = events[1]
    assert {
        "sessionId",
        "phase",
        "event",
        "step",
        "name",
        "tag",
        "notes",
        "timestamp",
    } <= step_event.keys()
    completed = events[2]
    # Node.js: completedSteps is a count int in the JSONL, not an array.
    assert isinstance(completed["completedSteps"], int)
    assert completed["completedSteps"] == 1
    assert completed["summary"] == "done"
    assert "duration" in completed


# ── execution history rendering ─────────────────────────────────


@pytest.mark.asyncio
async def test_get_sdd_execution_history_empty(tmp_path: Path) -> None:
    sm = _make_session(tmp_path)
    mcp = _make_server(session=sm)
    out = await _call_tool(mcp, "get_sdd_execution_history", {})
    assert "No session history found" in out


@pytest.mark.asyncio
async def test_get_sdd_execution_history_with_completed_session(
    tmp_path: Path,
) -> None:
    sm = _make_session(tmp_path)
    mcp = _make_server(session=sm)
    await _call_tool(mcp, "start_sdd_session", {"phase": "phase_alpha"})
    await _call_tool(
        mcp, "record_sdd_step", {"step": 1, "name": "step1", "tag": "design"}
    )
    await _call_tool(
        mcp, "complete_sdd_session", {"summary": "wrap"}
    )

    out = await _call_tool(mcp, "get_sdd_execution_history", {"limit": 5})
    assert "phase_alpha" in out
    assert "[OK]" in out
    assert "Steps Completed" in out


@pytest.mark.asyncio
async def test_get_sdd_execution_history_filters_by_workflow_name(
    tmp_path: Path,
) -> None:
    sm = _make_session(tmp_path)
    mcp = _make_server(session=sm)
    # Two distinct sessions on different phases.
    await _call_tool(mcp, "start_sdd_session", {"phase": "phase_alpha"})
    await _call_tool(mcp, "complete_sdd_session", {})
    await _call_tool(mcp, "start_sdd_session", {"phase": "phase_beta"})
    await _call_tool(mcp, "complete_sdd_session", {})

    out_all = await _call_tool(mcp, "get_sdd_execution_history", {})
    assert "phase_alpha" in out_all and "phase_beta" in out_all

    out_filtered = await _call_tool(
        mcp,
        "get_sdd_execution_history",
        {"workflow_name": "phase_alpha"},
    )
    assert "phase_alpha" in out_filtered
    assert "phase_beta" not in out_filtered


@pytest.mark.asyncio
async def test_get_sdd_execution_history_analytics_block(
    tmp_path: Path,
) -> None:
    sm = _make_session(tmp_path)
    mcp = _make_server(session=sm)
    # Build a history with one completed (2 steps), one abandoned, one in-progress.
    await _call_tool(mcp, "start_sdd_session", {"phase": "phase_alpha"})
    await _call_tool(
        mcp, "record_sdd_step", {"step": 1, "name": "a", "tag": "research"}
    )
    await _call_tool(
        mcp, "record_sdd_step", {"step": 2, "name": "b", "tag": "implement"}
    )
    await _call_tool(mcp, "complete_sdd_session", {})

    await _call_tool(mcp, "start_sdd_session", {"phase": "phase_beta"})
    await _call_tool(
        mcp, "record_sdd_step", {"step": 1, "name": "c", "tag": "implement"}
    )
    await _call_tool(
        mcp, "complete_sdd_session", {"abandon": True, "reason": "halt"}
    )

    await _call_tool(mcp, "start_sdd_session", {"phase": "phase_gamma"})

    out = await _call_tool(
        mcp, "get_sdd_execution_history", {"analytics": True}
    )
    assert "Session Analytics" in out
    assert "Phases by Status" in out
    assert "Step Tag Distribution" in out
    assert "research" in out
    assert "implement" in out
    assert "Velocity" in out


# ── validate_sdd_compliance ─────────────────────────────────────


def test_perform_sdd_checks_bash_clean() -> None:
    src = '#!/bin/bash\nset -e\n# Documented\nERR_CHK=1\necho "$ERR_CHK"\n'
    checks = sdd_workflow._perform_sdd_checks(src, "bash")
    by_name = {c["name"]: c for c in checks}
    assert by_name["Documentation"]["status"] == "pass"
    assert by_name["Error Handling"]["status"] == "pass"
    assert by_name["Shebang"]["status"] == "pass"
    assert by_name["Path Abstraction"]["status"] == "pass"


def test_perform_sdd_checks_bash_failures() -> None:
    src = "echo /scratch/foo/bar\n"
    checks = sdd_workflow._perform_sdd_checks(src, "bash")
    by_name = {c["name"]: c for c in checks}
    assert by_name["Shebang"]["status"] == "fail"
    assert by_name["Error Handling"]["status"] == "warn"
    assert by_name["Path Abstraction"]["status"] == "fail"


def test_perform_sdd_checks_python_with_type_hints() -> None:
    src = (
        "# main module\n"
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n"
        'if __name__ == "__main__":\n'
        "    add(1, 2)\n"
    )
    checks = sdd_workflow._perform_sdd_checks(src, "python")
    by_name = {c["name"]: c for c in checks}
    assert by_name["Entry Point"]["status"] == "pass"
    assert by_name["Type Hints"]["status"] == "pass"


def test_perform_sdd_checks_python_missing_features() -> None:
    src = "x = 1\ny = 2\nprint(x + y)\n"
    checks = sdd_workflow._perform_sdd_checks(src, "python")
    by_name = {c["name"]: c for c in checks}
    assert by_name["Entry Point"]["status"] == "warn"
    assert by_name["Type Hints"]["status"] == "warn"


def test_detect_content_type_handles_common_cases() -> None:
    assert (
        sdd_workflow._detect_content_type("#!/bin/bash\necho hi\n") == "bash"
    )
    assert (
        sdd_workflow._detect_content_type(
            "#!/usr/bin/env python3\nprint(1)\n"
        )
        == "python"
    )
    assert sdd_workflow._detect_content_type('{"a": 1}') == "json"
    assert sdd_workflow._detect_content_type(
        "def add(a, b):\n    return a+b\n"
    ) == "python"


@pytest.mark.asyncio
async def test_validate_compliance_requires_content_or_target(
    tmp_path: Path,
) -> None:
    mcp = _make_server(session=_make_session(tmp_path))
    out = await _call_tool(mcp, "validate_sdd_compliance", {})
    assert out.startswith("[ERROR]")
    assert "content" in out.lower()


@pytest.mark.asyncio
async def test_validate_compliance_target_path_unsupported(
    tmp_path: Path,
) -> None:
    mcp = _make_server(session=_make_session(tmp_path))
    out = await _call_tool(
        mcp, "validate_sdd_compliance", {"target": "/some/path.py"}
    )
    assert out.startswith("[ERROR]")
    assert "content" in out.lower()


@pytest.mark.asyncio
async def test_validate_compliance_auto_detects_python(
    tmp_path: Path,
) -> None:
    mcp = _make_server(session=_make_session(tmp_path))
    src = (
        "# Hello\n"
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n"
        'if __name__ == "__main__":\n'
        "    add(1, 2)\n"
    )
    out = await _call_tool(
        mcp,
        "validate_sdd_compliance",
        {"content": src, "content_type": "auto"},
    )
    assert "Content Type**: python" in out
    assert "Type Hints" in out
    assert "Entry Point" in out


@pytest.mark.asyncio
async def test_validate_compliance_summary_counts(tmp_path: Path) -> None:
    mcp = _make_server(session=_make_session(tmp_path))
    src = "echo /scratch/foo\n"
    out = await _call_tool(
        mcp,
        "validate_sdd_compliance",
        {"content": src, "content_type": "bash"},
    )
    # Bash with no shebang, no error handling, hardcoded path, no comments
    assert "Failed: 2" in out  # shebang + path
    assert "Warnings:" in out


# ── workflow catalogue (filesystem) ─────────────────────────────


def _write_workflow(workflows_dir: Path, name: str, body: str) -> None:
    workflows_dir.mkdir(parents=True, exist_ok=True)
    (workflows_dir / f"{name}.md").write_text(body, encoding="utf-8")


@pytest.mark.asyncio
async def test_list_sdd_workflows_with_files(tmp_path: Path) -> None:
    workflows = tmp_path / "workflows"
    _write_workflow(
        workflows,
        "phase_demo",
        "# Demo Workflow\n\nIntro paragraph.\n\n## Phase 1: Setup\n",
    )
    _write_workflow(
        workflows,
        "phase_other",
        "# Other Workflow\n\n## Phase 1: Init\n### Step 1: Bootstrap\n",
    )
    mcp = _make_server(
        session=_make_session(tmp_path), workflows_dir=workflows
    )
    out = await _call_tool(mcp, "list_sdd_workflows", {})
    assert "Found 2 workflows" in out
    assert "phase_demo" in out
    assert "phase_other" in out


@pytest.mark.asyncio
async def test_list_sdd_workflows_with_metadata(tmp_path: Path) -> None:
    workflows = tmp_path / "workflows"
    _write_workflow(
        workflows,
        "phase_with_meta",
        (
            "# Pretty Title\n\nIntro.\n\n"
            "## Phase 1: First\n## Phase 2: Second\n\n"
            "### Step 1: Alpha\n### Step 2: Beta\n### Step 3: Gamma\n"
        ),
    )
    mcp = _make_server(
        session=_make_session(tmp_path), workflows_dir=workflows
    )
    out = await _call_tool(
        mcp, "list_sdd_workflows", {"include_metadata": True}
    )
    assert "Title**: Pretty Title" in out
    assert "Phases**: 2" in out
    assert "Steps**: 3" in out


@pytest.mark.asyncio
async def test_list_sdd_workflows_missing_directory(tmp_path: Path) -> None:
    mcp = _make_server(
        session=_make_session(tmp_path),
        workflows_dir=tmp_path / "does_not_exist",
    )
    out = await _call_tool(mcp, "list_sdd_workflows", {})
    assert "[INFO]" in out
    assert "Workflows directory not available" in out


@pytest.mark.asyncio
async def test_get_sdd_workflow_renders_phases_and_steps(
    tmp_path: Path,
) -> None:
    workflows = tmp_path / "workflows"
    _write_workflow(
        workflows,
        "phase_render",
        (
            "---\n"
            "version: 1.0\n"
            "owner: mdc\n"
            "---\n\n"
            "# Render Workflow\n\n"
            "Brief description here.\n\n"
            "## Phase 1: Bootstrap\n"
            "## Phase 2: Run\n\n"
            "### Step 1: Init\n"
            "### Step 2: Process\n"
        ),
    )
    mcp = _make_server(
        session=_make_session(tmp_path), workflows_dir=workflows
    )
    out = await _call_tool(
        mcp, "get_sdd_workflow", {"workflow_name": "phase_render"}
    )
    assert "Render Workflow" in out
    assert "Description" in out
    assert "Phases (2)" in out
    assert "Steps (2)" in out
    assert "version" in out
    assert "owner" in out


@pytest.mark.asyncio
async def test_get_sdd_workflow_not_found(tmp_path: Path) -> None:
    mcp = _make_server(
        session=_make_session(tmp_path),
        workflows_dir=tmp_path / "workflows",
    )
    (tmp_path / "workflows").mkdir()
    out = await _call_tool(
        mcp, "get_sdd_workflow", {"workflow_name": "ghost"}
    )
    assert out.startswith("[ERROR]")
    assert "ghost" in out


# ── framework status ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_framework_status_no_active_session(tmp_path: Path) -> None:
    mcp = _make_server(
        session=_make_session(tmp_path),
        workflows_dir=tmp_path / "workflows",
    )
    out = await _call_tool(mcp, "get_sdd_framework_status", {})
    assert "SDD Framework Status" in out
    assert "*No active session*" in out
    assert "Available Workflows**: 0" in out


@pytest.mark.asyncio
async def test_framework_status_with_active_session(tmp_path: Path) -> None:
    sm = _make_session(tmp_path)
    workflows = tmp_path / "workflows"
    _write_workflow(workflows, "phase_demo", "# Demo\n")
    mcp = _make_server(session=sm, workflows_dir=workflows)
    await _call_tool(
        mcp,
        "start_sdd_session",
        {"phase": "phase_status_test", "total_steps": 5},
    )
    await _call_tool(
        mcp,
        "record_sdd_step",
        {"step": 1, "name": "First", "tag": "research"},
    )

    out = await _call_tool(mcp, "get_sdd_framework_status", {})
    assert "Available Workflows**: 1" in out
    assert "Active Session" in out
    assert "phase_status_test" in out
    assert "Progress" in out
    assert "1/5 steps" in out


@pytest.mark.asyncio
async def test_framework_status_detailed_recent_sessions(
    tmp_path: Path,
) -> None:
    sm = _make_session(tmp_path)
    mcp = _make_server(session=sm, workflows_dir=tmp_path / "workflows")
    await _call_tool(mcp, "start_sdd_session", {"phase": "phase_alpha"})
    await _call_tool(
        mcp, "record_sdd_step", {"step": 1, "name": "x", "tag": "research"}
    )
    await _call_tool(mcp, "complete_sdd_session", {})

    out = await _call_tool(
        mcp, "get_sdd_framework_status", {"detailed": True}
    )
    assert "Session Tools" in out
    assert "Preserved Infrastructure" in out
    assert "Recent Sessions" in out
    assert "phase_alpha" in out


# ── helpers ─────────────────────────────────────────────────────


def test_parse_duration_minutes_handles_formats() -> None:
    assert sdd_workflow._parse_duration_minutes("15m") == 15
    assert sdd_workflow._parse_duration_minutes("1h 22m") == 82
    assert sdd_workflow._parse_duration_minutes("2h") == 120
    assert sdd_workflow._parse_duration_minutes("") is None
    assert sdd_workflow._parse_duration_minutes(None) is None
    assert sdd_workflow._parse_duration_minutes("noise") is None


def test_session_status_helper() -> None:
    completed_events = [
        {"event": "started"},
        {"event": "step_completed"},
        {"event": "completed"},
    ]
    abandoned_events = [
        {"event": "started"},
        {"event": "abandoned"},
    ]
    in_progress_events = [{"event": "started"}, {"event": "step_completed"}]
    assert sdd_workflow._session_status(completed_events) == STATUS_COMPLETED
    assert sdd_workflow._session_status(abandoned_events) == STATUS_ABANDONED
    assert sdd_workflow._session_status(in_progress_events) == "in_progress"
