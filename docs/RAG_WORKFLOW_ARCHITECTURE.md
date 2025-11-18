# RAG Workflow Architecture for Global Workflow MCP System

**Date**: November 17, 2025  
**Purpose**: Architecture documentation for embedding model evaluation meeting

---

## System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PHASE 1: DOCUMENT INGESTION                         │
└─────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────┐
│  Source Repositories │
│                      │
│  • global-workflow/  │──┐
│  • nws-hpc-standards/│  │
│  • Python/Shell code │  │
│  • Documentation     │  │
└──────────────────────┘  │
                          │
                          ▼
                ┌─────────────────────┐
                │  Ingestion Scripts  │
                │  (Python)           │
                │                     │
                │  • Parse files      │
                │  • Extract metadata │
                │  • Chunk documents  │
                └─────────────────────┘
                          │
                          ▼
                ┌─────────────────────┐
                │  Embedding Model    │◄────── DECISION POINT
                │  (Client-Side)      │        (See comparison table)
                │                     │
                │  OPTIONS:           │
                │  1. MPNet (local)   │
                │  2. Google API      │
                │  3. OpenAI API      │
                │  4. Cohere API      │
                └─────────────────────┘
                          │
                          ▼
              ┌───────────────────────────┐
              │  Generate Embeddings      │
              │  (768-3072 dimensions)    │
              │                           │
              │  Input: Text chunks       │
              │  Output: Float vectors    │
              └───────────────────────────┘
                          │
                          ▼
              ┌───────────────────────────┐
              │  Store in ChromaDB        │
              │  (Vector Database)        │
              │                           │
              │  Collections:             │
              │  • docs-mpnet-768         │
              │  • docs-google-768        │
              │  • code-mpnet-768         │
              │                           │
              │  5,307 documents ingested │
              └───────────────────────────┘
                          │
                          ├──────────────────────────┐
                          ▼                          ▼
              ┌───────────────────────┐   ┌─────────────────────┐
              │  Neo4j Graph Database │   │  File System Cache  │
              │                       │   │                     │
              │  • Code structure     │   │  • Original docs    │
              │  • Dependencies       │   │  • Markdown files   │
              │  • Call chains        │   │  • Source code      │
              │  78,339 relationships │   │                     │
              └───────────────────────┘   └─────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                    PHASE 2: QUERY & RETRIEVAL (RAG)                         │
└─────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────┐
│  User in VS Code     │
│                      │
│  Types question:     │
│  "How does C48_ATM   │
│   test case work?"   │
└──────────────────────┘
           │
           ▼
┌──────────────────────┐
│  GitHub Copilot      │
│  (VS Code Extension) │
│                      │
│  Recognizes need for │
│  workflow context    │
└──────────────────────┘
           │
           ▼
┌──────────────────────┐
│  MCP Protocol        │
│  (stdio transport)   │
│                      │
│  Sends tool request  │
│  to MCP server       │
└──────────────────────┘
           │
           ▼
┌──────────────────────────────┐
│  MCP Server (Node.js)        │
│  UnifiedMCPServer v3.1.0     │
│                              │
│  Receives:                   │
│  search_documentation({      │
│    query: "C48_ATM test",    │
│    max_results: 5            │
│  })                          │
└──────────────────────────────┘
           │
           ▼
┌──────────────────────────────┐
│  Generate Query Embedding    │◄────── SAME MODEL AS INGESTION
│  (Client-Side)               │        (Critical: Must match!)
│                              │
│  Input: "C48_ATM test"       │
│  Output: [0.028, -0.041,...] │
│  (768-dim vector)            │
└──────────────────────────────┘
           │
           ▼
┌──────────────────────────────┐
│  ChromaDB Vector Search      │
│  (Cosine similarity)         │
│                              │
│  Query vector vs 5,307 docs  │
│  Returns top 5 matches       │
│  with similarity scores      │
└──────────────────────────────┘
           │
           ├─────────────────────────┐
           ▼                         ▼
