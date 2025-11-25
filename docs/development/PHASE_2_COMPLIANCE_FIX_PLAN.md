# Phase 2 Compliance Fix Plan
## Issue: Best Practices Hallucinations in Scan Tool

**Date**: November 20, 2025  
**Priority**: **CRITICAL** - Violates core Phase 2 principle  
**Reporter**: User feedback during EVS report review

---

## Problem Statement

The `scan_repository_compliance` MCP tool is reporting **best practice violations** that are **NOT explicitly documented in EE2 standards**:

1. **Variable Quoting** (730 files flagged)
   - Lines 1022-1041 in `SemanticSearchTools.js`
   - Hard-coded regex check: `/(?<!["'])\$([A-Z_][A-Z0-9_]*)\b(?!["'])/g`
   - Report says: "Quote variables: \"$VAR\" or \"${VAR}\" per EE2 standard"
   - **Reality**: No EE2 standard exists for bash variable quoting

2. **Hardcoded Paths** (unknown count)
   - Lines 1043-1051 in `SemanticSearchTools.js`
   - Checks for `/[a-z]+/[a-z]+/[a-z]+/` patterns
   - Report says: "Replace with standard variables: $HOMEmodel, $USHmodel, $EXECmodel"
   - **Reality**: This is a best practice recommendation, not an EE2 requirement

---

## Root Cause Analysis

### Architectural Violation

**Phase 2 Principle** (from PHASE_2_HYBRID_ARCHITECTURE_SPECIFICATION.md):
> "AI must ONLY recommend changes explicitly stated in EE2 documentation. DO NOT add 'improvements' or 'best practices' beyond EE2 requirements."

**Current State**: Scan tool contains hard-coded checks that bypass Phase 2 annotations entirely.

### Evidence Chain

✅ **Phase 2 Annotations**: No variable quoting requirements
- Checked: `sdd_framework/phase2_annotations/ee2_error_handling_sme_corrections.rst`
- Checked: `sdd_framework/phase2_annotations/err_chk_pattern_recognition.rst`
- Result: **Zero mentions of variable quoting**

✅ **Phase 2 Generated Config**: No variable quoting requirements
- Checked: `mcp_server_node/phase2_anti_patterns.json`
- `environment_variables` categories: **Empty arrays**
- Result: **No rules generated for variable quoting**

✅ **EE2 Standards Search**: No variable quoting requirements
- Searched: "bash variable quoting shell variable expansion quote variables"
- Found: Error handling (err_chk/err_exit), file naming, standard env vars
- Result: **No explicit quoting requirements in official EE2 standards**

❌ **Scan Tool Implementation**: Hard-coded best practices
- Location: `SemanticSearchTools.js` lines 1019-1051
- Logic: Regex-based detection independent of Phase 2 config
- Result: **Violates single source of truth principle**

---

## Impact Assessment

### Immediate Impact

1. **User Trust Degradation**
   - Report claims "per EE2 standard" for non-existent standards
   - 730/792 files (92%) flagged for non-compliance
   - **93.8% compliance gap rate** largely driven by hallucinated requirement

2. **Operational Risk**
   - Developers may implement unnecessary changes
   - Compliance energy wasted on non-requirements
   - Actual EE2 violations diluted by noise

3. **Phase 2 Architecture Integrity**
   - Defeats purpose of semantic annotations
   - Undermines SME trust in system
   - Creates precedent for future hallucinations

### Long-Term Risk

- If not fixed, SMEs will lose confidence in MCP system
- Future compliance reports will be questioned
- Phase 2 annotation effort wasted if tool ignores annotations

---

## Fix Strategy

### Principle: Phase 2-Only Validation

**New Rule**: Scan tool MUST ONLY report violations that meet **BOTH** criteria:
1. Pattern appears in `phase2_anti_patterns.json` (generated from annotations)
2. Pattern has explicit EE2 evidence chain (line numbers from standards.rst)

**Enforcement**:
```javascript
// BEFORE (Phase 1 - Hard-coded):
if (unquotedVars.length > 5) {
  violations.push({
    issue: 'unquoted variables',
    fix: 'Quote variables per EE2 standard'  // ❌ No such standard!
  });
}

// AFTER (Phase 2 - Evidence-based):
const envVarRules = phase2Config.anti_patterns.environment_variables || [];
if (envVarRules.length === 0) {
  // No Phase 2 rules = No violations to report
  return;
}

envVarRules.forEach(rule => {
  if (rule.evidence.length === 0) {
    console.warn(`Skipping rule ${rule.name}: No EE2 evidence`);
    return;  // ❌ Can't report without evidence
  }
  
  // Only now check for pattern match...
});
```

