# MCP/RAG System — Current Roadmap

**Document Purpose**: Executive summary and prioritized delivery roadmap  
**Last Updated**: February 24, 2026  
**Lead**: Terrence McGuinness  
**Status**: Active Development — v7.20.0, 43 tools, Phase 31 SDD Model

---

## Current System Status

| Component | Status | Metrics |
|-----------|--------|---------|
| **MCP Server** | Operational | v7.20.0, 43 tools across 9 modules |
| **ChromaDB** | Healthy | 5 collections, 63,837 documents, MPNet 768-dim |
| **Neo4j** | Healthy | 41,355 nodes, 589,396 relationships, 28 label types |
| **Fortran Graph** | Complete (Phase 10) | 17,575 nodes, 440K CALLS, 91K USES |
| **Shell Graph** | Complete (Phase 27F/J) | 264 ShellScript (deduped), 63 ShellFunction, 9,155 relationships |
| **Docker Gateway** | Operational | Port 18888, Streamable HTTP, systemd service |
| **SDD Framework** | v6.0 / Phase 31 | 39 active workflows, 11 archived |
| **Git Submodules** | Complete | 16 repos registered under `supported_repos/` |

### ChromaDB Collections

| Collection | Documents | Content |
|------------|-----------|---------|
| `code-with-context-v8-0-0` | 58,761 | Python, Fortran, Shell source code |
| `global-workflow-docs-v8-0-0` | 3,514 | Documentation, READMEs |
| `jjobs-v8-0-0` | 700 | J-Job scripts with structured metadata |
| `community-summaries` | 828 | Hierarchical community summary embeddings (4 levels) |
| `ee2-standards-v5-0-0-enhanced` | 34 | EE2/NCO compliance standards |
| **Total** | **63,837** | |

### Neo4j Node Inventory

| Label | Count | Source |
|-------|-------|--------|
| FortranSubroutine | 13,537 | `ingest_fortran_graph.py` |
| CodeFunction | 5,059 | `ingest_code_v8.py` |
| PythonFunction | 3,267 | `ingest_code_v8.py` |
| EnvironmentVariable | 2,489 | `ingest_env_variables.py` |
| FortranModule | 1,539 | `ingest_fortran_graph.py` |
| FortranFunction | 2,355 | `ingest_fortran_graph.py` |
| FortranProgram | 169 | `ingest_fortran_graph.py` + cross-language bridges |
| ShellScript | 264 | `ingest_shell_graph_v8.py` (deduped, Phase 27J) |
| ShellFunction | 63 | `ingest_shell_graph_v8.py` (Phase 27F) |
| Commit | 2,880 | Git history ingestion |
| File | 2,744 | File-level nodes |
| Component | 66 | Workflow components |
| Community | 1,036 | Phase 24E-5 (L0:694, L1:175, L2:86, L3:81) |
| *28 label types total* | **41,355** | |

> **Community Detection**: Leiden algorithm (Phase 24E) with `includeIntermediateCommunities: true`. 1,036 Community nodes materialized across 4 hierarchical levels with MEMBER_OF (21,559), PARENT_OF (978), and INTERACTS_WITH (1,297) relationships. 828 level-aware summaries in both Neo4j and ChromaDB. Phase 24E-5 **COMPLETE** (v7.20.0).

### Neo4j Relationship Summary

| Type | Count | Notes |
|------|-------|-------|
| CALLS | 439,919 | Fortran subroutine/function calls |
| USES | 91,285 | Module USE statements |
| DEFINES | 9,753 | Symbol definitions |
| IMPORTS | 8,034 | Python imports |
| DEPENDS_ON_ENV | 5,522 | Environment variable references |
| AUTHORED | 2,880 | Developer → Commit |
| HAS_METHOD | 2,579 | Class → method |
| DOC_REFERENCES | 1,906 | Documentation cross-references |
| EXPORTS | 880 | Exported symbols |
| CONTRIBUTED_TO | 789 | Developer contributions |
| DEPENDS_ON | 752 | Module/library dependencies |
| SOURCES | 357 | Shell source statements |
| INVOKES | 243 | Shell invocations (J-Job → ex-script) |
| BUILT_BY | 207 | Build system relationships |
| INHERITS | 169 | Class inheritance |
| DOC_DESCRIBES | 144 | Documentation → code links |
| CONTAINS | 70 | Containment hierarchy |
| EXECUTES | 65 | Cross-language bridges (33 Shell→Fortran, 32 File→Fortran) |
| BUILD_ORCHESTRATES | 7 | Build orchestration |
| MEMBER_OF | 21,559 | Community membership (Phase 24E-5) |
| PARENT_OF | 978 | Community hierarchy (level N → N-1) |
| INTERACTS_WITH | 1,297 | Inter-community edges (avg strength: 69.7) |
| READS_CONFIG | 1 | Config file reads |
| **Total** | **589,396** | 23 relationship types |

