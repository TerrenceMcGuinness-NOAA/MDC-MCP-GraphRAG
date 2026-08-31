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
from src.tenancy.resolver import (
    get_current_tenant_or_none,
    tenant_label_predicate,
)
from src.tools._bfs_walker import (
    BFSResult,
    bfs_fallback_failed,
    bfs_walk,
    insert_bfs_header,
)
from src.tools._traversal_bounds import (
    BFS_FAN_OUT_LIMIT,
    CALL_CHAIN_DEPTH,
    FAN_OUT_THRESHOLD,
    FULL_CHAIN_DEPTH,
    RESULT_LIMIT,
    TIMEOUT_S,
    _use_bfs,
    anchor_degree,
    degraded_notice,
    effective_depth,
    is_hub,
    truncation_marker,
)

log = logging.getLogger(__name__)


def _is_timeout_error(exc: BaseException) -> bool:
    """True when ``exc`` is a traversal statement-timeout (R5.3).

    Recognises the :pyexc:`NeptuneAdapterError` raised by
    :pymeth:`NeptuneAdapter.query` on ``asyncio.wait_for`` expiry (its
    message contains ``statement timeout``) and a bare
    :pyexc:`asyncio.TimeoutError`. Non-timeout errors return ``False`` so
    they keep propagating to the tool's ``[ERROR]`` handler.
    """
    import asyncio as _asyncio

    if isinstance(exc, _asyncio.TimeoutError):
        return True
    return "statement timeout" in str(exc).lower()


def _tenant():
    """Return the active tenant or None (for adapter kwarg)."""
    ctx = get_current_tenant_or_none()
    return ctx.tenant if ctx else None


