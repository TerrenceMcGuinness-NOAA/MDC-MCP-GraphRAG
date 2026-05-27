"""Tenancy runtime — module-scoped catalog singleton and default tenant.

Provides get_catalog() and get_default_tenant() for use by health checks
and smoke probes that need catalog access outside a per-request scope.

Implements Requirements 2.2, 2.3, 2.4.
"""
from __future__ import annotations

import os
from pathlib import Path

from src.config.tenants import Tenant, TenantCatalog, load_catalog

_CATALOG: TenantCatalog | None = None

# Default catalog path: package-relative src/config/tenants.yaml
_DEFAULT_CATALOG_PATH = str(
    Path(__file__).resolve().parent.parent / "config" / "tenants.yaml"
)


def get_catalog() -> TenantCatalog:
    """Return the cached tenant catalog (loaded on first call)."""
    global _CATALOG
    if _CATALOG is None:
        path = os.environ.get("MCP_TENANT_CATALOG_PATH", _DEFAULT_CATALOG_PATH)
        _CATALOG = load_catalog(path)
    return _CATALOG


def get_default_tenant() -> Tenant:
    """Resolve the default tenant using the precedence chain (env → catalog → gw).

    This is the non-request-scoped version used by health checks and
    smoke probes. For request-scoped resolution, use resolve_tenant().
    """
    catalog = get_catalog()
    chosen = (
        os.environ.get("MCP_DEFAULT_TENANT")
        or catalog.defaults.tenant_id
        or "gw"
    )
    tenant = catalog.by_id(chosen)
    if tenant is None:
        # Fall back to first tenant in catalog
        tenant = catalog.tenants[0] if catalog.tenants else None
    if tenant is None:
        raise RuntimeError("tenant catalog is empty — cannot resolve default tenant")
    return tenant


def reset_catalog() -> None:
    """Reset the cached catalog (for testing only)."""
    global _CATALOG
    _CATALOG = None
