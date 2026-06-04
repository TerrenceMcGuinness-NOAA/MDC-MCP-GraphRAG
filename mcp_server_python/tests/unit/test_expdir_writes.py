"""Unit tests for the EXPDIR ingester (resolver, discovery, write helper).

Validates: R4.1–R4.6, R5.1–R5.6, R8.4.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))
sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from scripts._ingest_cost_model import IngestionReportWriter
from scripts.ingest_expdir_configs_v8 import (
    discover_experiments,
    resolve_expdir_base,
    _ingest_experiment,
)


@dataclass
class FakeTenant:
    tenant_id: str = "gw_v17"
    branch: str = "dev/gfs.v17"


@pytest.fixture
def mock_graph_db():
    db = AsyncMock()
    db.calls = []

    async def record_query(cypher, params=None, *, tenant=None):
        db.calls.append({"cypher": cypher, "params": params, "tenant": tenant})

    db.query = record_query
    return db


def _make_expdir(base: Path):
    d = base / "C48_ATM_250b0130-10380"
    d.mkdir(parents=True)
    (d / "config.fcst").write_text('export COMROOT="${COMROOT:-/com}"\nexport CASE=C48')
    (d / "config.resources.HERA").write_text("export NTASKS=40")
    (d / "C48_ATM.xml").write_text("<workflow/>")
    (d / "notconfig.txt").write_text("ignore")
    return d


class TestResolveExpdirBase:
    def test_override_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MCP_EXPDIR_BASE_OVERRIDE", str(tmp_path))
        assert resolve_expdir_base(FakeTenant()) == tmp_path

    def test_default_supported_repos(self, monkeypatch):
        monkeypatch.delenv("MCP_EXPDIR_BASE_OVERRIDE", raising=False)
        base = resolve_expdir_base(FakeTenant())
        assert base.parts[-2:] == ("supported_repos", "EXPDIR")


class TestDiscoverExperiments:
    def test_name_resolution_configs_xml(self, tmp_path):
        _make_expdir(tmp_path)
        exps = discover_experiments(tmp_path)
        assert len(exps) == 1
        e = exps[0]
        assert e['experiment_name'] == "C48_ATM"     # hash stripped
        assert e['pslot'] == "C48_ATM_250b0130-10380"
        assert e['resolution'] == "C48"
        assert e['xml_path'].endswith("C48_ATM.xml")
        # only config.* files, sorted
        assert all(Path(c).name.startswith("config.") for c in e['configs'])
        assert len(e['configs']) == 2

    def test_filter(self, tmp_path):
        _make_expdir(tmp_path)
        (tmp_path / "C96_OTHER_aabbcc11-2233").mkdir()
        assert len(discover_experiments(tmp_path, "C48")) == 1
        assert len(discover_experiments(tmp_path, "C96")) == 1
        assert len(discover_experiments(tmp_path, "ZZZ")) == 0

    def test_missing_base(self, tmp_path):
        assert discover_experiments(tmp_path / "nope") == []


class TestIngestExperiment:
    @pytest.mark.asyncio
    async def test_full_sequence(self, tmp_path, mock_graph_db):
        _make_expdir(tmp_path)
        exp = discover_experiments(tmp_path)[0]
        report = IngestionReportWriter("gw_v17", "dev/gfs.v17", "full")
        await _ingest_experiment(mock_graph_db, "GW_V17_", exp, FakeTenant(), report)

        cyphers = [c["cypher"] for c in mock_graph_db.calls]
        # Experiment node
        assert any("`GW_V17_Experiment`" in c and "MERGE (e" in c for c in cyphers)
        # EXPDIRConfig node with compound name key experiment/filename
        ec_call = next(c for c in mock_graph_db.calls
                       if "MERGE (ec:`GW_V17_EXPDIRConfig`" in c["cypher"])
        assert ec_call["params"]["name"] == "C48_ATM/config.fcst"
        # PART_OF + RESOLVES_FROM present
        assert any("PART_OF" in c for c in cyphers)
        assert any("RESOLVES_FROM" in c for c in cyphers)
        # SETS_ENV present, tenant=None on all
        assert any("SETS_ENV" in c for c in cyphers)
        assert all(c["tenant"] is None for c in mock_graph_db.calls)

    @pytest.mark.asyncio
    async def test_resources_excluded_from_resolves_from(self, tmp_path, mock_graph_db):
        _make_expdir(tmp_path)
        exp = discover_experiments(tmp_path)[0]
        report = IngestionReportWriter("gw_v17", "dev/gfs.v17", "full")
        await _ingest_experiment(mock_graph_db, "GW_V17_", exp, FakeTenant(), report)

        # RESOLVES_FROM must reference config.fcst (short name 'fcst'),
        # never the config.resources.HERA file.
        rf_calls = [c for c in mock_graph_db.calls if "RESOLVES_FROM" in c["cypher"]]
        short_names = {c["params"]["short_name"] for c in rf_calls}
        assert short_names == {"fcst"}
