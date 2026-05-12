"""AWS region + endpoint defaults for the Python MCP server.

Kept separate from ``environment.py`` so AWS-specific constants can be
imported without triggering a full config load. Values match the active
Phase 53 deployment (see ``.kiro/steering/01-architecture-context.md``).
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

# ── OpenSearch indices (Requirement 2.4) ──────────────────────────────────
# Maps a logical collection to its MPNet-768 production index. Adapters use
# this to translate ChromaDB-style collection names into OpenSearch indices.

PRODUCTION_INDICES: dict[str, str] = {
    "code-with-context-v8-0-0":       "mdc-code-context-mpnet768",
    "global-workflow-docs-v8-0-0":    "mdc-workflow-docs-mpnet768",
    "jjobs-v8-0-0":                   "mdc-jjobs-mpnet768",
    "community-summaries":            "mdc-community-summaries-mpnet768",
    "ee2-standards-v5-0-0-enhanced":  "mdc-ee2-standards-mpnet768",
}


def resolve_index(collection: str) -> str:
    """Translate a ChromaDB collection name to an OpenSearch index name.

    Falls back to the collection name itself when no mapping exists, which
    matches the Node.js ``OpenSearchAdapter._toIndex()`` behavior.
    """
    return PRODUCTION_INDICES.get(collection, collection)
