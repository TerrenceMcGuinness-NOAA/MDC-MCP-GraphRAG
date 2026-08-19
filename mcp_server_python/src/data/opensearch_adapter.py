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
import hashlib
import os
import random
import re
import time
from typing import Any, Callable

from src.config.aws_config import DEFAULT_AWS_REGION, resolve_index
from src.data.collection_scope import active_scope_transport
from src.data.embedding_provider import (
    EmbeddingError,
    EmbeddingProvider,
    create_provider,
)
from src.data.embedding_registry import EmbeddingModelRegistry, ModelProfile
from src.data.read_router import (
    CollectionCondition,
    ResolvedTarget,
    RoutingDiagnostic,
    resolve_read_targets,
)
from src.data.vector_errors import CollectionNotProvisionedError

log = logging.getLogger(__name__)

#: Default TTL, in seconds, for a cached *positive* Collection_Condition
#: (``PROVISIONED_EMPTY`` or ``PROVISIONED_POPULATED``). Overridable via
#: ``MCP_COLLECTION_CONDITION_TTL_S`` (shared-scope-query-routing Task
#: 7.2, design "Cross-backend normalization" point 3). ``UNPROVISIONED``
#: is never cached regardless of this setting -- see
#: :pymeth:`OpenSearchAdapter.collection_condition`.
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


def _is_missing_index_exc(exc: BaseException) -> bool:
    """Return True iff ``exc`` is an OpenSearch ``index_not_found_exception``.

    Reused verbatim from ``src.tools._common._is_missing_index_exc`` so no
    behaviour shifts for the paths that already call that helper
    (shared-scope-query-routing design, "Cross-backend normalization").
    Detects two equivalent forms: the structured ``opensearchpy``
    ``NotFoundError`` whose ``info['error']['type']`` is
    ``index_not_found_exception``, or the literal token in ``str(exc)``.
    """
    try:
        from opensearchpy.exceptions import NotFoundError  # type: ignore
    except ImportError:  # pragma: no cover - dev/test path without the SDK
        NotFoundError = None  # type: ignore[assignment]

    if NotFoundError is not None and isinstance(exc, NotFoundError):
        info = getattr(exc, "info", None) or {}
        err = info.get("error") if isinstance(info, dict) else None
        if (
            isinstance(err, dict)
            and err.get("type") == "index_not_found_exception"
        ):
            return True

    return "index_not_found_exception" in str(exc)


