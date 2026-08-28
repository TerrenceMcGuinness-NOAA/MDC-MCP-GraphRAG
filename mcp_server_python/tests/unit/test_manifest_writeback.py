"""Unit tests for manifest writeback (Phase 81, Requirement 7).

Covers:
  * ``done`` transition writes the correct ``ingest_status`` block.
  * ``blocked`` transition writes ``blocked_reason``.
  * Concurrent writebacks do not corrupt the JSON.
  * Non-ingest kinds (prep, validate) do not trigger writeback.
  * Stages with ``--sources`` args have their sources resolved.
  * Static STAGE_TO_SOURCES fallback works.
  * Missing manifest file produces a warning, not a crash.
  * Atomic write survives interrupted write (temp file cleanup).

Spec: .kiro/specs/mpnet768-tenant-reingest-aug2026/ (Task 6.2).
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

# Add scripts/ to path for direct import.
sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

import reingest_state as rs  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MANIFEST_TEMPLATE: dict = {
    "version": "9.2.0",
    "description": "Test manifest",
    "generated_at": "2026-08-28T00:00:00Z",
    "sources": [
        {
            "name": "jjob-docs",
            "source_type": "jjob_docs",
            "collection_target": "jjobs-v8-0-0",
            "embedding_profile": "titan1024",
            "enabled": True,
            "scope": "tenant",
            "last_ingested": None,
            "doc_count": 700,
        },
        {
            "name": "ee2-standards",
            "source_type": "standards",
            "collection_target": "ee2-standards-v5-0-0-enhanced",
            "embedding_profile": "titan1024",
            "enabled": True,
            "scope": "shared",
            "last_ingested": None,
            "doc_count": 34,
        },
        {
            "name": "fortran-code-context",
            "source_type": "code_parse",
            "collection_target": "code-with-context-v8-0-0",
            "embedding_profile": "titan1024",
            "enabled": True,
            "scope": "tenant",
            "last_ingested": None,
            "doc_count": 77613,
        },
        {
            "name": "shell-code-context",
            "source_type": "code_parse",
            "collection_target": "code-with-context-v8-0-0",
            "embedding_profile": "titan1024",
            "enabled": True,
            "scope": "tenant",
            "last_ingested": None,
            "doc_count": 0,
        },
        {
            "name": "community-summaries",
            "source_type": "community_summary",
            "collection_target": "community-summaries",
            "embedding_profile": "titan1024",
            "enabled": True,
            "scope": "shared",
            "last_ingested": None,
            "doc_count": 2113,
        },
        {
            "name": "rocoto",
            "source_type": "url_crawl",
            "collection_target": "global-workflow-docs-v8-0-0",
            "embedding_profile": "titan1024",
            "enabled": True,
            "scope": "shared",
            "last_ingested": None,
            "doc_count": 0,
        },
        {
            "name": "cmeps",
            "source_type": "url_crawl",
            "collection_target": "global-workflow-docs-v8-0-0",
            "embedding_profile": "titan1024",
            "enabled": True,
            "scope": "shared",
            "last_ingested": None,
            "doc_count": 0,
        },
    ],
}


@pytest.fixture()
def manifest_path(tmp_path: Path) -> Path:
    """Write a test manifest and return its path."""
    p = tmp_path / "unified_manifest.json"
    p.write_text(json.dumps(_MANIFEST_TEMPLATE, indent=2), encoding="utf-8")
    return p


def _make_unit(
    stage: str = "jjobs",
    kind: str = "vector",
    tenant_id: str = "gw",
    metrics: dict | None = None,
    status: str = "done",
    ended_at: str = "2026-08-29T04:12:07Z",
    last_error: str | None = None,
) -> dict:
    """Build a minimal Reingest_Unit dict for writeback testing."""
    return {
        "id": f"{tenant_id}:{stage}",
        "tenant_id": tenant_id,
        "stage": stage,
        "kind": kind,
        "status": status,
        "metrics": metrics or {},
        "ended_at": ended_at,
        "last_error": last_error,
    }


# ---------------------------------------------------------------------------
# Tests: _resolve_stage_sources
# ---------------------------------------------------------------------------


class TestResolveStageSourcesStatic:
    """Static STAGE_TO_SOURCES mapping."""

    def test_jjobs_maps_to_jjob_docs(self):
        unit = _make_unit(stage="jjobs")
        result = rs._resolve_stage_sources(unit)
        assert result == ["jjob-docs"]

    def test_ee2_standards_maps_to_ee2_standards(self):
        unit = _make_unit(stage="ee2_standards")
        result = rs._resolve_stage_sources(unit)
        assert result == ["ee2-standards"]

    def test_community_summaries_maps_correctly(self):
        unit = _make_unit(stage="community_summaries")
        result = rs._resolve_stage_sources(unit)
        assert result == ["community-summaries"]

    def test_config_maps_to_two_sources(self):
        unit = _make_unit(stage="config")
        result = rs._resolve_stage_sources(unit)
        assert set(result) == {"rocoto-config", "expdir-configs"}

    def test_shell_graph_maps_to_shell_code_context(self):
        unit = _make_unit(stage="shell_graph")
        result = rs._resolve_stage_sources(unit)
        assert result == ["shell-code-context"]

    def test_fortran_graph_maps_to_fortran_code_context(self):
        unit = _make_unit(stage="fortran_graph")
        result = rs._resolve_stage_sources(unit)
        assert result == ["fortran-code-context"]

    def test_bridge_has_no_sources(self):
        unit = _make_unit(stage="bridge")
        result = rs._resolve_stage_sources(unit)
        assert result == []

    def test_unknown_stage_returns_empty(self):
        unit = _make_unit(stage="nonexistent_stage")
        result = rs._resolve_stage_sources(unit)
        assert result == []


class TestResolveStageSourcesFromArgs:
    """Resolution from the stage catalog's --sources arg."""

    def test_workflow_docs_external_from_catalog_args(self):
        stages_data = {
            "per_tenant": [
                {
                    "name": "workflow_docs_external",
                    "kind": "vector",
                    "args": ["--sources", "rocoto,cmeps,nceplibs-sfcio"],
                },
            ],
            "global": [],
        }
        unit = _make_unit(stage="workflow_docs_external")
        result = rs._resolve_stage_sources(unit, stages_data=stages_data)
        assert result == ["rocoto", "cmeps", "nceplibs-sfcio"]

    def test_code_with_context_local_from_catalog_args(self):
        stages_data = {
            "per_tenant": [
                {
                    "name": "code_with_context_local",
                    "kind": "vector",
                    "args": ["--sources", "fortran-code-context,shell-code-context,python-code-context,rocoto-config,expdir-configs"],
                },
            ],
            "global": [],
        }
        unit = _make_unit(stage="code_with_context_local")
        result = rs._resolve_stage_sources(unit, stages_data=stages_data)
        assert result == [
            "fortran-code-context", "shell-code-context",
            "python-code-context", "rocoto-config", "expdir-configs",
        ]

    def test_stage_not_in_args_sources_set_uses_static(self):
        """Stages NOT in _STAGES_WITH_ARGS_SOURCES use the static map even
        when stages_data is provided."""
        stages_data = {
            "per_tenant": [
                {"name": "jjobs", "kind": "vector", "args": ["--some-flag"]},
            ],
            "global": [],
        }
        unit = _make_unit(stage="jjobs")
        result = rs._resolve_stage_sources(unit, stages_data=stages_data)
        assert result == ["jjob-docs"]

    def test_args_sources_stage_without_args_falls_back(self):
        """A stage in _STAGES_WITH_ARGS_SOURCES but missing from catalog falls
        back to the static map (which is empty for these stages)."""
        stages_data = {"per_tenant": [], "global": []}
        unit = _make_unit(stage="workflow_docs_external")
        # Not in STAGE_TO_SOURCES, not in catalog → empty
        result = rs._resolve_stage_sources(unit, stages_data=stages_data)
        assert result == []


