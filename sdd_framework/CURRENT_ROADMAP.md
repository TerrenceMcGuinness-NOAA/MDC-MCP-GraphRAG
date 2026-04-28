# MCP/RAG System — Current Roadmap

**Document Purpose**: Executive summary and prioritized delivery roadmap
**Last Updated**: April 14, 2026
**Lead**: Terrence McGuinness
**Status**: Active Development — v8.3.0, 51 tools, AWS-native (OpenSearch + Neptune)

---

## Current System Status

### Two-System Architecture

Development operates across two environments during the AWS port:

| System | Role | Infrastructure | Status |
|--------|------|----------------|--------|
| **Legacy (Parallel Works)** | Reference / development aid | Docker Compose, ChromaDB, Neo4j | Operational (read-only) |
| **AWS (EC2 + managed services)** | Production target | OpenSearch, Neptune, CDK, AgentCore | Operational (dev bridge) |

The `eib-mcp-gateway` MCP connection points at the legacy PW system. The AWS system runs
via `mcp-http-server.js` on port 3000 (temporary dev bridge, pending AgentCore deployment).

### AWS System (Primary)

| Component | Status | Metrics |
|-----------|--------|---------|
| **MCP Server** | Operational | v8.3.0, 51 tools across 9 modules |
| **OpenSearch** | Healthy | 5 indices, 85,921 documents, MPNet 768-dim |
| **Neptune** | Healthy | 59,759 nodes, 2,633,374 relationships |
| **CDK Stacks** | Deployed | VPC, Security, Data (Neptune + OpenSearch + EFS + S3) |
| **Adapter Layer** | Complete | OpenSearch + Neptune adapters, backend selector |
| **SDD Framework** | v6.0 / Phase 31 | 51 workflows, 29 sessions (27 completed) |
| **Git Submodules** | Complete | 16 repos registered under `supported_repos/` |

### Legacy System (Reference)

| Component | Status | Metrics |
|-----------|--------|---------|
| **ChromaDB** | Healthy | 6 collections, 85,995 documents |
| **Neo4j** | Degraded | 0 nodes (graph cleared after S3 export) |
| **Docker Gateway** | Operational | Port 18888, Streamable HTTP |

### OpenSearch Indices (AWS)

| Index | Documents | Content |
|-------|-----------|---------|
| `mdc-code-context-mpnet768` | 60,576 | Python, Fortran, Shell source code |
| `mdc-workflow-docs-mpnet768` | 22,498 | Documentation, READMEs, RTD sources |
| `mdc-jjobs-mpnet768` | 700 | J-Job scripts with structured metadata |
| `mdc-community-summaries-mpnet768` | 2,113 | Hierarchical community summaries (4 levels) |
| `mdc-ee2-standards-mpnet768` | 34 | EE2/NCO compliance standards |
| **Total** | **85,921** | |

### Neptune Graph (AWS)

| Label | Count | Source |
|-------|-------|--------|
| FortranSubroutine | 25,829 | `ingest_fortran_graph.py` |
| FortranFunction | 4,629 | `ingest_fortran_graph.py` |
| FortranModule | 4,214 | `ingest_fortran_graph.py` |
| PythonFunction | ~3,200 | `ingest_code_v8.py` |
| CodeFunction | ~5,000 | `ingest_code_v8.py` |
| EnvironmentVariable | ~2,700 | `ingest_env_variables.py` |
| ShellScript | ~314 | `ingest_shell_graph_v8.py` |
| Community | ~2,100 | Phase 24E hierarchical communities |
| *59,759 total nodes* | | Deduplicated from 98,813 raw exports |

### Neptune Relationship Summary (AWS)

| Type | Count | Notes |
|------|-------|-------|
| CALLS | 2,116,421 | Fortran subroutine/function calls |
| USES | 380,316 | Module USE statements |
| MEMBER_OF | 91,737 | Community membership |
| DEFINES | 11,350 | Symbol definitions |
| IMPORTS | 9,141 | Python imports |
| DEPENDS_ON_ENV | 7,499 | Environment variable references |
| SETS_ENV | 7,151 | Environment variable exports |
| INTERACTS_WITH | 4,934 | Inter-community edges |
| USES_ENV | 4,871 | Environment variable usage |
| DEPENDS_ON | 2,942 | Module/library + Rocoto task dependencies |
| SOURCES | 309 | Shell source statements |
| INVOKES | 348 | Shell invocations (J-Job to ex-script) |
| EXPORTS | 1,207 | Exported symbols |
| **Total** | **2,633,374** | |

