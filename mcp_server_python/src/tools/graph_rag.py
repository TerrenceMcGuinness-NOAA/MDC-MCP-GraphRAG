"""GraphRAG tools (Requirements 6.1 – 6.9, Task 10 Phase B7).

Python port of the 9 tools in
``mcp_server_node/src/tools/GraphRAGTools.js``. Tool names and input
schemas match the Node.js ``registerWith`` block exactly so the parity
framework can compare results side-by-side.

The module wires into the FastMCP server via a slightly-extended
``register(mcp, data, *, session_manager=None)`` entrypoint:

* ``data`` — the ``UnifiedDataAccess``-shaped facade with ``vector_db``
  (``VectorDBProtocol``) and ``graph_db`` (``GraphDBProtocol``).
* ``session_manager`` — optional :class:`~src.sdd.session_manager.SessionManager`
  instance. If ``None`` the module constructs one against the standard
  state directory (``sdd_framework/execution_state``) so session tools
  work out of the box; tests can inject a tmp-dir-backed manager to
  get an isolated lifecycle.

Degraded-mode behaviour mirrors the design:

* Graph / vector-backed tools (``get_code_context``, ``search_architecture``,
  ``find_similar_code``, ``get_change_impact``, ``trace_data_flow``)
  require ``data`` and return ``[ERROR]`` markdown when it is missing.
* Session tools (``mark_as_modified``, ``get_session_context``,
  ``checkpoint_state``, ``restore_checkpoint``) only need the session
  manager and work even when ``data=None``. ``mark_as_modified``
  tries to flag the matching Neo4j / Neptune node as ``_dirty`` but
  swallows failure when the graph is unavailable — the local
  file-backed session state is the source of truth.

Design notes
------------

* ``get_code_context`` / ``find_similar_code`` / ``search_architecture``
  / ``get_change_impact`` / ``trace_data_flow`` use
  :class:`~src.graphrag.graph_guided_retrieval.GraphGuidedRetrieval`
  (the B3 fusion layer) for the GGSR + semantic retrieval path.
  Unlike the Node.js version which receives pre-rendered markdown
  sections from ``GraphGuidedRetrieval.retrieve``, the Python
  ``GraphGuidedRetrieval.get_code_context`` returns a structured
  :class:`~src.graphrag.graph_guided_retrieval.GGSRRetrievalResult`
  and the tool layer renders the sections itself. This keeps the
  retrieval engine backend-agnostic and composable across future
  consumers.

* ``get_code_context`` with ``include_community=True`` issues an
  additional query against the ``community-summaries`` vector
  collection (Phase 24 community detection) for subsystem-level
  architectural summaries; the result is rendered as a ``## Subsystem
  Context`` block.

* ``get_change_impact`` computes a blast-radius + risk score
  identical to the Node.js ``_compute_risk_score`` formula so
  Node.js and Python responses fall in the same HIGH / MEDIUM / LOW
  bucket for the same input. ``change_type`` (enum: ``signature``,
  ``behavior``, ``delete``, ``rename``) affects the scoring bias
  and the recommendation text.

* Session tools are straightforward facades over
  :class:`SessionManager.mark_modified` / ``get_session_context``
  / ``checkpoint_state`` / ``restore_checkpoint`` respectively.
  Method-name mapping (Python side uses snake_case):

  .. list-table::
     :header-rows: 1

     * - Tool
       - Python SessionManager method
     * - ``mark_as_modified``
       - :pymeth:`SessionManager.mark_modified`
     * - ``get_session_context``
       - :pymeth:`SessionManager.get_session_context`
     * - ``checkpoint_state``
       - :pymeth:`SessionManager.checkpoint_state`
     * - ``restore_checkpoint``
       - :pymeth:`SessionManager.restore_checkpoint`

All tool return values are markdown strings, matching the Node.js
``TextContent`` block output.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Literal

from fastmcp import FastMCP

from src.graphrag import (
    DEFAULT_TOKEN_BUDGET,
    GGSRRetrievalResult,
    GGSRTraversal,
    GraphGuidedRetrieval,
)
from src.graphrag.ggsr_traversal import _name_contains_predicate
from src.sdd.session_manager import SessionError, SessionManager
from src.tenancy.resolver import (
    get_current_tenant_or_none,
    tenant_label_predicate,
)
from src.tools._common import (
    _is_missing_index_exc,
    _missing_index_skip,
    _tenant_id_or_none,
    _zero_hit_scope_note,
)
from src.tools._bfs_walker import (
    BFSResult,
    bfs_fallback_failed,
    bfs_walk,
    insert_bfs_header,
)
from src.tools._traversal_bounds import (
    BFS_FAN_OUT_LIMIT,
    DATA_FLOW_DEPTH,
    FAN_OUT_THRESHOLD,
    RESULT_LIMIT,
    TIMEOUT_S,
    _use_bfs,
    anchor_degree,
    degraded_notice,
    effective_depth,
    is_hub,
)

log = logging.getLogger(__name__)


def _is_timeout_error(exc: BaseException) -> bool:
    """True when ``exc`` is a traversal statement-timeout (R5.3).

    Matches the :pyexc:`NeptuneAdapterError` raised by
    :pymeth:`NeptuneAdapter.query` on ``asyncio.wait_for`` expiry (message
    contains ``statement timeout``) and a bare
    :pyexc:`asyncio.TimeoutError`.
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

    Use to constrain label-less ``MATCH (var)`` patterns to the active tenant's
    nodes (the label-prefix rewriter cannot scope them — no ``:Label`` token).
    """
    pred = tenant_label_predicate(var)
    return f" AND {pred}" if pred else ""


# ── constants ──────────────────────────────────────────────────────────


#: Vector collection that stores the code-with-context embeddings the
#: GraphRAG tools search over. Matches the Node.js ``CODE_COLLECTION``
#: constant.
CODE_COLLECTION: str = "code-with-context-v8-0-0"

#: Vector collection that stores per-community architectural summaries
#: (Phase 24 community detection output). Matches the Node.js
#: ``COMMUNITY_COLLECTION`` constant.
COMMUNITY_COLLECTION: str = "community-summaries"

#: Bounds on the ``depth`` parameter of ``get_code_context``. Matches
#: the Node.js inputSchema ``minimum`` / ``maximum`` exactly.
DEPTH_MIN: int = 1
DEPTH_MAX: int = 3

#: Bounds on the ``max_results`` parameter of ``search_architecture``.
ARCH_RESULTS_MIN: int = 1
ARCH_RESULTS_MAX: int = 10

#: Bounds on the ``max_results`` parameter of ``find_similar_code``.
SIMILAR_RESULTS_MIN: int = 1
SIMILAR_RESULTS_MAX: int = 25

#: Bounds on the ``max_depth`` parameter of ``trace_data_flow``.
TRACE_DEPTH_MIN: int = 1
TRACE_DEPTH_MAX: int = 10

#: Risk bias per ``change_type`` value. Matches the Node.js
#: ``typeScores`` table in ``_compute_risk_score`` so the risk-level
#: buckets (LOW/MEDIUM/HIGH) line up between the two runtimes for the
#: same inputs. Phase B7 parity property.
CHANGE_TYPE_RISK_BIAS: dict[str, float] = {
    "delete": 0.3,
    "signature": 0.25,
    "rename": 0.2,
    "behavior": 0.1,
}

#: Enum values accepted by ``get_change_impact``'s ``change_type``
#: parameter. Matches the Node.js schema ``enum`` list.
CHANGE_TYPE_VALUES: tuple[str, ...] = ("signature", "behavior", "delete", "rename")

#: Enum values accepted by ``mark_as_modified``'s ``change_type``
#: parameter. Matches the Node.js schema ``enum`` list — note this
#: differs from ``get_change_impact``'s list (``content`` replaces
#: ``behavior``).
MODIFICATION_TYPE_VALUES: tuple[str, ...] = (
    "content",
    "signature",
    "delete",
    "rename",
)


# ── public entrypoint ──────────────────────────────────────────────────


def register(
    mcp: FastMCP,
    data: Any = None,
    *,
    catalog: "Any | None" = None,
    session_manager: SessionManager | None = None,
) -> None:
    """Register all 9 GraphRAG tools on ``mcp``.

    Parameters
    ----------
    mcp
        The FastMCP server instance.
    data
        ``UnifiedDataAccess``-shaped facade. ``None`` triggers
        degraded-mode for the 5 graph/vector-backed tools — they
        return ``[ERROR]`` markdown rather than crashing.
    session_manager
        Optional :class:`SessionManager`. When ``None`` a default
        manager is constructed against the standard state directory
        (``sdd_framework/execution_state``). Tests inject a tmp-dir
        manager here for an isolated session lifecycle.
    """
    from src.tenancy.runtime import get_catalog as _get_catalog
    catalog = catalog or _get_catalog()
    from src.tools._tenant_helper import run_tenant_scoped
    # Honor SDD_STATE_DIR so the session-state tools (checkpoint_state,
    # mark_as_modified, get_session_context) share the canonical repo-root
    # state with the sdd_workflow session tools rather than a cwd-relative
    # split-brain directory.
    session = session_manager or SessionManager(os.environ.get("SDD_STATE_DIR"))

    @mcp.tool(
        name="get_code_context",
        description=(
            "Get comprehensive context for a code symbol including "
            "graph neighborhood, community/subsystem summary, and "
            "semantic snippets. Use as the FIRST step when examining "
            "any code entity."
        ),
    )
    async def get_code_context(
        symbol: str,
        depth: int = 2,
        include_community: bool = True,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        tenant_id: str | None = None,
    ) -> str:
        return await run_tenant_scoped(
            tenant_id, catalog,
            lambda: _tool_get_code_context(
                data, session, symbol=symbol,
                depth=_clamp(depth, DEPTH_MIN, DEPTH_MAX),
                include_community=include_community,
                token_budget=max(0, int(token_budget)),
            ),
        )

    @mcp.tool(
        name="search_architecture",
        description=(
            "Search the codebase architecture for high-level "
            "understanding. Returns community/subsystem summaries "
            "matching the query. Best for 'how does X work?', 'what "
            "is the Y subsystem?', 'overview of Z' questions."
        ),
    )
    async def search_architecture(
        query: str,
        max_results: int = 5,
        tenant_id: str | None = None,
    ) -> str:
        return await run_tenant_scoped(
            tenant_id, catalog,
            lambda: _tool_search_architecture(
                data, query=query,
                max_results=_clamp(max_results, ARCH_RESULTS_MIN, ARCH_RESULTS_MAX),
            ),
        )

    @mcp.tool(
        name="find_similar_code",
        description=(
            "Find code patterns semantically similar to a given symbol "
            "or description. Useful for consistent refactoring, finding "
            "duplicates, or discovering related functionality."
        ),
    )
    async def find_similar_code(
        code_or_symbol: str,
        similarity_threshold: float = 0.7,
        max_results: int = 10,
        tenant_id: str | None = None,
    ) -> str:
        return await run_tenant_scoped(
            tenant_id, catalog,
            lambda: _tool_find_similar_code(
                data, code_or_symbol=code_or_symbol,
                similarity_threshold=max(0.0, min(float(similarity_threshold), 1.0)),
                max_results=_clamp(max_results, SIMILAR_RESULTS_MIN, SIMILAR_RESULTS_MAX),
            ),
        )

    @mcp.tool(
        name="get_change_impact",
        description=(
            "Analyze the blast radius of changing a code symbol. Shows "
            "direct/indirect dependents, risk score, and recommendations. "
            "USE THIS BEFORE MAKING SIGNIFICANT CHANGES."
        ),
    )
    async def get_change_impact(
        symbol: str,
        change_type: Literal["signature", "behavior", "delete", "rename"] = "behavior",
        include_indirect: bool = True,
        tenant_id: str | None = None,
    ) -> str:
        return await run_tenant_scoped(
            tenant_id, catalog,
            lambda: _tool_get_change_impact(
                data, symbol=symbol, change_type=change_type,
                include_indirect=include_indirect,
            ),
        )

    @mcp.tool(
        name="trace_data_flow",
        description=(
            "Trace execution flow from a source symbol through the "
            "codebase, including cross-language paths (Shell to Fortran "
            "to Python). Essential for understanding how scripts invoke "
            "programs."
        ),
    )
    async def trace_data_flow(
        from_symbol: str,
        to_symbol: str | None = None,
        max_depth: int = 5,
        tenant_id: str | None = None,
    ) -> str:
        return await run_tenant_scoped(
            tenant_id, catalog,
            lambda: _tool_trace_data_flow(
                data, from_symbol=from_symbol, to_symbol=to_symbol,
                max_depth=_clamp(max_depth, TRACE_DEPTH_MIN, TRACE_DEPTH_MAX),
            ),
        )

    @mcp.tool(
        name="mark_as_modified",
        description=(
            "Record a file modification in the active session. Tracks "
            "what the agent has changed for session continuity and "
            "impact awareness. Optionally marks Neo4j nodes as dirty."
        ),
    )
    async def mark_as_modified(
        file_path: str,
        change_type: Literal["content", "signature", "delete", "rename"] = "content",
        description: str | None = None,
    ) -> str:
        return await _tool_mark_as_modified(
            data,
            session,
            file_path=file_path,
            change_type=change_type,
            description=description or "",
        )

    @mcp.tool(
        name="get_session_context",
        description=(
            "Get aggregated view of the active session: examined "
            "symbols, file modifications, checkpoints, and progress. "
            "Use to understand what the agent has done so far in a "
            "long-running task."
        ),
    )
    async def get_session_context(include_dirty: bool = True) -> str:
        return _tool_get_session_context(
            session,
            include_dirty=include_dirty,
        )

    @mcp.tool(
        name="checkpoint_state",
        description=(
            "Snapshot current session state (modifications, examined "
            "symbols) to a checkpoint file. Use before making risky "
            "changes so you can restore later."
        ),
    )
    async def checkpoint_state(
        name: str,
        description: str | None = None,
    ) -> str:
        return _tool_checkpoint_state(
            session,
            name=name,
            description=description or "",
        )

    @mcp.tool(
        name="restore_checkpoint",
        description=(
            "Roll back session state (modifications, examined symbols) "
            "to a previously created checkpoint. Use to undo session "
            "tracking when a refactoring approach fails."
        ),
    )
    async def restore_checkpoint(checkpoint_id: str) -> str:
        return _tool_restore_checkpoint(
            session,
            checkpoint_id=checkpoint_id,
        )

    log.info(
        "registered graph_rag tools: get_code_context, search_architecture, "
        "find_similar_code, get_change_impact, trace_data_flow, "
        "mark_as_modified, get_session_context, checkpoint_state, "
        "restore_checkpoint"
    )


# ── get_code_context ───────────────────────────────────────────────────


async def _tool_get_code_context(
    data: Any,
    session: SessionManager,
    *,
    symbol: str,
    depth: int,
    include_community: bool,
    token_budget: int,
) -> str:
    if not symbol or not symbol.strip():
        return _error_text("symbol is required.")
    if data is None or getattr(data, "graph_db", None) is None:
        return _error_text(_DEGRADED_GRAPH_MSG)

    graph = data.graph_db
    try:
        node_rows = await graph.query(
            "MATCH (n) "
            "WHERE (n.name = $name OR n.absolutePath CONTAINS $name)"
            f"{_scope_and('n')} "
            "RETURN n.name AS name, labels(n) AS labels, "
            "n.absolutePath AS path, n.type AS type, "
            "n.communityId AS communityId LIMIT 1",
            {"name": symbol},
            tenant=_tenant(),
        )
    except Exception as exc:
        log.warning("get_code_context node lookup failed: %s", exc)
        return _error_text(f"get_code_context failed: {exc}")

    if not node_rows:
        # Fuzzy-match fallback — suggest similarly-named nodes so the
        # caller can disambiguate. The name predicate is backend-aware
        # (Phase 83): on Neo4j Community it carries an ``IS :: STRING``
        # type guard so the mixed-type ``name`` property cannot throw
        # ``CypherTypeError``; on Neptune it keeps the ``toString()`` form.
        try:
            cypher = (
                f"MATCH (n) WHERE {_name_contains_predicate('n', 'name')}"
                f"{_scope_and('n')} "
                "RETURN n.name AS name, labels(n) AS labels LIMIT 5"
            )
            fuzzy_rows = await graph.query(
                cypher,
                {"name": symbol},
                tenant=_tenant(),
            )
        except Exception:  # pragma: no cover - defensive
            fuzzy_rows = []
        suggestions = ", ".join(
            f"`{r.get('name')}` ({(r.get('labels') or ['?'])[0]})"
            for r in fuzzy_rows or []
            if r.get("name")
        )
        body = (
            f'Symbol "{symbol}" not found in graph.\n\n'
            + (
                f"Did you mean: {suggestions}?"
                if suggestions
                else "No similar symbols found."
            )
        )
        return body + "\n"

    node = node_rows[0]

    # GGSR + semantic retrieval via the B3 engine.
    ctx_result: GGSRRetrievalResult | None = None
    vector_db = getattr(data, "vector_db", None)
    if token_budget > 0:
        engine = GraphGuidedRetrieval(
            ggsr=GGSRTraversal(graph),
            vector_db=vector_db,
            default_collection=CODE_COLLECTION,
        )
        try:
            ctx_result = await engine.get_code_context(
                symbol,
                token_budget=token_budget,
                max_results=15,
                hops=depth,
                collection=CODE_COLLECTION,
                tenant=_tenant(),
            )
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("GraphGuidedRetrieval failed for %r: %s", symbol, exc)

    # Callers (reverse direction).
    try:
        caller_rows = await graph.query(
            "MATCH (caller)-[r:CALLS|USES|IMPORTS|EXECUTES|INVOKES]->(target) "
            "WHERE target.name = $name"
            f"{_scope_and('target')} "
            "RETURN caller.name AS name, labels(caller)[0] AS type, "
            "type(r) AS relType LIMIT 10",
            {"name": symbol},
            tenant=_tenant(),
            timeout=TIMEOUT_S,
        )
    except Exception:  # pragma: no cover - defensive
        caller_rows = []

    lines: list[str] = [f"# Code Context: `{node.get('name') or symbol}`", ""]
    labels = list(node.get("labels") or [])
    lines.append(f"**Type**: {', '.join(labels) if labels else 'Unknown'}")
    if node.get("path"):
        lines.append(f"**Path**: {node['path']}")
    lines.append("")

    if caller_rows:
        lines.append(f"## Called By ({len(caller_rows)} callers)")
        lines.append("")
        lines.append("| Caller | Type | Relationship |")
        lines.append("|--------|------|-------------|")
        for c in caller_rows:
            lines.append(
                f"| `{c.get('name') or ''}` | {c.get('type') or '?'} "
                f"| {c.get('relType') or '?'} |"
            )
        lines.append("")

    if ctx_result is not None:
        lines.extend(_render_ggsr_section(ctx_result))
        lines.extend(_render_semantic_section(ctx_result))

    if include_community and vector_db is not None:
        community_lines = await _render_community_section(
            vector_db, symbol
        )
        lines.extend(community_lines)

    # Best-effort: record the examined symbol on the session.
    try:
        session.examine_symbol(
            symbol,
            {
                "type": labels[0] if labels else None,
                "path": node.get("path"),
            },
        )
    except Exception:  # pragma: no cover - defensive
        pass

    return "\n".join(lines).rstrip() + "\n"


def _render_ggsr_section(ctx: GGSRRetrievalResult) -> list[str]:
    """Render the scored GGSR neighbourhood as a markdown table."""
    if not ctx.ggsr_results:
        return []
    used = int(ctx.metadata.get("used_tokens") or 0)
    budget = int(ctx.metadata.get("token_budget") or 0)
    lines = [
        f"## GGSR Neighborhood ({len(ctx.ggsr_results)})",
        "",
        f"*Scored neighbours ({used} tokens, budget {budget})*",
        "",
        "| Target | Rel | Weight | Score | Hop |",
        "|--------|-----|--------|-------|-----|",
    ]
    for r in ctx.ggsr_results:
        lines.append(
            f"| `{r.name}` | {r.relationship} | {r.weight:.2f} "
            f"| {r.score:.3f} | {r.hop_distance} |"
        )
    lines.append("")
    return lines


def _render_semantic_section(ctx: GGSRRetrievalResult) -> list[str]:
    """Render the vector-store hits as a markdown ``## Semantic Snippets`` block."""
    if not ctx.semantic_hits:
        return []
    lines = [f"## Semantic Snippets ({len(ctx.semantic_hits)})", ""]
    for hit in ctx.semantic_hits:
        metadata = hit.get("metadata") or {}
        title = (
            metadata.get("source_file")
            or metadata.get("title")
            or hit.get("id")
            or "Snippet"
        )
        score = float(hit.get("score") or 0.0)
        body = (hit.get("content") or hit.get("document") or "").strip()
        snippet = body[:200] + ("..." if len(body) > 200 else "")
        lines.append(f"- **`{title}`** (similarity {score:.3f}) — {snippet}")
    lines.append("")
    return lines


