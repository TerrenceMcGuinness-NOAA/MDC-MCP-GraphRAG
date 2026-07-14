"""Single scope-aware collection-naming authority.

rag-data-plane-gap-closure Requirement 3. This is the ONE function every
ingester, the reset tool, and the Work_Matrix builder route through to derive a
physical collection/index name — so names can never drift apart again.

Naming rule
-----------
``mdc-{domain}-{profile}{suffix}`` where:

* ``domain``  — the logical content domain: ``workflow-docs``, ``code-context``,
  ``jjobs``, ``ee2-standards``, ``community-summaries``. These are the exact
  domains the serving layer resolves to (see
  ``src.config.aws_config.PRODUCTION_INDICES_BY_PROFILE``).
* ``profile`` — the ACTIVE embedding profile short-name (``mpnet768`` on COTS,
  ``titan1024`` on AWS), taken from ``MCP_EMBEDDING_PROFILE``. This is
  profile-derived, NOT hard-coded — resolving the historical
  ``titan1024``→``mpnet768`` mismatch on COTS (Correction C8).
* ``suffix``  — empty for the default serving version (so serving collection
  names stay byte-for-byte stable, R3.2/R9), else ``-{version}``.

Scope
-----
* ``shared``  → NWS-wide content (docs, EE2 standards, community summaries):
  ONE unprefixed collection regardless of the tenant argument (R3.4).
* ``tenant``  → per (repo, branch) content (code, jjobs, config-derived):
  ``{tenant.index_prefix}`` prepended.

The default serving version and profile reproduce the live physical names
(e.g. shared docs → ``mdc-workflow-docs-mpnet768``; gw_v17 code →
``gw_v17_mdc-code-context-mpnet768``), so routing the ingesters through this
function aligns the write side with the serving side without touching
``resolve_index`` (R9).
"""

from __future__ import annotations

import os
from typing import Any

#: Default (serving) collection version — an empty version suffix. Kept in
#: lock-step with ``scripts/_ingest_common.DEFAULT_COLLECTION_VERSION`` (which
#: imports this value so there is a single source of truth).
DEFAULT_COLLECTION_VERSION: str = "v8-0-0"

#: Fallback embedding-profile short-name when ``MCP_EMBEDDING_PROFILE`` is
#: unset. COTS default is the local all-mpnet-base-v2 (768-dim) profile.
DEFAULT_EMBEDDING_PROFILE: str = "mpnet768"

#: The five content domains, matching the serving-side physical index domains.
DOMAIN_WORKFLOW_DOCS = "workflow-docs"
DOMAIN_CODE_CONTEXT = "code-context"
DOMAIN_JJOBS = "jjobs"
DOMAIN_EE2_STANDARDS = "ee2-standards"
DOMAIN_COMMUNITY_SUMMARIES = "community-summaries"

_VALID_SCOPES = frozenset({"shared", "tenant"})


def active_embedding_profile(explicit: str | None = None) -> str:
    """Resolve the active embedding-profile short-name.

    Precedence: explicit argument > ``MCP_EMBEDDING_PROFILE`` env var >
    :data:`DEFAULT_EMBEDDING_PROFILE`.
    """
    return explicit or os.environ.get("MCP_EMBEDDING_PROFILE") or DEFAULT_EMBEDDING_PROFILE


def _version_suffix(version: str | None) -> str:
    """Return ``""`` for the default serving version, else ``-{version}``."""
    if not version or version == DEFAULT_COLLECTION_VERSION:
        return ""
    return f"-{version}"


def resolve_collection_name(
    *,
    domain: str,
    scope: str,
    tenant: Any = None,
    version: str | None = None,
    profile: str | None = None,
) -> str:
    """Return the physical collection/index name for one source (R3).

    Parameters
    ----------
    domain
        Logical content domain (e.g. ``"workflow-docs"``, ``"code-context"``).
    scope
        ``"shared"`` (unprefixed, NWS-wide) or ``"tenant"`` (prefixed with the
        active tenant's ``index_prefix``).
    tenant
        The active :class:`~src.config.tenants.Tenant` (or any object exposing
        ``index_prefix``). Ignored for ``shared`` scope (R3.4). ``None`` /
        empty prefix yields the unprefixed name (the default ``gw`` tenant).
    version
        Collection_Version. The default serving version drops the suffix so
        serving names stay byte-for-byte stable (R3.2).
    profile
        Embedding-profile short-name override; defaults to the active profile
        (:func:`active_embedding_profile`).
    """
    if scope not in _VALID_SCOPES:
        raise ValueError(
            f"resolve_collection_name: invalid scope {scope!r} "
            f"(expected one of {sorted(_VALID_SCOPES)})"
        )
    prof = active_embedding_profile(profile)
    base = f"mdc-{domain}-{prof}{_version_suffix(version)}"
    if scope == "shared":
        return base
    prefix = getattr(tenant, "index_prefix", "") if tenant is not None else ""
    return f"{prefix}{base}"


__all__ = [
    "DEFAULT_COLLECTION_VERSION",
    "DEFAULT_EMBEDDING_PROFILE",
    "DOMAIN_WORKFLOW_DOCS",
    "DOMAIN_CODE_CONTEXT",
    "DOMAIN_JJOBS",
    "DOMAIN_EE2_STANDARDS",
    "DOMAIN_COMMUNITY_SUMMARIES",
    "active_embedding_profile",
    "resolve_collection_name",
]
