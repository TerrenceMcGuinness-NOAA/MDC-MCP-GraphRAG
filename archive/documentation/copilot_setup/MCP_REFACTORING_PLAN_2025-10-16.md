# MCP System Refactoring Plan - Context7-Inspired Graph RAG Architecture
**Date**: 2025-10-16  
**Status**: Planning Phase  
**Goal**: Refactor MCP tools to leverage Neo4j Graph Database + ChromaDB Vector Store

---

## 📊 Current System State Assessment

### ✅ Infrastructure Complete (Phase 1-2)
- **ChromaDB**: Running on port 8080 (systemd service)
- **Neo4j**: Running in Docker (global-workflow-neo4j)
  - Credentials: neo4j/gfsworkflow2025
  - Port: 7474 (Browser), 7687 (Bolt)
- **LangFlow**: Docker container on port 7860
- **Persistent Storage**: `/mcp_rag_eib` (25GB dedicated drive)

### ✅ Initial Ingestion Complete (Phase 2.5)
**Completed Ingestions**:
- ✅ Python code structure → Neo4j (178 functions, 27 classes, 641 imports, 2,206 calls)
- ✅ Shell code structure → Neo4j
- ✅ CMake build system → Neo4j
- ✅ Documentation → ChromaDB (2 collections: `global-workflow-docs`, `global_workflow_docs`)

**Neo4j Graph Structure**:
```cypher
Node Labels: File, Function, Class, Module
Relationships: IMPORTS, CALLS, DEFINES
Total Nodes: ~300
Total Relationships: ~2,800
```

**ChromaDB Collections**:
```json
[
  "global-workflow-docs",      // Documentation collection
  "global_workflow_docs"        // Duplicate - needs cleanup
]
```

### 🔧 Current MCP Architecture

**Repository Structure** (Source of Truth):
```
/mcp_rag_eib/global-workflow_MCP_node.js-RAG/dev/ci/scripts/utils/Copilot/mcp_server_node/
├── src/
│   ├── core/
│   │   └── BaseServer.js                    # MCP protocol handler
│   ├── tools/
│   │   ├── WorkflowTools.js                 # Basic workflow tools (8 tools)
│   │   ├── RAGTools.js                      # ChromaDB semantic search (7 tools)
│   │   ├── EnhancedRAGTools.js              # Advanced RAG (9 tools)
│   │   └── GitHubTools.js                   # GitHub integration (4 tools)
│   ├── ingestion/
│   │   ├── DocumentationIngester.js         # Web crawler
│   │   ├── WebCrawler.js                    # URL fetching
│   │   ├── SemanticChunker.js               # Content chunking
│   │   ├── neo4j/
│   │   │   ├── CodeStructureIngester.js     # Python AST → Neo4j
│   │   │   └── parse-python-ast.py          # Python parser
│   │   └── [URLFetcher, RobotsTxt, etc.]
│   └── UnifiedMCPServer.js                  # Main server (combines all tools)
└── [test files, startup scripts]
```

**Runtime Deployment**:
```
/mcp_rag_eib/mcp_server_node/
├── src/                          # COPIED from repo (needs sync strategy)
├── node_modules/                 # 407+ packages
├── bin/                          # Startup scripts
├── knowledge-base/               # Empty (for future use)
├── database/                     # Empty (for future use)
└── logs/                         # Runtime logs
```

**Issues Identified**:
1. ❌ **Duplication**: Runtime copies repo files (sync problems)
2. ❌ **No Graph RAG Integration**: Tools don't query Neo4j yet
3. ❌ **Inconsistent Collection Names**: ChromaDB has duplicate collections
4. ❌ **No Multi-Dimensional Search**: Can't combine graph + vector queries
5. ❌ **Missing Context7 Patterns**: No intelligent code chunking with relationships
6. ❌ **Tool Overlap**: RAGTools vs EnhancedRAGTools (redundancy)

---

## 🎯 Refactoring Objectives

