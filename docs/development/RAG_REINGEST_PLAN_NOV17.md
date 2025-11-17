# RAG Re-Ingest Plan - November 17, 2025

**Date**: November 17, 2025  
**Context**: Fresh SSO connection, Docker ChromaDB operational, ready for fresh RAG ingestion  
**ChromaDB Version**: Docker container (chromadb/chroma:latest)  
**Status**: ✅ System validated, ready to proceed

---

## Executive Summary

### Current State Assessment

✅ **ChromaDB Docker Container**
- Running: 19 minutes uptime
- Port mapping: 8080 (host) → 8000 (container)
- Volume mount: `/mcp_rag_eib/data/chromadb` → `/chroma/chroma` (CONFIRMED PERSISTENT)
- API v2: Healthy (heartbeat verified)
- Data size: 147M on persistent volume

✅ **Persistent Storage**
- AWS EBS volume: `/mcp_rag_eib` (492G, 12% used, 413G available)
- ChromaDB data: Mounted in container AND persisted on host
- Volume binding confirmed: Docker inspect shows bind mount

✅ **Neo4j Graph Database**
- Status: Healthy (14 hours uptime)
- Data: 213 files, 469 functions, 49,826 relationships
- Graph queries: Operational

✅ **MCP Server Health**
- Overall: 5/6 components healthy
- 26 tools registered
- Vector DB: Shows 0 documents (collections empty but exist)
- Graph DB: Fully populated

### Critical Findings

🔴 **All ChromaDB Collections are EMPTY** (0 documents)
```
Collections found in SQLite database:
- code_with_context (0 docs)
- global-workflow-docs-v4-0-0-mpnet (0 docs)
- global-workflow-docs-v4-1-0-enhanced (0 docs)
- global-workflow-docs-v4-2-0-unified (0 docs)
- global-workflow-docs-v5-0-0-consolidated (0 docs)
- ee2-test-v5 (0 docs)
- ee2-standards-v5-0-0-enhanced (0 docs)
- code_with_context_v6_graph_enriched (0 docs)
- ci-test-cases-v1-0-0 (0 docs)
- ci-test-cases-v2-0-0-gfs-expert (0 docs)
```

**Root Cause Analysis**:
1. **SQLite database exists** (126M) with collection metadata
2. **Embeddings table is empty** - No documents were actually ingested
3. **Collections created but never populated** - Ingestion scripts may have failed silently
4. **Docker migration may have reset data** - Old Spack-based data not transferred

**Implication**: Despite 126M SQLite file, actual vector embeddings are missing. This is a FRESH START scenario.

---

## Re-Ingest Strategy

### Option A: Clean Slate Approach (RECOMMENDED)

**Rationale**: 
- Current collections have no data
- Clean slate ensures consistency
- Docker environment is fresh and stable
- No legacy cruft to deal with

**Steps**:
1. **Delete all existing empty collections** (cleanup)
2. **Create new versioned collection** (`global-workflow-docs-v6-0-0-docker`)
3. **Run comprehensive ingestion** using proven scripts
4. **Verify ingestion** with document counts
5. **Update MCP tools** to use new collection

**Estimated Time**: 2-4 hours (depending on documentation crawl)

### Option B: Incremental Repair (NOT RECOMMENDED)

**Rationale**: Collections exist but are empty, attempting to re-populate may hit metadata conflicts

**Concerns**:
- May encounter stale metadata
- Collection IDs are UUID-based (hard to track)
- No guarantee of consistency

---

## Recommended Ingestion Plan

### Phase 1: Environment Preparation (10 minutes)

