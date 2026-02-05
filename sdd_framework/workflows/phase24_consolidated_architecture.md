# SDD: Phase 24 - True GraphRAG Fusion (Consolidated Architecture)

**Version:** 2.0.0  
**Created:** 2026-02-05  
**Author:** Terry McGuinness + AI Assistants  
**Status:** Consolidated Prospectus  
**Supersedes:** Initial Phase 24 fragments

---

## 1. Document Reconciliation

This document consolidates three Phase 24 sub-specifications into a coherent architecture:

| Document | Focus | Status | Integration |
|----------|-------|--------|-------------|
| [phase24_graph_guided_speculative_retrieval.md](phase24_graph_guided_speculative_retrieval.md) | Local queries via GGSR | Foundation | → 24A-D |
| [Phase24E_HierarchicalCommunit.md](Phase24E%20_HierarchicalCommunit.md) | Global queries via communities | Supplement | → 24E |
| [phase24h_supplement_graphRAG.md](phase24h_supplement_graphRAG.md) | Agentic tool surface | Supplement | → 24H |

### Identified Gaps (Addressed Below)

| Gap | Resolution |
|-----|------------|
| Missing 24F, 24G sub-phases | Added: 24F (Cross-Language), 24G (Benchmarking) |
| Outdated Neo4j statistics | Updated: 86K → **368K relationships** (Phase 10 Fortran) |
| Timeline conflicts (24E/24H both Q3) | Sequenced: 24E weeks 9-16, 24H weeks 17-24 |
| Tool surface overlap (24D vs 24H) | Clarified: 24D = retrieval layer, 24H = agent-facing tools |
| Fortran integration not addressed | New 24F leverages Phase 10 Shell→Fortran graph |

---

## 2. Consolidated Sub-Phase Map

```
Phase 24: True GraphRAG Fusion
│
├── Q2 2026: Foundation (Weeks 1-10)
│   ├── 24A: Traversal Query Prototype      [Weeks 1-2]   → Cypher patterns
│   ├── 24B: Weight Tuning                  [Weeks 3-4]   → Empirical optimization
│   ├── 24C: Token Budget Management        [Weeks 5-6]   → Context window
│   └── 24D: Core Retrieval Integration     [Weeks 7-10]  → GraphGuidedRetrieval class
│
├── Q2-Q3 2026: Extension (Weeks 9-16)
│   ├── 24E: Hierarchical Community Summaries [Weeks 9-16]
│   │   ├── 24E-1: Community Detection (Leiden)
│   │   ├── 24E-2: Summary Generation (LLM)
│   │   ├── 24E-3: Dual Retrieval Router (Local/Global)
│   │   └── 24E-4: Incremental Update Pipeline
│   │
│   └── 24F: Cross-Language Graph Integration [NEW] [Weeks 13-16]
│       ├── 24F-1: Fortran CALLS/USES traversal integration
│       ├── 24F-2: Shell→Fortran EXECUTES path queries
│       └── 24F-3: End-to-end trace: J-Job→Shell→Fortran→Subroutine
│
├── Q3 2026: Agent Surface (Weeks 17-24)
│   ├── 24G: Benchmark & Validation [NEW]   [Weeks 17-18]
│   │   ├── Baseline: Current tool-assisted RAG
│   │   ├── Comparison: GGSR (24D) vs GGSR+Community (24E)
│   │   └── Metrics: Query count, latency, accuracy
│   │
│   └── 24H: Agentic MCP Tool Surface       [Weeks 19-24]
│       ├── 24H-1: Discovery Tools (get_code_context, find_similar)
│       ├── 24H-2: Impact Analysis (get_change_impact, trace_data_flow)
│       ├── 24H-3: Session State (checkpoint, resume)
│       └── 24H-4: Integration & Documentation
│
└── Q4 2026: Advanced (Future)
    ├── 24I: Learned Graph Embeddings (node2vec, GNN)
    └── 24J: Subgraph Retrieval & Reasoning
```

---

## 3. Updated Infrastructure Context

### Neo4j Graph Statistics (Post-Phase 10)

| Metric | Original Spec | Current (Feb 2026) | Growth |
|--------|---------------|-------------------|--------|
| Total Nodes | ~3,000 | **20,496** | 6.8x |
| Total Relationships | 86,189 | **368,978** | 4.3x |
| CALLS (Fortran) | 0 | **268,666** | New |
| USES (Fortran) | 0 | **91,285** | New |
| EXECUTES (Shell→Fortran) | 0 | **35** | New |
| Language Coverage | Shell only | Shell + Fortran | +Fortran |

