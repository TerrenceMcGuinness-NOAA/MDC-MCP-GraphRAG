# Phase 48: AWS Infrastructure Port — SDD Workflow Spec

**Version**: 1.0.0
**Status**: Planned
**Created**: 2026-03-30
**Author**: GitHub Copilot (Claude Opus 4.6) + Terry McGuinness
**Branch**: `develop_aws`
**Kiro Spec Source**: `.kiro/specs/aws-infrastructure-port/` (requirements.md, design.md, tasks.md)

---

## 1. Executive Summary

Port the MDC MCP RAG Server from Docker-based Parallel Works VMs to AWS-native services. The system's 51 MCP tools across 9 modules must remain backward-compatible throughout migration. The legacy system (`eib-mcp-gateway`) stays operational during build-out; cutover occurs only after full validation.

**Scale of data being migrated**:
- Neo4j → Neptune: ~95K nodes, ~2.6M relationships
- ChromaDB → OpenSearch: ~85K documents across 5 collections, 768-dim MPNet embeddings
- Persistent filesystem → EFS: `/mcp_rag_eib` → `/mdc-mcp-rag`

**Key architectural decision**: Adapter pattern in `UnifiedDataAccess` provides the seam for swapping backends without modifying any tool module code.

**Kiro cross-reference**: This SDD phase is the execution tracking counterpart to the Kiro design-first spec at `.kiro/specs/aws-infrastructure-port/`. The Kiro spec is the requirements/design source of truth; this SDD spec is the execution/validation tracker.

---

## 2. Source-of-Truth Inputs

### 2.1 Kiro Specification (design authority)
- `.kiro/specs/aws-infrastructure-port/requirements.md` — 17 requirements, 80+ acceptance criteria
- `.kiro/specs/aws-infrastructure-port/design.md` — AWS topology, component mapping, sequence diagrams
- `.kiro/specs/aws-infrastructure-port/tasks.md` — 17 task groups across 5 sub-phases (46A–46E)

### 2.2 Kiro Steering (governance)
- `.kiro/steering/01-architecture-context.md` — Two-system architecture, branch strategy
- `.kiro/steering/02-development-workflow.md` — SDD methodology integration, code conventions
- `.kiro/steering/03-naming-conventions.md` — EIB → MDC rename rules

### 2.3 Legacy System Baseline
- MCP Server: `mcp_server_node/` — Node.js ES Modules, 51 tools, 9 modules
- Data layer: `mcp_server_node/src/data/` — `VectorDatabase.js` (ChromaDB), `GraphDatabase.js` (Neo4j)
- Ingestion: `mcp_server_node/scripts/` — 7 Python scripts
- Infrastructure: `SETUP/` — 15 provisioning shell scripts (reference only, not ported)
- Knowledge base: ChromaDB 5 collections (~85K docs), Neo4j (~95K nodes, ~2.6M rels)

### 2.4 Related SDD Phases
- **Phase 21**: Fully Portable MCP Container (Docker focus) — provides container patterns, not AWS-specific
- **Phase 22**: Validation & Benchmarking — quality gates reusable for AWS parity testing
- **Phase 44**: RAG Quality Assurance Framework — P@5, MRR, Coverage metrics baseline for search parity
- **Phase 46**: Knowledge Base Gap Closure — established the 85K-doc, 6-collection baseline being migrated

---

## 3. Target AWS Architecture

### 3.1 Service Topology

```
CloudFront + WAF → API Gateway → ALB → ECS Fargate (MCP Server)
                                         ├── Amazon Neptune (graph, openCypher)
                                         ├── Amazon OpenSearch (vector, k-NN)
                                         ├── Amazon EFS (/mdc-mcp-rag)
                                         ├── Secrets Manager (credentials)
                                         └── SSM Parameter Store (endpoints)

Amazon Cognito (OAuth 2.0) → CloudFront (token validation)
AWS CDK (TypeScript) → 4 stacks (VPC, Security, Data, Server)
```

### 3.2 Legacy → AWS Component Mapping

