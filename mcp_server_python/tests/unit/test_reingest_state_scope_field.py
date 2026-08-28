"""Unit tests for reingest_state.py Phase 81 scope extensions.

Feature: mpnet768-tenant-reingest-aug2026, Task 1.3.

Covers:
  * New fields (shared_once, tenancy_precheck, validation_path) default correctly.
  * Fields are preserved on idempotent re-init.
  * catalog_scope_drift fires when a stage's shared_once flips.
  * --force-scope-migration clears the drift warning.
  * v1 → v2 migration adds missing fields without clobbering statuses.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

import reingest_state as rs  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures — minimal catalog + stage catalog
# ---------------------------------------------------------------------------

_CATALOG_YAML = """\
schema_version: 1
defaults:
  tenant_id: gw
tenants:
  - tenant_id: gw
    repo_ref: NOAA-EMC/global-workflow
    branch: develop
    index_prefix: ""
    label_prefix: ""
    workflow_subdir: develop
    lifecycle: production
  - tenant_id: gw_v17
    repo_ref: NOAA-EMC/global-workflow
    branch: dev/gfs.v17
    index_prefix: "gw_v17_"
    label_prefix: "GW_V17_"
    workflow_subdir: dev-v17
    lifecycle: staging
"""

_STAGES_YAML = """\
schema_version: 1
attempt_cap_default: 3
per_tenant_stages:
  - name: worktree
    scope: tenant
    order: 10
    kind: prep
    script: setup_pw_workflow_mount.sh
    depends_on: []
  - name: code
    scope: tenant
    order: 40
    kind: vector
    script: ingest_code_v8.py
    depends_on: [worktree]
    probe: vector
  - name: validate
    scope: tenant
    order: 200
    kind: validate
    script: null
    depends_on: [code]
    probe: integrity
global_stages:
  - name: ee2_standards
    scope: shared
    shared_once: true
    order: 300
    kind: vector
    script: ingest_ee2_v7.py
    depends_on: []
