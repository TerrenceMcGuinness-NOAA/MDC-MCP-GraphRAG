"""Unit tests for src/tenancy/resolver.py — edge cases and ContextVar isolation.

Validates Requirements 2.5, 2.6.
"""
from __future__ import annotations

import asyncio

import pytest

from src.config.tenants import CatalogDefaults, Tenant, TenantCatalog
from src.tenancy.exceptions import UnknownTenantError
from src.tenancy.resolver import (
    get_current_tenant,
    resolve_tenant,
    tenant_aware,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_catalog(*tenant_ids: str) -> TenantCatalog:
    """Build a minimal catalog with the given tenant IDs."""
    tenants = tuple(
        Tenant(
            tenant_id=tid,
            repo_ref="NOAA-EMC/global-workflow",
            branch="develop",
            index_prefix="" if tid == "gw" else f"{tid}_",
            label_prefix="" if tid == "gw" else f"{tid.upper()}_",
            workflow_subdir=tid,
            lifecycle="production",
            description=f"Test tenant {tid}",
        )
        for tid in tenant_ids
    )
    return TenantCatalog(
        schema_version=1,
        defaults=CatalogDefaults(tenant_id=tenant_ids[0]),
        tenants=tenants,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestResolverEdgeCases:
    """Edge-case unit tests for resolve_tenant."""

    def test_unknown_tenant_raises(self):
        catalog = _make_catalog("gw")
        with pytest.raises(UnknownTenantError) as exc_info:
            resolve_tenant(
                request_tenant_id="nonexistent",
                catalog=catalog,
                env={},
            )
        assert exc_info.value.tenant_id == "nonexistent"
        assert "gw" in exc_info.value.known

    def test_get_current_tenant_outside_scope_raises(self):
        with pytest.raises(RuntimeError, match="no active TenantContext"):
            get_current_tenant()


class TestContextVarIsolation:
    """ContextVar isolation — concurrent tenant_aware calls see independent contexts."""

    @pytest.mark.asyncio
    async def test_concurrent_tenant_aware_isolation(self):
        """Two concurrent tenant_aware-wrapped tools with different tenant_ids
        must not cross-talk via the ContextVar."""
        catalog = _make_catalog("gw", "sfs")
        wrap = tenant_aware(catalog)

        seen_tenants: dict[str, str] = {}

        @wrap
        async def stub_tool_a():
            # Simulate some async work
            await asyncio.sleep(0.01)
            ctx = get_current_tenant()
            seen_tenants["a"] = ctx.tenant_id
            return f"result from {ctx.tenant_id}"

        @wrap
        async def stub_tool_b():
            await asyncio.sleep(0.01)
            ctx = get_current_tenant()
            seen_tenants["b"] = ctx.tenant_id
            return f"result from {ctx.tenant_id}"

        # Run concurrently with different tenant_ids
        result_a, result_b = await asyncio.gather(
            stub_tool_a(tenant_id="gw"),
            stub_tool_b(tenant_id="sfs"),
        )

        # Each saw its own tenant — no cross-talk
        assert seen_tenants["a"] == "gw"
        assert seen_tenants["b"] == "sfs"
        assert "*Tenant: gw*" in result_a
        assert "*Tenant: sfs*" in result_b
