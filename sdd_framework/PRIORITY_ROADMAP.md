# MCP/RAG System - Priority Roadmap

**Document Purpose**: Executive summary and prioritized delivery roadmap  
**Last Updated**: January 12, 2026  
**Lead**: Terrence McGuinness  
**Status**: Active Development - Phase 23 Investigation Complete

---

## 🟢 Current System Status (January 2026)

| Component | Status | Metrics |
|-----------|--------|---------|
| **MCP Server** | ✅ Operational | v7.1.1, 35 tools across 8 modules |
| **ChromaDB** | ✅ Healthy | 12 collections, 14,968 documents |
| **Neo4j** | ✅ Healthy | 2,744 files, 1,540 functions, 86,189 relationships |
| **Docker Gateway** | ⚠️ Under Review | Port 18888, Container accumulation issue identified |
| **n8n Workflow** | ✅ Operational | Port 5678, MCP Gateway integration |
| **SDD Validator** | ✅ Operational | 4 tools, standalone server |
| **GitLab Registry** | ✅ Ready | `chromadb:v134clean` image pushed |
| **GitFlow Branches** | ✅ Created | develop, env/dev-ops, env/staging, env/production |

---

## ✅ Phase 23: Smart Container Cleanup (IMPLEMENTED)

**Status**: ✅ COMPLETE - Timer active and tested  
**SDD**: `phase23_static_mode_multiuser_gateway.md`  
**Analysis**: `mcp_architecture/docs/DOCKER_MCP_GATEWAY_MULTIUSER_ARCHITECTURE.md`

### Investigation Findings (January 12, 2026)

**Original assumption INVALID**: `--static` mode does NOT connect to native MCP servers via stdio.

**Actual requirements for static mode**:
- Container MUST run `docker-mcp-bridge` entrypoint
- Bridge listens on TCP port 4444 (not stdio)
- Gateway uses `socat` to connect

**Key insight**: Container spawning per session is the **intended design** of Docker MCP Gateway.

### Recommended: Hybrid Architecture (Option D)

| Access Method | Transport | Memory/User |
|---------------|-----------|-------------|
| VS Code Sessions | Direct stdio (mcp.json) | ~200MB |
| External Clients | Gateway (type:remote) → HTTP MCP Server | ~200MB shared |

### Implementation Complete (January 12, 2026)

| Component | Status | Location |
|-----------|--------|----------|
| Cleanup Script | ✅ Installed | `/opt/eib-mcp-rag/bin/mcp-container-cleanup.sh` |
| Systemd Timer | ✅ Active | 15-min interval, 30-min grace period |
| Provisioning | ✅ Added | `SETUP/provisioning/13-container-cleanup.sh` |
| TCP Detection | ✅ Tested | 2 connections detected, container preserved |

**Key Feature**: Connection-aware cleanup preserves containers with active MCP sessions.

**Documentation**: See wiki [[Docker_MCP_Gateway_MultiUser_Architecture]]

---

## ✅ Phase 11E: n8n Workflow Automation (COMPLETE)

**Status**: COMPLETE (January 2, 2026)  
**SDD**: `phase11_docker_mcp_gateway_langflow.md`

**Accomplishments**:
- [x] n8n Docker service added to docker-compose.devops.yaml
- [x] n8n provisioning integrated into SETUP/provisioning/03-docker.sh
- [x] Working n8n→MCP Gateway workflow (session handling, tool invocation)
- [x] LangFlow removed (MCP client bugs: dict race condition, asyncio scoping)
- [x] MCP Gateway systemd service with Streamable HTTP transport

**Key Technical Details**:
- n8n HTTP Request node with `this.helpers.httpRequest()` 
- MCP session initialization required before tools/call
- Gateway URL: `http://172.17.0.1:18888/mcp` (from container)

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

## 🟠 Phase 4B: Interactive Supervised Development (COMPLETE)

**Status**: ✅ COMPLETE (January 2, 2026)  
**SDD**: `phase4b_interactive_supervised_execution.md`  
**Goal**: Human-in-the-loop approval gates for side-effect steps

