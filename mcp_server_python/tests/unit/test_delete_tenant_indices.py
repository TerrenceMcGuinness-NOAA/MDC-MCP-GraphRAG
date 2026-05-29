"""Unit tests for delete_tenant_indices.py.

Feature: omd-tenants-2-v17-pilot, Requirements 7.1, 7.2, 7.3
"""
from __future__ import annotations

import fnmatch
import inspect
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from delete_tenant_indices import _delete_tenant_data, run_delete


def _write_catalog(tmp_path, tenants):
    """Write a tenants.yaml and return its path."""
    catalog_yaml = tmp_path / "tenants.yaml"
    catalog_yaml.write_text(yaml.dump({
        "schema_version": 1,
        "defaults": {"tenant_id": "gw", "staleness_threshold_days": 30},
        "tenants": tenants,
    }))
    return str(catalog_yaml)


_GW = {
    "tenant_id": "gw", "repo_ref": "R", "branch": "develop",
    "index_prefix": "", "label_prefix": "",
    "workflow_subdir": "develop", "lifecycle": "production",
    "description": "d", "extends": [],
}
_GW_V17 = {
    "tenant_id": "gw_v17", "repo_ref": "R", "branch": "dev/gfs.v17",
    "index_prefix": "gw_v17_", "label_prefix": "GW_V17_",
    "workflow_subdir": "dev-v17", "lifecycle": "staging",
    "description": "d", "extends": [],
}


# ---------------------------------------------------------------------------
# Real-contract test doubles (design Change 4)
#
# These mirror the ACTUAL surface the rollback script drives:
#   * the raw opensearch-py client: ``indices.get_alias`` / ``indices.delete``
#     (both sync) and a sync ``delete_by_query``;
#   * NeptuneAdapter.query(cypher, params=None, *, tenant=None) (async).
# They deliberately do NOT expose the fictional list_indices / delete_index /
# execute_cypher, so any drift back to those is caught by the suite.
# ---------------------------------------------------------------------------


class FakeIndices:
    """Stand-in for ``raw_client.indices`` (sync, like opensearch-py)."""

    def __init__(self, names):
        self._names = list(names)
        self.deleted: list[str] = []

    def get_alias(self, *, index):
        matched = {n: {} for n in self._names if fnmatch.fnmatch(n, index)}
        if not matched:
            # Real opensearch-py raises 404 when the glob matches nothing.
            from opensearchpy.exceptions import NotFoundError
            raise NotFoundError(404, "index_not_found_exception")
        return matched

    def delete(self, *, index):
        self.deleted.append(index)


class FakeRawClient:
    """Stand-in for the underlying opensearch-py ``OpenSearch`` client."""

    def __init__(self, names):
        self.indices = FakeIndices(names)
        self.dbq_calls: list[tuple] = []

    def delete_by_query(self, *, index, body):
        self.dbq_calls.append((index, body))


class FakeGraphDB:
    """Stand-in for ``NeptuneAdapter`` — only the real ``query`` method."""

    def __init__(self):
        self.queries: list[tuple] = []

    async def query(self, cypher, params=None, *, tenant=None):
        self.queries.append((cypher, params, tenant))
        return []


async def _call_run_delete(**kwargs):
    """Call ``run_delete``, dropping ``raw_os_client`` on the unfixed signature.

    Lets the SAME exploration-test body run against both the unfixed
    ``run_delete`` (no ``raw_os_client`` parameter) and the fixed one, so the
    failure on unfixed code surfaces behaviorally (``AttributeError`` from the
    deletion logic) rather than as a ``TypeError`` on an unexpected kwarg.
    """
    if "raw_os_client" not in inspect.signature(run_delete).parameters:
        kwargs.pop("raw_os_client", None)
    return await run_delete(**kwargs)


class _RealContractVectorDB:
    """Vector adapter exposing only the REAL surface (``_raw_client``)."""

    def __init__(self, raw):
        self._raw = raw

    def _raw_client(self):
        return self._raw


# ===========================================================================
# Task 1 — Bug Condition exploration (MUST FAIL on unfixed code)
# ===========================================================================


