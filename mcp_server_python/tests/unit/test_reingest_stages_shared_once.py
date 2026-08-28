"""Unit tests for reingest_stages.yaml shared-once semantics.

Feature: mpnet768-tenant-reingest-aug2026, Task 2.6.

Asserts: Every stage with ``shared_once: true`` produces exactly one Work_Matrix
unit regardless of tenant count. No per-tenant unit leaks for shared-once stages.
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


class TestSharedOnceStagesEmitOnce:
    """Every shared_once=true stage produces exactly ONE unit (global)."""

    def test_each_shared_once_stage_appears_once(self, tmp_path):
        store = _init_production(tmp_path)
        units = store.units()

        shared_once_units = [u for u in units if u.get("shared_once") is True]
        # Each shared_once stage must appear exactly once
        stage_names = [u["stage"] for u in shared_once_units]
        assert len(stage_names) == len(set(stage_names)), (
            f"Duplicate shared_once stage(s): {stage_names}"
        )

    def test_shared_once_units_are_global(self, tmp_path):
        store = _init_production(tmp_path)
        units = store.units()

        shared_once_units = [u for u in units if u.get("shared_once") is True]
        for u in shared_once_units:
            assert u["tenant_id"] == rs.GLOBAL_TENANT, (
                f"shared_once unit {u['id']} should be __global__, "
                f"got tenant_id={u['tenant_id']}"
            )

    def test_no_per_tenant_copies_of_shared_once_stages(self, tmp_path):
        store = _init_production(tmp_path)
        units = store.units()

        shared_once_stage_names = {
            u["stage"] for u in units if u.get("shared_once") is True
        }
        tenant_units = [u for u in units if u["tenant_id"] != rs.GLOBAL_TENANT]
        leaked = [
            u for u in tenant_units if u["stage"] in shared_once_stage_names
        ]
        assert leaked == [], (
            f"Shared-once stages leaked as per-tenant units: "
            f"{[u['id'] for u in leaked]}"
        )

    def test_shared_once_stages_enumerated(self, tmp_path):
        """Verify the expected set of shared-once stages from the catalog."""
        store = _init_production(tmp_path)
        units = store.units()

        shared_once_stages = sorted(
            u["stage"] for u in units if u.get("shared_once") is True
        )
        expected = sorted([
            "neo4j_drop_indexes",
            "workflow_docs_external",
            "pdf_sources",
            "ee2_standards",
            "community_summaries",
            "ci_test_cases",
            "neo4j_rebuild_indexes",
        ])
        assert shared_once_stages == expected

    def test_shared_once_scope_is_shared(self, tmp_path):
        """All shared_once units have scope == 'shared'."""
        store = _init_production(tmp_path)
        units = store.units()

        shared_once_units = [u for u in units if u.get("shared_once") is True]
        for u in shared_once_units:
            assert u["scope"] == "shared", (
                f"shared_once unit {u['id']} has scope={u['scope']}, expected 'shared'"
            )

    def test_shared_once_count_invariant_with_more_tenants(self, tmp_path):
        """Adding a tenant does not duplicate shared-once units."""
        # Extended catalog with 6 tenants
        extended = Path(rs._DEFAULT_CATALOG).read_text(encoding="utf-8")
        extended += """\

  - tenant_id: gw_test
    repo_ref: NOAA-EMC/global-workflow
    branch: feature/test
    index_prefix: "gw_test_"
    label_prefix: "GW_TEST_"
    workflow_subdir: feature-test
    lifecycle: experimental
    description: "Test tenant"
    extends: []
"""
        cat_path = tmp_path / "extended_catalog.yaml"
        cat_path.write_text(extended, encoding="utf-8")

        argv = [
            "--state-root", str(tmp_path),
            "--collection-version", "v9-0-0",
            "init",
            "--catalog", str(cat_path),
            "--stages", str(rs._DEFAULT_STAGES),
            "--backend", "cots",
            "--embedding-profile", "mpnet768",
        ]
        rc = rs.main(argv)
        assert rc == 0

        store = rs.StateStore(rs._state_dir(tmp_path, "v9-0-0"))
        units = store.units()

        shared_once_units = [u for u in units if u.get("shared_once") is True]
        # Still exactly 7 shared-once units, not 7+1
        assert len(shared_once_units) == 7

        # But tenant units increased by 12 (one per per-tenant stage)
        tenant_units = [u for u in units if u["tenant_id"] != rs.GLOBAL_TENANT]
        assert len(tenant_units) == 72  # 6 tenants × 12 per-tenant stages
