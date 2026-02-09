# SDD: Phase 28 - Immediate GraphRAG Acceleration

**Version:** 1.0.0  
**Created:** 2026-02-09  
**Author:** Terry McGuinness + AI Assistants  
**Status:** Complete  
**Execution Mode:** USD (Unsupervised Development)  
**Accelerates:** Phase 24A, Phase 24F-1, Phase 24H  

---

## 1. Executive Summary

The Neo4j graph reached critical density (485K+ relationships) from Phase 10 Fortran ingestion and Phase 27 J-Job enhancements, but three capabilities remained unwired. Phase 28 consolidates immediate acceleration work that unblocks Phase 24 GGSR without waiting for the full Q2 2026 timeline.

**Key Innovation:** Build foundational GGSR traversal infrastructure now — weighted Cypher queries, Fortran weight integration, and graph-to-vector enrichment — so Phase 24A-D can consume production-ready primitives.

---

## 2. Problem Statement

| Gap | Current State | Target State |
|-----|---------------|--------------|
| No GGSR traversal prototypes | Phase 24A defines patterns, none implemented | Validated 1-hop/2-hop weighted Cypher queries |
| Fortran CALLS/USES not weighted | 357K relationships in Neo4j, unweighted traversal only | Weighted traversal with CALLS=1.0, USES=0.7 scores |
| enrichGraphResults in 1/5 tools | Only `find_env_dependencies` has graph-to-vector enrichment | All 5 CodeAnalysisTools enriched |

---

## 3. Implementation

### Phase 28A: Cypher Traversal Query Prototypes for GGSR

**Deliverable:** `mcp_server_node/src/graphrag/GGSRTraversalPrototypes.js`

**Module provides:**
- `oneHopNeighborhood(entityName, options)` — 1-hop weighted traversal
- `twoHopNeighborhood(entityName, options)` — 2-hop with hop decay (0.5×)
- `fortranWeightedTraversal(entityName, maxDepth)` — Fortran CALLS/USES weighted chain
- Static `getWeightMatrix()` and `getHopDecay()` accessors

**Weight Matrix (23 relationship types — full Neo4j coverage):**
```
CALLS=1.0, EXECUTES=1.0, SOURCES=0.95, INVOKES=0.9, CALLED_BY=0.9,
DEPENDS_ON=0.8, DEPENDS_ON_ENV=0.8, IMPORTS=0.7, USES=0.7, INHERITS=0.7,
DEFINES=0.65, EXPORTS=0.6, DOC_REFERENCES=0.6, DOC_DESCRIBES=0.55,
HAS_METHOD=0.5, CONTAINS=0.5, SETS=0.5, SAME_DIRECTORY=0.4,
BUILT_BY=0.35, BUILD_ORCHESTRATES=0.35, AUTHORED=0.3, AUTHORED_BY=0.3,
CONTRIBUTED_TO=0.3
```

**Latency Target:** <100ms per traversal query

### Phase 28B: Wire Weighted Traversal into trace_execution_path for GGSR

**Changes to `CodeAnalysisTools.js`:**
- Added `include_weights` boolean parameter to `trace_execution_path` tool schema (default: `true`)
- Fortran entities: full `fortranWeightedTraversal()` with CALLS/USES chains
- Shell/generic entities: `oneHopNeighborhood()` with weighted scoring via `scoreResults()` + `formatWeightedTable()`
- Reports latency and <100ms target compliance

### Phase 28D: Wire GGSR Weighted Traversal into All 5 CodeAnalysisTools

**GGSR wired into every CodeAnalysisTool:**
- `analyze_code_structure` — 1-hop GGSR neighborhood for structural entities
- `find_dependencies` — 2-hop GGSR neighborhood for dependency graph exploration
- `trace_execution_path` — Fortran weighted traversal + generic 1-hop for shell/Python
- `find_callers_callees` — GGSR scoring of caller/callee results by relationship type
- `find_env_dependencies` — 1-hop GGSR neighborhood for environment variable entities

