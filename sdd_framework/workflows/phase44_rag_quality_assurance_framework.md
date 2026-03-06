# Phase 44: RAG Quality Assurance & Regression Framework

**Version**: 1.0.0
**Status**: Planned
**Created**: 2026-03-06
**Author**: AI Assistant + Terry McGuinness
**Dependency**: Phase 38 (data quality normalization), Phase 43 (health observability infrastructure)
**Archaeology**: Legacy capabilities from Phase 9 (metrics comparative analysis), Phase 22 (validation benchmarking subsystem), Phase 24G (benchmark validation)

---

## 1. Executive Summary

The MCP-RAG server can answer questions but has **no way to measure whether its answers are improving or degrading** as the knowledge base evolves. Phases 38-42 will add thousands of new documents and graph nodes — without a quality baseline and regression framework, we cannot tell if these additions help or hurt retrieval quality.

This phase builds the **measurement infrastructure** that transforms the expert system from "trust it works" to "prove it works":

1. **Ground truth test corpus** — 60 curated question/answer pairs across 6 categories
2. **Automated benchmark harness** — runs the corpus against the RAG pipeline and computes metrics
3. **Quality metrics** — Precision@K, Recall@K, MRR, answer relevance scoring
4. **Regression detection** — compare metric snapshots before/after knowledge base changes
5. **Quality dashboard** — structured output summarizing current quality state

### Motivation

Three legacy specs (Phase 9, Phase 22, Phase 24G) all designed quality measurement frameworks but none shipped. The core insight is the same across all three: **you can't optimize what you don't measure**. With Phases 38-42 about to reshape the knowledge base, this is the right time to establish a baseline.

### Actionable vs Notional

This phase is split into two tiers:

| Tier | What | Status |
|------|------|--------|
| **ACTIONABLE** | Ground truth corpus, benchmark script, metric computation, regression comparison | Can be built with current infrastructure |
| **NOTIONAL** | CI/CD integration, LLM-as-judge scoring, automated re-optimization, Gemini multimodal evaluation | Requires design decisions, API keys, or CI pipeline |

---

## 2. Problem Analysis

### 2.1 What We Cannot Currently Answer

- "Did adding 3,500 UFS Fortran files improve retrieval quality?"
- "Is the GraphRAG hybrid approach actually better than vector-only?"
- "Which question categories have the weakest answers?"
- "Did fixing the path prefix (Phase 38) improve cross-database join accuracy?"

### 2.2 Prior Art in This Codebase

| Spec | What It Designed | What Shipped |
|------|-----------------|-------------|
| Phase 9 (metrics) | 50-query corpus, 5 categories, Precision@K/MRR/NDCG | Nothing — design only |
| Phase 22 (benchmarking) | Ground truth suite, LLM-as-judge, baseline comparison | Nothing — design only |
| Phase 24G (benchmark) | Validation gates for GraphRAG, community quality scoring | Partial — community detection works, no measurement |

### 2.3 Available Infrastructure

- `search_documentation({ query })` — returns ranked results with similarity scores
- `get_code_context({ symbol })` — returns graph neighborhood with community summaries
- `search_architecture({ query })` — returns community-level matches
- `explain_with_context({ topic })` — returns RAG-powered explanation with citations
- Health check infrastructure (Phase 43) — can store quality snapshots alongside health data

---

## 3. Technical Specification

### 3.1 Ground Truth Test Corpus

**Location**: `mcp_server_node/test/benchmark/ground_truth.json`

Structure:
```json
{
  "version": "1.0.0",
  "created": "2026-03-06",
  "categories": {
    "code_structure": [
      {
        "id": "cs_001",
        "question": "What functions does exgfs_atmos_post.sh call?",
        "tool": "find_callers_callees",
        "tool_args": { "function_name": "exgfs_atmos_post" },
        "expected_results": ["wgrib2", "cnvgrib", "copygb2", "err_chk"],
        "expected_min_results": 3,
        "category": "code_structure"
      }
    ],
    "semantic_search": [...],
    "architecture": [...],
    "ee2_compliance": [...],
    "operational": [...],
    "cross_language": [...]
  }
}
```

