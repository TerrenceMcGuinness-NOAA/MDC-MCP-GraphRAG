# Advanced Future Work: MCP/RAG System Evolution

**Document Type**: Strategic Development Roadmap  
**Target**: Q2 2026 Funding Cycle  
**Status**: Draft for Review  
**Last Updated**: January 6, 2026  
**Authors**: EIB Development Team

---

## Executive Summary

The MCP/RAG system has achieved operational capability with 38 tools, hybrid retrieval (ChromaDB + Neo4j), and EE2 compliance validation. This document outlines the next evolutionary phase: **intelligent, self-improving AI assistance** that learns from operational history, understands visual system representations, and provides truly graph-aware semantic reasoning.

Three transformational initiatives are proposed:

| Initiative | Impact | Complexity | Timeline |
|------------|--------|------------|----------|
| Multi-Modal Visual Understanding | High | Medium | Q2 2026 |
| Self-Learning from CI/CD History | Very High | High | Q2-Q3 2026 |
| True GraphRAG Fusion | Transformational | High | Q3 2026 |

**Estimated Team Requirement**: 3-4 FTEs + LLM fine-tuning expertise  
**Infrastructure**: Existing + GPU compute for training

---

## 1. Multi-Modal Visual Understanding

### 1.1 Problem Statement

The Global Workflow system has extensive visual documentation:
- **Rocoto XML DAG flowcharts** showing job dependencies
- **System architecture diagrams** maintained by SMEs
- **UML-style component diagrams** for subsystems (GSI, UFS, UPP)
- **Operational runbooks** with embedded decision flowcharts

Current RAG systems treat these as opaque images or skip them entirely. Yet these diagrams often contain the most accurate, up-to-date representation of system relationships.

### 1.2 Proposed Solution

Leverage multi-modal LLM capabilities (GPT-4V, Claude 3.5 Sonnet, Gemini Pro Vision) to:

1. **Index Visual Content**: Extract semantic understanding from flowcharts during ingestion
2. **Runtime Visual Queries**: Allow operators to ask "What does this diagram show?" with image input
3. **Cross-Reference**: Link visual elements to code entities in Neo4j graph

### 1.3 Technical Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Multi-Modal Ingestion Pipeline               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐     ┌──────────────┐    ┌──────────────────┐  │
│  │  Flowchart   │ ──▶│ Vision LLM   │───▶│ Structured JSON  │  │
│  │  PNG/SVG     │     │ Extraction   │    │ (nodes, edges)   │  │
│  └──────────────┘     └──────────────┘    └────────┬─────────┘  │
│                                                    │            │
│  ┌──────────────┐    ┌──────────────┐              │            │
│  │  Rocoto XML  │───▶│ DAG Parser   │─────────────┤            │
│  │  Workflow    │    │              │              │            │
│  └──────────────┘    └──────────────┘             ▼            │
│                                          ┌──────────────────┐  │
│                                          │   Neo4j Graph    │  │
│                                          │   (visual_node)  │  │
│                                          └──────────────────┘  │
│                                                    │            │
│                                                    ▼            │
│                                          ┌──────────────────┐  │
│                                          │   ChromaDB       │  │
│                                          │ (visual_context) │  │
│                                          └──────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 1.4 Key Deliverables

- [ ] Visual content ingestion pipeline for PNG, SVG, PDF diagrams
- [ ] Neo4j schema extension: `(:VisualElement)-[:DEPICTS]->(:CodeEntity)`
- [ ] New MCP tool: `analyze_visual_diagram` 
- [ ] ChromaDB collection: `global-workflow-visuals-v1`
- [ ] Integration with existing SME-maintained flowcharts

### 1.5 Success Metrics

| Metric | Target |
|--------|--------|
| Diagram coverage | 80% of documented flowcharts indexed |
| Visual query accuracy | 85% correct entity extraction |
| Cross-reference linkage | 70% visual elements linked to code |

---

## 2. Self-Learning from CI/CD History

### 2.1 Vision

Transform the MCP/RAG system from a **static knowledge retrieval** system to a **continuously learning** system that improves from operational experience.

