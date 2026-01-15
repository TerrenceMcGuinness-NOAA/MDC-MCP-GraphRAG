# SDD: Phase 24 - Graph-Guided Speculative Retrieval

**Version:** 1.0.0  
**Created:** 2026-01-15  
**Author:** AI Assistant + Terry McGuinness  
**Status:** Prospectus (Q2 2026)  
**Target Quarter:** Q2 2026 (April - June)

---

## 1. Executive Summary

This phase proposes a fundamental shift from **tool-assisted RAG** to **inference-integrated RAG** by convolving two architectural patterns:

1. **Graph-Structured Reasoning** - Use Neo4j relationships to scaffold multi-step reasoning
2. **Speculative Pre-fetch** - Anticipate information needs based on graph neighborhood

The result is **Graph-Guided Speculative Retrieval (GGSR)**: when a user query touches any node in the knowledge graph, the system traverses outward and pre-loads semantically adjacent nodes into context *before* the user asks follow-up questions.

### Key Innovation

Move RAG from a **lookup service** called during inference to an **inference substrate** that shapes the reasoning space itself.

---

## 2. Problem Statement

### Current State: Tool-Assisted RAG

```
User Query → LLM → [decides to call tool] → RAG Search → Results → LLM → Response
                   ↑
            LLM controls when/if to use RAG
```

**Limitations:**
- Multi-turn: User must ask follow-up questions for related context
- Reactive: No anticipation of information needs
- Siloed: Vector search and graph traversal are separate operations
- Stateless: Each query starts fresh with no semantic memory

### Target State: Inference-Integrated RAG

```
User Query → Entity Extraction → Graph Traversal → Speculative Fetch → 
           → Augmented Context (query + neighborhood) → LLM → Complete Response
```

**Benefits:**
- One query, complete answer
- Graph topology guides reasoning structure
- Anticipatory context loading
- Reduced round-trips between user and system

---

## 3. Technical Architecture

### 3.1 System Flow

```
┌─────────────────────────────────────────────────────────┐
│                   User Query                            │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│  1. Entity Extraction                                   │
│     "config.resources" → Node ID in Neo4j               │
│     Uses: NER, keyword matching, embedding similarity   │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│  2. Graph Traversal (Speculative)                       │
│     MATCH (n)-[r*1..2]-(related)                        │
│     WHERE n.name = 'config.resources'                   │
│     RETURN related, type(r), r.weight                   │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│  3. Weighted Pre-fetch from ChromaDB                    │
│     - CALLS/SOURCES: weight 1.0 (definitely relevant)   │
│     - DEPENDS_ON: weight 0.8 (likely relevant)          │
│     - IMPORTS: weight 0.6 (possibly relevant)           │
│     - 2-hop connections: weight × 0.5 decay             │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│  4. Context Assembly                                    │
│     [User Query]                                        │
│     [Primary Match: config.resources content]           │
│     [Speculative Context: env/*.env summaries]          │
│     [Speculative Context: calling scripts]              │
│     Token budget: 4000-8000 tokens                      │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│  5. LLM Inference with Pre-loaded Graph Neighborhood    │
└─────────────────────────────────────────────────────────┘
```

### 3.2 Graph Traversal Example

When user mentions `config.resources`:

```
                         config.resources
                               │
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                      ▼
    SOURCES                DEPENDS_ON             CALLED_BY
        │                      │                      │
        ▼                      ▼                      ▼
  env/HERA.env            env/WCOSS2.env        JGFS_FORECAST
  env/ORION.env           parm/config/*         exglobal_*.sh
        │                                             │
        └──────────────► PRE-LOADED ◄─────────────────┘
                       INTO CONTEXT
```

### 3.3 Relationship Weight Matrix

| Relationship | Weight | Rationale |
|--------------|--------|-----------|
| `CALLS` | 1.0 | If examining A, will need what A calls |
| `CALLED_BY` | 0.9 | Caller provides context for why A exists |
| `SOURCES` | 0.95 | Shell sourcing = tight coupling |
| `DEPENDS_ON` | 0.8 | Dependencies explain behavior |
| `IMPORTS` | 0.7 | Python imports = likely related |
| `DOC_REFERENCES` | 0.6 | Documentation often needed |
| `SAME_DIRECTORY` | 0.4 | Proximity hints at relatedness |
| `AUTHORED_BY` | 0.3 | Author context occasionally useful |

