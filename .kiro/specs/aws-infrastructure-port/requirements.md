# Requirements Document

## Introduction

This document defines the requirements for porting the MDC MCP RAG Server from its legacy Docker-based infrastructure on NOAA Parallel Works VMs to AWS-native services. The system provides 51 MCP tools across 9 modules for NOAA Global Workflow AI assistance, backed by graph and vector databases. The migration replaces Docker Compose orchestration with Amazon Neptune (graph), Amazon OpenSearch (vector search), ECS Fargate (MCP server hosting), API Gateway (HTTP transport), CloudFront (CDN/WAF), and CDK for infrastructure as code. All new infrastructure uses `mdc-mcp-rag` naming per the EIB → MDC institutional rename.

## Glossary

- **MCP_Server**: The Node.js Model Context Protocol server hosting 51 tools across 9 modules for NOAA Global Workflow AI assistance
- **Neptune**: Amazon Neptune graph database service, replacing Neo4j, using openCypher query language
- **OpenSearch**: Amazon OpenSearch Service with k-NN plugin, replacing ChromaDB for vector search
- **ECS_Fargate**: AWS Elastic Container Service with Fargate launch type for serverless container hosting
- **CDK**: AWS Cloud Development Kit (TypeScript) used for infrastructure as code
- **VectorDatabaseAdapter**: Interface abstracting vector search operations across ChromaDB (legacy) and OpenSearch (AWS) backends
- **GraphDatabaseAdapter**: Interface abstracting graph query operations across Neo4j (legacy) and Neptune (AWS) backends
- **UnifiedDataAccess**: Facade providing tool modules with backend-agnostic database access via adapter pattern
- **APOC**: A Package Of Components — Neo4j plugin library not supported by Neptune, requiring query transformation
- **MPNet**: The `all-mpnet-base-v2` sentence transformer model producing 768-dimensional embeddings
- **Legacy_System**: The existing Docker-based MCP RAG server running on NOAA Parallel Works VMs via `eib-mcp-gateway`
- **Migration_Script**: Tooling that exports data from the legacy system and imports it into AWS services
- **Health_Endpoint**: The `/health` or `mcp_health_check` tool reporting system status
- **Secrets_Manager**: AWS Secrets Manager service for storing and retrieving credentials
- **SSM_Parameter_Store**: AWS Systems Manager Parameter Store for non-secret configuration values
- **WAF**: AWS Web Application Firewall for DDoS protection and request filtering
- **Cognito**: Amazon Cognito user pool providing OAuth 2.0 authentication

## Requirements

### Requirement 1: Database Adapter Layer

**User Story:** As a tool module developer, I want database access abstracted behind adapter interfaces, so that the 51 MCP tools work identically against legacy or AWS backends without code changes.

#### Acceptance Criteria

1. THE VectorDatabaseAdapter SHALL expose `connect()`, `query()`, `multiCollectionQuery()`, `addDocuments()`, `listCollections()`, `getCollectionCount()`, `healthCheck()`, and `close()` methods
2. THE GraphDatabaseAdapter SHALL expose `connect()`, `query()`, `findCallers()`, `traceCallChain()`, `getStatistics()`, `healthCheck()`, and `close()` methods
3. WHEN the `DB_BACKEND` environment variable or SSM parameter `/mdc-mcp-rag/db-backend` is set to `aws`, THE UnifiedDataAccess SHALL instantiate OpenSearch and Neptune adapters
4. WHEN the `DB_BACKEND` environment variable or SSM parameter is set to `legacy`, THE UnifiedDataAccess SHALL instantiate ChromaDB and Neo4j adapters
5. WHEN an unknown backend value is provided, THE UnifiedDataAccess SHALL return a descriptive error identifying the invalid value
6. THE OpenSearch adapter `query()` method SHALL return results in the same format as the existing ChromaDB `_formatQueryResults()` output
7. THE Neptune adapter `query()` method SHALL return records in the same format as the existing Neo4j `_recordToObject()` output

### Requirement 2: APOC Query Transformation

**User Story:** As a graph query consumer, I want APOC procedure calls transparently replaced with openCypher equivalents, so that existing Cypher queries work on Neptune without modification.

#### Acceptance Criteria

