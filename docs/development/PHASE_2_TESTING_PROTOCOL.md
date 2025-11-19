# Phase 2: Before/After Query Testing Plan

**Purpose**: Validate that Phase 2 annotations eliminate systematic false positives in EE2 compliance recommendations.

**Target**: 55-75% reduction in false positive rate after Phase 3 enhanced ingestion.

---

## Test Queries - Error Handling

### Query 1: Bash Script Error Handling Requirements

**Query**: "What error handling is required at the top of bash operational scripts according to EE2 standards?"

**BEFORE Phase 2** (Expected Incorrect Response):
```
According to EE2 standards, bash scripts should include:

1. #!/bin/bash
2. set -eu (or set -euo pipefail)
3. Error traps for undefined variables

This ensures scripts exit on errors and undefined variables.
```

❌ **False Positive**: Recommends `set -eu` which is NOT in EE2 standards  
❌ **False Positive**: Claims this is "required" when it's not documented  
❌ **Evidence Violation**: EE2 Example 8 and 9 show ONLY `set -x`

**AFTER Phase 2** (Expected Correct Response):
```
According to EE2 standards (lines 588-595, Examples 8 & 9):

Required at top of ALL shell scripts:
  set -x                                 # enable verbose logging

Required in J-jobs:
  export PS4='+ $SECONDS + '             # add timing to trace

Error handling uses EE2 utilities (Section C):
  - err_chk: Check $err variable after operations
  - err_exit: Fatal error with descriptive message

Example from standards.rst line 912:
  export err=$?; err_chk

⚠️ Do NOT use set -e or set -eu (not in EE2 standards)
⚠️ Do NOT use exit 0 or exit 1 in operational jobs (NCO SPA guidance)
```

✅ **Correct**: Only mentions `set -x` (literally in EE2)  
✅ **Correct**: References specific EE2 examples and line numbers  
✅ **Correct**: Warns against anti-patterns with SME justification

---

### Query 2: Should I Add set -eu?

**Query**: "Should I add 'set -eu' to my operational ex-script for better error handling?"

**BEFORE Phase 2** (Expected Incorrect Response):
```
Yes, adding 'set -eu' is highly recommended:

- 'set -e' exits on any command failure
- 'set -u' exits on undefined variable usage
- This follows shell scripting best practices
- Improves reliability and catches errors early

Example:
  #!/bin/bash
  set -eu
  # your script...
```

❌ **False Positive**: Recommends non-EE2 requirement  
❌ **Context Confusion**: Applies general practices to EE2 operations  
❌ **Missing Guidance**: Doesn't mention err_chk/err_exit alternatives

**AFTER Phase 2** (Expected Correct Response):
```
No, do NOT add 'set -eu' to operational scripts.

EE2 standards (Examples 8 & 9, lines 868-985) show:
  ✅ set -x    (required for debug logging)
  ❌ set -e    (not in EE2 examples)
  ❌ set -eu   (not in EE2 examples)

For error handling, use EE2 production utilities:
  
  # After critical operations:
  export err=$?; err_chk
  
  # For fatal errors:
  if [ ! -f "$required_file" ]; then
      err_exit "Required file $required_file not found"
  fi

⚠️ Anti-pattern: Adding 'set -eu' extends EE2 beyond documented requirements
⚠️ Context: You asked about ex-script (operational) - strict EE2 compliance required

Reference: standards.rst Section C: Production Utilities
```

✅ **Correct**: Explicitly says "No" to non-EE2 requirement  
✅ **Correct**: Provides EE2-compliant alternatives  
✅ **Correct**: Explains context (operational script)  
✅ **Correct**: References specific documentation sections

---

### Query 3: Exit Statement Usage

**Query**: "How should my operational job indicate success or failure? Should I use exit codes?"

**BEFORE Phase 2** (Expected Incorrect Response):
```
Yes, use explicit exit codes:

Success:
  exit 0

Failure:
  exit 1

This is standard practice:
  if [ $status -ne 0 ]; then
      echo "Error occurred"
      exit 1
  fi
  exit 0
```

❌ **False Positive**: Recommends explicit exits prohibited by NCO  
❌ **Missing Context**: Doesn't distinguish operational vs test scripts  
❌ **Contradicts SME Guidance**: NCO asked to REMOVE these statements

