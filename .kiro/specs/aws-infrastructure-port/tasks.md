# Implementation Plan: AWS Infrastructure Port (Phase 46)

## Overview

Port the MDC MCP RAG Server from Docker-based Parallel Works VMs to AWS-native services across 5 sub-phases (46A–46E). Implementation languages: JavaScript (ES Modules) for MCP server and adapters, TypeScript for CDK infrastructure, Python for ingestion scripts. Property-based tests use `fast-check`.

## Tasks

- [ ] 1. Phase 46A — Foundation: CDK Project and VPC Stack
  - [ ] 1.1 Scaffold CDK project and define `MdcVpcStack`
    - Create `infrastructure/cdk/` directory with CDK TypeScript project (`cdk init app --language typescript`)
    - Implement `MdcVpcStack` with VPC, public/private subnets across 2 AZs, NAT Gateway, and VPC endpoints for Secrets Manager, SSM, CloudWatch, and S3
    - _Requirements: 7.1, 7.2, 12.3_

  - [ ] 1.2 Define `MdcSecurityStack` with Secrets Manager and SSM entries
    - Create Secrets Manager entries at `mdc-mcp-rag/neptune/credentials` and `mdc-mcp-rag/github/token`
    - Create SSM Parameter Store entries at `/mdc-mcp-rag/neptune/endpoint` and `/mdc-mcp-rag/opensearch/endpoint`
    - Create Cognito user pool, WAF web ACL, and IAM roles for ECS task execution
    - Ensure no secret values appear in CloudFormation outputs
    - _Requirements: 7.4, 8.1, 8.2, 8.5, 10.4, 12.4, 16.5_

  - [ ] 1.3 Define `MdcDataStack` with Neptune, OpenSearch, EFS, and S3
    - Provision Neptune cluster (openCypher, IAM auth, private subnets, KMS encryption)
    - Provision OpenSearch domain with k-NN plugin enabled (`nmslib` engine, HNSW)
    - Provision EFS filesystem for `/mdc-mcp-rag` persistent mount
    - Provision S3 staging bucket `mdc-mcp-rag-migration`
    - Configure security groups: ECS → Neptune (8182), ECS → OpenSearch (443), deny all other inbound
    - _Requirements: 7.3, 12.1, 12.2, 13.1, 16.4, 17.3_

  - [ ]* 1.4 Write unit tests for CDK stacks
    - Test VPC has correct subnet configuration and VPC endpoints
    - Test security groups enforce least-privilege rules
    - Test no secrets in CloudFormation outputs
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 8.5, 12.1, 12.2_

- [ ] 2. Checkpoint — Verify CDK stacks synthesize cleanly
  - Ensure `cdk synth` succeeds for all three stacks, ask the user if questions arise.

- [ ] 3. Phase 46A — Configuration and Secrets Resolution
  - [ ] 3.1 Implement `resolveConfig()` in `mcp_server_node/src/config/aws-config.js`
    - Fetch credentials from Secrets Manager and endpoints from SSM Parameter Store
    - Cache resolved configuration for process lifetime (single API call per key)
    - Fall back to environment variables if Secrets Manager/SSM unavailable, with warning log
    - Ensure no secret values are logged to stdout/stderr
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.6_

  - [ ]* 3.2 Write property test for configuration caching (Property 12)
    - **Property 12: Configuration Caching** — For any sequence of config lookups within a process, only the first lookup calls Secrets Manager/SSM; subsequent lookups return cached values
    - **Validates: Requirements 8.3**

  - [ ]* 3.3 Write property test for secret non-exposure (Property 11)
    - **Property 11: Secret Non-Exposure** — For any config resolution, no secret value appears in log output, environment variable dumps, or CDK outputs
    - **Validates: Requirements 8.5, 8.6**

