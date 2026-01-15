# SDD: Phase 22 - Validation & Benchmarking Subsystem

**Description**: Establish a practical, repeatable validation framework to evaluate hybrid graph system effectiveness, MCP tool quality, and code changes. Provides empirical evidence for system improvements.

**Status**: PLANNING  
**Priority**: High  
**Prerequisite**: Phase 4C ISD/USD Architecture (complete), Phase 9 Metrics (partial)  
**Downstream Consumers**: [Phase 24 - Graph-Guided Speculative Retrieval](phase24_graph_guided_speculative_retrieval.md) (GGSR benchmarking)  
**Date**: January 5, 2026

---

## 1. Executive Summary

We currently have **no empirical way to validate** that the hybrid graph system (ChromaDB vectors + Neo4j relationships) improves results over vector-only search. This SDD establishes a validation subsystem that:

1. **Measures** retrieval quality with reproducible benchmarks
2. **Compares** hybrid vs. vector-only vs. graph-only approaches
3. **Tracks** quality changes across code updates
4. **Integrates** with our SDD workflow for automated regression testing

The design draws from AI community evaluation standards (MTEB, BEIR, RAGAS) while remaining practical for our single-developer, HPC-focused context.

---

## 2. Problem Statement

### 2.1 Current State: Flying Blind

| What We Have | What We Don't Know |
|--------------|-------------------|
| 14,968 documents in ChromaDB | Whether hybrid search beats vector-only |
| 86,189 relationships in Neo4j | Which queries benefit from graph enrichment |
| 34 MCP tools | If tools return relevant/accurate results |
| Multiple collection versions (v4-v7) | Which version performs best |

### 2.2 The Validation Gap

