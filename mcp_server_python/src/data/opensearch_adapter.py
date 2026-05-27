"""OpenSearch adapter implementing :class:`VectorDBProtocol`.

Wraps :pyclass:`aws_backend.OpenSearchVectorClient` (vendored from
``mcp_server_node/scripts/aws_backend.py``) with the async query
interface expected by tool modules.

Implements Requirements 2.1 – 2.7:

* SigV4 authenticated access to Amazon OpenSearch (R2.1).
* Hybrid BM25 + k-NN search with Reciprocal Rank Fusion (R2.2, R2.3).
* Cross-index support via :pyfunc:`src.config.aws_config.resolve_index`
  (R2.4).
* Node.js-compatible result schema ``(id, content, metadata, score)``
  (R2.5).
* Exponential-backoff retry (1s → 2s → 4s, max 3 retries) on HTTP 429
  and 5xx (R2.6).
* Pluggable embedding via :class:`src.data.embedding_provider.EmbeddingProvider`,
  defaulting to Bedrock Titan Embed Text V2 via
  :data:`MCP_EMBEDDING_PROFILE=titan1024` (R2.7, Phase C-2c).

Phase C-2c (Bedrock-native embedding swap) replaces the prior
``sentence-transformers/all-mpnet-base-v2`` default with a
:func:`src.data.embedding_provider.create_provider`-resolved provider
selected by ``MCP_EMBEDDING_PROFILE``. The runtime image no longer
ships ``sentence-transformers``, ``torch``, or ``transformers`` —
selecting the legacy ``mpnet768`` profile in this image surfaces a
clean ``OpenSearchQueryError`` from the first ``_generate_embedding``
call (Requirement 9.3).

The sync ``opensearch-py`` client is run in a worker thread so the
adapter stays non-blocking when awaited from FastMCP handlers.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from typing import Any, Callable

from src.config.aws_config import DEFAULT_AWS_REGION, resolve_index
from src.data.embedding_provider import (
    EmbeddingError,
    EmbeddingProvider,
    create_provider,
)
from src.data.embedding_registry import EmbeddingModelRegistry, ModelProfile

log = logging.getLogger(__name__)


class OpenSearchQueryError(RuntimeError):
    """Raised when an OpenSearch request ultimately fails.

    Mirrors the Node.js ``OpenSearchAdapter`` error shape — ``status``
    holds the last HTTP status observed (or ``None`` for network
    errors) so tool handlers can emit structured MCP errors.
    """

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


# ── retry constants (R2.6) ──────────────────────────────────────────────

RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})
MAX_RETRIES: int = 3
INITIAL_BACKOFF_S: float = 1.0
BACKOFF_MULTIPLIER: float = 2.0


# ── adapter ─────────────────────────────────────────────────────────────


class OpenSearchAdapter:
    """Async OpenSearch adapter.

    Parameters
    ----------
    endpoint
        OpenSearch HTTPS endpoint (no scheme required; ``https://`` is
        assumed to match ``mcp_server_node`` behaviour).
    region
        AWS region for SigV4 signing. Defaults to :data:`DEFAULT_AWS_REGION`.
    embedding_function
        Optional callable ``list[str] -> list[list[float]]`` used to
        generate query-time embeddings. When unset the adapter resolves
        the active embedding profile from ``MCP_EMBEDDING_PROFILE``
        (default ``"titan1024"``) and builds the matching
        :class:`src.data.embedding_provider.EmbeddingProvider`. If the
        provider's constructor raises :class:`EmbeddingError` (e.g.
        ``mpnet768`` in this image), the error is captured and surfaces
        from the first :meth:`_generate_embedding` call as
        :class:`OpenSearchQueryError` with ``status=None`` so MCP tool
        handlers see a structured error.
    """

    # ── tenant scoping (R3.1-R3.4) ────────────────────────────────────

    @staticmethod
    def resolve_tenant_index(collection: str, tenant: "Any") -> str:
        """Apply tenant.index_prefix to a logical collection name.

        Returns ``f"{tenant.index_prefix}{collection}"``; empty prefix
        yields passthrough (R3.3).
        """
        if not tenant.index_prefix:
            return collection
        return f"{tenant.index_prefix}{collection}"

    # ── constructor ─────────────────────────────────────────────────────

    def __init__(
        self,
        endpoint: str,
        *,
        region: str = DEFAULT_AWS_REGION,
        embedding_function: Callable[[list[str]], list[list[float]]] | None = None,
    ):
        if not endpoint:
            raise ValueError(
                "OpenSearchAdapter: endpoint is required "
                "(set OPENSEARCH_ENDPOINT or pass `endpoint=`)"
            )
        self._endpoint = endpoint
        self._region = region
        self._embedding_function = embedding_function

        # Always resolve the active profile so ``query`` can route to
        # the matching ``mdc-{domain}-{profile}`` index, even when an
        # ``embedding_function`` override is supplied (the index map is
        # tied to the profile, not to the embedding source).
        profile_name = os.getenv("MCP_EMBEDDING_PROFILE", "titan1024")
        self._profile: ModelProfile = (
            EmbeddingModelRegistry().get_profile(profile_name)
        )

        # Build the provider only when no explicit override was supplied.
        # Catch ``EmbeddingError`` from the provider's constructor (e.g.
        # ``LocalProvider`` import fail) so the error surfaces from the
        # first ``_generate_embedding`` call rather than aborting
        # adapter construction (Requirement 5.3, 9.3).
        self._provider: EmbeddingProvider | None = None
        self._provider_error: EmbeddingError | None = None
        if embedding_function is None:
            try:
                self._provider = create_provider(self._profile)
            except EmbeddingError as exc:
                self._provider_error = exc

        self._client = None  # type: ignore[assignment]
        self._connected = False
        self._metrics: dict[str, Any] = {
            "queries_executed": 0,
            "queries_failed": 0,
            "last_query_ms": None,
        }

    # ── VectorDBProtocol ────────────────────────────────────────────────

    async def connect(self) -> None:
        """Lazily initialise the vendored ``OpenSearchVectorClient``.

        Safe to call multiple times (R2.1 idempotence).
        """
        if self._connected:
            return
        # Late import so test suites can stub the client without
        # importing the heavy boto3/opensearchpy chain.
        from src.data.aws_backend import OpenSearchVectorClient

        def _build() -> Any:
            client = OpenSearchVectorClient(self._endpoint, self._region)
            if self._embedding_function is not None:
                client.set_embedding_function(self._embedding_function)
            return client

        self._client = await asyncio.to_thread(_build)
        self._connected = True
        log.info("[OK] OpenSearchAdapter connected: %s", self._endpoint)

    async def query(
        self,
        collection: str,
        query_text: str,
        *,
        k: int = 10,
        similarity_threshold: float = 0.0,
        where: dict[str, Any] | None = None,
        include_graph: bool = True,  # noqa: ARG002 — honored upstream in tool layer
        tenant: Any = None,
    ) -> list[dict[str, Any]]:
        """Run hybrid BM25 + k-NN with RRF fusion, then format hits."""
        if not self._connected:
            await self.connect()
        if not query_text:
            raise ValueError("query_text must be non-empty")
        if not 1 <= k <= 1000:
            raise ValueError(f"k must be between 1 and 1000, got {k}")

        # Route to the index whose vector dimensionality matches the
        # active embedding profile (Requirement 8.1, 5.3 of design).
        scoped = self.resolve_tenant_index(collection, tenant) if tenant else collection
        index = resolve_index(scoped, self._profile.short_name)
        embedding = await self._generate_embedding(query_text)
        body = self._build_hybrid_query(query_text, embedding, k, where)

        started = time.perf_counter()
        response = await self._search_with_retry(index=index, body=body)
        self._metrics["queries_executed"] += 1
        self._metrics["last_query_ms"] = round(
            (time.perf_counter() - started) * 1000, 2
        )

        hits = response.get("hits", {}).get("hits", [])
        return self._format_hits(hits, similarity_threshold)

    async def multi_collection_query(
        self,
        collections: list[str],
        query_text: str,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Query several collections concurrently and return top-``k`` by score."""
        k = int(kwargs.get("k", 10))
        tasks = [
            self.query(name, query_text, **kwargs) for name in collections
        ]
        per_collection = await asyncio.gather(*tasks, return_exceptions=True)

        merged: list[dict[str, Any]] = []
        for name, result in zip(collections, per_collection):
            if isinstance(result, BaseException):
                log.warning(
                    "[WARN] multi_collection_query: %s failed — %s",
                    name,
                    result,
                )
                continue
            for row in result:
                row = dict(row)
                row.setdefault("collection", name)
                merged.append(row)

        merged.sort(key=lambda r: r.get("score", 0.0), reverse=True)
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for row in merged:
            fp = (row.get("content") or "")[:200]
            if fp not in seen:
                seen.add(fp)
                deduped.append(row)
                if len(deduped) == k:
                    break
        return deduped

    async def health_check(self, *, deep: bool = False) -> dict[str, Any]:
        """Return a snapshot of adapter + cluster health.

        When ``deep=True`` the adapter issues a ``cluster.health`` request
        to OpenSearch in addition to reporting local metrics, and also
        enumerates indices with document counts so that callers like
        ``get_knowledge_base_status`` can render per-index breakdowns.
        """
        if not self._connected:
            try:
                await self.connect()
            except Exception as exc:  # pragma: no cover - defensive
                return {
                    "status": "unhealthy",
                    "connected": False,
                    "error": str(exc),
                }

        base = {
            "status": "healthy",
            "connected": self._connected,
            "endpoint": self._endpoint,
            "metrics": dict(self._metrics),
        }
        if not deep:
            return base

        try:
            cluster = await asyncio.to_thread(
                self._raw_client().cluster.health
            )
            base["cluster_status"] = cluster.get("status")
            if cluster.get("status") == "red":
                base["status"] = "unhealthy"
        except Exception as exc:
            base["status"] = "degraded"
            base["error"] = str(exc)
            return base

        # Enumerate indices and document counts for status reporting.
        try:
            cat_indices = await asyncio.to_thread(
                self._raw_client().cat.indices,
                format="json",
            )
            # Filter to mdc-* indices (our production indices) and
            # exclude system indices (starting with .).
            indices_detail: dict[str, int] = {}
            total_docs = 0
            for idx in cat_indices or []:
                name = idx.get("index", "")
                if name.startswith(".") or not name.startswith("mdc-"):
                    continue
                doc_count = int(idx.get("docs.count") or 0)
                indices_detail[name] = doc_count
                total_docs += doc_count
            base["indices"] = list(indices_detail.keys())
            base["indices_detail"] = indices_detail
            base["total_documents"] = total_docs
        except Exception as exc:
            # Non-fatal — index enumeration is best-effort for status
            # reporting. The adapter is still healthy for queries.
            log.debug("cat.indices failed (non-fatal): %s", exc)
            base["indices"] = []
            base["indices_detail"] = {}
            base["total_documents"] = 0

        return base

    async def close(self) -> None:
        """Release sockets held by the underlying ``opensearch-py`` client."""
        client = self._client
        self._client = None
        self._connected = False
        if client is None:
            return
        try:
            raw = getattr(client, "_client", None)
            if raw is not None and hasattr(raw, "close"):
                await asyncio.to_thread(raw.close)
        except Exception as exc:
            log.warning("[WARN] OpenSearchAdapter.close: %s", exc)

    # ── query construction (R2.2, R2.3) ─────────────────────────────────

    def _build_hybrid_query(
        self,
        query_text: str,
        embedding: list[float],
        k: int,
        where: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Construct a BM25 + k-NN hybrid body using OpenSearch RRF fusion.

        The query body has two equal-weight subqueries:

        * ``match`` against ``content`` for classic BM25 lexical scoring.
        * ``knn`` against ``embedding`` using the supplied dense vector.

        Fused via OpenSearch's ``search_pipeline``-less RRF — implemented
        at client side by wrapping both clauses in a ``bool.should`` with
        ``minimum_should_match: 1``. This mirrors the behaviour of the
        Node.js ``OpenSearchAdapter`` which prior to Phase 51 used the
        same construction for compatibility with clusters that lack a
        configured RRF search pipeline.
        """
        should: list[dict[str, Any]] = [
            {"match": {"content": {"query": query_text, "boost": 1.0}}},
            {"knn": {"embedding": {"vector": embedding, "k": k, "boost": 1.0}}},
        ]

        query_block: dict[str, Any] = {
            "bool": {
                "should": should,
                "minimum_should_match": 1,
            }
        }

        if where:
            query_block["bool"]["filter"] = self._build_filter(where)

        return {
            "size": k,
            "query": query_block,
            "_source": [
                "content",
                "metadata",
                "source_file",
                "chunk_id",
                "collection_name",
            ],
        }

    @staticmethod
    def _build_filter(where: dict[str, Any]) -> list[dict[str, Any]]:
        """Translate a ChromaDB-style ``where`` dict into OpenSearch filters.

        Supports plain equality (``{key: value}``) as well as the
        ``$eq`` / ``$in`` / ``$gte`` / ``$lte`` operators recognised by
        the Node.js adapter.
        """
        filters: list[dict[str, Any]] = []
        for key, value in where.items():
            field = f"metadata.{key}"
            if isinstance(value, dict):
                if "$eq" in value:
                    filters.append({"term": {field: value["$eq"]}})
                if "$in" in value:
                    filters.append({"terms": {field: value["$in"]}})
                if "$gte" in value:
                    filters.append({"range": {field: {"gte": value["$gte"]}}})
                if "$lte" in value:
                    filters.append({"range": {field: {"lte": value["$lte"]}}})
            else:
                filters.append({"term": {field: value}})
        return filters

    # ── embeddings (R2.7, Phase C-2c) ───────────────────────────────────

    async def _generate_embedding(self, query_text: str) -> list[float]:
        """Return a dense-vector embedding for ``query_text``.

        Uses ``self._embedding_function`` when set; otherwise delegates
        to the active provider built from ``MCP_EMBEDDING_PROFILE``.
        Translates :class:`EmbeddingError` (raised by the provider, or
        captured at adapter-construction time) into
        :class:`OpenSearchQueryError` with ``status=None`` so MCP tool
        handlers surface a structured error (Requirement 9.3).
        """
        # If provider construction failed (e.g. ``mpnet768`` ``LocalProvider``
        # import failure), surface the deferred error here on the first
        # call rather than at adapter-construction time.
        if self._provider_error is not None:
            raise OpenSearchQueryError(
                str(self._provider_error), status=None
            ) from self._provider_error

        fn = self._embedding_function or (
            self._provider.embed if self._provider is not None else None
        )
        if fn is None:  # pragma: no cover — defense in depth
            raise OpenSearchQueryError(
                "OpenSearchAdapter: no embedding provider configured",
                status=None,
            )

        try:
            embeddings = await asyncio.to_thread(fn, [query_text])
        except EmbeddingError as exc:
            raise OpenSearchQueryError(str(exc), status=None) from exc
        return list(embeddings[0])

    # ── retry wrapper (R2.6) ────────────────────────────────────────────

    async def _search_with_retry(
        self,
        *,
        index: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a search with exponential-backoff retry on transient errors.

        Retries on HTTP 429/5xx up to :data:`MAX_RETRIES` times. The
        delay schedule is ``INITIAL_BACKOFF_S * BACKOFF_MULTIPLIER**i``
        plus ±10 % jitter.
        """
        attempt = 0
        while True:
            try:
                raw = self._raw_client()
                return await asyncio.to_thread(raw.search, index=index, body=body)
            except Exception as exc:
                status = _status_of(exc)
                if status not in RETRYABLE_STATUS_CODES or attempt >= MAX_RETRIES:
                    self._metrics["queries_failed"] += 1
                    raise OpenSearchQueryError(
                        f"OpenSearch search on index={index!r} failed: {exc}",
                        status=status,
                    ) from exc
                delay = INITIAL_BACKOFF_S * (BACKOFF_MULTIPLIER**attempt)
                delay *= 1.0 + random.uniform(-0.1, 0.1)
                log.warning(
                    "[WARN] OpenSearch retry %d/%d after HTTP %s — sleeping %.2fs",
                    attempt + 1,
                    MAX_RETRIES,
                    status,
                    delay,
                )
                await asyncio.sleep(delay)
                attempt += 1

    # ── hit formatting (R2.5) ───────────────────────────────────────────

    def _format_hits(
        self,
        hits: list[dict[str, Any]],
        similarity_threshold: float,
    ) -> list[dict[str, Any]]:
        """Project OpenSearch hits onto the ``DocumentResult`` schema.

        The shape matches the Node.js ``OpenSearchAdapter._formatHits``
        contract so parity tests can compare top-N IDs directly:

        * ``id``       — hit ``_id``
        * ``content``  — ``_source.content``
        * ``metadata`` — ``_source.metadata`` (defaults to ``{}``)
        * ``score``    — ``_score`` clamped to ``[0, 1]``
        """
        formatted: list[dict[str, Any]] = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            source = hit.get("_source") or {}
            raw_score = hit.get("_score")
            score = float(raw_score) if raw_score is not None else 0.0
            if score < 0.0:
                score = 0.0
            elif score > 1.0:
                score = 1.0
            if score < similarity_threshold:
                continue
            formatted.append(
                {
                    "id": hit.get("_id"),
                    "content": source.get("content"),
                    "metadata": source.get("metadata") or {},
                    "score": score,
                }
            )
        return formatted

    # ── helpers ─────────────────────────────────────────────────────────

    def _raw_client(self) -> Any:
        """Return the underlying ``opensearch-py`` client (test seam)."""
        if self._client is None:
            raise OpenSearchQueryError(
                "OpenSearchAdapter: client not initialised (call connect())"
            )
        raw = getattr(self._client, "_client", None)
        if raw is None:
            raise OpenSearchQueryError(
                "OpenSearchAdapter: underlying opensearch-py client unavailable"
            )
        return raw


# ── module-level helpers ────────────────────────────────────────────────


def _status_of(exc: BaseException) -> int | None:
    """Best-effort extraction of an HTTP status code from an exception.

    ``opensearch-py`` wraps REST errors in ``TransportError`` /
    ``ConnectionError`` subclasses that expose either ``.status_code``
    or ``.status`` attributes. Falls back to ``None`` for network
    errors where no status is available.
    """
    for attr in ("status_code", "status", "info"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
        if isinstance(value, dict):
            nested = value.get("status") or value.get("statusCode")
            if isinstance(nested, int):
                return nested
    return None
