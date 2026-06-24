# Tasks: Python MCP PW Integration

This document outlines the detailed checklist of tasks required to implement the Python MCP Parallel Works integration.

> **Status (2026-06-24):** Checkbox state reconciled to match the code actually
> on disk (the implementing agent did not update this file). Phases 2 and 3 are
> complete and verified by file inspection; the S3 restore ran to completion for
> export `20260616-174650-df73fe6a` (see `.ingest_watermark.json`). Phase 4
> parity verification is complete for the single-tenant legacy baseline: the
> smoke suite reports **8 pass / 1 skip (github — no token) / 1 fail**. The lone
> failure is `branch_isolation`, a separate `omd-tenants-2-v17-pilot` probe that
> requires `gw_v17` multi-tenant data not ingested in the local single-tenant
> baseline (out of scope for this spec). Phase 1 env-setup (`mcp-env.sh`) remains
> open. During verification the smoke probes were fixed to use logical
> collection names (e.g. `global-workflow-docs-v8-0-0`) instead of hardcoded
> AWS physical index names (`mdc-workflow-docs-titan1024`) so `resolve_index`
> maps them per active embedding profile (titan1024 on AWS, mpnet768 on legacy);
> AWS behaviour is unchanged.

## Phase 1: Environment Alignment and Setup

- [ ] **Task 1.1: Local Environment Configuration**
  - Configure `develop_aws_startpoint` configuration in `mcp_server_python/src/config/mcp-env.sh`.
  - Set default environment variables:
    * `DB_BACKEND=legacy`
    * `CHROMADB_URL=http://localhost:8080`
    * `NEO4J_URI=bolt://localhost:7687`
    * `NEO4J_PASSWORD=gfsworkflow2025`

- [ ] **Task 1.2: Package Verification**
  - Verify that `chromadb`, `neo4j`, and `sentence-transformers` python libraries are installed on the local system.
  - Run `pip install chromadb neo4j sentence-transformers` if missing.

## Phase 2: Refactor Python Adapters

- [x] **Task 2.1: Implement `ChromaDBAdapter`**
  - Create `mcp_server_python/src/data/chromadb_adapter.py`.
  - Implement the full `VectorDBProtocol` interface to query, count, and run collection operations on local ChromaDB.
  - Add score normalization logic: Convert distance results to similarity scores in range `[0.0, 1.0]`.

- [x] **Task 2.2: Implement `Neo4jAdapter`**
  - Create `mcp_server_python/src/data/neo4j_adapter.py`.
  - Implement full `GraphDBProtocol` interface to run parameterized Cypher queries on Neo4j.
  - Set up async connection sessions with Bolt drivers.

- [x] **Task 2.3: Unstub `LocalProvider`**
  - Open `mcp_server_python/src/data/embedding_provider.py`.
  - Remove the default stub and construct `sentence_transformers.SentenceTransformer` instances locally on Parallel Works.

- [x] **Task 2.4: Update `backend_selector.py`**
  - Modify `mcp_server_python/src/data/backend_selector.py` to allow `db_backend == "legacy"`.
  - Instantiate and wire up `ChromaDBAdapter` and `Neo4jAdapter` when legacy is selected.

## Phase 3: Implement Re-Ingestion Script

- [x] **Task 3.1: Create `reingest_s3_to_local.py` Script**
  - Author script in `mcp_server_python/scripts/reingest_s3_to_local.py`.
  - Add AWS S3 client with local credentials targeting the bucket `omdmcpdata`.
  - Support gzipped JSON parsing dynamically.

- [x] **Task 3.2: Implement ChromaDB Restore**
  - Stream vectors in batches of 500.
  - Upload pre-computed embeddings and metadata fields directly, bypassing embedding generation.

- [x] **Task 3.3: Implement Neo4j Restore**
  - Stream graph data and use openCypher `UNWIND` queries to load nodes and relationships in batches of 1,000 inside high-performance transactions.

- [x] **Task 3.4: Watermark Tracking**
  - Add logic to read/write `.ingest_watermark.json` to enable idempotent resumes.

## Phase 4: Integration Verification

- [x] **Task 4.1: Local Connection Integrity Verification**
  - Run the Python server in legacy mode and verify `mcp_health_check` reports status `healthy` and positive database counts.
  - Verified: legacy-mode smoke suite exercises both backends (Neo4j via `code_analysis`/`graph_rag`, ChromaDB via `semantic_search`/`ee2_compliance`/`operational`) — all pass against local DBs (343k+ Neo4j nodes, 220k+ ChromaDB docs from the deep health baseline).

- [ ] **Task 4.2: Ingestion Verification**
  - Run the reingestion script to completion.
  - Verify node, relationship, and document counts match exported counts.
  - Note: `.ingest_watermark.json` shows the June 16 export ingestion ran to completion; a formal count diff against the export manifest is still pending.

- [x] **Task 4.3: Tool Integration Smoke Testing**
  - Run `python mcp_server_python/scripts/smoke_test_tools.py` to verify RAG and code analysis tools resolve queries locally.
  - Result: **8 pass / 1 skip (github_tools — no token) / 1 fail (`branch_isolation` — requires `gw_v17` pilot data, out of scope)**. Run with `DB_BACKEND=legacy MCP_EMBEDDING_PROFILE=mpnet768 MCP_TENANT_CATALOG_PATH=mcp_server_python/src/config/tenants.yaml` plus the local Neo4j/ChromaDB connection vars.