- [ ] 4. Phase 46B — Database Adapter Interfaces and OpenSearch Adapter
  - [ ] 4.1 Define `VectorDatabaseAdapter` and `GraphDatabaseAdapter` interfaces
    - Create `mcp_server_node/src/data/adapters/VectorDatabaseAdapter.js` with `connect()`, `query()`, `multiCollectionQuery()`, `addDocuments()`, `listCollections()`, `getCollectionCount()`, `healthCheck()`, `close()`
    - Create `mcp_server_node/src/data/adapters/GraphDatabaseAdapter.js` with `connect()`, `query()`, `findCallers()`, `traceCallChain()`, `getStatistics()`, `healthCheck()`, `close()`
    - _Requirements: 1.1, 1.2_

  - [ ] 4.2 Implement `OpenSearchAdapter` extending `VectorDatabaseAdapter`
    - Create `mcp_server_node/src/data/adapters/OpenSearchAdapter.js`
    - Implement `query()` using k-NN search with 768-dim embeddings, returning results in same format as `VectorDatabase._formatQueryResults()`
    - Implement `multiCollectionQuery()` searching across multiple OpenSearch indices and merging results
    - Implement metadata filter translation to OpenSearch bool query with filter clause
    - Use AWS Signature V4 for authentication
    - _Requirements: 1.1, 1.6, 5.2, 5.3, 6.2, 6.3, 17.1, 17.2_

  - [ ] 4.3 Implement `ChromaDBLegacyAdapter` wrapping existing `VectorDatabase`
    - Create `mcp_server_node/src/data/adapters/ChromaDBLegacyAdapter.js` wrapping existing `VectorDatabase.js` to conform to `VectorDatabaseAdapter` interface
    - _Requirements: 1.1, 1.4_

  - [ ]* 4.4 Write property test for adapter output compatibility (Property 2)
    - **Property 2: Adapter Output Compatibility** — For any query input, OpenSearch adapter `query()` output conforms to same structure as ChromaDB `_formatQueryResults()`, and Neptune adapter `query()` output conforms to Neo4j `_recordToObject()`
    - **Validates: Requirements 1.6, 1.7**

  - [ ]* 4.5 Write property test for score normalization (Property 7)
    - **Property 7: Score Normalization** — For any vector query result from OpenSearch adapter, all cosine similarity scores are in range [0, 1]
    - **Validates: Requirements 5.3**

- [ ] 5. Phase 46B — Neptune Adapter and APOC Transformation
  - [ ] 5.1 Implement `NeptuneAdapter` extending `GraphDatabaseAdapter`
    - Create `mcp_server_node/src/data/adapters/NeptuneAdapter.js`
    - Implement `query()` with APOC-to-openCypher transformation pipeline
    - Implement `findCallers()` and `traceCallChain()` using variable-length path patterns
    - Use Neptune bolt endpoint with IAM authentication
    - Return records in same format as `GraphDatabase._recordToObject()`
    - _Requirements: 1.2, 1.7, 12.4_

  - [ ] 5.2 Implement APOC replacement map and transformation engine
    - Create `mcp_server_node/src/data/adapters/apoc-transform.js`
    - Map `apoc.path.expand` → variable-length path patterns
    - Map `apoc.algo.dijkstra` → Neptune shortest path / Gremlin fallback
    - Map `apoc.periodic.iterate` → batched UNWIND queries
    - Map `apoc.create.node` → standard CREATE
    - Map `apoc.merge.node` → MERGE with ON CREATE SET / ON MATCH SET
    - Throw `UnsupportedQueryError` for unknown APOC procedures
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [ ] 5.3 Implement `Neo4jLegacyAdapter` wrapping existing `GraphDatabase`
    - Create `mcp_server_node/src/data/adapters/Neo4jLegacyAdapter.js` wrapping existing `GraphDatabase.js` to conform to `GraphDatabaseAdapter` interface
    - _Requirements: 1.2, 1.4_

  - [ ]* 5.4 Write property test for APOC transformation semantic preservation (Property 3)
    - **Property 3: APOC Transformation Semantic Preservation** — For any Cypher query containing a known APOC procedure, the transformed openCypher query produces semantically equivalent results
    - **Validates: Requirements 2.7**

  - [ ]* 5.5 Write unit tests for each APOC replacement
    - Test each of the 5 APOC replacements with input/output Cypher pairs
    - Test `UnsupportedQueryError` thrown for unknown APOC procedures
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

- [ ] 6. Phase 46B — Backend Selection and UnifiedDataAccess Wiring
  - [ ] 6.1 Implement `selectDatabaseBackend()` in `mcp_server_node/src/data/backend-selector.js`
    - Read `DB_BACKEND` env var or SSM parameter `/mdc-mcp-rag/db-backend`
    - Instantiate OpenSearch + Neptune adapters for `aws` backend
    - Instantiate ChromaDB + Neo4j legacy adapters for `legacy` backend
    - Return descriptive error for unknown backend values
    - Connect both adapters and verify health checks pass
    - _Requirements: 1.3, 1.4, 1.5_

  - [ ] 6.2 Refactor `UnifiedDataAccess` to accept adapter instances
    - Modify `mcp_server_node/src/data/UnifiedDataAccess.js` to accept `VectorDatabaseAdapter` and `GraphDatabaseAdapter` via constructor injection
    - Wire `selectDatabaseBackend()` into `UnifiedMCPServer.js` startup
    - Ensure all 51 tools receive adapters transparently — no tool code changes
    - _Requirements: 1.3, 1.4, 3.1, 3.2_

  - [ ]* 6.3 Write property test for tool interface preservation (Property 1)
    - **Property 1: Tool Interface Preservation** — For any MCP tool invocation, the output JSON schema is identical between legacy and AWS backends
    - **Validates: Requirements 3.2**

