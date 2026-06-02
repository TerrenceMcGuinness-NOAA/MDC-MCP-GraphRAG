"""Unit tests for :mod:`src.tools.workflow_info` (Task 15.2, Phase B10b).

Covers tool-schema parity with Node.js, the static structure dict
rendering, content-abstraction (the ``structure_data`` /
``content`` bypass paths), and the 12-path filesystem search for
``describe_component``. Filesystem-backed assertions use a tmp_path
fixture seeded with a minimal global-workflow-like tree so the tests
do not depend on the real ``supported_repos/global-workflow`` clone
being present.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from fastmcp import FastMCP

from src.tools import workflow_info

pytestmark = pytest.mark.unit


# ── helpers ──────────────────────────────────────────────────────


def _make_server(
    *,
    workflow_root: Path | str | None = None,
    data: Any = None,
) -> FastMCP:
    mcp = FastMCP("mdc-mcp-rag-test", version="1.0.0")
    workflow_info.register(mcp, data=data, workflow_root=workflow_root)
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


@pytest.fixture
def workflow_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Build a minimal global-workflow-like tree under tmp_path.

    Provides:
    - env/ with HERA.env, WCOSS2.env, ORION.env (no GAEA.env, mirrors
      reality where the actual filename is GAEAC6.env)
    - dev/jobs/JGFS_FORECAST sample
    - dev/scripts/exgfs_forecast.sh sample
    - ush/detect_machine.sh sample (legacy path)

    Also sets MCP_WORKFLOW_ROOT so the tenant-aware resolution path
    (which falls back to env var when no tenant context is active)
    finds the test tree.
    """
    root = tmp_path / "wf"
    root.mkdir()
    monkeypatch.setenv("MCP_WORKFLOW_ROOT", str(root))

    env_dir = root / "env"
    env_dir.mkdir()
    (env_dir / "HERA.env").write_text(
        "#!/bin/bash\nexport HERA_VAR=hera\n", encoding="utf-8"
    )
    (env_dir / "WCOSS2.env").write_text(
        "#!/bin/bash\nexport WCOSS2_VAR=wcoss2\n", encoding="utf-8"
    )
    (env_dir / "ORION.env").write_text(
        "#!/bin/bash\nexport ORION_VAR=orion\n", encoding="utf-8"
    )

    dev_jobs = root / "dev" / "jobs"
    dev_jobs.mkdir(parents=True)
    (dev_jobs / "JGFS_FORECAST").write_text(
        "#!/bin/bash\n# Description: GFS forecast job\nexport STEP=fcst\n",
        encoding="utf-8",
    )

    dev_scripts = root / "dev" / "scripts"
    dev_scripts.mkdir(parents=True)
    (dev_scripts / "exgfs_forecast.sh").write_text(
        "#!/bin/bash\n# PURPOSE: run forecast\necho hi\n",
        encoding="utf-8",
    )

    ush = root / "ush"
    ush.mkdir()
    (ush / "detect_machine.sh").write_text(
        "#!/bin/bash\n# Synopsis: detect platform\nMACHINE_ID=foo\n",
        encoding="utf-8",
    )

    parm = root / "parm"
    parm.mkdir()
    (parm / "archive").mkdir()
    (parm / "archive" / "config1.yaml").write_text("foo: 1\n", encoding="utf-8")

    return root


# ── registration parity ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_exposes_three_tools(workflow_tree: Path) -> None:
    mcp = _make_server(workflow_root=workflow_tree)
    names = sorted(t.name for t in await mcp.list_tools(run_middleware=False))
    assert names == sorted(
        ["get_workflow_structure", "get_system_configs", "describe_component"]
    )


@pytest.mark.asyncio
async def test_tool_schemas_match_nodejs_parameter_names(
    workflow_tree: Path,
) -> None:
    mcp = _make_server(workflow_root=workflow_tree)
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}

    expected = {
        "get_workflow_structure": {"component", "structure_data", "tenant_id"},
        "get_system_configs": {"platform", "config_type", "content", "tenant_id"},
        "describe_component": {
            "component",
            "show_content",
            "content",
            "file_type", "tenant_id"},
    }
    for name, want in expected.items():
        schema = tools[name].parameters
        actual = set((schema.get("properties") or {}).keys())
        assert actual == want, name


