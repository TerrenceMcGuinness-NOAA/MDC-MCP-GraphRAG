"""End-to-end integration tests (Task 14).

Wires the real pipeline modules together over a moto-backed S3 (the
Portable_Export staging contract) with in-memory fixtures standing in for the
OpenSearch / Neptune / ChromaDB / Neo4j data planes:

* **AWS_Export -> AWS_Reimport** -- small fixture corpus exported to moto S3,
  re-imported; Count_Parity_Check passes; Property 3 holds (per-index /
  per-tenant counts equal, embeddings bitwise).
* **AWS_Export -> COTS_Restore** -- restored into in-memory ChromaDB + Neo4j;
  Count_Parity_Check passes; Property 4 holds; Query_Incompatible surfaces for
  titan1024 when the COTS host has no Bedrock.
* **Bundle round-trip** -- the S3-native layout is packed into an Export_Bundle,
  unpacked on a "disconnected" host, and a restore from the bundle is shown to
  be byte-equivalent to the S3-native restore (R12.4).
* **Resume round-trip** -- an export interrupted mid-stream is resumed with the
  persisted watermark and produces a manifest byte-equal to an uninterrupted
  run (Property 6).

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 9.1, 9.2, 12.4.
"""

from __future__ import annotations

import boto3
import pytest

from moto import mock_aws

from portable_export import config
from portable_export.adapters import DedupeRow, NodeRow, RelRow
from portable_export.adapters.chromadb_writer import ChromaDBWriter
from portable_export.adapters.neo4j_writer import Neo4jWriter
from portable_export.adapters.neptune_loader import NeptuneLoader, STATUS_COMPLETE
from portable_export.adapters.opensearch_reader import OpenSearchReader
from portable_export.adapters.opensearch_writer import OpenSearchWriter
from portable_export.direction_dispatcher import COTS_RESTORE, execute_restore
from portable_export.kms_writer import KmsWriter, compute_sha256
from portable_export.manifest import ExportManifest, write_manifest
from portable_export.phases.count_parity import compare_counts, source_counts
from portable_export.phases.export_dedupe import export_dedupe
from portable_export.phases.export_graph import export_graph
from portable_export.phases.export_vectors import export_vectors
from portable_export.phases.load_graph_aws import load_graph_aws
from portable_export.phases.load_graph_cots import load_graph_cots
from portable_export.phases.load_vectors_aws import load_vectors_aws
from portable_export.phases.load_vectors_cots import load_vectors_cots
from portable_export.serialization import csv_gz_decode
from portable_export.watermarks import Watermarks

BUCKET = "mdc-mcp-rag-snapshots-itest"
KMS_ARN = "arn:aws:kms:us-east-1:903050880929:key/itest"
PREFIX = "portable-export/dev/itest/"
FIXED_TS = "2026-06-16T00:00:00Z"

# ── fixture corpus ────────────────────────────────────────────────────────────

GW_VECTORS = [
    {"id": f"gw_d{i}", "content": f"content {i}",
     "embedding": [0.0123456789 * i, -1.0 + i, 2.5e-08],
     "metadata": {"tenant_id": "gw"}, "model_profile": "titan1024",
     "collection_name": "mdc-code-context-titan1024", "chunk_id": f"c{i}"}
    for i in range(5)
]
V17_VECTORS = [
    {"id": f"v17_d{i}", "content": f"v17 content {i}",
     "embedding": [float(i), 0.5, -0.25],
     "metadata": {"tenant_id": "gw_v17"}, "model_profile": "titan1024",
     "collection_name": "gw_v17_mdc-code-context-titan1024", "chunk_id": f"c{i}"}
    for i in range(3)
]
GW_NODES = [
    NodeRow(id=f"n{i}", label="File", properties={"path": f"f{i}.py", "loc": i})
    for i in range(4)
]
GW_RELS = [
    RelRow(id=f"r{i}", type="CALLS", start=f"n{i}", end=f"n{i+1}",
           properties={"count": i})
    for i in range(3)
]
DEDUPE_ROWS = [
    DedupeRow(tenant_id="gw", collection="code", sha=f"sha{i}") for i in range(5)
] + [DedupeRow(tenant_id="gw_v17", collection="code", sha="shaX")]

VECTOR_UNITS = [
    ("gw", "mdc-code-context-titan1024", "titan1024"),
    ("gw_v17", "gw_v17_mdc-code-context-titan1024", "titan1024"),
]
TENANTS = ["gw", "gw_v17"]


# ── in-memory data-plane fakes ────────────────────────────────────────────────


