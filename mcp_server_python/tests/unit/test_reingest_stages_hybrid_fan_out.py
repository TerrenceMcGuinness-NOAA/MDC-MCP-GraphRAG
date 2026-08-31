"""Unit tests for reingest_stages.yaml hybrid fan-out semantics.

Feature: mpnet768-tenant-reingest-aug2026, Task 2.6.

Asserts: The two hybrid domains (workflow_docs, code_with_context) split into
external (shared) + local (per-tenant × N) sub-stages with the correct scope
on each.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

import reingest_state as rs  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_production(tmp_path: Path) -> rs.StateStore:
    """Initialize a fresh state from the production catalog and stages."""
    argv = [
        "--state-root", str(tmp_path),
        "--collection-version", "v9-0-0",
        "init",
        "--catalog", str(rs._DEFAULT_CATALOG),
        "--stages", str(rs._DEFAULT_STAGES),
        "--backend", "cots",
        "--embedding-profile", "mpnet768",
    ]
    rc = rs.main(argv)
    assert rc == 0
    return rs.StateStore(rs._state_dir(tmp_path, "v9-0-0"))


# ---------------------------------------------------------------------------
# Tests: workflow_docs hybrid domain
# ---------------------------------------------------------------------------


class TestWorkflowDocsHybridFanOut:
    """workflow_docs splits into external (shared-once) + local (per-tenant)."""

    def test_workflow_docs_external_is_shared_once(self, tmp_path):
        store = _init_production(tmp_path)
        units = store.units()

        ext_units = [u for u in units if u["stage"] == "workflow_docs_external"]
        assert len(ext_units) == 1
        assert ext_units[0]["tenant_id"] == rs.GLOBAL_TENANT
        assert ext_units[0]["scope"] == "shared"
        assert ext_units[0]["shared_once"] is True

    def test_workflow_docs_local_is_per_tenant(self, tmp_path):
        store = _init_production(tmp_path)
        units = store.units()

        local_units = [u for u in units if u["stage"] == "workflow_docs_local"]
        # One per tenant (5 tenants)
        assert len(local_units) == 5
        tenant_ids = {u["tenant_id"] for u in local_units}
        assert tenant_ids == {"gw", "gw_sfs", "gw_jedi_gfs", "gw_v17", "gw_gefs_v12"}

    def test_workflow_docs_local_scope_is_hybrid_local(self, tmp_path):
        store = _init_production(tmp_path)
        units = store.units()

        local_units = [u for u in units if u["stage"] == "workflow_docs_local"]
        for u in local_units:
            assert u["scope"] == "hybrid_local"
            assert u["shared_once"] is False

    def test_pdf_sources_is_shared_once(self, tmp_path):
        """pdf_sources (a sub-stage of workflow_docs_external) is shared-once."""
        store = _init_production(tmp_path)
        units = store.units()

        pdf_units = [u for u in units if u["stage"] == "pdf_sources"]
        assert len(pdf_units) == 1
        assert pdf_units[0]["tenant_id"] == rs.GLOBAL_TENANT
        assert pdf_units[0]["scope"] == "shared"
        assert pdf_units[0]["shared_once"] is True

    def test_pdf_sources_depends_on_workflow_docs_external(self, tmp_path):
        """pdf_sources depends on workflow_docs_external."""
        store = _init_production(tmp_path)
        units = store.units()

        pdf_unit = [u for u in units if u["stage"] == "pdf_sources"][0]
        assert "workflow_docs_external" in pdf_unit["depends_on"]

    def test_workflow_docs_local_depends_on_worktree(self, tmp_path):
        """workflow_docs_local depends on worktree (needs the tenant checkout)."""
        store = _init_production(tmp_path)
        units = store.units()

        local_units = [u for u in units if u["stage"] == "workflow_docs_local"]
        for u in local_units:
            assert "worktree" in u["depends_on"]


# ---------------------------------------------------------------------------
# Tests: code_with_context hybrid domain
# ---------------------------------------------------------------------------


class TestCodeWithContextHybridFanOut:
    """code_with_context_local is per-tenant; no external sub-stage today."""

    def test_code_with_context_local_is_per_tenant(self, tmp_path):
        store = _init_production(tmp_path)
        units = store.units()

        code_units = [u for u in units if u["stage"] == "code_with_context_local"]
        # One per tenant (5 tenants)
        assert len(code_units) == 5
        tenant_ids = {u["tenant_id"] for u in code_units}
        assert tenant_ids == {"gw", "gw_sfs", "gw_jedi_gfs", "gw_v17", "gw_gefs_v12"}

    def test_code_with_context_local_scope_is_tenant(self, tmp_path):
        store = _init_production(tmp_path)
        units = store.units()

        code_units = [u for u in units if u["stage"] == "code_with_context_local"]
        for u in code_units:
            assert u["scope"] == "tenant"
            assert u["shared_once"] is False

    def test_code_with_context_local_depends_on_reset(self, tmp_path):
        store = _init_production(tmp_path)
        units = store.units()

        code_units = [u for u in units if u["stage"] == "code_with_context_local"]
        for u in code_units:
            assert "reset" in u["depends_on"]

    def test_no_code_with_context_external_today(self, tmp_path):
        """code_with_context_external is reserved but not emitted today."""
        store = _init_production(tmp_path)
        units = store.units()

        ext_units = [u for u in units if u["stage"] == "code_with_context_external"]
        assert ext_units == []


# ---------------------------------------------------------------------------
# Tests: overall hybrid structure
# ---------------------------------------------------------------------------


class TestHybridStructureOverall:
    """The two hybrid domains have the correct total unit counts."""

    def test_total_workflow_docs_units(self, tmp_path):
        """workflow_docs: 1 external + 5 local + 1 pdf_sources = 7 total."""
        store = _init_production(tmp_path)
        units = store.units()

        wf_doc_units = [
            u for u in units
            if u["stage"] in ("workflow_docs_external", "workflow_docs_local",
                              "pdf_sources")
        ]
        assert len(wf_doc_units) == 7  # 1 + 5 + 1

    def test_total_code_with_context_units(self, tmp_path):
        """code_with_context: 5 local = 5 total."""
        store = _init_production(tmp_path)
        units = store.units()

        code_units = [
            u for u in units
            if u["stage"].startswith("code_with_context")
        ]
        assert len(code_units) == 5

    def test_tenancy_precheck_correct_for_hybrid_local(self, tmp_path):
        """Hybrid-local units get tenancy_precheck with their tenant's prefix."""
        store = _init_production(tmp_path)
        units = store.units()

        v17_local = [
            u for u in units
            if u["stage"] == "workflow_docs_local" and u["tenant_id"] == "gw_v17"
        ]
        assert len(v17_local) == 1
        assert v17_local[0]["tenancy_precheck"]["expected_prefix"] == "gw_v17_"
        assert v17_local[0]["tenancy_precheck"]["expected_tenant"] == "gw_v17"

    def test_tenancy_precheck_null_for_shared_external(self, tmp_path):
        """Shared external units get tenancy_precheck with empty prefix/null tenant."""
        store = _init_production(tmp_path)
        units = store.units()

        ext = [u for u in units if u["stage"] == "workflow_docs_external"][0]
        assert ext["tenancy_precheck"]["expected_prefix"] == ""
        assert ext["tenancy_precheck"]["expected_tenant"] is None