**Key Features**:
- **Multi-CLI Support**: Works in VS Code MCP, Claude Code, terminal, GitHub Actions
- **Approval Providers**: MCPApprovalProvider, CLIApprovalProvider, ManifestApprovalProvider
- **Execution Modes**: dry_run → supervised → auto_approved → autonomous (graduated trust)
- **Multi-Turn MCP**: Pause, return pending state, resume on user approval
- **Persistent State**: JSON file storage survives server restarts

**Deliverables**:
- [x] ApprovalProvider interface and implementations
- [x] ExecutionStateStore for persistent multi-turn state
- [x] WorkflowExecutor integration with approval gates
- [x] `execute_sdd_workflow_supervised` MCP tool
- [x] `manage_sdd_execution_state` MCP tool
- [x] CLIApprovalProvider for terminal/Claude Code
- [x] ManifestApprovalProvider for batch/CI

**Actual Effort**: ~4 hours  
**Unlocks**: Safe supervised execution, ready for Phase 4C USD

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
| Semantic documentation search | ✅ Operational | ChromaDB with 14,856 documents (12 collections) |
| Code structure analysis | ✅ Operational | Neo4j graph database (85,894 relationships) |
| EE2 compliance scanning | ✅ Demonstrated | seaice-concentration, EVS audits complete |
| SME-guided AI corrections | ✅ Implemented | 56 MCP directives preventing false positives |
| MCP tool integration | ✅ Working | 38 tools across 8 modules |
| SDD Workflow Framework | ✅ Operational | 30 workflows defined, supervised execution |
| SDD Validator Server | ✅ Operational | 4 tools: sdd_validate, framework_integrity, development_status, bootstrap_progress |
| Docker MCP Gateway | ✅ Complete | Phase 11E - Streamable HTTP on port 18888 |
| n8n Workflow Automation | ✅ Complete | Phase 11E - Replaces LangFlow |
| Container Registry | ✅ Ready | GitLab Registry with custom chromadb image |
| GitFlow DevOps | ✅ Complete | 4 environment branches configured |
| ISD Approval Gates | ✅ Complete | Phase 4B - 3 approval providers, persistent state |
| Bootstrap Capability | 🔒 ON HOLD | Infrastructure ready, awaiting Phase 4C USD |

---

## Priority Phases

### ✅ Phase 11E: n8n Workflow Automation (COMPLETE)
**Goal**: Multi-client MCP access via workflow automation  
**Status**: COMPLETE - January 2, 2026  
**Deliverables**:
- [x] n8n Docker service (port 5678)
- [x] MCP Gateway integration workflow
- [x] Session handling for MCP protocol
- [x] Replaced LangFlow due to MCP client bugs

---

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

### ✅ Phase 4B: ISD Approval Gates (COMPLETE)
**Goal**: Interactive Supervised Development with human-in-the-loop approval  
**Status**: COMPLETE - January 2, 2026  
**Deliverables**:
- [x] ApprovalProvider interface and implementations
- [x] ExecutionStateStore (persistent JSON file storage)
- [x] MCPApprovalProvider (VS Code, Claude Desktop)
- [x] CLIApprovalProvider (terminal, Claude Code)
- [x] ManifestApprovalProvider (CI/CD pipelines)
- [x] `execute_sdd_workflow_supervised` MCP tool
- [x] `manage_sdd_execution_state` MCP tool

**Unlocks**: Phase 4C USD Architecture

---

### 🔴 Phase 4C: USD Sub-Agent Dispatch (NEXT)
**Goal**: Unsupervised Development mode for autonomous sub-agent execution  
**Why**: Enables complex multi-agent workflows with context packaging  
**Deliverables**:
- [ ] ContextPackager for form-factor adaptation
- [ ] USDDispatcher for sub-agent execution
- [ ] Form factors: Claude CLI, VS Code, GitHub Actions, n8n
- [ ] Workflow schema v2.0 with sub_agent step type