---

## Ingestion Pipeline (Phase 49 — Restructured)

All scripts now subclass `BaseIngester` with registry-driven embedding model selection,
deterministic IDs, upsert semantics, and `--model`/`--backend` flags.

| Script | Target | Backend Support | Output |
|--------|--------|-----------------|--------|
| `ingest_code_v8.py` | Graph + Vector | legacy, aws | 60,576 docs, 5K+ nodes |
| `ingest_documentation_v8.py` | Vector | legacy, aws | 22,498 docs |
| `ingest_fortran_graph.py` | Graph | legacy, aws | 25,829+ nodes, 2.1M CALLS |
| `ingest_shell_graph_v8.py` | Graph + Vector | legacy, aws | 314 scripts, 2,113 community summaries |
| `ingest_jjobs_v8.py` | Vector | legacy, aws | 700 J-Job documents |
| `ingest_env_variables.py` | Graph | legacy, aws | 2,700+ env vars |
| `ingest_cross_language_bridges.py` | Graph | legacy, aws | EXECUTES + INVOKES edges |

### Embedding Model Registry

| Short Name | Provider | Dimensions | Status |
|------------|----------|------------|--------|
| `mpnet768` | Local (sentence-transformers) | 768 | Active (default) |
| `titan1024` | Bedrock (Titan V2) | 1024 | Planned (Phase 52) |
| `nova256` | Bedrock (Nova) | 256 | Registered |
| `nova512` | Bedrock (Nova) | 512 | Registered |
| `nova1024` | Bedrock (Nova) | 1024 | Registered |
| `nova3072` | Bedrock (Nova) | 3072 | Registered |

### Retrieval Enhancements (Phase 49C)

| Feature | File | Status |
|---------|------|--------|
| Hybrid Search (BM25 + Vector + RRF) | `HybridSearchBuilder.js` | Wired |
| Graph-Augmented Retrieval | `GraphAugmenter.js` | Wired |
| Matryoshka Adaptive Dimensions | `MatryoshkaQuery.js` | Wired |
| Comparative Multi-Model Query | `OpenSearchAdapter.comparativeQuery()` | Wired |
| Feedback Logger | `FeedbackLogger.js` | Wired (opt-in) |

---

## Completed Phases

### Legacy Platform (Parallel Works / Docker)

| Phase | Version | Deliverable |
|-------|---------|-------------|
| 4B | v7.3.0 | ISD Approval Gates (3 providers, persistent state) |
| 10 | v7.2.0 | Fortran Call Tree (17,575 nodes, 369K relationships) |
| 11E | v7.1.0 | n8n Workflow Automation (port 5678, MCP Gateway integration) |
| 12 | v7.0.0 | DevOps GitFlow and Containerization (4 environment branches) |
| 23 | v7.3.5 | Smart Container Cleanup (systemd timer, connection-aware) |
| 24A-D | v7.5-7.7 | GGSR Foundation (Graph-Guided Semantic Retrieval) |
| 24E | v7.20.0 | Hierarchical Communities (1,036 nodes, 4 levels, 828 summaries) |
| 24F | v7.8.0 | Cross-Language Integration (Shell to Fortran bridges) |
| 24G | v7.10.0 | Benchmark and Validation (60% vs 40% baseline) |
| 24H | v7.11.0 | Agentic Tool Surface (5 new MCP tools) |
| 25 | v7.12.0 | VNC Cleanup and Deprecation |
| 26 | v7.13.0 | Docker MCP Gateway systemd fix (port 18888) |
| 27A-J | v7.15-7.19 | J-Job RAG Enhancement (shell parser, graph, dedup, bridges) |
| 28 | v7.5.0 | GraphRAG Acceleration (GGSR prototypes, enrichment wiring) |
| 29 | v4.1.0 | Provisioning Modernization (VNC removed, scripts consolidated) |
| 30 | v7.14.0 | SDD Framework Cleanup (18 files deleted, 7 migrated) |
| 31 | v7.14.0 | SDD Execution Model (session-oriented tracking) |
| 32 | v7.21.0 | AI Instruction File Architecture |
| 34 | v7.22.0 | NCEPLIBS GraphRAG Integration |
| 35 | v7.23.0 | GitLab Runner Launch Hardening |
| 37 | v7.24.0 | PW MCP Tool Expansion (51 tools) |
| 38 | v7.25.0 | Knowledge Base Data Quality Normalization |
| 39 | v7.26.0 | UFS Fortran Graph Gap Closure |
| 40 | v7.28.0 | Config and CI File Ingestion (Rocoto DAG, experiments, Jinja2) |
| 41 | v7.31.0 | External Framework Documentation (ESMF, WW3, FV3, CMEPS) |
| 42 | v7.32.0 | JEDI Deep Submodule Coverage |
| 43/43a | v7.33.0 | Expert System Self-Diagnosis and Health Observability |
| 44 | v7.27.0 | RAG Quality Assurance Framework (P@5=0.71, MRR=0.93) |
| 45 | v7.34.0 | EnKF Surface Analysis CTest |
| 46 | v7.35.0 | Knowledge Base Gap Closure (85,995 docs, no domain below B-) |
| 47 | v7.36.0 | Rocoto Dryrun PR #124 Reconciliation |

