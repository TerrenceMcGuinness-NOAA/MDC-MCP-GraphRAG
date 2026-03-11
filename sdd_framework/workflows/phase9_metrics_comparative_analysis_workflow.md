# Phase 9: RAG Metrics & Comparative Analysis Framework

**Version**: 1.0.0
**Date**: December 3, 2025
**Status**: Superseded by Phase 44 (RAG Quality Assurance & Regression Framework, v7.27.0)
**Priority**: High
**Dependencies**: Phase 8 (Multimodal Embeddings), Stable v7 baseline

## Executive Summary

Establish a rigorous metrics and evaluation framework to measure RAG system quality, enabling data-driven decisions about which features actually improve retrieval and generation quality. This addresses the **multidimensional optimization problem** of RAG development where intuition alone is insufficient.

## The Problem

### Current State: Flying Blind
- Multiple collection versions (v4, v5, v6, v7) with no comparative metrics
- No quantitative evidence of improvement between versions
- Feature additions based on assumption, not measurement
- Unknown which changes help vs. hurt retrieval quality

### The Multidimensional Challenge
RAG quality depends on many interacting factors:

```
┌─────────────────────────────────────────────────────────────────┐
│                RAG Quality Optimization Space                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Embedding Model ────┐                                          │
│  (MPNet, Gemini)     │                                          │
│                      │                                          │
│  Chunk Size ─────────┼───┐                                      │
│  (500, 1000, 2000)   │   │                                      │
│                      │   │    ┌──────────────────┐              │
│  Chunk Overlap ──────┼───┼───►│  Retrieval       │              │
│  (100, 200, 400)     │   │    │  Quality         │              │
│                      │   │    │  (Precision,     │              │
│  Semantic vs Fixed ──┼───┼───►│   Recall, MRR)   │              │
│  Chunking            │   │    └──────────────────┘              │
│                      │   │              │                       │
│  Graph Enrichment ───┼───┘              │                       │
│  (Neo4j context)     │                  ▼                       │
│                      │         ┌──────────────────┐             │
│  Reranking ──────────┤         │  Answer          │             │
│  (None, BM25, Cross) │         │  Quality         │             │
│                      │         │  (Accuracy,      │             │
│  Context Window ─────┤         │   Relevance)     │             │
│  (3, 5, 10 chunks)   │         └──────────────────┘             │
│                      │                                          │
│  Multimodal ─────────┘                                          │
│  (Text-only, +Images)                                           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Proposed Solution: Metrics-Driven Development

### Core Metrics Framework

#### 1. Retrieval Metrics (Automated)
| Metric | Description | Target |
|--------|-------------|--------|
| **Precision@K** | Relevant docs in top K results | ≥ 0.8 |
| **Recall@K** | Fraction of relevant docs retrieved | ≥ 0.7 |
| **MRR** | Mean Reciprocal Rank of first relevant | ≥ 0.6 |
| **NDCG** | Normalized Discounted Cumulative Gain | ≥ 0.7 |
| **Latency P50/P95** | Query response time | <500ms / <2s |

#### 2. Answer Quality Metrics (Requires Ground Truth)
| Metric | Description | Measurement |
|--------|-------------|-------------|
| **Factual Accuracy** | Correct information retrieved | Human eval + LLM judge |
| **Relevance Score** | Answer addresses the question | LLM-as-judge (1-5) |
| **Hallucination Rate** | Claims not in source docs | Automated detection |
| **Completeness** | All relevant info included | Human eval |

#### 3. System Health Metrics (Automated)
| Metric | Description | Target |
|--------|-------------|--------|
| **Embedding Throughput** | Docs/second during ingestion | ≥ 10/sec |
| **Query Throughput** | Queries/second | ≥ 50/sec |
| **Index Size** | Storage per 1K documents | < 50MB |
| **Cold Start Time** | Time to first query | < 30s |

## Evaluation Dataset: Global Workflow Test Suite

### Ground Truth Query Set
Create curated question-answer pairs with known correct retrievals:

```json
{
  "test_cases": [
    {
      "id": "gfs-001",
      "query": "How do I set up the GFS forecast on Hera?",
      "expected_docs": ["setup_gfs.md", "hera_config.rst"],
      "expected_answer_contains": ["module load", "EXPDIR", "workflow"],
      "category": "setup",
      "difficulty": "basic"
    },
    {
      "id": "ee2-001", 
      "query": "What environment variables are required for EE2 compliance?",
      "expected_docs": ["ee2_standards.rst", "environment_variables.rst"],
      "expected_answer_contains": ["DATAROOT", "COMROOT", "err_exit"],
      "category": "compliance",
      "difficulty": "intermediate"
    },
    {
      "id": "debug-001",
      "query": "Why did my GDAS analysis job fail with exit code 99?",
      "expected_docs": ["error_handling.md", "gdas_troubleshooting.rst"],
      "expected_answer_contains": ["err_chk", "postmsg", "log"],
      "category": "troubleshooting",
      "difficulty": "advanced"
    }
  ]
}
```

### Test Categories
- **Setup/Installation** (20 queries)
- **Configuration** (20 queries)
- **EE2 Compliance** (15 queries)
- **Troubleshooting** (15 queries)
- **Code Understanding** (15 queries)
- **Workflow Structure** (15 queries)

**Total: 100 curated test queries with ground truth**

## Comparative Analysis Framework

### A/B Testing Infrastructure

```
┌─────────────────────────────────────────────────────────────────┐
│                    Comparative Analysis Pipeline                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────┐         ┌─────────────────┐               │
│  │  Collection A   │         │  Collection B   │               │
│  │  (v7-baseline)  │         │  (v8-multimodal)│               │
│  └────────┬────────┘         └────────┬────────┘               │
│           │                           │                         │
│           ▼                           ▼                         │
│  ┌─────────────────────────────────────────────────┐           │
│  │              Test Query Runner                   │           │
│  │         (100 queries × 2 collections)           │           │
│  └─────────────────────────────────────────────────┘           │
│                          │                                      │
│                          ▼                                      │
│  ┌─────────────────────────────────────────────────┐           │
│  │              Metrics Calculator                  │           │
│  │   Precision, Recall, MRR, NDCG, Latency         │           │
│  └─────────────────────────────────────────────────┘           │
│                          │                                      │
│                          ▼                                      │
│  ┌─────────────────────────────────────────────────┐           │
│  │           Statistical Significance              │           │
│  │      (t-test, confidence intervals)             │           │
│  └─────────────────────────────────────────────────┘           │
│                          │                                      │
│                          ▼                                      │
│  ┌─────────────────────────────────────────────────┐           │
│  │              Results Dashboard                   │           │
│  │    (Tables, Charts, Recommendations)            │           │
│  └─────────────────────────────────────────────────┘           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Version Comparison Matrix

