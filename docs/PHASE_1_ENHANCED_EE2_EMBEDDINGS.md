# Phase 1: Enhanced EE2 Embeddings with Intent-Aware Metadata

**Date**: November 14, 2025  
**Version**: 5.0.0  
**Status**: Design Complete - Ready for Implementation

---

## Executive Summary

This document defines the implementation strategy for **Phase 1** of the MCP/RAG enhancement roadmap: building a specialized EE2 compliance embedding system with RST directive parsing and intent-aware semantic metadata. This work enables the "hyper-dimensional semantic manifold" vision for compliance analysis.

### Strategic Context

**Current State** (Post Phase 2 Consolidation):
- ✅ ChromaDB collection consolidated: v5-0-0 with 1,695 high-quality documents
- ✅ EE2VectorStore.js exists (620 lines) but **NOT integrated** with MCP tools
- ✅ 7 compliance categories defined but unused by semantic search tools
- ✅ Pragmatic tool design philosophy established (actionable violations, not descriptions)

**Phase 1 Goal**: Create specialized EE2 compliance collection with context-rich embeddings that enable:
- Intent-aware semantic search (validation vs guidance vs examples vs reference)
- Compliance category filtering (environment_variables, error_handling, etc.)
- Standard-level awareness (MUST vs SHOULD vs MAY requirements)
- Platform-specific guidance (Hera, Hercules, Orion, WCOSS2, Gaea)
- RST directive preservation for structured compliance metadata

---

## Technical Foundation

### 1. Source Material: nws-hpc-standards Repository

**Primary Source**: EE2 compliance standards from nws-hpc-standards repo

**Document Structure** (RST format):
```restructuredtext
.. mcp:standard:: environment_variables
   :category: environment_variables
   :level: must
   :intent: validation
   :platforms: hera,hercules,orion,wcoss2,gaea

Environment Variable Standards
==============================

All production scripts **MUST** check for required environment variables...

.. mcp:example::
   :category: environment_variables
   :intent: example

   ```bash
   if [[ -z "${COMROOT}" ]]; then
       echo "ERROR: COMROOT not defined"
       exit 1
   fi
   ```

.. mcp:guidance::
   :category: environment_variables
   :intent: guidance
   :platform: hera

   On Hera systems, COMROOT should be set to /scratch1/NCEPDEV/...
```

**Key RST Directives** (to be parsed):
- `.. mcp:standard::` - Core compliance requirement
- `.. mcp:example::` - Code example demonstrating compliance
- `.. mcp:guidance::` - Implementation guidance for developers
- `.. mcp:reference::` - Links to related standards or documentation
- `.. mcp:validation::` - Validation rules or test criteria

**Directive Attributes**:
- `:category:` - Compliance category (environment_variables, error_handling, etc.)
- `:level:` - Standard level (must, should, may)
- `:intent:` - Document intent (validation, guidance, example, reference)
- `:platform:` - Target HPC platform(s) (comma-separated)
- `:priority:` - Priority level (critical, high, medium, low)

### 2. EE2 Compliance Categories (7 Total)

From `EE2VectorStore.js` analysis:

```javascript
{
  'environment_variables': { weight: 2.5, keywords: [...] },
  'workflow_structure': { weight: 2.0, keywords: [...] },
  'error_handling': { weight: 2.5, keywords: [...] },
  'file_naming': { weight: 1.8, keywords: [...] },
  'production_utilities': { weight: 2.2, keywords: [...] },
  'code_standards': { weight: 1.5, keywords: [...] },
  'directory_structure': { weight: 1.8, keywords: [...] }
}
```

### 3. Intent-Aware Metadata Schema

