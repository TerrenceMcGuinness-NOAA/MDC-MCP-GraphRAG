"""Graph-Guided Semantic Retrieval (GGSR) traversal engine (Requirement 6.6).

Pure-Python port of the scoring / budget logic from
``mcp_server_node/src/graphrag/GGSRTraversalPrototypes.js``. This module is
deliberately a "thin" engine: it owns

* the relationship ``WEIGHT_MATRIX`` (how important each edge type is),
* the ``HOP_DECAY`` multiplier (how much to penalise far-away neighbours),
* ``_score_results`` (apply weight × decay^hop and sort),
* ``_trim_to_budget`` (greedy cap on total estimated tokens), and
* ``budget_aware_neighborhood`` (orchestrates a multi-hop query + scoring +
  trimming through an injected graph adapter).

It does **not** format markdown, classify queries, or touch a vector
store — those responsibilities live in
:pyclass:`src.graphrag.graph_guided_retrieval.GraphGuidedRetrieval`.

Weight matrix and hop decay values are copied verbatim from the
authoritative Node.js source
``mcp_server_node/src/graphrag/GGSRTraversalPrototypes.js`` so that the
Python port produces identical scores for the parity framework (Task 7).
Unknown relationship types fall back to :data:`DEFAULT_WEIGHT` so an
unexpected edge does not crash scoring — it just contributes little.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from src.data.protocols import GraphDBProtocol

log = logging.getLogger(__name__)


# ── constants ─────────────────────────────────────────────────────────────

# Relationship weight matrix — must match Node.js RELATIONSHIP_WEIGHTS in
# mcp_server_node/src/graphrag/GGSRTraversalPrototypes.js exactly. Any
# divergence breaks parity tests in Task 7. Phase 34C added NCEPLIBS edge
# types (PROVIDED_BY, TRANSITIVELY_DEPENDS, DOCUMENTED_BY, REQUIRES_VERSION).
WEIGHT_MATRIX: dict[str, float] = {
    "CALLS":                1.0,
    "EXECUTES":             1.0,
    "SOURCES":              0.95,
    "INVOKES":              0.9,
    "CALLED_BY":            0.9,
    "DEPENDS_ON":           0.8,
    "DEPENDS_ON_ENV":       0.8,
    "IMPORTS":              0.7,
    "USES":                 0.7,
    "INHERITS":             0.7,
    "DEFINES":              0.65,
    "PROVIDED_BY":          0.6,   # Phase 34C: Fortran USE → NCEPLIBS ExternalLibrary
    "EXPORTS":              0.6,
    "DOC_REFERENCES":       0.6,
    "DOC_DESCRIBES":        0.55,
    "TRANSITIVELY_DEPENDS": 0.5,   # Phase 34C: indirect library deps
    "HAS_METHOD":           0.5,
    "CONTAINS":             0.5,
    "SETS":                 0.5,
    "DOCUMENTED_BY":        0.4,   # Phase 34C: graph node → ChromaDB doc
    "SAME_DIRECTORY":       0.4,
    "BUILT_BY":             0.35,
    "BUILD_ORCHESTRATES":   0.35,
    "REQUIRES_VERSION":     0.3,   # Phase 34C: platform version constraints
    "AUTHORED":             0.3,
    "AUTHORED_BY":          0.3,
    "CONTRIBUTED_TO":       0.3,
}

# Penalty applied for each additional hop from the seed entity.
# score = weight × HOP_DECAY ** hop_distance  (hop_distance ≥ 1)
HOP_DECAY: float = 0.5

# Cross-language bridge hops (Shell↔Fortran↔Python) get a reduced penalty
# because those edges represent meaningful execution handoffs, not incidental
# proximity. Used in place of HOP_DECAY when traversing an EXECUTES or
# INVOKES edge that crosses a language boundary. Phase 24F.
BRIDGE_DECAY_OVERRIDE: float = 0.8

# Fallback weight for relationship types missing from WEIGHT_MATRIX.
DEFAULT_WEIGHT: float = 0.3

# Default cap on tokens the engine will emit per invocation.
DEFAULT_TOKEN_BUDGET: int = 4000


# ── data models ───────────────────────────────────────────────────────────


@dataclass
class GGSRScoredResult:
    """One scored graph neighbour produced by the traversal engine.

    Mirrors the design's ``GGSRScoredResult`` with the fields tool modules
    actually read. Kept as a plain (non-frozen) dataclass because scoring
    attaches ``score`` / ``estimated_tokens`` after the initial query.
    """

    name: str
    relationship: str
    hop_distance: int
    weight: float = 0.0
    score: float = 0.0
    estimated_tokens: int = 0
    path: str | None = None
    labels: list[str] = field(default_factory=list)
    # Keep the raw record for tool layers that want additional fields.
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "relationship": self.relationship,
            "hop_distance": self.hop_distance,
            "weight": self.weight,
            "score": self.score,
            "estimated_tokens": self.estimated_tokens,
            "path": self.path,
            "labels": list(self.labels),
        }


# ── helpers ───────────────────────────────────────────────────────────────


def estimate_tokens(text: str | None) -> int:
    """Rough token count using the ``words × 1.3`` heuristic from Node.js.

    Mirrors ``GGSRTraversalPrototypes.estimateTokens`` so Python and
    Node.js sides agree on budget accounting within ~10% for English code.
    """
    if not text:
        return 0
    words = [w for w in text.split() if w]
    # Match Node.js Math.ceil(words * 1.3)
    return -(-len(words) * 13 // 10)  # ceil(words*1.3) without float


def estimate_row_tokens(result: GGSRScoredResult | dict[str, Any]) -> int:
    """Token estimate for a single table-row rendering of a scored result.

    Matches Node.js ``_estimateRowTokens``: ``15 + len(name) / 4`` ceil.
    """
    name = result.name if isinstance(result, GGSRScoredResult) else (
        result.get("name") or result.get("neighbor") or ""
    )
    # ceil(15 + len/4) == 15 + ceil(len/4)
    return 15 + (-(-len(name) // 4))


# ── traversal engine ─────────────────────────────────────────────────────


class GGSRTraversal:
    """Budget-aware graph-guided neighbourhood traversal.

    Parameters
    ----------
    graph_db
        Anything that implements :class:`~src.data.protocols.GraphDBProtocol`.
        In production this is ``NeptuneAdapter``; tests inject a mock.

    The engine is stateless beyond the graph handle — scoring is a pure
    function of the relationship type and hop distance of each result.
    """

    weight_matrix: dict[str, float] = WEIGHT_MATRIX
    hop_decay: float = HOP_DECAY
    default_weight: float = DEFAULT_WEIGHT

    def __init__(self, graph_db: GraphDBProtocol):
        self._graph = graph_db

    # ── public API ────────────────────────────────────────────────────

    async def budget_aware_neighborhood(
        self,
        entity: str,
        *,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        max_results: int = 50,
        hops: int = 1,
        min_weight: float = 0.0,
    ) -> list[GGSRScoredResult]:
        """Fetch, score, and budget-trim the neighbourhood of ``entity``.

        Parameters
        ----------
        entity
            Node name / identifier to anchor traversal. Matched with a
            case-insensitive ``CONTAINS`` against the ``name`` property,
            mirroring the Node.js implementation's flexible match.
        token_budget
            Maximum estimated tokens of scored rows to return. The engine
            accumulates highest-scored rows first and stops when the next
            row would exceed the budget.
        max_results
            Upper bound on the number of candidate neighbours fetched
            from the graph before scoring. Tightens latency for very
            popular entities.
        hops
            ``1`` or ``2``. Two-hop traversal applies one additional
            multiplication by :data:`HOP_DECAY`.
        min_weight
            Results with a scored value below this threshold are
            discarded. ``0.0`` keeps everything (default).

        Returns
        -------
        list[GGSRScoredResult]
            Sorted by ``score`` descending, trimmed to ``token_budget``.

        Notes
        -----
        The engine is defensive: any graph-side error yields an empty
        list rather than propagating, matching the Node.js behaviour of
        degraded-but-available context retrieval.
        """
        if hops not in (1, 2):
            raise ValueError(f"hops must be 1 or 2, got {hops}")
        if token_budget < 0:
            raise ValueError(f"token_budget must be >= 0, got {token_budget}")
        if max_results < 0:
            raise ValueError(f"max_results must be >= 0, got {max_results}")
        if not entity:
            return []

        try:
            raw = await self._multi_hop_query(entity, hops=hops, limit=max_results * 2)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("GGSR graph query failed for %r: %s", entity, exc)
            return []

        scored = self._score_results(raw)
        if min_weight > 0.0:
            scored = [r for r in scored if r.score >= min_weight]
        scored = scored[:max_results]
        return self._trim_to_budget(scored, token_budget)

    # ── pure helpers (unit-testable without a graph) ─────────────────

    def _score_results(
        self, raw_results: list[dict[str, Any]]
    ) -> list[GGSRScoredResult]:
        """Score a list of raw graph records and return them sorted desc.

        Each record is expected to carry at least ``name`` and
        ``relationship``; ``hop_distance`` defaults to ``1`` if missing.
        The scoring formula is::

            score = WEIGHT_MATRIX.get(rel, DEFAULT_WEIGHT) * HOP_DECAY ** hop_distance

        and is identical for 1-hop and 2-hop results (the hop count
        itself encodes the chain length, see Property 9).
        """
        scored: list[GGSRScoredResult] = []
        for r in raw_results:
            # Accept multiple naming conventions to match the variety of
            # cypher RETURN clauses in the codebase.
            name = (
                r.get("name")
                or r.get("neighbor")
                or r.get("target")
                or ""
            )
            relationship = (
                r.get("relationship")
                or r.get("relType")
                or r.get("type")
                or "UNKNOWN"
            )
            hop_distance = int(
                r.get("hop_distance")
                or r.get("hop")
                or r.get("depth")
                or 1
            )
            if hop_distance < 1:
                hop_distance = 1

            weight = self.weight_matrix.get(relationship, self.default_weight)
            score = weight * (self.hop_decay ** hop_distance)

            scored.append(
                GGSRScoredResult(
                    name=name,
                    relationship=relationship,
                    hop_distance=hop_distance,
                    weight=weight,
                    score=score,
                    path=r.get("path") or r.get("filepath"),
                    labels=list(r.get("labels") or []),
                    raw=r,
                )
            )

        scored.sort(key=lambda x: x.score, reverse=True)
        return scored

    def _trim_to_budget(
        self,
        scored: list[GGSRScoredResult],
        token_budget: int,
    ) -> list[GGSRScoredResult]:
        """Return the prefix of ``scored`` whose total tokens fit the budget.

        Greedy — consumes highest-scored rows first and stops as soon as
        the next row would exceed ``token_budget``. Results beyond the
        cut-off are dropped, not reordered. A row's own token estimate is
        cached on the returned object as ``estimated_tokens``.
        """
        if token_budget <= 0:
            return []

        total = 0
        kept: list[GGSRScoredResult] = []
        for row in scored:
            tokens = estimate_row_tokens(row)
            if total + tokens > token_budget:
                break
            row.estimated_tokens = tokens
            total += tokens
            kept.append(row)
        return kept

    # ── graph I/O ─────────────────────────────────────────────────────

    async def _multi_hop_query(
        self, entity: str, *, hops: int, limit: int
    ) -> list[dict[str, Any]]:
        """Issue a 1- or 2-hop neighbourhood query.

        The cypher here is a Neptune-compatible port of the Node.js
        ``oneHopNeighborhood`` / ``twoHopNeighborhood`` queries: no
        regex operators, ``toLower($baseName) CONTAINS`` for matching.
        """
        limit = max(1, int(limit))
        base_name = entity

        from src.tenancy.resolver import get_current_tenant_or_none, tenant_label_predicate
        ctx = get_current_tenant_or_none()
        tenant_obj = ctx.tenant if ctx else None

        pred_n = tenant_label_predicate("n")
        scope_n = f" AND {pred_n}" if pred_n else ""

        pred_hop1 = tenant_label_predicate("hop1")
        scope_hop1 = f" AND {pred_hop1}" if pred_hop1 else ""

        if hops == 1:
            cypher = (
                "MATCH (n)-[r]-(hop1) "
                "WHERE toLower(apoc.text.join([x IN apoc.convert.toList(n.name) | toString(x)], ' ')) CONTAINS toLower($baseName) "
                f"{scope_n}{scope_hop1} "
                "RETURN n.name AS source, "
                "type(r) AS relationship, "
                "hop1.name AS name, "
                "labels(hop1) AS labels, "
                "hop1.filepath AS path, "
                "1 AS hop_distance "
                f"LIMIT {limit}"
            )
            rows = await self._graph.query(cypher, {"baseName": base_name}, tenant=tenant_obj)
            return list(rows or [])

        # hops == 2 — emit flattened records for both legs
        pred_hop2 = tenant_label_predicate("hop2")
        scope_hop2 = f" AND {pred_hop2}" if pred_hop2 else ""
        cypher = (
            "MATCH (n)-[r1]-(hop1) "
            "WHERE toLower(apoc.text.join([x IN apoc.convert.toList(n.name) | toString(x)], ' ')) CONTAINS toLower($baseName) "
            f"{scope_n}{scope_hop1} "
            "OPTIONAL MATCH (hop1)-[r2]-(hop2) "
            f"WHERE hop2 <> n{scope_hop2} "
            "RETURN n.name AS source, "
            "type(r1) AS rel1, hop1.name AS hop1Name, "
            "labels(hop1) AS hop1Labels, hop1.filepath AS hop1Path, "
            "type(r2) AS rel2, hop2.name AS hop2Name, "
            "labels(hop2) AS hop2Labels, hop2.filepath AS hop2Path "
            f"LIMIT {limit}"
        )
        rows = await self._graph.query(cypher, {"baseName": base_name}, tenant=tenant_obj)

        flattened: list[dict[str, Any]] = []
        seen: set[str] = set()
        for r in rows or []:
            hop1_name = r.get("hop1Name")
            if hop1_name and hop1_name not in seen:
                seen.add(hop1_name)
                flattened.append(
                    {
                        "name": hop1_name,
                        "relationship": r.get("rel1") or "UNKNOWN",
                        "hop_distance": 1,
                        "labels": r.get("hop1Labels") or [],
                        "path": r.get("hop1Path"),
                    }
                )
            hop2_name = r.get("hop2Name")
            if hop2_name and hop2_name != entity and hop2_name not in seen:
                seen.add(hop2_name)
                # Use the *second* relationship type for scoring at hop 2;
                # the decay factor applies to hop_distance directly.
                flattened.append(
                    {
                        "name": hop2_name,
                        "relationship": r.get("rel2") or "UNKNOWN",
                        "hop_distance": 2,
                        "labels": r.get("hop2Labels") or [],
                        "path": r.get("hop2Path"),
                    }
                )
        return flattened


__all__ = [
    "GGSRTraversal",
    "GGSRScoredResult",
    "WEIGHT_MATRIX",
    "HOP_DECAY",
    "BRIDGE_DECAY_OVERRIDE",
    "DEFAULT_WEIGHT",
    "DEFAULT_TOKEN_BUDGET",
    "estimate_tokens",
    "estimate_row_tokens",
]
