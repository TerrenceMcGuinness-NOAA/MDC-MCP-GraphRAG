"""Unit tests for reingest_state.py (the COTS re-ingest State_Manager).

Feature: cots-reingest-ralph-loop, Task 1.3 / Requirement 4.5.

Covers, against a ``tmp_path`` state file (pure state I/O, no network):
  * Work_Matrix build from a fixture catalog x stages.
  * ``next`` respects depends_on terminality + attempt cap.
  * attempt cap -> ``blocked`` (terminal); ``--requeue`` resets without penalty.
  * idempotent ``init`` preserves statuses and adds new tenants.
  * atomic write survives a simulated crash (temp file left, state intact).
  * ``is-complete`` exit codes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Add scripts/ to path for direct import (mirrors test_ingest_dedupe.py).
sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

import reingest_state as rs  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures — a minimal catalog + stage catalog on disk
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
    order: 10
    kind: prep
    script: setup_pw_workflow_mount.sh
    depends_on: []
  - name: reset
    order: 20
    kind: destructive
    script: reset_tenant_cots.py
    depends_on: [worktree]
    destructive: true
  - name: code
    order: 40
    kind: vector
    script: ingest_code_v8.py
    depends_on: [reset]
    probe: vector
  - name: validate
    order: 200
    kind: validate
    script: null
    depends_on: [code]
    probe: integrity
global_stages:
  - name: ee2_standards
    order: 300
    kind: vector
    script: ingest_ee2_v7.py
    depends_on: []
  - name: community_summaries
    order: 310
    kind: graph
    script: null
    depends_on: []
    optional: true
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
          cap=None, mode_override=None) -> int:
    argv = [
        "--state-root", str(state_root),
        "--collection-version", version,
        "init",
        "--catalog", str(catalog),
        "--stages", str(stages),
        "--backend", "cots",
        "--embedding-profile", "mpnet768",
    ]
    if cap is not None:
        argv += ["--attempt-cap", str(cap)]
    if mode_override:
        argv += ["--mode-override", mode_override]
    return rs.main(argv)


def _store(state_root: Path, version="v9-0-0") -> rs.StateStore:
    return rs.StateStore(rs._state_dir(state_root, version))


# ---------------------------------------------------------------------------
# Matrix build
# ---------------------------------------------------------------------------


def test_matrix_build(tmp_path, catalog_file, stages_file):
    rc = _init(tmp_path, catalog_file, stages_file)
    assert rc == 0
    store = _store(tmp_path)
    units = store.units()
    # 2 tenants x 4 per-tenant stages + 2 global = 10
    assert len(units) == 10
    ids = {u["id"] for u in units}
    assert "gw:worktree" in ids
    assert "gw_v17:validate" in ids
    assert "__global__:ee2_standards" in ids
    # Self-describing fields stamped (Requirement 2.2)
    v17_code = store.by_id("gw_v17:code")
    assert v17_code["branch"] == "dev/gfs.v17"
    assert v17_code["label_prefix"] == "GW_V17_"
    assert v17_code["mode"] == "full"          # staging -> full
    # Global unit has shared scope (Phase 81: "global" → "shared" terminology)
    assert store.by_id("__global__:ee2_standards")["scope"] == "shared"


def test_mode_derivation_experimental_diff(tmp_path, stages_file):
    # A catalog whose tenant is experimental -> diff mode
    cat = tmp_path / "c.yaml"
    cat.write_text(_CATALOG_YAML.replace("lifecycle: staging", "lifecycle: experimental"),
                   encoding="utf-8")
    _init(tmp_path, cat, stages_file)
    assert _store(tmp_path).by_id("gw_v17:code")["mode"] == "diff"


def test_mode_override_forces_full(tmp_path, catalog_file, stages_file):
    cat = tmp_path / "c.yaml"
    cat.write_text(_CATALOG_YAML.replace("lifecycle: production", "lifecycle: experimental"),
                   encoding="utf-8")
    _init(tmp_path, cat, stages_file, mode_override="full")
    assert _store(tmp_path).by_id("gw:code")["mode"] == "full"


# ---------------------------------------------------------------------------
# next — dependency gating + ordering
# ---------------------------------------------------------------------------


def test_next_returns_lowest_order_worktree(tmp_path, catalog_file, stages_file):
    _init(tmp_path, catalog_file, stages_file)
    unit = _store(tmp_path).next_unit()
    assert unit["stage"] == "worktree"
    assert unit["tenant_id"] == "gw"           # first tenant in catalog order


def test_next_gates_on_depends_on(tmp_path, catalog_file, stages_file):
    _init(tmp_path, catalog_file, stages_file)
    store = _store(tmp_path)
    # code depends_on reset; reset depends_on worktree. Until worktree+reset are
    # terminal for gw, gw:code must never be returned.
    actionable_ids = {u["id"] for u in store.actionable()}
    assert "gw:code" not in actionable_ids
    assert "gw:reset" not in actionable_ids     # its dep (worktree) not terminal
    assert "gw:worktree" in actionable_ids


def test_next_unblocks_after_deps_terminal(tmp_path, catalog_file, stages_file):
    _init(tmp_path, catalog_file, stages_file)
    store = _store(tmp_path)
    # Mark gw worktree done and reset skipped -> gw:code becomes actionable.
    for uid, status in (("gw:worktree", "done"), ("gw:reset", "skipped")):
        store.by_id(uid)["status"] = status
    store.save()
    store2 = _store(tmp_path)
    actionable_ids = {u["id"] for u in store2.actionable()}
    assert "gw:code" in actionable_ids


def test_skip_is_terminal_for_deps(tmp_path, catalog_file, stages_file):
    _init(tmp_path, catalog_file, stages_file)
    store = _store(tmp_path)
    store.by_id("gw:worktree")["status"] = "skipped"
    store.save()
    actionable_ids = {u["id"] for u in _store(tmp_path).actionable()}
    assert "gw:reset" in actionable_ids


# ---------------------------------------------------------------------------
# fail / attempt cap -> blocked, requeue
# ---------------------------------------------------------------------------


def test_attempt_cap_marks_blocked(tmp_path, catalog_file, stages_file):
    _init(tmp_path, catalog_file, stages_file, cap=2)
    base = ["--state-root", str(tmp_path), "--collection-version", "v9-0-0"]
    # First fail -> failed (attempts=1)
    assert rs.main(base + ["fail", "--id", "gw:worktree", "--error", "boom"]) == 0
    assert _store(tmp_path).by_id("gw:worktree")["status"] == "failed"
    assert _store(tmp_path).by_id("gw:worktree")["attempts"] == 1
    # Second fail -> blocked (attempts=2 == cap)
    assert rs.main(base + ["fail", "--id", "gw:worktree", "--error", "boom2"]) == 0
    u = _store(tmp_path).by_id("gw:worktree")
    assert u["status"] == "blocked"
    assert u["attempts"] == 2
    # blocked is terminal -> not actionable
    assert "gw:worktree" not in {a["id"] for a in _store(tmp_path).actionable()}


def test_requeue_does_not_increment_attempts(tmp_path, catalog_file, stages_file):
    _init(tmp_path, catalog_file, stages_file, cap=3)
    base = ["--state-root", str(tmp_path), "--collection-version", "v9-0-0"]
    rs.main(base + ["fail", "--id", "gw:worktree", "--error", "e1"])
    assert _store(tmp_path).by_id("gw:worktree")["attempts"] == 1
    # requeue with an adaptation note -> pending, attempts unchanged
    rs.main(base + ["fail", "--id", "gw:worktree", "--error", "e2",
                    "--requeue", "--note", "fixed the path"])
    u = _store(tmp_path).by_id("gw:worktree")
    assert u["status"] == "pending"
    assert u["attempts"] == 1
    assert u["adaptations"] and u["adaptations"][0]["note"] == "fixed the path"


# ---------------------------------------------------------------------------
# start / done / skip lifecycle
# ---------------------------------------------------------------------------


def test_done_merges_metrics(tmp_path, catalog_file, stages_file):
    _init(tmp_path, catalog_file, stages_file)
    base = ["--state-root", str(tmp_path), "--collection-version", "v9-0-0"]
    rs.main(base + ["start", "--id", "gw:worktree"])
    assert _store(tmp_path).by_id("gw:worktree")["status"] == "running"
    rs.main(base + ["done", "--id", "gw:worktree", "--metrics", '{"files": 1234}'])
    u = _store(tmp_path).by_id("gw:worktree")
    assert u["status"] == "done"
    assert u["metrics"]["files"] == 1234
    assert u["ended_at"] is not None


def test_skip_records_reason(tmp_path, catalog_file, stages_file):
    _init(tmp_path, catalog_file, stages_file)
    base = ["--state-root", str(tmp_path), "--collection-version", "v9-0-0"]
    rs.main(base + ["skip", "--id", "gw_v17:code", "--reason", "no sorc submodules"])
    u = _store(tmp_path).by_id("gw_v17:code")
    assert u["status"] == "skipped"
    assert u["skip_reason"] == "no sorc submodules"


# ---------------------------------------------------------------------------
# idempotent re-init
# ---------------------------------------------------------------------------


def test_reinit_preserves_status_and_adds_new_tenant(tmp_path, catalog_file, stages_file):
    _init(tmp_path, catalog_file, stages_file)
    base = ["--state-root", str(tmp_path), "--collection-version", "v9-0-0"]
    rs.main(base + ["done", "--id", "gw:worktree", "--metrics", '{"files": 7}'])

    # Add a third tenant to the catalog and re-init.
    extended = _CATALOG_YAML + """\
  - tenant_id: gw_sfs
    repo_ref: NOAA-EMC/global-workflow
    branch: dev/sfs
    index_prefix: "gw_sfs_"
    label_prefix: "GW_SFS_"
    workflow_subdir: dev-sfs
    lifecycle: experimental