---

## Ingestion Pipeline

Seven scripts handle data ingestion into Neo4j and ChromaDB. No master orchestrator exists — each must be run manually.

| Script | Target | Status | Output |
|--------|--------|--------|--------|
| `ingest_fortran_graph.py` | Neo4j | Run | 17,575 nodes, 360K relationships |
| `ingest_code_v8.py` | Neo4j + ChromaDB | Run | 58,761 docs, 8K+ nodes |
| `ingest_env_variables.py` | Neo4j | Run | 2,730 env vars |
| `ingest_jjobs_v8.py` | ChromaDB | Run | 700 J-Job documents |
| `ingest_documentation_v8.py` | ChromaDB | Run | 3,514 documentation docs |
| `ingest_shell_graph_v8.py` | Neo4j | Run (Phase 27F/J) | 264 ShellScript (deduped), 63 ShellFunction, 9,155 rels |
| `ingest_cross_language_bridges.py` | Neo4j | Run (Phase 24F/27I/27J) | 65 EXECUTES (33 Shell→Fortran, 32 File→Fortran), 243 INVOKES |

---

## Completed Phases

| Phase | Version | Deliverable |
|-------|---------|-------------|
| 4B | v7.3.0 | ISD Approval Gates (3 providers, persistent state) |
| 10 | v7.2.0 | Fortran Call Tree (17,575 nodes, 369K relationships) |
| 11E | v7.1.0 | n8n Workflow Automation (port 5678, MCP Gateway integration) |
| 12 | v7.0.0 | DevOps GitFlow & Containerization (4 environment branches) |
| 23 | v7.3.5 | Smart Container Cleanup (systemd timer, connection-aware) |
| 24A-D | v7.5–7.7 | GGSR Foundation (Graph-Guided Semantic Retrieval) |
| 24E | v7.20.0 | Hierarchical Communities — **COMPLETE** (flat Leiden v7.9.0 + hierarchical materialization v7.20.0: 1,036 Community nodes, 4 levels, 828 summaries) |
| 24F | v7.8.0 | Cross-Language Integration (Shell→Fortran bridges, 33 EXECUTES edges) |
| 24G | v7.10.0 | Benchmark & Validation (60% vs 40% baseline — GO for 24H) |
| 24H | v7.11.0 | Agentic Tool Surface (5 new MCP tools) |
| 25 | v7.12.0 | VNC Cleanup & Deprecation |
| 26 | v7.13.0 | Docker MCP Gateway systemd fix (port 18888) |
| 27A-G | v7.15.0 | J-Job RAG Enhancement (path fix, shell parser, ChromaDB, filters, embeddings, shell graph ingestion, validation) |
| 27I | v7.17.0 | External Fortran EXECUTES bridge resolution (9 placeholder FortranProgram nodes, 65 EXECUTES edges total) |
| 27H | v7.16.0 | Multi-collection search routing (search_documentation → 3 collections: docs + jjobs + ee2) |
| 27J | v7.19.0 | ShellScript node dedup (383→264) + delegate script bridge parsing (19/89 J-Job coverage) |
| 24E-5 | v7.20.0 | Community Node Materialization (1,036 Community nodes, 4 levels, 21,559 MEMBER_OF, 978 PARENT_OF, 1,297 INTERACTS_WITH, 828 summaries) |
| 28 | v7.5.0 | GraphRAG Acceleration (GGSR prototypes, enrichment wiring) |
| 29 | v4.1.0 | Provisioning Modernization (VNC removed, scripts consolidated) |
| 30 | v7.14.0 | SDD Framework Cleanup (18 files deleted, 7 migrated, 11 archived) |
| 31 | v7.14.0 | SDD Execution Model (session-oriented tracking, replaces 4B ISD) |

### Active / Immediate

| Phase | Priority | Goal |
|-------|----------|------|
| *None* | — | GraphRAG core loop closed. Next priority: Phase 4C (USD Sub-Agent Dispatch) or Phase 13 (CI/CD Pipeline) |

### Planned