```
┌─────────────────────────────────────────────────────────────────────┐
│                    CURRENT DEVELOPMENT CYCLE                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   Code Change ───► "Looks Good" ───► Deploy ───► Hope It Works      │
│       │                                              │               │
│       │              NO FEEDBACK LOOP                │               │
│       └──────────────────────────────────────────────┘               │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                    DESIRED DEVELOPMENT CYCLE                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   Code Change ───► Benchmark ───► Compare ───► Evidence-Based       │
│       ▲               │             │          Decision              │
│       │               │             │              │                 │
│       │               ▼             ▼              │                 │
│       │          Ground Truth   Baseline           │                 │
│       │          Test Suite     Scores             │                 │
│       │                                            │                 │
│       └────────────────────────────────────────────┘                 │
│                     FEEDBACK LOOP                                    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.3 Why This Matters

Without validation:
- We can't justify hybrid complexity over simpler vector-only
- We can't detect regressions from code changes
- We can't prioritize which improvements matter most
- We can't demonstrate value to stakeholders

---

## 3. AI Community Benchmark Standards (Background)

### 3.1 Relevant Benchmarks

| Benchmark | Purpose | Applicability |
|-----------|---------|---------------|
| **MTEB** (Massive Text Embedding Benchmark) | Evaluate embedding models across tasks | Model selection only |
| **BEIR** (Benchmarking IR) | Domain-agnostic retrieval evaluation | Dataset format inspiration |
| **RAGAS** (RAG Assessment) | RAG pipeline quality metrics | Metric definitions |
| **LangChain Evals** | LLM application testing | Test harness patterns |
| **DeepEval** | Unit testing for LLM outputs | Assertion patterns |

### 3.2 Standard Metrics We'll Adopt

**Retrieval Quality:**
| Metric | Definition | Why It Matters |
|--------|------------|----------------|
| **Precision@K** | Relevant docs in top K / K | Are top results useful? |
| **Recall@K** | Relevant docs in top K / Total relevant | Did we find all relevant docs? |
| **MRR** | Mean Reciprocal Rank | How quickly do we find the first relevant result? |
| **NDCG@K** | Normalized Discounted Cumulative Gain | Are results in optimal order? |

**Answer Quality (LLM-as-Judge):**
| Metric | Definition | Why It Matters |
|--------|------------|----------------|
| **Faithfulness** | Answer supported by retrieved context | No hallucinations |
| **Relevance** | Answer addresses the query | Useful response |
| **Completeness** | All relevant info included | Thorough response |

### 3.3 What We WON'T Do (Practical Constraints)

| Standard Practice | Why We Skip It |
|-------------------|----------------|
| Large-scale crowdsourced annotation | Single developer, no budget |
| Multi-model evaluation ensemble | One embedding model (MPNet) |
| Continuous benchmark servers | Overkill for project scale |
| Statistical significance testing | Small test set, focus on trends |

---

## 4. Proposed Architecture

### 4.1 Subsystem Components

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    VALIDATION SUBSYSTEM                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────────────────┐    ┌─────────────────────┐                     │
│  │   GROUND TRUTH      │    │   TEST HARNESS      │                     │
│  │   TEST SUITE        │───►│                     │                     │
│  │                     │    │  • Query executor   │                     │
│  │  • Query + Expected │    │  • Mode switcher    │                     │
│  │  • Categories       │    │  • Result collector │                     │
│  │  • Difficulty       │    │                     │                     │
│  └─────────────────────┘    └──────────┬──────────┘                     │
│                                        │                                 │
│                                        ▼                                 │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                      EVALUATION MODES                              │  │
│  │                                                                    │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                │  │
│  │  │ VECTOR-ONLY │  │ GRAPH-ONLY  │  │   HYBRID    │                │  │
│  │  │             │  │             │  │             │                │  │
│  │  │ ChromaDB    │  │ Neo4j       │  │ ChromaDB +  │                │  │
│  │  │ similarity  │  │ traversal   │  │ Neo4j       │                │  │
│  │  │ search      │  │ queries     │  │ enrichment  │                │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘                │  │
│  │                                                                    │  │
│  └────────────────────────────┬──────────────────────────────────────┘  │
│                               │                                          │
│                               ▼                                          │
│  ┌─────────────────────┐    ┌─────────────────────┐                     │
│  │   METRIC CALCULATOR │───►│   REPORT GENERATOR  │                     │
│  │                     │    │                     │                     │
│  │  • Precision/Recall │    │  • Comparison tables│                     │
│  │  • MRR/NDCG         │    │  • Trend charts     │                     │
│  │  • LLM-as-Judge     │    │  • Regression flags │                     │
│  └─────────────────────┘    └─────────────────────┘                     │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Directory Structure

```
sdd_framework/
├── validation/                      # NEW - Validation subsystem
│   ├── README.md                    # Subsystem documentation
│   ├── ground_truth/                # Test cases with expected results
│   │   ├── test_suite.json          # Main test case file
│   │   ├── categories/              # Category-specific tests
│   │   │   ├── gfs_setup.json       # GFS workflow questions
│   │   │   ├── ee2_compliance.json  # EE2 standard questions
│   │   │   ├── hpc_operations.json  # Platform-specific questions
│   │   │   └── code_analysis.json   # Code structure questions
│   │   └── difficulty/              # By complexity
│   │       ├── basic.json           # Single-hop retrieval
│   │       ├── intermediate.json    # Multi-doc synthesis
│   │       └── advanced.json        # Graph traversal required
│   ├── harness/                     # Test execution code
│   │   ├── ValidationHarness.js     # Main test runner
│   │   ├── QueryExecutor.js         # Execute queries in different modes
│   │   ├── MetricCalculator.js      # Compute evaluation metrics
│   │   └── ReportGenerator.js       # Generate comparison reports
│   ├── baselines/                   # Stored baseline results
│   │   ├── v7_baseline_2026-01-05.json
│   │   └── latest.json → v7_baseline_2026-01-05.json
│   └── reports/                     # Generated evaluation reports
│       └── .gitkeep
```

---

## 5. Ground Truth Test Suite Design

### 5.1 Test Case Schema

```json
{
  "$schema": "validation_test_case_v1",
  "test_cases": [
    {
      "id": "gfs-setup-001",
      "query": "How do I set up the GFS forecast on Hera?",
      "category": "gfs_setup",
      "difficulty": "basic",
      "expected_retrieval": {
        "must_contain": [
          "setup_expt.py",
          "parm/config.base"
        ],
        "should_contain": [
          "machine-hera.config",
          "EXPDIR"
        ],
        "must_not_contain": [
          "obsolete_setup.sh"
        ]
      },
      "expected_answer": {
        "must_mention": ["module load", "EXPDIR", "workflow"],
        "factual_assertions": [
          "GFS setup requires sourcing environment",
          "Configuration files are in parm/ directory"
        ]
      },
      "metadata": {
        "author": "tmcguinness",
        "created": "2026-01-05",
        "validated_by_sme": false,
        "notes": "Basic single-hop retrieval test"
      }
    }
  ]
}
```

### 5.2 Category Distribution (Target: 100 Test Cases)

| Category | Count | Focus Area |
|----------|-------|------------|
| **gfs_setup** | 20 | Workflow setup, configuration |
| **ee2_compliance** | 20 | EE2 standards, error handling |
| **hpc_operations** | 20 | Platform-specific (Hera, WCOSS2, etc.) |
| **code_analysis** | 20 | Code structure, dependencies |
| **troubleshooting** | 20 | Error resolution, debugging |

### 5.3 Difficulty Levels

| Level | Definition | Example |
|-------|------------|---------|
| **Basic** | Single document retrieval, direct answer | "What is the GFS cycle length?" |
| **Intermediate** | Multi-document synthesis | "Compare GFS and GEFS configuration" |
| **Advanced** | Requires graph traversal + vector search | "What functions call `setup_expt` and what configs do they use?" |

### 5.4 Ground Truth Creation Strategy

**Phase 1: Bootstrap (Manual)**
- Developer creates 20 test cases from common support questions
- Uses actual user queries from past interactions
- Focus on questions we KNOW the answer to

**Phase 2: LLM-Assisted (Semi-automated)**
- Use Claude to generate candidate test cases from documentation
- Developer validates and corrects expected results
- Expand to 50 test cases

**Phase 3: Query Log Mining (Automated)**
- Log actual MCP tool queries in production
- Identify frequently asked question patterns
- Add top queries to test suite
- Target 100 test cases

---

## 6. Evaluation Modes

### 6.1 Vector-Only Mode

Query ChromaDB without Neo4j enrichment:

```javascript
async function vectorOnlySearch(query, k = 10) {
  const results = await chromaClient.query({
    collection: 'ee2-standards-v7',
    queryTexts: [query],
    nResults: k,
    // No graph enrichment
  });
  return results;
}
```

### 6.2 Graph-Only Mode

Query Neo4j relationships without vector similarity:

```javascript
async function graphOnlySearch(query, keywords) {
  // Extract entities from query
  const entities = extractEntities(query);
  
  // Traverse graph for related documents
  const cypher = `
    MATCH (n)-[r*1..3]-(related)
    WHERE n.name IN $entities
    RETURN DISTINCT related
    LIMIT 10
  `;
  return neo4jSession.run(cypher, { entities });
}
```

### 6.3 Hybrid Mode (Current Production)

Current `search_documentation` implementation:

```javascript
async function hybridSearch(query, k = 10) {
  // 1. Vector search for initial candidates
  const vectorResults = await vectorOnlySearch(query, k * 2);
  
  // 2. Graph enrichment for context expansion
  const enriched = await enrichWithGraph(vectorResults);
  
  // 3. Re-rank based on combined score
  return rerank(enriched, query, k);
}
```

### 6.4 Mode Comparison Matrix

For each test case, run all three modes and compare:

| Test ID | Vector P@5 | Graph P@5 | Hybrid P@5 | Winner |
|---------|------------|-----------|------------|--------|
| gfs-001 | 0.6 | 0.4 | 0.8 | Hybrid |
| ee2-001 | 0.8 | 0.2 | 0.8 | Tie (V/H) |
| code-001 | 0.4 | 0.8 | 0.9 | Hybrid |

---

## 7. Metric Implementation

### 7.1 Precision@K

```javascript
function precisionAtK(retrieved, relevant, k) {
  const topK = retrieved.slice(0, k);
  const relevantInTopK = topK.filter(doc => relevant.includes(doc.id));
  return relevantInTopK.length / k;
}
```

### 7.2 Recall@K

```javascript
function recallAtK(retrieved, relevant, k) {
  const topK = retrieved.slice(0, k);
  const relevantInTopK = topK.filter(doc => relevant.includes(doc.id));
  return relevantInTopK.length / relevant.length;
}
```

### 7.3 Mean Reciprocal Rank (MRR)

```javascript
function mrr(retrieved, relevant) {
  for (let i = 0; i < retrieved.length; i++) {
    if (relevant.includes(retrieved[i].id)) {
      return 1 / (i + 1);
    }
  }
  return 0;
}

