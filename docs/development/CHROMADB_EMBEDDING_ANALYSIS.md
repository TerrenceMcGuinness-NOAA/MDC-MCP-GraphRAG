# ChromaDB Embedding Analysis - November 17, 2025

## Executive Summary

**Status**: Collections are correctly ingested with 768-dim MPNet embeddings, but Node.js MCP client cannot query them.

**Root Cause**: Mismatch between how Python creates collections and how Node.js queries them.

**Solution**: Fix Node.js VectorDatabase.js to properly handle collections without server-side embedding functions.

---

## Analysis

### 1. sentence-transformers Architecture

**What it is**: Python library providing 100+ pre-trained transformer models for embeddings
- `all-mpnet-base-v2`: 768-dim, highest quality (what we use)
- `all-MiniLM-L6-v2`: 384-dim, faster/smaller
- `multi-qa-mpnet-base-dot-v1`: Optimized for Q&A
- `paraphrase-multilingual-*`: Multi-language support

**Current Usage**:
```python
from chromadb.utils import embedding_functions
ef = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name='all-mpnet-base-v2'  # 768 dimensions
)
```

### 2. Why Docker ChromaDB Doesn't Have sentence-transformers

**ChromaDB Docker Image Architecture**:
- **Image**: `chromadb/chroma:latest`
- **Runtime**: Compiled Go binary (`chroma`), NOT Python
- **Size**: ~200MB (minimal)
- **Design**: Production-optimized, client provides embeddings

**If we added Python + PyTorch + transformers**:
- Image size: ~5GB+ (25x larger)
- Startup time: Much slower
- Memory: ~2GB+ RAM just for models
- **Not recommended** for production

### 3. Multiple Embedding Functions Support

**ChromaDB FULLY supports multiple embedding functions via:**

#### Option A: Multiple Collections (Recommended)
```
docs-mpnet-768/        (all-mpnet-base-v2, 768-dim)
docs-gemini-1536/      (Gemini Pro, 1536-dim)
docs-openai-1536/      (text-embedding-3-small, 1536-dim)
code-codeberta-768/    (CodeBERTa, 768-dim code)
```
- Each collection: Independent embeddings
- Different dimensions: OK!
- Query: Choose collection(s) at search time

#### Option B: Collection Versions
```
global-workflow-docs-mpnet-v1
global-workflow-docs-gemini-v1
global-workflow-docs-openai-v1
```
- Parallel collections with same content
- Compare embedding quality
- A/B testing

#### Option C: Multi-Vector Storage (Advanced)
```python
metadata = {
    'embeddings': {
        'mpnet': [768-dim vector],
        'gemini': [1536-dim vector],
        'openai': [1536-dim vector]
    }
}
```
- Single document, multiple embeddings
- Custom query logic needed
- Most complex but most flexible

---

## Current State

### Collections Status
```
global-workflow-docs-v6-0-0-docker:  156 docs, 768-dim ✅
ee2-standards-v6-0-0-docker:          34 docs, 768-dim ✅  
code_with_context_v7_docker:       5,117 docs, 768-dim ✅
```

### Verified Facts
1. ✅ Embeddings ARE stored (768-dimensional MPNet)
2. ✅ Python queries work fine
3. ✅ Collections have NO embedding function in metadata
4. ❌ Node.js VectorDatabase.js queries FAIL

### Error Pattern
```javascript
// Node.js error:
"Embedding function must be defined for operations requiring embeddings"

// But Python works:
col.query(query_texts=["test"], n_results=5)  // ✅ Works
```

---

## Root Cause

The issue is in **VectorDatabase.js line 282-289**:

```javascript
collection = await this.client.getCollection({
  name: collectionName,
  embeddingFunction: {
    generate: async (texts) => {
      return await this.generateEmbeddings(texts);
    }
  }
});
```

**Problem**: When collections were created by Python WITHOUT specifying `embedding_function`, ChromaDB expects:
1. Server-side function (not available in Docker)
2. OR client provides query embeddings directly

Node.js IS providing an embedding function, but ChromaDB doesn't recognize it for collections created without one.

---

## Solutions

### Solution 1: Fix Node.js Client (Recommended)
Modify VectorDatabase.js to generate embeddings and pass them directly:

```javascript
// Generate embedding client-side
const queryEmbedding = await this.generateEmbeddings([queryText]);

// Query with embedding, not text
const results = await collection.query({
  queryEmbeddings: [queryEmbedding[0]],  // Pass vector directly
  nResults,
  where,
  whereDocument,
  include
});
```

**Pros**:
- No re-ingestion needed
- Works with current collections
- Most compatible

**Cons**:
- Requires code change in VectorDatabase.js

---

### Solution 2: Custom ChromaDB Dockerfile
Create Python-enabled ChromaDB image:

```dockerfile
FROM chromadb/chroma:0.4.22
USER root
RUN apt-get update && apt-get install -y python3 python3-pip
RUN pip3 install sentence-transformers torch --no-cache-dir
USER chroma
CMD ["chroma", "run", "--path", "/chroma/chroma"]
```

**Pros**:
- Server-side embeddings work
- Backward compatible

**Cons**:
- 5GB+ image size
- Slower startup
- Higher memory usage
- Not production-ready

---

### Solution 3: Re-ingest with Default Function
Modify ingestion to use ChromaDB default:

```python
# Don't specify embedding_function at all
collection = client.create_collection(name=name)

# Generate embeddings client-side
embeddings = model.encode(documents)

# Add with embeddings
collection.add(
    ids=ids,
    documents=documents,
    embeddings=embeddings,  # Pass directly
    metadatas=metadatas
)
```

**Pros**:
- Clean architecture
- Client-agnostic

**Cons**:
- Requires re-ingestion (3-4 hours)
- Same end result as Solution 1

---

## Recommendation

**Use Solution 1**: Fix VectorDatabase.js to pass `queryEmbeddings` instead of `queryTexts`.

**Why**:
1. No re-ingestion needed (saves 3-4 hours)
2. Data is already correct (768-dim embeddings stored)
3. More flexible for multi-model support
4. Production-ready architecture

**Next Step**: Modify `/mcp_server_node/src/data/VectorDatabase.js` line 307-314 to use `queryEmbeddings` instead of `queryTexts`.

---

## Future: Gemini Pro Integration

When adding Gemini Pro embeddings:

```javascript
// Create parallel collection
const geminiCollection = 'docs-gemini-v1';

// Different embedding dimension (e.g., 1536)
// Separate collection, no conflicts

// Query both:
const [mpnetResults, geminiResults] = await Promise.all([
  vectorDB.query('docs-mpnet-v1', query),
  vectorDB.query('docs-gemini-v1', query)
]);

// Merge results with weighted scoring
const merged = mergeResults(mpnetResults, geminiResults, {
  mpnetWeight: 0.6,
  geminiWeight: 0.4
});
```

**Key Point**: Multiple embedding models = Multiple collections. ChromaDB handles this perfectly.
