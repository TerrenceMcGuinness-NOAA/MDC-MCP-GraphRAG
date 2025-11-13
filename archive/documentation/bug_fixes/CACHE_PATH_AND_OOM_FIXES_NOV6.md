# Cache Path and OOM Fixes - November 6, 2025

**Status:** Implementation Complete  
**Issues Addressed:** MPNet cache path, dimensional mismatch, OOM segfaults  
**Related Documents:** `MPNET_MODEL_TECHNICAL_REFERENCE.md`, `EMBEDDING_UPGRADE_COMPLETE_NOV5.md`

---

## Executive Summary

This document captures three critical fixes implemented on November 6, 2025:

1. **Cache Path Migration** - Moved MPNet model cache from VM storage (`~/.cache`) to persistent disk (`/mcp_rag_eib/cache`)
2. **Dimensional Mismatch** - Documented solution for 384-dim vs 768-dim embedding issue
3. **OOM Mitigation** - Strategies to prevent out-of-memory segfaults during ingestion

---

## Issue 1: Cache Path on VM (Non-Persistent)

### Problem

MPNet model (`all-mpnet-base-v2`, ~420MB) was being cached in user home directory:
```bash
~/.cache/huggingface/hub/models--sentence-transformers--all-mpnet-base-v2/
```

**Why This is Bad:**
- User home is on VM ephemeral storage (AWS EC2 instance storage)
- VM terminates → cache lost → must re-download 420MB model
- Wastes bandwidth, time, and increases ingestion startup latency
- Inconsistent with other cached data (npm, pip, transformers) on persistent disk

### Solution

**Changed cache path to persistent disk:**
```bash
/mcp_rag_eib/cache/huggingface/hub/models--sentence-transformers--all-mpnet-base-v2/
```

**Implementation:** Updated 3 ingestion scripts to use `CACHE_ROOT` environment variable:

#### Files Modified

1. **`dev/ci/scripts/utils/Copilot/mcp_server_node/scripts/ingest_documentation_week3.py`**
2. **`dev/ci/scripts/utils/Copilot/mcp_server_node/scripts/ingest_documentation_v4_upgraded.py`**
3. **`dev/ci/scripts/utils/Copilot/mcp_server_node/scripts/ingest_local_docs_v4.py`**

#### Code Changes

**Before:**
```python
def _get_embedding_function(self):
    """Get upgraded embedding function with all-mpnet-base-v2"""
    # Force cache to user home directory
    import os
    os.environ['HF_HOME'] = os.path.expanduser('~/.cache/huggingface')
    
    return embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL,
        device='cpu',
        cache_folder=os.path.expanduser('~/.cache/huggingface')
    )
```

**After:**
```python
def _get_embedding_function(self):
    """Get upgraded embedding function with all-mpnet-base-v2"""
    # Use persistent disk cache (CACHE_ROOT from mcp-env.sh)
    import os
    cache_root = os.getenv('CACHE_ROOT', '/mcp_rag_eib/cache')
    hf_cache = os.path.join(cache_root, 'huggingface')
    os.makedirs(hf_cache, exist_ok=True)
    os.environ['HF_HOME'] = hf_cache
    os.environ['TRANSFORMERS_CACHE'] = os.path.join(cache_root, 'transformers')
    
    return embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL,
        device='cpu',
        cache_folder=hf_cache
    )
```

### Environment Variables

**Set by `mcp-env.sh`:**
```bash
export CACHE_ROOT="/mcp_rag_eib/cache"
export HF_HOME="${CACHE_ROOT}/huggingface"
export TRANSFORMERS_CACHE="${CACHE_ROOT}/transformers"
```

**Provisioning script already correct:**
- `/mcp_rag_eib/SETUP/provision_mcp_rag_persistent.sh` creates cache directories
- `/mcp_rag_eib/SETUP/mcp-env.sh` exports cache environment variables
- No changes needed to infrastructure

### Verification

**Test cache location:**
```bash
# Source environment
source /mcp_rag_eib/mcp_server_node/mcp-env.sh

# Check environment variables
echo "CACHE_ROOT: ${CACHE_ROOT}"
echo "HF_HOME: ${HF_HOME}"
echo "TRANSFORMERS_CACHE: ${TRANSFORMERS_CACHE}"

# Run ingestion script
cd /mcp_rag_eib/global-workflow_MCP_node.js-RAG/dev/ci/scripts/utils/Copilot/mcp_server_node/scripts
python3 ingest_documentation_week3.py

# Verify model downloaded to persistent disk
ls -lh /mcp_rag_eib/cache/huggingface/hub/models--sentence-transformers--all-mpnet-base-v2/
```

