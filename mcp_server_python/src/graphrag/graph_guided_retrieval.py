"""Hybrid graph + vector retrieval (Requirements 6.2, 6.8).

Python port of ``mcp_server_node/src/graphrag/GraphGuidedRetrieval.js``,
trimmed down to the workflows the Python tool modules actually use:

* ``get_code_context`` — GGSR neighbourhood + semantic enrichment from
  the vector store, combined into a single result structure.

The Node.js version ships a larger surface (query classification,
community summaries, markdown formatting). Those concerns are being
deferred to the GraphRAGTools port (Phase B7) so this file stays a thin
orchestration layer that mirrors the design's ``GraphGuidedRetrieval``
component box.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable

from src.data.protocols import VectorDBProtocol

from .ggsr_traversal import (
    DEFAULT_TOKEN_BUDGET,
    GGSRScoredResult,
    GGSRTraversal,
)

log = logging.getLogger(__name__)

# Collection used for semantic enrichment when the caller does not pass
# one explicitly. Matches the canonical code-context index shipped by
# the Node.js server (see ``GraphGuidedRetrieval.js``).
DEFAULT_SEMANTIC_COLLECTION: str = "mdc-code-context-mpnet768"


# ── result model ─────────────────────────────────────────────────────────


@dataclass
class GGSRRetrievalResult:
    """Combined output of :pymeth:`GraphGuidedRetrieval.get_code_context`.

    Attributes
    ----------
    entity
        The seed entity the caller asked about.
    ggsr_results
        Scored, budget-trimmed graph neighbours.
    semantic_hits
        Vector-store documents that add context for ``entity`` or for
        key identifiers discovered in the graph neighbourhood. Each
        hit is a dict with at least ``id``, ``content``, ``metadata``,
        ``score`` (the :data:`~src.data.protocols.VECTOR_RESULT_KEYS`
        shape).
    metadata
        Diagnostic fields — GGSR count, semantic hit count, token
        accounting, and any degraded-mode flags.
    """

    entity: str
    ggsr_results: list[GGSRScoredResult] = field(default_factory=list)
    semantic_hits: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ggsr_count(self) -> int:
        return len(self.ggsr_results)

    @property
    def semantic_count(self) -> int:
        return len(self.semantic_hits)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "ggsr_results": [r.to_dict() for r in self.ggsr_results],
            "semantic_hits": list(self.semantic_hits),
            "metadata": dict(self.metadata),
        }


# ── retrieval engine ─────────────────────────────────────────────────────


class GraphGuidedRetrieval:
    """Combine GGSR graph traversal with OpenSearch semantic retrieval.

    The class deliberately mirrors the Node.js constructor shape —
    ``{ggsr, vector_db}`` — so the wiring in the tool layer (B7) is a
    direct translation of the JS version.

    Parameters
    ----------
    ggsr
        Configured :class:`GGSRTraversal` instance. Its injected graph
        adapter is how the engine reaches Neptune (or a legacy Neo4j
        adapter, via :mod:`src.data.backend_selector`).
    vector_db
        Optional :class:`~src.data.protocols.VectorDBProtocol` adapter.
        When ``None`` the engine degrades to graph-only retrieval — the
        ``semantic_hits`` list comes back empty and ``metadata`` flags
        it via ``semantic_available=False``.
    default_collection
        Collection name passed to ``vector_db.query`` when the caller
        doesn't override it.
    """

    def __init__(
        self,
        ggsr: GGSRTraversal,
        vector_db: VectorDBProtocol | None = None,
        *,
        default_collection: str = DEFAULT_SEMANTIC_COLLECTION,
    ) -> None:
        self._ggsr = ggsr
        self._vector_db = vector_db
        self._default_collection = default_collection

    # ── public API ───────────────────────────────────────────────────

    async def get_code_context(
        self,
        entity: str,
        *,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        max_results: int = 15,
        hops: int = 1,
        collection: str | None = None,
        max_semantic_hits: int = 5,
        similarity_threshold: float = 0.1,
        extra_semantic_keys: Iterable[str] | None = None,
        tenant: Any = None,
    ) -> GGSRRetrievalResult:
        """Retrieve graph neighbourhood + semantic context for ``entity``.

        The two retrievals run **in parallel** via :func:`asyncio.gather`
        — same as ``Promise.all`` in the Node.js original — so tool
        latency is ``max(graph_ms, vector_ms)`` rather than their sum.

        Parameters
        ----------
        entity
            Seed node name / identifier.
        token_budget
            Propagated to :pymeth:`GGSRTraversal.budget_aware_neighborhood`.
        max_results
            Max scored neighbours kept after budget trimming.
        tenant
            The active Tenant (or ``None`` for the unprefixed default),
            forwarded to the semantic enrichment query
            (shared-scope-query-routing R1.5, R2.5). Without it the
            vector read resolves as the Default_Tenant regardless of
            which tenant is actually active — tenancy would be bypassed
            rather than merely degraded.
        hops
            ``1`` or ``2``.
        collection
            Overrides :data:`DEFAULT_SEMANTIC_COLLECTION` for this call.
        max_semantic_hits
            ``k`` for the vector query.
        similarity_threshold
            Minimum vector score (0.0 – 1.0).
        extra_semantic_keys
            Identifiers beyond ``entity`` itself to use as semantic
            probes (typically the top graph-neighbour names). Duplicates
            and blanks are removed; an empty iterable falls back to just
            the entity.

        Returns
        -------
        GGSRRetrievalResult
            A populated result — never raises for individual sub-query
            failures; those are reflected in ``metadata``.
        """
        coll = collection or self._default_collection

        graph_coro = self._safe_graph_neighborhood(
            entity,
            token_budget=token_budget,
            max_results=max_results,
            hops=hops,
        )
        vector_coro = self._safe_semantic_enrich(
            entity,
            coll,
            max_semantic_hits,
            similarity_threshold,
            extra_semantic_keys,
            tenant,
        )

        ggsr_results, (semantic_hits, semantic_meta) = await asyncio.gather(
            graph_coro, vector_coro
        )

        metadata = {
            "ggsr_count": len(ggsr_results),
            "semantic_count": len(semantic_hits),
            "used_tokens": sum(r.estimated_tokens for r in ggsr_results),
            "token_budget": token_budget,
            "hops": hops,
            "collection": coll,
            "semantic_available": self._vector_db is not None,
            **semantic_meta,
        }
        return GGSRRetrievalResult(
            entity=entity,
            ggsr_results=ggsr_results,
            semantic_hits=semantic_hits,
            metadata=metadata,
        )

    # Alias kept for parity with the Node.js method name.
    retrieve = get_code_context

    # ── internals ────────────────────────────────────────────────────

    async def _safe_graph_neighborhood(
        self,
        entity: str,
        *,
        token_budget: int,
        max_results: int,
        hops: int,
    ) -> list[GGSRScoredResult]:
        try:
            return await self._ggsr.budget_aware_neighborhood(
                entity,
                token_budget=token_budget,
                max_results=max_results,
                hops=hops,
            )
        except Exception as exc:  # pragma: no cover - defensive
            log.warning(
                "GGSR neighbourhood failed for %r: %s", entity, exc
            )
            return []

    async def _safe_semantic_enrich(
        self,
        entity: str,
        collection: str,
        k: int,
        similarity_threshold: float,
        extra_keys: Iterable[str] | None,
        tenant: Any = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Run the vector query, swallowing failures into metadata flags.

        Parameters
        ----------
        tenant
            Forwarded verbatim to ``vector_db.query(..., tenant=tenant)``
            (shared-scope-query-routing R1.5, R2.5). Defaults to ``None``
            so existing callers that do not pass a tenant keep today's
            unprefixed-default behaviour exactly.
        """
        if self._vector_db is None:
            return [], {"semantic_error": "vector_db_unavailable"}

        # Build the probe text: the entity plus any extra keys the caller
        # surfaced from the graph side. Deduplicate, preserving order.
        probes: list[str] = []
        seen: set[str] = set()
        for raw in (entity, *(extra_keys or ())):
            if not raw:
                continue
            key = str(raw).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            probes.append(key)

        query_text = " ".join(probes) if probes else entity
        try:
            hits = await self._vector_db.query(
                collection,
                query_text,
                k=k,
                similarity_threshold=similarity_threshold,
                include_graph=False,
                tenant=tenant,
            )
            # Defensive: adapters should already return list[dict] but
            # coerce None → [] so callers never see a surprise.
            return list(hits or []), {}
        except Exception as exc:
            log.warning(
                "Semantic enrichment failed for %r on %s: %s",
                entity,
                collection,
                exc,
            )
            return [], {"semantic_error": str(exc)}


__all__ = [
    "GraphGuidedRetrieval",
    "GGSRRetrievalResult",
    "DEFAULT_SEMANTIC_COLLECTION",
]