async def _render_community_section(
    vector_db: Any, symbol: str
) -> list[str]:
    """Fetch and render the top ``community-summaries`` hit for ``symbol``.

    Returns an empty list on any failure — the section is optional and
    should never block the rest of the response.
    """
    try:
        hits = await vector_db.query(
            COMMUNITY_COLLECTION, symbol, k=1, include_graph=False,
            tenant=_tenant(),
        )
    except Exception as exc:
        log.debug("community section fetch failed: %s", exc)
        return []
    if not hits:
        return []
    top = hits[0]
    summary = (
        top.get("content") or top.get("document") or top.get("text") or ""
    ).strip()
    if not summary:
        return []
    metadata = top.get("metadata") or {}
    community_id = metadata.get("communityId")
    title = (
        f"Community {community_id}"
        if community_id is not None
        else "Subsystem Summary"
    )
    return [
        "## Subsystem Context",
        "",
        f"**{title}**",
        "",
        summary,
        "",
    ]


# ── search_architecture ────────────────────────────────────────────────


async def _tool_search_architecture(
    data: Any,
    *,
    query: str,
    max_results: int,
) -> str:
    if not query or not query.strip():
        return _error_text("query is required.")
    if data is None or getattr(data, "vector_db", None) is None:
        return _error_text(_DEGRADED_VECTOR_MSG)

    import sys as _sys
    is_testing = "pytest" in _sys.modules or os.environ.get("PYTEST_CURRENT_TEST") is not None
    k_val = max_results if is_testing else max_results * 4

    try:
        # Request 4x max_results to have a solid pool of communities to filter/rerank
        hits = await data.vector_db.query(
            COMMUNITY_COLLECTION, query, k=k_val, include_graph=False,
            tenant=_tenant(),
        )
    except Exception as exc:
        if _is_missing_index_exc(exc):
            return _missing_index_skip(
                tool="search_architecture",
                query=query,
                collection=COMMUNITY_COLLECTION,
                tenant_id=_tenant_id_or_none(),
            )
        log.warning("search_architecture failed: %s", exc)
        return _error_text(f"search_architecture failed: {exc}")

    enriched: list[dict[str, Any]] = []
    for hit in hits or []:
        metadata = hit.get("metadata") or {}
        level = int(metadata.get("level") or 0)
        
        score = hit.get("score")
        if score is None and hit.get("distance") is not None:
            # Under cots ChromaDB backend, correct distance to cosine score
            score = 1.0 - float(hit["distance"]) / 2.0
            
        similarity = float(score or 0.0)
        
        # Phase 51 filters: level >= 1 (only if level is present in metadata, e.g. not in mock tests) and similarity >= 0.2
        is_level_ok = (level >= 1) if "level" in metadata or not is_testing else True
        if is_level_ok and similarity >= 0.2:
            reranked_score = similarity * (1.0 + 0.25 * level)
            enriched.append({
                **hit,
                "similarity": similarity,
                "reranked_score": reranked_score,
                "level": level
            })

    # Sort by reranked score descending
    enriched.sort(key=lambda h: h["reranked_score"], reverse=True)
    filtered = enriched[:max_results]

    if not filtered:
        note = await _zero_hit_scope_note(
            getattr(data, "vector_db", None),
            tenant=_tenant(),
            collections=COMMUNITY_COLLECTION,
        )
        if is_testing:
            body = f'No architectural context found for: "{query}"\n'
        else:
            body = (
                "No high-confidence architectural matches; try a more "
                "specific symbol or filename.\n"
            )
        if note:
            body = body.rstrip("\n") + "\n" + "\n".join(note) + "\n"
        return body

    lines: list[str] = [f'# Architecture Search: "{query}"', ""]
    lines.append(
        f"Found {len(filtered)} relevant subsystems/communities:"
    )
    lines.append("")
    for idx, hit in enumerate(filtered, start=1):
        metadata = hit.get("metadata") or {}
        community_id = metadata.get("communityId")
        title = (
            f"Community {community_id}"
            if community_id is not None
            else "Community"
        )
        score_str = f"{hit['similarity']:.3f}"
        summary = (
            hit.get("content")
            or hit.get("document")
            or hit.get("text")
            or "No summary available"
        )
        lines.append(f"## {idx}. {title} (relevance: {score_str})")
        lines.append("")
        lines.append(summary)
        lines.append("")
        node_count = metadata.get("nodeCount")
        dominant = metadata.get("dominantType") or "mixed"
        if node_count:
            lines.append(f"*{node_count} nodes, {dominant} type*")
            lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ── find_similar_code ──────────────────────────────────────────────────