### Implementation Steps

#### Step 1: Remove Hard-Coded Checks (SemanticSearchTools.js)

**Files to Modify**:
- `mcp_server_node/src/tools/SemanticSearchTools.js` (lines 1019-1051)

**Changes**:
```javascript
// DELETE lines 1019-1051 (environment variable hard-coded checks)
// REPLACE with Phase 2 config-driven approach:

if (categories.includes('environment_variables')) {
  const envVarRules = phase2Config?.anti_patterns?.environment_variables || [];
  
  if (envVarRules.length === 0) {
    // No Phase 2 rules defined = No violations possible
    console.error('[INFO] No Phase 2 environment variable rules - skipping category');
    continue;
  }
  
  // Only check patterns explicitly defined in Phase 2 config
  envVarRules.forEach(rule => {
    if (!rule.evidence || rule.evidence.length === 0) {
      console.error(`[WARN] Skipping rule ${rule.name}: No EE2 evidence chain`);
      return;
    }
    
    // Apply rule pattern detection here...
    // (Only if rule has explicit EE2 line number references)
  });
}
```

#### Step 2: Add Evidence Validation (generatePhase2Config.js)

**File**: `mcp_server_node/scripts/generatePhase2Config.js`

**Add Validation**:
```javascript
// After building pattern object (line ~120)
if (!pattern.evidence || pattern.evidence.length === 0) {
  console.warn(`⚠️  Pattern ${pattern.name} has no EE2 evidence - will not be enforced`);
  pattern.severity = 'best_practice';  // Downgrade to advisory
  pattern.enforceable = false;
}
```

#### Step 3: Update Scan Categories (Default Behavior)

**Current**: `categories: ["error_handling", "environment_variables", "file_naming"]`

**New Default**: `categories: ["error_handling"]`  
(Only include categories with Phase 2 rules)

**Logic**:
```javascript
function getActiveCategories(phase2Config) {
  const active = [];
  
  // Only enable category if it has rules with evidence
  Object.keys(phase2Config.anti_patterns).forEach(category => {
    const rules = phase2Config.anti_patterns[category];
    const enforceableRules = rules.filter(r => 
      r.evidence && r.evidence.length > 0
    );
    
    if (enforceableRules.length > 0) {
      active.push(category);
    } else {
      console.error(`[INFO] Skipping category ${category}: No enforceable rules`);
    }
  });
  
  return active;
}
```

#### Step 4: Update Report Generation

**Remove**:
- All mentions of "Quote variables per EE2 standard"
- All environment variable sections (if no Phase 2 rules exist)
- Hardcoded path checks (unless SME adds to Phase 2 annotations)

**Add**:
- Disclaimer section explaining what IS and ISN'T checked
- Clear separation between "EE2 Violations" and "Best Practice Suggestions"

---

## Validation Plan

