"""Workflow info tools (Requirements 10.1 – 10.5, Task 15 Phase B10b).

Python port of the 3 tools in
``mcp_server_node/src/tools/WorkflowInfoTools.js``. Tool names, input
schemas, and output shapes match the Node.js source so the parity
framework can compare results side-by-side.

These tools are intentionally lightweight — they perform NO database
access. They read from the local global-workflow tree on disk to
report system structure, platform-specific environment configurations,
and per-component metadata. For graph-enriched component
explanations, callers should use
``operational.explain_workflow_component`` instead.

Tool overview
-------------

* ``get_workflow_structure`` — pure-static description of the global
  workflow's top-level layout (jobs, scripts, parm, ush, sorc, env,
  docs). The structure dict is ported verbatim from Node.js so the
  rendered text is byte-identical under parity. ``component`` filters
  to a single section; ``structure_data`` overrides the static dict
  for remote / hosted callers that want to drive the rendering with
  pre-computed data.

* ``get_system_configs`` — platform-specific HPC configuration. With
  ``platform={hera, hercules, orion, wcoss2, gaea}`` reads
  ``{workflow_root}/env/{PLATFORM}.env`` and surfaces the first 2 KB
  in a fenced block. With ``platform`` omitted (or ``"all"``) lists
  every ``*.env`` file in the env directory. ``content`` bypasses the
  filesystem entirely. ``config_type`` adds Module / Resource / Path
  Configuration appendix blocks (``"all"`` includes every block).

* ``describe_component`` — locate a component (file or directory)
  inside the global-workflow tree by searching 12 well-known paths
  (the Phase 27A ``dev/`` layout takes priority over the legacy
  layout). Reports type, size, directory contents preview (first 20
  entries), and optional file content preview (first 50 lines) when
  ``show_content=true``. ``content`` bypasses the filesystem and
  drives the analysis directly.

Degraded-mode contract (Requirement 1.7)
----------------------------------------

The whole module is data-access-free — ``data=None`` is fine for
every tool. When the workflow_root is not bind-mounted on the
hosted Python runtime:

* ``get_workflow_structure`` works fine — the structure is static.
* ``get_system_configs`` returns a friendly "Could not read env
  directory" line plus the platform-omitted listing when invoked
  without ``content``. Callers wanting actual config bytes pass
  ``content=...``.
* ``describe_component`` returns its standard "Component not found"
  message listing all searched paths and a hint pointing at
  ``content=...``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Literal

from fastmcp import FastMCP

log = logging.getLogger(__name__)


# ── constants ──────────────────────────────────────────────────────


#: Component enum values for ``get_workflow_structure``. Mirrors the
#: Node.js schema exactly.
COMPONENT_VALUES: tuple[str, ...] = (
    "jobs",
    "scripts",
    "parm",
    "ush",
    "sorc",
    "docs",
    "env",
)

#: Platform enum values for ``get_system_configs.platform``. ``"all"``
#: triggers the directory-listing path. Mirrors Node.js exactly.
PLATFORM_VALUES: tuple[str, ...] = (
    "hera",
    "hercules",
    "orion",
    "wcoss2",
    "gaea",
    "all",
)

#: Config-type enum for ``get_system_configs.config_type``.
CONFIG_TYPE_VALUES: tuple[str, ...] = (
    "modules",
    "resources",
    "paths",
    "all",
)

#: File-type hint enum for ``describe_component.file_type``.
FILE_TYPE_VALUES: tuple[str, ...] = ("file", "directory")

#: Default workflow root, relative to the project working tree. The
#: Node.js source falls back to this same path when neither
#: ``MCP_WORKFLOW_ROOT`` nor ``HOMEgfs`` is set.
DEFAULT_WORKFLOW_ROOT: str = "supported_repos/global-workflow"

#: Maximum size (bytes) of an env-file body inlined in the response.
#: Mirrors the Node.js ``content.slice(0, 2000)`` limit so the rendered
#: text is byte-identical under parity.
MAX_ENV_PREVIEW_BYTES: int = 2000

#: Maximum number of lines previewed when ``show_content=true``.
MAX_CONTENT_PREVIEW_LINES: int = 50

#: Maximum number of entries listed for a directory in
#: ``describe_component``.
MAX_DIRECTORY_ENTRIES: int = 20


#: Verbatim port of the Node.js ``structure`` dict in
#: ``getWorkflowStructure``. Field order matches the JS object
#: insertion order so per-component rendering is byte-compatible.
_STATIC_STRUCTURE: dict[str, dict[str, Any]] = {
    "jobs": {
        "desc": "Production Job Control Language (JCL) scripts",
        "pattern": "J*",
        "note": "Entry points for operational jobs",
    },
    "scripts": {
        "desc": "Execution scripts called by jobs",
        "pattern": "ex*.{sh,py}",
        "note": "Implementation logic for each component",
    },
    "parm": {
        "desc": "Parameter files and configuration templates",
        "subdirs": ["archive", "gdas", "post", "ufs", "wave", "product"],
        "note": "System configuration templates",
    },
    "ush": {
        "desc": "Utility shell scripts and functions",
        "key_files": ["detect_machine.sh", "jjob_header.sh", "bash_utils.sh"],
        "note": "Shared utilities and platform detection",
    },
    "sorc": {
        "desc": "Source code and build infrastructure",
        "key_files": ["build_all.sh", "CMakeLists.txt"],
        "subdirs": ["ufs_model.fd", "gfs_utils.fd", "gsi_*.fd", "wxflow"],
        "note": "Source compilation and dependencies",
    },
    "env": {
        "desc": "HPC platform environment configurations",
        "platforms": ["WCOSS2", "HERA", "HERCULES", "ORION", "GAEA"],
        "note": "Platform-specific settings",
    },
    "docs": {
        "desc": "Documentation and user guides",
        "note": "System documentation",
    },
}


# ── helpers — workflow root resolution ─────────────────────────────


def _resolve_workflow_root(workflow_root: str | os.PathLike[str] | None) -> Path:
    """Pick the workflow_root path with the same precedence as Node.js.

    Order: explicit constructor arg → ``MCP_WORKFLOW_ROOT`` env var →
    ``HOMEgfs`` env var → :data:`DEFAULT_WORKFLOW_ROOT`. The path is
    resolved (made absolute) so downstream code can rely on
    ``Path.is_dir`` etc. without surprises from the cwd shifting.
    """
    candidate: str | os.PathLike[str] | None = workflow_root
    if candidate is None:
        candidate = os.environ.get("MCP_WORKFLOW_ROOT")
    if not candidate:
        candidate = os.environ.get("HOMEgfs")
    if not candidate:
        candidate = DEFAULT_WORKFLOW_ROOT
    return Path(candidate).resolve()


# ── helpers — pure-text rendering (used by all 3 tools) ────────────


def _render_component_block(component: str, info: dict[str, Any]) -> str:
    """Render one section of ``get_workflow_structure`` (component focus)."""
    lines: list[str] = [f"## Component: {component}\n"]
    lines.append(f"**Description:** {info.get('desc', '')}\n")
    if info.get("pattern"):
        lines.append(f"**Pattern:** {info['pattern']}")
    if info.get("subdirs"):
        lines.append(
            "**Subdirectories:** " + ", ".join(info["subdirs"])
        )
    if info.get("key_files"):
        lines.append(
            "**Key Files:** " + ", ".join(info["key_files"])
        )
    if info.get("platforms"):
        lines.append(
            "**Platforms:** " + ", ".join(info["platforms"])
        )
    lines.append(f"\n**Note:** {info.get('note', '')}")
    return "\n".join(lines).rstrip() + "\n"


def _render_full_structure(structure: dict[str, dict[str, Any]]) -> str:
    """Render the no-component-focus full overview."""
    lines = ["## System Components\n"]
    for key, info in structure.items():
        lines.append(f"### {key}/")
        lines.append(info.get("desc", ""))
        lines.append(f"*{info.get('note', '')}*\n")

    lines.append("## Execution Flow\n")
    lines.append(
        "1. **Jobs (jobs/J*)** - Entry points defining environment"
    )
    lines.append("2. **Scripts (scripts/ex*)** - Implementation logic")
    lines.append("3. **Utilities (ush/)** - Shared functions")
    lines.append("4. **Parameters (parm/)** - Configuration templates")
    lines.append("5. **Build System (sorc/)** - Source compilation")
    return "\n".join(lines).rstrip() + "\n"


def _detect_language(content: str, first_line: str) -> str:
    """Replicate the Node.js shebang/import-based language detection."""
    has_python = (
        "python" in first_line.lower()
        or "import " in content
    )
    has_bash = (
        "bash" in first_line.lower()
        or "#!/bin/sh" in content
    )
    if has_python:
        return "Python"
    if has_bash:
        return "Bash/Shell"
    return "Unknown"


def _find_purpose_line(lines: list[str]) -> str | None:
    """Pick the first line containing Description / PURPOSE / Synopsis.

    Mirrors the Node.js ``lines.find(...)`` loop. Returns the trimmed
    line or ``None`` when no candidate matches.
    """
    for line in lines:
        if (
            "Description" in line
            or "PURPOSE" in line
            or "Synopsis" in line
        ):
            return line.strip()
    return None


def _content_preview_block(lines: list[str]) -> str:
    """Render the ``## Content Preview`` block (first 50 lines)."""
    visible = lines[:MAX_CONTENT_PREVIEW_LINES]
    out = ["", "## Content Preview\n", "```", "\n".join(visible)]
    if len(lines) > MAX_CONTENT_PREVIEW_LINES:
        out.append(
            f"\n... ({len(lines) - MAX_CONTENT_PREVIEW_LINES} more lines)"
        )
    out.append("```")
    return "\n".join(out) + "\n"