**Enhanced Chunk Metadata**:
```json
{
  "source_url": "https://...",
  "source_file": "environment_variables.rst",
  "chunk_type": "semantic_section",
  "chunk_index": 3,
  
  "compliance_category": "environment_variables",
  "compliance_categories": ["environment_variables", "error_handling"],
  
  "intent": "validation",
  "intent_confidence": 0.95,
  
  "standard_level": "must",
  "priority": "critical",
  
  "platform": "hera,hercules,orion",
  "platform_specific": true,
  
  "semantic_tags": [
    "environment_check",
    "error_exit",
    "comroot_validation"
  ],
  
  "has_code_example": true,
  "example_language": "bash",
  
  "quality_score": 0.87,
  "importance_score": 2.5,
  
  "rst_directive": "mcp:standard",
  "rst_role": "validation",
  
  "created_at": "2025-11-14T15:50:00Z",
  "ingestion_version": "5.0.0"
}
```

---

## Implementation Architecture

### Component 1: RST Directive Parser

**Location**: `mcp_server_node/scripts/ingestion_base.py`

**New Class**: `RSTDirectiveParser`

```python
class RSTDirectiveParser:
    """Parse RST directives for MCP semantic metadata extraction"""
    
    MCP_DIRECTIVES = [
        'mcp:standard',
        'mcp:example',
        'mcp:guidance',
        'mcp:reference',
        'mcp:validation'
    ]
    
    def parse_document(self, rst_content: str) -> List[Dict]:
        """
        Parse RST document into structured sections with directive metadata
        
        Returns:
            List of dicts with {text, metadata, directive_type, attributes}
        """
        pass
    
    def extract_directive_metadata(self, directive_block: str) -> Dict:
        """Extract :attribute: values from directive block"""
        pass
    
    def identify_intent(self, text: str, directive: str) -> Tuple[str, float]:
        """
        Classify document intent with confidence score
        
        Returns:
            (intent, confidence) where intent in:
            - 'validation': Checking/testing compliance
            - 'guidance': Implementation instructions
            - 'example': Code examples demonstrating compliance
            - 'reference': Background/links to related material
        """
        pass
    
    def extract_code_blocks(self, text: str) -> List[Dict]:
        """Extract code examples with language detection"""
        pass
    
    def categorize_compliance(self, text: str, directive_attrs: Dict) -> List[str]:
        """
        Determine compliance categories based on:
        - Explicit :category: attribute
        - Keyword matching against category definitions
        - Semantic similarity to category descriptions
        
        Returns list of applicable categories
        """
        pass
```

**Key Features**:
- Parse RST directive syntax (`.. mcp:standard::`)
- Extract directive attributes (`:category:`, `:level:`, `:intent:`, etc.)
- Identify code blocks with language detection
- Classify document intent with ML-based confidence scoring
- Map content to compliance categories

### Component 2: Enhanced EE2 Ingester

**Location**: `mcp_server_node/scripts/ingest_ee2_enhanced_v5.py`

**New Class**: `EnhancedEE2Ingester(BaseIngester)`