### Primary Goals
1. **Unified Data Access Layer**: Single interface for Neo4j + ChromaDB
2. **Graph-Enhanced RAG**: Combine relationship graphs with semantic search
3. **Context7-Inspired Chunking**: Code chunks with dependency context
4. **Clean Separation**: Repo (development) vs Runtime (deployment)
5. **Modular Tools**: Clear tool boundaries, no redundancy

### Success Criteria
- [ ] All MCP tools can query both Neo4j and ChromaDB
- [ ] Code search returns results with dependency context
- [ ] Error diagnosis uses call graphs + historical patterns
- [ ] Single source of truth for ingested data
- [ ] Clean deployment process (repo → runtime sync)
- [ ] Comprehensive test coverage

---

## 📐 New Architecture Design

### Tier 1: Data Access Layer (NEW)

**Location**: `src/data/` (new directory)

```
src/data/
├── GraphDatabase.js              # Neo4j connection & queries
├── VectorDatabase.js             # ChromaDB connection & queries
├── UnifiedDataAccess.js          # Combined graph + vector queries
└── QueryBuilder.js               # DSL for complex queries
```

**Features**:
- Connection pooling
- Query caching
- Error handling
- Health checks
- Metrics/logging

**Example API**:
```javascript
// Graph-enhanced semantic search
const results = await unifiedData.searchWithContext({
  query: "How do I fix import errors in task files?",
  includeGraph: true,  // Add dependency context
  collections: ['code_knowledge', 'error_patterns'],
  graphFilters: {
    nodeLabels: ['File', 'Function'],
    relationships: ['IMPORTS', 'CALLS']
  }
});

// Result structure:
{
  semanticResults: [...],        // ChromaDB vector matches
  graphContext: {
    dependencies: [...],          // Related files via imports
    callers: [...],               // Functions that call this
    callees: [...]                // Functions this calls
  },
  combinedScore: 0.92            // Hybrid relevance score
}
```

### Tier 2: Tool Modules (REFACTORED)

**New Organization**:
```
src/tools/
├── core/
│   ├── WorkflowStructureTools.js     # Read-only structure queries
│   └── SystemConfigTools.js          # Platform configs, versions
├── search/
│   ├── SemanticSearchTools.js        # Pure vector search
│   ├── GraphSearchTools.js           # Pure graph queries
│   └── HybridSearchTools.js          # Combined graph + vector
├── analysis/
│   ├── CodeAnalysisTools.js          # AST, dependencies, patterns
│   ├── ErrorDiagnosisTools.js        # Error logs + call graphs
│   └── EE2ComplianceTools.js         # Compliance checking
└── integration/
    ├── GitHubTools.js                # GitHub API (existing)
    └── OperationalGuidanceTools.js   # HPC-specific guidance
```

**Key Changes**:
1. **Consolidate RAGTools + EnhancedRAGTools** → New search/ directory
2. **Split WorkflowTools** → core/ (structure) + search/ (queries)
3. **New Tool Categories**: analysis/, integration/
4. **All tools use UnifiedDataAccess** for data queries

### Tier 3: Ingestion Pipeline (ENHANCED)

**Context7-Inspired Enhancements**:

```
src/ingestion/
├── orchestration/
│   ├── IngestionOrchestrator.js      # Pipeline coordination
│   └── IngestionScheduler.js         # Incremental updates
├── extractors/
│   ├── CodeExtractor.js              # Language-agnostic AST
│   ├── DependencyExtractor.js        # Import/include graphs
│   └── MetadataExtractor.js          # Annotations, comments
├── chunkers/
│   ├── ContextAwareChunker.js        # NEW: Code + context windows
│   ├── SemanticChunker.js            # Existing (enhanced)
│   └── ChunkRelationshipMapper.js    # NEW: Link chunks via graph
├── loaders/
│   ├── Neo4jLoader.js                # Graph database writes
│   ├── ChromaDBLoader.js             # Vector database writes
│   └── DualLoader.js                 # Coordinated writes
└── neo4j/
    ├── CodeStructureIngester.js      # Existing (keep)
    ├── ShellIngester.js              # Existing (keep)
    └── CMakeIngester.js              # Existing (keep)
```

