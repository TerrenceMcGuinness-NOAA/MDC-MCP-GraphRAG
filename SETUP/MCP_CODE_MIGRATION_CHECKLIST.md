# MCP Server Source Code Migration Checklist - ChromaDB 3.x

**Status:** 📋 READY TO START  
**Prerequisites:** ✅ All infrastructure provisioning scripts updated to v3.1.0  
**Target:** Migrate MCP server source code from chromadb@1.x to chromadb@3.x API

---

## Quick Reference: What's Done vs What's Next

### ✅ COMPLETE - Infrastructure Layer
- [x] ChromaDB server upgraded to 1.1.1
- [x] Python dependencies: FastAPI 0.119.0, Pydantic 2.12.2, Uvicorn 0.37.0
- [x] OpenTelemetry instrumentation added
- [x] Node.js chromadb package upgraded to 3.0.17
- [x] @chroma-core/default-embed installed
- [x] All provisioning scripts updated
- [x] Service configurations updated
- [x] Test scripts updated
- [x] Documentation complete

### ❌ PENDING - Application Layer
- [ ] MCP server source code migration
- [ ] Update ChromaClient instantiation patterns
- [ ] Add embedding functions to collection operations
- [ ] Update query patterns
- [ ] Handle API v2 response structures
- [ ] Migrate existing collections
- [ ] Full integration testing

---

## Files Requiring Updates

### Priority 1: Core RAG Components

#### 1. `/mcp_rag_eib/mcp_server_node/src/rag/EE2VectorStore.js`
**Status:** ❌ Not Updated  
**Reason:** Contains ChromaClient instantiation and collection management

**Expected Changes:**
```javascript
// OLD (chromadb@1.x)
const { ChromaClient } = require('chromadb');
this.client = new ChromaClient('http://localhost:8080');

// NEW (chromadb@3.x)
const { ChromaClient } = require('chromadb');
const { DefaultEmbeddingFunction } = require('@chroma-core/default-embed');
this.client = new ChromaClient({ path: 'http://localhost:8080' });
this.embedder = new DefaultEmbeddingFunction();
```

**Collection Creation:**
```javascript
// OLD
const collection = await this.client.getOrCreateCollection({
    name: 'collection-name'
});

// NEW
const collection = await this.client.getOrCreateCollection({
    name: 'collection-name',
    embeddingFunction: this.embedder
});
```

**Lines to Check:**
- ChromaClient instantiation
- getOrCreateCollection calls
- query() method calls
- add() method calls

---

#### 2. `/mcp_rag_eib/mcp_server_node/src/tools/RAGTools.js`
**Status:** ❌ Not Updated  
**Reason:** Contains RAG semantic search implementations

**Expected Changes:**
- Update client initialization if present
- Update collection query patterns
- Handle new response structures
- Update error handling for API v2

**Lines to Check:**
- Any direct ChromaClient usage
- Collection query operations
- Response parsing logic

---

#### 3. `/mcp_rag_eib/mcp_server_node/src/UnifiedMCPServer.js`
**Status:** ❌ Not Updated  
**Reason:** Main server file that may initialize ChromaDB connections

**Expected Changes:**
- Update any ChromaDB initialization
- Update configuration passing to RAG tools
- Ensure embedding function is propagated

**Lines to Check:**
- Server initialization
- RAG tool initialization
- Configuration setup

---

### Priority 2: Supporting Files

#### 4. Any other files using ChromaDB
Search for files containing:
```bash
grep -r "ChromaClient" /mcp_rag_eib/mcp_server_node/src/
grep -r "getOrCreateCollection" /mcp_rag_eib/mcp_server_node/src/
grep -r "require('chromadb')" /mcp_rag_eib/mcp_server_node/src/
```

---

## API Migration Quick Reference

### 1. Client Initialization

```javascript
// ❌ OLD (chromadb@1.x)
const { ChromaClient } = require('chromadb');
const client = new ChromaClient('http://localhost:8080');

// ✅ NEW (chromadb@3.x)
const { ChromaClient } = require('chromadb');
const client = new ChromaClient({ 
    path: 'http://localhost:8080' 
});
```

### 2. Embedding Function Setup

```javascript
// ✅ NEW (required for chromadb@3.x)
const { DefaultEmbeddingFunction } = require('@chroma-core/default-embed');
const embedder = new DefaultEmbeddingFunction();
```

### 3. Collection Creation

```javascript
// ❌ OLD (chromadb@1.x)
const collection = await client.getOrCreateCollection({
    name: 'my-collection',
    metadata: { description: 'My collection' }
});

// ✅ NEW (chromadb@3.x)
const collection = await client.getOrCreateCollection({
    name: 'my-collection',
    embeddingFunction: embedder,
    metadata: { description: 'My collection' }
});
```

### 4. Adding Documents

```javascript
// ✅ UNCHANGED (same in both versions)
await collection.add({
    ids: ['id1', 'id2'],
    documents: ['text1', 'text2'],
    metadatas: [{ key: 'value1' }, { key: 'value2' }]
});
```

### 5. Querying

