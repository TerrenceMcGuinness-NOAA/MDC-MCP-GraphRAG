# MCP Integration TODO - External Documentation Ingestion

## Current State ✅

### What We Have:
1. **Complete Ingestion Pipeline**
   - ✅ URL extraction from sitemaps
   - ✅ Semantic HTML chunking
   - ✅ Quality scoring (97.5% average)
   - ✅ File-based storage (external_documentation_chunks.json)
   - ✅ 125 chunks from 5 projects (Spack, wxflow, Pint, UFS, EE2)

2. **Existing MCP Server Tools** (9 tools)
   - ✅ get_workflow_structure
   - ✅ list_job_scripts
   - ✅ get_system_configs
   - ✅ explain_component
   - ✅ search_documentation (RAG-based)
   - ✅ explain_with_context (RAG-based)
   - ✅ find_similar_code
   - ✅ get_operational_guidance
   - ✅ analyze_dependencies

3. **Storage Infrastructure**
   - ✅ external_documentation_chunks.json (125 chunks)
   - ✅ EnhancedVectorStore class
   - ✅ EE2VectorStore class

---

## What's Missing for MCP Integration 🚧

### 1. MCP Tool for Ingestion Management ❌
**Need:** Expose ingestion capabilities as MCP tools

**Required Tools:**
```javascript
{
  name: "ingest_external_documentation",
  description: "Ingest external documentation into the knowledge base",
  inputSchema: {
    type: "object",
    properties: {
      urls: {
        type: "array",
        items: { type: "string" },
        description: "URLs to ingest"
      },
      mode: {
        type: "string",
        enum: ["direct", "crawl"],
        description: "Ingestion mode"
      },
      collection: {
        type: "string",
        description: "Collection name"
      }
    }
  }
}

{
  name: "extract_sitemap_urls",
  description: "Extract URLs from documentation sitemap",
  inputSchema: {
    type: "object",
    properties: {
      base_url: {
        type: "string",
        description: "Base documentation URL"
      },
      filter: {
        type: "string",
        description: "URL filter pattern"
      },
      show_metadata: {
        type: "boolean",
        default: true
      }
    }
  }
}

{
  name: "get_ingestion_status",
  description: "Get status of documentation ingestion",
  inputSchema: {
    type: "object",
    properties: {
      collection: {
        type: "string",
        description: "Collection name (optional)"
      }
    }
  }
}
```

### 2. Vector Store Integration ❌
**Need:** Load external_documentation_chunks.json into EnhancedVectorStore

**Current Issue:**
- Chunks stored in JSON file ✅
- EnhancedVectorStore NOT loading external chunks ❌
- MCP tools can't search external documentation ❌

**Required:**
- Modify EnhancedVectorStore to load external_documentation_chunks.json on init
- Update search_documentation tool to query external chunks
- Add filtering by source/project

### 3. Embedding Generation ❌
**Need:** Generate embeddings for semantic search

**Current:**
- Chunks have no embeddings (only metadata + content)
- search_documentation tool can't do semantic search without embeddings

**Required:**
- Generate embeddings for all 125 chunks
- Store embeddings in chunks_with_embeddings.json
- Update EnhancedVectorStore to use embeddings for search

### 4. Tool Handlers for Ingestion ❌
**Need:** Implement tool handlers in mcp-server-rag.js

**Required:**
```javascript
case "ingest_external_documentation":
  // Call DocumentationIngester
  // Return ingestion results

case "extract_sitemap_urls":
  // Call SitemapParser
  // Return extracted URLs

case "get_ingestion_status":
  // Read external_documentation_chunks.json
  // Return statistics
```

### 5. Real-time Ingestion Capability ❌
**Need:** Ability to ingest new documentation via MCP

**Current:** Only command-line scripts work

**Required:**
- Async ingestion in MCP server
- Progress reporting via MCP
- Error handling and retry logic

---

## Priority Order for Tomorrow 🎯

### Phase 1: Vector Store Integration (CRITICAL) 🔥
**Goal:** Make external chunks searchable

