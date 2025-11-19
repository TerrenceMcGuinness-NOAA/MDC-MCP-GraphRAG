# Phase 2 Semantic Annotations Integration Guide

**Version**: 1.0.0  
**Last Updated**: November 19, 2025  
**Purpose**: Ensure Phase 2 semantic annotations are always included when re-ingesting with new embedding models

---

## Overview

Phase 2 semantic annotations are **SME-validated corrections** to EE2 compliance standards stored in `sdd_framework/phase2_annotations/*.rst`. These annotations teach the AI system to avoid false positives by providing explicit anti-patterns, correct patterns, and guidance rules.

**Critical Requirement**: When changing embedding models (e.g., upgrading to Gemini Pro API), Phase 2 annotations MUST be re-ingested alongside standard documentation to maintain single source of truth.

---

## Architecture

```
Embedding Model Change Trigger
    ↓
Complete Re-Ingestion (reingest_all_with_phase2.sh)
    ├─→ Step 1: Ingest standard docs (global-workflow, EE2, UFS, etc.)
    ├─→ Step 2: Ingest Phase 2 annotations (sdd_framework/phase2_annotations/)
    ├─→ Step 3: Generate phase2_anti_patterns.json config
    └─→ Step 4: Validate results
```

---

## When to Use Complete Re-Ingestion

### Scenario 1: Upgrading Embedding Model
```bash
# Example: Switching from all-mpnet-base-v2 (768-dim) to Gemini Pro API
./scripts/reingest_all_with_phase2.sh global-workflow-docs-v5-0-0-gemini-pro
```

**Why**: Different embedding models produce different vector representations. All documents (including Phase 2 annotations) must use the same embedding model for consistent semantic search.

### Scenario 2: Changing Embedding Dimensions
```bash
# Example: Upgrading from 384-dim to 768-dim embeddings
./scripts/reingest_all_with_phase2.sh global-workflow-docs-v4-3-0-mpnet768
```

**Why**: ChromaDB collections are tied to specific embedding dimensions. Cannot mix 384-dim and 768-dim vectors in same collection.

### Scenario 3: Adding New Phase 2 Annotations
```bash
# Option A: Quick update (existing collection)
cd mcp_server_node
python3 scripts/ingest_ee2_enhanced_v5.py \
    ../sdd_framework/phase2_annotations \
    --collection ee2-standards-v6-0-0-corrected \
    --pattern new_annotation.rst

node scripts/generatePhase2Config.js

# Option B: Full re-ingest (new collection with all docs)
./scripts/reingest_all_with_phase2.sh ee2-standards-v6-1-0-updated
```

**Why**: New annotations need to be embedded and integrated into configuration for scan tool to use them.

---

## Usage

### Basic Re-Ingestion

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node
./scripts/reingest_all_with_phase2.sh <new_collection_name>
```

### With Gemini Pro API

```bash
# Set API key
export GOOGLE_API_KEY="your-gemini-pro-api-key"

# Update embedding model in ingest script
# Edit: scripts/ingest_documentation_week3.py
# Change: EMBEDDING_MODEL = "all-mpnet-base-v2"
# To: Use Google Generative AI embeddings

# Run complete re-ingestion
./scripts/reingest_all_with_phase2.sh global-workflow-docs-v5-0-0-gemini-pro
```

### Validation

After re-ingestion, verify:

```bash
# 1. Check collection size
python3 << 'EOF'
import chromadb
client = chromadb.HttpClient(host='localhost', port=8080)
coll = client.get_collection('global-workflow-docs-v5-0-0-gemini-pro')
print(f"Total documents: {coll.count()}")
EOF

# 2. Check Phase 2 annotations count
python3 << 'EOF'
import chromadb
client = chromadb.HttpClient(host='localhost', port=8080)
coll = client.get_collection('global-workflow-docs-v5-0-0-gemini-pro')
results = coll.get(limit=10000)
phase2_count = sum(1 for m in results['metadatas'] if 'phase2_annotations' in str(m.get('source_file', '')))
print(f"Phase 2 annotation chunks: {phase2_count}")
EOF