class FakeOSLowLevel:
    """opensearch-py-like client serving one scroll page per index."""

    def __init__(self, docs_by_index):
        self._docs = docs_by_index

    def list_indices(self):
        return list(self._docs)

    def count(self, *, index):
        return {"count": len(self._docs.get(index, []))}

    def search(self, *, index, scroll, size, body):
        docs = self._docs.get(index, [])
        return {"_scroll_id": f"s-{index}",
                "hits": {"hits": [{"_id": d["id"], "_source": d} for d in docs]}}

    def scroll(self, *, scroll_id, scroll):
        return {"_scroll_id": scroll_id, "hits": {"hits": []}}

    def clear_scroll(self, *, scroll_id):
        return {}


class StreamGraphReader:
    """Minimal graph source: per-tenant node/rel lists."""

    def __init__(self, nodes_by_tenant, rels_by_tenant):
        self._n = nodes_by_tenant
        self._r = rels_by_tenant

    def stream_nodes(self, tenant):
        return iter(self._n.get(tenant, []))

    def stream_relationships(self, tenant):
        return iter(self._r.get(tenant, []))


class FakeOSWriteClient:
    def __init__(self):
        self.created = {}
        self.docs_by_index = {}

    def index_exists(self, *, index):
        return index in self.created

    def get_mapping(self, *, index):
        return {index: {"mappings": {"properties": {}}}}

    def create_index(self, *, index, body):
        self.created[index] = body
        self.docs_by_index.setdefault(index, [])

    def bulk(self, *, body):
        for i in range(0, len(body), 2):
            index = body[i]["index"]["_index"]
            self.docs_by_index.setdefault(index, []).append(body[i + 1])

    def count(self, *, index):
        return {"count": len(self.docs_by_index.get(index, []))}


class FakeNeptuneLoaderS3:
    """Bulk-loader that actually reads the staged CSV.gz from S3 and tallies."""

    def __init__(self, s3, bucket):
        self.s3 = s3
        self.bucket = bucket
        self.tallies: dict[str, tuple[int, int]] = {}

    def loader_fn(self, action, payload):
        if action == "start":
            source = payload["source"]
            key_prefix = source.split(f"s3://{self.bucket}/", 1)[1]
            tenant = key_prefix.rstrip("/").split("/")[-1]
            nodes = rels = 0
            resp = self.s3.list_objects_v2(Bucket=self.bucket, Prefix=key_prefix)
            for obj in resp.get("Contents", []):
                key = obj["Key"]
                body = self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
                rows = csv_gz_decode(body)
                if "/nodes/" in key:
                    nodes += len(rows)
                elif "/rels/" in key:
                    rels += len(rows)
            self.tallies[tenant] = (nodes, rels)
            return {"payload": {"loadId": f"L-{tenant}"}}
        return {"payload": {"overallStatus": {"status": STATUS_COMPLETE}}}


class FakeColl:
    def __init__(self):
        self.ids = []
        self.embeddings = []

    def add(self, *, ids, documents, embeddings, metadatas):
        self.ids += list(ids)
        self.embeddings += list(embeddings)

    def count(self):
        return len(self.ids)


class FakeChroma:
    def __init__(self):
        self.collections = {}

    def get_or_create_collection(self, name):
        return self.collections.setdefault(name, FakeColl())

    def list_collections(self):
        return list(self.collections)


class CountingSession:
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


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_bucket(s3, bucket=BUCKET):
    s3.create_bucket(Bucket=bucket)
    s3.put_bucket_encryption(
        Bucket=bucket,
        ServerSideEncryptionConfiguration={
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms"}}]
        },
    )


def _fetch(s3, bucket=BUCKET):
    return lambda key: s3.get_object(Bucket=bucket, Key=key)["Body"].read()


def run_full_export(s3, *, bucket=BUCKET, prefix=PREFIX, watermarks=None, kms=None,
                    produced_at=FIXED_TS):
    """Run a complete AWS_Export to moto S3 and return the manifest."""
    kms = kms or KmsWriter(s3, bucket, kms_key_arn=KMS_ARN, guard_encryption=True)
    m = ExportManifest.new(manifest_id="itest", tenants=TENANTS,
                           source_endpoints={"opensearch": "https://os",
                                             "neptune": "https://neptune:8182"})
    m.produced_at = produced_at
    prof = config.model_profile("titan1024")
    m.add_model_profile("titan1024", dimensions=prof.dimensions,
                        provider=prof.provider, model_id=prof.model_id)

    os_reader = OpenSearchReader(
        FakeOSLowLevel({
            "mdc-code-context-titan1024": GW_VECTORS,
            "gw_v17_mdc-code-context-titan1024": V17_VECTORS,
        }),
        index_prefixes={"gw": "", "gw_v17": "gw_v17_"},
    )
    graph_reader = StreamGraphReader(
        {"gw": GW_NODES, "gw_v17": []}, {"gw": GW_RELS, "gw_v17": []}
    )

    export_vectors(os_reader, kms, watermarks, m, prefix=prefix,
                   units=VECTOR_UNITS, part_max_records=2)
    export_graph(graph_reader, kms, watermarks, m, prefix=prefix, tenants=TENANTS)
    m.dedupe_export = export_dedupe(DEDUPE_ROWS, kms, watermarks, prefix=prefix)
    m.recompute_totals()
    write_manifest(s3, bucket, prefix, m)
    return m


