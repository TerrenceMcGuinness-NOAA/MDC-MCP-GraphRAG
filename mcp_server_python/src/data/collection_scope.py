"""Single authority for Collection_Scope and Hybrid_Domain membership.

shared-scope-query-routing Requirement 1. Read-path counterpart to
``src/data/collection_namer.py``: that module receives a scope per source
from the ingesters (each ingester passes a literal ``scope="shared"`` or
``scope="tenant"``), this one answers what the scope of a logical
collection is when a reader -- an adapter, the status reporter, the
integrity checker, or the health reporter -- needs to decide.

Import boundary (Requirement 12.6)
-----------------------------------
This module imports the standard library only. Nothing from this
repository -- no ``read_router``, no Vector_Adapter, no ``src.tools``
module. That is exactly what lets both the read path (this change) and,
potentially, the write path (NOT wired in this change -- see below)
consume it without a dependency cycle. Enforced by a unit test in
``tests/unit/test_collection_scope.py``.

The write path is NOT re-pointed at this module in this change.
Requirement 12.2 freezes every file under ``mcp_server_python/scripts/``
byte-for-byte, including ``_ingest_common.py``, which re-exports
``resolve_collection_name``. Each ingester already passes ``scope`` as a
literal, so ``collection_namer.py`` needs no lookup table -- adoption of
this module by the write side is a future, independently-decided step,
not part of this change.

Two design points worth restating here because they shape the API:

1. :func:`check_scope_consistency` reads
   ``src/config/unified_manifest.json`` directly with ``json.load``,
   deliberately NOT through ``src.manifest.loader.load_manifest``. That
   loader catches ``JSONDecodeError``, ``OSError``, and ``ValueError``,
   falls back to ``documentation_sources.json``, and on further failure
   returns an *empty* registry so callers can boot degraded. Routing this
   check through it would mean a corrupt manifest silently reports zero
   findings -- exactly the failure mode this check exists to catch. An
   unreadable or unparsable manifest is itself a finding here, never an
   exception.
2. The Hybrid_Domain invariant ("every hybrid member must classify
   ``shared``") is asserted at **import time**, not at query time. A
   future mistake then fails the process at load, where it is obvious,
   rather than surfacing as a wrong query result months later.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Final, Literal

CollectionScope = Literal["shared", "tenant"]

SCOPE_SHARED: Final[CollectionScope] = "shared"
SCOPE_TENANT: Final[CollectionScope] = "tenant"

_VALID_SCOPES: Final[frozenset[str]] = frozenset({SCOPE_SHARED, SCOPE_TENANT})

#: Authoritative Logical_Collection -> Collection_Scope table (R1.2).
#: Keys are exactly the keys of every inner map in
#: ``PRODUCTION_INDICES_BY_PROFILE``
#: (``src/config/aws_config.py``). Cross-checked against the
#: ``(collection_target, scope)`` pairs of all 67 sources in
#: ``src/config/unified_manifest.json`` by :func:`check_scope_consistency`.
_BUILTIN_SCOPES: Final[dict[str, CollectionScope]] = {
    "global-workflow-docs-v8-0-0": SCOPE_SHARED,
    "ee2-standards-v5-0-0-enhanced": SCOPE_SHARED,
    "community-summaries": SCOPE_SHARED,
    "code-with-context-v8-0-0": SCOPE_TENANT,
    "jjobs-v8-0-0": SCOPE_TENANT,
}

#: Shared collections that ALSO carry per-tenant content (R1.8).
#: ``global-workflow-docs-v8-0-0`` qualifies because its
#: ``global-workflow-rst`` source reads repo-local ``docs/**/*.rst``,
#: which varies per branch. Members must be ``shared``; enforced below,
#: at import time.
_BUILTIN_HYBRID: Final[frozenset[str]] = frozenset(
    {"global-workflow-docs-v8-0-0"}
)

#: Manifest ``source_type`` values that read the on-disk repo tree rather
#: than an external URL. Used only by :func:`check_scope_consistency`'s
#: hybridity-drift expectation -- a ``shared`` collection is expected to
#: be a Hybrid_Domain exactly when it has an enabled source of one of
#: these types. Today that is ``global-workflow-rst`` alone
#: (``source_type: on_disk_submodule``).
_REPO_LOCAL_SOURCE_TYPES: Final[frozenset[str]] = frozenset(
    {"on_disk_submodule"}
)

#: Environment variable names for the optional override transport (R5.7).
ENV_SCOPE_JSON: Final[str] = "MCP_COLLECTION_SCOPE_JSON"
ENV_SCOPE_PATH: Final[str] = "MCP_COLLECTION_SCOPE_PATH"

_OVERRIDE_SCHEMA_VERSION: Final[int] = 1


class ScopeConfigError(RuntimeError):
    """Raised when an override transport cannot be read or parsed (R5.6).

    This is the hard-error path: a configuration source exists and is
    unreadable or malformed. The caller must resolve nothing, issue no
    read, and never degrade to treating every Logical_Collection as
    ``tenant`` -- that silent fallback is precisely the defect this
    module exists to prevent from recurring. The Read_Router's R1.5
    unknown-identifier fallback is a separate, later-stage concern that
    is only reachable once a table has loaded successfully; see the
    module docstring and ``read_router.py`` (Task 2).
    """


@dataclass(frozen=True, slots=True)
class _ScopeTable:
    """One resolved (scopes, hybrid) table plus the transport it came from."""

    scopes: dict[str, CollectionScope]
    hybrid: frozenset[str]
    transport: str  # "builtin" | "env" | "file"


def _validate_override(
    raw: dict[str, Any], *, source: str
) -> tuple[dict[str, CollectionScope], frozenset[str]]:
    """Validate an override document's shape and return its tables.

    Parameters
    ----------
    raw
        Parsed JSON content of the override document.
    source
        Human-readable description of where ``raw`` came from, used in
        the raised error message so an operator can locate the failing
        configuration source.

    Returns
    -------
    tuple[dict[str, CollectionScope], frozenset[str]]
        The validated ``(scopes, hybrid_domains)`` pair.

    Raises
    ------
    ScopeConfigError
        On any schema violation, naming ``source`` and the violation.
    """
    if not isinstance(raw, dict):
        raise ScopeConfigError(
            f"collection scope override at {source} is not a JSON object"
        )

    schema_version = raw.get("schema_version")
    if schema_version != _OVERRIDE_SCHEMA_VERSION:
        raise ScopeConfigError(
            f"collection scope override at {source} has unsupported "
            f"schema_version {schema_version!r}; expected "
            f"{_OVERRIDE_SCHEMA_VERSION!r}"
        )

    raw_scopes = raw.get("scopes")
    if not isinstance(raw_scopes, dict) or not raw_scopes:
        raise ScopeConfigError(
            f"collection scope override at {source} has a missing or "
            f"empty 'scopes' map"
        )

    scopes: dict[str, CollectionScope] = {}
    for collection, scope_value in raw_scopes.items():
        if not isinstance(collection, str) or not collection:
            raise ScopeConfigError(
                f"collection scope override at {source} has a non-string "
                f"or empty collection key: {collection!r}"
            )
        if scope_value not in _VALID_SCOPES:
            raise ScopeConfigError(
                f"collection scope override at {source} declares scope "
                f"{scope_value!r} for {collection!r}; must be one of "
                f"{sorted(_VALID_SCOPES)}"
            )
        scopes[collection] = scope_value  # type: ignore[assignment]

    raw_hybrid = raw.get("hybrid_domains", [])
    if not isinstance(raw_hybrid, list):
        raise ScopeConfigError(
            f"collection scope override at {source} has a non-list "
            f"'hybrid_domains' value: {raw_hybrid!r}"
        )

    hybrid_set: set[str] = set()
    for entry in raw_hybrid:
        if entry not in scopes:
            raise ScopeConfigError(
                f"collection scope override at {source} declares "
                f"hybrid_domains entry {entry!r} that is not present in "
                f"'scopes'"
            )
        if scopes[entry] != SCOPE_SHARED:
            raise ScopeConfigError(
                f"collection scope override at {source} declares "
                f"hybrid_domains entry {entry!r} with scope "
                f"{scopes[entry]!r}; every Hybrid_Domain member must be "
                f"classified {SCOPE_SHARED!r}"
            )
        hybrid_set.add(entry)

    return scopes, frozenset(hybrid_set)


def _load_override() -> _ScopeTable | None:
    """Resolve the active override table, or ``None`` for the built-in.

    Precedence: inline JSON content (:data:`ENV_SCOPE_JSON`), then a
    JSON file path (:data:`ENV_SCOPE_PATH`), then ``None`` to signal
    "use the built-in tables". An override **replaces both tables
    wholesale** rather than merging, so the active classification is
    always readable from one document.

    Raises
    ------
    ScopeConfigError
        If either environment variable is set but its content cannot
        be read or parsed as valid JSON, or fails schema validation
        (R5.6).
    """
    inline = os.environ.get(ENV_SCOPE_JSON)
    if inline:
        source = f"env:{ENV_SCOPE_JSON}"
        try:
            raw = json.loads(inline)
        except json.JSONDecodeError as exc:
            raise ScopeConfigError(
                f"collection scope override at {source} is not valid "
                f"JSON: {exc}"
            ) from exc
        scopes, hybrid = _validate_override(raw, source=source)
        return _ScopeTable(scopes=scopes, hybrid=hybrid, transport="env")

    path = os.environ.get(ENV_SCOPE_PATH)
    if path:
        source = f"file:{path}"
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except OSError as exc:
            raise ScopeConfigError(
                f"collection scope override at {source} could not be "
                f"read: {exc}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise ScopeConfigError(
                f"collection scope override at {source} is not valid "
                f"JSON: {exc}"
            ) from exc
        scopes, hybrid = _validate_override(raw, source=source)
        return _ScopeTable(scopes=scopes, hybrid=hybrid, transport="file")

    return None


def _builtin_table() -> _ScopeTable:
    """Return the built-in table, wrapped as a :class:`_ScopeTable`."""
    return _ScopeTable(
        scopes=dict(_BUILTIN_SCOPES),
        hybrid=_BUILTIN_HYBRID,
        transport="builtin",
    )


#: Memoized active table. Populated on first use by :func:`_active_table`
#: so an override is read (and, if invalid, raises) at most once per
#: process -- the no-per-resolution-I/O guarantee (R5.1, P9) depends on
#: this being read once and reused, not re-read on every call.
_active_table_cache: _ScopeTable | None = None


def _active_table() -> _ScopeTable:
    """Return the memoized active scope table, loading it on first use."""
    global _active_table_cache
    if _active_table_cache is None:
        override = _load_override()
        _active_table_cache = (
            override if override is not None else _builtin_table()
        )
    return _active_table_cache


def _reset_active_table_cache_for_tests() -> None:
    """Clear the memoized table so a test can change the env and re-load.

    Test-only. Production code never needs to invalidate the cache
    within one process lifetime -- the override transport is read once
    at first use, matching the design's "read once, memoize" rule.
    """
    global _active_table_cache
    _active_table_cache = None


def scope_of(collection: str) -> CollectionScope | None:
    """Return the Collection_Scope of ``collection``, or ``None``.

    Parameters
    ----------
    collection
        A Logical_Collection identifier, e.g.
        ``"global-workflow-docs-v8-0-0"``.

    Returns
    -------
    CollectionScope or None
        ``"shared"`` or ``"tenant"`` for a recognised Logical_Collection.
        ``None`` means the identifier is not a Logical_Collection this
        module knows about -- it does **not** mean "unknown, treat as
        tenant". The Read_Router (Task 2) owns that fallback decision;
        this module only reports what it knows, so Requirement 5.6's
        hard-error path and Requirement 1.5's graceful-degradation path
        stay separable.

    Notes
    -----
    Deterministic and free of I/O and network access on every call
    after the first (R1.1): the active table is memoized by
    :func:`_active_table`.
    """
    return _active_table().scopes.get(collection)


def is_hybrid_domain(collection: str) -> bool:
    """Return True iff ``collection`` is a Hybrid_Domain (R1.8).

    A Hybrid_Domain is always also classified ``shared`` -- that
    invariant is enforced both at import time for the built-in table
    (see the module-level assertion below) and at load time for an
    override document (see :func:`_validate_override`).
    """
    return collection in _active_table().hybrid


def logical_collections() -> tuple[str, ...]:
    """Return every registered Logical_Collection, in table order.

    This is the iteration order the Status_Reporter, the
    Integrity_Checker, and the Health_Reporter rely on so their
    enumerations are reproducible across invocations (R9.1, R10.6,
    R11.1).
    """
    return tuple(_active_table().scopes.keys())


def active_scope_transport() -> str:
    """Return which Configuration_Transport supplied the active table.

    One of ``"builtin"``, ``"env"``, or ``"file"`` (R5.7). Reported by
    the Read_Router's diagnostics so a routing decision's provenance is
    never ambiguous.
    """
    return _active_table().transport


def check_scope_consistency(manifest_path: str | None = None) -> list[str]:
    """Compare this module's table against the unified manifest (R1.6).

    Reads ``manifest_path`` (default: the bundled
    ``src/config/unified_manifest.json``) directly with :func:`json.load`
    -- deliberately **not** through
    ``src.manifest.loader.load_manifest``. That loader's fallback chain
    (legacy migration, then an empty registry) exists so the server can
    boot degraded; routing this drift check through it would let a
    corrupt manifest report zero findings, which is exactly the failure
    mode this check exists to catch. Issues no network request (R1.7).

    Parameters
    ----------
    manifest_path
        Explicit path to the unified manifest JSON file. Defaults to
        the bundled ``src/config/unified_manifest.json`` alongside this
        package's ``src/config`` directory.

    Returns
    -------
    list[str]
        One human-readable finding per discrepancy, empty when the
        table and the manifest fully agree. Four finding classes:

        (a) a Logical_Collection whose Scope_Authority classification
            differs from the ``scope`` its enabled sources declare;
        (b) a non-Hybrid_Domain ``collection_target`` whose enabled
            sources declare more than one distinct ``scope``;
        (c) a source whose ``scope`` is absent or outside
            ``{shared, tenant}``;
        (d) a ``collection_target`` for which the Scope_Authority holds
            no entry.

        An unreadable or unparsable manifest is itself reported as a
        single finding, never raised as an exception.
    """
    if manifest_path is None:
        manifest_path = str(
            _default_manifest_path()
        )

    try:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except OSError as exc:
        return [
            f"unified manifest at {manifest_path!r} could not be read: {exc}"
        ]
    except json.JSONDecodeError as exc:
        return [
            f"unified manifest at {manifest_path!r} is not valid JSON: {exc}"
        ]

    if not isinstance(raw, dict):
        return [f"unified manifest at {manifest_path!r} is not a JSON object"]

    sources = raw.get("sources")
    if not isinstance(sources, list):
        return [
            f"unified manifest at {manifest_path!r} has a missing or "
            f"non-list 'sources' field"
        ]

    findings: list[str] = []
    table = _active_table()

    # Per-target: the set of distinct declared scopes among enabled
    # sources, and whether any enabled source is repo-local (drives the
    # hybridity-drift expectation).
    declared_scopes_by_target: dict[str, set[str]] = {}
    repo_local_targets: set[str] = set()
    seen_targets: set[str] = set()

    for entry in sources:
        if not isinstance(entry, dict):
            findings.append(
                f"unified manifest source entry is not a JSON object: "
                f"{entry!r}"
            )
            continue

        name = entry.get("name", "<unnamed>")
        target = entry.get("collection_target")
        scope_value = entry.get("scope")
        enabled = entry.get("enabled", True)

        if scope_value not in _VALID_SCOPES:
            findings.append(
                f"source {name!r} (collection_target={target!r}) declares "
                f"scope {scope_value!r}; must be one of "
                f"{sorted(_VALID_SCOPES)}"
            )

        if not isinstance(target, str) or not target:
            # No usable target -- nothing further to cross-check for
            # this entry, but the scope-validity finding above still
            # applies.
            continue

        seen_targets.add(target)

        if not enabled:
            continue

        if scope_value in _VALID_SCOPES:
            declared_scopes_by_target.setdefault(target, set()).add(
                scope_value
            )

        if entry.get("source_type") in _REPO_LOCAL_SOURCE_TYPES:
            repo_local_targets.add(target)

    for target, declared in declared_scopes_by_target.items():
        table_scope = table.scopes.get(target)

        if table_scope is None:
            findings.append(
                f"collection_target {target!r} has no Scope_Authority "
                f"entry (declared scope(s): {sorted(declared)})"
            )
            continue

        if table_scope not in declared:
            findings.append(
                f"collection_target {target!r} classified {table_scope!r} "
                f"by the Scope_Authority disagrees with its sources' "
                f"declared scope(s) {sorted(declared)}"
            )

        is_hybrid = target in table.hybrid
        if not is_hybrid and len(declared) > 1:
            findings.append(
                f"collection_target {target!r} is not a Hybrid_Domain but "
                f"its enabled sources declare more than one distinct "
                f"scope: {sorted(declared)}"
            )

    for target in seen_targets:
        already_reported = (
            target in table.scopes or target in declared_scopes_by_target
        )
        if not already_reported:
            findings.append(
                f"collection_target {target!r} has no Scope_Authority entry"
            )

    # Hybridity-drift expectation: a shared collection is expected to be
    # a Hybrid_Domain exactly when it has an enabled repo-local source.
    for target in repo_local_targets:
        table_scope = table.scopes.get(target)
        if table_scope == SCOPE_SHARED and target not in table.hybrid:
            findings.append(
                f"collection_target {target!r} has an enabled repo-local "
                f"source but is not classified as a Hybrid_Domain"
            )

    for hybrid_target in table.hybrid:
        if hybrid_target not in repo_local_targets:
            findings.append(
                f"collection_target {hybrid_target!r} is classified as a "
                f"Hybrid_Domain but has no enabled repo-local source in "
                f"the manifest"
            )

    return findings


def _default_manifest_path() -> str:
    """Return the bundled ``unified_manifest.json`` path.

    Mirrors ``src/manifest/loader.BUNDLED_MANIFEST_PATH`` without
    importing that module -- this module is stdlib-only (R12.6), and
    ``src/manifest/loader.py`` is not stdlib.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    # mcp_server_python/src/data/collection_scope.py
    #   -> mcp_server_python/src/config/unified_manifest.json
    src_dir = os.path.dirname(here)
    return os.path.join(src_dir, "config", "unified_manifest.json")


# ── Import-time invariant (R1.8) ────────────────────────────────────────
# Every Hybrid_Domain member must classify "shared". A future mistake
# then fails the process at load, where it is obvious, rather than
# surfacing as a silently wrong query result months later.
for _hybrid_member in _BUILTIN_HYBRID:
    if _BUILTIN_SCOPES.get(_hybrid_member) != SCOPE_SHARED:
        raise AssertionError(
            f"collection_scope: built-in Hybrid_Domain member "
            f"{_hybrid_member!r} must classify 'shared', got "
            f"{_BUILTIN_SCOPES.get(_hybrid_member)!r}"
        )
del _hybrid_member


__all__ = [
    "CollectionScope",
    "SCOPE_SHARED",
    "SCOPE_TENANT",
    "ScopeConfigError",
    "ENV_SCOPE_JSON",
    "ENV_SCOPE_PATH",
    "scope_of",
    "is_hybrid_domain",
    "logical_collections",
    "active_scope_transport",
    "check_scope_consistency",
]
