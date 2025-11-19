# Phase 2 Annotation Tracker - EE2 Error Handling Corrections

**Date Started**: November 19, 2025  
**Phase**: 2 - Source Annotation  
**Status**: In Progress - SME Review  
**Priority**: Critical (Corrects 80% false positive rate)

---

## Quick Status

| Metric | Value |
|--------|-------|
| **False Positives Identified** | 2 critical issues |
| **Scripts Affected** | ~80% of EVS codebase |
| **Annotation File Created** | ✅ `ee2_error_handling_sme_corrections.rst` |
| **SME Sign-Off Status** | ⏳ Pending |
| **Enhanced Ingestion** | ⏳ Pending Phase 3 |

---

## Critical Issues Corrected

### Issue 1: `set -eu` False Positives

**Problem**: AI recommends `set -eu` but EE2 only shows `set -x` in examples

**Impact**: 
- ~80% of EVS scripts flagged incorrectly
- "Missing set -eu" warnings everywhere
- Zero basis in EE2 documentation

**Evidence**:
- ✅ Verified EE2 standards.rst lines 588-595
- ✅ Verified Example 8 (J-job) - NO set -e
- ✅ Verified Example 9 (ex-script) - NO set -e
- ✅ Only `set -x` shown in examples

**Correction Applied**:
```rst
.. mcp:anti_pattern:: adding_set_e_or_set_eu
   :severity: must_not
   :sme_justification: Not present in EE2 standards or examples
```

---

### Issue 2: Forced Exit Statement False Positives

**Problem**: AI recommends adding `exit 0`/`exit 1` but NCO SPAs explicitly prohibit this

**Impact**:
- ~60% of EVS scripts flagged for "missing exits"
- Directly contradicts NCO operational guidance
- Historical evidence: NCO asked to REMOVE these statements

**Evidence**:
- ✅ NCO SPA guidance: "Do not exit out of operational jobs"
- ✅ EVS team removed exits per NCO request
- ✅ EE2 only mentions `err_chk` and `err_exit` utilities

**Correction Applied**:
```rst
.. mcp:anti_pattern:: forced_exit_in_operational_job
   :severity: must_not
   :sme_justification: NCO SPA guidance - explicitly prohibited
```

---

## Annotation Strategy

### New MCP Directives Introduced

1. **`mcp:sme_correction`** - Documents false positives with severity
2. **`mcp:anti_pattern`** - Explicitly marks prohibited patterns
3. **`mcp:correct_pattern`** - Shows approved alternatives
4. **`mcp:context_types`** - Distinguishes operational/utility/test scripts
5. **`mcp:ai_guidance_rule`** - Machine-readable rules for AI queries

### Context Discrimination

The annotations now distinguish three script contexts:

| Context | Location | Exit Statements | Error Handling |
|---------|----------|-----------------|----------------|
| **Operational Job** | `jobs/`, `scripts/ex*` | ❌ Prohibited | err_chk/err_exit |
| **Utility Script** | `ush/` | ⚠️ Discouraged | err_exit recommended |
| **Test Script** | `tests/` | ✅ Allowed | Standard practices |

---

## AI Guidance Rules Embedded

### Rule 1: Literal Compliance Only

```yaml
directive: literal_compliance
rule: |
  ONLY recommend changes explicitly stated in EE2 documentation.
  DO NOT add "improvements" or "best practices" beyond EE2 requirements.

example_violation: |
  EE2 says: "use set -x"
  AI recommends: "use set -eu"  # ❌ WRONG
```

### Rule 2: Context-Aware Recommendations

```python
def detect_script_context(filepath):
    if re.search(r'/jobs/J[A-Z]', filepath):
        return 'operational_job'  # Strict EE2 compliance
    elif re.search(r'/ush/', filepath):
        return 'utility_script'   # More flexibility
    elif re.search(r'/test', filepath):
        return 'test_script'      # General practices OK
```

### Rule 3: Anti-Pattern Enforcement

```text
When mcp:anti_pattern detected:
  - Flag as compliance violation
  - Reference SME justification
  - Provide mcp:correct_pattern alternative
  - DO NOT suggest as improvement
```

---

## Files Created

### Primary Annotation Document

**File**: `sdd_framework/phase2_annotations/ee2_error_handling_sme_corrections.rst`

**Size**: 21,445 bytes  
**Format**: ReStructuredText with MCP semantic directives  
**Sections**:
- Critical SME Findings (3 findings)
- EE2 Annotation Schema (context types, AI rules)
- Corrected Annotations for standards.rst (2 sections)
- AI Guidance Rules (3 rules)
- Validation Checklist (10 items)
- SME Sign-Off Block (4 signatures required)

### Key Content

**Evidence Chain**:
1. ✅ Direct quotes from standards.rst with line numbers
2. ✅ Code blocks from EE2 Example 8 (J-job)
3. ✅ Code blocks from EE2 Example 9 (ex-script)
4. ✅ Historical NCO SPA guidance documentation

