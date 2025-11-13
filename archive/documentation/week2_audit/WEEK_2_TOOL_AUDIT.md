# MCP Tools Audit - Week 2 Starting Point

**Date:** October 16, 2025  
**Purpose:** Comprehensive audit of all 26 MCP tools before consolidation  
**Current State:** RAGTools.js (7) + EnhancedRAGTools.js (11) + WorkflowTools.js (4) + GitHubTools.js (4) = 26 total

---

## 🎯 Executive Summary

**Total Tools:** 26 registered tools  
**Problem:** 8 duplicate tools between RAGTools and EnhancedRAGTools  
**Goal:** Consolidate to ~18 unique tools, update to use UnifiedDataAccess from Week 1

---

## 📊 Tool Inventory by Module

### RAGTools.js (7 tools)
Uses direct ChromaDB access - **NEEDS UPDATE** to use UnifiedDataAccess

| Tool Name | Purpose | ChromaDB? | Status |
|-----------|---------|-----------|--------|
| `search_documentation` | Semantic search docs/code | ✅ Direct | 🔴 Duplicate |
| `search_ee2_standards` | EE2 compliance standards | ✅ Direct | 🔴 Duplicate |
| `analyze_ee2_compliance` | Analyze code for EE2 | ✅ Direct | 🔴 Duplicate |
| `generate_compliance_report` | EE2 compliance report | ✅ Direct | 🔴 Duplicate |
| `explain_with_context` | Contextual explanations | ✅ Direct | 🔴 Duplicate |
| `find_similar_code` | Vector-based code similarity | ✅ Direct | 🔴 Duplicate |
| `get_knowledge_base_status` | KB stats | ✅ Direct | ✅ Unique |

**ChromaDB Access Pattern:**
```javascript
const { ChromaClient } = await import('chromadb');
this.chromaClient = new ChromaClient({ path: chromaUrl });
this.collection = await this.chromaClient.getOrCreateCollection({
  name: 'global-workflow-docs'
});
```

### EnhancedRAGTools.js (11 tools)
Uses EE2VectorStore wrapper - **NEEDS UPDATE** to use UnifiedDataAccess

| Tool Name | Purpose | ChromaDB? | Status |
|-----------|---------|-----------|--------|
| `search_documentation` | Enhanced semantic search | ✅ EE2VectorStore | 🔴 Duplicate |
| `search_ee2_standards` | Enhanced EE2 search | ✅ EE2VectorStore | 🔴 Duplicate |
| `analyze_ee2_compliance` | Enhanced EE2 analysis | ✅ EE2VectorStore | 🔴 Duplicate |
| `generate_compliance_report` | Enhanced report | ✅ EE2VectorStore | 🔴 Duplicate |
| `explain_with_context` | Enhanced context | ✅ EE2VectorStore | 🔴 Duplicate |
| `find_similar_code` | Enhanced code search | ✅ EE2VectorStore | 🔴 Duplicate |
| `get_operational_guidance` | Ops procedures | ✅ EE2VectorStore | 🔴 Duplicate* |
| `explain_workflow_component` | Component deep-dive | ✅ EE2VectorStore | ✅ Unique |
| `list_job_scripts` | Job script inventory | ✅ EE2VectorStore | ✅ Unique |
| `get_system_configs` | HPC platform configs | ❌ Static | ✅ Unique |
| `get_workflow_structure` | System architecture | ❌ Static | ✅ Unique |

**ChromaDB Access Pattern:**
```javascript
import { EE2VectorStore } from '../rag/EE2VectorStore.js';
this.ee2VectorStore = new EE2VectorStore(chromaUrl);
await this.ee2VectorStore.initialize();
const results = await this.ee2VectorStore.query(query, maxResults);
```

*Note: `get_operational_guidance` has counterpart in RAGTools but different implementation

### WorkflowTools.js (4 tools)
Static tools, no ChromaDB - **NO UPDATE NEEDED**

| Tool Name | Purpose | ChromaDB? | Status |
|-----------|---------|-----------|--------|
| `get_workflow_structure` | System overview | ❌ Static | ✅ Unique |
| `list_job_scripts` | Job script listing | ❌ Static | ✅ Unique |
| `explain_workflow_component` | Component explanation | ❌ Static | ✅ Unique |
| `get_system_configs` | Platform configs | ❌ Static | ✅ Unique |

**Note:** These are basic versions. EnhancedRAGTools has enhanced versions with RAG.

### GitHubTools.js (4 tools)
GitHub integration only - **NO UPDATE NEEDED**