@pytest.mark.asyncio
async def test_describe_component_required_field(workflow_tree: Path) -> None:
    mcp = _make_server(workflow_root=workflow_tree)
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    schema = tools["describe_component"].parameters
    assert schema.get("required") == ["component"]
    # show_content default explicitly false
    show_schema = schema["properties"]["show_content"]
    assert show_schema["default"] is False


@pytest.mark.asyncio
async def test_component_enum_matches_nodejs(workflow_tree: Path) -> None:
    mcp = _make_server(workflow_root=workflow_tree)
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    component_schema = tools["get_workflow_structure"].parameters[
        "properties"
    ]["component"]
    assert _enum_of(component_schema) == set(workflow_info.COMPONENT_VALUES)
    assert _enum_of(component_schema) == {
        "jobs",
        "scripts",
        "parm",
        "ush",
        "sorc",
        "docs",
        "env",
    }


@pytest.mark.asyncio
async def test_platform_enum_matches_nodejs(workflow_tree: Path) -> None:
    mcp = _make_server(workflow_root=workflow_tree)
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    platform_schema = tools["get_system_configs"].parameters["properties"][
        "platform"
    ]
    assert _enum_of(platform_schema) == set(workflow_info.PLATFORM_VALUES)
    assert _enum_of(platform_schema) == {
        "hera",
        "hercules",
        "orion",
        "wcoss2",
        "gaea",
        "all",
    }
    config_type_schema = tools["get_system_configs"].parameters[
        "properties"
    ]["config_type"]
    assert _enum_of(config_type_schema) == set(
        workflow_info.CONFIG_TYPE_VALUES
    )


@pytest.mark.asyncio
async def test_file_type_enum_matches_nodejs(workflow_tree: Path) -> None:
    mcp = _make_server(workflow_root=workflow_tree)
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    file_type_schema = tools["describe_component"].parameters["properties"][
        "file_type"
    ]
    assert _enum_of(file_type_schema) == set(workflow_info.FILE_TYPE_VALUES)


# ── degraded mode (data=None, missing workflow_root) ─────────────


@pytest.mark.asyncio
async def test_module_registers_in_degraded_mode_without_data(
    tmp_path: Path,
) -> None:
    """``data=None`` must succeed and every tool must still respond."""
    mcp = _make_server(workflow_root=tmp_path / "missing", data=None)
    names = {t.name for t in await mcp.list_tools(run_middleware=False)}
    assert len(names) == 3


@pytest.mark.asyncio
async def test_get_workflow_structure_works_without_filesystem(
    tmp_path: Path,
) -> None:
    """The static structure dict path doesn't read disk — it works
    even when workflow_root doesn't exist."""
    mcp = _make_server(workflow_root=tmp_path / "does_not_exist")
    out = await _call_tool(mcp, "get_workflow_structure", {})
    assert "Global Workflow Structure" in out
    assert "## System Components" in out
    assert "jobs" in out and "scripts" in out and "env" in out
    assert "Execution Flow" in out


# ── get_workflow_structure ─────────────────────────────────────


@pytest.mark.asyncio
async def test_get_workflow_structure_full_overview(
    workflow_tree: Path,
) -> None:
    mcp = _make_server(workflow_root=workflow_tree)
    out = await _call_tool(mcp, "get_workflow_structure", {})
    assert "Global Workflow Structure" in out
    assert "## System Components" in out
    # Each component header rendered as ### key/
    for key in workflow_info.COMPONENT_VALUES:
        assert f"### {key}/" in out


@pytest.mark.asyncio
async def test_get_workflow_structure_component_focus(
    workflow_tree: Path,
) -> None:
    mcp = _make_server(workflow_root=workflow_tree)
    out = await _call_tool(
        mcp, "get_workflow_structure", {"component": "env"}
    )
    assert "## Component: env" in out
    assert "**Description:** HPC platform environment configurations" in out
    assert "**Platforms:**" in out
    # Should NOT render the full overview block when focused.
    assert "## System Components" not in out