**AFTER Phase 2** (Expected Correct Response):
```
Do NOT use explicit exit statements in operational jobs.

Operational scripts (jobs/, scripts/ex*) must:
  - Return naturally (no exit 0 or exit 1)
  - Use err_chk for error checking
  - Use err_exit for fatal errors

Examples from standards.rst:

Success case (line 912):
  mpiexec $EXECmodel/$pgm >>$pgmout 2>errfile
  export err=$?; err_chk
  # Script continues naturally - no exit 0

Failure case (line 978):
  if [ ! -s outputfile.grib2 ]; then
      err_exit "outputfile.grib2 was not generated"
  fi

⚠️ Anti-pattern: exit 0 and exit 1 prohibited in operational jobs (NCO SPA guidance)
⚠️ Rationale: Scripts must return naturally for proper workflow error propagation

ℹ️ Exception: Test scripts (tests/) may use exit codes for status reporting
```

✅ **Correct**: Explicitly prohibits exit statements  
✅ **Correct**: Provides NCO SPA justification  
✅ **Correct**: Shows correct alternatives with line numbers  
✅ **Correct**: Notes exception for test scripts (context awareness)

---

## Test Queries - Context Discrimination

### Query 4: Test Script Error Handling

**Query**: "I'm writing a test script in tests/unit/test_dataflow.sh - what error handling should I use?"

**BEFORE Phase 2** (Expected Response):
```
Use standard shell error handling:
  set -eu
  # test code...
  
Exit with status:
  exit 0  # pass
  exit 1  # fail
```

⚠️ **Partially Correct**: Advice is OK for test scripts  
❌ **Missing Context Awareness**: Doesn't distinguish from operational scripts

**AFTER Phase 2** (Expected Correct Response):
```
Context detected: Test script (tests/)

For test scripts, standard shell practices apply:
  ✅ set -e or set -eu allowed (not restricted by EE2)
  ✅ exit 0 / exit 1 allowed for test status
  ✅ More flexibility than operational jobs

Example test script:
  #!/bin/bash
  set -eu
  
  # Test logic
  if [[ $result == $expected ]]; then
      echo "PASS: Test case succeeded"
      exit 0
  else
      echo "FAIL: Expected $expected, got $result"
      exit 1
  fi

ℹ️ Note: This differs from operational jobs (jobs/, scripts/ex*)
   which must use err_chk/err_exit and return naturally.

EE2 operational restrictions do NOT apply to test scripts.
```

✅ **Correct**: Detects test context from filepath  
✅ **Correct**: Allows standard practices for tests  
✅ **Correct**: Distinguishes from operational requirements  
✅ **Context Aware**: Explains why different rules apply

---

### Query 5: Utility Script Error Handling

**Query**: "I have a utility script in ush/stage_data.sh - what are the EE2 requirements?"

**BEFORE Phase 2** (Expected Response):
```
All scripts must follow EE2 standards:
  set -eu
  err_chk after operations
  exit 1 on errors
```

❌ **Context Confusion**: Applies same rules as operational jobs  
❌ **False Positive**: Recommends set -eu

**AFTER Phase 2** (Expected Correct Response):
```
Context detected: Utility script (ush/)

For utility scripts, EE2 requirements are:
  ✅ Use standard environment variables (Table 1)
  ✅ set -x for debug logging (recommended)
  ⚠️ err_exit for fatal errors (recommended but context-dependent)
  ⚠️ More flexibility than operational jobs

Utility scripts have intermediate requirements:
  - Stricter than test scripts
  - More flexible than operational jobs (ex-scripts)
  - May need explicit exits if called from outside workflow

Example:
  #!/bin/bash
  set -x
  
  # Utility logic
  if [ ! -f "$input_file" ]; then
      err_exit "ush/stage_data.sh: Input file not found"
  fi
  
  # Process data...
  # May return naturally OR exit explicitly (context-dependent)

ℹ️ If called only from ex-scripts: Use err_exit, return naturally
ℹ️ If standalone utility: May use exit codes

Reference: standards.rst lines 581-584 (ush scripts)
```

✅ **Correct**: Detects utility context  
✅ **Correct**: Shows intermediate requirements  
✅ **Correct**: Explains context-dependent guidance  
✅ **Context Aware**: Distinguishes from both operational and test scripts

