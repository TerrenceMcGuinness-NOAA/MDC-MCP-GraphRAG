# MCP/RAG System - Priority Roadmap

**Document Purpose**: Executive summary and prioritized delivery roadmap  
**Last Updated**: December 5, 2025  
**Lead**: Terrence McGuinness  
**Status**: Active Development

---

## ⚠️ Bootstrap Capability (Phase 4) - ON HOLD

**Status**: Infrastructure complete, execution **PAUSED**  
**Reason**: Unsupervised code modification requires additional safeguards  
**Resume After**: Phase 4B completion (interactive supervised execution)

The SDD Framework includes autonomous self-modification capabilities (`SelfModificationEngine.js`, `WorkflowExecutor.js`, `bootstrap_capability_demo.md`), but these are **intentionally disabled** for unsupervised runs until:

1. ✅ Containerization complete (shareable, reproducible environment)
2. ✅ Production hardening (reliable rollback, monitoring)
3. ✅ Human-in-the-loop gates tested in production
4. ✅ SME review of generated code patterns

**Current Safe Usage**: Interactive, supervised execution with `dry_run: true` preview.

---

## 🟠 Phase 4B: Interactive Supervised Execution (NEW)

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
| Semantic documentation search | ✅ Operational | ChromaDB with 13,423 documents (11 collections) |
| Code structure analysis | ✅ Operational | Neo4j graph database (82,338 relationships) |
| EE2 compliance scanning | ✅ Demonstrated | seaice-concentration audit (14 scripts, 72% score) |
| SME-guided AI corrections | ✅ Implemented | 56 MCP directives preventing false positives |
| MCP tool integration | ✅ Working | 30+ tools accessible via VS Code Copilot |
| SDD Workflow Framework | ✅ Operational | 17 workflows defined, supervised execution |
| Bootstrap Capability | 🔒 ON HOLD | Infrastructure ready, awaiting Phase 5-6 |

---

## Priority Phases

### 🔴 Phase 5: Containerization & Deployment (CRITICAL PATH)
**Goal**: Package system for distribution to stakeholders  
**Why First**: Leadership needs hands-on demonstration; can't share dev environment  
**Deliverables**:
- [ ] Docker container with MCP server + ChromaDB + Neo4j
- [ ] docker-compose.yml for one-command startup
- [ ] README with 5-minute quickstart
- [ ] Pre-loaded knowledge base (no ingestion required for demo)

**Timeline**: 1-2 weeks  
**Blocks**: All stakeholder demos

---

### 🟡 Phase 6: Production Hardening
**Goal**: Make system reliable for daily use  
**Deliverables**:
- [ ] Health monitoring dashboard
- [ ] Automatic restart on failure
- [ ] Log aggregation and search
- [ ] Backup/restore procedures

**Timeline**: 1 week after Phase 5

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
│                    Docker Container                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │ MCP Server  │  │  ChromaDB   │  │   Neo4j     │          │
│  │ (Node.js)   │  │  (Vectors)  │  │  (Graph)    │          │
│  │  20+ Tools  │  │ 3,761 docs  │  │ Code rels   │          │
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

---

## Value Proposition for Leadership

### Immediate Benefits (Phase 5 delivery)
- **Demo-ready**: Show executives AI-powered code compliance in action
- **Shareable**: Any developer with Docker can run it
- **Evidence-based**: Actual seaice-concentration audit shows 8 critical, 12 major issues

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

| Resource | Current | Needed |
|----------|---------|--------|
| Developer time | 1 person (Terrence) | Same for prototype |
| Compute (ParallelWorks) | ✅ Available | Sufficient |
| Docker registry | ❓ Need access | For sharing containers |
| GitHub Enterprise | ✅ NOAA-EMC | For code repos |

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Leadership doesn't see value | Demo with real code (seaice), show actual findings |
| Developers resist AI tools | Start with search/docs, not code generation |
| Security concerns | Container runs locally, no cloud dependency |
| Hallucination/false positives | SME annotations correct AI behavior |

---

## Next Actions

1. **This Week**: Complete Docker containerization (Phase 5 Step 4-5)
2. **Next Week**: Test container on clean machine, iterate
3. **Week 3**: First stakeholder demo
4. **Ongoing**: Gather feedback, prioritize Phase 6-7 based on needs

---

*"The best way to predict the future is to prototype it."*
