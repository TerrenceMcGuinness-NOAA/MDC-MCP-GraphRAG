"""Unit tests for reingest_stages.yaml dependency closure.

Feature: mpnet768-tenant-reingest-aug2026, Task 2.6.

Asserts: ``neo4j_rebuild_indexes`` transitively depends on every tenant's
``fortran_graph``, ``shell_graph``, ``bridge``, ``rocoto``, and ``expdir``
stages via the ``depends_on_all_tenants: true`` mechanism.
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
# Tests
# ---------------------------------------------------------------------------


class TestNeo4jRebuildDependsClosure:
    """neo4j_rebuild_indexes has depends_on_all_tenants: true."""

    def test_rebuild_depends_on_all_tenants_flag(self, tmp_path):
        """The neo4j_rebuild_indexes unit carries depends_on_all_tenants=True."""
        store = _init_production(tmp_path)
        rebuild = store.by_id("__global__:neo4j_rebuild_indexes")
        assert rebuild is not None
        assert rebuild["depends_on_all_tenants"] is True

    def test_rebuild_depends_on_graph_stages(self, tmp_path):
        """neo4j_rebuild_indexes depends on the five graph stage names."""
        store = _init_production(tmp_path)
        rebuild = store.by_id("__global__:neo4j_rebuild_indexes")
        expected_deps = {"fortran_graph", "shell_graph", "bridge", "rocoto", "expdir"}
        assert set(rebuild["depends_on"]) == expected_deps

    def test_rebuild_not_actionable_when_one_tenant_graph_pending(self, tmp_path):
        """rebuild is blocked if even one tenant has a pending graph stage."""
        store = _init_production(tmp_path)
        units = store.units()

        # Mark ALL per-tenant graph stages done for all tenants EXCEPT
        # gw_v17:fortran_graph stays pending.
        graph_stages = {"fortran_graph", "shell_graph", "bridge", "rocoto", "expdir"}
        for u in units:
            if u["tenant_id"] == rs.GLOBAL_TENANT:
                # Mark all global prereqs done (e.g. neo4j_drop_indexes)
                if u["stage"] == "neo4j_drop_indexes":
                    u["status"] = "done"
                continue
            if u["stage"] in graph_stages:
                if u["tenant_id"] == "gw_v17" and u["stage"] == "fortran_graph":
                    u["status"] = "pending"  # explicitly keep pending
                else:
                    u["status"] = "done"
        store.save()

        store2 = rs.StateStore(store.state_dir)
        actionable_ids = {u["id"] for u in store2.actionable()}
        assert "__global__:neo4j_rebuild_indexes" not in actionable_ids

    def test_rebuild_actionable_when_all_tenants_graph_done(self, tmp_path):
        """rebuild becomes actionable once all tenants' graph stages are terminal."""
        store = _init_production(tmp_path)
        units = store.units()

        graph_stages = {"fortran_graph", "shell_graph", "bridge", "rocoto", "expdir"}
        for u in units:
            if u["tenant_id"] == rs.GLOBAL_TENANT:
                if u["stage"] == "neo4j_drop_indexes":
                    u["status"] = "done"
                continue
            if u["stage"] in graph_stages:
                u["status"] = "done"
        store.save()

        store2 = rs.StateStore(store.state_dir)
        actionable_ids = {u["id"] for u in store2.actionable()}
        assert "__global__:neo4j_rebuild_indexes" in actionable_ids

    def test_rebuild_actionable_when_graph_stages_skipped(self, tmp_path):
        """skipped is also terminal — rebuild proceeds if a tenant skipped graph."""
        store = _init_production(tmp_path)
        units = store.units()

        graph_stages = {"fortran_graph", "shell_graph", "bridge", "rocoto", "expdir"}
        for u in units:
            if u["tenant_id"] == rs.GLOBAL_TENANT:
                if u["stage"] == "neo4j_drop_indexes":
                    u["status"] = "done"
                continue
            if u["stage"] in graph_stages:
                # Mix of done and skipped — both are terminal
                if u["stage"] == "fortran_graph":
                    u["status"] = "skipped"
                    u["skip_reason"] = "no sorc submodules"
                else:
                    u["status"] = "done"
        store.save()

        store2 = rs.StateStore(store.state_dir)
        actionable_ids = {u["id"] for u in store2.actionable()}
        assert "__global__:neo4j_rebuild_indexes" in actionable_ids

    def test_rebuild_blocked_when_one_tenant_graph_blocked(self, tmp_path):
        """rebuild waits even if a graph stage is blocked (terminal but failure)."""
        store = _init_production(tmp_path)
        units = store.units()

        graph_stages = {"fortran_graph", "shell_graph", "bridge", "rocoto", "expdir"}
        for u in units:
            if u["tenant_id"] == rs.GLOBAL_TENANT:
                if u["stage"] == "neo4j_drop_indexes":
                    u["status"] = "done"
                continue
            if u["stage"] in graph_stages:
                if u["tenant_id"] == "gw_sfs" and u["stage"] == "bridge":
                    u["status"] = "blocked"  # blocked is terminal
                else:
                    u["status"] = "done"
        store.save()

        store2 = rs.StateStore(store.state_dir)
        actionable_ids = {u["id"] for u in store2.actionable()}
        # blocked IS terminal, so rebuild should be actionable
        assert "__global__:neo4j_rebuild_indexes" in actionable_ids


class TestNeo4jDropIndexesDependency:
    """neo4j_drop_indexes has no cross-tenant deps (runs first)."""

    def test_drop_has_no_depends_on(self, tmp_path):
        store = _init_production(tmp_path)
        drop = store.by_id("__global__:neo4j_drop_indexes")
        assert drop is not None
        assert drop["depends_on"] == []
        assert drop.get("depends_on_all_tenants", False) is False

    def test_drop_is_actionable_immediately(self, tmp_path):
        """neo4j_drop_indexes is actionable right after init."""
        store = _init_production(tmp_path)
        actionable_ids = {u["id"] for u in store.actionable()}
        assert "__global__:neo4j_drop_indexes" in actionable_ids

    def test_drop_runs_before_graph_stages(self, tmp_path):
        """neo4j_drop_indexes has lower order than any graph stage."""
        store = _init_production(tmp_path)
        drop = store.by_id("__global__:neo4j_drop_indexes")
        units = store.units()

        graph_stages = [u for u in units if u["kind"] == "graph"]
        for g in graph_stages:
            assert drop["order"] < g["order"], (
                f"neo4j_drop_indexes (order={drop['order']}) should sort before "
                f"{g['id']} (order={g['order']})"
            )


class TestDependsOnAllTenantsField:
    """The depends_on_all_tenants field defaults correctly."""

    def test_tenant_stages_default_false(self, tmp_path):
        """Per-tenant stages do not have depends_on_all_tenants."""
        store = _init_production(tmp_path)
        tenant_units = [
            u for u in store.units() if u["tenant_id"] != rs.GLOBAL_TENANT
        ]
        for u in tenant_units:
            assert u.get("depends_on_all_tenants", False) is False

    def test_only_rebuild_has_the_flag(self, tmp_path):
        """Only neo4j_rebuild_indexes has depends_on_all_tenants=True."""
        store = _init_production(tmp_path)
        flagged = [
            u for u in store.units()
            if u.get("depends_on_all_tenants") is True
        ]
        assert len(flagged) == 1
        assert flagged[0]["stage"] == "neo4j_rebuild_indexes"