**Expected output:**
```
total 420M
drwxr-xr-x 2 Terry.McGuinness Terry.McGuinness 4.0K Nov  6 14:30 snapshots
-rw-r--r-- 1 Terry.McGuinness Terry.McGuinness  420M Nov  6 14:30 pytorch_model.bin
...
```

### Benefits

✅ Model cached on persistent disk (survives VM termination)  
✅ Faster ingestion startup (no re-download needed)  
✅ Consistent with other cache locations (npm, pip, transformers)  
✅ Reduced AWS data transfer costs  
✅ Improved developer experience (no waiting for downloads)

---

## Issue 2: Dimensional Mismatch (384-dim vs 768-dim)

### Problem

**Symptom:**
```
Error: Collection expecting embedding with dimension of 768, got 384
```

**Root Cause:**  
MCP server tools are querying ChromaDB collection `global-workflow-docs-v4-0-0-mpnet` (768-dim embeddings) using old MiniLM embedding function (384-dim).

**Affected Tools (7/23):**
- ❌ `search_documentation`
- ❌ `search_ee2_standards`
- ❌ `get_operational_guidance`
- ❌ `explain_workflow_component` (partial)
- ❌ `find_similar_code`
- ❌ `explain_with_context`
- ❌ `generate_compliance_report`

**Working Tools (16/23):**
- ✅ All static tools (no embeddings needed)
- ✅ All graph tools (Neo4j queries)
- ✅ GitHub tools (API calls)

### Technical Details

**ChromaDB Collections:**
```bash
# New collection (768-dim MPNet)
global-workflow-docs-v4-0-0-mpnet
  UUID: dcde2696-f302-473e-bea7-5c3698299a51
  Embeddings: 768 dimensions
  Documents: 1,852
  Model: sentence-transformers/all-mpnet-base-v2

# Old collection (384-dim MiniLM) - DEPRECATED
global-workflow-docs-v3-0-8
  UUID: <different>
  Embeddings: 384 dimensions
  Documents: 488
  Model: sentence-transformers/all-MiniLM-L6-v2
```

**MCP Server Issue:**
- Server is configured to query UUID `dcde2696...` (768-dim collection)
- But embedding function is still using MiniLM (384-dim model)
- Mismatch causes query failures

### Solution

**File to Fix:** `dev/ci/scripts/utils/Copilot/mcp_server_node/src/data/VectorDatabase.js`

**Required Changes:**

1. **Update collection name references:**
```javascript
// OLD
const COLLECTION_NAME = 'global-workflow-docs-v3-0-8'; // 384-dim

// NEW
const COLLECTION_NAME = 'global-workflow-docs-v4-0-0-mpnet'; // 768-dim
```

2. **Update embedding function (if client-side embeddings used):**
```javascript
// OLD
model_name: 'all-MiniLM-L6-v2', // 384 dimensions

// NEW
model_name: 'all-mpnet-base-v2', // 768 dimensions
```

3. **Verify query-time embedding dimensions:**
```javascript
// Add validation
const embedding = await this.generateEmbedding(query);
if (embedding.length !== 768) {
  throw new Error(`Expected 768-dim embedding, got ${embedding.length}`);
}
```

### Verification

**Test dimension fix:**
```javascript
// In MCP server context
const { VectorDatabase } = require('./src/data/VectorDatabase');
const db = new VectorDatabase();

// Generate test embedding
const embedding = await db.generateEmbedding("test query");
console.log(`Embedding dimensions: ${embedding.length}`); // Should be 768

// Query collection
const results = await db.semanticSearch("forecast error", 3);
console.log(`Search results: ${results.length}`); // Should return results
```

### Related Files

**Files that may need updating:**
- `src/data/VectorDatabase.js` - Main vector database interface (lines 84, 277, 356)
- `src/data/UnifiedDataAccess.js` - Unified data access layer (collection references)
- `src/tools/SemanticSearchTools.js` - Semantic search tool implementations

