"""OpenSearch source reader (Task 6).

Reads every targeted OpenSearch index document-by-document using the scroll
(scan) API and enumerates the Index_Family per tenant from the index naming
convention. The embedding vector is read bitwise from the source document and
passed through untouched (R5.1, R5.2) -- this reader never re-embeds.

The adapter operates on an injected low-level client modelled on the
``opensearch-py`` surface so unit tests can supply an in-memory fake and assert
the read-only invariant (Property 5): only ``list_indices`` / ``search`` /
``scroll`` / ``clear_scroll`` are ever called -- no ``index`` / ``bulk`` /
``delete`` / ``update`` / ``create``.

The baseline ``gw`` tenant owns the unprefixed ``mdc-*`` indices; a non-default
tenant owns ``<index_prefix>mdc-*`` (R7.2, R7.3).

Requirements: 1.1, 1.5, 7.1, 7.2, 7.3.
"""

from __future__ import annotations

from typing import Any, Iterator, Optional

#: openCypher / OpenSearch read-only method allow-list (Property 5 guard).
READ_ONLY_METHODS: frozenset[str] = frozenset(
    {"list_indices", "search", "scroll", "clear_scroll", "count"}
)

#: Default document batch size for scroll.
DEFAULT_BATCH: int = 500

#: Scroll keep-alive window.
SCROLL_TTL: str = "2m"

#: Prefix shared by every managed index.
_INDEX_BASE_PREFIX = "mdc-"


class OpenSearchReader:
    """Read-only scroll reader over OpenSearch indices.

    Parameters
    ----------
    client
        Low-level client exposing ``list_indices()`` and the scroll trio
        ``search`` / ``scroll`` / ``clear_scroll``. Injected so tests use a
        fake; production wires an ``opensearch-py`` client.
    index_prefixes
        Mapping ``tenant_id -> index_prefix`` for every tenant (from the
        Tenant_Catalog). Used to resolve and to *exclude* foreign prefixes for
        the default tenant.
    """

    def __init__(
        self,
        client: Any,
        *,
        index_prefixes: dict[str, str],
    ) -> None:
        self._client = client
        self._index_prefixes = dict(index_prefixes)

    # ── Index_Family enumeration ──────────────────────────────────────

    def _all_indices(self) -> list[str]:
        return list(self._client.list_indices())

    def _non_default_prefixes(self) -> list[str]:
        return [p for p in self._index_prefixes.values() if p]

    def index_family_for_tenant(self, tenant_id: str) -> list[str]:
        """Return the Index_Family (concrete index names) for one tenant."""
        prefix = self._index_prefixes.get(tenant_id, "")
        indices = self._all_indices()
        if prefix:
            return sorted(
                i for i in indices if i.startswith(f"{prefix}{_INDEX_BASE_PREFIX}")
            )
        # Default tenant: unprefixed mdc-* indices, excluding any that carry a
        # known foreign (non-default) tenant prefix.
        foreign = self._non_default_prefixes()
        out = []
        for i in indices:
            if not i.startswith(_INDEX_BASE_PREFIX):
                continue
            if any(i.startswith(f"{fp}{_INDEX_BASE_PREFIX}") for fp in foreign):
                continue
            out.append(i)
        return sorted(out)

    def list_index_families(self, tenants: list[str]) -> list[str]:
        """Return the union of Index_Families across ``tenants`` (R7.1)."""
        seen: list[str] = []
        for t in tenants:
            for idx in self.index_family_for_tenant(t):
                if idx not in seen:
                    seen.append(idx)
        return seen

    # ── document scroll ──────────────────────────────────────────────

    def count_index(self, index: str) -> int:
        """Return the document count for ``index`` (preflight counts)."""
        resp = self._client.count(index=index)
        return int(resp.get("count", 0))

    def scroll_records(
        self, index: str, batch: int = DEFAULT_BATCH
    ) -> Iterator[list[dict]]:
        """Yield batches of normalized Vector_Export records for ``index``.

        Each record is ``{id, content, embedding, metadata, model_profile,
        collection_name, chunk_id}``. The embedding is read verbatim from the
        source ``_source`` and never recomputed (R5.1, R5.2).
        """
        resp = self._client.search(
            index=index,
            scroll=SCROLL_TTL,
            size=batch,
            body={"query": {"match_all": {}}},
        )
        scroll_id = resp.get("_scroll_id")
        try:
            while True:
                hits = resp.get("hits", {}).get("hits", [])
                if not hits:
                    break
                yield [self._to_record(h, index) for h in hits]
                resp = self._client.scroll(scroll_id=scroll_id, scroll=SCROLL_TTL)
                scroll_id = resp.get("_scroll_id", scroll_id)
        finally:
            if scroll_id is not None:
                self._client.clear_scroll(scroll_id=scroll_id)

    @staticmethod
    def _to_record(hit: dict, index: str) -> dict:
        src = dict(hit.get("_source", {}))
        embedding = src.get("embedding") or src.get("vector")
        model_profile = (
            src.get("model_profile")
            or src.get("metadata", {}).get("model_profile")
        )
        metadata = src.get("metadata", {})
        return {
            "id": hit.get("_id") or src.get("id"),
            "content": src.get("content") or src.get("text") or src.get("document"),
            "embedding": embedding,
            "metadata": metadata,
            "model_profile": model_profile,
            "collection_name": src.get("collection_name") or index,
            "chunk_id": src.get("chunk_id") or metadata.get("chunk_id"),
        }

    # protocol stubs delegated to the Neptune reader in practice -- present so
    # an OpenSearchReader satisfies the structural SourceReader where only the
    # vector half is exercised.
    def list_graph_label_families(self, tenants: list[str]) -> list[str]:
        return []

    def stream_nodes(self, tenant: str):  # pragma: no cover - vector-only reader
        return iter(())

    def stream_relationships(self, tenant: str):  # pragma: no cover
        return iter(())

    def read_dedupe_registry(self):  # pragma: no cover
        return iter(())


__all__ = ["OpenSearchReader", "READ_ONLY_METHODS", "DEFAULT_BATCH", "SCROLL_TTL"]
