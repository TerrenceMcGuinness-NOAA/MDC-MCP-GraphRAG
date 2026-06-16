"""COTS Restore phase tests (Task 10.1) + Property 4.

Property 4: per-collection ChromaDB count == manifest count; per-tenant Neo4j
node + relationship counts == manifest counts. Per-part SHA-256 mismatch
refuses load (R13.4). Missing required fields per R2.4 records error and
continues.

Requirements: 2.1, 2.2, 2.4, 6.5, 13.3, 13.4.
"""

from __future__ import annotations

import pytest

from portable_export.adapters import NodeRow, RelRow
from portable_export.adapters.chromadb_writer import ChromaDBWriter
from portable_export.adapters.neo4j_writer import Neo4jWriter
from portable_export.kms_writer import ChecksumMismatch, compute_sha256
from portable_export.manifest import ExportManifest
from portable_export.phases.export_graph import export_graph_tenant
from portable_export.phases.export_vectors import export_collection
from portable_export.phases.load_graph_cots import load_graph_cots
from portable_export.phases.load_vectors_cots import load_vectors_cots


# ── fakes ─────────────────────────────────────────────────────────────────────


class FakeKms:
    def __init__(self):
        self.objects = {}

    def put(self, key, body, content_type="application/octet-stream"):
        self.objects[key] = body
        return compute_sha256(body)


class FakeCollection:
    def __init__(self):
        self.ids = []

    def add(self, *, ids, documents, embeddings, metadatas):
        self.ids += list(ids)

    def count(self):
        return len(self.ids)


class FakeChroma:
    def __init__(self):
        self.collections = {}

    def get_or_create_collection(self, name):
        return self.collections.setdefault(name, FakeCollection())

    def list_collections(self):
        return list(self.collections)


class CountingSession:
    """Records nodes/rels created so count_graph can report them."""

    def __init__(self, store):
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, cypher, **params):
        rows = params.get("rows", [])
        if "CREATE (n:" in cypher:
            self.store["nodes"] += len(rows)
        elif "CREATE (a)-[" in cypher:
            self.store["rels"] += len(rows)
        return []


class FakeVectorReader:
    def __init__(self, docs):
        self._docs = docs

    def scroll_records(self, index, batch):
        docs = self._docs.get(index, [])
        for i in range(0, len(docs), batch):
            yield docs[i:i + batch]


class FakeGraphReader:
    def __init__(self, nodes, rels):
        self._nodes = nodes
        self._rels = rels

    def stream_nodes(self, tenant):
        return iter(self._nodes)

    def stream_relationships(self, tenant):
        return iter(self._rels)


def _build_export(sample_vector_records, sample_graph_nodes, sample_graph_rels):
    """Export a small corpus to a FakeKms and return (manifest, fetch)."""
    kms = FakeKms()
    m = ExportManifest.new(manifest_id="m", tenants=["gw"])
    ve = export_collection(
        FakeVectorReader({"mdc-code-context-titan1024": sample_vector_records}),
        kms, None, prefix="pfx/", tenant="gw",
        collection="mdc-code-context-titan1024", model_profile="titan1024",
    )
    m.add_vector_export(ve)
    nodes = [NodeRow(**n) for n in sample_graph_nodes]
    rels = [RelRow(**r) for r in sample_graph_rels]
    ge = export_graph_tenant(FakeGraphReader(nodes, rels), kms, None,
                             prefix="pfx/", tenant="gw")
    m.add_graph_export(ge)
    m.recompute_totals()

    def fetch(key):
        return kms.objects[key]

    return m, fetch, kms


# ── Property 4: COTS_Restore completeness ────────────────────────────────────


def test_property4_vector_count_matches_manifest(
    sample_vector_records, sample_graph_nodes, sample_graph_rels
):
    m, fetch, _ = _build_export(sample_vector_records, sample_graph_nodes,
                                sample_graph_rels)
    chroma = FakeChroma()
    target = ChromaDBWriter(chroma, version="0.5.0")
    report = load_vectors_cots(fetch, target, m)
    coll = "mdc-code-context-titan1024"
    manifest_count = m.vector_exports[0].record_count
    assert report.loaded_per_collection[coll] == manifest_count
    assert chroma.collections[coll].count() == manifest_count


def test_property4_graph_counts_match_manifest(
    sample_vector_records, sample_graph_nodes, sample_graph_rels
):
    m, fetch, _ = _build_export(sample_vector_records, sample_graph_nodes,
                                sample_graph_rels)
    store = {"nodes": 0, "rels": 0}
    target = Neo4jWriter(session_fn=lambda: CountingSession(store), version="5.0.0")
    report = load_graph_cots(fetch, target, m)
    ge = m.graph_exports[0]
    assert report.nodes_per_tenant["gw"] == ge.node_count
    assert report.rels_per_tenant["gw"] == ge.relationship_count
    assert store["nodes"] == ge.node_count
    assert store["rels"] == ge.relationship_count


# ── R13.4 checksum mismatch ──────────────────────────────────────────────────


def test_checksum_mismatch_refuses_load(
    sample_vector_records, sample_graph_nodes, sample_graph_rels
):
    m, fetch, kms = _build_export(sample_vector_records, sample_graph_nodes,
                                  sample_graph_rels)
    # Corrupt the manifest's recorded sha for the vector part.
    m.vector_exports[0].sha256_per_part[0] = "deadbeef"
    target = ChromaDBWriter(FakeChroma(), version="0.5.0")
    with pytest.raises(ChecksumMismatch):
        load_vectors_cots(fetch, target, m)


# ── R2.4 missing field continues ─────────────────────────────────────────────


def test_missing_field_records_error_and_continues(sample_graph_nodes, sample_graph_rels):
    bad_corpus = [
        {"id": "ok", "content": "c", "embedding": [0.1], "model_profile": "titan1024"},
        {"id": "bad", "content": "c", "model_profile": "titan1024"},  # no embedding
    ]
    m, fetch, _ = _build_export(bad_corpus, sample_graph_nodes, sample_graph_rels)
    chroma = FakeChroma()
    target = ChromaDBWriter(chroma, version="0.5.0")
    report = load_vectors_cots(fetch, target, m)
    assert report.loaded_per_collection["mdc-code-context-titan1024"] == 1
    assert any("missing" in e for e in report.errors)