class TestC1RollbackCannotRunAgainstRealAdapters:
    """Property 1 (Bug Condition): a real CLI invocation against a valid
    non-empty-prefix tenant raises AttributeError before any deletion runs —
    because main() wires None adapters and the deletion logic calls methods
    absent from the real adapters.

    EXPECTED on UNFIXED code: FAILS (AttributeError). That failure is the
    success criterion for task 1. The same body PASSES on the fixed code
    (task 8). Real-contract fakes are supplied for the surfaces the FIXED code
    uses (raw_os_client, graph_db) so the run can complete once fixed; the
    UNFIXED failure still comes from the fictional/None calls.
    """

    @pytest.mark.asyncio
    async def test_none_wired_data_layer_no_attribute_error(self, tmp_path):
        """Test case 1 — None-wired vector_db. UNFIXED: the deletion logic
        calls ``vector_db.list_indices()`` on ``None`` →
        ``'NoneType' object has no attribute 'list_indices'``."""
        path = _write_catalog(tmp_path, [_GW, _GW_V17])
        code = await _call_run_delete(
            tenant_id="gw_v17", catalog_path=path, dry_run=False,
            vector_db=None, graph_db=FakeGraphDB(),
            raw_os_client=FakeRawClient(["gw_v17_mdc-code-titan1024"]),
        )
        assert code == 0

    @pytest.mark.asyncio
    async def test_real_contract_fake_no_attribute_error(self, tmp_path):
        """Test case 2 — real-contract fake vector_db (no ``list_indices``).
        UNFIXED: the deletion logic calls the fictional ``list_indices`` →
        ``'_RealContractVectorDB' object has no attribute 'list_indices'``."""
        path = _write_catalog(tmp_path, [_GW, _GW_V17])
        raw = FakeRawClient(["gw_v17_mdc-code-titan1024"])
        code = await _call_run_delete(
            tenant_id="gw_v17", catalog_path=path, dry_run=False,
            vector_db=_RealContractVectorDB(raw), graph_db=FakeGraphDB(),
            raw_os_client=raw,
        )
        assert code == 0


class TestUnknownTenant:
    @pytest.mark.asyncio
    async def test_unknown_tenant_exits_1(self, tmp_path):
        """Unknown tenant → exit 1, no AWS calls."""
        path = _write_catalog(tmp_path, [_GW, _GW_V17])
        code = await run_delete(
            tenant_id="nonexistent", catalog_path=path,
            dry_run=False, vector_db=None, graph_db=None,
        )
        assert code == 1


class TestEmptyPrefixProtection:
    @pytest.mark.asyncio
    async def test_gw_exits_2(self, tmp_path):
        """gw (empty prefix) → exit 2, no AWS calls."""
        path = _write_catalog(tmp_path, [_GW, _GW_V17])
        code = await run_delete(
            tenant_id="gw", catalog_path=path,
            dry_run=False, vector_db=None, graph_db=None,
        )
        assert code == 2


class TestDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_no_mutations(self, tmp_path):
        """--dry-run lists the real indices, exit 0, zero mutating calls."""
        path = _write_catalog(tmp_path, [_GW, _GW_V17])
        raw = FakeRawClient(["gw_v17_mdc-docs", "mdc-docs", "mdc-content-sha-registry"])
        graph = FakeGraphDB()

        code = await run_delete(
            tenant_id="gw_v17", catalog_path=path, dry_run=True,
            vector_db=None, graph_db=graph, raw_os_client=raw,
        )
        assert code == 0
        assert raw.indices.deleted == []
        assert raw.dbq_calls == []
        assert graph.queries == []


class TestSuccessfulDeletion:
    @pytest.mark.asyncio
    async def test_deletes_only_prefixed_data(self, tmp_path):
        """Successful run deletes only prefixed indices via the raw client and
        issues the DETACH DELETE through NeptuneAdapter.query (tenant=None)."""
        path = _write_catalog(tmp_path, [_GW, _GW_V17])
        raw = FakeRawClient([
            "mdc-workflow-docs-titan1024",
            "gw_v17_mdc-workflow-docs-titan1024",
            "gw_v17_mdc-code-titan1024",
            "gw_sfs_mdc-workflow-docs-titan1024",
            "mdc-content-sha-registry",
        ])
        graph = FakeGraphDB()

        code = await run_delete(
            tenant_id="gw_v17", catalog_path=path, dry_run=False,
            vector_db=None, graph_db=graph, raw_os_client=raw,
        )
        assert code == 0
        assert set(raw.indices.deleted) == {
            "gw_v17_mdc-workflow-docs-titan1024",
            "gw_v17_mdc-code-titan1024",
        }
        # System index and other tenants never touched.
        assert "mdc-content-sha-registry" not in raw.indices.deleted
        assert "gw_sfs_mdc-workflow-docs-titan1024" not in raw.indices.deleted
        # Neptune deletion via the real query() — scoped, tenant=None (no rewrite).
        assert len(graph.queries) == 1
        cypher, params, tenant = graph.queries[0]
        assert params == {"prefix": "GW_V17_"}
        assert tenant is None
        assert "DETACH DELETE" in cypher


