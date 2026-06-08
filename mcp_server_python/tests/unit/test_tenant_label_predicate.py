"""Unit tests for tenant_label_predicate (Gap E — label-less query scoping).

The predicate scopes label-less ``MATCH (n)`` patterns to the active tenant
using ``labels(n)`` — the only reliable discriminator (the ``tenant_id``
property is absent on placeholder nodes). Verifies:

* Non-default tenant → membership predicate on its own prefix.
* Default gw tenant → exclusion predicate over the OTHER tenants' prefixes.
* No active scope → empty string (caller appends unconditionally).
"""
from __future__ import annotations

import pytest

from src.config.tenants import CatalogDefaults, Tenant, TenantCatalog
from src.tenancy.resolver import tenant_label_predicate, tenant_scope


def _make_catalog() -> TenantCatalog:
    gw = Tenant(
        tenant_id="gw", repo_ref="R", branch="develop",
        index_prefix="", label_prefix="",
        workflow_subdir="develop", lifecycle="production",
    )
    gw_v17 = Tenant(
        tenant_id="gw_v17", repo_ref="R", branch="dev/gfs.v17",
        index_prefix="gw_v17_", label_prefix="GW_V17_",
        workflow_subdir="dev-v17", lifecycle="staging",
    )
    gw_sfs = Tenant(
        tenant_id="gw_sfs", repo_ref="R", branch="dev/sfs",
        index_prefix="gw_sfs_", label_prefix="GW_SFS_",
        workflow_subdir="dev-sfs", lifecycle="experimental",
    )
    return TenantCatalog(
        schema_version=1,
        defaults=CatalogDefaults(tenant_id="gw"),
        tenants=(gw, gw_v17, gw_sfs),
    )


def test_predicate_empty_when_no_active_scope() -> None:
    """Outside any tenant scope the predicate is empty (no-op)."""
    assert tenant_label_predicate("n") == ""


@pytest.mark.asyncio
async def test_predicate_for_non_default_tenant() -> None:
    """A prefixed tenant requires a label starting with its prefix."""
    catalog = _make_catalog()
    async with tenant_scope("gw_v17", catalog):
        pred = tenant_label_predicate("n")
    assert "labels(n)" in pred
    assert "STARTS WITH 'GW_V17_'" in pred
    assert pred.endswith("> 0")


@pytest.mark.asyncio
async def test_predicate_for_default_tenant_excludes_others() -> None:
    """The gw default excludes nodes carrying any OTHER tenant's prefix."""
    catalog = _make_catalog()
    async with tenant_scope("gw", catalog):
        pred = tenant_label_predicate("n")
    assert "labels(n)" in pred
    assert "STARTS WITH 'GW_V17_'" in pred
    assert "STARTS WITH 'GW_SFS_'" in pred
    assert pred.endswith("= 0")


@pytest.mark.asyncio
async def test_predicate_uses_supplied_variable_name() -> None:
    """The predicate references the variable name the caller passes."""
    catalog = _make_catalog()
    async with tenant_scope("gw_v17", catalog):
        assert "labels(target)" in tenant_label_predicate("target")
        assert "labels(src)" in tenant_label_predicate("src")


@pytest.mark.asyncio
async def test_default_tenant_with_no_other_prefixes_is_empty() -> None:
    """If the catalog has only gw (no prefixed tenants), gw predicate is empty."""
    gw = Tenant(
        tenant_id="gw", repo_ref="R", branch="develop",
        index_prefix="", label_prefix="",
        workflow_subdir="develop", lifecycle="production",
    )
    catalog = TenantCatalog(
        schema_version=1,
        defaults=CatalogDefaults(tenant_id="gw"),
        tenants=(gw,),
    )
    async with tenant_scope("gw", catalog):
        assert tenant_label_predicate("n") == ""