```python
class EnhancedEE2Ingester(BaseIngester):
    """
    Specialized ingester for EE2 compliance documentation
    Inherits from BaseIngester in ingestion_base.py
    """
    
    def __init__(self, collection_name='ee2-standards-v5-0-0-enhanced'):
        super().__init__(
            collection_name=collection_name,
            embedding_model='all-mpnet-base-v2',
            chunk_size_range=(200, 2000),
            chunk_overlap=200
        )
        
        self.rst_parser = RSTDirectiveParser()
        self.ee2_categories = load_ee2_categories()  # From EE2VectorStore.js
        
    def process_rst_document(self, file_path: str, content: str) -> List[Dict]:
        """
        Process RST document with directive parsing
        
        Returns chunks with enhanced metadata
        """
        # Parse RST directives
        directive_sections = self.rst_parser.parse_document(content)
        
        # Chunk each directive section semantically
        chunks = []
        for section in directive_sections:
            section_chunks = self.semantic_chunker.chunk_by_headers(
                section['text'],
                min_size=200,
                max_size=2000
            )
            
            # Enrich each chunk with directive metadata
            for chunk in section_chunks:
                metadata = self.enrich_metadata(
                    chunk,
                    section['metadata'],
                    section['directive_type'],
                    section['attributes']
                )
                chunks.append({
                    'text': chunk['text'],
                    'metadata': metadata
                })
        
        return chunks
    
    def enrich_metadata(self, chunk: Dict, base_metadata: Dict,
                        directive_type: str, directive_attrs: Dict) -> Dict:
        """
        Add intent-aware metadata to chunk
        
        Combines:
        - Base metadata (URL, file, chunk index)
        - RST directive information
        - Compliance category classification
        - Intent detection
        - Platform specificity
        - Quality/importance scoring
        """
        
        text = chunk['text']
        
        # Start with base metadata
        metadata = base_metadata.copy()
        
        # Add directive information
        metadata['rst_directive'] = directive_type
        metadata['directive_attrs'] = directive_attrs
        
        # Extract explicit attributes
        metadata['compliance_category'] = directive_attrs.get('category', 'general')
        metadata['standard_level'] = directive_attrs.get('level', 'should')
        metadata['platform'] = directive_attrs.get('platform', 'all')
        metadata['priority'] = directive_attrs.get('priority', 'medium')
        
        # Classify intent
        intent, confidence = self.rst_parser.identify_intent(text, directive_type)
        metadata['intent'] = intent
        metadata['intent_confidence'] = confidence
        
        # Multi-category classification
        categories = self.rst_parser.categorize_compliance(text, directive_attrs)
        metadata['compliance_categories'] = categories
        
        # Extract semantic tags
        metadata['semantic_tags'] = self.extract_semantic_tags(text, categories)
        
        # Code example detection
        code_blocks = self.rst_parser.extract_code_blocks(text)
        metadata['has_code_example'] = len(code_blocks) > 0
        if code_blocks:
            metadata['example_language'] = code_blocks[0].get('language', 'unknown')
            metadata['example_count'] = len(code_blocks)
        
        # Quality scoring
        metadata['quality_score'] = self.compute_quality_score(text, metadata)
        
        # Importance scoring (from EE2VectorStore.js category weights)
        category_weight = self.ee2_categories.get(
            metadata['compliance_category'], {}
        ).get('weight', 1.0)
        metadata['importance_score'] = category_weight
        
        # Platform specificity
        metadata['platform_specific'] = metadata['platform'] != 'all'
        
        # Timestamps
        metadata['created_at'] = datetime.now().isoformat()
        metadata['ingestion_version'] = '5.0.0'
        
        return metadata
    
    def extract_semantic_tags(self, text: str, categories: List[str]) -> List[str]:
        """
        Extract semantic tags from text for enhanced searchability
        
        Uses:
        - Keyword extraction (TF-IDF or KeyBERT)
        - Named entity recognition
        - Category-specific patterns
        """
        pass
    
    def compute_quality_score(self, text: str, metadata: Dict) -> float:
        """
        Calculate quality score based on:
        - Text completeness (has intro, body, examples)
        - Metadata richness
        - Code example presence
        - Standard level (MUST > SHOULD > MAY)
        - RST directive structure
        """
        pass
```

**Ingestion Workflow**:
1. Clone/update nws-hpc-standards repository
2. Discover RST files in standards/ directory
3. Parse each RST file with RSTDirectiveParser
4. Chunk directive sections semantically (200-2000 chars)
5. Enrich chunks with intent-aware metadata
6. Generate embeddings with MPNet (768-dim)
7. Store in `ee2-standards-v5-0-0-enhanced` collection

### Component 3: EE2VectorStore Integration

**Location**: `mcp_server_node/src/rag/EE2VectorStore.js`

**Modifications Required**:

