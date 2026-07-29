"""Semantic search tools (Requirements 4.1 – 4.7, Task 8 Phase B5).

Python port of the 7 tools in
``mcp_server_node/src/tools/SemanticSearchTools.js``. Tool names and
input schemas match the Node.js ``UnifiedMCPServer.js`` registrations
exactly so the parity framework can compare results side-by-side.

The module wires into the FastMCP server via the standard
``register(mcp, data)`` entrypoint. ``data`` is the
``UnifiedDataAccess``-shaped facade the Python port uses; it exposes
``vector_db`` (``VectorDBProtocol``) and ``graph_db``
(``GraphDBProtocol``). Degraded-mode boot (``data is None``) is
supported — every tool returns a clear error message instead of
crashing, matching the Node.js behaviour when ChromaDB / Neo4j are
unavailable.

Design notes
------------

* The Node.js implementation calls a ``UnifiedDataAccess`` facade with
  methods like ``hybridQuery`` / ``multiSourceSearch`` /
  ``findRelatedCode``. The Python port talks directly to the
  ``VectorDBProtocol`` (``query`` / ``multi_collection_query`` /
  ``health_check``) and ``GraphDBProtocol`` (``query``) surfaces so the
  port is backend-agnostic (OpenSearch + Neptune today, something else
  tomorrow).

* ``search_documentation`` supports two modes matching the Node.js
  semantics:

  - With ``collection`` set: single-collection hybrid BM25 + k-NN via
    ``vector_db.query(collection, ...)``.
  - Without ``collection`` (the default): multi-collection fan-out via
    ``vector_db.multi_collection_query([...], ...)``.

  When ``include_graph=True`` and a graph adapter is available, each
  hit is annotated with the count of 1-hop graph neighbours around its
  ``source_file`` — the same enrichment the Node.js path does.

* ``get_knowledge_base_status`` is specifically the tool currently
  failing on the Node.js runtime with
  ``Max connection limit reached. Limit = 1000``. The Python port
  relies on ``opensearch-py`` (which pools connections natively) via
  the ``OpenSearchAdapter.health_check`` path, so the failure mode
  does not repeat here.

* ``list_ingested_urls`` and ``get_ingested_urls_array`` read a baked-in
  copy of ``documentation_sources.json`` from
  ``src/config/documentation_sources.json`` in the container (or a
  developer's working tree). The resolver also searches
  ``mcp_server_node/config/`` so local dev keeps working without a
  duplicated file. Override with ``MCP_DOCUMENTATION_SOURCES_PATH``.

* ``check_knowledge_integrity`` runs Phase 43's four-check battery
  (path consistency, orphaned graph nodes, stale embeddings, coverage
  gap) against the current adapters. For OpenSearch the implementation
  uses ``scroll`` sampling rather than ChromaDB's ``get(limit, offset)``
  since OpenSearch doesn't support the latter — the outcome is the
  same "random sample of up to N documents with metadata".

All tool return values are markdown strings, matching the Node.js
``TextContent`` block output.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal, Protocol

from fastmcp import FastMCP

from src.manifest import (
    GapDetector,
    GapReport,
    ManifestRegistry,
    SourceEntry,
    SourceType,
)
from src.tenancy.resolver import get_current_tenant_or_none
from src.tools._common import (
    _is_missing_index_exc,
    _missing_index_skip,
    _tenant_id_or_none,
)

log = logging.getLogger(__name__)


def _tenant():
    """Return the active tenant or None (for adapter kwarg)."""
    ctx = get_current_tenant_or_none()
    return ctx.tenant if ctx else None


# ── constants ───────────────────────────────────────────────────────────


#: Default collections searched by ``search_documentation`` when the
#: caller does not pin a specific collection. Matches the Node.js
#: ``UnifiedDataAccess.multiSourceSearch`` default fan-out.
DEFAULT_SEARCH_COLLECTIONS: tuple[str, ...] = (
    "global-workflow-docs-v8-0-0",
    "code-with-context-v8-0-0",
    "jjobs-v8-0-0",
    "ee2-standards-v5-0-0-enhanced",
    "community-summaries",
)

#: Collections surfaced in the ``collection`` parameter's help text. This
#: mirrors the Node.js schema's description field verbatim so tool list
#: displays are identical between runtimes.
COLLECTION_HELP_LIST: str = ", ".join(
    [
        "global-workflow-docs-v8-0-0",
        "jjobs-v8-0-0",
        "ee2-standards-v5-0-0-enhanced",
    ]
)

#: Collections filtered by ``context_type`` in ``explain_with_context``.
CONTEXT_TYPE_COLLECTIONS: dict[str, tuple[str, ...]] = {
    "technical": ("code-with-context-v8-0-0", "global-workflow-docs-v8-0-0"),
    "operational": ("jjobs-v8-0-0", "global-workflow-docs-v8-0-0"),
    "configuration": (
        "global-workflow-docs-v8-0-0",
        "ee2-standards-v5-0-0-enhanced",
    ),
    "all": DEFAULT_SEARCH_COLLECTIONS,
}

#: Semantic hits fetched per ``detail_level`` for ``explain_with_context``.
DETAIL_LEVEL_LIMITS: dict[str, int] = {
    "basic": 3,
    "intermediate": 5,
    "advanced": 8,
}

#: Default sample size for ``check_knowledge_integrity``.
DEFAULT_INTEGRITY_SAMPLE_SIZE: int = 50

#: Prefixes that indicate a checkout-specific (bad) file path. See
#: Phase 43 path-consistency check.
BAD_PATH_PREFIXES: tuple[str, ...] = ("/home/", "/scratch/", "/mcp_rag_eib/")

#: How old an embedding can be (in days) before ``check_knowledge_integrity``
#: considers it stale when no git-based comparison is available. Matches the
#: Node.js fallback threshold.
STALE_EMBEDDING_DAYS: int = 30

#: Where the baked-in copy of ``documentation_sources.json`` lives when
#: running under the Docker image produced by ``mcp_server_python/Dockerfile``.
BUNDLED_DOC_SOURCES_PATH: Path = (
    Path(__file__).resolve().parent.parent / "config" / "documentation_sources.json"
)


# ── data-layer protocol ─────────────────────────────────────────────────


class _DataAccess(Protocol):
    """Structural contract the semantic search tools need from ``data``.

    Any object exposing ``vector_db`` / ``graph_db`` attributes (the
    ``UnifiedDataAccess`` facade or the ``MockUnifiedDataAccess`` in
    tests) is accepted. Kept as a plain Protocol so callers don't need
    to import the concrete type.
    """

    vector_db: Any
    graph_db: Any | None


# ── public entrypoint ───────────────────────────────────────────────────


def register(
    mcp: FastMCP,
    data: Any = None,
    *,
    catalog: "Any | None" = None,
    manifest_registry: ManifestRegistry | None = None,
    documentation_sources_path: str | os.PathLike[str] | None = None,
    repo_base: str | os.PathLike[str] | None = None,
) -> None:
    """Register all 7 semantic-search tools on ``mcp``.

    Parameters
    ----------
    mcp
        The FastMCP server instance.
    data
        ``UnifiedDataAccess``-shaped facade. ``None`` triggers
        degraded-mode — tools return error messages rather than
        crashing.
    manifest_registry
        Optional :class:`ManifestRegistry` carrying the unified ingest
        manifest. When provided, ``list_all_sources``,
        ``list_ingested_urls``, and ``get_ingested_urls_array`` read
        from the registry; when ``None`` they fall back to the legacy
        file-based resolver below (Requirements 4.1, 4.2, 6.1).
    documentation_sources_path
        Override for the path to ``documentation_sources.json``.
        Defaults to the ``MCP_DOCUMENTATION_SOURCES_PATH`` env var,
        then to the bundled copy at ``src/config/``. Used as the
        legacy fallback when ``manifest_registry`` is ``None``.
    repo_base
        Optional override for the path used by
        ``check_knowledge_integrity`` to count Fortran files on disk
        and run ``git log`` for stale-embedding detection. Defaults to
        ``supported_repos/global-workflow_develop`` relative to the working
        tree, matching the Node.js layout.
    """
    from src.tenancy.runtime import get_catalog
    catalog = catalog or get_catalog()
    doc_sources_resolver = _make_doc_sources_resolver(documentation_sources_path)

    from src.tools._tenant_helper import run_tenant_scoped

    @mcp.tool(
        name="search_documentation",
        description=(
            "Hybrid semantic + graph search across workflow documentation "
            "and code. Runs BM25 + k-NN (RRF) against the vector store "
            "and optionally enriches each hit with graph neighbourhood "
            "statistics."
        ),
    )
    async def search_documentation(
        query: str,
        collection: str | None = None,
        max_results: int = 8,
        include_graph: bool = True,
        similarity_threshold: float = 0.1,
        tenant_id: str | None = None,
    ) -> str:
        return await run_tenant_scoped(
            tenant_id, catalog,
            lambda: _tool_search_documentation(
                data, query=query, collection=collection,
                max_results=max_results, include_graph=include_graph,
                similarity_threshold=similarity_threshold,
            ),
        )

    @mcp.tool(
        name="find_related_files",
        description=(
            "Find files with similar dependencies and import relationships. "
            "Traverses IMPORTS / USES edges from the seed file and returns "
            "other files importing the same modules, optionally with "
            "related documentation."
        ),
    )
    async def find_related_files(
        file_path: str,
        max_results: int = 10,
        include_documentation: bool = True,
        tenant_id: str | None = None,
    ) -> str:
        return await run_tenant_scoped(
            tenant_id, catalog,
            lambda: _tool_find_related_files(
                data, file_path=file_path, max_results=max_results,
                include_documentation=include_documentation,
            ),
        )

    @mcp.tool(
        name="explain_with_context",
        description=(
            "Provide comprehensive explanations using hybrid search. "
            "Combines documentation vector hits with graph structure "
            "around the topic, filtered by context_type."
        ),
    )
    async def explain_with_context(
        topic: str,
        context_type: Literal[
            "technical", "operational", "configuration", "all"
        ] = "all",
        detail_level: Literal["basic", "intermediate", "advanced"] = "intermediate",
        tenant_id: str | None = None,
    ) -> str:
        return await run_tenant_scoped(
            tenant_id, catalog,
            lambda: _tool_explain_with_context(
                data, topic=topic, context_type=context_type,
                detail_level=detail_level,
            ),
        )

    @mcp.tool(
        name="get_knowledge_base_status",
        description=(
            "Get comprehensive knowledge base statistics. Reports "
            "vector index / document counts, graph node / "
            "relationship counts, and overall health. Backend labels "
            "reflect the active DB_BACKEND (ChromaDB + Neo4j for "
            "cots, OpenSearch + Neptune for aws). The graph node count "
            "is tenant-scoped; pass all_tenants=True to also report the "
            "whole-graph count. See "
            "docs/development/graph_node_count_scopes.md for the scope model."
        ),
    )
    async def get_knowledge_base_status(
        include_graph: bool = True,
        include_vector: bool = True,
        all_tenants: bool = False,
        tenant_id: str | None = None,
    ) -> str:
        return await run_tenant_scoped(
            tenant_id, catalog,
            lambda: _tool_get_knowledge_base_status(
                data, include_graph=include_graph,
                include_vector=include_vector,
                all_tenants=all_tenants,
            ),
        )

    @mcp.tool(
        name="list_ingested_urls",
        description=(
            "List all URLs that have been ingested into the RAG knowledge "
            "base. Supports detailed / summary / urls_only output formats "
            "and source_filter substring matching."
        ),
    )
    async def list_ingested_urls(
        format: Literal["detailed", "summary", "urls_only"] = "detailed",
        source_filter: str | None = None,
    ) -> str:
        return await _tool_list_ingested_urls(
            data,
            manifest_registry=manifest_registry,
            doc_sources_resolver=doc_sources_resolver,
            fmt=format,
            source_filter=source_filter,
        )

    @mcp.tool(
        name="get_ingested_urls_array",
        description=(
            "Get a structured markdown-formatted array of all ingested "
            "documentation URLs for programmatic access."
        ),
    )
    async def get_ingested_urls_array(include_failed: bool = False) -> str:
        return _tool_get_ingested_urls_array(
            manifest_registry=manifest_registry,
            doc_sources_resolver=doc_sources_resolver,
            include_failed=include_failed,
        )

    @mcp.tool(
        name="list_all_sources",
        description=(
            "List every ingestion source declared in the unified manifest "
            "across all 7 source types (url_crawl, on_disk_submodule, "
            "code_parse, config_parse, standards, community_summary, "
            "jjob_docs). Supports source_type / collection filters, "
            "summary vs detailed output, and optional gap detection "
            "comparing declared vs actual OpenSearch document counts."
        ),
    )
    async def list_all_sources(
        source_type: Literal[
            "url_crawl",
            "on_disk_submodule",
            "code_parse",
            "config_parse",
            "standards",
            "community_summary",
            "jjob_docs",
        ]
        | None = None,
        collection: str | None = None,
        format: Literal["summary", "detailed"] = "summary",
        include_gaps: bool = False,
    ) -> str:
        return await _tool_list_all_sources(
            data,
            manifest_registry=manifest_registry,
            source_type=source_type,
            collection=collection,
            fmt=format,
            include_gaps=include_gaps,
        )

    @mcp.tool(
        name="check_knowledge_integrity",
        description=(
            "Check knowledge base integrity: path consistency, orphaned "
            "nodes, stale embeddings, coverage gaps. Reports health of "
            "the knowledge base in a markdown table."
        ),
    )
    async def check_knowledge_integrity(
        sample_size: int = DEFAULT_INTEGRITY_SAMPLE_SIZE,
        tenant_id: str | None = None,
    ) -> str:
        return await run_tenant_scoped(
            tenant_id, catalog,
            lambda: _tool_check_knowledge_integrity(
                data, sample_size=sample_size,
                repo_base=_resolve_repo_base_with_tenant(repo_base),
            ),
        )

    log.info(
        "registered semantic search tools: search_documentation, "
        "find_related_files, explain_with_context, "
        "get_knowledge_base_status, list_ingested_urls, "
        "get_ingested_urls_array, list_all_sources, "
        "check_knowledge_integrity"
    )


# ── search_documentation ────────────────────────────────────────────────


async def _tool_search_documentation(
    data: Any,
    *,
    query: str,
    collection: str | None,
    max_results: int,
    include_graph: bool,
    similarity_threshold: float,
) -> str:
    if not query or not query.strip():
        return _error_text("Query is required.")
    if data is None or getattr(data, "vector_db", None) is None:
        return _error_text(_DEGRADED_VECTOR_MSG)

    # Clamp to the Node.js schema bounds (1-20). We accept the raw value
    # but silently cap to match the inputSchema validation the Node.js
    # MCP SDK performs server-side.
    k = max(1, min(int(max_results), 20))
    threshold = max(0.0, min(float(similarity_threshold), 1.0))

    try:
        if collection:
            hits = await data.vector_db.query(
                collection,
                query,
                k=k,
                similarity_threshold=threshold,
                include_graph=include_graph,
                tenant=_tenant(),
            )
            collection_label = f"collection: {collection}"
        else:
            hits = await data.vector_db.multi_collection_query(
                list(DEFAULT_SEARCH_COLLECTIONS),
                query,
                k=k,
                similarity_threshold=threshold,
                include_graph=include_graph,
                tenant=_tenant(),
            )
            collection_label = "multi-collection search"
    except Exception as exc:
        # Explicit-collection branch only: a genuine missing index for the
        # active tenant becomes a clean Skip_Block. The multi-collection
        # branch is intentionally untouched — multi_collection_query
        # swallows per-collection 404s and returns [], which still renders
        # as "No results found for: ..." (Property 4 / R3.5).
        if collection and _is_missing_index_exc(exc):
            return _missing_index_skip(
                tool="search_documentation",
                query=query,
                collection=collection,
                tenant_id=_tenant_id_or_none(),
            )
        log.warning("search_documentation failed: %s", exc)
        return _error_text(f"Error searching documentation: {exc}")

    if not hits:
        return f'No results found for: "{query}"\n'

    graph_counts: dict[str, int] = {}
    if include_graph and getattr(data, "graph_db", None) is not None:
        graph_counts = await _enrich_with_graph_counts(data.graph_db, hits, tenant=_tenant())

    lines: list[str] = [
        f"# Search Results: {query}",
        "",
        f"Found {len(hits)} results ({collection_label})",
        "",
    ]
    for hit in hits:
        lines.extend(_format_search_hit(hit, graph_counts))

    return "\n".join(lines).rstrip() + "\n"


def _format_search_hit(
    hit: dict[str, Any], graph_counts: dict[str, int]
) -> list[str]:
    """Render one vector-store hit as markdown (matches Node.js output).

    Preserves the Node.js ordering: title / similarity / source
    [/ collection] / graph context / body / divider.
    """
    metadata = hit.get("metadata") or {}
    title = (
        metadata.get("title")
        or metadata.get("source_file")
        or hit.get("id")
        or "Result"
    )
    score = float(hit.get("score") or 0.0)
    source = metadata.get("source") or metadata.get("source_file") or "Unknown"
    body = hit.get("content") or hit.get("document") or hit.get("text") or ""

    out = [f"## {title}", f"**Similarity:** {score * 100:.1f}%"]
    source_line = f"**Source:** {source}"
    collection_name = hit.get("collection") or metadata.get("collection")
    if collection_name:
        source_line += f" | **Collection:** {collection_name}"
    out.append(source_line)

    if graph_counts:
        key = metadata.get("source_file") or hit.get("id")
        if key and graph_counts.get(key):
            out.append(
                f"**Graph Context:** {graph_counts[key]} related entities"
            )
    out.extend(["", body, "", "---", ""])
    return out


async def _enrich_with_graph_counts(
    graph_db: Any, hits: list[dict[str, Any]], tenant: Any = None,
) -> dict[str, int]:
    """Return ``{source_file: neighbour_count}`` for each hit with a path.

    Runs one parameterised 1-hop cypher per unique source file. Failures
    are swallowed — graph enrichment is best-effort; the main vector
    result stands on its own.
    """
    keys: list[str] = []
    seen: set[str] = set()
    for h in hits:
        meta = h.get("metadata") or {}
        source = meta.get("source_file") or h.get("id")
        if source and source not in seen:
            seen.add(source)
            keys.append(source)
    if not keys:
        return {}

    cypher = (
        "MATCH (n)-[r]-(m) "
        "WHERE n.name = $name OR n.path = $name OR n.filepath = $name "
        "RETURN count(r) AS count"
    )

    async def _count(name: str) -> tuple[str, int]:
        try:
            rows = await graph_db.query(cypher, {"name": name}, tenant=tenant)
            if rows and isinstance(rows, list):
                return name, int(rows[0].get("count") or 0)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("graph enrichment for %r failed: %s", name, exc)
        return name, 0

    # Cap concurrent queries at a reasonable number so we don't flood
    # Neptune when a search returns 20 results.
    results = await asyncio.gather(*[_count(n) for n in keys[:20]])
    return {name: count for name, count in results if count > 0}


# ── find_related_files ──────────────────────────────────────────────────


async def _tool_find_related_files(
    data: Any,
    *,
    file_path: str,
    max_results: int,
    include_documentation: bool,
) -> str:
    if not file_path or not file_path.strip():
        return _error_text("file_path is required.")
    if data is None or getattr(data, "graph_db", None) is None:
        return _error_text(_DEGRADED_GRAPH_MSG)

    k = max(1, min(int(max_results), 20))

    # Resolve imports for the seed file. Uses a CONTAINS match so
    # callers can pass either an absolute or repository-relative path,
    # matching the Node.js ``findFileImports`` behaviour.
    imports_cypher = (
        "MATCH (f:File)-[:IMPORTS|USES|SOURCES|INVOKES]->(m) "
        "WHERE f.path CONTAINS $path OR f.name = $path "
        "RETURN DISTINCT coalesce(m.name, m.path) AS moduleName LIMIT 50"
    )
    related_cypher = (
        "MATCH (src:File)-[:IMPORTS|USES|SOURCES|INVOKES]->(m) "
        "WHERE (m.name IN $modules OR m.path IN $modules) "
        "AND NOT (src.path CONTAINS $path OR src.name = $path) "
        "RETURN DISTINCT coalesce(src.path, src.name) AS filePath LIMIT $limit"
    )

    try:
        imports_rows = await data.graph_db.query(
            imports_cypher, {"path": file_path}, tenant=_tenant()
        )
    except Exception as exc:
        log.warning("find_related_files: import query failed: %s", exc)
        return _error_text(
            f"Error finding related files: {exc}\n\n"
            "This tool searches for files with similar import "
            "dependencies based on graph relationships."
        )

    imports = [
        row["moduleName"]
        for row in imports_rows or []
        if row.get("moduleName")
    ]

    related_files: list[str] = []
    if imports:
        try:
            related_rows = await data.graph_db.query(
                related_cypher,
                {"modules": imports, "path": file_path, "limit": k},
                tenant=_tenant(),
            )
            related_files = [
                row["filePath"]
                for row in related_rows or []
                if row.get("filePath")
            ]
        except Exception as exc:
            log.warning("find_related_files: related query failed: %s", exc)

    documentation: list[dict[str, Any]] = []
    if include_documentation and imports and getattr(data, "vector_db", None):
        doc_query = " ".join(imports[:3])
        try:
            documentation = await data.vector_db.query(
                "global-workflow-docs-v8-0-0",
                doc_query,
                k=5,
                include_graph=False,
                tenant=_tenant(),
            )
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("find_related_files: doc fetch failed: %s", exc)

    # Render
    lines: list[str] = [
        "# Related Files by Dependencies",
        "",
        f'Query: "{file_path}"',
        "",
        f"Found {len(related_files)} related files",
        "",
    ]

    if related_files:
        lines.append("## Files with Similar Dependencies")
        lines.append("")
        for f in related_files[:k]:
            lines.append(f"- `{f}`")
        lines.append("")

    if imports:
        lines.append(f"## Shared Dependencies ({len(imports)})")
        lines.append("")
        for mod in imports[:10]:
            lines.append(f"- `{mod}`")
        if len(imports) > 10:
            lines.append(f"- *... and {len(imports) - 10} more*")
        lines.append("")

    if include_documentation and documentation:
        lines.append(f"## Related Documentation ({len(documentation)})")
        lines.append("")
        for doc in documentation[:3]:
            text = (
                doc.get("content") if isinstance(doc, dict) else None
            ) or (doc.get("document") if isinstance(doc, dict) else None) or ""
            # Match Node.js truncation at 200 chars + "..." suffix.
            snippet = text[:200]
            lines.append(f"{snippet}...")
            lines.append("")

    if not related_files and not imports:
        lines.insert(
            4,
            f'No related files found for: "{file_path}"\n\n'
            "This tool finds files with similar import dependencies. "
            "The file must exist in the graph database.\n",
        )

    return "\n".join(lines).rstrip() + "\n"


# ── explain_with_context ────────────────────────────────────────────────


async def _tool_explain_with_context(
    data: Any,
    *,
    topic: str,
    context_type: str,
    detail_level: str,
) -> str:
    if not topic or not topic.strip():
        return _error_text("topic is required.")
    if data is None or getattr(data, "vector_db", None) is None:
        return _error_text(_DEGRADED_VECTOR_MSG)

    max_hits = DETAIL_LEVEL_LIMITS.get(detail_level, 5)
    collections = list(
        CONTEXT_TYPE_COLLECTIONS.get(context_type, DEFAULT_SEARCH_COLLECTIONS)
    )

    try:
        vector_hits = await data.vector_db.multi_collection_query(
            collections,
            topic,
            k=max_hits,
            include_graph=False,
            tenant=_tenant(),
        )
    except Exception as exc:
        log.warning("explain_with_context: vector query failed: %s", exc)
        return _error_text(f"Error explaining with context: {exc}")

    graph_rows: list[dict[str, Any]] = []
    graph_db = getattr(data, "graph_db", None)
    if graph_db is not None:
        graph_cypher = (
            "MATCH (n) "
            "WHERE toLower(apoc.text.join([x IN apoc.convert.toList(n.name) | toString(x)], ' ')) CONTAINS toLower($topic) "
            "RETURN n.name AS name, labels(n) AS labels, "
            "n.path AS path LIMIT $limit"
        )
        try:
            rows = await graph_db.query(
                graph_cypher, {"topic": topic, "limit": max_hits},
                tenant=_tenant(),
            )
            graph_rows = list(rows or [])
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("explain_with_context: graph query failed: %s", exc)

    lines: list[str] = [
        f"# Explanation: {topic}",
        "",
        f"**Context Type:** {context_type}",
        f"**Detail Level:** {detail_level}",
        "",
    ]

    if vector_hits:
        lines.append("## Documentation Context")
        lines.append("")
        for hit in vector_hits[:3]:
            body = hit.get("content") or hit.get("document") or hit.get("text") or ""
            lines.append(body)
            lines.append("")

    if graph_rows:
        lines.append("## Code Structure Context")
        lines.append("")
        for row in graph_rows[:3]:
            name = row.get("name") or "Unknown"
            labels = row.get("labels") or []
            label_str = labels[0] if labels else "Component"
            lines.append(f"- **{name}**: {label_str}")
        lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append(
        "This explanation combines semantic documentation search with "
        "code structure analysis."
    )

    return "\n".join(lines).rstrip() + "\n"


# ── get_knowledge_base_status ───────────────────────────────────────────


async def _tool_get_knowledge_base_status(
    data: Any,
    *,
    include_graph: bool,
    include_vector: bool,
    all_tenants: bool = False,
) -> str:
    if data is None:
        return _error_text(_DEGRADED_DATA_MSG)

    lines: list[str] = ["# Knowledge Base Status", ""]

    if include_vector and getattr(data, "vector_db", None) is not None:
        lines.extend(await _render_vector_status_block(data.vector_db))

    if include_graph and getattr(data, "graph_db", None) is not None:
        lines.extend(
            await _render_graph_status_block(
                data.graph_db, tenant=_tenant(), all_tenants=all_tenants
            )
        )

    return "\n".join(lines).rstrip() + "\n"


def _vector_backend_label() -> str:
    """Display name for the active vector backend.

    ``DB_BACKEND=aws`` routes to OpenSearch; any other value (default
    ``cots``) uses ChromaDB. Keeps the rendered status headers honest
    on non-AWS deployments (e.g. Parallel Works / Rocky 9).
    """
    return "OpenSearch" if os.environ.get("DB_BACKEND", "cots") == "aws" else "ChromaDB"


def _graph_backend_label() -> str:
    """Display name for the active graph backend.

    ``DB_BACKEND=aws`` routes to Neptune; any other value (default
    ``cots``) uses Neo4j.
    """
    return "Neptune" if os.environ.get("DB_BACKEND", "cots") == "aws" else "Neo4j"


async def _render_vector_status_block(vector_db: Any) -> list[str]:
    """Render the vector-DB block (ChromaDB cots / OpenSearch aws).

    Uses ``health_check(deep=True)`` which returns the extended stats
    the Node.js ``getStatistics`` produces. The enumerated indices are
    scoped to the active tenant's ``index_prefix`` so a non-default
    tenant sees only its own ``<prefix>mdc-*`` indices and the default
    ``gw`` tenant sees only the unprefixed base set (R2.1, R2.2, R2.4).
    """
    try:
        health = await vector_db.health_check(deep=True)
    except Exception as exc:
        return [
            f"## Vector Database ({_vector_backend_label()})",
            "",
            f"[ERROR] health check failed: {exc}",
            "",
        ]

    tenant = _tenant()
    prefix = tenant.index_prefix if tenant else ""
    others = _other_index_prefixes(tenant)
    indices, detail, total_docs = _filter_indices_by_tenant(
        health, prefix=prefix, others=others
    )
    # Healthy when the store is up AND either it has documents OR the tenant
    # simply owns no applicable collections yet (a fresh tenant is healthy, not
    # unhealthy) — rag-data-plane-gap-closure R6.2.
    status_ok = (
        health.get("status") == "healthy"
        and (total_docs > 0 or len(indices) == 0)
    )

    lines = [
        f"## Vector Database ({_vector_backend_label()})",
        "",
    ]
    # Show the active scoping only for non-default tenants — the default
    # gw block stays byte-equivalent to the pre-fix output (Property 4).
    if prefix:
        lines.append(f"- **Tenant prefix:** {prefix}")
    lines.append(f"- **Collections:** {len(indices)}")

    if isinstance(detail, dict) and detail:
        lines.append("- **Collections Detail:**")
        for name, count in detail.items():
            lines.append(f"  - {name}: {count} documents")
    elif indices and isinstance(indices[0], str):
        # Flat list of index names — no per-index counts available.
        lines.append("- **Collections Detail:**")
        for name in indices:
            lines.append(f"  - {name}")

    lines.append(f"- **Total Documents:** {total_docs}")
    lines.append(
        f"- **Status:** {'[OK] Healthy' if status_ok else '[ERROR] Unhealthy'}"
    )
    lines.append("")
    return lines


def _other_index_prefixes(tenant: Any) -> tuple[str, ...]:
    """Return non-empty ``index_prefix`` values for every catalog tenant
    other than the active one.

    Used to exclude other tenants' prefixed indices from the default
    (empty-prefix) tenant's view, mirroring the label-side exclusion in
    :func:`src.tenancy.resolver.tenant_label_predicate`. Returns an empty
    tuple when the catalog cannot be loaded (best-effort; never raises).
    """
    active = tenant.index_prefix if tenant else ""
    try:
        from src.tenancy.runtime import get_catalog

        catalog = get_catalog()
    except Exception:  # pragma: no cover - defensive
        return ()
    return tuple(
        t.index_prefix
        for t in catalog.tenants
        if t.index_prefix and t.index_prefix != active
    )


def _index_in_tenant_scope(
    name: str, prefix: str, others: tuple[str, ...]
) -> bool:
    """True if index ``name`` belongs to the active tenant's scope.

    * Non-default tenant (``prefix`` non-empty): ``name`` starts with it.
    * Default tenant (``prefix`` empty): ``name`` starts with NO other
      tenant's prefix (i.e. it is a base/unprefixed index).
    """
    if prefix:
        return name.startswith(prefix)
    return not any(name.startswith(p) for p in others)


def _filter_indices_by_tenant(
    health: dict[str, Any], *, prefix: str, others: tuple[str, ...]
) -> tuple[list[str], dict[str, int], int]:
    """Filter a ``health_check(deep=True)`` payload to the active tenant.

    Returns ``(index_names, index_detail, total_documents)`` where the
    total is recomputed from the filtered subset (R2.4), never the global
    ``total_documents`` field.
    """
    detail_raw = (
        health.get("indices_detail")
        or health.get("collections_detail")
        or {}
    )
    if isinstance(detail_raw, dict) and detail_raw:
        detail = {
            n: int(c)
            for n, c in detail_raw.items()
            if _index_in_tenant_scope(n, prefix, others)
        }
        return list(detail.keys()), detail, sum(detail.values())

    raw = health.get("indices") or health.get("collections") or []
    if isinstance(raw, dict):
        detail = {
            n: int(c)
            for n, c in raw.items()
            if _index_in_tenant_scope(n, prefix, others)
        }
        return list(detail.keys()), detail, sum(detail.values())

    names = [
        n
        for n in raw
        if isinstance(n, str) and _index_in_tenant_scope(n, prefix, others)
    ]
    # No per-index counts available — fall back to the reported total
    # only when nothing was filtered out (so a scoped view never inflates).
    total = int(health.get("total_documents") or 0)
    if len(names) != len(raw):
        total = 0
    return names, {}, total


async def _whole_graph_node_count(graph_db: Any) -> int | None:
    """Whole-graph node count — all labels, all tenant prefixes (R4).

    Runs an unfiltered ``MATCH (n) RETURN count(n)`` (deliberately NOT tenant-
    scoped). Returns ``None`` if the query fails (e.g. a Neptune full-scan
    timeout on a very large graph) so the caller renders a graceful placeholder
    instead of erroring the whole status. See
    docs/development/graph_node_count_scopes.md for the scope model.
    """
    try:
        rows = await graph_db.query("MATCH (n) RETURN count(n) AS total")
        return int((rows or [{}])[0].get("total") or 0)
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("whole-graph node count failed: %s", exc)
        return None


async def _render_graph_status_block(
    graph_db: Any, tenant: Any = None, *, all_tenants: bool = False
) -> list[str]:
    """Render the graph-DB block (Neo4j cots / Neptune aws).

    Uses ``health_check`` first, then falls back to direct cypher
    queries for per-label / per-relationship counts when the health
    response doesn't include them.
    """
    try:
        health = await graph_db.health_check()
    except Exception as exc:
        return [
            f"## Graph Database ({_graph_backend_label()})",
            "",
            f"[ERROR] health check failed: {exc}",
            "",
        ]

    # Per-label / per-relationship counts — attempt to fetch when the
    # health payload doesn't already include them.
    label_counts: dict[str, int] = dict(health.get("labelBreakdown") or {})
    rel_breakdown: list[dict[str, Any]] = []

    if not label_counts:
        label_counts = await _safe_label_counts(graph_db, tenant=tenant)
    try:
        rel_breakdown = await _safe_relationship_counts(graph_db, tenant=tenant)
    except Exception:  # pragma: no cover - defensive
        rel_breakdown = []

    # Compute totals from the per-label/per-rel breakdowns rather than
    # relying on health_check() which may not include them (Neptune's
    # health probe only runs ``RETURN 1 AS ok``).
    node_count = int(health.get("nodes") or 0)
    rel_count = int(health.get("relationships") or 0)
    if node_count == 0 and label_counts:
        node_count = sum(label_counts.values())
    if rel_count == 0 and rel_breakdown:
        rel_count = sum(int(r.get("count") or 0) for r in rel_breakdown)

    status_ok = (
        health.get("status") == "healthy"
        and (node_count > 0 or rel_count > 0)
    )

    tid = getattr(tenant, "tenant_id", None) if tenant else None
    scope_label = f"tenant {tid}" if tid else "tenant scope"
    lines = [
        f"## Graph Database ({_graph_backend_label()})",
        "",
        f"- **Files:** {label_counts.get('File', 0)}",
        f"- **Functions:** {label_counts.get('Function', 0) + label_counts.get('FortranFunction', 0) + label_counts.get('PythonFunction', 0)}",
        f"- **Classes:** {label_counts.get('Class', 0) + label_counts.get('PythonClass', 0)}",
        f"- **Total Nodes ({scope_label}):** {node_count}",
        f"- **Total Relationships:** {rel_count}",
    ]

    # graph-node-count-scope-documentation R4: optional whole-graph count
    # (all labels, all tenant prefixes) for parity troubleshooting. Additive —
    # the tenant-scoped line above is unchanged.
    if all_tenants:
        whole = await _whole_graph_node_count(graph_db)
        lines.append(
            "- **Total Nodes (all tenants, all labels):** "
            + (str(whole) if whole is not None else "[unavailable]")
        )

    if rel_breakdown:
        lines.append("- **Relationship Types:**")
        for rel in rel_breakdown[:10]:
            rtype = rel.get("relationshipType") or rel.get("type") or "?"
            count = int(rel.get("count") or 0)
            lines.append(f"  - {rtype}: {count}")

    if label_counts:
        lines.append("- **Label Breakdown:**")
        for label, count in sorted(
            label_counts.items(), key=lambda kv: kv[1], reverse=True
        )[:10]:
            lines.append(f"  - {label}: {count}")

    lines.append(
        f"- **Status:** {'[OK] Healthy' if status_ok else '[ERROR] Unhealthy'}"
    )
    lines.append("")
    return lines


async def _safe_label_counts(graph_db: Any, tenant: Any = None) -> dict[str, int]:
    """Return per-label node counts via label-specific cypher queries.

    Matches the Node.js ``NeptuneAdapter.getStatistics`` strategy that
    avoids the full ``MATCH (n) RETURN count(n)`` scan which Neptune
    cannot answer in bounded time.

    When ``tenant`` is passed, the adapter rewrites ``:Label`` to
    ``:<prefix>Label`` so each query targets the correct tenant's nodes.
    """
    labels = (
        "File",
        "Function",
        "Class",
        "Module",
        "ShellScript",
        "EnvVar",
        "FortranModule",
        "FortranSubroutine",
        "FortranFunction",
        "FortranProgram",
        "PythonModule",
        "PythonFunction",
        "PythonClass",
    )

    async def _count(label: str) -> tuple[str, int]:
        try:
            rows = await graph_db.query(
                f"MATCH (n:{label}) RETURN count(n) AS count",
                tenant=tenant,
            )
            if rows:
                return label, int(rows[0].get("count") or 0)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("label count for %s failed: %s", label, exc)
        return label, 0

    results = await asyncio.gather(*[_count(label) for label in labels])
    return {label: count for label, count in results if count > 0}


async def _safe_relationship_counts(
    graph_db: Any, tenant: Any = None,
) -> list[dict[str, Any]]:
    """Return per-type relationship counts in descending order.

    When ``tenant`` is passed, we anchor on a source-side label so the
    adapter can rewrite it to the tenant-prefixed variant. Each rel type
    is counted via the most common source label that emits it. For the
    default ``gw`` tenant (empty prefix) the rewriter is a no-op so
    these queries are equivalent to the old unlabeled form.
    """
    # (rel_type, source_label) — we pick the dominant source for each.
    # CALLS/USES originate from multiple Fortran types; we count from
    # multiple and sum. But to keep it simple and fast, we use a single
    # broad query per type that constrains the source.
    rel_types = (
        "CALLS",
        "USES",
        "DEFINES",
        "IMPORTS",
        "SOURCES",
        "INVOKES",
        "EXECUTES",
        "DEPENDS_ON",
        "DEPENDS_ON_ENV",
        "EXPORTS",
    )

    async def _count(rtype: str) -> dict[str, Any]:
        try:
            # For tenanted queries, we need a node label anchor.
            # Use File as source for most types — if it gets 0 results,
            # try without anchor (for default gw tenant where prefix is empty).
            if tenant is not None and getattr(tenant, "label_prefix", ""):
                # Tenanted: use labeled anchors on BOTH sides to scope
                rows = await graph_db.query(
                    f"MATCH (s:File)-[r:{rtype}]->() RETURN count(r) AS count",
                    tenant=tenant,
                )
                count = int(rows[0].get("count") or 0) if rows else 0
                if count == 0:
                    # Try FortranSubroutine as source (for CALLS/USES)
                    rows = await graph_db.query(
                        f"MATCH (s:FortranSubroutine)-[r:{rtype}]->() RETURN count(r) AS count",
                        tenant=tenant,
                    )
                    count = int(rows[0].get("count") or 0) if rows else 0
                if count == 0:
                    # Try ShellScript as source (for SOURCES/INVOKES/EXECUTES)
                    rows = await graph_db.query(
                        f"MATCH (s:ShellScript)-[r:{rtype}]->() RETURN count(r) AS count",
                        tenant=tenant,
                    )
                    count = int(rows[0].get("count") or 0) if rows else 0
            else:
                # Default tenant (no prefix) — original unscoped query
                rows = await graph_db.query(
                    f"MATCH ()-[r:{rtype}]->() RETURN count(r) AS count",
                    tenant=tenant,
                )
                count = int(rows[0].get("count") or 0) if rows else 0
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("relationship count for %s failed: %s", rtype, exc)
            count = 0
        return {"relationshipType": rtype, "count": count}

    results = await asyncio.gather(*[_count(rt) for rt in rel_types])
    return sorted(
        (r for r in results if r["count"] > 0),
        key=lambda r: r["count"],
        reverse=True,
    )


# ── list_ingested_urls / get_ingested_urls_array ───────────────────────


def _make_doc_sources_resolver(
    override: str | os.PathLike[str] | None,
):
    """Return a ``() -> (Path, dict) | (None, {})`` resolver closure.

    The resolver is lazy: file I/O happens on first call so registration
    stays cheap and a missing file does not block server boot.
    """
    explicit: Path | None = Path(override).resolve() if override else None

    def _resolve() -> tuple[Path | None, dict[str, Any]]:
        candidates: list[Path] = []
        if explicit is not None:
            candidates.append(explicit)
        env = os.environ.get("MCP_DOCUMENTATION_SOURCES_PATH")
        if env:
            candidates.append(Path(env).resolve())
        candidates.append(BUNDLED_DOC_SOURCES_PATH)
        # Developer workflow fallback — the Node.js config file lives
        # at the sibling path in the repo.
        candidates.append(
            Path(__file__).resolve().parent.parent.parent.parent
            / "mcp_server_node"
            / "config"
            / "documentation_sources.json"
        )
        for path in candidates:
            if path.is_file():
                try:
                    with path.open("r", encoding="utf-8") as fh:
                        return path, json.load(fh)
                except (OSError, json.JSONDecodeError) as exc:
                    log.warning(
                        "failed to load documentation sources from %s: %s",
                        path,
                        exc,
                    )
                    continue
        return None, {}

    return _resolve


def _resolve_repo_base(override: str | os.PathLike[str] | None) -> Path:
    if override is not None:
        return Path(override).resolve()
    env = os.environ.get("MCP_REPO_BASE")
    if env:
        return Path(env).resolve()
    # Default: ``supported_repos/global-workflow_develop`` relative to the
    # workspace root (four levels up from this file in the container
    # layout: ``/app/src/tools/semantic_search.py`` → ``/app``).
    candidate = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "supported_repos"
        / "global-workflow"
    )
    return candidate


def _resolve_repo_base_with_tenant(
    override: str | os.PathLike[str] | None,
) -> Path:
    """Resolve the repo base for the integrity checks, tenant-aware (R4.2).

    Precedence: explicit ``override`` (e.g. a test-supplied path) > the active
    tenant's ``workflow_root`` (Phase-67 leak fix — the default ``gw`` tenant
    resolves to ``.pw_workflow_mount/develop`` via the mount base) >
    ``MCP_REPO_BASE`` env var > the legacy default. Must be called inside a
    ``tenant_aware`` scope for the tenant branch to fire (defense-in-depth via
    ``get_current_tenant_or_none``).
    """
    if override is not None:
        return Path(override).resolve()
    ctx = get_current_tenant_or_none()
    if ctx is not None:
        return Path(ctx.workflow_root)
    return _resolve_repo_base(None)


async def _tool_list_ingested_urls(
    data: Any,
    *,
    manifest_registry: ManifestRegistry | None,
    doc_sources_resolver,
    fmt: str,
    source_filter: str | None,
) -> str:
    sources, config_version, source_path = _resolve_url_sources_view(
        manifest_registry, doc_sources_resolver
    )

    # Fetch actual ingestion status from the vector store's health
    # payload — opensearch-py pools connections natively so this is
    # safe to call repeatedly, unlike the Node.js ChromaDB path.
    per_index: dict[str, int] = {}
    total_documents = 0
    if data is not None and getattr(data, "vector_db", None) is not None:
        try:
            health = await data.vector_db.health_check(deep=True)
            detail = health.get("indices_detail") or {}
            if isinstance(detail, dict):
                per_index = {k: int(v) for k, v in detail.items()}
                total_documents = sum(per_index.values())
            else:
                total_documents = int(health.get("total_documents") or 0)
        except Exception as exc:
            log.debug("list_ingested_urls: health_check failed: %s", exc)

    # urls_only shortcut — matches the Node.js behaviour of returning a
    # newline-joined list of enabled source URLs.
    if fmt == "urls_only":
        urls = [
            s.get("url", "")
            for s in sources
            if s.get("enabled")
            and (not source_filter or source_filter in s.get("name", ""))
            and s.get("url")
        ]
        return "\n".join(urls) + ("\n" if urls else "")

    lines: list[str] = [
        "# RAG Knowledge Base Ingested URLs",
        "",
        f"**Generated**: {_iso_now()}",
        "",
    ]

    if per_index:
        lines.append(f"## Actual Ingestion Status (from {_vector_backend_label()})")
        lines.append("")
        lines.append(f"**Total Documents**: {total_documents:,}")
        lines.append("")
        lines.append("### Indices by Document Count")
        lines.append("")
        lines.append("| Index | Documents | % of Total |")
        lines.append("|-------|-----------|------------|")
        sorted_indices = sorted(
            per_index.items(), key=lambda kv: kv[1], reverse=True
        )
        for idx_name, count in sorted_indices:
            if source_filter and source_filter not in idx_name:
                continue
            pct = (count / total_documents * 100) if total_documents else 0.0
            lines.append(f"| {idx_name} | {count:,} | {pct:.1f}% |")
        lines.append("")

    if sources:
        lines.append(f"## Configured Documentation Sources (SPOT v{config_version})")
        lines.append("")
        lines.append("| Source | URL | Status |")
        lines.append("|--------|-----|--------|")
        for source in sources:
            name = source.get("name", "")
            url = source.get("url", "")
            if source_filter and source_filter not in name:
                continue
            status = "[ENABLED]" if source.get("enabled") else "[DISABLED]"
            lines.append(f"| {name} | {url} | {status} |")
        lines.append("")
        enabled_count = sum(1 for s in sources if s.get("enabled"))
        lines.append(
            f"**Total Sources**: {len(sources)} ({enabled_count} enabled)"
        )
        lines.append("")
    else:
        lines.append(
            f"No documentation sources configured "
            f"(looked in: {source_path or 'default paths'})"
        )
        lines.append("")

    # Detailed format on a registry-backed call appends a summary of
    # non-URL source counts so agents see that other sources exist
    # (Requirement 4.5). The legacy file-backed path skips this
    # because legacy data has no non-URL sources to report on.
    if fmt == "detailed" and manifest_registry is not None:
        non_url_summary = _summarize_non_url_sources(manifest_registry)
        if non_url_summary:
            lines.extend(non_url_summary)

    if fmt == "summary":
        # Drop the per-index table for summary mode.
        summary_lines: list[str] = []
        skip = False
        for line in lines:
            if line.startswith("### Indices by Document Count"):
                skip = True
                continue
            if skip and (line.startswith("## ") or line == ""):
                skip = False
                if line.startswith("## "):
                    summary_lines.append(line)
                continue
            if skip:
                continue
            summary_lines.append(line)
        return "\n".join(summary_lines).rstrip() + "\n"

    return "\n".join(lines).rstrip() + "\n"


def _tool_get_ingested_urls_array(
    *,
    manifest_registry: ManifestRegistry | None,
    doc_sources_resolver,
    include_failed: bool,
) -> str:
    sources, version, _path = _resolve_url_sources_view(
        manifest_registry, doc_sources_resolver
    )

    enabled = [s for s in sources if s.get("enabled")]
    disabled = [s for s in sources if not s.get("enabled")]

    result = {
        "version": version,
        "generatedAt": _iso_now(),
        "totalSources": len(sources),
        "enabledCount": len(enabled),
        "disabledCount": len(disabled),
        "enabledUrls": [s.get("url", "") for s in enabled if s.get("url")],
        "sources": [
            {"name": s.get("name", ""), "url": s.get("url", "")}
            for s in enabled
        ],
    }
    if include_failed:
        result["disabledUrls"] = [
            s.get("url", "") for s in disabled if s.get("url")
        ]
        result["disabledSources"] = [
            {"name": s.get("name", ""), "url": s.get("url", "")}
            for s in disabled
        ]

    lines = [
        "# Ingested URLs Array",
        "",
        f"**Version**: {result['version']}",
        f"**Generated**: {result['generatedAt']}",
        f"**Total Sources**: {result['totalSources']}",
        f"**Enabled**: {result['enabledCount']}",
        f"**Disabled**: {result['disabledCount']}",
        "",
        f"## Enabled URLs ({len(result['enabledUrls'])})",
        "",
        "```json",
        json.dumps(result["enabledUrls"], indent=2),
        "```",
        "",
        "## Source Details",
        "",
        "```json",
        json.dumps(result["sources"], indent=2),
        "```",
        "",
    ]
    if include_failed and result.get("disabledUrls"):
        lines.extend(
            [
                f"## Disabled URLs ({len(result['disabledUrls'])})",
                "",
                "```json",
                json.dumps(result["disabledUrls"], indent=2),
                "```",
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


# ── list_all_sources (Requirements 3.1 – 3.6, 6.5) ────────────────────


async def _tool_list_all_sources(
    data: Any,
    *,
    manifest_registry: ManifestRegistry | None,
    source_type: str | None,
    collection: str | None,
    fmt: str,
    include_gaps: bool,
) -> str:
    """Render the unified manifest as a markdown report."""
    if manifest_registry is None:
        return _error_text(
            "Unified manifest registry unavailable. The server is running "
            "in legacy fallback mode — only url_crawl sources are visible. "
            "Use list_ingested_urls instead, or set "
            "MCP_UNIFIED_MANIFEST_PATH and restart."
        )

    # Filter (Requirements 3.2, 3.3). enabled_only=False so disabled
    # entries still appear in the report — operators need to see them.
    try:
        entries = manifest_registry.get_sources(
            source_type=source_type,
            collection=collection,
            enabled_only=False,
        )
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("list_all_sources: get_sources failed: %s", exc)
        return _error_text(f"Failed to query manifest registry: {exc}")

    # Resolve actual document counts for the indices we will reference
    # so the report can show declared vs actual side-by-side
    # (Requirement 3.6). Use the same health_check shape the URL tools
    # use so we hit the cluster once.
    actual_counts: dict[str, int] = {}
    health_status: str | None = None
    if data is not None and getattr(data, "vector_db", None) is not None:
        try:
            health = await data.vector_db.health_check(deep=True)
            if isinstance(health, dict):
                health_status = health.get("status")
            # ChromaDB (cots) reports per-collection counts under
            # ``collections_detail``; OpenSearch (aws) under ``indices_detail``.
            # Recognise either so the Actual column is populated on both
            # backends (cots-backend-observability-parity R5).
            detail = (
                health.get("indices_detail")
                or health.get("collections_detail")
                or {}
            )
            if isinstance(detail, dict):
                actual_counts = {str(k): int(v) for k, v in detail.items()}
        except Exception as exc:
            log.debug("list_all_sources: health_check failed: %s", exc)

    # Surface the case where the cluster reports healthy but the
    # per-index breakdown is missing — declared/actual columns and
    # gap reports will silently show 0/n/a otherwise (Requirement 4.1).
    if not actual_counts and health_status in ("healthy", "degraded"):
        log.warning(
            "list_all_sources: actual_counts empty despite successful "
            "health_check (status=%s)",
            health_status,
        )

    lines: list[str] = [
        "# Unified Ingest Manifest",
        "",
        f"**Generated**: {_iso_now()}",
        f"**Manifest Version**: {manifest_registry.version}",
        f"**Total Sources**: {manifest_registry.total_sources} "
        f"({manifest_registry.enabled_sources} enabled)",
        "",
    ]
    filter_bits: list[str] = []
    if source_type:
        filter_bits.append(f"source_type=`{source_type}`")
    if collection:
        filter_bits.append(f"collection=`{collection}`")
    if filter_bits:
        lines.append(f"**Filter**: {', '.join(filter_bits)}")
        lines.append("")

    if not entries:
        lines.append("_No sources match the current filter._")
        lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    if fmt == "summary":
        lines.extend(_render_summary(entries, actual_counts))
    else:
        lines.extend(_render_detailed(entries, actual_counts))

    if include_gaps:
        lines.append("")
        lines.append("## Gap Detection")
        lines.append("")
        if data is None or getattr(data, "vector_db", None) is None:
            lines.append("_Gap detection unavailable — no vector adapter._")
        else:
            try:
                reports = await GapDetector().detect(
                    manifest_registry, data.vector_db
                )
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("list_all_sources: GapDetector failed: %s", exc)
                reports = []
            if not reports:
                if not actual_counts:
                    lines.append(
                        "_⚠️ Actual index counts unavailable — "
                        "gap status may be inaccurate._"
                    )
                else:
                    lines.append(
                        "_Gap detection unavailable — could not query OpenSearch._"
                    )
            else:
                lines.extend(_render_gap_reports(reports))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_summary(
    entries: list[SourceEntry],
    actual_counts: dict[str, int],
) -> list[str]:
    """Aggregated counts grouped by source_type and collection."""
    lines: list[str] = []

    # Group by source_type.
    by_type: dict[str, list[SourceEntry]] = {}
    for entry in entries:
        by_type.setdefault(entry.source_type.value, []).append(entry)

    lines.append("## By Source Type")
    lines.append("")
    lines.append("| Source Type | Sources | Enabled | Declared Docs |")
    lines.append("|-------------|---------|---------|---------------|")
    for stype in sorted(by_type):
        bucket = by_type[stype]
        enabled = sum(1 for e in bucket if e.enabled)
        declared = sum(e.doc_count for e in bucket if e.enabled)
        lines.append(
            f"| {stype} | {len(bucket)} | {enabled} | {declared:,} |"
        )
    lines.append("")

    # Group by scope (shared vs tenant) — rag-data-plane-gap-closure R1/R10.4.
    # shared = NWS-wide, ingested once (unprefixed); tenant = per (repo, branch).
    by_scope: dict[str, list[SourceEntry]] = {}
    for entry in entries:
        by_scope.setdefault(getattr(entry, "scope", "?"), []).append(entry)
    lines.append("## By Scope")
    lines.append("")
    lines.append("| Scope | Sources | Enabled | Note |")
    lines.append("|-------|---------|---------|------|")
    _scope_note = {
        "shared": "NWS-wide, ingested once (unprefixed collection)",
        "tenant": "per (repo, branch) — tenant-prefixed collection",
    }
    for scope in sorted(by_scope):
        bucket = by_scope[scope]
        enabled = sum(1 for e in bucket if e.enabled)
        lines.append(
            f"| {scope} | {len(bucket)} | {enabled} | {_scope_note.get(scope, '')} |"
        )
    lines.append("")

    # Group by collection_target.
    by_collection: dict[str, list[SourceEntry]] = {}
    for entry in entries:
        by_collection.setdefault(entry.collection_target, []).append(entry)

    lines.append("## By Collection Target")
    lines.append("")
    lines.append(
        "| Collection | Sources | Enabled | Declared | Actual |"
    )
    lines.append("|------------|---------|---------|----------|--------|")
    for coll in sorted(by_collection):
        bucket = by_collection[coll]
        enabled = sum(1 for e in bucket if e.enabled)
        declared = sum(e.doc_count for e in bucket if e.enabled)
        actual = _resolve_actual_for_collection(coll, bucket, actual_counts)
        actual_str = f"{actual:,}" if actual is not None else "n/a"
        lines.append(
            f"| {coll} | {len(bucket)} | {enabled} | "
            f"{declared:,} | {actual_str} |"
        )
    lines.append("")
    return lines


def _render_detailed(
    entries: list[SourceEntry],
    actual_counts: dict[str, int],
) -> list[str]:
    """Full SourceEntry metadata for each source."""
    lines: list[str] = []
    for entry in sorted(entries, key=lambda e: (e.source_type.value, e.name)):
        status = "[ENABLED]" if entry.enabled else "[DISABLED]"
        lines.append(f"## {entry.name} ({entry.source_type.value}) {status}")
        lines.append("")
        lines.append(f"- **Description**: {entry.description}")
        lines.append(f"- **Scope**: `{getattr(entry, 'scope', '?')}`")
        lines.append(f"- **Collection**: `{entry.collection_target}`")
        lines.append(f"- **Embedding Profile**: `{entry.embedding_profile}`")
        lines.append(f"- **Declared Docs**: {entry.doc_count:,}")
        lines.append(
            f"- **Last Ingested**: {entry.last_ingested or '_never_'}"
        )
        if entry.ingestion_script:
            lines.append(f"- **Ingestion Script**: `{entry.ingestion_script}`")
        # Render type-specific fields in their declaration order so the
        # output stays diffable when the manifest is regenerated.
        if entry.type_fields:
            lines.append("- **Type-Specific Fields**:")
            for k, v in entry.type_fields.items():
                lines.append(f"  - `{k}`: {v!r}")
        lines.append("")
    return lines


def _render_gap_reports(reports: list[GapReport]) -> list[str]:
    """Render :class:`GapReport` entries as a markdown table."""
    lines = [
        "| Collection | Status | Declared | Actual | Coverage | Issues |",
        "|------------|--------|----------|--------|----------|--------|",
    ]
    for r in reports:
        issues_bits: list[str] = []
        if r.never_ingested:
            issues_bits.append(
                f"never: {', '.join(r.never_ingested)}"
            )
        if r.stale_sources:
            issues_bits.append(
                f"stale: {', '.join(r.stale_sources)}"
            )
        issues = "; ".join(issues_bits) or "—"
        lines.append(
            f"| {r.collection} | {r.status} | "
            f"{r.declared_count:,} | {r.actual_count:,} | "
            f"{r.coverage_pct * 100:.1f}% | {issues} |"
        )
    return lines


def _resolve_actual_for_collection(
    collection: str,
    entries: list[SourceEntry],
    actual_counts: dict[str, int],
) -> int | None:
    """Look up the OpenSearch doc count for ``collection``.

    Mirrors the resolver logic in :class:`GapDetector` so the summary
    table and the gap section agree on numbers. Returns ``None`` when
    no actual data is available so the caller can render ``n/a``.
    """
    if not actual_counts:
        return None
    if collection in actual_counts:
        return actual_counts[collection]
    # Late import — avoid pulling AWS config into module load time.
    from src.config.aws_config import resolve_index

    for entry in entries:
        try:
            index_name = resolve_index(collection, entry.embedding_profile)
        except Exception:  # pragma: no cover - defensive
            continue
        if index_name in actual_counts:
            return actual_counts[index_name]
    return 0


def _summarize_non_url_sources(
    registry: ManifestRegistry,
) -> list[str]:
    """Produce the "non-URL summary" section for ``list_ingested_urls``.

    Returns an empty list when the registry only contains url_crawl
    entries so the rendered output stays unchanged in legacy
    deployments (Requirement 4.5).
    """
    by_type: dict[str, int] = {}
    for entry in registry.get_sources(enabled_only=False):
        if entry.source_type == SourceType.URL_CRAWL:
            continue
        by_type[entry.source_type.value] = (
            by_type.get(entry.source_type.value, 0) + 1
        )
    if not by_type:
        return []

    lines = [
        "## Other Knowledge Base Sources (non-URL)",
        "",
        (
            "The unified manifest also declares the following non-URL "
            "sources. Use `list_all_sources` to see them in detail."
        ),
        "",
        "| Source Type | Count |",
        "|-------------|-------|",
    ]
    for stype in sorted(by_type):
        lines.append(f"| {stype} | {by_type[stype]} |")
    lines.append("")
    return lines


def _resolve_url_sources_view(
    manifest_registry: ManifestRegistry | None,
    doc_sources_resolver,
) -> tuple[list[dict[str, Any]], str, Path | None]:
    """Return ``(legacy-shaped sources, version, source_path)``.

    Prefers the registry view (Requirements 4.1, 4.2). Falls back to
    the file-based resolver when the registry is None or yields no
    url_crawl entries (so a server booted in legacy-fallback mode
    still renders the existing sources).
    """
    if manifest_registry is not None:
        legacy = manifest_registry.get_legacy_format()
        sources = legacy.get("sources") or []
        if sources:
            return (
                list(sources),
                str(legacy.get("version") or "unknown"),
                manifest_registry.source_path,
            )

    path, config = doc_sources_resolver()
    if isinstance(config, dict):
        return (
            list(config.get("sources") or []),
            str(config.get("version") or "unknown"),
            path,
        )
    return [], "unknown", path


# ── check_knowledge_integrity ───────────────────────────────────────────


@dataclass
class _Check:
    name: str
    passed: bool
    details: str


async def _tool_check_knowledge_integrity(
    data: Any,
    *,
    sample_size: int,
    repo_base: Path,
) -> str:
    if data is None:
        return _error_text(_DEGRADED_DATA_MSG)

    sample_size = max(1, int(sample_size))
    checks: list[_Check] = []

    checks.append(
        await _check_path_consistency(data, sample_size=sample_size)
    )
    checks.append(await _check_orphaned_graph_nodes(data))
    checks.append(
        await _check_stale_embeddings(
            data, sample_size=sample_size, repo_base=repo_base
        )
    )
    checks.extend(await _check_coverage_gap(data, repo_base=repo_base))

    all_passed = all(c.passed for c in checks)
    lines = [
        "# Knowledge Base Integrity Report",
        "",
        "**Overall**: " + (
            "All checks passed" if all_passed else "Issues detected"
        ),
        "",
        "| Check | Status | Details |",
        "|-------|--------|---------|",
    ]
    for c in checks:
        icon = "[OK]" if c.passed else "[WARN]"
        lines.append(f"| {c.name} | {icon} | {c.details} |")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


async def _check_path_consistency(
    data: Any, *, sample_size: int
) -> _Check:
    """Sample vector metadata and count file paths with a bad prefix."""
    sampler = _build_vector_sampler(data.vector_db)
    if sampler is None:
        return _Check(
            "Path Consistency",
            True,
            "[SKIP] vector adapter does not expose a metadata sampler",
        )
    try:
        metadatas = await sampler(sample_size)
    except Exception as exc:
        return _Check(
            "Path Consistency", False, f"[ERROR] {exc}"
        )

    bad = 0
    for meta in metadatas:
        fp = (meta or {}).get("file_path") or (meta or {}).get("source_path") or ""
        if isinstance(fp, str) and (
            fp.startswith("/") or any(prefix in fp for prefix in BAD_PATH_PREFIXES)
        ):
            bad += 1
    total = len(metadatas)
    if bad == 0:
        return _Check(
            "Path Consistency",
            True,
            f"[OK] 0/{total} randomly sampled docs have checkout-specific prefix",
        )
    return _Check(
        "Path Consistency",
        False,
        f"[WARN] {bad}/{total} randomly sampled docs have checkout-specific prefix",
    )


async def _check_orphaned_graph_nodes(data: Any) -> _Check:
    graph_db = getattr(data, "graph_db", None)
    if graph_db is None:
        return _Check(
            "Orphaned Graph Nodes", True, "[SKIP] graph adapter not available"
        )
    tenant = _tenant()
    try:
        total_rows = await graph_db.query(
            "MATCH (f:File) RETURN count(f) AS total",
            tenant=tenant,
        )
        total = int((total_rows or [{}])[0].get("total") or 0)
        sample_rows = await graph_db.query(
            "MATCH (f:File) RETURN f.name AS name, f.path AS path LIMIT 20",
            tenant=tenant,
        )
        orphaned = [
            r for r in (sample_rows or [])
            if not (r.get("name") or r.get("path"))
        ]
    except Exception as exc:
        return _Check(
            "Orphaned Graph Nodes", False, f"[ERROR] {exc}"
        )

    if not orphaned:
        return _Check(
            "Orphaned Graph Nodes",
            True,
            f"[OK] {total} File nodes in graph, 0/20 sampled lack identity",
        )
    return _Check(
        "Orphaned Graph Nodes",
        False,
        f"[WARN] {len(orphaned)}/20 sampled File nodes lack name or path",
    )


async def _check_stale_embeddings(
    data: Any, *, sample_size: int, repo_base: Path
) -> _Check:
    sampler = _build_vector_sampler(data.vector_db)
    if sampler is None:
        return _Check(
            "Stale Embeddings",
            True,
            "[SKIP] vector adapter does not expose a metadata sampler",
        )

    try:
        metadatas = await sampler(sample_size)
    except Exception as exc:
        return _Check("Stale Embeddings", False, f"[ERROR] {exc}")

    repo_head_time = _git_head_time(repo_base)
    method = "git source comparison" if repo_head_time else "30-day age threshold"
    now = datetime.now(timezone.utc)

    checked = 0
    stale = 0
    file_date_cache: dict[str, datetime | None] = {}

    for meta in metadatas:
        meta = meta or {}
        timestamp_raw = (
            meta.get("lastModified")
            or meta.get("ingestedAt")
            or meta.get("ingested_at")
            or meta.get("timestamp")
        )
        if not timestamp_raw:
            continue
        mod_time = _parse_iso_ts(timestamp_raw)
        if mod_time is None or mod_time.tzinfo is None:
            # Defence-in-depth: never compare a tz-naive datetime against
            # the tz-aware ``now`` (would raise TypeError). _parse_iso_ts
            # already guarantees tz-aware; this guard tolerates a future
            # bypass without aborting the whole check.
            continue
        checked += 1

        if repo_head_time is not None:
            fp = meta.get("file_path") or meta.get("source_path") or ""
            if not fp or fp.startswith("http"):
                continue
            rel = fp.lstrip("/")
            if rel not in file_date_cache:
                file_date_cache[rel] = _git_file_time(repo_base, rel)
            file_time = file_date_cache[rel]
            if file_time and mod_time < file_time:
                stale += 1
        else:
            if (now - mod_time).days > STALE_EMBEDDING_DAYS:
                stale += 1

    if checked == 0:
        return _Check(
            "Stale Embeddings",
            True,
            f"[OK] 0 sampled docs had usable timestamps ({method})",
        )

    fraction = stale / checked
    passed = fraction < 0.25
    if stale == 0:
        details = (
            f"[OK] {checked}/{checked} sampled docs appear current ({method})"
        )
    else:
        details = (
            f"[WARN] {stale}/{checked} sampled docs have embeddings older "
            f"than source ({method})"
        )
    return _Check("Stale Embeddings", passed, details)


#: Coverage-gap language buckets: (label, graph_labels, disk_subdirs, disk_globs).
#: Fortran symbols live under sorc/; Python under ush/ + workflow/; Shell under
#: ush/ + scripts/ + jobs/ (fortran-coverage-gap-path-fix R1.2, R3.2).
_COVERAGE_LANGUAGES: tuple[
    tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]], ...
] = (
    (
        "Fortran",
        ("FortranSubroutine", "FortranFunction", "FortranModule", "FortranProgram"),
        ("sorc",),
        ("*.f90", "*.F90", "*.f", "*.F"),
    ),
    (
        "Python",
        ("PythonModule", "PythonFunction"),
        ("ush", "workflow"),
        ("*.py",),
    ),
    (
        "Shell",
        ("ShellScript",),
        ("ush", "scripts", "jobs"),
        ("*.sh", "*.ksh"),
    ),
)

#: Graph node count above which a language's graph-only coverage is [OK]
#: (fortran-coverage-gap-path-fix R2.3). 1..threshold → [WARN]; 0 → [FAIL].
_COVERAGE_GRAPH_OK_THRESHOLD: int = 100


async def _check_coverage_gap(data: Any, *, repo_base: Path) -> list[_Check]:
    """Coverage-gap checks per primary language (fortran-coverage-gap-path-fix).

    Resolves source roots under the active tenant's ``repo_base`` (the Phase-61
    workflow_root; see :func:`_resolve_repo_base_with_tenant`) rather than a
    hard-coded path, cross-references on-disk source files against
    ``<Language>*``-labelled graph nodes (tenant-scoped), and falls back to a
    graph-only count when the filesystem is not mounted. Never returns
    ``[SKIP]`` for a missing source path — that was the Phase 72 bug. Returns
    one ``_Check`` row per language.
    """
    graph_db = getattr(data, "graph_db", None)
    if graph_db is None:
        # Degraded-mode boot: no graph to check against (consistent with the
        # sibling Orphaned-Graph-Nodes check). Distinct from the missing-
        # source-path SKIP that Phase 72 removes.
        return [_Check("Coverage Gap", True, "[SKIP] graph adapter not available")]

    tenant = _tenant()
    checks: list[_Check] = []
    for label, graph_labels, subdirs, globs in _COVERAGE_LANGUAGES:
        checks.append(
            await _coverage_for_language(
                graph_db, tenant, repo_base, label, graph_labels, subdirs, globs
            )
        )
    return checks


async def _coverage_for_language(
    graph_db: Any,
    tenant: Any,
    repo_base: Path,
    label: str,
    graph_labels: tuple[str, ...],
    subdirs: tuple[str, ...],
    globs: tuple[str, ...],
) -> _Check:
    """One language's coverage-gap row (always [OK]/[WARN]/[FAIL], never [SKIP]).

    * filesystem available:
        - files present, 0 nodes  → [FAIL] (ingest gap)
        - nodes < files           → [WARN] (possible partial coverage)
        - nodes >= files          → [OK]
        - no source files present → [OK] (nothing to cover)
    * filesystem not mounted (graph-only fallback, R2):
        - nodes > threshold → [OK]; 1..threshold → [WARN]; 0 → [FAIL]

    Deviation note: the draft design compared on-disk *file* count to graph
    *symbol* count via a percentage "divergence", but files and symbols are
    different scales (one .f90 defines many subroutines), so that divergence is
    always huge and meaningless. This uses the sound signal "graph nodes must
    be at least as many as source files" — valid across all three buckets
    (ShellScript is ~1:1 with files; Fortran/Python yield >=1 symbol per parsed
    file).
    """
    name = f"Coverage Gap ({label})"
    where = " OR ".join(f"n:{lbl}" for lbl in graph_labels)
    try:
        rows = await graph_db.query(
            f"MATCH (n) WHERE {where} RETURN count(n) AS total",
            tenant=tenant,
        )
        in_graph = int((rows or [{}])[0].get("total") or 0)
    except Exception as exc:
        return _Check(name, False, f"[ERROR] {exc}")

    dirs = [repo_base / d for d in subdirs]
    present_dirs = [d for d in dirs if d.is_dir()]
    scope = "/".join(subdirs)

    if not present_dirs:
        # Graph-only fallback — filesystem not mounted (e.g. AgentCore microVM).
        if in_graph > _COVERAGE_GRAPH_OK_THRESHOLD:
            return _Check(
                name, True,
                f"[OK] {in_graph} {label} nodes "
                "(graph-only; filesystem not mounted)",
            )
        if in_graph > 0:
            return _Check(
                name, True,
                f"[WARN] only {in_graph} {label} nodes "
                "(graph-only; filesystem not mounted)",
            )
        return _Check(name, False, f"[FAIL] 0 {label} nodes in graph")

    on_disk = _count_source_files(present_dirs, globs)
    if on_disk == 0:
        return _Check(
            name, True,
            f"[OK] no {label} source files under {scope}/ "
            f"({in_graph} nodes in graph)",
        )
    if in_graph == 0:
        return _Check(
            name, False,
            f"[FAIL] {on_disk} {label} files under {scope}/ but 0 nodes in graph",
        )
    if in_graph < on_disk:
        return _Check(
            name, True,
            f"[WARN] {in_graph} {label} nodes < {on_disk} files under {scope}/ "
            "(possible partial coverage)",
        )
    return _Check(
        name, True,
        f"[OK] {in_graph} {label} nodes for {on_disk} files under {scope}/",
    )


def _count_source_files(dirs: list[Path], globs: tuple[str, ...]) -> int:
    """Count files matching ``globs`` recursively under each dir in ``dirs``."""
    count = 0
    for d in dirs:
        if not d.is_dir():
            continue
        for pattern in globs:
            count += sum(1 for _ in d.rglob(pattern))
    return count


def _build_vector_sampler(vector_db: Any):
    """Return an async callable ``(n) -> list[metadata]`` or ``None``.

    Adapter compatibility:

    * Adapters/mocks with a ``sample_metadata`` method (ChromaDB adapter →
      ``sample_metadata(collection=None, n=...)``; test doubles →
      ``sample_metadata(n=...)``) → used directly (called with keyword ``n``
      so both signatures work).
    * Production ``OpenSearchAdapter`` → falls back to a scroll-based
      sampler when possible.

    Returning ``None`` means the tool should skip the check.
    """
    if vector_db is None:
        return None

    if hasattr(vector_db, "sample_metadata"):
        async def _adapter_sampler(n: int) -> list[dict[str, Any]]:
            return list(await vector_db.sample_metadata(n=n))
        return _adapter_sampler

    raw_client = getattr(vector_db, "_raw_client", None)
    if not callable(raw_client):
        return None

    async def _scroll_sampler(n: int) -> list[dict[str, Any]]:
        def _sample() -> list[dict[str, Any]]:
            raw = raw_client()
            # Scan-like sampling: request up to ``n`` documents from
            # each known index and shuffle locally. Keeps load predictable
            # while still producing a "random-ish" sample.
            collected: list[dict[str, Any]] = []
            try:
                indices_resp = raw.cat.indices(format="json", h="index")
                index_names = [
                    row["index"] for row in indices_resp
                    if not row["index"].startswith(".")
                ]
            except Exception:
                index_names = []
            if not index_names:
                return []
            per_index = max(1, n // max(1, len(index_names)))
            for idx in index_names:
                try:
                    resp = raw.search(
                        index=idx,
                        body={
                            "size": per_index,
                            "query": {
                                "function_score": {
                                    "query": {"match_all": {}},
                                    "random_score": {},
                                }
                            },
                            "_source": ["metadata"],
                        },
                    )
                    for hit in resp.get("hits", {}).get("hits", []):
                        meta = (hit.get("_source") or {}).get("metadata") or {}
                        collected.append(meta)
                except Exception:
                    continue
            random.shuffle(collected)
            return collected[:n]
        return await asyncio.to_thread(_sample)

    return _scroll_sampler


# ── helpers ─────────────────────────────────────────────────────────────


_DEGRADED_DATA_MSG = (
    "Data access layer unavailable (degraded-mode boot). Restart the "
    "server with DB_BACKEND=aws and valid NEPTUNE_ENDPOINT / "
    "OPENSEARCH_ENDPOINT to enable this tool."
)
_DEGRADED_VECTOR_MSG = (
    "Vector database unavailable (degraded-mode boot). Ensure "
    "OPENSEARCH_ENDPOINT is reachable from the runtime."
)
_DEGRADED_GRAPH_MSG = (
    "Graph database unavailable (degraded-mode boot). Ensure "
    "NEPTUNE_ENDPOINT is reachable from the runtime."
)


def _error_text(message: str) -> str:
    return f"[ERROR] {message}\n"


def _iso_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _parse_iso_ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    # Every persisted timestamp in this codebase is UTC by convention, so a
    # tz-naive parse is safely interpreted as already-UTC. Returning a
    # tz-aware datetime keeps downstream arithmetic against
    # ``datetime.now(timezone.utc)`` from raising a tz-mismatch TypeError.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _git_head_time(repo_base: Path) -> datetime | None:
    """Return the HEAD commit's author date, or ``None`` if git fails."""
    if not repo_base.is_dir():
        return None
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_base), "log", "-1", "--format=%aI"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    raw = (out.stdout or "").strip()
    if not raw:
        return None
    return _parse_iso_ts(raw)


def _git_file_time(repo_base: Path, relative: str) -> datetime | None:
    """Return the last-commit time for a specific repo-relative file."""
    if not repo_base.is_dir() or not relative:
        return None
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_base), "log", "-1", "--format=%aI", "--", relative],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    raw = (out.stdout or "").strip()
    return _parse_iso_ts(raw) if raw else None


__all__ = [
    "BUNDLED_DOC_SOURCES_PATH",
    "CONTEXT_TYPE_COLLECTIONS",
    "DEFAULT_INTEGRITY_SAMPLE_SIZE",
    "DEFAULT_SEARCH_COLLECTIONS",
    "DETAIL_LEVEL_LIMITS",
    "register",
]