**Impact on Phase 24:**
- GGSR traversal now spans **cross-language boundaries**
- Community detection will find Fortran subsystems (GSI, UFS, etc.)
- Path queries can trace: `(J-Job)-[:SOURCES]->(shell)-[:EXECUTES]->(Fortran)-[:CALLS*]->(subroutine)`

### ChromaDB Collections

| Collection | Documents | Purpose |
|------------|-----------|---------|
| code-with-context-v8-0-0 | ~50K | Source code chunks |
| jjobs-v8-0-0 | ~500 | J-Job scripts |
| global-workflow-docs-v8-0-0 | ~15K | Documentation |
| ee2-standards-v5-0-0-enhanced | ~2K | EE2 compliance |
| **community-summaries** (24E) | TBD | Hierarchical summaries |

---

## 4. Architecture Integration Points

### 4.1 Layer Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                     AGENT LAYER (24H)                               │
│  get_code_context | get_change_impact | session_state | checkpoint  │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
┌───────────────────────────────┼─────────────────────────────────────┐
│                     ROUTING LAYER (24E-3)                           │
│         ┌─────────────────┬───┴───┬─────────────────┐               │
│         ▼                 ▼       ▼                 ▼               │
│    LOCAL QUERY       GLOBAL QUERY    HYBRID         TRACE           │
│    (24A-D GGSR)      (24E Community) (Local+Global) (24F Cross-Lang)│
└───────────────────────────────┬─────────────────────────────────────┘
                                │
┌───────────────────────────────┼─────────────────────────────────────┐
│                     RETRIEVAL LAYER (24D)                           │
│         GraphGuidedRetrieval class                                  │
│         - Entity extraction                                         │
│         - Graph traversal (weighted)                                │
│         - Token budget management                                   │
│         - ChromaDB fetch                                            │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
        ┌───────────────────────┴───────────────────────┐
        ▼                                               ▼
┌───────────────────────┐               ┌───────────────────────────┐
│      NEO4J            │               │      CHROMADB             │
│  368K relationships   │               │   ~70K documents          │
│  20K nodes            │               │   + community summaries   │
│  Shell+Fortran graph  │               │                           │
└───────────────────────┘               └───────────────────────────┘
```

### 4.2 Query Classification (24E-3 Router)

```javascript
// From 24E: DualRetrievalRouter
async classifyQuery(query) {
  const localSignals = [
    /how does .+ work/i,           // "How does X work?"
    /what is .+/i,                 // "What is X?"
    /show me .+/i,                 // "Show me X"
    /where is .+ defined/i,        // "Where is X defined?"
  ];
  
  const globalSignals = [
    /overall|architecture|pattern/i,   // Holistic
    /strategy|approach|methodology/i,  // Cross-cutting
    /how does .+ work across/i,        // System-wide
    /what are the main/i,              // Summary request
  ];
  
  const traceSignals = [
    /trace|path|flow|calls/i,      // Execution path
    /from .+ to .+/i,              // Source to destination
    /what calls|who calls/i,       // Caller/callee
  ];
  
  // Score each category
  const scores = {
    LOCAL: countMatches(query, localSignals),
    GLOBAL: countMatches(query, globalSignals),
    TRACE: countMatches(query, traceSignals),
  };
  
  // Return highest or HYBRID if tie
  return getMaxCategory(scores);
}
```

### 4.3 Cross-Language Trace (24F)

Leveraging Phase 10 Fortran ingestion:

```cypher
// End-to-end execution trace: J-Job → Shell → Fortran → Subroutine
MATCH path = (job:ShellScript {type: 'j-job'})
  -[:SOURCES|INVOKES*1..3]->(shell:ShellScript)
  -[:EXECUTES]->(program:FortranProgram)
  -[:CALLS*1..5]->(subroutine:FortranSubroutine)
WHERE job.name =~ '(?i).*JGFS_FORECAST.*'
RETURN path
LIMIT 20

