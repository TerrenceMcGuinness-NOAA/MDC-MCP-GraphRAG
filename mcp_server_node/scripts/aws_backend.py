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

# Collection → OpenSearch index mapping (matches OpenSearchAdapter.js)
COLLECTION_TO_INDEX = {
    "code-with-context-v8-0-0":      "mdc-code-context",
    "global-workflow-docs-v8-0-0":   "mdc-workflow-docs",
    "jjobs-v8-0-0":                  "mdc-jjobs",
    "community-summaries":           "mdc-community-summaries",
    "ee2-standards-v5-0-0-enhanced": "mdc-ee2-standards",
}


class OpenSearchVectorClient:
    """
    Minimal ChromaDB-compatible interface backed by OpenSearch.
    Supports: get_or_create_collection(), collection.add()
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

    def get_or_create_collection(self, name: str, **kwargs):
        index = COLLECTION_TO_INDEX.get(name, name)
        return _OpenSearchCollection(self._client, index, name)


class _OpenSearchCollection:
    """Minimal ChromaDB Collection interface for OpenSearch."""

    def __init__(self, client, index: str, collection_name: str):
        self._client = client
        self._index = index
        self._collection_name = collection_name

    def add(self, ids, documents=None, embeddings=None, metadatas=None):
        """Bulk-index documents into OpenSearch. Embeddings transferred bitwise."""
        if not ids:
            return
        body = []
        for i, doc_id in enumerate(ids):
            body.append({"index": {"_index": self._index, "_id": doc_id}})
            body.append({
                "content":         (documents or [])[i] if documents else "",
                "embedding":       (embeddings or [])[i] if embeddings else [],
                "metadata":        (metadatas or [])[i] if metadatas else {},
                "source_file":     ((metadatas or [])[i] or {}).get("source_file", ""),
                "chunk_id":        doc_id,
                "collection_name": self._collection_name,
            })
        result = self._client.bulk(body=body)
        if result.get("errors"):
            failed = sum(1 for item in result["items"] if item.get("index", {}).get("error"))
            print(f"[WARN] {failed}/{len(ids)} docs failed to index in {self._index}", file=sys.stderr)

    def count(self) -> int:
        try:
            return self._client.count(index=self._index)["count"]
        except Exception:
            return 0


def get_vector_client():
    """Return a ChromaDB client (legacy) or OpenSearchVectorClient (aws)."""
    if BACKEND == "aws":
        endpoint = os.environ.get("OPENSEARCH_ENDPOINT", "")
        if not endpoint:
            print("[ERROR] OPENSEARCH_ENDPOINT required for DB_BACKEND=aws", file=sys.stderr)
            sys.exit(1)
        return OpenSearchVectorClient(endpoint, AWS_REGION)
    else:
        import chromadb
        host = os.environ.get("CHROMADB_HOST", "localhost")
        port = int(os.environ.get("CHROMADB_PORT", "8080"))
        return chromadb.HttpClient(host=host, port=port)
