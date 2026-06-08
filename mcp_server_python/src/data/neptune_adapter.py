"""Neptune adapter implementing :class:`GraphDBProtocol`.

Wraps :pyclass:`src.data.aws_backend.NeptuneHTTPAdapter` (vendored from
``mcp_server_node/scripts/aws_backend.py``) with the async query
interface expected by tool modules.

Implements Requirements 3.1 – 3.7:

* SigV4 authenticated openCypher access to Amazon Neptune via
  HTTP POST (R3.1, R3.2).
* JSON parameter serialization in the POST body
  (R3.2, R3.3).
* Result rows returned as plain ``dict``\\ s — keys match the query's
  ``RETURN`` aliases (R3.3, Property 6).
* Session-based execution with implicit close-on-exit
  (R3.4 — handled internally; the protocol's ``query()`` is always
  short-lived).
* Exponential-backoff retry (1s → 2s → 4s, max 3 retries) on HTTP
  429 / 500 / 503 — implemented by the underlying ``NeptuneSession``
  (R3.5, R3.6).
* Network / connection errors surface as :pyexc:`NeptuneAdapterError`
  with the original ``aws_backend`` exception attached so tool
  handlers can emit structured MCP errors (R3.7).

The vendored ``NeptuneHTTPAdapter`` is synchronous (urllib3-backed).
This adapter runs each call in a worker thread via
:pyfunc:`asyncio.to_thread` so it stays non-blocking when awaited
from FastMCP handlers — exactly the same pattern the
:pyclass:`~src.data.opensearch_adapter.OpenSearchAdapter` uses.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.config.aws_config import DEFAULT_AWS_REGION

log = logging.getLogger(__name__)


class NeptuneAdapterError(RuntimeError):
    """Raised when a Neptune call ultimately fails after retries.

    Mirrors the Node.js ``NeptuneAdapter`` error envelope. ``status``
    holds the last HTTP status observed (or ``None`` for network
    errors); ``cause`` is the original ``aws_backend`` exception so
    callers can re-classify if needed.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        cause: BaseException | None = None,
    ):
        super().__init__(message)
        self.status = status
        self.cause = cause


# ── tenant label rewrite helpers (R4.1-R4.4) ────────────────────────────

import re as _re

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
    The mask lets the rewriter skip relationship types — Neptune only
    prefixes node labels, never relationship types.
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
    """Yield (start, end, label) for every node-label :Label token.

    ``cleaned`` is the output of ``_strip_quoted`` — quoted regions are
    spaces so regex matches only structural tokens. Tokens that fall
    inside square brackets are relationship types and are skipped, so
    only node labels are surfaced to the rewriter.
    """
    mask = _square_bracket_mask(cleaned)
    for m in _LABEL_TOKEN_RE.finditer(cleaned):
        # The ':' is at m.start(); the label name follows. If the ':'
        # is inside square brackets it's a relationship type — skip.
        if mask[m.start()]:
            continue
        yield m.start(), m.end(), m.group(1)


# ── adapter ─────────────────────────────────────────────────────────────


