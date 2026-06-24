# Design: Python MCP PW Integration

## 1. Architectural Overview

The integration uses the established **adapter (Protocol) pattern** in `mcp_server_python`. The data-access layer uses structural interfaces (`VectorDBProtocol` and `GraphDBProtocol`) to decoupling the query tool handlers from the active database engines. 

When `DB_BACKEND` is set to `legacy`, the system instantiates local python `ChromaDBAdapter` and `Neo4jAdapter` instances. Both local adapters are connected eagerly at startup, with identical error trapping to ensure graceful degradation.

```
       mcp_server_python (Tools)
                 │
                 ▼
       UnifiedDataAccess Facade
                 │
        ┌────────┴────────┐
        ▼                 ▼
VectorDBProtocol    GraphDBProtocol
        │                 │
        ├─► [aws]         ├─► [aws]
        │   OpenSearch    │   Neptune
        │                 │
        └─► [legacy]      └─► [legacy]
            ChromaDB          Neo4j
            (New Class)       (New Class)
```

## 2. Component Design

### 2.1 `ChromaDBAdapter` (`src/data/chromadb_adapter.py`)
Encapsulates interaction with local ChromaDB.

- **Library**: `chromadb` client package.
- **Connection**: HTTP transport `chromadb.HttpClient(host=host, port=port)`.
- **Formatting**:
  - Distance metrics from ChromaDB (L2 or Cosine distance) are normalized back to a similarity score range `[0.0, 1.0]` so that semantic search results contain unified relevance scores:
    $$\text{score} = 1.0 - \text{distance}$$
  - Metadata filters are translated to ChromaDB query syntax.

### 2.2 `Neo4jAdapter` (`src/data/neo4j_adapter.py`)
Encapsulates graph traversals on Parallel Works' local Neo4j.

- **Library**: `neo4j` official python driver.
- **Connection**: Bolt transport `AsyncGraphDatabase.driver(uri, auth=(user, password))`.
- **Query execution**:
  - OpenCypher queries are run inside async transaction sessions.
  - Unlike Neptune, APOC procedures are natively supported by Neo4j on PW. The `Neo4jAdapter` bypasses the APOC string transformation and executes queries raw, ensuring maximum performance.

### 2.3 Unstubbing local `LocalProvider`
We will re-enable the local embedding logic within `src/data/embedding_provider.py` by replacing the `ImportError` block with active loading of `sentence-transformers`:

```python
class LocalProvider(EmbeddingProvider):
    def __init__(self, profile: ModelProfile) -> None:
        self._profile = profile
        import sentence_transformers
        self._model = sentence_transformers.SentenceTransformer(profile.model_id)

    def embed(self, texts: list[str]) -> list[list[float]]:
        # Compute embeddings in python
        embeddings = self._model.encode(texts, convert_to_numpy=True)
        return embeddings.tolist()
```

## 3. S3 Re-Ingestion Design

To handle the restore of the AWS RAG databases, we will implement `mcp_server_python/scripts/reingest_s3_to_local.py` targeting bucket `omdmcpdata` and prefix `portable-export/dev/20260616-174650-df73fe6a/`.

### 3.1 Dataset Layout inside `omdmcpdata` S3 Bucket
- **Manifest**: `portable-export/dev/20260616-174650-df73fe6a/manifest.json`
- **Vectors**: `portable-export/dev/20260616-174650-df73fe6a/vectors/gw/*-mpnet768/00*.jsonl.gz`
- **Graph Nodes**: `portable-export/dev/20260616-174650-df73fe6a/graph/gw/nodes/*.csv.gz`
- **Graph Rels**: `portable-export/dev/20260616-174650-df73fe6a/graph/gw/rels/*.csv.gz`

### 3.2 Vector Records Schema
Each JSON line inside the vector `.jsonl.gz` parts is formatted as follows:
```json
{
  "id": "standards_1",
  "chunk_id": "standards_1",
  "collection_name": "ee2-standards-v5-0-0-enhanced",
  "content": "Document text content...",
  "embedding": [-0.012260827, -0.056836423, ...],
  "metadata": {
    "source_file": "supported_repos/nws-hpc-standards/docs/standards.rst",
    "relative_path": "standards.rst",
    "compliance_category": "environment_variables"
    // ... other metadata properties
  }
}
```

### 3.3 Ingestion Flow
```
                  S3: omdmcpdata/portable-export/...
                             │
                             ▼
              [reingest_s3_to_local.py]
              (Downloads and streams gzip)
                             │
              ┌──────────────┴──────────────┐
              ▼                             ▼
       ChromaDB Batch Load            Neo4j Batch Load
       (Batches of 500 docs           (Batches of 1000 nodes/rels
        with raw vector inject)        via Cypher UNWIND query)
```

1.  **Idempotency**: It checks `.ingest_watermark.json` before processing. If a collection is marked as completed, it is skipped.
2.  **ChromaDB load optimization**:
    - The JSON contains pre-computed embeddings (768-dim MPNet). The ingestion script injects the raw `embedding` list directly to prevent expensive local model re-runs.
    - Added documents are grouped in batches of 500.
3.  **Neo4j load optimization**:
    - Uses openCypher `UNWIND` queries inside transactions to bulk-merge nodes and relationships in batches of 1,000 to prevent transaction overhead bottlenecks.
