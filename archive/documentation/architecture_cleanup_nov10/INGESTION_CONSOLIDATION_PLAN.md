# Ingestion Architecture Consolidation Plan

**Date**: November 10, 2025  
**Objective**: Consolidate v4.0 + v4.1 + EE2/GW-specific needs into clean, reusable architecture  
**Status**: Implementation Ready

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  BASE INGESTION LIBRARY (Shared Code)                              │
│  File: scripts/lib/ingestion_base.py                               │
├─────────────────────────────────────────────────────────────────────┤
│  - SemanticChunker (by headers, quality filtering)                 │
│  - ChromaDBClient (connection, collection mgmt)                     │
│  - URLCrawler (recursive, sitemap, single page)                     │
│  - LocalRepoParser (RST, Markdown)                                  │
│  - MetadataEnricher (keywords, hierarchy, quality scoring)          │
│  - EmbeddingManager (MPNet 768-dim)                                 │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
        ┌─────────────────────┼─────────────────────┐
        ↓                     ↓                     ↓
┌───────────────┐   ┌───────────────────┐   ┌──────────────────┐
│ General Docs  │   │ EE2 Standards     │   │ Global-Workflow  │
│ v4.2          │   │ Specialized       │   │ Specialized      │
├───────────────┤   ├───────────────────┤   ├──────────────────┤
│ - 10+ sources │   │ - Local repo      │   │ - Main docs      │
│ - Tiered      │   │ - SME annotations │   │ - Code analysis  │
│ - Sitemap     │   │ - Compliance cats │   │ - Neo4j trees    │
│ - Recursive   │   │ - RST parsing     │   │ - Dependencies   │
└───────────────┘   └───────────────────┘   └──────────────────┘
        ↓                     ↓                     ↓
┌─────────────────────────────────────────────────────────────────────┐
│  CHROMADB COLLECTIONS                                               │
├─────────────────────────────────────────────────────────────────────┤
│  - global-workflow-docs-v4-2-unified (general docs, all sources)    │
│  - ee2-standards-v1-0-annotated (EE2 with SME metadata)             │
│  - global-workflow-code-v1-0 (code with call trees)                 │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Code Reuse Strategy

### 1. Base Library (`scripts/lib/ingestion_base.py`)

**Core Classes**:

```python
class SemanticChunker:
    """Chunks documents by semantic sections (headers, paragraphs)"""
    - chunk_by_headers()
    - chunk_by_sections()
    - chunk_rst_document()  # For EE2
    - smart_split()
    - quality_filter()

class ChromaDBClient:
    """Manages ChromaDB connections and collections"""
    - connect()
    - get_or_create_collection()
    - add_documents_batch()
    - validate_embeddings()

class URLCrawler:
    """Crawls documentation websites"""
    - crawl_recursive()
    - fetch_sitemap()
    - fetch_single_page()
    - extract_links()
    - respect_robots_txt()

class LocalRepoParser:
    """Parses local documentation repositories"""
    - parse_rst_files()
    - parse_markdown_files()
    - extract_sections()
    - handle_sphinx_directives()

class MetadataEnricher:
    """Enriches chunks with metadata"""
    - extract_keywords()
    - calculate_quality_score()
    - build_hierarchy()
    - detect_code_blocks()
    - identify_compliance_categories()  # For EE2

class EmbeddingManager:
    """Manages embedding model and generation"""
    - load_model()  # MPNet 768-dim
    - generate_embeddings_batch()
    - cache_embeddings()
```

---

## Implementation Plan

### Phase 1: Create Base Library (3 hours)

**File**: `scripts/lib/ingestion_base.py`

**Tasks**:
1. Extract common code from v4.0 and v4.1
2. Merge SemanticChunker improvements from v4.1
3. Merge comprehensive source handling from v4.0
4. Add RST parsing support (for EE2)
5. Add compliance category detection
6. Add SME annotation support

**Key Improvements**:
- MPNet 768-dim embeddings (from v4.0)
- Semantic chunking (from v4.1)
- Recursive crawling (from v4.1)
- Quality filtering (from v4.1)
- Deduplication (from v4.1)
- RST parsing (NEW for EE2 local repo)
- Code block detection (for code examples)

### Phase 2: General Documentation Ingester v4.2 (2 hours)

**File**: `scripts/ingest_documentation_v4_2_unified.py`

**Features**:
- Uses base library
- 10+ sources from v4.0
- Quality improvements from v4.1
- Collection: `global-workflow-docs-v4-2-unified`

**Sources** (from v4.0):
```python
DOCUMENTATION_SOURCES = {
    'tier1_critical': [
        'global-workflow',
        'ee2-standards',  # Still crawl URL for general access
        'ufs-utils'
    ],
    'tier2_infrastructure': [
        'ufs-weather-model',
        'wxflow',
        'rocoto'
    ],
    'tier3_build_system': [
        'spack-stack'
    ],
    'tier4_reference': [
        'google-shell-style',
        'pep8',
        'numpy-docstrings'
    ]
}
```