// Example result:
// JGFS_FORECAST → exglobal_forecast.sh → EXECUTES → ufs_model → 
// CALLS → atmosphere_init → CALLS → fv_dynamics → CALLS → fv_update_phys
```

---

## 5. Tool Surface Reconciliation

### Original 24D Tools vs 24H Tools

| 24D (Retrieval Layer) | 24H (Agent Layer) | Relationship |
|----------------------|-------------------|--------------|
| `GraphGuidedRetrieval.retrieve()` | `get_code_context()` | 24H wraps 24D |
| (internal traversal) | `trace_data_flow()` | 24H exposes as tool |
| (internal token management) | (transparent to agents) | 24D handles internally |
| - | `get_change_impact()` | New in 24H |
| - | `session_state` tools | New in 24H |

### Consolidated Tool Manifest (24H)

```javascript
const PHASE24_TOOLS = {
  // Discovery (uses 24D GraphGuidedRetrieval internally)
  get_code_context: {
    uses: ['24D.retrieve', '24E.getCommunityContext'],
    returns: 'Full context + community summary'
  },
  find_similar_code: {
    uses: ['ChromaDB.semanticSearch', '24D.enrichWithGraph'],
    returns: 'Similar patterns with graph context'
  },
  search_architecture: {
    uses: ['24E.searchCommunitySummaries'],
    returns: 'Global/holistic answers'
  },
  
  // Trace (uses 24F cross-language queries)
  trace_data_flow: {
    uses: ['24F.crossLanguageTrace'],
    returns: 'Shell→Fortran execution paths'
  },
  trace_execution_path: {
    uses: ['24F.crossLanguageTrace'],
    returns: 'J-Job→Shell→Fortran→Subroutine chains'
  },
  
  // Impact Analysis (new in 24H)
  get_change_impact: {
    uses: ['24D.traverseGraph', '24E.getCommunityContext'],
    returns: 'Blast radius, affected tests, risk score'
  },
  get_test_coverage: {
    uses: ['Neo4j.testRelationships'],
    returns: 'Direct and indirect test coverage'
  },
  
  // Session State (new in 24H)
  mark_as_modified: { persistence: 'session' },
  get_session_context: { persistence: 'session' },
  checkpoint_state: { persistence: 'durable' },
  restore_checkpoint: { persistence: 'durable' }
};
```

---

## 6. Community Detection with Fortran Nodes (24E Update)

### Extended Schema for Cross-Language Communities

```cypher
// Community detection should include Fortran nodes
CALL gds.graph.project(
  'codeGraph',
  ['ShellScript', 'File', 'FortranModule', 'FortranSubroutine', 'FortranFunction', 'FortranProgram'],
  {
    CALLS: { orientation: 'UNDIRECTED' },
    USES: { orientation: 'UNDIRECTED' },
    EXECUTES: { orientation: 'UNDIRECTED' },
    SOURCES: { orientation: 'UNDIRECTED' },
    DEPENDS_ON: { orientation: 'UNDIRECTED' }
  }
)