```javascript
// ✅ MOSTLY UNCHANGED (API same, response may differ slightly)
const results = await collection.query({
    queryTexts: ['search text'],
    nResults: 5
});

// Response structure (check for differences)
console.log(results.ids);
console.log(results.documents);
console.log(results.distances);
console.log(results.metadatas);
```

---

## Testing Strategy

### Step 1: Minimal Test (No Server)
```javascript
// Create standalone test: /tmp/test_mcp_chromadb.js
const { ChromaClient } = require('chromadb');
const { DefaultEmbeddingFunction } = require('@chroma-core/default-embed');

async function test() {
    const client = new ChromaClient({ path: 'http://localhost:8080' });
    const embedder = new DefaultEmbeddingFunction();
    
    // Test collection creation
    const collection = await client.getOrCreateCollection({
        name: 'test-mcp-migration',
        embeddingFunction: embedder
    });
    
    // Test add
    await collection.add({
        ids: ['test1'],
        documents: ['This is a test document']
    });
    
    // Test query
    const results = await collection.query({
        queryTexts: ['test'],
        nResults: 1
    });
    
    console.log('✅ All operations successful');
    console.log(results);
}

test().catch(console.error);
```

### Step 2: Update EE2VectorStore.js
- Modify file with new API patterns
- Test locally with simple initialization

### Step 3: Update RAGTools.js
- Modify search/query operations
- Test with simple queries

### Step 4: Update UnifiedMCPServer.js
- Ensure proper initialization
- Test core mode first (no RAG)
- Then test RAG mode

### Step 5: Full Integration Test
```bash
# Test core tools only
node src/UnifiedMCPServer.js core --test

# Test RAG tools
node src/UnifiedMCPServer.js rag --test

# Test full server
node src/UnifiedMCPServer.js full --test
```

---

## Expected Errors & Solutions

### Error 1: "Cannot read property 'ChromaClient' of undefined"
**Cause:** Package not installed  
**Solution:** `npm install chromadb@latest @chroma-core/default-embed`

### Error 2: "Collection created with undefined embedding function"
**Cause:** Missing embedding function in getOrCreateCollection  
**Solution:** Add `embeddingFunction: embedder` parameter

### Error 3: "TypeError: ChromaClient is not a constructor"
**Cause:** Old API pattern (string URL)  
**Solution:** Use `new ChromaClient({ path: 'http://...' })`

### Error 4: "Default embedding function not found"
**Cause:** Missing @chroma-core/default-embed  
**Solution:** `npm install @chroma-core/default-embed`

### Error 5: API v2 response structure different
**Cause:** ChromaDB 1.1.1 may return slightly different structures  
**Solution:** Log and compare response objects, adjust parsing

---

## Existing Collections Issue

**Problem:** 2 collections exist with "undefined" embedding functions from chromadb@1.x

**Options:**

1. **Recreate (Recommended)**
   ```javascript
   // Delete old collection
   await client.deleteCollection({ name: 'old-collection' });
   
   // Create new with embedding function
   const collection = await client.getOrCreateCollection({
       name: 'old-collection',
       embeddingFunction: embedder
   });
   ```

2. **Migrate (Complex)**
   - Export all documents from old collection
   - Create new collection with embedding function
   - Re-import all documents

3. **Leave As-Is (Not Recommended)**
   - May cause issues with queries
   - Embedding function warnings

---

## Rollback Plan

If migration fails, rollback:

```bash
# 1. Restore old source code
cd /mcp_rag_eib/mcp_server_node/src
git checkout HEAD~1 rag/EE2VectorStore.js tools/RAGTools.js UnifiedMCPServer.js

# 2. Downgrade npm packages
cd /mcp_rag_eib/mcp_server_node
npm uninstall chromadb @chroma-core/default-embed
npm install chromadb@1.10.5

# 3. Downgrade infrastructure (if needed)
# See PROVISIONING_V3.1_UPGRADE_NOTES.md for full rollback
```

---

## Success Criteria

- [ ] MCP server starts without errors
- [ ] All 17 tools register successfully
- [ ] RAG semantic search returns results
- [ ] Collections can be created/queried
- [ ] No "undefined embedding function" warnings
- [ ] Service runs stable for 5+ minutes
- [ ] Full integration test passes

---

## Estimated Timeline

- **File Discovery & Analysis:** 30 minutes
- **EE2VectorStore.js Update:** 45 minutes
- **RAGTools.js Update:** 30 minutes
- **UnifiedMCPServer.js Update:** 20 minutes
- **Testing & Debugging:** 1-2 hours
- **Integration Testing:** 30 minutes
- **Total:** 2-3 hours

---

## Next Command to Run

```bash
# 1. Find all files using ChromaDB
cd /mcp_rag_eib/mcp_server_node
grep -r "ChromaClient\|chromadb" src/ --include="*.js" | grep -v node_modules

# 2. Check current EE2VectorStore.js
cat src/rag/EE2VectorStore.js | head -100

# 3. Ready to start migration!
```

---

**Status:** 📋 Checklist Ready - Infrastructure Complete - Ready for Code Migration  
**Last Updated:** October 14, 2025