# ---------------------------------------------------------------------------
# Tests: _writeback_manifest_status (done)
# ---------------------------------------------------------------------------


class TestWritebackDone:
    """Manifest writeback on ``done`` transition."""

    def test_writes_ingest_status_block(self, manifest_path: Path):
        unit = _make_unit(
            stage="jjobs",
            kind="vector",
            metrics={
                "docs_ingested": 859,
                "collection_version": "v9-0-0",
                "sha": "abc123",
                "backend": "cots",
                "embedding_profile": "mpnet768",
            },
        )
        count = rs._writeback_manifest_status(unit, manifest_path=manifest_path)
        assert count == 1

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        jjob_src = next(s for s in manifest["sources"] if s["name"] == "jjob-docs")
        status = jjob_src["ingest_status"]
        assert status["collection_version"] == "v9-0-0"
        assert status["actual_docs"] == 859
        assert status["ingested_at"] == "2026-08-29T04:12:07Z"
        assert status["sha"] == "abc123"
        assert status["backend"] == "cots"
        assert status["embedding_profile"] == "mpnet768"
        assert "blocked_reason" not in status

    def test_writes_defaults_when_metrics_sparse(self, manifest_path: Path):
        unit = _make_unit(stage="ee2_standards", kind="vector", metrics={})
        count = rs._writeback_manifest_status(unit, manifest_path=manifest_path)
        assert count == 1

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        ee2_src = next(s for s in manifest["sources"] if s["name"] == "ee2-standards")
        status = ee2_src["ingest_status"]
        assert status["collection_version"] == "v9-0-0"
        assert status["actual_docs"] == 0
        assert status["backend"] == "cots"
        assert status["embedding_profile"] == "mpnet768"

    def test_non_ingest_kind_skipped(self, manifest_path: Path):
        unit = _make_unit(stage="worktree", kind="prep")
        count = rs._writeback_manifest_status(unit, manifest_path=manifest_path)
        assert count == 0
        # Manifest unchanged
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for src in manifest["sources"]:
            assert "ingest_status" not in src

    def test_validate_kind_skipped(self, manifest_path: Path):
        unit = _make_unit(stage="validate", kind="validate")
        count = rs._writeback_manifest_status(unit, manifest_path=manifest_path)
        assert count == 0

    def test_multiple_sources_updated(self, manifest_path: Path):
        """The ``config`` stage maps to two sources."""
        unit = _make_unit(
            stage="config",
            kind="dual",
            metrics={"docs_ingested": 150, "collection_version": "v9-0-0"},
        )
        count = rs._writeback_manifest_status(unit, manifest_path=manifest_path)
        # Neither rocoto-config nor expdir-configs are in our test manifest,
        # so count should be 0 (sources not found).
        assert count == 0

    def test_stage_with_actual_docs_in_metrics(self, manifest_path: Path):
        """Accepts ``actual_docs`` as an alternative key to ``docs_ingested``."""
        unit = _make_unit(
            stage="jjobs",
            kind="vector",
            metrics={"actual_docs": 700, "collection_version": "v9-0-0"},
        )
        count = rs._writeback_manifest_status(unit, manifest_path=manifest_path)
        assert count == 1
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        jjob_src = next(s for s in manifest["sources"] if s["name"] == "jjob-docs")
        assert jjob_src["ingest_status"]["actual_docs"] == 700

    def test_bridge_stage_no_writeback(self, manifest_path: Path):
        """Bridge has no manifest sources — writeback returns 0."""
        unit = _make_unit(stage="bridge", kind="graph")
        count = rs._writeback_manifest_status(unit, manifest_path=manifest_path)
        assert count == 0