# ── inner-merge helpers (shared-scope-query-routing Task 7.3) ────────────
#
# These three functions implement the design's inner merge (steps 3-6) for
# a Resolved_Collection_Set with more than one member. They are pure and
# deliberately duplicated verbatim in ``chromadb_adapter.py`` rather than
# hoisted into a new module: the owned-file set for this step is the two
# adapters, and Property 10 exercises both adapters through the same
# ``adapters()`` fixture, so any drift between the two copies fails the
# suite. Keep the two copies identical.

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

    The per-member scores are NOT comparable in the strict sense (BM25 is
    index-local; OpenSearch clamps ``_score`` to ``[0, 1]``), and this is
    deliberately not corrected: per-member normalization or RRF fusion
    would have to apply to the outer cross-collection merge to be
    coherent, and that moves gw ordering (R6.2). The resulting semantics:
    for a Hybrid_Domain the merged order is score-bucketed, and within a
    bucket shared content precedes branch-local content.
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
        # Collection_Condition cache (Task 7.2): physical name ->
        # (condition, cached_at_monotonic). UNPROVISIONED is never
        # stored here -- see collection_condition().
        self._condition_cache: dict[
            str, tuple[CollectionCondition, float]
        ] = {}

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
        """Resolve read targets, fan out, merge, and attach provenance.

        The Read_Router (shared-scope-query-routing Task 7.3) is now the
        only component that applies an ``index_prefix`` on the read path:
        this method addresses exactly the Physical_Collections
        :func:`resolve_read_targets` returns. For a ``shared`` collection
        under a prefixed tenant that is the unprefixed index; for a
        Hybrid_Domain it is both the unprefixed and the prefixed index,
        merged. Under the Default_Tenant every set has exactly one member,
        so the merge is the identity by construction -- there is no
        ``if tenant is default`` branch.

        Every returned row gains ``physical_collection`` naming the member
        that produced it (R3.5); the pre-existing ``collection`` key is
        left untouched (it carries the logical name and is rendered by
        ``semantic_search._format_search_hit``).

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

        # Preserve the pre-change passthrough diagnostic on THIS adapter's
        # log channel (message byte-identical) for callers/tests that watch
        # ``src.data.opensearch_adapter``. The Read_Router emits its own
        # ``unmapped-profile`` diagnostic on its channel; this is the
        # adapter-local echo, unchanged from before the routing move.
        real = resolve_index(collection, profile)
        if real == collection:
            first = resolved.physical_names[0] if resolved.physical_names \
                else collection
            log.info(
                "[opensearch] collection %r not in production index map "
                "(profile=%s, tenant=%s); passthrough -> index=%r",
                collection,
                profile,
                getattr(tenant, "tenant_id", "none"),
                first,
            )

        # Generate the embedding ONCE and reuse it for every member read:
        # the fan-out passes identical query_text/k/threshold/where (R3.2).
        embedding = await self._generate_embedding(query_text)

        reads = [
            self._query_member(
                physical=target.physical,
                query_text=query_text,
                embedding=embedding,
                k=k,
                similarity_threshold=similarity_threshold,
                where=where,
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
        query_text: str,
        embedding: list[float],
        k: int,
        similarity_threshold: float,
        where: dict[str, Any] | None,
        logical: str,
        tenant_id: str | None,
    ) -> list[dict[str, Any]]:
        """Run one hybrid read against a single physical index.

        Classifies collection absence BEFORE the caller sees the generic
        ``OpenSearchQueryError`` (R4.3, R4.6), reusing the existing
        ``index_not_found_exception`` detection verbatim so no behaviour
        shifts for the paths that already call
        ``src.tools._common._is_missing_index_exc``. Any other failure
        (connection, auth, embedding, non-404 transport error) keeps its
        existing ``OpenSearchQueryError`` shape and is never presented as
        unprovisioned.
        """
        body = self._build_hybrid_query(query_text, embedding, k, where)
        started = time.perf_counter()
        try:
            response = await self._search_with_retry(index=physical, body=body)
        except Exception as exc:
            if _is_missing_index_exc(exc):
                log.info(
                    "[INFO] OpenSearch index not provisioned: %r", physical
                )
                raise CollectionNotProvisionedError(
                    physical, logical=logical, tenant_id=tenant_id
                ) from exc
            raise
        self._metrics["queries_executed"] += 1
        self._metrics["last_query_ms"] = round(
            (time.perf_counter() - started) * 1000, 2
        )
        hits = response.get("hits", {}).get("hits", [])
        return self._format_hits(hits, similarity_threshold)

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

        A :class:`CollectionNotProvisionedError` marks that member
        UNPROVISIONED (contributes zero hits, R7.1/R7.3); any other
        exception propagates as a query failure (R4.6). When EVERY member
        is absent the whole set raises once, naming the logical collection
        so the tool renders exactly one Skip_Block (R4.7, R7.9).
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

        UNPROVISIONED members are known for free from the fan-out; a member
        that returned zero hits is probed once (the sole ambiguous case) to
        tell PROVISIONED_EMPTY from PROVISIONED_POPULATED. Log-channel-only
        and best-effort: the whole body is guarded so a probe failure never
        breaks a read. Fires for the Default_Tenant too (R6.8) -- a log
        line is not rendered output, so gw byte-equivalence is unaffected.
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
            # Keep production indices: the unprefixed ``mdc-*`` base set
            # (default gw tenant) and any tenant-prefixed ``<prefix>mdc-*``
            # index (e.g. ``gw_v17_mdc-code-titan1024``). Per-tenant scoping
            # is applied downstream by the status renderer; enumerating both
            # families here keeps gw's view unchanged (the renderer filters
            # the prefixed entries back out for gw). System indices (``.``)
            # are excluded.
            indices_detail: dict[str, int] = {}
            total_docs = 0
            for idx in cat_indices or []:
                name = idx.get("index", "")
                if name.startswith(".") or not (
                    name.startswith("mdc-") or "_mdc-" in name
                ):
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

    # ── observability parity (cots-backend-observability-parity) ─────────

    async def count_documents(self, collection: str) -> int:
        """Return the document count for an index (0 if missing).

        cots-backend-observability-parity R1/R6 — the OpenSearch-side
        counterpart to :pymeth:`ChromaDBAdapter.count_documents` so both
        adapters fulfil the same :class:`VectorDBProtocol` contract.
        ``collection`` is the physical index name; callers such as the
        manifest gap detector resolve the logical -> physical mapping via
        :pyfunc:`resolve_index` before calling. Non-raising: a missing index
        or any transport error yields ``0``.
        """
        if not self._connected:
            await self.connect()

        def _do() -> int:
            raw = self._raw_client()
            try:
                resp = raw.count(index=collection)
            except Exception:
                # Missing index / transport error → 0 (never raise).
                return 0
            try:
                return int(resp.get("count", 0) or 0)
            except Exception:
                return 0

        return await asyncio.to_thread(_do)

    async def collection_condition(
        self, physical_collection: str
    ) -> CollectionCondition:
        """Classify one physical OpenSearch index (shared-scope-query-
        routing Task 7.2, R7.3, R7.4, R7.8).

        Takes the free answers first and probes only the ambiguous case:

        * ``UNPROVISIONED`` -- the index does not exist. Detected via the
          same :func:`_is_missing_index_exc` signal the query path uses,
          so this classifier and ``query()`` agree on what "absent"
          means. **Never cached**: a collection can be provisioned at
          any moment, and a stale absence is far more damaging than a
          stale count (design "Cross-backend normalization" point 3).
        * ``PROVISIONED_EMPTY`` / ``PROVISIONED_POPULATED`` -- the index
          exists; disambiguated by the document count. Cached per
          physical name for :func:`_collection_condition_ttl_s` seconds.

        The kill switch ``MCP_COLLECTION_CONDITION_PROBE=0`` skips the
        existence/count probe entirely and reports
        ``PROVISIONED_POPULATED`` for any index reachable without
        raising, logging that the probe is disabled.

        Never raises. Issues no mutating call -- only ``count`` (a
        metadata read), already used elsewhere in this adapter without
        creating, deleting, or writing anything (Requirement 12.5).
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

        def _count_or_absent() -> int | None:
            """Return the document count, or ``None`` if the index is absent.

            ``None`` distinguishes UNPROVISIONED from a genuine zero
            count. Any failure -- absence-signalled or otherwise -- is
            treated as absent here: this method's contract is "never
            raises", and a transport error offers no meaningful third
            outcome to report through a two-state count/absent result.
            """
            raw = self._raw_client()
            try:
                resp = raw.count(index=physical_collection)
            except Exception:
                return None
            try:
                return int(resp.get("count", 0) or 0)
            except Exception:
                return 0

        count = await asyncio.to_thread(_count_or_absent)
        if count is None:
            # Deliberately not cached (see docstring).
            return CollectionCondition.UNPROVISIONED

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

        return await asyncio.to_thread(_do)

    async def sample_metadata(
        self,
        collection: str | None = None,
        limit: int = 50,
        *,
        n: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return up to ``limit`` document-metadata dicts for integrity sampling.

        cots-backend-observability-parity R2/R6 — the OpenSearch-side
        counterpart to :pymeth:`ChromaDBAdapter.sample_metadata`. Uses a
        ``random_score`` ``match_all`` query per index (the exact strategy the
        ``check_knowledge_integrity`` scroll sampler used prior to Phase 70) so
        the AWS integrity-check behaviour is preserved when the tool layer now
        routes through this method. When ``collection`` is ``None`` the adapter
        samples across every non-system index up to ``limit`` total. Returns
        ``[]`` on any error (never raises).

        ``n`` is a backward-compatible alias for ``limit``.
        """
        effective_limit = int(n) if n is not None else int(limit)
        if not self._connected:
            await self.connect()

        def _do() -> list[dict[str, Any]]:
            raw = self._raw_client()
            if collection is not None:
                index_names = [collection]
            else:
                try:
                    rows = raw.cat.indices(format="json", h="index")
                    index_names = [
                        r["index"] for r in rows
                        if not r["index"].startswith(".")
                    ]
                except Exception:
                    index_names = []
            if not index_names:
                return []
            per_index = max(1, effective_limit // max(1, len(index_names)))
            collected: list[dict[str, Any]] = []
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
                        # Preserve pre-Phase-70 behaviour: include the (possibly
                        # empty) metadata dict so the Path-Consistency /
                        # Stale-Embeddings denominators match the prior scroll
                        # sampler exactly on AWS.
                        meta = (hit.get("_source") or {}).get("metadata") or {}
                        collected.append(meta)
                except Exception:
                    continue
            random.shuffle(collected)
            return collected[:effective_limit]

        return await asyncio.to_thread(_do)

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