1. **Modify EnhancedVectorStore to load external chunks**
   - File: `src/rag/EnhancedVectorStore.js`
   - Add: Load external_documentation_chunks.json in constructor
   - Merge with internal chunks

2. **Test chunk retrieval**
   - Verify chunks accessible
   - Test filtering by source/category
   - Validate metadata preservation

3. **Update search_documentation tool**
   - Query external chunks
   - Filter by project/source
   - Return with proper context

**Time Estimate:** 2-3 hours
**Impact:** HIGH - Enables searching ingested docs

---

### Phase 2: MCP Ingestion Tools (HIGH PRIORITY) 🔥
**Goal:** Expose ingestion via MCP

1. **Add ingestion tools to mcp-server-rag.js**
   - ingest_external_documentation
   - extract_sitemap_urls
   - get_ingestion_status

2. **Implement tool handlers**
   - Import DocumentationIngester
   - Import SitemapParser
   - Add async processing

3. **Test via MCP client**
   - Test URL extraction
   - Test documentation ingestion
   - Verify status reporting

**Time Estimate:** 3-4 hours
**Impact:** HIGH - Enables ingestion via AI agents

---

### Phase 3: Embedding Generation (MEDIUM PRIORITY) 📊
**Goal:** Enable semantic search

1. **Generate embeddings for existing chunks**
   - Use existing embedding model
   - Process all 125 chunks
   - Store in chunks_with_embeddings.json

2. **Update search to use embeddings**
   - Modify search_documentation tool
   - Add similarity scoring
   - Rank results by relevance

3. **Test semantic search**
   - Query for concepts
   - Verify relevance ranking
   - Compare with keyword search

**Time Estimate:** 2-3 hours
**Impact:** MEDIUM - Improves search quality

---

### Phase 4: Testing & Documentation (IMPORTANT) 📝
**Goal:** Validate end-to-end flow

1. **Test complete flow**
   - Extract URLs via MCP
   - Ingest via MCP
   - Search ingested docs via MCP

2. **Update documentation**
   - MCP tool usage examples
   - Integration guide
   - Troubleshooting

3. **Performance testing**
   - Large document ingestion
   - Concurrent requests
   - Memory usage

**Time Estimate:** 1-2 hours
**Impact:** MEDIUM - Ensures reliability

---

## Success Criteria ✅

### Minimum Viable Product (MVP):
- [ ] EnhancedVectorStore loads external_documentation_chunks.json
- [ ] search_documentation tool queries external chunks
- [ ] ingest_external_documentation tool works via MCP
- [ ] extract_sitemap_urls tool works via MCP
- [ ] End-to-end test: Extract → Ingest → Search

### Nice to Have:
- [ ] Embedding generation for semantic search
- [ ] Real-time ingestion progress reporting
- [ ] Automatic re-ingestion on document changes
- [ ] Collection management (create/delete/list)

---

## Estimated Total Time

**Critical Path (MVP):**
- Phase 1: 2-3 hours (Vector Store Integration)
- Phase 2: 3-4 hours (MCP Ingestion Tools)
- Phase 4: 1-2 hours (Testing)

**Total: 6-9 hours** (1 full work day)

**With Nice-to-Haves:**
- Phase 3: 2-3 hours (Embeddings)
- **Total: 8-12 hours** (1.5 work days)

---

## Risk Assessment ⚠️

### Low Risk:
- ✅ Ingestion pipeline proven (125 chunks at 97.5% quality)
- ✅ File-based storage working
- ✅ MCP server infrastructure exists

### Medium Risk:
- ⚠️ Vector store integration complexity
- ⚠️ Embedding generation performance
- ⚠️ Concurrent ingestion handling

### High Risk:
- 🔴 Memory usage with large collections
- 🔴 Real-time ingestion blocking MCP server

### Mitigation:
- Use async/await for all operations
- Implement queuing for ingestion requests
- Add memory monitoring and limits
- Test with larger datasets before production