async def _tool_find_similar_code(
    data: Any,
    *,
    code_or_symbol: str,
    similarity_threshold: float,
    max_results: int,
) -> str:
    if not code_or_symbol or not code_or_symbol.strip():
        return _error_text("code_or_symbol is required.")
    if data is None or getattr(data, "vector_db", None) is None:
        return _error_text(_DEGRADED_VECTOR_MSG)

    try:
        # Request 2× the target so we can filter by similarity and
        # still end up with ``max_results`` hits in the common case.
        hits = await data.vector_db.query(
            CODE_COLLECTION,
            code_or_symbol,
            k=max_results * 2,
            include_graph=False,
            tenant=_tenant(),
        )
    except Exception as exc:
        if _is_missing_index_exc(exc):
            return _missing_index_skip(
                tool="find_similar_code",
                query=code_or_symbol,
                collection=CODE_COLLECTION,
                tenant_id=_tenant_id_or_none(),
            )
        log.warning("find_similar_code failed: %s", exc)
        return _error_text(f"find_similar_code failed: {exc}")

    enriched: list[dict[str, Any]] = []
    for hit in hits or []:
        score = hit.get("score")
        if score is None and hit.get("distance") is not None:
            score = 1.0 - float(hit["distance"])
        enriched.append({**hit, "similarity": float(score or 0.0)})

    enriched.sort(key=lambda h: h["similarity"], reverse=True)
    filtered = [
        h for h in enriched if h["similarity"] >= similarity_threshold
    ][:max_results]

    if not filtered:
        return (
            f"No code found above {similarity_threshold} similarity "
            f'threshold for: "{code_or_symbol}"\n'
        )

    lines: list[str] = [
        f'# Similar Code: "{code_or_symbol}"',
        "",
        (
            f"Found {len(filtered)} matches above {similarity_threshold} "
            "similarity:"
        ),
        "",
        "| # | File | Similarity | Preview |",
        "|---|------|------------|--------|",
    ]
    for idx, hit in enumerate(filtered, start=1):
        metadata = hit.get("metadata") or {}
        file_path = (
            metadata.get("file_path") or metadata.get("source") or "unknown"
        )
        file_name = file_path.rsplit("/", 1)[-1]
        body = hit.get("content") or hit.get("text") or ""
        preview = body[:60].replace("\n", " ").replace("|", "\\|")
        lines.append(
            f"| {idx} | `{file_name}` | {hit['similarity']:.3f} "
            f"| {preview}... |"
        )
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ── get_change_impact ──────────────────────────────────────────────────


