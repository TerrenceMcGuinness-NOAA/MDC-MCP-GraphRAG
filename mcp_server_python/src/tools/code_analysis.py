"""Code analysis tools (Requirements 5.1 – 5.7, Task 9 Phase B6).

Python port of the 6 tools in
``mcp_server_node/src/tools/CodeAnalysisTools.js``. Tool names and
input schemas match the Node.js ``registerWith`` block exactly so the
parity framework can compare results side-by-side.

The module wires into the FastMCP server via the standard
``register(mcp, data)`` entrypoint. ``data`` is the
``UnifiedDataAccess``-shaped facade the Python port uses; it exposes
``graph_db`` (``GraphDBProtocol``) and ``vector_db``
(``VectorDBProtocol``, optional — not consulted by this module
directly; enrichment lives in GraphRAGTools).

Design notes
------------

* The Node.js implementation calls rich helper methods on the graph
  facade (``findFileFunctions``, ``findImporters``, ``traceCallChain``,
  ``traceCrossLanguageChain`` and friends). The Python port talks
  directly to the ``GraphDBProtocol.query`` surface with inline
  openCypher so the implementation is backend-agnostic — Neptune today,
  anything the protocol accepts tomorrow.

* The 6 tools share a set of small, single-responsibility cypher
  queries wrapped by ``_file_symbols`` / ``_file_imports`` /
  ``_file_importers`` / ``_call_chain`` / ``_callers`` /
  ``_cross_language_nodes``. These helpers return plain dicts / lists,
  so unit tests can seed ``MockGraphDB`` with ``add_response`` fragment
  matches and exercise the rendering layer without a live Neptune.

* ``trace_execution_path`` and ``find_callers_callees`` use
  :class:`~src.graphrag.ggsr_traversal.GGSRTraversal` for the
  token-budget-aware weighted-context section (B3's first real
  exercise). The engine's ``budget_aware_neighborhood`` handles
  scoring + trimming; we render the scored results as a markdown
  table mirroring the Node.js weighted-traversal output shape.

* ``find_callers_callees`` with ``cross_language=True`` follows the
  SOURCES/INVOKES/EXECUTES/CALLS/USES/DEFINES edge set identical to
  the Node.js version and applies
  :data:`~src.graphrag.ggsr_traversal.BRIDGE_DECAY_OVERRIDE` when
  scoring cross-language hops (so a Shell→Fortran EXECUTES bridge
  decays more gently than a same-language hop).

* ``trace_full_execution_chain`` supports the ``languages`` filter
  (``["shell", "fortran", "python"]``) — it filters the expanded
  chain in Python after the graph walk so one database round-trip
  serves any language subset.

* Degraded-mode boot (``data=None``) — every tool returns a clear
  ``[ERROR]`` markdown message instead of crashing, matching the B5
  ``semantic_search`` pattern.

All tool return values are markdown strings, matching the Node.js
``TextContent`` block output.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Literal, Protocol

from fastmcp import FastMCP

from src.graphrag import (
    BRIDGE_DECAY_OVERRIDE,
    DEFAULT_TOKEN_BUDGET,
    GGSRScoredResult,
    GGSRTraversal,
    estimate_row_tokens,
)
from src.tenancy.resolver import get_current_tenant_or_none

log = logging.getLogger(__name__)


def _tenant():
    """Return the active tenant or None (for adapter kwarg)."""
    ctx = get_current_tenant_or_none()
    return ctx.tenant if ctx else None


# ── constants ───────────────────────────────────────────────────────────


#: Bounds on the ``depth`` parameter of ``analyze_code_structure``.
#: Matches the Node.js inputSchema ``minimum`` / ``maximum`` exactly.
ANALYZE_DEPTH_MIN: int = 1
ANALYZE_DEPTH_MAX: int = 3

#: Bounds on the ``max_depth`` parameter of ``find_dependencies`` and
#: ``trace_execution_path``.
DEPENDENCY_DEPTH_MIN: int = 1
DEPENDENCY_DEPTH_MAX: int = 5

#: Bounds on the ``max_depth`` parameter of ``trace_full_execution_chain``.
FULL_CHAIN_DEPTH_MIN: int = 1
FULL_CHAIN_DEPTH_MAX: int = 10

#: Bounds on the ``limit`` parameter of ``find_env_dependencies``. The
#: Node.js implementation clamps to 1..500.
ENV_LIMIT_MIN: int = 1
ENV_LIMIT_MAX: int = 500

#: Labels the graph assigns to nodes that represent a callable symbol.
#: Used to classify ``findFileSymbols`` rows into FUNCTION / CLASS.
FUNCTION_LABELS: frozenset[str] = frozenset({
    "Function",
    "PythonFunction",
    "FortranFunction",
    "FortranSubroutine",
    "FortranProgram",
    "CodeFunction",
})
CLASS_LABELS: frozenset[str] = frozenset({
    "Class",
    "PythonClass",
    "CodeClass",
})

#: Edge types traversed by ``trace_full_execution_chain`` and by
#: ``find_callers_callees(cross_language=True)``.
CROSS_LANGUAGE_EDGES: tuple[str, ...] = (
    "SOURCES",
    "INVOKES",
    "EXECUTES",
    "CALLS",
    "USES",
    "DEFINES",
)

#: Mapping from node label substring to logical language, used when
#: rendering cross-language chains.
LANGUAGE_LABEL_MAP: tuple[tuple[str, str], ...] = (
    ("Python", "python"),
    ("Fortran", "fortran"),
    ("Shell", "shell"),
    ("Rocoto", "shell"),
    ("Job", "shell"),
)


# ── data-layer protocol ─────────────────────────────────────────────────


class _DataAccess(Protocol):
    """Structural contract the code-analysis tools need from ``data``.

    Only ``graph_db`` is required; ``vector_db`` is accepted so the
    facade can be the same object the semantic_search module consumes.
    """

    graph_db: Any
    vector_db: Any | None


# ── public entrypoint ───────────────────────────────────────────────────


def register(mcp: FastMCP, data: Any = None, *, catalog: "Any | None" = None) -> None:
    """Register all 6 code-analysis tools on ``mcp``.

    Parameters
    ----------
    mcp
        The FastMCP server instance.
    data
        ``UnifiedDataAccess``-shaped facade. ``None`` triggers
        degraded-mode — tools return ``[ERROR]`` messages rather than
        crashing.
    """
    from src.tenancy.runtime import get_catalog as _get_catalog
    catalog = catalog or _get_catalog()
    from src.tools._tenant_helper import run_tenant_scoped

    @mcp.tool(
        name="analyze_code_structure",
        description=(
            "Analyze code structure, relationships, and dependencies "
            "for a specific file."
        ),
    )
    async def analyze_code_structure(
        file_path: str,
        include_dependencies: bool = True,
        depth: int = 2,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        tenant_id: str | None = None,
    ) -> str:
        return await run_tenant_scoped(
            tenant_id, catalog,
            lambda: _tool_analyze_code_structure(
                data, file_path=file_path,
                include_dependencies=include_dependencies,
                depth=_clamp(depth, ANALYZE_DEPTH_MIN, ANALYZE_DEPTH_MAX),
                token_budget=max(0, int(token_budget)),
            ),
        )

    @mcp.tool(
        name="find_dependencies",
        description=(
            "Find all dependencies (imports) and dependents (importers) "
            "for a file or module."
        ),
    )
    async def find_dependencies(
        target: str,
        direction: Literal["upstream", "downstream", "both"] = "both",
        max_depth: int = 3,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        tenant_id: str | None = None,
    ) -> str:
        return await run_tenant_scoped(
            tenant_id, catalog,
            lambda: _tool_find_dependencies(
                data, target=target, direction=direction,
                max_depth=_clamp(max_depth, DEPENDENCY_DEPTH_MIN, DEPENDENCY_DEPTH_MAX),
                token_budget=max(0, int(token_budget)),
            ),
        )

    @mcp.tool(
        name="trace_execution_path",
        description=(
            "Trace the execution path from a starting function through "
            "call chains."
        ),
    )
    async def trace_execution_path(
        function_name: str,
        file_path: str | None = None,
        max_depth: int = 3,
        include_callers: bool = False,
        include_weights: bool = True,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        tenant_id: str | None = None,
    ) -> str:
        return await run_tenant_scoped(
            tenant_id, catalog,
            lambda: _tool_trace_execution_path(
                data, function_name=function_name, file_path=file_path,
                max_depth=_clamp(max_depth, DEPENDENCY_DEPTH_MIN, DEPENDENCY_DEPTH_MAX),
                include_callers=include_callers, include_weights=include_weights,
                token_budget=max(0, int(token_budget)),
            ),
        )

    @mcp.tool(
        name="find_callers_callees",
        description=(
            "Find all functions that call a target function (callers) "
            "and functions it calls (callees)."
        ),
    )
    async def find_callers_callees(
        function_name: str,
        file_path: str | None = None,
        include_source: bool = False,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        cross_language: bool = False,
        tenant_id: str | None = None,
    ) -> str:
        return await run_tenant_scoped(
            tenant_id, catalog,
            lambda: _tool_find_callers_callees(
                data, function_name=function_name, file_path=file_path,
                include_source=include_source,
                token_budget=max(0, int(token_budget)),
                cross_language=cross_language,
            ),
        )

    @mcp.tool(
        name="trace_full_execution_chain",
        description=(
            "Trace complete execution chain across Shell, Python, and "
            "Fortran language boundaries. Starting from any node (J-Job, "
            "script, Fortran program, Python task), follows SOURCES, "
            "INVOKES, EXECUTES, CALLS, USES, and DEFINES edges to build "
            "the full execution tree."
        ),
    )
    async def trace_full_execution_chain(
        start: str,
        direction: Literal["forward", "reverse", "both"] = "forward",
        max_depth: int = 5,
        languages: list[Literal["shell", "fortran", "python"]] | None = None,
        tenant_id: str | None = None,
    ) -> str:
        return await run_tenant_scoped(
            tenant_id, catalog,
            lambda: _tool_trace_full_execution_chain(
                data, start=start, direction=direction,
                max_depth=_clamp(max_depth, FULL_CHAIN_DEPTH_MIN, FULL_CHAIN_DEPTH_MAX),
                languages=tuple(languages) if languages else None,
            ),
        )

    @mcp.tool(
        name="find_env_dependencies",
        description=(
            "Find all scripts that depend on or export a specific "
            "environment variable (uses Neo4j graph)."
        ),
    )
    async def find_env_dependencies(
        variable_name: str,
        show_exports: bool = True,
        limit: int = 50,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        tenant_id: str | None = None,
    ) -> str:
        return await run_tenant_scoped(
            tenant_id, catalog,
            lambda: _tool_find_env_dependencies(
                data, variable_name=variable_name, show_exports=show_exports,
                limit=_clamp(int(limit or 50), ENV_LIMIT_MIN, ENV_LIMIT_MAX),
                token_budget=max(0, int(token_budget)),
            ),
        )

    log.info(
        "registered code analysis tools: analyze_code_structure, "
        "find_dependencies, trace_execution_path, find_callers_callees, "
        "trace_full_execution_chain, find_env_dependencies"
    )


# ── analyze_code_structure ─────────────────────────────────────────────


async def _tool_analyze_code_structure(
    data: Any,
    *,
    file_path: str,
    include_dependencies: bool,
    depth: int,
    token_budget: int,
) -> str:
    if not file_path or not file_path.strip():
        return _error_text("file_path is required.")
    if data is None or getattr(data, "graph_db", None) is None:
        return _error_text(_DEGRADED_GRAPH_MSG)

    try:
        symbols = await _file_symbols(data.graph_db, file_path)
    except Exception as exc:
        log.warning("analyze_code_structure: symbol query failed: %s", exc)
        return _error_text(
            f"Error analyzing code structure: {exc}\n\n"
            "Graph database may not be fully populated."
        )

    if not symbols:
        basename = file_path.rsplit("/", 1)[-1]
        return (
            f"File not found: {file_path}\n\n"
            "Tip: Use semantic search to find similar files:\n"
            "```\n"
            f'search_documentation query:"{basename}"\n'
            "```\n"
        )

    functions = [s for s in symbols if s["type"] == "FUNCTION"]
    classes = [s for s in symbols if s["type"] == "CLASS"]

    lines: list[str] = [
        f"# Code Structure Analysis: {file_path}",
        "",
        "## Overview",
        f"- **Functions:** {len(functions)}",
        f"- **Classes:** {len(classes)}",
        f"- **Total Symbols:** {len(symbols)}",
        "",
    ]

    if functions:
        lines.append("## Functions")
        lines.append("")
        for func in functions[:10]:
            lines.append(f"### `{func['name']}`")
            doc = (func.get("docstring") or "").splitlines()
            if doc:
                lines.append(doc[0])
            if func.get("lineNumber"):
                lines.append(f"*Line {func['lineNumber']}*")
            lines.append("")
        if len(functions) > 10:
            lines.append(f"*... and {len(functions) - 10} more functions*")
            lines.append("")

    if classes:
        lines.append("## Classes")
        lines.append("")
        for cls in classes[:5]:
            lines.append(f"### `{cls['name']}`")
            doc = (cls.get("docstring") or "").splitlines()
            if doc:
                lines.append(doc[0])
            lines.append("")
        if len(classes) > 5:
            lines.append(f"*... and {len(classes) - 5} more classes*")
            lines.append("")

    if include_dependencies:
        try:
            imports = await _file_imports(data.graph_db, file_path)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("findFileImports failed: %s", exc)
            imports = []
        try:
            importers = await _file_importers(data.graph_db, file_path)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("findImporters failed: %s", exc)
            importers = []

        lines.append("## Dependencies")
        lines.append("")
        lines.append(f"### Imports ({len(imports)})")
        if imports:
            for imp in imports[:10]:
                lines.append(f"- `{imp}`")
            if len(imports) > 10:
                lines.append(f"- *... and {len(imports) - 10} more imports*")
        else:
            lines.append("*No imports found*")
        lines.append("")
        lines.append(f"### Imported By ({len(importers)})")
        if importers:
            for imp in importers[:10]:
                lines.append(f"- `{imp}`")
            if len(importers) > 10:
                lines.append(f"- *... and {len(importers) - 10} more importers*")
        else:
            lines.append("*Not imported by other files*")
        lines.append("")

    lines.append("## Related Queries")
    lines.append("")
    lines.append("- `find_dependencies` - Full dependency graph")
    lines.append("- `trace_execution_path` - Trace function call chains")
    if functions:
        lines.append(
            f'- `find_callers_callees function_name:"{functions[0]["name"]}"` '
            "- Analyze function relationships"
        )

    # GGSR weighted-context enrichment around the file itself.
    try:
        ctx = await _render_ggsr_section(
            data.graph_db,
            entity=file_path.rsplit("/", 1)[-1],
            token_budget=token_budget,
            hops=min(depth, 2),
            heading="GGSR Weighted Context",
        )
        if ctx:
            lines.append("")
            lines.extend(ctx)
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("GGSR enrichment for analyze_code_structure failed: %s", exc)

    return "\n".join(lines).rstrip() + "\n"


# ── find_dependencies ──────────────────────────────────────────────────


async def _tool_find_dependencies(
    data: Any,
    *,
    target: str,
    direction: str,
    max_depth: int,
    token_budget: int,
) -> str:
    if not target or not target.strip():
        return _error_text("target is required.")
    if data is None or getattr(data, "graph_db", None) is None:
        return _error_text(_DEGRADED_GRAPH_MSG)

    lines: list[str] = [f"# Dependency Analysis: {target}", ""]

    try:
        if direction in ("upstream", "both"):
            imports = await _file_imports(data.graph_db, target)
            lines.append(f"## Upstream Dependencies (What {target} imports)")
            lines.append("")
            if imports:
                lines.append(f"Found {len(imports)} direct imports:")
                lines.append("")
                for imp in imports:
                    lines.append(f"- `{imp}`")
            else:
                lines.append("*No imports found*")
            lines.append("")

        if direction in ("downstream", "both"):
            importers = await _file_importers(data.graph_db, target)
            lines.append(f"## Downstream Dependencies (What imports {target})")
            lines.append("")
            if importers:
                lines.append(f"Found {len(importers)} files that import this:")
                lines.append("")
                for imp in importers:
                    lines.append(f"- `{imp}`")
            else:
                lines.append("*No importers found*")
            lines.append("")

        if max_depth > 1:
            lines.append("## Circular Dependency Check")
            lines.append("")
            try:
                cycles = await _circular_dependencies(data.graph_db)
            except Exception as exc:  # pragma: no cover - defensive
                log.debug("circular dep query failed: %s", exc)
                cycles = []
            relevant = [c for c in cycles if target in (c.get("path") or [])]
            if relevant:
                lines.append(
                    f"[WARN]  **Warning:** Found {len(relevant)} circular "
                    "dependency chains involving this file:"
                )
                lines.append("")
                for cycle in relevant[:5]:
                    lines.append(f"- {' → '.join(cycle['path'])}")
            elif cycles:
                lines.append(
                    "[OK] No circular dependencies detected for this file"
                )
            else:
                lines.append("[OK] No circular dependencies in entire codebase")
            lines.append("")

        try:
            ctx = await _render_ggsr_section(
                data.graph_db,
                entity=target,
                token_budget=token_budget,
                hops=min(max_depth, 2),
                heading="GGSR Weighted Context",
            )
            if ctx:
                lines.extend(ctx)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("GGSR enrichment for find_dependencies failed: %s", exc)

    except Exception as exc:
        log.warning("find_dependencies failed: %s", exc)
        return _error_text(f"Error finding dependencies: {exc}")

    return "\n".join(lines).rstrip() + "\n"


# ── trace_execution_path ───────────────────────────────────────────────


async def _tool_trace_execution_path(
    data: Any,
    *,
    function_name: str,
    file_path: str | None,
    max_depth: int,
    include_callers: bool,
    include_weights: bool,
    token_budget: int,
) -> str:
    if not function_name or not function_name.strip():
        return _error_text("function_name is required.")
    if data is None or getattr(data, "graph_db", None) is None:
        return _error_text(_DEGRADED_GRAPH_MSG)

    try:
        entity_type, entity_labels = await _detect_entity_type(
            data.graph_db, function_name
        )
        if entity_type is None and not file_path:
            return (
                f'Entity "{function_name}" not found in function, Python, '
                f"Fortran, or shell script graphs.\n\n"
                "Try using `analyze_code_structure` first to find available "
                "entities.\n"
            )
        entity_label = {
            "function": "Function",
            "python": "Python Function",
            "fortran": "Fortran",
            "shell": "Shell Script",
        }.get(entity_type or "function", "Function")
        calls_label = {
            "function": "function calls",
            "python": "Python calls",
            "fortran": "Fortran calls",
            "shell": "script invocations",
        }.get(entity_type or "function", "function calls")

        lines: list[str] = [
            f"# Execution Path Trace: {function_name}",
            "",
            f"*Entity type: {entity_label}*",
            "",
            f"## Call Chain (What {function_name} calls)",
            "",
        ]

        call_chain = await _call_chain(
            data.graph_db, function_name, max_depth, entity_type
        )
        if call_chain:
            lines.append(f"Traced {len(call_chain)} {calls_label}:")
            lines.append("")
            for call in call_chain[:20]:
                depth_val = int(call.get("depth") or 1)
                indent = "  " * (depth_val - 1)
                name = call.get("callee") or call.get("name") or ""
                line = f"{indent}{depth_val}. `{name}`"
                if call.get("file"):
                    line += f" (in {call['file']})"
                lines.append(line)
            if len(call_chain) > 20:
                lines.append("")
                lines.append(f"*... and {len(call_chain) - 20} more calls*")
        else:
            lines.append(f"*No {calls_label} found or this is a leaf node*")

        if include_callers:
            lines.append("")
            lines.append(f"## Callers (What calls {function_name})")
            lines.append("")
            callers = await _callers(data.graph_db, function_name, entity_type)
            if callers:
                lines.append(f"Found {len(callers)} callers:")
                lines.append("")
                for caller in callers[:10]:
                    name = caller.get("name") or ""
                    line = f"- `{name}`"
                    if caller.get("file"):
                        line += f" (in {caller['file']})"
                    lines.append(line)
                if len(callers) > 10:
                    lines.append(f"*... and {len(callers) - 10} more callers*")
            else:
                lines.append("*No callers found - this may be an entry point*")

        if include_weights:
            try:
                ctx = await _render_ggsr_section(
                    data.graph_db,
                    entity=function_name,
                    token_budget=token_budget,
                    hops=1,
                    heading="GGSR Weighted Traversal",
                )
                if ctx:
                    lines.append("")
                    lines.extend(ctx)
            except Exception as exc:  # pragma: no cover - defensive
                log.debug("GGSR weighted traversal failed: %s", exc)

        return "\n".join(lines).rstrip() + "\n"
    except Exception as exc:
        log.warning("trace_execution_path failed: %s", exc)
        return _error_text(f"Error tracing execution path: {exc}")


# ── find_callers_callees ───────────────────────────────────────────────


async def _tool_find_callers_callees(
    data: Any,
    *,
    function_name: str,
    file_path: str | None,
    include_source: bool,
    token_budget: int,
    cross_language: bool,
) -> str:
    if not function_name or not function_name.strip():
        return _error_text("function_name is required.")
    if data is None or getattr(data, "graph_db", None) is None:
        return _error_text(_DEGRADED_GRAPH_MSG)

    try:
        entity_type, _ = await _detect_entity_type(
            data.graph_db, function_name
        )
        entity_type = entity_type or "function"
        entity_labels = {
            "function": {
                "name": "Function",
                "caller": "Functions that call",
                "callee": "Functions called by",
            },
            "python": {
                "name": "Python Function",
                "caller": "Python functions that call",
                "callee": "Python functions called by",
            },
            "fortran": {
                "name": "Fortran Subroutine/Function",
                "caller": "Fortran code that calls",
                "callee": "Fortran code called by",
            },
            "shell": {
                "name": "Shell Script",
                "caller": "Scripts that source/invoke",
                "callee": "Scripts sourced/invoked by",
            },
        }[entity_type]

        callers = await _callers(data.graph_db, function_name, entity_type)
        callees = await _call_chain(
            data.graph_db, function_name, 1, entity_type
        )

        lines: list[str] = [
            f"# {entity_labels['name']} Analysis: {function_name}",
            "",
        ]

        if entity_type == "fortran":
            lines.append("*Showing Fortran call graph (CALLS/USES relationships)*")
            lines.append("")
        elif entity_type == "shell":
            lines.append("*Showing shell script call tree (J-Jobs, ex-scripts, ush)*")
            lines.append("")

        lines.append(f"## Callers ({len(callers)})")
        lines.append(f"*{entity_labels['caller']} {function_name}*")
        lines.append("")
        if callers:
            for caller in callers[:15]:
                name = caller.get("name") or ""
                line = f"- **`{name}`**"
                if caller.get("file"):
                    line += f" in `{caller['file']}`"
                if caller.get("lineNumber"):
                    line += f" (line {caller['lineNumber']})"
                lines.append(line)
            if len(callers) > 15:
                lines.append("")
                lines.append(f"*... and {len(callers) - 15} more callers*")
        else:
            lines.append("*No callers found - this may be an entry point*")

        lines.append("")
        lines.append("## Callees")
        lines.append(f"*{entity_labels['callee']} {function_name}*")
        lines.append("")
        if callees:
            for call in callees[:15]:
                name = call.get("callee") or call.get("name") or ""
                line = f"- **`{name}`**"
                if call.get("file"):
                    line += f" in `{call['file']}`"
                if call.get("depth"):
                    line += f" (depth: {call['depth']})"
                lines.append(line)
            if len(callees) > 15:
                lines.append("")
                lines.append(f"*... and {len(callees) - 15} more callees*")
        else:
            lines.append(
                f"*No callees found - this is a leaf "
                f"{entity_labels['name'].lower()}*"
            )

        if cross_language:
            cross_nodes = await _cross_language_nodes(
                data.graph_db, function_name, 5, "forward"
            )
            if cross_nodes:
                lines.append("")
                lines.append("## Cross-Language Callees")
                lines.append("")
                shell_nodes = [
                    n for n in cross_nodes
                    if n["language"] == "shell" and n["hop"] > 0
                ]
                fortran_nodes = [
                    n for n in cross_nodes if n["language"] == "fortran"
                ]
                python_nodes = [
                    n for n in cross_nodes if n["language"] == "python"
                ]
                if shell_nodes:
                    lines.append("### Shell Layer")
                    for n in shell_nodes[:10]:
                        lines.append(
                            f"- {function_name} → `{n['name']}` "
                            f"({n.get('relType') or 'SOURCES/INVOKES'})"
                        )
                    lines.append("")
                if fortran_nodes:
                    lines.append("### Fortran Layer")
                    for n in fortran_nodes[:15]:
                        lines.append(
                            f"- `{n['name']}` [{n.get('label') or 'Fortran'}] "
                            f"({n.get('relType') or 'CALLS'}, depth: {n['hop']})"
                        )
                    lines.append("")
                if python_nodes:
                    lines.append("### Python Layer")
                    for n in python_nodes[:15]:
                        lines.append(
                            f"- `{n['name']}` [{n.get('label') or 'Python'}] "
                            f"({n.get('relType') or 'DEFINES'}, depth: {n['hop']})"
                        )
                    lines.append("")
                langs = sorted({n["language"] for n in cross_nodes})
                bridge_count = sum(
                    1 for n in cross_nodes
                    if n.get("relType") in ("EXECUTES", "INVOKES")
                    and n["hop"] > 0
                )
                lines.append(
                    f"*Languages traversed: {', '.join(langs)} | "
                    f"Bridge crossings: {bridge_count}*"
                )

        lines.append("")
        lines.append("## Complexity Analysis")
        lines.append("")
        lines.append(
            f"- **Fan-in:** {len(callers)} "
            f"({entity_labels['caller'].lower()} this)"
        )
        lines.append(
            f"- **Fan-out:** {len(callees)} "
            f"({entity_labels['callee'].lower()} this)"
        )
        complexity = len(callers) * len(callees)
        lines.append(f"- **Complexity Score:** {complexity}")
        if complexity > 50:
            lines.append("")
            lines.append("[WARN]  **High complexity** - Consider refactoring")
        elif complexity > 20:
            lines.append("")
            lines.append("[WARN]  **Moderate complexity** - Review for simplification")
        else:
            lines.append("")
            lines.append(
                f"[OK] **Low complexity** - Well-scoped "
                f"{entity_labels['name'].lower()}"
            )

        try:
            ctx = await _render_ggsr_section(
                data.graph_db,
                entity=function_name,
                token_budget=token_budget,
                hops=1,
                heading="GGSR Weighted Context",
                apply_bridge_decay=cross_language,
            )
            if ctx:
                lines.append("")
                lines.extend(ctx)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("GGSR context for find_callers_callees failed: %s", exc)

        return "\n".join(lines).rstrip() + "\n"
    except Exception as exc:
        log.warning("find_callers_callees failed: %s", exc)
        return _error_text(f"Error finding callers/callees: {exc}")


# ── trace_full_execution_chain ─────────────────────────────────────────


async def _tool_trace_full_execution_chain(
    data: Any,
    *,
    start: str,
    direction: str,
    max_depth: int,
    languages: tuple[str, ...] | None,
) -> str:
    if not start or not start.strip():
        return _error_text("start is required.")
    if data is None or getattr(data, "graph_db", None) is None:
        return _error_text(_DEGRADED_GRAPH_MSG)

    started = time.monotonic()
    try:
        forward_nodes: list[dict[str, Any]] = []
        reverse_nodes: list[dict[str, Any]] = []
        if direction in ("forward", "both"):
            forward_nodes = await _cross_language_nodes(
                data.graph_db, start, max_depth, "forward"
            )
        if direction in ("reverse", "both"):
            reverse_nodes = await _cross_language_nodes(
                data.graph_db, start, max_depth, "reverse"
            )

        if languages:
            keep = set(languages)
            forward_nodes = [n for n in forward_nodes if n["language"] in keep]
            reverse_nodes = [n for n in reverse_nodes if n["language"] in keep]

        all_nodes = forward_nodes + reverse_nodes
        lines: list[str] = [f"# Full Execution Chain: {start}", ""]

        if not all_nodes:
            lines.append(
                f'*No execution chain found for "{start}". Try a J-Job '
                "name (e.g., JGLOBAL_FORECAST), script name (e.g., "
                "exglobal_forecast.sh), or Fortran program (e.g., gsi).*"
            )
            return "\n".join(lines).rstrip() + "\n"

        if forward_nodes:
            lines.append("### Forward Direction")
            lines.append("")
            lines.append(_format_chain_tree(forward_nodes))
            lines.append("")
        if reverse_nodes:
            lines.append("### Reverse Direction")
            lines.append("")
            lines.append(_format_chain_tree(reverse_nodes))
            lines.append("")

        langs_seen = sorted({n["language"] for n in all_nodes if n.get("language")})
        bridge_count = sum(
            1
            for n in all_nodes
            if n.get("relType") in ("EXECUTES", "INVOKES") and n["hop"] > 0
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)

        lines.append("### Statistics")
        lines.append(f"- Languages traversed: {', '.join(langs_seen) or 'none'}")
        lines.append(f"- Total nodes: {len(all_nodes)}")
        lines.append(f"- Bridge crossings: {bridge_count}")
        lines.append(f"- Max depth: {max_depth} hops")
        lines.append(f"- Query time: {elapsed_ms}ms")
        return "\n".join(lines).rstrip() + "\n"
    except Exception as exc:
        log.warning("trace_full_execution_chain failed: %s", exc)
        return _error_text(f"Error tracing execution chain: {exc}")


def _format_chain_tree(nodes: list[dict[str, Any]]) -> str:
    """Render chain nodes as an indented tree (mirrors Node.js output)."""
    lines: list[str] = []
    for n in nodes:
        hop = int(n.get("hop") or 0)
        indent = "  " * hop
        prefix = "" if hop == 0 else "├── "
        lang = n.get("language") or ""
        lang_tag = f"[{lang.capitalize()}]" if lang else ""
        rel = n.get("relType")
        rel_info = f" ({rel})" if rel else ""
        bridge_marker = (
            " ═══" if rel in ("EXECUTES", "INVOKES") and hop > 0 else ""
        )
        lines.append(
            f"{indent}{prefix}{lang_tag} `{n['name']}`"
            f"{bridge_marker}{rel_info}"
        )
    return "\n".join(lines)


# ── find_env_dependencies ──────────────────────────────────────────────


async def _tool_find_env_dependencies(
    data: Any,
    *,
    variable_name: str,
    show_exports: bool,
    limit: int,
    token_budget: int,
) -> str:
    if not variable_name or not variable_name.strip():
        return _error_text("variable_name is required.")
    if data is None or getattr(data, "graph_db", None) is None:
        return _error_text(_DEGRADED_GRAPH_MSG)

    try:
        depends_cypher = (
            "MATCH (s:CodeFile)-[:DEPENDS_ON_ENV]->"
            "(e:EnvironmentVariable {name: $varName}) "
            "RETURN s.name AS script, s.path AS path, "
            "s.script_type AS type, s.language AS language "
            f"ORDER BY s.script_type, s.name LIMIT {limit}"
        )
        dependents = list(
            await data.graph_db.query(depends_cypher, {"varName": variable_name}, tenant=_tenant())
            or []
        )

        lines: list[str] = [
            f"# Environment Variable Analysis: {variable_name}",
            "",
            f"## Scripts Depending on `{variable_name}` ({len(dependents)})",
            "",
        ]
        if dependents:
            by_type: dict[str, list[dict[str, Any]]] = {}
            for dep in dependents:
                dtype = dep.get("type") or "unknown"
                by_type.setdefault(dtype, []).append(dep)
            for dtype, scripts in by_type.items():
                lines.append(f"### {dtype} ({len(scripts)})")
                for script in scripts[:20]:
                    row = f"- **`{script.get('script') or ''}`**"
                    if script.get("path"):
                        row += f" - `{script['path']}`"
                    lines.append(row)
                if len(scripts) > 20:
                    lines.append(f"*... and {len(scripts) - 20} more*")
                lines.append("")
        else:
            lines.append("*No scripts found depending on this variable*")
            lines.append("")

        exporters: list[dict[str, Any]] = []
        if show_exports:
            exports_cypher = (
                "MATCH (s:CodeFile)-[r:EXPORTS]->"
                "(e:EnvironmentVariable {name: $varName}) "
                "RETURN s.name AS script, s.path AS path, "
                "s.script_type AS type, r.line AS line, r.value AS value "
                f"ORDER BY s.script_type, s.name LIMIT {limit}"
            )
            exporters = list(
                await data.graph_db.query(
                    exports_cypher, {"varName": variable_name},
                    tenant=_tenant(),
                )
                or []
            )
            lines.append(
                f"## Scripts Exporting `{variable_name}` ({len(exporters)})"
            )
            lines.append("")
            if exporters:
                for exp in exporters[:20]:
                    row = f"- **`{exp.get('script') or ''}`**"
                    if exp.get("path"):
                        row += f" - `{exp['path']}`"
                    if exp.get("line"):
                        row += f" (line {exp['line']})"
                    value = exp.get("value")
                    if value and len(str(value)) < 50:
                        row += f" = `{value}`"
                    lines.append(row)
                if len(exporters) > 20:
                    lines.append(f"*... and {len(exporters) - 20} more*")
            else:
                lines.append("*No scripts found exporting this variable*")
            lines.append("")

        meta_cypher = (
            "MATCH (e:EnvironmentVariable {name: $varName}) "
            "RETURN e.is_ee2_standard AS isEE2, e.is_home_model AS isHome, "
            "e.first_seen_in AS firstSeen"
        )
        meta = list(
            await data.graph_db.query(meta_cypher, {"varName": variable_name}, tenant=_tenant())
            or []
        )

        lines.append("## Summary")
        lines.append("")
        if meta:
            m = meta[0]
            tags: list[str] = []
            if m.get("isEE2"):
                tags.append("EE2 Standard")
            if m.get("isHome"):
                tags.append("HOMEmodel")
            if tags:
                lines.append(f"- **Classification:** {', '.join(tags)}")
            if m.get("firstSeen"):
                lines.append(f"- **First seen in:** `{m['firstSeen']}`")
        lines.append(f"- **Total dependencies:** {len(dependents)} scripts")
        impact = (
            "HIGH" if len(dependents) > 50
            else "MEDIUM" if len(dependents) > 20
            else "LOW"
        )
        lines.append(f"- **Impact level:** {impact}")
        if len(dependents) > 50:
            lines.append("")
            lines.append(
                "[WARN] This variable is widely used - changes will have "
                "broad impact"
            )

        try:
            ctx = await _render_ggsr_section(
                data.graph_db,
                entity=variable_name,
                token_budget=token_budget,
                hops=1,
                heading="GGSR Weighted Context",
            )
            if ctx:
                lines.append("")
                lines.extend(ctx)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("GGSR context for find_env_dependencies failed: %s", exc)

        return "\n".join(lines).rstrip() + "\n"
    except Exception as exc:
        log.warning("find_env_dependencies failed: %s", exc)
        return _error_text(f"Error finding env dependencies: {exc}")


# ── graph helpers ──────────────────────────────────────────────────────


async def _file_symbols(graph_db: Any, file_path: str) -> list[dict[str, Any]]:
    """Return function/class symbols defined by ``file_path``.

    Each row is ``{name, type: 'FUNCTION'|'CLASS', docstring, lineNumber}``.
    """
    cypher = (
        "MATCH (f)-[:DEFINES|CONTAINS]->(s) "
        "WHERE (f.path CONTAINS $path OR f.name = $path) "
        "RETURN s.name AS name, labels(s) AS labels, "
        "s.docstring AS docstring, s.lineNumber AS lineNumber "
        "LIMIT 500"
    )
    rows = await graph_db.query(cypher, {"path": file_path}, tenant=_tenant())
    out: list[dict[str, Any]] = []
    for row in rows or []:
        labels = list(row.get("labels") or [])
        if any(lbl in CLASS_LABELS for lbl in labels):
            typ = "CLASS"
        elif any(lbl in FUNCTION_LABELS for lbl in labels):
            typ = "FUNCTION"
        else:
            continue
        out.append(
            {
                "name": row.get("name") or "",
                "type": typ,
                "docstring": row.get("docstring"),
                "lineNumber": row.get("lineNumber"),
                "labels": labels,
            }
        )
    return out


async def _file_imports(graph_db: Any, target: str) -> list[str]:
    """Return module / file names that ``target`` imports."""
    cypher = (
        "MATCH (f)-[:IMPORTS|USES|SOURCES|INVOKES]->(m) "
        "WHERE f.path CONTAINS $path OR f.name = $path "
        "RETURN DISTINCT coalesce(m.name, m.path) AS moduleName LIMIT 200"
    )
    rows = await graph_db.query(cypher, {"path": target}, tenant=_tenant())
    return [row["moduleName"] for row in rows or [] if row.get("moduleName")]


async def _file_importers(graph_db: Any, target: str) -> list[str]:
    """Return file paths that import ``target``."""
    cypher = (
        "MATCH (src)-[:IMPORTS|USES|SOURCES|INVOKES]->(t) "
        "WHERE t.path CONTAINS $path OR t.name = $path "
        "RETURN DISTINCT coalesce(src.path, src.name) AS filePath LIMIT 200"
    )
    rows = await graph_db.query(cypher, {"path": target}, tenant=_tenant())
    return [row["filePath"] for row in rows or [] if row.get("filePath")]


async def _circular_dependencies(graph_db: Any) -> list[dict[str, Any]]:
    """Return a bounded list of cycles in the IMPORTS graph."""
    cypher = (
        "MATCH p=(a)-[:IMPORTS*2..5]->(a) "
        "RETURN [n IN nodes(p) | coalesce(n.name, n.path)] AS path LIMIT 20"
    )
    rows = await graph_db.query(cypher, {}, tenant=_tenant())
    return list(rows or [])


async def _call_chain(
    graph_db: Any,
    function_name: str,
    max_depth: int,
    entity_type: str | None,
) -> list[dict[str, Any]]:
    """Return callees up to ``max_depth`` hops from ``function_name``.

    Entity type selects the edge set — CALLS for code, SOURCES/INVOKES
    for shell scripts. Returns ``[{callee, file, depth}]`` rows.
    """
    depth = _clamp(int(max_depth), 1, DEPENDENCY_DEPTH_MAX)
    if entity_type == "shell":
        cypher = (
            "MATCH p=(f)-[:SOURCES|INVOKES|EXECUTES*1.." + str(depth) + "]->(callee) "
            "WHERE f.name = $name "
            "RETURN callee.name AS callee, callee.path AS file, "
            "length(p) AS depth LIMIT 200"
        )
    else:
        cypher = (
            "MATCH p=(f)-[:CALLS*1.." + str(depth) + "]->(callee) "
            "WHERE f.name = $name "
            "RETURN callee.name AS callee, callee.filepath AS file, "
            "length(p) AS depth LIMIT 200"
        )
    rows = await graph_db.query(cypher, {"name": function_name}, tenant=_tenant())
    return [r for r in (rows or []) if r.get("callee")]


async def _callers(
    graph_db: Any, function_name: str, entity_type: str | None
) -> list[dict[str, Any]]:
    """Return direct callers of ``function_name``."""
    if entity_type == "shell":
        cypher = (
            "MATCH (caller)-[:SOURCES|INVOKES|EXECUTES]->(f) "
            "WHERE f.name = $name "
            "RETURN DISTINCT caller.name AS name, caller.path AS file LIMIT 200"
        )
    else:
        cypher = (
            "MATCH (caller)-[:CALLS]->(f) "
            "WHERE f.name = $name "
            "RETURN DISTINCT caller.name AS name, "
            "caller.filepath AS file LIMIT 200"
        )
    rows = await graph_db.query(cypher, {"name": function_name}, tenant=_tenant())
    return [r for r in (rows or []) if r.get("name")]


async def _detect_entity_type(
    graph_db: Any, name: str
) -> tuple[str | None, list[str]]:
    """Classify ``name`` into ``function|python|fortran|shell|None``.

    Probes the graph with a single cypher lookup that returns the
    labels attached to the first matching node. Returns ``(None, [])``
    when no node matches.
    """
    cypher = (
        "MATCH (n) WHERE n.name = $name "
        "RETURN labels(n) AS labels LIMIT 1"
    )
    rows = await graph_db.query(cypher, {"name": name}, tenant=_tenant())
    if not rows:
        return None, []
    labels = list(rows[0].get("labels") or [])
    if any("Python" in lbl for lbl in labels):
        return "python", labels
    if any(
        lbl in (
            "FortranSubroutine",
            "FortranFunction",
            "FortranModule",
            "FortranProgram",
        )
        for lbl in labels
    ):
        return "fortran", labels
    if any("Shell" in lbl or "Script" in lbl for lbl in labels):
        return "shell", labels
    return "function", labels


async def _cross_language_nodes(
    graph_db: Any,
    start: str,
    max_depth: int,
    direction: str,
) -> list[dict[str, Any]]:
    """Expand ``start`` via the cross-language edge set.

    Returns one row per reachable node::

        {name, label, language, hop, relType, direction}

    Bridge edges (EXECUTES / INVOKES) are preserved so callers can
    count them for statistics. The cypher issues a single variable-
    length path lookup; for very deep traversals the ``LIMIT`` caps
    the result set at 200 rows.
    """
    depth = _clamp(int(max_depth), 1, FULL_CHAIN_DEPTH_MAX)
    edge_union = "|".join(CROSS_LANGUAGE_EDGES)
    if direction == "reverse":
        pattern = f"MATCH p = (n)<-[:{edge_union}*1..{depth}]-(start)"
    else:
        pattern = f"MATCH p = (start)-[:{edge_union}*1..{depth}]->(n)"
    cypher = (
        pattern
        + " WHERE start.name = $name OR start.path = $name "
        "RETURN DISTINCT n.name AS name, n.path AS path, labels(n) AS labels, "
        "length(p) AS hop, "
        "[rel IN relationships(p) | type(rel)][-1] AS relType "
        "LIMIT 200"
    )
    rows = await graph_db.query(cypher, {"name": start}, tenant=_tenant())

    out: list[dict[str, Any]] = []
    # Always include the seed node at hop 0 when we have it.
    seed_rows = await graph_db.query(
        "MATCH (n) WHERE n.name = $name OR n.path = $name "
        "RETURN n.name AS name, labels(n) AS labels LIMIT 1",
        {"name": start},
        tenant=_tenant(),
    )
    if seed_rows:
        labels = list(seed_rows[0].get("labels") or [])
        out.append(
            {
                "name": seed_rows[0].get("name") or start,
                "label": labels[0] if labels else None,
                "language": _label_to_language(labels),
                "hop": 0,
                "relType": None,
                "direction": direction,
            }
        )

    for row in rows or []:
        name = row.get("name") or row.get("path")
        if not name:
            continue
        labels = list(row.get("labels") or [])
        out.append(
            {
                "name": name,
                "label": labels[0] if labels else None,
                "language": _label_to_language(labels),
                "hop": int(row.get("hop") or 1),
                "relType": row.get("relType"),
                "direction": direction,
            }
        )
    return out


def _label_to_language(labels: list[str]) -> str:
    """Map a list of node labels to a logical language string."""
    joined = " ".join(labels)
    for marker, lang in LANGUAGE_LABEL_MAP:
        if marker in joined:
            return lang
    return "other"


# ── GGSR rendering ─────────────────────────────────────────────────────


async def _render_ggsr_section(
    graph_db: Any,
    *,
    entity: str,
    token_budget: int,
    hops: int,
    heading: str,
    apply_bridge_decay: bool = False,
) -> list[str]:
    """Produce markdown lines for a GGSR weighted-traversal block.

    Uses :class:`GGSRTraversal.budget_aware_neighborhood` to fetch +
    score + trim the neighbourhood of ``entity``. When
    ``apply_bridge_decay`` is True the renderer uses
    :data:`BRIDGE_DECAY_OVERRIDE` to rescore hops that cross a
    language boundary via EXECUTES / INVOKES — matching the
    ``cross_language`` path in the Node.js version.
    """
    if token_budget <= 0 or not entity:
        return []
    engine = GGSRTraversal(graph_db)
    results = await engine.budget_aware_neighborhood(
        entity,
        token_budget=token_budget,
        max_results=15,
        hops=min(max(hops, 1), 2),
    )
    if not results:
        return []
    if apply_bridge_decay:
        results = _apply_bridge_decay(results)
        results.sort(key=lambda r: r.score, reverse=True)

    total_tokens = sum(r.estimated_tokens or estimate_row_tokens(r) for r in results)
    lines: list[str] = [f"## {heading}", ""]
    lines.append(
        f"*Scored {len(results)} neighbours ({total_tokens} tokens, "
        f"budget {token_budget})*"
    )
    lines.append("")
    lines.append("| Target | Rel | Weight | Score | Hop |")
    lines.append("|--------|-----|--------|-------|-----|")
    for r in results:
        lines.append(
            f"| `{r.name}` | {r.relationship} | {r.weight:.2f} "
            f"| {r.score:.3f} | {r.hop_distance} |"
        )
    lines.append("")
    return lines


def _apply_bridge_decay(results: list[GGSRScoredResult]) -> list[GGSRScoredResult]:
    """Re-score ``EXECUTES``/``INVOKES`` hops using the bridge decay.

    Same semantics as Node.js' cross-language path: bridge edges
    represent meaningful execution handoffs, not incidental proximity,
    and therefore decay more slowly than regular hops.
    """
    adjusted: list[GGSRScoredResult] = []
    for r in results:
        if r.relationship in ("EXECUTES", "INVOKES") and r.hop_distance >= 1:
            r.score = r.weight * (BRIDGE_DECAY_OVERRIDE ** r.hop_distance)
        adjusted.append(r)
    return adjusted


# ── helpers ────────────────────────────────────────────────────────────


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(int(value), hi))


_DEGRADED_GRAPH_MSG = (
    "Graph database unavailable (degraded-mode boot). Ensure "
    "NEPTUNE_ENDPOINT is reachable from the runtime."
)


def _error_text(message: str) -> str:
    return f"[ERROR] {message}\n"


__all__ = [
    "ANALYZE_DEPTH_MIN",
    "ANALYZE_DEPTH_MAX",
    "DEPENDENCY_DEPTH_MIN",
    "DEPENDENCY_DEPTH_MAX",
    "FULL_CHAIN_DEPTH_MIN",
    "FULL_CHAIN_DEPTH_MAX",
    "ENV_LIMIT_MIN",
    "ENV_LIMIT_MAX",
    "CROSS_LANGUAGE_EDGES",
    "register",
]
