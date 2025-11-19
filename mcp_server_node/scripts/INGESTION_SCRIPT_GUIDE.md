# Ingestion Script Selection Guide

**Purpose**: Clear decision tree for selecting the correct ingestion script  
**Version**: 1.0.0  
**Last Updated**: November 19, 2025

---

## 🎯 Quick Decision Tree

```
START: What do you want to ingest?

├─ EVERYTHING (Standard docs + Phase 2 annotations)
│  └─→ USE: reingest_all_with_phase2.sh
│     Example: ./reingest_all_with_phase2.sh global-workflow-docs-v5-0-0
│     When: Changing embedding models (Gemini Pro), full system refresh
│
├─ Standard Documentation ONLY (Global Workflow, EE2, UFS, etc.)
│  └─→ USE: ingest_documentation_week3.py
│     Example: python3 ingest_documentation_week3.py --collection <name>
│     When: Updating web-based documentation without Phase 2 changes
│
├─ Phase 2 Annotations ONLY (sdd_framework/phase2_annotations/*.rst)
│  └─→ USE: ingest_ee2_enhanced_v5.py
│     Example: python3 ingest_ee2_enhanced_v5.py ../sdd_framework/phase2_annotations --collection <name>
│     When: Adding/updating semantic annotations without full re-ingest
│
├─ Python/Shell Code (for semantic code search)
│  ├─ Simple: Function-level embeddings
│  │  └─→ USE: ingest_code_embeddings.py
│  │     When: Quick code search without graph analysis
│  │
│  └─ Advanced: Graph-enriched embeddings (Neo4j + ChromaDB)
│     └─→ USE: ingest_code_graph_enriched_v6.py
│        When: Need dependency analysis, call graphs, impact analysis
│
├─ CI Test Case Documentation (YAML analysis)
│  └─→ USE: ingest_ci_test_cases.py
│     When: Analyzing test case structure and dependencies
│
└─ Local Markdown Files (docs/ directory)
   └─→ USE: ingest_local_docs_v4.py
      When: Testing ingestion with local files before web crawl
```

---

## 📊 Script Comparison Matrix

| Script | Purpose | Input | Output Collection | Use When |
|--------|---------|-------|-------------------|----------|
| **reingest_all_with_phase2.sh** | Complete system re-ingest | All sources | Any name | 🌟 **RECOMMENDED**: Full refresh, embedding model changes |
| **ingest_documentation_week3.py** | Standard docs (web crawl) | URLs | global-workflow-docs-* | Routine doc updates |
| **ingest_ee2_enhanced_v5.py** | Phase 2 annotations | RST files | ee2-standards-* | Phase 2 updates |
| **ingest_code_graph_enriched_v6.py** | Graph + vector code | Python/Shell | code-graph-* | Advanced code analysis |
| **ingest_code_embeddings.py** | Vector-only code | Python/Shell | code-embeddings-* | Simple code search |
| **ingest_ci_test_cases.py** | Test case docs | YAML files | ci-test-cases | CI/CD analysis |
| **ingest_local_docs_v4.py** | Local markdown | docs/ dir | local-docs-* | Testing/dev |

---

## 🎯 Common Use Cases

### Use Case 1: First-Time Setup (New User)

**Goal**: Get complete system running with all documentation

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node
./scripts/reingest_all_with_phase2.sh global-workflow-docs-v4-2-0-complete
```

**What it does**: 
- Ingests all standard documentation (Global Workflow, EE2, UFS, etc.)
- Ingests Phase 2 semantic annotations
- Generates phase2_anti_patterns.json
- Creates single unified collection

---

### Use Case 2: Upgrading to Gemini Pro Embeddings

**Goal**: Replace all embeddings with Gemini Pro API

```bash
# Set API key
export GOOGLE_API_KEY="your-api-key"

# Update embedding configuration
# (Edit scripts/ingest_documentation_week3.py to use Google embeddings)

# Complete re-ingest with new embeddings
./scripts/reingest_all_with_phase2.sh global-workflow-docs-v5-0-0-gemini-pro
```

**Why complete re-ingest**: Different embedding models create incompatible vector spaces. All documents must use same model.

---

### Use Case 3: Adding New Phase 2 Annotation

**Goal**: Add new semantic annotation without re-ingesting everything

```bash
# Create new RST file
vim ../sdd_framework/phase2_annotations/new_pattern.rst

# Ingest ONLY the new annotation
cd mcp_server_node
python3 scripts/ingest_ee2_enhanced_v5.py \
    ../sdd_framework/phase2_annotations \
    --collection ee2-standards-v6-0-0-corrected \
    --pattern new_pattern.rst