# ── helpers — describe_component search paths ─────────────────────


def _describe_search_paths(
    workflow_root: Path, component: str
) -> list[Path]:
    """Build the priority-ordered search list for describe_component.

    Order is identical to Node.js ``searchPaths`` array — the Phase 27A
    ``dev/`` layout takes priority over the legacy paths.
    """
    return [
        workflow_root / "dev" / "jobs" / component,
        workflow_root / "dev" / "scripts" / component,
        workflow_root / "dev" / "parm" / component,
        workflow_root / "dev" / "parm" / "config" / "gfs" / component,
        workflow_root / "dev" / "parm" / "config" / "gcafs" / component,
        workflow_root / "dev" / "job_cards" / component,
        workflow_root / "dev" / "job_cards" / "rocoto" / component,
        # Legacy fallbacks
        workflow_root / "jobs" / component,
        workflow_root / "scripts" / component,
        workflow_root / "ush" / component,
        workflow_root / "parm" / component,
        workflow_root / component,
    ]


def _abbrev_path(path: Path, workflow_root: Path) -> str:
    """Replace the workflow root prefix with ``${HOMEgfs}`` for output.

    Mirrors the Node.js ``searchPath.replace(this.workflowRoot, '${HOMEgfs}')``
    — the leading slash is preserved so the rendered path looks like
    ``${HOMEgfs}/dev/jobs/...``.
    """
    try:
        suffix = path.relative_to(workflow_root)
    except ValueError:
        return path.as_posix()
    return "${HOMEgfs}/" + suffix.as_posix()