def _scope_and(var: str) -> str:
    """Return `` AND <predicate>`` to tenant-scope a label-less node, else ``""``.

    Constrains label-less ``MATCH (var)`` patterns to the active tenant's nodes
    (the label-prefix rewriter cannot scope them — no ``:Label`` token).
    """
    pred = tenant_label_predicate(var)
    return f" AND {pred}" if pred else ""


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

        # Pre-flight degree gate (R1): probe the anchor's fan-out over the
        # edge set the call-chain will traverse. Over threshold (or probe
        # failure) -> one-hop Degraded_Result, no variable-length expansion.
        rel_set = _call_rel_set(entity_type)
        degree = await anchor_degree(
            data.graph_db, function_name, rel_set, _tenant(), _scope_and("a")
        )
        if is_hub(degree):
            neighbors = await _one_hop_neighbors(
                data.graph_db, function_name, rel_set, "forward"
            )
            log.info(
                "[traversal-bounds] trace_execution_path degraded "
                "anchor=%s degree=%s guard=degree",
                function_name,
                degree,
            )
            return _degraded_body(
                "Execution Path Trace",
                function_name,
                degraded_notice(function_name, degree, FAN_OUT_THRESHOLD),
                neighbors,
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

        fallback = False
        # Walks that produced part of this response, for the R8.4
        # indicator. This tool has no strategy selector of its own, so the
        # only entry it can ever collect is the timeout-fallback walk
        # below; the list keeps the render call identical to the other
        # three tools' rather than special-casing the single source.
        bfs_walks: list[BFSResult] = []
        try:
            call_chain = await _call_chain(
                data.graph_db, function_name, max_depth, entity_type
            )
        except Exception as exc:  # noqa: BLE001
            if not _is_timeout_error(exc):
                raise
            # Fallback chain (R3.3, R5.5): the single variable-length
            # pattern timed out, so retry the same expansion as a bounded
            # BFS_Walker walk before accepting the one-hop
            # Degraded_Result. Only if the walk salvages nothing does the
            # tool fall through to the pre-5.4 behavior below.
            log.info(
                "[traversal-bounds] trace_execution_path fallback "
                "anchor=%s guard=timeout strategy=bfs",
                function_name,
            )
            walk = await _call_chain_bfs(
                data.graph_db, function_name, max_depth, entity_type, degree
            )
            bfs_walks.append(walk)
            if bfs_fallback_failed(walk.nodes):
                neighbors = await _one_hop_neighbors(
                    data.graph_db, function_name, rel_set, "forward"
                )
                log.info(
                    "[traversal-bounds] trace_execution_path degraded "
                    "anchor=%s guard=timeout",
                    function_name,
                )
                return _degraded_body(
                    "Execution Path Trace",
                    function_name,
                    _timeout_notice(function_name),
                    neighbors,
                )
            call_chain = _bfs_callee_rows(walk)
            fallback = True

        if fallback:
            lines.append(_fallback_notice(function_name))
            lines.append("")
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

        # R8.4: a no-op unless the timeout-fallback walk above produced
        # the call chain, so the ordinary single-query response is
        # unchanged. The `## Callers` section is a separate single query
        # either way and is deliberately not counted -- the indicator
        # names the strategy behind the traversal, not every query the
        # response made.
        insert_bfs_header(lines, *bfs_walks)

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

        # Pre-flight degree gate (R1) over the call-chain edge set.
        rel_set = _call_rel_set(entity_type)
        degree = await anchor_degree(
            data.graph_db, function_name, rel_set, _tenant(), _scope_and("a")
        )
        if is_hub(degree):
            neighbors = await _one_hop_neighbors(
                data.graph_db, function_name, rel_set, "forward"
            )
            log.info(
                "[traversal-bounds] find_callers_callees degraded "
                "anchor=%s degree=%s guard=degree",
                function_name,
                degree,
            )
            return _degraded_body(
                f"{entity_labels['name']} Analysis",
                function_name,
                degraded_notice(function_name, degree, FAN_OUT_THRESHOLD),
                neighbors,
            )

        # Non-hub anchor: the strategy selector picks how the two sections
        # are expanded (R3.1, R3.2). The Hub_Node branch above already
        # returned, so the ordering is hub -> BFS -> single-query, per the
        # design's flow diagram: a node with 100+ edges never attempts a
        # walk (the walker's per-type Fan_Out_Limit is 100 too, so it
        # would still be expensive there), and a failed probe
        # (``degree is None``) degrades via `is_hub` rather than walking
        # (``_use_bfs(None, ...)`` would also be True, but the hub branch
        # wins by running first). The walk is therefore reserved for the
        # moderately-connected band between BFS_ACTIVATION_THRESHOLD and
        # FAN_OUT_THRESHOLD, where the combinatorial risk is real but the
        # decomposed cost is not.
        bfs_truncated = False
        fallback = False
        # Walks that produced part of this response, for the R8.4
        # indicator. This tool can contribute up to three: one per
        # direction from `_callers_callees_bfs` (selector branch or
        # timeout-fallback arm, never both -- the fallback runs only when
        # the selector chose the single query), plus one from the
        # `cross_language` section below. They collapse into a single
        # aggregate header; see `bfs_optimized_header` for why.
        bfs_walks: list[BFSResult] = []
        try:
            if _use_bfs(degree, _CALLERS_CALLEES_DEPTH):
                callers, callees, bfs_truncated = await _callers_callees_bfs(
                    data.graph_db,
                    function_name,
                    entity_type,
                    degree,
                    walk_sink=bfs_walks,
                )
            else:
                # Existing single-query path, unchanged for low-degree
                # anchors so their results stay byte-identical to the
                # pre-optimization behavior (R3.1, R5.1).
                #
                # Its timeout is caught here rather than by the outer
                # handler so the fallback chain (R3.3, R5.5) can retry it
                # as a walk. The nesting is what keeps the chain from
                # doubling back on itself: a timeout raised by the
                # ``_use_bfs`` branch above -- or by the retry below,
                # which runs inside this handler -- reaches only the outer
                # handler, so BFS is attempted at most once per call.
                try:
                    callers = await _callers(
                        data.graph_db, function_name, entity_type
                    )
                    callees = await _call_chain(
                        data.graph_db, function_name, 1, entity_type
                    )
                except Exception as exc:  # noqa: BLE001
                    if not _is_timeout_error(exc):
                        raise
                    log.info(
                        "[traversal-bounds] find_callers_callees fallback "
                        "anchor=%s guard=timeout strategy=bfs",
                        function_name,
                    )
                    (
                        callers,
                        callees,
                        bfs_truncated,
                    ) = await _callers_callees_bfs(
                        data.graph_db,
                        function_name,
                        entity_type,
                        degree,
                        walk_sink=bfs_walks,
                    )
                    if bfs_fallback_failed(callers, callees):
                        # Nothing salvaged: re-raise the original timeout
                        # so the outer handler renders the same
                        # Degraded_Result it did before 5.4.
                        raise
                    fallback = True
        except Exception as exc:  # noqa: BLE001
            if _is_timeout_error(exc):
                neighbors = await _one_hop_neighbors(
                    data.graph_db, function_name, rel_set, "forward"
                )
                log.info(
                    "[traversal-bounds] find_callers_callees degraded "
                    "anchor=%s guard=timeout",
                    function_name,
                )
                return _degraded_body(
                    f"{entity_labels['name']} Analysis",
                    function_name,
                    _timeout_notice(function_name),
                    neighbors,
                )
            raise

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

        if fallback:
            # The walk got here as the fallback arm, so its notice
            # supersedes the truncation one: it already says the results
            # may be partial, and adds the reason (the single query timed
            # out) that the truncation notice cannot express (R3.3).
            lines.append(_fallback_notice(function_name))
            lines.append("")
        elif bfs_truncated:
            # A truncated walk is a partial view of the anchor's
            # neighborhood, never an exhausted one -- say so rather than
            # letting the two lists (and the fan-in / fan-out counts the
            # complexity section derives from their sizes) read as
            # complete (R2.3, R2.7).
            lines.append(
                f"[INFO] The traversal from `{function_name}` hit a "
                "traversal bound (per-hop fan-out limit, result cap, or "
                "statement timeout); the callers and callees below are a "
                "partial view."
            )
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
            # This section is the tool's deep traversal: depth 5 over the
            # six-type Cross_Language_Edge_Set -- exactly the
            # Multi_Type_Expansion shape Root Cause A describes, so it is
            # opted into the strategy selector too (R3.2).
            #
            # ``degree`` is deliberately *not* forwarded: it was measured
            # over the call-chain edge set (`_call_rel_set`), not over the
            # cross-language set this section expands, so it would
            # understate the fan-out it is meant to describe. Left
            # unprobed, `_use_bfs` reads it as unknown and selects the
            # walk -- which is the same decision its depth arm reaches
            # anyway, since 5 > 3. Both paths agree here, so no second
            # probe is issued for the sake of a value that cannot change
            # the outcome.
            cross_nodes = await _cross_language_nodes(
                data.graph_db,
                function_name,
                5,
                "forward",
                allow_bfs=True,
                tool="find_callers_callees",
                walk_sink=bfs_walks,
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

        # R8.4: one aggregate indicator for however many of this tool's
        # three possible walks actually ran. A no-op when the selector
        # kept the single query and `cross_language` was off or stayed on
        # its single-query branch, so those responses are unchanged.
        insert_bfs_header(lines, *bfs_walks)

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
        # Pre-flight degree gate (R1) over the cross-language edge set.
        cross_rel_set = "|".join(CROSS_LANGUAGE_EDGES)
        degree = await anchor_degree(
            data.graph_db, start, cross_rel_set, _tenant(), _scope_and("a")
        )
        if is_hub(degree):
            neighbors: list[dict[str, Any]] = []
            if direction in ("forward", "both"):
                neighbors += await _one_hop_neighbors(
                    data.graph_db, start, cross_rel_set, "forward"
                )
            if direction in ("reverse", "both"):
                neighbors += await _one_hop_neighbors(
                    data.graph_db, start, cross_rel_set, "reverse"
                )
            log.info(
                "[traversal-bounds] trace_full_execution_chain degraded "
                "anchor=%s degree=%s guard=degree",
                start,
                degree,
            )
            return _degraded_body(
                "Full Execution Chain",
                start,
                degraded_notice(start, degree, FAN_OUT_THRESHOLD),
                neighbors,
            )

        # Non-hub anchor: hand the measured degree to the strategy
        # selector so `_cross_language_nodes` can pick the BFS_Walker
        # over the single multi-type variable-length pattern (R3.1,
        # R3.2). The Hub_Node branch above already returned, so the
        # ordering is hub -> BFS -> single-query, per the design's flow
        # diagram: a 100+ edge node never attempts a walk, and a failed
        # probe (degree None) degrades via `is_hub` rather than walking.
        forward_nodes: list[dict[str, Any]] = []
        reverse_nodes: list[dict[str, Any]] = []
        chain_depth, _chain_clamped = effective_depth(
            max_depth, FULL_CHAIN_DEPTH
        )
        fallback = False
        # Walks that produced part of this response, for the R8.4
        # indicator. A ``direction="both"`` request runs two (one per
        # direction) and aggregates them into one header line; see
        # `bfs_optimized_header`.
        bfs_walks: list[BFSResult] = []
        try:
            if direction in ("forward", "both"):
                forward_nodes = await _cross_language_nodes(
                    data.graph_db,
                    start,
                    max_depth,
                    "forward",
                    degree=degree,
                    allow_bfs=True,
                    walk_sink=bfs_walks,
                )
            if direction in ("reverse", "both"):
                reverse_nodes = await _cross_language_nodes(
                    data.graph_db,
                    start,
                    max_depth,
                    "reverse",
                    degree=degree,
                    allow_bfs=True,
                    walk_sink=bfs_walks,
                )
        except Exception as exc:  # noqa: BLE001
            if not _is_timeout_error(exc):
                raise
            # Fallback chain (R3.3, R5.5). The retry is offered only when
            # the *single query* is what timed out, which is why the
            # strategy decision is recomputed here rather than inferred
            # from the exception: `_cross_language_nodes` makes the same
            # `_use_bfs(degree, chain_depth)` call internally, so a `True`
            # here means the walk already ran and the timeout came from
            # inside it (its seed-node lookup -- `bfs_walk` itself absorbs
            # hop failures). Retrying a walk that just timed out would
            # only spend the budget twice, so those go straight to the
            # Degraded_Result, exactly as the design specifies for hubs.
            salvaged_forward: list[dict[str, Any]] | None = None
            salvaged_reverse: list[dict[str, Any]] | None = None
            if not _use_bfs(degree, chain_depth):
                log.info(
                    "[traversal-bounds] trace_full_execution_chain fallback "
                    "anchor=%s guard=timeout strategy=bfs",
                    start,
                )
                if direction in ("forward", "both"):
                    salvaged_forward = await _cross_language_bfs_fallback(
                        data.graph_db,
                        start,
                        max_depth,
                        "forward",
                        degree,
                        walk_sink=bfs_walks,
                    )
                if direction in ("reverse", "both"):
                    salvaged_reverse = await _cross_language_bfs_fallback(
                        data.graph_db,
                        start,
                        max_depth,
                        "reverse",
                        degree,
                        walk_sink=bfs_walks,
                    )
            if salvaged_forward is None and salvaged_reverse is None:
                neighbors = []
                if direction in ("forward", "both"):
                    neighbors += await _one_hop_neighbors(
                        data.graph_db, start, cross_rel_set, "forward"
                    )
                if direction in ("reverse", "both"):
                    neighbors += await _one_hop_neighbors(
                        data.graph_db, start, cross_rel_set, "reverse"
                    )
                log.info(
                    "[traversal-bounds] trace_full_execution_chain degraded "
                    "anchor=%s guard=timeout",
                    start,
                )
                return _degraded_body(
                    "Full Execution Chain",
                    start,
                    _timeout_notice(start),
                    neighbors,
                )
            # A ``direction="both"`` request can salvage one side only;
            # render what came back rather than discarding both.
            forward_nodes = salvaged_forward or []
            reverse_nodes = salvaged_reverse or []
            fallback = True

        if languages:
            keep = set(languages)
            forward_nodes = [n for n in forward_nodes if n["language"] in keep]
            reverse_nodes = [n for n in reverse_nodes if n["language"] in keep]

        all_nodes = forward_nodes + reverse_nodes
        lines: list[str] = [f"# Full Execution Chain: {start}", ""]
        # R8.4: inserted here rather than at the return so it covers the
        # "no execution chain found" early return below too -- a walk that
        # ran and found nothing is still the walk that produced the
        # response, and that is the case an operator correlating a thin
        # response against the COMPLETED log line most wants labelled. A
        # no-op when the selector kept the single query.
        insert_bfs_header(lines, *bfs_walks)
        if fallback:
            lines.append(_fallback_notice(start))
            lines.append("")

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

    Both ends of the one-hop expansion are tenant-scoped: the anchor
    ``f`` and the expanded symbol ``s`` (R4.2, R4.4). Without the second
    fragment a ``DEFINES`` edge that crosses a tenant boundary would
    contribute the other tenant's symbol to this file's symbol list.
    """
    cypher = (
        "MATCH (f)-[:DEFINES|CONTAINS]->(s) "
        "WHERE (f.path CONTAINS $path OR f.name = $path)"
        f"{_scope_and('f')}{_scope_and('s')} "
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
    """Return module / file names that ``target`` imports.

    Anchor ``f`` and expanded module ``m`` are both tenant-scoped, so an
    import edge into another tenant's partition is filtered server-side
    rather than listed as this file's dependency (R4.2, R4.4).
    """
    cypher = (
        "MATCH (f)-[:IMPORTS|USES|SOURCES|INVOKES]->(m) "
        "WHERE (f.path CONTAINS $path OR f.name = $path)"
        f"{_scope_and('f')}{_scope_and('m')} "
        "RETURN DISTINCT coalesce(m.name, m.path) AS moduleName LIMIT 200"
    )
    rows = await graph_db.query(cypher, {"path": target}, tenant=_tenant())
    return [row["moduleName"] for row in rows or [] if row.get("moduleName")]


async def _file_importers(graph_db: Any, target: str) -> list[str]:
    """Return file paths that import ``target``.

    The expansion runs *against* the edge direction here — ``t`` is the
    anchor and ``src`` is the discovered node — so ``src`` is the variable
    that needs the terminal-node Label_Scope_Predicate (R4.2, R4.4).
    """
    cypher = (
        "MATCH (src)-[:IMPORTS|USES|SOURCES|INVOKES]->(t) "
        "WHERE (t.path CONTAINS $path OR t.name = $path)"
        f"{_scope_and('t')}{_scope_and('src')} "
        "RETURN DISTINCT coalesce(src.path, src.name) AS filePath LIMIT 200"
    )
    rows = await graph_db.query(cypher, {"path": target}, tenant=_tenant())
    return [row["filePath"] for row in rows or [] if row.get("filePath")]


async def _circular_dependencies(graph_db: Any) -> list[dict[str, Any]]:
    """Return a bounded list of cycles in the IMPORTS graph.

    Terminal-node scoping (R4.2) needs no addition here: the pattern is a
    cycle, so its terminal node *is* its anchor — the single ``a`` the
    Label_Scope_Predicate already constrains. The intermediate nodes of
    the cycle stay unscoped, which is not a gap either: a cycle whose
    endpoint is tenant-scoped cannot leave and re-enter the tenant's
    partition unless a cross-tenant ``IMPORTS`` edge pair exists, and the
    predicate cannot be applied to path-interior variables in a
    variable-length pattern anyway.
    """
    cypher = (
        "MATCH p=(a)-[:IMPORTS*2..5]->(a) "
        f"WHERE {tenant_label_predicate('a') or 'true'} "
        "RETURN [n IN nodes(p) | coalesce(n.name, n.path)] AS path LIMIT 20"
    )
    rows = await graph_db.query(
        cypher, {}, tenant=_tenant(), timeout=TIMEOUT_S
    )
    return list(rows or [])


def _call_rel_set(entity_type: str | None) -> str:
    """Pipe-joined edge set a call-chain traversal follows for ``entity_type``.

    Shell entities follow the script-invocation edges; everything else
    follows ``CALLS``. Used for both the degree probe and the expansion so
    the probed fan-out matches what the expansion would traverse.
    """
    return "SOURCES|INVOKES|EXECUTES" if entity_type == "shell" else "CALLS"


async def _call_chain(
    graph_db: Any,
    function_name: str,
    max_depth: int,
    entity_type: str | None,
) -> list[dict[str, Any]]:
    """Return callees up to ``max_depth`` hops from ``function_name``.

    Entity type selects the edge set — CALLS for code, SOURCES/INVOKES
    for shell scripts. Returns ``[{callee, file, depth}]`` rows.

    The caller-supplied ``max_depth`` is clamped to the
    :data:`CALL_CHAIN_DEPTH` ceiling so the emitted pattern is always an
    explicit ``*1..N`` bound (R2.1, R2.4), and the query carries the
    :data:`TIMEOUT_S` statement-timeout backstop (R5.2).

    Both the anchor ``f`` and the pattern's terminal ``callee`` carry the
    Label_Scope_Predicate (R4.2, R4.4), matching what the BFS branch of
    this tool does per-hop via ``label_scope_expanded``. Only the
    endpoints can be scoped: a variable-length pattern exposes no
    variable for its interior nodes, so a chain may still *pass through*
    another tenant's node, but it cannot *terminate* on one and so cannot
    contribute one to the rendered call chain.
    """
    depth, _clamped = effective_depth(max_depth, CALL_CHAIN_DEPTH)
    if entity_type == "shell":
        cypher = (
            "MATCH p=(f)-[:SOURCES|INVOKES|EXECUTES*1.." + str(depth) + "]->(callee) "
            "WHERE f.name = $name"
            + _scope_and("f") + _scope_and("callee") + " "
            "RETURN callee.name AS callee, callee.path AS file, "
            "length(p) AS depth LIMIT " + str(RESULT_LIMIT)
        )
    else:
        cypher = (
            "MATCH p=(f)-[:CALLS*1.." + str(depth) + "]->(callee) "
            "WHERE f.name = $name"
            + _scope_and("f") + _scope_and("callee") + " "
            "RETURN callee.name AS callee, callee.filepath AS file, "
            "length(p) AS depth LIMIT " + str(RESULT_LIMIT)
        )
    rows = await graph_db.query(
        cypher, {"name": function_name}, tenant=_tenant(), timeout=TIMEOUT_S
    )
    return [r for r in (rows or []) if r.get("callee")]


async def _callers(
    graph_db: Any, function_name: str, entity_type: str | None
) -> list[dict[str, Any]]:
    """Return direct callers of ``function_name``.

    The expansion runs against the edge direction — ``f`` is the anchor,
    ``caller`` is the discovered node — so ``caller`` is the variable that
    takes the terminal-node Label_Scope_Predicate (R4.2, R4.4).
    """
    if entity_type == "shell":
        cypher = (
            "MATCH (caller)-[:SOURCES|INVOKES|EXECUTES]->(f) "
            "WHERE f.name = $name"
            + _scope_and("f") + _scope_and("caller") + " "
            "RETURN DISTINCT caller.name AS name, caller.path AS file LIMIT "
            + str(RESULT_LIMIT)
        )
    else:
        cypher = (
            "MATCH (caller)-[:CALLS]->(f) "
            "WHERE f.name = $name"
            + _scope_and("f") + _scope_and("caller") + " "
            "RETURN DISTINCT caller.name AS name, "
            "caller.filepath AS file LIMIT " + str(RESULT_LIMIT)
        )
    rows = await graph_db.query(
        cypher, {"name": function_name}, tenant=_tenant(), timeout=TIMEOUT_S
    )
    return [r for r in (rows or []) if r.get("name")]


#: Depth the ``find_callers_callees`` caller / callee sections expand to.
#: Both are *direct*-relationship sections by definition (``## Callers``
#: lists what calls the anchor, ``## Callees`` what the anchor calls), so
#: this is the ``requested_depth`` handed to
#: :func:`~src.tools._traversal_bounds._use_bfs` — the depth > 3 arm of the
#: strategy selector therefore never fires here, and only the anchor's
#: measured degree selects the walk. The deep, variable-length part of
#: this tool is the optional ``cross_language`` section, which routes
#: through :func:`_cross_language_nodes` and its own FULL_CHAIN_DEPTH
#: budget.
_CALLERS_CALLEES_DEPTH: int = 1


def _call_edge_types(entity_type: str | None) -> tuple[str, ...]:
    """Split :func:`_call_rel_set` into the walker's per-type edge tuple.

    The BFS_Walker expands one relationship type per query, so it takes a
    sequence of plain identifiers (a pipe-joined string is refused by
    ``_expand_one_hop``'s identifier check). Derived from
    :func:`_call_rel_set` rather than restated, so the walk and the degree
    probe that selected it can never drift onto different edge sets.
    """
    return tuple(_call_rel_set(entity_type).split("|"))


def _bfs_call_nodes(result: BFSResult) -> list[tuple[str, Any, int]]:
    """Fold walker nodes into deduplicated ``(name, file, hop)`` triples.

    Shared by :func:`_bfs_caller_rows` and :func:`_bfs_callee_rows` so the
    two sections agree on which nodes survive, and in what order, from the
    same walk shape.

    ``file`` comes from the node's ``path`` property because that is what
    the walker projects (``b.name`` / ``b.path``). A node that carries its
    location on ``filepath`` instead — the property the non-shell
    single-query path reads — therefore renders without the file
    annotation. That is a cosmetic difference on the BFS branch only: the
    node itself is still listed, and the counts the complexity section
    derives are unaffected.

    The walker's visited-set already guarantees each *node id* appears at
    most once, but two distinct nodes can share a ``(name, file)`` pair,
    which the single-query path collapses server-side via ``RETURN
    DISTINCT``. Folding on the same tuple here keeps the rendered list
    free of duplicate lines on either strategy (R5.1), and the row cap is
    re-applied across the merged set.
    """
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, Any, int]] = []
    for node in result.nodes:
        name = node.get("name") or node.get("path")
        if not name:
            continue
        file = node.get("path")
        key = (str(name), str(file or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append((str(name), file, int(node.get("hop") or 1)))
        if len(out) >= RESULT_LIMIT:
            break
    return out


def _bfs_caller_rows(result: BFSResult) -> list[dict[str, Any]]:
    """Fold a reverse walk into the :func:`_callers` row shape (R5.1).

    ``_callers`` returns ``{name, file}`` and the ``## Callers`` section
    renders exactly those two columns (plus an optional ``lineNumber``
    neither the shell single-query branch nor the walker projects), so a
    caller cannot tell from the rendered list which strategy ran.
    """
    return [
        {"name": name, "file": file}
        for name, file, _hop in _bfs_call_nodes(result)
    ]


def _bfs_callee_rows(result: BFSResult) -> list[dict[str, Any]]:
    """Fold a forward walk into the :func:`_call_chain` row shape (R5.1).

    ``_call_chain`` returns ``{callee, file, depth}``. The walker's
    ``hop`` is the same 1-based value ``length(p)`` yields for the
    ``*1..1`` pattern this section issues, so the rendered ``(depth: N)``
    annotation is unchanged.
    """
    return [
        {"callee": name, "file": file, "depth": hop}
        for name, file, hop in _bfs_call_nodes(result)
    ]


async def _call_chain_bfs(
    graph_db: Any,
    function_name: str,
    max_depth: int,
    entity_type: str | None,
    degree: int | None = None,
) -> BFSResult:
    """Re-issue :func:`_call_chain`'s expansion as a BFS_Walker walk (R3.3).

    The fallback arm for ``trace_execution_path``: the same anchor, the
    same edge set (:func:`_call_edge_types`, derived from the
    :func:`_call_rel_set` the degree probe used, so the walk cannot drift
    onto a different edge set than the query it replaces) and the same
    clamped Effective_Depth, expanded as bounded per-type single hops
    instead of one variable-length pattern.

    Why a walk is the right retry for *this* query, given
    ``trace_execution_path`` has no strategy selector of its own: the
    pattern it replaces is ``*1..CALL_CHAIN_DEPTH``, i.e. ``*1..4`` at
    the ceiling, and for a shell entity it is a *three*-type expansion
    (``SOURCES|INVOKES|EXECUTES*1..4``) -- precisely the
    Multi_Type_Expansion shape of Root Cause A. Depth 4 also exceeds the
    depth arm of :func:`~src.tools._traversal_bounds._use_bfs` (``> 3``),
    so had this site been wired into the selector the selector would have
    chosen the walk here anyway. And :func:`_bfs_callee_rows` already
    folds a forward walk into ``_call_chain``'s exact ``{callee, file,
    depth}`` row shape, so the retry needs no rendering of its own.

    Tenant scoping matches the query it replaces: ``scope_pred`` is the
    ``_scope_and`` fragment applied to the anchor, and
    ``label_scope_expanded`` extends it to the expanded nodes, which is
    the per-hop counterpart of the terminal-node predicate ``_call_chain``
    carries (R4.1, R4.2, R4.4).

    Returns the raw :class:`BFSResult` rather than rows so the caller can
    consult :func:`bfs_fallback_failed` before committing to it.

    ``degree`` is the caller's measured Node_Degree, forwarded only for the
    walker's R8.1 activation log. It is measured over
    :func:`_call_rel_set`, the same edge set :func:`_call_edge_types`
    splits for the walk, so the logged degree describes this expansion.
    """
    depth, _clamped = effective_depth(max_depth, CALL_CHAIN_DEPTH)
    scope_pred = _scope_and("n")
    return await bfs_walk(
        graph_db,
        start_name=function_name,
        direction="forward",
        edge_types=_call_edge_types(entity_type),
        max_depth=depth,
        fan_out_limit=BFS_FAN_OUT_LIMIT,
        result_limit=RESULT_LIMIT,
        timeout_s=TIMEOUT_S,
        scope_pred=scope_pred,
        tenant=_tenant(),
        label_scope_expanded=bool(scope_pred),
        tool="trace_execution_path",
        degree=degree,
    )


async def _callers_callees_bfs(
    graph_db: Any,
    function_name: str,
    entity_type: str | None,
    degree: int | None = None,
    *,
    walk_sink: list[BFSResult] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    """Resolve callers and callees with the BFS_Walker (R2.1, R3.2).

    Two walks from the same anchor over the same edge set, differing only
    in direction: ``"reverse"`` follows incoming edges (what calls the
    anchor) for ``## Callers``, ``"forward"`` follows outgoing edges (what
    the anchor calls) for ``## Callees``. Each replaces its single query
    with ``|edge_types|`` bounded single-hop seeks per hop (R2.2), so the
    shell edge set (``SOURCES|INVOKES|EXECUTES``) no longer interleaves
    three types inside one variable-length pattern.

    The two walks run sequentially, in the same order the single-query
    path issues its two queries, so the worst-case wall clock is
    unchanged — either strategy is two Statement_Timeout-bounded steps.

    Tenant scoping is carried through: ``scope_pred`` is the same
    ``_scope_and("n")`` fragment the single-query path applies to its
    anchor, and ``label_scope_expanded`` turns it on for the *expanded*
    nodes too, so a neighbor from another tenant is rejected before it
    enters the frontier (R4.1, R4.4). The signal is ``bool(scope_pred)``:
    scope the target exactly when a predicate exists to scope it with,
    and emit no filter when none does (R4.3). Note that the default
    ``gw`` tenant still yields a predicate here -- the *exclusion* form
    (``... STARTS WITH '<other tenant>' ...]) = 0``), which admits every
    unprefixed baseline node while keeping another tenant's prefixed
    nodes out of a ``gw`` walk.

    Returns
    -------
    tuple[list[dict], list[dict], bool]
        The caller rows, the callee rows, and whether *either* walk was
        cut short by a traversal bound — so the caller can say the two
        lists are a partial view rather than an exhaustive one
        (R2.3, R2.7).

    Notes
    -----
    ``degree`` is the caller's measured Node_Degree, forwarded only for
    the walker's R8.1 activation log; it is one measurement over
    :func:`_call_rel_set` and is therefore reported on *both* walks, since
    the probe counts the anchor's edges of those types in either
    direction.

    ``walk_sink``, when given, receives both :class:`BFSResult` objects so
    the caller can render the R8.4 ``[optimized: ...]`` indicator from
    their counters. It is an append-sink rather than a fourth tuple
    element for two reasons: the existing three-element shape stays valid
    for the two call sites that do not need the counters, and it mirrors
    the ``timeout_sink`` convention :func:`~src.tools._bfs_walker.
    _expand_one_hop` already uses for exactly this problem (recovering a
    signal that the folded return value cannot carry). Both walks are
    deposited even when one salvaged nothing -- a zero-node walk is still
    a walk that ran, and its wall clock is time the caller paid.
    """
    scope_pred = _scope_and("n")
    bounds: dict[str, Any] = {
        "edge_types": _call_edge_types(entity_type),
        "max_depth": _CALLERS_CALLEES_DEPTH,
        "fan_out_limit": BFS_FAN_OUT_LIMIT,
        "result_limit": RESULT_LIMIT,
        "timeout_s": TIMEOUT_S,
        "scope_pred": scope_pred,
        "tenant": _tenant(),
        "label_scope_expanded": bool(scope_pred),
        "tool": "find_callers_callees",
        "degree": degree,
    }
    caller_walk = await bfs_walk(
        graph_db, start_name=function_name, direction="reverse", **bounds
    )
    callee_walk = await bfs_walk(
        graph_db, start_name=function_name, direction="forward", **bounds
    )
    if walk_sink is not None:
        walk_sink.extend((caller_walk, callee_walk))
    return (
        _bfs_caller_rows(caller_walk),
        _bfs_callee_rows(callee_walk),
        caller_walk.truncated or callee_walk.truncated,
    )


# ── bounded-traversal degree gate + Degraded_Result rendering ───────────


async def _one_hop_neighbors(
    graph_db: Any,
    name: str,
    rel_set: str,
    direction: str = "forward",
) -> list[dict[str, Any]]:
    """Return the anchor's direct (one-hop) neighbors over ``rel_set``.

    A plain single-hop expand — never a variable-length pattern — used to
    build the Degraded_Result for a Hub_Node (R4.1). Tenant-scoped and
    timeout-bounded like the expansion it replaces (Property 5, R5.2).
    Swallows a statement-timeout (returns ``[]``) so a degraded render
    never raises (R4.4).

    The Anchor_Predicate uses UNION_ALL_Decomposition (R1.1): the
    anchor is matched by ``a.name`` on one branch and ``a.path`` on
    another, joined by ``UNION ALL``, rather than the index-defeating
    ``(a.name = $name OR a.path = $name)`` disjunction on an unlabelled
    node. Each branch carries the tenant scope predicate and its own
    ``LIMIT`` so the server-side bound is preserved (R1.2, R1.4); the
    two row sets are then deduplicated and re-capped here, which is
    set-equivalent to the ``OR`` form the ``DISTINCT`` used to give
    (R1.3).
    """
    if direction == "reverse":
        match = f"MATCH (x)-[r:{rel_set}]->(a)"
    else:
        match = f"MATCH (a)-[r:{rel_set}]->(x)"
    # Both ends are scoped: the anchor ``a`` and the expanded neighbor
    # ``x`` (R4.2, R4.4). ``x`` is the terminal node in both directions —
    # only the pattern's arrow moves, not which variable is discovered —
    # so one fragment covers forward and reverse alike.
    scope = _scope_and("a") + _scope_and("x")
    returning = (
        " RETURN DISTINCT x.name AS name, "
        "coalesce(x.filepath, x.path) AS file "
        "LIMIT " + str(RESULT_LIMIT)
    )
    cypher = (
        match + " WHERE a.name = $name" + scope + returning
        + " UNION ALL "
        + match + " WHERE a.path = $name" + scope + returning
    )
    try:
        rows = await graph_db.query(
            cypher, {"name": name}, tenant=_tenant(), timeout=TIMEOUT_S
        )
    except Exception as exc:  # noqa: BLE001 - degraded render must not raise
        if _is_timeout_error(exc):
            log.info(
                "[traversal-bounds] one-hop neighbor probe timed out for "
                "anchor=%s",
                name,
            )
            return []
        raise
    # ``UNION ALL`` does not dedupe, so an anchor matched by both name
    # and path contributes its neighbors twice: fold them back here and
    # re-apply the row cap across the merged set (R1.3).
    seen: set[tuple[str, str]] = set()
    merged: list[dict[str, Any]] = []
    for row in rows or []:
        row_name = row.get("name")
        if not row_name:
            continue
        key = (str(row_name), str(row.get("file") or ""))
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
        if len(merged) >= RESULT_LIMIT:
            break
    return merged


def _timeout_notice(anchor: str) -> str:
    """Notice rendered when a traversal hits the statement-timeout (R5.3)."""
    return (
        f"[INFO] Traversal from `{anchor}` exceeded the {TIMEOUT_S:g}s "
        "statement timeout and was bounded. Showing the node's direct "
        "(one-hop) neighbors instead of the full expansion."
    )


def _fallback_notice(anchor: str) -> str:
    """Notice rendered when a BFS_Walker fallback answered a timeout (R3.3).

    The middle link of the fallback chain produced the rendered results,
    so the response says so: the single-query expansion did *not*
    complete, and the walk that replaced it carries its own bounds (a
    per-hop Fan_Out_Limit and a result cap). Saying "may be a partial
    view" once, unconditionally, is deliberate -- an untruncated walk is
    still narrower than the pattern it stands in for, because the
    Fan_Out_Limit applies per type per hop rather than to the path set as
    a whole (R2.3, R2.7).
    """
    return (
        f"[INFO] The full expansion from `{anchor}` exceeded the "
        f"{TIMEOUT_S:g}s statement timeout, so it was retried as a bounded "
        "step-by-step traversal. The results below come from that fallback "
        "and may be a partial view."
    )


def _degraded_body(
    title: str, anchor: str, notice: str, neighbors: list[dict[str, Any]]
) -> str:
    """Render a successful Degraded_Result (R4.1-R4.5).

    A labeled ``notice`` (hub or timeout) plus the anchor's direct
    neighbors, truncated to the row LIMIT with a ``[truncated: ...]``
    marker. Not an ``[ERROR]`` response.
    """
    lines: list[str] = [
        f"# {title}: {anchor}",
        "",
        notice,
        "",
        "## Direct Neighbors (one hop)",
        "",
    ]
    display_cap = 50
    shown = neighbors[:display_cap]
    if shown:
        for n in shown:
            name = n.get("name") or ""
            line = f"- `{name}`"
            if n.get("file"):
                line += f" (in {n['file']})"
            lines.append(line)
        marker = truncation_marker(len(shown), len(neighbors))
        if marker:
            lines.append("")
            lines.append(f"*{marker}*")
    else:
        lines.append("*No direct neighbors found.*")
    return "\n".join(lines).rstrip() + "\n"


async def _detect_entity_type(
    graph_db: Any, name: str
) -> tuple[str | None, list[str]]:
    """Classify ``name`` into ``function|python|fortran|shell|None``.

    Probes the graph with a single cypher lookup that returns the
    labels attached to the first matching node. Returns ``(None, [])``
    when no node matches.
    """
    cypher = (
        "MATCH (n) WHERE n.name = $name"
        f"{_scope_and('n')} "
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


async def _cross_language_seed_row(
    graph_db: Any, start: str, direction: str
) -> list[dict[str, Any]]:
    """Return the hop-0 Anchor_Node row for a cross-language chain.

    Shared by both traversal strategies in
    :func:`_cross_language_nodes` so the rendered chain always opens on
    the same seed entry regardless of which strategy expanded it (R5.1).
    Returns ``[]`` when the anchor does not resolve.

    The lookup is a UNION_ALL_Decomposition of the Anchor_Predicate
    (R1.1, R1.3)::

        MATCH (n) WHERE n.name = $name <scope>
        RETURN n.name AS name, labels(n) AS labels LIMIT 1
        UNION ALL
        MATCH (n) WHERE n.path = $name <scope>
        RETURN n.name AS name, labels(n) AS labels LIMIT 1

    The former ``(n.name = $name OR n.path = $name)`` form is a
    disjunction over two properties of an unlabelled node, which Neptune
    cannot satisfy from an index and so evaluates against every node; the
    2026-08-28 benchmark measured 7.3s across this helper's 7 calls. Each
    branch is an indexable equality lookup instead.

    Both branches keep their own ``LIMIT 1``, so the query returns at
    most two rows and the pre-decomposition bound is preserved per
    branch. The first row wins, which makes deduplication trivial (R1.3):
    the ``OR`` form also returned one arbitrary matching node, and a node
    matched on *both* properties appears in both branches but is read
    once. Reading the ``name`` branch first is a deliberate tie-break --
    a name match is the more canonical identification of an anchor the
    caller named -- and it makes the seed row deterministic where the
    ``OR`` form left it to the planner.

    Errors are *not* absorbed here: the callers' contract is unchanged
    (:func:`_cross_language_bfs_fallback` catches a timeout from this
    query to decide between salvage and degradation, and the tool bodies
    render an ``[ERROR]`` otherwise), so swallowing one would convert a
    handled failure into a chain that silently lost its anchor.
    """
    seed_projection = (
        "RETURN n.name AS name, labels(n) AS labels LIMIT 1"
    )
    scope = _scope_and("n")
    seed_rows = await graph_db.query(
        f"MATCH (n) WHERE n.name = $name{scope} "
        f"{seed_projection} "
        "UNION ALL "
        f"MATCH (n) WHERE n.path = $name{scope} "
        f"{seed_projection}",
        {"name": start},
        tenant=_tenant(),
        timeout=TIMEOUT_S,
    )
    if not seed_rows:
        return []
    labels = list(seed_rows[0].get("labels") or [])
    return [
        {
            "name": seed_rows[0].get("name") or start,
            "label": labels[0] if labels else None,
            "language": _label_to_language(labels),
            "hop": 0,
            "relType": None,
            "direction": direction,
        }
    ]


async def _cross_language_nodes_bfs(
    graph_db: Any,
    start: str,
    depth: int,
    direction: str,
    *,
    tool: str = "trace_full_execution_chain",
    degree: int | None = None,
    walk_sink: list[BFSResult] | None = None,
) -> list[dict[str, Any]]:
    """Expand ``start`` with the BFS_Walker instead of one big pattern.

    The Per_Type_BFS strategy for the cross-language chain (R2.1, R3.2).
    :func:`~src.tools._bfs_walker.bfs_walk` issues one bounded single-hop
    query per relationship type per hop rather than a single
    ``[:SOURCES|INVOKES|EXECUTES|CALLS|USES|DEFINES*1..N]`` pattern whose
    cost grows combinatorially in ``depth``.

    Rows are mapped into the *same* shape the single-query path returns
    (``{name, label, language, hop, relType, direction}``), so
    :func:`_format_chain_tree`, the ``languages`` filter, and the
    statistics block in ``trace_full_execution_chain`` are unchanged
    (R5.1, R5.2).

    Tenant scoping is carried through: ``scope_pred`` is the same
    ``_scope_and("n")`` fragment the single-query path applies to its
    anchor, and ``label_scope_expanded`` turns it on for the *expanded*
    nodes too, so a neighbor from another tenant is rejected before it
    enters the frontier (R4.1, R4.4). The signal is ``bool(scope_pred)``:
    scope the target exactly when a predicate exists to scope it with,
    and emit no filter when none does (R4.3). Note that the default
    ``gw`` tenant still yields a predicate here -- the *exclusion* form
    (``... STARTS WITH '<other tenant>' ...]) = 0``), which admits every
    unprefixed baseline node while keeping another tenant's prefixed
    nodes out of a ``gw`` walk.

    ``tool`` and ``degree`` feed the walker's R8.1 activation log only.
    ``tool`` is a parameter rather than a constant because this helper is
    reachable from two tools -- ``trace_full_execution_chain`` (its
    default) and ``find_callers_callees``' cross-language section -- so
    hardcoding either would mislabel the other's walks. ``degree``
    defaults to ``None`` (logged as ``degree=unknown``) because the
    cross-language edge set is not always probed; see
    :func:`_cross_language_nodes`.

    ``walk_sink``, when given, receives this walk's :class:`BFSResult` so
    the calling tool can render the R8.4 ``[optimized: ...]`` indicator
    from its counters. An append-sink rather than a widened return type
    because the row list is this helper's contract with three call sites
    (:func:`_cross_language_nodes`, :func:`_cross_language_bfs_fallback`,
    and the latter's own hop-0 filter), and because it threads through the
    nesting without each layer having to unpack and repack a tuple. It
    follows the ``timeout_sink`` convention already established in
    :func:`~src.tools._bfs_walker._expand_one_hop`. The walk is deposited
    before the seed-row query runs, so a walk whose counters exist is
    reported even if that query then raises.
    """
    scope_pred = _scope_and("n")
    result = await bfs_walk(
        graph_db,
        start_name=start,
        direction=direction,
        edge_types=CROSS_LANGUAGE_EDGES,
        max_depth=depth,
        fan_out_limit=BFS_FAN_OUT_LIMIT,
        result_limit=RESULT_LIMIT,
        timeout_s=TIMEOUT_S,
        scope_pred=scope_pred,
        tenant=_tenant(),
        label_scope_expanded=bool(scope_pred),
        tool=tool,
        degree=degree,
    )
    if walk_sink is not None:
        walk_sink.append(result)

    # The walker excludes the Anchor_Node (hop is 1-based), so the seed
    # row is fetched separately exactly as the single-query path does.
    out: list[dict[str, Any]] = await _cross_language_seed_row(
        graph_db, start, direction
    )
    for node in result.nodes:
        name = node.get("name") or node.get("path")
        if not name:
            continue
        labels = list(node.get("labels") or [])
        out.append(
            {
                "name": name,
                "label": labels[0] if labels else None,
                "language": _label_to_language(labels),
                "hop": int(node.get("hop") or 1),
                "relType": node.get("relType"),
                "direction": direction,
            }
        )
    return out


async def _cross_language_bfs_fallback(
    graph_db: Any,
    start: str,
    max_depth: int,
    direction: str,
    degree: int | None = None,
    *,
    walk_sink: list[BFSResult] | None = None,
) -> list[dict[str, Any]] | None:
    """Retry a timed-out cross-language expansion as a walk (R3.3).

    The fallback arm for ``trace_full_execution_chain``: reuses
    :func:`_cross_language_nodes_bfs` verbatim so the salvaged rows are
    the same shape, in the same order, that the strategy selector's own
    BFS branch would have produced for this anchor. Depth is re-clamped
    here because the caller passes the request's raw ``max_depth``.

    Returns ``None`` -- meaning "degrade" -- in two cases:

    * The walk salvaged nothing (:func:`bfs_fallback_failed`). Only rows
      the walk itself discovered count, so the hop-0 seed row is excluded
      first: it is the Anchor_Node the caller already named, and letting
      it stand in as salvage would turn every failed retry into a chain
      of one node.
    * The walk's own anchor lookup timed out. :func:`bfs_walk` absorbs
      hop failures, but :func:`_cross_language_seed_row` is a separate
      query issued outside it, so it can still raise -- and it must not
      escape a fallback path as an ``[ERROR]`` when a Degraded_Result is
      available (Property 7). Non-timeout errors still propagate.

    ``walk_sink`` is forwarded to :func:`_cross_language_nodes_bfs` so the
    R8.4 indicator reports fallback walks too -- a response the fallback
    arm produced *was* produced by the BFS_Walker, and is exactly the case
    a caller most needs distinguished from a single-query result. The sink
    is filled by the walk itself, so it carries the counters even when
    this function goes on to return ``None``; the caller only renders the
    indicator on the branch where it actually uses the rows.
    """
    depth, _clamped = effective_depth(max_depth, FULL_CHAIN_DEPTH)
    try:
        rows = await _cross_language_nodes_bfs(
            graph_db,
            start,
            depth,
            direction,
            degree=degree,
            walk_sink=walk_sink,
        )
    except Exception as exc:  # noqa: BLE001 - fallback must not raise
        if not _is_timeout_error(exc):
            raise
        log.info(
            "[traversal-bounds] cross-language fallback walk timed out "
            "anchor=%s direction=%s",
            start,
            direction,
        )
        return None
    expanded = [r for r in rows if int(r.get("hop") or 0) > 0]
    if bfs_fallback_failed(expanded):
        return None
    return rows


async def _cross_language_nodes(
    graph_db: Any,
    start: str,
    max_depth: int,
    direction: str,
    *,
    degree: int | None = None,
    allow_bfs: bool = False,
    tool: str = "trace_full_execution_chain",
    walk_sink: list[BFSResult] | None = None,
) -> list[dict[str, Any]]:
    """Expand ``start`` via the cross-language edge set.

    Returns one row per reachable node::

        {name, label, language, hop, relType, direction}

    Bridge edges (EXECUTES / INVOKES) are preserved so callers can
    count them for statistics. The result set is capped at
    :data:`~src.tools._traversal_bounds.RESULT_LIMIT` rows either way.

    Tenant scoping: the single-query branch applies the
    Label_Scope_Predicate to the pattern's *terminal* node ``n`` as well
    as to the ``start`` anchor (R4.2, R4.4), which is the single-query
    counterpart of the BFS branch's per-hop ``label_scope_expanded``.
    Interior nodes of the variable-length pattern cannot be scoped (no
    variable is bound to them), so a chain may pass through another
    tenant's node without being able to terminate on one — the rendered
    rows, which are all terminal nodes, stay inside the tenant.

    ``direction="reverse"`` correctness (fixed in task 7.2): the reverse
    pattern used to be written ``(n)<-[:...]-(start)``, which in
    openCypher is the *same* traversal as the forward
    ``(start)-[:...]->(n)`` — the arrow and the variable positions cancel
    out. Reverse requests therefore returned forward results. It is now
    ``(start)<-[:...]-(n)``, genuinely following the anchor's incoming
    edges, which is what the BFS branch's reverse expansion
    (``MATCH (b)-[:TYPE]->(a)``) has always done. This makes the two
    strategies agree, restoring design Property 2 (a BFS result is a
    subset of the single-query result) for the reverse case; it also
    means reverse output differs from prior releases, because prior
    releases were wrong. Reachable from ``trace_full_execution_chain``
    with ``direction`` reverse/both at ``max_depth <= 3``, where the
    strategy selector keeps the single query.

    Two strategies produce those rows. By default (and for callers that
    have not opted in) the historical single variable-length path lookup
    is issued, unchanged. When ``allow_bfs`` is set the caller's measured
    ``degree`` selects between them via
    :func:`~src.tools._traversal_bounds._use_bfs`: a moderately connected
    anchor (degree >= BFS_ACTIVATION_THRESHOLD) or a deep request
    (Effective_Depth > 3) takes the decomposed BFS_Walker, while a
    low-degree shallow request keeps the single query, which is faster on
    small neighborhoods (R3.1, R3.2, R5.1).

    Strategy order note: the Hub_Node check (:func:`is_hub`) happens in
    the *caller*, before this function is reached, and short-circuits to
    the one-hop Degraded_Result. That ordering is deliberate and follows
    the design's flow diagram -- a node with 100+ edges gets no BFS
    attempt, because the walker's per-type Fan_Out_Limit (also 100) would
    still be expensive there. It also preserves the
    ``bounded-graph-traversal`` [8.36.0] fail-safe: a probe that failed
    yields ``degree is None``, which ``is_hub`` treats as a hub, so a
    failed probe degrades rather than walking (``_use_bfs(None, ...)``
    would also be ``True``, but the hub branch wins by running first).

    Parameters
    ----------
    graph_db
        The graph adapter (must accept ``tenant=`` and ``timeout=``).
    start
        The Anchor_Node's ``name`` or ``path``.
    max_depth
        Requested hops, clamped to
        :data:`~src.tools._traversal_bounds.FULL_CHAIN_DEPTH`.
    direction
        ``"reverse"`` or ``"forward"``.
    degree
        The anchor's measured Node_Degree from :func:`anchor_degree`, or
        ``None`` when unprobed / unmeasurable. Only consulted when
        ``allow_bfs`` is set.
    allow_bfs
        ``True`` to let the strategy selector run. Callers that have not
        run a degree probe over the cross-language edge set leave this
        ``False`` and keep the single-query behavior verbatim.
    tool
        Name of the tool this expansion serves, forwarded to the walker's
        R8.1 activation log so a walk is attributed to the tool the caller
        is actually rendering. Two tools reach this helper --
        ``trace_full_execution_chain`` (the default) and
        ``find_callers_callees``' cross-language section -- so the name is
        threaded down rather than assumed.
    walk_sink
        Optional list that receives the :class:`BFSResult` when (and only
        when) the BFS branch is taken, so the calling tool can render the
        R8.4 ``[optimized: ...]`` indicator. Left untouched on the
        single-query branch -- that absence is precisely how the caller
        knows to render no indicator, so the sink doubles as the strategy
        signal and the tool needs no second copy of the ``_use_bfs``
        decision.
    """
    depth, _clamped = effective_depth(max_depth, FULL_CHAIN_DEPTH)

    if allow_bfs and _use_bfs(degree, depth):
        return await _cross_language_nodes_bfs(
            graph_db,
            start,
            depth,
            direction,
            tool=tool,
            degree=degree,
            walk_sink=walk_sink,
        )

    edge_union = "|".join(CROSS_LANGUAGE_EDGES)
    if direction == "reverse":
        # Incoming edges: the discovered node ``n`` points *at* the
        # anchor. Written anchor-first so the path's node/relationship
        # ordering starts at ``start`` in both directions, which is what
        # ``[rel IN relationships(p) | type(rel)][-1]`` below relies on to
        # report the edge adjacent to ``n``.
        pattern = f"MATCH p = (start)<-[:{edge_union}*1..{depth}]-(n)"
    else:
        pattern = f"MATCH p = (start)-[:{edge_union}*1..{depth}]->(n)"
    cypher = (
        pattern
        + " WHERE (start.name = $name OR start.path = $name)"
        + _scope_and("start")
        + _scope_and("n")
        + " RETURN DISTINCT n.name AS name, n.path AS path, labels(n) AS labels, "
        "length(p) AS hop, "
        "[rel IN relationships(p) | type(rel)][-1] AS relType "
        "LIMIT " + str(RESULT_LIMIT)
    )
    rows = await graph_db.query(
        cypher, {"name": start}, tenant=_tenant(), timeout=TIMEOUT_S
    )

    # Always include the seed node at hop 0 when we have it.
    out: list[dict[str, Any]] = await _cross_language_seed_row(
        graph_db, start, direction
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
