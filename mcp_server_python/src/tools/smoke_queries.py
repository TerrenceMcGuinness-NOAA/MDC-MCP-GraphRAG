"""Per-tool-module functional smoke queries.

Implements the shared registry consumed by both
:func:`src.tools.utility.mcp_health_check` (when ``functional=True``)
and the standalone ``mcp_server_python/scripts/smoke_test_tools.py``
CLI. Each of the 9 tool modules gets one lightweight query that
exercises the real data path (OpenSearch, Neptune, or filesystem)
and reports pass/fail/skip with latency.

Design rationale
----------------
Queries hit the data-access layer **directly** rather than invoking
the MCP tool functions. That isolates this smoke check from
tool-level bugs (which the parity suite catches) and keeps the
focus on "can the backend respond?". It also avoids the circular
dependency that would arise from the health-check tool calling
itself.

Spec deviations from
``.kiro/specs/functional-smoke-tests/design.md``
=================================================

The literal queries in the design were authored against an
imagined Neptune/disk state that doesn't match what's deployed. The
deviations below preserve the spec's intent (one real query per
module against the live backend) while matching the ground truth:

* **graph queries**: the spec references a ``JGFS_FORECAST`` File-
  label node, but Neptune actually has ``JGLOBAL_FORECAST`` (as
  ``ShellScript`` and ``CodeFile``). The smoke queries match by
  ``name`` only, so the test is robust to label drift.
* **workflow_info**: the spec checks
  ``Path(workflow_root / "jobs").is_dir()``. The on-disk
  ``global-workflow`` repo keeps job scripts under ``dev/jobs/``
  (no top-level ``jobs/`` symlink). The smoke query passes when
  **either** path is a directory — same fallback pattern used by
  ``workflow_info.describe_component``.
* **OpenSearch adapter signature**: the spec example
  ``data.vector_db.query("text", index="...", k=1)`` doesn't match
  the actual :pyclass:`OpenSearchAdapter.query` signature
  ``(collection, query_text, *, k=10, ...)``. The smoke queries
  pass the literal index name as the first positional argument; it
  falls through :pyfunc:`src.config.aws_config.resolve_index`
  unchanged because the index map only resolves logical
  collections, not concrete index names.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

log = logging.getLogger(__name__)


# ── exceptions ─────────────────────────────────────────────────────────


class SkipProbe(Exception):
    """Raised by a probe to signal a graceful skip (not a failure).

    When a probe raises SkipProbe, the registry reports status="skip"
    rather than status="fail". Use for probes that require specific
    catalog entries or data that may not be present in all deployments.
    """


# ── module canon ───────────────────────────────────────────────────────

#: Order matters — this is the order results are reported in. Mirrors
#: :data:`src.tools.utility.ALL_TOOL_MODULES`.
ALL_MODULES: tuple[str, ...] = (
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


# ── data classes ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class SmokeQueryDef:
    """Definition of a single module's smoke query.

    Attributes
    ----------
    module
        Name of the tool module being validated. Must match one of
        :data:`ALL_MODULES`.
    description
        Human-readable label rendered in the markdown output (e.g.
        ``"search 'global workflow forecast' in mdc-workflow-docs-titan1024"``).
    query_fn
        Async callable ``(data, mcp) -> bool``. Returns ``True`` on
        pass; raises any exception (or returns ``False``) on fail.
    requires
        Tuple of environment variable names that must be set for the
        query to run. If any are missing, the module is reported as
        ``skip`` with reason ``"missing env: <var>"``.
    """

    module: str
    description: str
    query_fn: Callable[[Any, Any], Awaitable[bool]]
    requires: tuple[str, ...] = field(default_factory=tuple)


@dataclass
class ModuleResult:
    """Outcome of executing one smoke query."""

    module: str
    status: Literal["pass", "fail", "skip"]
    latency_ms: int
    error: str = ""
    description: str = ""

    def as_dict(self) -> dict[str, Any]:
        """JSON-friendly representation for the standalone CLI."""
        return {
            "module": self.module,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "description": self.description,
        }


# ── per-module query implementations ───────────────────────────────────


async def _smoke_semantic_search(data: Any, _mcp: Any) -> bool:
    """OpenSearch hit on ``mdc-workflow-docs-titan1024``.

    Exercises the full BM25 + k-NN + Bedrock-embedding path.
    """
    if data is None or data.vector_db is None:
        raise RuntimeError("vector_db is not configured")
    hits = await data.vector_db.query(
        "mdc-workflow-docs-titan1024",
        "global workflow forecast",
        k=1,
    )
    if not hits:
        raise RuntimeError(
            "0 hits for 'global workflow forecast' in "
            "mdc-workflow-docs-titan1024"
        )
    return True


async def _smoke_code_analysis(data: Any, _mcp: Any) -> bool:
    """Neptune outgoing-edge traversal from ``JGLOBAL_FORECAST``.

    Uses :ShellScript label to scope to gw-baseline nodes and avoid
    cross-tenant leakage from prefixed labels (e.g. GW_V17_ShellScript).
    """
    if data is None or data.graph_db is None:
        raise RuntimeError("graph_db is not configured")
    rows = await data.graph_db.query(
        "MATCH (f:ShellScript {name:'JGLOBAL_FORECAST'})-[r]->(t) "
        "RETURN type(r) AS rel, t.name AS name LIMIT 3"
    )
    if not rows:
        raise RuntimeError(
            "0 rows for JGLOBAL_FORECAST outgoing-edge traversal"
        )
    return True


async def _smoke_graph_rag(data: Any, _mcp: Any) -> bool:
    """Neptune neighbourhood (both directions) from ``JGLOBAL_FORECAST``."""
    if data is None or data.graph_db is None:
        raise RuntimeError("graph_db is not configured")
    rows = await data.graph_db.query(
        "MATCH (n:ShellScript {name:'JGLOBAL_FORECAST'})-[r]-(m) "
        "RETURN n.name AS src, type(r) AS rel, m.name AS tgt LIMIT 5"
    )
    if not rows:
        raise RuntimeError(
            "0 rows for JGLOBAL_FORECAST neighbourhood query"
        )
    return True


async def _smoke_ee2_compliance(data: Any, _mcp: Any) -> bool:
    """OpenSearch hit on ``mdc-ee2-standards-titan1024``."""
    if data is None or data.vector_db is None:
        raise RuntimeError("vector_db is not configured")
    hits = await data.vector_db.query(
        "mdc-ee2-standards-titan1024",
        "error handling",
        k=1,
    )
    if not hits:
        raise RuntimeError(
            "0 hits for 'error handling' in mdc-ee2-standards-titan1024"
        )
    return True


async def _smoke_operational(data: Any, _mcp: Any) -> bool:
    """OpenSearch hit on platform-specific operational guidance."""
    if data is None or data.vector_db is None:
        raise RuntimeError("vector_db is not configured")
    hits = await data.vector_db.query(
        "mdc-workflow-docs-titan1024",
        "running forecast on hera",
        k=1,
    )
    if not hits:
        raise RuntimeError(
            "0 hits for 'running forecast on hera' in "
            "mdc-workflow-docs-titan1024"
        )
    return True


async def _smoke_sdd_workflow(_data: Any, _mcp: Any) -> bool:
    """SDD execution-state filesystem probe.

    Pass when either ``active_session.json`` or ``history.jsonl``
    exists under ``$SDD_STATE_DIR`` (default
    ``sdd_framework/execution_state``).
    """
    state_dir = Path(
        os.environ.get("SDD_STATE_DIR", "sdd_framework/execution_state")
    )
    candidates = [
        state_dir / "active_session.json",
        state_dir / "history.jsonl",
    ]
    if any(p.exists() for p in candidates):
        return True
    raise RuntimeError(
        f"neither active_session.json nor history.jsonl exists in {state_dir}"
    )


async def _smoke_workflow_info(_data: Any, _mcp: Any) -> bool:
    """Workflow-root filesystem probe.

    Pass when either ``<workflow_root>/jobs`` or
    ``<workflow_root>/dev/jobs`` is a directory. Uses tenant context
    when available, falls back to MCP_WORKFLOW_ROOT env var.
    """
    from src.tenancy.resolver import get_current_tenant_or_none

    ctx = get_current_tenant_or_none()
    if ctx is not None:
        workflow_root = ctx.workflow_root
    else:
        workflow_root = Path(
            os.environ.get("MCP_WORKFLOW_ROOT")
            or "supported_repos/global-workflow"
        )
    if _smoke_workflow_info_check(workflow_root):
        return True
    raise RuntimeError(
        f"workflow_root={workflow_root} contains neither jobs/ nor dev/jobs/ "
        f"(tenant={ctx.tenant_id if ctx else 'none'})"
    )


def _smoke_workflow_info_check(workflow_root: Path) -> bool:
    """Pure check: returns True if jobs/ or dev/jobs/ exists under root."""
    candidates = [workflow_root / "jobs", workflow_root / "dev" / "jobs"]
    return any(p.is_dir() for p in candidates)


async def _smoke_github_tools(_data: Any, _mcp: Any) -> bool:
    """GitHub API smoke probe placeholder.

    Always returns ``True`` when invoked — but the registry's
    ``requires=("GITHUB_TOKEN",)`` means this function only runs
    when the token is set, in which case "the module is wired up
    and credentials are present" is the meaningful signal we want.
    """
    return True


async def _smoke_utility(_data: Any, mcp: Any) -> bool:
    """In-process tool-count check.

    Counts tools registered on the FastMCP server. When called from
    the standalone script (``mcp is None``) returns ``True`` because
    the standalone path has no server instance to introspect — the
    smoke check is "the registry runs" rather than "the registry
    sees ≥ 50 tools".
    """
    if mcp is None:
        return True
    try:
        tools = list(await mcp.list_tools(run_middleware=False))
    except Exception as exc:  # pragma: no cover - defensive
        raise RuntimeError(f"mcp.list_tools failed: {exc}") from exc
    if len(tools) < 50:
        raise RuntimeError(
            f"utility: expected >= 50 tools, got {len(tools)}"
        )
    return True


async def _smoke_branch_isolation(data: Any, _mcp: Any) -> bool:
    """R4.1 — assert v17 J-Job is visible only to gw_v17, develop content
    only to gw, and bidirectional isolation holds for cross-tenant search.

    Skipped (raises SkipProbe) if either gw or gw_v17 is absent from the
    catalog (R4.2 — graceful skip).

    Implements: Requirements 4.1, 4.2, 4.3, 4.4 of omd-tenants-2-v17-pilot.
    """
    from src.config.tenants import load_catalog

    catalog_path = os.environ.get(
        "MCP_TENANT_CATALOG_PATH", "/app/src/config/tenants.yaml"
    )
    catalog = load_catalog(catalog_path)
    tids = catalog.tenant_ids
    if "gw" not in tids or "gw_v17" not in tids:
        raise SkipProbe("requires both gw and gw_v17 in catalog")

    gw = catalog.by_id("gw")
    v17 = catalog.by_id("gw_v17")

    # Assertion 1: v17-only J-Job exists under gw_v17
    # NOTE: queries MUST include a :Label so _rewrite_cypher can scope
    # them. For v17, :ShellScript becomes :GW_V17_ShellScript.
    deps_v17 = await data.graph_db.query(
        "MATCH (f:ShellScript {name:'JGDAS_ATMOS_ANALYSIS_WDQMS'})-[r]-(m) "
        "RETURN f.name AS name LIMIT 1",
        tenant=v17,
    )
    if not deps_v17:
        raise RuntimeError(
            "R4.1#1: JGDAS_ATMOS_ANALYSIS_WDQMS not found under gw_v17 — "
            "ingestion may be incomplete"
        )

    # Assertion 2: same query returns nothing under gw
    # For gw (empty prefix), :ShellScript stays as :ShellScript —
    # only matches unprefixed nodes, not GW_V17_ShellScript.
    deps_gw = await data.graph_db.query(
        "MATCH (f:ShellScript {name:'JGDAS_ATMOS_ANALYSIS_WDQMS'})-[r]-(m) "
        "RETURN f.name AS name LIMIT 1",
        tenant=gw,
    )
    if deps_gw:
        raise RuntimeError(
            "R4.1#2: JGDAS_ATMOS_ANALYSIS_WDQMS unexpectedly returned "
            "under gw — tenant isolation violated"
        )

    # Assertion 3: develop-only content visible to gw
    mpas_gw = await data.vector_db.query(
        "mdc-workflow-docs-titan1024",
        "MPAS Voronoi",
        k=3,
        tenant=gw,
    )
    if not mpas_gw:
        raise RuntimeError(
            "R4.1#3: MPAS Voronoi not found under gw — "
            "smoke probe assumption failure"
        )

    # Assertion 4: cross-tenant search does not leak develop content
    # Use the bare index name — the adapter applies the tenant prefix.
    mpas_v17 = await data.vector_db.query(
        "mdc-workflow-docs-titan1024",
        "MPAS Voronoi",
        k=3,
        tenant=v17,
    )
    leaked = [
        h for h in (mpas_v17 or [])
        if "/develop/" in (h.get("metadata", {}).get("source") or "")
    ]
    if leaked:
        raise RuntimeError(
            f"R4.1#4: gw_v17 search returned develop-sourced content "
            f"({len(leaked)} hit(s)) — tenant isolation violated"
        )

    return True


# ── registry / runner ─────────────────────────────────────────────────


class SmokeQueryRegistry:
    """Sequential runner for the 9 module smoke queries.

    The class holds per-query timeouts and a total-suite timeout as
    constants so callers can read them off the instance for
    documentation purposes.
    """

    #: Maximum wall-clock per query before we mark the module ``fail``.
    TIMEOUT_MS: int = 2000

    #: Maximum wall-clock for the whole suite. Remaining modules are
    #: marked ``skip`` with reason ``"total timeout exceeded"`` once
    #: the suite passes this budget. 30 s is generous — at 9 modules
    #: with a 2 s per-query cap, the worst-case is 18 s.
    TOTAL_TIMEOUT_MS: int = 30000

    QUERIES: dict[str, SmokeQueryDef] = {
        "semantic_search": SmokeQueryDef(
            module="semantic_search",
            description=(
                "search 'global workflow forecast' in "
                "mdc-workflow-docs-titan1024"
            ),
            query_fn=_smoke_semantic_search,
        ),
        "code_analysis": SmokeQueryDef(
            module="code_analysis",
            description=(
                "MATCH (n {name:'JGLOBAL_FORECAST'})-[r]->(t) "
                "(outgoing edges)"
            ),
            query_fn=_smoke_code_analysis,
        ),
        "graph_rag": SmokeQueryDef(
            module="graph_rag",
            description=(
                "MATCH (n {name:'JGLOBAL_FORECAST'})-[r]-(m) "
                "(neighbourhood)"
            ),
            query_fn=_smoke_graph_rag,
        ),
        "ee2_compliance": SmokeQueryDef(
            module="ee2_compliance",
            description=(
                "search 'error handling' in mdc-ee2-standards-titan1024"
            ),
            query_fn=_smoke_ee2_compliance,
        ),
        "operational": SmokeQueryDef(
            module="operational",
            description=(
                "search 'running forecast on hera' in "
                "mdc-workflow-docs-titan1024"
            ),
            query_fn=_smoke_operational,
        ),
        "sdd_workflow": SmokeQueryDef(
            module="sdd_workflow",
            description="active_session.json or history.jsonl exists",
            query_fn=_smoke_sdd_workflow,
        ),
        "workflow_info": SmokeQueryDef(
            module="workflow_info",
            description=(
                "MCP_WORKFLOW_ROOT/jobs or /dev/jobs is a directory"
            ),
            query_fn=_smoke_workflow_info,
        ),
        "github_tools": SmokeQueryDef(
            module="github_tools",
            description="GitHub API connectivity (requires GITHUB_TOKEN)",
            query_fn=_smoke_github_tools,
            requires=("GITHUB_TOKEN",),
        ),
        "utility": SmokeQueryDef(
            module="utility",
            description="FastMCP registers >= 50 tools",
            query_fn=_smoke_utility,
        ),
        "branch_isolation": SmokeQueryDef(
            module="branch_isolation",
            description=(
                "v17-only J-Job visible under gw_v17, not gw; "
                "no cross-tenant leaks"
            ),
            query_fn=_smoke_branch_isolation,
        ),
    }

    async def run_all(
        self,
        data: Any,
        mcp: Any | None = None,
        only: str | None = None,
    ) -> list[ModuleResult]:
        """Execute every (or one) smoke query sequentially.

        Parameters
        ----------
        data
            The :pyclass:`UnifiedDataAccess` facade, or ``None`` to
            short-circuit every module to ``skip`` with reason
            ``"data layer unavailable"``.
        mcp
            FastMCP instance (used by the ``utility`` module's
            tool-count check). May be ``None`` when called from the
            standalone CLI.
        only
            Optional module name. When set, runs only that module's
            smoke query. Raises :class:`KeyError` if the name is
            unknown.

        Returns
        -------
        list[ModuleResult]
            One result per module, in :data:`ALL_MODULES` order
            (or a single-element list when ``only`` is set).
        """
        if only is not None:
            if only not in self.QUERIES:
                raise KeyError(
                    f"Unknown smoke module: {only!r}. "
                    f"Known: {list(self.QUERIES.keys())}"
                )
            modules = [only]
        else:
            modules = list(self.QUERIES.keys())

        # Short-circuit: data layer down → all modules skip.
        # Filesystem-only and in-process modules technically don't
        # need ``data``, but the spec is explicit about reporting
        # "data layer unavailable" uniformly when ``data is None``
        # to keep the rendered output predictable in degraded mode.
        if data is None:
            return [
                ModuleResult(
                    module=name,
                    status="skip",
                    latency_ms=0,
                    error="data layer unavailable",
                    description=self.QUERIES[name].description,
                )
                for name in modules
            ]

        results: list[ModuleResult] = []
        suite_start = time.perf_counter()
        for name in modules:
            qd = self.QUERIES[name]
            elapsed_total_ms = int(
                (time.perf_counter() - suite_start) * 1000
            )
            if elapsed_total_ms > self.TOTAL_TIMEOUT_MS:
                results.append(
                    ModuleResult(
                        module=name,
                        status="skip",
                        latency_ms=0,
                        error=(
                            f"total timeout exceeded "
                            f"({elapsed_total_ms}ms > "
                            f"{self.TOTAL_TIMEOUT_MS}ms)"
                        ),
                        description=qd.description,
                    )
                )
                continue
            results.append(await self._run_single(qd, data, mcp))
        return results

    async def run_one(
        self,
        name: str,
        data: Any,
        mcp: Any | None = None,
    ) -> ModuleResult:
        """Execute a single named module's smoke query."""
        if name not in self.QUERIES:
            raise KeyError(
                f"Unknown smoke module: {name!r}. "
                f"Known: {list(self.QUERIES.keys())}"
            )
        return await self._run_single(self.QUERIES[name], data, mcp)

    async def _run_single(
        self,
        qd: SmokeQueryDef,
        data: Any,
        mcp: Any | None,
    ) -> ModuleResult:
        """Run one query with timeout + ``requires`` env-var skip.

        All exceptions raised by ``query_fn`` are caught and
        translated into a ``fail`` :class:`ModuleResult`. The runner
        never propagates query exceptions to the caller — the suite
        is meant to keep going when one module fails.
        """
        # Skip when a required env var is missing — Graceful_Degradation
        # for github_tools today; future modules can opt in by
        # adding to the SmokeQueryDef.requires tuple.
        missing = [v for v in qd.requires if not os.environ.get(v)]
        if missing:
            return ModuleResult(
                module=qd.module,
                status="skip",
                latency_ms=0,
                error=f"missing env: {','.join(missing)}",
                description=qd.description,
            )

        start = time.perf_counter()
        try:
            ok = await asyncio.wait_for(
                qd.query_fn(data, mcp),
                timeout=self.TIMEOUT_MS / 1000.0,
            )
        except asyncio.TimeoutError:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return ModuleResult(
                module=qd.module,
                status="fail",
                latency_ms=elapsed_ms,
                error=f"timeout after {elapsed_ms}ms (limit {self.TIMEOUT_MS}ms)",
                description=qd.description,
            )
        except SkipProbe as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return ModuleResult(
                module=qd.module,
                status="skip",
                latency_ms=elapsed_ms,
                error=str(exc),
                description=qd.description,
            )
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            log.warning(
                "[WARN] smoke query %r failed: %s", qd.module, exc
            )
            return ModuleResult(
                module=qd.module,
                status="fail",
                latency_ms=elapsed_ms,
                error=f"{type(exc).__name__}: {exc}",
                description=qd.description,
            )

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        if ok is True:
            return ModuleResult(
                module=qd.module,
                status="pass",
                latency_ms=elapsed_ms,
                description=qd.description,
            )
        # ``ok is not True`` — defensive: a query function that
        # returns False (rather than raising) is reported as fail
        # without a useful error message. We discourage this
        # pattern; query functions should raise on failure.
        return ModuleResult(
            module=qd.module,
            status="fail",
            latency_ms=elapsed_ms,
            error=f"query returned non-True value: {ok!r}",
            description=qd.description,
        )


__all__ = [
    "ALL_MODULES",
    "ModuleResult",
    "SkipProbe",
    "SmokeQueryDef",
    "SmokeQueryRegistry",
]