### 2.2 The Learning Loop

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Self-Learning Training Pipeline                       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   ┌─────────────┐         ┌─────────────┐         ┌─────────────┐      │
│   │  CI/CD      │         │  Git Log    │         │  GitHub PR  │      │
│   │  Error Logs │         │  History    │         │  Messages   │      │
│   └──────┬──────┘         └──────┬──────┘         └──────┬──────┘      │
│          │                       │                       │              │
│          └───────────────────────┼───────────────────────┘              │
│                                  ▼                                      │
│                    ┌─────────────────────────────┐                      │
│                    │   Training Data Generator   │                      │
│                    │   (Error → Solution Pairs)  │                      │
│                    └──────────────┬──────────────┘                      │
│                                   │                                     │
│                                   ▼                                     │
│          ┌────────────────────────────────────────────┐                 │
│          │         MCP/RAG Attempt Resolution         │                 │
│          │    (Generate candidate fix using RAG)      │                 │
│          └────────────────────────┬───────────────────┘                 │
│                                   │                                     │
│                                   ▼                                     │
│          ┌────────────────────────────────────────────┐                 │
│          │           Validation Against               │                 │
│          │        Actual Git Commit/PR Fix            │                 │
│          └────────────────────────┬───────────────────┘                 │
│                                   │                                     │
│                   ┌───────────────┴───────────────┐                     │
│                   ▼                               ▼                     │
│          ┌──────────────┐                ┌──────────────┐               │
│          │   Correct    │                │  Incorrect   │               │
│          │  (Reinforce) │                │   (Learn)    │               │
│          └──────┬───────┘                └──────┬───────┘               │
│                 │                               │                       │
│                 └───────────────┬───────────────┘                       │
│                                 ▼                                       │
│                    ┌─────────────────────────────┐                      │
│                    │   Fine-Tuning Dataset       │                      │
│                    │   (RLHF / DPO Format)       │                      │
│                    └──────────────┬──────────────┘                      │
│                                   │                                     │
│                                   ▼                                     │
│                    ┌─────────────────────────────┐                      │
│                    │   Domain-Adapted Weights    │                      │
│                    │   (LoRA / QLoRA Adapter)    │                      │
│                    └─────────────────────────────┘                      │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.3 Data Sources

| Source | Volume | Content |
|--------|--------|---------|
| Jenkins CI logs | ~50,000 builds/year | Build failures, test errors, deployment issues |
| GitHub Actions | ~10,000 runs/year | Workflow failures, linting errors |
| Git commit history | ~5,000 commits/year | Fixes, refactors, bug patches |
| GitHub PR discussions | ~800 PRs/year | Problem descriptions, review comments, solutions |
| Jira/Issue trackers | ~1,200 tickets/year | Bug reports, resolution notes |

### 2.4 Training Data Format

```json
{
  "error_context": {
    "log_snippet": "FATAL: exglobal_atmos_analysis.py line 342: KeyError 'LEVS'",
    "job_name": "gfs_atmos_analysis_f000",
    "platform": "WCOSS2",
    "timestamp": "2025-08-15T06:32:00Z"
  },
  "rag_attempt": {
    "retrieved_docs": ["config_guide.md#environment-vars", "LEVS_param.rst"],
    "generated_fix": "Add LEVS=${LEVS:-127} to job card preamble",
    "confidence": 0.72
  },
  "actual_solution": {
    "commit_sha": "a1b2c3d4",
    "pr_number": 1247,
    "fix_description": "Export LEVS from parent script before job submission",
    "files_changed": ["scripts/exglobal_atmos_analysis.sh"]
  },
  "evaluation": {
    "rag_correct": false,
    "error_category": "environment_variable_propagation",
    "lesson": "LEVS must be exported, not just set, for subprocess inheritance"
  }
}
```

### 2.5 Fine-Tuning Strategy

**Phase 1: Supervised Fine-Tuning (SFT)**
- Create instruction-following dataset from correct solutions
- Fine-tune base model (Llama 3, Mistral, or domain-specific)
- Target: Improve first-attempt accuracy on common error patterns

**Phase 2: Reinforcement Learning from Human Feedback (RLHF)**
- Collect SME preferences on generated solutions
- Train reward model on preference pairs
- PPO optimization for solution quality

