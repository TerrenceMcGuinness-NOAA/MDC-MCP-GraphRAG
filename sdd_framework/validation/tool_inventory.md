# MCP Tool Inventory & Consolidation Analysis
**Date**: 2025-10-16  
**Purpose**: Audit existing tools and plan consolidation

---

## Current Tool Count: 26 Tools

### Tool Distribution by Module

**EnhancedRAGTools.js**: 11 tools
- Advanced RAG queries
- Multi-dimensional search
- Context-aware retrieval

**RAGTools.js**: 7 tools  
- Basic semantic search
- ChromaDB queries
- Simple vector operations

**WorkflowTools.js**: 4 tools
- Structure queries
- System information
- Configuration access

**GitHubTools.js**: 4 tools
- Repository search
- Issue/PR queries
- Code search
- Cross-repo analysis

---

## Duplication Analysis

### Overlap: RAGTools vs EnhancedRAGTools

**Likely Duplicates** (need verification):
1. Basic semantic search functionality
2. Collection querying
3. Simple document retrieval

**Unique in EnhancedRAGTools**:
- Multi-collection search
- Hybrid scoring
- Advanced filters

**Unique in RAGTools**:
- Legacy collection access
- Simple query interface

**Recommendation**: 
- Consolidate into `SemanticSearchTools.js`
- Keep advanced features from Enhanced
- Remove duplicates from basic RAG
- Estimated final count: 9 tools (down from 18)

---

## Proposed New Structure

### Core Tools (4 tools)
**Module**: `src/tools/core/WorkflowStructureTools.js`
- get_workflow_structure
- list_job_scripts
- get_system_configs
- explain_workflow_component

### Search Tools (9 tools)
**Module**: `src/tools/search/SemanticSearchTools.js` (consolidated)
- search_documentation
- search_code  
- search_errors
- multi_collection_search
- hybrid_search (with filters)

**Module**: `src/tools/search/GraphSearchTools.js` (NEW)
- find_dependencies
- trace_call_chain
- find_importers
- analyze_module_usage

### Analysis Tools (6 tools) - NEW
**Module**: `src/tools/analysis/CodeAnalysisTools.js`
- analyze_code_complexity
- find_similar_patterns
- detect_anti_patterns

**Module**: `src/tools/analysis/ErrorDiagnosisTools.js`
- diagnose_error (with call graph)
- find_error_patterns
- suggest_fixes

### Integration Tools (7 tools)
**Module**: `src/tools/integration/GitHubTools.js` (existing, keep as-is)
- github_search_repositories
- github_search_code
- github_get_issues
- github_cross_repo_analysis

**Module**: `src/tools/integration/OperationalGuidanceTools.js` (NEW)
- get_hpc_guidance
- find_deployment_docs
- search_runbooks

---

## Migration Plan

### Phase 1: No Breaking Changes
- Create new modules alongside existing
- Implement with UnifiedDataAccess
- Test thoroughly
- Keep old modules functional

### Phase 2: Deprecation Warnings
- Add deprecation notices to old tools
- Update documentation
- Notify users of migration path

### Phase 3: Removal
- Remove deprecated modules after 2 weeks
- Update UnifiedMCPServer.js
- Final testing

---

## Tool Count Summary

**Current**: 26 tools (4 modules)
**After Consolidation**: 26 tools (9 modules)  
- Better organized
- No duplication
- Clear responsibilities
- Graph-enhanced capabilities

**New Tools Added**: ~8 (graph search, analysis)
**Removed Duplicates**: ~8
**Net Change**: 0 (but much better structure)

---

## Next Steps

1. ✅ Create this inventory
2. 🔲 Read EnhancedRAGTools.js to identify exact tools
3. 🔲 Read RAGTools.js to identify exact tools
4. 🔲 Map duplicates precisely
5. 🔲 Start implementing GraphSearchTools.js (new)
