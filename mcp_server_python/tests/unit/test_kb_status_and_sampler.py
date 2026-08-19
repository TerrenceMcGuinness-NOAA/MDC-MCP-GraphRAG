"""Unit tests for the KB-status count fix + ChromaDB metadata sampler.

rag-data-plane-gap-closure Tasks 5.3 (sample_metadata) and 6.3
(get_knowledge_base_status document count).
"""
from __future__ import annotations

import asyncio

from src.data.chromadb_adapter import ChromaDBAdapter
from src.tools import semantic_search as ss
from src.tools.semantic_search import _default_scope_indices


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
    """ChromaDB returns `collections_detail`; the default-tenant filter must
    recognize it and sum the in-scope subset (root cause of the Total
    Documents: 0 bug). shared-scope-query-routing Task 10.2 renamed the
    empty-prefix path to _default_scope_indices; the ChromaDB-shaped-payload
    case it once covered is re-expressed here against that helper."""
    health = {
        "status": "healthy",
        "collections_detail": {
            "mdc-workflow-docs-mpnet768": 100,
            "mdc-code-context-mpnet768": 50,
            "gw_v17_mdc-code-context-mpnet768": 7,  # another tenant's index
        },
    }
    # Default gw (empty prefix) excludes gw_v17_-prefixed → total 150, 2 indices.
    names, detail, total = _default_scope_indices(
        health, others=("gw_v17_",)
    )
    assert total == 150
    assert len(names) == 2
    assert "gw_v17_mdc-code-context-mpnet768" not in names


def test_nondefault_scoping_via_tenant_collection_set():
    """Non-default scoping is now the Read_Router's job, not a name-shape
    filter: a prefixed tenant's collection set carries its own prefixed
    members and the unprefixed shared members, and excludes any other
    tenant's prefixed index (Task 10.2)."""
    from src.config.tenants import Tenant
    from src.data.read_router import tenant_collection_set

    tenant = Tenant(
        tenant_id="gw_v17", repo_ref="R", branch="b",
        index_prefix="gw_v17_", label_prefix="GW_V17_",
        workflow_subdir="dev-v17", lifecycle="staging",
    )
    names = tenant_collection_set(tenant, profile="mpnet768").physical_names
    assert any(n.startswith("gw_v17_") for n in names)
    assert any(not n.startswith("gw_v17_") for n in names)
    # never another tenant's prefix
    assert not any(n.startswith("gw_sfs_") for n in names)


# ── cots-backend-observability-parity R3 — KB-status vector block ────────


class _ChromaShapeVectorDB:
    """Vector-db double returning a ChromaDB-shaped deep health payload
    (per-collection counts under ``collections_detail``, no OpenSearch keys)."""

    def __init__(self, collections_detail: dict[str, int]):
        self._detail = collections_detail

    async def health_check(self, *, deep: bool = False):  # noqa: ARG002
        return {
            "status": "healthy",
            "collections": list(self._detail.keys()),
            "collections_detail": dict(self._detail),
            "total_documents": sum(self._detail.values()),
        }


def test_kb_status_vector_block_healthy_with_chromadb_counts():
    """R3.1/R3.2: on a ChromaDB-shaped payload the vector block reports the
    summed document count and ``[OK] Healthy`` (not the false 0/Unhealthy)."""
    from src.tools.semantic_search import _render_vector_status_block

    vdb = _ChromaShapeVectorDB(
        {"mdc-workflow-docs-mpnet768": 100, "mdc-code-context-mpnet768": 50}
    )
    lines = asyncio.run(_render_vector_status_block(vdb))
    text = "\n".join(lines)
    assert "- **Total Documents:** 150" in text
    assert "[OK] Healthy" in text
    assert "[ERROR] Unhealthy" not in text


def test_kb_status_vector_block_fresh_tenant_zero_collections_is_healthy():
    """R3.3: a tenant that owns no applicable collections is healthy, not
    punished as unhealthy."""
    from src.tools.semantic_search import _render_vector_status_block

    vdb = _ChromaShapeVectorDB({})
    lines = asyncio.run(_render_vector_status_block(vdb))
    text = "\n".join(lines)
    assert "- **Total Documents:** 0" in text
    assert "[OK] Healthy" in text
    assert "[ERROR] Unhealthy" not in text