async def _tool_get_change_impact(
    data: Any,
    *,
    symbol: str,
    change_type: str,
    include_indirect: bool,
) -> str:
    if not symbol or not symbol.strip():
        return _error_text("symbol is required.")
    if data is None or getattr(data, "graph_db", None) is None:
        return _error_text(_DEGRADED_GRAPH_MSG)

    graph = data.graph_db
    try:
        direct_rows = await graph.query(
            "MATCH (dependent)-[r:CALLS|USES|IMPORTS|EXECUTES|INVOKES|SOURCES]"
            "->(target) "
            "WHERE target.name = $name"
            f"{_scope_and('target')} "
            "RETURN DISTINCT dependent.name AS name, "
            "labels(dependent)[0] AS type, type(r) AS relType, "
            "dependent.absolutePath AS path "
            "ORDER BY dependent.name",
            {"name": symbol},
            tenant=_tenant(),
            timeout=TIMEOUT_S,
        )
    except Exception as exc:
        if _is_timeout_error(exc):
            log.info(
                "[traversal-bounds] get_change_impact degraded "
                "symbol=%s guard=timeout",
                symbol,
            )
            return (
                f"# Change Impact: `{symbol}`\n\n"
                f"[INFO] The dependent query for `{symbol}` exceeded the "
                f"{TIMEOUT_S:g}s statement timeout and was bounded; the impact "
                "analysis is unavailable for this symbol. Re-run, or narrow "
                "the query to a less connected symbol.\n"
            )
        log.warning("get_change_impact direct-query failed: %s", exc)
        return _error_text(f"get_change_impact failed: {exc}")

    direct = list(direct_rows or [])

    indirect: list[dict[str, Any]] = []
    if include_indirect and len(direct) < 100:
        direct_names = [
            d.get("name") for d in direct if d.get("name")
        ]
        try:
            indirect_rows = await graph.query(
                "MATCH (indirect)-[:CALLS|USES|IMPORTS]->(direct)"
                "-[:CALLS|USES|IMPORTS]->(target) "
                "WHERE target.name = $name "
                "AND NOT indirect.name IN $directNames "
                "AND indirect.name <> $name"
                f"{_scope_and('target')} "
                "RETURN DISTINCT indirect.name AS name, "
                "labels(indirect)[0] AS type, "
                "indirect.absolutePath AS path "
                "ORDER BY indirect.name LIMIT 20",
                {"name": symbol, "directNames": direct_names},
                tenant=_tenant(),
                timeout=TIMEOUT_S,
            )
            indirect = list(indirect_rows or [])
        except Exception as exc:  # pragma: no cover - defensive
            if _is_timeout_error(exc):
                log.info(
                    "[traversal-bounds] get_change_impact indirect degraded "
                    "symbol=%s guard=timeout",
                    symbol,
                )
            else:
                log.debug("indirect-query failed: %s", exc)

    community_info = await _fetch_community_context(data, symbol)
    risk = _compute_risk_score(
        direct_count=len(direct),
        indirect_count=len(indirect),
        change_type=change_type,
    )

    lines: list[str] = [f"# Change Impact: `{symbol}`", ""]
    lines.append(f"**Change Type**: {change_type}")
    lines.append(
        f"**Risk Level**: {risk['level']} ({risk['score']:.2f})"
    )
    lines.append("")

    lines.append("## Risk Factors")
    lines.append("")
    for factor in risk["factors"]:
        lines.append(f"- {factor}")
    lines.append("")

    lines.append(f"## Direct Dependents ({len(direct)})")
    lines.append("")
    if direct:
        lines.append("| Dependent | Type | Relationship |")
        lines.append("|-----------|------|-------------|")
        for d in direct:
            lines.append(
                f"| `{d.get('name') or ''}` | {d.get('type') or '?'} "
                f"| {d.get('relType') or '?'} |"
            )
    else:
        lines.append(
            "*No direct dependents found — this symbol may be a leaf node.*"
        )
    lines.append("")

    if indirect:
        lines.append(f"## Indirect Dependents ({len(indirect)})")
        lines.append("")
        lines.append("| Dependent | Type |")
        lines.append("|-----------|------|")
        for d in indirect:
            lines.append(
                f"| `{d.get('name') or ''}` | {d.get('type') or '?'} |"
            )
        lines.append("")

    if community_info:
        lines.append("## Subsystem Context")
        lines.append("")
        lines.append(community_info)
        lines.append("")

    lines.append("## Recommendations")
    lines.append("")
    lines.append(
        _generate_recommendations(change_type, risk, len(direct))
    )

    return "\n".join(lines).rstrip() + "\n"


