# SDD: Phase 24G - Benchmark & Validation

**Version:** 1.0.0  
**Created:** 2026-02-05  
**Author:** Terry McGuinness + AI Assistant  
**Status:** Prospectus (Q3 2026)  
**Dependencies:** Phase 24D (GGSR), Phase 24E (Communities), Phase 22 (Metrics Framework)

---

## 1. Executive Summary

Before deploying the agentic tool surface (24H), this phase validates that GraphRAG delivers measurable improvements over the baseline tool-assisted RAG system.

### Benchmark Question

> "Does GGSR + Community Summarization reduce queries-to-answer and improve accuracy compared to current search_documentation?"

---

## 2. Benchmark Design

### 2.1 Test Corpus

| Category | Example Query | Expected Answer Source |
|----------|--------------|----------------------|
| Local (specific) | "How does config.resources work?" | Node neighborhood |
| Global (holistic) | "What's the error handling strategy?" | Community summaries |
| Trace (path) | "What calls exgfs_atmos?" | Graph traversal |
| Cross-language | "What Fortran does forecast execute?" | 24F paths |
| Comparative | "Difference between HERA and WCOSS2?" | Multi-node context |

### 2.2 Systems Under Test

| System | Components | Description |
|--------|------------|-------------|
| **Baseline** | search_documentation (vector only) | Current tool-assisted RAG |
| **GGSR** | 24D GraphGuidedRetrieval | Speculative pre-fetch |
| **GGSR+Community** | 24D + 24E | Full GraphRAG |
| **GGSR+Community+Fortran** | 24D + 24E + 24F | Cross-language enabled |

### 2.3 Metrics

| Metric | Measurement Method |
|--------|-------------------|
| **Queries to complete answer** | Count tool calls in session |
| **Answer accuracy** | Human evaluation (1-5 scale) |
| **Answer completeness** | Did response include all expected content? |
| **Latency P50/P95** | End-to-end timing |
| **Token efficiency** | Context tokens used / total available |
| **Follow-up rate** | Did user ask clarifying questions? |

---

## 3. Implementation Phases

### 24G-1: Test Corpus Creation (Week 17)

**Steps:**
- [ ] Create 50 benchmark queries across categories
- [ ] Define expected answers for each query
- [ ] Tag queries with expected retrieval strategy

### 24G-2: Automated Benchmark Runner (Week 17)

**Steps:**
- [ ] Build benchmark harness that runs queries against each system
- [ ] Capture tool call counts, latencies, responses
- [ ] Store results in structured format for analysis

### 24G-3: Evaluation & Analysis (Week 18)

**Steps:**
- [ ] Human evaluation of answer quality
- [ ] Statistical comparison of metrics
- [ ] Identify failure cases and gaps
- [ ] Generate report with recommendations

---

## 4. Success Criteria

| Metric | Baseline | GGSR Target | Full Target |
|--------|----------|-------------|-------------|
| Queries per answer | 3-5 | 1-2 | 1 |
| Accuracy (1-5) | 3.0 | 3.5 | 4.0+ |
| Global query accuracy | 30% | 40% | 75%+ |
| P95 latency | 500ms | 800ms | 1000ms |

**Go/No-Go for 24H:** GGSR must meet targets before proceeding to agentic tools.

---

## 5. Dependency: Phase 22 Metrics Framework

This phase requires metrics infrastructure from Phase 22:
- Instrumentation for tool call counting
- Latency tracking
- User feedback collection mechanism

If Phase 22 is not complete, 24G will implement minimal benchmarking inline.

---

*Stub document - to be expanded with test corpus during implementation*
