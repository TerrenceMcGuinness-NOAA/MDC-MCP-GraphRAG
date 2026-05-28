"""Unit tests for delete_tenant_indices.py.

Feature: omd-tenants-2-v17-pilot, Requirements 7.1, 7.2, 7.3
"""
from __future__ import annotations

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
        """--dry-run prints plan, exit 0, zero mutating calls."""
        path = _write_catalog(tmp_path, [_GW, _GW_V17])
        deleted = []

        class StubVectorDB:
            async def list_indices(self):
                return ["gw_v17_mdc-docs", "mdc-docs", "mdc-content-sha-registry"]
            async def delete_index(self, name):
                deleted.append(name)

        class StubGraphDB:
            async def execute_cypher(self, q, p):
                deleted.append(("cypher", p))

        code = await run_delete(
            tenant_id="gw_v17", catalog_path=path, dry_run=True,
            vector_db=StubVectorDB(), graph_db=StubGraphDB(),
        )
        assert code == 0
        assert deleted == []  # no mutations


class TestSuccessfulDeletion:
    @pytest.mark.asyncio
    async def test_deletes_only_prefixed_data(self, tmp_path):
        """Successful run deletes only prefixed indices + labels."""
        path = _write_catalog(tmp_path, [_GW, _GW_V17])
        deleted_indices = []
        cypher_calls = []

        class StubVectorDB:
            async def list_indices(self):
                return [
                    "mdc-workflow-docs-titan1024",
                    "gw_v17_mdc-workflow-docs-titan1024",
                    "gw_v17_mdc-code-titan1024",
                    "gw_sfs_mdc-workflow-docs-titan1024",
                    "mdc-content-sha-registry",
                ]
            async def delete_index(self, name):
                deleted_indices.append(name)

        class StubGraphDB:
            async def execute_cypher(self, q, p):
                cypher_calls.append(p)

        code = await run_delete(
            tenant_id="gw_v17", catalog_path=path, dry_run=False,
            vector_db=StubVectorDB(), graph_db=StubGraphDB(),
        )
        assert code == 0
        assert set(deleted_indices) == {
            "gw_v17_mdc-workflow-docs-titan1024",
            "gw_v17_mdc-code-titan1024",
        }
        # System index never touched
        assert "mdc-content-sha-registry" not in deleted_indices
        # Other tenant untouched
        assert "gw_sfs_mdc-workflow-docs-titan1024" not in deleted_indices
        # Neptune called with correct prefix
        assert cypher_calls[0]["prefix"] == "GW_V17_"
