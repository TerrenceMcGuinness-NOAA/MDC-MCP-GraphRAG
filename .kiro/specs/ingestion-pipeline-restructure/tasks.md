# Implementation Plan: Ingestion Pipeline Restructure

## Overview

Restructure the GraphRAG MCP server's ingestion pipeline from 14+ independent Python scripts with hardcoded embedding models into a modular, multi-model, idempotent pipeline. Implementation proceeds in layers: core Python infrastructure (registry, provider, base class), Node.js retrieval enhancements (hybrid search, graph augmentation), SageMaker compute offloading, and the self-improving feedback loop. Each layer builds on the previous, with property tests validating universal invariants at each stage.

## Tasks

- [x] 1. Embedding Model Registry and Provider Abstraction
  - [x] 1.1 Create `embedding_registry.py` with `ModelProfile` dataclass and `EmbeddingModelRegistry` class
    - Define `ModelProfile` frozen dataclass with fields: `short_name`, `provider`, `model_id`, `dimensions`, `supports_matryoshka`, `supports_multimodal`, `provider_params`
    - Implement `EmbeddingModelRegistry` with `get_profile()`, `get_default()`, `list_profiles()`, `register()` methods
    - Register built-in profiles: `mpnet768`, `titan1024`, `nova256`, `nova512`, `nova1024`, `nova3072`
    - Default profile: `mpnet768`
    - File: `mcp_server_node/scripts/embedding_registry.py`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 24.1, 24.5_

  - [x]* 1.2 Write property test: registry profile invariants
    - **Property P1: For any registered ModelProfile, `get_profile(short_name)` returns a profile with `dimensions > 0` and `provider` in `{"local", "bedrock"}`**
    - **Property P2: For any short_name not in the registry, `get_profile()` raises `KeyError` listing available profiles**
    - **Validates: Requirements 1.1, 1.4, 8.4**

  - [x] 1.3 Create `embedding_provider.py` with `EmbeddingProvider` ABC, `LocalProvider`, and `BedrockProvider`
    - `EmbeddingProvider` ABC with `embed(texts)`, `embed_image(image_bytes)`, `dimensions` property
    - `LocalProvider`: uses `sentence-transformers`, auto-detects CUDA, downloads to `$CACHE_ROOT/huggingface`
    - `BedrockProvider`: uses `boto3` bedrock-runtime client, passes `outputEmbeddingLength` for Nova models, logs errors with model_id and input length
    - `create_provider(profile)` factory function
    - File: `mcp_server_node/scripts/embedding_provider.py`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 12.1, 12.2, 12.3, 24.2, 24.3_

  - [x]* 1.4 Write property test: embedding dimension consistency
    - **Property P3: For any ModelProfile and any non-empty text input, `provider.embed([text])` returns a vector of length equal to `profile.dimensions`**
    - **Validates: Requirements 2.1, 24.3**

  - [x] 1.5 Create `collection_namer.py` with `CollectionNamer` class
    - `get_name(domain, version)` → `"{domain}-{version}-{profile.short_name}"`
    - `is_legacy_name(name)` → True if name lacks any known model suffix
    - `get_legacy_name(domain, version)` → `"{domain}-{version}"` for backward compat
    - File: `mcp_server_node/scripts/collection_namer.py`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x]* 1.6 Write property test: collection naming determinism and model encoding
    - **Property P4: For any (domain, version, profile) triple, `get_name()` always returns the same string, and that string ends with `-{profile.short_name}`**
    - **Property P5: For any legacy collection name (without model suffix), `is_legacy_name()` returns True**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.5**