"""


@pytest.fixture()
def catalog_file(tmp_path: Path) -> Path:
    p = tmp_path / "tenants.yaml"
    p.write_text(_CATALOG_YAML, encoding="utf-8")
    return p


@pytest.fixture()
def stages_file(tmp_path: Path) -> Path:
    p = tmp_path / "reingest_stages.yaml"
    p.write_text(_STAGES_YAML, encoding="utf-8")
    return p


def _init(state_root: Path, catalog: Path, stages: Path, *, version="v9-0-0",
          force_scope_migration=False) -> int:
    argv = [
        "--state-root", str(state_root),
        "--collection-version", version,
        "init",
        "--catalog", str(catalog),
        "--stages", str(stages),
        "--backend", "cots",
        "--embedding-profile", "mpnet768",
    ]
    if force_scope_migration:
        argv.append("--force-scope-migration")
    return rs.main(argv)


def _store(state_root: Path, version="v9-0-0") -> rs.StateStore:
    return rs.StateStore(rs._state_dir(state_root, version))


# ---------------------------------------------------------------------------
# Task 1.1 — new fields default correctly on fresh init
# ---------------------------------------------------------------------------


class TestScopeFieldsOnFreshInit:
    """Fields (shared_once, tenancy_precheck, validation_path) are set on init."""

    def test_shared_once_true_on_ee2(self, tmp_path, catalog_file, stages_file):
        _init(tmp_path, catalog_file, stages_file)
        store = _store(tmp_path)
        ee2 = store.by_id("__global__:ee2_standards")
        assert ee2["shared_once"] is True

    def test_shared_once_false_on_tenant_stage(self, tmp_path, catalog_file, stages_file):
        _init(tmp_path, catalog_file, stages_file)
        store = _store(tmp_path)
        code = store.by_id("gw:code")
        assert code["shared_once"] is False

    def test_tenancy_precheck_null_tenant_for_shared(self, tmp_path, catalog_file,
                                                      stages_file):
        _init(tmp_path, catalog_file, stages_file)
        store = _store(tmp_path)
        ee2 = store.by_id("__global__:ee2_standards")
        assert ee2["tenancy_precheck"]["expected_prefix"] == ""
        assert ee2["tenancy_precheck"]["expected_tenant"] is None

    def test_tenancy_precheck_set_for_tenant_stage(self, tmp_path, catalog_file,
                                                    stages_file):
        _init(tmp_path, catalog_file, stages_file)
        store = _store(tmp_path)
        v17_code = store.by_id("gw_v17:code")
        assert v17_code["tenancy_precheck"]["expected_prefix"] == "gw_v17_"
        assert v17_code["tenancy_precheck"]["expected_tenant"] == "gw_v17"

    def test_tenancy_precheck_empty_prefix_for_gw(self, tmp_path, catalog_file,
                                                   stages_file):
        _init(tmp_path, catalog_file, stages_file)
        store = _store(tmp_path)
        gw_code = store.by_id("gw:code")
        assert gw_code["tenancy_precheck"]["expected_prefix"] == ""
        assert gw_code["tenancy_precheck"]["expected_tenant"] == "gw"

    def test_validation_path_set_for_validate_kind(self, tmp_path, catalog_file,
                                                    stages_file):
        _init(tmp_path, catalog_file, stages_file)
        store = _store(tmp_path)
        val_gw = store.by_id("gw:validate")
        assert val_gw["validation_path"] == "validation/gw.json"
        val_v17 = store.by_id("gw_v17:validate")
        assert val_v17["validation_path"] == "validation/gw_v17.json"

    def test_validation_path_none_for_non_validate(self, tmp_path, catalog_file,
                                                    stages_file):
        _init(tmp_path, catalog_file, stages_file)
        store = _store(tmp_path)
        code = store.by_id("gw:code")
        assert code["validation_path"] is None

    def test_schema_version_is_2(self, tmp_path, catalog_file, stages_file):
        _init(tmp_path, catalog_file, stages_file)
        store = _store(tmp_path)
        data = store.load()
        assert data["schema_version"] == 2

    def test_warnings_list_exists(self, tmp_path, catalog_file, stages_file):
        _init(tmp_path, catalog_file, stages_file)
        store = _store(tmp_path)
        data = store.load()
        assert isinstance(data.get("warnings"), list)


# ---------------------------------------------------------------------------
# Task 1.1 — fields preserved on re-init
# ---------------------------------------------------------------------------


class TestScopeFieldsPreservedOnReinit:
    """Idempotent re-init preserves existing unit statuses including new fields."""

    def test_reinit_preserves_scope_fields(self, tmp_path, catalog_file, stages_file):
        _init(tmp_path, catalog_file, stages_file)
        store = _store(tmp_path)
        # Manually alter a unit to confirm preservation
        code = store.by_id("gw:code")
        code["status"] = "done"
        code["metrics"] = {"docs": 1234}
        store.save()

        # Re-init (same catalog + stages)
        rc = _init(tmp_path, catalog_file, stages_file)
        assert rc == 0

        store2 = _store(tmp_path)
        code2 = store2.by_id("gw:code")
        assert code2["status"] == "done"
        assert code2["metrics"]["docs"] == 1234
        # New fields still present
        assert "shared_once" in code2
        assert "tenancy_precheck" in code2


# ---------------------------------------------------------------------------
# Task 1.1 — v1 → v2 migration
# ---------------------------------------------------------------------------


class TestMigrateV1ToV2:
    """_migrate_state_v1_to_v2 adds missing fields without clobbering."""

    def test_adds_missing_fields(self):
        data = {
            "schema_version": 1,
            "units": [
                {"id": "gw:code", "status": "done", "stage": "code"},
                {"id": "__global__:ee2_standards", "status": "pending",
                 "stage": "ee2_standards"},
            ],
        }
        result = rs._migrate_state_v1_to_v2(data)
        assert result["schema_version"] == 2
        assert "warnings" in result
        for u in result["units"]:
            assert "shared_once" in u
            assert u["shared_once"] is False
            assert "tenancy_precheck" in u
            assert u["tenancy_precheck"] is None
            assert "validation_path" in u
            assert u["validation_path"] is None

    def test_preserves_existing_status(self):
        data = {
            "schema_version": 1,
            "units": [
                {"id": "gw:code", "status": "done", "stage": "code",
                 "metrics": {"docs": 5000}},
            ],
        }
        result = rs._migrate_state_v1_to_v2(data)
        assert result["units"][0]["status"] == "done"
        assert result["units"][0]["metrics"]["docs"] == 5000

    def test_does_not_overwrite_existing_v2_fields(self):
        data = {
            "schema_version": 1,
            "units": [
                {"id": "gw:code", "status": "pending", "stage": "code",
                 "shared_once": True, "tenancy_precheck": {"expected_prefix": "x"},
                 "validation_path": "some/path.json"},
            ],
        }
        result = rs._migrate_state_v1_to_v2(data)
        # Existing fields not overwritten
        assert result["units"][0]["shared_once"] is True
        assert result["units"][0]["tenancy_precheck"]["expected_prefix"] == "x"
        assert result["units"][0]["validation_path"] == "some/path.json"

    def test_migration_runs_on_reinit_of_v1_file(self, tmp_path, catalog_file,
                                                   stages_file):
        """A pre-existing v1 state file gets migrated when cmd_init re-runs."""
        # Create a v1 state file manually
        _init(tmp_path, catalog_file, stages_file)
        store = _store(tmp_path)
        data = store.load()
        # Downgrade to v1 by removing the new fields
        data["schema_version"] = 1
        for u in data["units"]:
            u.pop("shared_once", None)
            u.pop("tenancy_precheck", None)
            u.pop("validation_path", None)
        data.pop("warnings", None)
        store._data = data
        store.save()

        # Re-init should migrate
        rc = _init(tmp_path, catalog_file, stages_file)
        assert rc == 0
        store2 = _store(tmp_path)
        data2 = store2.load()
        assert data2["schema_version"] == 2
        for u in data2["units"]:
            assert "shared_once" in u
            assert "tenancy_precheck" in u
            assert "validation_path" in u


# ---------------------------------------------------------------------------
# Task 1.2 — catalog_scope_drift detection
# ---------------------------------------------------------------------------


class TestCatalogScopeDrift:
    """catalog_scope_drift fires on shared_once flip; --force clears it."""

    def test_drift_detected_on_shared_once_flip(self, tmp_path, catalog_file):
        """Init with shared_once=true, then re-init with shared_once=false."""
        stages_v1 = tmp_path / "stages_v1.yaml"
        stages_v1.write_text(_STAGES_YAML, encoding="utf-8")
        rc = _init(tmp_path, catalog_file, stages_v1)
        assert rc == 0

        # Create a v2 stages file where ee2_standards flips shared_once
        stages_v2 = tmp_path / "stages_v2.yaml"
        flipped = _STAGES_YAML.replace("shared_once: true", "shared_once: false")
        stages_v2.write_text(flipped, encoding="utf-8")

        # Re-init with the flipped catalog -> should fail
        rc = _init(tmp_path, catalog_file, stages_v2)
        assert rc == 1

        # Verify warning recorded
        store = _store(tmp_path)
        data = store.load()
        drift_warns = [w for w in data.get("warnings", [])
                       if w.get("type") == "catalog_scope_drift"]
        assert len(drift_warns) == 1
        assert drift_warns[0]["stage"] == "ee2_standards"
        assert drift_warns[0]["old_shared_once"] is True
        assert drift_warns[0]["new_shared_once"] is False

    def test_force_scope_migration_clears_drift(self, tmp_path, catalog_file):
        """--force-scope-migration accepts the drift and clears warnings."""
        stages_v1 = tmp_path / "stages_v1.yaml"
        stages_v1.write_text(_STAGES_YAML, encoding="utf-8")
        _init(tmp_path, catalog_file, stages_v1)

        stages_v2 = tmp_path / "stages_v2.yaml"
        flipped = _STAGES_YAML.replace("shared_once: true", "shared_once: false")
        stages_v2.write_text(flipped, encoding="utf-8")

        # First re-init fails
        rc = _init(tmp_path, catalog_file, stages_v2)
        assert rc == 1

        # Force-scope-migration succeeds
        rc = _init(tmp_path, catalog_file, stages_v2, force_scope_migration=True)
        assert rc == 0

        store = _store(tmp_path)
        data = store.load()
        drift_warns = [w for w in data.get("warnings", [])
                       if w.get("type") == "catalog_scope_drift"]
        assert len(drift_warns) == 0

    def test_no_drift_when_shared_once_unchanged(self, tmp_path, catalog_file,
                                                  stages_file):
        """No drift warning when re-init with identical stages."""
        _init(tmp_path, catalog_file, stages_file)
        rc = _init(tmp_path, catalog_file, stages_file)
        assert rc == 0
        store = _store(tmp_path)
        data = store.load()
        drift_warns = [w for w in data.get("warnings", [])
                       if w.get("type") == "catalog_scope_drift"]
        assert len(drift_warns) == 0


# ---------------------------------------------------------------------------
# Scope field in _build_matrix — shared/hybrid emit correct unit count
# ---------------------------------------------------------------------------


class TestBuildMatrixScopeSemantics:
    """_build_matrix emits correct number of units per scope."""

    def test_shared_once_stage_emits_one_unit(self, tmp_path, catalog_file,
                                              stages_file):
        _init(tmp_path, catalog_file, stages_file)
        store = _store(tmp_path)
        ee2_units = [u for u in store.units() if u["stage"] == "ee2_standards"]
        assert len(ee2_units) == 1
        assert ee2_units[0]["tenant_id"] == rs.GLOBAL_TENANT

    def test_tenant_stage_emits_per_tenant(self, tmp_path, catalog_file, stages_file):
        _init(tmp_path, catalog_file, stages_file)
        store = _store(tmp_path)
        code_units = [u for u in store.units() if u["stage"] == "code"]
        assert len(code_units) == 2  # gw + gw_v17

    def test_hybrid_external_emits_one_unit(self, tmp_path, catalog_file):
        """A stage with scope=hybrid_external emits exactly one unit."""
        stages = tmp_path / "stages.yaml"
        stages.write_text("""\
