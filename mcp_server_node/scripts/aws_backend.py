"""
aws_backend.py — AWS backend adapters for ingestion scripts (Phase 48D)

Provides drop-in replacements for Neo4j and ChromaDB clients that write
to Neptune (via bolt/openCypher) and OpenSearch (via bulk API) respectively.

Usage in ingestion scripts:
    from aws_backend import get_graph_driver, get_vector_client, BACKEND

    driver = get_graph_driver()   # neo4j.Driver (legacy) or Neptune bolt driver
    vector = get_vector_client()  # ChromaDB client (legacy) or OpenSearchVectorClient

Environment variables:
    DB_BACKEND          — 'legacy' (default) or 'aws'
    NEO4J_URI / NEPTUNE_ENDPOINT
    NEO4J_USER / NEO4J_PASSWORD
    CHROMADB_URL / OPENSEARCH_ENDPOINT
    AWS_REGION          — default: us-east-1
"""

import os
import json
import sys

BACKEND = os.environ.get("DB_BACKEND", "legacy")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# ── Graph driver ──────────────────────────────────────────────────────────────

def get_graph_driver():
    """Return a neo4j.Driver connected to Neo4j (legacy) or Neptune (aws)."""
    from neo4j import GraphDatabase, Auth

    if BACKEND == "aws":
        endpoint = os.environ.get("NEPTUNE_ENDPOINT", "")
        if not endpoint:
            print("[ERROR] NEPTUNE_ENDPOINT required for DB_BACKEND=aws", file=sys.stderr)
            sys.exit(1)
        bolt_uri = endpoint.replace("wss://", "bolt+s://") if endpoint.startswith("wss://") else endpoint
        # Neptune uses IAM auth — no username/password
        return GraphDatabase.driver(bolt_uri, auth=Auth("none", "", ""), encrypted=True)
    else:
        uri  = os.environ.get("NEO4J_URI",      "bolt://localhost:7687")
        user = os.environ.get("NEO4J_USER",     "neo4j")
        pwd  = os.environ.get("NEO4J_PASSWORD", "gfsworkflow2025")
        return GraphDatabase.driver(uri, auth=(user, pwd))


# ── Vector client ─────────────────────────────────────────────────────────────

# Legacy collection → OpenSearch base index mapping
COLLECTION_TO_INDEX = {
    "code-with-context-v8-0-0":      "mdc-code-context",
    "global-workflow-docs-v8-0-0":   "mdc-workflow-docs",
    "jjobs-v8-0-0":                  "mdc-jjobs",
    "community-summaries":           "mdc-community-summaries",
    "ee2-standards-v5-0-0-enhanced": "mdc-ee2-standards",
}

# Base domain → base index (for model-aware name construction)
_DOMAIN_TO_BASE_INDEX = {
    "code-with-context":      "mdc-code-context",
    "global-workflow-docs":   "mdc-workflow-docs",
    "jjobs":                  "mdc-jjobs",
    "community-summaries":    "mdc-community-summaries",
    "ee2-standards":          "mdc-ee2-standards",
}


def _to_index(collection_name: str) -> str:
    """Map a collection name to an OpenSearch index name.

    - Legacy names (no model suffix) → existing COLLECTION_TO_INDEX mapping (P9)
    - Model-aware names (e.g. 'code-with-context-v8-0-0-titan1024') →
      base-index + '-' + model-suffix (P10)

    Requirements: 3.4, 10.1, 10.2, 11.2, 11.3
    """
    # 1. Exact legacy match
    if collection_name in COLLECTION_TO_INDEX:
        return COLLECTION_TO_INDEX[collection_name]

    # 2. Model-aware: detect known model suffixes from registry
    try:
        from embedding_registry import EmbeddingModelRegistry
        known_suffixes = EmbeddingModelRegistry().list_profiles()
    except Exception:
        known_suffixes = ["mpnet768", "titan1024", "nova256", "nova512", "nova1024", "nova3072"]

    for suffix in known_suffixes:
        if collection_name.endswith(f"-{suffix}"):
            # Strip the model suffix to get the base collection name
            base_col = collection_name[: -(len(suffix) + 1)]
            # Try exact legacy lookup on base
            if base_col in COLLECTION_TO_INDEX:
                return f"{COLLECTION_TO_INDEX[base_col]}-{suffix}"
            # Try domain-prefix lookup (strip version segment)
            parts = base_col.rsplit("-", 2)  # e.g. ["code-with-context", "v8", "0-0"]
            domain = parts[0] if parts else base_col
            if domain in _DOMAIN_TO_BASE_INDEX:
                return f"{_DOMAIN_TO_BASE_INDEX[domain]}-{suffix}"
            # Fallback: use base collection name as index + suffix
            return f"{base_col}-{suffix}"

    # 3. Unknown — pass through as-is
    return collection_name