- [x] 2. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Refactor `ingestion_base.py` — Centralized BaseIngester
  - [x] 3.1 Implement `BaseIngester` class in `ingestion_base.py`
    - `_parse_common_args()`: parse `--model`, `--backend`, `--collections`, `--dry-run` centrally
    - `get_clients()`: unified backend routing replacing inline `--backend` parsing and `ChromaDBClient.connect()` boilerplate
    - `deterministic_id(content, source, chunk_index)`: SHA-256 hash of `content|source|chunk_index|profile.short_name`, truncated to 32 hex chars
    - `upsert_document()`: upsert semantics for vector writes (insert-or-update by doc ID)
    - `merge_graph_node()` / `merge_graph_relationship()`: MERGE semantics for graph writes
    - Abstract `extract_content()` method for subclasses
    - `run()` main loop: extract → embed → deterministic_id → upsert/merge
    - Remove hardcoded `EMBEDDING_MODEL = "all-mpnet-base-v2"` constant, replace with registry resolution
    - Consolidate `ChromaDBClient.connect()` backend routing and `aws_backend.py` factory into `get_clients()`
    - Preserve existing `SemanticChunker`, `URLCrawler`, `LocalRepoParser`, `MetadataEnricher` classes unchanged
    - File: `mcp_server_node/scripts/ingestion_base.py`
    - _Requirements: 6.1, 6.2, 6.4, 6.5, 7.1, 7.2, 7.4, 7.5, 8.1, 8.2, 8.3, 8.5, 13.1, 13.2, 13.3, 13.4_

  - [x]* 3.2 Write property test: deterministic ID idempotence
    - **Property P6: For any (content, source, chunk_index, model) tuple, `deterministic_id()` called twice returns the same value**
    - **Property P7: For any two distinct (content, source, chunk_index, model) tuples, `deterministic_id()` returns different values (collision resistance)**
    - **Validates: Requirements 7.1, 7.2, 7.6**

  - [x]* 3.3 Write property test: backend routing completeness
    - **Property P8: For backend value "legacy", `get_clients()` returns ChromaDB + Neo4j clients; for "aws", returns OpenSearch + Neptune clients; for any other value, raises an error**
    - **Validates: Requirements 6.1, 6.2, 6.4, 6.5**

- [x] 4. Refactor ingestion scripts to subclass BaseIngester
  - [x] 4.1 Refactor `ingest_code_v8.py` to subclass `BaseIngester`
    - Remove inline `--backend` parsing boilerplate
    - Implement `extract_content()` returning `ContentChunk` objects
    - Use `self.provider.embed()` instead of hardcoded MPNet
    - Use `self.namer.get_name()` for collection names
    - Use `self.deterministic_id()` for document IDs
    - Use `self.upsert_document()` and `self.merge_graph_node()` / `self.merge_graph_relationship()`
    - _Requirements: 6.3, 7.1, 7.4, 7.5, 8.1, 13.2_

  - [x] 4.2 Refactor `ingest_documentation_v8.py` to subclass `BaseIngester`
    - Same pattern as 4.1
    - _Requirements: 6.3, 7.1, 7.4, 8.1, 13.2_

  - [x] 4.3 Refactor `ingest_fortran_graph.py` to subclass `BaseIngester`
    - Same pattern as 4.1
    - _Requirements: 6.3, 7.1, 7.5, 8.1, 13.2_

  - [x] 4.4 Refactor `ingest_shell_graph_v8.py` to subclass `BaseIngester`
    - Same pattern as 4.1
    - _Requirements: 6.3, 7.1, 7.5, 8.1, 13.2_

  - [x] 4.5 Refactor `ingest_jjobs_v8.py` to subclass `BaseIngester`
    - Same pattern as 4.1
    - _Requirements: 6.3, 7.1, 7.4, 8.1, 13.2_

  - [x] 4.6 Refactor `ingest_cross_language_bridges.py` to subclass `BaseIngester`
    - Same pattern as 4.1
    - _Requirements: 6.3, 7.1, 7.5, 8.1, 13.2_

  - [x] 4.7 Refactor `ingest_env_variables.py` to subclass `BaseIngester`
    - Same pattern as 4.1
    - _Requirements: 6.3, 7.1, 7.4, 8.1, 13.2_

- [x] 5. Checkpoint — Ensure all refactored scripts work
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Update `aws_backend.py` for model-aware index routing
  - [x] 6.1 Extend `COLLECTION_TO_INDEX` mapping to support model-aware names
    - Preserve existing legacy mapping for backward compatibility
    - Add dynamic resolution: if collection name ends with a known model suffix, map to `{base-index}-{model-suffix}`
    - Update `OpenSearchVectorClient.get_or_create_collection()` to use model-aware index names
    - File: `mcp_server_node/scripts/aws_backend.py`
    - _Requirements: 3.4, 10.1, 10.2, 11.2_

  - [x]* 6.2 Write property test: model-aware index name mapping
    - **Property P9: For any legacy collection name (without model suffix), `_toIndex()` returns the same index as the existing `COLLECTION_TO_INDEX` mapping**
    - **Property P10: For any model-aware collection name, `_toIndex()` returns an index name that includes the model suffix**
    - **Validates: Requirements 3.4, 11.2, 11.3_

