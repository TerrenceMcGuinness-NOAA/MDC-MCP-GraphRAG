# V7 Collection Upgrade Workflow

**Version**: 7.0.0
**Date**: December 3, 2025
**Status**: ✅ Completed (Scripts & Code Updates)

## Description

Upgrade all ChromaDB collections to v7 naming scheme with consistent naming convention and aligned ingestion scripts. This ensures MCP tools use current, consistent collection references.

## V7 Collection Naming Convention

| Content Type | Collection Name | Script |
|-------------|-----------------|--------|
| Documentation | `global-workflow-docs-v7-0-0` | `ingest_documentation_v7.py` |
| Code | `code-with-context-v7-0-0` | `ingest_code_v7.py` |
| EE2 Standards | `ee2-standards-v7-0-0` | `ingest_ee2_v7.py` |

## Phases

### Phase 1: Create V7 Ingestion Scripts ✅
- [x] Create `ingest_documentation_v7.py` - 3-tier doc sources, semantic chunking
- [x] Create `ingest_code_v7.py` - AST parsing, Neo4j graph enrichment  
- [x] Create `ingest_ee2_v7.py` - RST directive parsing, EE2 categories

### Phase 2: Update MCP Server References ✅
- [x] Update `WorkflowExecutor.js` collection references (lines 361-385)
- [x] Update `UnifiedDataAccess.js` default collections (lines 84, 243, 282, 361, 418)

### Phase 3: Run Ingestion Pipeline (Pending)
```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node/scripts
python3 ingest_documentation_v7.py
python3 ingest_code_v7.py
python3 ingest_ee2_v7.py
```

## Validation

- [ ] All v7 collections created with expected document counts
- [ ] MCP health check passes
- [ ] Semantic search returns results from v7 collections
- [ ] WorkflowExecutor ingestion step references correct scripts
