"""Tenant-scoping helper for tool bodies (Approach B).

Provides run_tenant_scoped() — the single call each tenant-scoped tool
wraps its body in. Resolves tenant_id, sets the ContextVar, awaits the
tool's coroutine factory, applies attribution, and handles errors.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable

from src.tenancy.exceptions import UnknownTenantError
from src.tenancy.resolver import tenant_scope
from src.tools._attribution import attribute

if TYPE_CHECKING:
    from src.config.tenants import TenantCatalog


async def run_tenant_scoped(
    tenant_id: str | None,
    catalog: "TenantCatalog",
    coro_factory: Callable[[], Awaitable[str]],
) -> str:
    """Resolve tenant, run coro_factory() inside scope, attribute result.

    Parameters
    ----------
    tenant_id
        Optional tenant_id from the tool request.
    catalog
        The loaded TenantCatalog.
    coro_factory
        Zero-arg async callable returning the tool's rendered body.

    Returns
    -------
    str
        Attributed body on success; ``[ERROR] ...`` on UnknownTenantError.
    """
    try:
        async with tenant_scope(tenant_id, catalog) as ctx:
            body = await coro_factory()
            return attribute(body, ctx.tenant)
    except UnknownTenantError as e:
        return f"[ERROR] {e}"