**Semantic Annotations**:
- 2 `mcp:sme_correction` directives (critical severity)
- 3 `mcp:anti_pattern` directives (must_not severity)
- 2 `mcp:correct_pattern` directives (with working examples)
- 3 `mcp:ai_guidance_rule` directives (machine-readable)
- 2 `mcp:context_types` definitions

---

## Expected Impact

### False Positive Reduction

| Category | Baseline | Target | Improvement |
|----------|----------|--------|-------------|
| `set -eu` warnings | 80% | <5% | 75% reduction |
| Forced exit recommendations | 60% | <10% | 50% reduction |
| Overall false positives | 70% | <15% | 55% reduction |

### Query Precision Improvement

**Test Queries** (expected to be corrected):
1. ❌ Before: "Add `set -eu` to your bash script"
   ✅ After: "Add `set -x` for debug logging per EE2 standards"

2. ❌ Before: "Use `exit 0` to indicate success"
   ✅ After: "Use `err_chk` after operations, let script return naturally"

3. ❌ Before: "Missing error handling: add `set -e`"
   ✅ After: "Use `err_exit` utility for fatal errors per EE2 Section C"

---

## Next Steps

### Immediate (Phase 2 Completion)

- [ ] SME Review Session
  - [ ] EVS Development Team Lead review
  - [ ] NCO SPA review and sign-off
  - [ ] EIB Operations representative review
  - [ ] EMC Global Workflow maintainers review

- [ ] Validation Testing
  - [ ] Apply annotations to test corpus
  - [ ] Run AI queries on annotated corpus
  - [ ] Measure false positive reduction
  - [ ] Document SME feedback

### Phase 3 Preparation

- [ ] Enhanced Ingestion
  - [ ] Run `ingest_ee2_enhanced_v5.py` with corrected annotations
  - [ ] Create new collection: `ee2-standards-v6-0-0-corrected`
  - [ ] Verify annotation parsing and embedding

- [ ] Query Testing
  - [ ] Test 10 known false positive queries
  - [ ] Verify anti-pattern detection working
  - [ ] Validate context discrimination
  - [ ] Measure precision improvement

- [ ] Documentation
  - [ ] Update WEEK_3_PLAN with Phase 2 results
  - [ ] Document false positive reduction metrics
  - [ ] Create Phase 3 execution plan

---

## SME Review Schedule

**Target Date**: November 22, 2025 (3 business days)

| Reviewer | Role | Review Focus | Status |
|----------|------|--------------|--------|
| **EVS Lead** | Development | False positive accuracy | ⏳ Scheduled |
| **NCO SPA** | Operations | Anti-pattern validation | ⏳ Scheduled |
| **EIB Ops** | Production | Operational impact | ⏳ Scheduled |
| **EMC GW** | Standards | global-workflow compat | ⏳ Scheduled |

**Review Materials**:
- ✅ `ee2_error_handling_sme_corrections.rst` (primary document)
- ✅ Evidence: standards.rst excerpts with line numbers
- ✅ Test queries showing before/after behavior
- ✅ Impact analysis (80% false positive on set -eu)

---

## Success Criteria

**Phase 2 Complete When**:

1. ✅ Annotations created with SME evidence
2. ⏳ All 4 SME reviews complete with sign-off
3. ⏳ Validation testing shows >50% false positive reduction
4. ⏳ No operational objections from NCO/EIB
5. ⏳ Documentation updated with Phase 2 results

**Phase 3 Ready When**:

1. ⏳ Enhanced ingestion script tested
2. ⏳ New ChromaDB collection created
3. ⏳ Query testing framework prepared
4. ⏳ Measurement methodology documented

---

## Notes

### Key Insights from SME Feedback

1. **EE2 Documentation Gap**: 
   - EE2 examples show `set -x` only
   - No explicit prohibition of `set -e` documented
   - But absence in examples is significant evidence

2. **NCO Operational Culture**:
   - Strong preference for natural script returns
   - Workflow manager (ecFlow) expects natural completion
   - Explicit exits break error propagation chain

3. **AI Reasoning Issue**:
   - AI conflates "shell scripting best practices" with "EE2 requirements"
   - Need explicit anti-patterns to override this reasoning
   - Context discrimination critical (operational vs test)

### Technical Challenges

1. **RST Parsing**:
   - Custom MCP directives need parser support
   - May need fallback to code-block annotations

2. **Embedding Strategy**:
   - Anti-patterns need high similarity to wrong queries
   - Correct patterns need high similarity to right queries
   - May need separate collections or metadata filtering

3. **Query Routing**:
   - Context detection from query text
   - Filepath-based routing when available
   - Default to "ask for clarification" when ambiguous

---

**Last Updated**: November 19, 2025  
**Next Review**: After SME sign-off (target November 22, 2025)
