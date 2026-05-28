"""Tenant attribution wrapper — prepends *Tenant: <id>* header.

Implements Requirements 5.1, 5.2.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.config.tenants import Tenant


def attribute(body, tenant: "Tenant", *, now=None):
    """Prepend ``*Tenant: <id>*`` header to a tool's rendered output.

    Parameters
    ----------
    body : str | Any
        The tool's rendered output. Non-string values pass through unchanged.
    tenant : Tenant
        The resolved tenant for this request.
    now : datetime | None
        Unused placeholder for future staleness-threshold logic (54g).

    Returns
    -------
    str | Any
        The attributed output (string with header) or the original value
        if body is not a string.
    """
    if not isinstance(body, str):
        return body
    stale = " [STALE]" if tenant.lifecycle == "stale" else ""
    lines = [f"*Tenant: {tenant.tenant_id}*{stale}"]
    if tenant.branch:
        lines.append(f"*Branch: {tenant.branch}*")
    header = "\n".join(lines) + "\n\n"
    return header + body
