"""Unit tests for config ingester write helpers (cypher + OS doc shape).

Validates: R2.1–R2.5, R3.2–R3.3.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))
sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from scripts.ingest_config_files_v8 import (
    _build_context_header,
    _build_os_metadata,
    _node_name,
    _write_config_node,
    _write_sets_env_edges,
)


@dataclass
class FakeTenant:
    tenant_id: str = "gw_v17"


@pytest.fixture
def mock_graph_db():
    db = AsyncMock()
    db.calls = []

    async def record_query(cypher, params=None, *, tenant=None):
        db.calls.append({"cypher": cypher, "params": params, "tenant": tenant})

    db.query = record_query
    return db


@pytest.fixture
def gfs_cfg():
    return {'abs_path': '/w/parm/config/gfs/config.fcst',
            'rel_path': 'parm/config/gfs/config.fcst',
            'filename': 'config.fcst', 'system': 'gfs'}


@pytest.fixture
def gefs_cfg():
    return {'abs_path': '/w/parm/config/gefs/config.fcst',
            'rel_path': 'parm/config/gefs/config.fcst',
            'filename': 'config.fcst', 'system': 'gefs'}


@pytest.fixture
def parsed():
    return {'env_vars': [{'name': 'COMROOT', 'default_value': '/com', 'is_default': True},
                         {'name': 'CASE', 'default_value': 'C384', 'is_default': False}],
            'sources': [], 'raw_content': 'export COMROOT=...', 'line_count': 1}


class TestNodeName:
    """R2.5: GFS short name; non-GFS system-qualified."""

    def test_gfs_short(self, gfs_cfg):
        assert _node_name(gfs_cfg) == 'fcst'

    def test_non_gfs_qualified(self, gefs_cfg):
        assert _node_name(gefs_cfg) == 'gefs/fcst'


class TestWriteConfigNode:
    """R2.1/R2.4: ConfigFile node, prefixed label, tenant=None."""

    @pytest.mark.asyncio
    async def test_prefixed_label(self, mock_graph_db, gfs_cfg, parsed):
        await _write_config_node(mock_graph_db, "GW_V17_", gfs_cfg, parsed, FakeTenant())
        call = mock_graph_db.calls[0]
        assert "`GW_V17_ConfigFile`" in call["cypher"]
        assert call["params"]["name"] == "fcst"
        assert call["params"]["env_var_count"] == 2
        assert call["params"]["category"] == "forecast"
        assert call["params"]["tenant_id"] == "gw_v17"
        assert call["tenant"] is None

    @pytest.mark.asyncio
    async def test_empty_prefix(self, mock_graph_db, gfs_cfg, parsed):
        await _write_config_node(mock_graph_db, "", gfs_cfg, parsed, FakeTenant("gw"))
        call = mock_graph_db.calls[0]
        assert "`ConfigFile`" in call["cypher"]
        assert "`_ConfigFile`" not in call["cypher"]


class TestWriteSetsEnv:
    """R2.2: one SETS_ENV MERGE per env var; empty names skipped."""

    @pytest.mark.asyncio
    async def test_one_edge_per_var(self, mock_graph_db, gfs_cfg, parsed):
        await _write_sets_env_edges(mock_graph_db, "GW_V17_", gfs_cfg, parsed)
        assert len(mock_graph_db.calls) == 2
        c0 = mock_graph_db.calls[0]
        assert "SETS_ENV" in c0["cypher"]
        assert "`GW_V17_EnvironmentVariable`" in c0["cypher"]
        assert c0["params"]["config_name"] == "fcst"
        assert c0["params"]["var_name"] == "COMROOT"
        assert c0["params"]["value"] == "/com"
        assert c0["params"]["is_default"] is True
        assert c0["tenant"] is None

    @pytest.mark.asyncio
    async def test_empty_name_skipped(self, mock_graph_db, gfs_cfg):
        p = {'env_vars': [{'name': '', 'default_value': 'x', 'is_default': False}]}
        await _write_sets_env_edges(mock_graph_db, "GW_V17_", gfs_cfg, p)
        assert len(mock_graph_db.calls) == 0


class TestContextHeaderAndMetadata:
    """R3.3 header; R3.2 metadata."""

    def test_header_contains_fields(self, gfs_cfg, parsed):
        h = _build_context_header(gfs_cfg, parsed)
        assert "config.fcst" in h
        assert "gfs" in h
        assert "forecast" in h
        assert "parm/config/gfs/config.fcst" in h
        assert "COMROOT" in h

    def test_metadata_fields(self, gfs_cfg, parsed):
        m = _build_os_metadata(gfs_cfg, parsed, FakeTenant())
        assert m['file_type'] == 'config'
        assert m['system'] == 'gfs'
        assert m['category'] == 'forecast'
        assert m['file_path'] == 'parm/config/gfs/config.fcst'
        assert m['filename'] == 'config.fcst'
        assert m['env_var_count'] == 2
        assert m['tenant_id'] == 'gw_v17'
        assert json.loads(m['env_vars']) == ['COMROOT', 'CASE']
