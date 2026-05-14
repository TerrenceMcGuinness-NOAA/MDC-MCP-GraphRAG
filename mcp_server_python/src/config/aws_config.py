"""AWS region + endpoint defaults for the Python MCP server.

Kept separate from ``environment.py`` so AWS-specific constants can be
imported without triggering a full config load. Values match the active
Phase 53 deployment (see ``.kiro/steering/01-architecture-context.md``).

Phase C-2c (Bedrock-native embedding swap, Requirement 8) replaces the
single-profile ``PRODUCTION_INDICES`` map with a profile-keyed
:data:`PRODUCTION_INDICES_BY_PROFILE` so the same five logical
collections route to the matching ``mdc-{domain}-{profile}`` index for
the active embedding profile. :func:`resolve_index` now takes a
``profile_short_name`` argument (default ``"titan1024"``) and consults
the per-profile inner map.
"""

from __future__ import annotations

# ── Region + transport defaults ────────────────────────────────────────────

DEFAULT_AWS_REGION: str = "us-east-1"

DEFAULT_HOST: str = "0.0.0.0"
DEFAULT_PORT: int = 8000

# ── Known production endpoints (reference only) ───────────────────────────
# These are *not* hardcoded into the ``ServerConfig`` — they must come from
# environment variables so the same image can be deployed to other stages.
# They exist here purely as documentation / fallbacks for local dev.

KNOWN_NEPTUNE_ENDPOINT: str = (
    "wss://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s."
    "us-east-1.neptune.amazonaws.com:8182"
)
KNOWN_OPENSEARCH_ENDPOINT: str = (
    "vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com"
)

# ── OpenSearch indices (Requirement 8) ────────────────────────────────────
# Maps a logical collection to its concrete OpenSearch index, keyed by
# embedding-profile ``short_name``. The Python runtime image only ever
# selects ``titan1024`` (the new default) or ``mpnet768`` (the parity-
# debug fallback); the Nova family is reserved for a future ingestion
# phase and currently has no registered index map, so its profiles fall
# through to the collection-name passthrough.

PRODUCTION_INDICES_BY_PROFILE: dict[str, dict[str, str]] = {
    "titan1024": {
        "code-with-context-v8-0-0":      "mdc-code-context-titan1024",
        "global-workflow-docs-v8-0-0":   "mdc-workflow-docs-titan1024",
        "jjobs-v8-0-0":                  "mdc-jjobs-titan1024",
        "community-summaries":           "mdc-community-summaries-titan1024",
        "ee2-standards-v5-0-0-enhanced": "mdc-ee2-standards-titan1024",
    },
    "mpnet768": {
        "code-with-context-v8-0-0":      "mdc-code-context-mpnet768",
        "global-workflow-docs-v8-0-0":   "mdc-workflow-docs-mpnet768",
        "jjobs-v8-0-0":                  "mdc-jjobs-mpnet768",
        "community-summaries":           "mdc-community-summaries-mpnet768",
        "ee2-standards-v5-0-0-enhanced": "mdc-ee2-standards-mpnet768",
    },
    # Nova profiles intentionally have no map — see get_production_indices.
}


def get_production_indices(profile_short_name: str) -> dict[str, str]:
    """Return the index map for ``profile_short_name``.

    Falls back to ``{}`` for profiles that have no registered map (the
    Nova family today). Callers downstream of :func:`resolve_index`
    therefore see "no mapping found, pass collection through unchanged"
    when the active profile is e.g. ``nova1024`` — Requirement 8.3, 8.5.
    """
    return PRODUCTION_INDICES_BY_PROFILE.get(profile_short_name, {})


def resolve_index(collection: str, profile_short_name: str = "titan1024") -> str:
    """Translate a ChromaDB collection name to an OpenSearch index name.

    Parameters
    ----------
    collection
        Logical collection name (e.g. ``"code-with-context-v8-0-0"``).
    profile_short_name
        Active embedding-profile alias from
        :class:`src.data.embedding_registry.EmbeddingModelRegistry`.
        Defaults to ``"titan1024"`` so legacy callers that pass a
        single positional argument continue to work and pick up the
        new production indices automatically.

    Returns
    -------
    The matching ``mdc-{domain}-{profile}`` index name when both
    ``profile_short_name`` and ``collection`` are registered;
    otherwise the ``collection`` argument unchanged. The latter
    behavior covers Nova profiles (no registered map) and any
    non-production collection — Requirement 8.3, 8.4.
    """
    return get_production_indices(profile_short_name).get(collection, collection)