- [x] 7. Dead code archival
  - [x] 7.1 Move `mcp_server_python/` to `archive/mcp_server_python/`
    - Verify no active script or config imports from `mcp_server_python/`
    - Update `.gitmodules` if it references `mcp_server_python/`
    - _Requirements: 9.1, 9.2, 9.3_

- [x] 8. Model-aware OpenSearch index creation
  - [x] 8.1 Update `create-opensearch-indices.js` for multi-model support
    - Accept `--model` argument (specific model short name or `all`)
    - Read model profiles from a shared JSON config (or inline registry matching Python registry)
    - Set `knn_vector` dimension dynamically per model profile
    - Generate model-aware index names (e.g., `mdc-code-context-mpnet768`, `mdc-code-context-titan1024`)
    - Add `model_profile` keyword field to index mapping
    - Add `content` as `text` type for BM25 search (dual-indexed with `embedding`)
    - Idempotent: skip existing indices without error
    - Default to `mpnet768` when `--model` omitted
    - File: `mcp_server_node/scripts/create-opensearch-indices.js`
    - _Requirements: 10.1, 10.2, 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 26.1_

  - [x]* 8.2 Write property test: index creation idempotence
    - **Property P11: For any model profile, running `create-opensearch-indices` twice produces the same set of indices with the same mappings**
    - **Validates: Requirements 15.6**

- [x] 9. Model-aware migration updates
  - [x] 9.1 Update `migrate-to-aws.js` for model-aware export/load
    - Read model metadata from ChromaDB collection metadata
    - Include model short name in S3 export keys (e.g., `vectors/code-with-context-v8-0-0-mpnet768.json.gz`)
    - Target model-aware OpenSearch indices during load
    - Support migrating multiple vector spaces per content domain in a single run
    - Preserve legacy `COLLECTION_TO_INDEX` mapping for pre-model-aware collections
    - Use S3 watermarks per collection-model combination for idempotent re-execution
    - File: `mcp_server_node/scripts/migrate-to-aws.js`
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 16.1, 16.2, 16.3, 16.4, 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7, 19.1, 19.2, 19.3, 19.4, 19.5_

  - [x] 9.2 Update `verify-migration.js` for multi-model verification
    - Check count parity for every model-aware index in OpenSearch
    - Report per-model, per-collection counts
    - Upload parity report to S3 with timestamp
    - Exit non-zero on any model-specific count mismatch
    - File: `mcp_server_node/scripts/verify-migration.js`
    - _Requirements: 17.1, 17.2, 17.3, 17.4_

- [x] 10. Checkpoint — Ensure migration and index scripts work
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Hybrid Search — BM25 + Vector + RRF
  - [x] 11.1 Create `HybridSearchBuilder.js`
    - `build(queryText, queryVector, options)` → OpenSearch hybrid query body
    - `_containsCodeIdentifiers(queryText)` → detect camelCase, snake_case, dot.notation, file paths
    - Support `search_mode`: `vector` (default), `keyword`, `hybrid`
    - Auto-boost BM25 weight when code identifiers detected
    - Use OpenSearch `search_pipeline` with `normalization-processor` and RRF for score fusion
    - File: `mcp_server_node/src/data/search/HybridSearchBuilder.js`
    - _Requirements: 26.1, 26.2, 26.3, 26.4, 26.5_

  - [x]* 11.2 Write property test: code identifier detection
    - **Property P12: For any string containing camelCase, snake_case, dot.notation, or file path patterns, `_containsCodeIdentifiers()` returns true**
    - **Property P13: For any plain English sentence without code patterns, `_containsCodeIdentifiers()` returns false**
    - **Validates: Requirements 26.3**

  - [x] 11.3 Update `OpenSearchAdapter.js` to support hybrid search mode
    - Add `hybridQuery(collectionName, queryText, options)` method that uses `HybridSearchBuilder`
    - Preserve existing `query()` method unchanged for backward compatibility
    - File: `mcp_server_node/src/data/adapters/OpenSearchAdapter.js`
    - _Requirements: 26.2, 26.4_

