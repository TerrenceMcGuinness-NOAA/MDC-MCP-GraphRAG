"""AWS writer contract tests (Task 7.1).

Index ensure-or-refuse on mapping conflict; knn_vector dimension matches
Model_Profile; bulk insert preserves embedding bytes; Neptune-loader poll
loop; tenant prefix preservation.

Requirements: 3.3, 3.4, 3.5.
"""

from __future__ import annotations

import pytest

from portable_export.adapters.neptune_loader import (
    NeptuneLoader,
    NeptuneLoaderError,
    STATUS_COMPLETE,
)
from portable_export.adapters.opensearch_writer import (
    MappingConflictError,
    OpenSearchWriter,
    knn_index_body,
)


class FakeOSWriteClient:
    def __init__(self, existing=None):
        self.existing = existing or {}  # index -> mapping props
        self.created: dict[str, dict] = {}
        self.bulk_bodies: list = []
        self.counts: dict[str, int] = {}

    def index_exists(self, *, index):
        return index in self.existing or index in self.created

    def get_mapping(self, *, index):
        props = self.existing.get(index) or self.created.get(index, {}).get(
            "mappings", {}
        ).get("properties", {})
        return {index: {"mappings": {"properties": props}}}

    def create_index(self, *, index, body):
        self.created[index] = body

    def bulk(self, *, body):
        self.bulk_bodies.append(body)

    def count(self, *, index):
        return {"count": self.counts.get(index, 0)}


def test_ensure_creates_index_with_matching_dimension():
    client = FakeOSWriteClient()
    w = OpenSearchWriter(client)
    w.ensure_collection_or_index("mdc-code-context-titan1024", "titan1024")
    body = client.created["mdc-code-context-titan1024"]
    field = body["mappings"]["properties"]["embedding"]
    assert field["type"] == "knn_vector"
    assert field["dimension"] == 1024


def test_ensure_idempotent_when_compatible():
    client = FakeOSWriteClient(existing={
        "idx": {"embedding": {"type": "knn_vector", "dimension": 768}}
    })
    w = OpenSearchWriter(client)
    # mpnet768 -> 768 matches existing
    assert w.ensure_collection_or_index("idx", "mpnet768") == "idx"
    assert "idx" not in client.created  # not re-created


def test_ensure_refuses_incompatible_dimension():
    client = FakeOSWriteClient(existing={
        "idx": {"embedding": {"type": "knn_vector", "dimension": 1024}}
    })
    w = OpenSearchWriter(client)
    with pytest.raises(MappingConflictError):
        w.ensure_collection_or_index("idx", "mpnet768")  # 768 != 1024


def test_ensure_refuses_non_knn_field():
    client = FakeOSWriteClient(existing={
        "idx": {"embedding": {"type": "float"}}
    })
    w = OpenSearchWriter(client)
    with pytest.raises(MappingConflictError):
        w.ensure_collection_or_index("idx", "titan1024")


def test_bulk_insert_preserves_embedding_bytes():
    client = FakeOSWriteClient()
    w = OpenSearchWriter(client)
    recs = [
        {"id": "d1", "content": "x", "embedding": [0.0123456789, -1.0],
         "model_profile": "titan1024", "metadata": {"t": "gw"}},
    ]
    n = w.bulk_insert_vectors("idx", recs)
    assert n == 1
    body = client.bulk_bodies[0]
    # action line + doc line
    doc = body[1]
    assert doc["embedding"] == [0.0123456789, -1.0]
    assert doc["model_profile"] == "titan1024"


def test_tenant_prefix_index_preserved():
    client = FakeOSWriteClient()
    w = OpenSearchWriter(client)
    w.ensure_collection_or_index("gw_v17_mdc-jjobs-titan1024", "titan1024")
    assert "gw_v17_mdc-jjobs-titan1024" in client.created


# ── Neptune loader ────────────────────────────────────────────────────────────


def _loader(statuses):
    """Build a loader whose status() returns the given sequence."""
    seq = iter(statuses)

    def loader_fn(action, payload):
        if action == "start":
            return {"payload": {"loadId": "load-1"}}
        return {"payload": {"overallStatus": {"status": next(seq)}}}

    return NeptuneLoader(loader_fn, s3_loader_role_arn="arn:role",
                         poll_interval=0, sleep_fn=lambda s: None)


def test_loader_waits_until_complete():
    ld = _loader(["LOAD_IN_PROGRESS", "LOAD_IN_PROGRESS", STATUS_COMPLETE])
    assert ld.wait("load-1") == STATUS_COMPLETE


def test_loader_raises_on_failure():
    ld = _loader(["LOAD_IN_PROGRESS", "LOAD_FAILED"])
    with pytest.raises(NeptuneLoaderError) as exc:
        ld.wait("load-1")
    assert exc.value.status == "LOAD_FAILED"


def test_loader_start_returns_id_then_completes():
    ld = _loader([STATUS_COMPLETE])
    assert ld.load_graph_bundle("gw", "s3://b/pfx/graph/gw/", None) == STATUS_COMPLETE


def test_loader_start_without_id_raises():
    def loader_fn(action, payload):
        return {"payload": {}}
    ld = NeptuneLoader(loader_fn, s3_loader_role_arn="arn:role",
                       poll_interval=0, sleep_fn=lambda s: None)
    with pytest.raises(NeptuneLoaderError):
        ld.start("s3://b/pfx/")