**Hop Decay:** Multiply weight by 0.5 for each additional hop (2-hop max).

---

## 4. Implementation Phases

### Phase 24A: Traversal Query Prototype (Week 1-2)

**Objective:** Validate graph traversal patterns against live Neo4j

**Steps:**
- [ ] Write Cypher queries for 1-hop and 2-hop neighborhood traversal
- [ ] Test against current Neo4j (86,189 relationships)
- [ ] Measure query latency (target: <100ms)
- [ ] Validate relationship type coverage

**Cypher Template:**
```cypher
MATCH (n:File|Function)-[r1]-(hop1)
WHERE n.name =~ '(?i).*config.resources.*' 
   OR n.path =~ '(?i).*config.resources.*'
OPTIONAL MATCH (hop1)-[r2]-(hop2)
WHERE NOT hop2 = n
RETURN n.name, n.path,
       type(r1) as rel1, hop1.name as neighbor1, hop1.path as path1,
       type(r2) as rel2, hop2.name as neighbor2, hop2.path as path2
LIMIT 50
```

### Phase 24B: Weight Tuning & Empirical Validation (Week 3-4)

**Objective:** Determine optimal weights through user study

**Steps:**
- [ ] Instrument current tool usage to log follow-up queries
- [ ] Analyze: "After querying X, what did users query next?"
- [ ] Correlate follow-up queries with graph relationships
- [ ] Adjust weights based on empirical prediction accuracy

**Metrics:**
- Prediction Accuracy: Did speculative fetch include what user asked next?
- Precision: What % of speculative context was actually used?
- Recall: What % of user's actual needs were pre-fetched?

### Phase 24C: Token Budget Management (Week 5-6)

**Objective:** Optimize context window utilization

**Steps:**
- [ ] Implement token counting for ChromaDB documents
- [ ] Design summarization strategy for large documents
- [ ] Create priority queue: primary match → 1-hop → 2-hop
- [ ] Test with varying budgets: 2K, 4K, 8K, 16K tokens

**Algorithm:**
```
ranked_nodes = sort_by_weight(neighborhood)
context = []
tokens_used = 0

for node in ranked_nodes:
    doc = fetch_document(node)
    if tokens_used + len(doc) > budget:
        doc = summarize(doc, remaining_budget)
    context.append(doc)
    tokens_used += len(doc)
    if tokens_used >= budget:
        break
```

### Phase 24D: MCP Integration (Week 7-8)

**Objective:** Integrate GGSR into MCP tool pipeline

**Options:**
1. **New Tool:** `speculative_search_documentation` - explicit GGSR
2. **Enhanced Existing:** Modify `search_documentation` with `--speculative` flag
3. **Automatic Mode:** Always use GGSR when graph data available

**Recommended:** Option 3 with fallback to vector-only when graph unavailable

**New Module:** `src/tools/GraphGuidedRetrieval.js`

```javascript
class GraphGuidedRetrieval {
  constructor(neo4jClient, chromaClient, options = {}) {
    this.neo4j = neo4jClient;
    this.chroma = chromaClient;
    this.maxHops = options.maxHops || 2;
    this.tokenBudget = options.tokenBudget || 4000;
    this.weights = options.weights || DEFAULT_WEIGHTS;
  }

  async retrieve(query) {
    // 1. Entity extraction
    const entities = await this.extractEntities(query);
    
    // 2. Graph traversal
    const neighborhood = await this.traverseGraph(entities);
    
    // 3. Weighted ranking
    const ranked = this.rankByWeight(neighborhood);
    
    // 4. Fetch with token budget
    const context = await this.fetchWithBudget(ranked);
    
    return {
      primaryResults: context.primary,
      speculativeContext: context.speculative,
      graphPath: neighborhood.paths,
      tokensUsed: context.tokensUsed
    };
  }
}
```

---

## 5. Success Metrics

| Metric | Current | Target | Measurement |
|--------|---------|--------|-------------|
| Queries to complete answer | 2-4 | 1 | User interaction logs |
| Follow-up prediction accuracy | N/A | >70% | A/B test with/without GGSR |
| Context relevance (user rating) | N/A | >4.0/5.0 | Feedback mechanism |
| Query latency | ~500ms | <800ms | End-to-end timing |
| Token efficiency | Unknown | >60% used | Track context utilization |

