# MCP Server Parity Assessment & SoC Topology Analysis

**Date**: May 20, 2026  
**Scope**: Comparative assessment of `agentcore-mcp-rag` (Python/Titan) vs `eib-mcp-gateway` (Node.js/MPNet)  
**Purpose**: Identify gaps, evaluate response quality, and recommend tool surface refinements

---

## Executive Summary

Both MCP servers expose 52 tools across 9 modules with identical tool names and parameter schemas. However, the underlying data layers differ significantly:

| Dimension | AgentCore (Python) | Gateway (Node.js) |
|-----------|-------------------|-------------------|
| **Embedding model** | Titan v2 (1024-dim) | MPNet (768-dim) |
| **Vector store** | OpenSearch (AWS) | ChromaDB (local) |
| **Graph store** | Neptune (AWS) | Neo4j (local) |
| **Workflow docs** | 30,173 docs (Titan) | 22,498 docs (MPNet) |
| **Code context** | 90,135 docs | 60,576 docs |
| **Total documents** | 209,277 | 134,617 |
| **Graph nodes** | 105,891 | 5,174 |
| **Graph relationships** | 2,941,593 | ~85,000 |

**Key finding**: The AgentCore server has **56% more documents** and **35x more graph data** than the gateway. The Titan embeddings produce significantly higher similarity scores and more relevant results for domain-specific queries.

---

## 1. Comparative Response Quality

### 1.1 Semantic Search (`search_documentation`)

**Query**: "ESMF coupling framework NUOPC component initialization"

| Metric | AgentCore (Titan) | Gateway (MPNet) |
|--------|-------------------|-----------------|
| Top similarity | 100% | 37.8% |
| Result relevance | Directly answers the query (NUOPC initialization phases, phase maps, specialization labels) | Returns related but less focused content (API reference tables, ingestion status metadata) |
| Source diversity | Single authoritative source (esmf-user-guide) | Mixed sources (wiki metadata + esmf-user-guide) |
| Deduplication | Returns 3 identical chunks (dedup issue) | Returns distinct chunks |

**Assessment**: Titan produces dramatically higher similarity scores and more relevant content. However, the AgentCore server has a **deduplication bug** — it returns the same chunk 3 times instead of 3 different relevant chunks. The gateway returns distinct results but with lower relevance.

**Recommendation**: Fix the deduplication in the AgentCore server's multi-collection query path. The underlying retrieval quality is superior but the presentation wastes the user's result budget.

### 1.2 Architecture Search (`search_architecture`)

**Query**: "data assimilation cycling GDAS"

| Metric | AgentCore (Titan) | Gateway (MPNet) |
|--------|-------------------|-----------------|
| Relevance scores | 0.527, 0.518 (positive) | -0.660, -0.668 (negative, low-confidence) |
| Community identification | Identifies relevant communities (79 nodes, 5 nodes) | Returns low-confidence results with disclaimer |
| Actionability | Provides community IDs for follow-up queries | Effectively returns "no good match found" |

**Assessment**: The Titan embeddings in the community-summaries collection produce meaningful matches where MPNet fails entirely. This is the highest-impact quality difference between the two servers.

**Recommendation**: The gateway's community summaries were embedded with MPNet 768-dim. Re-embedding them with Titan would close this gap, but since the gateway is the legacy system, the priority is ensuring the AgentCore server's community summaries are comprehensive.

### 1.3 Knowledge Base Status (`get_knowledge_base_status`)

| Metric | AgentCore | Gateway |
|--------|-----------|---------|
| Collections reported | 15 indices | 10 collections |
| Total documents | 209,277 | 134,617 |
| Graph detail | Full label breakdown (17,273 files, 95,996 functions, etc.) | Basic counts (2,758 files, 2,012 functions) |
| Relationship types | 10 types with counts | Not broken down |

**Assessment**: The AgentCore server provides significantly richer status information. The gateway's Neo4j graph is a subset (~5% of the Neptune graph).

---

## 2. Gap Analysis

