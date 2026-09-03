"""Unit tests for neo4j_index_rebuild.py.

Feature: mpnet768-tenant-reingest-aug2026, Task 3.2.

Covers:
  * `list` returns the Index_Rebuild_Set (mocked Neo4j driver).
  * `drop` refuses without the confirmation token.
  * `drop` writes a snapshot that `restore` accepts round-trip.
  * `create` parametrises labels by every tenant's label_prefix.
  * Expanded index set has correct count based on templates x prefixes.
  * Dry-run mode does not touch the driver.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

import neo4j_index_rebuild as nir  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
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
  - tenant_id: gw_sfs
    repo_ref: NOAA-EMC/global-workflow
    branch: dev/sfs
    index_prefix: "gw_sfs_"
    label_prefix: "GW_SFS_"
    workflow_subdir: dev-sfs
    lifecycle: experimental
"""


@pytest.fixture
def catalog_file(tmp_path):
    """Write a minimal tenants.yaml to tmp_path."""
    p = tmp_path / "tenants.yaml"
    p.write_text(_CATALOG_YAML)
    return str(p)


@pytest.fixture
def snapshot_path(tmp_path):
    """Return a path for writing snapshot files."""
    return str(tmp_path / "neo4j_pre_drop.json")


@pytest.fixture
def mock_driver():
    """Create a mock Neo4j driver."""
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    # Default: no live indexes/constraints
    session.run.return_value = []
    return driver


# ---------------------------------------------------------------------------
# Tests: _load_tenant_prefixes
# ---------------------------------------------------------------------------


class TestLoadTenantPrefixes:
    def test_loads_all_prefixes(self, catalog_file):
        prefixes = nir._load_tenant_prefixes(Path(catalog_file))
        assert "" in prefixes
        assert "GW_V17_" in prefixes
        assert "GW_SFS_" in prefixes

    def test_unprefixed_always_present(self, catalog_file):
        prefixes = nir._load_tenant_prefixes(Path(catalog_file))
        assert prefixes.count("") == 1


# ---------------------------------------------------------------------------
# Tests: _expand_index_set
# ---------------------------------------------------------------------------


class TestExpandIndexSet:
    def test_correct_count(self, catalog_file):
        """7 templates x 3 prefixes = 21 concrete entries."""
        prefixes = nir._load_tenant_prefixes(Path(catalog_file))
        expanded = nir._expand_index_set(prefixes)
        # All entries are for_tenant=True, so 7 * 3 = 21
        assert len(expanded) == 7 * len(prefixes)

    def test_labels_are_prefixed(self, catalog_file):
        prefixes = nir._load_tenant_prefixes(Path(catalog_file))
        expanded = nir._expand_index_set(prefixes)
        # Find entries for the GW_V17_ prefix
        v17_entries = [e for e in expanded if e["prefix"] == "GW_V17_"]
        assert len(v17_entries) == 7
        for entry in v17_entries:
            assert entry["label"].startswith("GW_V17_")

    def test_base_entries_are_unprefixed(self, catalog_file):
        prefixes = nir._load_tenant_prefixes(Path(catalog_file))
        expanded = nir._expand_index_set(prefixes)
        base_entries = [e for e in expanded if e["prefix"] == ""]
        assert len(base_entries) == 7
        # None should start with a prefix
        for entry in base_entries:
            assert not entry["label"].startswith("GW_")

    def test_names_are_unique(self, catalog_file):
        prefixes = nir._load_tenant_prefixes(Path(catalog_file))
        expanded = nir._expand_index_set(prefixes)
        names = [e["name"] for e in expanded]
        assert len(names) == len(set(names)), "Index names must be unique"


# ---------------------------------------------------------------------------
# Tests: _cypher_create / _cypher_drop
# ---------------------------------------------------------------------------


