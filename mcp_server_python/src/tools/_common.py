"""Shared tool-layer helpers.

Small, dependency-light utilities imported by multiple tool modules.
Currently hosts the missing-index detection + skip-rendering helpers
introduced by the ``graceful-missing-index-handling`` spec (widened by
``shared-scope-query-routing`` Task 4.3 to also accept the backend-
normalized ``CollectionNotProvisionedError``), plus a tiny tenant-id
accessor.

These helpers are intentionally pure and free of any data-layer
*adapter* import at module load so the unit tests do not require the AWS
SDK. ``src.data.vector_errors`` is safe to import here because it is
itself dependency-light (stdlib only, no adapters, no network).
"""

from __future__ import annotations

from typing import Any, Iterable

from src.data.vector_errors import CollectionNotProvisionedError
from src.tenancy.resolver import get_current_tenant_or_none

__all__ = [
    "_is_missing_index_exc",
    "_missing_index_skip",
    "_tenant_id_or_none",
    "_zero_hit_scope_note",
]


def _is_missing_index_exc(exc: BaseException) -> bool:
    """Return True iff ``exc`` signals a missing/unprovisioned collection.

    Widened (shared-scope-query-routing R4.3, R4.6, R6.2) to accept the
    backend-normalized :class:`~src.data.vector_errors.
    CollectionNotProvisionedError` that both Vector_Adapters now raise on
    collection absence, in addition to the pre-existing OpenSearch-specific
    detection below. Widening rather than replacing keeps the four existing
    call sites (``semantic_search._tool_search_documentation``,
    ``graph_rag._tool_search_architecture``,
    ``graph_rag._tool_find_similar_code``,
    ``operational._tool_get_operational_guidance``) working unchanged.

    Detects two equivalent forms for the OpenSearch case:

    * The structured opensearchpy ``NotFoundError`` whose
      ``info['error']['type']`` is ``index_not_found_exception``.
    * The string-fallback case where the exception's ``str()`` form
      contains the literal token ``index_not_found_exception`` (covers
      the case where the upstream wraps the original error before it
      reaches the tool layer).

    The opensearchpy import is wrapped in ``try/except ImportError`` so
    the helper works in environments that do not pull the AWS SDK
    (Requirement 1.3).
    """
    if isinstance(exc, CollectionNotProvisionedError):
        return True

    try:
        from opensearchpy.exceptions import NotFoundError  # type: ignore
    except ImportError:  # pragma: no cover - dev/test path without the SDK
        NotFoundError = None  # type: ignore[assignment]

    if NotFoundError is not None and isinstance(exc, NotFoundError):
        info = getattr(exc, "info", None) or {}
        err = info.get("error") if isinstance(info, dict) else None
        if isinstance(err, dict) and err.get("type") == "index_not_found_exception":
            return True

    return "index_not_found_exception" in str(exc)


def _missing_index_skip(
    *,
    tool: str,
    query: str,
    collection: str,
    tenant_id: str | None,
) -> str:
    """Return the standardised ``[INFO]`` Skip_Block markdown.

    A genuine missing-index condition is a configuration state, not a
    runtime failure, so it is rendered with ``[INFO]`` (not ``[ERROR]``)
    mirroring the existing ``[INFO] Script content is not available ...``
    precedent. ASCII-only, no payloads or stack traces (Requirement 2.5).
    """
    tid = tenant_id or "gw"
    coll_short = collection.split("/")[-1]  # cosmetic strip
    return (
        f"[INFO] {tool}: no results\n"
        f"\n"
        f"Collection '{coll_short}' is not provisioned for tenant "
        f"'{tid}'.\n"
        f"Tip: use `get_knowledge_base_status(tenant_id=\"{tid}\")` to list "
        f"collections that ARE provisioned for this tenant.\n"
    )


def _tenant_id_or_none() -> str | None:
    """Return the active tenant's id, or ``None`` outside a tenant scope."""
    ctx = get_current_tenant_or_none()
    if ctx is None:
        return None
    tenant = getattr(ctx, "tenant", None)
    return getattr(tenant, "tenant_id", None) if tenant is not None else None


async def _zero_hit_scope_note(
    vector_db: Any,
    *,
    tenant: Any,
    collections: "str | Iterable[str]",
    profile: str | None = None,
) -> list[str]:
    """Return the R7.7 zero-hit annotation lines, or ``[]`` if inapplicable.

    shared-scope-query-routing Task 7.5 (Requirements 6.6, 6.8, 7.7).

    When a read returns zero hits, this names each addressed
    Physical_Collection that is ``unprovisioned`` or ``provisioned-empty``
    together with its Collection_Scope, so a structural blind spot -- a
    tenant that cannot reach content that exists, or an empty collection --
    is distinguishable from a genuine absence of matching content.

    Gated on a non-empty ``tenant.index_prefix`` (R6.8): under the
    Default_Tenant ``gw`` this returns ``[]`` WITHOUT touching the backend,
    so the rendered zero-hit body stays byte-equivalent and the condition
    is left to the log channel. The returned lines are a plain body note,
    never a Routing_Diagnostic -- the ``[routing]`` diagnostic string is
    confined to ``log.info`` and never appears in tool output (R6.6).

    Parameters
    ----------
    vector_db
        The active Vector_Adapter (has ``collection_condition``).
    tenant
        The resolved active tenant, or ``None`` for the Default_Tenant.
    collections
        One Logical_Collection, or an iterable of them (for a
        multi-collection read).
    profile
        Embedding_Profile short name; defaults to the router's own
        default (``MCP_EMBEDDING_PROFILE``).
    """
    index_prefix = (
        getattr(tenant, "index_prefix", "") if tenant is not None else ""
    )
    if not index_prefix:
        return []
    if vector_db is None:
        return []

    if isinstance(collections, str):
        logicals: list[str] = [collections]
    else:
        logicals = list(collections)

    # Imported lazily so this module stays free of a data-layer *adapter*
    # import at load time; ``read_router`` is dependency-light (stdlib +
    # config) and imports no adapter.
    from src.data.read_router import resolve_read_targets

    flagged: list[tuple[str, str, str]] = []  # (physical, scope, condition)
    seen: set[str] = set()
    for logical in logicals:
        try:
            resolved = resolve_read_targets(logical, tenant, profile=profile)
        except Exception:  # pragma: no cover - defensive
            continue
        for target in resolved.targets:
            if target.physical in seen:
                continue
            seen.add(target.physical)
            try:
                condition = await vector_db.collection_condition(
                    target.physical
                )
            except Exception:  # pragma: no cover - never break a render
                continue
            cond_value = getattr(condition, "value", str(condition))
            if cond_value in ("unprovisioned", "provisioned-empty"):
                flagged.append((target.physical, target.scope, cond_value))

    if not flagged:
        return []

    tid = getattr(tenant, "tenant_id", None) or "gw"
    lines = [
        "",
        (
            f"Note: this zero-hit result for tenant '{tid}' reflects an "
            "unreachable or empty collection rather than an absence of "
            "matching content:"
        ),
    ]
    for physical, scope, cond_value in flagged:
        lines.append(f"- {physical} ({scope}): {cond_value}")
    return lines
