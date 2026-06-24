"""Neo4j adapter implementing :class:`GraphDBProtocol`.

Wraps the asynchronous official ``neo4j`` Bolt client with the async query
interface expected by tool modules.

Implements requirements for local Neo4j support on Parallel Works VM, including
multi-tenant query rewriting.
"""

from __future__ import annotations

import asyncio
import logging
import re as _re
import time
from typing import Any

from neo4j import AsyncGraphDatabase
from src.data.protocols import GraphDBProtocol

log = logging.getLogger(__name__)


# ── tenant label rewrite helpers ────────────────────────────────────────

_LABEL_TOKEN_RE = _re.compile(r":([A-Za-z_][A-Za-z0-9_]*)")


def _strip_quoted(cypher: str) -> str:
    """Replace quoted string contents with spaces, preserving length.

    Handles single-quoted, double-quoted strings, and backslash escapes.
    The returned string has the same length as the input so that offsets
    found in the stripped version map directly to the original.
    """
    out = list(cypher)
    i = 0
    n = len(cypher)
    while i < n:
        ch = cypher[i]
        if ch in ('"', "'"):
            quote = ch
            out[i] = " "
            i += 1
            while i < n:
                c = cypher[i]
                if c == "\\" and i + 1 < n:
                    out[i] = " "
                    out[i + 1] = " "
                    i += 2
                elif c == quote:
                    out[i] = " "
                    i += 1
                    break
                else:
                    out[i] = " "
                    i += 1
        else:
            i += 1
    return "".join(out)


def _square_bracket_mask(cleaned: str) -> list[bool]:
    """Return a per-character mask where True means 'inside [ ... ]'.

    Relationship-type tokens (``[r:CALLS]``, ``[:USES|IMPORTS]``,
    ``[:CALLS*1..3]``) live inside square brackets. Node-label tokens
    (``(n:File)``) and bare label predicates (``WHERE n:File``) do not.
    The mask lets the rewriter skip relationship types.
    """
    mask = [False] * len(cleaned)
    depth = 0
    for i, ch in enumerate(cleaned):
        if ch == "[":
            depth += 1
            mask[i] = depth > 0
        elif ch == "]":
            mask[i] = depth > 0
            if depth > 0:
                depth -= 1
        else:
            mask[i] = depth > 0
    return mask


def _label_token_offsets(cleaned: str):
    """Yield (start, end, label) for every node-label :Label token."""
    mask = _square_bracket_mask(cleaned)
    for m in _LABEL_TOKEN_RE.finditer(cleaned):
        if mask[m.start()]:
            continue
        yield m.start(), m.end(), m.group(1)


# ── adapter ─────────────────────────────────────────────────────────────