1. WHEN a Cypher query contains `apoc.path.expand`, THE Neptune adapter SHALL replace it with variable-length path patterns in openCypher
2. WHEN a Cypher query contains `apoc.algo.dijkstra`, THE Neptune adapter SHALL replace it with Neptune shortest path or Gremlin equivalent
3. WHEN a Cypher query contains `apoc.periodic.iterate`, THE Neptune adapter SHALL replace it with batched UNWIND queries
4. WHEN a Cypher query contains `apoc.create.node`, THE Neptune adapter SHALL replace it with standard CREATE syntax
5. WHEN a Cypher query contains `apoc.merge.node`, THE Neptune adapter SHALL replace it with MERGE with ON CREATE SET / ON MATCH SET syntax
6. WHEN a Cypher query contains an APOC procedure not in the replacement map, THE Neptune adapter SHALL throw an `UnsupportedQueryError` identifying the specific APOC procedure
7. THE Neptune adapter SHALL preserve the semantic meaning of each query after APOC transformation

### Requirement 3: MCP Tool Interface Preservation

**User Story:** As an MCP client (Kiro, VS Code), I want all 51 tools to expose identical input schemas and output formats on AWS, so that no client-side changes are required after migration.

#### Acceptance Criteria

1. THE MCP_Server SHALL expose all 51 tools across 9 modules (WorkflowInfoTools, CodeAnalysisTools, SemanticSearchTools, EE2ComplianceTools, OperationalTools, GraphRAGTools, GitHubTools, SDDWorkflowTools, Health/Misc) on the AWS deployment
2. WHEN a tool is invoked on the AWS backend, THE MCP_Server SHALL return output conforming to the same JSON schema as the legacy backend
3. WHEN the MCP_Server starts on ECS Fargate, THE MCP_Server SHALL register all 51 tools in `full` scenario mode
4. THE MCP_Server SHALL accept Streamable HTTP transport via API Gateway, replacing the legacy Docker MCP Gateway on port 18888

### Requirement 4: Data Migration

**User Story:** As a system administrator, I want to migrate all graph and vector data from the legacy system to AWS services, so that the AWS deployment has complete data parity.

#### Acceptance Criteria

1. WHEN the Migration_Script exports Neo4j data, THE Migration_Script SHALL produce a complete graph dump and upload it to the S3 staging bucket `s3://mdc-mcp-rag-migration/graph/`
2. WHEN the Migration_Script exports ChromaDB collections, THE Migration_Script SHALL export embeddings, metadata, and content for all 5 collections to `s3://mdc-mcp-rag-migration/vectors/`
3. WHEN the Migration_Script loads graph data into Neptune, THE Migration_Script SHALL use the Neptune bulk loader with the S3 staging path
4. WHEN the Migration_Script loads vector data into OpenSearch, THE Migration_Script SHALL bulk-index documents into the corresponding OpenSearch index for each collection
5. WHEN migration completes, THE Migration_Script SHALL verify that Neptune node count equals the legacy Neo4j node count
6. WHEN migration completes, THE Migration_Script SHALL verify that Neptune relationship count equals the legacy Neo4j relationship count
7. WHEN migration completes, THE Migration_Script SHALL verify that each OpenSearch index document count equals the corresponding ChromaDB collection document count
8. IF the Migration_Script fails mid-execution, THEN THE Migration_Script SHALL support idempotent re-execution by tracking watermarks and resuming from the last successful point

### Requirement 5: Embedding Fidelity

**User Story:** As a semantic search user, I want embeddings preserved exactly during migration, so that search relevance is maintained without re-embedding.

#### Acceptance Criteria

1. THE Migration_Script SHALL transfer 768-dimensional MPNet embeddings from ChromaDB to OpenSearch without re-generating them
2. THE OpenSearch indices SHALL use `knn_vector` field type with dimension 768, `nmslib` engine, `cosinesimil` space type, and `hnsw` method
3. WHEN a vector query is executed on OpenSearch, THE OpenSearch adapter SHALL return results with cosine similarity scores normalized to the range [0, 1]

### Requirement 6: Search Relevance Parity

**User Story:** As a developer using semantic search tools, I want search results on AWS to be comparable to legacy results, so that the migration does not degrade search quality.

#### Acceptance Criteria

1. WHEN the same query is executed against both OpenSearch and ChromaDB, THE search results SHALL have a ranking similarity within 5% tolerance (epsilon = 0.05)
2. WHEN a vector query includes metadata filters, THE OpenSearch adapter SHALL apply filters using OpenSearch bool query with filter clause, producing equivalent filtering to ChromaDB metadata filters
3. WHEN a multi-collection query is executed, THE OpenSearch adapter SHALL search across the corresponding OpenSearch indices and merge results, matching the behavior of ChromaDB multi-collection search

### Requirement 7: CDK Infrastructure as Code

