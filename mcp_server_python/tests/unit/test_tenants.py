"""Unit tests for the configurable workflow mount base (Phase 61).

Covers :pyattr:`src.config.tenants.Tenant.workflow_root` and its
``MCP_WORKFLOW_MOUNT`` override:

* default base is ``/mnt/workflow`` (AgentCore EFS — R2.7 preserved)
* ``MCP_WORKFLOW_MOUNT`` override changes the resolved root
* the ``workflow_subdir`` is always appended to the base
* unsetting the env var restores the default
"""

from __future__ import annotations

from pathlib import Path

from src.config.tenants import Tenant


def _make_tenant(workflow_subdir: str = "develop") -> Tenant:
    return Tenant(
        tenant_id="gw",
        repo_ref="NOAA-EMC/global-workflow",
        branch="develop",
        index_prefix="",
        label_prefix="",
        workflow_subdir=workflow_subdir,
        lifecycle="production",
    )


def test_workflow_root_defaults_to_efs_mount(monkeypatch):
    monkeypatch.delenv("MCP_WORKFLOW_MOUNT", raising=False)
    t = _make_tenant("develop")
    assert t.workflow_root == Path("/mnt/workflow/develop")


def test_workflow_root_honours_env_override(monkeypatch):
    monkeypatch.setenv("MCP_WORKFLOW_MOUNT", "/tmp/pw_mount")
    t = _make_tenant("dev-v17")
    assert t.workflow_root == Path("/tmp/pw_mount/dev-v17")


def test_workflow_root_appends_subdir_under_override(monkeypatch):
    monkeypatch.setenv("MCP_WORKFLOW_MOUNT", "/data/wf")
    for subdir in ("develop", "dev-sfs", "dev-jedi-gfs", "dev-v17", "gefs-v12"):
        t = _make_tenant(subdir)
        assert t.workflow_root == Path("/data/wf") / subdir


def test_workflow_root_restores_default_after_unset(monkeypatch):
    monkeypatch.setenv("MCP_WORKFLOW_MOUNT", "/tmp/override")
    t = _make_tenant("develop")
    assert t.workflow_root == Path("/tmp/override/develop")
    monkeypatch.delenv("MCP_WORKFLOW_MOUNT", raising=False)
    assert t.workflow_root == Path("/mnt/workflow/develop")
