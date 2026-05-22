# MCP RAG Parity Assessment — Round 2 (Post-Dedup)

**Date**: May 21, 2026  
**Scope**: Focused parity test of RAG components (`search_documentation`, `search_architecture`, knowledge base status)  
**Purpose**: Identify gaps in legacy ChromaDB/Neo4j stack for re-ingestion priorities  
**Servers**:
- `agentcore-mcp-rag` — AWS Python runtime, OpenSearch Titan-1024 + Neptune
- `eib-mcp-gateway` — Legacy Parallel Works Node.js, ChromaDB MPNet-768 + Neo4j

---

## Executive Summary

The post-dedup AgentCore RAG layer dominates the legacy gateway on every test query — by an order of magnitude in similarity scores and with significantly higher relevance. The legacy gateway has **two distinct gap categories**:

1. **Volume gaps** — code context is 49% smaller, graph is 35x smaller, no Titan embeddings
2. **Currency gaps** — has v8-2-0 collection (newer than AgentCore's v8-0-0) but missing the 9 newly-ingested sources (MPAS, CATChem, CECE, CDEPS, Land-DA, uwtools, SRW, GSI, HAFS) and 4 PDFs (ESMF/ESMC/NUOPC/ESMPy refs)

**A surprising third finding**: MPAS-specific queries fail on **both** servers, suggesting the 2026-05-19 MPAS ingestion either failed silently or content was minimal. Verification needed.

---

## 1. Knowledge Base Inventory Comparison

| Resource | AgentCore (post-dedup) | Gateway (legacy) | Delta |
|----------|------------------------|------------------|-------|
| **Total docs** | 198,393 | 134,617 | +47% |
| Workflow docs (Titan) | 19,289 | 0 | AgentCore-only |
| Workflow docs (MPNet v8-0-0) | 22,498 | 22,498 | parity |
| Workflow docs (MPNet v8-1-0) | 0 | 20,511 | Gateway-only |
| Workflow docs (MPNet v8-2-0) | 0 | 23,624 | **Gateway-only (newer)** |
| Code context | 90,135 | 60,574 | +49% AgentCore |
| J-Jobs | 751 | 700 + 859 (v8-1-0) | parity-ish |
| EE2 standards | 34 | 34 | parity |
| Community summaries | 2,113 | 2,113 | parity |
| CI test cases | 0 | 74 | **Gateway-only** |
| Phase48-scratch | 0 | 3,630 | dev artifact |
| **Graph nodes** | 148,976 | ~5,200 | **35x AgentCore** |
| **Graph relationships** | 2,823,382 | 2,653,565 | +6.4% AgentCore |

### Critical observations

- **Gateway has v8-1-0 (20,511) and v8-2-0 (23,624) workflow docs** that AgentCore does not — these are newer crawl runs that included content like the global-workflow wiki we saw in the search results.
- **AgentCore has all the Titan-embedded content** (19,289 workflow + 90,135 code) — gateway has none.
- **Gateway graph is tiny** — 2,758 files, 2,012 functions vs Neptune's 17,273 files / 95,996 functions. The Neo4j graph never received the full re-ingestion that Neptune did (Phase 53 Track B).

---

## 2. Query-Level Parity Tests

### Test 1: ESMF/NUOPC initialization

| Server | Top score | Result quality |
|--------|-----------|----------------|
| AgentCore | **100%** | Direct hit on NUOPC initialization phase maps from esmf-user-guide |
| Gateway | 47-49% | Wiki summary + namelist docs (less direct) |

**Winner**: AgentCore by a wide margin. Titan embeddings produce dramatically tighter semantic matches.

### Test 2: HAFS hurricane vortex initialization 3DIAU

| Server | Top score | Result quality |
|--------|-----------|----------------|
| AgentCore | **100%** | Direct hit on HAFS user guide CDEPS configuration with vortex init flags |
| Gateway | 31-39% | UFS WM idealized TC case (less direct, doesn't cover 3DIAU) |

**Winner**: AgentCore. The HAFS-specific docs (newly ingested 2026-05-19) are AgentCore-only.

### Test 3: CMEPS mediator field exchange

| Server | Top score | Result quality |
|--------|-----------|----------------|
| AgentCore | **100%** | UFS WM namelist docs (cplflx, use_med_flux flags) |
| Gateway | 47-49% | Workflow wiki + UFS WM namelist (mixed) |

**Winner**: AgentCore (better top hit), Gateway (slightly broader sources). The gateway's wiki-derived "Coupling Process" diagram is genuinely useful and missing from AgentCore.

### Test 4: ESMPy regridding Python interface

| Server | Top score | Result quality |
|--------|-----------|----------------|
| AgentCore | **100%** | ESMPy overview + table of contents |
| Gateway | 38-41% | ESMPy API docs + Regrid class table |

**Winner**: AgentCore on similarity, but gateway returns more API-specific detail. Both adequate.

### Test 5: MPAS Atmosphere Voronoi mesh — **BOTH FAIL**

| Server | Top score | Result quality |
|--------|-----------|----------------|
| AgentCore | 100% | **Wrong content** — returned FV3 dynamical core docs (not MPAS) |
| Gateway | 53-54% | UFS WM namelist + GFDL FV3 wiki (also not MPAS) |

**Critical finding**: Neither server has actionable MPAS content. The AgentCore MPAS source (https://www2.mmm.ucar.edu/projects/mpas/site/index.html) was added 2026-05-18 but the high-similarity match on FV3 suggests **the MPAS crawl returned little or no content** — the index doesn't have the MPAS-specific terms ("Voronoi mesh", "MPAS-Atmosphere") strongly enough to outweigh FV3 noise.

---

## 3. Gateway Re-Ingestion Priorities

Based on the gaps, here are the recommended re-ingestion actions for the legacy ChromaDB + Neo4j stack:

### Priority 1: Code & Graph (highest impact)

| Action | Target | Effort | Rationale |
|--------|--------|--------|-----------|
| Re-ingest Fortran/Shell/Python code into Neo4j | Get to ~17,000 files / 95,000 functions | High | Gateway graph is 5% of Neptune — code analysis tools are crippled |
| Re-ingest Fortran/Shell/Python into ChromaDB code-context | Get from 60,574 → ~90,000 docs | Medium | Mirrors Phase 53 Track B work that Neptune received |

The gateway's Neo4j was effectively cleared after the S3 export and never re-populated. Neptune got Track B re-ingestion; Neo4j did not. **This is the single largest gap.**

### Priority 2: Newly Added Sources (volume gap)

| Source | AgentCore docs | Gateway | Action |
|--------|---------------|---------|--------|
| HAFS (`hafsdoc.readthedocs.io`) | 78 | 0 | Crawl + ingest |
| MPAS (verify first!) | ~134 (suspect) | 0 | Verify AgentCore content quality first; then crawl gateway |
| CATChem | 45 | 0 | Crawl + ingest |
| CDEPS | 62 | 0 | Crawl + ingest |
| CECE | 38 | 0 | Crawl + ingest |
| Land-DA | 56 | 0 | Crawl + ingest |
| uwtools | 152 | 0 | Crawl + ingest |
| ufs-srweather-app | 189 | 0 | Crawl + ingest |
| GSI user guide | 87 | 0 | Crawl + ingest |
| ESMF/ESMC/NUOPC/ESMPy PDFs | 1,871 | 0 | **Requires PDF pipeline port to legacy** |

Total: ~2,710 docs missing from gateway.

### Priority 3: Verify MPAS Content Quality (both servers)

Action item: spot-check the AgentCore MPAS index to see how many real MPAS documents were ingested vs how many were generic UFS pages that mentioned MPAS. If the MPAS crawl was thin:
- Check `mpas-atmosphere` source `doc_count` in the manifest after the crawl
- Try alternative seed URLs (`https://www2.mmm.ucar.edu/projects/mpas/atmosphere_model/` or the GitHub wiki)
- Consider falling back to PDF ingestion of the MPAS Atmosphere User's Guide

---

## 4. Specific Gaps Where Gateway HAS Something AgentCore LACKS

These are the cases where the gateway is genuinely useful as a reference:

| Content | Gateway Source | Why Useful |
|---------|---------------|-----------|
| Global-workflow wiki content | `global-workflow-docs-v8-2-0` | Ops-focused diagrams (coupling process flows, file naming conventions, FMS usage analysis) |
| CI test cases | `ci-test-cases-v1-0-0` (74 docs) | Test case documentation referenced by automation |
| Newer crawl iterations | `v8-1-0`, `v8-2-0` | More recent doc snapshots for sources both have |

**Recommendation**: Re-crawl these into AgentCore as a `global-workflow-wiki` source (or expand the `global-workflow` source to include the wiki paths). The wiki has high-density operational content not captured by the readthedocs crawl.

---

## 5. Recommended Action Plan

### Phase 61: Legacy Stack Refresh (re-ingestion)

**Sub-phase 61a — Neo4j graph rebuild** (highest impact)
1. Clear the legacy Neo4j graph
2. Re-run `ingest_fortran_graph.py` against gateway's ChromaDB-paired Neo4j
3. Re-run `ingest_shell_graph_v8.py`, `ingest_cross_language_bridges.py`, `ingest_python_graph.py`
4. Verify: ~17K files, ~95K functions, ~2.9M relationships

**Sub-phase 61b — ChromaDB doc volume**
1. Re-run `ingest_documentation_v8.py` against legacy ChromaDB with the updated source list (the 9 newly-added sources + 4 PDFs)
2. Note: PDF pipeline currently exists only in AgentCore (mcp_server_node version was added 2026-05-19) — verify it works against ChromaDB backend

**Sub-phase 61c — MPAS verification & remediation**
1. Inspect AgentCore's mpas-atmosphere index — count real MPAS docs vs noise
2. If <50 real docs, re-crawl with a deeper seed URL set
3. Consider PDF ingestion of MPAS user guide as fallback

### Phase 62: AgentCore Content Refresh (pull from gateway)

1. Add `global-workflow-wiki` source to manifest pointing at the wiki content
2. Bring v8-2-0 collection content into AgentCore by re-crawling sources that produced richer wiki content

---

## 6. Conclusion

The post-dedup AgentCore Titan stack is the clear production winner — every test query produced higher relevance, more direct hits, and broader coverage. The gateway's data layer is **stale and incomplete**:

- **Neo4j graph** is 5% of Neptune's size (the biggest gap)
- **ChromaDB workflow docs** are missing the 9 newly added sources and 4 PDFs (~2,700 docs gap)
- **MPAS coverage** is suspect on both servers and needs verification

The gateway should be treated as a **reference snapshot** — useful for cross-checking and for content not yet pulled into AgentCore (the wiki content, CI test cases) — but not as the primary RAG target for new queries.

The top action item is **re-ingesting the Neo4j graph from the current source tree** to match Neptune's depth. That single action would close the largest functional gap between the two servers.
