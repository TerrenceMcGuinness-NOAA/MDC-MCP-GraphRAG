"""Tenant resolution — TenantContext, resolve_tenant, ContextVar plumbing.

Implements Requirements 2.1-2.8, 5.5, 6.3.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator, Callable

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

# All non-empty label prefixes declared in the active catalog. Used to build
# the gw-default exclusion predicate (a base/gw node is one whose labels carry
# none of the other tenants' prefixes). Set alongside the tenant context.
_all_prefixes_var: ContextVar[tuple[str, ...]] = ContextVar(
    "tenant_all_prefixes", default=()
)


def _catalog_label_prefixes(catalog: "TenantCatalog") -> tuple[str, ...]:
    """Return all non-empty label prefixes declared in the catalog."""
    return tuple(
        t.label_prefix for t in catalog.tenants if t.label_prefix
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


def get_current_tenant_or_none() -> TenantContext | None:
    """Read the active TenantContext, or None if no scope is active.

    Use this in call sites that may run both inside and outside a
    tenant_aware scope (e.g. during the transition before the decorator
    is wired into all tools).
    """
    return _ctx_var.get()


def get_all_label_prefixes() -> tuple[str, ...]:
    """Return the catalog's non-empty label prefixes for the active scope.

    Empty tuple when no scope is active or the catalog declares none.
    """
    return _all_prefixes_var.get()


def tenant_label_predicate(var: str) -> str:
    """Build a Cypher WHERE fragment scoping a label-less node to the tenant.

    Label-less patterns like ``MATCH (n) WHERE n.name = $x`` cannot be scoped
    by the label-prefix rewriter (there is no ``:Label`` token to rewrite), so
    they match nodes from every tenant. This helper returns a predicate based
    on ``labels(n)`` — the only reliable discriminator, since the ``tenant_id``
    property is absent on placeholder nodes.

    * Non-default tenant (non-empty prefix): the node must carry at least one
      label starting with that prefix.
    * Default ``gw`` tenant (empty prefix): the node must carry NO label that
      starts with any other tenant's prefix (i.e. it is a base/unprefixed node).

    Returns an empty string when no scoping can be applied (no active tenant,
    or gw with no other tenants in the catalog) so callers can append it
    unconditionally.

    Parameters
    ----------
    var : str
        The node variable name used in the query (e.g. ``"n"``).
    """
    ctx = _ctx_var.get()
    if ctx is None:
        return ""
    prefix = ctx.tenant.label_prefix
    if prefix:
        # Non-default tenant: node must own a label with this prefix.
        return (
            f"size([__lbl IN labels({var}) "
            f"WHERE __lbl STARTS WITH '{prefix}']) > 0"
        )
    # Default gw tenant: exclude nodes owning any other tenant's prefix.
    others = _all_prefixes_var.get()
    if not others:
        return ""
    conds = " OR ".join(
        f"__lbl STARTS WITH '{p}'" for p in others
    )
    return f"size([__lbl IN labels({var}) WHERE {conds}]) = 0"


# ---------------------------------------------------------------------------
# tenant_scope context manager (Approach B — explicit tenant_id on tools)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def tenant_scope(
    tenant_id: str | None, catalog: "TenantCatalog"
) -> AsyncGenerator[TenantContext, None]:
    """Resolve tenant_id and bind the ContextVar for the call's duration.

    Yields the resolved TenantContext. Raises UnknownTenantError on an
    unknown id (caller renders the error).
    """
    ctx = resolve_tenant(request_tenant_id=tenant_id, catalog=catalog)
    token = _ctx_var.set(ctx)
    prefixes_token = _all_prefixes_var.set(_catalog_label_prefixes(catalog))
    try:
        yield ctx
    finally:
        _ctx_var.reset(token)
        _all_prefixes_var.reset(prefixes_token)


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
            prefixes_token = _all_prefixes_var.set(
                _catalog_label_prefixes(catalog)
            )
            try:
                body = await fn(*args, **kwargs)
            finally:
                _ctx_var.reset(token)
                _all_prefixes_var.reset(prefixes_token)
            from src.tools._attribution import attribute
            return attribute(body, ctx.tenant)

        inner.__wrapped__ = fn
        inner.__name__ = getattr(fn, "__name__", "unknown")
        inner.__qualname__ = getattr(fn, "__qualname__", inner.__name__)
        return inner

    return decorator