def _aws_dest_counts(m, os_client, loader_tallies):
    collection, model_profile, tenant_vectors = {}, {}, {}
    meta = {ve.collection_name: (ve.tenant_id, ve.model_profile)
            for ve in m.vector_exports}
    for index, (tenant, profile) in meta.items():
        c = os_client.count(index=index)["count"]
        collection[index] = c
        model_profile[profile] = model_profile.get(profile, 0) + c
        tenant_vectors[tenant] = tenant_vectors.get(tenant, 0) + c
    return {
        "collection": collection,
        "model_profile": model_profile,
        "tenant_vectors": tenant_vectors,
        "tenant_nodes": {t: v[0] for t, v in loader_tallies.items()},
        "tenant_rels": {t: v[1] for t, v in loader_tallies.items()},
    }


def _cots_dest_counts(m, chroma, graph_report):
    collection, model_profile, tenant_vectors = {}, {}, {}
    meta = {ve.collection_name: (ve.tenant_id, ve.model_profile)
            for ve in m.vector_exports}
    for index, (tenant, profile) in meta.items():
        c = chroma.get_or_create_collection(index).count()
        collection[index] = c
        model_profile[profile] = model_profile.get(profile, 0) + c
        tenant_vectors[tenant] = tenant_vectors.get(tenant, 0) + c
    return {
        "collection": collection,
        "model_profile": model_profile,
        "tenant_vectors": tenant_vectors,
        "tenant_nodes": dict(graph_report.nodes_per_tenant),
        "tenant_rels": dict(graph_report.rels_per_tenant),
    }


# ── 1. AWS_Export -> AWS_Reimport (Property 3) ──────────────────────────────


@mock_aws
def test_export_then_reimport_parity_and_bitwise():
    s3 = boto3.client("s3", region_name="us-east-1")
    _make_bucket(s3)
    m = run_full_export(s3)

    fetch = _fetch(s3)
    os_client = FakeOSWriteClient()
    vreport = load_vectors_aws(fetch, OpenSearchWriter(os_client), m)
    assert vreport.total_indexed == 8

    loader_impl = FakeNeptuneLoaderS3(s3, BUCKET)
    loader = NeptuneLoader(loader_impl.loader_fn, s3_loader_role_arn="arn:role",
                           poll_interval=0, sleep_fn=lambda s: None)
    load_graph_aws(loader, m, None, bucket=BUCKET, prefix=PREFIX)

    # Count_Parity_Check passes across all dimensions.
    dest = _aws_dest_counts(m, os_client, loader_impl.tallies)
    report = compare_counts(source_counts(m), dest)
    assert report.passed is True, report.mismatches
    assert report.exit_status == 0

    # Property 3: embeddings bitwise-identical after round-trip.
    indexed = {d["id"]: d for d in os_client.docs_by_index["mdc-code-context-titan1024"]}
    for src in GW_VECTORS:
        assert indexed[src["id"]]["embedding"] == src["embedding"]
    # graph counts equal source
    assert loader_impl.tallies["gw"] == (4, 3)


# ── 2. AWS_Export -> COTS_Restore (Property 4 + Query_Incompatible) ──────────


@mock_aws
def test_export_then_cots_restore_parity_and_query_flags():
    s3 = boto3.client("s3", region_name="us-east-1")
    _make_bucket(s3)
    m = run_full_export(s3)
    fetch = _fetch(s3)

    chroma = FakeChroma()
    ctarget = ChromaDBWriter(chroma, version="0.5.0")
    store = {"nodes": 0, "rels": 0}
    ntarget = Neo4jWriter(session_fn=lambda: CountingSession(store), version="5.0.0")

    # Drive the gated dispatcher with an empty target (no confirmation needed)
    # and a COTS host WITHOUT Bedrock -> titan1024 must flag Query_Incompatible.
    outcome = execute_restore(
        COTS_RESTORE, manifest=m, fetch=fetch,
        vector_target=ctarget, graph_target=ntarget,
        probe_result={}, confirmed=True, has_bedrock=False,
    )
    assert outcome.performed is True
    assert outcome.vector_report.total_loaded == 8
    assert outcome.query_compatibility.incompatible_profiles == ["titan1024"]

    # Count_Parity_Check passes (Property 4).
    dest = _cots_dest_counts(m, chroma, outcome.graph_report)
    report = compare_counts(source_counts(m), dest)
    assert report.passed is True, report.mismatches
    # embeddings bitwise into ChromaDB
    coll = chroma.collections["mdc-code-context-titan1024"]
    assert GW_VECTORS[0]["embedding"] in coll.embeddings