class OpenSearchVectorClient:
    """
    Minimal ChromaDB-compatible interface backed by OpenSearch.
    Supports: get_or_create_collection(), collection.add(), collection.upsert()
    Preserves MPNet embeddings bitwise — no re-generation.
    """

    def __init__(self, endpoint: str, region: str = "us-east-1"):
        from opensearchpy import OpenSearch, RequestsHttpConnection, AWSV4SignerAuth
        import boto3
        credentials = boto3.Session().get_credentials()
        auth = AWSV4SignerAuth(credentials, region, "es")
        self._client = OpenSearch(
            hosts=[{"host": endpoint.replace("https://", "").rstrip("/"), "port": 443}],
            http_auth=auth,
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection,
        )
        self._region = region
        self._embedding_fn = None

    def set_embedding_function(self, fn):
        """Set a callable(texts) -> list[list[float]] for auto-embedding."""
        self._embedding_fn = fn

    def get_collection(self, name: str, **kwargs):
        """ChromaDB-compatible get_collection (alias for get_or_create)."""
        return self.get_or_create_collection(name, **kwargs)

    def create_collection(self, name: str, **kwargs):
        """ChromaDB-compatible create_collection (alias for get_or_create)."""
        return self.get_or_create_collection(name, **kwargs)

    def get_or_create_collection(self, name: str, **kwargs):
        index = _to_index(name)
        embedding_function = kwargs.get("embedding_function") or self._embedding_fn
        return _OpenSearchCollection(self._client, index, name,
                                     embedding_function=embedding_function)


class _OpenSearchCollection:
    """Minimal ChromaDB Collection interface for OpenSearch."""

    def __init__(self, client, index: str, collection_name: str,
                 embedding_function=None):
        self._client = client
        self._index = index
        self._collection_name = collection_name
        self._embedding_fn = embedding_function

    def _auto_embed(self, documents, embeddings):
        """Generate embeddings via registry provider if not supplied."""
        if embeddings or not documents or not self._embedding_fn:
            return embeddings
        return self._embedding_fn(documents)

    def _bulk_index(self, ids, documents, embeddings, metadatas, action="index"):
        """Shared bulk indexing logic for add() and upsert()."""
        if not ids:
            return
        embeddings = self._auto_embed(documents, embeddings)
        body = []
        for i, doc_id in enumerate(ids):
            op = {action: {"_index": self._index, "_id": doc_id}}
            body.append(op)
            doc = {
                "content":         (documents or [])[i] if documents else "",
                "embedding":       (embeddings or [])[i] if embeddings else [],
                "metadata":        (metadatas or [])[i] if metadatas else {},
                "source_file":     ((metadatas or [])[i] or {}).get("source_file", ""),
                "chunk_id":        doc_id,
                "collection_name": self._collection_name,
                "model_profile":   ((metadatas or [])[i] or {}).get("model_profile", ""),
            }
            body.append(doc)
        result = self._client.bulk(body=body)
        if result.get("errors"):
            failed = sum(1 for item in result["items"] if item.get(action, {}).get("error"))
            print(f"[WARN] {failed}/{len(ids)} docs failed to index in {self._index}", file=sys.stderr)

    def add(self, ids, documents=None, embeddings=None, metadatas=None):
        """Bulk-index documents into OpenSearch."""
        self._bulk_index(ids, documents, embeddings, metadatas, action="index")

    def upsert(self, ids, documents=None, embeddings=None, metadatas=None):
        """Upsert documents into OpenSearch (insert-or-update by ID)."""
        self._bulk_index(ids, documents, embeddings, metadatas, action="index")

    def get(self, include=None, limit=None, **kwargs):
        """ChromaDB-compatible get() — returns existing doc IDs."""
        try:
            body = {"query": {"match_all": {}}, "_source": False, "size": 0}
            # Use scroll to get all IDs if needed
            if include is not None and include == []:
                # Caller only wants IDs — use scroll API
                ids = []
                body["size"] = 10000
                resp = self._client.search(index=self._index, body=body,
                                           scroll="2m")
                scroll_id = resp.get("_scroll_id")
                while True:
                    hits = resp["hits"]["hits"]
                    if not hits:
                        break
                    ids.extend(h["_id"] for h in hits)
                    resp = self._client.scroll(scroll_id=scroll_id, scroll="2m")
                if scroll_id:
                    try:
                        self._client.clear_scroll(scroll_id=scroll_id)
                    except Exception:
                        pass
                return {"ids": ids}
            return {"ids": []}
        except Exception:
            return {"ids": []}

    def modify(self, **kwargs):
        """ChromaDB-compatible modify() — no-op for OpenSearch."""
        pass

    def count(self) -> int:
        try:
            return self._client.count(index=self._index)["count"]
        except Exception:
            return 0


def get_vector_client(embedding_function=None):
    """Return a ChromaDB client (legacy) or OpenSearchVectorClient (aws).

    If embedding_function is provided, it will be used for auto-embedding
    when documents are added without explicit embeddings.
    """
    if BACKEND == "aws":
        endpoint = os.environ.get("OPENSEARCH_ENDPOINT", "")
        if not endpoint:
            print("[ERROR] OPENSEARCH_ENDPOINT required for DB_BACKEND=aws", file=sys.stderr)
            sys.exit(1)
        client = OpenSearchVectorClient(endpoint, AWS_REGION)
        if embedding_function:
            client.set_embedding_function(embedding_function)
        elif not embedding_function:
            # Auto-detect from registry if --model flag was used
            try:
                from embedding_registry import EmbeddingModelRegistry
                from embedding_provider import create_provider
                import argparse
                p = argparse.ArgumentParser(add_help=False)
                p.add_argument("--model", default="mpnet768")
                a, _ = p.parse_known_args()
                if a.model != "mpnet768":
                    profile = EmbeddingModelRegistry().get_profile(a.model)
                    provider = create_provider(profile)
                    client.set_embedding_function(provider.embed)
            except Exception:
                pass
        return client
    else:
        import chromadb
        host = os.environ.get("CHROMADB_HOST", "localhost")
        port = int(os.environ.get("CHROMADB_PORT", "8080"))
        return chromadb.HttpClient(host=host, port=port)