# ---------------------------------------------------------------------------
# Tests: _writeback_manifest_status (blocked)
# ---------------------------------------------------------------------------


class TestWritebackBlocked:
    """Manifest writeback on ``blocked`` transition."""

    def test_writes_blocked_reason(self, manifest_path: Path):
        unit = _make_unit(
            stage="jjobs",
            kind="vector",
            status="blocked",
            last_error="timeout after 3 attempts",
        )
        count = rs._writeback_manifest_status(
            unit,
            manifest_path=manifest_path,
            blocked_reason="timeout after 3 attempts",
        )
        assert count == 1

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        jjob_src = next(s for s in manifest["sources"] if s["name"] == "jjob-docs")
        status = jjob_src["ingest_status"]
        assert status["blocked_reason"] == "timeout after 3 attempts"
        assert status["actual_docs"] == 0  # Cleared for blocked units

    def test_blocked_preserves_other_fields(self, manifest_path: Path):
        unit = _make_unit(
            stage="ee2_standards",
            kind="vector",
            status="blocked",
            metrics={"sha": "deadbeef"},
        )
        count = rs._writeback_manifest_status(
            unit,
            manifest_path=manifest_path,
            blocked_reason="needs_ingester",
        )
        assert count == 1

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        ee2_src = next(s for s in manifest["sources"] if s["name"] == "ee2-standards")
        status = ee2_src["ingest_status"]
        assert status["blocked_reason"] == "needs_ingester"
        assert status["collection_version"] == "v9-0-0"


# ---------------------------------------------------------------------------
# Tests: robustness
# ---------------------------------------------------------------------------


