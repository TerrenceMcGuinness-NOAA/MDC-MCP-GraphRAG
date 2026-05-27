"""Tenant exception hierarchy.

Implements Requirements 1.7-1.11, 2.5, 9.3.
"""
from __future__ import annotations


class TenantError(Exception):
    """Base class for all tenant-related errors."""


class DuplicateTenantError(TenantError):
    """Two tenants share the same tenant_id (R1.7)."""


class UnknownTenantReferenceError(TenantError):
    """A tenant extends a tenant_id that does not exist (R1.8)."""


class InvalidPrefixError(TenantError):
    """An index_prefix or label_prefix fails regex validation (R1.9)."""


class DuplicateWorkflowSubdirError(TenantError):
    """Two tenants share the same workflow_subdir (R1.10)."""


class InvalidWorkflowSubdirError(TenantError):
    """A workflow_subdir contains path separators or invalid chars (R1.11)."""


class UnsupportedSchemaVersionError(TenantError):
    """Catalog schema_version exceeds what this server supports (R9.3)."""


class UnknownTenantError(TenantError):
    """A request specifies a tenant_id not in the catalog (R2.5).

    Parameters
    ----------
    tenant_id : str
        The unknown tenant_id from the request.
    known : tuple[str, ...]
        The set of valid tenant_ids in the catalog.
    """

    def __init__(self, tenant_id: str, *, known: tuple[str, ...]):
        self.tenant_id = tenant_id
        self.known = known
        super().__init__(
            f"unknown tenant_id={tenant_id!r}; "
            f"known tenants: {', '.join(known)}"
        )
