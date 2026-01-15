# EE2 Enhanced Embeddings Workflow
**Semantic Compliance System via Source Annotation**

## Overview

Strategic shift from web crawling to **source-level semantic annotation** for EE2 compliance embeddings.

**Repository**: `nws-hpc-standards`  
**Branch**: `mcp_enhanced_embeddings` (isolated from develop)  
**Source**: RST/Markdown files  
**Goal**: Intent-aware compliance system, not just text search

---

## 📐 Roadmap Alignment

This workflow establishes the **EE2 semantic layer** that feeds into the GraphRAG roadmap:

| Downstream Phase | Relationship | How This Enables |
|------------------|--------------|------------------|
| Phase 22 | Validation | EE2 docs used as ground truth for benchmark queries |
| Phase 24 | GraphRAG | EE2 nodes linked in graph for speculative pre-fetch |

**Vision Reference**: [ADVANCED_FUTURE_WORK.md §3](../../docs/development/ADVANCED_FUTURE_WORK.md#3-true-graphrag-fusion)

---

## 🎯 Strategic Advantages

### OLD Approach ❌
- Web crawl Read the Docs HTML
- Generic text chunking
- Search/replace pattern matching
- No semantic structure
- No intent capture

### NEW Approach ✅
- **Source repository access**: Direct RST/MD files
- **Semantic tagging**: Compliance metadata in source
- **Intent annotation**: Mark purpose and requirements
- **Chunk control**: Precise boundary definition
- **Version control**: Track enhancements separately
- **Iterative refinement**: Tune without rebuilding docs

---

## 📁 Repository Structure

```
nws-hpc-standards/
├── docs/
│   ├── standards.rst          # Main EE2 standards (1214 lines)
│   ├── index.rst              # Documentation index
│   ├── conf.py                # Sphinx configuration
│   └── requirements.txt       # Doc build dependencies
├── .readthedocs.yaml          # RTD build config
└── README.md
```

**Branch Strategy:**
- `develop` → Production documentation (unchanged)
- `mcp_enhanced_embeddings` → MCP annotation layer (our work)

---

## 🏷️ Semantic Tagging Schema

### Compliance Metadata Tags

**1. Category Tags** (Primary classification)
```rst
.. mcp:compliance:: error_handling
   :priority: critical
   :type: mandatory
```

**2. Intent Tags** (Purpose specification)
```rst
.. mcp:intent:: fatal_error_format
   :description: All fatal errors must begin with "FATAL ERROR:"
   :enforcement: runtime_check
```

**3. Example Tags** (Code samples)
```rst
.. mcp:example:: err_check_usage
   :language: bash
   :context: production_utility
```

**4. Reference Tags** (Cross-linking)
```rst
.. mcp:see-also:: production_utilities
   :section: C
   :related: [err_exit, cpreq]
```

**5. Severity Tags** (Compliance level)
```rst
.. mcp:severity:: must
   :rationale: operational_stability
```

### Standard Categories

**Core Compliance Areas:**
- `error_handling` - Error messages, err_check, err_exit
- `environment_variables` - Standard vars, naming conventions
- `file_naming` - Directory structure, extensions
- `workflow_structure` - Job card, J-job, ex-script pattern
- `production_utilities` - prep_step, startmsg, postmsg, etc.
- `code_standards` - Formatting, documentation blocks
- `directory_structure` - Package layout, version files
- `restart_capability` - Cold start, checkpoint requirements

---

## 🔧 Implementation Plan

### Phase 1: Annotation Schema Design ✅ COMPLETE

**Tasks:**
1. ✅ Define tagging schema (above)
2. ✅ Create RST directive templates (`sdd_framework/templates/mcp_rst_directive_templates.md`)
3. ✅ Document annotation guidelines (`sdd_framework/templates/sme_review_guide.md`)
4. ✅ Test with pilot section (error_handling)

**Deliverables:**
- ✅ Annotation schema specification
- ✅ RST directive definitions
- ✅ Annotation style guide
- ✅ Pilot annotated section

---

### Phase 2: Source Annotation ✅ COMPLETE

**Status:** Annotations moved from `sdd_framework/phase2_annotations/` directly into `standards.rst`

**Tasks:**
1. ✅ Annotate Section A: Standard Environment Variables
   - Tagged variables with compliance metadata
   - Added intent descriptions
   - Linked related sections
   
2. ✅ Annotate Section C: Production Utilities
   - Tagged each utility (err_chk, err_exit, cpreq, etc.)
   - Marked usage patterns with `mcp:utility::` directives
   - Added anti-patterns with `mcp:anti_pattern::` directives
   
3. ✅ Annotate Standards Section
   - Tagged error handling requirements
   - Marked severity levels (must, must_not, should)
   - Added SME corrections for AI false positives

4. ✅ Annotate Workflow Section
   - Tagged script_debug_logging requirements
   - Marked J-job patterns

**Deliverables:**
- ✅ Fully annotated `standards.rst` (on `mcp_enhanced_embedings` branch)
- ✅ Tagged sections: `mcp:compliance::`, `mcp:intent::`, `mcp:anti_pattern::`, `mcp:utility::`
- ✅ SME corrections embedded: `mcp:sme_correction::`
- ✅ Intent metadata throughout

**Location:** `supported_repos/nws-hpc-standards/docs/standards.rst` (branch: `mcp_enhanced_embedings`)

---

### Phase 3: Enhanced Ingestion Pipeline ✅ COMPLETE

**Tasks:**
1. ✅ **RST Parser** - Extract annotated sections (`ingest_ee2_v7.py`)
   ```python
   # Regex patterns for mcp:* directives
   'anti_pattern': re.compile(r'\.\.\s+mcp:anti_pattern::\s*(\w*)\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
   'compliance': re.compile(r'\.\.\s+mcp:compliance::\s*(\w*)\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
   'intent': re.compile(r'\.\.\s+mcp:intent::\s*(\w*)\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
   ```

2. ✅ **Semantic Chunker** - Intelligent boundary detection (`ingestion_base.py`)
   ```python
   # MPNet 768-dim embeddings
   EMBEDDING_MODEL = "all-mpnet-base-v2"
   # Chunk by headers and semantic sections
   ```

3. ✅ **Metadata Enrichment** - Enhanced embeddings
   ```python
   # MCP directives as high-value chunks
   'doc_type': 'mcp_directive',
   'priority': 'high',
   'directive_type': directive_type
   ```

4. ✅ **MCP Tool: `analyze_ee2_compliance`** - Uses v7 collection

**Deliverables:**
- ✅ RST parser with directive support (`ingest_ee2_v7.py`)
- ✅ Semantic chunking engine (`ingestion_base.py`)
- ✅ Metadata-enriched embeddings (collection: `global-workflow-docs-v7-0-0`)
- ✅ MCP compliance tools (SemanticSearchTools, EE2ComplianceTools)

---

### Phase 4: Enhanced Compliance Tools ✅ COMPLETE

**Tasks:**
1. ✅ **`analyze_ee2_compliance`** - Intent-aware analysis
   - Uses category tags for precise matching
   - References SME corrections to avoid false positives
   - Returns anti-patterns with severity levels

2. ✅ **`search_documentation`** - Hybrid semantic + graph search
   - Query: "How to handle fatal errors?"
   - Returns: mcp:intent sections with context
   - Includes: Tagged examples, related utilities

3. ✅ **`generate_compliance_report`** - Category-specific guidance
   - Comprehensive EE2 compliance reports
   - Organized by severity (critical/high/medium/low)
   - Markdown format with tables

4. ✅ **`scan_repository_compliance`** - Full repo scanning
   - Analyzes entire repositories against EE2 standards
   - Returns structured compliance data

**Deliverables:**
- ✅ Intent-aware compliance analyzer
- ✅ Hybrid search tool (vector + graph)
- ✅ Compliance report generator
- ✅ Repository-wide scanning

**Validated:** Successfully tested on NOAA-EMC/seaice-concentration (Dec 4, 2025)

---

## 📊 Metadata Schema

### Embedding Metadata Structure

```json
{
  "chunk_id": "ee2_standards_error_handling_001",
  "source": "standards.rst",
  "section": "Standards > A. General Application Standards",
  "line_range": [45, 98],
  "compliance": {
    "category": "error_handling",
    "priority": "critical",
    "type": "mandatory",
    "severity": "must"
  },
  "intent": {
    "name": "fatal_error_format",
    "description": "All fatal errors must begin with 'FATAL ERROR:'",
    "enforcement": "runtime_check",
    "rationale": "operational_stability"
  },
  "examples": [
    {
      "id": "err_check_usage",
      "language": "bash",
      "context": "production_utility"
    }
  ],
  "related": [
    "production_utilities",
    "err_exit",
    "cpreq"
  ],
  "content": "Fatal errors must print a descriptive message beginning with \"FATAL ERROR:\"...",
  "embedding": [0.123, 0.456, ...]
}
```

---

## 🎯 Success Criteria

### Phase 1: Schema ✅ COMPLETE
- [x] Annotation schema defined
- [x] RST directives created
- [x] Style guide documented
- [x] Pilot section tested

### Phase 2: Annotation ✅ COMPLETE
- [x] Environment variables section annotated
- [x] Production utilities section annotated
- [x] Standards section annotated
- [x] Workflow section annotated
- [x] **Annotations moved to source** (`standards.rst` on `mcp_enhanced_embedings` branch)

### Phase 3: Pipeline ✅ COMPLETE
- [x] RST parser working (`ingest_ee2_v7.py`)
- [x] Semantic chunking operational (`ingestion_base.py`)
- [x] Metadata enrichment complete (MPNet 768-dim)
- [x] MCP ingestion tool functional (v7 collection)

### Phase 4: Tools ✅ COMPLETE
- [x] Intent-aware analyzer working (`analyze_ee2_compliance`)
- [x] Hybrid search operational (`search_documentation`)
- [x] Compliance report generator (`generate_compliance_report`)
- [x] Repository scanning (`scan_repository_compliance`)
- [x] **End-to-end validation:** seaice-concentration report (Dec 4, 2025)

---

## 🔄 Iterative Refinement Process

1. **Annotate** section in `mcp_enhanced_embeddings` branch
2. **Ingest** into vector store with metadata
3. **Test** compliance analysis accuracy
4. **Refine** annotations based on results
5. **Repeat** until quality threshold met
6. **Never merge to develop** - keep annotation layer separate

---

## 💡 Key Innovation

**This approach enables:**
- ✅ **Semantic understanding** vs text matching
- ✅ **Intent capture** vs pattern detection  
- ✅ **Category organization** vs flat search
- ✅ **Iterative tuning** vs static crawl
- ✅ **Version control** for embeddings
- ✅ **True compliance intelligence**

**Result:** Move from "find relevant text" to "understand compliance requirements" 🎯

---

## 📝 Next Steps

### Completed ✅
1. ~~Create RST directive templates for mcp:* tags~~
2. ~~Annotate pilot section (Standards > Error Handling)~~
3. ~~Build RST parser with directive support~~
4. ~~Test enhanced ingestion pipeline~~
5. ~~Validate improved compliance analysis~~

### Future Enhancements 🔮
1. **Expand annotation coverage** - Add more mcp:* directives to standards.rst
2. **Add mcp:example:: directives** - Link code examples to compliance rules
3. **Cross-repo validation** - Test on more NOAA-EMC repositories
4. **SME review cycle** - PhD linguist/annotator refinement of semantic tags
5. **Push mcp_enhanced_embedings branch** - Upstream to TerrenceMcGuinness-NOAA/nws-hpc-standards

**Status:** ✅ **OPERATIONAL** - All phases complete, system validated! 🎯

---

## 📊 Current System State (Dec 4, 2025)

| Component | Status | Location |
|-----------|--------|----------|
| Annotations | ✅ Live | `standards.rst` on `mcp_enhanced_embedings` branch |
| Ingestion | ✅ v7 | `ingest_ee2_v7.py`, `ingest_documentation_v7.py` |
| Collection | ✅ Active | `global-workflow-docs-v7-0-0` (3,746 docs) |
| Embeddings | ✅ MPNet | `all-mpnet-base-v2` (768-dim) |
| MCP Tools | ✅ 30 tools | UnifiedMCPServer v3.6.2 |
| Validation | ✅ Tested | seaice-concentration EE2 report |
