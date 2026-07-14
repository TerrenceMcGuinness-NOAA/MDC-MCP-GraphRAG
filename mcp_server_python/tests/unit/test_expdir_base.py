"""Unit tests for tenant-derived EXPDIR base resolution.

rag-data-plane-gap-closure Task 9.5 / R15.3, R15.4: resolve_expdir_base is
per-tenant, honors MCP_EXPDIR_BASE_OVERRIDE, and returns None (skip signal) for
a tenant with no materialized EXPDIR — never another tenant's tree.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from ingest_expdir_configs_v8 import resolve_expdir_base  # noqa: E402


@dataclass
class _T:
    tenant_id: str


def test_override_existing_dir_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_EXPDIR_BASE_OVERRIDE", str(tmp_path))
    # Override wins for ANY tenant, even an unmapped one.
    assert resolve_expdir_base(_T("gw_sfs")) == tmp_path


def test_override_nonexistent_dir_returns_none(monkeypatch):
    monkeypatch.setenv("MCP_EXPDIR_BASE_OVERRIDE", "/no/such/expdir/path")
    assert resolve_expdir_base(_T("gw")) is None


def test_unmapped_tenant_returns_none(monkeypatch):
    monkeypatch.delenv("MCP_EXPDIR_BASE_OVERRIDE", raising=False)
    assert resolve_expdir_base(_T("gw_sfs")) is None
    assert resolve_expdir_base(_T("gw_jedi_gfs")) is None
    assert resolve_expdir_base(_T("gw_gefs_v12")) is None


def test_mapped_tenants_use_distinct_trees(monkeypatch):
    monkeypatch.delenv("MCP_EXPDIR_BASE_OVERRIDE", raising=False)
    gw = resolve_expdir_base(_T("gw"))
    v17 = resolve_expdir_base(_T("gw_v17"))
    # On COTS both trees are materialized; assert the per-tenant basenames when
    # present (never cross-fall-back to the same tree).
    if gw is not None:
        assert gw.name == "EXPDIR"
    if v17 is not None:
        assert v17.name == "EXPDIR_v17"
    if gw is not None and v17 is not None:
        assert gw != v17