# ── tool implementations ──────────────────────────────────────────


def _tool_get_workflow_structure(
    workflow_root: Path,
    *,
    component: str | None,
    structure_data: dict[str, Any] | None,
) -> str:
    """Implementation of ``get_workflow_structure``."""
    structure: dict[str, dict[str, Any]]
    if structure_data is not None:
        # Caller-provided structure overrides the default. We accept
        # any dict shape — the Node.js handler does no validation.
        structure = dict(structure_data)
    else:
        structure = _STATIC_STRUCTURE

    output_lines = ["# Global Workflow Structure\n"]
    output_lines.append(f"**Root:** {workflow_root}\n")

    if component and component in structure:
        output_lines.append(
            _render_component_block(component, structure[component])
        )
    else:
        output_lines.append(_render_full_structure(structure))

    return "\n".join(output_lines).rstrip() + "\n"


def _tool_get_system_configs(
    workflow_root: Path,
    *,
    platform: str | None,
    config_type: str | None,
    content: str | None,
) -> str:
    """Implementation of ``get_system_configs``."""
    env_dir = workflow_root / "env"
    output_lines = ["# System Configurations\n"]

    if platform:
        output_lines.append(f"**Platform:** {platform.upper()}")
    if config_type:
        output_lines.append(f"**Config Type:** {config_type}")
    output_lines.append("")

    # Priority: caller-provided content > filesystem read
    if content is not None:
        platform_label = platform.upper() if platform else "Provided"
        output_lines.append(f"## {platform_label} Environment\n")
        output_lines.append("*Source: content parameter (remote access)*\n")
        output_lines.append("```bash")
        output_lines.append(content[:MAX_ENV_PREVIEW_BYTES])
        output_lines.append("```\n")
    elif platform and platform != "all":
        env_file = env_dir / f"{platform.upper()}.env"
        try:
            file_content = env_file.read_text(encoding="utf-8")
            output_lines.append(f"## {platform.upper()} Environment\n")
            output_lines.append("```bash")
            output_lines.append(file_content[:MAX_ENV_PREVIEW_BYTES])
            output_lines.append("```\n")
        except OSError:
            output_lines.append(f"Environment file not found: {env_file}\n")
            output_lines.append(
                "**Hint:** Use 'content' parameter to provide env file "
                "content directly for remote access.\n"
            )
    else:
        # No platform → list every *.env file in env_dir.
        try:
            env_files = sorted(
                f.name for f in env_dir.iterdir()
                if f.is_file() and f.suffix == ".env"
            )
            output_lines.append("## Available Platforms\n")
            for fname in env_files:
                platform_name = fname[:-4]  # strip ".env"
                output_lines.append(f"### {platform_name}")
                output_lines.append(f"**File:** env/{fname}\n")
        except OSError:
            output_lines.append("Could not read env directory")

    # Config-type-specific appendix blocks. ``"all"`` includes every block;
    # a single value includes just its own.
    if config_type in ("modules", "all"):
        output_lines.append("## Module Configuration\n")
        output_lines.append("Module files are located in: modulefiles/")
        output_lines.append("Use: `module use ${HOMEgfs}/modulefiles`")
        output_lines.append(
            "Load: `module load module_gwsetup.${MACHINE_ID}`\n"
        )

    if config_type in ("resources", "all"):
        output_lines.append("## Resource Configuration\n")
        output_lines.append(
            "Resource requirements defined in: parm/config/"
        )
        output_lines.append(
            "Platform-specific resources in workflow XML\n"
        )

    if config_type in ("paths", "all"):
        output_lines.append("## Path Configuration\n")
        output_lines.append(f"- **HOMEgfs:** {workflow_root}")
        output_lines.append("- **Jobs:** ${HOMEgfs}/jobs")
        output_lines.append("- **Scripts:** ${HOMEgfs}/scripts")
        output_lines.append("- **Utilities:** ${HOMEgfs}/ush")
        output_lines.append("- **Parameters:** ${HOMEgfs}/parm")
        output_lines.append("- **Source:** ${HOMEgfs}/sorc\n")

    return "\n".join(output_lines).rstrip() + "\n"