### AWS Port (EC2 / Managed Services)

| Phase | Version | Deliverable |
|-------|---------|-------------|
| 48 | v8.0.0 | AWS Infrastructure Port (CDK stacks, adapter pattern, migration scripts, 26 SDD steps) |
| 49 | v8.1.0 | Ingestion Pipeline Restructure (BaseIngester, model registry, hybrid search, graph augmenter, SageMaker, drift detection) |
| 50 | v8.2.0 | Parallel Works S3 Migration Export (85,921 docs, 98,813 nodes, 2.6M rels to S3) |
| 50b | v8.2.1 | Neptune Bulk Loader Remediation (59,759 nodes, 2,633,374 rels, 0 errors) |
| 51 | v8.3.0 | AWS MCP Server Validation (45/45 tools pass, 9/9 healthy, adapter fixes, perf benchmarks) |

---

## Active / Immediate

| Phase | Priority | Goal | Status |
|-------|----------|------|--------|
| 53 | **High** | Neptune Recovery — Track B Re-Ingestion (Fortran ✅, Shell ✅, Bridges ✅, Python pending) | In progress |
| 51b | **High** | AgentCore MCP Deployment (replace dev bridge with managed AWS) | Blocked on IAM trust policy |
| 52 | **High** | Bedrock Embedding Re-ingestion (Titan 1024-dim, benchmark vs MPNet) | Complete |

---

## Q3 2026 — Path A: AgentCore Container Deployment

| Phase | Priority | Goal |
|-------|----------|------|
| 51b | **High** | Deploy Node.js MCP server to AgentCore Runtime (container, VPC mode, Cognito auth) |
| 54 | **High** | Remove dev bridge (port 3000), retire security group hack |

---

## Q4 2026–Q1 2027 — Path B: Full Python Port (Strands Agents SDK)

*Reference: `docs/presentations/papers/agentcore_strategic_assessment/AgentCore_Strategic_Assessment.tex`*

| Phase | Priority | Goal | Effort |
|-------|----------|------|--------|
| B1 | High | FastMCP wrapper + tool registration (Python scaffolding) | 1 week |
| B2 | High | OpenSearch adapter (Python) — reuse `aws_backend.py` | 1 week |
| B3 | High | Neptune adapter (Python) — openCypher via SigV4 HTTP | 2 weeks |
| B4 | High | SemanticSearchTools port (7 tools) | 1 week |
| B5 | High | CodeAnalysisTools port (6 tools) | 2 weeks |
| B6 | High | GraphRAGTools + GGSR port (9 tools) — most complex | 3 weeks |
| B7 | Medium | EE2ComplianceTools port (5 tools) | 1 week |
| B8 | Medium | OperationalTools port (4 tools) | 1 week |
| B9 | Medium | SDDWorkflowTools port (9 tools) | 1 week |
| B10 | Medium | WorkflowInfoTools port (3 tools) | 3 days |
| B11 | High | Strands agent layer — multi-agent orchestration | 2 weeks |
| B12 | Medium | AgentCore Memory integration (STM + LTM) | 1 week |
| B13 | Medium | AgentCore Gateway + Cedar Policy | 1 week |
| B14 | Medium | Observability (OpenTelemetry) + Evaluations | 1 week |

