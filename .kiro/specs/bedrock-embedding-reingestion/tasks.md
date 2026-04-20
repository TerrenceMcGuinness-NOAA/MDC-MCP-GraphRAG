# Implementation Plan

- [x] 1. Create titan1024 OpenSearch indices
  - [x] 1.1 Run index creation script
    - `OPENSEARCH_ENDPOINT=https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com node scripts/create-opensearch-indices.js --model titan1024`
    - Creates 5 indices: mdc-code-context-titan1024, mdc-workflow-docs-titan1024, mdc-jjobs-titan1024, mdc-community-summaries-titan1024, mdc-ee2-standards-titan1024
    - Each with 1024-dim knn_vector, HNSW, cosinesimil, BM25 content field
    - _Requirements: 1.1, 1.2, 1.3, 1.4_
  - [x] 1.2 Verify indices exist
    - Query `_cat/indices?v` and confirm 10 total indices (5 mpnet768 + 5 titan1024)
    - _Requirements: 1.5_

- [x] 2. Re-ingest all 5 collections with Bedrock Titan embeddings
  - [x] 2.1 Ingest code-with-context (~60,576 docs — largest, run first)
    - `python3 scripts/ingest_code_v8.py --model titan1024 --backend aws`
    - Verify doc count in mdc-code-context-titan1024 matches mpnet768 ±1%
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_
  - [x] 2.2 Ingest global-workflow-docs (~22,498 docs)
    - `python3 scripts/ingest_documentation_v8.py --model titan1024 --backend aws`
    - Verify doc count matches mpnet768 ±1%
    - _Requirements: 3.1, 3.2, 3.3_
  - [x] 2.3 Ingest jjobs (~700 docs)
    - `python3 scripts/ingest_jjobs_v8.py --model titan1024 --backend aws`
    - _Requirements: 4.1_
  - [x] 2.4 Ingest community-summaries (~2,113 docs)
    - `python3 scripts/ingest_shell_graph_v8.py --model titan1024 --backend aws`
    - _Requirements: 4.2_
  - [x] 2.5 Ingest ee2-standards (~34 docs)
    - `python3 scripts/ingest_ee2_v7.py --model titan1024 --backend aws`
    - _Requirements: 4.3_
  - [x] 2.6 Verify total titan1024 doc count across all 5 indices
    - Should be ~85,921 matching mpnet768 total ±1%
    - _Requirements: 4.4_

- [x] 3. Checkpoint — Verify re-ingestion complete
  - All 5 titan1024 indices populated, doc counts match mpnet768 baseline

- [x] 4. Create ground truth and run benchmark
  - [x] 4.1 Create ground truth file
    - At least 20 queries spanning all 5 collection domains
    - Store at `mcp_server_node/scripts/config/benchmark_ground_truth.json`
    - Include keyword, multi-concept, code identifier, and natural language queries
    - _Requirements: 5.1, 5.2, 5.3, 5.4_
  - [x] 4.2 Run benchmark: titan1024 vs mpnet768
    - `python3 scripts/benchmark_runner.py scripts/config/benchmark_ground_truth.json`
    - Compute precision@5, precision@10, recall@5, recall@10, MRR, nDCG
    - Evaluate vector and hybrid search modes for both models (4 result rows)
    - Include latency measurements (p50, p95, p99)
    - Upload report to S3
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [x] 5. Test Matryoshka queries with Nova embeddings
  - [x] 5.1 Create nova1024 index and ingest subset
    - `node scripts/create-opensearch-indices.js --model nova1024`
    - Ingest at least 100 docs from workflow-docs using nova1024
    - _Requirements: 7.1_
  - [x] 5.2 Test MatryoshkaQuery at dimensions 256, 512, 1024
    - Run same queries at each dimension level
    - Document quality/latency tradeoff
    - _Requirements: 7.2, 7.3, 7.4_

- [x] 6. Establish drift detection baselines
  - [x] 6.1 Run drift detector on all 5 titan1024 collections
    - `python3 scripts/drift_detector.py <collection> --backend aws --sample-size 100` × 5
    - Expect mean_similarity ≥ 0.99 (freshly ingested)
    - Upload reports to S3
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

- [x] 7. Validate hybrid search with titan1024
  - [x] 7.1 Run 5+ hybrid search queries against titan1024 indices
    - Include code identifier queries (camelCase, snake_case, file paths)
    - Verify BM25 + vector results combined
    - Compare rankings with mpnet768 hybrid results
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

- [x] 8. SageMaker container build and test (optional) — **DEFERRED**
  - Deferred to future SageMaker exploration phase. All code exists (Dockerfile.sagemaker, sagemaker_launcher.py); requires admin IAM role creation (SAGEMAKER_ROLE_ARN).
  - _Requirements: 9.1–9.5 — deferred, not blocked_

- [x] 9. Documentation and wrap-up
  - [x] 9.1 Update CHANGELOG.md with Bedrock re-ingestion results
  - [x] 9.2 Update steering file with Phase 52 completion
  - [x] 9.3 Commit all changes