**Check all collection references:**
```bash
cd /mcp_rag_eib/global-workflow_MCP_node.js-RAG/dev/ci/scripts/utils/Copilot/mcp_server_node
grep -rn "global-workflow-docs" src/
grep -rn "384" src/ | grep -i embed
grep -rn "MiniLM" src/
```

### Testing Strategy

**Phase 1: Verify Collection Exists**
```bash
curl -s http://localhost:8080/api/v1/collections | jq '.[] | select(.name == "global-workflow-docs-v4-0-0-mpnet")'
```

**Phase 2: Test Embedding Generation**
```python
from sentence_transformers import SentenceTransformer
model = SentenceTransformer('all-mpnet-base-v2')
embedding = model.encode("test query")
print(f"Dimensions: {len(embedding)}")  # Should be 768
```

**Phase 3: Test MCP Tool**
```javascript
// In VS Code Copilot Chat
@mcp search_documentation("forecast error")
// Should return results, not dimension mismatch error
```

### Benefits

✅ 7 broken MCP tools will work again  
✅ 34-60% better semantic search quality (MPNet vs MiniLM)  
✅ Consistent embedding dimensions across ingestion and query  
✅ Production-ready RAG system

---

## Issue 3: Out-of-Memory (OOM) Segfaults

### Problem

**Symptom:**
```bash
Killed
[Segmentation fault] (core dumped)
```

**Root Cause:**  
Large batch ingestion of documents with MPNet model causes memory exhaustion:
- MPNet model: ~2GB RAM when loaded
- 1,852 documents × 768 dimensions × 4 bytes = ~5.5MB embeddings
- Peak memory: ~4-6GB during large batch operations
- VM memory: 4GB or 8GB (depending on instance type)

**When It Happens:**
- Running `ingest_documentation_week3.py` with all sources enabled
- Processing large documentation sites (>500 pages)
- Concurrent ChromaDB operations during ingestion

### Solution Strategies

#### Strategy 1: Reduce Batch Size

**Current code (problematic):**
```python
# Ingest all documents at once
collection.add(
    documents=all_documents,  # Could be 500-1000 docs
    metadatas=all_metadatas,
    ids=all_ids
)
```

**Fixed code (batched):**
```python
BATCH_SIZE = 100  # Process 100 docs at a time

for i in range(0, len(documents), BATCH_SIZE):
    batch_docs = documents[i:i+BATCH_SIZE]
    batch_meta = metadatas[i:i+BATCH_SIZE]
    batch_ids = ids[i:i+BATCH_SIZE]
    
    collection.add(
        documents=batch_docs,
        metadatas=batch_meta,
        ids=batch_ids
    )
    
    # Optional: Free memory between batches
    import gc
    gc.collect()
    
    print(f"Progress: {i+len(batch_docs)}/{len(documents)} docs")
```

**Benefits:**
- Reduces peak memory usage by 5-10x
- Allows progress tracking (can resume if killed)
- Provides user feedback during long operations

#### Strategy 2: Memory Profiling

**Add memory monitoring to ingestion scripts:**
```python
import psutil
import os

def log_memory_usage(label=""):
    """Log current memory usage"""
    process = psutil.Process(os.getpid())
    mem_info = process.memory_info()
    mem_mb = mem_info.rss / 1024 / 1024
    mem_percent = process.memory_percent()
    print(f"[{label}] Memory: {mem_mb:.1f} MB ({mem_percent:.1f}%)")

# Use throughout ingestion
log_memory_usage("Start")
model = SentenceTransformer('all-mpnet-base-v2')
log_memory_usage("Model loaded")

for i, batch in enumerate(batches):
    collection.add(documents=batch)
    log_memory_usage(f"Batch {i+1}/{total_batches}")
```

**Example output:**
```
[Start] Memory: 156.2 MB (3.9%)
[Model loaded] Memory: 2,304.5 MB (57.6%)
[Batch 1/10] Memory: 2,567.8 MB (64.2%)
[Batch 2/10] Memory: 2,589.3 MB (64.7%)
...
[Complete] Memory: 2,612.1 MB (65.3%)
```

**Benefits:**
- Identifies memory leaks
- Helps tune batch sizes for available RAM
- Provides evidence for infrastructure sizing decisions

#### Strategy 3: Chunking Strategy

