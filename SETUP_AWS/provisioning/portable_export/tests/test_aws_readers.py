"""AWS reader contract tests (Task 6.1) + Property 5 (source immutability).

Asserts no mutating call lands on OpenSearch or Neptune during any reader
operation, and that Index_Family / label-family enumeration honours tenant
prefixes and node/relationship streaming is complete.

Requirements: 1.5, 7.1, 7.2, 7.3.
"""

from __future__ import annotations

import pytest

from portable_export.adapters import NodeRow, RelRow
from portable_export.adapters.neptune_reader import NeptuneReader, is_read_only
from portable_export.adapters.opensearch_reader import (
    READ_ONLY_METHODS,
    OpenSearchReader,
)

INDEX_PREFIXES = {
    "gw": "",
    "gw_sfs": "gw_sfs_",
    "gw_v17": "gw_v17_",
    "gw_gefs_v12": "gw_gefs_v12_",
    "gw_jedi_gfs": "gw_jedi_gfs_",
}
LABEL_PREFIXES = {
    "gw": "",
    "gw_sfs": "GW_SFS_",
    "gw_v17": "GW_V17_",
    "gw_gefs_v12": "GW_GEFS_V12_",
    "gw_jedi_gfs": "GW_JEDI_GFS_",
}

_MUTATING_OS = {"index", "bulk", "delete", "update", "create", "delete_by_query",
                "update_by_query", "reindex", "put_mapping"}


class FakeOpenSearch:
    """Records every method call; serves canned scroll pages."""

    def __init__(self, indices, docs_by_index):
        self._indices = list(indices)
        self._docs = docs_by_index
        self.calls: list[str] = []
        self._scrolls: dict[str, list] = {}
        self._seq = 0

    def list_indices(self):
        self.calls.append("list_indices")
        return list(self._indices)

    def count(self, *, index):
        self.calls.append("count")
        return {"count": len(self._docs.get(index, []))}

    def search(self, *, index, scroll, size, body):
        self.calls.append("search")
        self._seq += 1
        sid = f"s{self._seq}"
        # one page then empty
        docs = self._docs.get(index, [])
        self._scrolls[sid] = []  # remaining after first page
        hits = [{"_id": d["id"], "_source": d} for d in docs]
        return {"_scroll_id": sid, "hits": {"hits": hits}}

    def scroll(self, *, scroll_id, scroll):
        self.calls.append("scroll")
        return {"_scroll_id": scroll_id, "hits": {"hits": []}}

    def clear_scroll(self, *, scroll_id):
        self.calls.append("clear_scroll")
        return {}

    # mutating methods exist but must never be called by the reader
    def index(self, **kw):  # pragma: no cover
        self.calls.append("index")

    def bulk(self, **kw):  # pragma: no cover
        self.calls.append("bulk")

    def delete(self, **kw):  # pragma: no cover
        self.calls.append("delete")


# ── OpenSearch reader ───────────────────────────────────────────────────────


def _os_reader():
    docs = {
        "mdc-code-context-titan1024": [
            {"id": "d1", "content": "x", "embedding": [0.1, 0.2],
             "model_profile": "titan1024", "metadata": {"tenant_id": "gw"}},
            {"id": "d2", "content": "y", "embedding": [0.3, 0.4],
             "model_profile": "titan1024", "metadata": {"tenant_id": "gw"}},
        ],
        "gw_v17_mdc-code-context-titan1024": [
            {"id": "v1", "content": "z", "embedding": [0.5],
             "model_profile": "titan1024", "metadata": {"tenant_id": "gw_v17"}},
        ],
    }
    client = FakeOpenSearch(list(docs), docs)
    return OpenSearchReader(client, index_prefixes=INDEX_PREFIXES), client


def test_index_family_default_excludes_foreign_prefix():
    reader, _ = _os_reader()
    fam = reader.index_family_for_tenant("gw")
    assert fam == ["mdc-code-context-titan1024"]
    # foreign prefix excluded from default tenant
    assert "gw_v17_mdc-code-context-titan1024" not in fam


