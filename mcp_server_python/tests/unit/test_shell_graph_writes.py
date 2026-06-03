"""Unit tests for shell graph write helpers (cypher generation).

Validates: R3.1–R3.7 — correct back-tick-quoted, prefix-interpolated cypher
with tenant=None bypass.
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))
sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from scripts._shell_parser import ShellParseResult
from scripts.ingest_shell_graph_v8 import (
    _write_defines,
    _write_depends_on_env,
    _write_exports,
    _write_invokes,
    _write_reads_config,
    _write_script_node,
    _write_sources,
)


@pytest.fixture
def mock_graph_db():
    """AsyncMock graph_db that records (cypher, params, tenant) calls."""
    db = AsyncMock()
    db.calls = []

    async def record_query(cypher, params=None, *, tenant=None):
        db.calls.append({"cypher": cypher, "params": params, "tenant": tenant})

    db.query = record_query
    return db


@pytest.fixture
def sample_result():
    return ShellParseResult(
        path="dev/jobs/JGFS_FORECAST",
        name="JGFS_FORECAST",
        type="jjob",
        category="forecast",
        sources=[{"path": "${USHgfs}/preamble.sh", "line": 3, "resolved": "ush/preamble.sh"}],
        invokes=[{"script": "exglobal_fcst.sh", "variable": "SCRIPTSgfs", "line": 10, "package": "internal"}],
        exports=[{"name": "CDATE", "value": "2024010100", "line": 5}],
        env_deps=["DATAROOT", "COMOUT"],
        functions=[{"name": "cleanup", "line": 20}],
        configs=[{"name": "base", "line": 7}],
    )


class TestWriteScriptNode:
    """R3.1: ShellScript node creation with tenant prefix."""

    @pytest.mark.asyncio
    async def test_prefixed_label(self, mock_graph_db, sample_result):
        await _write_script_node(mock_graph_db, "GW_V17_", sample_result, "gw_v17")
        call = mock_graph_db.calls[0]
        assert "`GW_V17_ShellScript`" in call["cypher"]
        assert call["params"]["path"] == "dev/jobs/JGFS_FORECAST"
        assert call["params"]["tenant_id"] == "gw_v17"
        assert call["tenant"] is None

    @pytest.mark.asyncio
    async def test_empty_prefix_no_underscore(self, mock_graph_db, sample_result):
        """Default tenant (gw) → empty prefix → :ShellScript not :_ShellScript."""
        await _write_script_node(mock_graph_db, "", sample_result, "gw")
        call = mock_graph_db.calls[0]
        assert "`ShellScript`" in call["cypher"]
        assert "`_ShellScript`" not in call["cypher"]


class TestWriteSources:
    """R3.6: SOURCES relationship."""

    @pytest.mark.asyncio
    async def test_sources_relationship(self, mock_graph_db, sample_result):
        await _write_sources(mock_graph_db, "GW_V17_", sample_result)
        call = mock_graph_db.calls[0]
        assert "SOURCES" in call["cypher"]
        assert "`GW_V17_ShellScript`" in call["cypher"]
        assert call["params"]["tp"] == "ush/preamble.sh"  # resolved path
        assert call["params"]["line"] == 3
        assert call["tenant"] is None


class TestWriteInvokes:
    """R3.6: INVOKES relationship."""

    @pytest.mark.asyncio
    async def test_invokes_relationship(self, mock_graph_db, sample_result):
        await _write_invokes(mock_graph_db, "GW_V17_", sample_result)
        call = mock_graph_db.calls[0]
        assert "INVOKES" in call["cypher"]
        assert call["params"]["tn"] == "exglobal_fcst.sh"
        assert call["params"]["var"] == "SCRIPTSgfs"


class TestWriteExports:
    """R3.6: EXPORTS relationship to EnvironmentVariable."""

    @pytest.mark.asyncio
    async def test_exports_relationship(self, mock_graph_db, sample_result):
        await _write_exports(mock_graph_db, "GW_V17_", sample_result)
        call = mock_graph_db.calls[0]
        assert "EXPORTS" in call["cypher"]
        assert "`GW_V17_EnvironmentVariable`" in call["cypher"]
        assert call["params"]["vn"] == "CDATE"
        assert call["params"]["dv"] == "2024010100"


class TestWriteDependsOnEnv:
    """R3.6: DEPENDS_ON_ENV relationship."""

    @pytest.mark.asyncio
    async def test_depends_on_env(self, mock_graph_db, sample_result):
        await _write_depends_on_env(mock_graph_db, "GW_V17_", sample_result)
        assert len(mock_graph_db.calls) == 2  # DATAROOT, COMOUT
        for call in mock_graph_db.calls:
            assert "DEPENDS_ON_ENV" in call["cypher"]
            assert "`GW_V17_EnvironmentVariable`" in call["cypher"]


class TestWriteReadsConfig:
    """R3.6: READS_CONFIG relationship."""

    @pytest.mark.asyncio
    async def test_reads_config(self, mock_graph_db, sample_result):
        await _write_reads_config(mock_graph_db, "GW_V17_", sample_result)
        call = mock_graph_db.calls[0]
        assert "READS_CONFIG" in call["cypher"]
        assert "`GW_V17_ConfigFile`" in call["cypher"]
        assert call["params"]["cn"] == "base"
        assert call["params"]["cp"] == "parm/config/config.base"


class TestWriteDefines:
    """R3.6: DEFINES relationship to ShellFunction."""

    @pytest.mark.asyncio
    async def test_defines_function(self, mock_graph_db, sample_result):
        await _write_defines(mock_graph_db, "GW_V17_", sample_result)
        call = mock_graph_db.calls[0]
        assert "DEFINES" in call["cypher"]
        assert "`GW_V17_ShellFunction`" in call["cypher"]
        assert call["params"]["fn"] == "cleanup"


class TestAllWritesBypassRewrite:
    """R3.7: All writes pass tenant=None to bypass _rewrite_cypher."""

    @pytest.mark.asyncio
    async def test_all_writes_tenant_none(self, mock_graph_db, sample_result):
        await _write_script_node(mock_graph_db, "GW_V17_", sample_result, "gw_v17")
        await _write_sources(mock_graph_db, "GW_V17_", sample_result)
        await _write_invokes(mock_graph_db, "GW_V17_", sample_result)
        await _write_exports(mock_graph_db, "GW_V17_", sample_result)
        await _write_depends_on_env(mock_graph_db, "GW_V17_", sample_result)
        await _write_reads_config(mock_graph_db, "GW_V17_", sample_result)
        await _write_defines(mock_graph_db, "GW_V17_", sample_result)
        for call in mock_graph_db.calls:
            assert call["tenant"] is None, f"Expected tenant=None, got {call['tenant']}"
