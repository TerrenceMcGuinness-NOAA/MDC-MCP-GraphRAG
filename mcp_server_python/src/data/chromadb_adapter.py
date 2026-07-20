"""ChromaDB adapter implementing :class:`VectorDBProtocol`.

Wraps the synchronous ``chromadb`` client with the async query interface
expected by tool modules.

Implements requirements for local ChromaDB support on Parallel Works VM.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Callable

import chromadb
from src.config.aws_config import resolve_index
from src.data.embedding_provider import (
    EmbeddingError,
    EmbeddingProvider,
    create_provider,
)
from src.data.embedding_registry import EmbeddingModelRegistry, ModelProfile
from src.data.protocols import VectorDBProtocol

log = logging.getLogger(__name__)


class ChromaDBAdapter(VectorDBProtocol):
    """Async ChromaDB adapter.

    Parameters
    ----------
    host
        ChromaDB HTTP host.
    port
        ChromaDB HTTP port.
    embedding_function
        Optional callable ``list[str] -> list[list[float]]`` used to
        generate query-time embeddings.
    """

    @staticmethod
    def resolve_tenant_index(collection: str, tenant: Any) -> str:
        """Apply tenant.index_prefix to a logical collection name."""
        if not tenant or not getattr(tenant, "index_prefix", None):
            return collection
        return f"{tenant.index_prefix}{collection}"

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8080,
        *,
        embedding_function: Callable[[list[str]], list[list[float]]] | None = None,
    ):
        self._host = host
        self._port = port
        self._embedding_function = embedding_function

        # Resolve active embedding profile (defaults to mpnet768 on-premise)
        profile_name = os.getenv("MCP_EMBEDDING_PROFILE", "mpnet768")
        self._profile: ModelProfile = (
            EmbeddingModelRegistry().get_profile(profile_name)
        )

        self._provider: EmbeddingProvider | None = None
        self._provider_error: EmbeddingError | None = None
        if embedding_function is None:
            try:
                self._provider = create_provider(self._profile)
            except EmbeddingError as exc:
                self._provider_error = exc

        self._client: chromadb.HttpClient | None = None
        self._connected = False
        self._metrics: dict[str, Any] = {
            "queries_executed": 0,
            "queries_failed": 0,
            "last_query_ms": None,
        }

    # ── VectorDBProtocol ────────────────────────────────────────────────

    async def connect(self) -> None:
        """Lazily initialize the ChromaDB HTTP client.

        Safe to call multiple times (idempotent).
        """
        if self._connected:
            return

        def _build() -> chromadb.HttpClient:
            return chromadb.HttpClient(host=self._host, port=self._port)

        self._client = await asyncio.to_thread(_build)
        self._connected = True
        log.info("[OK] ChromaDBAdapter connected: http://%s:%d", self._host, self._port)

    async def query(
        self,
        collection: str,
        query_text: str,
        *,
        k: int = 10,
        similarity_threshold: float = 0.0,
        where: dict[str, Any] | None = None,
        include_graph: bool = True,  # noqa: ARG002 - ignored in vector adapter
        tenant: Any = None,
    ) -> list[dict[str, Any]]:
        """Run vector query against ChromaDB, then format hits."""
        if not self._connected:
            await self.connect()
        if not query_text:
            raise ValueError("query_text must be non-empty")
        if not 1 <= k <= 1000:
            raise ValueError(f"k must be between 1 and 1000, got {k}")

        # Resolve physical collection name pre-tenant
        real = resolve_index(collection, self._profile.short_name)
        index = self.resolve_tenant_index(real, tenant) if tenant else real

        embedding = await self._generate_embedding(query_text)

        started = time.perf_counter()

        def _execute() -> dict[str, Any]:
            assert self._client is not None
            coll = self._client.get_collection(index)
            # Query ChromaDB collection using pre-computed embedding vector
            res = coll.query(
                query_embeddings=[embedding],
                n_results=k,
                where=where,
            )
            return res

        try:
            raw_res = await asyncio.to_thread(_execute)
            self._metrics["queries_executed"] += 1
            self._metrics["last_query_ms"] = round(
                (time.perf_counter() - started) * 1000, 2
            )
        except Exception as exc:
            self._metrics["queries_failed"] += 1
            log.error("[ERROR] ChromaDB query failed on collection=%r: %s", index, exc)
            raise ValueError(f"ChromaDB query failed on index={index!r}: {exc}") from exc

        return self._format_hits(raw_res, similarity_threshold)

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
        """Return a snapshot of adapter + cluster health."""
        base: dict[str, Any] = {
            "status": "healthy" if self._connected else "unknown",
            "backend": "chromadb",
            "host": self._host,
            "port": self._port,
            "queries_executed": self._metrics["queries_executed"],
            "queries_failed": self._metrics["queries_failed"],
            "last_query_ms": self._metrics["last_query_ms"],
        }
        if not deep:
            return base

        try:
            assert self._client is not None
            # Heartbeat check to verify connection
            await asyncio.to_thread(self._client.heartbeat)
            base["status"] = "healthy"
        except Exception as exc:
            base["status"] = "unhealthy"
            base["error"] = str(exc)
            return base

        # List collections for diagnostic status reporting
        try:
            colls = await asyncio.to_thread(self._client.list_collections)
            collections_detail: dict[str, int] = {}
            total_docs = 0
            for coll in colls:
                name = coll.name
                count = coll.count()
                collections_detail[name] = count
                total_docs += count
            base["collections"] = list(collections_detail.keys())
            base["collections_detail"] = collections_detail
            base["total_documents"] = total_docs
        except Exception as exc:
            log.debug("list_collections failed (non-fatal): %s", exc)
            base["collections"] = []
            base["collections_detail"] = {}
            base["total_documents"] = 0

        return base

    async def close(self) -> None:
        """Close ChromaDB connections (idempotent stub)."""
        self._client = None
        self._connected = False

    # ── ingestion write path (cots-reingest-ralph-loop) ────────────────

    @staticmethod
    def _sanitize_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
        """Flatten metadata to ChromaDB-legal scalars (str/int/float/bool).

        Nested dicts/lists are JSON-encoded; None values are dropped.
        ChromaDB rejects non-scalar or null metadata values.
        """
        import json as _json

        out: dict[str, Any] = {}
        for key, value in (metadata or {}).items():
            if value is None:
                continue
            if isinstance(value, (str, int, float, bool)):
                out[key] = value
            else:
                out[key] = _json.dumps(value)
        return out

    async def upsert_document(
        self,
        *,
        collection: str,
        doc_id: str,
        content: str,
        metadata: dict[str, Any] | None,
        embedding: list[float],
    ) -> None:
        """Upsert one precomputed-embedding document into a ChromaDB collection.

        Idempotent by ``doc_id`` (content-addressed SHA id from the ingesters).
        The collection is created on first write; the embedding dimension is
        fixed by the first vector. Always writes with an explicit embedding, so
        the collection's default embedding function is never invoked.
        """
        if not self._connected:
            await self.connect()

        def _do() -> None:
            assert self._client is not None
            coll = self._client.get_or_create_collection(collection)
            coll.upsert(
                ids=[doc_id],
                embeddings=[list(embedding)],
                documents=[content],
                metadatas=[self._sanitize_metadata(metadata)],
            )

        await asyncio.to_thread(_do)

    async def count_documents(self, collection: str) -> int:
        """Return the number of documents in ``collection`` (0 if missing).

        cots-backend-observability-parity R1. Uses ChromaDB's native
        ``collection.count()``. Non-raising: a missing collection (or any
        client error) yields ``0`` so observability tools
        (``get_knowledge_base_status``, ``list_all_sources --include_gaps``)
        can dispatch through ``backend.vector.count_documents(...)`` on either
        backend without branching on backend type. This is the ChromaDB-side
        counterpart to :pymeth:`OpenSearchAdapter.count_documents`.
        """
        if not self._connected:
            await self.connect()

        def _do() -> int:
            assert self._client is not None
            try:
                coll = self._client.get_collection(collection)
            except Exception:
                # Missing collection → 0 (never raise).
                return 0
            try:
                return int(coll.count())
            except Exception:
                return 0

        return await asyncio.to_thread(_do)

    async def sample_metadata(
        self,
        collection: str | None = None,
        limit: int = 50,
        *,
        n: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return up to ``limit`` document metadata dicts for integrity sampling.

        cots-backend-observability-parity R2 (canonical ``limit`` parameter) +
        rag-data-plane-gap-closure R5.1. Backed by ChromaDB ``get(limit=...)``.
        When ``collection`` is given, samples that collection; when ``None``
        (the default used by the integrity checks), samples across all
        collections up to ``limit`` total. Returns ``[]`` for an empty or
        missing collection (never raises), so ``check_knowledge_integrity``
        degrades gracefully rather than crashing.

        ``n`` is a backward-compatible alias for ``limit`` (the pre-Phase-70
        parameter name still used by ``_build_vector_sampler`` and older test
        doubles); when supplied it takes precedence over ``limit``.
        """
        effective_limit = int(n) if n is not None else int(limit)
        if not self._connected:
            await self.connect()

        def _do() -> list[dict[str, Any]]:
            assert self._client is not None
            if collection is not None:
                names = [collection]
            else:
                try:
                    names = [c.name for c in self._client.list_collections()]
                except Exception:
                    return []
            out: list[dict[str, Any]] = []
            for name in names:
                if len(out) >= effective_limit:
                    break
                try:
                    coll = self._client.get_collection(name)
                    got = coll.get(
                        limit=effective_limit - len(out),
                        include=["metadatas"],
                    )
                except Exception:
                    # Missing/empty collection → skip (never raise).
                    continue
                for meta in (got.get("metadatas") or []):
                    if meta:
                        out.append(meta)
            return out[:effective_limit]

        return await asyncio.to_thread(_do)

    # ── internals ──────────────────────────────────────────────────────

    async def _generate_embedding(self, query_text: str) -> list[float]:
        """Return a dense-vector embedding for ``query_text``."""
        if self._provider_error is not None:
            raise ValueError(str(self._provider_error)) from self._provider_error

        fn = self._embedding_function or (
            self._provider.embed if self._provider is not None else None
        )
        if fn is None:
            raise ValueError("ChromaDBAdapter: no embedding provider configured")

        try:
            embeddings = await asyncio.to_thread(fn, [query_text])
        except EmbeddingError as exc:
            raise ValueError(str(exc)) from exc
        return list(embeddings[0])

    def _format_hits(
        self,
        raw_res: dict[str, Any],
        similarity_threshold: float,
    ) -> list[dict[str, Any]]:
        """Project ChromaDB raw results onto DocumentResult schema."""
        ids = raw_res.get("ids", [[]])[0]
        documents = raw_res.get("documents", [[]])[0]
        metadatas = raw_res.get("metadatas", [[]])[0]
        distances = raw_res.get("distances", [[]])[0]

        formatted: list[dict[str, Any]] = []
        for i in range(len(ids)):
            distance = distances[i] if i < len(distances) else 0.0
            # Our local ChromaDB collections default to L2 squared space.
            # For normalized embeddings, the relationship between L2 squared and cosine
            # similarity is: L2_squared = 2 - 2 * cos_sim => cos_sim = 1 - L2_squared / 2.
            score = 1.0 - float(distance) / 2.0
            if score < 0.0:
                score = 0.0
            elif score > 1.0:
                score = 1.0

            if score < similarity_threshold:
                continue

            formatted.append(
                {
                    "id": ids[i],
                    "content": documents[i] if i < len(documents) else "",
                    "metadata": metadatas[i] if i < len(metadatas) else {},
                    "score": score,
                }
            )
        return formatted
