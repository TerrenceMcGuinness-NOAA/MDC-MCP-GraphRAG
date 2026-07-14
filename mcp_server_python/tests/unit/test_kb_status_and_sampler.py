"""Unit tests for the KB-status count fix + ChromaDB metadata sampler.

rag-data-plane-gap-closure Tasks 5.3 (sample_metadata) and 6.3
(get_knowledge_base_status document count).
"""
from __future__ import annotations

import asyncio

from src.data.chromadb_adapter import ChromaDBAdapter
from src.tools.semantic_search import _filter_indices_by_tenant


# ── Task 5.3 — ChromaDBAdapter.sample_metadata ──────────────────────────


class _FakeColl:
    def __init__(self, metas):
        self._metas = metas

    def get(self, limit, include):  # noqa: ARG002
        return {"metadatas": self._metas[:limit]}


class _FakeClient:
    def __init__(self, colls):
        self._colls = colls

    def list_collections(self):
        return [type("C", (), {"name": n}) for n in self._colls]

    def get_collection(self, name):
        if name not in self._colls:
            raise ValueError(f"missing collection {name}")
        return self._colls[name]


def _adapter(colls) -> ChromaDBAdapter:
    a = ChromaDBAdapter(embedding_function=lambda xs: [[0.0] for _ in xs])
    a._client = _FakeClient(colls)
    a._connected = True
    return a


def test_sample_metadata_three_docs_returns_three():
    a = _adapter({"c": _FakeColl([{"source": "a"}, {"source": "b"}, {"source": "c"}])})
    got = asyncio.run(a.sample_metadata("c", n=20))
    assert len(got) == 3


def test_sample_metadata_empty_returns_empty():
    a = _adapter({"c": _FakeColl([])})
    assert asyncio.run(a.sample_metadata("c", n=20)) == []


def test_sample_metadata_missing_collection_returns_empty():
    a = _adapter({"c": _FakeColl([{"source": "a"}])})
    assert asyncio.run(a.sample_metadata("does-not-exist", n=20)) == []


def test_sample_metadata_across_all_collections_caps_at_n():
    a = _adapter({
        "c1": _FakeColl([{"source": "a"}, {"source": "b"}]),
        "c2": _FakeColl([{"source": "c"}, {"source": "d"}]),
    })
    got = asyncio.run(a.sample_metadata(n=3))  # collection=None → all, capped at 3
    assert len(got) == 3


# ── Task 6.3 — count via collections_detail ─────────────────────────────


def test_filter_recognizes_collections_detail_and_sums():
    """ChromaDB returns `collections_detail`; the filter must recognize it and
    sum the in-scope subset (root cause of the Total Documents: 0 bug)."""
    health = {
        "status": "healthy",
        "collections_detail": {
            "mdc-workflow-docs-mpnet768": 100,
            "mdc-code-context-mpnet768": 50,
            "gw_v17_mdc-code-context-mpnet768": 7,  # another tenant's index
        },
    }
    # Default gw (empty prefix) excludes gw_v17_-prefixed → total 150, 2 indices.
    names, detail, total = _filter_indices_by_tenant(
        health, prefix="", others=("gw_v17_",)
    )
    assert total == 150
    assert len(names) == 2
    assert "gw_v17_mdc-code-context-mpnet768" not in names


def test_filter_non_default_tenant_scopes_to_prefix():
    health = {
        "status": "healthy",
        "collections_detail": {
            "mdc-workflow-docs-mpnet768": 100,
            "gw_v17_mdc-code-context-mpnet768": 7,
        },
    }
    names, detail, total = _filter_indices_by_tenant(
        health, prefix="gw_v17_", others=()
    )
    assert total == 7
    assert names == ["gw_v17_mdc-code-context-mpnet768"]
