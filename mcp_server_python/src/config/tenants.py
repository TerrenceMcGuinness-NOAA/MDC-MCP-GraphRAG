"""Tenant catalog — dataclasses, loader, validator, CLI.

Implements Requirements 1.1-1.11, 7.1, 7.5, 9.1-9.3, 10.1-10.4.

shared-scope-query-routing Task 3.1 adds :func:`load_catalog_from_transport`,
the content-carrying Configuration_Transport chain that Requirements 5.3
and 5.7 presuppose. :func:`load_catalog` (path-only) keeps its existing
signature and behaviour untouched -- the ingestion scripts under
``mcp_server_python/scripts/`` and ``src/tools/smoke_queries.py`` import it
directly, and Requirement 12.2 freezes that directory byte-for-byte.
"""
from __future__ import annotations

import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

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


class CatalogConfigError(RuntimeError):
    """Raised when a catalog Configuration_Transport cannot be read or
    parsed (shared-scope-query-routing Requirement 5.6).

    This is the hard-error path for :func:`load_catalog_from_transport`:
    a configuration source exists (an environment variable is set, or a
    path is named) and its content is unreadable or malformed. The
    caller must resolve nothing and issue no read -- it must never
    degrade to a default catalog or to treating every tenant as
    unresolved. Distinct from :func:`load_catalog`'s existing exception
    surface (``FileNotFoundError``, ``yaml.YAMLError``, the
    ``TenantError`` subclasses), which callers of the path-only loader
    already handle; this transport-selection wrapper re-raises those as
    ``CatalogConfigError`` so a caller of the new function has one
    exception type naming the failing Configuration_Transport.
    """


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


def _parse_catalog_yaml_text(text: str) -> TenantCatalog:
    """Parse and validate catalog YAML content already read into memory.

    This is the single parser both :func:`load_catalog` (path transport)
    and :func:`load_catalog_from_transport` (env-content-or-path
    transport, shared-scope-query-routing Requirement 5.7) route
    through, so byte-identical YAML content yields a structurally equal
    :class:`TenantCatalog` regardless of which transport supplied it
    (Requirement 5.3, Property 4).

    Parameters
    ----------
    text : str
        Raw YAML document content (already decoded).

    Returns
    -------
    TenantCatalog
        The validated catalog.

    Raises
    ------
    yaml.YAMLError
        If ``text`` is not valid YAML.
    DuplicateTenantError, UnknownTenantReferenceError, InvalidPrefixError,
    DuplicateWorkflowSubdirError, InvalidWorkflowSubdirError,
    UnsupportedSchemaVersionError
        On structural validation failures.
    """
    raw = yaml.safe_load(text)
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


