"""Cross-backend missing-collection normalization tests.

shared-scope-query-routing Task 4 (sub-tasks 4.1-4.4). Covers:

* ``src.data.vector_errors.CollectionNotProvisionedError`` (Task 4.1).
* ChromaDB collection-absence classification, both detection forms, and
  the non-absence fall-through to the pre-existing ``ValueError`` wrap
  with its message unchanged (Task 4.2, Requirements 4.3, 4.6).
* The OpenSearch side of the same normalization, reusing the existing
  ``index_not_found_exception`` detection verbatim (Task 4.3,
  Requirements 4.3, 4.6).
* Cross-backend Skip_Block character-for-character identity and the
  Requirement 4.7 "raise once for the whole set, one Skip_Block naming
  the logical collection" behaviour (Task 4.4, Requirements 4.4, 4.7).

No live AWS or ChromaDB call. The Task 4.4 cross-backend cases live in
``tests/properties/test_vector_errors_cross_backend.py``, which consumes
the ``adapters()`` fixture from ``tests/properties/conftest.py``
(Task 2.4) rather than duplicating it -- that fixture is scoped to the
``tests/properties/`` subtree.
"""

from __future__ import annotations

import pytest

from src.data.chromadb_adapter import ChromaDBAdapter
from src.data.opensearch_adapter import OpenSearchAdapter
from src.data.vector_errors import (
    CollectionNotProvisionedError,
    VectorReadError,
)

pytestmark = pytest.mark.unit


# ── CollectionNotProvisionedError (Task 4.1) ────────────────────────────


def test_collection_not_provisioned_error_is_a_vector_read_error() -> None:
    exc = CollectionNotProvisionedError("gw_v17_mdc-ee2-standards-titan1024")
    assert isinstance(exc, VectorReadError)
    assert isinstance(exc, RuntimeError)


def test_collection_not_provisioned_error_carries_context() -> None:
    exc = CollectionNotProvisionedError(
        "gw_v17_mdc-ee2-standards-titan1024",
        logical="ee2-standards-v5-0-0-enhanced",
        tenant_id="gw_v17",
    )
    assert exc.physical == "gw_v17_mdc-ee2-standards-titan1024"
    assert exc.logical == "ee2-standards-v5-0-0-enhanced"
    assert exc.tenant_id == "gw_v17"
    # Message names the physical collection at minimum.
    assert "gw_v17_mdc-ee2-standards-titan1024" in str(exc)


def test_collection_not_provisioned_error_context_is_optional() -> None:
    exc = CollectionNotProvisionedError("x")
    assert exc.physical == "x"
    assert exc.logical is None
    assert exc.tenant_id is None


# ── ChromaDB classification (Task 4.2, R4.3, R4.6) ──────────────────────


@pytest.fixture
def chroma_adapter() -> ChromaDBAdapter:
    def embedding_function(texts: list[str]) -> list[list[float]]:
        return [[0.0, 0.0] for _ in texts]

    adapter = ChromaDBAdapter(embedding_function=embedding_function)
    return adapter