```javascript
class EE2VectorStore {
    constructor(collectionName = 'ee2-standards-v5-0-0-enhanced') {
        // Use new v5 collection instead of hardcoded name
        this.collectionName = collectionName;
        // ... existing initialization
    }
    
    async searchByIntent(query, intent, options = {}) {
        /**
         * Search EE2 standards filtered by document intent
         * 
         * @param {string} query - Search query
         * @param {string} intent - Intent filter: validation|guidance|example|reference
         * @param {object} options - Additional filters (category, platform, level)
         */
        
        const whereClause = {
            intent: intent
        };
        
        if (options.category) {
            whereClause.compliance_category = options.category;
        }
        
        if (options.platform) {
            whereClause.platform = { $contains: options.platform };
        }
        
        if (options.level) {
            whereClause.standard_level = options.level;
        }
        
        return await this.searchEE2Compliance(query, {
            ...options,
            where: whereClause
        });
    }
    
    async searchByCategory(query, category, options = {}) {
        /**
         * Search within specific compliance category
         */
        
        return await this.searchEE2Compliance(query, {
            ...options,
            where: {
                compliance_category: category
            }
        });
    }
    
    async getStandardsByLevel(level = 'must', options = {}) {
        /**
         * Retrieve all standards at specific requirement level
         * 
         * @param {string} level - must|should|may
         */
        
        return await this.collection.query({
            queryTexts: ['compliance standards requirements'],
            nResults: options.limit || 50,
            where: {
                standard_level: level
            }
        });
    }
}
```

### Component 4: MCP Tool Integration

**Location**: `mcp_server_node/src/tools/SemanticSearchTools.js`

**Updated Tool**: `search_ee2_standards`

```javascript
{
    name: 'search_ee2_standards',
    description: 'Search EE2 compliance standards with intent and category filtering',
    inputSchema: {
        type: 'object',
        properties: {
            query: {
                type: 'string',
                description: 'Search query for EE2 standards'
            },
            intent: {
                type: 'string',
                enum: ['validation', 'guidance', 'example', 'reference', 'any'],
                description: 'Filter by document intent',
                default: 'any'
            },
            category: {
                type: 'string',
                enum: [
                    'environment_variables',
                    'workflow_structure',
                    'error_handling',
                    'file_naming',
                    'production_utilities',
                    'code_standards',
                    'directory_structure',
                    'any'
                ],
                description: 'Filter by compliance category',
                default: 'any'
            },
            level: {
                type: 'string',
                enum: ['must', 'should', 'may', 'any'],
                description: 'Filter by standard requirement level',
                default: 'any'
            },
            platform: {
                type: 'string',
                enum: ['hera', 'hercules', 'orion', 'wcoss2', 'gaea', 'any'],
                description: 'Filter by HPC platform',
                default: 'any'
            },
            max_results: {
                type: 'number',
                description: 'Maximum results to return',
                default: 10
            }
        },
        required: ['query']
    }
}
```

**Implementation**:
```javascript
async function searchEE2Standards(args) {
    const { query, intent, category, level, platform, max_results } = args;
    
    // Initialize EE2VectorStore
    const ee2Store = new EE2VectorStore('ee2-standards-v5-0-0-enhanced');
    await ee2Store.initialize();
    
    // Build filter options
    const options = {
        limit: max_results || 10
    };
    
    if (category && category !== 'any') {
        options.category = category;
    }
    
    if (platform && platform !== 'any') {
        options.platform = platform;
    }
    
    if (level && level !== 'any') {
        options.level = level;
    }
    
    // Search with intent filtering
    const results = await (intent && intent !== 'any')
        ? ee2Store.searchByIntent(query, intent, options)
        : ee2Store.searchEE2Compliance(query, options);
    
    // Format results
    return formatEE2SearchResults(results);
}
```

---

## Implementation Plan

### Week 1: RST Parser Development