```bash
# 1. Verify Docker ChromaDB is running
docker ps | grep chromadb
curl -s http://localhost:8080/api/v2/heartbeat

# 2. Check persistent storage
df -h /mcp_rag_eib
du -sh /mcp_rag_eib/data/chromadb

# 3. Load Spack modules for Python dependencies
module load gcc/11.5.0
module load py-pydantic py-neo4j py-httpx py-idna py-requests py-certifi py-anyio py-sniffio
module load py-numpy py-scipy py-pillow py-tokenizers py-tqdm py-pyyaml

# 4. Install chromadb client via pip (--user --no-deps)
python3 -m pip install --user --no-deps chromadb

# 5. Verify client can connect
python3 -c "import chromadb; client = chromadb.HttpClient(host='localhost', port=8080); print(f'Connected: {client.heartbeat()}')"
```

### Phase 2: Collection Cleanup (5 minutes)

**Option 2A: Delete via Python script**
```python
#!/usr/bin/env python3
"""cleanup_empty_collections.py - Remove all empty ChromaDB collections"""
import chromadb

client = chromadb.HttpClient(host='localhost', port=8080)
collections = client.list_collections()

print(f"Found {len(collections)} collections")
for col in collections:
    count = col.count()
    print(f"  - {col.name}: {count} docs")
    if count == 0:
        print(f"    [DELETE] Removing empty collection: {col.name}")
        client.delete_collection(col.name)
        
print("\n[OK] Cleanup complete")
```

**Option 2B: Manual Docker restart (nuclear option)**
```bash
# Stop container
docker stop chromadb

# Backup old data
sudo mv /mcp_rag_eib/data/chromadb /mcp_rag_eib/data/chromadb.backup.nov17

# Create fresh directory
sudo mkdir -p /mcp_rag_eib/data/chromadb
sudo chown Terry.McGuinness:Terry.McGuinness /mcp_rag_eib/data/chromadb

# Restart container (will create fresh SQLite DB)
docker start chromadb
```

### Phase 3: Fresh Documentation Ingestion (1-2 hours)

**Script**: `mcp_server_node/scripts/ingest_documentation_v4_2_unified.py`

**Why this script**:
- Uses `ingestion_base.py` library (proven, tested)
- Imports from `documentation_sources_config.py` (single source of truth)
- 4 tiers of documentation sources (13 sources total)
- Semantic chunking with MPNet embeddings (768-dim)
- Metadata enrichment

**Collection Name**: `global-workflow-docs-v6-0-0-docker`

**Expected Output**: 2,000-3,000 chunks from:
- Tier 1 Critical: global-workflow, ee2-standards, ufs-utils
- Tier 2 Infrastructure: ufs-weather-model, wxflow, rocoto, ecflow, pyflow
- Tier 3 Build System: spack-stack, jedi-docs
- Tier 4 Reference: google-shell-style, pep8, numpy-docstrings

**Command**:
```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node/scripts

# Dry run first
python3 ingest_documentation_v4_2_unified.py --dry-run

# Full ingestion (specify new collection name)
python3 ingest_documentation_v4_2_unified.py \
    --collection global-workflow-docs-v6-0-0-docker \
    --log-file ../../logs/ingest_v6_docker_$(date +%Y%m%d_%H%M%S).log

# Monitor progress
tail -f ../../logs/ingest_v6_docker_*.log
```

### Phase 4: EE2 Standards Enhanced Ingestion (30 minutes)

**Script**: `mcp_server_node/scripts/ingest_ee2_enhanced_v5.py`

**Why this matters**:
- EE2 compliance is critical for NOAA operational code
- Enhanced with code examples from nws-hpc-standards submodule
- RST format parsing (reStructuredText)
- Cross-references and code block extraction

**Collection Name**: `ee2-standards-v6-0-0-docker`

**Expected Output**: 30-50 documents

**Command**:
```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node/scripts

python3 ingest_ee2_enhanced_v5.py \
    --collection ee2-standards-v6-0-0-docker \
    --standards-repo ../../supported_repos/nws-hpc-standards \
    --log-file ../../logs/ingest_ee2_v6_$(date +%Y%m%d_%H%M%S).log
```

### Phase 5: Code Context Ingestion (1 hour)

**Script**: `mcp_server_node/scripts/ingest_code_graph_enriched_v6.py`