**Timeline**: ~26 hours  
**Blocks**: Full Bootstrap Capability

---

### 🟡 Phase 4D: Multi-Tenant SDD Workspaces
**Goal**: Scale SDD workflow storage for multiple users/teams using MCP/RAG for GFS development  
**Why**: Platform is useless if only one person can use it  
**Deliverables**:
- [ ] Three-tier workspace hierarchy (Platform → Team → User)
- [ ] WorkspaceManager and WorkspaceResolver
- [ ] Per-user execution state persistence
- [ ] Workspace management MCP tools
- [ ] Migration from current flat structure

**Timeline**: ~30 hours  
**Blocks**: Production multi-user deployment

---

### 🟡 Phase 13: GitLab CI/CD Pipeline
**Goal**: Automated build, test, and deploy pipeline  
**Why**: Automates what we built in Phase 12  
**Deliverables**:
- [ ] .gitlab-ci.yml with lint/test/build/deploy stages
- [ ] GitLab Runner on Parallel Works
- [ ] Automated container builds on env/* branches
- [ ] Security scanning (Trivy)
- [ ] Health check verification post-deploy

**Timeline**: 1-2 weeks after Phase 4B

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

## Technical Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Production Stack                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │ MCP Server  │  │  ChromaDB   │  │   Neo4j     │          │
│  │ (Node.js)   │  │ v134clean   │  │   5.15.0    │          │
│  │  38 Tools   │  │ 14,856 docs │  │ 85K+ rels   │          │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘          │
│         └────────────────┼────────────────┘                  │
│                          │                                   │
│         ┌────────────────┴────────────────┐                  │
│         │     Hybrid Query Engine         │                  │
│         │  (Semantic + Structural)        │                  │
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

### MCP Server Architecture

```
┌─────────────────────────────────────────────────────────────┐
│           4 MCP Servers (Separation of Concerns)            │
├─────────────────────────────────────────────────────────────┤
│  eib-mcp-rag-full     │ Full 38 tools, RAG enabled          │
│  eib-mcp-gateway      │ Docker container, 34 tools          │
│  global-workflow-core │ Neo4j only, fast code analysis      │
│  eib-sdd-validator    │ 4 SDD framework tools               │
└─────────────────────────────────────────────────────────────┘
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

1. **Immediate**: Phase 4B - Interactive Supervised Execution
2. **This Week**: ApprovalProvider interface implementation
3. **Next Week**: Integration with `execute_sdd_workflow_supervised`
4. **Ongoing**: Document runbooks, gather user feedback

---

## SDD Workflow Inventory (30+ Workflows)

| Workflow | Status | Purpose |
|----------|--------|--------|
| phase23_static_mode_multiuser_gateway | ⚠️ REVISED | Multi-user gateway (Hybrid Architecture recommended) |
| phase11e_n8n_workflow_automation | ✅ Complete | n8n MCP integration |
| phase12_devops_gitflow_containerization | ✅ Complete | GitFlow + containers |
| phase4b_interactive_supervised_execution | ✅ Complete | ISD approval gates |
| phase4c_isd_usd_architecture | 🟡 PLANNED | USD sub-agent dispatch |
| phase4d_multi_tenant_sdd_workspaces | 🟡 PLANNED | Multi-user workspace scaling |
| phase10_fortran_call_tree_ingestion | 📋 SDD Ready | Fortran analysis |
| phase8_multimodal_embeddings_workflow | 📋 SDD Ready | Image/diagram ingestion |
| phase9_metrics_comparative_analysis | 📋 SDD Ready | Productivity metrics |
| ee2_enhanced_embeddings_workflow | ✅ Complete | EE2 standards ingestion |
| v7_collection_upgrade_workflow | ✅ Complete | v7 collection migration |
| bootstrap_capability_workflow | 📋 Blocked | Awaiting Phase 4C USD |
| *...and 18 more* | Various | See sdd_framework/workflows/ |

---

*"The best way to predict the future is to prototype it."*