# Regenerate config
node scripts/generatePhase2Config.js
```

**When to use**: Phase 2 updates only, no embedding model change

---

### Use Case 4: Documentation Updated on ReadTheDocs

**Goal**: Refresh documentation after upstream changes (e.g., Global Workflow docs updated)

```bash
cd mcp_server_node
python3 scripts/ingest_documentation_week3.py \
    --collection global-workflow-docs-v4-2-0-unified

# Note: Phase 2 annotations unchanged, no need to re-ingest them
```

**When to use**: Routine doc updates, same embedding model

---

### Use Case 5: Code Analysis for Dependency Mapping

**Goal**: Enable semantic code search with graph relationships

```bash
cd mcp_server_node
python3 scripts/ingest_code_graph_enriched_v6.py \
    --directory ../supported_repos/global-workflow \
    --collection code-graph-v6-0-0 \
    --neo4j-uri bolt://localhost:7687
```

**When to use**: Need call graphs, dependency analysis, impact assessment

---

## 🚫 Deprecated Scripts (Do NOT Use)

| Script | Status | Reason | Use Instead |
|--------|--------|--------|-------------|
| ingest_documentation_v4_upgraded.py | ⚠️ DEPRECATED | Missing bug fixes | ingest_documentation_week3.py |
| ingest_documentation_v4_1_enhanced.py | ⚠️ DEPRECATED | Superseded by v4.2 | ingest_documentation_week3.py |
| ingest_documentation_v4_2_unified.py | ⚠️ DEPRECATED | Missing Phase 2 integration | reingest_all_with_phase2.sh |

**Rule**: If version number in filename, use highest version. If "week" naming, use latest week.

---

## 🔍 Script Details

### PRIMARY SCRIPT: reingest_all_with_phase2.sh

**Path**: `mcp_server_node/scripts/reingest_all_with_phase2.sh`

**What it does**:
1. Calls `ingest_documentation_week3.py` for standard docs
2. Calls `ingest_ee2_enhanced_v5.py` for Phase 2 annotations
3. Calls `generatePhase2Config.js` for runtime config
4. Validates results

**Arguments**:
- `<collection_name>`: Name for new ChromaDB collection

**Example**:
```bash
./scripts/reingest_all_with_phase2.sh global-workflow-docs-v5-0-0-complete
```

**Output**:
- ChromaDB collection with ~3000-5000 chunks
- `phase2_anti_patterns.json` config file
- Validation report

---

### STANDARD DOCS: ingest_documentation_week3.py

**Path**: `mcp_server_node/scripts/ingest_documentation_week3.py`

**What it ingests**:
- Global Workflow docs (readthedocs.io)
- EE2 HPC Standards (readthedocs.io)
- UFS Utils, UFS Weather Model (readthedocs.io)
- Rocoto, ecFlow, wxflow documentation
- Spack-stack, JEDI docs
- Style guides (Google Shell, PEP8, NumPy docstrings)

**Source**: `documentation_sources_config.py` (single source of truth)

**Arguments**:
```bash
python3 ingest_documentation_week3.py [OPTIONS]
  --collection NAME      ChromaDB collection name
  --verbose              Detailed output
  --dry-run              Preview without ingesting
```

**Example**:
```bash
python3 ingest_documentation_week3.py \
    --collection global-workflow-docs-v4-2-0-unified \
    --verbose
```

---

### PHASE 2 ANNOTATIONS: ingest_ee2_enhanced_v5.py

**Path**: `mcp_server_node/scripts/ingest_ee2_enhanced_v5.py`

**What it ingests**:
- RST files from `sdd_framework/phase2_annotations/`
- Parses `mcp:` directives (anti_pattern, correct_pattern, ai_guidance_rule)
- Extracts metadata (severity, false_positive_rate, sme_justification, evidence)

**RST Directive Types**:
- `mcp:anti_pattern::` - Prohibited patterns to avoid
- `mcp:correct_pattern::` - Approved implementations
- `mcp:ai_guidance_rule::` - Behavioral rules for AI
- `mcp:sme_correction::` - Expert corrections to false positives
- `mcp:sme_validation::` - Validation of correct behavior
- `mcp:context_types::` - Context-aware rules

**Arguments**:
```bash
python3 ingest_ee2_enhanced_v5.py DIRECTORY [OPTIONS]
  DIRECTORY              Path to RST files
  --collection NAME      ChromaDB collection (default: ee2-standards-v6-0-0-corrected)
  --pattern GLOB         File pattern (default: *.rst)
  --no-recursive         Don't scan subdirectories
```

**Example**:
```bash
python3 ingest_ee2_enhanced_v5.py \
    ../sdd_framework/phase2_annotations \
    --collection ee2-standards-v6-0-0-corrected \
    --pattern "*.rst"