### Test 1: Re-run EVS Scan (After Fix)

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node
# Apply fixes to SemanticSearchTools.js
# Re-run scan
```

**Expected Results**:
- **Before**: 743/792 files with issues (93.8%)
- **After**: ~62/792 files with issues (7.8%)
  - **ONLY error handling violations** (no variable quoting)
  - **ONLY patterns with EE2 evidence**

### Test 2: Empty Category Behavior

**Scenario**: environment_variables category has zero Phase 2 rules

**Expected**: Category skipped entirely, no violations reported

**Test Command**:
```javascript
// In test environment
phase2Config.anti_patterns.environment_variables = [];
const result = await scan_repository_compliance({ 
  categories: ['environment_variables'] 
});
// Should return: "No enforceable rules for this category"
```

### Test 3: Evidence Chain Validation

**Scenario**: Rule exists but has no `evidence` array

**Expected**: Rule skipped with warning logged

**Test**:
```json
{
  "anti_patterns": {
    "error_handling": [{
      "name": "test_rule",
      "evidence": []  // ❌ No EE2 line numbers
    }]
  }
}
```

**Expected Log**:
```
[WARN] Skipping rule test_rule: No EE2 evidence chain
```

---

## Success Criteria

### Quantitative

1. ✅ EVS scan shows ~62 files with issues (not 743)
2. ✅ Zero "environment variables" violations (unless Phase 2 rules added)
3. ✅ Every violation in report cites EE2 line numbers
4. ✅ No "per EE2 standard" claims for non-existent standards

### Qualitative

1. ✅ Report only contains explicit EE2 violations
2. ✅ SMEs can verify every violation against standards.rst
3. ✅ No best practice suggestions masquerading as requirements
4. ✅ Phase 2 annotation system demonstrates integrity

---

## Rollout Plan

### Phase A: Fix Implementation (30 minutes)

1. Modify `SemanticSearchTools.js` - Remove hard-coded checks
2. Modify `generatePhase2Config.js` - Add evidence validation
3. Update default scan categories
4. Commit with message: "Phase 2 Compliance Fix: Remove best practice hallucinations"

### Phase B: Re-scan EVS (10 minutes)

1. Re-run `scan_repository_compliance` on EVS
2. Generate new report
3. Create updated gist
4. Update wiki with corrected metrics

### Phase C: Documentation (20 minutes)

1. Update `PHASE_2_HYBRID_ARCHITECTURE_SPECIFICATION.md` with lessons learned
2. Add "Evidence Chain Required" section to SME training
3. Update `changelog.md` with Phase 2 compliance fix

### Phase D: Validation (15 minutes)

1. Manual review: Every violation cites EE2 line numbers
2. Spot check: 10 random files from "clean" list
3. SME review: Confirm no false positives remain

**Total Time**: ~75 minutes

---

## Future Safeguards

### Guardrail 1: Evidence Chain Enforcement

**Policy**: No violation reported without EE2 line number citation

**Implementation**: Add to `generatePhase2Config.js`:
```javascript
if (!pattern.evidence || pattern.evidence.length === 0) {
  throw new Error(`Pattern ${pattern.name} has no EE2 evidence - annotation rejected`);
}
```

### Guardrail 2: SME Sign-Off on New Categories

**Policy**: New compliance categories require SME review BEFORE implementation

**Process**:
1. Developer proposes new category (e.g., "code_style")
2. SME must create Phase 2 annotation with EE2 evidence
3. Annotation reviewed by 2+ SMEs
4. Only then can scan tool check for violations

### Guardrail 3: Audit Trail

**Policy**: Every violation includes traceability metadata

**Example**:
```json
{
  "violation": {
    "issue": "Missing set -x",
    "file": "ecf/setup_ecf_links.sh",
    "line": 2,
    "ee2_evidence": ["standards.rst:588-595"],
    "phase2_rule": "set_x_debug_logging",
    "annotation_file": "ee2_error_handling_sme_corrections.rst",
    "sme_justification": "EE2 explicitly requires set -x for debug logging"
  }
}
```

---

## Lessons Learned

### What Went Wrong

1. **Assumption**: Developer assumed variable quoting was an EE2 requirement
2. **Bypass**: Hard-coded checks bypassed Phase 2 annotation system
3. **Validation Gap**: No test verified "EE2 standard" claims against actual standards
4. **Documentation**: SME training didn't emphasize evidence chain criticality

### Corrective Actions

1. ✅ Remove all hard-coded compliance checks
2. ✅ Require EE2 evidence for every rule
3. ✅ Add pre-commit validation: Rules must have evidence
4. ✅ Update SME training: "No Evidence = No Enforcement"

### Process Improvements

- **Pre-Implementation Review**: Every new check requires EE2 citation
- **Quarterly Audit**: Review all active rules for evidence chains
- **SME Feedback Loop**: Monthly review of reported violations for hallucinations

---

## Approval

- [ ] **Developer**: Code changes implemented and tested
- [ ] **SME Lead**: Confirmed fix aligns with Phase 2 principles
- [ ] **User**: Validated report accuracy post-fix

**Target Completion**: November 20, 2025

---

## References

- **Issue Report**: User feedback on EVS report (variable quoting hallucination)
- **Architecture**: `PHASE_2_HYBRID_ARCHITECTURE_SPECIFICATION.md`
- **Phase 2 Annotations**: `sdd_framework/phase2_annotations/*.rst`
- **Generated Config**: `mcp_server_node/phase2_anti_patterns.json`
- **Scan Tool**: `mcp_server_node/src/tools/SemanticSearchTools.js`