"""
    catalog_file.write_text(extended, encoding="utf-8")
    rc = _init(tmp_path, catalog_file, stages_file)
    assert rc == 0

    store = _store(tmp_path)
    # Preserved status for pre-existing unit
    gw_wt = store.by_id("gw:worktree")
    assert gw_wt["status"] == "done"
    assert gw_wt["metrics"]["files"] == 7
    # New tenant's units added
    assert store.by_id("gw_sfs:code") is not None
    # 3 tenants x 4 + 2 global = 14
    assert len(store.units()) == 14


def test_reinit_warns_on_stages_drift(tmp_path, catalog_file, stages_file, capsys):
    _init(tmp_path, catalog_file, stages_file)
    # Mutate the stages file (append a comment -> different sha) and re-init.
    stages_file.write_text(_STAGES_YAML + "\n# drift\n", encoding="utf-8")
    _init(tmp_path, catalog_file, stages_file)
    err = capsys.readouterr().err
    assert "reingest_stages.yaml changed" in err


# ---------------------------------------------------------------------------
# atomic write + is-complete
# ---------------------------------------------------------------------------


def test_atomic_write_leaves_no_partial_and_valid_json(tmp_path, catalog_file, stages_file):
    _init(tmp_path, catalog_file, stages_file)
    state_dir = rs._state_dir(tmp_path, "v9-0-0")
    # No leftover temp files after a clean write.
    leftovers = list(state_dir.glob(".state.*.tmp"))
    assert leftovers == []
    # state.json is valid JSON.
    data = json.loads((state_dir / "state.json").read_text())
    assert data["schema_version"] == rs.SCHEMA_VERSION
    assert data["collection_version"] == "v9-0-0"


def test_atomic_write_survives_simulated_crash(tmp_path, catalog_file, stages_file, monkeypatch):
    _init(tmp_path, catalog_file, stages_file)
    store = _store(tmp_path)
    store.load()
    good = (store.state_dir / "state.json").read_text()

    # Simulate a crash during the rename step: os.replace raises after the temp
    # file was written. The original state.json must be untouched.
    real_replace = rs.os.replace

    def _boom(src, dst):
        raise OSError("simulated crash mid-rename")

    monkeypatch.setattr(rs.os, "replace", _boom)
    store.by_id("gw:worktree")["status"] = "running"
    with pytest.raises(OSError):
        store.save()
    monkeypatch.setattr(rs.os, "replace", real_replace)

    # Original state.json is intact and still valid.
    after = (store.state_dir / "state.json").read_text()
    assert after == good
    # The failed write cleaned up its temp file.
    assert list(store.state_dir.glob(".state.*.tmp")) == []


def test_is_complete_exit_codes(tmp_path, catalog_file, stages_file):
    _init(tmp_path, catalog_file, stages_file)
    base = ["--state-root", str(tmp_path), "--collection-version", "v9-0-0"]
    assert rs.main(base + ["is-complete"]) == 1     # nothing terminal yet
    # Drive every unit terminal (done or skipped).
    store = _store(tmp_path)
    for u in store.units():
        u["status"] = "skipped" if u["optional"] else "done"
    store.save()
    assert rs.main(base + ["is-complete"]) == 0


# ---------------------------------------------------------------------------
# Scope-aware Work_Matrix (rag-data-plane-gap-closure R2)
# ---------------------------------------------------------------------------

# Stages with an explicit scope: a per-tenant stage tagged shared
# (documentation) must collapse to ONE __global__ unit; tenant stages
# still fan out per tenant.
_SCOPED_STAGES_YAML = """\
schema_version: 1
attempt_cap_default: 3
per_tenant_stages:
  - name: worktree
    scope: tenant
    order: 10
    kind: prep
    script: setup_pw_workflow_mount.sh
    depends_on: []
  - name: documentation
    scope: shared
    order: 30
    kind: vector
    script: ingest_documentation_v8.py
    depends_on: []
    probe: vector
  - name: code
    scope: tenant
    order: 40
    kind: vector
    script: ingest_code_v8.py
    depends_on: [worktree]
    probe: vector