**Phase 3: Direct Preference Optimization (DPO)**
- Simpler alternative to full RLHF
- Use (RAG attempt, actual fix) pairs as preference data
- Lower compute requirements, faster iteration

### 2.6 Deployment Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  Inference Stack                        │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─────────────────┐     ┌─────────────────────────┐   │
│  │  Base LLM       │     │  Domain LoRA Adapter    │   │
│  │  (Claude/GPT)   │ ◀── │  (GFS/GEFS Expertise)   │   │
│  └────────┬────────┘     └─────────────────────────┘   │
│           │                                             │
│           ▼                                             │
│  ┌─────────────────────────────────────────────────┐   │
│  │              MCP/RAG Hybrid Layer               │   │
│  │  ChromaDB (semantic) + Neo4j (graph) + Adapter  │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 2.7 Key Deliverables

- [ ] CI/CD log parser and error categorizer
- [ ] Git history analyzer (commit ↔ issue linkage)
- [ ] Training data generation pipeline
- [ ] Fine-tuning infrastructure (GPU cluster access)
- [ ] LoRA adapter for GFS/GEFS domain
- [ ] A/B testing framework for model comparison
- [ ] Continuous learning pipeline (monthly retraining)

### 2.8 Success Metrics

| Metric | Baseline | Target |
|--------|----------|--------|
| First-attempt fix accuracy | 35% | 65% |
| Time to resolution (assisted) | 4.2 hours | 1.5 hours |
| SME satisfaction score | 3.2/5 | 4.5/5 |
| Novel error pattern recognition | 0% | 40% |

---

## 3. True GraphRAG Fusion

### 3.1 Current Limitation

Today's hybrid retrieval is **parallel but disconnected**:

```
Query → ChromaDB (semantic similarity) → Results A
Query → Neo4j (graph traversal) → Results B
Merge A + B → Final Results
```

The graph structure does NOT inform the semantic search, and vice versa.

### 3.2 GraphRAG Vision

**Graph-Informed Semantic Search**: Use relationship topology as a retrieval dimension.

```
Query: "How do I fix the sfcanl job when it fails on missing sea ice data?"

Traditional RAG:
  → Searches for "sfcanl" + "sea ice" + "missing" in vector space
  → May miss: seaice_analysis.py, prep_seaice.sh, ice_blend.F90

GraphRAG:
  → Finds sfcanl job node in Neo4j
  → Traverses: sfcanl -[DEPENDS_ON]-> prep_seaice -[CALLS]-> ice_blend
  → Expands semantic search to include 2-hop neighborhood
  → Retrieves documentation for ALL related components
  → Ranks by: semantic_score × graph_proximity_score
```

### 3.3 Technical Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         GraphRAG Retrieval Engine                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐ │
│  │                        Query Understanding                         │ │
│  │  "Fix sfcanl sea ice failure" → entities: [sfcanl, sea_ice]       │ │
│  └───────────────────────────────────────────────────────────────────┘ │
│                                    │                                    │
│                    ┌───────────────┴───────────────┐                   │
│                    ▼                               ▼                    │
│  ┌─────────────────────────────┐   ┌─────────────────────────────┐    │
│  │       Neo4j Expansion       │   │    ChromaDB Base Search     │    │
│  │                             │   │                             │    │
│  │  MATCH (n {name:'sfcanl'})  │   │  similarity_search(         │    │
│  │  -[*1..3]-(related)         │   │    "sfcanl sea ice failure" │    │
│  │  RETURN related.name,       │   │  )                          │    │
│  │         relationship_type,  │   │                             │    │
│  │         path_length         │   │  → [doc1, doc2, doc3, ...]  │    │
│  │                             │   │                             │    │
│  │  → [prep_seaice: 1 hop,     │   │                             │    │
│  │     ice_blend: 2 hops,      │   │                             │    │
│  │     CICE_config: 2 hops]    │   │                             │    │
│  └──────────────┬──────────────┘   └──────────────┬──────────────┘    │
│                 │                                  │                   │
│                 └──────────────────┬───────────────┘                   │
│                                    ▼                                   │
│  ┌───────────────────────────────────────────────────────────────────┐ │
│  │                    Graph-Aware Reranking                          │ │
│  │                                                                   │ │
│  │  final_score = α × semantic_sim + β × (1 / graph_distance) +     │ │
│  │                γ × relationship_weight                            │ │
│  │                                                                   │ │
│  │  Where:                                                           │ │
│  │    - semantic_sim: cosine similarity from ChromaDB                │ │
│  │    - graph_distance: shortest path length in Neo4j                │ │
│  │    - relationship_weight: CALLS > DEPENDS_ON > REFERENCES         │ │
│  │    - α, β, γ: learned or tuned weights                           │ │
│  └───────────────────────────────────────────────────────────────────┘ │
│                                    │                                   │
│                                    ▼                                   │
│  ┌───────────────────────────────────────────────────────────────────┐ │
│  │                     Augmented Context Window                      │ │
│  │                                                                   │ │
│  │  [High relevance]  sfcanl_job_card.rst (0.92)                    │ │
│  │  [Graph neighbor]  prep_seaice.sh (0.78 + 1-hop bonus)           │ │
│  │  [Graph neighbor]  ice_blend.F90 (0.65 + 2-hop bonus)            │ │
│  │  [Semantic only]   seaice_overview.md (0.71)                     │ │
│  └───────────────────────────────────────────────────────────────────┘ │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.4 Implementation Phases

