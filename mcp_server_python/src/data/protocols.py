"""Database adapter protocols (Requirements 2.1, 3.1).

These ``Protocol`` classes define the async interface contract between
tool modules and whichever backend is wired in by
``src.data.backend_selector``. They are the structural-typing equivalent
of the Node.js ``VectorDatabaseAdapter`` / ``GraphDatabaseAdapter`` base
classes.

Tool modules should depend on the protocol, not on a concrete adapter:

.. code-block:: python

    async def search(data: VectorDBProtocol, q: str) -> list[dict]:
        return await data.query("mdc-workflow-docs-mpnet768", q, k=5)

Marked ``@runtime_checkable`` so tests can use ``isinstance(adapter,
VectorDBProtocol)`` when mocking.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from src.data.read_router import CollectionCondition

# Keys every search result is guaranteed to contain
# (see :pyclass:`src.data.opensearch_adapter.OpenSearchAdapter._format_hits`).
#
# ``physical_collection`` (shared-scope-query-routing Task 7.1, R3.5) is a
# NEW key, not yet populated by either adapter -- Task 7.3 (the next,
# atomic step) is what stamps it onto every returned hit. It is declared
# here now so the protocol documents the target shape. It is deliberately
# a *separate* key from the pre-existing ``collection``: ``collection``
# carries the *logical* collection name and is rendered verbatim by
# ``semantic_search._format_search_hit``
# (``source_line += f" | **Collection:** {collection_name}"``), so
# repurposing it would move default-tenant (``gw``) response bytes and
# violate the R6.2 byte-equivalence invariant. ``physical_collection``
# will carry the *physical* name of the member that produced the hit.
VECTOR_RESULT_KEYS: frozenset[str] = frozenset(
    {"id", "content", "metadata", "score", "physical_collection"}
)


@runtime_checkable
class VectorDBProtocol(Protocol):
    """Interface for vector database operations (R2.1 – R2.7).

    Concrete implementations: :pyclass:`OpenSearchAdapter`,
    :pyclass:`ChromaDBLegacyAdapter` (Phase B2 / B12 respectively).
    """

    async def connect(self) -> None:
        """Open the underlying connection pool.

        Implementations MUST be idempotent — calling ``connect()`` on an
        already-connected adapter is a no-op.
        """
        ...

    async def query(
        self,
        collection: str,
        query_text: str,
        *,
        k: int = 10,
        similarity_threshold: float = 0.0,
        where: dict[str, Any] | None = None,
        include_graph: bool = True,
        tenant: Any = None,
    ) -> list[dict[str, Any]]:
        """Execute hybrid BM25 + k-NN search against a single collection.

        Parameters
        ----------
        collection
            Logical collection name (e.g. ``code-with-context-v8-0-0``).
            The adapter maps it to a concrete index via
            :pyfunc:`src.config.aws_config.resolve_index`.
        query_text
            User query string. Adapters are responsible for generating
            embeddings when required.
        k
            Maximum number of hits to return.
        similarity_threshold
            Minimum score (0.0 – 1.0) for a hit to be returned.
        where
            Optional ChromaDB-style metadata filter.
        include_graph
            When ``True`` and a graph adapter is also available, the
            tool layer may enrich each hit with graph context. The
            vector adapter itself never performs graph lookups.
        tenant
            The active :class:`~src.config.tenants.Tenant`, or ``None``
            for the unprefixed Default_Tenant. Documents existing
            reality rather than introducing new behaviour
            (shared-scope-query-routing Task 7.1): both
            :class:`~src.data.chromadb_adapter.ChromaDBAdapter` and
            :class:`~src.data.opensearch_adapter.OpenSearchAdapter`
            already accept this keyword and every tool call site already
            passes it via ``_tenant()``. Declaring it here closes a
            latent drift between the protocol and its implementations,
            it does not create a parameter.

        Returns
        -------
        list[dict]
            Each dict has at minimum the keys in
            :data:`VECTOR_RESULT_KEYS`, including ``physical_collection``
            -- the physical collection name that produced the hit, drawn
            from the Resolved_Collection_Set the read addressed. This key
            is additive; the pre-existing ``collection``, ``id``,
            ``content``, ``metadata``, and ``score`` keys are unchanged
            in name and meaning.
        """
        ...

    async def multi_collection_query(
        self,
        collections: list[str],
        query_text: str,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Query several collections and merge results by score descending.

        All keyword arguments are forwarded to :pymeth:`query`.
        """
        ...

    async def health_check(self, *, deep: bool = False) -> dict[str, Any]:
        """Return a status dictionary describing adapter health.

        The returned dict SHOULD include at least ``status``
        (``"healthy"`` | ``"degraded"`` | ``"unhealthy"``) and
        ``connected`` (bool).
        """
        ...

    async def count_documents(self, collection: str) -> int:
        """Return the number of documents in ``collection`` (0 if missing).

        Implementations MUST be non-raising: a missing collection/index
        yields ``0`` rather than an exception, so observability tools
        (``get_knowledge_base_status``, ``list_all_sources --include_gaps``)
        can dispatch through this method on any backend without branching on
        backend type (cots-backend-observability-parity R1, R6).
        """
        ...

    async def sample_metadata(
        self, collection: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Return up to ``limit`` document-metadata dicts for integrity sampling.

        When ``collection`` is ``None`` the adapter samples across all
        collections up to ``limit`` total. Returns ``[]`` for an empty or
        missing collection (never raises). Used by
        ``check_knowledge_integrity``'s Path-Consistency and Stale-Embeddings
        sub-checks (cots-backend-observability-parity R2, R6).
        """
        ...

    async def collection_condition(
        self, physical_collection: str
    ) -> CollectionCondition:
        """Classify one physical collection's Collection_Condition (R7.8).

        shared-scope-query-routing Task 7.2. Returns
        :attr:`CollectionCondition.UNPROVISIONED`,
        :attr:`CollectionCondition.PROVISIONED_EMPTY`, or
        :attr:`CollectionCondition.PROVISIONED_POPULATED` for
        ``physical_collection`` -- already a resolved physical name, not
        a Logical_Collection. Backed by the existing non-raising
        :pymeth:`count_documents`; never issues a mutating call and
        never raises (Requirement 12.5).

        Parameters
        ----------
        physical_collection
            The concrete OpenSearch index or ChromaDB collection name to
            classify, e.g. ``"gw_v17_mdc-ee2-standards-titan1024"``.

        Returns
        -------
        CollectionCondition
            The three-way classification. ``PROVISIONED_POPULATED`` is
            returned for a collection holding one or more documents even
            when the *triggering read* matched none of them -- this
            method answers "does this collection hold anything", not
            "did the query match".
        """
        ...

    async def close(self) -> None:
        """Release all sockets/connections held by the adapter.

        Must be safe to call even when ``connect()`` was never called.
        """
        ...


@runtime_checkable
class GraphDBProtocol(Protocol):
    """Interface for graph database operations (R3.1 – R3.7).

    Concrete implementations: :pyclass:`NeptuneAdapter`,
    :pyclass:`Neo4jLegacyAdapter` (Phase B2 / B12 respectively).
    """

    async def connect(self) -> None:
        """Open the underlying driver / connection pool (idempotent)."""
        ...

    async def query(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a parameterized openCypher query.

        Parameters
        ----------
        cypher
            openCypher query string.
        params
            Named parameters referenced by the query; values may be
            ``str``, ``int``, ``float``, ``bool``, or ``list`` thereof.

        Returns
        -------
        list[dict]
            One dict per result row; keys match the ``RETURN`` aliases
            in the query.
        """
        ...

    async def health_check(self) -> dict[str, Any]:
        """Return a status dictionary describing adapter health."""
        ...

    async def close(self) -> None:
        """Release the driver / connection pool (idempotent)."""
        ...