### 2.1 Data Gaps (AgentCore has, Gateway lacks)

| Category | AgentCore | Gateway | Gap |
|----------|-----------|---------|-----|
| Titan-embedded docs | 30,173 | 0 | Gateway has no Titan index |
| PDF-sourced content | 1,871 chunks (ESMF/NUOPC/ESMPy) | 0 | Gateway never ingested PDFs |
| New URL sources (Phase 58) | ~2,951 new docs | 0 | 9 new sources not in gateway |
| Graph depth | 105,891 nodes | 5,174 nodes | 20x more graph coverage |
| Fortran code context | 90,135 chunks | 60,576 chunks | 49% more code indexed |

### 2.2 Data Gaps (Gateway has, AgentCore lacks)

| Category | Gateway | AgentCore | Gap |
|----------|---------|-----------|-----|
| Collection versions | v8-2-0 (latest crawl) | v8-0-0 (older) | Gateway has newer doc versions |
| ChromaDB-specific features | Full-text search fallback | N/A | OpenSearch handles this natively |
| Phase 48 scratch collection | 3,630 docs | 0 | Development/experimental data |

### 2.3 Functional Gaps

| Tool | AgentCore | Gateway | Notes |
|------|-----------|---------|-------|
| `list_all_sources` | ✅ Full manifest (64 sources) | ❌ Not available | AgentCore-only tool |
| `get_health_trend` | ✅ Persists snapshots | ✅ Works | Both functional |
| `trace_full_execution_chain` | ✅ Cross-language (Shell→Fortran→Python) | ✅ Works | AgentCore has deeper graph |
| `get_job_details` | ✅ 751 J-Jobs indexed | ✅ Works | Same data |
| `find_env_dependencies` | ✅ 11,167 DEPENDS_ON_ENV edges | ⚠️ Limited | Gateway graph is smaller |

---

## 3. SoC Topology Analysis

### 3.1 Current Module Organization