**6 categories, 10 questions each = 60 test queries:**

| Category | Tests | Tools Exercised | What It Measures |
|----------|-------|----------------|-----------------|
| Code Structure | 10 | `find_callers_callees`, `find_dependencies`, `analyze_code_structure` | Graph completeness |
| Semantic Search | 10 | `search_documentation`, `explain_with_context` | Vector retrieval quality |
| Architecture | 10 | `search_architecture`, `get_code_context` | Community summary quality |
| EE2 Compliance | 10 | `analyze_ee2_compliance`, `search_ee2_standards` | Standards coverage |
| Operational | 10 | `get_operational_guidance`, `get_job_details` | Operational doc coverage |
| Cross-Language | 10 | `trace_full_execution_chain`, `trace_data_flow` | Cross-language graph linking |

### 3.2 Benchmark Harness

**Location**: `mcp_server_node/scripts/run_benchmark.js`

The harness:
1. Loads `ground_truth.json`
2. For each test query, calls the specified MCP tool via the server's internal API
3. Compares returned results against `expected_results`
4. Computes per-query and per-category metrics
5. Writes results to `mcp_server_node/test/benchmark/results/<timestamp>.json`
6. If a previous result exists, computes regression delta

```
$ node scripts/run_benchmark.js
[OK] Running 60 benchmark queries...
[OK] Code Structure:   P@5=0.72  R@5=0.65  MRR=0.81
[OK] Semantic Search:   P@5=0.68  R@5=0.71  MRR=0.74
[OK] Architecture:      P@5=0.55  R@5=0.48  MRR=0.62
[OK] EE2 Compliance:    P@5=0.82  R@5=0.79  MRR=0.88
[OK] Operational:       P@5=0.61  R@5=0.52  MRR=0.67
[OK] Cross-Language:    P@5=0.33  R@5=0.28  MRR=0.41
[OK] Overall:           P@5=0.62  R@5=0.57  MRR=0.69
[OK] Results saved to test/benchmark/results/2026-03-06T20-00-00.json
[WARN] Regression detected: Cross-Language P@5 dropped 0.05 since last run
```

### 3.3 Quality Metrics

| Metric | Definition | Why It Matters |
|--------|-----------|---------------|
| **Precision@K** | Of the top K results, how many are in the expected set | Measures noise in results |
| **Recall@K** | Of the expected results, how many appear in top K | Measures completeness |
| **MRR** (Mean Reciprocal Rank) | Average of 1/rank of first correct result | Measures how quickly the right answer appears |
| **Coverage** | % of test queries that return ≥1 expected result | Measures basic functionality |
| **Latency P50/P95** | Response time percentiles | Measures performance regression |

### 3.4 Regression Detection

**Trigger**: Compare latest benchmark results against the most recent previous run.

**Thresholds**:
```json
{
  "regression_threshold_pct": 5,
  "critical_threshold_pct": 15,
  "minimum_coverage_pct": 80
}
```

- **>5% drop** in any category metric → `[WARN]` flag
- **>15% drop** in any category metric → `[ERROR]` flag
- **Coverage <80%** in any category → `[ERROR]` flag

### 3.5 Quality Dashboard Tool

**New tool**: `get_quality_metrics` — reads latest benchmark results and returns formatted summary.

Parameters: `category` (optional filter), `compare` (boolean — show delta from previous run)

---

## 4. Implementation Steps

### ACTIONABLE (can be built now)

