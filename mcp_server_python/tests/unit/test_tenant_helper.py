"""Unit tests for tenant_scope and run_tenant_scoped (Task 3.1)."""
from __future__ import annotations

import pytest

from src.config.tenants import CatalogDefaults, Tenant, TenantCatalog
from src.tenancy.resolver import _ctx_var, tenant_scope
from src.tools._tenant_helper import run_tenant_scoped


def _make_catalog() -> TenantCatalog:
    gw = Tenant(
        tenant_id="gw",
        repo_ref="NOAA-EMC/global-workflow",
        branch="develop",
        index_prefix="",
        label_prefix="",
        workflow_subdir="global-workflow",
        lifecycle="production",
    )
    gw_v17 = Tenant(
        tenant_id="gw_v17",
        repo_ref="NOAA-EMC/global-workflow",
        branch="dev/gfs.v17",
        index_prefix="gw_v17_",
        label_prefix="GW_V17_",
        workflow_subdir="global-workflow-v17",
        lifecycle="experimental",
    )
    return TenantCatalog(
        schema_version=1,
        defaults=CatalogDefaults(tenant_id="gw"),
        tenants=(gw, gw_v17),
    )


class TestTenantScope:
    """Tests for the tenant_scope async context manager."""

    @pytest.mark.asyncio
    async def test_sets_ctx_var_inside_scope(self):
        catalog = _make_catalog()
        assert _ctx_var.get() is None
        async with tenant_scope("gw_v17", catalog) as ctx:
            assert ctx.tenant_id == "gw_v17"
            assert _ctx_var.get() is ctx
        assert _ctx_var.get() is None

    @pytest.mark.asyncio
    async def test_resets_ctx_var_after_scope(self):
        catalog = _make_catalog()
        async with tenant_scope("gw", catalog) as ctx:
            assert _ctx_var.get() is ctx
        assert _ctx_var.get() is None

    @pytest.mark.asyncio
    async def test_raises_unknown_tenant_error(self):
        catalog = _make_catalog()
        from src.tenancy.exceptions import UnknownTenantError
        with pytest.raises(UnknownTenantError) as exc_info:
            async with tenant_scope("nope", catalog):
                pass  # pragma: no cover
        assert "nope" in str(exc_info.value)
        assert "gw" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_none_tenant_id_resolves_default(self):
        catalog = _make_catalog()
        async with tenant_scope(None, catalog) as ctx:
            assert ctx.tenant_id == "gw"


class TestRunTenantScoped:
    """Tests for the run_tenant_scoped helper."""

    @pytest.mark.asyncio
    async def test_valid_tenant_returns_attributed_body(self):
        catalog = _make_catalog()

        async def factory():
            return "# Results\nsome content"

        result = await run_tenant_scoped("gw_v17", catalog, factory)
        assert "*Tenant: gw_v17*" in result
        assert "*Branch: dev/gfs.v17*" in result
        assert "# Results" in result

    @pytest.mark.asyncio
    async def test_none_tenant_uses_default(self):
        catalog = _make_catalog()

        async def factory():
            return "body"

        result = await run_tenant_scoped(None, catalog, factory)
        assert "*Tenant: gw*" in result

    @pytest.mark.asyncio
    async def test_unknown_tenant_returns_error(self):
        catalog = _make_catalog()

        async def factory():
            return "should not reach"  # pragma: no cover

        result = await run_tenant_scoped("nonexistent", catalog, factory)
        assert result.startswith("[ERROR]")
        assert "nonexistent" in result
        assert "gw" in result
        assert "gw_v17" in result

    @pytest.mark.asyncio
    async def test_unknown_tenant_no_adapter_calls(self):
        """On unknown tenant, the coro_factory must NOT be called."""
        catalog = _make_catalog()
        called = []

        async def factory():
            called.append(True)
            return "x"  # pragma: no cover

        await run_tenant_scoped("bad_id", catalog, factory)
        assert called == [], "factory was called despite unknown tenant"
