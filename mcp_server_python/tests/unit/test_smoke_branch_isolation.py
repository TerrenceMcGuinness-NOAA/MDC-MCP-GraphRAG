"""Tests for the realigned ``_smoke_branch_isolation`` probe.

shared-scope-query-routing Task 7.6 (Requirements 8.1-8.8). Supersedes
the omd-tenants-2-v17-pilot R4.1 assertion-4 tests: the vector-side
origin test now derives a hit's originating tenant from the attached
``physical_collection`` (Task 7.3) rather than from a ``metadata.source``
substring (which R8.4 forbids). The two graph-side assertions are
unchanged and their query text is asserted byte-identical to the
pre-change form (R8.5).

Hermetic: a small fake vector adapter returns canned hits keyed by
``(logical, tenant_id)`` and a fixed Collection_Condition; the graph
adapter is an ``AsyncMock``. No live backend.
"""
from __future__ import annotations

import inspect

import pytest
import yaml
from unittest.mock import AsyncMock, MagicMock

from src.data.read_router import CollectionCondition
from src.tools.smoke_queries import SkipProbe, _smoke_branch_isolation

pytestmark = pytest.mark.unit

_DOCS = "global-workflow-docs-v8-0-0"
_EE2 = "ee2-standards-v5-0-0-enhanced"


@pytest.fixture
def both_tenants_catalog(tmp_path, monkeypatch):
    """Write a catalog with both gw and gw_v17 and point the env at it."""
    catalog_yaml = tmp_path / "tenants.yaml"
    catalog_yaml.write_text(yaml.dump({
        "schema_version": 1,
        "defaults": {"tenant_id": "gw", "staleness_threshold_days": 30},
        "tenants": [
            {"tenant_id": "gw", "repo_ref": "NOAA-EMC/global-workflow",
             "branch": "develop", "index_prefix": "", "label_prefix": "",
             "workflow_subdir": "develop", "lifecycle": "production",
             "description": "t", "extends": []},
            {"tenant_id": "gw_v17", "repo_ref": "NOAA-EMC/global-workflow",
             "branch": "dev/gfs.v17", "index_prefix": "gw_v17_",
             "label_prefix": "GW_V17_", "workflow_subdir": "dev-v17",
             "lifecycle": "staging", "description": "t", "extends": []},
        ],
    }))
    monkeypatch.setenv("MCP_TENANT_CATALOG_PATH", str(catalog_yaml))
    return catalog_yaml


class _FakeVector:
    """Canned vector adapter keyed by ``(logical, tenant_id)``."""

    def __init__(
        self,
        hits_by_key: dict[tuple[str, str], list[dict]],
        *,
        condition: CollectionCondition = (
            CollectionCondition.PROVISIONED_POPULATED
        ),
        raise_on: set[tuple[str, str]] | None = None,
    ) -> None:
        self._hits = hits_by_key
        self._condition = condition
        self._raise_on = raise_on or set()

    async def query(self, logical, query_text, *, k=10, tenant=None, **kw):
        tid = tenant.tenant_id if tenant is not None else "gw"
        if (logical, tid) in self._raise_on:
            raise RuntimeError("simulated query error")
        return [dict(h) for h in self._hits.get((logical, tid), [])]

    async def collection_condition(self, physical):
        return self._condition


def _data(vector: _FakeVector) -> MagicMock:
    """Build a ``data`` facade: fake vector + graph passing both graph
    assertions (v17 has WDQMS, gw does not)."""
    data = MagicMock()
    data.vector_db = vector
    data.graph_db.query = AsyncMock(side_effect=[
        [{"name": "JGDAS_ATMOS_ANALYSIS_WDQMS"}],  # v17 has it
        [],  # gw does not
    ])
    return data


def _happy_hits() -> dict[tuple[str, str], list[dict]]:
    return {
        (_DOCS, "gw_v17"): [
            {"physical_collection": "mdc-workflow-docs-titan1024",
             "metadata": {}},
            {"physical_collection": "gw_v17_mdc-workflow-docs-titan1024",
             "metadata": {}},
        ],
        (_DOCS, "gw"): [
            {"physical_collection": "mdc-workflow-docs-titan1024",
             "metadata": {}},
        ],
        (_EE2, "gw_v17"): [
            {"physical_collection": "mdc-ee2-standards-titan1024",
             "metadata": {}},
        ],
    }


# ── happy path + graph assertions ──────────────────────────────────────


@pytest.mark.asyncio
async def test_probe_passes_when_scopes_are_correct(both_tenants_catalog):
    """R8.2/R8.3/R8.6: shared reaches gw_v17, branch-local stays scoped."""
    result = await _smoke_branch_isolation(_data(_FakeVector(_happy_hits())),
                                           None)
    assert result is True


@pytest.mark.asyncio
async def test_r41_1_wdqms_not_found_under_v17(both_tenants_catalog):
    """Graph assertion 1 unchanged: WDQMS missing under gw_v17 -> R4.1#1."""
    data = MagicMock()
    data.vector_db = _FakeVector(_happy_hits())
    data.graph_db.query = AsyncMock(return_value=[])
    with pytest.raises(RuntimeError, match="R4.1#1"):
        await _smoke_branch_isolation(data, None)


@pytest.mark.asyncio
async def test_r41_2_wdqms_found_under_gw(both_tenants_catalog):
    """Graph assertion 2 unchanged: WDQMS under gw -> R4.1#2."""
    data = MagicMock()
    data.vector_db = _FakeVector(_happy_hits())
    data.graph_db.query = AsyncMock(side_effect=[
        [{"name": "JGDAS_ATMOS_ANALYSIS_WDQMS"}],
        [{"name": "JGDAS_ATMOS_ANALYSIS_WDQMS"}],
    ])
    with pytest.raises(RuntimeError, match="R4.1#2"):
        await _smoke_branch_isolation(data, None)