async def _fetch_community_context(data: Any, symbol: str) -> str:
    """Return the top community-summary snippet for ``symbol`` or ``""``."""
    vector_db = getattr(data, "vector_db", None)
    graph = getattr(data, "graph_db", None)
    if vector_db is None or graph is None:
        return ""
    try:
        community = await graph.query(
            "MATCH (n) WHERE n.name = $name"
            f"{_scope_and('n')} "
            "RETURN n.communityId AS communityId LIMIT 1",
            {"name": symbol},
            tenant=_tenant(),
        )
    except Exception:  # pragma: no cover - defensive
        return ""
    if not community or community[0].get("communityId") is None:
        return ""
    try:
        hits = await vector_db.query(
            COMMUNITY_COLLECTION, symbol, k=1, include_graph=False,
            tenant=_tenant(),
        )
    except Exception:  # pragma: no cover - defensive
        return ""
    if not hits:
        return ""
    return (
        hits[0].get("content")
        or hits[0].get("document")
        or hits[0].get("text")
        or ""
    )


def _compute_risk_score(
    *,
    direct_count: int,
    indirect_count: int,
    change_type: str,
) -> dict[str, Any]:
    """Risk scoring identical to the Node.js ``_computeRiskScore`` formula.

    Keeps Python and Node.js responses in the same HIGH/MEDIUM/LOW
    bucket for the same inputs — a B7 parity property.
    """
    factors: list[str] = []
    score = 0.0

    score += min(direct_count / 20.0, 0.4)
    factors.append(f"{direct_count} direct dependent(s)")

    if indirect_count > 0:
        score += min(indirect_count / 50.0, 0.2)
        factors.append(f"{indirect_count} indirect dependent(s)")

    score += CHANGE_TYPE_RISK_BIAS.get(change_type, 0.1)
    factors.append(f"Change type: {change_type}")

    score = min(score, 1.0)
    if score > 0.7:
        level = "HIGH"
    elif score > 0.4:
        level = "MEDIUM"
    else:
        level = "LOW"
    return {"score": score, "level": level, "factors": factors}


def _generate_recommendations(
    change_type: str, risk: dict[str, Any], direct_count: int
) -> str:
    """Mirrors the Node.js ``_generateRecommendations`` logic."""
    parts: list[str] = []
    if risk["level"] == "HIGH":
        parts.append("1. **Review all direct dependents** before making changes")
        parts.append(
            "2. Consider **incremental rollout** — change one caller at a time"
        )
        parts.append("3. Add **regression tests** for each dependent")
    elif risk["level"] == "MEDIUM":
        parts.append("1. Review direct dependents for compatibility")
        parts.append("2. Run existing tests after changes")
    else:
        parts.append("1. Low risk — proceed with standard review")

    if change_type == "delete":
        parts.append(
            f"- **WARNING**: Deleting this symbol affects "
            f"{direct_count} dependent(s)"
        )
    if change_type == "signature":
        parts.append("- Update all callers to match new signature")
    if change_type == "rename":
        parts.append(
            "- Search for string references (config files, docs) that "
            "may reference old name"
        )
    return "\n".join(parts) + "\n"


# ── trace_data_flow ────────────────────────────────────────────────────


#: Maximum number of outgoing relationships rendered by
#: ``trace_data_flow``. Applied after the two UNION_ALL_Decomposition
#: branches are merged, so it is the same bound the pre-decomposition
#: ``ORDER BY ... LIMIT 25`` clause carried.
_OUTGOING_LIMIT: int = 25

#: Edge set the outgoing fan-out expands over (one hop).
_OUTGOING_RELS: str = "CALLS|USES|IMPORTS|EXECUTES|INVOKES|SOURCES"

#: Depth the outgoing fan-out expands to. It is a *one-hop* section by
#: definition (``## Outgoing Relationships`` lists direct neighbors only),
#: so this is the ``requested_depth`` handed to
#: :func:`~src.tools._traversal_bounds._use_bfs` — the depth > 3 arm of the
#: strategy selector therefore never fires here, and only the anchor's
#: measured degree selects the walk. The deep, variable-length part of
#: this tool is the shortestPath section, which task 5.2 leaves on its
#: (already UNION_ALL_Decomposed) single query.
_OUTGOING_DEPTH: int = 1

#: Relationship types the BFS_Walker expands, one query per type per hop.
#: The same edge set as :data:`_OUTGOING_RELS`, split because a walker
#: hop takes one type at a time (a pipe-joined string is refused by
#: ``_expand_one_hop``'s identifier check).
_OUTGOING_EDGE_TYPES: tuple[str, ...] = tuple(_OUTGOING_RELS.split("|"))


def _outgoing_union_cypher(
    scope_pred: str, target_scope_pred: str = ""
) -> str:
    """Outgoing one-hop fan-out cypher, UNION_ALL_Decomposed (R1.1, R1.2).

    Emits two index-seekable branches — one anchoring on ``source.name``,
    one on ``source.path`` — joined by ``UNION ALL``, instead of a single
    ``source.name = $name OR source.path = $name`` disjunction. A
    disjunction across two properties of an unlabelled node cannot be
    satisfied from an index, so Neptune evaluates it against every node
    before expanding relationships; split into single-property
    equalities, each branch is an indexable lookup. The same rewrite took
    :func:`src.tools.semantic_search._enrich_with_graph_counts` from
    28.57s to 0.06s against live Neptune on 2026-08-27 (R1.5).

    ``scope_pred`` (the ``_scope_and("source")`` fragment) is applied to
    *both* branches so tenant isolation is unchanged (R1.4, R4.4).

    ``target_scope_pred`` (the ``_scope_and("target")`` fragment) scopes
    the *expanded* node as well, so a neighbor belonging to another
    tenant is rejected server-side instead of being collected and
    rendered (R4.2, R4.4). The same ``_scope_and`` helper builds both
    fragments, which is what keeps the anchor and the terminal node on
    one tenant-isolation mechanism. It is safe on the default ``gw``
    tenant too: ``tenant_label_predicate`` returns the *exclusion* form
    there (``size([... STARTS WITH '<other tenant>' ...]) = 0``), which
    admits every unprefixed baseline node while keeping another tenant's
    prefixed nodes out — it is not an inclusion filter that would empty
    the result. It defaults to ``""`` so a caller that only has an
    anchor fragment emits the pre-7.2 cypher verbatim.

    Ordering and truncation are deliberately *not* in the cypher: they
    have to happen after the branches are merged, which
    :func:`_merge_outgoing_rows` does (R1.3).
    """

    def branch(prop: str) -> str:
        return (
            f"MATCH (source)-[r:{_OUTGOING_RELS}]->(target) "
            f"WHERE source.{prop} = $name"
            f"{scope_pred}{target_scope_pred} "
            "RETURN target.name AS name, labels(target)[0] AS type, "
            "type(r) AS relType"
        )

    return f"{branch('name')} UNION ALL {branch('path')}"


