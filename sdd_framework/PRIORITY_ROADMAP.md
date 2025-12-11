# MCP/RAG System - Priority Roadmap

**Document Purpose**: Executive summary and prioritized delivery roadmap  
**Last Updated**: December 11, 2025  
**Lead**: Terrence McGuinness  
**Status**: Active Development - Phase 12 Complete

---

## 🟢 Current System Status (December 2025)

| Component | Status | Metrics |
|-----------|--------|---------|
| **MCP Server** | ✅ Operational | v3.0.0, 16 tools registered |
| **ChromaDB** | ✅ Healthy | 12 collections, 14,854 documents |
| **Neo4j** | ✅ Healthy | 2,730 files, 1,481 functions, 85,894 relationships |
| **GitLab Registry** | ✅ Ready | `chromadb:v134clean` image pushed |
| **GitFlow Branches** | ✅ Created | develop, env/dev-ops, env/staging, env/production |
| **Environment Isolation** | ✅ Implemented | MCP_ENV config for all environments |

---

## ✅ Phase 12: DevOps GitFlow & Containerization (COMPLETE)

**Status**: COMPLETE (December 11, 2025)  
**SDD**: `phase12_devops_gitflow_containerization.md`

**Accomplishments**:
- [x] Root cause analysis: ChromaDB version mismatch (1.3.4 vs 1.3.7.dev9)
- [x] Custom `chromadb:v134clean` image built and pushed to GitLab Registry
- [x] GitFlow branches created (develop, env/dev-ops, env/staging, env/production)
- [x] Environment-aware configuration (Python + Node.js)
- [x] Docker-compose files for devops, staging, production
- [x] MCP_ENV isolation strategy documented

**Key Finding**: BuildKit attestations caused "Invalid tag: missing manifest digest" in GitLab.  
**Solution**: Build with `--provenance=false --sbom=false` flags.

---

## ⚠️ Bootstrap Capability (Phase 4) - ON HOLD

**Status**: Infrastructure complete, execution **PAUSED**  
**Reason**: Unsupervised code modification requires additional safeguards  
**Resume After**: Phase 4B completion (interactive supervised execution)

The SDD Framework includes autonomous self-modification capabilities (`SelfModificationEngine.js`, `WorkflowExecutor.js`, `bootstrap_capability_demo.md`), but these are **intentionally disabled** for unsupervised runs until:

1. ✅ Containerization complete (shareable, reproducible environment)
2. ⏳ Production hardening (reliable rollback, monitoring)
3. ⏳ Human-in-the-loop gates tested in production
4. ⏳ SME review of generated code patterns

**Current Safe Usage**: Interactive, supervised execution with `dry_run: true` preview.

---

## 🟠 Phase 4B: Interactive Supervised Execution

**Status**: SDD Complete (`phase4b_interactive_supervised_execution.md`)  
**Priority**: HIGH - Enables safe workflow execution before full autonomy  
**Goal**: Human-in-the-loop approval gates for side-effect steps

**Key Features**:
- **Multi-CLI Support**: Works in VS Code MCP, Claude Code, terminal, GitHub Actions
- **Approval Providers**: MCPApprovalProvider, CLIApprovalProvider, ManifestApprovalProvider
- **Execution Modes**: dry_run → supervised → auto_approved → autonomous (graduated trust)
- **Multi-Turn MCP**: Pause, return pending state, resume on user approval

**Deliverables**:
- [ ] ApprovalProvider interface and implementations
- [ ] WorkflowExecutor integration with approval gates
- [ ] `execute_sdd_workflow_supervised` MCP tool
- [ ] CLI wrapper for terminal/Claude Code
- [ ] Approval manifest format for batch/CI

**Estimated Effort**: ~20 hours  
**Unlocks**: Safe supervised execution without full autonomy risk

---

## Vision

An AI-assisted development platform for NOAA operational weather systems that:
- **Accelerates development** - Semantic search across 30+ years of code/docs
- **Ensures compliance** - Automated EE2/NCO standards validation
- **Reduces onboarding** - New developers productive in days, not months
- **Prevents errors** - AI catches issues before production deployment