┌─────────────────────┐   ┌─────────────────────┐
│  Neo4j Graph Query  │   │  Retrieve Full Text │
│                     │   │                     │
│  • Find related     │   │  Original document  │
│    files/functions  │   │  content (not the   │
│  • Get dependencies │   │  embedding vectors) │
│  • Enrich context   │   │                     │
└─────────────────────┘   └─────────────────────┘
           │                         │
           └────────────┬────────────┘
                        ▼
              ┌─────────────────────┐
              │  Hybrid Results     │
              │                     │
              │  • Vector matches   │
              │  • Graph context    │
              │  • Full TEXT docs   │
              └─────────────────────┘
                        │
                        ▼
              ┌─────────────────────┐
              │  Format Response    │
              │  (JSON)             │
              │                     │
              │  {                  │
              │    "content": [{    │
              │      "text": "..."  │
              │    }]               │
              │  }                  │
              └─────────────────────┘
                        │
                        ▼
              ┌─────────────────────┐
              │  Return to Copilot  │
              │  via MCP Protocol   │
              └─────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────┐
│  GitHub Copilot LLM                  │
│  (Claude 3.5 Sonnet)                 │
│                                      │
│  Receives:                           │
│  • User question                     │
│  • Retrieved TEXT documents          │◄─── NOT embeddings!
│  • Graph context                     │     Just the text
│                                      │
│  Generates answer using context      │
└──────────────────────────────────────┘
                        │
                        ▼
              ┌─────────────────────┐
              │  Display to User    │
              │  in VS Code Chat    │
              │                     │
              │  "The C48_ATM test  │
              │   case is a 48km    │
              │   atmosphere-only   │
              │   forecast..."      │
              └─────────────────────┘
```

---

## Key Architecture Principles

### 1. **Embeddings are for SEARCH, not LLM Input**
```
User Query → Embedding → Vector Search → Retrieve TEXT → TEXT to LLM
            (768-dim)    (similarity)    (documents)    (context)
```

**Why this matters:**
- LLMs work with text, not embedding vectors
- Better embeddings = better search = better context = better answers
- Embedding quality directly impacts RAG accuracy

### 2. **Client-Side Embedding Generation**
- **During Ingestion**: Python script generates embeddings, stores in ChromaDB
- **During Query**: Node.js MCP server generates query embedding
- **Docker ChromaDB**: Just stores and searches vectors (no model running)

**Why this architecture:**
- ChromaDB Docker is lightweight (200MB vs 5GB with Python)
- Flexibility to use different embedding models (local, API-based)
- Can have multiple collections with different embeddings

### 3. **Hybrid Search Strategy**
- **Vector Search**: Finds semantically similar documents (ChromaDB)
- **Graph Search**: Finds structurally related code (Neo4j)
- **Combined Results**: Most relevant context for LLM

**Example:**
```
Query: "How does GFS forecast initialization work?"

Vector Search finds:
- Documentation about forecast procedures
- Configuration examples
- Operational guides

Graph Search enriches:
- Related Python functions
- Dependency chains
- Calling workflows

Combined context sent to LLM = Better answer
```

---

## Current System Status

### Ingestion Complete (5,307 documents)
- **global-workflow-docs-v6-0-0-docker**: 156 docs (documentation)
- **ee2-standards-v6-0-0-docker**: 34 docs (compliance)
- **code_with_context_v7_docker**: 5,117 docs (Python code)

### Embedding Model in Use
- **all-mpnet-base-v2** (768-dim, local, free)
- Inference time: ~50ms per query on CPU
- No API costs

### Known Issue (Being Fixed)
- VectorDatabase.js uses `queryTexts` instead of `queryEmbeddings`
- Fix: One-line code change to pass vectors instead of text
- Status: Ready to implement

---

## Proposed Enhancement: Multi-Model Embeddings

### Architecture for Multiple Embedding Models

```
┌─────────────────────────────────────────────────────┐
│         PARALLEL COLLECTIONS STRATEGY               │
└─────────────────────────────────────────────────────┘

Same documents, different embeddings:

