"""OpenSearch target writer (Task 7).

Re-imports Vector_Export records into OpenSearch. Before writing vectors into
an index the writer ensures the index exists with a ``knn_vector`` mapping
whose dimension matches the Model_Profile (R3.3). If a target index already
exists with an incompatible mapping (wrong dimension / wrong field type) the
writer reports the conflict and refuses to write (R3.5). Embedding bytes are
indexed verbatim -- never recomputed (R5.3).

The adapter operates on an injected low-level client modelled on the
``opensearch-py`` surface (``indices.exists`` / ``indices.get_mapping`` /
``indices.create`` / ``bulk``) so unit tests inject a fake.

Requirements: 3.1, 3.3, 3.4, 3.5, 5.3.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from portable_export.config import model_profile_dimensions

#: OpenSearch field that holds the embedding vector.
EMBEDDING_FIELD: str = "embedding"


class MappingConflictError(Exception):
    """A target index exists with a mapping incompatible with the profile (R3.5)."""

    def __init__(self, index: str, reason: str) -> None:
        super().__init__(f"index {index!r} mapping conflict: {reason}")
        self.index = index
        self.reason = reason


def knn_index_body(dimensions: int) -> dict[str, Any]:
    """Return the index create body with a ``knn_vector`` mapping (R3.3)."""
    return {
        "settings": {"index": {"knn": True}},
        "mappings": {
            "properties": {
                EMBEDDING_FIELD: {"type": "knn_vector", "dimension": dimensions},
                "content": {"type": "text"},
                "model_profile": {"type": "keyword"},
                "collection_name": {"type": "keyword"},
                "metadata": {"type": "object", "enabled": True},
            }
        },
    }


class OpenSearchWriter:
    """Index-ensuring, conflict-refusing bulk vector writer.

    Parameters
    ----------
    client
        Low-level client with ``index_exists`` / ``get_mapping`` /
        ``create_index`` / ``bulk`` / ``count`` methods. Injected for tests.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    def _existing_dimension(self, index: str) -> Optional[int]:
        mapping = self._client.get_mapping(index=index)
        # mapping shape: {index: {"mappings": {"properties": {embedding: {...}}}}}
        props = (
            mapping.get(index, {})
            .get("mappings", {})
            .get("properties", {})
        )
        field = props.get(EMBEDDING_FIELD)
        if not field:
            return None
        if field.get("type") != "knn_vector":
            raise MappingConflictError(
                index, f"field {EMBEDDING_FIELD!r} is {field.get('type')!r}, "
                f"not knn_vector"
            )
        return int(field.get("dimension"))

    def ensure_collection_or_index(self, name: str, model_profile: str) -> str:
        """Ensure ``name`` exists with a knn_vector mapping for ``model_profile``.

        Raises
        ------
        MappingConflictError
            If the index exists with a different dimension or a non-knn_vector
            embedding field (R3.5).
        """
        dims = model_profile_dimensions(model_profile)
        if self._client.index_exists(index=name):
            existing = self._existing_dimension(name)
            if existing is not None and existing != dims:
                raise MappingConflictError(
                    name,
                    f"existing dimension {existing} != profile "
                    f"{model_profile} dimension {dims}",
                )
            return name
        self._client.create_index(index=name, body=knn_index_body(dims))
        return name

    def bulk_insert_vectors(
        self, collection: str, records: Iterable[dict]
    ) -> int:
        """Bulk-index ``records`` into ``collection`` preserving embeddings.

        Returns the number of records sent. The embedding value is passed
        through verbatim (R5.3) -- no normalization / quantization.
        """
        actions: list[dict] = []
        count = 0
        for rec in records:
            actions.append({"index": {"_index": collection, "_id": rec["id"]}})
            actions.append(
                {
                    "id": rec["id"],
                    "content": rec.get("content"),
                    EMBEDDING_FIELD: rec["embedding"],
                    "metadata": rec.get("metadata", {}),
                    "model_profile": rec.get("model_profile"),
                    "collection_name": rec.get("collection_name", collection),
                    "chunk_id": rec.get("chunk_id"),
                }
            )
            count += 1
        if actions:
            self._client.bulk(body=actions)
        return count

    def count_collection(self, collection: str) -> int:
        return int(self._client.count(index=collection).get("count", 0))


__all__ = [
    "OpenSearchWriter",
    "MappingConflictError",
    "knn_index_body",
    "EMBEDDING_FIELD",
]