### Phase 3: EE2 Standards Ingester (2-3 hours)

**File**: `scripts/ingest_ee2_standards.py`

**Features**:
- Uses base library
- Reads **local repo**: `/mcp_rag_eib/nws-hpc-standards/docs/`
- Parses RST files (Sphinx)
- SME annotation injection
- Compliance category tagging
- Collection: `ee2-standards-v1-0-annotated`

**Unique Features**:
```python
class EE2Ingester(BaseIngester):
    def parse_local_repo(self):
        """Parse local EE2 repo instead of URL crawling"""
        # Parse standards.rst (1214 lines)
        # Extract compliance categories
        # Preserve RST structure
        
    def inject_sme_annotations(self):
        """Add subject matter expert annotations"""
        # Load SME annotation file
        # Inject into metadata
        # Examples, best practices, common mistakes
        
    def tag_compliance_categories(self):
        """Tag with EE2 compliance categories"""
        categories = [
            'environment_variables',
            'workflow_structure',
            'error_handling',
            'file_naming',
            'production_utilities',
            'code_standards',
            'directory_structure'
        ]
```

**SME Annotation Format**:
```json
{
  "section": "Standard Environment Variables",
  "annotations": [
    {
      "type": "best_practice",
      "content": "Always quote variables: \"${VAR}\" not $VAR",
      "expert": "NCO Operations Team",
      "date": "2025-11-10"
    },
    {
      "type": "common_mistake",
      "content": "Forgetting to export variables in J-jobs",
      "expert": "Implementation Team"
    }
  ]
}
```

### Phase 4: Global-Workflow Ingester (3 hours)

**File**: `scripts/ingest_global_workflow.py`

**Features**:
- Uses base library
- Main documentation
- Code analysis integration
- Neo4j call tree metadata
- Collection: `global-workflow-docs-enhanced-v1-0`

**Unique Features**:
```python
class GlobalWorkflowIngester(BaseIngester):
    def __init__(self):
        super().__init__()
        self.neo4j_client = Neo4jClient()  # Connect to graph DB
        
    def enrich_with_call_trees(self, doc_chunks):
        """Add Neo4j call tree information to documentation chunks"""
        # For each code mention in docs
        # Query Neo4j for call tree
        # Add as metadata
        
    def link_code_examples(self):
        """Link documentation to actual code in Neo4j"""
        # Find code references in docs
        # Query Neo4j for matching files/functions
        # Create DOC_DESCRIBES relationships
        
    def analyze_dependencies(self):
        """Add dependency information from Neo4j"""
        # Component dependencies
        # Import relationships
        # Call chains
```

---

## File Structure

```
/mcp_server_node/scripts/
│
├── lib/                              # SHARED CODE
│   ├── __init__.py
│   ├── ingestion_base.py             # Base classes (NEW)
│   ├── chromadb_utils.py             # ChromaDB helpers
│   ├── neo4j_utils.py                # Neo4j helpers
│   └── parsing_utils.py              # RST/MD parsers
│
├── ingest_documentation_v4_2_unified.py   # GENERAL (10+ sources)
├── ingest_ee2_standards.py                # EE2 SPECIALIZED
├── ingest_global_workflow.py              # GW SPECIALIZED
│
├── archive/                          # LEGACY
│   └── ingestion_v3_v4/
│       ├── ingest_documentation_week3.py
│       ├── ingest_documentation_v4_upgraded.py
│       └── ingest_documentation_v4_1_enhanced.py
│
└── sme_annotations/                  # SME DATA
    ├── ee2_environment_variables.json
    ├── ee2_error_handling.json
    └── ee2_workflow_structure.json
```

---

## Migration Strategy

### Step 1: Create Base Library (Today)
```bash
# Create library structure
mkdir -p /mcp_rag_eib/mcp_server_node/scripts/lib
touch /mcp_rag_eib/mcp_server_node/scripts/lib/__init__.py

# Extract and merge code from v4.0 + v4.1
# Create ingestion_base.py with all shared classes
```

### Step 2: Build v4.2 Unified (Tomorrow)
```bash
# Merge v4.0 sources + v4.1 quality
python3 ingest_documentation_v4_2_unified.py --tier tier1_critical
python3 ingest_documentation_v4_2_unified.py --tier tier2_infrastructure
```

### Step 3: Build EE2 Specialized (Day 3)
```bash
# Create SME annotation files
# Build EE2 ingester with local repo parsing
python3 ingest_ee2_standards.py \
  --repo /mcp_rag_eib/nws-hpc-standards \
  --sme-annotations sme_annotations/
```

### Step 4: Build Global-Workflow Specialized (Day 4)
```bash
# Integrate with Neo4j
# Add call tree enrichment
python3 ingest_global_workflow.py \
  --neo4j-enrich \
  --link-code
```