**Phase 1: Entity Linking** (Q2 2026)
- Extract named entities from queries (job names, file names, functions)
- Link to Neo4j nodes
- Expand search scope to N-hop neighbors

**Phase 2: Relationship-Weighted Scoring** (Q2-Q3 2026)
- Assign weights to relationship types (CALLS, IMPORTS, DEPENDS_ON)
- Incorporate path length into reranking
- A/B test against baseline hybrid retrieval

**Phase 3: Learned Graph Embeddings** (Q3 2026)
- Train graph neural network on Neo4j structure
- Generate node embeddings that capture topological position
- Fuse with text embeddings in joint vector space

**Phase 4: Subgraph Retrieval** (Q4 2026)
- Return relevant subgraphs, not just nodes
- Visualize dependency chains in responses
- "Here's why sfcanl depends on sea ice processing: [interactive graph]"

### 3.5 Key Deliverables

- [ ] Entity extraction and Neo4j linking module
- [ ] Graph-aware reranking algorithm
- [ ] Relationship weight tuning framework
- [ ] Graph embedding training pipeline (optional Phase 3)
- [ ] Updated MCP tools with GraphRAG backend
- [ ] Evaluation benchmark: GraphRAG vs baseline

### 3.6 Success Metrics

| Metric | Baseline (Hybrid) | Target (GraphRAG) |
|--------|-------------------|-------------------|
| Recall@10 for related code | 62% | 85% |
| Cross-component issue resolution | 45% | 75% |
| "Missing context" user complaints | 23% of queries | <10% |
| Avg. relevant docs per query | 3.2 | 6.5 |

---

## 4. Additional Strategic Enhancements

### 4.1 Temporal Awareness

**Goal**: Understand time-sensitive aspects of weather operations.

- Index by model cycle (00Z, 06Z, 12Z, 18Z)
- Track documentation freshness (stale content warnings)
- Version-aware retrieval ("Show me the GFS v16.3 config, not v17")

### 4.2 Confidence Calibration

**Goal**: Provide uncertainty quantification with every response.

```
Response: "Set FHMAX=384 for extended forecast"
Confidence: HIGH (0.94) - Found in 3 authoritative sources
Source agreement: 3/3 sources consistent
Last verified: 2025-12-15
```

### 4.3 Proactive Anomaly Detection

**Goal**: Warn before changes cause downstream issues.

- Monitor code changes against Neo4j dependency graph
- Alert: "Modifying `exglobal_forecast.py` impacts 12 downstream jobs"
- Integration with PR review process

### 4.4 Execution Memory

**Goal**: Learn from past workflow executions.

- Capture SDD workflow outcomes (success/failure/partial)
- Build "lessons learned" knowledge base
- Surface: "Last time X was attempted on WCOSS2, issue Y occurred"

---

## 5. Resource Requirements

### 5.1 Team Composition

