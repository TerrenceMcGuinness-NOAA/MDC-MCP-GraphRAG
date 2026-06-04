"""Unit tests for the Rocoto ingester write helpers.

Validates: R7.1–R7.9, R8.1–R8.3, R8.5.
"""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))
sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from scripts._ingest_cost_model import IngestionReportWriter
from scripts._rocoto_parser import RocotoXMLParser
from scripts.ingest_rocoto_xml_v8 import (
    _collect_all_tasks,
    _ingest_rocoto_workflow,
    _walk_deps,
    _write_data_dependencies,
    _write_metatask,
    _write_runs_on,
    _write_runs_script,
    _write_task,
    _write_uses_env,
)


@dataclass
class FakeTenant:
    tenant_id: str = "gw_v17"
    branch: str = "dev/gfs.v17"


class RecordingDB:
    """graph_db stub recording calls; query returns a configurable value."""

    def __init__(self, return_value=None):
        self.calls = []
        self._return = return_value

    async def query(self, cypher, params=None, *, tenant=None):
        self.calls.append({"cypher": cypher, "params": params, "tenant": tenant})
        # ShellScript existence probe returns the configured value
        if "RETURN s.path AS path" in cypher:
            return self._return
        return None

    def cyphers(self):
        return [c["cypher"] for c in self.calls]


def _report():
    return IngestionReportWriter("gw_v17", "dev/gfs.v17", "full")


@pytest.fixture
def task():
    return {'name': 'fcst', 'experiment': 'C48', 'command': '/scripts/exfcst.sh',
            'cycledefs': 'gfs,gdas', 'maxtries': '2', 'is_final': False,
            'resources': {'walltime': '01:00:00', 'cores': 240},
            'envars': {'CDATE': 'x', 'RUN': 'gfs'},
            'dependency_tree': {}, 'data_dependencies': []}


class TestWriteTask:
    """R7.1: composite key {name, experiment}."""

    @pytest.mark.asyncio
    async def test_composite_key_and_props(self, task):
        db = RecordingDB()
        await _write_task(db, "GW_V17_", task, "C48", FakeTenant())
        c = db.calls[0]
        assert "`GW_V17_RocotoTask`" in c["cypher"]
        assert "{name: $name, experiment: $experiment}" in c["cypher"]
        assert c["params"]["name"] == "fcst"
        assert c["params"]["experiment"] == "C48"
        assert c["params"]["cores"] == 240
        assert c["tenant"] is None


class TestWalkDeps:
    """R7.5: DEPENDS_ON edges with dep_type, cycle_offset, condition."""

    @pytest.mark.asyncio
    async def test_nested_and_or(self):
        dep = ET.fromstring(
            '<dependency><and>'
            '<taskdep task="prep"/>'
            '<or><taskdep task="a"/><taskdep task="b" cycle_offset="-06:00:00"/></or>'
            '</and></dependency>'
        )
        tree = RocotoXMLParser.parse_dependency_tree(dep)
        db = RecordingDB()
        await _walk_deps(db, "GW_V17_", "fcst", tree, "C48", _report())
        # three leaf task deps → three DEPENDS_ON edges
        dep_calls = [c for c in db.calls if "DEPENDS_ON" in c["cypher"]]
        assert len(dep_calls) == 3
        names = {c["params"]["dep_name"] for c in dep_calls}
        assert names == {"prep", "a", "b"}
        # condition carried from nearest operator; 'b' under <or>
        b = next(c for c in dep_calls if c["params"]["dep_name"] == "b")
        assert b["params"]["condition"] == "or"
        assert b["params"]["cycle_offset"] == "-06:00:00"


class TestDataDeps:
    """R7.6: DEPENDS_ON_DATA with path_pattern + age."""

    @pytest.mark.asyncio
    async def test_data_dep_edge(self):
        t = {'name': 'fcst', 'data_dependencies': [{'path': '/in/@Y', 'age': '120'}]}
        db = RecordingDB()
        await _write_data_dependencies(db, "GW_V17_", t, "C48", _report())
        c = db.calls[0]
        assert "DEPENDS_ON_DATA" in c["cypher"]
        assert "`GW_V17_DataDependency`" in c["cypher"]
        assert c["params"]["path_pattern"] == "/in/@Y"
        assert c["params"]["age"] == "120"


