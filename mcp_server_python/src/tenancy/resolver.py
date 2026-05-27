"""Tenant resolution — TenantContext, resolve_tenant, ContextVar plumbing.

Implements Requirements 2.1-2.8, 5.5, 6.3.
"""
from __future__ import annotations

import os
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from src.config.tenants import Tenant, TenantCatalog

from src.tenancy.exceptions import UnknownTenantError

# ---------------------------------------------------------------------------
# TenantContext
# ---------------------------------------------------------------------------

DEFAULT_HARDCODED_TENANT = "gw"


@dataclass(frozen=True)
class TenantContext:
    """Request-scoped tenant view (R2.6, R2.7)."""

    tenant_id: str
    tenant: "Tenant"

    @property
    def workflow_root(self) -> Path:
        """Per-tenant absolute path on the AgentCore EFS mount."""
        return self.tenant.workflow_root


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def resolve_tenant(
    *,
    request_tenant_id: str | None,
    catalog: "TenantCatalog",
    env: dict[str, str] | None = None,
) -> TenantContext:
    """Apply the precedence chain from R2.1-R2.4.

    Precedence:
      1. request_tenant_id (explicit field on the tool request) — R2.1
      2. MCP_DEFAULT_TENANT env var — R2.2
      3. catalog.defaults.tenant_id — R2.3
      4. "gw" hardcoded — R2.4

    Parameters
    ----------
    request_tenant_id : str | None
        The optional tenant_id from the MCP tool request.
    catalog : TenantCatalog
        The loaded tenant catalog.
    env : dict[str, str] | None
        Environment dict; defaults to os.environ if None.

    Returns
    -------
    TenantContext
        The resolved request-scoped context.

    Raises
    ------
    UnknownTenantError
        If the resolved tenant_id is not in the catalog.
    """
    if env is None:
        env = os.environ
    chosen = (
        request_tenant_id
        or env.get("MCP_DEFAULT_TENANT")
        or catalog.defaults.tenant_id
        or DEFAULT_HARDCODED_TENANT
    )
    tenant = catalog.by_id(chosen)
    if tenant is None:
        raise UnknownTenantError(chosen, known=catalog.tenant_ids)
    return TenantContext(tenant_id=tenant.tenant_id, tenant=tenant)


# ---------------------------------------------------------------------------
# ContextVar plumbing
# ---------------------------------------------------------------------------

_ctx_var: ContextVar[TenantContext | None] = ContextVar(
    "tenant_ctx", default=None
)


def get_current_tenant() -> TenantContext:
    """Read the active TenantContext from the ContextVar.

    Raises
    ------
    RuntimeError
        If called outside a tenant_aware-decorated scope.
    """
    ctx = _ctx_var.get()
    if ctx is None:
        raise RuntimeError(
            "no active TenantContext — call from within a tenant_aware scope"
        )
    return ctx


# ---------------------------------------------------------------------------
# tenant_aware decorator
# ---------------------------------------------------------------------------


def tenant_aware(catalog: "TenantCatalog") -> Callable:
    """Decorator factory that wraps a FastMCP tool with tenant resolution.

    Usage::

        wrap = tenant_aware(catalog)

        @mcp.tool(name="describe_component")
        @wrap
        async def describe_component(component: str, *,
                                     tenant_id: str | None = None): ...

    The decorator:
      1. Pops the optional ``tenant_id`` kwarg.
      2. Calls ``resolve_tenant``.
      3. Sets the ContextVar for the duration of the call.
      4. Wraps the rendered string body with the attribution header.
    """
    def decorator(fn):
        async def inner(*args, tenant_id: str | None = None, **kwargs):
            ctx = resolve_tenant(
                request_tenant_id=tenant_id, catalog=catalog
            )
            token = _ctx_var.set(ctx)
            try:
                body = await fn(*args, **kwargs)
            finally:
                _ctx_var.reset(token)
            from src.tools._attribution import attribute
            return attribute(body, ctx.tenant)

        inner.__wrapped__ = fn
        inner.__name__ = getattr(fn, "__name__", "unknown")
        inner.__qualname__ = getattr(fn, "__qualname__", inner.__name__)
        return inner

    return decorator