**Context7 Pattern - Code Chunking Example**:
```javascript
// Instead of this (line-based):
chunk = {
  text: "function calculateTotal(items) { ... }",
  metadata: { file: "utils.py", lines: "45-52" }
}

// Do this (context-aware):
chunk = {
  text: "function calculateTotal(items) { ... }",
  context: {
    imports: ["from typing import List", "import numpy as np"],
    dependencies: ["Item", "TaxCalculator"],  // From Neo4j graph
    calledBy: ["processOrder", "generateInvoice"],
    calls: ["validateItems", "applyDiscount"],
    docstring: "Calculate total price including tax...",
    relatedChunks: ["chunk_id_123", "chunk_id_456"]  // Similar functions
  },
  metadata: { 
    file: "ush/python/pygfs/utils/pricing.py",
    lines: "45-52",
    class: null,
    complexity: 12  // Cyclomatic complexity from AST
  }
}
```

---

## 🔧 Refactoring Implementation Plan

### Phase 1: Data Access Layer (Week 1)

**Tasks**:
1. Create `src/data/` directory structure
2. Implement `GraphDatabase.js`
   - Neo4j connection with Bolt driver
   - Common query patterns (find imports, trace calls, etc.)
   - Connection pooling and health checks
3. Implement `VectorDatabase.js`
   - ChromaDB client with collection management
   - Embedding generation (Xenova transformers)
   - Batch operations for performance
4. Implement `UnifiedDataAccess.js`
   - Hybrid query methods
   - Result merging and scoring
   - Cache layer (Redis optional, in-memory for now)
5. Write comprehensive tests
   - Unit tests for each database client
   - Integration tests for unified queries
   - Performance benchmarks

**Deliverables**:
- [ ] `src/data/GraphDatabase.js` (100% test coverage)
- [ ] `src/data/VectorDatabase.js` (100% test coverage)
- [ ] `src/data/UnifiedDataAccess.js` (90% test coverage)
- [ ] Test suite in `src/data/__tests__/`
- [ ] Documentation: `docs/DATA_ACCESS_LAYER.md`

### Phase 2: Tool Consolidation (Week 2)

**Tasks**:
1. **Audit existing tools**:
   ```bash
   # List all current tools
   grep -r "registerTool" src/tools/*.js | wc -l
   # Expected: ~28 tools across 4 files
   ```

2. **Consolidate RAGTools + EnhancedRAGTools**:
   - Create `src/tools/search/SemanticSearchTools.js`
   - Migrate unique tools from both
   - Remove duplicates
   - Update to use `UnifiedDataAccess`

3. **Refactor WorkflowTools**:
   - Split into `WorkflowStructureTools.js` (read structure)
   - Move search functions to `HybridSearchTools.js`

4. **Create new tool modules**:
   - `GraphSearchTools.js` - Pure Neo4j queries
   - `HybridSearchTools.js` - Combined queries
   - `CodeAnalysisTools.js` - Dependency analysis
   - `ErrorDiagnosisTools.js` - Error patterns + call graphs

5. **Update UnifiedMCPServer.js**:
   - Register new tool modules
   - Remove old modules
   - Add configuration flags

**Deliverables**:
- [ ] Consolidated tool modules (8-10 files)
- [ ] Total tool count: ~25-30 (deduplicated)
- [ ] All tools using `UnifiedDataAccess`
- [ ] Updated `UnifiedMCPServer.js`
- [ ] Migration guide: `docs/TOOL_MIGRATION.md`

### Phase 3: Context7 Ingestion (Week 3)

**Tasks**:
1. **Implement ContextAwareChunker**:
   - Extract code with surrounding context
   - Use Neo4j to fetch related code
   - Generate relationship metadata

2. **Implement ChunkRelationshipMapper**:
   - Link chunks via Neo4j relationships
   - Store chunk IDs in graph nodes
   - Create RELATED_TO relationships between chunks