@pytest.mark.asyncio
async def test_get_workflow_structure_with_structure_data_override(
    workflow_tree: Path,
) -> None:
    """Caller-provided structure_data bypasses the static dict.

    FastMCP enforces the Literal enum on ``component`` so the override
    must be applied to one of the known component slots (``env`` here).
    The point of structure_data is to swap in custom info for a known
    section — typically what hosted callers want when they have the
    real on-disk structure data already in hand.
    """
    mcp = _make_server(workflow_root=workflow_tree)
    custom = {
        "env": {
            "desc": "Custom env description",
            "subdirs": ["alpha", "beta"],
            "platforms": ["FOO", "BAR"],
            "note": "custom note",
        }
    }
    out = await _call_tool(
        mcp,
        "get_workflow_structure",
        {"component": "env", "structure_data": custom},
    )
    assert "## Component: env" in out
    assert "Custom env description" in out
    assert "alpha, beta" in out
    assert "FOO, BAR" in out
    assert "custom note" in out


def test_render_full_structure_falls_back_when_component_missing() -> None:
    """Implementation-level test: when a focused component isn't in
    the structure dict the renderer falls back to the full overview.

    Tested directly against the helper since FastMCP's enum
    validation prevents reaching this branch via the tool layer.
    """
    structure = {"jobs": {"desc": "j", "note": "n"}}
    out = workflow_info._tool_get_workflow_structure(
        Path("/tmp/wf"),
        component="ghost_not_in_dict",
        structure_data=structure,
    )
    assert "## System Components" in out
    assert "### jobs/" in out


# ── get_system_configs ────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_system_configs_specific_platform_filesystem(
    workflow_tree: Path,
) -> None:
    mcp = _make_server(workflow_root=workflow_tree)
    out = await _call_tool(
        mcp, "get_system_configs", {"platform": "hera"}
    )
    assert "**Platform:** HERA" in out
    assert "## HERA Environment" in out
    assert "HERA_VAR=hera" in out
    assert "```bash" in out


@pytest.mark.asyncio
async def test_get_system_configs_unknown_platform_file_hint(
    workflow_tree: Path,
) -> None:
    """gaea is in the enum but GAEA.env doesn't exist (Node.js parity:
    surfaces "file not found" + content hint)."""
    mcp = _make_server(workflow_root=workflow_tree)
    out = await _call_tool(
        mcp, "get_system_configs", {"platform": "gaea"}
    )
    assert "Environment file not found" in out
    assert "Hint" in out
    assert "content" in out.lower()


@pytest.mark.asyncio
async def test_get_system_configs_all_platforms_listing(
    workflow_tree: Path,
) -> None:
    mcp = _make_server(workflow_root=workflow_tree)
    # platform omitted entirely → list every *.env
    out = await _call_tool(mcp, "get_system_configs", {})
    assert "## Available Platforms" in out
    assert "### HERA" in out
    assert "### WCOSS2" in out
    assert "### ORION" in out
    assert "**File:** env/HERA.env" in out


@pytest.mark.asyncio
async def test_get_system_configs_content_bypasses_filesystem(
    tmp_path: Path,
) -> None:
    """Caller-provided content trumps the filesystem read — and works
    even when the workflow_root doesn't exist."""
    mcp = _make_server(workflow_root=tmp_path / "missing")
    out = await _call_tool(
        mcp,
        "get_system_configs",
        {
            "platform": "hera",
            "content": "#!/bin/bash\nexport CONTENT_DRIVEN=1\n",
        },
    )
    assert "*Source: content parameter (remote access)*" in out
    assert "CONTENT_DRIVEN=1" in out


