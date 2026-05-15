from __future__ import annotations

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
import time
import urllib.parse

try:
    import boto3
    import botocore.auth
    import botocore.awsrequest
    import urllib3
except ImportError:
    boto3 = None  # type: ignore[assignment]
    botocore = None  # type: ignore[assignment]
    urllib3 = None  # type: ignore[assignment]

BACKEND = os.environ.get("DB_BACKEND", "legacy")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


# ── Neptune exception classes ─────────────────────────────────────────────────

class NeptuneQueryError(Exception):
    """Raised when a Neptune openCypher query fails."""
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"Neptune query failed: {status_code} {message}")


class NeptuneConnectionError(Exception):
    """Raised when Neptune is unreachable."""
    pass


# ── Endpoint normalization ────────────────────────────────────────────────────

def _normalize_endpoint(endpoint: str) -> str:
    """Normalize a Neptune endpoint to ``https://<host>:<port>/opencypher``.

    Handles four input formats:
      - ``wss://host:port/path``   → replace scheme with ``https://``
      - ``bolt+s://host:port``     → replace scheme with ``https://``
      - ``https://host:port``      → keep as-is
      - bare hostname              → prepend ``https://`` and append ``:8182``

    The returned URL always ends with ``/opencypher``.
    """
    # Strip whitespace
    endpoint = endpoint.strip()

    # Scheme replacement
    if endpoint.startswith("wss://"):
        endpoint = "https://" + endpoint[len("wss://"):]
    elif endpoint.startswith("bolt+s://"):
        endpoint = "https://" + endpoint[len("bolt+s://"):]
    elif not endpoint.startswith("https://"):
        # Bare hostname — prepend scheme and append default port
        endpoint = f"https://{endpoint}:8182"

    # Ensure path ends with /opencypher
    if not endpoint.endswith("/opencypher"):
        # Strip trailing slash before appending
        endpoint = endpoint.rstrip("/") + "/opencypher"

    return endpoint


# ── Neptune result wrapper ────────────────────────────────────────────────────

class NeptuneResult:
    """neo4j Result-compatible wrapper for Neptune HTTP JSON responses."""

    def __init__(self, records: list[dict]):
        self._records = records
        self._index = 0

    def single(self) -> dict | None:
        """Return the first record, or None if empty."""
        return self._records[0] if self._records else None

    def __iter__(self):
        self._index = 0
        return self

    def __next__(self):
        if self._index >= len(self._records):
            raise StopIteration
        record = self._records[self._index]
        self._index += 1
        return record


# ── Neptune session (HTTP + SigV4) ────────────────────────────────────────────