# ── R8.6 / R8.3 reachability failures ──────────────────────────────────


@pytest.mark.asyncio
async def test_r86_missing_shared_docs_half(both_tenants_catalog):
    """R8.6: gw_v17 docs with no shared (unprefixed) hit fails."""
    hits = _happy_hits()
    hits[(_DOCS, "gw_v17")] = [
        {"physical_collection": "gw_v17_mdc-workflow-docs-titan1024",
         "metadata": {}},
    ]
    with pytest.raises(RuntimeError, match="R8.6"):
        await _smoke_branch_isolation(_data(_FakeVector(hits)), None)


@pytest.mark.asyncio
async def test_r83_missing_shared_ee2(both_tenants_catalog):
    """R8.3: gw_v17 ee2 with no shared hit fails (empty + populated cond)."""
    hits = _happy_hits()
    hits[(_EE2, "gw_v17")] = []  # empty, but condition below says populated
    data = _data(_FakeVector(
        hits, condition=CollectionCondition.PROVISIONED_POPULATED
    ))
    with pytest.raises(RuntimeError, match="R8.3"):
        await _smoke_branch_isolation(data, None)


# ── R8.2 isolation violations ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_r82_default_tenant_sees_prefixed_content(both_tenants_catalog):
    """R8.2: gw docs returning gw_v17-prefixed content fails."""
    hits = _happy_hits()
    hits[(_DOCS, "gw")] = [
        {"physical_collection": "gw_v17_mdc-workflow-docs-titan1024",
         "metadata": {}},
    ]
    with pytest.raises(RuntimeError, match="R8.2"):
        await _smoke_branch_isolation(_data(_FakeVector(hits)), None)


# ── R8.4 classification follows the name, not metadata ─────────────────


@pytest.mark.asyncio
async def test_r84_classification_follows_physical_name(both_tenants_catalog):
    """R8.4: metadata that contradicts the attached name is ignored.

    A gw_v17-owned hit whose metadata.source says ``/develop/`` is NOT a
    leak (its physical name carries the gw_v17 prefix); a shared hit whose
    metadata claims gw_v17 is still shared. The probe passes.
    """
    hits = _happy_hits()
    hits[(_DOCS, "gw_v17")] = [
        {"physical_collection": "mdc-workflow-docs-titan1024",
         "metadata": {"source": "/mnt/workflow/dev-v17/docs/x.rst"}},
        {"physical_collection": "gw_v17_mdc-workflow-docs-titan1024",
         "metadata": {"source": "/mnt/workflow/develop/docs/mpas.md"}},
    ]
    result = await _smoke_branch_isolation(_data(_FakeVector(hits)), None)
    assert result is True


# ── R8.7 missing provenance ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_r87_hit_without_provenance_fails(both_tenants_catalog):
    """R8.7: a hit carrying no physical_collection fails naming coll+tenant."""
    hits = _happy_hits()
    hits[(_DOCS, "gw_v17")] = [{"metadata": {}}]  # no physical_collection
    with pytest.raises(RuntimeError, match="R8.7"):
        await _smoke_branch_isolation(_data(_FakeVector(hits)), None)


# ── R8.8 unreachable / empty / error, kept distinct ────────────────────


@pytest.mark.asyncio
async def test_r88_unprovisioned_member(both_tenants_catalog):
    """R8.8: an empty read whose member is unprovisioned fails as such."""
    hits = _happy_hits()
    hits[(_DOCS, "gw_v17")] = []
    data = _data(_FakeVector(
        hits, condition=CollectionCondition.UNPROVISIONED
    ))
    with pytest.raises(RuntimeError, match="R8.8.*unprovisioned"):
        await _smoke_branch_isolation(data, None)


@pytest.mark.asyncio
async def test_r88_provisioned_empty_member(both_tenants_catalog):
    """R8.8: provisioned-empty is kept distinct from unprovisioned."""
    hits = _happy_hits()
    hits[(_DOCS, "gw_v17")] = []
    data = _data(_FakeVector(
        hits, condition=CollectionCondition.PROVISIONED_EMPTY
    ))
    with pytest.raises(RuntimeError, match="R8.8.*provisioned-empty"):
        await _smoke_branch_isolation(data, None)


@pytest.mark.asyncio
async def test_r88_query_error(both_tenants_catalog):
    """R8.8: a query error is reported distinctly from a condition."""
    data = _data(_FakeVector(_happy_hits(), raise_on={(_DOCS, "gw_v17")}))
    with pytest.raises(RuntimeError, match="R8.8.*query error"):
        await _smoke_branch_isolation(data, None)


# ── R8.5 graph-side query text is byte-identical to pre-change ─────────


def test_graph_side_queries_are_byte_identical():
    """R8.5: the two label-scoped graph query strings are unchanged."""
    source = inspect.getsource(_smoke_branch_isolation)
    # The two fragments the query text splits into across the string
    # literals, byte-identical to the pre-change form.
    assert (
        "MATCH (f:ShellScript {name:'JGDAS_ATMOS_ANALYSIS_WDQMS'})-[r]-(m) "
        in source
    )
    assert "RETURN f.name AS name LIMIT 1" in source
    # Exactly two graph queries (v17 + gw), one per tenant.
    assert source.count(
        "MATCH (f:ShellScript {name:'JGDAS_ATMOS_ANALYSIS_WDQMS'})"
    ) == 2