3. **Enhanced Code Ingestion**:
   - Re-ingest Python code with context
   - Generate embeddings for enhanced chunks
   - Store in new ChromaDB collection: `code_with_context`

4. **Dual Loader Implementation**:
   - Coordinate Neo4j + ChromaDB writes
   - Transactional consistency (best effort)
   - Rollback on failures

**Deliverables**:
- [ ] `src/ingestion/chunkers/ContextAwareChunker.js`
- [ ] `src/ingestion/chunkers/ChunkRelationshipMapper.js`
- [ ] `src/ingestion/loaders/DualLoader.js`
- [ ] New ChromaDB collection: `code_with_context`
- [ ] Enhanced graph nodes with `chunkId` property
- [ ] Documentation: `docs/CONTEXT7_CHUNKING.md`

### Phase 4: Cleanup & Deployment (Week 4)

**Tasks**:
1. **Clean up ChromaDB**:
   - Merge duplicate collections
   - Standardize collection naming
   - Archive old collections

2. **Repository vs Runtime Separation**:
   - Create deployment script: `deploy-to-runtime.sh`
   - Define which files are deployed
   - Automate sync process
   - Document deployment procedure

3. **Clean up deprecated files**:
   - Remove old server scripts (mcp-server-rag.js, etc.)
   - Archive test files
   - Update documentation

4. **Integration Testing**:
   - End-to-end tool testing
   - Performance benchmarks
   - Load testing (concurrent users)

5. **Documentation Updates**:
   - Architecture diagrams
   - API documentation
   - Deployment guide
   - Developer guide

**Deliverables**:
- [ ] `bin/deploy-to-runtime.sh` (automated deployment)
- [ ] Clean ChromaDB collections (3-5 collections)
- [ ] Archived old code in `archive/` directory
- [ ] Complete test suite (unit + integration)
- [ ] Updated documentation (5+ docs)
- [ ] Performance report

---

## 🗂️ ChromaDB Collection Design

### Proposed Collections (After Cleanup)

```javascript
collections = [
  {
    name: "code_with_context",           // NEW: Context7-enhanced code
    description: "Source code chunks with dependency context",
    metadata_fields: [
      "file_path", "language", "function_name", "class_name",
      "imports", "dependencies", "called_by", "calls",
      "complexity", "lines", "chunk_type", "related_chunks"
    ]
  },
  {
    name: "documentation",                // Consolidated from duplicates
    description: "Official documentation, guides, READMEs",
    metadata_fields: [
      "url", "title", "section", "doc_type", "last_updated"
    ]
  },
  {
    name: "error_patterns",               // NEW: Historical errors
    description: "Error logs with resolution patterns",
    metadata_fields: [
      "error_type", "component", "timestamp", "severity",
      "resolution_status", "resolution_method", "related_code"
    ]
  },
  {
    name: "github_intelligence",          // NEW: Issues, PRs, commits
    description: "GitHub issues, PRs, discussions",
    metadata_fields: [
      "type", "number", "title", "author", "labels",
      "state", "created_at", "updated_at"
    ]
  },
  {
    name: "ee2_compliance",                // NEW: EE2 requirements
    description: "EE2 compliance requirements and examples",
    metadata_fields: [
      "requirement_id", "category", "severity",
      "example_type", "compliant"
    ]
  }
]
```

### Migration Plan
```bash
# 1. Export existing data
node scripts/export-collection.js global-workflow-docs > backup-docs.json

# 2. Create new collections
node scripts/create-collections.js

# 3. Import to new collection
node scripts/import-collection.js backup-docs.json documentation

# 4. Verify data
node scripts/verify-migration.js

# 5. Delete old collections
node scripts/cleanup-collections.js
```

---

## 📁 Repository vs Runtime Strategy

### Problem
- **Current**: Manual copying from repo → runtime
- **Issues**: Version drift, unclear source of truth, deployment errors

### Solution: Automated Deployment