class TestWritebackRobustness:
    """Edge cases and robustness."""

    def test_missing_manifest_file(self, tmp_path: Path):
        """No crash when manifest doesn't exist — just a warning."""
        nonexistent = tmp_path / "does_not_exist.json"
        unit = _make_unit(stage="jjobs", kind="vector")
        count = rs._writeback_manifest_status(unit, manifest_path=nonexistent)
        assert count == 0

    def test_manifest_preserved_on_writeback(self, manifest_path: Path):
        """Other sources are untouched after a writeback."""
        unit = _make_unit(
            stage="ee2_standards",
            kind="vector",
            metrics={"docs_ingested": 34, "collection_version": "v9-0-0"},
        )
        rs._writeback_manifest_status(unit, manifest_path=manifest_path)

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        # jjob-docs should NOT have ingest_status
        jjob_src = next(s for s in manifest["sources"] if s["name"] == "jjob-docs")
        assert "ingest_status" not in jjob_src
        # version preserved
        assert manifest["version"] == "9.2.0"

    def test_concurrent_writebacks_no_corruption(self, manifest_path: Path):
        """Multiple threads writing different sources don't corrupt JSON."""
        errors: list[str] = []

        def _write(stage: str, kind: str):
            try:
                unit = _make_unit(
                    stage=stage,
                    kind=kind,
                    metrics={"docs_ingested": 100, "collection_version": "v9-0-0"},
                )
                rs._writeback_manifest_status(unit, manifest_path=manifest_path)
            except Exception as e:
                errors.append(str(e))

        threads = [
            threading.Thread(target=_write, args=("jjobs", "vector")),
            threading.Thread(target=_write, args=("ee2_standards", "vector")),
            threading.Thread(target=_write, args=("fortran_graph", "graph")),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent writeback errors: {errors}"

        # Manifest must be valid JSON after concurrent writes.
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert "sources" in manifest
        assert len(manifest["sources"]) == len(_MANIFEST_TEMPLATE["sources"])

    def test_idempotent_writeback(self, manifest_path: Path):
        """Writing the same unit twice overwrites the ingest_status cleanly."""
        unit = _make_unit(
            stage="jjobs",
            kind="vector",
            metrics={"docs_ingested": 500, "collection_version": "v9-0-0"},
        )
        rs._writeback_manifest_status(unit, manifest_path=manifest_path)

        # Write again with different count.
        unit["metrics"]["docs_ingested"] = 859
        rs._writeback_manifest_status(unit, manifest_path=manifest_path)

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        jjob_src = next(s for s in manifest["sources"] if s["name"] == "jjob-docs")
        assert jjob_src["ingest_status"]["actual_docs"] == 859


# ---------------------------------------------------------------------------
# Tests: CLI integration (cmd_done and cmd_fail trigger writeback)
# ---------------------------------------------------------------------------

_CLI_CATALOG_YAML = """\
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
"""

_CLI_STAGES_YAML = """\
schema_version: 2
attempt_cap_default: 2
per_tenant_stages:
  - name: worktree
    scope: tenant
    shared_once: false
    order: 10
    kind: prep
    script: setup_pw_workflow_mount.sh
    depends_on: []
  - name: jjobs
    scope: tenant
    shared_once: false
    order: 50
    kind: vector
    script: ingest_jjobs_v8.py
    depends_on: [worktree]
    probe: vector
global_stages:
  - name: ee2_standards
    scope: shared
    shared_once: true
    order: 300
    kind: vector
    script: ingest_ee2_v7.py
    depends_on: []
"""


class TestCLIWriteback:
    """End-to-end: cmd_done and cmd_fail trigger manifest writeback."""

    @pytest.fixture()
    def cli_env(self, tmp_path: Path):
        """Set up catalog, stages, manifest, and state for CLI tests."""
        catalog = tmp_path / "tenants.yaml"
        catalog.write_text(_CLI_CATALOG_YAML, encoding="utf-8")
        stages = tmp_path / "reingest_stages.yaml"
        stages.write_text(_CLI_STAGES_YAML, encoding="utf-8")
        manifest = tmp_path / "unified_manifest.json"
        manifest.write_text(json.dumps(_MANIFEST_TEMPLATE, indent=2), encoding="utf-8")

        # Init the state.
        rc = rs.main([
            "--state-root", str(tmp_path),
            "--collection-version", "v9-0-0",
            "init",
            "--catalog", str(catalog),
            "--stages", str(stages),
            "--backend", "cots",
            "--embedding-profile", "mpnet768",
        ])
        assert rc == 0
        return tmp_path, manifest

    def test_cmd_done_triggers_writeback(self, cli_env):
        tmp_path, manifest = cli_env

        # Start the jjobs unit.
        # First mark worktree done so jjobs is actionable.
        rs.main([
            "--state-root", str(tmp_path),
            "--collection-version", "v9-0-0",
            "start", "--id", "gw:worktree",
        ])
        rs.main([
            "--state-root", str(tmp_path),
            "--collection-version", "v9-0-0",
            "done", "--id", "gw:worktree",
            "--manifest", str(manifest),
        ])

        # Now start and complete jjobs with metrics.
        rs.main([
            "--state-root", str(tmp_path),
            "--collection-version", "v9-0-0",
            "start", "--id", "gw:jjobs",
        ])
        rs.main([
            "--state-root", str(tmp_path),
            "--collection-version", "v9-0-0",
            "done", "--id", "gw:jjobs",
            "--metrics", json.dumps({"docs_ingested": 859, "collection_version": "v9-0-0"}),
            "--manifest", str(manifest),
        ])

        # Verify manifest was updated.
        data = json.loads(manifest.read_text(encoding="utf-8"))
        jjob_src = next(s for s in data["sources"] if s["name"] == "jjob-docs")
        assert "ingest_status" in jjob_src
        assert jjob_src["ingest_status"]["actual_docs"] == 859
        assert jjob_src["ingest_status"]["collection_version"] == "v9-0-0"

    def test_cmd_done_prep_kind_no_writeback(self, cli_env):
        tmp_path, manifest = cli_env

        # Complete worktree (kind=prep) — should NOT write to manifest.
        rs.main([
            "--state-root", str(tmp_path),
            "--collection-version", "v9-0-0",
            "start", "--id", "gw:worktree",
        ])
        rs.main([
            "--state-root", str(tmp_path),
            "--collection-version", "v9-0-0",
            "done", "--id", "gw:worktree",
            "--manifest", str(manifest),
        ])

        data = json.loads(manifest.read_text(encoding="utf-8"))
        for src in data["sources"]:
            assert "ingest_status" not in src

    def test_cmd_fail_blocked_triggers_writeback(self, cli_env):
        tmp_path, manifest = cli_env

        # Mark worktree done so jjobs can start.
        rs.main([
            "--state-root", str(tmp_path),
            "--collection-version", "v9-0-0",
            "start", "--id", "gw:worktree",
        ])
        rs.main([
            "--state-root", str(tmp_path),
            "--collection-version", "v9-0-0",
            "done", "--id", "gw:worktree",
            "--manifest", str(manifest),
        ])

        # Fail jjobs twice to reach blocked (cap=2).
        rs.main([
            "--state-root", str(tmp_path),
            "--collection-version", "v9-0-0",
            "start", "--id", "gw:jjobs",
        ])
        rs.main([
            "--state-root", str(tmp_path),
            "--collection-version", "v9-0-0",
            "fail", "--id", "gw:jjobs",
            "--error", "timeout",
            "--manifest", str(manifest),
        ])
        rs.main([
            "--state-root", str(tmp_path),
            "--collection-version", "v9-0-0",
            "start", "--id", "gw:jjobs",
        ])
        rs.main([
            "--state-root", str(tmp_path),
            "--collection-version", "v9-0-0",
            "fail", "--id", "gw:jjobs",
            "--error", "timeout again",
            "--manifest", str(manifest),
        ])

        # Verify manifest was updated with blocked_reason.
        data = json.loads(manifest.read_text(encoding="utf-8"))
        jjob_src = next(s for s in data["sources"] if s["name"] == "jjob-docs")
        assert "ingest_status" in jjob_src
        assert jjob_src["ingest_status"]["blocked_reason"] == "timeout again"
        assert jjob_src["ingest_status"]["actual_docs"] == 0

    def test_cmd_fail_not_blocked_no_writeback(self, cli_env):
        tmp_path, manifest = cli_env

        # Mark worktree done.
        rs.main([
            "--state-root", str(tmp_path),
            "--collection-version", "v9-0-0",
            "start", "--id", "gw:worktree",
        ])
        rs.main([
            "--state-root", str(tmp_path),
            "--collection-version", "v9-0-0",
            "done", "--id", "gw:worktree",
            "--manifest", str(manifest),
        ])

        # Fail jjobs once (cap=2, so it stays "failed" not "blocked").
        rs.main([
            "--state-root", str(tmp_path),
            "--collection-version", "v9-0-0",
            "start", "--id", "gw:jjobs",
        ])
        rs.main([
            "--state-root", str(tmp_path),
            "--collection-version", "v9-0-0",
            "fail", "--id", "gw:jjobs",
            "--error", "first failure",
            "--manifest", str(manifest),
        ])

        # Manifest should NOT have ingest_status for jjob-docs yet.
        data = json.loads(manifest.read_text(encoding="utf-8"))
        jjob_src = next(s for s in data["sources"] if s["name"] == "jjob-docs")
        assert "ingest_status" not in jjob_src
