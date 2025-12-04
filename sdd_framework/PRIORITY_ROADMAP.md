# MCP/RAG System - Priority Roadmap

**Document Purpose**: Executive summary and prioritized delivery roadmap  
**Last Updated**: December 4, 2025  
**Lead**: Terrence McGuinness  
**Status**: Active Development

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
| Semantic documentation search | ✅ Operational | ChromaDB with 3,761 documents |
| Code structure analysis | ✅ Operational | Neo4j graph database |
| EE2 compliance scanning | ✅ Demonstrated | seaice-concentration audit (14 scripts, 72% score) |
| SME-guided AI corrections | ✅ Implemented | 29 semantic annotations preventing false positives |
| MCP tool integration | ✅ Working | 20+ tools accessible via VS Code Copilot |

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