**deployment-manifest.json**:
```json
{
  "version": "2.0.0",
  "sourceRoot": "/mcp_rag_eib/global-workflow_MCP_node.js-RAG/dev/ci/scripts/utils/Copilot/mcp_server_node",
  "targetRoot": "/mcp_rag_eib/mcp_server_node",
  "deploymentRules": [
    {
      "source": "src/**/*.js",
      "target": "src/",
      "action": "sync",
      "preserve": []
    },
    {
      "source": "package.json",
      "target": "./",
      "action": "copy"
    },
    {
      "source": "bin/*.sh",
      "target": "bin/",
      "action": "copy",
      "permissions": "755"
    }
  ],
  "excludePatterns": [
    "**/__tests__/**",
    "**/test/**",
    "**/*.test.js",
    "**/node_modules/**"
  ],
  "postDeploy": [
    "cd /mcp_rag_eib/mcp_server_node && npm install --production",
    "sudo systemctl restart mcp-server-persistent.service"
  ]
}
```

**bin/deploy-to-runtime.sh**:
```bash
#!/bin/bash
# Deployment script using manifest

MANIFEST="/mcp_rag_eib/global-workflow_MCP_node.js-RAG/dev/ci/scripts/utils/Copilot/mcp_server_node/deployment-manifest.json"

echo "🚀 Deploying MCP Server to Runtime..."
node /mcp_rag_eib/SETUP/deploy-mcp-server.js --manifest "$MANIFEST"

if [ $? -eq 0 ]; then
  echo "✅ Deployment successful"
  echo "📊 Verifying service..."
  sleep 3
  sudo systemctl status mcp-server-persistent.service | head -10
else
  echo "❌ Deployment failed"
  exit 1
fi
```

---

## 🧪 Testing Strategy

### Test Pyramid

```
                    E2E Tests (5%)
                  ┌─────────────┐
                  │ Tool chains │
                  └─────────────┘
              Integration Tests (25%)
          ┌───────────────────────────┐
          │ Tool + Data Access        │
          │ Ingestion pipelines       │
          └───────────────────────────┘
            Unit Tests (70%)
    ┌─────────────────────────────────────┐
    │ Data access methods                 │
    │ Tool individual functions           │
    │ Chunking algorithms                 │
    └─────────────────────────────────────┘
```

### Test Files Structure
```
src/
├── data/
│   ├── __tests__/
│   │   ├── GraphDatabase.test.js
│   │   ├── VectorDatabase.test.js
│   │   └── UnifiedDataAccess.test.js
├── tools/
│   ├── search/
│   │   └── __tests__/
│   │       ├── SemanticSearchTools.test.js
│   │       └── HybridSearchTools.test.js
│   └── analysis/
│       └── __tests__/
│           └── CodeAnalysisTools.test.js
└── ingestion/
    ├── chunkers/
    │   └── __tests__/
    │       └── ContextAwareChunker.test.js
```

### Test Commands
```bash
# Unit tests
npm test -- --testPathPattern=__tests__

# Integration tests
npm run test:integration

# E2E tests
npm run test:e2e

# Coverage report
npm run test:coverage

# Watch mode (development)
npm run test:watch
```

---

## 📅 Timeline & Milestones

### Week 1: Data Access Layer
- Days 1-2: GraphDatabase.js + tests
- Days 3-4: VectorDatabase.js + tests
- Day 5: UnifiedDataAccess.js + integration tests

### Week 2: Tool Refactoring
- Days 1-2: Consolidate RAG tools
- Day 3: Refactor Workflow tools
- Days 4-5: New analysis tools + testing

### Week 3: Context7 Ingestion
- Days 1-2: ContextAwareChunker + ChunkRelationshipMapper
- Days 3-4: Re-ingest Python code with context
- Day 5: Testing and validation

### Week 4: Cleanup & Deployment
- Days 1-2: ChromaDB cleanup + deployment automation
- Day 3: Integration testing
- Days 4-5: Documentation + final validation

---

## 🎯 Success Metrics

### Technical Metrics
- [ ] **Test Coverage**: >85% for all new code
- [ ] **Query Performance**: <100ms for 95% of queries
- [ ] **Deployment Time**: <2 minutes (automated)
- [ ] **Tool Count**: 25-30 (deduplicated from 28)
- [ ] **Collection Count**: 5 (down from current duplicates)