---

## Validation Metrics

### False Positive Tracking

| Query | Before (Incorrect) | After (Correct) | Status |
|-------|-------------------|-----------------|--------|
| Query 1: Error handling requirements | Recommends set -eu | Recommends set -x only | ⏳ Pending |
| Query 2: Should add set -eu? | Says "Yes" | Says "No" with EE2 justification | ⏳ Pending |
| Query 3: Exit statement usage | Recommends exit 0/1 | Prohibits with NCO justification | ⏳ Pending |
| Query 4: Test script handling | Generic advice | Context-aware (tests OK) | ⏳ Pending |
| Query 5: Utility script handling | Same as operational | Intermediate requirements | ⏳ Pending |

### Success Criteria

**Phase 2 annotations successful if:**

1. ✅ Query 1-3 responses change from incorrect to correct
2. ✅ Query 4-5 show context awareness
3. ✅ All responses cite EE2 line numbers or sections
4. ✅ Anti-patterns explicitly flagged with ⚠️ warnings
5. ✅ SME justifications included in responses
6. ✅ No false recommendations for set -eu or forced exits
7. ✅ Overall false positive rate < 15% (down from 70%)

---

## Testing Protocol

### Phase 3 Testing (After Enhanced Ingestion)

**Step 1: Enhanced Ingestion**
```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node/scripts
python3 ingest_ee2_enhanced_v5.py \
    --source /mcp_rag_eib/eib-mcp-rag-server/sdd_framework/phase2_annotations/ \
    --collection ee2-standards-v6-0-0-corrected
```

**Step 2: Query Testing**
```bash
# Test each query via MCP tool
mcp_eib-mcp-rag-f_search_ee2_standards \
    query="What error handling is required at the top of bash operational scripts"
```

**Step 3: Response Analysis**
- [ ] Check for set -eu recommendations (should be 0)
- [ ] Check for exit statement recommendations (should be 0 for operational)
- [ ] Check for line number citations (should be present)
- [ ] Check for anti-pattern warnings (should be present)
- [ ] Check for context awareness (operational vs utility vs test)

**Step 4: Metrics Collection**
```python
# False positive detection
false_positives = {
    'set_eu_recommended': 0,  # Should be 0
    'exit_statements_recommended': 0,  # Should be 0 for operational
    'context_confused': 0,  # Should be 0
}

# Expected improvements
baseline_fp_rate = 0.70  # 70%
target_fp_rate = 0.15    # 15%
improvement = (baseline_fp_rate - actual_fp_rate) / baseline_fp_rate
# Target: >50% improvement (0.55+ reduction)
```

---

## SME Validation

### Review Questions for SME Sign-Off

**For EVS Development Team Lead:**
1. Do corrected responses match EVS operational experience?
2. Are false positives (set -eu, exit statements) eliminated?
3. Are recommended alternatives (err_chk, err_exit) accurate?

**For NCO SPA:**
1. Do anti-pattern warnings correctly reflect NCO operational guidance?
2. Is natural return behavior properly documented?
3. Are workflow integration concerns addressed?

**For EIB Operations:**
1. Would corrected recommendations prevent operational issues?
2. Is context discrimination (operational vs test) clear?
3. Are there any remaining false positives?

**For EMC Global Workflow:**
1. Are recommendations compatible with global-workflow standards?
2. Do examples match global-workflow coding patterns?
3. Are there conflicts with existing documentation?

---

## Documentation Updates After Testing

**When testing complete:**

1. Update `PHASE_2_ANNOTATION_TRACKER.md` with actual metrics
2. Update changelog with measured false positive reduction
3. Create `PHASE_2_RESULTS.md` with before/after comparisons
4. Update `SDD_FRAMEWORK_STATUS.md` to Phase 2 Complete
5. Create Phase 3 plan based on results

**Deliverables:**
- [ ] Test results spreadsheet (5 queries × 2 conditions = 10 responses)
- [ ] False positive rate calculation (baseline vs corrected)
- [ ] SME satisfaction scores (4 reviewers × 3 questions = 12 ratings)
- [ ] Improvement percentage vs 55% target
- [ ] Lessons learned for future annotation phases

---

**Last Updated**: November 19, 2025  
**Status**: Testing protocol ready, pending Phase 3 ingestion and SME sign-off
