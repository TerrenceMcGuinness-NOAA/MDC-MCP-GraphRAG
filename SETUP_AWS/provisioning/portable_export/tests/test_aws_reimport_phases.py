"""AWS Reimport phase tests (Task 11.1) + Property 3.

Property 3: per-index OpenSearch document counts equal source via the manifest;
embeddings bitwise-identical (SHA-256 round-trip). Incompatible mapping refusal
(R3.5); dedupe rebuild deterministic / idempotent across reruns (R8.4).

Requirements: 3.3, 3.4, 3.5, 5.3, 6.1, 6.2, 6.3, 6.4, 8.3, 8.4.
"""

from __future__ import annotations

import pytest

from portable_export.adapters import NodeRow, RelRow
from portable_export.adapters.neptune_loader import NeptuneLoader, STATUS_COMPLETE
from portable_export.adapters.opensearch_writer import (
    MappingConflictError,
    OpenSearchWriter,
)
from portable_export.kms_writer import compute_sha256
from portable_export.manifest import ExportManifest
from portable_export.phases.export_graph import export_graph_tenant
from portable_export.phases.export_vectors import export_collection
from portable_export.phases.load_graph_aws import load_graph_aws
from portable_export.phases.load_vectors_aws import load_vectors_aws
from portable_export.phases.rebuild_dedupe_aws import rebuild_dedupe


class FakeKms:
    def __init__(self):
        self.objects = {}

    def put(self, key, body, content_type="application/octet-stream"):
        self.objects[key] = body
        return compute_sha256(body)


class FakeOSWriteClient:
    def __init__(self, existing=None):
        self.existing = existing or {}
        self.created = {}
        self.docs_by_index = {}

    def index_exists(self, *, index):
        return index in self.existing or index in self.created

    def get_mapping(self, *, index):
        props = self.existing.get(index) or {}
        return {index: {"mappings": {"properties": props}}}

    def create_index(self, *, index, body):
        self.created[index] = body
        self.docs_by_index.setdefault(index, [])

    def bulk(self, *, body):
        # body is [action, doc, action, doc, ...]
        idx = None
        for i in range(0, len(body), 2):
            action = body[i]
            doc = body[i + 1]
            index = action["index"]["_index"]
            self.docs_by_index.setdefault(index, []).append(doc)

    def count(self, *, index):
        return {"count": len(self.docs_by_index.get(index, []))}


class FakeVectorReader:
    def __init__(self, docs):
        self._docs = docs

    def scroll_records(self, index, batch):
        docs = self._docs.get(index, [])
        for i in range(0, len(docs), batch):
            yield docs[i:i + batch]


class FakeGraphReader:
    def __init__(self, nodes, rels):
        self._nodes, self._rels = nodes, rels

    def stream_nodes(self, tenant):
        return iter(self._nodes)

    def stream_relationships(self, tenant):
        return iter(self._rels)


def _export(sample_vector_records, sample_graph_nodes=None, sample_graph_rels=None):
    kms = FakeKms()
    m = ExportManifest.new(manifest_id="m", tenants=["gw"])
    ve = export_collection(
        FakeVectorReader({"mdc-code-context-titan1024": sample_vector_records}),
        kms, None, prefix="pfx/", tenant="gw",
        collection="mdc-code-context-titan1024", model_profile="titan1024")
    m.add_vector_export(ve)
    if sample_graph_nodes is not None:
        ge = export_graph_tenant(
            FakeGraphReader([NodeRow(**n) for n in sample_graph_nodes],
                            [RelRow(**r) for r in sample_graph_rels]),
            kms, None, prefix="pfx/", tenant="gw")
        m.add_graph_export(ge)
    m.recompute_totals()
    return m, (lambda k: kms.objects[k]), kms


# ── Property 3: round-trip fidelity ──────────────────────────────────────────


def test_property3_index_counts_equal_source(sample_vector_records):
    m, fetch, _ = _export(sample_vector_records)
    client = FakeOSWriteClient()
    target = OpenSearchWriter(client)
    report = load_vectors_aws(fetch, target, m)
    index = "mdc-code-context-titan1024"
    src_count = m.vector_exports[0].record_count
    assert report.indexed_per_index[index] == src_count
    assert client.count(index=index)["count"] == src_count


def test_property3_embeddings_bitwise_after_reimport(sample_vector_records):
    m, fetch, _ = _export(sample_vector_records)
    client = FakeOSWriteClient()
    load_vectors_aws(fetch, OpenSearchWriter(client), m)
    indexed = client.docs_by_index["mdc-code-context-titan1024"]
    indexed_by_id = {d["id"]: d for d in indexed}
    for src in sample_vector_records:
        assert indexed_by_id[src["id"]]["embedding"] == src["embedding"]


def test_knn_mapping_created_with_profile_dimension(sample_vector_records):
    m, fetch, _ = _export(sample_vector_records)
    client = FakeOSWriteClient()
    load_vectors_aws(fetch, OpenSearchWriter(client), m)
    body = client.created["mdc-code-context-titan1024"]
    assert body["mappings"]["properties"]["embedding"]["dimension"] == 1024


# ── R3.5 mapping refusal ─────────────────────────────────────────────────────


def test_incompatible_mapping_refused(sample_vector_records):
    m, fetch, _ = _export(sample_vector_records)
    # target index already exists with wrong dimension
    client = FakeOSWriteClient(existing={
        "mdc-code-context-titan1024": {"embedding": {"type": "knn_vector", "dimension": 768}}
    })
    with pytest.raises(MappingConflictError):
        load_vectors_aws(fetch, OpenSearchWriter(client), m)


# ── graph reimport via loader ────────────────────────────────────────────────


def test_load_graph_aws_starts_loader_per_tenant(
    sample_vector_records, sample_graph_nodes, sample_graph_rels
):
    m, fetch, _ = _export(sample_vector_records, sample_graph_nodes, sample_graph_rels)
    started = []

    def loader_fn(action, payload):
        if action == "start":
            started.append(payload["source"])
            return {"payload": {"loadId": "L1"}}
        return {"payload": {"overallStatus": {"status": STATUS_COMPLETE}}}

    loader = NeptuneLoader(loader_fn, s3_loader_role_arn="arn:role",
                           poll_interval=0, sleep_fn=lambda s: None)
    report = load_graph_aws(loader, m, bucket="b", prefix="pfx/")
    assert report.load_ids_per_tenant["gw"] == "L1"
    assert started == ["s3://b/pfx/graph/gw/"]


# ── R8.4 dedupe rebuild deterministic ────────────────────────────────────────


def test_rebuild_dedupe_deterministic(sample_vector_records):
    m, fetch, _ = _export(sample_vector_records)
    rows1 = rebuild_dedupe(fetch, m)
    rows2 = rebuild_dedupe(fetch, m)
    # identical across reruns (R8.4)
    assert rows1 == rows2
    # keyed (collection, sha) per tenant
    assert all(r.tenant_id == "gw" for r in rows1)
    assert all(r.collection == "code" for r in rows1)
    assert len(rows1) == len(sample_vector_records)


def test_rebuild_dedupe_writes_when_writer_supplied(sample_vector_records):
    m, fetch, _ = _export(sample_vector_records)
    written = []
    rebuild_dedupe(fetch, m, write_fn=lambda rows: written.extend(rows))
    assert len(written) == len(sample_vector_records)