**Total estimated effort: ~16 weeks**

**Strategy**: Node.js server continues serving production during port. Each module validated against existing baseline before cutover. No big-bang migration.

---

## Q2 2027 — Path B Phase 3: Autonomous Agents

| Phase | Priority | Goal |
|-------|----------|------|
| B15 | Medium | Autonomous Code Analyst Agent (impact reports for PRs) |
| B16 | Medium | Autonomous Compliance Auditor (nightly EE2 scans) |
| B17 | Medium | Knowledge Curator Agent (stale embedding detection, auto re-ingestion) |
| B18 | Low | Browser-based Documentation Crawler (AgentCore Browser) |
| B19 | Low | Agent Registry publication (organizational tool catalog) |

---

## Planned (Deferred)

| Phase | Priority | Goal |
|-------|----------|------|
| 4C | Low | USD Sub-Agent Dispatch (superseded by Strands multi-agent in B11) |
| 4D | Medium | Multi-Tenant SDD Workspaces (team/user hierarchy) |
| 8 | Low | Multi-Modal Embeddings (diagrams, flowcharts) |
| 24I | Low | Learned Graph Embeddings |
| 24J | Low | Subgraph Retrieval |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    AWS Production Stack                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐            │
│  │  MCP Server  │  │  OpenSearch  │  │   Neptune    │            │
│  │  (Node.js)   │  │  5 indices   │  │  59K nodes   │            │
│  │  51 Tools    │  │  MPNet 768d  │  │  2.6M rels   │            │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘            │
│         └─────────────────┼─────────────────┘                    │
│                           │                                      │
│         ┌─────────────────┴─────────────────┐                    │
│         │     Hybrid Query Engine            │                   │
│         │  GGSR + BM25/RRF + Graph Augment   │                   │
│         └─────────────────┬─────────────────┘                    │
│                           │                                      │
│  ┌────────────────────────┼────────────────────────┐             │
│  │         Adapter Layer (Phase 48)                │             │
│  │  OpenSearchAdapter ←→ VectorDatabaseAdapter     │             │
│  │  NeptuneAdapter    ←→ GraphDatabaseAdapter      │             │
│  │  backend-selector.js (DB_BACKEND=aws|legacy)    │             │
│  └─────────────────────────────────────────────────┘             │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐            │
│  │  CDK Stacks  │  │  S3 Staging  │  │  SageMaker   │            │
│  │  VPC/Sec/Data│  │  Migration   │  │  (planned)   │            │
│  └──────────────┘  └──────────────┘  └──────────────┘            │
└──────────────────────────────────────────────────────────────────┘
                           │
     ┌─────────────────────┼─────────────────────┐
     │                     │                     │