| Role | FTE | Responsibilities |
|------|-----|------------------|
| ML Engineer | 1.5 | Fine-tuning, GraphRAG implementation |
| Backend Developer | 1.0 | Pipeline development, Neo4j/ChromaDB |
| DevOps/MLOps | 0.5 | Training infrastructure, CI/CD |
| Domain SME (part-time) | 0.5 | Validation, feedback, training data QA |
| **Total** | **3.5 FTE** | |

### 5.2 Infrastructure

| Resource | Specification | Est. Cost/Month |
|----------|---------------|-----------------|
| GPU Compute (training) | 4x A100 80GB | $8,000 |
| GPU Compute (inference) | 2x A10G | $2,000 |
| Storage (training data) | 2TB NVMe | $200 |
| Neo4j Enterprise (optional) | 32GB RAM cluster | $1,500 |
| ChromaDB (current) | Existing | $0 |
| **Total** | | **~$11,700/month** |

### 5.3 Timeline

```
Q2 2026
├── Month 1: Multi-modal pipeline, CI/CD log parser
├── Month 2: Visual content indexing, training data generation
└── Month 3: GraphRAG Phase 1 (entity linking)

Q3 2026
├── Month 4: Fine-tuning infrastructure, first LoRA adapter
├── Month 5: GraphRAG Phase 2 (relationship scoring)
└── Month 6: A/B testing, evaluation benchmarks

Q4 2026
├── Month 7: RLHF/DPO training cycles
├── Month 8: GraphRAG Phase 3 (learned embeddings)
└── Month 9: Production deployment, documentation
```

---

## 6. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Insufficient training data quality | Medium | High | SME review cycles, data augmentation |
| GPU compute availability | Medium | Medium | Cloud burst capacity, spot instances |
| Model hallucination on novel errors | High | Medium | Confidence thresholds, human-in-loop |
| Neo4j performance at scale | Low | Medium | Query optimization, caching |
| Scope creep | High | Medium | Strict phase gates, MVP focus |

---

## 7. Success Criteria for Funding Approval

### 7.1 Minimum Viable Outcomes (Must Achieve)

- [ ] Visual diagram ingestion operational for top 20 flowcharts
- [ ] Training data pipeline generating 1000+ error→solution pairs
- [ ] GraphRAG entity linking showing measurable recall improvement
- [ ] One fine-tuned adapter deployed for evaluation

### 7.2 Stretch Goals

- [ ] Full RLHF training cycle completed
- [ ] GraphRAG with learned embeddings
- [ ] Proactive anomaly detection in PR workflow
- [ ] Sub-2-hour assisted resolution time for common errors

---

## 8. Conclusion

The MCP/RAG system has proven the value of AI-assisted weather operations. The next phase transforms it from a **knowledge retrieval tool** into an **intelligent learning partner** that:

1. **Sees** what operators see (visual understanding)
2. **Learns** from every resolved issue (self-improvement)
3. **Understands** system relationships deeply (GraphRAG)

This is not incremental improvement—it's a paradigm shift toward **autonomous operational intelligence** for NOAA's critical weather forecasting infrastructure.

---

## Appendix A: References

- Microsoft GraphRAG: https://github.com/microsoft/graphrag
- LoRA Fine-Tuning: https://arxiv.org/abs/2106.09685
- DPO Training: https://arxiv.org/abs/2305.18290
- Neo4j Graph Data Science: https://neo4j.com/docs/graph-data-science/
- ChromaDB Documentation: https://docs.trychroma.com/

## Appendix B: Related Internal Documents