@pytest.mark.asyncio
async def test_get_system_configs_content_truncates_at_2000_bytes(
    tmp_path: Path,
) -> None:
    """The Node.js source slices content at 2000 bytes — preserve."""
    mcp = _make_server(workflow_root=tmp_path / "missing")
    big = "x" * 5000
    out = await _call_tool(
        mcp,
        "get_system_configs",
        {"platform": "hera", "content": big},
    )
    assert "x" * workflow_info.MAX_ENV_PREVIEW_BYTES in out
    # And NOT longer than the truncated body (allow some markdown chrome)
    assert "x" * 2001 not in out.replace("```", "").replace("\n", "")


@pytest.mark.asyncio
async def test_get_system_configs_config_type_modules_block(
    workflow_tree: Path,
) -> None:
    mcp = _make_server(workflow_root=workflow_tree)
    out = await _call_tool(
        mcp,
        "get_system_configs",
        {"platform": "hera", "config_type": "modules"},
    )
    assert "## Module Configuration" in out
    assert "modulefiles" in out
    assert "module_gwsetup" in out
    # Should NOT include the resources / paths block when filtered
    assert "## Resource Configuration" not in out
    assert "## Path Configuration" not in out


@pytest.mark.asyncio
async def test_get_system_configs_config_type_paths_block(
    workflow_tree: Path,
) -> None:
    mcp = _make_server(workflow_root=workflow_tree)
    out = await _call_tool(
        mcp, "get_system_configs", {"config_type": "paths"}
    )
    assert "## Path Configuration" in out
    # Resolved workflow_root surfaces as HOMEgfs value
    assert str(workflow_tree.resolve()) in out
    assert "${HOMEgfs}/jobs" in out


@pytest.mark.asyncio
async def test_get_system_configs_config_type_all_includes_every_block(
    workflow_tree: Path,
) -> None:
    mcp = _make_server(workflow_root=workflow_tree)
    out = await _call_tool(
        mcp,
        "get_system_configs",
        {"platform": "hera", "config_type": "all"},
    )
    assert "## Module Configuration" in out
    assert "## Resource Configuration" in out
    assert "## Path Configuration" in out


@pytest.mark.asyncio
async def test_get_system_configs_missing_env_dir_surfaces_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_WORKFLOW_ROOT", str(tmp_path / "no_workflow"))
    mcp = _make_server(workflow_root=tmp_path / "no_workflow")
    out = await _call_tool(mcp, "get_system_configs", {})
    assert "Could not read env directory" in out


# ── describe_component (filesystem search) ─────────────────────


@pytest.mark.asyncio
async def test_describe_component_finds_dev_jobs_first(
    workflow_tree: Path,
) -> None:
    mcp = _make_server(workflow_root=workflow_tree)
    out = await _call_tool(
        mcp, "describe_component", {"component": "JGFS_FORECAST"}
    )
    assert "# Component: JGFS_FORECAST" in out
    assert "**Type:** File" in out
    # Path uses ${HOMEgfs} prefix — and dev/jobs takes priority
    assert "${HOMEgfs}/dev/jobs/JGFS_FORECAST" in out
    assert "**Size:**" in out


@pytest.mark.asyncio
async def test_describe_component_finds_dev_scripts(
    workflow_tree: Path,
) -> None:
    mcp = _make_server(workflow_root=workflow_tree)
    out = await _call_tool(
        mcp, "describe_component", {"component": "exgfs_forecast.sh"}
    )
    assert "${HOMEgfs}/dev/scripts/exgfs_forecast.sh" in out


@pytest.mark.asyncio
async def test_describe_component_falls_back_to_legacy_ush(
    workflow_tree: Path,
) -> None:
    """Files only present under the legacy ``ush/`` path are found."""
    mcp = _make_server(workflow_root=workflow_tree)
    out = await _call_tool(
        mcp, "describe_component", {"component": "detect_machine.sh"}
    )
    assert "${HOMEgfs}/ush/detect_machine.sh" in out


@pytest.mark.asyncio
async def test_describe_component_directory_listing(
    workflow_tree: Path,
) -> None:
    """A directory hit shows item count + content listing."""
    mcp = _make_server(workflow_root=workflow_tree)
    out = await _call_tool(
        mcp, "describe_component", {"component": "archive"}
    )
    # parm/archive directory found via legacy path
    assert "**Type:** Directory" in out
    assert "**Contents:** 1 items" in out
    assert "config1.yaml" in out