class TestClearRegistryEntries:
    """--clear-registry-entries delete-by-query semantics (design Change 4)."""

    @pytest.mark.asyncio
    async def test_flag_issues_scoped_delete_by_query(self, tmp_path):
        """Flag set → one delete-by-query scoped to tenant_id via the raw
        client; the registry index itself is never deleted."""
        path = _write_catalog(tmp_path, [_GW, _GW_V17])
        raw = FakeRawClient(["gw_v17_mdc-code-titan1024", "mdc-content-sha-registry"])
        graph = FakeGraphDB()

        code = await run_delete(
            tenant_id="gw_v17", catalog_path=path, dry_run=False,
            vector_db=None, graph_db=graph, raw_os_client=raw,
            clear_registry_entries=True,
        )
        assert code == 0
        assert raw.dbq_calls == [
            ("mdc-content-sha-registry", {"query": {"term": {"tenant_id": "gw_v17"}}}),
        ]
        # The shared registry index is never deleted, only its tenant rows.
        assert "mdc-content-sha-registry" not in raw.indices.deleted

    @pytest.mark.asyncio
    async def test_without_flag_registry_untouched(self, tmp_path):
        """No flag → no delete-by-query at all."""
        path = _write_catalog(tmp_path, [_GW, _GW_V17])
        raw = FakeRawClient(["gw_v17_mdc-code-titan1024"])

        code = await run_delete(
            tenant_id="gw_v17", catalog_path=path, dry_run=False,
            vector_db=None, graph_db=FakeGraphDB(), raw_os_client=raw,
        )
        assert code == 0
        assert raw.dbq_calls == []

    @pytest.mark.asyncio
    async def test_dry_run_with_flag_no_mutation(self, tmp_path):
        """--dry-run + flag → plan only, zero mutations."""
        path = _write_catalog(tmp_path, [_GW, _GW_V17])
        raw = FakeRawClient(["gw_v17_mdc-code-titan1024", "mdc-content-sha-registry"])
        graph = FakeGraphDB()

        code = await run_delete(
            tenant_id="gw_v17", catalog_path=path, dry_run=True,
            vector_db=None, graph_db=graph, raw_os_client=raw,
            clear_registry_entries=True,
        )
        assert code == 0
        assert raw.indices.deleted == []
        assert raw.dbq_calls == []
        assert graph.queries == []

    @pytest.mark.asyncio
    async def test_gw_guard_refuses_even_with_flag(self, tmp_path):
        """gw empty-prefix guard still refuses (exit 2); no adapter calls."""
        path = _write_catalog(tmp_path, [_GW, _GW_V17])
        raw = FakeRawClient([])
        graph = FakeGraphDB()

        code = await run_delete(
            tenant_id="gw", catalog_path=path, dry_run=False,
            vector_db=None, graph_db=graph, raw_os_client=raw,
            clear_registry_entries=True,
        )
        assert code == 2
        assert raw.indices.deleted == []
        assert raw.dbq_calls == []
        assert graph.queries == []


class TestMockFidelity:
    """Property 3: the doubles expose exactly the surface the script drives,
    and none of the fictional adapter methods — so drift back to the fiction
    is caught by the suite."""

    def test_doubles_match_real_surface(self):
        raw = FakeRawClient([])
        assert hasattr(raw.indices, "get_alias")
        assert hasattr(raw.indices, "delete")
        assert hasattr(raw, "delete_by_query")
        assert inspect.iscoroutinefunction(FakeGraphDB.query)
        # The fictional adapter methods must NOT exist on the doubles.
        assert not hasattr(raw, "list_indices")
        assert not hasattr(raw, "delete_index")
        assert not hasattr(FakeGraphDB, "execute_cypher")


# ===========================================================================
# Task 5 — Fix Checking (PASSES on fixed code)
# ===========================================================================


