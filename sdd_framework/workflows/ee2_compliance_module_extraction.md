# EE2 Compliance Module Extraction Workflow
**Extract EE2 Compliance Tools from SemanticSearchTools**

## Overview

Extract EE2 compliance functionality from `SemanticSearchTools.js` into a dedicated `EE2ComplianceTools.js` module to improve separation of concerns and maintainability.

**Priority**: Medium  
**Complexity**: Low-Medium  
**Estimated Effort**: 2-3 hours  
**Target Date**: Week of December 2, 2025

---

## 🎯 Goals

1. **Single Responsibility**: SemanticSearchTools focuses on search, EE2ComplianceTools focuses on compliance
2. **Cleaner Dependencies**: EE2 tools can evolve independently
3. **Better Testing**: Isolated compliance validation testing
4. **Enhanced Discoverability**: Clear tool grouping for users

---

## 📊 Current State Analysis

### SemanticSearchTools.js - Current Tools (7 tools)

| Tool | Category | Extract? |
|------|----------|----------|
| `search_documentation` | Search | No |
| `search_ee2_standards` | **EE2** | **Yes** |
| `find_related_files` | Search | No |
| `explain_with_context` | Search | No |
| `analyze_ee2_compliance` | **EE2** | **Yes** |
| `generate_compliance_report` | **EE2** | **Yes** |
| `scan_repository_compliance` | **EE2** | **Yes** |
| `get_knowledge_base_status` | Utility | No (move to utility?) |

### Proposed Split

**SemanticSearchTools.js** (4 tools - search focused):
- `search_documentation`
- `find_related_files`
- `explain_with_context`
- `get_knowledge_base_status` (or move to utility)

**EE2ComplianceTools.js** (4 tools - compliance focused):
- `search_ee2_standards`
- `analyze_ee2_compliance`
- `validate_ee2_compliance` (rename from analyze for clarity)
- `generate_compliance_report`
- `scan_repository_compliance`

---

## 📁 Target File Structure

```
mcp_server_node/src/tools/
├── CodeAnalysisTools.js       # Graph-based code analysis (4 tools)
├── EE2ComplianceTools.js      # NEW: EE2 compliance validation (4-5 tools)
├── GitHubTools.js             # Repository integration (4+ tools)
├── OperationalTools.js        # HPC operational guidance (3 tools)
├── SDDWorkflowTools.js        # SDD automation (6 tools)
├── SemanticSearchTools.js     # Semantic search only (3-4 tools)
└── WorkflowInfoTools.js       # Static workflow structure (3 tools)
```

---

## 🔧 Implementation Steps

### Step 1: Create EE2ComplianceTools.js Scaffold

Create new file with class structure:

```javascript
/**
 * EE2ComplianceTools.js - EE2 Standards Compliance Validation
 * 
 * Provides tools for validating code and documentation against
 * NOAA NWS EE2 (Enterprise Environmental 2) standards.
 * 
 * Extracted from SemanticSearchTools.js for better SOC.
 * 
 * @version 1.0.0
 * @domain EE2_Compliance
 */

import { UnifiedDataAccess } from '../data/UnifiedDataAccess.js';

export class EE2ComplianceTools {
  constructor(dataAccess = null) {
    this.dataAccess = dataAccess || new UnifiedDataAccess();
    this.initialized = false;
  }

  async initialize() {
    if (this.initialized) return;
    await this.dataAccess.connect();
    this.initialized = true;
  }

  registerWith(server) {
    // Register all EE2 compliance tools
    this.registerSearchEE2Standards(server);
    this.registerAnalyzeCompliance(server);
    this.registerGenerateReport(server);
    this.registerScanRepository(server);
  }
  
  // Tool implementations moved from SemanticSearchTools...
}
```

### Step 2: Extract Tool Implementations

Move the following methods from SemanticSearchTools.js:

1. `search_ee2_standards` → Copy implementation
2. `analyze_ee2_compliance` → Copy implementation
3. `generate_compliance_report` → Copy implementation
4. `scan_repository_compliance` → Copy implementation

### Step 3: Update SemanticSearchTools.js

Remove extracted tools, keeping only:
- `search_documentation`
- `find_related_files`
- `explain_with_context`
- `get_knowledge_base_status`

### Step 4: Update UnifiedMCPServer.js

Add EE2ComplianceTools registration:

```javascript
import { EE2ComplianceTools } from './tools/EE2ComplianceTools.js';

// In constructor:
if (this.options.enableRAG) {
  this.semanticSearchTools = new SemanticSearchTools();
  this.ee2ComplianceTools = new EE2ComplianceTools();  // NEW
  this.operationalTools = new OperationalTools();
}

// In registerAllTools:
if (this.options.enableRAG && this.ee2ComplianceTools) {
  this.ee2ComplianceTools.registerWith(this.server);
  console.error('[MCP] EE2 Compliance tools registered');
}
```

### Step 5: Update Tests

Create/update test file:
- `src/__tests__/EE2ComplianceTools.test.js`

### Step 6: Validate

1. Run health check to verify tool count
2. Test each extracted tool
3. Verify no regressions in SemanticSearchTools

---

## ✅ Validation Checklist

- [ ] EE2ComplianceTools.js created with 4-5 tools
- [ ] SemanticSearchTools.js reduced to 3-4 tools
- [ ] UnifiedMCPServer.js updated with new import
- [ ] All EE2 tools respond correctly
- [ ] No duplicate tools registered
- [ ] Tests pass for both modules
- [ ] Health check shows correct tool count

---

## 📈 Expected Outcome

| Metric | Before | After |
|--------|--------|-------|
| SemanticSearchTools | 7 tools | 3-4 tools |
| EE2ComplianceTools | N/A | 4-5 tools |
| Total tools | ~27 | ~27 (same) |
| SOC Grade | B+ | A |

---

## 🔗 Related SDDs

- `phase5_service_integration_workflow.md` - Service integration patterns
- `ee2_enhanced_embeddings_workflow.md` - EE2 embeddings source

---

## 📝 Notes

- This is a refactoring task, not new functionality
- Tool names and behavior should remain identical for backward compatibility
- Consider adding `validate_file_ee2_compliance` for single-file validation
- Future: Could add `suggest_ee2_fixes` for automated remediation suggestions
