"""Unit tests for ingestion CLI surfaces (--tenant, --mode resolution).

Feature: omd-tenants-2-v17-pilot, Requirements 3.1, 3.2
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from _ingest_common import (
    build_ingestion_parser,
    derive_mode_from_lifecycle,
    resolve_tenant_and_mode,
)


@dataclass(frozen=True)
class _FakeTenant:
    tenant_id: str
    repo_ref: str = "NOAA-EMC/global-workflow"
    branch: str = "develop"
    index_prefix: str = ""
    label_prefix: str = ""
    workflow_subdir: str = "develop"
    lifecycle: str = "production"
    description: str = ""
    extends: tuple = ()
    staleness_threshold_days: int | None = None

    @property
    def workflow_root(self) -> Path:
        return Path("/mnt/workflow") / self.workflow_subdir


class _FakeCatalog:
    def __init__(self, tenants: list[_FakeTenant]):
        self._tenants = {t.tenant_id: t for t in tenants}
        self.tenant_ids = list(self._tenants.keys())

    @property
    def defaults(self):
        class D:
            tenant_id = "gw"
        return D()

    def by_id(self, tid):
        return self._tenants.get(tid)


_GW = _FakeTenant(tenant_id="gw", lifecycle="production")
_GW_V17 = _FakeTenant(
    tenant_id="gw_v17", branch="dev/gfs.v17",
    index_prefix="gw_v17_", label_prefix="GW_V17_",
    workflow_subdir="dev-v17", lifecycle="staging",
)
_CATALOG = _FakeCatalog([_GW, _GW_V17])


class TestResolveUnknownTenant:
    """--tenant <unknown> → SystemExit with known-IDs hint."""

    def test_unknown_tenant_exits(self):
        parser = build_ingestion_parser("test")
        args = parser.parse_args(["--tenant", "nonexistent"])
        with pytest.raises(SystemExit) as exc_info:
            resolve_tenant_and_mode(args, _CATALOG)
        assert exc_info.value.code == 1


class TestModeResolution:
    """--mode flag and lifecycle-derived mode."""

    def test_explicit_diff_overrides_lifecycle(self):
        """--mode diff with staging tenant → uses diff (override)."""
        parser = build_ingestion_parser("test")
        args = parser.parse_args(["--tenant", "gw_v17", "--mode", "diff"])
        tenant, mode = resolve_tenant_and_mode(args, _CATALOG)
        assert tenant.tenant_id == "gw_v17"
        assert mode == "diff"

    def test_explicit_full_with_production(self):
        """--mode full with production tenant → uses full."""
        parser = build_ingestion_parser("test")
        args = parser.parse_args(["--tenant", "gw", "--mode", "full"])
        tenant, mode = resolve_tenant_and_mode(args, _CATALOG)
        assert tenant.tenant_id == "gw"
        assert mode == "full"

    def test_no_mode_staging_derives_full(self):
        """No --mode with staging lifecycle → derives full."""
        parser = build_ingestion_parser("test")
        args = parser.parse_args(["--tenant", "gw_v17"])
        tenant, mode = resolve_tenant_and_mode(args, _CATALOG)
        assert mode == "full"

    def test_no_mode_production_derives_full(self):
        """No --mode with production lifecycle → derives full."""
        parser = build_ingestion_parser("test")
        args = parser.parse_args(["--tenant", "gw"])
        tenant, mode = resolve_tenant_and_mode(args, _CATALOG)
        assert mode == "full"


class TestMergedStaleRefusal:
    """merged/stale lifecycle without explicit --mode → SystemExit."""

    def test_merged_without_mode_exits(self):
        merged_tenant = _FakeTenant(tenant_id="old", lifecycle="merged")
        catalog = _FakeCatalog([merged_tenant])
        catalog.defaults.tenant_id = "old"  # type: ignore
        parser = build_ingestion_parser("test")
        args = parser.parse_args(["--tenant", "old"])
        with pytest.raises(SystemExit) as exc_info:
            resolve_tenant_and_mode(args, catalog)
        assert exc_info.value.code == 1

    def test_stale_without_mode_exits(self):
        stale_tenant = _FakeTenant(tenant_id="stale_t", lifecycle="stale")
        catalog = _FakeCatalog([stale_tenant])
        parser = build_ingestion_parser("test")
        args = parser.parse_args(["--tenant", "stale_t"])
        with pytest.raises(SystemExit) as exc_info:
            resolve_tenant_and_mode(args, catalog)
        assert exc_info.value.code == 1

    def test_merged_with_explicit_mode_succeeds(self):
        """merged + explicit --mode full → allowed (operator override)."""
        merged_tenant = _FakeTenant(tenant_id="old", lifecycle="merged")
        catalog = _FakeCatalog([merged_tenant])
        parser = build_ingestion_parser("test")
        args = parser.parse_args(["--tenant", "old", "--mode", "full"])
        tenant, mode = resolve_tenant_and_mode(args, catalog)
        assert mode == "full"
