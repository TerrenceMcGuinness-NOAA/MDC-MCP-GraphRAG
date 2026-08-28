"""Tenancy runtime — module-scoped catalog singleton and default tenant.

Provides get_catalog() and get_default_tenant() for use by health checks
and smoke probes that need catalog access outside a per-request scope.

Implements Requirements 2.2, 2.3, 2.4.

shared-scope-query-routing Task 3.1: :func:`get_catalog` now resolves
through :func:`src.config.tenants.load_catalog_from_transport`, which
adds the content-carrying ``MCP_TENANT_CATALOG_YAML`` transport ahead of
the existing path-only ``MCP_TENANT_CATALOG_PATH`` (Requirements 5.3,
5.7). Only this accessor switches -- the ingestion scripts and
``src/tools/smoke_queries.py`` continue to call
``src.config.tenants.load_catalog(path)`` directly and are unaffected
(Requirement 12.2).
"""
from __future__ import annotations

import os
from pathlib import Path

from src.config.tenants import (
    Tenant,
    TenantCatalog,
    load_catalog_from_transport,
)

_CATALOG: TenantCatalog | None = None

# Default catalog path: package-relative src/config/tenants.yaml
_DEFAULT_CATALOG_PATH = str(
    Path(__file__).resolve().parent.parent / "config" / "tenants.yaml"
)


def get_catalog() -> TenantCatalog:
    """Return the cached tenant catalog (loaded on first call).

    Resolves via :func:`load_catalog_from_transport`'s precedence chain:
    inline ``MCP_TENANT_CATALOG_YAML`` content, then the
    ``MCP_TENANT_CATALOG_PATH`` file, then the bundled
    ``src/config/tenants.yaml``.

    Raises
    ------
    CatalogConfigError
        If a named source (either environment variable is set) cannot
        be read or parsed (Requirement 5.6). This module does not catch
        the error and does not fall back to the bundled default in that
        case -- doing so would silently mask the hard-error path the
        transport chain exists to preserve.
    """
    global _CATALOG
    if _CATALOG is None:
        catalog, _transport = load_catalog_from_transport(
            _DEFAULT_CATALOG_PATH
        )
        _CATALOG = catalog
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
    """Reset the cached catalog (for testing only).

    Also resets the memoized transport catalog in
    :mod:`src.config.tenants` so a subsequent :func:`get_catalog` call
    re-reads the active Configuration_Transport rather than returning a
    stale cross-module cache entry.
    """
    global _CATALOG
    _CATALOG = None
    from src.config.tenants import _reset_transport_catalog_cache_for_tests
    _reset_transport_catalog_cache_for_tests()