class TestCypherGeneration:
    def test_uniqueness_constraint_create(self):
        entry = {
            "name": "file_path_uniq_base",
            "type": "uniqueness",
            "label": "File",
            "property": "path",
        }
        cypher = nir._cypher_create(entry)
        assert "CREATE CONSTRAINT" in cypher
        assert "file_path_uniq_base" in cypher
        assert "IF NOT EXISTS" in cypher
        assert ":`File`" in cypher
        assert "IS UNIQUE" in cypher

    def test_text_index_create(self):
        entry = {
            "name": "function_name_text_base",
            "type": "text",
            "label": "Function",
            "property": "name",
        }
        cypher = nir._cypher_create(entry)
        assert "CREATE TEXT INDEX" in cypher
        assert "function_name_text_base" in cypher
        assert "IF NOT EXISTS" in cypher
        assert ":`Function`" in cypher

    def test_uniqueness_constraint_drop(self):
        entry = {
            "name": "file_path_uniq_base",
            "type": "uniqueness",
            "label": "File",
            "property": "path",
        }
        cypher = nir._cypher_drop(entry)
        assert "DROP CONSTRAINT" in cypher
        assert "file_path_uniq_base" in cypher
        assert "IF EXISTS" in cypher

    def test_text_index_drop(self):
        entry = {
            "name": "function_name_text_base",
            "type": "text",
            "label": "Function",
            "property": "name",
        }
        cypher = nir._cypher_drop(entry)
        assert "DROP INDEX" in cypher
        assert "function_name_text_base" in cypher
        assert "IF EXISTS" in cypher

    def test_prefixed_label_in_create(self):
        entry = {
            "name": "file_path_uniq_gw_v17",
            "type": "uniqueness",
            "label": "GW_V17_File",
            "property": "path",
        }
        cypher = nir._cypher_create(entry)
        assert ":`GW_V17_File`" in cypher

    def test_unknown_type_raises(self):
        entry = {"name": "x", "type": "bogus", "label": "X", "property": "y"}
        with pytest.raises(ValueError, match="Unknown index type"):
            nir._cypher_create(entry)


# ---------------------------------------------------------------------------
# Tests: cmd_drop — confirmation token requirement
# ---------------------------------------------------------------------------


class TestCmdDrop:
    def test_refuses_without_confirmation_token(self, catalog_file, snapshot_path):
        """drop requires --i-mean-it; argparse enforces this."""
        # Simulate calling with missing --i-mean-it (argparse will error)
        with pytest.raises(SystemExit):
            nir.main(["drop", "--snapshot", snapshot_path,
                      "--catalog", catalog_file])

    def test_refuses_bad_confirmation_token(self, catalog_file, snapshot_path):
        """Token must start with Target_Version="""
        rc = nir.main(["drop",
                       "--i-mean-it", "WrongFormat",
                       "--snapshot", snapshot_path,
                       "--catalog", catalog_file,
                       "--dry-run"])
        assert rc == 1

    def test_accepts_valid_token_dry_run(self, catalog_file, snapshot_path):
        """Valid token in dry-run mode succeeds without touching Neo4j."""
        rc = nir.main(["drop",
                       "--i-mean-it", "Target_Version=v9-0-0",
                       "--snapshot", snapshot_path,
                       "--catalog", catalog_file,
                       "--dry-run"])
        assert rc == 0

    @patch("neo4j_index_rebuild._get_driver")
    def test_writes_snapshot_before_dropping(
        self, mock_get_driver, catalog_file, tmp_path
    ):
        """drop writes a snapshot file before executing any drops."""
        snap = str(tmp_path / "snap.json")

        # Mock driver with mock session
        driver = MagicMock()
        mock_session = MagicMock()
        driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        driver.session.return_value.__exit__ = MagicMock(return_value=False)
        # SHOW INDEXES / SHOW CONSTRAINTS return empty
        mock_session.run.return_value = iter([])
        mock_get_driver.return_value = driver

        rc = nir.main(["drop",
                       "--i-mean-it", "Target_Version=v9-0-0",
                       "--snapshot", snap,
                       "--catalog", catalog_file])
        assert rc == 0
        # Snapshot file must exist
        assert Path(snap).exists()
        snapshot = json.loads(Path(snap).read_text())
        assert snapshot["target_version"] == "v9-0-0"
        assert "dropped_entries" in snapshot
        assert len(snapshot["dropped_entries"]) > 0


# ---------------------------------------------------------------------------
# Tests: cmd_create — label parametrisation
# ---------------------------------------------------------------------------


class TestCmdCreate:
    def test_dry_run_shows_all_tenant_labels(self, catalog_file, capsys):
        """create --dry-run parametrises by every tenant prefix."""
        rc = nir.main(["create",
                       "--target-version", "v9-0-0",
                       "--catalog", catalog_file,
                       "--dry-run"])
        assert rc == 0
        output = capsys.readouterr().out
        # Check that all tenant labels appear
        assert ":`File`" in output  # base
        assert ":`GW_V17_File`" in output
        assert ":`GW_SFS_File`" in output
        assert ":`GW_V17_FortranSubroutine`" in output
        assert ":`GW_SFS_PythonFunction`" in output


# ---------------------------------------------------------------------------
# Tests: cmd_restore — round-trip with snapshot
# ---------------------------------------------------------------------------