| Phase | Priority | Goal |
|-------|----------|------|
| 4C | High | USD Sub-Agent Dispatch (autonomous multi-agent workflows) |
| 4D | Medium | Multi-Tenant SDD Workspaces (team/user hierarchy) |
| 13 | Medium | GitLab CI/CD Pipeline (automated build/test/deploy) |
| 22 | Medium | Validation & Benchmarking Subsystem (ground truth, regression) |
| 24I | Low | Learned Graph Embeddings |
| 24J | Low | Subgraph Retrieval |
| 6 | Low | Production Hardening (monitoring, restart, logging) |
| 7 | Low | Documentation & Training (user guides, SME annotation) |
| 8 | Low | Multi-Modal Embeddings (diagrams, flowcharts) |
| 9 | Low | Metrics & Comparative Analysis (productivity measurement) |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Production Stack                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │ MCP Server  │  │  ChromaDB   │  │   Neo4j     │          │
│  │ (Node.js)   │  │  5 collns   │  │ 40K+ nodes  │          │
│  │  43 Tools   │  │ MPNet 768d  │  │ 566K rels  │          │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘          │
│         └────────────────┼────────────────┘                  │
│                          │                                   │
│         ┌────────────────┴────────────────┐                  │
│         │     Hybrid Query Engine         │                  │
│         │  (GGSR: Semantic + Structural)  │                  │
│         └────────────────┬────────────────┘                  │
└──────────────────────────┼──────────────────────────────────┘
                           │
     ┌────────────────────┼────────────────────┐
     │                    │                    │
┌────┴─────┐    ┌─────────┴────────┐    ┌─────┴─────┐
│ VS Code  │    │ Docker Gateway   │    │   n8n     │
│ Copilot  │    │ (port 18888)     │    │ (5678)    │
└──────────┘    └──────────────────┘    └───────────┘
```

### MCP Tool Modules (43 tools)

| Module | Tools | Database |
|--------|-------|----------|
| WorkflowInfoTools | `get_workflow_structure`, `get_system_configs`, `describe_component` | Filesystem |
| CodeAnalysisTools | `analyze_code_structure`, `find_dependencies`, `find_callers_callees`, `find_env_dependencies` | Neo4j |
| SemanticSearchTools | `search_documentation`, `explain_with_context`, `get_knowledge_base_status` | ChromaDB + Neo4j |
| EE2ComplianceTools | `analyze_ee2_compliance`, `scan_repository_compliance`, `search_ee2_standards`, `generate_compliance_report` | ChromaDB |
| OperationalTools | `get_operational_guidance`, `list_job_scripts`, `get_job_details`, `explain_workflow_component` | ChromaDB |
| GraphRAGTools | `get_code_context`, `search_architecture`, `find_similar_code`, `get_change_impact`, `trace_data_flow`, `trace_execution_path` | ChromaDB + Neo4j |
| GitHubTools | `search_issues`, `get_pull_requests`, `analyze_repository_structure` | GitHub API |
| SDDWorkflowTools | `list_sdd_workflows`, `get_sdd_workflow`, `start_sdd_session`, `record_sdd_step`, `get_sdd_session`, `complete_sdd_session` | Filesystem |
| Health/Misc | `mcp_health_check`, `get_server_info`, `code-mode`, + MCP orchestration tools | Various |

### Server Scenarios

| Scenario | Command | Tools | Databases |
|----------|---------|-------|-----------|
| Full | `npm start` | ~43 | ChromaDB + Neo4j |
| Core | `npm run start:core` | ~20 | Neo4j only |
| RAG | `npm run start:rag` | ~38 | ChromaDB + Neo4j |
| GitHub | `npm run start:github` | ~24 | Neo4j + GitHub API |

---

## SDD Framework

**Model**: `start_sdd_session` → `record_sdd_step` (repeat) → `complete_sdd_session`  
**State**: Persists in `sdd_framework/execution_state/`  
**Workflows**: 39 active in `sdd_framework/workflows/`, 11 archived

Phase naming convention: `phase<N><letter>_<descriptor>.md`  
Currently at Phase 31 with sub-phases through the alphabet.

---

## Value Proposition

### Delivered
- 43 MCP tools for code analysis, semantic search, compliance checking
- 41,355 graph nodes with 589,396 relationships (Fortran, Python, Shell, env vars, cross-language, communities)
- 63,837 searchable documents across 5 ChromaDB collections (828 hierarchical community summaries)
- Graph-Guided Semantic Retrieval (60% improvement over vector-only baseline)
- EE2/NCO compliance scanning (demonstrated on seaice-concentration, EVS)
- SDD methodology with session tracking across conversations
- Docker MCP Gateway for external client access

### Known Gaps
- **No ingestion orchestrator** — 7 scripts must be run manually in correct order
- **No CI/CD pipeline** — Builds and tests are manual (Phase 13)
- **Single-user** — No multi-tenant workspace support yet (Phase 4D)
- **J-Job→Fortran coverage** — Only 19/89 J-Jobs (21%) reach Fortran via cross-language bridges

---

## Resource Requirements

| Resource | Current | Status |
|----------|---------|--------|
| Developer time | 1 person (Terrence) | Sufficient for prototype |
| Compute (ParallelWorks) | Available | Sufficient |
| Docker registry | GitLab Registry | Configured |
| GitHub Enterprise | NOAA-EMC | Available |
| Git submodules | 16 registered | Complete |

---

*"If it's not in the SDD, it doesn't get coded."*
