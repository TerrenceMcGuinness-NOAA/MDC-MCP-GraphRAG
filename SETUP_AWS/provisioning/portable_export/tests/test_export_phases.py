"""Export-phase tests (Task 9.1) + Property 1 + Property 2.

Property 1 (engine-neutral readability): JSONL.gz parses with gzip+json only;
CSV.gz parses with the standard csv reader and carries Neptune-loader headers.
Property 2 (no-re-embedding): SHA-256 over read embeddings equals SHA-256 over
written-then-reparsed embeddings.
Tenant zero-data -> zero count, no error (R7.5).

Requirements: 1.1, 1.2, 1.5, 5.1, 5.2, 5.3, 7.5.
"""

from __future__ import annotations

import gzip
import hashlib
import json

from portable_export.adapters import NodeRow, RelRow
from portable_export.kms_writer import compute_sha256
from portable_export.manifest import ExportManifest
from portable_export.phases.export_dedupe import export_dedupe
from portable_export.phases.export_graph import export_graph_tenant
from portable_export.phases.export_vectors import export_collection, export_vectors
from portable_export.serialization import (
    NODE_RESERVED,
    REL_RESERVED,
    csv_gz_decode,
    jsonl_gz_decode,
)
from portable_export.adapters import DedupeRow
from portable_export.watermarks import Watermarks, unit_key