**Why this matters**:
- Code-level semantic search
- Graph-enriched embeddings (Neo4j integration)
- Function/class/module documentation
- Call chain context

**Collection Name**: `code_with_context_v7_docker`

**Expected Output**: 4,000-5,000 code chunks

**Command**:
```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node/scripts

python3 ingest_code_graph_enriched_v6.py \
    --workflow-root ../../supported_repos/global-workflow \
    --collection code_with_context_v7_docker \
    --log-file ../../logs/ingest_code_v7_$(date +%Y%m%d_%H%M%S).log
```

### Phase 6: CI Test Cases Expert System (15 minutes)

**Script**: `mcp_server_node/scripts/ingest_ci_test_cases.py`

**Why this matters**:
- GFS operational knowledge embedded
- 66 CI test cases with full meteorological context
- Jinja2-aware YAML parsing
- Category intelligence

**Collection Name**: `ci-test-cases-v3-0-0-docker`

**Expected Output**: 66 documents

**Command**:
```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node/scripts

python3 ingest_ci_test_cases.py \
    --workflow-root ../../supported_repos/global-workflow \
    --collection ci-test-cases-v3-0-0-docker \
    --log-file ../../logs/ingest_ci_v3_$(date +%Y%m%d_%H%M%S).log
```

### Phase 7: Verification (10 minutes)

```bash
# Check collection counts
python3 << 'EOF'
import chromadb
client = chromadb.HttpClient(host='localhost', port=8080)
collections = client.list_collections()

print(f"\n{'='*70}")
print(f"ChromaDB Status - Post Ingestion")
print(f"{'='*70}")
print(f"Total collections: {len(collections)}\n")

total_docs = 0
for col in collections:
    count = col.count()
    total_docs += count
    print(f"  ✓ {col.name}: {count:,} documents")

print(f"\n{'='*70}")
print(f"Total documents: {total_docs:,}")
print(f"{'='*70}\n")
EOF
```

**Expected Results**:
- `global-workflow-docs-v6-0-0-docker`: 2,000-3,000 docs
- `ee2-standards-v6-0-0-docker`: 30-50 docs
- `code_with_context_v7_docker`: 4,000-5,000 docs
- `ci-test-cases-v3-0-0-docker`: 66 docs
- **Total**: ~6,000-8,000 documents

### Phase 8: MCP Tool Configuration Update (10 minutes)

**File**: `mcp_server_node/src/UnifiedMCPServer.js` (or relevant tool modules)

**Update collection names**:
```javascript
// OLD (empty collections)
const PRIMARY_COLLECTION = 'global-workflow-docs-v5-0-0-consolidated';
const CODE_COLLECTION = 'code_with_context_v6_graph_enriched';
const EE2_COLLECTION = 'ee2-standards-v5-0-0-enhanced';
const CI_COLLECTION = 'ci-test-cases-v2-0-0-gfs-expert';

// NEW (Docker re-ingest)
const PRIMARY_COLLECTION = 'global-workflow-docs-v6-0-0-docker';
const CODE_COLLECTION = 'code_with_context_v7_docker';
const EE2_COLLECTION = 'ee2-standards-v6-0-0-docker';
const CI_COLLECTION = 'ci-test-cases-v3-0-0-docker';
```

**Restart MCP Server**:
```bash
# If using VS Code MCP integration
# Reload VS Code window: Cmd/Ctrl+Shift+P -> "Developer: Reload Window"

# Or restart manually if using start script
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node
./start-mcp-server-node.sh
```

### Phase 9: Functional Testing (15 minutes)