**Helper methods added to `GGSRTraversalPrototypes.js`:**
- `scoreResults(results)` — tool-agnostic GGSR scoring for any relationship results
- `formatWeightedTable(scored, options)` — formatted markdown table output
- `_normalizeEntityName(name)` — strips file extensions before Neo4j regex matching

### Phase 28C: Wire enrichGraphResults into Remaining 4 CodeAnalysisTools

**Pattern (consistent across all 4 tools):**
```javascript
try {
  const keyEntities = /* extract top entities from graph results */;
  if (keyEntities.length > 0) {
    const enrichment = await this.dataAccess.enrichGraphResults(keyEntities, {
      collection: 'code-with-context-v8-0-0',
      nResultsPerQuery: 1,
      maxIdentifiers: 8
    });
    if (enrichment.size > 0) {
      result += `\n## Semantic Context\n`;
      // ... render enrichment snippets
    }
  }
} catch (enrichError) {
  console.error('[WARN] Vector enrichment failed:', enrichError.message);
}
```

**Tools updated:**
- [x] `analyze_code_structure` — enriches key function names
- [x] `find_dependencies` — enriches target module
- [x] `trace_execution_path` — enriches call chain entities
- [x] `find_callers_callees` — enriches callers and callees
- [x] `find_env_dependencies` — already had enrichment (existing)

---

## 4. Files Changed

| File | Change |
|------|--------|
| `mcp_server_node/src/graphrag/GGSRTraversalPrototypes.js` | **NEW** — GGSR traversal module with 23-type weight matrix, `scoreResults()`, `formatWeightedTable()`, `_normalizeEntityName()` |
| `mcp_server_node/src/tools/CodeAnalysisTools.js` | Import GGSR, init in constructor, add `include_weights` param, GGSR weighted traversal in all 5 tools, enrichment in all 5 tools |

---

## 5. Dependencies

| Dependency | Status | Required For |
|------------|--------|--------------|
| Phase 10 (Fortran call tree ingestion) | ✅ Complete | 485K relationships in Neo4j |
| Phase 27A-E (J-Job RAG enhancement) | ✅ Complete | MPNet embeddings in ChromaDB |
| ChromaDB service | Runtime | Graph-to-vector enrichment |
| Neo4j service | Runtime | All graph traversal |

---

## 6. Roadmap Alignment

```
ADVANCED_FUTURE_WORK.md §3  ──►  Phase 24 SDD  ──►  Phase 28 (this)
(True GraphRAG Vision)          (GGSR Q2 2026)      (Acceleration, immediate)
```

**Novel Contribution:** Phase 28 was not in original Phase 24 roadmap. It extracts and implements foundational primitives (traversal queries, weight matrix, enrichment wiring) that Phase 24A-D will consume as production-ready infrastructure rather than building from scratch.

---

## 7. Validation

- [x] Syntax validation: `node -c` passes on both files
- [x] Unit tests: 7/19 passed, 10 failed, 2 skipped — **no regressions** (identical to pre-Phase 28 baseline)
- [x] Integration: All 5 CodeAnalysisTools validated with GGSR weighted traversal against live Neo4j
- [x] Latency benchmark: All traversals <100ms on 485K relationship graph (1-hop: 82ms, 2-hop: 58ms, Fortran: 85ms)
- [x] GGSR present in:
  - `find_dependencies("exglobal_forecast.py")`: GGSR ✅ | Semantic ✅
  - `find_callers_callees("UFS_init")`: GGSR ✅ | Semantic ✅
  - `analyze_code_structure("scripts/exglobal_forecast.py")`: GGSR ✅
  - `trace_execution_path("atms_spatial_average")`: GGSR ✅ (Fortran weighted)
  - `find_env_dependencies("HOMEgfs")`: GGSR ✅ | Semantic ✅
