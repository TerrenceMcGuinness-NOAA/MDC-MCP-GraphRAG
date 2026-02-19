# MCP/RAG System — Current Roadmap

**Document Purpose**: Executive summary and prioritized delivery roadmap  
**Last Updated**: February 19, 2026  
**Lead**: Terrence McGuinness  
**Status**: Active Development — v7.14.1, 43 tools, Phase 31 SDD Model

---

## Current System Status

| Component | Status | Metrics |
|-----------|--------|---------|
| **MCP Server** | Operational | v7.14.1, 43 tools across 9 modules |
| **ChromaDB** | Healthy | 5 collections, 63,072 documents, MPNet 768-dim |
| **Neo4j** | Healthy | 40,207 nodes, 567,663 relationships, 24 label types |
| **Fortran Graph** | Complete (Phase 10) | 17,575 nodes, 268K CALLS, 91K USES |
| **Shell Graph** | **NOT INGESTED** | `ingest_shell_graph_v8.py` exists but never run |
| **Docker Gateway** | Operational | Port 18888, Streamable HTTP, systemd service |
| **SDD Framework** | v6.0 / Phase 31 | 39 active workflows, 11 archived |
| **Git Submodules** | Complete | 16 repos registered under `supported_repos/` |

### ChromaDB Collections

| Collection | Documents | Content |
|------------|-----------|---------|
| `code-with-context-v8-0-0` | 58,761 | Python, Fortran, Shell source code |
| `global-workflow-docs-v8-0-0` | 3,514 | Documentation, READMEs |
| `jjobs-v8-0-0` | 700 | J-Job scripts with structured metadata |
| `community-summaries` | 63 | Leiden community summary embeddings |
| `ee2-standards-v5-0-0-enhanced` | 34 | EE2/NCO compliance standards |
| **Total** | **63,072** | |

### Neo4j Node Inventory

| Label | Count | Source |
|-------|-------|--------|
| FortranSubroutine | 13,537 | `ingest_fortran_graph.py` |
| CodeFunction | 5,059 | `ingest_code_v8.py` |
| PythonFunction | 3,267 | `ingest_code_v8.py` |
| EnvironmentVariable | 2,730 | `ingest_env_variables.py` |
| FortranModule | 1,762 | `ingest_fortran_graph.py` |
| Community | 3,847 | Leiden community detection (Phase 24E) |
| **ShellScript** | **0** | **`ingest_shell_graph_v8.py` — NEVER RUN** |
| *24 label types total* | **40,207** | |

### Neo4j Relationship Summary

| Type | Count | Notes |
|------|-------|-------|
| CALLS | 439,919 | Fortran subroutine calls dominate |
| USES | 91,285 | Module USE statements |
| DEFINES | 9,690 | Symbol definitions |
| IMPORTS | 8,034 | Python imports |
| DEPENDS_ON_ENV | 6,007 | Environment variable references |
| EXPORTS | 1,669 | Exported symbols |
| SETS | 1,401 | Variable assignments |
| SOURCES | 148 | Shell source statements |
| INVOKES | 4 | Cross-language invocations |
| EXECUTES | 3 | Shell→Fortran execution bridges |
| **Total** | **567,663** | |

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
| **`ingest_shell_graph_v8.py`** | **Neo4j** | **NEVER RUN** | **0 nodes — password default wrong** |
| `ingest_cross_language_bridges.py` | Neo4j | Run (low yield) | 7 edges (3 EXECUTES, 4 INVOKES) |

### Critical Gap: Shell Script Graph

`ingest_shell_graph_v8.py` creates `:ShellScript`, `:ShellFunction`, `:ConfigFile` nodes and `SOURCES`, `INVOKES`, `READS_CONFIG`, `EXPORTS`, `DEFINES` relationships. It was **never executed** because:

1. **Neo4j password mismatch**: Script defaults to `"password"` but the database uses `"gfsworkflow2025"` (SPOT violation — should read from `mcp-env.sh`)
2. **No dry-run flag**: Unlike `ingest_jjobs_v8.py` and `ingest_env_variables.py`, there's no safe preview mode
3. **Destructive default**: `clear_shell_graph()` runs unconditionally on startup

**Impact**: Without shell script nodes, `ingest_cross_language_bridges.py` found only 7 edges. Re-running bridges after shell ingestion should yield 50+ cross-language links.

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
| 24E | v7.9.0 | Hierarchical Community Summaries (Leiden + GDS, 3,847 communities) |
| 24F | v7.8.0 | Cross-Language Integration (Shell→Fortran bridges) |
| 24G | v7.10.0 | Benchmark & Validation (60% vs 40% baseline — GO for 24H) |
| 24H | v7.11.0 | Agentic Tool Surface (5 new MCP tools) |
| 25 | v7.12.0 | VNC Cleanup & Deprecation |
| 26 | v7.13.0 | Docker MCP Gateway systemd fix (port 18888) |
| 27A-E | v7.13.x | J-Job RAG Enhancement (path fix, shell parser, ChromaDB, filters, embeddings) |
| 28 | v7.5.0 | GraphRAG Acceleration (GGSR prototypes, enrichment wiring) |
| 29 | v4.1.0 | Provisioning Modernization (VNC removed, scripts consolidated) |
| 30 | v7.14.0 | SDD Framework Cleanup (18 files deleted, 7 migrated, 11 archived) |
| 31 | v7.14.0 | SDD Execution Model (session-oriented tracking, replaces 4B ISD) |

### Active / Immediate

| Phase | Status | Goal |
|-------|--------|------|
| **27F** | NOT STARTED | Run ingestion pipeline: shell graph → bridges → validate |
| **27G** | NOT STARTED | End-to-end validation of all 27A-F deliverables |

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
│  │ (Node.js)   │  │  5 collns   │  │ 40K nodes   │          │
│  │  43 Tools   │  │ MPNet 768d  │  │ 568K rels   │          │
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
- 40,207 graph nodes with 567,663 relationships (Fortran, Python, env vars)
- 63,072 searchable documents across 5 ChromaDB collections
- Graph-Guided Semantic Retrieval (60% improvement over vector-only baseline)
- EE2/NCO compliance scanning (demonstrated on seaice-concentration, EVS)
- SDD methodology with session tracking across conversations
- Docker MCP Gateway for external client access

### Known Gaps
- **Shell script graph empty** — `ingest_shell_graph_v8.py` never executed (Phase 27F)
- **Cross-language bridges sparse** — Only 7 edges; needs shell graph for full yield
- **No ingestion orchestrator** — 7 scripts must be run manually in correct order
- **No CI/CD pipeline** — Builds and tests are manual (Phase 13)
- **Single-user** — No multi-tenant workspace support yet (Phase 4D)

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