function meanMRR(testResults) {
  const mrrs = testResults.map(r => mrr(r.retrieved, r.relevant));
  return mrrs.reduce((a, b) => a + b, 0) / mrrs.length;
}
```

### 7.4 LLM-as-Judge (Answer Quality)

```javascript
async function llmJudge(query, answer, context, metric) {
  const prompts = {
    faithfulness: `
      Given the context and answer, rate faithfulness (1-5):
      Does the answer only contain information from the context?
      
      Context: ${context}
      Answer: ${answer}
      
      Score (1-5):`,
    
    relevance: `
      Given the query and answer, rate relevance (1-5):
      Does the answer address the query?
      
      Query: ${query}
      Answer: ${answer}
      
      Score (1-5):`
  };
  
  // Use local LLM or API call
  const response = await llm.complete(prompts[metric]);
  return parseInt(response.trim());
}
```

---

## 8. Integration with SDD Workflows

### 8.1 Pre-Merge Validation Gate

Add validation step to ISD workflows that modify retrieval code:

```yaml
# In relevant SDD workflow
steps:
  - id: code_modification
    type: code_modification
    description: "Update hybrid search algorithm"
    
  - id: validation_gate    # NEW
    type: validation
    description: "Run benchmark suite"
    config:
      test_suite: "ground_truth/test_suite.json"
      baseline: "baselines/latest.json"
      fail_on_regression: true
      regression_threshold: 0.05  # 5% drop triggers failure