# ── Task 11.1 / 11.3 — tenant-scoped integrity sampling ────────────────


class _RecordingSampleVDB:
    """Vector-db double recording every ``(collection)`` sample call.

    ``per_collection`` maps a physical name to the metadata list it returns;
    a name absent from the map returns ``[]`` (an absent / empty member).
    """

    def __init__(self, per_collection: dict | None = None) -> None:
        self._pc = per_collection or {}
        self.calls: list = []

    async def sample_metadata(self, collection=None, limit=50, *, n=None):
        self.calls.append(collection)
        eff = n if n is not None else limit
        return list((self._pc.get(collection) or [])[:eff])


def _v17_tenant():
    from src.config.tenants import Tenant

    return Tenant(
        tenant_id="gw_v17", repo_ref="R", branch="b",
        index_prefix="gw_v17_", label_prefix="GW_V17_",
        workflow_subdir="dev-v17", lifecycle="staging",
    )


def test_default_tenant_union_is_five_base_collections():
    """R10.5 (router level): the Default_Tenant's union across all five
    logical collections is the five unprefixed base collections.

    The default integrity *sampler* itself keeps the legacy global
    ``sample_metadata`` call (see the next test) because R6.3 byte-
    equivalence takes precedence over R10's union-sampling for the default
    tenant -- a deviation forced by the immutable byte-equivalence baseline
    and by the minimal ``sample_metadata(n)`` doubles used elsewhere."""
    from src.data.read_router import tenant_collection_set

    names = tenant_collection_set(None, profile="titan1024").physical_names
    assert len(names) == 5
    assert all(not n.startswith("gw_") for n in names)


def test_default_sampler_uses_legacy_global_call():
    """Default tenant: a single unscoped ``sample_metadata`` call
    (collection defaults to None) -- byte-equivalent to pre-change."""
    vdb = _RecordingSampleVDB()
    sampler = ss._build_vector_sampler(vdb, None)
    asyncio.run(sampler(10))
    assert vdb.calls == [None]


def test_scoped_sampler_only_touches_union_members():
    """Non-default tenant: the sampler names each union member explicitly
    and never touches a foreign / bookkeeping collection (R10.1, R10.2)."""
    tenant = _v17_tenant()
    from src.data.read_router import tenant_collection_set

    members = list(tenant_collection_set(tenant).physical_names)
    vdb = _RecordingSampleVDB(
        {m: [{"i": j} for j in range(3)] for m in members}
    )
    sampler = ss._build_vector_sampler(vdb, tenant)
    asyncio.run(sampler(20))
    assert set(vdb.calls) == set(members)
    assert None not in vdb.calls


def test_scoped_sampler_absent_and_empty_members_contribute_zero():
    """R10.7: an absent member and a zero-document member each contribute
    zero records while the remaining members are still sampled."""
    tenant = _v17_tenant()
    from src.data.read_router import tenant_collection_set

    members = list(tenant_collection_set(tenant).physical_names)
    pc = {members[0]: [{"a": 1}, {"a": 2}], members[1]: []}
    vdb = _RecordingSampleVDB(pc)
    counts: dict = {}
    got = asyncio.run(
        ss._allocate_scoped_sample(vdb, members, 10, counts)
    )
    assert counts[members[0]] == 2
    assert counts[members[1]] == 0
    for m in members[2:]:
        assert counts[m] == 0
    assert len(got) == 2


def test_scoped_sampler_dedups_identical_records():
    """De-duplication collapses byte-identical records a stubbed adapter
    returns for every member -- the mechanism that keeps the default report
    byte-equivalent and bounds the draw."""
    tenant = _v17_tenant()
    from src.data.read_router import tenant_collection_set

    members = list(tenant_collection_set(tenant).physical_names)
    same = [{"file_path": "a"}, {"file_path": "b"}, {"file_path": "c"}]
    vdb = _RecordingSampleVDB({m: list(same) for m in members})
    got = asyncio.run(ss._allocate_scoped_sample(vdb, members, 25, {}))
    assert len(got) == 3