class _RaisingChromaClient:
    """Client double that raises a chosen exception from get_collection."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def get_collection(self, name: str):
        raise self._exc


@pytest.mark.asyncio
async def test_chromadb_missing_collection_substring_does_not_exist(
    chroma_adapter: ChromaDBAdapter,
) -> None:
    """The FakeChromaClient shape used across the suite: ValueError(...).

    ``FakeChromaClient.get_collection`` (tests/properties/conftest.py)
    raises exactly this message for an unseeded collection, so this test
    also documents that the fixture's absence signal is recognised.
    """
    chroma_adapter._client = _RaisingChromaClient(
        ValueError("Collection missing-one does not exist.")
    )
    chroma_adapter._connected = True

    with pytest.raises(CollectionNotProvisionedError) as excinfo:
        await chroma_adapter.query("ee2-standards-v5-0-0-enhanced", "err_chk")

    assert excinfo.value.logical == "ee2-standards-v5-0-0-enhanced"


@pytest.mark.asyncio
async def test_chromadb_missing_collection_substring_not_found(
    chroma_adapter: ChromaDBAdapter,
) -> None:
    chroma_adapter._client = _RaisingChromaClient(
        Exception("collection not found: missing-one")
    )
    chroma_adapter._connected = True

    with pytest.raises(CollectionNotProvisionedError):
        await chroma_adapter.query("community-summaries", "q")


@pytest.mark.asyncio
async def test_chromadb_missing_collection_substring_is_case_insensitive(
    chroma_adapter: ChromaDBAdapter,
) -> None:
    chroma_adapter._client = _RaisingChromaClient(
        Exception("Collection NOT FOUND for that name")
    )
    chroma_adapter._connected = True

    with pytest.raises(CollectionNotProvisionedError):
        await chroma_adapter.query("community-summaries", "q")


@pytest.mark.asyncio
async def test_chromadb_notfounderror_type_when_available(
    chroma_adapter: ChromaDBAdapter,
) -> None:
    """Structured-type form: chromadb.errors.NotFoundError (in 1.5.8)."""
    import chromadb.errors as chroma_errors

    NotFoundError = getattr(chroma_errors, "NotFoundError", None)
    if NotFoundError is None:  # pragma: no cover - defensive
        pytest.skip("chromadb.errors.NotFoundError not available")

    chroma_adapter._client = _RaisingChromaClient(NotFoundError("gone"))
    chroma_adapter._connected = True

    with pytest.raises(CollectionNotProvisionedError):
        await chroma_adapter.query("community-summaries", "q")


@pytest.mark.asyncio
async def test_chromadb_connection_failure_keeps_existing_valueerror_shape(
    chroma_adapter: ChromaDBAdapter,
) -> None:
    """Non-absence failures fall through unchanged (R4.6).

    The existing message shape --
    ``f"ChromaDB query failed on index={index!r}: {exc}"`` -- must be
    preserved so connection, auth, and embedding-generation failures stay
    distinguishable from absence.
    """
    chroma_adapter._client = _RaisingChromaClient(
        ConnectionError("connection refused")
    )
    chroma_adapter._connected = True

    with pytest.raises(ValueError) as excinfo:
        await chroma_adapter.query("community-summaries", "q")

    assert not isinstance(excinfo.value, CollectionNotProvisionedError)
    assert "ChromaDB query failed on index=" in str(excinfo.value)
    assert "connection refused" in str(excinfo.value)


@pytest.mark.asyncio
async def test_chromadb_embedding_generation_failure_is_not_unprovisioned(
    chroma_adapter: ChromaDBAdapter,
) -> None:
    """An embedding-generation failure is a query failure, not an absence."""
    chroma_adapter._connected = True
    chroma_adapter._provider = None
    chroma_adapter._embedding_function = None
    chroma_adapter._provider_error = None

    with pytest.raises(ValueError) as excinfo:
        await chroma_adapter.query("community-summaries", "q")

    assert not isinstance(excinfo.value, CollectionNotProvisionedError)


# ── OpenSearch classification (Task 4.3, R4.3, R4.6) ────────────────────


class _NamespaceWithRawClient:
    def __init__(self, raw) -> None:
        self._client = raw


class _RaisingOpenSearchRawClient:
    """Raw client double that raises a chosen exception from ``search``."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def search(self, *, index: str, body):
        raise self._exc


@pytest.fixture
def opensearch_adapter() -> OpenSearchAdapter:
    def embedding_function(texts: list[str]) -> list[list[float]]:
        return [[0.0, 0.0] for _ in texts]

    adapter = OpenSearchAdapter(
        endpoint="https://example.invalid",
        embedding_function=embedding_function,
    )
    return adapter


@pytest.mark.asyncio
async def test_opensearch_structured_notfound_raises_not_provisioned(
    opensearch_adapter: OpenSearchAdapter,
) -> None:
    from opensearchpy.exceptions import NotFoundError

    exc = NotFoundError(
        404,
        "index_not_found_exception",
        {"error": {"type": "index_not_found_exception"}},
    )
    opensearch_adapter._client = _NamespaceWithRawClient(
        _RaisingOpenSearchRawClient(exc)
    )
    opensearch_adapter._connected = True

    with pytest.raises(CollectionNotProvisionedError) as excinfo:
        await opensearch_adapter.query(
            "ee2-standards-v5-0-0-enhanced", "err_chk"
        )

    assert excinfo.value.logical == "ee2-standards-v5-0-0-enhanced"


@pytest.mark.asyncio
async def test_opensearch_string_fallback_raises_not_provisioned(
    opensearch_adapter: OpenSearchAdapter,
) -> None:
    opensearch_adapter._client = _NamespaceWithRawClient(
        _RaisingOpenSearchRawClient(
            Exception("no such index_not_found_exception")
        )
    )
    opensearch_adapter._connected = True

    with pytest.raises(CollectionNotProvisionedError):
        await opensearch_adapter.query("community-summaries", "q")


@pytest.mark.asyncio
async def test_opensearch_non_absence_failure_keeps_query_error_shape(
    opensearch_adapter: OpenSearchAdapter,
) -> None:
    """R4.6: a non-404, non-retryable failure stays an OpenSearchQueryError."""
    from src.data.opensearch_adapter import OpenSearchQueryError

    class _AuthError(Exception):
        status_code = 403

    opensearch_adapter._client = _NamespaceWithRawClient(
        _RaisingOpenSearchRawClient(_AuthError("forbidden"))
    )
    opensearch_adapter._connected = True

    with pytest.raises(OpenSearchQueryError) as excinfo:
        await opensearch_adapter.query("community-summaries", "q")

    assert not isinstance(excinfo.value, CollectionNotProvisionedError)


# Cross-backend Skip_Block identity (Task 4.4, R4.4, R4.7) is covered in
# tests/properties/test_vector_errors_cross_backend.py, which consumes the
# adapters() fixture defined in tests/properties/conftest.py. That fixture
# is scoped to the tests/properties/ subtree (pytest fixture discovery is
# directory-scoped via the owning conftest.py), so the cross-backend cases
# live there rather than being duplicated here or imported piecemeal.