- [x] 12. Graph-Augmented Vector Retrieval
  - [x] 12.1 Create `GraphAugmenter.js`
    - `augment(vectorResults, graphDB, options)` → results with `graph_context` field
    - Query Neptune for 1-hop relationships: CALLS, USES, IMPORTS, CONTAINS
    - Configurable `hopDepth` (default: 1, max: 2)
    - Graceful fallback: if Neptune unavailable, return original results unchanged
    - File: `mcp_server_node/src/data/search/GraphAugmenter.js`
    - _Requirements: 28.1, 28.2, 28.3, 28.4, 28.5_

  - [x]* 12.2 Write property test: graph augmentation backward compatibility
    - **Property P14: For any vector result set, when graph augmentation is disabled, the output is identical to the input**
    - **Validates: Requirements 28.4**

- [x] 13. Matryoshka Adaptive Dimension Retrieval
  - [x] 13.1 Create `MatryoshkaQuery.js`
    - Support `--dimensions` query parameter for prefix truncation
    - Truncate stored embeddings to specified prefix length at query time
    - Use `script_score` or k-NN query with truncated prefix for lower-dimension searches
    - File: `mcp_server_node/src/data/search/MatryoshkaQuery.js`
    - _Requirements: 25.1, 25.2, 25.3, 25.4_

  - [x]* 13.2 Write property test: Matryoshka truncation preserves prefix
    - **Property P15: For any embedding of dimension D and truncation target T < D, the truncated vector equals the first T elements of the original**
    - **Validates: Requirements 25.2**

- [x] 14. Comparative Query Support
  - [x] 14.1 Extend `VectorDatabaseAdapter.js` with `comparativeQuery()` method
    - Execute a single query text against multiple vector spaces
    - Embed query using each target vector space's model profile
    - Return results grouped by model profile
    - Preserve existing single-model query interface unchanged
    - File: `mcp_server_node/src/data/adapters/VectorDatabaseAdapter.js`
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x] 14.2 Implement `comparativeQuery()` in `OpenSearchAdapter.js`
    - Query multiple model-aware indices in parallel
    - Group results by model profile
    - File: `mcp_server_node/src/data/adapters/OpenSearchAdapter.js`
    - _Requirements: 5.1, 5.2, 5.3_

- [x] 15. Wire retrieval enhancements into UnifiedDataAccess
  - [x] 15.1 Update `UnifiedDataAccess.js` to expose hybrid, graph-augmented, and comparative query modes
    - Import and wire `HybridSearchBuilder`, `GraphAugmenter`, `MatryoshkaQuery`
    - Add `search_mode`, `graph_augmented`, `dimensions` options to query methods
    - Preserve all existing 51 MCP tool interfaces unchanged
    - File: `mcp_server_node/src/data/UnifiedDataAccess.js`
    - _Requirements: 5.4, 11.1, 11.3, 11.4, 26.4, 28.4_

- [x] 16. Checkpoint — Ensure all Node.js retrieval enhancements work
  - Ensure all tests pass, ask the user if questions arise.

- [x] 17. Feedback Logger
  - [x] 17.1 Create `FeedbackLogger.js`
    - Log anonymized query-result pairs to S3 (JSON Lines format)
    - Capture: query text, result doc IDs, scores, collection, model profile, tool name
    - Opt-in via `FEEDBACK_LOGGING=true` env var, disabled by default
    - No PII or raw user prompts
    - File: `mcp_server_node/src/data/feedback/FeedbackLogger.js`
    - _Requirements: 31.1, 31.2, 31.4, 31.5_

  - [x]* 17.2 Write property test: feedback log contains no PII
    - **Property P16: For any logged feedback entry, the entry contains only query_text, result_ids, result_scores, collection, model_profile, tool_name, and timestamp — no raw user prompts or PII fields**
    - **Validates: Requirements 31.5**