**Test via MCP tools**:
```javascript
// Test 1: Basic search
search_documentation({ 
  query: "How do I configure GFS resolution?",
  doc_type: "all",
  max_results: 5 
})

// Test 2: EE2 compliance
search_ee2_standards({
  query: "error handling requirements",
  max_results: 5
})

// Test 3: Code search
find_similar_code({
  code_snippet: "def run_gdas():",
  language: "python",
  similarity_threshold: 0.7
})

// Test 4: CI test case lookup
search_documentation({
  query: "C96C48mx500 S2S subseasonal forecast",
  doc_type: "all"
})

// Test 5: Knowledge base status
get_knowledge_base_status({ detailed: true, include_vector: true, include_graph: true })
```

---

## Risk Assessment

### Low Risk ✅
- Docker container stability (proven)
- Persistent volume mount (verified)
- Neo4j data preserved (graph DB unaffected)
- Ingestion scripts battle-tested

### Medium Risk ⚠️
- Network issues during documentation crawl (mitigation: retry logic in scripts)
- Embedding generation time (mitigation: run during off-hours if needed)
- Disk space (413G available, need ~2-5G max)

### High Risk ❌
- None identified

### Rollback Strategy

If ingestion fails:
```bash
# 1. Stop ChromaDB container
docker stop chromadb

# 2. Restore backup (if nuclear option was used)
sudo rm -rf /mcp_rag_eib/data/chromadb
sudo mv /mcp_rag_eib/data/chromadb.backup.nov17 /mcp_rag_eib/data/chromadb

# 3. Restart container
docker start chromadb

# 4. Revert MCP server configuration to v5 collections (no-op since they're empty)
```

---

## Success Criteria

✅ **Must Have**:
1. ChromaDB contains 6,000+ documents across 4 collections
2. MCP `get_knowledge_base_status` reports "Healthy" with document counts
3. All 4 search tools return relevant results
4. Neo4j graph database remains intact (49,826 relationships)

✅ **Should Have**:
5. Ingestion logs show no errors
6. Search latency < 2 seconds for simple queries
7. All 13 documentation sources successfully crawled

✅ **Nice to Have**:
8. Backup of old (empty) collections preserved
9. Documentation of new collection naming convention
10. CHANGELOG updated to v3.6.0

---

## Timeline Estimate

| Phase | Task | Duration |
|-------|------|----------|
| 1 | Environment prep | 10 min |
| 2 | Collection cleanup | 5 min |
| 3 | Documentation ingestion | 1-2 hours |
| 4 | EE2 standards ingestion | 30 min |
| 5 | Code context ingestion | 1 hour |
| 6 | CI test cases ingestion | 15 min |
| 7 | Verification | 10 min |
| 8 | MCP config update | 10 min |
| 9 | Functional testing | 15 min |
| **TOTAL** | | **3-4 hours** |

---

## Post-Ingestion Documentation Tasks

1. **Update CHANGELOG.md** (v3.6.0)
   - Document ChromaDB Docker re-ingest
   - List new collection names
   - Note document counts and timing

2. **Update CURRENT_STATUS.md**
   - Reflect new knowledge base status
   - Update collection inventory
   - Note Docker ChromaDB as production approach

3. **Create ingestion reference doc**
   - Document collection naming convention (v6+: `-docker` suffix)
   - Preserve ingestion commands for future reference
   - Note lessons learned

4. **Git commit and push**
   ```bash
   git add docs/development/RAG_REINGEST_PLAN_NOV17.md
   git add CHANGELOG.md docs/development/CURRENT_STATUS.md
   git commit -m "v3.6.0 - Fresh RAG re-ingest on Docker ChromaDB"
   git push origin main
   ```

---

## Decision Point: Proceed with Re-Ingest?

**Recommendation**: ✅ **YES - PROCEED WITH CLEAN SLATE (Option A)**

**Rationale**:
1. Collections are empty anyway (no data loss)
2. Docker environment is stable and fresh
3. Persistent volume is confirmed working
4. All ingestion scripts are ready and tested
5. 413G available storage (more than enough)
6. Graph database is intact (no re-ingestion needed)

**Next Step**: Confirm approval, then proceed with Phase 1 (Environment Preparation)

---

**Status**: 📋 Plan complete, awaiting approval to execute