**User Story:** As a DevOps engineer, I want all AWS infrastructure defined in CDK TypeScript stacks, so that environments are reproducible and version-controlled.

#### Acceptance Criteria

1. THE CDK project SHALL define four stacks: `MdcVpcStack`, `MdcDataStack`, `MdcSecurityStack`, and `MdcServerStack`
2. THE MdcVpcStack SHALL provision a VPC with public and private subnets, NAT Gateway, and VPC endpoints for Secrets Manager, SSM, CloudWatch, and S3
3. THE MdcDataStack SHALL provision a Neptune cluster, OpenSearch domain, EFS filesystem, and S3 staging bucket
4. THE MdcSecurityStack SHALL provision a Cognito user pool, WAF web ACL, Secrets Manager entries, and IAM roles
5. THE MdcServerStack SHALL provision an ECS cluster, Fargate task definition, Application Load Balancer, API Gateway, and CloudFront distribution
6. THE MdcServerStack SHALL depend on MdcVpcStack, MdcDataStack, and MdcSecurityStack

### Requirement 8: Configuration and Secrets Management

**User Story:** As a security-conscious operator, I want credentials stored in Secrets Manager and configuration in SSM Parameter Store, so that no secrets are hardcoded or exposed.

#### Acceptance Criteria

1. THE MCP_Server SHALL retrieve database credentials from Secrets Manager at paths `mdc-mcp-rag/neptune/credentials` and `mdc-mcp-rag/github/token`
2. THE MCP_Server SHALL retrieve service endpoints from SSM Parameter Store at paths `/mdc-mcp-rag/neptune/endpoint` and `/mdc-mcp-rag/opensearch/endpoint`
3. THE MCP_Server SHALL cache resolved configuration for the lifetime of the process to avoid repeated API calls
4. IF Secrets Manager or SSM Parameter Store is unavailable, THEN THE MCP_Server SHALL fall back to environment variables with a warning log
5. THE CDK stacks SHALL NOT output any secret values (credentials, tokens) in CloudFormation outputs
6. THE MCP_Server SHALL NOT log secret values to CloudWatch or container stdout/stderr


### Requirement 9: ECS Fargate MCP Server Hosting

**User Story:** As a platform operator, I want the MCP server running as an ECS Fargate service, so that it is managed, scalable, and does not require Docker on the host.

#### Acceptance Criteria

1. THE ECS Fargate task SHALL run the `UnifiedMCPServer.js` in `full` scenario mode with 1 vCPU and 2GB memory
2. THE ECS Fargate service SHALL maintain a minimum desired task count of 1 to avoid cold starts
3. WHEN request volume increases, THE ECS Fargate service SHALL auto-scale up to the configured maximum task count
4. THE ECS Fargate task SHALL connect to Neptune and OpenSearch via VPC private networking
5. THE ECS Fargate task SHALL pull secrets from Secrets Manager at startup using the task IAM role
6. THE Application Load Balancer SHALL perform health checks against the MCP_Server health endpoint

### Requirement 10: API Gateway and CloudFront Layer

**User Story:** As an MCP client, I want to connect to the MCP server via a secure HTTPS endpoint with OAuth 2.0 authentication, so that the server is accessible and protected.

#### Acceptance Criteria

1. THE CloudFront distribution SHALL terminate TLS and forward requests to the Application Load Balancer
2. THE WAF web ACL SHALL provide rate limiting, geo-restriction, and SQL injection protection on the CloudFront distribution
3. THE API Gateway SHALL route `/mcp` requests to the ECS Fargate service via the Application Load Balancer
4. THE Cognito user pool SHALL validate OAuth 2.0 tokens for all external MCP requests
5. THE MCP_Server SHALL expose a Protected Resource Metadata endpoint per RFC 9728 for MCP client discovery

### Requirement 11: Health Check and Monitoring

**User Story:** As an operations engineer, I want health checks that accurately reflect system state, so that degraded services are detected and alerted on promptly.

#### Acceptance Criteria

1. WHEN the Health_Endpoint is invoked, THE MCP_Server SHALL report `healthy` only when both the vector database and graph database connections are active, at least 5 collections/indices exist, and node count is greater than zero
2. WHEN either database connection is lost, THE Health_Endpoint SHALL report `degraded` with details identifying which database is unreachable
3. WHEN the Health_Endpoint reports `degraded`, THE MCP_Server SHALL continue serving tools that do not require the unavailable database
4. THE CDK stacks SHALL provision CloudWatch dashboards and alarms for ECS task health, Neptune performance, and OpenSearch cluster status

### Requirement 12: Network Security

