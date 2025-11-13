# EE2 Enhanced Embeddings Workflow
**Semantic Compliance System via Source Annotation**

## Overview

Strategic shift from web crawling to **source-level semantic annotation** for EE2 compliance embeddings.

**Repository**: `nws-hpc-standards`  
**Branch**: `mcp_enhanced_embeddings` (isolated from develop)  
**Source**: RST/Markdown files  
**Goal**: Intent-aware compliance system, not just text search

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

### Phase 1: Annotation Schema Design ✅

**Tasks:**
1. ✅ Define tagging schema (above)
2. ⏳ Create RST directive templates
3. ⏳ Document annotation guidelines
4. ⏳ Test with pilot section

**Deliverables:**
- Annotation schema specification
- RST directive definitions
- Annotation style guide
- Pilot annotated section

---

### Phase 2: Source Annotation

**Tasks:**
1. Annotate Section A: Standard Environment Variables
   - Tag each variable with compliance metadata
   - Add intent descriptions
   - Link related sections
   
2. Annotate Section C: Production Utilities
   - Tag each utility (err_check, err_exit, cpreq, etc.)
   - Mark usage patterns
   - Add examples with context
   
3. Annotate Standards Section
   - Tag error handling requirements
   - Mark severity levels (MUST, SHOULD, MAY)
   - Link to examples

4. Annotate Workflow Section
   - Tag job card requirements
   - Mark J-job patterns
   - Link to directory structure

**Deliverables:**
- Fully annotated standards.rst
- Tagged sections for all compliance areas
- Cross-referenced examples
- Intent metadata throughout

---

### Phase 3: Enhanced Ingestion Pipeline

**Tasks:**
1. **RST Parser** - Extract annotated sections
   ```javascript
   // Parse RST with Sphinx directives
   // Extract mcp:* directive content
   // Preserve structure and metadata
   ```

2. **Semantic Chunker** - Intelligent boundary detection
   ```javascript
   // Chunk by compliance category
   // Preserve mcp:* tags as metadata
   // Maintain cross-references
   ```

3. **Metadata Enrichment** - Enhance embeddings
   ```javascript
   // Add category to vector metadata
   // Include intent in embedding context
   // Link related sections
   ```

4. **MCP Tool: `ingest_enhanced_ee2_standards`**
   ```javascript
   {
     name: "ingest_enhanced_ee2_standards",
     description: "Ingest semantically-annotated EE2 standards",
     inputSchema: {
       type: "object",
       properties: {
         source_path: {
           type: "string",
           description: "Path to nws-hpc-standards repo"
         },
         branch: {
           type: "string",
           default: "mcp_enhanced_embeddings"
         },
         categories: {
           type: "array",
           items: { type: "string" },
           description: "Filter by compliance categories"
         }
       }
     }
   }
   ```

**Deliverables:**
- RST parser with directive support
- Semantic chunking engine
- Metadata-enriched embeddings
- MCP ingestion tool

---

### Phase 4: Enhanced Compliance Tools

**Tasks:**
1. **`analyze_ee2_compliance_enhanced`** - Intent-aware analysis
   ```javascript
   // Use category tags for precise matching
   // Reference intent descriptions
   // Suggest fixes based on examples
   ```

2. **`search_ee2_by_intent`** - Search by purpose
   ```javascript
   // Query: "How to handle fatal errors?"
   // Returns: mcp:intent::fatal_error_format sections
   // Includes: Tagged examples, related utilities
   ```

3. **`get_compliance_category`** - Category-specific guidance
   ```javascript
   // Input: "error_handling"
   // Returns: All tagged sections, examples, requirements
   // Organized: By severity (MUST/SHOULD/MAY)
   ```

**Deliverables:**
- Intent-aware compliance analyzer
- Category-based search tool
- Compliance guidance by category
- Enhanced recommendation engine

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

### Phase 1: Schema ✅
- [x] Annotation schema defined
- [ ] RST directives created
- [ ] Style guide documented
- [ ] Pilot section tested

### Phase 2: Annotation
- [ ] Environment variables section annotated
- [ ] Production utilities section annotated
- [ ] Standards section annotated
- [ ] Workflow section annotated

### Phase 3: Pipeline
- [ ] RST parser working
- [ ] Semantic chunking operational
- [ ] Metadata enrichment complete
- [ ] MCP ingestion tool functional

### Phase 4: Tools
- [ ] Intent-aware analyzer working
- [ ] Category search operational
- [ ] Compliance guidance by category
- [ ] Enhanced recommendations

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

1. Create RST directive templates for mcp:* tags
2. Annotate pilot section (Standards > Error Handling)
3. Build RST parser with directive support
4. Test enhanced ingestion pipeline
5. Validate improved compliance analysis

**Status:** Ready to start annotation! 🚀