class TestCmdRestore:
    def test_restore_from_snapshot_dry_run(self, tmp_path, catalog_file):
        """restore reads a snapshot and shows the re-creation plan."""
        # First, create a snapshot file
        snap = tmp_path / "snap.json"
        prefixes = nir._load_tenant_prefixes(Path(catalog_file))
        expanded = nir._expand_index_set(prefixes)
        snapshot = {
            "schema_version": 1,
            "target_version": "v9-0-0",
            "captured_at": "2026-08-28T00:00:00Z",
            "indexes": [],
            "constraints": [],
            "dropped_entries": expanded,
        }
        snap.write_text(json.dumps(snapshot, indent=2))

        rc = nir.main(["restore",
                       "--snapshot", str(snap),
                       "--catalog", catalog_file,
                       "--dry-run"])
        assert rc == 0

    def test_restore_missing_snapshot_errors(self, tmp_path, catalog_file):
        """restore errors if the snapshot file does not exist."""
        rc = nir.main(["restore",
                       "--snapshot", str(tmp_path / "nonexistent.json"),
                       "--catalog", catalog_file])
        assert rc == 1

    def test_restore_empty_entries_is_noop(self, tmp_path, catalog_file):
        """restore with no dropped_entries does nothing."""
        snap = tmp_path / "snap.json"
        snapshot = {
            "schema_version": 1,
            "target_version": "v9-0-0",
            "captured_at": "2026-08-28T00:00:00Z",
            "indexes": [],
            "constraints": [],
            "dropped_entries": [],
        }
        snap.write_text(json.dumps(snapshot, indent=2))

        rc = nir.main(["restore",
                       "--snapshot", str(snap),
                       "--catalog", catalog_file,
                       "--dry-run"])
        assert rc == 0


# ---------------------------------------------------------------------------
# Tests: cmd_list — dry-run (no Neo4j connection)
# ---------------------------------------------------------------------------


class TestCmdList:
    def test_list_dry_run(self, catalog_file, capsys):
        """list in dry-run mode shows entries without connecting."""
        rc = nir.main(["list", "--catalog", catalog_file, "--dry-run"])
        assert rc == 0
        output = capsys.readouterr().out
        # Should show all template entries
        assert "file_path_uniq" in output
        assert "function_name_text" in output
        assert "fortran_sub_name_text" in output


# ---------------------------------------------------------------------------
# Tests: drop + restore round-trip
# ---------------------------------------------------------------------------


class TestDropRestoreRoundTrip:
    def test_snapshot_is_restorable(self, catalog_file, tmp_path):
        """A snapshot produced by drop is directly consumable by restore."""
        # Simulate a drop (dry-run creates no snapshot, so we manually create one)
        snap = tmp_path / "snap.json"
        prefixes = nir._load_tenant_prefixes(Path(catalog_file))
        expanded = nir._expand_index_set(prefixes)

        nir._write_snapshot(
            snap,
            indexes=[{"name": "idx1", "state": "ONLINE"}],
            constraints=[{"name": "cst1", "state": "ONLINE"}],
            target_version="v9-0-0",
            dropped_entries=expanded,
        )

        # Verify the snapshot is valid JSON and has the right structure
        loaded = nir._load_snapshot(snap)
        assert loaded["target_version"] == "v9-0-0"
        assert loaded["schema_version"] == 1
        assert len(loaded["dropped_entries"]) == len(expanded)

        # Restore in dry-run should accept it
        rc = nir.main(["restore",
                       "--snapshot", str(snap),
                       "--catalog", catalog_file,
                       "--dry-run"])
        assert rc == 0


# ---------------------------------------------------------------------------
# Tests: INDEX_REBUILD_SET structure
# ---------------------------------------------------------------------------


class TestIndexRebuildSet:
    def test_all_entries_have_required_fields(self):
        """Every entry in the set must have name, type, label, property."""
        for entry in nir.INDEX_REBUILD_SET:
            assert "name" in entry
            assert "type" in entry
            assert "label" in entry
            assert "property" in entry
            assert "for_tenant" in entry

    def test_valid_types_only(self):
        """All entries have a valid type."""
        valid = {"uniqueness", "text", "range"}
        for entry in nir.INDEX_REBUILD_SET:
            assert entry["type"] in valid, f"{entry['name']} has invalid type"

    def test_no_duplicate_names(self):
        """Template names are unique within the set."""
        names = [e["name"] for e in nir.INDEX_REBUILD_SET]
        assert len(names) == len(set(names))

    def test_set_matches_design_doc(self):
        """The set contains the seven entries specified in design.md Delta 3."""
        expected_names = {
            "file_path_uniq",
            "function_qname_uniq",
            "function_name_text",
            "fortran_sub_name_text",
            "fortran_fn_name_text",
            "python_fn_name_text",
            "shell_script_path_uniq",
        }
        actual_names = {e["name"] for e in nir.INDEX_REBUILD_SET}
        assert actual_names == expected_names