---

## 6. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Over-fetching irrelevant context | Medium | Medium | Tune weights empirically; add user feedback loop |
| Latency increase from graph traversal | Low | Medium | Cache hot paths; async pre-fetch |
| Token budget exceeded by large neighborhoods | Medium | Low | Summarization fallback; priority queue |
| Entity extraction misses key terms | Medium | High | Hybrid: NER + embedding similarity + keyword |
| Graph data stale vs ChromaDB | Low | Medium | Sync pipeline; version alignment |

---

## 7. Dependencies

### Required Infrastructure
- [x] Neo4j with relationship data (86,189 relationships) ✓
- [x] ChromaDB with document embeddings (14,968 docs) ✓
- [ ] Entity extraction module (NER or embedding-based)
- [ ] Token counting utility
- [ ] Document summarization capability

### Related SDD Phases
- Phase 4: Dynamic Source Analysis (entity extraction patterns)
- Phase 19: Content Abstraction Layer (document access patterns)
- Phase 22: Validation & Benchmarking (metrics framework) - **CRITICAL DEPENDENCY**

### Roadmap Alignment

> **This phase implements the concrete execution plan for "True GraphRAG Fusion"
> as defined in [ADVANCED_FUTURE_WORK.md §3](../../docs/development/ADVANCED_FUTURE_WORK.md#3-true-graphrag-fusion)**

| ADVANCED_FUTURE_WORK Phase | Phase 24 Implementation | Status |
|----------------------------|-------------------------|--------|
| Phase 1: Entity Linking | Phase 24A: Traversal Query Prototype | Aligned |
| Phase 2: Relationship-Weighted Scoring | Phase 24B: Weight Tuning | Aligned |
| Phase 3: Learned Graph Embeddings | Deferred (Q3 2026) | Future |
| Phase 4: Subgraph Retrieval | Deferred (Q4 2026) | Future |

**Novel Contributions** (not in original vision):
- Speculative pre-fetch (anticipatory context loading)
- Token budget management (context window optimization)

---

## 8. Timeline

| Week | Phase | Deliverable |
|------|-------|-------------|
| 1-2 | 24A | Cypher traversal queries validated |
| 3-4 | 24B | Weight matrix empirically tuned |
| 5-6 | 24C | Token budget algorithm implemented |
| 7-8 | 24D | MCP integration complete |
| 9 | Testing | End-to-end validation |
| 10 | Documentation | User guide, API docs |

**Total Duration:** 10 weeks (Q2 2026)

---

## 9. Open Questions

1. **Caching Strategy:** Should we cache graph neighborhoods for frequently accessed nodes?
2. **User Feedback Loop:** How do we collect implicit feedback on speculative context usefulness?
3. **Multi-Entity Queries:** When query mentions multiple entities, how do we merge neighborhoods?
4. **Cross-Repository Traversal:** Should speculation cross repository boundaries?
5. **Session Memory:** Should speculative context persist across queries in a session?

---

## 10. References

### Internal
- **[ADVANCED_FUTURE_WORK.md §3](../../docs/development/ADVANCED_FUTURE_WORK.md#3-true-graphrag-fusion)**: True GraphRAG Fusion vision (this SDD implements Phases 1-2)
- **[Phase 22 SDD](phase22_validation_benchmarking_subsystem.md)**: Validation framework for benchmarking GGSR vs baseline
- Neo4j Schema: 86,189 relationships across CALLS, IMPORTS, SOURCES, DEPENDS_ON, etc.
- ChromaDB Collections: 12 collections, 14,968 documents
- MCP Tool Architecture: Week 2 consolidated, 35 tools

### External (Peer-Reviewed)

#### GraphRAG Foundations
- **He et al. (2025)**: "GraphRAG Under Fire" - Comprehensive survey of Graph-based RAG methods, taxonomy of retrieval-augmented generation with knowledge graphs. [arXiv:2501.00309](https://arxiv.org/abs/2501.00309)
- **Fang et al. (2024)**: "LEGO-GraphRAG: Modularizing Graph-based Retrieval-Augmented Generation" - Design space exploration, modular framework decomposition. [arXiv:2411.05844](https://arxiv.org/abs/2411.05844)
- **Wu et al. (2025)**: "AGRAG: An Agentic Graph Retrieval Augmented Generation" - Multi-agent GraphRAG architecture. [arXiv:2511.05549](https://arxiv.org/abs/2511.05549)
- **Zhou et al. (2025)**: "XGraphRAG: Explainable Graph-based Retrieval-Augmented Generation" - Interpretable graph traversal for RAG. [arXiv:2506.13782](https://arxiv.org/abs/2506.13782)

#### Token-Efficient Retrieval
- **Wang et al. (2025)**: "TERAG: Token-Efficient GraphRAG" - Cost-effective context compression for graph-augmented retrieval. [arXiv:2509.18667](https://arxiv.org/abs/2509.18667)
- **Ravi et al. (2024)**: "CORAG: Cost-Constrained Retrieval Optimization for RAG" - Budget-aware retrieval under token constraints. [arXiv:2411.00744](https://arxiv.org/abs/2411.00744)
- **Liu et al. (2024)**: "HiRAG: Hierarchical Retrieval-Augmented Generation" - Efficient context hierarchy for reduced token usage. [arXiv:2408.11875](https://arxiv.org/abs/2408.11875)

#### Code Knowledge Graphs
- **Wei et al. (2024)**: "CKGFuzzer: LLM-Based Fuzz Driver Generation via Code Knowledge Graph" - Automated code knowledge graph construction. [arXiv:2411.11532](https://arxiv.org/abs/2411.11532)
- **Abdelaziz et al. (2020)**: "GraphGen4Code: A Graph-based Code Analysis Framework" - 2 billion code relationships at scale. [arXiv:2002.09440](https://arxiv.org/abs/2002.09440)

#### Weather/NWP AI Context
- **Bi et al. (2022)**: "Pangu-Weather: A 3D High-Resolution Model for Fast and Accurate Global Weather Forecasting" - AI models outperforming NWP operational systems. [arXiv:2211.02556](https://arxiv.org/abs/2211.02556)
- **Chen et al. (2024)**: "FuXi-2.0: A Generalized AI Foundation Model for Weather and Climate" - Multi-modal forecasting foundation model. [arXiv:2409.07188](https://arxiv.org/abs/2409.07188)
- Palmer et al. (2020): "A Vision for NWP 2030" - Complexity drivers for next-generation weather systems

#### Design Inspiration
- **Baek et al. (2024)**: "Plan*RAG: Planning-Guided RAG for Decision QA" - Multi-step retrieval planning. [arXiv:2410.20753](https://arxiv.org/abs/2410.20753)
- **Yang et al. (2024)**: "ROGRAG: Robustness-Oriented Graph Retrieval Augmented Generation" - Edge case handling in graph retrieval. [arXiv:2503.06474](https://arxiv.org/abs/2503.06474)

---

## 11. Appendix: Comparison Before/After

### Before (Current Tool-Assisted)

```
User: "How does config.resources work?"
LLM: [calls search_documentation]
LLM: [reads result]
LLM: "It defines resources... you might also want to look at env files"
User: "Show me the env files"
LLM: [calls another tool]
User: "What about the forecast script?"
LLM: [calls another tool]
...
```

**Result:** 3+ round trips to get complete picture

### After (Graph-Guided Speculative)

```
User: "How does config.resources work?"

System: [graph traversal finds: config.resources → SOURCES → env/*.env]
        [graph traversal finds: config.resources → CALLED_BY → JGFS_FORECAST]
        [pre-loads all into context]

LLM: "config.resources defines computational resources using if-elif 
      cascades. Here's how it works:

      1. Resource Selection (config.resources lines 45-67):
         [shows relevant code]

      2. Platform Integration - On HERA (env/HERA.env):
         [shows APRUN configuration]

      3. On WCOSS2 (env/WCOSS2.env):
         [shows mpiexec configuration]

      4. Usage in Forecast (JGFS_FORECAST → exglobal_forecast.sh):
         [shows how resources are consumed]

      The key difference from CROW is that this approach uses 
      imperative shell logic rather than declarative YAML tables..."
```

**Result:** Complete answer in one query

---

*Document generated as part of SDD Phase 24 prospectus - Q2 2026*