```

### 8.2 MCP Tool: `run_validation_suite`

New tool for on-demand validation:

```javascript
{
  name: "run_validation_suite",
  description: "Run validation benchmark against current system",
  parameters: {
    test_suite: {
      type: "string",
      description: "Path to test suite JSON",
      default: "validation/ground_truth/test_suite.json"
    },
    modes: {
      type: "array",
      items: { enum: ["vector", "graph", "hybrid"] },
      default: ["hybrid"]
    },
    compare_baseline: {
      type: "boolean",
      default: true
    }
  }
}
```

### 8.3 Baseline Management

```javascript
// After successful validation, optionally save as new baseline
async function saveBaseline(results, version) {
  const filename = `baselines/${version}_${date}.json`;
  await fs.writeFile(filename, JSON.stringify(results, null, 2));
  
  // Update symlink
  await fs.symlink(filename, 'baselines/latest.json');
}
```

---

## 9. Report Generation

### 9.1 Comparison Report Format

```markdown
# Validation Report: 2026-01-05

## Summary
- Test Suite: ground_truth/test_suite.json (100 cases)
- Baseline: v7_baseline_2026-01-01.json
- Current: v7.1 (commit abc123)

## Overall Metrics

| Metric | Baseline | Current | Delta | Status |
|--------|----------|---------|-------|--------|
| Precision@5 | 0.72 | 0.78 | +0.06 | ✅ IMPROVED |
| Recall@10 | 0.65 | 0.68 | +0.03 | ✅ IMPROVED |
| MRR | 0.58 | 0.55 | -0.03 | ⚠️ REGRESSION |
| Faithfulness | 4.2 | 4.3 | +0.1 | ✅ IMPROVED |