class TestRunsScript:
    """R8.1 / R8.5: ENDS WITH match; graceful when no ShellScript."""

    @pytest.mark.asyncio
    async def test_match_creates_edge(self, task):
        db = RecordingDB(return_value=[{"path": "scripts/exfcst.sh"}])
        unmatched = []
        await _write_runs_script(db, "GW_V17_", task, "C48", _report(), unmatched)
        assert any("RUNS_SCRIPT" in c for c in db.cyphers())
        assert any("ENDS WITH $basename" in c for c in db.cyphers())
        assert unmatched == []

    @pytest.mark.asyncio
    async def test_no_match_records_unmatched(self, task):
        db = RecordingDB(return_value=[])   # no ShellScript
        unmatched = []
        await _write_runs_script(db, "GW_V17_", task, "C48", _report(), unmatched)
        assert not any("MERGE (t)-[:RUNS_SCRIPT]" in c for c in db.cyphers())
        assert unmatched == [{"task": "fcst", "basename": "exfcst.sh"}]


class TestUsesEnvAndRunsOn:
    @pytest.mark.asyncio
    async def test_uses_env_per_var(self, task):
        db = RecordingDB()
        await _write_uses_env(db, "GW_V17_", task, "C48", _report())
        assert len(db.calls) == 2  # CDATE, RUN
        assert all("USES_ENV" in c for c in db.cyphers())

    @pytest.mark.asyncio
    async def test_runs_on_comma_split(self, task):
        db = RecordingDB()
        await _write_runs_on(db, "GW_V17_", task, "C48", _report())
        groups = {c["params"]["group"] for c in db.calls}
        assert groups == {"gfs", "gdas"}
        assert all("RUNS_ON" in c for c in db.cyphers())


class TestMetataskAndTwoPass:
    """R7.7 MEMBER_OF; two-pass node-before-edge ordering."""

    @pytest.mark.asyncio
    async def test_metatask_member_of(self):
        mt = {'name': 'efcs', 'mode': 'parallel', 'variables': {'m': ['1', '2']},
              'tasks': [{'name': 't1', 'experiment': 'C48', 'command': '', 'cycledefs': '',
                         'maxtries': '1', 'is_final': False, 'resources': {},
                         'envars': {}, 'dependency_tree': {}, 'data_dependencies': []}],
              'nested_metatasks': []}
        db = RecordingDB()
        await _write_metatask(db, "GW_V17_", mt, "C48", FakeTenant(), _report())
        assert any("`GW_V17_RocotoMetatask`" in c for c in db.cyphers())
        assert any("MEMBER_OF" in c for c in db.cyphers())

    @pytest.mark.asyncio
    async def test_two_pass_nodes_before_edges(self):
        xml = (
            '<workflow>'
            '<cycledef group="gfs">2024 2025 06:00:00</cycledef>'
            '<task name="prep"><command>/p.sh</command><cycledefs/></task>'
            '<task name="fcst" cycledefs="gfs"><command>/f.sh</command>'
            '<dependency><taskdep task="prep"/></dependency></task>'
            '</workflow>'
        )
        # parse via ET into our parser's dict shape
        root = ET.fromstring(xml)
        parsed = {
            'cycledefs': [{'group': 'gfs', 'definition': '2024 2025 06:00:00'}],
            'tasks': [RocotoXMLParser.parse_task_element(c)
                      for c in root if c.tag == 'task'],
            'metatasks': [],
        }
        db = RecordingDB()
        unmatched = []
        await _ingest_rocoto_workflow(db, "GW_V17_", parsed, "C48",
                                      FakeTenant(), _report(), unmatched)
        cyphers = db.cyphers()
        first_task_merge = next(i for i, c in enumerate(cyphers)
                                if "MERGE (t:`GW_V17_RocotoTask`" in c)
        first_depends_on = next(i for i, c in enumerate(cyphers)
                                if "DEPENDS_ON" in c)
        assert first_task_merge < first_depends_on
        assert _collect_all_tasks(parsed)[0]['name'] == 'prep'