def _render_describe_from_content(
    component: str,
    content: str,
    *,
    file_type: str | None,
    show_content: bool,
) -> str:
    """Render ``describe_component`` when caller passes ``content``.

    Mirrors the Node.js Priority-1 branch: byte length, line count,
    shebang, language inference, purpose-line extraction, optional
    content preview.
    """
    lines = ["# Component: " + component + "\n"]
    type_label = file_type or "File (inferred)"
    lines.append(
        "**Source:** Content provided via parameter "
        "(container-compatible mode)"
    )
    lines.append(f"**Type:** {type_label}")
    body_lines = content.split("\n")
    lines.append(f"**Lines:** {len(body_lines)}")
    lines.append(f"**Size:** {len(content)} bytes\n")

    first_line = body_lines[0] if body_lines else ""
    if first_line.startswith("#!"):
        lines.append(f"**Shebang:** {first_line}")
    lines.append(
        f"**Language:** {_detect_language(content, first_line)}\n"
    )

    purpose = _find_purpose_line(body_lines)
    if purpose:
        lines.append("## Purpose\n")
        lines.append(purpose + "\n")

    if show_content:
        lines.append(_content_preview_block(body_lines))

    return "\n".join(lines).rstrip() + "\n"


def _render_describe_from_filesystem(
    workflow_root: Path,
    component: str,
    *,
    show_content: bool,
) -> str:
    """Render ``describe_component`` after a filesystem search.

    Walks the 12 priority-ordered search paths; on first hit emits a
    rendered block (file size + optional content preview, or directory
    contents preview). On miss emits the searched-paths list + content
    parameter hint, exactly like the Node.js path.
    """
    output_lines = ["# Component: " + component + "\n"]
    search_paths = _describe_search_paths(workflow_root, component)

    found_path: Path | None = None
    found_is_dir = False
    found_size: int | None = None

    for candidate in search_paths:
        try:
            if candidate.is_symlink():
                # ``Path.is_dir`` follows symlinks like Node.js ``fs.stat``.
                pass
            if candidate.is_dir():
                found_path = candidate
                found_is_dir = True
                break
            if candidate.is_file():
                found_path = candidate
                found_is_dir = False
                found_size = candidate.stat().st_size
                break
        except OSError:
            continue

    if found_path is None:
        output_lines.append("Component not found in standard locations.\n")
        output_lines.append("Searched paths:")
        for p in search_paths:
            output_lines.append(f"- {p}")
        output_lines.append("")
        output_lines.append(
            "**Hint:** Use the 'content' parameter to provide file "
            "content directly for remote/container access."
        )
        return "\n".join(output_lines).rstrip() + "\n"

    output_lines.append(
        f"**Path:** {_abbrev_path(found_path, workflow_root)}"
    )
    output_lines.append(
        "**Type:** " + ("Directory" if found_is_dir else "File")
    )

    if not found_is_dir:
        output_lines.append(f"**Size:** {found_size} bytes")
        if show_content:
            try:
                file_text = found_path.read_text(
                    encoding="utf-8", errors="replace"
                )
                output_lines.append(
                    _content_preview_block(file_text.split("\n"))
                )
            except OSError:
                output_lines.append("\nCould not read file content")
    else:
        try:
            entries = sorted(p.name for p in found_path.iterdir())
        except OSError:
            output_lines.append("\nCould not list directory contents")
            return "\n".join(output_lines).rstrip() + "\n"

        output_lines.append(f"**Contents:** {len(entries)} items\n")
        output_lines.append("### Files/Directories\n")
        for item in entries[:MAX_DIRECTORY_ENTRIES]:
            output_lines.append(f"- {item}")
        if len(entries) > MAX_DIRECTORY_ENTRIES:
            output_lines.append(
                f"\n... ({len(entries) - MAX_DIRECTORY_ENTRIES} more items)"
            )

    return "\n".join(output_lines).rstrip() + "\n"