def test_index_family_non_default_tenant():
    reader, _ = _os_reader()
    assert reader.index_family_for_tenant("gw_v17") == [
        "gw_v17_mdc-code-context-titan1024"
    ]


def test_scroll_records_reads_embeddings_bitwise():
    reader, _ = _os_reader()
    batches = list(reader.scroll_records("mdc-code-context-titan1024", batch=10))
    recs = [r for b in batches for r in b]
    assert [r["id"] for r in recs] == ["d1", "d2"]
    assert recs[0]["embedding"] == [0.1, 0.2]
    assert recs[0]["model_profile"] == "titan1024"


def test_property5_opensearch_reader_is_read_only():
    reader, client = _os_reader()
    reader.list_index_families(["gw", "gw_v17"])
    reader.count_index("mdc-code-context-titan1024")
    list(reader.scroll_records("mdc-code-context-titan1024", batch=10))
    # every recorded call must be in the read-only allow-list
    assert set(client.calls) <= READ_ONLY_METHODS
    assert not (set(client.calls) & _MUTATING_OS)


# ── Neptune reader ────────────────────────────────────────────────────────────


class FakeNeptune:
    """Answers canned openCypher; records every query string."""

    def __init__(self):
        self.queries: list[str] = []

    def __call__(self, cypher, params=None):
        self.queries.append(cypher)
        c = cypher
        if "DISTINCT labels(n)" in c:
            return [{"labels": ["File"]}, {"labels": ["GW_V17_File"]},
                    {"labels": ["FortranSubroutine"]}]
        if "count(n)" in c:
            return [{"c": 2}]
        if "labels(a) AS la, count(r)" in c:
            return [{"la": ["File"], "c": 3}, {"la": ["GW_V17_File"], "c": 5}]
        if "properties(n) AS props" in c:
            if "SKIP 0" in c and ":`File`" in c:
                return [{"id": 1, "props": {"path": "a.py"}},
                        {"id": 2, "props": {"path": "b.py"}}]
            return []  # subsequent pages empty
        if "type(r) AS type" in c:
            if "SKIP 0" in c:
                return [
                    {"id": 10, "type": "CALLS", "start": 1, "end": 2,
                     "la": ["File"], "props": {"n": 1}},
                    {"id": 11, "type": "USES", "start": 99, "end": 2,
                     "la": ["GW_V17_File"], "props": {}},
                ]
            return []
        return []


def _nep_reader():
    fake = FakeNeptune()
    return NeptuneReader(fake, label_prefixes=LABEL_PREFIXES, page_size=1000), fake


def test_label_families_default_excludes_foreign():
    reader, _ = _nep_reader()
    fams = reader.label_families_for_tenant("gw")
    assert "File" in fams
    assert "FortranSubroutine" in fams
    assert "GW_V17_File" not in fams


def test_label_families_non_default():
    reader, _ = _nep_reader()
    assert reader.label_families_for_tenant("gw_v17") == ["GW_V17_File"]


def test_stream_nodes_complete():
    reader, _ = _nep_reader()
    nodes = list(reader.stream_nodes("gw"))
    # File label yields 2 nodes; FortranSubroutine label yields 0 (page empty)
    assert all(isinstance(n, NodeRow) for n in nodes)
    paths = sorted(n.properties.get("path") for n in nodes if n.properties.get("path"))
    assert paths == ["a.py", "b.py"]


def test_stream_relationships_filters_by_tenant():
    reader, _ = _nep_reader()
    rels = list(reader.stream_relationships("gw"))
    # only the CALLS rel (start node labeled File) belongs to gw
    assert [r.type for r in rels] == ["CALLS"]
    assert isinstance(rels[0], RelRow)


def test_property5_neptune_reader_only_read_queries():
    reader, fake = _nep_reader()
    reader.list_graph_label_families(["gw", "gw_v17"])
    reader.count_nodes("gw")
    reader.count_relationships("gw")
    list(reader.stream_nodes("gw"))
    list(reader.stream_relationships("gw"))
    assert all(is_read_only(q) for q in fake.queries)


def test_reader_refuses_mutating_query():
    reader, _ = _nep_reader()
    with pytest.raises(RuntimeError):
        reader._run("MATCH (n) DELETE n")