| Step | Name | Tag | Description |
|------|------|-----|-------------|
| 1 | Design ground truth corpus structure | design | Define JSON schema, categories, expected results format |
| 2 | Author Code Structure test queries | research | 10 queries with known-correct answers from Neo4j graph |
| 3 | Author Semantic Search test queries | research | 10 queries with known-correct documentation matches |
| 4 | Author Architecture test queries | research | 10 queries about system architecture with expected community matches |
| 5 | Author EE2 Compliance test queries | research | 10 queries about standards with known answers |
| 6 | Author Operational + Cross-Language queries | research | 20 queries covering operational guidance and cross-language tracing |
| 7 | Implement benchmark harness | implement | `run_benchmark.js` — load corpus, call tools, compute metrics, save results |
| 8 | Implement regression detection | implement | Compare consecutive benchmark runs, flag regressions above threshold |
| 9 | Implement `get_quality_metrics` tool | implement | New MCP tool that reads benchmark results and returns formatted summary |
| 10 | Run initial baseline | validate | Execute benchmark against current knowledge base state (pre-Phase 38) |
| 11 | Run post-Phase-38 comparison | validate | Re-run after Phase 38 data quality fixes, verify improvement |
| 12 | Update tool instruction files | document | Add `get_quality_metrics` to instruction files |

### NOTIONAL (requires design decisions or infrastructure)

| Item | Description | Prerequisite | Notes |
|------|-------------|-------------|-------|
| A | CI/CD integration | GitLab or GitHub Actions pipeline | Run benchmark on every PR that modifies ingestion scripts; block merge on regression |
| B | LLM-as-judge answer scoring | API key for evaluation LLM | Use a second LLM to score answer quality beyond keyword matching |
| C | Automated re-optimization | Phase 43 Item D (self-triggered re-ingestion) | If quality drops, automatically re-embed affected collections |
| D | Gemini multimodal evaluation | API key + Phase 8 (multimodal embeddings) | Evaluate diagram/visualization understanding quality |
| E | A/B testing framework | Multiple embedding model support | Compare retrieval quality across different embedding models side-by-side |
| F | NDCG metric | Graded relevance judgments | Requires per-result relevance grades (0/1/2/3) in ground truth — more effort to author |

---

## 5. Success Criteria

| Metric | Target |
|--------|--------|
| Ground truth corpus complete | 60 queries across 6 categories with expected results |
| Benchmark harness runs end-to-end | All 60 queries execute, metrics computed |
| Baseline snapshot captured | Pre-Phase-38 quality metrics recorded |
| Regression detection works | Intentionally degrade data, verify `[WARN]`/`[ERROR]` emitted |
| Quality tool accessible | `get_quality_metrics()` returns formatted summary via MCP |

---

## 6. Architecture Notes

### Tool Count Impact

| Change | Tools |
|--------|-------|
| New: `get_quality_metrics` | +1 |
| **Net new tools** | **+1 (50 → 51 with Phase 43)** |

### File Changes

| File | Changes |
|------|---------|
| `test/benchmark/ground_truth.json` | New: 60-query test corpus |
| `scripts/run_benchmark.js` | New: benchmark harness script |
| `test/benchmark/results/` | New directory: timestamped result snapshots |
| `src/tools/UtilityTools.js` | New `get_quality_metrics` tool |

### Relationship to Legacy Specs

This phase consolidates and replaces:
- `phase9_metrics_comparative_analysis_workflow.md` → corpus design, metrics definitions
- `phase22_validation_benchmarking_subsystem.md` → benchmark harness, LLM-as-judge concept
- `phase24g_benchmark_validation.md` → GraphRAG quality gates

After this phase executes, those three specs can be archived.

---

## 7. Implementation Order Context

Phase 44 should run **after** Phase 43 (health observability) and ideally **straddle** Phase 38:

```
Phase 38 (data quality) ─────→ Phase 39 (UFS Fortran) ─→ Phase 40-42
        │                              │
Phase 43 (self-diagnosis) ────→ Phase 44 (quality framework)
                                  │
                    Steps 1-6: author corpus (can start now)
                    Steps 7-9: implement harness (needs Phase 43 patterns)
                    Step 10: baseline (run BEFORE Phase 38)  ← critical timing
                    Step 11: comparison (run AFTER Phase 38)
```

**Critical timing note**: Step 10 (baseline) should be captured **before** Phase 38 changes data, so we can measure the improvement. Steps 1-6 (corpus authoring) can begin immediately while other phases are in progress.