schema_version: 1
attempt_cap_default: 3
per_tenant_stages:
  - name: worktree
    scope: tenant
    order: 10
    kind: prep
    script: setup_pw_workflow_mount.sh
    depends_on: []
  - name: docs_external
    scope: hybrid_external
    shared_once: true
    order: 30
    kind: vector
    script: ingest_documentation_v9.py
    depends_on: []
  - name: docs_local
    scope: hybrid_local
    order: 35
    kind: vector
    script: ingest_documentation_v9.py
    depends_on: [worktree]
global_stages: []
""", encoding="utf-8")
        _init(tmp_path, catalog_file, stages)
        store = _store(tmp_path)
        ext_units = [u for u in store.units() if u["stage"] == "docs_external"]
        assert len(ext_units) == 1
        assert ext_units[0]["scope"] == "hybrid_external"
        assert ext_units[0]["shared_once"] is True

    def test_hybrid_local_emits_per_tenant(self, tmp_path, catalog_file):
        """A stage with scope=hybrid_local emits per-tenant."""
        stages = tmp_path / "stages.yaml"
        stages.write_text("""\
schema_version: 1
attempt_cap_default: 3
per_tenant_stages:
  - name: worktree
    scope: tenant
    order: 10
    kind: prep
    script: setup_pw_workflow_mount.sh
    depends_on: []
  - name: docs_local
    scope: hybrid_local
    order: 35
    kind: vector
    script: ingest_documentation_v9.py
    depends_on: [worktree]
global_stages: []
""", encoding="utf-8")
        _init(tmp_path, catalog_file, stages)
        store = _store(tmp_path)
        local_units = [u for u in store.units() if u["stage"] == "docs_local"]
        assert len(local_units) == 2  # gw + gw_v17
        for u in local_units:
            assert u["scope"] == "hybrid_local"
            assert u["shared_once"] is False
