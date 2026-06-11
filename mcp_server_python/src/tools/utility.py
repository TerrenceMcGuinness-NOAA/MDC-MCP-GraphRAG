"""Utility tools module (Requirements 12.1 – 12.6).

Python port of the 4 utility tools from the Node.js
``UnifiedMCPServer.js.registerUtilityTools``:

* ``get_server_info`` — server version / tool count / capability summary.
* ``mcp_health_check`` — OpenSearch + Neptune connectivity with optional
  deep validation; matches the Phase 48/51 HealthChecker behaviour.
* ``get_health_trend`` — reads
  ``sdd_framework/execution_state/health_history.jsonl`` and renders
  count / latency / anomaly trend analysis.
* ``get_quality_metrics`` — reads
  ``sdd_framework/execution_state/quality_metrics.jsonl`` (if present)
  and renders a summary with optional regression comparison.

The tools are registered against a :class:`fastmcp.FastMCP` instance
via the standard ``register(mcp, data)`` entrypoint used by
``src.mcp_server._register_module``.

Sequencing note
---------------
Task 17 (this module) belongs to Phase B11 in the spec, but is ported
early because the first AgentCore Runtime smoke test needs a minimal
working tool set to validate deployment. The module has **zero hard
dependencies** on the yet-to-be-ported tool layers above it: if
``data`` is ``None`` (degraded-mode boot), ``get_server_info`` still
works and ``mcp_health_check`` reports the degraded state cleanly.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal, Protocol

from fastmcp import FastMCP

log = logging.getLogger(__name__)


# ── constants / defaults ────────────────────────────────────────────────


#: Default location of ``health_history.jsonl`` and ``quality_metrics.jsonl``.
#: Honors the ``SDD_STATE_DIR`` env var so tests can redirect without
#: patching the module.
DEFAULT_STATE_DIR: str = "sdd_framework/execution_state"

HEALTH_HISTORY_FILENAME: str = "health_history.jsonl"
QUALITY_METRICS_FILENAME: str = "quality_metrics.jsonl"

#: Canonical list of all 9 Python tool-port module names. Kept in sync
#: with ``src.config.environment.KNOWN_MODULES``. Used by
#: ``get_server_info`` to list active modules when the caller asks for
#: capability details.
ALL_TOOL_MODULES: tuple[str, ...] = (
    "semantic_search",
    "code_analysis",
    "graph_rag",
    "ee2_compliance",
    "operational",
    "sdd_workflow",
    "workflow_info",
    "github_tools",
    "utility",
)

#: Minimum vector indices expected for the cluster to be "healthy"
#: (matches Node.js ``HealthChecker.checkDatabases({minIndices: 5})``).
MIN_HEALTHY_INDICES: int = 5

#: Anomaly threshold for ``get_health_trend`` — matches the Node.js
#: constant used by phase 43's anomaly detector.
HEALTH_ANOMALY_PCT: float = 0.10


# ── light data-access protocol ──────────────────────────────────────────


class _HealthProvider(Protocol):
    """Structural contract the utility tools need from ``data``.

    Any object that exposes an awaitable ``health_check(*, deep)``
    returning the shape described in
    :pymeth:`tests.conftest.MockUnifiedDataAccess.health_check` is
    acceptable. The real ``UnifiedDataAccess`` facade implements the
    same shape; the mock variant implements it for unit tests.
    """

    async def health_check(self, *, deep: bool = False) -> dict[str, Any]: ...


# ── public entrypoint ───────────────────────────────────────────────────


def register(
    mcp: FastMCP,
    data: Any = None,
    *,
    state_dir: str | os.PathLike[str] | None = None,
    server_version: str | None = None,
) -> None:
    """Register all 4 utility tools on ``mcp``.

    Parameters
    ----------
    mcp
        The FastMCP server the tools should be registered against.
    data
        The ``UnifiedDataAccess`` facade (or ``None`` for degraded mode).
        Must have an awaitable ``health_check(deep=...)`` method when
        non-``None``.
    state_dir
        Override for the directory holding ``health_history.jsonl`` and
        ``quality_metrics.jsonl``. Falls back to the ``SDD_STATE_DIR``
        environment variable, then to :data:`DEFAULT_STATE_DIR`.
    server_version
        Override for the version string surfaced by ``get_server_info``.
        Defaults to :data:`src.mcp_server.SERVER_VERSION` (``"1.0.0"``
        at the time of this port).
    """
    state_root = _resolve_state_dir(state_dir)
    version = server_version or _default_server_version()

    @mcp.tool(
        name="get_server_info",
        description=(
            "Get information about the MCP server and available tools. "
            "Returns a markdown summary including version, tool count, "
            "and active module list."
        ),
    )
    async def get_server_info(include_capabilities: bool = False) -> str:
        """Port of Node.js ``UnifiedMCPServer.getServerInfo``."""
        return await _render_server_info(
            mcp,
            version,
            data,
            include_capabilities=include_capabilities,
        )

    @mcp.tool(
        name="mcp_health_check",
        description=(
            "Check the health status of all MCP server components with "
            "empirical data validation. Supports detailed per-component "
            "output, deep sample-query validation, and functional tool tests."
        ),
    )
    async def mcp_health_check(
        detailed: bool = False,
        deep: bool = False,
        functional: bool = False,
    ) -> str:
        """Port of Node.js ``UnifiedMCPServer.healthCheck``."""
        return await _render_health_check(
            data,
            state_dir=state_root,
            detailed=detailed,
            deep=deep,
            functional=functional,
            mcp=mcp,
        )

    @mcp.tool(
        name="get_health_trend",
        description=(
            "Get health trend data from persisted snapshots. Shows count "
            "trends, latency trends, and anomaly detection over time."
        ),
    )
    async def get_health_trend(limit: int = 10) -> str:
        """Port of Node.js ``UnifiedMCPServer.getHealthTrend``."""
        return _render_health_trend(state_root, limit=limit)

    @mcp.tool(
        name="get_quality_metrics",
        description=(
            "Get RAG quality benchmark metrics. Reads latest benchmark "
            "results and returns a formatted summary with optional "
            "regression comparison against the prior snapshot."
        ),
    )
    async def get_quality_metrics(
        category: Literal[
            "code_structure",
            "semantic_search",
            "architecture",
            "ee2_compliance",
            "operational",
            "cross_language",
        ]
        | None = None,
        compare: bool = False,
    ) -> str:
        """Port of Node.js ``UnifiedMCPServer.getQualityMetrics``."""
        return _render_quality_metrics(
            state_root, category=category, compare=compare
        )

    log.info("registered utility tools: get_server_info, mcp_health_check, "
             "get_health_trend, get_quality_metrics")


# ── get_server_info ─────────────────────────────────────────────────────


async def _render_server_info(
    mcp: FastMCP,
    version: str,
    data: Any,
    *,
    include_capabilities: bool,
) -> str:
    tools = await _safe_list_tools(mcp)
    tool_names = sorted(t.name for t in tools)
    active_modules = _infer_active_modules(tool_names)

    lines = [
        f"# MDC MCP/RAG Server v{version}",
        "",
        f"**Total Tools**: {len(tool_names)}",
        f"**Active Modules**: {len(active_modules)} of {len(ALL_TOOL_MODULES)}",
    ]

    # Tenant info (R5.4)
    try:
        from src.tenancy.runtime import get_catalog, get_default_tenant
        catalog = get_catalog()
        default = get_default_tenant()
        lines.append(f"**Tenants**: {len(catalog.tenants)} (default: {default.tenant_id})")
    except Exception:
        lines.append("**Tenants**: unavailable")

    lines.append("")
    lines.append("## Active Modules")
    if active_modules:
        for mod in active_modules:
            lines.append(f"- `{mod}`")
    else:
        lines.append("- _(none — server in degraded mode)_")
    lines.append("")

    lines.append("## Registered Tools")
    if tool_names:
        for name in tool_names:
            lines.append(f"- `{name}`")
    else:
        lines.append("- _(no tools registered yet)_")
    lines.append("")

    if include_capabilities:
        lines.extend(_render_capability_block(data, active_modules))

    return "\n".join(lines).rstrip() + "\n"


async def _safe_list_tools(mcp: FastMCP) -> list[Any]:
    """Return the currently registered tools, or an empty list on error.

    The try/except guard handles the (unlikely) case where FastMCP's
    internal tool manager hasn't finished registering before the tool
    itself is called — e.g. during a dry-run health check at startup.
    """
    try:
        return list(await mcp.list_tools(run_middleware=False))
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("list_tools() failed: %s", exc)
        return []


def _infer_active_modules(tool_names: Iterable[str]) -> list[str]:
    """Guess which of the 9 tool modules are loaded from the tool set.

    We only know which Phase B11 tools are live (utility module) so the
    detection is conservative — the module is considered active if at
    least one of its canonical tool names appears. The canonical lists
    are taken from the Node.js ``UnifiedMCPServer.js`` tool registration
    blocks.
    """
    tool_set = set(tool_names)
    module_markers: dict[str, tuple[str, ...]] = {
        "semantic_search": (
            "search_documentation",
            "find_related_files",
            "explain_with_context",
            "get_knowledge_base_status",
            "list_ingested_urls",
            "get_ingested_urls_array",
            "check_knowledge_integrity",
        ),
        "code_analysis": (
            "analyze_code_structure",
            "find_dependencies",
            "trace_execution_path",
            "find_callers_callees",
            "trace_full_execution_chain",
            "find_env_dependencies",
        ),
        "graph_rag": (
            "get_code_context",
            "search_architecture",
            "find_similar_code",
            "get_change_impact",
            "trace_data_flow",
            "mark_as_modified",
            "get_session_context",
            "checkpoint_state",
            "restore_checkpoint",
        ),
        "ee2_compliance": (
            "search_ee2_standards",
            "analyze_ee2_compliance",
            "generate_compliance_report",
            "scan_repository_compliance",
            "extract_code_for_analysis",
        ),
        "operational": (
            "get_operational_guidance",
            "explain_workflow_component",
            "list_job_scripts",
            "get_job_details",
        ),
        "sdd_workflow": (
            "list_sdd_workflows",
            "get_sdd_workflow",
            "start_sdd_session",
            "record_sdd_step",
            "get_sdd_session",
            "complete_sdd_session",
            "get_sdd_execution_history",
            "validate_sdd_compliance",
            "get_sdd_framework_status",
        ),
        "workflow_info": (
            "get_workflow_structure",
            "get_system_configs",
            "describe_component",
        ),
        "github_tools": (
            "search_issues",
            "get_pull_requests",
            "analyze_workflow_dependencies",
            "analyze_repository_structure",
        ),
        "utility": (
            "get_server_info",
            "mcp_health_check",
            "get_health_trend",
            "get_quality_metrics",
        ),
    }
    active: list[str] = []
    for module, markers in module_markers.items():
        if any(marker in tool_set for marker in markers):
            active.append(module)
    return active


def _render_capability_block(
    data: Any, active_modules: list[str]
) -> list[str]:
    lines = ["## Capabilities", ""]
    lines.append(f"- **Data Access**: {'connected' if data is not None else 'degraded (no data layer)'}")
    lines.append(
        f"- **Vector Search**: {'available' if data is not None else 'unavailable'}"
    )
    lines.append(
        f"- **Graph Queries**: {'available' if data is not None else 'unavailable'}"
    )
    lines.append(
        f"- **Utility Tools**: always-on "
        f"({'4 tools registered' if 'utility' in active_modules else 'not loaded'})"
    )
    lines.append("")
    return lines


# ── mcp_health_check ────────────────────────────────────────────────────


@dataclass
class _HealthRow:
    component: str
    status: str  # healthy | degraded | unhealthy | disabled | initializing
    details: str


async def _render_health_check(
    data: Any,
    *,
    state_dir: Path,
    detailed: bool,
    deep: bool,
    functional: bool,
    mcp: FastMCP | None = None,
) -> str:
    rows: list[_HealthRow] = [
        _HealthRow("Base Server", "healthy", "FastMCP running"),
        _HealthRow(
            "Utility Tools",
            "healthy",
            "4 utility tools registered",
        ),
    ]

    health_payload: dict[str, Any] | None = None
    if data is None:
        rows.append(
            _HealthRow(
                "Data Access Layer",
                "disabled",
                "No data access layer (degraded-mode boot)",
            )
        )
    else:
        try:
            health_payload = await data.health_check(deep=deep)
        except Exception as exc:
            log.warning("data.health_check failed: %s", exc)
            rows.append(
                _HealthRow("Data Access Layer", "unhealthy", f"{exc}")
            )

    if health_payload is not None:
        vec = health_payload.get("vector") or {}
        graph = health_payload.get("graph") or {}
        vec_status = "healthy" if vec.get("ok") else "degraded"
        graph_status = "healthy" if graph.get("ok") else "degraded"
        rows.append(
            _HealthRow(
                "Vector Database",
                vec_status,
                (
                    f"{vec.get('indexCount', 0)} indices"
                    if vec.get("ok")
                    else (vec.get("reason") or "unavailable")
                ),
            )
        )
        rows.append(
            _HealthRow(
                "Graph Database",
                graph_status,
                (
                    f"{graph.get('nodeCount', 0)} nodes, "
                    f"{graph.get('relationshipCount', 0)} relationships"
                    if graph.get("ok")
                    else (graph.get("reason") or "unavailable")
                ),
            )
        )

    overall = _overall_status(rows)
    healthy_count = sum(1 for r in rows if r.status == "healthy")

    # ── render ────────────────────────────────────────────────────────
    status_emoji = {
        "healthy": "[OK]",
        "degraded": "[WARN]",
        "unhealthy": "[ERROR]",
        "disabled": "[OFF]",
        "initializing": "[INIT]",
    }

    lines = [
        "# Server Health Check",
        "",
        f"**Overall Status**: {overall} ({healthy_count}/{len(rows)} components healthy)",
        "",
    ]
    for row in rows:
        marker = status_emoji.get(row.status, "[?]")
        line = f"{marker} **{row.component}**: {row.status}"
        if detailed or row.status != "healthy":
            line += f" - {row.details}"
        lines.append(line)

    # ── Tenants section (R8.1, R8.5) ──────────────────────────────────
    if detailed:
        try:
            from src.tenancy.runtime import get_catalog, get_default_tenant

            catalog = get_catalog()
            default_tenant = get_default_tenant()
            lines.append("")
            lines.append(f"## Tenants ({len(catalog.tenants)})")
            lines.append("")
            lines.append(
                "| tenant_id | branch | lifecycle | index_prefix | "
                "label_prefix | workflow_subdir | workflow_root reachable |"
            )
            lines.append(
                "|-----------|--------|-----------|--------------|"
                "--------------|-----------------|-------------------------|"
            )
            for t in catalog.tenants:
                reachable = "yes" if t.workflow_root.is_dir() else "no"
                lines.append(
                    f"| {t.tenant_id} | {t.branch} | {t.lifecycle} "
                    f"| {t.index_prefix!r} | {t.label_prefix!r} "
                    f"| {t.workflow_subdir} | {reachable} ({t.workflow_root}) |"
                )
            lines.append("")
            lines.append(
                f"Default tenant: {default_tenant.tenant_id}  "
                f"(resolved from catalog.defaults.tenant_id)"
            )
        except Exception as exc:
            lines.append("")
            lines.append(f"## Tenants\n\n_Error loading catalog: {exc}_")

    # ── Workflow Filesystem section (R8.6) ─────────────────────────────
    if detailed:
        mount_path = Path("/mnt/workflow")
        mounted = mount_path.is_dir()
        lines.append("")
        lines.append("## Workflow Filesystem")
        lines.append("")
        lines.append(
            f"- mount: /mnt/workflow ({'mounted' if mounted else 'NOT mounted'})"
        )
        if mounted:
            subdirs = sorted(
                p.name for p in mount_path.iterdir() if p.is_dir()
            )
            lines.append(f"- subdirectories: {', '.join(subdirs) if subdirs else '(none)'}")

    functional_summary: dict[str, int] | None = None
    if functional:
        lines.append("")
        lines.append("## Functional Validation")
        lines.append("")
        if data is None:
            lines.append(
                "_Functional tests skipped — no data access layer available._"
            )
        else:
            # Late import keeps the smoke-query module out of the
            # utility import graph for callers that never opt into
            # ``functional=True``.
            from src.tools.smoke_queries import SmokeQueryRegistry

            registry = SmokeQueryRegistry()
            try:
                results = await registry.run_all(data, mcp=mcp)
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("smoke registry run_all failed: %s", exc)
                lines.append(
                    f"_Functional tests aborted: {type(exc).__name__}: {exc}_"
                )
            else:
                functional_summary = _functional_summary(results)
                lines.extend(_render_functional_results(results))

    if deep and health_payload is not None:
        _append_health_snapshot(
            state_dir, health_payload, functional=functional_summary
        )
        lines.append("")
        lines.append("*Health snapshot persisted to health_history.jsonl*")

    return "\n".join(lines).rstrip() + "\n"


def _overall_status(rows: list[_HealthRow]) -> str:
    if any(r.status == "unhealthy" for r in rows):
        return "UNHEALTHY"
    if any(r.status == "degraded" for r in rows):
        return "DEGRADED"
    return "HEALTHY"


def _render_functional_results(results: list[Any]) -> list[str]:
    """Render a list of :pyclass:`ModuleResult` as markdown.

    Output shape (matches design.md §4):

    .. code-block:: markdown

        | Module | Status | Latency | Error |
        |--------|--------|---------|-------|
        | semantic_search | [OK] pass | 142ms |  |
        | github_tools    | [SKIP] skip | 0ms | GITHUB_TOKEN not set |

        **Summary**: 8/9 passed, 0 failed, 1 skipped

    Status emoji prefixes (``[OK]`` / ``[ERROR]`` / ``[SKIP]``) match
    the rest of the health-check output for visual consistency, and
    are ASCII-only per the steering rule.
    """
    status_marker = {"pass": "[OK]", "fail": "[ERROR]", "skip": "[SKIP]"}

    lines: list[str] = []
    lines.append("| Module | Status | Latency | Error |")
    lines.append("|--------|--------|---------|-------|")
    for r in results:
        marker = status_marker.get(r.status, "[?]")
        status_cell = f"{marker} {r.status}"
        # Pipes in error messages would break the markdown table —
        # collapse them to slashes; truncate egregiously long
        # messages so the table stays scannable.
        err = (r.error or "").replace("|", "/")
        if len(err) > 140:
            err = err[:137] + "..."
        latency = f"{r.latency_ms}ms"
        lines.append(
            f"| {r.module} | {status_cell} | {latency} | {err} |"
        )

    summary = _functional_summary(results)
    lines.append("")
    lines.append(
        f"**Summary**: {summary['passed']}/{summary['total']} passed, "
        f"{summary['failed']} failed, {summary['skipped']} skipped"
    )
    return lines


def _functional_summary(results: list[Any]) -> dict[str, int]:
    """Tally pass / fail / skip counts for a list of ``ModuleResult``.

    Single source of truth for both the rendered summary line and the
    persisted ``health_history.jsonl`` ``functional`` block (R3.5).
    Skips are counted separately from failures so a downstream trend
    tool can distinguish "not provisioned" from "broken".
    """
    passed = failed = skipped = 0
    for r in results:
        if r.status == "pass":
            passed += 1
        elif r.status == "fail":
            failed += 1
        elif r.status == "skip":
            skipped += 1
    return {
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "total": len(results),
    }


def _append_health_snapshot(
    state_dir: Path,
    payload: dict[str, Any],
    *,
    functional: dict[str, int] | None = None,
) -> None:
    """Persist a health snapshot in the Node.js-compatible JSONL format.

    Schema is a 1:1 port of the Node.js ``UnifiedMCPServer.healthCheck``
    deep-mode writer:

    .. code-block:: json

        {
          "timestamp": "2026-05-12T23:10:00.000Z",
          "source": "tool_call",
          "neo4j": {"status": "ok", "nodes": 59759,
                    "relationships": 2633374, "latency_ms": 12},
          "chromadb": {"status": "healthy", "collections": 5,
                       "total_docs": 85000, "latency_ms": 5},
          "drift": {"neo4j_node_delta": 0, "chromadb_doc_delta": 0}
        }

    Drift is computed against the last line of the file, mirroring the
    Node.js implementation.
    """
    vec = payload.get("vector") or {}
    graph = payload.get("graph") or {}
    timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
    snapshot: dict[str, Any] = {
        "timestamp": timestamp,
        "source": "tool_call",
        "neo4j": {
            "status": "ok" if graph.get("ok") else (graph.get("status") or "error"),
            "nodes": int(graph.get("nodeCount") or 0),
            "relationships": int(graph.get("relationshipCount") or 0),
            "latency_ms": graph.get("latency_ms"),
        },
        "chromadb": {
            "status": vec.get("status") or "unknown",
            "collections": int(vec.get("indexCount") or 0),
            "total_docs": int(vec.get("totalDocuments") or 0),
            "latency_ms": vec.get("latency_ms"),
        },
        "drift": {"neo4j_node_delta": 0, "chromadb_doc_delta": 0},
    }

    # R3.5: carry functional smoke counts (passed/failed/skipped) into the
    # persisted snapshot so a downstream trend tool can distinguish skips
    # from failures. Additive + optional — old readers ignore the key, so
    # this is forward-compatible with the existing JSONL schema.
    if functional is not None:
        snapshot["functional"] = {
            "passed": int(functional.get("passed", 0)),
            "failed": int(functional.get("failed", 0)),
            "skipped": int(functional.get("skipped", 0)),
        }

    history_path = state_dir / HEALTH_HISTORY_FILENAME
    prev = _read_last_health_snapshot(history_path)
    if prev is not None:
        snapshot["drift"]["neo4j_node_delta"] = snapshot["neo4j"]["nodes"] - int(
            (prev.get("neo4j") or {}).get("nodes") or 0
        )
        snapshot["drift"]["chromadb_doc_delta"] = snapshot["chromadb"][
            "total_docs"
        ] - int((prev.get("chromadb") or {}).get("total_docs") or 0)

    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        with history_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    except OSError as exc:  # pragma: no cover - defensive
        log.warning("failed to persist health snapshot: %s", exc)


def _read_last_health_snapshot(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            last = None
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    last = json.loads(line)
                except json.JSONDecodeError:
                    continue
            return last
    except OSError:
        return None


# ── get_health_trend ────────────────────────────────────────────────────


def _render_health_trend(state_dir: Path, *, limit: int) -> str:
    if limit < 1:
        return "# Health Trend\n\nInvalid limit — must be ≥ 1.\n"

    history_path = state_dir / HEALTH_HISTORY_FILENAME
    if not history_path.is_file():
        return (
            "# Health Trend\n\n"
            "No health history found. Run `mcp_health_check({ deep: true })` "
            "to generate the first snapshot.\n"
        )

    snapshots = _read_health_snapshots(history_path, limit=limit)
    if not snapshots:
        return (
            "# Health Trend\n\n"
            "Health history file is empty. Run `mcp_health_check({ deep: true })` "
            "to generate snapshots.\n"
        )

    lines = [f"# Health Trend (last {len(snapshots)} snapshots)", ""]
    lines.append(
        "| Timestamp | Neo4j Nodes | Neo4j Rels | ChromaDB Docs | "
        "Collections | Node Drift | Doc Drift |"
    )
    lines.append(
        "|-----------|-------------|------------|---------------|"
        "-------------|------------|-----------|"
    )
    for s in snapshots:
        ts = _format_ts(s.get("timestamp"))
        neo = s.get("neo4j") or {}
        chroma = s.get("chromadb") or {}
        drift = s.get("drift") or {}
        lines.append(
            f"| {ts} | {neo.get('nodes', '?')} | {neo.get('relationships', '?')} "
            f"| {chroma.get('total_docs', '?')} | {chroma.get('collections', '?')} "
            f"| {drift.get('neo4j_node_delta', 0)} "
            f"| {drift.get('chromadb_doc_delta', 0)} |"
        )
    lines.append("")

    # Trends + anomalies require at least 2 snapshots.
    if len(snapshots) >= 2:
        lines.extend(_render_trend_section(snapshots))
        lines.extend(_render_anomaly_section(snapshots))

    return "\n".join(lines).rstrip() + "\n"


def _read_health_snapshots(
    path: Path, *, limit: int
) -> list[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            items: list[dict[str, Any]] = []
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return items[-limit:]


def _render_trend_section(snapshots: list[dict[str, Any]]) -> list[str]:
    first = snapshots[0]
    last = snapshots[-1]
    first_neo = (first.get("neo4j") or {}).get("nodes") or 0
    last_neo = (last.get("neo4j") or {}).get("nodes") or 0
    first_docs = (first.get("chromadb") or {}).get("total_docs") or 0
    last_docs = (last.get("chromadb") or {}).get("total_docs") or 0

    def _label(delta: int) -> str:
        if delta > 0:
            return "increasing"
        if delta < 0:
            return "decreasing"
        return "stable"

    node_delta = last_neo - first_neo
    doc_delta = last_docs - first_docs
    lines = ["## Trends", ""]
    lines.append(
        f"- **Neo4j nodes**: {_label(node_delta)} "
        f"({'+' if node_delta >= 0 else ''}{node_delta} over "
        f"{len(snapshots)} snapshots)"
    )
    lines.append(
        f"- **ChromaDB docs**: {_label(doc_delta)} "
        f"({'+' if doc_delta >= 0 else ''}{doc_delta} over "
        f"{len(snapshots)} snapshots)"
    )

    neo_lat = [
        (s.get("neo4j") or {}).get("latency_ms")
        for s in snapshots
        if (s.get("neo4j") or {}).get("latency_ms") is not None
    ]
    chroma_lat = [
        (s.get("chromadb") or {}).get("latency_ms")
        for s in snapshots
        if (s.get("chromadb") or {}).get("latency_ms") is not None
    ]
    if len(neo_lat) >= 2:
        avg = sum(neo_lat) / len(neo_lat)
        trend = neo_lat[-1] - neo_lat[0]
        lines.append(
            f"- **Neo4j latency**: avg {avg:.0f}ms, trend "
            f"{'+' if trend >= 0 else ''}{trend}ms "
            f"({'degrading' if trend > 0 else 'improving'})"
        )
    if len(chroma_lat) >= 2:
        avg = sum(chroma_lat) / len(chroma_lat)
        trend = chroma_lat[-1] - chroma_lat[0]
        lines.append(
            f"- **ChromaDB latency**: avg {avg:.0f}ms, trend "
            f"{'+' if trend >= 0 else ''}{trend}ms "
            f"({'degrading' if trend > 0 else 'improving'})"
        )
    lines.append("")
    return lines


def _render_anomaly_section(snapshots: list[dict[str, Any]]) -> list[str]:
    anomalies: list[str] = []
    for prev, curr in zip(snapshots, snapshots[1:]):
        prev_neo = (prev.get("neo4j") or {}).get("nodes") or 0
        curr_neo = (curr.get("neo4j") or {}).get("nodes") or 0
        prev_docs = (prev.get("chromadb") or {}).get("total_docs") or 0
        curr_docs = (curr.get("chromadb") or {}).get("total_docs") or 0
        ts = curr.get("timestamp", "?")
        if prev_neo > 0 and abs(curr_neo - prev_neo) / prev_neo > HEALTH_ANOMALY_PCT:
            anomalies.append(
                f"[WARN] Neo4j node count jumped from {prev_neo} to {curr_neo} at {ts}"
            )
        if prev_docs > 0 and abs(curr_docs - prev_docs) / prev_docs > HEALTH_ANOMALY_PCT:
            anomalies.append(
                f"[WARN] ChromaDB doc count jumped from {prev_docs} to "
                f"{curr_docs} at {ts}"
            )
    if anomalies:
        return ["## Anomalies Detected", "", *anomalies, ""]
    return [
        "## Anomalies",
        "",
        "No anomalies detected (all consecutive changes within "
        f"{int(HEALTH_ANOMALY_PCT * 100)}% threshold).",
        "",
    ]


def _format_ts(ts: Any) -> str:
    if not isinstance(ts, str):
        return "?"
    # "2026-05-12T23:10:00.000Z" → "2026-05-12 23:10:00"
    return ts.replace("T", " ")[:19]


# ── get_quality_metrics ────────────────────────────────────────────────


def _render_quality_metrics(
    state_dir: Path,
    *,
    category: str | None,
    compare: bool,
) -> str:
    metrics_path = state_dir / QUALITY_METRICS_FILENAME
    if not metrics_path.is_file():
        return (
            "# RAG Quality Metrics\n\n"
            "No benchmark results found. Expected at "
            f"`{metrics_path}`.\n\n"
            "Run the benchmark harness to generate results.\n"
        )

    snapshots = _read_quality_snapshots(metrics_path)
    if not snapshots:
        return (
            "# RAG Quality Metrics\n\n"
            "`quality_metrics.jsonl` is empty. Run the benchmark harness "
            "to generate results.\n"
        )

    latest = snapshots[-1]
    previous = snapshots[-2] if len(snapshots) >= 2 else None

    lines = ["# RAG Quality Metrics", ""]
    lines.append(f"**Benchmark**: {latest.get('timestamp', 'Unknown')}")
    lines.append(
        f"**Corpus Version**: {latest.get('corpus_version', latest.get('version', 'Unknown'))}"
        f" ({latest.get('total_queries', 'N/A')} queries)"
    )
    lines.append("")

    overall = latest.get("overall")
    if isinstance(overall, dict):
        lines.extend(_render_overall_block(overall))

    categories = latest.get("categories") or {}
    if categories:
        lines.extend(
            _render_category_block(categories, filter_key=category)
        )

    if compare:
        if previous is None:
            lines.append("## Regression\n")
            lines.append(
                "Only one benchmark snapshot available — rerun the benchmark "
                "to enable regression comparison.\n"
            )
        else:
            lines.extend(
                _render_regression_block(latest, previous, filter_key=category)
            )

    return "\n".join(lines).rstrip() + "\n"


def _read_quality_snapshots(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            out: list[dict[str, Any]] = []
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            return out
    except OSError:
        return []


def _fmt_val(v: Any) -> str:
    if v is None:
        return "N/A"
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return str(v)


def _fmt_pct(v: Any) -> str:
    if v is None:
        return "N/A"
    try:
        return f"{float(v) * 100:.0f}%"
    except (TypeError, ValueError):
        return str(v)


def _fmt_ms(v: Any) -> str:
    if v is None:
        return "N/A"
    try:
        return f"{int(float(v))}ms"
    except (TypeError, ValueError):
        return str(v)


def _fmt_category_name(key: str) -> str:
    return key.replace("_", " ").title()


def _render_overall_block(overall: dict[str, Any]) -> list[str]:
    return [
        "## Overall",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Precision@5 | {_fmt_val(overall.get('precision_at_k'))} |",
        f"| Recall@5 | {_fmt_val(overall.get('recall_at_k'))} |",
        f"| MRR | {_fmt_val(overall.get('mrr'))} |",
        f"| Coverage | {_fmt_pct(overall.get('coverage'))} |",
        f"| Latency P50 | {_fmt_ms(overall.get('latency_p50_ms'))} |",
        f"| Latency P95 | {_fmt_ms(overall.get('latency_p95_ms'))} |",
        "",
    ]


def _render_category_block(
    categories: dict[str, Any], *, filter_key: str | None
) -> list[str]:
    items = categories.items()
    if filter_key is not None:
        items = [(k, v) for k, v in items if k == filter_key]
        if not items:
            return [
                f"## Category: {_fmt_category_name(filter_key)}",
                "",
                f"No results found for category `{filter_key}`.",
                "",
            ]

    heading = (
        f"## Category: {_fmt_category_name(filter_key)}"
        if filter_key is not None
        else "## By Category"
    )
    lines = [heading, ""]
    lines.append("| Category | P@5 | R@5 | MRR | Coverage | P50 |")
    lines.append("|----------|-----|-----|-----|----------|-----|")
    for key, cat in items:
        if not isinstance(cat, dict):
            continue
        lines.append(
            f"| {_fmt_category_name(key)} "
            f"| {_fmt_val(cat.get('precision_at_k'))} "
            f"| {_fmt_val(cat.get('recall_at_k'))} "
            f"| {_fmt_val(cat.get('mrr'))} "
            f"| {_fmt_pct(cat.get('coverage'))} "
            f"| {_fmt_ms(cat.get('latency_p50_ms'))} |"
        )
    lines.append("")
    return lines


def _render_regression_block(
    latest: dict[str, Any],
    previous: dict[str, Any],
    *,
    filter_key: str | None,
) -> list[str]:
    curr_cats = latest.get("categories") or {}
    prev_cats = previous.get("categories") or {}
    prev_ts = previous.get("timestamp", "previous")
    lines = [f"## Regression (vs {prev_ts})", ""]
    lines.append("| Category | Metric | Previous | Current | Delta |")
    lines.append("|----------|--------|----------|---------|-------|")

    metrics = [
        ("precision_at_k", "P@5", _fmt_val),
        ("recall_at_k", "R@5", _fmt_val),
        ("mrr", "MRR", _fmt_val),
        ("coverage", "Coverage", _fmt_pct),
        ("latency_p50_ms", "P50", _fmt_ms),
    ]
    all_cats = sorted(set(curr_cats) | set(prev_cats))
    if filter_key is not None:
        all_cats = [c for c in all_cats if c == filter_key]

    for cat in all_cats:
        cur = curr_cats.get(cat) or {}
        prev = prev_cats.get(cat) or {}
        for key, label, fmt in metrics:
            cur_val = cur.get(key)
            prev_val = prev.get(key)
            if cur_val is None and prev_val is None:
                continue
            delta_str = "N/A"
            if cur_val is not None and prev_val is not None:
                try:
                    prev_f = float(prev_val)
                    cur_f = float(cur_val)
                    if prev_f != 0:
                        delta_pct = ((cur_f - prev_f) / abs(prev_f)) * 100
                        sign = "+" if delta_pct >= 0 else ""
                        is_latency = key.startswith("latency_")
                        tag = (
                            ("[IMPROVED]" if delta_pct <= 0 else "[DEGRADED]")
                            if is_latency
                            else ("[IMPROVED]" if delta_pct >= 0 else "[DEGRADED]")
                        )
                        delta_str = f"{sign}{delta_pct:.0f}% {tag}"
                except (TypeError, ValueError):
                    pass
            lines.append(
                f"| {_fmt_category_name(cat)} | {label} "
                f"| {fmt(prev_val)} | {fmt(cur_val)} | {delta_str} |"
            )
    lines.append("")
    return lines


# ── helpers ─────────────────────────────────────────────────────────────


def _resolve_state_dir(
    state_dir: str | os.PathLike[str] | None,
) -> Path:
    """Resolve the effective state directory per the documented precedence.

    Precedence (highest → lowest):
    1. Explicit ``state_dir`` argument to :pyfunc:`register`.
    2. ``SDD_STATE_DIR`` environment variable.
    3. :data:`DEFAULT_STATE_DIR`.
    """
    if state_dir is not None:
        return Path(state_dir).resolve()
    env = os.environ.get("SDD_STATE_DIR")
    if env:
        return Path(env).resolve()
    return Path(DEFAULT_STATE_DIR).resolve()


def _default_server_version() -> str:
    """Return the server version as advertised by ``src.mcp_server``.

    Late-imported so a broken ``mcp_server`` cannot prevent the utility
    module from loading; falls back to ``"1.0.0"`` on any failure.
    """
    try:
        from src.mcp_server import SERVER_VERSION  # type: ignore[no-redef]
        return SERVER_VERSION
    except Exception:  # pragma: no cover - defensive
        return "1.0.0"


__all__ = [
    "ALL_TOOL_MODULES",
    "DEFAULT_STATE_DIR",
    "HEALTH_ANOMALY_PCT",
    "HEALTH_HISTORY_FILENAME",
    "MIN_HEALTHY_INDICES",
    "QUALITY_METRICS_FILENAME",
    "register",
]