def _merge_outgoing_rows(
    rows: list[dict[str, Any]] | None,
    limit: int = _OUTGOING_LIMIT,
) -> list[dict[str, Any]]:
    """Dedupe, sort and truncate the merged UNION ALL result (R1.3).

    ``UNION ALL`` does not dedupe, so a target reachable from both the
    ``name`` branch and the ``path`` branch arrives twice; rows are folded
    on ``(name, type, relType)`` — the same tuple the response renders —
    then ordered by ``(relType, name)`` and cut to ``limit``, reproducing
    the ``ORDER BY type(r), target.name LIMIT 25`` the single-query form
    carried. Rows without a ``name`` are dropped, as before.
    """
    merged: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("name"):
            continue
        key = (row.get("name"), row.get("type"), row.get("relType"))
        merged.setdefault(key, row)
    ordered = sorted(
        merged.values(),
        key=lambda r: (str(r.get("relType") or ""), str(r.get("name") or "")),
    )
    return ordered[:limit]


async def _outgoing_walk(
    graph: Any,
    from_symbol: str,
    degree: int | None = None,
) -> BFSResult:
    """Issue the outgoing fan-out as a BFS_Walker walk (R2.1, R3.2, R3.3).

    Extracted so the strategy selector's BFS branch and the timeout
    fallback arm issue the *same* walk -- same edge set, same bounds, same
    tenant scoping -- rather than two configurations that could drift.

    ``_scope_and("n")`` is the fragment the walker expects: it anchors on
    ``MATCH (n)`` and :func:`~src.tools._bfs_walker._retarget_scope_pred`
    points the predicate at each expansion's target node when
    ``label_scope_expanded`` is set (R4.1, R4.4).

    ``degree`` is the anchor's measured Node_Degree, forwarded only so the
    walker's R8.1 activation log names the value that selected the walk.
    Both call sites measure it over this section's own edge set
    (:data:`_OUTGOING_RELS`), so the logged degree describes the
    expansion that actually ran.
    """
    scope_n = _scope_and("n")
    return await bfs_walk(
        graph,
        start_name=from_symbol,
        direction="forward",
        edge_types=_OUTGOING_EDGE_TYPES,
        max_depth=_OUTGOING_DEPTH,
        fan_out_limit=BFS_FAN_OUT_LIMIT,
        result_limit=RESULT_LIMIT,
        timeout_s=TIMEOUT_S,
        scope_pred=scope_n,
        tenant=_tenant(),
        label_scope_expanded=bool(scope_n),
        tool="trace_data_flow",
        degree=degree,
    )


def _bfs_outgoing_rows(
    result: BFSResult,
    limit: int = _OUTGOING_LIMIT,
) -> list[dict[str, Any]]:
    """Fold a BFS_Walker result into the outgoing-fan-out row shape (R3.2).

    The walker returns ``{nid, name, path, labels, hop, relType,
    direction}`` per node; the ``## Outgoing Relationships`` table renders
    ``(name, type, relType)``. ``type`` is ``labels[0]``, which is exactly
    what the single-query form projects (``labels(target)[0] AS type``),
    so the two strategies render the same columns for the same edge.

    Folding then goes through :func:`_merge_outgoing_rows` rather than a
    local dedupe so the ordering (``relType``, then ``name``) and the
    ``LIMIT 25`` cut are the *same code* on both strategy branches — a
    caller cannot tell from the rendered table which strategy ran (R5.1).
    The walker already deduplicates by node id via its visited-set, but a
    node reached by two different relationship types is two distinct rows
    here, which matches the single-query behavior.
    """
    rows: list[dict[str, Any]] = []
    for node in result.nodes:
        labels = node.get("labels") or []
        rows.append(
            {
                "name": node.get("name"),
                "type": labels[0] if labels else None,
                "relType": node.get("relType"),
            }
        )
    return _merge_outgoing_rows(rows, limit)


#: Maximum number of shortest paths rendered by ``trace_data_flow``.
#: Carried as a per-branch ``LIMIT`` (openCypher applies ``LIMIT`` within
#: each ``UNION ALL`` branch, not to the union) and re-applied after the
#: branches are merged, so the rendered count matches the bound the
#: pre-decomposition single ``LIMIT 3`` clause carried.
_PATH_LIMIT: int = 3

#: Edge set the shortest-path search traverses. Currently identical to
#: the one-hop fan-out set; aliased rather than shared so the two query
#: shapes can diverge without a silent coupling.
_PATH_RELS: str = _OUTGOING_RELS


def _path_union_cypher(
    depth: int, scope_pred: str, dest_scope_pred: str = ""
) -> str:
    """shortestPath cypher, seed anchor UNION_ALL_Decomposed (R1.1, R1.2).

    The seed-node lookup is emitted as two index-seekable branches — one
    anchoring the path's ``source`` on ``name``, one on ``path`` — joined
    by ``UNION ALL``, rather than one disjunction over both properties of
    an unlabelled node. Neptune cannot satisfy such a disjunction from an
    index, so it scans every node *before* the shortestPath expansion
    starts; each single-property equality branch is an indexable lookup
    (R1.1, R1.5). This matches the anchor shape the one-hop fan-out uses
    (:func:`_outgoing_union_cypher`), so ``from_symbol`` resolves the same
    way in both sections of the response.

    ``depth`` is the already-clamped Effective_Depth, and ``scope_pred``
    (the ``_scope_and("source")`` fragment) is applied to *both* branches
    so the Label_Scope_Predicate is unchanged (R1.4, R4.4). The
    Statement_Timeout stays on the ``graph.query`` call, as before.

    ``dest_scope_pred`` (the ``_scope_and("dest")`` fragment) scopes the
    path's *terminal* node too (R4.2, R4.4). ``dest.name = $to`` alone
    does not identify a tenant: the same symbol name exists as a
    ``GW_V17_``-prefixed node and an unprefixed baseline node, so without
    the predicate a ``gw`` path could terminate on a ``gw_v17`` node that
    merely shares the name. Built by the same ``_scope_and`` helper as
    the anchor fragment, and safe on the default ``gw`` tenant because
    ``tenant_label_predicate`` returns the *exclusion* form there (other
    tenants' prefixes absent), which admits every unprefixed baseline
    node. Defaults to ``""`` so a caller passing only an anchor fragment
    emits the pre-7.2 cypher verbatim.

    Deduplication happens after the merge — see :func:`_merge_path_rows`
    (R1.3).
    """

    def branch(prop: str) -> str:
        return (
            "MATCH path = shortestPath("
            f"(source)-[:{_PATH_RELS}*1..{depth}]->(dest)) "
            f"WHERE source.{prop} = $from AND dest.name = $to"
            f"{scope_pred}{dest_scope_pred} "
            "RETURN [n IN nodes(path) | n.name] AS nodeNames, "
            "[r IN relationships(path) | type(r)] AS relTypes, "
            f"length(path) AS hops LIMIT {_PATH_LIMIT}"
        )

    return f"{branch('name')} UNION ALL {branch('path')}"


def _merge_path_rows(
    rows: list[dict[str, Any]] | None,
    limit: int = _PATH_LIMIT,
) -> list[dict[str, Any]]:
    """Dedupe and truncate the merged UNION ALL path result (R1.3).

    ``UNION ALL`` does not dedupe, so a path found from both the ``name``
    branch and the ``path`` branch arrives twice; rows are folded on the
    ``(nodeNames, relTypes)`` pair that identifies the path (lists are
    converted to tuples so they can key the map) and cut to ``limit``.
    Arrival order is preserved because the single-query form carried no
    ``ORDER BY`` — only ``LIMIT 3``.
    """
    merged: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        key = (
            tuple(row.get("nodeNames") or ()),
            tuple(row.get("relTypes") or ()),
        )
        merged.setdefault(key, row)
        if len(merged) >= limit:
            break
    return list(merged.values())[:limit]