**Tasks**:
- [ ] Implement `RSTDirectiveParser` class in `ingestion_base.py`
- [ ] Unit tests for RST directive extraction
- [ ] Intent classification model training/selection
- [ ] Compliance category mapping from EE2VectorStore.js
- [ ] Code block extraction with language detection

**Deliverables**:
- `RSTDirectiveParser` class with full test coverage
- Intent classification accuracy >85%
- Category mapping validated against EE2VectorStore definitions

### Week 2: Enhanced Ingester Implementation

**Tasks**:
- [ ] Implement `EnhancedEE2Ingester` in `ingest_ee2_enhanced_v5.py`
- [ ] Metadata enrichment pipeline
- [ ] Quality scoring implementation
- [ ] Semantic tag extraction (TF-IDF or KeyBERT)
- [ ] Integration with nws-hpc-standards repo

**Deliverables**:
- Working ingester script with dry-run mode
- Sample output showing enhanced metadata
- Quality score validation

### Week 3: Collection Population & Validation

**Tasks**:
- [ ] Ingest nws-hpc-standards RST files into `ee2-standards-v5-0-0-enhanced`
- [ ] Validate metadata quality and completeness
- [ ] Cross-reference with EE2VectorStore.js category definitions
- [ ] Performance testing (search latency, relevance)
- [ ] Documentation of collection schema

**Deliverables**:
- Populated collection with >500 enhanced EE2 chunks
- Validation report showing metadata coverage
- Performance benchmarks

### Week 4: MCP Tool Integration

**Tasks**:
- [ ] Update `EE2VectorStore.js` to use v5 collection
- [ ] Implement intent-aware search methods
- [ ] Update `search_ee2_standards` MCP tool
- [ ] Integration testing with MCP server
- [ ] End-to-end workflow testing (search → results → compliance analysis)

**Deliverables**:
- EE2VectorStore fully integrated with MCP tools
- Updated tool documentation
- Integration test suite passing

---

## Success Criteria

### Functional Requirements

1. **RST Directive Parsing**: ✅ Extract all `mcp:*` directives with attributes
2. **Intent Classification**: ✅ Classify with >85% accuracy (validation/guidance/example/reference)
3. **Category Mapping**: ✅ Multi-category support with confidence scores
4. **Metadata Enrichment**: ✅ All 15+ metadata fields populated for each chunk
5. **Search Filtering**: ✅ Filter by intent, category, level, platform
6. **Code Example Detection**: ✅ Extract and language-tag code blocks

### Quality Metrics

- **Collection Size**: >500 EE2 compliance chunks
- **Metadata Coverage**: >95% chunks have all required fields
- **Search Relevance**: Top-3 results relevant >90% of queries
- **Search Latency**: <500ms for typical queries
- **Intent Accuracy**: >85% correct intent classification

### Integration Validation

- [ ] `search_ee2_standards` tool returns filtered results
- [ ] `analyze_ee2_compliance` tool uses EE2VectorStore
- [ ] `generate_compliance_report` includes intent-aware examples
- [ ] MCP health check shows v5 collection
- [ ] All existing MCP tools still functional

---

## Risk Mitigation

### Technical Risks

**Risk**: RST parsing failures on malformed documents  
**Mitigation**: Robust error handling, fallback to text-only parsing, validation suite

**Risk**: Intent classification accuracy too low  
**Mitigation**: Start with rule-based classifier, upgrade to ML if needed, manual validation sample

**Risk**: Collection size smaller than expected  
**Mitigation**: Supplement with global-workflow examples showing compliance, community contributions

**Risk**: EE2VectorStore.js integration breaks existing tools  
**Mitigation**: Feature flags, gradual rollout, comprehensive integration tests

### Process Risks

**Risk**: nws-hpc-standards repo not ready  
**Mitigation**: Use existing EE2 documentation as interim, parallel track for standards repo setup

**Risk**: SME availability for validation  
**Mitigation**: Automated quality checks, phased validation approach

---

## Future Enhancements (Post Phase 1)