- [MCP_RAG_System_Architecture.pdf](https://vlab.noaa.gov/gitlab-community/NWS/Operations/NCEP/EMC/eib-mcp-rag-server/-/blob/main/docs/presentations/papers/mcp_rag_ai_initiative/MCP_RAG_System_Architecture.pdf)
- [HYBRID_GRAPH_STATUS_COMPLETE.md](https://vlab.noaa.gov/gitlab-community/NWS/Operations/NCEP/EMC/eib-mcp-rag-server/-/blob/main/docs/HYBRID_GRAPH_STATUS_COMPLETE.md)
- [SDD Framework Methodology](https://vlab.noaa.gov/gitlab-community/NWS/Operations/NCEP/EMC/eib-mcp-rag-server/-/blob/main/sdd_framework/methodology/spec_driven_design_core.md)
- [EE2 Compliance Standards](https://vlab.noaa.gov/gitlab-community/NWS/Operations/NCEP/EMC/eib-mcp-rag-server/-/blob/main/supported_repos/nws-hpc-standards/docs/standards.rst)

---

## Appendix C: Multi-Modal Proof of Concept - GFS v16 Flowchart Analysis

*The following analysis demonstrates the power of multi-modal AI comprehension applied to the GFS v16 Global Model Parallel Sequencing flowchart (Fig. 4.1). This is exactly the kind of visual understanding that Initiative #1 will systematize.*

![GFS v16 Global Model Parallel Sequencing Flowchart](https://vlab.noaa.gov/gitlab-community/NWS/Operations/NCEP/EMC/eib-mcp-rag-server/-/raw/main/docs/development/images/gfs_v16_parallel_sequencing.png)

*Figure: GFS v16 Schematic flow chart for operations - Source: Global Workflow Documentation*

---

### High-Level Architecture Insights

**Three Major Swim Lanes:**
1. **GDAS (left, green)** - Global Data Assimilation System
2. **Hybrid EnKF (center, light green)** - Ensemble Kalman Filter 
3. **GFS (right, blue)** - The forecast model itself

**Plus two vertical control systems:**
- **Workflow Manager** (yellow, right edge)
- **Configuration Manager** (yellow, far right)

---

### Job Dependency Chain (GDAS Lane)

```
prep → waveinit → waveprep → fcst → postN → wavepostsbs → wavepostpnt
         ↓
        anal → analcalc → analdiag
                  ↓
                gldas
                  ↓
        fcst → echgres → vrfy → arch
```

**Key observation**: The GDAS side feeds into the Hybrid EnKF AND cycles at +06 hours.

---

### Hybrid EnKF Data Flow

```
eobs → ediag → eupd → esfc → ecmn (ecenN metatask)
                 ↓
              efmn (efcsN) → epmn (eposN)
                              ↓
                           eamn (earcN)
```

**The "N" suffix** = metatask (runs multiple ensemble members in parallel)

---

### GFS Lane Dependencies

```
prep → anal → analcalc → fcst → wavepostsbs
         ↓                        wavepostbndpnt
      waveinit → waveprep         wavepostbndpntbll
                                  wavepostpnt
                                       ↓
                                    postN → vrfy → arch
                                             metpN
```

**Decision diamond**: "run GFS this cycle?" - determines if additional downstream jobs execute

---

### Critical Insights for MCP/RAG

1. **The `+06` cycle hour box** is the synchronization point between GDAS and GFS - this is why temporal awareness matters!

2. **Wave components** (`waveinit`, `waveprep`, `wavepost*`) run in both GDAS and GFS - these share code paths we should cross-reference in Neo4j.

3. **The `echgres` job** bridges forecast to verification - a common failure point.

4. **Metatasks (pink dashed boxes)** like `ecenN`, `efcsN`, `eposN`, `earcN` are ensemble parallelization - errors here cascade across all members.

5. **Dashed arrows** = optional dependencies - the system can degrade gracefully.

---

### What This Means for GraphRAG

If we ingested this diagram:
- **42 job nodes** could be created in Neo4j
- **~60 DEPENDS_ON relationships** from the arrows
- **3 BELONGS_TO_LANE relationships** (GDAS, EnKF, GFS)
- **Cross-lane links** where jobs feed each other

Then a query like *"What happens if `eupd` fails?"* could traverse:
```
eupd -[BLOCKS]-> esfc -[BLOCKS]-> ecmn -[BLOCKS]-> efmn -[BLOCKS]-> epmn
```

And the RAG would pull documentation for ALL affected downstream jobs, not just `eupd`.

**This single diagram encodes more operational knowledge than 50 pages of text.** That's why multi-modal ingestion is item #1 on our roadmap!

---

*"The measure of intelligence is the ability to change." — Albert Einstein*

*This system will not just answer questions. It will learn, adapt, and evolve with the operational needs of NOAA's weather forecasting mission.*