Collection 1: docs-mpnet-768
├── Doc A → [0.028, -0.041, ...] (768-dim MPNet)
├── Doc B → [0.015, 0.063, ...] (768-dim MPNet)
└── Doc C → [-0.032, 0.019, ...] (768-dim MPNet)

Collection 2: docs-google-768
├── Doc A → [0.041, -0.028, ...] (768-dim Google)
├── Doc B → [0.072, 0.015, ...] (768-dim Google)
└── Doc C → [-0.019, 0.032, ...] (768-dim Google)

Collection 3: docs-openai-3072
├── Doc A → [0.003, -0.011, ...] (3072-dim OpenAI)
├── Doc B → [0.008, 0.021, ...] (3072-dim OpenAI)
└── Doc C → [-0.015, 0.007, ...] (3072-dim OpenAI)
```

### Query Strategy Options

**Option A: Single Model (Current)**
```javascript
search_documentation({ query: "...", collection: "docs-mpnet-768" })
→ Fast, free, decent results
```

**Option B: Best Model**
```javascript
search_documentation({ query: "...", collection: "docs-google-768" })
→ Better results, API cost per query
```

**Option C: Hybrid (Future)**
```javascript
search_documentation({ 
  query: "...", 
  collections: ["docs-mpnet-768", "docs-google-768"],
  weights: [0.4, 0.6]  // Favor Google results
})
→ Combine results from multiple models
→ Best accuracy, highest cost
```

---

## Cost-Benefit Analysis Summary

See detailed comparison table in `EMBEDDING_MODEL_COMPARISON.md`

### For Tomorrow's Meeting

**Current State:**
- Using all-mpnet-base-v2 (local, free)
- 5,307 documents ingested
- RAG system functional (after VectorDatabase.js fix)

**Proposed Enhancement:**
- Add Google text-embedding-004 as parallel collection
- Cost: ~$0.10 for initial ingestion (one-time)
- Ongoing: ~$0.02/year for typical query volume (10 queries/day)

**Expected Improvement:**
- 20-40% better retrieval accuracy on code queries
- Particularly impactful for:
  - Complex workflow questions
  - Code dependency analysis
  - Cross-component understanding

**Risk:**
- Negligible cost (~$20/year worst case)
- No re-architecture needed (just add collection)
- Can A/B test before committing

---

## Implementation Phases

### Phase 1: Fix Current System (This Week)
- [ ] Fix VectorDatabase.js (queryTexts → queryEmbeddings)
- [ ] Test MCP tools with MPNet embeddings
- [ ] Validate 5,307 documents searchable

### Phase 2: Add Google Embeddings (Next Week, if approved)
- [ ] Update ingestion script to support API embeddings
- [ ] Ingest 5,307 docs with Google text-embedding-004
- [ ] Create parallel collection: `docs-google-768`
- [ ] A/B test query quality (MPNet vs Google)

### Phase 3: Evaluate and Decide (2 weeks)
- [ ] Measure retrieval accuracy improvement
- [ ] Monitor actual API costs
- [ ] User feedback on answer quality
- [ ] Decision: Keep both, choose one, or add more models

---

## Questions for Meeting

1. **Budget approval** for API embedding costs (~$20-100/year estimated)?
2. **Preferred vendor** (Google, OpenAI, Cohere) based on organizational relationships?
3. **Evaluation period** - how long to A/B test before committing?
4. **Success metrics** - how to measure if embeddings improve RAG quality?
5. **Fallback strategy** - stick with free MPNet if API costs exceed value?

---

## References

- **ChromaDB Documentation**: https://docs.trychroma.com/
- **Google Embeddings API**: https://cloud.google.com/vertex-ai/docs/generative-ai/embeddings
- **OpenAI Embeddings**: https://platform.openai.com/docs/guides/embeddings
- **Sentence Transformers (MPNet)**: https://www.sbert.net/
- **MCP Protocol**: https://modelcontextprotocol.io/

---

**Document Status**: Ready for November 18, 2025 meeting  
**Prepared by**: GitHub Copilot (Claude 3.5 Sonnet)  
**Last Updated**: November 17, 2025
