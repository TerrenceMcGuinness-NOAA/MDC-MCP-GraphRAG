"""ChromaDB adapter implementing :class:`VectorDBProtocol`.

Wraps the synchronous ``chromadb`` client with the async query interface
expected by tool modules.

Implements requirements for local ChromaDB support on Parallel Works VM.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
from typing import Any, Callable

import chromadb
from src.data.embedding_provider import (
    EmbeddingError,
    EmbeddingProvider,
    create_provider,
)
from src.data.embedding_registry import EmbeddingModelRegistry, ModelProfile
from src.data.protocols import VectorDBProtocol
from src.data.collection_scope import active_scope_transport
from src.data.read_router import (
    CollectionCondition,
    ResolvedTarget,
    RoutingDiagnostic,
    resolve_read_targets,
)
from src.data.vector_errors import CollectionNotProvisionedError

# Guarded import: ``chromadb.errors`` content varies by release.
# ``pyproject.toml`` pins ``chromadb==1.3.4`` but this interpreter has
# 1.5.8 installed; verified against 1.5.8, ``NotFoundError`` is present
# but ``InvalidCollectionException`` is not (the nearest relatives are
# ``InvalidArgumentError`` and ``InvalidDimensionException``). Names are
# therefore discovered via ``getattr`` rather than imported directly, so
# this module tolerates either release shape (shared-scope-query-routing
# Task 4.2).
try:
    import chromadb.errors as _chroma_errors
except ImportError:  # pragma: no cover - chromadb always ships errors today
    _chroma_errors = None  # type: ignore[assignment]

_CHROMA_NOT_FOUND_TYPES: tuple[type[BaseException], ...] = tuple(
    exc_type
    for exc_type in (
        getattr(_chroma_errors, "NotFoundError", None),
        getattr(_chroma_errors, "InvalidCollectionException", None),
    )
    if exc_type is not None
)

#: Case-insensitive substring fallback for client releases/wrappers whose
#: exception type does not match ``_CHROMA_NOT_FOUND_TYPES``.
_CHROMA_NOT_FOUND_TOKENS: tuple[str, ...] = (
    "does not exist",
    "collection not found",
)

log = logging.getLogger(__name__)

#: Default TTL, in seconds, for a cached *positive* Collection_Condition
#: (``PROVISIONED_EMPTY`` or ``PROVISIONED_POPULATED``). Overridable via
#: ``MCP_COLLECTION_CONDITION_TTL_S`` (shared-scope-query-routing Task
#: 7.2, design "Cross-backend normalization" point 3). ``UNPROVISIONED``
#: is never cached regardless of this setting -- see
#: :pymeth:`ChromaDBAdapter.collection_condition`.
_COLLECTION_CONDITION_TTL_S_DEFAULT: float = 300.0

#: Env var controlling the Collection_Condition probe kill switch
#: (Task 7.2, design point 4). Default enabled; set to ``"0"`` to treat
#: any non-raising member as ``PROVISIONED_POPULATED`` without issuing
#: the ambiguous-case ``count_documents`` probe.
_COLLECTION_CONDITION_PROBE_ENV: str = "MCP_COLLECTION_CONDITION_PROBE"


def _collection_condition_probe_enabled() -> bool:
    """Return whether the Collection_Condition probe is enabled (Task 7.2).

    Read fresh on every call (not cached) so a test can flip the env var
    between invocations without needing to reconstruct the adapter.
    """
    return os.getenv(_COLLECTION_CONDITION_PROBE_ENV, "1") != "0"


def _collection_condition_ttl_s() -> float:
    """Return the active Collection_Condition cache TTL, in seconds."""
    raw = os.getenv("MCP_COLLECTION_CONDITION_TTL_S")
    if raw is None:
        return _COLLECTION_CONDITION_TTL_S_DEFAULT
    try:
        return float(raw)
    except ValueError:
        return _COLLECTION_CONDITION_TTL_S_DEFAULT


def _is_missing_collection_exc(exc: BaseException) -> bool:
    """Return True iff ``exc`` signals a ChromaDB collection is absent.

    Mirrors the two-form approach ``src.tools._common._is_missing_index_exc``
    already uses for ``opensearchpy``: a structured exception-type match
    first, then a case-insensitive substring fallback on the message text.
    """
    if _CHROMA_NOT_FOUND_TYPES and isinstance(exc, _CHROMA_NOT_FOUND_TYPES):
        return True
    text = str(exc).lower()
    return any(token in text for token in _CHROMA_NOT_FOUND_TOKENS)


# ── inner-merge helpers (shared-scope-query-routing Task 7.3) ────────────
#
# Verbatim duplicate of the same three functions in
# ``opensearch_adapter.py``. They are pure and are kept as identical
# copies rather than hoisted into a new module: the owned-file set for
# this step is the two adapters, and Property 10 exercises both adapters
# through the same ``adapters()`` fixture, so any drift between the copies
# fails the suite. Keep the two copies identical.

_WHITESPACE_RUN: "re.Pattern[str]" = re.compile(r"\s+")


def _scope_content_digest(hit: dict[str, Any]) -> str:
    """SHA-256 over a hit's normalized content (R3.8).

    Normalization: ``content``, else ``document``, else ``text``, else
    ``""``; ``strip()``; collapse internal whitespace runs to one space;
    UTF-8. Whitespace collapsing makes the digest robust to the
    trailing-newline and indentation differences the two ingest paths
    introduce for the same source document.
    """
    text = hit.get("content") or hit.get("document") or hit.get("text") or ""
    normalized = _WHITESPACE_RUN.sub(" ", text.strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _stamp_provenance(
    hits: list[dict[str, Any]], physical: str
) -> list[dict[str, Any]]:
    """Attach ``physical_collection`` to each hit without re-ordering (R3.5).

    Used on the single-member path, where the merge is the identity by
    construction: the backend's native ordering is preserved and no
    de-duplication is applied (R3.3-R3.8 apply only to multi-member sets),
    so the Default_Tenant response stays byte-equivalent (R6.1, R6.7).
    """
    out: list[dict[str, Any]] = []
    for hit in hits:
        row = dict(hit)
        row["physical_collection"] = physical
        out.append(row)
    return out


def _merge_scope_members(
    member_hits: list[tuple[int, str, list[dict[str, Any]]]],
    k: int,
) -> list[dict[str, Any]]:
    """Order, de-duplicate, and cap hits from >1 addressed member.

    ``member_hits`` is ``(member_index, physical_name, hits)`` in router
    order (unprefixed member first). Implements the design's inner merge
    steps 3-6:

    * Step 3 -- stamp ``physical_collection`` from the producing member.
    * Step 4 -- order by the total key ``(-score, member_index,
      str(id))``. Total because ``(member_index, id)`` is unique within
      one read, so shared content precedes branch-local content at equal
      score (R3.3, R3.7).
    * Step 5 -- de-duplicate on the normalized content digest, keeping
      the first in step-4 order and its own provenance, so a document
      present in both members is retained as the shared copy (R3.8).
    * Step 6 -- cap at the first ``k`` survivors (R3.4).

    The per-member scores are NOT comparable in the strict sense, and
    that is deliberately not corrected here (see the OpenSearch copy's
    note): normalizing or fusing would move gw ordering on the outer
    merge (R6.2). Merged order is score-bucketed, shared before
    branch-local within a bucket.
    """
    flat: list[tuple[float, int, str, dict[str, Any]]] = []
    for member_index, physical, hits in member_hits:
        for hit in hits:
            row = dict(hit)
            row["physical_collection"] = physical
            score = float(row.get("score") or 0.0)
            flat.append((score, member_index, str(row.get("id")), row))
    flat.sort(key=lambda item: (-item[0], item[1], item[2]))

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for _score, _member_index, _hit_id, row in flat:
        digest = _scope_content_digest(row)
        if digest in seen:
            continue
        seen.add(digest)
        out.append(row)
        if len(out) >= k:
            break
    return out


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
        # Collection_Condition cache (Task 7.2): physical name ->
        # (condition, cached_at_monotonic). UNPROVISIONED is never
        # stored here -- see collection_condition().
        self._condition_cache: dict[
            str, tuple[CollectionCondition, float]
        ] = {}

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
        """Resolve read targets, fan out, merge, and attach provenance.

        The Read_Router (shared-scope-query-routing Task 7.3) is now the
        only component that applies an ``index_prefix`` on the read path,
        so ``ChromaDBAdapter`` and ``OpenSearchAdapter`` address the same
        Physical_Collections for the same ``(logical, tenant, profile)``
        triple (P3). Under the Default_Tenant every set has exactly one
        member and the merge is the identity by construction -- no
        ``if tenant is default`` branch.

        Raises
        ------
        CollectionNotProvisionedError
            When every member of the Resolved_Collection_Set is absent
            (R4.7, R7.9). A partially absent set does not raise (R7.1).
        """
        if not self._connected:
            await self.connect()
        if not query_text:
            raise ValueError("query_text must be non-empty")
        if not 1 <= k <= 1000:
            raise ValueError(f"k must be between 1 and 1000, got {k}")

        profile = self._profile.short_name
        resolved = resolve_read_targets(collection, tenant, profile=profile)
        targets = resolved.targets

        # Generate the embedding ONCE and reuse it for every member read.
        embedding = await self._generate_embedding(query_text)

        reads = [
            self._query_member(
                physical=target.physical,
                embedding=embedding,
                k=k,
                where=where,
                similarity_threshold=similarity_threshold,
                logical=collection,
                tenant_id=getattr(tenant, "tenant_id", None),
            )
            for target in targets
        ]
        results = await asyncio.gather(*reads, return_exceptions=True)

        member_hits, unprovisioned = self._triage_member_results(
            targets, results, logical=collection,
            tenant_id=getattr(tenant, "tenant_id", None),
        )

        if len(targets) == 1:
            merged = _stamp_provenance(
                member_hits[0][2], member_hits[0][1]
            )
        else:
            merged = _merge_scope_members(member_hits, k)

        await self._emit_member_conditions(
            resolved, member_hits, unprovisioned
        )
        return merged

    async def _query_member(
        self,
        *,
        physical: str,
        embedding: list[float],
        k: int,
        where: dict[str, Any] | None,
        similarity_threshold: float,
        logical: str,
        tenant_id: str | None,
    ) -> list[dict[str, Any]]:
        """Run one vector read against a single physical collection.

        Classifies collection absence BEFORE the catch-all ``ValueError``
        wrap (R4.3, R4.6): a collection-absence signal raises
        :class:`CollectionNotProvisionedError` so the tool layer's widened
        ``_is_missing_index_exc`` renders a Skip_Block; any other failure
        (connection, auth, embedding) falls through to the existing
        ``ValueError`` wrap with its message unchanged, staying
        distinguishable from absence.
        """
        def _execute() -> dict[str, Any]:
            assert self._client is not None
            coll = self._client.get_collection(physical)
            return coll.query(
                query_embeddings=[embedding],
                n_results=k,
                where=where,
            )

        started = time.perf_counter()
        try:
            raw_res = await asyncio.to_thread(_execute)
            self._metrics["queries_executed"] += 1
            self._metrics["last_query_ms"] = round(
                (time.perf_counter() - started) * 1000, 2
            )
        except Exception as exc:
            self._metrics["queries_failed"] += 1
            if _is_missing_collection_exc(exc):
                log.info(
                    "[INFO] ChromaDB collection not provisioned: %r", physical
                )
                raise CollectionNotProvisionedError(
                    physical, logical=logical, tenant_id=tenant_id
                ) from exc
            log.error(
                "[ERROR] ChromaDB query failed on collection=%r: %s",
                physical, exc,
            )
            raise ValueError(
                f"ChromaDB query failed on index={physical!r}: {exc}"
            ) from exc

        return self._format_hits(raw_res, similarity_threshold)

    def _triage_member_results(
        self,
        targets: tuple[ResolvedTarget, ...],
        results: list[Any],
        *,
        logical: str,
        tenant_id: str | None,
    ) -> tuple[
        list[tuple[int, str, list[dict[str, Any]]]],
        list[ResolvedTarget],
    ]:
        """Classify per-member fan-out outcomes (design step 2).

        UNPROVISIONED members contribute zero hits (R7.1/R7.3); any other
        exception propagates as a query failure (R4.6); every member
        absent raises once naming the logical collection (R4.7, R7.9).
        """
        member_hits: list[tuple[int, str, list[dict[str, Any]]]] = []
        unprovisioned: list[ResolvedTarget] = []
        for member_index, (target, result) in enumerate(zip(targets, results)):
            if isinstance(result, CollectionNotProvisionedError):
                unprovisioned.append(target)
                continue
            if isinstance(result, BaseException):
                raise result
            member_hits.append((member_index, target.physical, result))

        if not member_hits:
            first = targets[0] if targets else None
            physical = first.physical if first is not None else logical
            raise CollectionNotProvisionedError(
                physical, logical=logical, tenant_id=tenant_id
            )
        return member_hits, unprovisioned

    async def _emit_member_conditions(
        self,
        resolved: Any,
        member_hits: list[tuple[int, str, list[dict[str, Any]]]],
        unprovisioned: list[ResolvedTarget],
    ) -> None:
        """Emit per-member Collection_Condition diagnostics (design step 7).

        Log-channel-only and best-effort: the whole body is guarded so a
        probe failure never breaks a read. UNPROVISIONED members are known
        for free from the fan-out; a member that returned zero hits is
        probed once to tell PROVISIONED_EMPTY from PROVISIONED_POPULATED.
        Fires for the Default_Tenant too (R6.8) without changing rendered
        output.
        """
        try:
            target_by_physical = {
                t.physical: t for t in resolved.targets
            }
            for target in unprovisioned:
                self._log_member_condition(
                    resolved, target, CollectionCondition.UNPROVISIONED
                )
            for _member_index, physical, hits in member_hits:
                if hits:
                    continue
                target = target_by_physical.get(physical)
                if target is None:
                    continue
                condition = await self.collection_condition(physical)
                if condition in (
                    CollectionCondition.UNPROVISIONED,
                    CollectionCondition.PROVISIONED_EMPTY,
                ):
                    self._log_member_condition(resolved, target, condition)
        except Exception as exc:  # never let diagnostics break a read
            log.debug(
                "member-condition diagnostics failed (non-fatal): %s", exc
            )

    @staticmethod
    def _log_member_condition(
        resolved: Any,
        target: ResolvedTarget,
        condition: CollectionCondition,
    ) -> None:
        """Log one per-member condition Routing_Diagnostic (R7.3, R7.4)."""
        diagnostic = RoutingDiagnostic(
            tenant_id=resolved.tenant_id,
            logical=resolved.logical,
            profile=resolved.profile,
            members=((target.physical, target.scope, target.prefixed),),
            transport=active_scope_transport(),
            classification=condition.value,
        )
        log.info(diagnostic.render())

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

    async def collection_condition(
        self, physical_collection: str
    ) -> CollectionCondition:
        """Classify one physical ChromaDB collection (shared-scope-query-
        routing Task 7.2, R7.3, R7.4, R7.8).

        Takes the free answers first and probes only the ambiguous case:

        * ``UNPROVISIONED`` -- the collection does not exist. Detected via
          the same absence signal :func:`_is_missing_collection_exc` uses
          on the query path, so this classifier and ``query()`` agree on
          what "absent" means. **Never cached**: a collection can be
          provisioned at any moment, and a stale absence is far more
          damaging than a stale count (design "Cross-backend
          normalization" point 3).
        * ``PROVISIONED_EMPTY`` / ``PROVISIONED_POPULATED`` -- the
          collection exists; disambiguated by :pymeth:`count_documents`,
          which is already non-raising and read-only. These two are
          cached per physical name for
          :func:`_collection_condition_ttl_s` seconds.

        The kill switch ``MCP_COLLECTION_CONDITION_PROBE=0`` skips the
        existence/count probe entirely and reports
        ``PROVISIONED_POPULATED`` for any collection reachable without
        raising, logging that the probe is disabled.

        Never raises. Issues no mutating call -- only ``get_collection``
        (a read) and ``count()`` (a metadata read), both already used
        elsewhere in this adapter without creating, deleting, or writing
        anything (Requirement 12.5).
        """
        if not _collection_condition_probe_enabled():
            log.info(
                "[INFO] collection_condition probe disabled "
                "(MCP_COLLECTION_CONDITION_PROBE=0); reporting "
                "provisioned-populated for %r without a probe",
                physical_collection,
            )
            return CollectionCondition.PROVISIONED_POPULATED

        cached = self._condition_cache.get(physical_collection)
        if cached is not None:
            condition, cached_at = cached
            if (time.monotonic() - cached_at) < _collection_condition_ttl_s():
                return condition

        if not self._connected:
            await self.connect()

        def _exists() -> bool:
            assert self._client is not None
            try:
                self._client.get_collection(physical_collection)
                return True
            except Exception:
                # Any failure to fetch the collection -- absence-
                # signalled or otherwise -- is treated as absent here:
                # this method's contract is "never raises", and there is
                # no meaningful third outcome to report through a
                # boolean exists/absent result.
                return False

        exists = await asyncio.to_thread(_exists)
        if not exists:
            # Deliberately not cached (see docstring).
            return CollectionCondition.UNPROVISIONED

        count = await self.count_documents(physical_collection)
        condition = (
            CollectionCondition.PROVISIONED_POPULATED
            if count > 0
            else CollectionCondition.PROVISIONED_EMPTY
        )
        self._condition_cache[physical_collection] = (
            condition,
            time.monotonic(),
        )
        return condition

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