### Phase 1B: SME Refinement Workflow

- Web UI for SMEs to review/refine metadata
- Feedback loop for intent classification improvement
- Community contribution workflow

### Phase 1C: Advanced Features

- **Compliance Impact Analysis**: Show which components affected by standard
- **Version Tracking**: Track standard evolution over time
- **Conflict Detection**: Identify contradictory standards
- **Priority Recommendations**: Suggest which standards to implement first

### Integration with Phase 3 (Operational Docs)

- Link EE2 standards to operational procedures
- Platform-specific compliance checklists
- Automated compliance monitoring dashboards

---

## Appendices

### A. EE2 Compliance Category Definitions

(From `EE2VectorStore.js`)

#### 1. environment_variables (weight: 2.5)
**Keywords**: environment, variable, export, ENV, PATH, COMROOT, DATAROOT  
**Description**: Standards for environment variable usage and validation

#### 2. workflow_structure (weight: 2.0)
**Keywords**: workflow, rocoto, job, task, dependency, sequence  
**Description**: Workflow design and orchestration patterns

#### 3. error_handling (weight: 2.5)
**Keywords**: error, exception, exit, trap, cleanup, failure  
**Description**: Error detection, reporting, and recovery procedures

#### 4. file_naming (weight: 1.8)
**Keywords**: filename, naming, convention, path, directory  
**Description**: File and directory naming standards

#### 5. production_utilities (weight: 2.2)
**Keywords**: utility, script, module, library, tool, function  
**Description**: Reusable utilities and production script patterns

#### 6. code_standards (weight: 1.5)
**Keywords**: style, format, documentation, comment, best practice  
**Description**: Code quality and documentation standards

#### 7. directory_structure (weight: 1.8)
**Keywords**: directory, folder, structure, hierarchy, organization  
**Description**: Repository and runtime directory organization

### B. Intent Classification Examples

**Validation Intent**:
```
"All scripts MUST check for the presence of required environment 
variables before execution. Use [[ -z "${VAR}" ]] to test."
```

**Guidance Intent**:
```
"When implementing error handling, consider using trap for cleanup:
trap 'cleanup_function' EXIT TERM INT"
```

**Example Intent**:
```bash
if [[ -z "${COMROOT}" ]]; then
    echo "ERROR: COMROOT not defined"
    exit 1
fi
```

**Reference Intent**:
```
"See EE2 Section 4.2.1 for additional environment variable requirements.
Related: [Workflow Structure Standards](#workflow-structure)"
```

### C. Collection Migration Strategy

**Old Collections** (preserve for comparison):
- `global-workflow-docs-v4-0-0-mpnet` (1852 docs)
- `global-workflow-docs-v4-1-0-enhanced` (222 docs)
- `global-workflow-docs-v4-2-0-unified` (148 docs)

**Consolidated Collection** (general documentation):
- `global-workflow-docs-v5-0-0-consolidated` (1695 docs) ✅

**New EE2 Collection** (specialized compliance):
- `ee2-standards-v5-0-0-enhanced` (target: >500 docs)

**Code Collection** (unchanged):
- `code_with_context` (242 docs)

**Future Collections**:
- `hpc-operations-v5-0-0` (Phase 3 - operational docs)
- `ee2-examples-v5-0-0` (Phase 1B - community examples)

---

## Document Control

**Author**: AI Coding Agent (GitHub Copilot + Claude Sonnet 4.5)  
**Reviewer**: Terry McGuinness (System Architect)  
**Status**: Design Complete - Awaiting Implementation Approval  
**Version**: 1.0  
**Last Updated**: November 14, 2025

**Change Log**:
- 2025-11-14: Initial design document created
- Based on: EE2_WORK_STATUS_NOV10.md, PRAGMATIC_COMPLIANCE_TOOL_DESIGN.md analysis
- Incorporates: Phase 2 consolidation results (v5-0-0-consolidated)