### Functional Metrics
- [ ] **Code Search Accuracy**: Can find functions by description + context
- [ ] **Error Diagnosis**: Provides root cause + call graph
- [ ] **Dependency Analysis**: Shows complete import chains
- [ ] **EE2 Compliance**: Validates code against requirements
- [ ] **Multi-Modal Queries**: Combines graph + vector seamlessly

### Operational Metrics
- [ ] **Uptime**: 99.9% (systemd auto-restart)
- [ ] **Mean Time to Deploy**: <5 minutes
- [ ] **Rollback Capability**: <1 minute
- [ ] **Monitoring**: Health checks + metrics dashboard

---

## 🚀 Next Steps - Today's Tasks

### Immediate Actions (Priority 1)
1. ✅ **Create this plan document**
2. 🔲 **Create Data Access Layer skeleton**:
   ```bash
   mkdir -p /mcp_rag_eib/global-workflow_MCP_node.js-RAG/dev/ci/scripts/utils/Copilot/mcp_server_node/src/data
   touch src/data/{GraphDatabase.js,VectorDatabase.js,UnifiedDataAccess.js}
   ```

3. 🔲 **Audit existing tools**:
   ```bash
   grep -rn "registerTool" src/tools/*.js > tool-inventory.txt
   # Analyze duplicates and create consolidation plan
   ```

4. 🔲 **Clean ChromaDB collections**:
   ```bash
   # Verify current state
   curl http://localhost:8080/api/v1/collections | jq '.[].name'
   # Create migration script
   ```

5. 🔲 **Set up test infrastructure**:
   ```bash
   npm install --save-dev jest @jest/globals
   # Create jest.config.js
   ```

### Short-term (This Week)
- [ ] Implement GraphDatabase.js with Neo4j connection
- [ ] Implement VectorDatabase.js with ChromaDB client
- [ ] Write comprehensive unit tests
- [ ] Document data access patterns

### Medium-term (Next 2 Weeks)
- [ ] Complete tool refactoring
- [ ] Implement Context7 chunking
- [ ] Set up automated deployment
- [ ] Migration testing

---

## 📚 Documentation Deliverables

### New Documentation
1. `docs/DATA_ACCESS_LAYER.md` - API reference for unified queries
2. `docs/TOOL_MIGRATION.md` - Migration guide for tool changes
3. `docs/CONTEXT7_CHUNKING.md` - Context-aware chunking explained
4. `docs/DEPLOYMENT_GUIDE.md` - Automated deployment procedures
5. `docs/ARCHITECTURE_v2.md` - Updated system architecture

### Updated Documentation
1. `README.md` - Reflect new architecture
2. `CONTRIBUTING.md` - Developer workflow with new structure
3. `dev/ci/scripts/utils/Copilot/PROGRESS_REPORTS_INDEX.md` - Add this plan

---

## 🎓 Key Principles

### Context7 Inspiration
1. **Code = Graph + Text**: Every chunk has both vector and graph representation
2. **Context Windows**: Include surrounding code + dependencies
3. **Relationship Preservation**: Maintain semantic links between chunks
4. **Multi-Dimensional Search**: Combine similarity + structure

### Clean Architecture
1. **Single Responsibility**: Each module does one thing well
2. **Dependency Inversion**: High-level tools depend on abstractions
3. **Open/Closed**: Easy to extend, hard to break
4. **Interface Segregation**: Clients depend on minimal interfaces

### DevOps Best Practices
1. **Infrastructure as Code**: All deployment is scripted
2. **Automated Testing**: CI/CD integration
3. **Monitoring & Logging**: Observability built-in
4. **Disaster Recovery**: Backup and rollback procedures

---

**Status**: Ready to Begin Implementation  
**Next Meeting**: Daily standup to track progress  
**Questions/Blockers**: None currently  
**Owner**: Terry McGuinness + Claude Sonnet 4.5 Preview