class NeptuneSession:
    """neo4j Session-compatible object for Neptune HTTP queries.

    Each query is sent as a SigV4-signed HTTP POST to the Neptune
    openCypher endpoint.  Credentials are refreshed per-request so
    long-running ingestion jobs survive credential rotation.
    """

    def __init__(self, endpoint: str, region: str, pool):
        """
        Parameters
        ----------
        endpoint : str
            Fully-normalised Neptune HTTPS URL ending with ``/opencypher``.
        region : str
            AWS region for SigV4 signing.
        pool : urllib3.PoolManager
            Shared connection pool for HTTP requests.
        """
        self._endpoint = endpoint
        self._region = region
        self._pool = pool

    # -- public interface (neo4j Session surface) ---------------------------

    def run(self, query: str, **params) -> "NeptuneResult":
        """Execute an openCypher query against Neptune.

        Parameters
        ----------
        query : str
            Cypher query string.
        **params
            Query parameters (serialized as JSON in the POST body).

        Returns
        -------
        NeptuneResult
            Iterable result object with ``.single()`` support.
        """
        return self._execute_with_retry(query, params)

    def close(self) -> None:
        """No-op — HTTP is stateless."""
        pass

    def __enter__(self) -> "NeptuneSession":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    # -- internal: query execution -----------------------------------------

    def _execute_query(self, query: str, params: dict) -> "NeptuneResult":
        """Build, sign, and send a single HTTP POST to Neptune.

        Raises
        ------
        NeptuneQueryError
            On HTTP 4xx/5xx responses from Neptune.
        NeptuneConnectionError
            On network timeouts or connection failures.
        """
        # 1. Build POST body
        body_parts = {"query": query}
        if params:
            body_parts["parameters"] = json.dumps(params)
        body = urllib.parse.urlencode(body_parts)

        # 2. Obtain fresh credentials (handles rotation for long jobs)
        creds = boto3.Session().get_credentials().get_frozen_credentials()

        # 3. Create signable request
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        aws_request = botocore.awsrequest.AWSRequest(
            method="POST",
            url=self._endpoint,
            data=body,
            headers=headers,
        )

        # 4. Sign with SigV4
        botocore.auth.SigV4Auth(creds, "neptune-db", self._region).add_auth(aws_request)

        # 5. Send via urllib3
        try:
            response = self._pool.request(
                "POST",
                self._endpoint,
                body=body,
                headers=dict(aws_request.headers),
                timeout=30,
            )
        except Exception as exc:
            # urllib3 timeout / connection errors → NeptuneConnectionError
            raise NeptuneConnectionError(
                f"Neptune unreachable at {self._endpoint}: {exc}"
            ) from exc

        # 6. Handle HTTP errors
        status = response.status
        if status >= 400:
            try:
                err_body = json.loads(response.data.decode("utf-8"))
                message = err_body.get("detailedMessage", err_body.get("message", response.data.decode("utf-8")))
            except Exception:
                message = response.data.decode("utf-8", errors="replace")
            raise NeptuneQueryError(status, message)

        # 7. Parse successful JSON response
        try:
            data = json.loads(response.data.decode("utf-8"))
        except Exception as exc:
            raise NeptuneQueryError(
                status, f"Invalid JSON response: {response.data.decode('utf-8', errors='replace')}"
            ) from exc

        return NeptuneResult(data.get("results", []))

    # -- internal: retry wrapper -------------------------------------------

    def _execute_with_retry(self, query: str, params: dict) -> "NeptuneResult":
        """Wrap ``_execute_query`` with exponential-backoff retry logic.

        Retries up to 3 times on HTTP 429, 500, and 503 responses.
        Backoff schedule: 1 s → 2 s → 4 s.
        """
        max_retries = 3
        backoff = 1  # seconds
        for attempt in range(max_retries + 1):
            try:
                return self._execute_query(query, params)
            except NeptuneQueryError as e:
                if e.status_code in (429, 500, 503) and attempt < max_retries:
                    print(
                        f"[WARN] Neptune request retry {attempt + 1}/{max_retries}: "
                        f"HTTP {e.status_code}",
                        file=sys.stderr,
                    )
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                print(
                    f"[ERROR] Neptune query failed: {e.status_code} {e}",
                    file=sys.stderr,
                )
                raise


# ── Neptune HTTP adapter (neo4j Driver drop-in) ──────────────────────────────

class NeptuneHTTPAdapter:
    """neo4j.Driver-compatible adapter for Neptune HTTP openCypher API.

    Provides the ``session()`` / ``close()`` / ``verify_connectivity()``
    surface used by the four ingestion scripts so they require zero code
    changes when ``DB_BACKEND=aws``.
    """

    def __init__(self, endpoint: str, region: str = "us-east-1"):
        """
        Parameters
        ----------
        endpoint : str
            Neptune endpoint in any supported format (bare hostname,
            ``wss://``, ``bolt+s://``, or ``https://``).
        region : str
            AWS region for SigV4 signing.
        """
        self._endpoint = _normalize_endpoint(endpoint)
        self._region = region
        self._pool = urllib3.PoolManager()

    def session(self) -> "NeptuneSession":
        """Return a new NeptuneSession (context-manager compatible)."""
        return NeptuneSession(self._endpoint, self._region, self._pool)

    def close(self) -> None:
        """Release the urllib3 connection pool."""
        self._pool.clear()

    def verify_connectivity(self) -> None:
        """Execute ``RETURN 1`` against Neptune.

        Prints an ``[OK]`` banner to stderr on success.
        Raises on failure (NeptuneQueryError or NeptuneConnectionError).
        """
        with self.session() as s:
            s.run("RETURN 1")
        print(
            f"[OK] Connected to Neptune (HTTP/SigV4): {self._endpoint}",
            file=sys.stderr,
        )


# ── Graph driver ──────────────────────────────────────────────────────────────

def get_graph_driver():
    """Return a neo4j.Driver connected to Neo4j (legacy) or Neptune (aws)."""
    if BACKEND == "aws":
        endpoint = os.environ.get("NEPTUNE_ENDPOINT", "")
        if not endpoint:
            print("[ERROR] NEPTUNE_ENDPOINT required for DB_BACKEND=aws", file=sys.stderr)
            sys.exit(1)
        return NeptuneHTTPAdapter(endpoint, AWS_REGION)
    else:
        from neo4j import GraphDatabase, Auth
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
