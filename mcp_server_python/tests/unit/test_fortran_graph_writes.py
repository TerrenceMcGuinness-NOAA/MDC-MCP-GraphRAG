"""Unit tests for Fortran graph write helpers (cypher generation).

Validates: R5.1–R5.6, R6.1–R6.5 — correct back-tick-quoted, prefix-interpolated
cypher with tenant=None bypass, placeholder callees, and CONTAINS gating.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))
sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from scripts._fortran_parser import FortranParseResult
from scripts.ingest_fortran_graph_v8 import (
    VERSION,
    _write_calls,
    _write_contains,
    _write_function_nodes,
    _write_module_nodes,
    _write_program_nodes,
    _write_subroutine_nodes,
    _write_uses,
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
    return FortranParseResult(
        file_path="/wt/sorc/foo.f90",
        relative_path="sorc/foo.f90",
        modules=[{"name": "weather_mod", "line_start": 1}],
        subroutines=[
            {"name": "compute", "line_start": 5, "parent_module": "weather_mod"},
            {"name": "standalone", "line_start": 20, "parent_module": None},
        ],
        functions=[
            {"name": "square", "line_start": 10, "parent_module": "weather_mod",
             "return_type": None},
        ],
        programs=[{"name": "driver", "executable_name": "ufs_model.x"}],
        calls=[{"callee": "alpha", "line": 6, "caller": None}],
        uses=[{"module": "kinds_mod", "only": "Only_List(',', (Name('r8'),))"}],
    )


# ════════════════════════════════════════════════════════════════════════
# Node writers (R5)
# ════════════════════════════════════════════════════════════════════════


class TestWriteModuleNodes:
    """R5.1: FortranModule MERGE keyed on name."""

    @pytest.mark.asyncio
    async def test_prefixed_label_and_params(self, mock_graph_db, sample_result):
        await _write_module_nodes(mock_graph_db, "GW_V17_", sample_result, "gw_v17")
        call = mock_graph_db.calls[0]
        assert "MERGE (m:`GW_V17_FortranModule` {name: $name})" in call["cypher"]
        assert call["params"]["name"] == "weather_mod"
        assert call["params"]["file_path"] == "sorc/foo.f90"
        assert call["params"]["line_start"] == 1
        assert call["params"]["tenant_id"] == "gw_v17"
        assert call["params"]["version"] == VERSION
        assert call["tenant"] is None

    @pytest.mark.asyncio
    async def test_empty_prefix_no_underscore(self, mock_graph_db, sample_result):
        """Default tenant (gw) → empty prefix → :FortranModule not :_FortranModule."""
        await _write_module_nodes(mock_graph_db, "", sample_result, "gw")
        call = mock_graph_db.calls[0]
        assert "`FortranModule`" in call["cypher"]
        assert "`_FortranModule`" not in call["cypher"]


class TestWriteSubroutineNodes:
    """R5.2: FortranSubroutine MERGE keyed on (name, file_path)."""

    @pytest.mark.asyncio
    async def test_merge_key_is_name_and_path(self, mock_graph_db, sample_result):
        await _write_subroutine_nodes(mock_graph_db, "GW_V17_", sample_result, "gw_v17")
        assert len(mock_graph_db.calls) == 2
        call = mock_graph_db.calls[0]
        assert ("MERGE (s:`GW_V17_FortranSubroutine` "
                "{name: $name, file_path: $file_path})") in call["cypher"]
        assert call["params"]["parent_module"] == "weather_mod"
        assert call["tenant"] is None


class TestWriteFunctionNodes:
    """R5.3: FortranFunction MERGE keyed on (name, file_path) + return_type."""

    @pytest.mark.asyncio
    async def test_function_node(self, mock_graph_db, sample_result):
        await _write_function_nodes(mock_graph_db, "GW_V17_", sample_result, "gw_v17")
        call = mock_graph_db.calls[0]
        assert ("MERGE (f:`GW_V17_FortranFunction` "
                "{name: $name, file_path: $file_path})") in call["cypher"]
        assert "f.return_type = $return_type" in call["cypher"]
        assert call["params"]["name"] == "square"
        assert call["params"]["return_type"] is None


class TestWriteProgramNodes:
    """R5.4: FortranProgram MERGE keyed on name + executable_name."""

    @pytest.mark.asyncio
    async def test_program_node(self, mock_graph_db, sample_result):
        await _write_program_nodes(mock_graph_db, "GW_V17_", sample_result, "gw_v17")
        call = mock_graph_db.calls[0]
        assert "MERGE (p:`GW_V17_FortranProgram` {name: $name})" in call["cypher"]
        assert call["params"]["name"] == "driver"
        assert call["params"]["exe_name"] == "ufs_model.x"
        assert call["tenant"] is None


# ════════════════════════════════════════════════════════════════════════
# Relationship writers (R6)
# ════════════════════════════════════════════════════════════════════════


class TestWriteCalls:
    """R6.1, R6.5: CALLS edge + placeholder callee MERGE."""

    @pytest.mark.asyncio
    async def test_calls_creates_placeholder_callee(self, mock_graph_db, sample_result):
        await _write_calls(mock_graph_db, "GW_V17_", sample_result)
        call = mock_graph_db.calls[0]
        # Placeholder callee MERGE keyed on name only (no file_path).
        assert "MERGE (callee:`GW_V17_FortranSubroutine` {name: $callee_name})" in call["cypher"]
        assert "MERGE (caller)-[rel:CALLS]->(callee)" in call["cypher"]
        # Caller selected by file_path across the three node types.
        assert "caller:`GW_V17_FortranSubroutine`" in call["cypher"]
        assert "caller:`GW_V17_FortranFunction`" in call["cypher"]
        assert "caller:`GW_V17_FortranProgram`" in call["cypher"]
        assert call["params"]["callee_name"] == "alpha"
        assert call["params"]["line"] == 6
        assert call["params"]["source_file"] == "sorc/foo.f90"
        assert call["tenant"] is None


class TestWriteUses:
    """R6.2: USES edge to FortranModule with only property."""

    @pytest.mark.asyncio
    async def test_uses_edge(self, mock_graph_db, sample_result):
        await _write_uses(mock_graph_db, "GW_V17_", sample_result)
        call = mock_graph_db.calls[0]
        assert "MERGE (mod:`GW_V17_FortranModule` {name: $module_name})" in call["cypher"]
        assert "MERGE (user)-[rel:USES]->(mod)" in call["cypher"]
        assert call["params"]["module_name"] == "kinds_mod"
        assert "r8" in call["params"]["only_clause"]
        assert call["tenant"] is None


class TestWriteContains:
    """R6.3: CONTAINS only for entities with parent_module set."""

    @pytest.mark.asyncio
    async def test_contains_only_for_contained(self, mock_graph_db, sample_result):
        await _write_contains(mock_graph_db, "GW_V17_", sample_result)
        # 1 contained subroutine (compute) + 1 contained function (square).
        # standalone (parent_module None) → no CONTAINS edge.
        assert len(mock_graph_db.calls) == 2
        cyphers = [c["cypher"] for c in mock_graph_db.calls]
        assert any("MERGE (m)-[:CONTAINS]->(s)" in c for c in cyphers)
        assert any("MERGE (m)-[:CONTAINS]->(f)" in c for c in cyphers)
        for c in mock_graph_db.calls:
            assert "`GW_V17_FortranModule`" in c["cypher"]
            assert c["tenant"] is None
        # standalone subroutine never appears as a CONTAINS target.
        sub_names = [c["params"].get("sub_name") for c in mock_graph_db.calls]
        assert "standalone" not in sub_names
        assert "compute" in sub_names

    @pytest.mark.asyncio
    async def test_no_contains_when_no_parent(self, mock_graph_db):
        r = FortranParseResult(
            file_path="/wt/sorc/x.f90",
            relative_path="sorc/x.f90",
            subroutines=[{"name": "loner", "line_start": 1, "parent_module": None}],
        )
        await _write_contains(mock_graph_db, "GW_V17_", r)
        assert len(mock_graph_db.calls) == 0


class TestAllWritesBypassRewrite:
    """All writes pass tenant=None to bypass _rewrite_cypher."""

    @pytest.mark.asyncio
    async def test_all_writes_tenant_none(self, mock_graph_db, sample_result):
        await _write_module_nodes(mock_graph_db, "GW_V17_", sample_result, "gw_v17")
        await _write_subroutine_nodes(mock_graph_db, "GW_V17_", sample_result, "gw_v17")
        await _write_function_nodes(mock_graph_db, "GW_V17_", sample_result, "gw_v17")
        await _write_program_nodes(mock_graph_db, "GW_V17_", sample_result, "gw_v17")
        await _write_calls(mock_graph_db, "GW_V17_", sample_result)
        await _write_uses(mock_graph_db, "GW_V17_", sample_result)
        await _write_contains(mock_graph_db, "GW_V17_", sample_result)
        assert mock_graph_db.calls  # sanity: something was written
        for call in mock_graph_db.calls:
            assert call["tenant"] is None, f"Expected tenant=None, got {call['tenant']}"
            assert "MERGE" in call["cypher"]