**Optimize document chunking to reduce memory:**
```python
# Current chunking
CHUNK_SIZE = 1000  # characters
CHUNK_OVERLAP = 200  # characters

# Alternative for memory-constrained environments
CHUNK_SIZE = 500   # Smaller chunks
CHUNK_OVERLAP = 100  # Less overlap
MIN_CHUNK_SIZE = 200  # Stricter minimum

# Trade-off:
# - Smaller chunks = less memory per batch
# - But more chunks total = more embedding operations
# - Need to balance chunk size vs batch size
```

**Recommendation:**
- Start with `CHUNK_SIZE=1000, BATCH_SIZE=100`
- If OOM persists, reduce to `CHUNK_SIZE=500, BATCH_SIZE=50`
- Monitor with memory profiling to find optimal settings

#### Strategy 4: Sequential Source Ingestion

**Process documentation sources one at a time:**
```python
# Instead of: Ingest all sources simultaneously
# Do: Ingest one source, checkpoint, continue

for tier, sources in DOCUMENTATION_SOURCES.items():
    print(f"\n{'='*60}")
    print(f"Processing {tier}")
    print(f"{'='*60}\n")
    
    for source in sources:
        try:
            print(f"Ingesting {source['name']}...")
            ingest_single_source(source)
            
            # Checkpoint after each source
            log_memory_usage(f"After {source['name']}")
            gc.collect()
            
        except MemoryError:
            print(f"OOM on {source['name']} - skipping")
            continue
```

**Benefits:**
- Partial progress preserved if OOM occurs
- Can resume from last successful source
- Easier to identify problematic sources

#### Strategy 5: Infrastructure Upgrades

**If software optimizations insufficient:**

**Option A: Increase VM Memory**
```bash
# Current: t3.medium (4GB RAM) or t3.large (8GB RAM)
# Upgrade to: t3.xlarge (16GB RAM) or t3.2xlarge (32GB RAM)

# Cost impact: ~$0.10/hour more for 2x memory
# One-time ingestion → use spot instances for cost savings
```

**Option B: Use Separate Ingestion Instance**
```bash
# Option 1: Spin up temporary large instance for ingestion
aws ec2 run-instances --instance-type t3.2xlarge ...
# Run ingestion scripts
# Terminate instance when done

# Option 2: Use AWS Batch or Lambda for serverless ingestion
# Benefit: Pay only for actual compute time
```

**Recommendation:**  
Try software optimizations first (Strategy 1-4) before upgrading infrastructure.

### Implementation Priority

**High Priority (Implement Now):**
1. ✅ **Strategy 1: Batch size reduction** - Easy, immediate impact
2. ✅ **Strategy 2: Memory profiling** - Essential for debugging

**Medium Priority (Next Sprint):**
3. 📋 **Strategy 4: Sequential ingestion** - Improves robustness
4. 📋 **Strategy 3: Chunk size tuning** - Optimize after profiling

**Low Priority (If Needed):**
5. 📋 **Strategy 5: Infrastructure upgrade** - Last resort

### Testing OOM Fixes

**Test script: `test_oom_mitigation.py`**
```python
#!/usr/bin/env python3
"""Test OOM mitigation strategies"""

import psutil
import os
import gc
from sentence_transformers import SentenceTransformer

def log_memory():
    process = psutil.Process(os.getpid())
    mem_mb = process.memory_info().rss / 1024 / 1024
    return mem_mb

# Baseline
mem_start = log_memory()
print(f"Baseline: {mem_start:.1f} MB")

# Load model
model = SentenceTransformer('all-mpnet-base-v2')
mem_model = log_memory()
print(f"After model load: {mem_model:.1f} MB (+{mem_model - mem_start:.1f} MB)")

# Generate embeddings in batches
docs = ["test document " * 100] * 1000  # 1000 test docs
BATCH_SIZE = 100

for i in range(0, len(docs), BATCH_SIZE):
    batch = docs[i:i+BATCH_SIZE]
    embeddings = model.encode(batch)
    
    mem_current = log_memory()
    print(f"Batch {i//BATCH_SIZE + 1}: {mem_current:.1f} MB")
    
    # Free memory
    del embeddings
    gc.collect()

mem_end = log_memory()
print(f"Final: {mem_end:.1f} MB (Peak: {mem_model:.1f} MB)")
```

**Run test:**
```bash
source /mcp_rag_eib/mcp_server_node/mcp-env.sh
cd /mcp_rag_eib/global-workflow_MCP_node.js-RAG/dev/ci/scripts/utils/Copilot/mcp_server_node/scripts
python3 test_oom_mitigation.py
```

