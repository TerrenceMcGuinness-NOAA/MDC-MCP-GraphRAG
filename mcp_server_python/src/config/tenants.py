"""Tenant catalog — dataclasses, loader, validator, CLI.

Implements Requirements 1.1-1.11, 7.1, 7.5, 9.1-9.3, 10.1-10.4.
"""
from __future__ import annotations

import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

from src.tenancy.exceptions import (
    DuplicateTenantError,
    DuplicateWorkflowSubdirError,
    InvalidPrefixError,
    InvalidWorkflowSubdirError,
    UnknownTenantReferenceError,
    UnsupportedSchemaVersionError,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LIFECYCLE_VALUES = ("experimental", "staging", "production", "merged", "stale")
SUPPORTED_SCHEMA_VERSIONS = (1,)

# Base directory under which each tenant's ``workflow_subdir`` lives. Defaults
# to the AWS Bedrock AgentCore EFS access-point mount; native deployments
# (e.g. Parallel Works) override via ``MCP_WORKFLOW_MOUNT`` (Phase 61).
_DEFAULT_WORKFLOW_MOUNT = "/mnt/workflow"

_PREFIX_RE = re.compile(r"^([a-z][a-z0-9_]*_)?$")
_LABEL_PREFIX_RE = re.compile(r"^([A-Z][A-Z0-9_]*_)?$")
_SUBDIR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

_KNOWN_TENANT_FIELDS = frozenset({
    "tenant_id", "repo_ref", "branch", "index_prefix", "label_prefix",
    "workflow_subdir", "lifecycle", "description", "extends",
    "staleness_threshold_days",
})

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Tenant:
    """A single tenant entry from the catalog."""

    tenant_id: str
    repo_ref: str
    branch: str
    index_prefix: str
    label_prefix: str
    workflow_subdir: str
    lifecycle: str
    description: str = ""
    extends: tuple[str, ...] = ()
    staleness_threshold_days: int | None = None

    @property
    def workflow_root(self) -> Path:
        """Per-tenant absolute path under the configured workflow mount base.

        The base directory is ``MCP_WORKFLOW_MOUNT`` (default
        ``/mnt/workflow`` — the AWS Bedrock AgentCore EFS access-point
        mount, preserving R2.7 behaviour). Native deployments such as
        Parallel Works override it to a local directory whose children
        match the catalog ``workflow_subdir`` values (Phase 61).
        """
        base = os.environ.get("MCP_WORKFLOW_MOUNT", _DEFAULT_WORKFLOW_MOUNT)
        return Path(base) / self.workflow_subdir


@dataclass(frozen=True)
class CatalogDefaults:
    """Catalog-level defaults block."""

    tenant_id: str = "gw"
    staleness_threshold_days: int = 30


@dataclass(frozen=True)
class TenantCatalog:
    """The full parsed tenant catalog."""

    schema_version: int
    defaults: CatalogDefaults
    tenants: tuple[Tenant, ...]

    def by_id(self, tenant_id: str) -> Tenant | None:
        """Look up a tenant by ID; returns None if not found."""
        return next((t for t in self.tenants if t.tenant_id == tenant_id), None)

    @property
    def tenant_ids(self) -> tuple[str, ...]:
        """All tenant IDs in catalog order."""
        return tuple(t.tenant_id for t in self.tenants)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_prefix(value: str, *, kind: str, tenant_id: str) -> None:
    pattern = _PREFIX_RE if kind == "index" else _LABEL_PREFIX_RE
    if not pattern.match(value):
        raise InvalidPrefixError(
            f"tenant {tenant_id!r}: invalid {kind}_prefix={value!r}; "
            f"must match {pattern.pattern}"
        )


def _validate_workflow_subdir(value: str, *, tenant_id: str) -> None:
    if "/" in value or "\\" in value or value.startswith(".") or not _SUBDIR_RE.match(value):
        raise InvalidWorkflowSubdirError(
            f"tenant {tenant_id!r}: workflow_subdir={value!r} contains "
            f"a path separator, leading dot, or disallowed character"
        )


def _validate_catalog(catalog: TenantCatalog) -> None:
    if catalog.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise UnsupportedSchemaVersionError(
            f"catalog schema_version={catalog.schema_version} > "
            f"max supported {max(SUPPORTED_SCHEMA_VERSIONS)}"
        )
    seen_ids: set[str] = set()
    seen_subdirs: dict[str, str] = {}
    for t in catalog.tenants:
        if t.tenant_id in seen_ids:
            raise DuplicateTenantError(f"duplicate tenant_id: {t.tenant_id!r}")
        seen_ids.add(t.tenant_id)
        _validate_prefix(t.index_prefix, kind="index", tenant_id=t.tenant_id)
        _validate_prefix(t.label_prefix, kind="label", tenant_id=t.tenant_id)
        _validate_workflow_subdir(t.workflow_subdir, tenant_id=t.tenant_id)
        if t.workflow_subdir in seen_subdirs:
            other = seen_subdirs[t.workflow_subdir]
            raise DuplicateWorkflowSubdirError(
                f"workflow_subdir={t.workflow_subdir!r} declared by both "
                f"{other!r} and {t.tenant_id!r}"
            )
        seen_subdirs[t.workflow_subdir] = t.tenant_id
    for t in catalog.tenants:
        for ref in t.extends:
            if ref not in seen_ids:
                raise UnknownTenantReferenceError(
                    f"tenant {t.tenant_id!r} extends unknown tenant {ref!r}"
                )


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_catalog(path: str | Path) -> TenantCatalog:
    """Load and validate a tenant catalog from a YAML file.

    Parameters
    ----------
    path : str | Path
        Path to the tenants.yaml file.

    Returns
    -------
    TenantCatalog
        The validated catalog.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    yaml.YAMLError
        If the file is not valid YAML.
    DuplicateTenantError, UnknownTenantReferenceError, InvalidPrefixError,
    DuplicateWorkflowSubdirError, InvalidWorkflowSubdirError,
    UnsupportedSchemaVersionError
        On structural validation failures.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    schema_version = int(raw.get("schema_version", 1))
    defaults_raw = raw.get("defaults") or {}
    defaults = CatalogDefaults(
        tenant_id=defaults_raw.get("tenant_id", "gw"),
        staleness_threshold_days=int(
            defaults_raw.get("staleness_threshold_days", 30)
        ),
    )
    tenants: list[Tenant] = []
    for entry in raw.get("tenants", []):
        for k in entry:
            if k not in _KNOWN_TENANT_FIELDS:
                log.warning(
                    "[WARN] tenant %r: unknown field %r ignored "
                    "(forward-compat per R9.1)",
                    entry.get("tenant_id"), k,
                )
        tenants.append(Tenant(
            tenant_id=entry["tenant_id"],
            repo_ref=entry["repo_ref"],
            branch=entry["branch"],
            index_prefix=entry.get("index_prefix", ""),
            label_prefix=entry.get("label_prefix", ""),
            workflow_subdir=entry["workflow_subdir"],
            lifecycle=entry.get("lifecycle", "experimental"),
            description=entry.get("description", ""),
            extends=tuple(entry.get("extends") or ()),
            staleness_threshold_days=entry.get("staleness_threshold_days"),
        ))
    catalog = TenantCatalog(
        schema_version=schema_version,
        defaults=defaults,
        tenants=tuple(tenants),
    )
    _validate_catalog(catalog)
    return catalog


# ---------------------------------------------------------------------------
# CLI entry point (R10.1-R10.4)
# ---------------------------------------------------------------------------


def _cli_validate(path: str) -> int:
    """Validate a tenant catalog file.

    Exit codes: 0 = valid, 1 = structural error, 2 = unreachable file.
    """
    try:
        catalog = load_catalog(path)
    except FileNotFoundError:
        print(f"[ERROR] catalog not found: {path}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"[ERROR] catalog unreachable: {exc}", file=sys.stderr)
        return 2
    except (yaml.YAMLError,) as exc:
        print(f"[ERROR] YAML parse error: {exc}", file=sys.stderr)
        return 1
    except (DuplicateTenantError, UnknownTenantReferenceError,
            InvalidPrefixError, DuplicateWorkflowSubdirError,
            InvalidWorkflowSubdirError, UnsupportedSchemaVersionError) as exc:
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"# Tenant catalog ({len(catalog.tenants)} tenant(s))")
    for t in catalog.tenants:
        chain = " -> ".join((*t.extends, t.tenant_id))
        print(
            f"- {t.tenant_id}: index_prefix={t.index_prefix!r} "
            f"label_prefix={t.label_prefix!r} "
            f"workflow_subdir={t.workflow_subdir!r} "
            f"lifecycle={t.lifecycle} chain={chain}"
        )
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "validate":
        sys.exit(_cli_validate(sys.argv[2]))
    else:
        print("Usage: python -m src.config.tenants validate <path>", file=sys.stderr)
        sys.exit(2)