# ── 3. Bundle round-trip (R12.4) ─────────────────────────────────────────────


@mock_aws
def test_bundle_restore_byte_equivalent_to_s3_native():
    from portable_export.bundle import pack_objects, unpack_objects

    s3 = boto3.client("s3", region_name="us-east-1")
    _make_bucket(s3)
    m = run_full_export(s3)

    # Download every object under the prefix into a {full_key: bytes} map.
    objects = {}
    resp = s3.list_objects_v2(Bucket=BUCKET, Prefix=PREFIX)
    for obj in resp.get("Contents", []):
        key = obj["Key"]
        objects[key] = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    assert any(k.endswith("/manifest.json") for k in objects)

    # Pack -> unpack: layout is byte-equivalent.
    bundle = pack_objects(objects)
    restored = unpack_objects(bundle)
    assert restored == objects

    # Restore from S3-native vs from the bundle -> identical loaded data.
    def restore(fetch_fn):
        chroma = FakeChroma()
        load_vectors_cots(fetch_fn, ChromaDBWriter(chroma, version="0.5.0"), m)
        out = {}
        for name, coll in chroma.collections.items():
            out[name] = (list(coll.ids), list(coll.embeddings))
        return out

    s3_native = restore(_fetch(s3))
    from_bundle = restore(lambda k: restored[k])
    assert s3_native == from_bundle


# ── 4. Resume round-trip (Property 6) ────────────────────────────────────────


class _InterruptingKms:
    """Wraps a KmsWriter and raises after ``fail_after`` successful puts."""

    def __init__(self, inner, fail_after):
        self._inner = inner
        self._fail_after = fail_after
        self._n = 0

    def put(self, key, body, content_type="application/octet-stream"):
        if self._n >= self._fail_after:
            raise RuntimeError("simulated interruption mid-export")
        self._n += 1
        return self._inner.put(key, body, content_type=content_type)


@mock_aws
def test_resume_manifest_byte_equal_to_uninterrupted():
    s3 = boto3.client("s3", region_name="us-east-1")
    # Two isolated buckets, SAME prefix -> part keys identical, so a faithful
    # byte-for-byte manifest comparison is possible.
    _make_bucket(s3, "uninterrupted-bkt")
    _make_bucket(s3, "resume-bkt")

    # Reference: one clean uninterrupted run.
    wm_clean = Watermarks(s3, "uninterrupted-bkt", PREFIX + "watermarks.json",
                          manifest_id="itest", operation_id="clean")
    wm_clean.load()
    clean = run_full_export(s3, bucket="uninterrupted-bkt", watermarks=wm_clean)

    # Interrupted run: fail after 3 puts.
    wm1 = Watermarks(s3, "resume-bkt", PREFIX + "watermarks.json",
                     manifest_id="itest", operation_id="run1")
    wm1.load()
    inner = KmsWriter(s3, "resume-bkt", kms_key_arn=KMS_ARN, guard_encryption=True)
    with pytest.raises(RuntimeError):
        run_full_export(s3, bucket="resume-bkt", watermarks=wm1,
                        kms=_InterruptingKms(inner, fail_after=3))

    # Resume: new watermark instance loads persisted progress, refuses on
    # manifest mismatch (none here), and completes the remaining units.
    wm2 = Watermarks(s3, "resume-bkt", PREFIX + "watermarks.json",
                     manifest_id="itest", operation_id="run2")
    wm2.load()
    wm2.ensure_manifest_match()
    resumed = run_full_export(s3, bucket="resume-bkt", watermarks=wm2)

    # The resumed manifest is byte-for-byte equal to the uninterrupted one.
    assert resumed.to_json() == clean.to_json()

    # And the staged object bytes match across the two buckets.
    def objects(bucket):
        out = {}
        resp = s3.list_objects_v2(Bucket=bucket, Prefix=PREFIX)
        for obj in resp.get("Contents", []):
            if obj["Key"].endswith("watermarks.json"):
                continue
            out[obj["Key"]] = s3.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read()
        return out

    assert objects("uninterrupted-bkt") == objects("resume-bkt")