┌────┴──────┐    ┌─────────┴────────┐    ┌───────┴──────┐
│   Kiro    │    │  HTTP Bridge     │    │  Legacy PW   │
│  (stdio)  │    │  (port 3000)     │    │  (reference) │
└───────────┘    └──────────────────┘    └──────────────┘
```

### MCP Tool Modules (51 tools / 9 modules)

| Module | Tools | Count | Database |
|--------|-------|-------|----------|
| WorkflowInfoTools | `get_workflow_structure`, `get_system_configs`, `describe_component` | 3 | Filesystem |
| CodeAnalysisTools | `analyze_code_structure`, `find_dependencies`, `trace_execution_path`, `find_callers_callees`, `trace_full_execution_chain`, `find_env_dependencies` | 6 | Neptune |
| SemanticSearchTools | `search_documentation`, `find_related_files`, `explain_with_context`, `get_knowledge_base_status`, `list_ingested_urls`, `get_ingested_urls_array`, `check_knowledge_integrity` | 7 | OpenSearch + Neptune |
| EE2ComplianceTools | `search_ee2_standards`, `analyze_ee2_compliance`, `generate_compliance_report`, `scan_repository_compliance`, `extract_code_for_analysis` | 5 | OpenSearch |
| OperationalTools | `get_operational_guidance`, `explain_workflow_component`, `list_job_scripts`, `get_job_details` | 4 | OpenSearch |
| GraphRAGTools | `get_code_context`, `search_architecture`, `find_similar_code`, `get_change_impact`, `trace_data_flow`, `mark_as_modified`, `get_session_context`, `checkpoint_state`, `restore_checkpoint` | 9 | OpenSearch + Neptune |
| GitHubTools | `search_issues`, `get_pull_requests`, `analyze_workflow_dependencies`, `analyze_repository_structure` | 4 | GitHub API |
| SDDWorkflowTools | `list_sdd_workflows`, `get_sdd_workflow`, `start_sdd_session`, `record_sdd_step`, `get_sdd_session`, `complete_sdd_session`, `get_sdd_execution_history`, `validate_sdd_compliance`, `get_sdd_framework_status` | 9 | Filesystem |
| Utility | `get_server_info`, `mcp_health_check`, `get_health_trend`, `get_quality_metrics` | 4 | Various |

### Server Scenarios

| Scenario | Command | Tools | Databases |
|----------|---------|-------|-----------|
| Full | `npm start` | 51 | OpenSearch + Neptune (or ChromaDB + Neo4j) |
| Core | `npm run start:core` | ~20 | Neptune/Neo4j only |
| RAG | `npm run start:rag` | ~38 | OpenSearch/ChromaDB + Neptune/Neo4j |
| GitHub | `npm run start:github` | ~24 | Neptune/Neo4j + GitHub API |

---

## SDD Framework

**Model**: `start_sdd_session` → `record_sdd_step` (repeat) → `complete_sdd_session`
**State**: Persists in `sdd_framework/execution_state/`
**Workflows**: 51 specs in `sdd_framework/workflows/`
**Sessions**: 29 total (27 completed, 2 in-progress on legacy tracker)
**Steps Tracked**: 250+ across all sessions

Phase naming convention: `phase<N><letter>_<descriptor>.md`
Currently at Phase 51b with sub-phases through the alphabet.

---

## Migration Parity (Phase 50/50b)

| Component | Legacy (PW) | AWS | Parity |
|-----------|-------------|-----|--------|
| Vector documents | 85,995 | 85,921 | 99.9% (74 ci-test-cases not migrated) |
| Graph nodes | 98,813 | 59,759 | Deduplicated (39K dupes removed) |
| Graph relationships | 2,653,565 | 2,633,374 | 99.2% (20K unresolvable endpoints from dedup) |
| Tool validation | — | 45/45 pass | All non-GitHub tools verified |
| Health check | 8/9 | 9/9 | AWS healthier (no graph degradation) |

---

## Value Proposition

### Delivered
- 51 MCP tools for code analysis, semantic search, compliance checking, SDD tracking
- 59,759 graph nodes with 2,633,374 relationships (Fortran, Python, Shell, env vars, communities)
- 85,921 searchable documents across 5 OpenSearch indices
- Graph-Guided Semantic Retrieval with hybrid BM25/vector/RRF fusion
- Adapter pattern for backend-agnostic database access (legacy or AWS)
- Full CDK infrastructure (VPC, Neptune, OpenSearch, EFS, S3, IAM)
- Registry-driven ingestion pipeline with multi-model embedding support
- EE2/NCO compliance scanning (demonstrated on seaice-concentration, EVS)
- SDD methodology with 29 tracked sessions across 51 workflow specs
- SageMaker launcher and Dockerfile for compute offloading (ready, not yet executed)
- Drift detection, benchmark runner, and fine-tuning pipeline (ready, not yet executed)

### Known Gaps
- **Dev bridge deployment** — MCP server runs via `mcp-http-server.js` on port 3000, not AgentCore (Phase 51b)
- **Single embedding model** — Only MPNet 768-dim active; Bedrock Titan 1024-dim pending (Phase 52)
- **No CI/CD pipeline** — Builds and tests are manual
- **Single-user** — No multi-tenant workspace support yet (Phase 4D)
- **APOC transform gap** — `trace_full_execution_chain` directed path patterns fail on Neptune (APOC transform incomplete)

---

## Resource Requirements

| Resource | Current | Status |
|----------|---------|--------|
| Developer time | 1 person (Terrence) | Sufficient for prototype |
| Compute (AWS EC2) | t3.xlarge | Active |
| Compute (Parallel Works) | Available | Reference only |
| AWS Services | Neptune, OpenSearch, S3, EFS | Deployed via CDK |
| GitHub Enterprise | NOAA-EMC | Available |
| Git submodules | 16 registered | Complete |

---

*"If it's not in the SDD, it doesn't get coded."*