class Neo4jAdapter(GraphDBProtocol):
    """Async Neo4j adapter using official Bolt driver.

    Parameters
    ----------
    uri
        Neo4j URI (e.g. ``bolt://localhost:7687``).
    password
        Neo4j auth password. Defaults to ``"gfsworkflow2025"``.
    user
        Neo4j auth username. Defaults to ``"neo4j"``.
    """

    HEALTH_CYPHER: str = "RETURN 1 AS ok"

    @staticmethod
    def resolve_tenant_labels(labels: list[str], tenant: Any) -> list[str]:
        """Prepend tenant.label_prefix to each label; passthrough on empty."""
        if not tenant or not getattr(tenant, "label_prefix", None):
            return list(labels)
        return [f"{tenant.label_prefix}{label}" for label in labels]

    def _rewrite_cypher(self, cypher: str, tenant: Any) -> str:
        """Rewrite :Label tokens to :<prefix>Label (R4.1, R4.3)."""
        if not tenant or not getattr(tenant, "label_prefix", None):
            return cypher
        cleaned = _strip_quoted(cypher)
        offsets = list(_label_token_offsets(cleaned))
        if not offsets:
            return cypher
        out: list[str] = []
        cursor = 0
        for start, end, label in offsets:
            out.append(cypher[cursor:start])
            out.append(f":{tenant.label_prefix}{label}")
            cursor = end
        out.append(cypher[cursor:])
        return "".join(out)

    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        password: str = "gfsworkflow2025",
        user: str = "neo4j",
    ):
        self._uri = uri
        self._user = user
        self._password = password
        self._driver: AsyncGraphDatabase.driver | None = None
        self._connected = False
        self._metrics: dict[str, Any] = {
            "queries_executed": 0,
            "queries_failed": 0,
            "last_query_ms": None,
        }

    # ── GraphDBProtocol ────────────────────────────────────────────────

    async def connect(self) -> None:
        """Eagerly build and verify the Bolt driver connection.

        Safe to call multiple times (idempotent).
        """
        if self._connected:
            return

        def _build() -> Any:
            return AsyncGraphDatabase.driver(
                self._uri,
                auth=(self._user, self._password),
            )

        self._driver = await asyncio.to_thread(_build)
        self._connected = True
        log.info("[OK] Neo4jAdapter connected: %s", self._uri)

    async def query(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        *,
        tenant: Any = None,
        timeout: float | None = None,
    ) -> list[dict[str, Any]]:
        """Execute Cypher query and return result rows as plain dict lists."""
        if not cypher:
            raise ValueError("cypher must be non-empty")
        if not self._connected:
            await self.connect()

        # Apply multi-tenant label prefixing to query nodes
        if tenant is not None and getattr(tenant, "label_prefix", None):
            cypher = self._rewrite_cypher(cypher, tenant)

        params = params or {}
        started = time.perf_counter()

        # Session-based transaction wrapper
        async def _run() -> list[dict[str, Any]]:
            assert self._driver is not None
            async with self._driver.session() as session:
                result = await session.run(cypher, params)
                records = await result.data()
                return records

        try:
            if timeout is not None:
                rows = await asyncio.wait_for(_run(), timeout=timeout)
            else:
                rows = await _run()

            self._metrics["queries_executed"] += 1
            self._metrics["last_query_ms"] = round(
                (time.perf_counter() - started) * 1000, 2
            )
            return rows
        except asyncio.TimeoutError as exc:
            self._metrics["queries_failed"] += 1
            log.error("[ERROR] Neo4j query timed out after %s seconds", timeout)
            raise TimeoutError(f"Neo4j query timed out after {timeout} seconds") from exc
        except Exception as exc:
            self._metrics["queries_failed"] += 1
            log.error("[ERROR] Neo4j query failed: %s", exc)
            raise ValueError(f"Neo4j query failed: {exc}") from exc

    async def health_check(self) -> dict[str, Any]:
        """Probe the Neo4j endpoint with ``RETURN 1 AS ok``."""
        if not self._connected:
            try:
                await self.connect()
            except Exception as exc:
                return {
                    "status": "unhealthy",
                    "connected": False,
                    "uri": self._uri,
                    "error": str(exc),
                }

        base: dict[str, Any] = {
            "status": "healthy",
            "connected": self._connected,
            "uri": self._uri,
            "metrics": dict(self._metrics),
        }
        try:
            rows = await self.query(self.HEALTH_CYPHER)
            if rows and rows[0].get("ok") in (1, "1", True):
                return base
            base["status"] = "degraded"
            base["reason"] = "health probe returned unexpected payload"
            return base
        except Exception as exc:
            base["status"] = "unhealthy"
            base["error"] = str(exc)
            return base

    async def close(self) -> None:
        """Close the active database driver connection."""
        driver = self._driver
        self._driver = None
        self._connected = False
        if driver is not None:
            await driver.close()

    # ── statistics — used by HealthChecker / framework_status ──────────

    async def get_statistics(self) -> dict[str, Any]:
        """Return counts that mirror the Node.js ``getStatistics`` shape.

        Separate openCypher queries per node label keep individual
        responses small. Failures degrade gracefully — a missing label
        contributes 0 rather than failing the whole call.
        """
        if not self._connected:
            await self.connect()

        labels = ("File", "Function", "Class", "Module")
        counts: dict[str, int] = {}
        for label in labels:
            try:
                rows = await self.query(
                    f"MATCH (n:{label}) RETURN count(n) AS c"
                )
                counts[label] = (
                    int(rows[0].get("c", 0)) if rows else 0
                )
            except Exception as exc:
                log.warning(
                    "[WARN] Neo4jAdapter.get_statistics(%s): %s",
                    label,
                    exc,
                )
                counts[label] = 0

        try:
            rel_rows = await self.query("MATCH ()-[r]->() RETURN count(r) AS c")
            relationships = (
                int(rel_rows[0].get("c", 0)) if rel_rows else 0
            )
        except Exception as exc:
            log.warning("[WARN] Neo4jAdapter.get_statistics(rels): %s", exc)
            relationships = 0

        nodes = sum(counts.values())
        return {
            "nodes": nodes,
            "relationships": relationships,
            "fileCount": counts.get("File", 0),
            "functionCount": counts.get("Function", 0),
            "classCount": counts.get("Class", 0),
            "moduleCount": counts.get("Module", 0),
        }