### Step 5: Update Runtime Tools (Day 5)
```javascript
// Update UnifiedDataAccess.js to query new collections
const COLLECTIONS = {
  general: 'global-workflow-docs-v4-2-unified',
  ee2: 'ee2-standards-v1-0-annotated',
  code: 'global-workflow-code-v1-0'
};
```

### Step 6: Archive Legacy (Day 5)
```bash
# Move old scripts to archive
mv ingest_documentation_week3.py archive/ingestion_v3_v4/
mv ingest_documentation_v4_upgraded.py archive/ingestion_v3_v4/
mv ingest_documentation_v4_1_enhanced.py archive/ingestion_v3_v4/

# Remove unused VectorStore modules
mv src/rag/EE2VectorStore.js src/archive/experimental_rag/
mv src/rag/EnhancedVectorStore.js src/archive/experimental_rag/
```

---

## Key Design Decisions

### 1. Three Separate Collections

**Why not one collection?**
- Different use cases (general docs, compliance, code)
- Different metadata schemas
- Different query patterns
- Easier to version independently

**Tradeoff**: More complex queries (need to search multiple collections)
**Solution**: UnifiedDataAccess handles multi-collection queries

### 2. Local Repo for EE2 vs URL Crawling

**Advantages of local repo**:
- ✅ Authoritative source (git repo)
- ✅ Version controlled
- ✅ Parse RST directly (preserve structure)
- ✅ Add SME annotations
- ✅ No rate limiting
- ✅ Offline capability

**Keep URL crawling for general collection**: Public access, multiple sources

### 3. SME Annotations as JSON Files

**Why separate files?**
- ✅ Version controlled
- ✅ Easy to update (no code changes)
- ✅ Collaborative editing
- ✅ Audit trail

**Format**: JSON with section references, annotation types, attribution

### 4. Neo4j Integration for Global-Workflow

**Why integrate at ingestion time?**
- ✅ Pre-compute call trees (expensive queries)
- ✅ Enrich documentation with code context
- ✅ Link docs to actual implementations
- ✅ Faster runtime queries

---

## Quality Improvements Applied

From v4.1:
- ✅ Semantic chunking (by headers, not fixed size)
- ✅ Recursive crawling (follow all links)
- ✅ Quality filtering (skip navigation, boilerplate)
- ✅ Deduplication (content-based hashing)
- ✅ Rich metadata (hierarchy, keywords, quality scores)

From v4.0:
- ✅ MPNet 768-dim embeddings
- ✅ Comprehensive source list (10+ sources)
- ✅ Tiered priority system
- ✅ Sitemap support (ReadTheDocs)
- ✅ Multiple doc types (readthedocs, github_pages, single_page)

New for EE2:
- ✅ Local repo parsing (RST)
- ✅ SME annotation injection
- ✅ Compliance category tagging
- ✅ Code example extraction

New for Global-Workflow:
- ✅ Neo4j call tree integration
- ✅ Code-to-docs linking
- ✅ Dependency metadata

---

## Testing Plan

### Unit Tests
```python
# test_ingestion_base.py
test_semantic_chunker()
test_rst_parser()
test_metadata_enricher()
test_quality_scoring()
```

### Integration Tests
```bash
# Test v4.2 unified
python3 ingest_documentation_v4_2_unified.py --dry-run

# Test EE2 specialized
python3 ingest_ee2_standards.py --dry-run

# Test global-workflow specialized
python3 ingest_global_workflow.py --dry-run
```

### Validation
```python
# Validate collections
- Document counts
- Metadata completeness
- Quality score distribution
- Deduplication effectiveness
- Embedding dimensions (768)
```

---

## Timeline

| Phase | Duration | Deliverable |
|-------|----------|-------------|
| 1. Base library | 3 hours | `scripts/lib/ingestion_base.py` |
| 2. v4.2 unified | 2 hours | `ingest_documentation_v4_2_unified.py` |
| 3. EE2 specialized | 3 hours | `ingest_ee2_standards.py` + SME files |
| 4. GW specialized | 3 hours | `ingest_global_workflow.py` |
| 5. Runtime updates | 2 hours | UnifiedDataAccess.js updates |
| 6. Testing | 2 hours | Validation + fixes |
| 7. Documentation | 1 hour | Architecture docs |
| **Total** | **16 hours** | **Complete ingestion architecture** |

---

## Success Criteria

✅ Single base library with 90%+ code reuse  
✅ v4.2 unified ingests 10+ sources with v4.1 quality  
✅ EE2 ingester uses local repo with SME annotations  
✅ Global-workflow ingester enriched with Neo4j  
✅ All collections use MPNet 768-dim embeddings  
✅ Legacy code archived, not deleted  
✅ Runtime tools updated to use new collections  
✅ Documentation complete (ARCHITECTURE.md)  

---

## Next Step

**Ready to start Phase 1**: Create base library by extracting and merging code from v4.0 + v4.1.

Shall I proceed with creating `scripts/lib/ingestion_base.py`?