@pytest.mark.asyncio
async def test_describe_component_file_with_show_content(
    workflow_tree: Path,
) -> None:
    mcp = _make_server(workflow_root=workflow_tree)
    out = await _call_tool(
        mcp,
        "describe_component",
        {"component": "JGFS_FORECAST", "show_content": True},
    )
    assert "## Content Preview" in out
    assert "STEP=fcst" in out


@pytest.mark.asyncio
async def test_describe_component_not_found_lists_search_paths(
    workflow_tree: Path,
) -> None:
    mcp = _make_server(workflow_root=workflow_tree)
    out = await _call_tool(
        mcp, "describe_component", {"component": "ghost_does_not_exist"}
    )
    assert "Component not found" in out
    assert "Searched paths:" in out
    # Verify all 12 search paths surface
    for needed in (
        "dev/jobs",
        "dev/scripts",
        "dev/parm",
        "dev/parm/config/gfs",
        "dev/parm/config/gcafs",
        "dev/job_cards",
        "dev/job_cards/rocoto",
        "/jobs/ghost",
        "/scripts/ghost",
        "/ush/ghost",
        "/parm/ghost",
    ):
        assert needed in out, needed
    assert "Hint" in out
    assert "content" in out.lower()


# ── describe_component (content-driven path) ──────────────────


@pytest.mark.asyncio
async def test_describe_component_content_driven_python(
    tmp_path: Path,
) -> None:
    """When ``content`` is provided, the tool analyses it directly —
    no filesystem access happens."""
    mcp = _make_server(workflow_root=tmp_path / "missing")
    src = (
        "#!/usr/bin/env python3\n"
        "# Description: example python tool\n"
        "import sys\n"
        "print(sys.version)\n"
    )
    out = await _call_tool(
        mcp,
        "describe_component",
        {"component": "tool.py", "content": src},
    )
    assert "Source:** Content provided via parameter" in out
    assert "**Lines:** 5" in out  # 4 lines + trailing empty after \n
    assert "**Size:**" in out
    assert "**Shebang:**" in out
    assert "**Language:** Python" in out
    # Description line surfaces under Purpose
    assert "## Purpose" in out
    assert "Description: example python tool" in out


@pytest.mark.asyncio
async def test_describe_component_content_driven_bash_with_show_content(
    tmp_path: Path,
) -> None:
    mcp = _make_server(workflow_root=tmp_path / "missing")
    src = "#!/bin/bash\n# Synopsis: bash example\nset -e\necho hi\n"
    out = await _call_tool(
        mcp,
        "describe_component",
        {
            "component": "ex.sh",
            "content": src,
            "show_content": True,
            "file_type": "file",
        },
    )
    assert "**Type:** file" in out
    assert "**Language:** Bash/Shell" in out
    assert "## Content Preview" in out
    assert "set -e" in out


@pytest.mark.asyncio
async def test_describe_component_content_no_shebang_unknown_language(
    tmp_path: Path,
) -> None:
    mcp = _make_server(workflow_root=tmp_path / "missing")
    out = await _call_tool(
        mcp,
        "describe_component",
        {"component": "data.txt", "content": "just some text\nno shebang\n"},
    )
    assert "**Language:** Unknown" in out
    # No shebang line rendered
    assert "**Shebang:**" not in out


@pytest.mark.asyncio
async def test_describe_component_content_long_file_truncates_preview(
    tmp_path: Path,
) -> None:
    mcp = _make_server(workflow_root=tmp_path / "missing")
    src = "\n".join(f"line {i}" for i in range(150))
    out = await _call_tool(
        mcp,
        "describe_component",
        {
            "component": "long.py",
            "content": src,
            "show_content": True,
        },
    )
    assert "## Content Preview" in out
    # Truncation message — 150 lines, 50 shown, 100 remaining
    assert "100 more lines" in out


# ── workflow_root resolution ──────────────────────────────────