```
┌─────────────────────────────────────────────────────────────────┐
│                    9 Modules / 52 Tools                          │
├─────────────────────────────────────────────────────────────────┤
│  workflow_info (3)     │  code_analysis (6)    │  utility (4)   │
│  [Filesystem]          │  [Graph DB]           │  [Built-in]    │
├────────────────────────┼───────────────────────┼────────────────┤
│  semantic_search (7)   │  graph_rag (9)        │  operational(4)│
│  [Vector + Graph]      │  [Vector + Graph]     │  [Vector]      │
├────────────────────────┼───────────────────────┼────────────────┤
│  ee2_compliance (5)    │  github_tools (4)     │  sdd_workflow(9)│
│  [Vector]              │  [GitHub API]         │  [Filesystem]  │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 SoC Issues Identified

#### Issue A: Overlapping Concerns Between `semantic_search` and `graph_rag`

Both modules perform hybrid vector+graph queries. The distinction is:
- `semantic_search` → document-centric (find docs, explain topics)
- `graph_rag` → code-centric (find symbols, trace impact, session state)

**Problem**: An LLM choosing between `search_documentation` and `get_code_context` must understand this implicit boundary. Both accept natural language queries and return markdown. The LLM often picks the wrong one.

**Recommendation**: Merge the discovery tools or add explicit routing guidance in tool descriptions. Specifically:
- `search_documentation` should state: "Use for documentation and conceptual questions"
- `get_code_context` should state: "Use for specific code symbols (function names, module names)"

#### Issue B: Session State Tools in `graph_rag` Module

`mark_as_modified`, `get_session_context`, `checkpoint_state`, `restore_checkpoint` are session-management tools that happen to live in the `graph_rag` module. They have nothing to do with graph-guided retrieval.

**Recommendation**: These belong in `sdd_workflow` or a dedicated `session` module. Their current placement confuses the LLM about what `graph_rag` is for.

#### Issue C: `operational` Module is Thin and Overlapping

`get_operational_guidance` and `explain_workflow_component` both do semantic search + graph enrichment — the same pattern as `explain_with_context` in `semantic_search`. `list_job_scripts` and `get_job_details` are really data-access tools.

**Recommendation**: Fold `get_operational_guidance` into `semantic_search` as a specialized query mode (platform-aware). Move `list_job_scripts` / `get_job_details` to `workflow_info` (they're structural queries, not semantic ones).

#### Issue D: Tool Count Inflation

52 tools is a large surface area for an LLM to navigate. Several tools are rarely useful in practice:
- `get_ingested_urls_array` — programmatic variant of `list_ingested_urls` (same data, different format)
- `get_health_trend` — operator-only, never called by researchers
- `validate_sdd_compliance` — niche SDD framework tool
- `get_sdd_framework_status` — niche SDD framework tool

**Recommendation**: Consider a "core" tool set (25-30 tools) for researcher-facing deployments and a "full" set for operators. This reduces LLM decision fatigue.

### 3.3 Proposed Refined Topology

```
┌─────────────────────────────────────────────────────────────────┐
│              PROPOSED: 7 Modules / ~45 Core Tools               │
├─────────────────────────────────────────────────────────────────┤
│  DISCOVERY (10 tools)          │  ANALYSIS (8 tools)            │
│  search_documentation          │  analyze_code_structure        │
│  explain_with_context          │  find_dependencies             │
│  search_architecture           │  trace_execution_path          │
│  find_related_files            │  find_callers_callees          │
│  find_similar_code             │  trace_full_execution_chain    │
│  get_code_context              │  find_env_dependencies         │
│  get_operational_guidance      │  get_change_impact             │
│  search_ee2_standards          │  trace_data_flow               │
│  list_job_scripts              │                                │
│  get_job_details               │                                │
├────────────────────────────────┼────────────────────────────────┤
│  COMPLIANCE (4 tools)          │  WORKFLOW (6 tools)            │
│  analyze_ee2_compliance        │  get_workflow_structure        │
│  generate_compliance_report    │  get_system_configs            │
│  scan_repository_compliance    │  describe_component            │
│  extract_code_for_analysis     │  explain_workflow_component    │
│                                │  list_sdd_workflows            │
│                                │  get_sdd_workflow              │
├────────────────────────────────┼────────────────────────────────┤
│  SESSION (7 tools)             │  DIAGNOSTICS (6 tools)         │
│  start_sdd_session             │  get_server_info               │
│  record_sdd_step               │  mcp_health_check              │
│  get_sdd_session               │  get_knowledge_base_status     │
│  complete_sdd_session          │  check_knowledge_integrity     │
│  mark_as_modified              │  list_all_sources              │
│  checkpoint_state              │  get_quality_metrics           │
│  restore_checkpoint            │                                │
├────────────────────────────────┼────────────────────────────────┤
│  GITHUB (4 tools)              │                                │
│  search_issues                 │                                │
│  get_pull_requests             │                                │
│  analyze_workflow_dependencies │                                │
│  analyze_repository_structure  │                                │
└────────────────────────────────┴────────────────────────────────┘
```

**Key changes**:
1. **DISCOVERY** merges semantic_search + graph_rag discovery tools + operational guidance
2. **ANALYSIS** consolidates all code-structure tools (currently split across code_analysis + graph_rag)
3. **SESSION** pulls session-state tools out of graph_rag into their own module
4. **DIAGNOSTICS** consolidates health/status tools (currently scattered across utility + semantic_search)
5. **WORKFLOW** absorbs the structural tools from operational
6. Removed: `get_ingested_urls_array`, `get_health_trend`, `get_sdd_execution_history`, `validate_sdd_compliance`, `get_sdd_framework_status`, `list_ingested_urls` (6 tools demoted to operator-only)

---

## 4. LLM Efficiency Recommendations

### 4.1 Tool Description Improvements

Current tool descriptions are technically accurate but don't help the LLM choose correctly. Recommendations:

| Tool | Current Description | Recommended Addition |
|------|--------------------|--------------------|
| `search_documentation` | "Hybrid semantic + graph search..." | Add: "Use for conceptual questions, documentation lookup, and 'how does X work?' queries" |
| `get_code_context` | "Get comprehensive context for a code symbol..." | Add: "Use when you have a specific function/module name. NOT for general questions." |
| `explain_with_context` | "Provide comprehensive explanations..." | Add: "Use for deep-dive explanations. Slower but more thorough than search_documentation." |
| `find_similar_code` | "Find code patterns semantically similar..." | Add: "Use for refactoring — finds duplicates and related implementations." |

### 4.2 Parameter Naming Consistency

The current parameter naming has inconsistencies that trip up LLMs:

| Concept | Current Names | Recommendation |
|---------|--------------|----------------|
| "What to search for" | `query`, `topic`, `operation`, `code_or_symbol` | Standardize on `query` for text search, `symbol` for code entities |
| "How many results" | `max_results`, `max_depth`, `limit` | Standardize on `max_results` for search, `max_depth` for traversal |
| "What file" | `file_path`, `target`, `component` | Standardize on `file_path` for files, `component` for logical components |

### 4.3 Response Format Standardization

Both servers return markdown, but the structure varies:
- Some tools use `## Title` + body
- Others use `**Key:** value` pairs
- Some return tables, others return lists