| Legacy Component | AWS Replacement | Sub-Phase |
|------------------|----------------|-----------|
| Docker Compose | Eliminated (ECS Fargate) | 48B |
| Docker MCP Gateway (Go, port 18888) | API Gateway (Streamable HTTP) | 48B |
| Neo4j (bolt://localhost:7687) | Amazon Neptune (openCypher, port 8182) | 48C |
| ChromaDB (http://localhost:8080/api/v2) | Amazon OpenSearch (k-NN, port 443) | 48C |
| Docker volumes (`/mcp_rag_eib`) | Amazon EFS (`/mdc-mcp-rag`) | 48A |
| `.env` files / `mcp-env.sh` | Secrets Manager + SSM Parameter Store | 48A |
| systemd services | ECS task lifecycle (automatic) | 48B |
| VNC desktop | Eliminated (Kiro IDE) | N/A |
| Spack module system | Amazon Linux packages + pip | 48D |

### 3.3 Database Adapter Architecture

```
Tool Modules (9 files in src/tools/) — NO CHANGES
       │
       ▼
UnifiedDataAccess (src/data/)
  ├── selectDatabaseBackend() → DB_BACKEND env/SSM
  │     ├── 'aws'    → OpenSearchAdapter + NeptuneAdapter
  │     └── 'legacy' → ChromaDBLegacyAdapter + Neo4jLegacyAdapter
  │
  ├── VectorDatabaseAdapter interface
  │     ├── OpenSearchAdapter.js     (NEW — k-NN, SigV4 auth)
  │     └── ChromaDBLegacyAdapter.js (NEW — wraps existing VectorDatabase.js)
  │
  └── GraphDatabaseAdapter interface
        ├── NeptuneAdapter.js        (NEW — openCypher, APOC transform)
        │     └── apoc-transform.js  (NEW — APOC → openCypher map)
        └── Neo4jLegacyAdapter.js    (NEW — wraps existing GraphDatabase.js)
```

---

## 4. APOC Procedure Transformation Map

Neptune does not support Neo4j APOC procedures. The following transformations are required:

| APOC Procedure | openCypher Replacement | Risk |
|---------------|----------------------|------|
| `apoc.path.expand` | Variable-length path patterns `(n)-[*1..depth]->(m)` | Medium — semantics differ for filtering |
| `apoc.algo.dijkstra` | Neptune shortest path / Gremlin fallback | High — no direct openCypher equivalent |
| `apoc.periodic.iterate` | Batched `UNWIND` queries with explicit chunking | Low |
| `apoc.create.node` | Standard `CREATE` | Low |
| `apoc.merge.node` | `MERGE ... ON CREATE SET / ON MATCH SET` | Low |
| Unknown APOC | Throw `UnsupportedQueryError` | Safety net |

**SDD added value**: The Kiro spec lists these transformations but doesn't quantify risk. The `apoc.algo.dijkstra` → Gremlin fallback is the highest-risk transformation and should be validated with the existing `trace_execution_path` and `trace_data_flow` tool outputs as golden files.

---

## 5. Risk Assessment

### 5.1 Technical Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| APOC dijkstra has no direct openCypher equivalent | High | Gremlin traversal fallback; golden-file test against legacy results |
| OpenSearch cosine similarity scoring differs from ChromaDB | Medium | 5% tolerance threshold (Req 6.1); normalize scores to [0,1] |
| Neptune bolt driver differs from Neo4j driver | Medium | Adapter pattern isolates changes; legacy adapter as reference |
| Merge from `develop` could clobber AWS work (Phase 47 precedent) | Medium | `develop_aws` branch isolation; merge only AWS→develop, never develop→AWS |
| EFS latency vs local Docker volumes | Low | Profile with representative workload; cache hot paths |
| Secrets Manager cold start in Fargate | Low | Cache for process lifetime (Req 8.3) |

### 5.2 Process Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Legacy system goes down during migration | High | Legacy untouched during 48A–48D; read-only fallback for 2 weeks post-cutover |
| Knowledge base grows during migration (new phases) | Medium | Migration script supports idempotent re-execution with watermarks |
| CDK drift from manual AWS console changes | Low | CDK diff check before every deploy |

### 5.3 Merge Strategy (lesson learned from Phase 47)

The Phase 47 Rocoto experience showed that merging `develop` into a feature branch can silently revert critical code. For `develop_aws`:
- **Never merge `develop` into `develop_aws`** without reviewing the diff for removals
- Completed SDD phases push to `develop` as finished units
- AWS-specific code lives exclusively on `develop_aws` until cutover

---

## 6. Sub-Phase Breakdown

### Phase 48A — Foundation: CDK Infrastructure + Configuration

**Kiro reference**: Tasks 1.1–1.4, 3.1–3.3
**SDD steps**: 1–5
**Files created**:
- `infrastructure/cdk/` — CDK TypeScript project
- `infrastructure/cdk/lib/mdc-vpc-stack.ts`
- `infrastructure/cdk/lib/mdc-security-stack.ts`
- `infrastructure/cdk/lib/mdc-data-stack.ts`
- `mcp_server_node/src/config/aws-config.js`

**Acceptance criteria**:
1. `cdk synth` succeeds for all 3 stacks (VPC, Security, Data)
2. VPC has public/private subnets across 2 AZs, NAT Gateway, 4 VPC endpoints
3. Security groups enforce ECS→Neptune (8182), ECS→OpenSearch (443), deny all other inbound
4. No secret values in CloudFormation outputs
5. `resolveConfig()` fetches from Secrets Manager/SSM, caches, falls back to env vars
6. Property tests pass: Configuration Caching (P12), Secret Non-Exposure (P11)

### Phase 48B — Adapters, Server Hosting, and API Layer

**Kiro reference**: Tasks 4.1–9.5
**SDD steps**: 6–14
**Files created**:
- `mcp_server_node/src/data/adapters/VectorDatabaseAdapter.js`
- `mcp_server_node/src/data/adapters/GraphDatabaseAdapter.js`
- `mcp_server_node/src/data/adapters/OpenSearchAdapter.js`
- `mcp_server_node/src/data/adapters/ChromaDBLegacyAdapter.js`
- `mcp_server_node/src/data/adapters/NeptuneAdapter.js`
- `mcp_server_node/src/data/adapters/Neo4jLegacyAdapter.js`
- `mcp_server_node/src/data/adapters/apoc-transform.js`
- `mcp_server_node/src/data/backend-selector.js`
- `infrastructure/docker/Dockerfile`
- `infrastructure/cdk/lib/mdc-server-stack.ts`

**Files modified**:
- `mcp_server_node/src/data/UnifiedDataAccess.js` — constructor injection of adapters
- `mcp_server_node/src/core/UnifiedMCPServer.js` — wire `selectDatabaseBackend()`

**Acceptance criteria**:
1. Adapter interfaces defined with all required methods
2. OpenSearch adapter returns results in same format as `VectorDatabase._formatQueryResults()`
3. Neptune adapter returns records in same format as `GraphDatabase._recordToObject()`
4. APOC transform handles all 5 known procedures; throws `UnsupportedQueryError` for unknown
5. Backend selector correctly routes `aws`/`legacy` modes
6. All 51 tools receive adapters transparently — zero tool code changes
7. ECS Fargate task definition: 1 vCPU, 2GB, `full` scenario, IAM task role
8. API Gateway routes `/mcp` to ECS via ALB; CloudFront + WAF + Cognito wired
9. Health endpoint reports `healthy`/`degraded` accurately per database state
10. Exponential backoff retry: 5s, 10s, 20s, max 60s
11. Property tests pass: Adapter Output Compatibility (P2), Score Normalization (P7), APOC Semantic Preservation (P3), Tool Interface Preservation (P1), Health Check Accuracy (P9), Graceful Degradation (P10), Retry Backoff (P13)

### Phase 48C — Data Migration and Search Validation

**Kiro reference**: Tasks 11.1–13.2
**SDD steps**: 15–19
**Files created**:
- `scripts/migrate-to-aws.js` — export/import with watermark tracking
- `scripts/validate-search-relevance.js` — 5% tolerance comparison
- OpenSearch index definitions (5 indices, CDK custom resource or script)

**Acceptance criteria**:
1. 5 OpenSearch indices created with correct mappings (knn_vector 768-dim, nmslib, cosinesimil, hnsw)
2. Neptune node count == legacy Neo4j node count
3. Neptune relationship count == legacy Neo4j relationship count
4. Each OpenSearch index doc count == corresponding ChromaDB collection count
5. 768-dim MPNet embeddings transferred without re-generation (bitwise fidelity)
6. Migration idempotent — re-run produces identical state, no duplicates
7. Search relevance within 5% tolerance for same queries across backends
8. Metadata filter and multi-collection query equivalence validated
9. Property tests pass: Data Completeness (P4), Migration Idempotence (P5), Embedding Fidelity (P6), Search Equivalence (P8)

**SDD added value — Golden File Baseline**:
Before migration, capture golden-file outputs from all 51 tools on the legacy system. These serve as the regression baseline for Phase 48E validation. The Phase 44 RAG Quality metrics (P@5=0.71, MRR=0.93, Coverage=93%) are the minimum acceptable thresholds.

### Phase 48D — Ingestion Pipeline Adaptation

**Kiro reference**: Task 14.1–14.2
**SDD steps**: 20–21
**Files modified** (7 Python scripts):
- `mcp_server_node/scripts/ingest_fortran_graph.py` — Neptune bolt/openCypher
- `mcp_server_node/scripts/ingest_code_v8.py` — Neptune (graph) + OpenSearch (vectors)
- `mcp_server_node/scripts/ingest_env_variables.py` — Neptune
- `mcp_server_node/scripts/ingest_jjobs_v8.py` — OpenSearch
- `mcp_server_node/scripts/ingest_documentation_v8.py` — OpenSearch
- `mcp_server_node/scripts/ingest_shell_graph_v8.py` — Neptune
- `mcp_server_node/scripts/ingest_cross_language_bridges.py` — Neptune

**Acceptance criteria**:
1. All 7 scripts write to Neptune (graph) or OpenSearch (vectors) via adapter-selected backend
2. Same MPNet embedding model preserved (`all-mpnet-base-v2`, 768-dim)
3. Full re-ingestion produces counts matching legacy within expected tolerances
4. Integration test: complete re-ingestion cycle end-to-end

**SDD added value — Dual-Write Validation**:
The Kiro spec assumes scripts are modified to target AWS. A safer approach for validation: add a `--backend` flag to each script so they can target either backend. This allows running ingestion against both systems in parallel to verify count parity before committing to AWS-only mode.

### Phase 48E — Validation, Monitoring, and Cutover

**Kiro reference**: Tasks 16.1–16.3
**SDD steps**: 22–25
**Files created/modified**:
- CloudWatch dashboards/alarms (CDK constructs in `MdcServerStack`)
- `.kiro/settings/mcp.json` cutover script
- Golden file comparison test suite

**Acceptance criteria**:
1. CloudWatch dashboard shows ECS task health, Neptune performance, OpenSearch cluster status
2. Alarms configured for degraded health, high latency, task failures
3. All 51 tools pass golden-file comparison against legacy outputs
4. RAG quality metrics meet Phase 44 baseline: P@5 ≥ 0.71, MRR ≥ 0.93, Coverage ≥ 93%
5. MCP client config updated to AWS CloudFront endpoint
6. Legacy system retained as read-only fallback for 2 weeks
7. No regressions in non-AWS tool categories (WorkflowInfo, SDD tools — filesystem-only)

---

## 7. SDD Execution Steps (ISD-compatible)

| Step | Name | Sub-Phase | Tag | Kiro Task |
|------|------|-----------|-----|-----------|
| 0 | AWS EC2 provisioning scripts (SETUP_AWS/) | 48A | implement | 0.1–0.3 |
| 1 | Scaffold CDK project and VPC stack | 48A | implement | 1.1 |
| 2 | Define Security stack (Secrets Manager, Cognito, WAF, IAM) | 48A | implement | 1.2 |
| 3 | Define Data stack (Neptune, OpenSearch, EFS, S3) | 48A | implement | 1.3 |
| 4 | CDK unit tests + `cdk synth` validation | 48A | validate | 1.4, 2 |
| 5 | Implement `resolveConfig()` + property tests | 48A | implement | 3.1–3.3 |
| 6 | Define adapter interfaces (Vector + Graph) | 48B | design | 4.1 |
| 7 | Implement OpenSearch adapter | 48B | implement | 4.2 |
| 8 | Implement ChromaDB legacy adapter | 48B | implement | 4.3 |
| 9 | Implement Neptune adapter + APOC transform | 48B | implement | 5.1–5.2 |
| 10 | Implement Neo4j legacy adapter | 48B | implement | 5.3 |
| 11 | Implement backend selector + wire UnifiedDataAccess | 48B | implement | 6.1–6.2 |
| 12 | Adapter property tests (P1–P3, P7) | 48B | validate | 4.4–5.5, 6.3 |
| 13 | ECS Fargate + API Gateway + CloudFront CDK stack | 48B | implement | 8.1–8.3 |
| 14 | Health check + error handling + resilience | 48B | implement | 9.1–9.5 |
| 15 | Create OpenSearch index definitions | 48C | implement | 11.1 |
| 16 | Implement data migration script (export/import/watermark) | 48C | implement | 11.2 |
| 17 | Migration verification + count parity | 48C | validate | 11.3–11.6 |
| 18 | Capture golden-file baseline from legacy system | 48C | research | (SDD added) |
| 19 | Search relevance validation (5% tolerance) | 48C | validate | 13.1–13.2 |
| 20 | Adapt 7 ingestion scripts for AWS backends | 48D | implement | 14.1 |
| 21 | Integration test: full re-ingestion cycle | 48D | validate | 14.2 |
| 22 | CloudWatch dashboards + alarms | 48E | implement | 16.1 |
| 23 | Run all 51 tools against AWS + golden-file comparison | 48E | validate | 16.3 |
| 24 | MCP client cutover + legacy fallback documentation | 48E | configure | 16.2 |
| 25 | Final validation + SDD session completion + CHANGELOG | 48E | document | 17 |

**Total steps**: 26
**Tags used**: research, design, implement, validate, configure, document

---

## 8. Property Test Inventory

The Kiro spec defines 13 property-based tests using `fast-check`. These are mapped to SDD steps:

| ID | Property Name | Validates | SDD Step |
|----|--------------|-----------|----------|
| P1 | Tool Interface Preservation | Req 3.2 | 12 |
| P2 | Adapter Output Compatibility | Req 1.6, 1.7 | 12 |
| P3 | APOC Transformation Semantic Preservation | Req 2.7 | 12 |
| P4 | Data Completeness | Req 4.5–4.7 | 17 |
| P5 | Migration Idempotence | Req 4.8 | 17 |
| P6 | Embedding Fidelity | Req 5.1 | 17 |
| P7 | Score Normalization | Req 5.3 | 12 |
| P8 | Search Equivalence (5% tolerance) | Req 6.1–6.3 | 19 |
| P9 | Health Check Accuracy | Req 11.1–11.2 | 14 |
| P10 | Graceful Degradation | Req 11.3, 14.1–14.2 | 14 |
| P11 | Secret Non-Exposure | Req 8.5–8.6 | 5 |
| P12 | Configuration Caching | Req 8.3 | 5 |
| P13 | Retry Exponential Backoff | Req 14.4 | 14 |

---

## 9. SDD Enhancements Over Kiro Spec

Items added by this SDD spec that the Kiro design doesn't explicitly cover:

| Enhancement | Rationale |
|-------------|-----------|
| **Golden-file baseline capture** (Step 18) | Kiro mentions golden-file testing in 16.3 but doesn't schedule the capture step. Captured before migration ensures clean comparison baseline. |
| **Dual-write validation for ingestion** (Phase 48D) | `--backend` flag on ingestion scripts enables parallel validation against both systems before AWS-only commitment. |
| **Merge strategy documentation** (§5.3) | Phase 47 Rocoto experience showed merging `develop` can silently revert code. Explicit branch protection rules for `develop_aws`. |
| **RAG quality threshold gates** (Phase 48E) | Phase 44 metrics (P@5=0.71, MRR=0.93, Coverage=93%) as minimum acceptable AWS thresholds — Kiro Req 6 defines 5% tolerance but not absolute minimums. |
| **APOC risk quantification** (§4) | Kiro lists transformations; SDD adds risk ratings and identifies `dijkstra` as highest risk requiring Gremlin fallback validation. |
| **Ingestion script `--backend` flag** | Enables incremental validation without modifying the production ingestion path. |

---

## 10. Completion Definition

This phase is complete when:
- All 4 CDK stacks synthesize and deploy cleanly (`cdk deploy`)
- All 6 adapter files implement their interfaces with passing tests
- Data migration achieves count parity (nodes, relationships, documents)
- Embeddings are bitwise identical post-migration
- Search relevance is within 5% tolerance
- All 51 tools pass golden-file comparison on AWS
- RAG quality metrics meet Phase 44 baseline thresholds
- CloudWatch monitoring active with alarms
- MCP client config points to AWS endpoint
- Legacy system operational as read-only fallback
- CHANGELOG updated with Phase 48 entry
- SDD session completed with summary

---

## 11. Dependencies

```
Phase 48A (Foundation) ─────────────────┐
                                        ├── Phase 48B (Adapters + Server)
Phase 44 (RAG Quality baseline) ────────┘          │
                                                   ├── Phase 48C (Data + Search)
Phase 46 (Knowledge Base — data source) ───────────┘          │
                                                              ├── Phase 48D (Ingestion)
                                                              │          │
                                                              └──────────┼── Phase 48E (Validation + Cutover)
                                                                         │
Legacy system operational ───────────────────────────────────────────────┘
```