def test_resolve_workflow_root_prefers_explicit_arg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MCP_WORKFLOW_ROOT", "/should/not/win")
    monkeypatch.setenv("HOMEgfs", "/should/not/win/either")
    resolved = workflow_info._resolve_workflow_root(tmp_path)
    assert resolved == tmp_path.resolve()


def test_resolve_workflow_root_prefers_mcp_env_over_homegfs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "mcp_root"
    target.mkdir()
    monkeypatch.setenv("MCP_WORKFLOW_ROOT", str(target))
    monkeypatch.setenv("HOMEgfs", "/should/lose")
    resolved = workflow_info._resolve_workflow_root(None)
    assert resolved == target.resolve()


def test_resolve_workflow_root_falls_back_to_homegfs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("MCP_WORKFLOW_ROOT", raising=False)
    target = tmp_path / "homegfs"
    target.mkdir()
    monkeypatch.setenv("HOMEgfs", str(target))
    resolved = workflow_info._resolve_workflow_root(None)
    assert resolved == target.resolve()


def test_resolve_workflow_root_default_when_envs_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MCP_WORKFLOW_ROOT", raising=False)
    monkeypatch.delenv("HOMEgfs", raising=False)
    resolved = workflow_info._resolve_workflow_root(None)
    assert resolved.name == "global-workflow"


# ── pure-function helpers ─────────────────────────────────────


def test_detect_language_shebang_python() -> None:
    assert workflow_info._detect_language(
        "import sys\nprint('x')\n", "#!/usr/bin/env python3"
    ) == "Python"


def test_detect_language_shebang_bash() -> None:
    assert workflow_info._detect_language(
        "echo hi\n", "#!/bin/bash"
    ) == "Bash/Shell"


def test_detect_language_imports_only() -> None:
    assert workflow_info._detect_language(
        "import os\n", ""
    ) == "Python"


def test_detect_language_unknown() -> None:
    assert workflow_info._detect_language("just text\n", "") == "Unknown"


def test_find_purpose_line_finds_description() -> None:
    lines = ["# Description: foo", "x = 1"]
    assert workflow_info._find_purpose_line(lines) == "# Description: foo"


def test_find_purpose_line_finds_purpose() -> None:
    lines = ["other", "# PURPOSE: bar", "x"]
    assert workflow_info._find_purpose_line(lines) == "# PURPOSE: bar"


def test_find_purpose_line_finds_synopsis() -> None:
    lines = ["# Synopsis: test"]
    assert workflow_info._find_purpose_line(lines) == "# Synopsis: test"


def test_find_purpose_line_returns_none_when_absent() -> None:
    assert workflow_info._find_purpose_line(["x = 1", "y = 2"]) is None


def test_describe_search_paths_priority_order(tmp_path: Path) -> None:
    paths = workflow_info._describe_search_paths(tmp_path, "comp")
    assert len(paths) == 12
    names = [str(p.relative_to(tmp_path)) for p in paths]
    # Verify dev/ paths come first in priority order
    assert names[0] == os.path.join("dev", "jobs", "comp")
    assert names[1] == os.path.join("dev", "scripts", "comp")
    assert names[2] == os.path.join("dev", "parm", "comp")
    assert names[3] == os.path.join("dev", "parm", "config", "gfs", "comp")
    assert names[4] == os.path.join("dev", "parm", "config", "gcafs", "comp")
    # Legacy paths in the back half
    assert names[7] == os.path.join("jobs", "comp")
    assert names[10] == os.path.join("parm", "comp")
    assert names[11] == "comp"


def test_abbrev_path_replaces_workflow_root(tmp_path: Path) -> None:
    sub = tmp_path / "dev" / "jobs" / "JGFS"
    assert workflow_info._abbrev_path(sub, tmp_path) == "${HOMEgfs}/dev/jobs/JGFS"


def test_abbrev_path_unrelated_path_is_unchanged(tmp_path: Path) -> None:
    other = Path("/some/elsewhere/file")
    assert workflow_info._abbrev_path(other, tmp_path) == "/some/elsewhere/file"