def load_catalog(path: str | Path) -> TenantCatalog:
    """Load and validate a tenant catalog from a YAML file.

    Signature and behaviour are unchanged by the shared-scope-query-routing
    change (Requirement 12.2): the ingestion scripts under
    ``mcp_server_python/scripts/`` and ``src/tools/smoke_queries.py``
    import this function directly and that directory is frozen
    byte-for-byte. Use :func:`load_catalog_from_transport` for the new
    content-carrying Configuration_Transport chain.

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
    return _parse_catalog_yaml_text(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Content-carrying Configuration_Transport (shared-scope-query-routing
# Requirements 5.3, 5.6, 5.7)
# ---------------------------------------------------------------------------

#: Inline YAML content for the tenant catalog (highest precedence).
ENV_TENANT_CATALOG_YAML: Final[str] = "MCP_TENANT_CATALOG_YAML"

#: Path to a tenant catalog YAML file (second precedence).
ENV_TENANT_CATALOG_PATH: Final[str] = "MCP_TENANT_CATALOG_PATH"

#: Memoized (catalog, transport) pair. Populated on first use by
#: :func:`load_catalog_from_transport` so an env/file source is read (and,
#: if invalid, raises) at most once per process -- matching the
#: read-once-and-memoize rule ``collection_scope.py`` uses for the same
#: reason (no per-resolution I/O, Requirement 5.1/P9 in spirit for this
#: sibling transport).
_transport_catalog_cache: tuple[TenantCatalog, str] | None = None


def load_catalog_from_transport(
    default_path: str | Path,
) -> tuple[TenantCatalog, str]:
    """Resolve the tenant catalog via the content-carrying transport chain.

    Precedence, identical under every Form_Factor (Requirement 5.7 --
    one rule, no per-environment branching):

    1. ``MCP_TENANT_CATALOG_YAML`` -- inline YAML content.
    2. ``MCP_TENANT_CATALOG_PATH`` -- path to a YAML file.
    3. ``default_path`` -- the bundled catalog file.

    All three routes parse through :func:`_parse_catalog_yaml_text`, the
    same parser :func:`load_catalog` uses, so content that is
    byte-identical between the inline-env and mounted-file forms
    produces a structurally equal :class:`TenantCatalog` (Requirement
    5.3, Property 4) -- an equal catalog yields an equal ``index_prefix``
    for every tenant, which yields an equal Resolved_Collection_Set once
    the Read_Router consumes it.

    The resolved content is read once and memoized for the remainder of
    the process lifetime. This mirrors ``collection_scope.py``'s
    ``_active_table`` memoization and exists for the same reason: the
    Read_Router's no-per-resolution-I/O guarantee depends on its inputs
    not re-reading the environment or the filesystem on every call.

    Parameters
    ----------
    default_path : str | Path
        The bundled catalog path to fall back to when neither
        environment variable is set.

    Returns
    -------
    tuple[TenantCatalog, str]
        The validated catalog, and the transport it came from -- one of
        ``"env"``, ``"file"``, or ``"builtin"``.

    Raises
    ------
    CatalogConfigError
        If a source is named (either environment variable is set) and
        its content cannot be read or parsed. This is the Requirement
        5.6 hard-error path: resolve nothing, issue no read, and never
        degrade to the bundled default or to treating every tenant as
        unresolved.
    """
    global _transport_catalog_cache
    if _transport_catalog_cache is not None:
        return _transport_catalog_cache

    inline = os.environ.get(ENV_TENANT_CATALOG_YAML)
    if inline:
        source = f"env:{ENV_TENANT_CATALOG_YAML}"
        try:
            catalog = _parse_catalog_yaml_text(inline)
        except (
            yaml.YAMLError,
            DuplicateTenantError,
            UnknownTenantReferenceError,
            InvalidPrefixError,
            DuplicateWorkflowSubdirError,
            InvalidWorkflowSubdirError,
            UnsupportedSchemaVersionError,
        ) as exc:
            raise CatalogConfigError(
                f"tenant catalog at {source} could not be parsed: {exc}"
            ) from exc
        _transport_catalog_cache = (catalog, "env")
        return _transport_catalog_cache

    path = os.environ.get(ENV_TENANT_CATALOG_PATH)
    if path:
        source = f"file:{path}"
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            raise CatalogConfigError(
                f"tenant catalog at {source} could not be read: {exc}"
            ) from exc
        try:
            catalog = _parse_catalog_yaml_text(text)
        except (
            yaml.YAMLError,
            DuplicateTenantError,
            UnknownTenantReferenceError,
            InvalidPrefixError,
            DuplicateWorkflowSubdirError,
            InvalidWorkflowSubdirError,
            UnsupportedSchemaVersionError,
        ) as exc:
            raise CatalogConfigError(
                f"tenant catalog at {source} could not be parsed: {exc}"
            ) from exc
        _transport_catalog_cache = (catalog, "file")
        return _transport_catalog_cache

    source = f"file:{default_path}"
    try:
        text = Path(default_path).read_text(encoding="utf-8")
    except OSError as exc:
        raise CatalogConfigError(
            f"tenant catalog at {source} could not be read: {exc}"
        ) from exc
    try:
        catalog = _parse_catalog_yaml_text(text)
    except (
        yaml.YAMLError,
        DuplicateTenantError,
        UnknownTenantReferenceError,
        InvalidPrefixError,
        DuplicateWorkflowSubdirError,
        InvalidWorkflowSubdirError,
        UnsupportedSchemaVersionError,
    ) as exc:
        raise CatalogConfigError(
            f"tenant catalog at {source} could not be parsed: {exc}"
        ) from exc
    _transport_catalog_cache = (catalog, "builtin")
    return _transport_catalog_cache


def _reset_transport_catalog_cache_for_tests() -> None:
    """Clear the memoized transport catalog so a test can re-load.

    Test-only. Production code never needs to invalidate this cache
    within one process lifetime -- the transport chain is read once at
    first use, matching the design's "read once, memoize" rule.
    """
    global _transport_catalog_cache
    _transport_catalog_cache = None


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
