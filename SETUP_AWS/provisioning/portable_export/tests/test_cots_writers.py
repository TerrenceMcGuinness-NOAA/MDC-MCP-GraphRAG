"""COTS writer contract tests (Task 8.1).

In-memory ChromaDB + Neo4j fixtures (driver mocks); bitwise embedding
pass-through; tenant prefix preservation; missing required-field handling
(R2.4).

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5.
"""

from __future__ import annotations

import pytest

from portable_export.adapters import NodeRow, RelRow
from portable_export.adapters.chromadb_writer import (
    ChromaDBWriter,
    ChromaVersionError,
    assert_supported_version,
    missing_required_fields,
)
from portable_export.adapters.neo4j_writer import (
    Neo4jVersionError,
    Neo4jWriter,
    build_admin_import_command,
)


# ── ChromaDB fake ─────────────────────────────────────────────────────────────


class FakeCollection:
    def __init__(self):
        self.ids = []
        self.documents = []
        self.embeddings = []
        self.metadatas = []

    def add(self, *, ids, documents, embeddings, metadatas):
        self.ids += list(ids)
        self.documents += list(documents)
        self.embeddings += list(embeddings)
        self.metadatas += list(metadatas)

    def count(self):
        return len(self.ids)


class FakeChroma:
    def __init__(self):
        self.collections: dict[str, FakeCollection] = {}

    def get_or_create_collection(self, name):
        return self.collections.setdefault(name, FakeCollection())

    def list_collections(self):
        return list(self.collections)


def test_chromadb_version_guard():
    assert_supported_version("0.5.0")
    with pytest.raises(ChromaVersionError):
        assert_supported_version("0.3.9")
    with pytest.raises(ChromaVersionError):
        assert_supported_version("0.6.0")


def test_chromadb_bitwise_embedding_passthrough():
    chroma = FakeChroma()
    w = ChromaDBWriter(chroma, version="0.5.0")
    recs = [
        {"id": "d1", "content": "x", "embedding": [0.0123456789, -1.0, 2.5e-08],
         "model_profile": "titan1024", "metadata": {"tenant_id": "gw"}},
    ]
    result = w.bulk_insert_vectors("mdc-code-context-titan1024", recs)
    assert result.loaded == 1
    coll = chroma.collections["mdc-code-context-titan1024"]
    assert coll.embeddings[0] == [0.0123456789, -1.0, 2.5e-08]
    # model_profile carried into metadata
    assert coll.metadatas[0]["model_profile"] == "titan1024"


def test_chromadb_tenant_prefix_collection_preserved():
    chroma = FakeChroma()
    w = ChromaDBWriter(chroma, version="0.5.0")
    w.bulk_insert_vectors("gw_v17_mdc-jjobs-titan1024", [
        {"id": "d", "content": "c", "embedding": [0.1], "model_profile": "titan1024"}
    ])
    assert "gw_v17_mdc-jjobs-titan1024" in chroma.collections


def test_missing_required_field_recorded_and_skipped():
    chroma = FakeChroma()
    w = ChromaDBWriter(chroma, version="0.5.0")
    recs = [
        {"id": "ok", "content": "c", "embedding": [0.1], "model_profile": "titan1024"},
        {"id": "bad1", "content": "c", "embedding": [], "model_profile": "titan1024"},
        {"id": "bad2", "content": "c", "model_profile": "titan1024"},  # no embedding
        {"content": "c", "embedding": [0.2], "model_profile": "titan1024"},  # no id
    ]
    result = w.bulk_insert_vectors("c1", recs)
    assert result.loaded == 1
    assert len(result.errors) == 3
    # remaining valid record still loaded (R2.4 continue)
    assert chroma.collections["c1"].ids == ["ok"]


def test_missing_required_fields_helper():
    assert missing_required_fields(
        {"id": "x", "content": "c", "embedding": [0.1], "model_profile": "m"}
    ) == []
    assert set(missing_required_fields({"id": "x"})) == {
        "content", "embedding", "model_profile"
    }


# ── Neo4j ────────────────────────────────────────────────────────────────────


class FakeSession:
    def __init__(self, store):
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, cypher, **params):
        self.store.append((cypher, params))
        if "count(n)" in cypher:
            return [{"c": self.store_nodes}]
        if "count(r)" in cypher:
            return [{"c": self.store_rels}]
        return []

    store_nodes = 0
    store_rels = 0


def test_neo4j_version_guard():
    assert_supported_version_ok = Neo4jWriter(session_fn=lambda: FakeSession([]),
                                              version="5.12.0")
    assert assert_supported_version_ok is not None
    with pytest.raises(Neo4jVersionError):
        Neo4jWriter(version="3.5.0")


def test_neo4j_admin_import_command_quotes_paths():
    cmd = build_admin_import_command(
        database="neo4j",
        node_csvs=["/tmp/File-000.csv", "/tmp/weird name.csv"],
        rel_csvs=["/tmp/CALLS-000.csv"],
    )
    assert "--nodes=/tmp/File-000.csv" in cmd
    assert "'/tmp/weird name.csv'" in cmd  # shell-quoted
    assert "--relationships=/tmp/CALLS-000.csv" in cmd


def test_neo4j_bulk_load_invokes_runner():
    calls = []
    w = Neo4jWriter(runner=lambda cmd: calls.append(cmd), version="5.0.0")
    res = w.load_graph_bundle("gw", ["/tmp/File-000.csv"], ["/tmp/CALLS-000.csv"])
    assert res.method == "bulk"
    assert len(calls) == 1
    assert "neo4j-admin database import full" in calls[0]


def test_neo4j_transactional_nodes_preserve_labels():
    statements = []
    w = Neo4jWriter(session_fn=lambda: FakeSession(statements), version="5.0.0")
    nodes = [
        NodeRow(id="1", label="File", properties={"path": "a.py"}),
        NodeRow(id="2", label="GW_V17_FortranSubroutine", properties={"name": "calc"}),
    ]
    n = w.write_nodes(nodes)
    assert n == 2
    cyphers = " ".join(s[0] for s in statements)
    assert ":`File`" in cyphers
    assert ":`GW_V17_FortranSubroutine`" in cyphers  # tenant prefix preserved


def test_neo4j_transactional_relationships():
    statements = []
    w = Neo4jWriter(session_fn=lambda: FakeSession(statements), version="5.0.0")
    rels = [RelRow(id="r1", type="CALLS", start="1", end="2", properties={"n": 3})]
    n = w.write_relationships(rels)
    assert n == 1
    assert any(":`CALLS`" in s[0] for s in statements)
