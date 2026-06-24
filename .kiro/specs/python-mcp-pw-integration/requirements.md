# Requirements: Python MCP PW Integration

## 1. Introduction & Objectives

This specification defines the requirements for integrating the AWS-developed, Python-based multi-tenant MCP Server (`mcp_server_python`) into the Parallel Works (PW) VM COTS environment. The system currently runs a JavaScript-based Node.js server (`mcp_server_node`) backed by local **ChromaDB** and **Neo4j** database instances. 

The goal is to enable the fully-featured Python MCP runtime—complete with its multi-tenant branch routing capabilities—to operate on-premises using our local ChromaDB and Neo4j databases, and to restore the exported RAG data from our Parallel Works S3 storage bucket `omdmcpdata`.

## 2. Glossary

- **ChromaDBAdapter**: The Python class implementing `VectorDBProtocol` using the local `chromadb` HttpClient.
- **Neo4jAdapter**: The Python class implementing `GraphDBProtocol` using the local `neo4j` Bolt driver.
- **LocalProvider**: The embedding generator in `embedding_provider.py` which loads `sentence_transformers` (all-mpnet-base-v2) locally.
- **Reingestion_Script**: The python utility (`reingest_s3_to_local.py`) designed to download and restore embeddings/graphs from S3 bucket `omdmcpdata` to local databases.

## 3. Functional Requirements

### Requirement 1: Database Backend Mode `legacy`
- **Description**: The Python server must support `DB_BACKEND=legacy` cleanly.
- **Acceptance Criteria**:
  1. Setting `DB_BACKEND=legacy` must NOT raise an `UnsupportedBackendError` in `create_data_access`.
  2. In `legacy` mode, the server must dynamically instantiate `ChromaDBAdapter` and `Neo4jAdapter` rather than AWS adapters.
  3. If database connections fail during initialization, the server must gracefully degrade (nulling the failed adapter slot) and serve non-dependent tools, matching the documented AWS degraded-mode contract.

### Requirement 2: Python ChromaDB Adapter
- **Description**: Provide complete query and connection capabilities for local ChromaDB.
- **Acceptance Criteria**:
  1. `ChromaDBAdapter` must implement the `VectorDBProtocol` completely: `connect()`, `query()`, `multi_collection_query()`, `health_check()`, and `close()`.
  2. It must connect to ChromaDB at `http://{CHROMADB_HOST}:{CHROMADB_PORT}/api/v2` (defaulting to `http://localhost:8080/api/v2`).
  3. It must normalize cosine distances/similarity scores back to `[0.0, 1.0]` matching OpenSearch formats.
  4. It must support metadata filtering via standard ChromaDB query operators inside the `where` dictionary.

### Requirement 3: Local Embedding Generation
- **Description**: Un-stub local embedding generation for Parallel Works VM.
- **Acceptance Criteria**:
  1. `LocalProvider` in `embedding_provider.py` must load `sentence_transformers` and generate 768-dimensional embeddings using `Xenova/all-mpnet-base-v2`.
  2. If the Python library `sentence_transformers` is missing, it must raise a descriptive `EmbeddingError` on initialization so the server can report the error clearly.

### Requirement 4: Python Neo4j Adapter
- **Description**: Provide graph query capabilities for local Neo4j.
- **Acceptance Criteria**:
  1. `Neo4jAdapter` must implement the `GraphDBProtocol` completely: `connect()`, `query()`, `health_check()`, and `close()`.
  2. It must connect using `bolt://localhost:7687` with username `neo4j` and password `gfsworkflow2025`.
  3. Result records must be parsed and returned as standard dictionaries matching Node.js row objects.
  4. Neo4j queries must bypass APOC-to-openCypher translation and execute directly.

### Requirement 5: Branch Multi-Tenancy Resolution
- **Description**: Isolate database queries for multiple workflow branches (tenants).
- **Acceptance Criteria**:
  1. For **ChromaDB**: The adapter must map collections dynamically based on the active tenant (e.g. `code-with-context-v8-0-0_v17`).
  2. For **Neo4j**: Graph queries must apply tenant-specific labels (e.g. `MATCH (n:gw_v17:File)`) to enforce branch database isolation.

### Requirement 6: S3 Ingestion and Data Restore from `omdmcpdata`
- **Description**: Pull and restore AWS S3 gzipped JSON databases into local databases from bucket `omdmcpdata`, prefix `portable-export/dev/20260616-174650-df73fe6a/`.
- **Acceptance Criteria**:
  1. A standalone utility `reingest_s3_to_local.py` must be added.
  2. It must stream and extract gzip collections from `s3://omdmcpdata/portable-export/dev/20260616-174650-df73fe6a/`.
  3. For **ChromaDB**: Document vectors must be uploaded in batches of 500 with their pre-computed `mpnet768` embeddings (768 dimensions) to prevent expensive re-computation.
  4. For **Neo4j**: Nodes and relations must be loaded in batches of 1,000 using openCypher `UNWIND` queries.
  5. It must track progress via a local JSON watermark file to support idempotent resumption.