class FakeKms:
    """Captures object bytes by key; returns the real SHA-256."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put(self, key, body, content_type="application/octet-stream"):
        self.objects[key] = body
        return compute_sha256(body)


class FakeVectorReader:
    def __init__(self, docs_by_index):
        self._docs = docs_by_index

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


# ── Property 1: engine-neutral readability ──────────────────────────────────


def test_vector_part_is_plain_gzip_jsonl(sample_vector_records):
    kms = FakeKms()
    reader = FakeVectorReader({"mdc-code-context-titan1024": sample_vector_records})
    entry = export_collection(
        reader, kms, None,
        prefix="pfx/", tenant="gw", collection="mdc-code-context-titan1024",
        model_profile="titan1024", batch=500, part_max_records=1000,
    )
    assert entry.record_count == 2
    assert len(entry.parts) == 1
    key = entry.parts[0]
    raw = gzip.decompress(kms.objects[key]).decode("utf-8")
    # parses as JSONL with json only -- no OpenSearch dependency
    objs = [json.loads(l) for l in raw.splitlines() if l]
    assert [o["id"] for o in objs] == ["doc_0001", "doc_0002"]


def test_graph_part_csv_has_neptune_loader_headers(sample_graph_nodes, sample_graph_rels):
    kms = FakeKms()
    nodes = [NodeRow(**n) for n in sample_graph_nodes]
    rels = [RelRow(**r) for r in sample_graph_rels]
    reader = FakeGraphReader(nodes, rels)
    entry = export_graph_tenant(reader, kms, None, prefix="pfx/", tenant="gw")
    assert entry.node_count == 3
    assert entry.relationship_count == 2
    # node CSV headers begin with ~id,~label
    node_key = [k for k in kms.objects if "/nodes/" in k][0]
    rows = csv_gz_decode(kms.objects[node_key])
    assert all(c in rows[0] for c in NODE_RESERVED)
    rel_key = [k for k in kms.objects if "/rels/" in k][0]
    rel_rows = csv_gz_decode(kms.objects[rel_key])
    assert all(c in rel_rows[0] for c in REL_RESERVED)


# ── Property 2: no re-embedding (bitwise) ────────────────────────────────────


def test_property2_embeddings_bitwise_through_jsonl(sample_vector_records):
    kms = FakeKms()
    reader = FakeVectorReader({"c": sample_vector_records})
    entry = export_collection(
        reader, kms, None, prefix="pfx/", tenant="gw", collection="c",
        model_profile="titan1024",
    )
    # digest over source embeddings
    src_blob = json.dumps([r["embedding"] for r in sample_vector_records],
                          sort_keys=True).encode()
    src_digest = hashlib.sha256(src_blob).hexdigest()
    # reparse the written part and digest its embeddings
    parsed = jsonl_gz_decode(kms.objects[entry.parts[0]])
    dst_blob = json.dumps([r["embedding"] for r in parsed], sort_keys=True).encode()
    dst_digest = hashlib.sha256(dst_blob).hexdigest()
    assert src_digest == dst_digest
    # exact value equality too
    assert parsed[0]["embedding"] == sample_vector_records[0]["embedding"]


def test_part_sha_recorded_and_matches_object(sample_vector_records):
    kms = FakeKms()
    reader = FakeVectorReader({"c": sample_vector_records})
    entry = export_collection(reader, kms, None, prefix="pfx/", tenant="gw",
                              collection="c", model_profile="titan1024")
    body = kms.objects[entry.parts[0]]
    assert entry.sha256_per_part[0] == compute_sha256(body)


# ── zero-data tenant (R7.5) ──────────────────────────────────────────────────


def test_zero_data_collection_yields_zero_count_no_error():
    kms = FakeKms()
    reader = FakeVectorReader({})  # no docs for any index
    entry = export_collection(reader, kms, None, prefix="pfx/", tenant="gw_sfs",
                              collection="gw_sfs_mdc-code-context-titan1024",
                              model_profile="titan1024")
    assert entry.record_count == 0
    assert entry.parts == []
    assert kms.objects == {}


def test_export_vectors_appends_to_manifest(sample_vector_records):
    kms = FakeKms()
    reader = FakeVectorReader({"c": sample_vector_records})
    m = ExportManifest.new(manifest_id="m", tenants=["gw"])
    export_vectors(reader, kms, None, m, prefix="pfx/",
                   units=[("gw", "c", "titan1024")])
    assert len(m.vector_exports) == 1
    assert m.vector_exports[0].record_count == 2


# ── dedupe export (R8.2) ─────────────────────────────────────────────────────


def test_export_dedupe_preserves_collection_sha_keys():
    kms = FakeKms()
    rows = [
        DedupeRow(tenant_id="gw", collection="code", sha="aaa"),
        DedupeRow(tenant_id="gw", collection="docs", sha="bbb"),
        DedupeRow(tenant_id="gw_v17", collection="code", sha="ccc"),
    ]
    dd = export_dedupe(rows, kms, None, prefix="pfx/")
    assert dd["format"] == "exported"
    assert dd["entry_count"] == 3
    # gw part holds two (collection, sha) entries
    gw_key = [k for k in kms.objects if "/dedupe/gw/" in k][0]
    entries = jsonl_gz_decode(kms.objects[gw_key])
    assert {(e["collection"], e["sha"]) for e in entries} == {("code", "aaa"), ("docs", "bbb")}


# ── resume: completed part not rewritten ─────────────────────────────────────


class _MemS3:
    def __init__(self):
        self.objects = {}
        self._seq = 0

    def get_object(self, *, Bucket, Key):
        from botocore.exceptions import ClientError
        if (Bucket, Key) not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"},
                               "ResponseMetadata": {"HTTPStatusCode": 404}}, "GetObject")
        body, etag = self.objects[(Bucket, Key)]

        class _B:
            def __init__(self, d): self._d = d
            def read(self): return self._d
        return {"Body": _B(body), "ETag": f'"{etag}"'}

    def put_object(self, *, Bucket, Key, Body, ContentType=None, IfNoneMatch=None, IfMatch=None):
        self._seq += 1
        etag = f"e{self._seq}"
        self.objects[(Bucket, Key)] = (Body, etag)
        return {"ETag": f'"{etag}"'}


def test_resume_skips_completed_vector_part(sample_vector_records):
    s3 = _MemS3()
    wm = Watermarks(s3, "b", "pfx/watermarks.json", manifest_id="m", operation_id="op")
    wm.load()
    # pre-mark part 0 complete
    wm.mark_complete(unit_key(phase="export_vectors", tenant="gw", collection="c",
                              model_profile="titan1024", part=0))
    kms = FakeKms()
    reader = FakeVectorReader({"c": sample_vector_records})
    entry = export_collection(reader, kms, wm, prefix="pfx/", tenant="gw",
                              collection="c", model_profile="titan1024")
    # part already complete -> not re-written to KMS
    assert kms.objects == {}
    assert entry.record_count == 2  # still counted