// Expected communities:
// - L1: GSI analysis (gsi.x, gsimain_*, related subroutines)
// - L1: EnKF system (enkf_main, update modules)
// - L1: UFS model (ufs_model, atmosphere_*, dynamics)
// - L2: Data Assimilation subsystem (GSI + EnKF)
// - L2: Forecast subsystem (UFS + post-processing)
// - L3: GFS Workflow (all subsystems)
```

### Community Summary Prompt Extension

```javascript
const CROSS_LANGUAGE_SUMMARY_PROMPT = `
You are analyzing a code community that may span multiple languages (Shell, Fortran).

## Community Members
Shell scripts: {{shell_scripts}}
Fortran modules: {{fortran_modules}}
Fortran programs: {{fortran_programs}}
Fortran subroutines: {{fortran_subroutines}}

## Key Relationships
Shell → Fortran (EXECUTES): {{executes_relations}}
Fortran → Fortran (CALLS): {{calls_relations}}
Fortran → Module (USES): {{uses_relations}}

## Task
Generate a technical summary capturing:

1. **Purpose**: What computational task does this community perform?
2. **Entry Points**: Which shell scripts invoke which Fortran programs?
3. **Core Algorithms**: What are the key Fortran subroutines?
4. **Data Flow**: How does data move from shell setup through Fortran computation?
5. **HPC Patterns**: What parallelization strategies are used (MPI, OpenMP)?

Keep under 400 words. Be specific about scientific computing aspects.
`;
```

---

## 7. Unified Timeline

| Week | Phase | Deliverable | Dependencies |
|------|-------|-------------|--------------|
| **Q2 2026** | | | |
| 1-2 | 24A | Cypher traversal queries | Neo4j 368K rels ✓ |
| 3-4 | 24B | Weight matrix (empirical) | 24A |
| 5-6 | 24C | Token budget algorithm | 24B |
| 7-10 | 24D | GraphGuidedRetrieval class | 24C, ChromaDB |
| **Q2-Q3** | | | |
| 9-12 | 24E-1,2 | Community detection + summaries | 24D, Neo4j GDS |
| 13-14 | 24E-3 | Dual retrieval router | 24E-2 |
| 13-16 | 24F | Cross-language path queries | Phase 10 ✓ |
| 15-16 | 24E-4 | Incremental update pipeline | 24E-3 |
| **Q3 2026** | | | |
| 17-18 | 24G | Benchmark: GGSR vs baseline | 24D, 24E |
| 19-20 | 24H-1 | Discovery tools | 24D, 24E |
| 21-22 | 24H-2 | Impact analysis tools | 24H-1 |
| 23-24 | 24H-3,4 | Session state + integration | 24H-2 |
| **Q4 2026** | | | |
| 25+ | 24I | Learned graph embeddings | 24G results |
| 28+ | 24J | Subgraph retrieval | 24I |

---

## 8. Success Metrics (Consolidated)

| Metric | Baseline | 24D Target | 24E Target | 24H Target |
|--------|----------|------------|------------|------------|
| Queries per complete answer | 3-5 | 1-2 | 1 | 1 |
| Global query accuracy | ~30% | ~30% | >75% | >75% |
| Cross-language trace success | 0% | 0% | - | >90% |
| Session resumption success | N/A | N/A | N/A | >90% |
| Impact prediction accuracy | N/A | N/A | N/A | >85% |
| P95 latency | ~500ms | <800ms | <1000ms | <1000ms |
| Token efficiency | Unknown | >60% | >60% | >60% |

---

## 9. Open Questions (Consolidated)

From all three documents:

### Already Resolved
- ✅ Timeline conflicts → Sequenced in §7
- ✅ Tool overlap → Clarified in §5
- ✅ Missing sub-phases → Added 24F, 24G

### Still Open
1. **Community Naming** (24E): Auto-generated vs human-curated labels?
2. **Session Persistence** (24H): Redis vs SQLite for checkpoints?
3. **Cross-Repo Communities** (24E): Should communities span repositories?
4. **Rate Limiting** (24H): Should expensive tools have rate limits?
5. **Fortran Test Detection** (24F): How do we identify which subroutines are tested?

---

## 10. Roadmap Alignment

### ADVANCED_FUTURE_WORK.md §3 Traceability

| Vision Phase | Phase 24 Implementation | Status |
|--------------|-------------------------|--------|
| Phase 1: Entity Linking | 24A: Traversal queries | Q2 2026 |
| Phase 2: Relationship-Weighted Scoring | 24B: Weight tuning | Q2 2026 |
| Phase 3: Learned Graph Embeddings | 24I: node2vec/GNN | Q4 2026 |
| Phase 4: Subgraph Retrieval | 24J: Reasoning | Q4 2026 |

### Novel Extensions (Beyond Original Vision)
- **24E**: Hierarchical community summarization (Microsoft GraphRAG pattern)
- **24F**: Cross-language graph integration (Shell+Fortran)
- **24H**: Session-aware agentic tools (workflow optimization)

---

## 11. File Naming Cleanup

**Issue:** Current files have inconsistent naming:
- `Phase24E _HierarchicalCommunit.md` (space, truncated)
- `phase24h_supplement_graphRAG.md` (lowercase, "supplement")

**Recommended Standardization:**
```
phase24_consolidated_architecture.md  (this file - master reference)
phase24a-d_ggsr_foundation.md         (rename from original)
phase24e_hierarchical_communities.md  (rename, fix name)
phase24f_cross_language_integration.md (new)
phase24g_benchmark_validation.md      (new)
phase24h_agentic_tool_surface.md      (rename, drop "supplement")
```

---

## 12. Next Actions

1. **Immediate**: Rename files per §11 naming convention
2. **Phase 10 M5**: Update MCP tools to leverage Fortran graph (enables 24F)
3. **24A Kickoff**: Begin Cypher traversal query development
4. **Neo4j GDS**: Verify GDS plugin available for community detection

---

*Consolidated from three source documents on 2026-02-05*
*Phase 10 Fortran ingestion completed: 368K relationships available for Phase 24*