**User Story:** As a security engineer, I want all database services isolated in private subnets with least-privilege access, so that the attack surface is minimized.

#### Acceptance Criteria

1. THE Neptune cluster and OpenSearch domain SHALL reside in private subnets with no public IP addresses
2. THE security groups SHALL allow ECS Fargate tasks to connect to Neptune on port 8182 and OpenSearch on port 443, and deny all other inbound traffic to those services
3. THE VPC SHALL include VPC endpoints for Secrets Manager, SSM Parameter Store, CloudWatch, and S3 to avoid internet routing for AWS API calls
4. THE Neptune cluster SHALL use IAM authentication instead of username/password authentication

### Requirement 13: Data Encryption

**User Story:** As a compliance officer, I want all data encrypted at rest and in transit, so that sensitive NOAA data is protected.

#### Acceptance Criteria

1. THE Neptune cluster, OpenSearch domain, EFS filesystem, and S3 buckets SHALL encrypt data at rest using AWS KMS
2. THE MCP_Server SHALL use TLS 1.2 or higher for all connections to Neptune, OpenSearch, Secrets Manager, and SSM Parameter Store
3. THE Cognito client secrets SHALL be rotatable via Secrets Manager rotation Lambda

### Requirement 14: Error Handling and Resilience

**User Story:** As a system operator, I want the MCP server to handle infrastructure failures gracefully, so that partial outages do not cause complete service loss.

#### Acceptance Criteria

1. IF Neptune is unreachable, THEN THE MCP_Server SHALL mark graph-dependent tools as degraded and continue serving filesystem-only and vector-search tools
2. IF an OpenSearch index is missing, THEN THE MCP_Server SHALL return empty results for affected collections with a warning message and report `degraded` health status
3. IF Secrets Manager is throttled, THEN THE MCP_Server SHALL use cached secrets and fall back to environment variables with a warning log
4. WHEN the Neptune connection fails, THE MCP_Server SHALL retry with exponential backoff (5s, 10s, 20s, max 60s)
5. IF the Migration_Script fails mid-execution, THEN THE Migration_Script SHALL resume from the last successful watermark on re-execution

### Requirement 15: Ingestion Pipeline Adaptation

**User Story:** As a data engineer, I want the 7 ingestion scripts adapted for AWS backends, so that data can be re-ingested directly into Neptune and OpenSearch.

#### Acceptance Criteria

1. THE ingestion scripts SHALL write graph data to Neptune via the bolt protocol using openCypher queries
2. THE ingestion scripts SHALL write vector data to OpenSearch via the bulk index API
3. THE ingestion scripts SHALL use the same MPNet embedding model (`all-mpnet-base-v2`, 768 dimensions) as the legacy system
4. WHEN a full re-ingestion cycle completes, THE ingestion scripts SHALL produce node counts, relationship counts, and document counts matching the legacy system within expected tolerances

### Requirement 16: Phased Rollout and Legacy Coexistence

**User Story:** As a project lead, I want the migration executed in phases with the legacy system remaining operational, so that there is no service disruption during the port.

#### Acceptance Criteria

1. WHILE the AWS system is being built (Phases 46A-46D), THE Legacy_System SHALL remain operational and accessible via the `eib-mcp-gateway` MCP connection
2. WHEN Phase 46E validation completes, THE MCP client configuration (`.kiro/settings/mcp.json`) SHALL be updated to point to the AWS endpoint
3. WHEN cutover occurs, THE Legacy_System SHALL be kept as a read-only fallback for 2 weeks
4. THE persistent data root on AWS SHALL be `/mdc-mcp-rag`, replacing the legacy `/mcp_rag_eib` path
5. THE CDK infrastructure code and all new AWS resources SHALL use `mdc-mcp-rag` naming convention per the EIB to MDC institutional rename

### Requirement 17: OpenSearch Index Design

**User Story:** As a search infrastructure engineer, I want OpenSearch indices correctly mapped to replace ChromaDB collections, so that all vector search operations function correctly.

#### Acceptance Criteria

1. THE OpenSearch domain SHALL define 5 indices: `mdc-code-context`, `mdc-workflow-docs`, `mdc-jjobs`, `mdc-community-summaries`, and `mdc-ee2-standards`
2. WHEN an index is created, THE index mapping SHALL include fields for `embedding` (knn_vector, 768-dim), `content` (text), `metadata` (object), `source_file` (keyword), `chunk_id` (keyword), and `collection_name` (keyword)
3. THE OpenSearch domain SHALL have the k-NN plugin enabled with `nmslib` engine for HNSW-based approximate nearest neighbor search