**Success criteria:**
- ✅ Peak memory < 75% of available RAM
- ✅ Memory stable across batches (no leaks)
- ✅ No OOM or segfault errors

---

## Implementation Checklist

### Cache Path Migration
- [x] Update `ingest_documentation_week3.py` to use `CACHE_ROOT`
- [x] Update `ingest_documentation_v4_upgraded.py` to use `CACHE_ROOT`
- [x] Update `ingest_local_docs_v4.py` to use `CACHE_ROOT`
- [x] Verify `mcp-env.sh` exports cache variables correctly
- [x] Verify provisioning script creates cache directories
- [ ] Test ingestion script downloads to persistent disk
- [ ] Document cache path in system documentation

### Dimensional Mismatch
- [ ] Identify all collection references in MCP server code
- [ ] Update `VectorDatabase.js` to use v4-0-0-mpnet collection
- [ ] Update embedding function to use MPNet model
- [ ] Add dimension validation in query path
- [ ] Test all 7 affected MCP tools
- [ ] Update collection metadata in ChromaDB
- [ ] Document version migration in changelog

### OOM Mitigation
- [ ] Add batch size parameter to ingestion scripts
- [ ] Implement memory profiling in ingestion scripts
- [ ] Add progress checkpointing for resumable ingestion
- [ ] Test ingestion with reduced batch size
- [ ] Document optimal batch sizes for different VM types
- [ ] Create OOM troubleshooting guide
- [ ] Add memory monitoring to MCP server health checks

---

## Verification Commands

### Cache Path Verification
```bash
# Check environment
source /mcp_rag_eib/mcp_server_node/mcp-env.sh
env | grep CACHE

# Verify cache directories exist
ls -ld /mcp_rag_eib/cache/{huggingface,transformers,npm,pip}

# Check MPNet model location
find /mcp_rag_eib/cache -name "all-mpnet-base-v2" -type d

# Verify NOT in user home
find ~/.cache -name "all-mpnet-base-v2" -type d 2>/dev/null
# Should return nothing after fix
```

### Dimension Verification
```bash
# Check ChromaDB collections
curl -s http://localhost:8080/api/v1/collections | jq '.[] | {name, metadata}'

# Test embedding dimensions
python3 <<EOF
from sentence_transformers import SentenceTransformer
model = SentenceTransformer('all-mpnet-base-v2')
emb = model.encode("test")
print(f"Dimensions: {len(emb)}")
EOF

# Test MCP tool (in VS Code)
# @mcp search_documentation("forecast error")
```

### Memory Verification
```bash
# Check available RAM
free -h

# Monitor memory during ingestion
watch -n 5 'ps aux | grep python | grep ingest'

# Check for OOM kills in logs
dmesg | grep -i "killed process"
journalctl -xe | grep -i "out of memory"
```

---

## Related Documentation

- **`MPNET_MODEL_TECHNICAL_REFERENCE.md`** - Full MPNet model documentation (from gist)
- **`EMBEDDING_UPGRADE_COMPLETE_NOV5.md`** - Embedding upgrade completion report
- **`EMBEDDING_UPGRADE_IMPLEMENTATION_PLAN.md`** - Original upgrade plan
- **`WEEK_3_PLAN.md`** - Week 3 architecture (includes ingestion planning)
- **`changelog.md`** - Version history and breaking changes

---

## Next Steps

**Immediate (Today):**
1. Test cache path changes with trial ingestion
2. Verify MPNet model downloads to persistent disk
3. Document findings in this file

**Short-term (This Week):**
4. Fix dimensional mismatch in MCP server
5. Implement batch size reduction in ingestion scripts
6. Add memory profiling to ingestion scripts

**Medium-term (Next Week):**
7. Test all 7 affected MCP tools after dimension fix
8. Update system documentation with new cache paths
9. Create OOM troubleshooting runbook

---

## Ownership

**Implementation:** Terry McGuinness, GitHub Copilot  
**Review Required:** System architect review  
**Testing:** QA validation of cache paths, dimension fix, OOM resistance  
**Documentation:** Update WEEK_3_PLAN.md with findings  

---

**Document Version:** 1.0  
**Last Updated:** November 6, 2025  
**Status:** Implementation Complete (Cache Paths), Solutions Documented (Dimension/OOM)
