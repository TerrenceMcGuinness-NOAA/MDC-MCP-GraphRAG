"""Cross-backend missing-collection error normalization.

shared-scope-query-routing Task 4. Both :class:`~src.data.chromadb_adapter.
ChromaDBAdapter` and :class:`~src.data.opensearch_adapter.OpenSearchAdapter`
raise :class:`CollectionNotProvisionedError` when a query addresses a
physical collection absent from the active backend, so the tool layer's
missing-index classifier (``src.tools._common._is_missing_index_exc``) no
longer has to understand two incompatible client exception taxonomies.

This module is deliberately dependency-light: it imports neither adapter,
so both may import it without a cycle.
"""

from __future__ import annotations

__all__ = [
    "VectorReadError",
    "CollectionNotProvisionedError",
]


class VectorReadError(RuntimeError):
    """Base class for read-path errors surfaced by a Vector_Adapter."""


class CollectionNotProvisionedError(VectorReadError):
    """A physical collection addressed by a read is absent from the backend.

    Carries the physical name and, where known, the logical collection it
    resolved from and the active tenant id, so the tool layer can render a
    Skip_Block without re-deriving either (Requirement 4.3).

    Parameters
    ----------
    physical
        The physical collection (OpenSearch index or ChromaDB collection)
        name that was addressed and found absent.
    logical
        The Logical_Collection identifier the physical name resolved from,
        if known.
    tenant_id
        The active tenant id at the time of the read, if known.
    """

    def __init__(
        self,
        physical: str,
        *,
        logical: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        self.physical = physical
        self.logical = logical
        self.tenant_id = tenant_id
        message = f"collection not provisioned: {physical!r}"
        if logical is not None:
            message += f" (logical={logical!r})"
        if tenant_id is not None:
            message += f" (tenant_id={tenant_id!r})"
        super().__init__(message)
