"""Property tests for graph-port-workflow-structure (P1–P7).

P1 Config file completeness        — R1.1, R2.1
P2 SETS_ENV correctness            — R2.2, R5.5
P3 EXPDIR resolution chain         — R5.4, R8.4
P4 Rocoto DAG completeness         — R6.3/6.4, R7.1/7.5
P5 Metatask hierarchy correctness  — R6.4, R7.7
P6 Idempotence (MERGE semantics)   — R2.3, R5.6, R7.9
P7 Tenant isolation                — R2.4, R9.6
"""
from __future__ import annotations

import asyncio
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).parents[2]))
sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from scripts._ingest_cost_model import IngestionReportWriter
from scripts.ingest_config_files_v8 import (
    _write_config_node,
    _write_sets_env_edges,
    discover_config_files,
)
from scripts.ingest_expdir_configs_v8 import _ingest_experiment, discover_experiments
from scripts.ingest_rocoto_xml_v8 import _ingest_rocoto_workflow, _write_metatask


@dataclass
class FakeTenant:
    tenant_id: str = "gw_v17"
    branch: str = "dev/gfs.v17"


class RecordingDB:
    """graph_db stub; query records calls and returns a configurable value."""

    def __init__(self, return_value=None):
        self.calls = []
        self._return = return_value

    async def query(self, cypher, params=None, *, tenant=None):
        self.calls.append({"cypher": cypher, "params": params, "tenant": tenant})
        if "RETURN s.path AS path" in cypher:
            return self._return
        return None

    def cyphers(self):
        return [c["cypher"] for c in self.calls]


def _report():
    return IngestionReportWriter("gw_v17", "dev/gfs.v17", "full")


_LABELS = re.compile(r"`([A-Za-z0-9_]+)`")
_VAR_NAME = st.from_regex(r"[A-Z][A-Z0-9_]{0,7}", fullmatch=True)


# ════════════════════════════════════════════════════════════════════════
# P1 — config file completeness
# ════════════════════════════════════════════════════════════════════════


@settings(max_examples=100)
@given(n_valid=st.integers(min_value=0, max_value=12),
       n_excluded=st.integers(min_value=0, max_value=6))
def test_p1_discovery_count_equals_valid(n_valid, n_excluded, tmp_path_factory):
    root = tmp_path_factory.mktemp("wt")
    d = root / "parm" / "config" / "gfs"
    d.mkdir(parents=True)
    for i in range(n_valid):
        (d / f"config.v{i}").write_text("export A=1")
    for i in range(n_excluded):
        (d / f"config.x{i}.j2").write_text("{{x}}")
        (d / f"tmpl{i}.yaml").write_text("a: 1")

    configs = discover_config_files(root)
    assert len(configs) == n_valid

    # N discovered → N ConfigFile MERGE calls
    db = RecordingDB()
    for cfg in configs:
        asyncio.run(_write_config_node(db, "GW_V17_", cfg,
                                       {"env_vars": [], "line_count": 0}, FakeTenant()))
    merges = [c for c in db.cyphers() if "MERGE (c:`GW_V17_ConfigFile`" in c]
    assert len(merges) == n_valid


# ════════════════════════════════════════════════════════════════════════
# P2 — SETS_ENV correctness
# ════════════════════════════════════════════════════════════════════════


@settings(max_examples=100)
@given(names=st.lists(_VAR_NAME, unique=True, max_size=10),
       value=st.text(max_size=20))
def test_p2_sets_env_one_edge_per_var(names, value):
    parsed = {"env_vars": [{"name": n, "default_value": value, "is_default": False}
                           for n in names]}
    cfg = {"filename": "config.fcst", "system": "gfs"}
    db = RecordingDB()
    asyncio.run(_write_sets_env_edges(db, "GW_V17_", cfg, parsed))
    assert len(db.calls) == len(names)
    for call, name in zip(db.calls, names):
        assert "SETS_ENV" in call["cypher"]
        assert call["params"]["var_name"] == name
        assert call["params"]["value"] == value


# ════════════════════════════════════════════════════════════════════════
# P3 — EXPDIR resolution chain correctness
# ════════════════════════════════════════════════════════════════════════


@settings(max_examples=50, deadline=None)
@given(short_names=st.lists(st.from_regex(r"[a-z][a-z0-9_]{0,6}", fullmatch=True),
                            unique=True, max_size=6),
       n_resource=st.integers(min_value=0, max_value=3))
def test_p3_resolves_from_targets_short_name(short_names, n_resource, tmp_path_factory):
    base = tmp_path_factory.mktemp("expdir")
    exp_dir = base / "C48_ATM_250b0130-10380"
    exp_dir.mkdir(parents=True)
    for s in short_names:
        (exp_dir / f"config.{s}").write_text("export A=1")
    for i in range(n_resource):
        (exp_dir / f"config.resources.PLAT{i}").write_text("export N=1")

    exp = discover_experiments(base)[0]
    db = RecordingDB()
    asyncio.run(_ingest_experiment(db, "GW_V17_", exp, FakeTenant(), _report()))

    rf = [c for c in db.calls if "RESOLVES_FROM" in c["cypher"]]
    targets = {c["params"]["short_name"] for c in rf}
    # exactly the non-resource short names, never a resources.* file
    assert targets == set(short_names)