def _tool_describe_component(
    workflow_root: Path,
    *,
    component: str,
    show_content: bool,
    content: str | None,
    file_type: str | None,
) -> str:
    """Implementation of ``describe_component``."""
    if content is not None:
        return _render_describe_from_content(
            component,
            content,
            file_type=file_type,
            show_content=show_content,
        )
    return _render_describe_from_filesystem(
        workflow_root, component, show_content=show_content
    )


def _error_text(message: str) -> str:
    """Match the Node.js error envelope verbatim."""
    return f"Error: {message}\n"


# ── public entrypoint ──────────────────────────────────────────────


def register(
    mcp: FastMCP,
    data: Any = None,
    *,
    workflow_root: str | os.PathLike[str] | None = None,
) -> None:
    """Register all 3 workflow-info tools on ``mcp``.

    Parameters
    ----------
    mcp
        The FastMCP server instance.
    data
        Unused by this module — kept in the signature for the uniform
        ``register(mcp, data)`` contract that
        ``mcp_server._register_module`` invokes. The workflow-info
        tools are intentionally lightweight and have no database
        dependencies.
    workflow_root
        Optional override for the global-workflow root directory.
        When ``None`` resolves via the same precedence as Node.js:
        ``MCP_WORKFLOW_ROOT`` env var → ``HOMEgfs`` env var →
        :data:`DEFAULT_WORKFLOW_ROOT`. The directory is allowed to be
        missing on the hosted Python runtime — the tools degrade
        gracefully (``get_workflow_structure`` is fully static;
        ``get_system_configs`` and ``describe_component`` accept
        ``content=...`` to bypass filesystem entirely).
    """
    del data  # explicitly unused — kept for register-signature parity
    root = _resolve_workflow_root(workflow_root)

    @mcp.tool(
        name="get_workflow_structure",
        description=(
            "Get the structure and overview of the global workflow "
            "system."
        ),
    )
    async def get_workflow_structure(
        component: Literal[
            "jobs", "scripts", "parm", "ush", "sorc", "docs", "env"
        ]
        | None = None,
        structure_data: dict[str, Any] | None = None,
    ) -> str:
        try:
            return _tool_get_workflow_structure(
                root,
                component=component,
                structure_data=structure_data,
            )
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("get_workflow_structure failed")
            return _error_text(f"getting workflow structure: {exc}")

    @mcp.tool(
        name="get_system_configs",
        description=(
            "Get system configuration information for different HPC "
            "platforms."
        ),
    )
    async def get_system_configs(
        platform: Literal[
            "hera", "hercules", "orion", "wcoss2", "gaea", "all"
        ]
        | None = None,
        config_type: Literal["modules", "resources", "paths", "all"]
        | None = None,
        content: str | None = None,
    ) -> str:
        try:
            return _tool_get_system_configs(
                root,
                platform=platform,
                config_type=config_type,
                content=content,
            )
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("get_system_configs failed")
            return _error_text(f"getting system configs: {exc}")

    @mcp.tool(
        name="describe_component",
        description=(
            "Get basic description of a workflow component "
            "(file system only)."
        ),
    )
    async def describe_component(
        component: str,
        show_content: bool = False,
        content: str | None = None,
        file_type: Literal["file", "directory"] | None = None,
    ) -> str:
        try:
            return _tool_describe_component(
                root,
                component=component,
                show_content=show_content,
                content=content,
                file_type=file_type,
            )
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("describe_component failed")
            return _error_text(f"describing component: {exc}")


__all__ = [
    "register",
    "COMPONENT_VALUES",
    "PLATFORM_VALUES",
    "CONFIG_TYPE_VALUES",
    "FILE_TYPE_VALUES",
    "DEFAULT_WORKFLOW_ROOT",
    "MAX_ENV_PREVIEW_BYTES",
    "MAX_CONTENT_PREVIEW_LINES",
    "MAX_DIRECTORY_ENTRIES",
]