def test_integrity_out_of_range_sample_size_clamps_and_states(
    monkeypatch, tmp_path
):
    """R10.8: an out-of-range sample_size clamps to [1,1000] and the value
    used is stated in the rendered report; R10.3: each union member is
    named (non-default tenant)."""
    tenant = _v17_tenant()
    from src.data.read_router import tenant_collection_set

    members = list(tenant_collection_set(tenant).physical_names)
    vdb = _RecordingSampleVDB({m: [{"x": 1}] for m in members})

    class _Data:
        def __init__(self):
            self.vector_db = vdb
            self.graph_db = None

    monkeypatch.setattr(ss, "_tenant", lambda: tenant)
    text = asyncio.run(
        ss._tool_check_knowledge_integrity(
            _Data(), sample_size=5000, repo_base=tmp_path
        )
    )
    assert "clamped to 1000" in text
    assert "requested 5000" in text
    for m in members:
        assert m in text


def test_integrity_default_tenant_has_no_sampled_collections_row(
    monkeypatch, tmp_path
):
    """R6.3: the default (no-prefix) report omits the Task 10.3 per-member
    row, keeping the gw report byte-equivalent."""
    vdb = _RecordingSampleVDB()

    class _Data:
        def __init__(self):
            self.vector_db = vdb
            self.graph_db = None

    monkeypatch.setattr(ss, "_tenant", lambda: None)
    text = asyncio.run(
        ss._tool_check_knowledge_integrity(
            _Data(), sample_size=25, repo_base=tmp_path
        )
    )
    assert "Sampled Collections" not in text


# ── Task 10.4 — Isolation_Probe reported as pass / skip / fail ─────────
# The pass/skip/fail wiring is the existing smoke-registry + utility
# machinery (SkipProbe -> status="skip", counted separately from fail).
# These tests pin that skip is a third outcome, not a flavour of pass.


def test_skipprobe_yields_skip_distinct_from_pass_and_fail():
    """R11.4/R11.7: a probe raising SkipProbe reports ``skip`` -- distinct
    from ``pass`` (returns True) and ``fail`` (raises) -- and carries the
    blocking condition in ``error``."""
    from src.tools.smoke_queries import (
        SkipProbe,
        SmokeQueryDef,
        SmokeQueryRegistry,
    )

    reg = SmokeQueryRegistry()

    async def _skip(_data, _mcp):
        raise SkipProbe("branch_isolation: requires both gw and gw_v17")

    async def _pass(_data, _mcp):
        return True

    async def _fail(_data, _mcp):
        raise RuntimeError("boom")

    skip_def = SmokeQueryDef("utility", "skip probe", _skip)
    pass_def = SmokeQueryDef("utility", "pass probe", _pass)
    fail_def = SmokeQueryDef("utility", "fail probe", _fail)

    skip_res = asyncio.run(reg._run_single(skip_def, object(), None))
    pass_res = asyncio.run(reg._run_single(pass_def, object(), None))
    fail_res = asyncio.run(reg._run_single(fail_def, object(), None))

    assert skip_res.status == "skip"
    assert pass_res.status == "pass"
    assert fail_res.status == "fail"
    assert "requires both gw and gw_v17" in skip_res.error


def test_health_functional_summary_counts_skip_distinctly():
    """The health render tallies skip separately from pass and fail, so a
    skipped Isolation_Probe never reads as a pass."""
    from src.tools.smoke_queries import ModuleResult
    from src.tools.utility import _functional_summary

    results = [
        ModuleResult("a", "pass", 1),
        ModuleResult("branch_isolation", "skip", 0, error="not runnable"),
        ModuleResult("c", "fail", 2, error="boom"),
    ]
    summary = _functional_summary(results)
    assert summary["passed"] == 1
    assert summary["skipped"] == 1
    assert summary["failed"] == 1