- [ ] 7. Checkpoint — Verify adapter layer and backend selection
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 8. Phase 46B — ECS Fargate, API Gateway, and CloudFront
  - [ ] 8.1 Create Dockerfile for MCP server
    - Create `infrastructure/docker/Dockerfile` with Node.js base image
    - Install dependencies, copy `mcp_server_node/` source
    - Set entrypoint to run `UnifiedMCPServer.js` in `full` scenario mode
    - Configure health check endpoint
    - _Requirements: 9.1, 9.4_

  - [ ] 8.2 Implement `MdcServerStack` CDK stack
    - Create ECS cluster and Fargate task definition (1 vCPU, 2GB memory)
    - Configure Fargate service with minimum desired count of 1
    - Configure auto-scaling based on request volume
    - Create Application Load Balancer with health check against MCP health endpoint
    - Create API Gateway routing `/mcp` to ECS via ALB
    - Create CloudFront distribution with WAF (rate limiting, geo-restriction, SQL injection protection)
    - Wire Cognito user pool for OAuth 2.0 token validation
    - Expose Protected Resource Metadata endpoint per RFC 9728
    - Configure ECS task IAM role with Secrets Manager access
    - Ensure TLS 1.2+ for all connections
    - _Requirements: 7.5, 7.6, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 10.1, 10.2, 10.3, 10.4, 10.5, 13.2_

  - [ ]* 8.3 Write unit tests for `MdcServerStack`
    - Test ECS task definition has correct CPU/memory
    - Test ALB health check configuration
    - Test CloudFront + WAF association
    - _Requirements: 9.1, 9.6, 10.1, 10.2_

- [ ] 9. Phase 46B — Health Check and Error Handling
  - [ ] 9.1 Implement health check logic in MCP server
    - Update health endpoint to report `healthy` only when both databases connected, ≥5 indices exist, and node count > 0
    - Report `degraded` with details when either database is unreachable
    - Continue serving tools that don't require the unavailable database when degraded
    - _Requirements: 11.1, 11.2, 11.3_

  - [ ] 9.2 Implement error handling and resilience patterns
    - Mark graph-dependent tools as degraded when Neptune is unreachable; continue serving filesystem and vector-search tools
    - Return empty results with warning for missing OpenSearch indices
    - Use cached secrets when Secrets Manager is throttled, fall back to env vars
    - Implement exponential backoff for Neptune connection retries (5s, 10s, 20s, max 60s)
    - _Requirements: 14.1, 14.2, 14.3, 14.4_

  - [ ]* 9.3 Write property test for health check accuracy (Property 9)
    - **Property 9: Health Check Accuracy** — For any combination of database connection states, health endpoint reports `healthy` iff both databases connected with ≥5 indices and node count > 0; reports `degraded` otherwise
    - **Validates: Requirements 11.1, 11.2**

  - [ ]* 9.4 Write property test for graceful degradation (Property 10)
    - **Property 10: Graceful Degradation** — For any tool not depending on an unavailable database, the tool continues to function; tools depending on missing OpenSearch index return empty results with warning
    - **Validates: Requirements 11.3, 14.1, 14.2**

  - [ ]* 9.5 Write property test for retry exponential backoff (Property 13)
    - **Property 13: Retry Exponential Backoff** — For any sequence of Neptune connection retries, delays follow 5s, 10s, 20s pattern with max 60s
    - **Validates: Requirements 14.4**