| Tool Name | Purpose | ChromaDB? | Status |
|-----------|---------|-----------|--------|
| `search_issues` | GitHub issue search | ❌ GitHub API | ✅ Unique |
| `get_pull_requests` | PR information | ❌ GitHub API | ✅ Unique |
| `get_ingested_urls_array` | Ingested URL list | ❌ Local files | ✅ Unique |
| `list_ingested_urls` | Human-readable URL list | ❌ Local files | ✅ Unique |

---

## 🔍 Duplicate Analysis

### Exact Duplicates (6 tools)
Same tool name in both RAGTools and EnhancedRAGTools:

1. **`search_documentation`**
   - RAGTools: Direct ChromaDB query
   - EnhancedRAGTools: EE2VectorStore with metadata filtering
   - **Action:** Keep Enhanced version, migrate to UnifiedDataAccess

2. **`search_ee2_standards`**
   - RAGTools: Basic EE2 search
   - EnhancedRAGTools: Category filtering + examples
   - **Action:** Keep Enhanced version, migrate to UnifiedDataAccess

3. **`analyze_ee2_compliance`**
   - RAGTools: Basic compliance check
   - EnhancedRAGTools: Multi-category analysis
   - **Action:** Keep Enhanced version, migrate to UnifiedDataAccess

4. **`generate_compliance_report`**
   - RAGTools: Simple report
   - EnhancedRAGTools: Comprehensive report with categories
   - **Action:** Keep Enhanced version, migrate to UnifiedDataAccess

5. **`explain_with_context`**
   - RAGTools: Basic contextual explanation
   - EnhancedRAGTools: Multi-source context aggregation
   - **Action:** Keep Enhanced version, migrate to UnifiedDataAccess

6. **`find_similar_code`**
   - RAGTools: Vector similarity search
   - EnhancedRAGTools: Enhanced with file type filtering
   - **Action:** Keep Enhanced version, migrate to UnifiedDataAccess

### Similar Duplicates (4 tools)
Different implementations but overlapping functionality:

7. **`get_operational_guidance`**
   - RAGTools: Has method but not registered as tool
   - EnhancedRAGTools: Registered tool with platform context
   - **Action:** Keep Enhanced version only

8. **`explain_workflow_component`**
   - WorkflowTools: Basic static explanation
   - EnhancedRAGTools: RAG-enhanced with semantic search
   - **Action:** Keep both - rename WorkflowTools version to `describe_workflow_component`

9. **`list_job_scripts`**
   - WorkflowTools: Static file listing
   - EnhancedRAGTools: RAG-enhanced with categorization
   - **Action:** Keep both - WorkflowTools for quick list, Enhanced for deep analysis

10. **`get_workflow_structure`**
    - WorkflowTools: Static structure
    - EnhancedRAGTools: Has it too
    - **Action:** Keep WorkflowTools version (simpler, no RAG overhead)

11. **`get_system_configs`**
    - WorkflowTools: Static configs
    - EnhancedRAGTools: Has it too
    - **Action:** Keep WorkflowTools version (simpler, no RAG overhead)

---

## 📋 Consolidation Plan

### Phase 1: Merge RAGTools → EnhancedRAGTools
**Goal:** Single authoritative RAG module

**Actions:**
1. ✅ Keep EnhancedRAGTools versions (6 tools)
2. ✅ Add `get_knowledge_base_status` from RAGTools (unique)
3. ❌ Delete RAGTools.js entirely
4. 📝 Rename EnhancedRAGTools.js → **SemanticSearchTools.js**

**Result:** 11 tools → 11 tools (no duplicates)

### Phase 2: Create New Module Structure
**Goal:** Organize by function, not implementation

**New Modules:**

#### SemanticSearchTools.js (7 tools)
Semantic search and RAG operations using UnifiedDataAccess

- `search_documentation` - Hybrid search (vector + graph)
- `search_ee2_standards` - EE2 compliance search
- `find_similar_code` - Vector similarity with graph enrichment
- `explain_with_context` - Context-aware explanations
- `analyze_ee2_compliance` - Compliance analysis
- `generate_compliance_report` - Report generation
- `get_knowledge_base_status` - KB statistics

#### CodeAnalysisTools.js (4 tools) - **NEW MODULE**
Code structure and dependency analysis using UnifiedDataAccess

- `analyze_code_structure` - NEW: Use GraphDatabase for code structure
- `find_dependencies` - NEW: Graph-based dependency tracing
- `trace_execution_path` - NEW: Call chain tracing
- `find_callers_callees` - NEW: Function relationship analysis

