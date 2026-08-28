"""Read_Router -- one resolver for all four read-path consumer paths.

shared-scope-query-routing Requirement 1-7. This module maps a
``(Logical_Collection, Tenant, Embedding_Profile)`` triple to the ordered
set of Physical_Collections a read should address, and is the single
component that applies a tenant ``index_prefix`` on the read path (R4.2).

Both Vector_Adapters' ``query`` (Task 7.3), the Status_Reporter, the
Integrity_Checker, and the Health_Reporter (Tasks 10-11) consume it, so
all four defect manifestations named in the design converge on one
resolver. **Nothing calls it yet at this step** -- Task 7.3 wires the
adapters in; Task 2 (this step) delivers the resolver and its tests.

Design invariants this module upholds
-------------------------------------
1. **Resolve the physical name first, then prepend the prefix.** The
   physical name comes from :func:`src.config.aws_config.resolve_index`;
   the ``index_prefix`` is prepended to *that*, never to the logical
   identifier. Prefixing the logical identifier is the exact bug
   ``opensearch-tenant-resolution-fix`` removed once
   (``gw_v17_code-with-context-v8-0-0`` instead of
   ``gw_v17_mdc-code-context-titan1024``); it is not reintroduced here.
2. **``targets`` is an ordered tuple, not a Python ``set``.** R3.1
   requires the unprefixed member first for a Hybrid_Domain and R3.7's
   tie-break reads member position, so ordering is load-bearing.
   Distinctness is enforced by ``physical`` at construction rather than
   by set semantics.
3. **``Tenant`` is passed explicitly; the tenancy ``ContextVar`` is
   never read.** Both adapters already accept ``tenant=`` and every tool
   already passes ``_tenant()``, so the explicit form is the smaller
   change and keeps the resolver a pure function of its arguments -- the
   Hypothesis suite (P9) depends on that purity. ``tenant=None`` remains
   the unprefixed default.
4. **Pure: no network request, no collection-existence probe, no
   filesystem read** (R5.1, P9). A resolution is a frozen-dict lookup, a
   frozenset membership test, a ``PRODUCTION_INDICES_BY_PROFILE`` lookup,
   a string concatenation, and one ``os.environ`` read for the profile
   default. The Collection_Condition probe (Task 7.2) happens strictly
   *after* resolution, during the read, and is not part of this module.

The R1.5 unknown-identifier fallback lives here and never raises: an
identifier the Scope_Authority does not classify is treated as
``tenant``, yields one prefixed member, and emits a diagnostic. It cannot
mask a configuration failure, because an invalid override raises
:class:`~src.data.collection_scope.ScopeConfigError` inside
``collection_scope`` before this module is ever called -- a load failure
structurally cannot arrive here as a fallback (see the module docstring
of ``collection_scope.py``).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from src.config.aws_config import get_production_indices, resolve_index
from src.data.collection_namer import (
    DEFAULT_EMBEDDING_PROFILE,
    active_embedding_profile,
)
from src.data.collection_scope import (
    SCOPE_SHARED,
    SCOPE_TENANT,
    CollectionScope,
    active_scope_transport,
    is_hybrid_domain,
    logical_collections,
    scope_of,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from src.config.tenants import Tenant

log = logging.getLogger(__name__)

#: Profile short-name used when neither an explicit ``profile`` argument
#: nor ``MCP_EMBEDDING_PROFILE`` is supplied. Deferred to
#: :data:`src.data.collection_namer.DEFAULT_EMBEDDING_PROFILE`, the same
#: authority the write path uses, so the read path cannot address a
#: profile the write path did not write (P7, write-read round trip).
#:
#: An earlier revision pinned the literal ``"titan1024"`` on the grounds
#: that the router is backend-blind (P3) and so cannot consult
#: ``DB_BACKEND`` for a per-backend default. Backend-blindness is right,
#: but ``titan1024`` is not a neutral literal -- it is
#: :func:`src.config.aws_config.resolve_index`'s default precisely
#: because that function is an *OpenSearch* name translator. Adopting it
#: made the router silently AWS-biased: with ``MCP_EMBEDDING_PROFILE``
#: unset the write side resolved ``mpnet768`` while the read side
#: resolved ``titan1024``, so a COTS read addressed
#: ``mdc-code-context-titan1024`` for content written to
#: ``mdc-code-context-mpnet768``. Deferring to the naming SPOT keeps the
#: router backend-blind AND agreeing with the writer.
#:
#: Both deployed form factors set ``MCP_EMBEDDING_PROFILE`` explicitly
#: (``scripts/run_mcp_stdio.sh`` exports ``mpnet768`` on COTS; the
#: AgentCore runtime carries ``titan1024``), so this default governs only
#: embedded and test callers -- which is exactly where a silent
#: cross-backend mismatch would go unnoticed.
_DEFAULT_PROFILE: Final[str] = DEFAULT_EMBEDDING_PROFILE

#: Label recorded for the ``tenant=None`` unprefixed default. The
#: Default_Tenant is ``gw`` by definition (requirements Glossary), whose
#: ``index_prefix`` is the empty string; ``tenant=None`` is the router's
#: convenience spelling of that same unprefixed default.
_DEFAULT_TENANT_ID: Final[str] = "gw"

#: Diagnostic classification tokens (R1.5, R2.8, R7.3-R7.5). Carried on
#: the :class:`RoutingDiagnostic`, never in a tool response body.
CLASSIFICATION_TENANT_FALLBACK: Final[str] = "tenant-fallback"
CLASSIFICATION_UNMAPPED_PROFILE: Final[str] = "unmapped-profile"
CLASSIFICATION_ROUTING_MISCONFIGURATION: Final[str] = (
    "routing-misconfiguration"
)

#: R7.6 caps a rendered diagnostic at 1000 characters. The marker is
#: appended after truncation so the total never exceeds the cap.
_DIAG_MAX_CHARS: Final[int] = 1000
_DIAG_TRUNCATION_MARKER: Final[str] = "...[truncated]"


# ── data models (Task 2.1) ──────────────────────────────────────────────


class CollectionCondition(StrEnum):
    """Per-read classification of one addressed Physical_Collection (R7.8).

    Defined here; the classifier that returns it is implemented on the
    adapters by Task 7.2. ``PROVISIONED_POPULATED`` is assigned when the
    collection holds documents *even if the query matched none*, which is
    R7.8's explicit disambiguation and the reason the value cannot be
    inferred from hit count alone.
    """

    UNPROVISIONED = "unprovisioned"
    PROVISIONED_EMPTY = "provisioned-empty"
    PROVISIONED_POPULATED = "provisioned-populated"


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    """One Physical_Collection a read should address.

    Attributes
    ----------
    physical
        The concrete index/collection name, e.g.
        ``"gw_v17_mdc-workflow-docs-titan1024"``.
    scope
        The Collection_Scope of the Logical_Collection this target
        resolved from.
    prefixed
        Whether ``physical`` carries the active Tenant's ``index_prefix``.
    """

    physical: str
    scope: CollectionScope
    prefixed: bool


@dataclass(frozen=True, slots=True)
class ResolvedCollectionSet:
    """Ordered result of one ``(logical, tenant, profile)`` resolution.

    ``targets`` is ordered, not a Python ``set``: R3.1 requires the
    unprefixed member first for a Hybrid_Domain and R3.7's tie-break
    reads member position. "Set" in the requirements' vocabulary means
    "collection of distinct members"; distinctness by ``physical`` is
    enforced at construction rather than leaned on set semantics for.
    """

    logical: str
    scope: CollectionScope
    hybrid: bool
    tenant_id: str
    index_prefix: str
    profile: str
    targets: tuple[ResolvedTarget, ...]
    fallback_applied: bool = False
    unmapped_profile: bool = False

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for target in self.targets:
            if target.physical in seen:
                raise ValueError(
                    f"ResolvedCollectionSet for {self.logical!r} has a "
                    f"duplicate physical collection {target.physical!r}; "
                    f"members must be distinct by physical name"
                )
            seen.add(target.physical)

    @property
    def physical_names(self) -> tuple[str, ...]:
        """Return the ordered physical names of every member."""
        return tuple(target.physical for target in self.targets)


@dataclass(frozen=True, slots=True)
class TenantCollectionSet:
    """Union of a Tenant's Resolved_Collection_Sets (R1.4, P8).

    The single answer to "which Physical_Collections belong to Tenant T",
    consumed by the Status_Reporter, the Integrity_Checker, and the
    Health_Reporter so all three agree with the query path. Members are
    de-duplicated by physical name and ordered by
    :func:`~src.data.collection_scope.logical_collections` then by
    within-set position, so repeated invocations enumerate identically.
    """

    tenant_id: str
    index_prefix: str
    profile: str
    targets: tuple[ResolvedTarget, ...]
    by_logical: Mapping[str, tuple[str, ...]]

    @property
    def physical_names(self) -> tuple[str, ...]:
        """Return the ordered physical names of every member."""
        return tuple(target.physical for target in self.targets)


@dataclass(frozen=True, slots=True)
class RoutingDiagnostic:
    """One log-channel-only record of a routing decision (R7.2, R7.6).

    R7.6's constraints are enforced inside :meth:`render`, not at call
    sites: an explicit ASCII encode check, a 1000-character cap with a
    truncation marker, and a field whitelist. The record structurally
    cannot carry query text or document content because neither is a
    field -- keep it that way. Diagnostics go to the log channel only,
    never into a rendered tool response body.
    """

    tenant_id: str
    logical: str
    profile: str
    #: One ``(physical_name, scope, prefixed)`` triple per addressed member.
    members: tuple[tuple[str, CollectionScope, bool], ...]
    #: Which Configuration_Transport supplied the scope table (R5.7):
    #: ``"builtin"``, ``"env"``, or ``"file"``.
    transport: str
    classification: str | None = None

    def render(self) -> str:
        """Render one ASCII line, at most 1000 chars, no query/doc text.

        Returns
        -------
        str
            A single-line, ASCII-only diagnostic no longer than
            :data:`_DIAG_MAX_CHARS` characters. Non-ASCII bytes in any
            field are escaped rather than emitted, and an over-long line
            is truncated with :data:`_DIAG_TRUNCATION_MARKER` so the
            R7.6 cap always holds.
        """
        parts = [
            "[routing]",
            f"tenant={self.tenant_id}",
            f"logical={self.logical}",
            f"profile={self.profile}",
            f"transport={self.transport}",
        ]
        if self.classification:
            parts.append(f"classification={self.classification}")
        member_strs = []
        for name, scope, prefixed in self.members:
            flag = "prefixed" if prefixed else "unprefixed"
            member_strs.append(f"{name}({scope},{flag})")
        parts.append("members=" + ",".join(member_strs))
        line = " ".join(parts)
        # One line only: fold any embedded newlines the field values may
        # carry (a 10 KB collection name is a legitimate test input).
        line = line.replace("\r", " ").replace("\n", " ")
        # ASCII-only (R7.6): escape any non-ASCII rather than emit it.
        line = line.encode("ascii", "backslashreplace").decode("ascii")
        # 1000-character cap with a truncation marker (R7.6).
        if len(line) > _DIAG_MAX_CHARS:
            keep = _DIAG_MAX_CHARS - len(_DIAG_TRUNCATION_MARKER)
            line = line[:keep] + _DIAG_TRUNCATION_MARKER
        return line


# ── resolution (Task 2.2) ───────────────────────────────────────────────


def _resolve_profile(profile: str | None) -> str:
    """Resolve the active Embedding_Profile short-name.

    Precedence: an explicit ``profile`` argument, then
    ``MCP_EMBEDDING_PROFILE``, then :data:`_DEFAULT_PROFILE`.

    Delegated to :func:`src.data.collection_namer.active_embedding_profile`
    rather than reimplemented, so read and write share one precedence rule
    and cannot drift apart. That call is the module's only ``os.environ``
    read and its only non-pure-lookup operation; it opens no file and no
    socket, so P9's purity guarantee is unchanged.
    """
    return active_embedding_profile(profile)


def _build_targets(
    scope: CollectionScope,
    hybrid: bool,
    physical_base: str,
    index_prefix: str,
) -> tuple[ResolvedTarget, ...]:
    """Build the ordered, distinct targets for one resolution.

    Factored out so the R7.5 post-condition (a ``shared`` set with no
    unprefixed member) is reachable in a test by substituting this
    function, without the normal construction ever producing that state.

    Cardinality follows the design's table:

    ================  ======  =============  =======  ======================
    scope             hybrid  index_prefix   members  order
    ================  ======  =============  =======  ======================
    ``shared``        no      ``""``         1        unprefixed
    ``shared``        no      ``"gw_v17_"``  1        unprefixed
    ``shared``        yes     ``""``         1        unprefixed (collapsed)
    ``shared``        yes     ``"gw_v17_"``  2        unprefixed, prefixed
    ``tenant``        n/a     ``""``         1        unprefixed
    ``tenant``        n/a     ``"gw_v17_"``  1        prefixed only
    ================  ======  =============  =======  ======================
    """
    if scope == SCOPE_SHARED:
        targets = [
            ResolvedTarget(
                physical=physical_base, scope=SCOPE_SHARED, prefixed=False
            )
        ]
        # Hybrid_Domain contributes the prefixed member only under a
        # non-empty prefix; an empty prefix collapses the pair to the
        # single unprefixed member (R6.7).
        if hybrid and index_prefix:
            targets.append(
                ResolvedTarget(
                    physical=f"{index_prefix}{physical_base}",
                    scope=SCOPE_SHARED,
                    prefixed=True,
                )
            )
        return tuple(targets)

    # tenant scope, including the R1.5 fallback which is treated as tenant.
    if index_prefix:
        return (
            ResolvedTarget(
                physical=f"{index_prefix}{physical_base}",
                scope=SCOPE_TENANT,
                prefixed=True,
            ),
        )
    return (
        ResolvedTarget(
            physical=physical_base, scope=SCOPE_TENANT, prefixed=False
        ),
    )


def _classify(
    *,
    fallback_applied: bool,
    unmapped_profile: bool,
    scope: CollectionScope,
    targets: tuple[ResolvedTarget, ...],
) -> str | None:
    """Return the single diagnostic classification for a resolution.

    Precedence: the R1.5 ``tenant-fallback`` (an unclassified identifier)
    is the primary signal; then R2.8's ``unmapped-profile`` (the active
    profile has no index map); then R7.5's ``routing-misconfiguration``
    (a ``shared`` set that somehow carries no unprefixed member). The
    three do not co-occur in normal resolution -- the precedence only
    matters for artificial inputs -- but the field is single-valued, so
    a deterministic order is fixed here.
    """
    if fallback_applied:
        return CLASSIFICATION_TENANT_FALLBACK
    if unmapped_profile:
        return CLASSIFICATION_UNMAPPED_PROFILE
    if scope == SCOPE_SHARED and not any(
        not target.prefixed for target in targets
    ):
        return CLASSIFICATION_ROUTING_MISCONFIGURATION
    return None


def _emit_diagnostic(
    result: ResolvedCollectionSet, classification: str | None
) -> None:
    """Emit exactly one Routing_Diagnostic on the log channel (R7.2, R7.6)."""
    members = tuple(
        (target.physical, target.scope, target.prefixed)
        for target in result.targets
    )
    diagnostic = RoutingDiagnostic(
        tenant_id=result.tenant_id,
        logical=result.logical,
        profile=result.profile,
        members=members,
        transport=active_scope_transport(),
        classification=classification,
    )
    log.info(diagnostic.render())


def resolve_read_targets(
    collection: str,
    tenant: "Tenant | None" = None,
    *,
    profile: str | None = None,
) -> ResolvedCollectionSet:
    """Map a ``(Logical_Collection, Tenant, Embedding_Profile)`` triple.

    Parameters
    ----------
    collection
        Logical_Collection identifier. An unrecognised identifier takes
        the R1.5 ``tenant`` fallback -- one prefixed member,
        ``fallback_applied=True``, ``classification="tenant-fallback"``
        -- and never raises.
    tenant
        The active Tenant, or ``None`` for the unprefixed default. Passed
        explicitly rather than read from the tenancy ``ContextVar`` so
        the resolver stays a pure function of its arguments (see module
        docstring).
    profile
        Embedding_Profile short name. Defaults to ``MCP_EMBEDDING_PROFILE``
        and then to :data:`_DEFAULT_PROFILE`.

    Returns
    -------
    ResolvedCollectionSet
        Ordered, unprefixed member first for a Hybrid_Domain (R3.1).

    Notes
    -----
    Pure: no network request, no collection-existence probe, no
    filesystem read (R5.1, P9). The same inputs always yield an equal
    set. Exactly one Routing_Diagnostic is emitted per call, on the log
    channel only (R7.2, R6.6).
    """
    resolved_profile = _resolve_profile(profile)
    index_prefix = tenant.index_prefix if tenant is not None else ""
    tenant_id = tenant.tenant_id if tenant is not None else _DEFAULT_TENANT_ID

    raw_scope = scope_of(collection)
    fallback_applied = raw_scope is None
    scope: CollectionScope = (
        raw_scope if raw_scope is not None else SCOPE_TENANT
    )
    hybrid = (not fallback_applied) and is_hybrid_domain(collection)

    # Resolve the physical name FIRST, then prefix its result (R2.1). An
    # unmapped profile (e.g. nova1024) or an unknown identifier passes
    # through unchanged here; the prefix is still applied to that
    # passthrough name, never to the logical identifier.
    physical_base = resolve_index(collection, resolved_profile)
    unmapped_profile = (not fallback_applied) and (
        collection not in get_production_indices(resolved_profile)
    )

    targets = _build_targets(scope, hybrid, physical_base, index_prefix)
    classification = _classify(
        fallback_applied=fallback_applied,
        unmapped_profile=unmapped_profile,
        scope=scope,
        targets=targets,
    )

    result = ResolvedCollectionSet(
        logical=collection,
        scope=scope,
        hybrid=hybrid,
        tenant_id=tenant_id,
        index_prefix=index_prefix,
        profile=resolved_profile,
        targets=targets,
        fallback_applied=fallback_applied,
        unmapped_profile=unmapped_profile,
    )
    _emit_diagnostic(result, classification)
    return result


# ── tenant-wide enumeration (Task 2.3) ──────────────────────────────────


def tenant_collection_set(
    tenant: "Tenant | None" = None,
    *,
    profile: str | None = None,
) -> TenantCollectionSet:
    """Union of :func:`resolve_read_targets` over every Logical_Collection.

    The single answer to "which Physical_Collections belong to Tenant T"
    (R1.4, P8), consumed by the Status_Reporter, the Integrity_Checker,
    and the Health_Reporter so all three agree with the query path.
    Members are de-duplicated by physical name and ordered by
    :func:`~src.data.collection_scope.logical_collections` then by
    within-set position, so repeated invocations enumerate identically.

    Under ``gw_v17`` / ``titan1024`` the set holds six members for five
    logical collections -- the Hybrid_Domain contributes two. Under the
    Default_Tenant ``gw`` it holds five.
    """
    resolved_profile = _resolve_profile(profile)
    index_prefix = tenant.index_prefix if tenant is not None else ""
    tenant_id = tenant.tenant_id if tenant is not None else _DEFAULT_TENANT_ID

    ordered_targets: list[ResolvedTarget] = []
    seen: set[str] = set()
    by_logical: dict[str, tuple[str, ...]] = {}

    for logical in logical_collections():
        resolved = resolve_read_targets(
            logical, tenant, profile=resolved_profile
        )
        by_logical[logical] = resolved.physical_names
        for target in resolved.targets:
            if target.physical not in seen:
                seen.add(target.physical)
                ordered_targets.append(target)

    return TenantCollectionSet(
        tenant_id=tenant_id,
        index_prefix=index_prefix,
        profile=resolved_profile,
        targets=tuple(ordered_targets),
        by_logical=by_logical,
    )


__all__ = [
    "CollectionCondition",
    "ResolvedTarget",
    "ResolvedCollectionSet",
    "TenantCollectionSet",
    "RoutingDiagnostic",
    "CLASSIFICATION_TENANT_FALLBACK",
    "CLASSIFICATION_UNMAPPED_PROFILE",
    "CLASSIFICATION_ROUTING_MISCONFIGURATION",
    "resolve_read_targets",
    "tenant_collection_set",
]