- [ ] 10. Checkpoint — Verify MCP server on ECS with health checks
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Phase 46C — OpenSearch Index Creation and Data Migration
  - [ ] 11.1 Create OpenSearch index definitions
    - Define 5 indices: `mdc-code-context`, `mdc-workflow-docs`, `mdc-jjobs`, `mdc-community-summaries`, `mdc-ee2-standards`
    - Each index mapping: `embedding` (knn_vector, 768-dim, nmslib, cosinesimil, hnsw), `content` (text), `metadata` (object, dynamic), `source_file` (keyword), `chunk_id` (keyword), `collection_name` (keyword)
    - Create as CDK custom resource or migration script initialization step
    - _Requirements: 17.1, 17.2, 17.3_

  - [ ] 11.2 Implement data migration script (`scripts/migrate-to-aws.js`)
    - Export Neo4j graph dump and upload to `s3://mdc-mcp-rag-migration/graph/`
    - Export ChromaDB collections (embeddings + metadata + content) for all 5 collections to `s3://mdc-mcp-rag-migration/vectors/`
    - Load graph data into Neptune via bulk loader
    - Bulk-index vector data into corresponding OpenSearch indices
    - Transfer 768-dim MPNet embeddings without re-generating
    - Track watermarks for idempotent re-execution on failure
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.8, 5.1_

  - [ ] 11.3 Implement migration verification
    - Assert Neptune node count equals legacy Neo4j node count
    - Assert Neptune relationship count equals legacy Neo4j relationship count
    - Assert each OpenSearch index document count equals corresponding ChromaDB collection count
    - Generate migration report with per-collection counts
    - _Requirements: 4.5, 4.6, 4.7_

  - [ ]* 11.4 Write property test for data completeness (Property 4)
    - **Property 4: Data Completeness** — For any migrated dataset, Neptune node/rel counts equal Neo4j counts, and each OpenSearch index doc count equals corresponding ChromaDB collection count
    - **Validates: Requirements 4.5, 4.6, 4.7, 15.4**

  - [ ]* 11.5 Write property test for migration idempotence (Property 5)
    - **Property 5: Migration Idempotence** — Running migration a second time on same data produces identical final state — no duplicates, no missing data, identical counts
    - **Validates: Requirements 4.8, 14.5**

  - [ ]* 11.6 Write property test for embedding fidelity (Property 6)
    - **Property 6: Embedding Fidelity** — For any document, the 768-dim MPNet embedding in OpenSearch after migration is bitwise identical to the source ChromaDB embedding
    - **Validates: Requirements 5.1**

- [ ] 12. Checkpoint — Verify data migration and count parity
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 13. Phase 46C — Search Relevance Validation
  - [ ] 13.1 Implement search relevance comparison tooling
    - Create `scripts/validate-search-relevance.js`
    - Execute same queries against both OpenSearch and ChromaDB
    - Compare top-k rankings with 5% tolerance (epsilon = 0.05)
    - Validate metadata filter equivalence
    - Validate multi-collection query equivalence
    - _Requirements: 6.1, 6.2, 6.3_

  - [ ]* 13.2 Write property test for search equivalence (Property 8)
    - **Property 8: Search Equivalence** — For any search query (including metadata filters and multi-collection), OpenSearch ranking similarity is within 5% tolerance of ChromaDB ranking
    - **Validates: Requirements 6.1, 6.2, 6.3**

- [ ] 14. Phase 46D — Ingestion Pipeline Adaptation
  - [ ] 14.1 Adapt ingestion scripts for AWS backends
    - Modify `ingest_fortran_graph.py` to write to Neptune via bolt/openCypher
    - Modify `ingest_code_v8.py` to write to Neptune (graph) and OpenSearch (vectors) via bulk API
    - Modify `ingest_env_variables.py` to write to Neptune
    - Modify `ingest_jjobs_v8.py` to write to OpenSearch
    - Modify `ingest_documentation_v8.py` to write to OpenSearch
    - Modify `ingest_shell_graph_v8.py` to write to Neptune
    - Modify `ingest_cross_language_bridges.py` to write to Neptune
    - Preserve MPNet embedding model (`all-mpnet-base-v2`, 768-dim)
    - _Requirements: 15.1, 15.2, 15.3_

  - [ ]* 14.2 Write integration tests for ingestion pipeline
    - Test full re-ingestion cycle produces expected node/rel/doc counts
    - _Requirements: 15.4_

- [ ] 15. Checkpoint — Verify ingestion pipeline on AWS backends
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 16. Phase 46E — Validation, Monitoring, and Cutover
  - [ ] 16.1 Implement CloudWatch dashboards and alarms
    - Create CloudWatch dashboard for ECS task health, Neptune performance, OpenSearch cluster status
    - Configure alarms for degraded health, high latency, task failures
    - Add as CDK constructs in `MdcServerStack`
    - _Requirements: 11.4_

  - [ ] 16.2 Implement MCP client configuration cutover
    - Create script to update `.kiro/settings/mcp.json` to point to AWS CloudFront endpoint
    - Document legacy system read-only fallback for 2-week coexistence period
    - _Requirements: 16.1, 16.2, 16.3_

  - [ ]* 16.3 Write integration tests for full MCP tool suite on AWS
    - Run all 51 tools against AWS backends
    - Compare output schemas with legacy system (golden file testing)
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [ ] 17. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation at each sub-phase boundary
- Property tests validate universal correctness properties from the design document using `fast-check`
- Implementation languages: JavaScript (ES Modules) for MCP server code, TypeScript for CDK, Python for ingestion scripts
- The `eib-mcp-gateway` legacy MCP connection must remain operational throughout Phases 46A–46D (Requirement 16.1)
- All new code and AWS resources use `mdc-mcp-rag` naming convention
