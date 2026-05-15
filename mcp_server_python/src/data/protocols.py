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

# Keys every search result is guaranteed to contain
# (see :pyclass:`src.data.opensearch_adapter.OpenSearchAdapter._format_hits`).
VECTOR_RESULT_KEYS: frozenset[str] = frozenset({"id", "content", "metadata", "score"})


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

        Returns
        -------
        list[dict]
            Each dict has at minimum the keys in
            :data:`VECTOR_RESULT_KEYS`.
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
