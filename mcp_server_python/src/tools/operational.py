"""Operational tools (Requirement 1.7, Task 13 Phase B9).

Python port of the 4 tools in
``mcp_server_node/src/tools/OperationalTools.js``. Tool names and
input schemas match the Node.js ``registerWith`` block exactly so the
parity framework can compare results side-by-side.

Tool overview
-------------

* ``get_operational_guidance`` — hybrid semantic search over the
  ``global-workflow-docs-v8-0-0`` collection with graph context,
  filtered by platform + urgency. Appends a hardcoded platform-notes
  block (ported verbatim from Node.js).

* ``explain_workflow_component`` — hybrid search: vector_db for
  documentation hits + graph_db for code-structure nodes + a
  dependency probe (graph-only). Detail level routes between three
  rendering modes.

* ``list_job_scripts`` — content-abstracted J-Job listing. Accepts
  ``job_list`` (names only) or ``files`` (name+content) arrays for
  remote MCP access, mirroring the Node.js "remote mode". When
  neither is provided the tool falls back to a graph_db query for
  J-Job nodes (the hosted Python port has no filesystem access).

* ``get_job_details`` — J-Job metadata assembled from graph_db node
  properties + relationships plus vector_db ``jjobs-v8-0-0`` hits.
  The ``include_content=True`` flag surfaces an ``[INFO]`` note:
  script bodies are only available on the legacy Node.js port, not
  on the hosted Python port.

Degraded-mode contract (Requirement 1.7)
----------------------------------------

All four tools require ``data`` at call time. When booted in
degraded-mode (``data=None``) they return ``[ERROR]`` markdown
rather than crashing. Registration always succeeds regardless of
backend availability.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

from fastmcp import FastMCP

from src.tenancy.resolver import get_current_tenant_or_none

log = logging.getLogger(__name__)


def _tenant():
    """Return the active tenant or None (for adapter kwarg)."""
    ctx = get_current_tenant_or_none()
    return ctx.tenant if ctx else None


# ── constants ──────────────────────────────────────────────────────────


#: Vector collection that stores operational-procedure embeddings.
#: Used by ``get_operational_guidance`` and as one of the fan-out
#: targets for ``explain_workflow_component``.
WORKFLOW_DOCS_COLLECTION: str = "global-workflow-docs-v8-0-0"

#: Vector collection that stores J-Job documentation embeddings.
#: Used by ``list_job_scripts`` (fallback) and ``get_job_details``.
JJOBS_COLLECTION: str = "jjobs-v8-0-0"

#: Vector collection that stores code-with-context embeddings. One
#: of the fan-out targets for ``explain_workflow_component``.
CODE_COLLECTION: str = "code-with-context-v8-0-0"

#: Enum values accepted by ``get_operational_guidance.platform``.
#: Matches the Node.js schema exactly.
PLATFORM_VALUES: tuple[str, ...] = (
    "hera",
    "hercules",
    "orion",
    "wcoss2",
    "gaea",
    "generic",
)

#: Enum values accepted by ``get_operational_guidance.urgency``.
URGENCY_VALUES: tuple[str, ...] = ("routine", "urgent", "emergency")

#: Enum values accepted by ``explain_workflow_component.detail_level``.
DETAIL_LEVEL_VALUES: tuple[str, ...] = ("basic", "detailed", "expert")

#: Enum values accepted by ``list_job_scripts.category``. No default
#: in the Node.js schema — callers omit the parameter for "all".
JOB_CATEGORY_VALUES: tuple[str, ...] = (
    "analysis",
    "forecast",
    "post",
    "archive",
    "verification",
    "all",
)

#: Enum values accepted by ``list_job_scripts.format``.
JOB_FORMAT_VALUES: tuple[str, ...] = ("summary", "detailed", "json")


#: Platform-specific notes appended to ``get_operational_guidance``
#: output. Ported verbatim from the Node.js ``platformNotes`` dict so
#: the rendered text is byte-identical under parity.
_PLATFORM_NOTES: dict[str, str] = {
    "hera": (
        "- NOAA RDHPCS system\n"
        "- Use Slurm for job submission\n"
        "- Module loads: HERA.env\n"
    ),
    "hercules": (
        "- MSU research system\n"
        "- Slurm scheduler\n"
        "- Module loads: HERCULES.env\n"
    ),
    "orion": (
        "- MSU research system\n"
        "- Slurm scheduler\n"
        "- Module loads: ORION.env\n"
    ),
    "wcoss2": (
        "- NOAA operational system\n"
        "- PBS scheduler\n"
        "- Module loads: WCOSS2.env\n"
    ),
    "gaea": (
        "- NOAA operational system\n"
        "- Slurm scheduler\n"
        "- Module loads: GAEA.env\n"
    ),
    "generic": (
        "- Platform-agnostic procedures\n"
        "- Adapt to local scheduler\n"
        "- Check platform detection\n"
    ),
}


_DEGRADED_MSG = (
    "Data access unavailable (degraded-mode boot). Operational tools "
    "require both the vector store (OpenSearch) and the graph store "
    "(Neptune) to be reachable from the runtime."
)

_CONTENT_UNAVAILABLE_MSG = (
    "[INFO] Script content is not available on the hosted Python "
    "port. To inspect the full body, query the Node.js legacy runtime "
    "or read the script directly from the global-workflow repository."
)


# ── helpers (pure functions) ───────────────────────────────────────────


def _categorize_job(job_name: str) -> str:
    """Port of the Node.js ``categorizeJob`` helper. Pure function —
    returns a bucket name based solely on the J-Job filename."""
    name = job_name.lower()
    if re.search(r"anl|anal|enkf|letkf|chgres", name):
        return "analysis"
    if re.search(r"fcst|forecast", name):
        return "forecast"
    if re.search(r"post|upp|awips|gempak|prod", name):
        return "post-processing"
    if re.search(r"arch|clean|globus", name):
        return "archive"
    if re.search(r"verf|fit2obs|cyclone|stat|tracker", name):
        return "verification"
    if re.search(r"wave", name):
        return "wave"
    if re.search(r"ocean|ice|marine", name):
        return "ocean"
    if re.search(r"aero", name):
        return "aerosol"
    return "general"


def _extract_system(job_name: str) -> str:
    """Port of the Node.js ``extractSystem`` helper."""
    if job_name.startswith("JGDAS"):
        return "gdas"
    if job_name.startswith("JGFS"):
        return "gfs"
    if job_name.startswith("JGLOBAL"):
        return "global"
    if job_name.startswith("JGEFS"):
        return "gefs"
    return "unknown"


#: Per-category filter regexes used by ``list_job_scripts``. Mirrors
#: the Node.js ``categories`` object — the ``analysis`` category uses
#: a stricter regex than ``_categorize_job`` (no ``chgres``) because
#: the listing bucket and the per-job category are separate concepts
#: in the Node.js source.
_LIST_CATEGORY_FILTERS: dict[str, re.Pattern[str]] = {
    "analysis": re.compile(r"atm|anl|anal|enkf|letkf", re.IGNORECASE),
    "forecast": re.compile(r"fcst|forecast", re.IGNORECASE),
    "post": re.compile(r"post|upp|awips|gempak|prod", re.IGNORECASE),
    "archive": re.compile(r"arch|clean|globus", re.IGNORECASE),
    "verification": re.compile(
        r"verf|fit2obs|cyclone|stat", re.IGNORECASE
    ),
}


def _error_text(message: str) -> str:
    return f"[ERROR] {message}\n"


# ── public entrypoint ──────────────────────────────────────────────────


def register(mcp: FastMCP, data: Any = None) -> None:
    """Register all 4 operational tools on ``mcp``.

    Parameters
    ----------
    mcp
        The FastMCP server instance.
    data
        ``UnifiedDataAccess``-shaped facade. ``None`` triggers
        degraded-mode for all 4 tools — they return ``[ERROR]``
        markdown rather than crashing.
    """

    @mcp.tool(
        name="get_operational_guidance",
        description=(
            "Get operational guidance and best practices for HPC "
            "operations. Searches the workflow-docs vector collection "
            "for platform-relevant procedures and appends platform-"
            "specific notes."
        ),
    )
    async def get_operational_guidance(
        operation: str,
        platform: Literal[
            "hera", "hercules", "orion", "wcoss2", "gaea", "generic"
        ] = "generic",
        urgency: Literal["routine", "urgent", "emergency"] = "routine",
    ) -> str:
        return await _tool_get_operational_guidance(
            data,
            operation=operation,
            platform=platform,
            urgency=urgency,
        )

    @mcp.tool(
        name="explain_workflow_component",
        description=(
            "Get detailed explanation of a workflow component (job "
            "script, config file, or directory) with graph context + "
            "documentation excerpts. Detail level routes rendering."
        ),
    )
    async def explain_workflow_component(
        component: str,
        detail_level: Literal["basic", "detailed", "expert"] = "detailed",
    ) -> str:
        return await _tool_explain_workflow_component(
            data,
            component=component,
            detail_level=detail_level,
        )

    @mcp.tool(
        name="list_job_scripts",
        description=(
            "List and categorize J-Job scripts in the workflow. Pass "
            "`job_list` (names) or `files` ({name, content}) for "
            "remote MCP mode; otherwise the tool falls back to a "
            "graph query for J-Job nodes."
        ),
    )
    async def list_job_scripts(
        category: Literal[
            "analysis",
            "forecast",
            "post",
            "archive",
            "verification",
            "all",
        ]
        | None = None,
        search: str | None = None,
        format: Literal["summary", "detailed", "json"] = "summary",
        job_list: list[str] | None = None,
        files: list[dict[str, Any]] | None = None,
    ) -> str:
        return await _tool_list_job_scripts(
            data,
            category=category,
            search=search,
            fmt=format,
            job_list=list(job_list or []),
            files=list(files or []),
        )

    @mcp.tool(
        name="get_job_details",
        description=(
            "Get comprehensive details about a J-Job — inputs, "
            "outputs, config files, environment variables, related "
            "documentation. Metadata is assembled from the graph "
            "store + jjobs-v8-0-0 vector collection."
        ),
    )
    async def get_job_details(
        job_name: str,
        include_content: bool = False,
        include_config: bool = True,
        include_chromadb: bool = True,
    ) -> str:
        return await _tool_get_job_details(
            data,
            job_name=job_name,
            include_content=include_content,
            include_config=include_config,
            include_chromadb=include_chromadb,
        )

    log.info(
        "registered operational tools: get_operational_guidance, "
        "explain_workflow_component, list_job_scripts, get_job_details"
    )


# ── get_operational_guidance ───────────────────────────────────────────


async def _tool_get_operational_guidance(
    data: Any,
    *,
    operation: str,
    platform: str,
    urgency: str,
) -> str:
    if not operation or not operation.strip():
        return _error_text("operation is required.")
    if data is None or getattr(data, "vector_db", None) is None:
        return _error_text(_DEGRADED_MSG)

    query = f"{operation} {platform} operational procedure best practices"
    try:
        results = await data.vector_db.query(
            WORKFLOW_DOCS_COLLECTION,
            query,
            k=5,
            include_graph=True,
            tenant=_tenant(),
        )
    except Exception as exc:
        log.warning("get_operational_guidance failed: %s", exc)
        return _error_text(f"get_operational_guidance failed: {exc}")

    lines: list[str] = [f"# Operational Guidance: {operation}", ""]
    lines.append(f"**Platform:** {platform.upper()}")
    lines.append(f"**Urgency:** {urgency.upper()}")
    lines.append("")

    if urgency == "emergency":
        lines.append("[WARN]  **EMERGENCY PROCEDURE**")
        lines.append("")
        lines.append("1. Check system logs immediately")
        lines.append("2. Contact on-call staff if needed")
        lines.append("3. Follow emergency protocols")
        lines.append("")

    lines.append("## Procedure")
    lines.append("")

    if results:
        for result in results:
            body = (
                result.get("document")
                or result.get("text")
                or result.get("content")
                or ""
            )
            if body:
                lines.append(body)
                lines.append("")
    else:
        lines.append("### General Guidance")
        lines.append("")
        lines.append(f"For {operation} on {platform}:")
        lines.append("")
        lines.append(
            f"1. Check environment configuration in env/{platform.upper()}.env"
        )
        lines.append("2. Review relevant job scripts in jobs/ directory")
        lines.append("3. Verify module loads and dependencies")
        lines.append("4. Monitor job execution logs")
        lines.append("5. Follow platform-specific submission procedures")
        lines.append("")

    lines.append("## Platform-Specific Notes")
    lines.append("")
    notes = _PLATFORM_NOTES.get(platform, _PLATFORM_NOTES["generic"])
    lines.append(notes.rstrip())
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ── explain_workflow_component ─────────────────────────────────────────


async def _tool_explain_workflow_component(
    data: Any,
    *,
    component: str,
    detail_level: str,
) -> str:
    if not component or not component.strip():
        return _error_text("component is required.")
    if data is None or getattr(data, "vector_db", None) is None:
        return _error_text(_DEGRADED_MSG)

    # 1. Documentation hits (vector).
    try:
        doc_hits = await data.vector_db.query(
            WORKFLOW_DOCS_COLLECTION,
            component,
            k=5,
            include_graph=False,
            tenant=_tenant(),
        )
    except Exception as exc:
        log.warning(
            "explain_workflow_component doc query failed: %s", exc
        )
        doc_hits = []

    # 2. Code-structure hits (graph).
    graph = getattr(data, "graph_db", None)
    graph_rows: list[dict[str, Any]] = []
    if graph is not None:
        try:
            graph_rows = await graph.query(
                "MATCH (n) "
                "WHERE n.name = $component OR n.absolutePath CONTAINS $component "
                "RETURN n.name AS name, labels(n)[0] AS type, "
                "n.absolutePath AS path, n.language AS language "
                "LIMIT 5",
                {"component": component},
            )
        except Exception as exc:
            log.debug("graph query failed: %s", exc)

    lines: list[str] = [f"# Workflow Component: {component}", ""]
    lines.append(f"**Detail Level:** {detail_level}")
    lines.append("")

    if doc_hits:
        lines.append("## Documentation")
        lines.append("")
        for hit in (doc_hits or [])[:2]:
            body = (
                hit.get("document")
                or hit.get("text")
                or hit.get("content")
                or ""
            )
            if body:
                lines.append(body)
                lines.append("")

    if graph_rows:
        lines.append("## Code Structure")
        lines.append("")
        for row in graph_rows:
            name = row.get("name") or row.get("file") or component
            lines.append(f"### {name}")
            type_ = row.get("type") or "Component"
            lines.append(f"- **Type:** {type_}")
            if row.get("path"):
                lines.append(f"- **Path:** {row['path']}")
            if row.get("language"):
                lines.append(f"- **Language:** {row['language']}")
            lines.append("")

    # 3. Dependency probe — one-hop IMPORTS out of the first graph
    #    hit, mirroring ``dataAccess.graphDb.findFileImports``.
    if graph is not None and graph_rows:
        first = graph_rows[0]
        target = first.get("path") or first.get("name")
        if target:
            try:
                imports = await graph.query(
                    "MATCH (f)-[:IMPORTS|SOURCES|USES]->(dep) "
                    "WHERE f.absolutePath = $path OR f.name = $path "
                    "RETURN dep.name AS importedFile, dep.absolutePath AS path "
                    "LIMIT 5",
                    {"path": target},
                )
            except Exception as exc:
                log.debug("imports query failed: %s", exc)
                imports = []
            if imports:
                lines.append("## Dependencies")
                lines.append("")
                for imp in imports:
                    name = (
                        imp.get("importedFile")
                        or imp.get("path")
                        or ""
                    )
                    if name:
                        lines.append(f"- {name}")
                lines.append("")

    if detail_level == "expert":
        lines.append("## Expert Notes")
        lines.append("")
        lines.append(
            "- Check source in repository for latest implementation"
        )
        lines.append(
            "- Review associated test files for usage examples"
        )
        lines.append(
            "- Consult platform-specific configurations in env/ directory"
        )
        lines.append(
            "- Verify integration points in workflow XML definitions"
        )
        lines.append("")

    if not doc_hits and not graph_rows:
        lines.append(
            f'*No documentation or graph hits found for `{component}`. '
            "Check the component name and try again.*"
        )

    return "\n".join(lines).rstrip() + "\n"


# ── list_job_scripts ──────────────────────────────────────────────────


async def _tool_list_job_scripts(
    data: Any,
    *,
    category: str | None,
    search: str | None,
    fmt: str,
    job_list: list[str],
    files: list[dict[str, Any]],
) -> str:
    # Determine source — explicit arguments win; otherwise fall back
    # to a graph query.
    content_map: dict[str, str] = {}
    source_note: str = ""

    if job_list:
        job_files = [f for f in job_list if isinstance(f, str) and f.startswith("J")]
        source_note = "*Source: job_list parameter (remote access)*"
    elif files:
        job_files = []
        for entry in files:
            name = entry.get("name") if isinstance(entry, dict) else None
            content = entry.get("content") if isinstance(entry, dict) else None
            if isinstance(name, str) and name.startswith("J"):
                job_files.append(name)
                if isinstance(content, str):
                    content_map[name] = content
        source_note = (
            "*Source: files parameter (remote access with content)*"
        )
    else:
        # No caller-supplied list — query graph_db.
        if data is None or getattr(data, "graph_db", None) is None:
            return _error_text(_DEGRADED_MSG)
        try:
            rows = await data.graph_db.query(
                "MATCH (j) WHERE j.name STARTS WITH 'J' "
                "AND ('RocotoTask' IN labels(j) OR 'ShellScript' IN labels(j) "
                "OR labels(j)[0] CONTAINS 'Job') "
                "RETURN j.name AS name ORDER BY j.name",
                {},
                tenant=_tenant(),
            )
        except Exception as exc:
            log.warning("list_job_scripts graph query failed: %s", exc)
            return _error_text(
                f"list_job_scripts graph query failed: {exc}"
            )
        job_files = [
            r.get("name")
            for r in (rows or [])
            if isinstance(r.get("name"), str) and r.get("name").startswith("J")
        ]
        source_note = "*Source: graph_db J-Job query*"

    # Apply search filter.
    if search and search.strip():
        needle = search.lower()
        job_files = [j for j in job_files if needle in j.lower()]

    # Categorize (expanded per Node.js).
    categories = {
        cat: [j for j in job_files if pat.search(j)]
        for cat, pat in _LIST_CATEGORY_FILTERS.items()
    }
    categories["all"] = list(job_files)

    target = category or "all"
    job_listing = sorted(categories.get(target, categories["all"]))

    if fmt == "json":
        payload = {"category": target, "jobs": job_listing}
        return (
            "```json\n"
            + json.dumps(payload, indent=2, sort_keys=False)
            + "\n```\n"
        )

    lines: list[str] = ["# Job Scripts", ""]
    lines.append(f"**Category:** {target}")
    lines.append(f"**Total:** {len(job_listing)} jobs")
    lines.append("")
    if source_note:
        lines.append(source_note)
        lines.append("")

    if fmt == "detailed":
        for job in job_listing:
            lines.append(f"## {job}")
            if job in content_map:
                content = content_map[job]
                desc = next(
                    (
                        line_.strip()
                        for line_ in content.split("\n")
                        if "Description" in line_ or "PURPOSE" in line_
                    ),
                    None,
                )
                lines.append(desc or "Job control script (content provided)")
            else:
                lines.append("Job control script")
            lines.append("")
    else:
        lines.append("## Categories")
        lines.append("")
        lines.append(f"- **Analysis:** {len(categories['analysis'])} jobs")
        lines.append(f"- **Forecast:** {len(categories['forecast'])} jobs")
        lines.append(
            f"- **Post-Processing:** {len(categories['post'])} jobs"
        )
        lines.append(f"- **Archive:** {len(categories['archive'])} jobs")
        lines.append(
            f"- **Verification:** {len(categories['verification'])} jobs"
        )
        lines.append("")
        lines.append("## Job List")
        lines.append("")
        for job in job_listing:
            lines.append(f"- {job}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ── get_job_details ────────────────────────────────────────────────────


async def _tool_get_job_details(
    data: Any,
    *,
    job_name: str,
    include_content: bool,
    include_config: bool,
    include_chromadb: bool,
) -> str:
    if not job_name or not job_name.strip():
        return _error_text("job_name is required.")
    if data is None or getattr(data, "graph_db", None) is None:
        return _error_text(_DEGRADED_MSG)

    # 1. Look up the J-Job node and its stored metadata.
    try:
        node_rows = await data.graph_db.query(
            "MATCH (j) WHERE j.name = $name "
            "RETURN j.name AS name, j.absolutePath AS path, "
            "j.lineCount AS lineCount, j.jobTask AS jobTask, "
            "labels(j) AS labels LIMIT 1",
            {"name": job_name},
            tenant=_tenant(),
        )
    except Exception as exc:
        log.warning("get_job_details node query failed: %s", exc)
        return _error_text(f"get_job_details failed: {exc}")

    if not node_rows:
        return _error_text(
            f"J-Job '{job_name}' not found in the graph store."
        )

    node = node_rows[0]

    # 2. Fetch related structured metadata (inputs / outputs /
    #    config files / env vars / sources / calls / com templates).
    #    These are stored as relationships in the ingestion pipeline
    #    (Phase 27E). Missing relationships degrade gracefully.
    async def _relation_rows(cypher: str) -> list[dict[str, Any]]:
        try:
            return list(
                await data.graph_db.query(cypher, {"name": job_name}, tenant=_tenant())
            ) or []
        except Exception as exc:
            log.debug("relation query failed (%s): %s", cypher[:40], exc)
            return []

    config_rows = await _relation_rows(
        "MATCH (j {name: $name})-[:USES_CONFIG|DEPENDS_ON]->(c:ConfigFile) "
        "RETURN c.name AS name, c.absolutePath AS path"
    )
    source_rows = await _relation_rows(
        "MATCH (j {name: $name})-[r:SOURCES]->(s) "
        "RETURN s.name AS script, s.absolutePath AS path, "
        "r.line AS line"
    )
    call_rows = await _relation_rows(
        "MATCH (j {name: $name})-[r:CALLS|INVOKES|EXECUTES]->(s) "
        "RETURN s.name AS script, r.variable AS variable, r.line AS line"
    )
    input_rows = await _relation_rows(
        "MATCH (j {name: $name})-[:CONSUMES|READS]->(i) "
        "RETURN i.variable AS variable, i.pattern AS pattern"
    )
    output_rows = await _relation_rows(
        "MATCH (j {name: $name})-[:PRODUCES|WRITES]->(o) "
        "RETURN o.variable AS variable, o.path AS path"
    )
    env_rows = await _relation_rows(
        "MATCH (j {name: $name})-[:DEPENDS_ON_ENV|EXPORTS]->(e:EnvironmentVariable) "
        "RETURN e.name AS name, e.value AS value LIMIT 50"
    )

    # 3. Vector hits for related docs.
    chromadb_hits: list[dict[str, Any]] = []
    if include_chromadb and getattr(data, "vector_db", None) is not None:
        try:
            chromadb_hits = list(
                await data.vector_db.query(
                    JJOBS_COLLECTION,
                    job_name,
                    k=3,
                    include_graph=False,
                    tenant=_tenant(),
                )
            ) or []
        except Exception as exc:
            log.debug("jjobs vector query failed: %s", exc)
            chromadb_hits = []

    category = _categorize_job(job_name)
    system = _extract_system(job_name)

    lines: list[str] = [f"# J-Job Details: {job_name}", ""]
    lines.append(f"**Path:** {node.get('path') or 'unknown'}")
    lines.append(f"**Lines:** {node.get('lineCount') or 'unknown'}")
    lines.append(f"**Category:** {category}")
    lines.append(f"**System:** {system}")
    lines.append(f"**Task:** {node.get('jobTask') or 'unknown'}")
    lines.append("")

    if config_rows:
        lines.append("## Configuration Files")
        lines.append("")
        for c in config_rows:
            name = c.get("name") or c.get("path") or ""
            if name:
                lines.append(f"- `{name}`")
        lines.append("")

    if source_rows:
        lines.append("## Sourced Scripts")
        lines.append("")
        for s in source_rows:
            script = s.get("script") or "unknown"
            line_ = s.get("line")
            lines.append(
                f"- {script}" + (f" (line {line_})" if line_ else "")
            )
        lines.append("")

    if call_rows:
        lines.append("## External Script Calls")
        lines.append("")
        for c in call_rows:
            script = c.get("script") or "unknown"
            var = c.get("variable") or "?"
            line_ = c.get("line")
            lines.append(
                f"- `{script}` via `{var}`"
                + (f" (line {line_})" if line_ else "")
            )
        lines.append("")

    if input_rows:
        lines.append("## Inputs")
        lines.append("")
        for inp in input_rows:
            var = inp.get("variable") or "?"
            pattern = inp.get("pattern") or ""
            lines.append(f"- **{var}**: `{pattern}`")
        lines.append("")

    if output_rows:
        lines.append("## Outputs")
        lines.append("")
        for out in output_rows:
            var = out.get("variable") or "?"
            path_ = out.get("path") or ""
            lines.append(f"- **{var}**: `{path_}`")
        lines.append("")

    if env_rows:
        lines.append("## Environment Variables")
        lines.append("")
        lines.append("| Variable | Value Pattern |")
        lines.append("|----------|---------------|")
        for env in env_rows[:15]:
            name = env.get("name") or "?"
            value = (env.get("value") or "").replace("|", "\\|")[:50]
            lines.append(f"| {name} | `{value}` |")
        if len(env_rows) > 15:
            lines.append("")
            lines.append(f"*...and {len(env_rows) - 15} more*")
        lines.append("")

    if include_config and not config_rows:
        lines.append("## Configuration Files")
        lines.append("")
        lines.append(
            "*No config-file relationships recorded in the graph for "
            "this job. Config content is not available on the hosted "
            "port.*"
        )
        lines.append("")

    if include_chromadb:
        lines.append("## Related Documentation (vector store)")
        lines.append("")
        if chromadb_hits:
            for hit in chromadb_hits:
                meta = hit.get("metadata") or {}
                source = meta.get("source_file") or JJOBS_COLLECTION
                body = (
                    hit.get("content")
                    or hit.get("document")
                    or hit.get("text")
                    or ""
                )
                summary = (body[:100] + "...") if body else "(empty)"
                score = hit.get("score")
                if score is None and hit.get("distance") is not None:
                    score = 1.0 - float(hit["distance"])
                score_s = (
                    f"{float(score):.2f}" if score is not None else "N/A"
                )
                lines.append(
                    f"- **{source}**: {summary} (relevance: {score_s})"
                )
            lines.append("")
        else:
            lines.append(
                f"*No jjobs-v8-0-0 hits for '{job_name}'.*"
            )
            lines.append("")

    if include_content:
        lines.append("## Full Script Content")
        lines.append("")
        lines.append(_CONTENT_UNAVAILABLE_MSG)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "WORKFLOW_DOCS_COLLECTION",
    "JJOBS_COLLECTION",
    "CODE_COLLECTION",
    "PLATFORM_VALUES",
    "URGENCY_VALUES",
    "DETAIL_LEVEL_VALUES",
    "JOB_CATEGORY_VALUES",
    "JOB_FORMAT_VALUES",
    "register",
]