```

---

### CODE ANALYSIS: ingest_code_graph_enriched_v6.py

**Path**: `mcp_server_node/scripts/ingest_code_graph_enriched_v6.py`

**What it does**:
- Parses Python AST and Shell scripts
- Builds Neo4j graph (IMPORTS, CALLS, DEFINES, DEPENDS_ON)
- Creates vector embeddings enriched with graph context
- Enables hybrid vector + graph search

**Use Cases**:
- "What functions call this?"
- "What files import this module?"
- "Show me the dependency chain"
- "What breaks if I change this?"

**Arguments**:
```bash
python3 ingest_code_graph_enriched_v6.py [OPTIONS]
  --directory PATH       Code directory to analyze
  --collection NAME      ChromaDB collection
  --neo4j-uri URI        Neo4j connection (default: bolt://localhost:7687)
  --file-pattern GLOB    File pattern (default: *.py,*.sh)
```

---

## 🔧 Configuration Files

### documentation_sources_config.py

**Location**: `mcp_server_node/scripts/documentation_sources_config.py`

**Purpose**: Single source of truth for documentation URLs

**Structure**:
```python
DOCUMENTATION_SOURCES = {
    'tier1_critical': [
        {'name': 'global-workflow', 'url': '...', 'priority': 1},
        {'name': 'ee2-standards', 'url': '...', 'priority': 1},
    ],
    'tier2_infrastructure': [...],
    'tier3_build_system': [...],
    'tier4_reference': [...]
}
```

**Used by**: `ingest_documentation_week3.py`, `reingest_all_with_phase2.sh`

---

## ✅ Validation After Ingestion

Always validate after ingestion:

```bash
# Check collection exists and has documents
python3 << 'EOF'
import chromadb
client = chromadb.HttpClient(host='localhost', port=8080)
coll = client.get_collection('your-collection-name')
print(f"Total documents: {coll.count()}")

# Check Phase 2 annotations present
results = coll.get(limit=10000)
phase2_count = sum(1 for m in results['metadatas'] 
                   if 'phase2_annotations' in str(m.get('source_file', '')))
print(f"Phase 2 chunks: {phase2_count}")
EOF

# Verify config generated
cat mcp_server_node/phase2_anti_patterns.json | python3 -m json.tool | head -50
```

---

## 🆘 Troubleshooting

### "Which script should I use?"

**Decision factors**:
1. **Changing embedding model?** → `reingest_all_with_phase2.sh`
2. **Just updating Phase 2 annotations?** → `ingest_ee2_enhanced_v5.py`
3. **Just updating docs (no Phase 2 changes)?** → `ingest_documentation_week3.py`
4. **First time setup?** → `reingest_all_with_phase2.sh`

### "Script not found"

Check you're in correct directory:
```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node
ls scripts/ingest*.py  # Should show all scripts
```

### "Import errors"

Ensure environment set up:
```bash
module load gcc/11.5.0
module load py-chromadb py-pydantic py-httpx
```

---

## 📝 Quick Reference Card

```
╔══════════════════════════════════════════════════════════════════╗
║              INGESTION SCRIPT QUICK REFERENCE                    ║
╠══════════════════════════════════════════════════════════════════╣
║ FULL RE-INGEST (Recommended for most cases)                     ║
║   ./scripts/reingest_all_with_phase2.sh <collection-name>       ║
║                                                                  ║
║ STANDARD DOCS ONLY (Web crawl, no Phase 2)                      ║
║   python3 scripts/ingest_documentation_week3.py --collection X  ║
║                                                                  ║
║ PHASE 2 ANNOTATIONS ONLY (RST files)                            ║
║   python3 scripts/ingest_ee2_enhanced_v5.py ../sdd_framework/   ║
║           phase2_annotations --collection X                      ║
║                                                                  ║
║ CODE ANALYSIS (Graph + Vector)                                  ║
║   python3 scripts/ingest_code_graph_enriched_v6.py              ║
║           --directory PATH --collection X                        ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## 📚 Related Documentation

- **Phase 2 Re-ingestion Integration**: `docs/development/PHASE_2_REINGESTION_INTEGRATION.md`
- **Phase 2 Hybrid Architecture**: `docs/technical_specification/PHASE_2_HYBRID_ARCHITECTURE_SPECIFICATION.md`
- **Embedding Upgrade History**: `docs/development/EMBEDDING_UPGRADE_PROGRESS_REPORT_NOV5.md`
- **Documentation Sources Config**: `mcp_server_node/scripts/documentation_sources_config.py`

---

**Maintainer**: Terry McGuinness (terry.mcguinness@noaa.gov)  
**Team**: NOAA EMC EIB - Global Workflow MCP Development  
**Version**: 1.0.0  
**Last Updated**: November 19, 2025