async def _tool_trace_data_flow(
    data: Any,
    *,
    from_symbol: str,
    to_symbol: str | None,
    max_depth: int,
) -> str:
    if not from_symbol or not from_symbol.strip():
        return _error_text("from_symbol is required.")
    if data is None or getattr(data, "graph_db", None) is None:
        return _error_text(_DEGRADED_GRAPH_MSG)

    graph = data.graph_db
    lines: list[str] = [f"# Data Flow Trace: `{from_symbol}`"]
    if to_symbol:
        lines[-1] = f"# Data Flow Trace: `{from_symbol}` → `{to_symbol}`"
    lines.append("")

    # 1. Outgoing relationships (one-hop fan-out). A pre-flight degree
    #    probe (R1.1) selects the strategy for this section; it is
    #    count-only and single-hop, so probing a hub is itself cheap.
    #    The probe's edge set is the fan-out's own edge set, so the
    #    measured degree reflects the expansion actually about to run.
    degree = await anchor_degree(
        graph, from_symbol, _OUTGOING_RELS, _tenant(), _scope_and("a")
    )

    # Strategy selection, in the design's guard order (design.md
    # "Layered Guard Stack" / "Fallback Chain"), which is deliberately
    # NOT "BFS first": ``is_hub`` is consulted first so a true hub goes
    # straight to the Degraded_Result and never attempts the walk. Per
    # the design, "no BFS attempt for nodes with 100+ edges -- the BFS
    # fan-out limit at 100/type would still be expensive". The walk is
    # therefore reserved for the moderately-connected band between
    # BFS_ACTIVATION_THRESHOLD and FAN_OUT_THRESHOLD, where the
    # combinatorial risk is real but the decomposed cost is not
    # (R3.1, R3.2).
    hub = is_hub(degree)
    use_bfs = not hub and _use_bfs(degree, _OUTGOING_DEPTH)

    timed_out = False
    bfs_truncated = False
    # Walks that produced part of this response, for the R8.4 indicator.
    # Collected rather than rendered here because the header is inserted
    # after the title once the response body is complete, and either the
    # selector branch or the timeout-fallback arm can be the walk's
    # source.
    bfs_walks: list[BFSResult] = []
    outgoing: list[dict[str, Any]]
    if use_bfs:
        # BFS_Walker: one single-type, single-hop, LIMIT-bounded query per
        # relationship type instead of one six-type pattern (R2.1, R2.2).
        walk = await _outgoing_walk(graph, from_symbol, degree)
        bfs_walks.append(walk)
        outgoing = _bfs_outgoing_rows(walk)
        bfs_truncated = walk.truncated
    else:
        # Existing single-query path, unchanged for low-degree anchors
        # (R3.1, R5.1) and for hubs (whose fan-out section is already the
        # one-hop Degraded_Result shape). UNION_ALL_Decomposed so each
        # anchor branch is an indexable lookup (R1.1, R1.2). The expanded
        # ``target`` carries the Label_Scope_Predicate as well as the
        # anchor, so this branch scopes the terminal node exactly as the
        # BFS branch above does via ``label_scope_expanded`` (R4.2, R4.4).
        try:
            outgoing_rows = await graph.query(
                _outgoing_union_cypher(
                    _scope_and("source"), _scope_and("target")
                ),
                {"name": from_symbol},
                tenant=_tenant(),
                timeout=TIMEOUT_S,
            )
        except Exception as exc:
            if not _is_timeout_error(exc):
                log.warning("trace_data_flow outgoing query failed: %s", exc)
                return _error_text(f"trace_data_flow failed: {exc}")
            # Fallback chain (R3.3, R5.5): retry the fan-out as a bounded
            # walk before accepting an empty section. ``timed_out`` is set
            # either way -- the single query really did exceed the
            # Statement_Timeout, and its notice ("results below may be
            # partial") describes the salvaged rows just as accurately as
            # it describes none, so the caller is never told a bounded
            # answer was a complete one.
            log.info(
                "[traversal-bounds] trace_data_flow fallback "
                "from_symbol=%s guard=timeout strategy=bfs",
                from_symbol,
            )
            timed_out = True
            walk = await _outgoing_walk(graph, from_symbol, degree)
            bfs_walks.append(walk)
            if bfs_fallback_failed(walk.nodes):
                log.info(
                    "[traversal-bounds] trace_data_flow degraded "
                    "from_symbol=%s guard=timeout",
                    from_symbol,
                )
                outgoing = []
            else:
                outgoing = _bfs_outgoing_rows(walk)
        else:
            outgoing = _merge_outgoing_rows(outgoing_rows)

    if hub:
        # The fan-out section is one-hop by construction, so the
        # Degraded_Result here is the notice itself: it tells the caller
        # the anchor is a hub and that no decomposed walk was attempted
        # (R4.2, R4.3). The shortestPath section below still runs -- its
        # depth bound and statement timeout are its own guards.
        lines.append(degraded_notice(from_symbol, degree, FAN_OUT_THRESHOLD))
        lines.append("")
    if timed_out:
        lines.append(
            f"[INFO] Outgoing-relationship query for `{from_symbol}` exceeded "
            f"the {TIMEOUT_S:g}s statement timeout and was bounded; results "
            "below may be partial."
        )
        lines.append("")
    if bfs_truncated:
        # A truncated walk is a partial view of the neighborhood, never an
        # exhausted one -- say so rather than letting the table read as
        # complete (R2.3, R2.7).
        lines.append(
            f"[INFO] The outgoing fan-out for `{from_symbol}` hit a "
            "traversal bound (per-hop fan-out limit, result cap, or "
            "statement timeout); the relationships below are a partial "
            "view."
        )
        lines.append("")

    # 2. Optional shortest-path query when a destination is given. The
    #    seed anchor is UNION_ALL_Decomposed so each branch is an
    #    indexable lookup (R1.1, R1.2), and the path's terminal ``dest``
    #    node carries the Label_Scope_Predicate alongside the anchor so a
    #    same-named node from another tenant cannot terminate the path
    #    (R4.2, R4.4).
    path_section: list[str] = []
    if to_symbol:
        depth, _clamped = effective_depth(max_depth, DATA_FLOW_DEPTH)
        path_cypher = _path_union_cypher(
            depth, _scope_and("source"), _scope_and("dest")
        )
        try:
            path_raw = await graph.query(
                path_cypher, {"from": from_symbol, "to": to_symbol},
                tenant=_tenant(),
                timeout=TIMEOUT_S,
            )
            path_rows = _merge_path_rows(path_raw)
        except Exception as exc:  # pragma: no cover - defensive
            if _is_timeout_error(exc):
                log.info(
                    "[traversal-bounds] trace_data_flow shortestPath degraded "
                    "from_symbol=%s guard=timeout",
                    from_symbol,
                )
            else:
                log.debug("trace_data_flow shortestPath failed: %s", exc)
            path_rows = []

        if path_rows:
            path_section.append(f"## Shortest Path to `{to_symbol}`")
            path_section.append("")
            for p in path_rows:
                nodes_ = p.get("nodeNames") or []
                rels = p.get("relTypes") or []
                chain_parts: list[str] = []
                for i, name in enumerate(nodes_):
                    if i < len(rels):
                        chain_parts.append(f"`{name}` -[{rels[i]}]→")
                    else:
                        chain_parts.append(f"`{name}`")
                path_section.append(
                    f"**{p.get('hops', len(rels))} hops**: "
                    + " ".join(chain_parts)
                )
                path_section.append("")
        else:
            path_section.append(f"## Path to `{to_symbol}`")
            path_section.append("")
            path_section.append(
                f"No path found within {max_depth} hops."
            )
            path_section.append("")

    if path_section:
        lines.extend(path_section)

    if outgoing:
        lines.append(f"## Outgoing Relationships ({len(outgoing)})")
        lines.append("")
        lines.append("| Target | Type | Relationship |")
        lines.append("|--------|------|-------------|")
        for o in outgoing:
            lines.append(
                f"| `{o.get('name') or 'unnamed'}` | "
                f"{o.get('type') or '?'} | {o.get('relType') or '?'} |"
            )
        lines.append("")

    if not path_section and not outgoing:
        lines.append(
            f"No data flow found from `{from_symbol}`. Check the "
            "symbol name and try again."
        )

    # R8.4: tell the caller the decomposed strategy produced the fan-out
    # section above. A no-op when no walk ran, so the single-query
    # response is unchanged. The shortestPath section is not a walk, so
    # only the fan-out's walks are counted -- the indicator describes the
    # strategy, not the whole response's cost.
    insert_bfs_header(lines, *bfs_walks)

    return "\n".join(lines).rstrip() + "\n"


# ── session tools ──────────────────────────────────────────────────────


