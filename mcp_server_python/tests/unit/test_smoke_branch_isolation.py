"""Unit tests for _smoke_branch_isolation per-assertion FAIL messages.

Feature: omd-tenants-2-v17-pilot, Requirement 4.1
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from tools.smoke_queries import _smoke_branch_isolation, SkipProbe


@pytest.fixture
def both_tenants_catalog(tmp_path, monkeypatch):
    """Write a catalog with both gw and gw_v17, set env var."""
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


class TestAssertionFailMessages:
    """Each assertion failure produces the correct R4.1#N prefix."""

    @pytest.mark.asyncio
    async def test_r41_1_wdqms_not_found_under_v17(self, both_tenants_catalog):
        """Assertion 1: WDQMS not found under gw_v17 → R4.1#1."""
        data = MagicMock()
        data.graph_db.query = AsyncMock(return_value=[])  # v17 returns nothing
        data.vector_db.query = AsyncMock(return_value=[])

        with pytest.raises(RuntimeError, match="R4.1#1"):
            await _smoke_branch_isolation(data, None)

    @pytest.mark.asyncio
    async def test_r41_2_wdqms_found_under_gw(self, both_tenants_catalog):
        """Assertion 2: WDQMS found under gw → R4.1#2 (isolation violated)."""
        data = MagicMock()
        data.graph_db.query = AsyncMock(side_effect=[
            [{"name": "JGDAS_ATMOS_ANALYSIS_WDQMS"}],  # v17 has it (pass #1)
            [{"name": "JGDAS_ATMOS_ANALYSIS_WDQMS"}],  # gw also has it (fail #2)
        ])
        data.vector_db.query = AsyncMock(return_value=[])

        with pytest.raises(RuntimeError, match="R4.1#2"):
            await _smoke_branch_isolation(data, None)

    @pytest.mark.asyncio
    async def test_r41_3_mpas_not_found_under_gw(self, both_tenants_catalog):
        """Assertion 3: MPAS Voronoi not found under gw → R4.1#3."""
        data = MagicMock()
        data.graph_db.query = AsyncMock(side_effect=[
            [{"name": "JGDAS_ATMOS_ANALYSIS_WDQMS"}],  # v17 has it
            [],  # gw doesn't
        ])
        data.vector_db.query = AsyncMock(side_effect=[
            [],  # gw has no MPAS (fail #3)
        ])

        with pytest.raises(RuntimeError, match="R4.1#3"):
            await _smoke_branch_isolation(data, None)

    @pytest.mark.asyncio
    async def test_r41_4_develop_content_leaks_to_v17(self, both_tenants_catalog):
        """Assertion 4: develop-sourced content in v17 results → R4.1#4."""
        data = MagicMock()
        data.graph_db.query = AsyncMock(side_effect=[
            [{"name": "JGDAS_ATMOS_ANALYSIS_WDQMS"}],  # v17 has it
            [],  # gw doesn't
        ])
        data.vector_db.query = AsyncMock(side_effect=[
            [{"metadata": {"source": "/mnt/workflow/develop/docs/mpas.md"}}],  # gw has MPAS
            [{"metadata": {"source": "/mnt/workflow/develop/docs/mpas.md"}}],  # v17 leaks develop content
        ])

        with pytest.raises(RuntimeError, match="R4.1#4"):
            await _smoke_branch_isolation(data, None)