# 3. Verify config generated
ls -lh mcp_server_node/phase2_anti_patterns.json
python3 -c "import json; print(json.dumps(json.load(open('phase2_anti_patterns.json')), indent=2))" | head -50
```

---

## Integration Checklist

When performing complete re-ingestion:

- [ ] **Step 1**: Set new collection name following convention `*-v<major>-<minor>-<patch>-<model>`
- [ ] **Step 2**: Update embedding model configuration if changing (API keys, model names)
- [ ] **Step 3**: Run `reingest_all_with_phase2.sh` script
- [ ] **Step 4**: Verify Phase 2 annotations ingested (check document count)
- [ ] **Step 5**: Verify `phase2_anti_patterns.json` generated with expected pattern counts
- [ ] **Step 6**: Update MCP server config to use new collection
- [ ] **Step 7**: Restart MCP server
- [ ] **Step 8**: Test semantic search queries
- [ ] **Step 9**: Run Phase 2 testing protocol (5 test queries)
- [ ] **Step 10**: Update documentation with new collection name

---

## File Locations

### Phase 2 Annotations (Source)
```
/mcp_rag_eib/eib-mcp-rag-server/sdd_framework/phase2_annotations/
├── ee2_error_handling_sme_corrections.rst
├── err_chk_pattern_recognition.rst
└── [future annotations...]
```

### Ingestion Scripts
```
/mcp_rag_eib/eib-mcp-rag-server/mcp_server_node/scripts/
├── reingest_all_with_phase2.sh          # Complete re-ingestion wrapper
├── ingest_documentation_week3.py         # Standard docs ingestion
├── ingest_ee2_enhanced_v5.py            # Phase 2 annotations ingestion
└── generatePhase2Config.js              # Config generation from ChromaDB
```

### Generated Artifacts
```
/mcp_rag_eib/eib-mcp-rag-server/mcp_server_node/
└── phase2_anti_patterns.json            # Runtime config (gitignored)
```

### ChromaDB Collections
```
ChromaDB (http://localhost:8080)
├── ee2-standards-v6-0-0-corrected       # Current Phase 2 collection
├── global-workflow-docs-v4-2-0-unified  # Current standard docs
└── [future collections...]
```

---

## Troubleshooting

### Issue: Phase 2 annotations not appearing in new collection

**Cause**: Ingestion script failed or annotations not in expected directory

**Solution**:
```bash
# Check annotation files exist
ls -la ../sdd_framework/phase2_annotations/*.rst

# Manually run Phase 2 ingestion with verbose output
python3 scripts/ingest_ee2_enhanced_v5.py \
    ../sdd_framework/phase2_annotations \
    --collection <collection_name> \
    --pattern "*.rst"
```

### Issue: Config generation shows "unknown" for directive names

**Cause**: RST directive format doesn't match parser expectations

**Solution**: Verify directives use `mcp:` prefix:
```rst
✅ CORRECT:
.. mcp:anti_pattern:: pattern_name
   :category: error_handling

❌ WRONG:
.. ee2_directive::
   :type: anti_pattern
   :name: pattern_name
```

### Issue: Embedding dimension mismatch errors

**Cause**: Trying to add documents with different embedding dimensions to existing collection

**Solution**: Always create new collection when changing embedding models:
```bash
# Don't reuse old collection name
./scripts/reingest_all_with_phase2.sh NEW-collection-name-v5-0-0
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025-11-19 | Initial integration with `reingest_all_with_phase2.sh` |

---

## References

- **Phase 2 Hybrid Architecture Spec**: `docs/technical_specification/PHASE_2_HYBRID_ARCHITECTURE_SPECIFICATION.md`
- **Embedding Upgrade Report**: `docs/development/EMBEDDING_UPGRADE_PROGRESS_REPORT_NOV5.md`
- **MCP Tool Architecture**: `supported_repos/global-workflow.wiki/MCP_TOOL_ARCHITECTURE.md`
- **RAG Workflow Architecture**: `supported_repos/global-workflow.wiki/RAG_WORKFLOW_ARCHITECTURE.md`

---

**Contact**: Terry McGuinness (terry.mcguinness@noaa.gov)  
**Team**: NOAA EMC EIB - Global Workflow MCP Development