class NeptuneAdapter:
    """Async adapter for Amazon Neptune (HTTP openCypher + SigV4).

    Parameters
    ----------
    endpoint
        Neptune endpoint. Any of ``hostname``, ``wss://...``,
        ``bolt+s://...``, or ``https://...`` is accepted —
        :pyclass:`NeptuneHTTPAdapter` normalises to the openCypher
        HTTPS URL internally.
    region
        AWS region for SigV4 signing. Defaults to
        :data:`DEFAULT_AWS_REGION`.

    Notes
    -----
    The vendored ``NeptuneHTTPAdapter`` already handles SigV4 signing,
    credential rotation per-request, and exponential-backoff retry.
    This async wrapper adds:

    * Idempotent ``connect()`` / ``close()`` matching the protocol.
    * Result conversion from the raw Neptune JSON shape (each row is
      ``{"<RETURN alias>": value, ...}`` already — no transformation
      needed beyond ``dict()`` copy for safety).
    * ``health_check()`` that issues a cheap ``RETURN 1 AS ok``.
    """

    # ── tenant scoping (R4.1-R4.4) ────────────────────────────────────

    @staticmethod
    def resolve_tenant_labels(labels: list[str], tenant: "Any") -> list[str]:
        """Prepend tenant.label_prefix to each label; passthrough on empty (R4.4)."""
        if not tenant.label_prefix:
            return list(labels)
        return [f"{tenant.label_prefix}{label}" for label in labels]

    def _rewrite_cypher(self, cypher: str, tenant: "Any") -> str:
        """Rewrite :Label tokens to :<prefix>Label (R4.1, R4.3).

        Empty prefix returns input verbatim. Quoted strings are never modified.
        """
        if not tenant.label_prefix:
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

    # ── class constants ────────────────────────────────────────────────

    #: Cypher used by ``health_check`` and the lazy ``connect``
    #: verification probe. Cheap (no graph traversal).
    HEALTH_CYPHER: str = "RETURN 1 AS ok"

    def __init__(
        self,
        endpoint: str,
        *,
        region: str = DEFAULT_AWS_REGION,
    ):
        if not endpoint:
            raise ValueError(
                "NeptuneAdapter: endpoint is required "
                "(set NEPTUNE_ENDPOINT or pass `endpoint=`)"
            )
        self._endpoint = endpoint
        self._region = region
        self._driver: Any = None
        self._connected = False
        self._metrics: dict[str, Any] = {
            "queries_executed": 0,
            "queries_failed": 0,
            "last_query_ms": None,
        }

    # ── GraphDBProtocol ────────────────────────────────────────────────

    async def connect(self) -> None:
        """Lazily build the underlying ``NeptuneHTTPAdapter`` driver.

        Safe to call multiple times (R3.1 idempotence). The vendored
        adapter's constructor itself doesn't open a network
        connection (urllib3 ``PoolManager`` is created eagerly but
        connections are made lazily on first request), so this is
        cheap.
        """
        if self._connected:
            return
        # Late import so test suites can stub the underlying driver
        # without pulling in boto3 / urllib3 at module load time.
        from src.data.aws_backend import NeptuneHTTPAdapter

        def _build() -> Any:
            return NeptuneHTTPAdapter(self._endpoint, self._region)

        self._driver = await asyncio.to_thread(_build)
        self._connected = True
        log.info("[OK] NeptuneAdapter connected: %s", self._endpoint)

    async def query(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        *,
        tenant: Any = None,
    ) -> list[dict[str, Any]]:
        """Execute an openCypher query and return rows as plain dicts.

        Each row is a copy of the Neptune JSON record so callers can
        mutate the returned list freely without affecting future
        results.
        """
        if not cypher:
            raise ValueError("cypher must be non-empty")
        if not self._connected:
            await self.connect()

        if tenant is not None and tenant.label_prefix:
            cypher = self._rewrite_cypher(cypher, tenant)

        params = params or {}
        rows = await asyncio.to_thread(self._run_session, cypher, params)
        return rows

    async def health_check(self) -> dict[str, Any]:
        """Probe the Neptune endpoint with ``RETURN 1 AS ok``.

        Returns ``{"status": "healthy"|"degraded"|"unhealthy", ...}``
        per the protocol contract. ``status="healthy"`` only when the
        probe round-trips cleanly.
        """
        if not self._connected:
            try:
                await self.connect()
            except Exception as exc:  # pragma: no cover - defensive
                return {
                    "status": "unhealthy",
                    "connected": False,
                    "endpoint": self._endpoint,
                    "error": str(exc),
                }

        base: dict[str, Any] = {
            "status": "healthy",
            "connected": self._connected,
            "endpoint": self._endpoint,
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
            self._metrics["queries_failed"] += 1
            return base

    async def close(self) -> None:
        """Release the underlying ``urllib3.PoolManager``.

        Idempotent — safe to call when ``connect()`` was never invoked.
        """
        driver = self._driver
        self._driver = None
        self._connected = False
        if driver is None:
            return
        try:
            close = getattr(driver, "close", None)
            if callable(close):
                await asyncio.to_thread(close)
        except Exception as exc:
            log.warning("[WARN] NeptuneAdapter.close: %s", exc)

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
                    "[WARN] NeptuneAdapter.get_statistics(%s): %s",
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
            log.warning("[WARN] NeptuneAdapter.get_statistics(rels): %s", exc)
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

    # ── internals ──────────────────────────────────────────────────────

    def _run_session(
        self, cypher: str, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Run ``cypher`` in a fresh ``NeptuneSession`` (sync).

        Exists as a separate method so :pyfunc:`asyncio.to_thread` has
        a clean target. Translates any ``aws_backend`` exception into
        :pyexc:`NeptuneAdapterError` so callers see one consistent
        type from the adapter surface.
        """
        # Late import — keeps the exception types out of the protocol
        # module's import graph.
        from src.data.aws_backend import (
            NeptuneConnectionError,
            NeptuneQueryError,
        )

        import time as _time

        started = _time.perf_counter()
        try:
            with self._driver.session() as session:
                # NeptuneSession.run takes **kwargs for params — splat
                # the dict so it lines up with the Node.js
                # ``run(cypher, params)`` shape.
                result = session.run(cypher, **params)
                rows = [dict(record) for record in result]
        except NeptuneQueryError as exc:
            self._metrics["queries_failed"] += 1
            raise NeptuneAdapterError(
                str(exc),
                status=getattr(exc, "status_code", None),
                cause=exc,
            ) from exc
        except NeptuneConnectionError as exc:
            self._metrics["queries_failed"] += 1
            raise NeptuneAdapterError(
                f"Neptune connection error: {exc}",
                status=None,
                cause=exc,
            ) from exc
        except Exception as exc:
            # Anything we didn't anticipate (e.g. JSON decode in a
            # non-NeptuneQueryError path). Surface as adapter error so
            # tool layer doesn't have to know about the underlying
            # client.
            self._metrics["queries_failed"] += 1
            raise NeptuneAdapterError(
                f"Neptune query failed: {exc}",
                status=None,
                cause=exc,
            ) from exc
        else:
            self._metrics["queries_executed"] += 1
            self._metrics["last_query_ms"] = round(
                (_time.perf_counter() - started) * 1000, 2
            )
            return rows


__all__ = ["NeptuneAdapter", "NeptuneAdapterError"]