---

## Current Capabilities (Demonstrated)

| Capability | Status | Evidence |
|------------|--------|----------|
| Semantic documentation search | ✅ Operational | ChromaDB with 14,854 documents (12 collections) |
| Code structure analysis | ✅ Operational | Neo4j graph database (85,894 relationships) |
| EE2 compliance scanning | ✅ Demonstrated | seaice-concentration, EVS audits complete |
| SME-guided AI corrections | ✅ Implemented | 56 MCP directives preventing false positives |
| MCP tool integration | ✅ Working | 16 tools accessible via VS Code Copilot |
| SDD Workflow Framework | ✅ Operational | 24 workflows defined, supervised execution |
| Container Registry | ✅ Ready | GitLab Registry with custom chromadb image |
| GitFlow DevOps | ✅ Complete | 4 environment branches configured |
| Bootstrap Capability | 🔒 ON HOLD | Infrastructure ready, awaiting Phase 4B |

---

## Priority Phases

### ✅ Phase 12: DevOps GitFlow & Containerization (COMPLETE)
**Goal**: Establish complete DevOps pipeline  
**Status**: COMPLETE - December 11, 2025  
**Deliverables**:
- [x] Custom ChromaDB 1.3.4 Docker image
- [x] GitLab Container Registry integration
- [x] GitFlow branches (develop, env/*)
- [x] Environment-aware configuration (MCP_ENV)
- [x] Docker-compose for all environments

---

### 🔴 Phase 13: GitLab CI/CD Pipeline (NEXT)
**Goal**: Automated build, test, and deploy pipeline  
**Why Next**: Automates what we built in Phase 12  
**Deliverables**:
- [ ] .gitlab-ci.yml with lint/test/build/deploy stages
- [ ] GitLab Runner on Parallel Works
- [ ] Automated container builds on env/* branches
- [ ] Security scanning (Trivy)
- [ ] Health check verification post-deploy

**Timeline**: 1-2 weeks  
**Blocks**: Automated deployments

---

### 🟡 Phase 6: Production Hardening
**Goal**: Make system reliable for daily use  
**Deliverables**:
- [ ] Health monitoring dashboard
- [ ] Automatic restart on failure
- [ ] Log aggregation and search
- [ ] Backup/restore procedures

**Timeline**: 1 week after Phase 13

---

### 🟡 Phase 7: Documentation & Training
**Goal**: Enable self-service adoption  
**Deliverables**:
- [ ] User guide for developers
- [ ] Model selection guide (which AI for which task)
- [ ] SME annotation guide (how to correct AI behavior)
- [ ] Video walkthroughs (optional)

**Timeline**: Parallel with Phase 6

---

### 🟢 Phase 8: Multi-Modal Embeddings
**Goal**: Ingest diagrams, flowcharts, architecture images  
**Status**: SDD exists  
**Timeline**: After Phase 7

---

### 🟢 Phase 9: Metrics & Comparative Analysis
**Goal**: Quantify productivity improvements  
**Status**: SDD exists  
**Timeline**: After production deployment (need usage data)

---

### ⚪ Phase 10: Fortran Call Tree Ingestion
**Goal**: Trace execution from shell scripts into compiled code  
**Status**: SDD complete, BACKLOG  
**Timeline**: Future - high value but not critical for initial rollout

---

### ⚪ Phase 11: Docker MCP Gateway & LangFlow
**Goal**: Multi-client MCP access via gateway  
**Status**: SDD exists  
**Timeline**: After Phase 13

---

## Technical Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Production Stack                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │ MCP Server  │  │  ChromaDB   │  │   Neo4j     │          │
│  │ (Node.js)   │  │ v134clean   │  │   5.15.0    │          │
│  │  16 Tools   │  │ 14,854 docs │  │ 85K+ rels   │          │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘          │
│         └────────────────┼────────────────┘                  │
│                          │                                   │
│         ┌────────────────┴────────────────┐                  │
│         │     Hybrid Query Engine         │                  │
│         │  (Semantic + Structural)        │                  │
│         └────────────────┬────────────────┘                  │
└──────────────────────────┼──────────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              │   VS Code + Copilot     │
              │   (Developer Interface) │
              └─────────────────────────┘
```

### Environment Isolation

```
┌─────────────────────────────────────────────────────────────┐
│  MCP_ENV=development (feature/*, develop)                   │
│  → PersistentClient (direct SQLite)                         │
│  → Local experimentation, can break things                  │
├─────────────────────────────────────────────────────────────┤
│  MCP_ENV=devops (env/dev-ops)                               │
│  → HttpClient → Docker containers                           │
│  → CI/CD validates container compatibility                  │
├─────────────────────────────────────────────────────────────┤
│  MCP_ENV=staging (env/staging)                              │
│  → HttpClient → Staging containers                          │
│  → Read-only validation, pre-production                     │
├─────────────────────────────────────────────────────────────┤
│  MCP_ENV=production (env/production)                        │
│  → CI/CD pipeline only, no manual access                    │
│  → Audit logged, authentication required                    │
└─────────────────────────────────────────────────────────────┘
```

---

## Value Proposition for Leadership

### Immediate Benefits (Delivered)
- **Demo-ready**: Show executives AI-powered code compliance in action
- **Shareable**: Container images in GitLab Registry
- **Evidence-based**: Actual seaice-concentration, EVS audits show real findings
- **DevOps Foundation**: GitFlow and environment isolation established

### Near-Term Benefits (Phases 6-7)
- **Self-service**: Teams adopt without hand-holding
- **Measurable**: Track adoption and productivity metrics
- **Scalable**: Add more repositories to knowledge base

### Long-Term Benefits (Phases 8-10)
- **Deep tracing**: Understand Fortran call chains from shell scripts
- **Multi-modal**: Query architecture diagrams, not just text
- **Institutional knowledge**: Capture SME expertise in machine-readable form

---

## Resource Requirements

| Resource | Current | Status |
|----------|---------|--------|
| Developer time | 1 person (Terrence) | ✅ Sufficient for prototype |
| Compute (ParallelWorks) | Available | ✅ Sufficient |
| Docker registry | GitLab Registry | ✅ Configured |
| GitHub Enterprise | NOAA-EMC | ✅ Available |
| GitLab CI/CD Runners | Needed | ⏳ Phase 13 |

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Leadership doesn't see value | Demo with real code (seaice, EVS), show actual findings |
| Developers resist AI tools | Start with search/docs, not code generation |
| Security concerns | Container runs locally, no cloud dependency |
| Hallucination/false positives | SME annotations correct AI behavior |
| Version drift | Pinned container versions, environment isolation |

---

## Next Actions

1. **Immediate**: Set up GitLab Runners for CI/CD (Phase 13)
2. **This Week**: Test container deployments with docker-compose files
3. **Next Week**: First automated pipeline runs
4. **Ongoing**: Document runbooks, gather user feedback

---

## SDD Workflow Inventory (24 Workflows)

| Workflow | Status | Purpose |
|----------|--------|---------|
| phase12_devops_gitflow_containerization | ✅ Complete | GitFlow + containers |
| phase4b_interactive_supervised_execution | 📋 SDD Ready | Approval gates |
| phase10_fortran_call_tree_ingestion | 📋 SDD Ready | Fortran analysis |
| phase11_docker_mcp_gateway_langflow | 📋 SDD Ready | Multi-client gateway |
| phase8_multimodal_embeddings_workflow | 📋 SDD Ready | Image/diagram ingestion |
| phase9_metrics_comparative_analysis | 📋 SDD Ready | Productivity metrics |
| ee2_enhanced_embeddings_workflow | ✅ Complete | EE2 standards ingestion |
| v7_collection_upgrade_workflow | ✅ Complete | v7 collection migration |
| *...and 16 more* | Various | See sdd_framework/workflows/ |

---

*"The best way to predict the future is to prototype it."*