## Mode Comparison

| Mode | Precision@5 | Recall@10 | MRR | Best For |
|------|-------------|-----------|-----|----------|
| Vector | 0.65 | 0.60 | 0.52 | General queries |
| Graph | 0.45 | 0.70 | 0.40 | Code dependencies |
| Hybrid | 0.78 | 0.68 | 0.55 | Complex queries |

## Category Breakdown

| Category | Count | P@5 | Change |
|----------|-------|-----|--------|
| gfs_setup | 20 | 0.82 | +0.08 |
| ee2_compliance | 20 | 0.75 | +0.05 |
| hpc_operations | 20 | 0.80 | +0.02 |
| code_analysis | 20 | 0.70 | +0.10 |
| troubleshooting | 20 | 0.68 | -0.02 |

## Regressions (Require Investigation)

| Test ID | Baseline | Current | Notes |
|---------|----------|---------|-------|
| trouble-015 | 0.8 | 0.4 | Missing doc after v7 migration |
| code-008 | 0.6 | 0.4 | Graph relationship broken |

## Recommendations
1. Investigate MRR regression - first result quality dropped
2. Check code_analysis improvements - may over-prioritize code docs
3. Fix trouble-015: document was removed in v7 migration
```

---

## 10. Implementation Phases

### Phase 1: Foundation (Week 1)
- [ ] Create `sdd_framework/validation/` directory structure
- [ ] Define test case schema (JSON Schema)
- [ ] Create 20 bootstrap test cases manually
- [ ] Implement `ValidationHarness.js` skeleton

### Phase 2: Metrics (Week 2)
- [ ] Implement `MetricCalculator.js` (Precision, Recall, MRR)
- [ ] Implement `QueryExecutor.js` with mode switching
- [ ] Create baseline from current system state
- [ ] Generate first comparison report

### Phase 3: LLM Judge (Week 3)
- [ ] Implement LLM-as-judge for answer quality
- [ ] Add faithfulness and relevance scoring
- [ ] Expand test suite to 50 cases
- [ ] Validate scoring consistency

### Phase 4: Integration (Week 4)
- [ ] Create `run_validation_suite` MCP tool
- [ ] Add validation gate to ISD workflows
- [ ] Implement baseline management
- [ ] Document usage in copilot-instructions.md

### Phase 5: Expansion (Ongoing)
- [ ] Query log mining for new test cases
- [ ] Target 100 test cases
- [ ] Add category-specific benchmarks
- [ ] Trend analysis across releases

---

## 11. Success Criteria

### Minimum Viable Validation (Phase 2 Complete)
- [ ] 20+ ground truth test cases
- [ ] Automated metric calculation (P@K, R@K, MRR)
- [ ] Vector vs. Hybrid comparison report
- [ ] Baseline stored for regression detection

### Full Validation Subsystem (Phase 4 Complete)
- [ ] 50+ ground truth test cases
- [ ] LLM-as-judge for answer quality
- [ ] MCP tool for on-demand validation
- [ ] ISD workflow integration
- [ ] Regression alerts in CI/CD

### Production Quality (Phase 5+)
- [ ] 100+ ground truth test cases
- [ ] < 5% false positive regression alerts
- [ ] Query log-based test expansion
- [ ] Historical trend visualization

---

## 12. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Ground truth bias | Tests favor current implementation | External review, diverse query sources |
| Metric gaming | Optimize for metrics, not quality | Multiple metrics, LLM-as-judge |
| LLM judge inconsistency | Noisy quality scores | Average multiple judgments, calibration |
| Test maintenance burden | Tests become stale | Quarterly review, automated staleness detection |
| Baseline drift | Hard to compare across versions | Version-tagged baselines, changelog |

---

## 13. Open Questions

1. **LLM Provider for Judge**: Use Claude API, local Llama, or both?
2. **Test Case Ownership**: Who maintains ground truth as docs evolve?
3. **CI/CD Integration**: Run on every PR or nightly?
4. **Graph-Only Baseline**: Is pure graph search even meaningful as a comparison?

---

## 14. References

1. MTEB Benchmark: https://huggingface.co/spaces/mteb/leaderboard
2. BEIR Benchmark: https://github.com/beir-cellar/beir
3. RAGAS Framework: https://docs.ragas.io/
4. LangChain Evaluation: https://docs.langchain.com/docs/guides/evaluation
5. DeepEval: https://docs.deepeval.com/
6. Phase 9 Metrics Workflow: `phase9_metrics_comparative_analysis_workflow.md`

---

## Appendix A: Sample Test Cases (Bootstrap Set)

```json
{
  "test_cases": [
    {
      "id": "gfs-setup-001",
      "query": "How do I set up the GFS forecast on Hera?",
      "category": "gfs_setup",
      "difficulty": "basic",
      "expected_retrieval": {
        "must_contain": ["setup_expt.py", "config.base"],
        "should_contain": ["machine-hera"]
      }
    },
    {
      "id": "ee2-error-001",
      "query": "What is the correct way to handle errors in EE2 compliant scripts?",
      "category": "ee2_compliance",
      "difficulty": "basic",
      "expected_retrieval": {
        "must_contain": ["err_exit", "err_chk"],
        "should_contain": ["set -eu"]
      }
    },
    {
      "id": "code-deps-001",
      "query": "What modules does exglobal_forecast.py import?",
      "category": "code_analysis",
      "difficulty": "intermediate",
      "expected_retrieval": {
        "must_contain": ["exglobal_forecast.py"],
        "requires_graph": true
      }
    },
    {
      "id": "hpc-wcoss2-001",
      "query": "How do I load the GFS environment on WCOSS2?",
      "category": "hpc_operations",
      "difficulty": "basic",
      "expected_retrieval": {
        "must_contain": ["wcoss2", "module load"],
        "should_contain": ["machine-wcoss2"]
      }
    },
    {
      "id": "hybrid-001",
      "query": "What functions call setup_expt and what config files do they read?",
      "category": "code_analysis",
      "difficulty": "advanced",
      "expected_retrieval": {
        "requires_graph": true,
        "requires_vector": true,
        "notes": "Should demonstrate hybrid value"
      }
    }
  ]
}
```

---

## Appendix B: Metric Calculation Reference

### Precision@K Formula
$$P@K = \frac{|\{relevant\} \cap \{retrieved_{1..K}\}|}{K}$$

### Recall@K Formula
$$R@K = \frac{|\{relevant\} \cap \{retrieved_{1..K}\}|}{|\{relevant\}|}$$

### Mean Reciprocal Rank Formula
$$MRR = \frac{1}{|Q|} \sum_{i=1}^{|Q|} \frac{1}{rank_i}$$

Where $rank_i$ is the position of the first relevant document for query $i$.

### NDCG@K Formula
$$NDCG@K = \frac{DCG@K}{IDCG@K}$$

Where:
$$DCG@K = \sum_{i=1}^{K} \frac{2^{rel_i} - 1}{\log_2(i+1)}$$

---

*Document created: January 5, 2026*
*Author: T. McGuinness / Claude Opus 4.5*
*SDD Framework v5.0*