#### OperationalTools.js (3 tools)
Operational procedures and platform configs

- `get_operational_guidance` - From EnhancedRAGTools
- `explain_workflow_component` - From EnhancedRAGTools
- `list_job_scripts` - From EnhancedRAGTools

#### WorkflowInfoTools.js (3 tools)
Static workflow information (no RAG/DB)

- `get_workflow_structure` - From WorkflowTools
- `describe_component` - Renamed from explain_workflow_component
- `get_system_configs` - From WorkflowTools

#### GitHubTools.js (4 tools)
Keep as-is, no changes needed

- `search_issues`
- `get_pull_requests`
- `get_ingested_urls_array`
- `list_ingested_urls`

### Phase 3: Update All Tools to Use UnifiedDataAccess
**Goal:** Leverage Week 1 Data Access Layer

**Changes:**
```javascript
// OLD: Direct ChromaDB
const { ChromaClient } = await import('chromadb');
this.chromaClient = new ChromaClient({ path: chromaUrl });

// OLD: EE2VectorStore wrapper
import { EE2VectorStore } from '../rag/EE2VectorStore.js';
this.ee2VectorStore = new EE2VectorStore(chromaUrl);

// NEW: UnifiedDataAccess (Week 1)
import { UnifiedDataAccess } from '../data/UnifiedDataAccess.js';
this.dataAccess = new UnifiedDataAccess();
await this.dataAccess.initialize();

// NEW: Hybrid queries (semantic + graph)
const results = await this.dataAccess.hybridQuery(query, {
  maxResults: 5,
  includeGraph: true,
  graphDepth: 2
});
```

**Benefits:**
- ✅ Single unified interface
- ✅ Automatic graph enrichment
- ✅ Connection pooling
- ✅ Metrics tracking
- ✅ Health monitoring

---

## 📈 Before vs After

### Current State (Week 1 End)
```
Total Tools: 26
├── RAGTools.js: 7 tools (6 duplicates, 1 unique)
├── EnhancedRAGTools.js: 11 tools (6 duplicates, 5 unique)
├── WorkflowTools.js: 4 tools (2 basic versions of Enhanced tools)
└── GitHubTools.js: 4 tools (all unique)

ChromaDB Access: Direct + EE2VectorStore wrapper
Graph Database: Not used by tools yet
Data Access Layer: Exists but not used by tools
```

### Target State (Week 2 End)
```
Total Tools: 21 unique tools (5 fewer, 4 new)
├── SemanticSearchTools.js: 7 tools (uses UnifiedDataAccess)
├── CodeAnalysisTools.js: 4 tools (NEW - uses GraphDatabase)
├── OperationalTools.js: 3 tools (uses UnifiedDataAccess)
├── WorkflowInfoTools.js: 3 tools (static, no DB)
└── GitHubTools.js: 4 tools (unchanged)

ChromaDB Access: Via UnifiedDataAccess only
Graph Database: Via UnifiedDataAccess and directly for code analysis
Data Access Layer: Used by all tools requiring DB access
```

**Improvements:**
- ✅ 19% reduction in tool count (26 → 21)
- ✅ Zero duplicate tools
- ✅ Unified data access pattern
- ✅ Graph-enriched semantic search
- ✅ 4 new code analysis tools leveraging Neo4j
- ✅ Clear module organization by function
- ✅ Consistent API across all tools

---

## 🔧 Implementation Order

### Step 1: Create CodeAnalysisTools.js (NEW)
Implement 4 new tools using GraphDatabase directly

### Step 2: Create SemanticSearchTools.js
Merge EnhancedRAGTools + RAGTools, update to UnifiedDataAccess

### Step 3: Create OperationalTools.js
Extract operational tools from Enhanced, update to UnifiedDataAccess

### Step 4: Refactor WorkflowTools → WorkflowInfoTools
Keep static tools, rename to avoid confusion

### Step 5: Update UnifiedMCPServer.js
Update tool registrations to use new modules

### Step 6: Delete RAGTools.js
Remove after confirming all functionality migrated

### Step 7: Rename EnhancedRAGTools.js
Archive old file after migration complete

### Step 8: Update Documentation
- Tool migration guide
- New tool reference
- Examples for each module

---

## 📝 Next Actions

**Ready to start Step 1: Create CodeAnalysisTools.js**

This will demonstrate the pattern for:
1. Using UnifiedDataAccess
2. Leveraging GraphDatabase for code structure queries
3. Implementing hybrid semantic + graph queries
4. Writing clean, documented tool code

**Proceed?**
