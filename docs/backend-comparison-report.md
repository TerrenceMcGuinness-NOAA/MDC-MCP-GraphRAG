# Backend Comparison Report

**Date:** 2026-04-21T14:10:52.991Z
**Queries:** 13
**AWS Server:** mdc-mcp-rag-aws (OpenSearch + Neptune)
**Legacy Server:** eib-mcp-gateway (ChromaDB + Neo4j)

## Composite Scores

| Server | Score | Winner |
|--------|-------|--------|
| **AWS** | **59.7** | ✅ +2.7 |
| **Legacy** | **57.0** |  |

## Dimension Breakdown

| Dimension | Weight | AWS Score | Legacy Score | Winner |
|-----------|--------|-----------|--------------|--------|
| Latency (P50) | 0.3 | 100.0 | 0.2 | AWS |
| Relevance Quality | 0.3 | 44.2 | 59.2 | Legacy |
| Data Completeness | 0.2 | 21.2 | 100.0 | Legacy |
| Graph Richness | 0.1 | 22.3 | 100.0 | Legacy |
| Error Resilience | 0.1 | 100.0 | 92.3 | AWS |

## Latency Details

| Metric | AWS | Legacy |
|--------|-----|--------|
| P50 | 11 ms | 2927 ms |
| P95 | 90 ms | 60054 ms |

## Per-Query Results

| # | Tool | Category | AWS (ms) | Legacy (ms) | AWS OK | Legacy OK | Overlap |
|---|------|----------|----------|-------------|--------|-----------|---------|
| 1 | search_documentation | vector_search | 90 | 2767 | ✅ | ✅ | 100% |
| 2 | search_documentation | vector_search | 13 | 2793 | ✅ | ✅ | 0% |
| 3 | search_ee2_standards | vector_search | 14 | 2981 | ✅ | ✅ | 0% |
| 4 | explain_with_context | vector_search | 14 | 2699 | ✅ | ✅ | 100% |
| 5 | find_callers_callees | graph_traversal | 11 | 3196 | ✅ | ✅ | 0% |
| 6 | trace_full_execution_chain | graph_traversal | 11 | 2698 | ✅ | ✅ | 0% |
| 7 | find_dependencies | graph_traversal | 9 | 2927 | ✅ | ✅ | 100% |
| 8 | find_env_dependencies | graph_traversal | 10 | 3025 | ✅ | ✅ | 0% |
| 9 | get_code_context | ggsr_hybrid | 10 | 3273 | ✅ | ✅ | 0% |
| 10 | search_architecture | ggsr_hybrid | 9 | 2618 | ✅ | ✅ | 100% |
| 11 | get_change_impact | ggsr_hybrid | 10 | 60054 | ✅ | ❌ | — |
| 12 | trace_data_flow | ggsr_hybrid | 18 | 2819 | ✅ | ✅ | 0% |
| 13 | get_knowledge_base_status | health | 8 | 3342 | ✅ | ✅ | 100% |

## Errors

- **Legacy** get_change_impact: The operation was aborted due to timeout

## Methodology

```
Score = 0.3 × Latency + 0.3 × Relevance + 0.2 × DataCompleteness
      + 0.1 × GraphRichness + 0.1 × ErrorResilience
```
- **Latency**: Ratio of opponent P50 to own P50 (faster = higher score)
- **Relevance**: Jaccard overlap of extracted result IDs + volume bonus
- **Data Completeness**: Ratio of total result volume to max
- **Graph Richness**: Ratio of graph node counts for graph/GGSR queries
- **Error Resilience**: Percentage of successful tool calls