| Dimension | v5 | v6 | v7 | v8 | Winner |
|-----------|----|----|----|----|--------|
| Precision@5 | 0.62 | 0.71 | ? | ? | TBD |
| Recall@10 | 0.58 | 0.65 | ? | ? | TBD |
| MRR | 0.45 | 0.52 | ? | ? | TBD |
| Latency P50 | 120ms | 145ms | ? | ? | TBD |
| EE2 Accuracy | 0.70 | 0.78 | ? | ? | TBD |
| Code Search | 0.55 | 0.68 | ? | ? | TBD |

### Feature Ablation Study
Test impact of individual features:

| Feature | Enabled | Disabled | Delta | Significant? |
|---------|---------|----------|-------|--------------|
| Graph Enrichment | 0.75 | 0.68 | +0.07 | Yes (p<0.05) |
| Semantic Chunking | 0.72 | 0.65 | +0.07 | Yes (p<0.05) |
| Header Hierarchy | 0.71 | 0.69 | +0.02 | No (p=0.12) |
| Code Context | 0.80 | 0.72 | +0.08 | Yes (p<0.01) |

## Implementation Phases

### Phase 9.1: Test Dataset Creation (Week 1)
- [ ] Create 100 curated test queries with ground truth
- [ ] Categorize by topic, difficulty, query type
- [ ] Document expected retrievals and answer components
- [ ] Store in `test/evaluation/ground_truth.json`

### Phase 9.2: Metrics Infrastructure (Week 1-2)
- [ ] Create `MetricsCalculator.js` class
- [ ] Implement Precision@K, Recall@K, MRR, NDCG
- [ ] Add latency tracking to query pipeline
- [ ] Create metrics storage (SQLite or JSON)

### Phase 9.3: Evaluation Runner (Week 2)
- [ ] Create `EvaluationRunner.js` for batch testing
- [ ] Support multiple collection comparison
- [ ] Add statistical significance testing
- [ ] Generate comparison reports

### Phase 9.4: Dashboard & Reporting (Week 2-3)
- [ ] Create metrics visualization (charts/tables)
- [ ] Add regression detection (alert if metrics drop)
- [ ] Generate version comparison reports
- [ ] Document findings and recommendations

### Phase 9.5: CI/CD Integration (Week 3)
- [ ] Add evaluation to ingestion pipeline
- [ ] Block deployments if metrics regress
- [ ] Automate A/B testing for new collections
- [ ] Create metrics history tracking

## File Structure

```
mcp_server_node/
├── src/
│   └── evaluation/
│       ├── MetricsCalculator.js
│       ├── EvaluationRunner.js
│       ├── StatisticalTests.js
│       └── ReportGenerator.js
├── test/
│   └── evaluation/
│       ├── ground_truth.json        # 100 test queries
│       ├── expected_retrievals.json # Known-good docs
│       └── baseline_metrics.json    # v7 baseline scores
└── scripts/
    ├── run_evaluation.js
    ├── compare_collections.js
    └── generate_report.js
```

## Success Criteria

1. **Baseline Established**: v7 metrics documented as baseline
2. **Measurable Improvement**: v8 shows statistically significant gains
3. **Feature Validation**: Each feature's impact quantified
4. **Regression Prevention**: No new version worse than previous
5. **Decision Framework**: Clear criteria for accepting/rejecting changes

## Key Insights This Will Provide

1. **Does graph enrichment actually help?** (Quantified impact)
2. **Is semantic chunking worth the complexity?** (A/B test)
3. **Do multimodal embeddings improve retrieval?** (v7 vs v8)
4. **What chunk size is optimal for our content?** (Parameter sweep)
5. **Where does the system fail?** (Error analysis by category)

## Dependencies

- Phase 7: Stable v7 baseline (✅ in progress)
- Phase 8: Multimodal embeddings (for v8 comparison)
- Ground truth dataset: Human-curated test queries
- Time investment: ~3 weeks for full implementation

## References

- [RAGAS: RAG Assessment Framework](https://docs.ragas.io/)
- [MTEB: Massive Text Embedding Benchmark](https://huggingface.co/spaces/mteb/leaderboard)
- [LangChain Evaluation](https://docs.langchain.com/docs/use-cases/evaluation)
- Current collections: ChromaDB v7 (pending ingestion)