global_stages:
  - name: ee2_standards
    scope: shared
    order: 300
    kind: vector
    script: ingest_ee2_v7.py
    depends_on: []
"""


@pytest.fixture()
def scoped_stages_file(tmp_path: Path) -> Path:
    p = tmp_path / "scoped_stages.yaml"
    p.write_text(_SCOPED_STAGES_YAML, encoding="utf-8")
    return p


def test_shared_stage_emits_single_global_unit(tmp_path, catalog_file, scoped_stages_file):
    """A per-tenant stage tagged scope: shared yields one __global__ unit (R2.1)."""
    _init(tmp_path, catalog_file, scoped_stages_file)
    store = _store(tmp_path)
    units = store.units()
    # 2 tenants: worktree x2 + code x2 (tenant) + documentation x1 + ee2 x1 (shared) = 6
    assert len(units) == 6
    doc_units = [u for u in units if u["stage"] == "documentation"]
    assert len(doc_units) == 1
    assert doc_units[0]["id"] == "__global__:documentation"
    assert doc_units[0]["tenant_id"] == "__global__"
    # No per-tenant documentation units leaked.
    assert store.by_id("gw:documentation") is None
    assert store.by_id("gw_v17:documentation") is None
    # Tenant stages still fan out.
    assert store.by_id("gw:code") is not None
    assert store.by_id("gw_v17:code") is not None


def test_production_matrix_is_67_units(tmp_path):
    """The real catalog x stages yields exactly 60 tenant + 7 shared = 67 (Phase 81).

    Per-tenant stages (12 × 5 tenants = 60):
      worktree, reset, workflow_docs_local, code_with_context_local, jjobs,
      config, shell_graph, fortran_graph, expdir, rocoto, bridge, validate.

    Shared-once stages (7):
      neo4j_drop_indexes, workflow_docs_external, pdf_sources, ee2_standards,
      community_summaries, ci_test_cases, neo4j_rebuild_indexes.
    """
    _init(tmp_path, Path(rs._DEFAULT_CATALOG), Path(rs._DEFAULT_STAGES))
    store = _store(tmp_path)
    units = store.units()
    tenant_units = [u for u in units if u["tenant_id"] != rs.GLOBAL_TENANT]
    shared_units = [u for u in units if u["tenant_id"] == rs.GLOBAL_TENANT]
    assert len(units) == 67
    assert len(tenant_units) == 60
    assert len(shared_units) == 7
    shared_stages = sorted(u["stage"] for u in shared_units)
    assert shared_stages == [
        "ci_test_cases",
        "community_summaries",
        "ee2_standards",
        "neo4j_drop_indexes",
        "neo4j_rebuild_indexes",
        "pdf_sources",
        "workflow_docs_external",
    ]


def test_migration_preserves_terminal_and_collapses_documentation(
    tmp_path, catalog_file
):
    """Re-init from a pre-scope (per-tenant documentation) state collapses the
    per-tenant documentation units to one shared unit while preserving terminal
    statuses of surviving units (R2.3, R2.4)."""
    # Pre-scope stages: documentation is per-tenant (no scope → tenant default).
    pre = tmp_path / "pre_stages.yaml"
    pre.write_text(
        _SCOPED_STAGES_YAML.replace(
            "  - name: documentation\n    scope: shared\n",
            "  - name: documentation\n",
        ),
        encoding="utf-8",
    )
    _init(tmp_path, catalog_file, pre)
    store = _store(tmp_path)
    # Two per-tenant documentation units exist pre-migration.
    assert store.by_id("gw:documentation") is not None
    assert store.by_id("gw_v17:documentation") is not None
    # Drive a non-documentation unit terminal + one doc unit terminal.
    store.by_id("gw:worktree")["status"] = "done"
    store.by_id("gw_v17:documentation")["status"] = "done"
    store.save()

    # Re-init with the scoped stages (documentation now shared).
    scoped = tmp_path / "scoped_stages.yaml"
    scoped.write_text(_SCOPED_STAGES_YAML, encoding="utf-8")
    _init(tmp_path, catalog_file, scoped)

    store2 = _store(tmp_path)
    # Surviving terminal status preserved.
    assert store2.by_id("gw:worktree")["status"] == "done"
    # Documentation collapsed to one shared unit (per-tenant ones gone).
    doc_units = [u for u in store2.units() if u["stage"] == "documentation"]
    assert len(doc_units) == 1
    assert doc_units[0]["id"] == "__global__:documentation"
    assert store2.by_id("gw:documentation") is None
    assert store2.by_id("gw_v17:documentation") is None