# ════════════════════════════════════════════════════════════════════════
# P4 — Rocoto DAG completeness
# ════════════════════════════════════════════════════════════════════════


def _mk_task(name, deps):
    children = [{"type": "task", "name": d, "cycle_offset": None} for d in deps]
    tree = {"operator": "and", "children": children} if children else {}
    return {"name": name, "experiment": "C48", "command": "", "cycledefs": "",
            "maxtries": "1", "is_final": False, "resources": {}, "envars": {},
            "dependency_tree": tree, "data_dependencies": []}


@settings(max_examples=80, deadline=None)
@given(task_names=st.lists(st.from_regex(r"[a-z][a-z0-9]{0,5}", fullmatch=True),
                           unique=True, min_size=1, max_size=8),
       data=st.data())
def test_p4_dag_completeness(task_names, data):
    tasks = []
    total_deps = 0
    for name in task_names:
        others = [n for n in task_names if n != name]
        deps = data.draw(st.lists(st.sampled_from(others), unique=True,
                                  max_size=len(others))) if others else []
        total_deps += len(deps)
        tasks.append(_mk_task(name, deps))

    parsed = {"cycledefs": [], "tasks": tasks, "metatasks": []}
    db = RecordingDB()
    asyncio.run(_ingest_rocoto_workflow(db, "GW_V17_", parsed, "C48",
                                        FakeTenant(), _report(), []))
    node_merges = [c for c in db.cyphers() if "SET t.command" in c]
    depends_on = [c for c in db.cyphers() if "DEPENDS_ON" in c]
    assert len(node_merges) == len(task_names)
    assert len(depends_on) == total_deps


# ════════════════════════════════════════════════════════════════════════
# P5 — metatask hierarchy correctness
# ════════════════════════════════════════════════════════════════════════


def _mk_child(name):
    return {"name": name, "experiment": "C48", "command": "", "cycledefs": "",
            "maxtries": "1", "is_final": False, "resources": {}, "envars": {},
            "dependency_tree": {}, "data_dependencies": []}


@settings(max_examples=60, deadline=None)
@given(top=st.lists(st.from_regex(r"t[0-9]{1,3}", fullmatch=True), unique=True, max_size=5),
       nested=st.lists(st.from_regex(r"n[0-9]{1,3}", fullmatch=True), unique=True, max_size=5))
def test_p5_member_of_matches_child_count(top, nested):
    mt = {"name": "lvl1", "mode": "parallel", "variables": {"m": ["1", "2"]},
          "tasks": [_mk_child(n) for n in top],
          "nested_metatasks": [
              {"name": "lvl2", "mode": "serial", "variables": {},
               "tasks": [_mk_child(n) for n in nested], "nested_metatasks": []}
          ]}
    db = RecordingDB()
    asyncio.run(_write_metatask(db, "GW_V17_", mt, "C48", FakeTenant(), _report()))
    member_of = [c for c in db.cyphers() if "MEMBER_OF" in c]
    assert len(member_of) == len(top) + len(nested)


# ════════════════════════════════════════════════════════════════════════
# P6 — idempotence (deterministic + all writes use MERGE)
# ════════════════════════════════════════════════════════════════════════


@settings(max_examples=60)
@given(names=st.lists(_VAR_NAME, unique=True, max_size=8))
def test_p6_idempotent_merge_writes(names):
    parsed = {"env_vars": [{"name": n, "default_value": "v", "is_default": False}
                           for n in names]}
    cfg = {"filename": "config.fcst", "system": "gfs", "rel_path": "p", "abs_path": "p"}

    def run_once():
        db = RecordingDB()
        asyncio.run(_write_config_node(db, "GW_V17_", cfg,
                                       {**parsed, "line_count": 0}, FakeTenant()))
        asyncio.run(_write_sets_env_edges(db, "GW_V17_", cfg, parsed))
        return [(c["cypher"],
                 tuple(sorted((k, v) for k, v in (c["params"] or {}).items()
                              if k != "updated_at")))
                for c in db.calls]

    run1, run2 = run_once(), run_once()
    assert run1 == run2                                  # deterministic
    assert all("MERGE" in cypher for cypher, _ in run1)  # MERGE semantics


# ════════════════════════════════════════════════════════════════════════
# P7 — tenant isolation
# ════════════════════════════════════════════════════════════════════════


@settings(max_examples=60)
@given(pa=st.from_regex(r"[A-Z][A-Z0-9]{1,5}_", fullmatch=True),
       pb=st.from_regex(r"[A-Z][A-Z0-9]{1,5}_", fullmatch=True))
def test_p7_label_sets_disjoint(pa, pb):
    if pa == pb:
        return
    cfg = {"filename": "config.fcst", "system": "gfs", "rel_path": "p"}
    parsed = {"env_vars": [{"name": "FOO", "default_value": "x", "is_default": False}],
              "line_count": 0}

    def labels_for(prefix):
        db = RecordingDB()
        asyncio.run(_write_config_node(db, prefix, cfg, parsed, FakeTenant()))
        asyncio.run(_write_sets_env_edges(db, prefix, cfg, parsed))
        out = set()
        for c in db.cyphers():
            out.update(_LABELS.findall(c))
        return out

    la, lb = labels_for(pa), labels_for(pb)
    assert la and lb
    assert la.isdisjoint(lb)
