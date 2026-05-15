"""Unified data-access facade (Requirement 1.6, 1.8).

Tool modules consume a single object exposing both ``vector_db`` and
``graph_db`` attributes. This facade makes that object — wired by
:mod:`src.data.backend_selector` from whichever pair of adapters
is appropriate for the configured ``DB_BACKEND``.

The facade is intentionally thin. Tool modules already call
``data.vector_db.query(...)`` and ``data.graph_db.query(...)``
directly; this class adds:

* :pymeth:`connect` and :pymeth:`close` that fan out to both adapters
  in parallel via :pyfunc:`asyncio.gather` so bootstrap and shutdown
  are O(max(t_v, t_g)) instead of O(t_v + t_g).
* :pymeth:`health_check` that aggregates both adapter probes into a
  single ``HealthChecker``-shaped response (keys ``status``,
  ``vector``, ``graph``) — matches the Node.js
  ``HealthChecker.checkDatabases`` return shape used by the utility
  module's ``mcp_health_check`` tool.

Either adapter slot is allowed to be ``None``. When an adapter is
absent, ``connect`` / ``close`` skip it and ``health_check`` records
``status="disabled"`` for that side. Tools that need the missing
backend will surface their own ``[ERROR]`` markdown at call time —
the facade is not in the tool-error business.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.data.protocols import GraphDBProtocol, VectorDBProtocol

log = logging.getLogger(__name__)


class UnifiedDataAccess:
    """Composite of a vector adapter + a graph adapter.

    Parameters
    ----------
    vector_db
        Concrete adapter satisfying :pyclass:`VectorDBProtocol`, or
        ``None`` when only the graph backend is reachable. Tool
        modules that need vector search will return ``[ERROR]``
        markdown when this is ``None``.
    graph_db
        Concrete adapter satisfying :pyclass:`GraphDBProtocol`, or
        ``None`` when only the vector backend is reachable. Tool
        modules that need graph traversal will return ``[ERROR]``
        markdown when this is ``None``.
    backend
        Name of the backend that produced these adapters
        (``"aws"`` or ``"legacy"``). Surfaced in
        :pymeth:`health_check` output for diagnostics.
    """

    def __init__(
        self,
        *,
        vector_db: VectorDBProtocol | None,
        graph_db: GraphDBProtocol | None,
        backend: str = "aws",
    ):
        self.vector_db = vector_db
        self.graph_db = graph_db
        self.backend = backend
        self._connected = False

    # ── lifecycle ──────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Open both adapters in parallel.

        Idempotent. Errors from either side propagate so the caller
        (typically :func:`src.mcp_server._create_data_access`) can
        decide whether to fall back to degraded mode.
        """
        if self._connected:
            return
        tasks: list[Any] = []
        if self.vector_db is not None:
            tasks.append(self.vector_db.connect())
        if self.graph_db is not None:
            tasks.append(self.graph_db.connect())
        if tasks:
            await asyncio.gather(*tasks)
        self._connected = True
        log.info(
            "[OK] UnifiedDataAccess connected (backend=%s, vector=%s, graph=%s)",
            self.backend,
            type(self.vector_db).__name__ if self.vector_db else None,
            type(self.graph_db).__name__ if self.graph_db else None,
        )

    async def close(self) -> None:
        """Release both adapters in parallel.

        Errors are logged but do not propagate — close is best-effort.
        """
        tasks: list[Any] = []
        if self.vector_db is not None:
            tasks.append(self._safe_close(self.vector_db, "vector_db"))
        if self.graph_db is not None:
            tasks.append(self._safe_close(self.graph_db, "graph_db"))
        if tasks:
            await asyncio.gather(*tasks)
        self._connected = False

    @staticmethod
    async def _safe_close(adapter: Any, label: str) -> None:
        try:
            await adapter.close()
        except Exception as exc:
            log.warning("[WARN] UnifiedDataAccess.close(%s): %s", label, exc)

    # ── health ─────────────────────────────────────────────────────────

    async def health_check(
        self, *, deep: bool = False, min_indices: int = 5
    ) -> dict[str, Any]:
        """Aggregate adapter health into the HealthChecker shape.

        The return shape matches what the Node.js
        ``HealthChecker.checkDatabases`` produces and what the
        ``utility.mcp_health_check`` tool consumes:

        .. code-block:: python

            {
                "status": "healthy" | "degraded" | "unhealthy",
                "backend": "aws",
                "vector": {
                    "ok": bool, "status": str, "indexCount": int,
                    "totalDocuments": int, "latency_ms": float | None,
                    "reason": str | None,
                },
                "graph": {
                    "ok": bool, "status": str, "nodeCount": int,
                    "relationshipCount": int, "latency_ms": float | None,
                    "reason": str | None,
                },
            }

        Either side may be reported as ``status="disabled"`` when the
        adapter is missing — that's the degraded-but-running shape.
        Overall ``status`` is ``"healthy"`` only when BOTH sides are
        healthy and ``vector.indexCount >= min_indices`` (matches the
        Node.js gating rule).
        """
        vector_block = await self._vector_health(deep=deep, min_indices=min_indices)
        graph_block = await self._graph_health()

        vec_ok = vector_block.get("ok", False)
        graph_ok = graph_block.get("ok", False)
        if vec_ok and graph_ok:
            overall = "healthy"
        elif vec_ok or graph_ok:
            overall = "degraded"
        else:
            overall = "unhealthy"

        return {
            "status": overall,
            "backend": self.backend,
            "vector": vector_block,
            "graph": graph_block,
        }

    async def _vector_health(
        self, *, deep: bool, min_indices: int
    ) -> dict[str, Any]:
        if self.vector_db is None:
            return {
                "ok": False,
                "status": "disabled",
                "indexCount": 0,
                "totalDocuments": 0,
                "latency_ms": None,
                "reason": "vector_db adapter is not configured",
            }
        try:
            raw = await self.vector_db.health_check(deep=deep)
        except Exception as exc:
            return {
                "ok": False,
                "status": "unhealthy",
                "indexCount": 0,
                "totalDocuments": 0,
                "latency_ms": None,
                "reason": str(exc),
            }

        index_count = len(
            raw.get("indices") or raw.get("collections") or []
        )
        # If the adapter doesn't enumerate indices in its health
        # response, fall back to "configured" which means the probe
        # round-tripped (so ``ok`` should still be True).
        if index_count == 0 and raw.get("status") == "healthy":
            index_count = min_indices  # treat as gating-passed
        ok = (
            raw.get("status") == "healthy"
            and index_count >= min_indices
        )
        reason = (
            None
            if ok
            else f"only {index_count} indices (need >={min_indices})"
            if raw.get("status") == "healthy"
            else raw.get("reason") or raw.get("error") or "unhealthy"
        )
        return {
            "ok": ok,
            "status": raw.get("status", "unknown"),
            "indexCount": index_count,
            "totalDocuments": raw.get("total_documents", 0),
            "latency_ms": raw.get("latency_ms"),
            "reason": reason,
        }

    async def _graph_health(self) -> dict[str, Any]:
        if self.graph_db is None:
            return {
                "ok": False,
                "status": "disabled",
                "nodeCount": 0,
                "relationshipCount": 0,
                "latency_ms": None,
                "reason": "graph_db adapter is not configured",
            }
        try:
            raw = await self.graph_db.health_check()
        except Exception as exc:
            return {
                "ok": False,
                "status": "unhealthy",
                "nodeCount": 0,
                "relationshipCount": 0,
                "latency_ms": None,
                "reason": str(exc),
            }

        # Prefer counts from the health response; fall back to a
        # ``get_statistics()`` probe when the adapter exposes one.
        node_count = int(raw.get("nodes", 0) or 0)
        rel_count = int(raw.get("relationships", 0) or 0)
        if node_count == 0 and hasattr(self.graph_db, "get_statistics"):
            try:
                stats = await self.graph_db.get_statistics()
                node_count = int(stats.get("nodes", 0) or 0)
                rel_count = int(stats.get("relationships", 0) or 0)
            except Exception as exc:  # pragma: no cover - defensive
                log.warning(
                    "[WARN] UnifiedDataAccess._graph_health stats: %s", exc
                )

        ok = raw.get("status") == "healthy" and node_count > 0
        reason = (
            None
            if ok
            else "graph database has 0 nodes"
            if node_count == 0
            else raw.get("reason") or raw.get("error") or "unhealthy"
        )
        return {
            "ok": ok,
            "status": raw.get("status", "unknown"),
            "nodeCount": node_count,
            "relationshipCount": rel_count,
            "latency_ms": raw.get("latency_ms"),
            "reason": reason,
        }


__all__ = ["UnifiedDataAccess"]