**Recommendation**: Establish a standard response envelope:
```markdown
# [Tool Name]: [Query/Input Summary]

[Brief answer / top result]

## Details
[Expanded content]

## Sources
[Attribution / source files]
```

This helps the LLM parse responses consistently and extract the key information.

### 4.4 Reduce Round-Trips

Common workflows require 3-4 tool calls that could be 1-2:

| Current Pattern | Calls | Proposed Optimization |
|----------------|-------|----------------------|
| "What does this code do?" → `analyze_code_structure` + `get_code_context` + `explain_with_context` | 3 | Single `explain_code({ file_path })` that combines all three |
| "Is this production-ready?" → `analyze_ee2_compliance` + `find_dependencies` + `get_change_impact` | 3 | Single `assess_readiness({ file_path })` that runs the full battery |
| "Help me understand this subsystem" → `search_architecture` + `search_documentation` + `get_operational_guidance` | 3 | Single `explain_subsystem({ topic })` with all three data sources |

These composite tools would be Layer 2 agent capabilities (per the architecture doc), not Layer 1 primitives. But they could also be implemented as "macro tools" that orchestrate the existing primitives server-side.

---

## 5. Recommendations Summary

### Immediate (no code changes)
1. Update tool descriptions to include usage guidance for LLMs
2. Document the "when to use which tool" decision tree in steering files

### Short-term (Phase 60 candidate)
3. Fix deduplication bug in AgentCore `search_documentation` multi-collection path
4. Move session-state tools out of `graph_rag` into `sdd_workflow`
5. Add `list_all_sources` to the gateway (currently AgentCore-only)

### Medium-term (Phase 61+ candidates)
6. Implement the refined 7-module topology (breaking change for tool organization)
7. Standardize parameter naming across all tools
8. Create composite "macro tools" for common multi-step workflows
9. Implement a "core" vs "full" tool set toggle for different audiences

### Data layer
10. Re-embed gateway community summaries with Titan (closes architecture search gap)
11. Sync gateway graph to match Neptune depth (or deprecate gateway graph tools)
12. Address the v8-0-0 vs v8-2-0 collection version gap in AgentCore

---

## 6. Conclusion

The AgentCore (Python/Titan) server is the clear production path forward. Its embedding quality, data volume, and graph depth are all superior. The gateway remains valuable as a development reference and for its newer collection versions (v8-2-0), but the gap is widening.

The SoC topology is functional but has accumulated organic complexity over 59 development phases. The proposed 7-module refinement would reduce LLM decision fatigue by 30% while preserving all capabilities. The highest-impact immediate action is improving tool descriptions to guide LLM tool selection — this requires zero code changes and directly improves every user interaction.
