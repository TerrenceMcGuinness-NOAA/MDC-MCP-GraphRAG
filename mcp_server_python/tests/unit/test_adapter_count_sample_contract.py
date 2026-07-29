"""Backend adapter contract test: count_documents + sample_metadata parity.

cots-backend-observability-parity R6 — both the ChromaDB (``DB_BACKEND=cots``)
and OpenSearch (``DB_BACKEND=aws``) vector adapters MUST expose the same two
observability methods with identical contracted return types and
empty/missing-collection behaviour, so the three observability tools
(``get_knowledge_base_status``, ``check_knowledge_integrity``,
``list_all_sources --include_gaps``) can dispatch through the backend-abstract
interface without branching on backend type.

Runs without a live store: ChromaDB and OpenSearch adapters are constructed with
an injected fake client. The OpenSearch adapter imports ``opensearch-py`` lazily
inside ``connect()``, so this test does not require that package to be installed
(it is absent on the COTS host).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from src.data.chromadb_adapter import ChromaDBAdapter
from src.data.opensearch_adapter import OpenSearchAdapter
from src.data.protocols import VectorDBProtocol

pytestmark = pytest.mark.unit


# ── ChromaDB fakes ───────────────────────────────────────────────────────


class _FakeChromaColl:
    def __init__(self, metas: list[dict[str, Any]]):
        self._metas = metas

    def count(self) -> int:
        return len(self._metas)

    def get(self, limit: int, include: list[str]):  # noqa: ARG002
        return {"metadatas": self._metas[:limit]}


class _FakeChromaClient:
    def __init__(self, colls: dict[str, _FakeChromaColl]):
        self._colls = colls

    def list_collections(self):
        return [type("C", (), {"name": n}) for n in self._colls]

    def get_collection(self, name: str):
        if name not in self._colls:
            raise ValueError(f"missing collection {name}")
        return self._colls[name]


def _make_chromadb() -> tuple[Any, str, int]:
    metas = [
        {"file_path": f"a/b/{i}.py", "ingested_at": "2026-07-01T00:00:00Z"}
        for i in range(3)
    ]
    adapter = ChromaDBAdapter(embedding_function=lambda xs: [[0.0] for _ in xs])
    adapter._client = _FakeChromaClient({"existing": _FakeChromaColl(metas)})
    adapter._connected = True
    return adapter, "existing", 3


# ── OpenSearch fakes ─────────────────────────────────────────────────────


class _FakeOSRaw:
    def __init__(self, counts: dict[str, int], metas_by_index: dict[str, list[dict]]):
        self._counts = counts
        self._metas_by_index = metas_by_index
        self.cat = SimpleNamespace(indices=self._indices)

    def count(self, index: str):
        if index not in self._counts:
            raise Exception("index_not_found_exception")
        return {"count": self._counts[index]}

    def _indices(self, format: str | None = None, h: str | None = None):  # noqa: A002,ARG002
        return [{"index": n} for n in self._counts]

    def search(self, index: str, body: dict):
        metas = self._metas_by_index.get(index, [])
        size = int(body.get("size", 10))
        hits = [{"_source": {"metadata": m}} for m in metas[:size]]
        return {"hits": {"hits": hits}}


def _make_opensearch() -> tuple[Any, str, int]:
    metas = [
        {"file_path": f"a/b/{i}.py", "ingested_at": "2026-07-01T00:00:00Z"}
        for i in range(3)
    ]
    adapter = OpenSearchAdapter(
        endpoint="https://example.test",
        embedding_function=lambda xs: [[0.0] for _ in xs],
    )
    adapter._client = SimpleNamespace(
        _client=_FakeOSRaw({"existing": 3}, {"existing": metas})
    )
    adapter._connected = True
    return adapter, "existing", 3


ADAPTER_FACTORIES = {
    "chromadb": _make_chromadb,
    "opensearch": _make_opensearch,
}


# ── contract tests (both adapters) ───────────────────────────────────────


@pytest.mark.parametrize("backend", sorted(ADAPTER_FACTORIES))
def test_adapter_satisfies_vector_protocol(backend: str) -> None:
    """Both adapters structurally satisfy VectorDBProtocol (which now declares
    count_documents + sample_metadata)."""
    adapter, _, _ = ADAPTER_FACTORIES[backend]()
    assert isinstance(adapter, VectorDBProtocol)
    assert hasattr(adapter, "count_documents")
    assert hasattr(adapter, "sample_metadata")


@pytest.mark.parametrize("backend", sorted(ADAPTER_FACTORIES))
def test_count_documents_existing_returns_positive_int(backend: str) -> None:
    adapter, existing, expected = ADAPTER_FACTORIES[backend]()
    got = asyncio.run(adapter.count_documents(existing))
    assert isinstance(got, int)
    assert got == expected
    assert got > 0


@pytest.mark.parametrize("backend", sorted(ADAPTER_FACTORIES))
def test_count_documents_missing_returns_zero(backend: str) -> None:
    adapter, _, _ = ADAPTER_FACTORIES[backend]()
    got = asyncio.run(adapter.count_documents("does-not-exist"))
    assert got == 0


@pytest.mark.parametrize("backend", sorted(ADAPTER_FACTORIES))
def test_sample_metadata_existing_returns_list_of_dicts(backend: str) -> None:
    adapter, existing, _ = ADAPTER_FACTORIES[backend]()
    got = asyncio.run(adapter.sample_metadata(existing, limit=5))
    assert isinstance(got, list)
    assert 0 < len(got) <= 5
    assert all(isinstance(m, dict) for m in got)
    # R2.3: sampled metadata carries the fields the Path/Stale checks read.
    assert any("file_path" in m for m in got)


@pytest.mark.parametrize("backend", sorted(ADAPTER_FACTORIES))
def test_sample_metadata_missing_returns_empty(backend: str) -> None:
    adapter, _, _ = ADAPTER_FACTORIES[backend]()
    got = asyncio.run(adapter.sample_metadata("does-not-exist", limit=5))
    assert got == []


@pytest.mark.parametrize("backend", sorted(ADAPTER_FACTORIES))
def test_sample_metadata_n_alias_is_backward_compatible(backend: str) -> None:
    """The legacy ``n`` keyword still works (used by _build_vector_sampler and
    older test doubles)."""
    adapter, existing, _ = ADAPTER_FACTORIES[backend]()
    got = asyncio.run(adapter.sample_metadata(existing, n=2))
    assert isinstance(got, list)
    assert len(got) <= 2


@pytest.mark.parametrize("backend", sorted(ADAPTER_FACTORIES))
def test_count_documents_reachable_through_unified_data_access(backend: str) -> None:
    """R1.3: count_documents is reachable through the UnifiedDataAccess
    backend-abstract ``vector_db`` attribute (no backend branching)."""
    from src.data.unified_data_access import UnifiedDataAccess

    adapter, existing, expected = ADAPTER_FACTORIES[backend]()
    uda = UnifiedDataAccess(vector_db=adapter, graph_db=None, backend=backend)
    got = asyncio.run(uda.vector_db.count_documents(existing))
    assert got == expected