class TestFixChecking:
    """Property 1 (Fix): a real CLI-shaped invocation completes without
    AttributeError and drives the real adapter surface."""

    @pytest.mark.asyncio
    async def test_completes_via_real_adapter_surface(self, tmp_path):
        path = _write_catalog(tmp_path, [_GW, _GW_V17])
        raw = FakeRawClient(["gw_v17_mdc-code-titan1024", "gw_v17_mdc-jjobs-titan1024"])
        graph = FakeGraphDB()

        code = await run_delete(
            tenant_id="gw_v17", catalog_path=path, dry_run=False,
            vector_db=None, graph_db=graph, raw_os_client=raw,
            clear_registry_entries=True,
        )
        assert code == 0  # completed without AttributeError
        # raw opensearch-py client used for list (get_alias) + delete
        assert set(raw.indices.deleted) == {
            "gw_v17_mdc-code-titan1024", "gw_v17_mdc-jjobs-titan1024",
        }
        # NeptuneAdapter.query used with tenant=None (no rewrite)
        assert len(graph.queries) == 1
        assert graph.queries[0][2] is None
        # one scoped registry delete-by-query via the raw client
        assert raw.dbq_calls == [
            ("mdc-content-sha-registry", {"query": {"term": {"tenant_id": "gw_v17"}}}),
        ]


# ===========================================================================
# Task 6 — Preservation (control-flow contract unchanged)
# ===========================================================================


class TestPreservationNoAdapterCalls:
    """Property 2: the guard paths exit with the same codes and make ZERO
    adapter calls, even when real-contract fakes are supplied."""

    @pytest.mark.asyncio
    async def test_unknown_tenant_exit_1_no_calls(self, tmp_path):
        path = _write_catalog(tmp_path, [_GW, _GW_V17])
        raw = FakeRawClient(["gw_v17_mdc-code-titan1024"])
        graph = FakeGraphDB()
        code = await run_delete(
            tenant_id="nope", catalog_path=path, dry_run=False,
            vector_db=None, graph_db=graph, raw_os_client=raw,
        )
        assert code == 1
        assert raw.indices.deleted == []
        assert raw.dbq_calls == []
        assert graph.queries == []

    @pytest.mark.asyncio
    async def test_gw_empty_prefix_exit_2_no_calls(self, tmp_path):
        path = _write_catalog(tmp_path, [_GW, _GW_V17])
        raw = FakeRawClient(["gw_v17_mdc-code-titan1024"])
        graph = FakeGraphDB()
        code = await run_delete(
            tenant_id="gw", catalog_path=path, dry_run=False,
            vector_db=None, graph_db=graph, raw_os_client=raw,
        )
        assert code == 2
        assert raw.indices.deleted == []
        assert raw.dbq_calls == []
        assert graph.queries == []


# ===========================================================================
# Task 7 — get_alias NotFoundError + edge cases
# ===========================================================================


class TestGetAliasNotFound:
    @pytest.mark.asyncio
    async def test_no_matching_indices_treated_as_zero(self, tmp_path):
        """get_alias raising NotFoundError (no index matches the glob) is
        treated as zero target indices — no crash, no deletions."""
        path = _write_catalog(tmp_path, [_GW, _GW_V17])
        raw = FakeRawClient([])  # get_alias("gw_v17_*") → NotFoundError
        graph = FakeGraphDB()

        code = await run_delete(
            tenant_id="gw_v17", catalog_path=path, dry_run=False,
            vector_db=None, graph_db=graph, raw_os_client=raw,
        )
        assert code == 0
        assert raw.indices.deleted == []
        # Neptune deletion still runs (graph nodes are independent of indices).
        assert len(graph.queries) == 1

    @pytest.mark.asyncio
    async def test_registry_index_never_deleted_only_rows(self, tmp_path):
        """--clear-registry-entries removes rows via delete_by_query but never
        deletes the registry index itself."""
        path = _write_catalog(tmp_path, [_GW, _GW_V17])
        raw = FakeRawClient(["gw_v17_mdc-code-titan1024"])
        graph = FakeGraphDB()

        code = await run_delete(
            tenant_id="gw_v17", catalog_path=path, dry_run=False,
            vector_db=None, graph_db=graph, raw_os_client=raw,
            clear_registry_entries=True,
        )
        assert code == 0
        assert len(raw.dbq_calls) == 1
        assert raw.dbq_calls[0][0] == "mdc-content-sha-registry"
        assert "mdc-content-sha-registry" not in raw.indices.deleted