- [x] 18. SageMaker Processing Jobs
  - [x] 18.1 Create `sagemaker_launcher.py`
    - `submit(script, instance_type, model, backend, collections, dry_run)` → submit SageMaker Processing Job
    - `estimate_cost(instance_type, estimated_minutes)` → cost estimate for `--dry-run`
    - `get_job_status(job_name)` → poll status, return counts and errors
    - Support GPU instance types (`ml.g5.xlarge`, `ml.g5.2xlarge`)
    - Package ingestion scripts, `ingestion_base.py`, `aws_backend.py`, `embedding_registry.py`, and dependencies
    - Report job status, document counts, errors to stdout and optionally S3
    - IAM permissions: OpenSearch, Neptune, S3, Bedrock, Secrets Manager
    - Support `--collections` for partial re-ingestion
    - File: `mcp_server_node/scripts/sagemaker_launcher.py`
    - _Requirements: 20.1, 20.2, 20.3, 20.4, 20.5, 21.1, 21.2, 21.3, 21.4, 22.1, 22.2, 22.3, 22.4, 22.5_

  - [x] 18.2 Create `Dockerfile.sagemaker` for ECR container
    - Python 3.11+ base, sentence-transformers, boto3, neo4j, chromadb, opensearch-py, fparser
    - Include embedding registry and all ingestion scripts
    - Support CPU and GPU base images via build argument
    - Rebuildable via single `docker build` command
    - File: `mcp_server_node/scripts/Dockerfile.sagemaker`
    - _Requirements: 23.1, 23.2, 23.3, 23.4, 23.5_

- [x] 19. Checkpoint — Ensure SageMaker launcher and container build work
  - Ensure all tests pass, ask the user if questions arise.

- [x] 20. Drift Detection
  - [x] 20.1 Create `drift_detector.py`
    - `detect(collection_name)` → sample N docs, re-embed, compute cosine similarity, return `DriftReport`
    - `check_stale_documents(collection_name)` → find docs whose source files modified/deleted
    - Configurable threshold (default: 0.95) and sample size (default: 100)
    - Output drift report to S3
    - Optionally trigger SageMaker re-ingestion job when drift exceeds threshold
    - Schedulable as CloudWatch Events rule
    - File: `mcp_server_node/scripts/drift_detector.py`
    - _Requirements: 29.1, 29.2, 29.3, 29.4, 29.5_

  - [x]* 20.2 Write property test: drift detection threshold behavior
    - **Property P17: For any collection where all stored embeddings are identical to freshly generated embeddings, `detect()` reports `drifted=False` with `mean_similarity >= threshold`**
    - **Validates: Requirements 29.1, 29.2**

- [x] 21. Retrieval Quality Benchmarking Framework
  - [x] 21.1 Create `benchmark_runner.py`
    - `run(ground_truth_file, vector_spaces, search_modes)` → `BenchmarkReport`
    - Compute precision@k, recall@k, MRR, nDCG per model/dimension/search_mode
    - Accept ground-truth file mapping queries to expected relevant documents
    - Output comparison report (JSON + markdown)
    - Upload results to S3 with timestamps
    - Support running as SageMaker Processing Job
    - File: `mcp_server_node/scripts/benchmark_runner.py`
    - _Requirements: 27.1, 27.2, 27.3, 27.4, 27.5_

- [x] 22. Domain-Adaptive Fine-Tuning Pipeline
  - [x] 22.1 Create `fine_tuning_pipeline.py`
    - `generate_training_pairs(collection_name)` → auto-generate positive pairs (same-section) and hard negatives
    - `train(base_model, training_data, output_s3_path, instance_type)` → submit SageMaker Training Job, return model S3 path
    - `register_model(model_s3_path, short_name)` → register fine-tuned model in `EmbeddingModelRegistry`
    - Output training metrics (loss curve, validation MRR) and before/after benchmark comparison
    - Accept feedback log (Req 31) as additional training data source
    - File: `mcp_server_node/scripts/fine_tuning_pipeline.py`
    - _Requirements: 30.1, 30.2, 30.3, 30.4, 30.5, 31.3_

  - [x] 22.2 Create `hard_negative_miner.py`
    - `mine(graph_driver, collection_name)` → list of (anchor, positive, hard_negative) triples
    - Use Neptune graph distance as difficulty signal: 1-hop apart but different labels/communities
    - Output triples compatible with Sentence Transformers `TripletLoss` or `MultipleNegativesRankingLoss`
    - Runnable standalone or as preprocessing step in fine-tuning pipeline
    - File: `mcp_server_node/scripts/hard_negative_miner.py`
    - _Requirements: 32.1, 32.2, 32.3, 32.4_

- [x] 23. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Python components (registry, provider, base, SageMaker, drift, fine-tuning) live under `mcp_server_node/scripts/`
- Node.js components (hybrid search, graph augmenter, Matryoshka, feedback) live under `mcp_server_node/src/data/`
- Property tests use `fast-check` for Node.js components and `hypothesis` or `pytest` for Python components
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation between major layers
- Backward compatibility with existing 86K documents and 51 MCP tools is maintained throughout