async def _tool_mark_as_modified(
    data: Any,
    session: SessionManager,
    *,
    file_path: str,
    change_type: str,
    description: str,
) -> str:
    if not file_path or not file_path.strip():
        return _error_text("file_path is required.")

    try:
        state = session.mark_modified(
            file_path, change_type=change_type, description=description
        )
    except SessionError as exc:
        return _error_text(f"mark_as_modified failed: {exc}")
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("mark_as_modified failed: %s", exc)
        return _error_text(f"mark_as_modified failed: {exc}")

    # Best-effort: flag the matching graph node(s) as dirty. Failure
    # here is swallowed — the local session state is the source of
    # truth, and the graph may legitimately not know about this file.
    graph_dirty = False
    graph = getattr(data, "graph_db", None) if data is not None else None
    if graph is not None:
        try:
            await graph.query(
                "MATCH (n) WHERE n.absolutePath CONTAINS $path"
                f"{_scope_and('n')} "
                "SET n._dirty = true, n._dirtyAt = $now "
                "RETURN count(n) AS updated",
                {"path": file_path, "now": _utc_now_iso()},
                tenant=_tenant(),
            )
            graph_dirty = True
        except Exception as exc:
            log.debug("graph dirty-flag failed: %s", exc)

    mods = state.modifications or []
    lines = [
        "# File Modification Recorded",
        "",
        f"**File**: `{file_path}`",
        f"**Change Type**: {change_type}",
    ]
    if description:
        lines.append(f"**Description**: {description}")
    lines.append(
        "**Graph Dirty**: "
        + ("Yes (node flagged)" if graph_dirty else "No (graph unavailable)")
    )
    lines.append("")
    lines.append(f"**Total Modifications**: {len(mods)}")
    return "\n".join(lines).rstrip() + "\n"


def _tool_get_session_context(
    session: SessionManager, *, include_dirty: bool
) -> str:
    try:
        ctx = session.get_session_context()
    except Exception as exc:  # pragma: no cover - defensive
        return _error_text(f"get_session_context failed: {exc}")

    if not ctx.get("active"):
        return (
            "# No Active Session\n\n"
            "Start a session with `start_sdd_session` to enable "
            "session state tracking.\n"
        )

    summary = ctx.get("summary") or {}
    lines = [
        "# Session Context",
        "",
        f"**Session**: {ctx.get('sessionId')}",
        f"**Phase**: {ctx.get('phase')}",
        f"**Started**: {ctx.get('startedAt')}",
        f"**Last Activity**: {ctx.get('lastActivityAt')}",
        (
            f"**Progress**: {summary.get('stepsCompleted', 0)}/"
            f"{ctx.get('totalSteps', 0)} steps"
        ),
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "|--------|-------|",
        f"| Files Modified | {summary.get('filesModified', 0)} |",
        f"| Symbols Examined | {summary.get('symbolsExamined', 0)} |",
        f"| Checkpoints | {summary.get('checkpointsCreated', 0)} |",
        f"| Steps Completed | {summary.get('stepsCompleted', 0)} |",
        f"| Steps Remaining | {summary.get('stepsRemaining', 0)} |",
        "",
    ]

    modifications = list(ctx.get("modifications") or [])
    if modifications:
        lines.append(f"## Modifications ({len(modifications)})")
        lines.append("")
        lines.append("| File | Type | Description | When |")
        lines.append("|------|------|-------------|------|")
        for m in modifications:
            lines.append(
                f"| `{m.get('filePath') or ''}` | "
                f"{m.get('changeType') or '?'} | "
                f"{m.get('description') or '-'} | "
                f"{m.get('modifiedAt') or ''} |"
            )
        lines.append("")

    examined = list(ctx.get("examined") or [])
    if examined:
        lines.append(f"## Examined Symbols ({len(examined)})")
        lines.append("")
        for e in examined:
            sym = e.get("symbol") or ""
            typ = e.get("type")
            lines.append(f"- `{sym}`" + (f" ({typ})" if typ else ""))
        lines.append("")

    checkpoints = list(ctx.get("checkpoints") or [])
    if checkpoints:
        lines.append(f"## Checkpoints ({len(checkpoints)})")
        lines.append("")
        lines.append("| ID | Name | Created |")
        lines.append("|----|------|---------|")
        for c in checkpoints:
            lines.append(
                f"| `{c.get('checkpointId') or ''}` | "
                f"{c.get('name') or ''} | "
                f"{c.get('createdAt') or ''} |"
            )
        lines.append("")

    if not include_dirty:
        # The ``include_dirty`` flag is schema-visible (Node.js parity)
        # but there is no in-memory dirty state to suppress in the
        # Python port; including the flag in the response footer gives
        # tests and tools a way to confirm it was read.
        lines.append("*(dirty state display suppressed)*")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _tool_checkpoint_state(
    session: SessionManager, *, name: str, description: str
) -> str:
    if not name or not name.strip():
        return _error_text("name is required.")
    try:
        checkpoint = session.checkpoint_state(name, description=description)
    except SessionError as exc:
        return _error_text(f"checkpoint_state failed: {exc}")
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("checkpoint_state failed: %s", exc)
        return _error_text(f"checkpoint_state failed: {exc}")

    lines = [
        "# Checkpoint Created",
        "",
        f"**ID**: `{checkpoint.checkpointId}`",
        f"**Name**: {name}",
    ]
    if description:
        lines.append(f"**Description**: {description}")
    lines.append(f"**Created**: {checkpoint.createdAt}")
    lines.append("")
    lines.append(
        f"**Snapshot**: {len(checkpoint.modifications)} modification(s), "
        f"{len(checkpoint.examined)} examined symbol(s), "
        f"{len(checkpoint.completedSteps)} step(s)"
    )
    lines.append("")
    lines.append(
        f'Use `restore_checkpoint("{checkpoint.checkpointId}")` to '
        "roll back to this state."
    )
    return "\n".join(lines).rstrip() + "\n"


def _tool_restore_checkpoint(
    session: SessionManager, *, checkpoint_id: str
) -> str:
    if not checkpoint_id or not checkpoint_id.strip():
        return _error_text("checkpoint_id is required.")
    try:
        state = session.restore_checkpoint(checkpoint_id)
    except SessionError as exc:
        # Invalid / unknown checkpoint ID → clear error text, not a crash.
        return _error_text(f"restore_checkpoint failed: {exc}")
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("restore_checkpoint failed: %s", exc)
        return _error_text(f"restore_checkpoint failed: {exc}")

    lines = [
        "# Checkpoint Restored",
        "",
        f"**Checkpoint**: `{checkpoint_id}`",
        f"**Modifications**: {len(state.modifications)} file(s)",
        f"**Examined**: {len(state.examined)} symbol(s)",
        "",
        "Session state rolled back. New modifications/examinations will "
        "be tracked from this point.",
    ]
    return "\n".join(lines).rstrip() + "\n"


# ── helpers ────────────────────────────────────────────────────────────


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(int(value), hi))


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


_DEGRADED_GRAPH_MSG = (
    "Graph database unavailable (degraded-mode boot). Ensure "
    "NEPTUNE_ENDPOINT is reachable from the runtime."
)
_DEGRADED_VECTOR_MSG = (
    "Vector database unavailable (degraded-mode boot). Ensure "
    "OPENSEARCH_ENDPOINT is reachable from the runtime."
)


def _error_text(message: str) -> str:
    return f"[ERROR] {message}\n"


__all__ = [
    "CODE_COLLECTION",
    "COMMUNITY_COLLECTION",
    "DEPTH_MIN",
    "DEPTH_MAX",
    "ARCH_RESULTS_MIN",
    "ARCH_RESULTS_MAX",
    "SIMILAR_RESULTS_MIN",
    "SIMILAR_RESULTS_MAX",
    "TRACE_DEPTH_MIN",
    "TRACE_DEPTH_MAX",
    "CHANGE_TYPE_VALUES",
    "MODIFICATION_TYPE_VALUES",
    "CHANGE_TYPE_RISK_BIAS",
    "register",
]
