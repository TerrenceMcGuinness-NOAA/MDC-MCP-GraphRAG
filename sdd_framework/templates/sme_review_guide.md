# SME Review Guide - Enhanced EE2 Embeddings
**What to look for when reviewing semantic annotations**

## Purpose

This guide helps subject matter experts (SMEs) review the semantic annotations added to EE2 standards documentation. Your expertise is critical for ensuring the system captures the **intent** behind requirements, not just the text.

---

## Quick Overview

**What we did:** Added invisible "tags" to the RST source files that capture:
- **Why** requirements exist (intent)
- **How critical** they are (priority/severity)
- **What** they prevent or enable (rationale)
- **How** they relate to each other (relationships)
- **What** good examples look like (code patterns)

**Why this matters:** AI can now understand *why* you require something, not just pattern-match keywords.

**Your role:** Validate whether the tags accurately capture your expert knowledge.

---

## Review Checklist

### 1. Intent Accuracy ✓

**What to Check:**
```rst
.. mcp:intent:: rapid_error_detection
   :description: Enable immediate error detection and recovery for 99% on-time delivery
   :enforcement: runtime_check
   :rationale: Operational reliability requires catching failures at earliest point
```

**Questions to Ask:**
- [ ] Does the `:description:` capture the true purpose?
- [ ] Is the `:rationale:` the real reason this exists?
- [ ] Is `:enforcement:` (runtime/compile/manual) correct?
- [ ] Would a new developer understand *why* from this?

**Red Flags:**
- ❌ Circular reasoning ("we use err_chk to check errors")
- ❌ Missing the operational impact ("for 99% delivery rate")
- ❌ Wrong enforcement level (manual vs automated)

---

### 2. Priority/Severity Validation ✓

**What to Check:**
```rst
.. mcp:compliance:: error_handling
   :priority: critical
   :type: mandatory
   :scope: global

.. mcp:severity:: must
   :rationale: Critical for operational stability and rapid troubleshooting
   :exceptions: None
```

**Priority Levels:**
- **critical** - System fails/operational delivery at risk if violated
- **high** - Data quality/reliability significantly impacted
- **medium** - Maintainability/efficiency affected
- **low** - Stylistic/convenience

**Severity Levels (RFC 2119):**
- **must** / **must-not** - Absolute requirement
- **should** / **should-not** - Strong recommendation, exceptions allowed
- **may** - Optional, discretionary

**Questions to Ask:**
- [ ] Does the priority reflect real operational impact?
- [ ] Is the severity level correct (must vs should)?
- [ ] Are exceptions properly documented?
- [ ] Is scope accurate (global vs system-specific)?

**Red Flags:**
- ❌ Everything marked "critical" (severity inflation)
- ❌ "must" with undocumented exceptions
- ❌ Priority doesn't match rationale

---

### 3. Utility/Tool Metadata ✓

**What to Check:**
```rst
.. mcp:utility:: err_chk
   :module: prod_util
   :category: error-handling
   :required: yes
   :deprecated: no
```

**Questions to Ask:**
- [ ] Is `:module:` correct?
- [ ] Does `:category:` make sense?
- [ ] Is `:required:` accurate (truly required or recommended)?
- [ ] Is deprecation status current?

**Common Categories:**
- `error-handling` - err_chk, err_exit
- `data-management` - cpreq, cpfs
- `messaging` - mail.py, startmsg
- `initialization` - prep_step
- `date-utilities` - finddate.sh, ndate, setpdy.sh

**Red Flags:**
- ❌ Wrong module name
- ❌ "required: yes" but standard says "recommended"
- ❌ Miscategorized (messaging under error-handling)

---

### 4. Code Example Relevance ✓

**What to Check:**
```rst
.. mcp:example:: err_chk_usage
   :language: bash
   :context: error_checking_after_command
   :demonstrates: Standard error checking pattern with err_chk

   .. code-block:: bash
   
      some_critical_command arg1 arg2
      export err=$?
      err_chk
```

**Questions to Ask:**
- [ ] Does the example show the **right** way?
- [ ] Is `:demonstrates:` accurate?
- [ ] Does `:context:` explain when to use it?
- [ ] Would this help a new developer?

**Missing Examples to Flag:**
- ❌ Loop example for err_chk
- ❌ Pipeline error handling
- ❌ Multiple error checks in sequence
- ❌ Optional vs required file handling

---

### 5. Relationship Accuracy ✓

**What to Check:**
```rst
.. mcp:see-also:: production_utilities
   :related: [err_exit, err_chk]
   :type: prerequisite
```

**Relationship Types:**
- `prerequisite` - Must understand/have this first
- `reference` - Related concept for more info
- `alternative` - Different approach to same goal
- `example` - Concrete usage example

**Questions to Ask:**
- [ ] Are the `:related:` items truly related?
- [ ] Is `:type:` the right relationship?
- [ ] Are any important relationships missing?

**Common Relationships:**
```
prep_step → Fortran executables (prerequisite)
err_chk → err_exit (alternative)
cpreq → cpfs (reference - both copy utilities)
mail.py → WARNING messages (example)
```

**Red Flags:**
- ❌ Circular references
- ❌ Wrong relationship type
- ❌ Missing critical dependencies

---

### 6. Pattern Recognition ✓

**What to Check:**
```rst
.. mcp:pattern:: fail_fast_pattern
   :category: error-handling
   :anti-pattern: no
   :alternatives: []

  Failures must not be allowed to propagate downstream of the point where 
  the problem can first be detected; jobs should fail with err_chk or 
  err_exit as soon as a fatal error is encountered.
```

**Questions to Ask:**
- [ ] Is this truly a pattern (repeated across code)?
- [ ] Is it correctly identified (pattern vs anti-pattern)?
- [ ] Are alternatives listed when they exist?
- [ ] Would recognizing this pattern help compliance checking?

**Common Patterns:**
- `fail_fast_pattern` - Detect and abort at earliest point
- `error_check_pattern` - command → export err → err_chk
- `atomic_copy_pattern` - copy to .tmp → fsync → move
- `optional_file_pattern` - check existence → skip or fail

**Anti-Patterns to Watch For:**
- Silent failures (no err_chk after critical command)
- Downstream error propagation
- Partial file writes without fsync
- Missing FATAL ERROR prefix

---

### 7. Environment Variable Metadata ✓

**What to Check:**
```rst
.. mcp:envvar:: PDY
   :set-by: j-job
   :required: yes
   :scope: per-cycle
   :format: YYYYMMDD

Date in YYYYMMDD format representing the current processing day.
```

**Questions to Ask:**
- [ ] Is `:set-by:` accurate (job-card/j-job/ex-script/module)?
- [ ] Is `:required:` correct?
- [ ] Does `:scope:` match reality (per-cycle/per-job/global)?
- [ ] Is `:format:` precisely documented?

**Red Flags:**
- ❌ Wrong lifecycle (set-by)
- ❌ Format string incorrect (YYYYMMDD vs YYYYMMDDHH)
- ❌ Scope mismatch (per-cycle but actually global)

---

## Review Workflow

### Step 1: High-Level Scan
1. Open annotated section (e.g., `pilot_annotation_error_handling.md`)
2. Skim compliance categories - do they cover the section?
3. Check priority distribution - is everything "critical"?

### Step 2: Deep Dive by Directive
For each `mcp:intent::`:
1. Read the `:description:` and `:rationale:`
2. Ask: "Is this the real reason?"
3. Check: Does enforcement match reality?

For each `mcp:utility::`:
1. Verify module name and category
2. Check required vs recommended
3. Validate deprecation status

For each `mcp:example::`:
1. Does it demonstrate the right pattern?
2. Is context clear?
3. Would you show this to a trainee?

### Step 3: Cross-Reference Check
1. Follow `mcp:see-also::` links
2. Verify relationships are bidirectional
3. Flag missing connections

### Step 4: Gap Analysis
1. What's missing from annotations?
2. What examples should be added?
3. What intent isn't captured?

---

## Common SME Feedback

### Adding Missing Intent
```diff
.. mcp:intent:: rapid_error_detection
   :description: Enable immediate error detection and recovery
   :enforcement: runtime_check
-  :rationale: Operational reliability requires catching failures at earliest point
+  :rationale: 99% on-time delivery SLA requires detection within 5 minutes of failure
```

### Correcting Priority
```diff
.. mcp:compliance:: messaging
-  :priority: medium
+  :priority: low
   :type: recommended
   :scope: global
```

### Adding Exception
```diff
.. mcp:severity:: must
   :rationale: Critical for operational stability
-  :exceptions: None
+  :exceptions: Data assimilation jobs exempt due to ensemble workflow
```

### Expanding Examples
```rst
.. mcp:example:: err_chk_in_loop
   :language: bash
   :context: error_checking_in_loop
   :demonstrates: err_chk pattern inside loop with file iteration

   .. code-block:: bash
   
      for file in $input_files; do
          process_file $file
          export err=$?
          err_chk
      done
```

### Flagging Anti-Pattern
```rst
.. mcp:pattern:: silent_failure
   :category: error-handling
   :anti-pattern: yes
   :alternatives: [error_check_pattern]

   # WRONG - no error checking
   critical_command
   continue_processing

   # RIGHT - check errors
   critical_command
   export err=$?
   err_chk
   continue_processing
```

---

## What Good Annotations Look Like

### ✅ Clear Intent with Operational Context
```rst
.. mcp:intent:: atomic_file_operations
   :description: Ensure files are completely written before becoming accessible
   :enforcement: automated
   :rationale: Prevent downstream jobs from reading partial files which causes
                cascade failures across 6-hour forecast window
```

### ✅ Precise Severity with Documented Exceptions
```rst
.. mcp:severity:: should
   :rationale: Prevents unnecessary fatal errors when optional files missing
   :exceptions: When file is truly required, use err_exit directly instead
```

### ✅ Actionable Example with Context
```rst
.. mcp:example:: cpfs_with_validation
   :language: bash
   :context: optional_vs_required_files
   :demonstrates: Pre-checking file existence before atomic copy

   .. code-block:: bash
   
      # Optional file - skip if missing
      if [ -f "$COMIN/optional_file.dat" ]; then
          cpfs $COMIN/optional_file.dat $DATA/
      fi
      
      # Required file - fail explicitly if missing
      if [ ! -f "$COMIN/required_file.dat" ]; then
          err_exit "Required file missing: $COMIN/required_file.dat"
      fi
      cpfs $COMIN/required_file.dat $DATA/
```

---

## What to Flag for Discussion

### 🚩 Ambiguous Requirement
When the text says "should" but severity is marked "must":
```rst
The variable cycle must be set...  # Text says "must"

.. mcp:severity:: should            # Annotation says "should"
```

### 🚩 Missing Rationale
When the "why" isn't captured:
```rst
.. mcp:intent:: prep_step_usage
   :description: Unset FORT## variables before Fortran execution
   :rationale: ???  # Why? What breaks if you don't?
```

### 🚩 Incomplete Relationships
When utilities are mentioned but not cross-referenced:
```text
"Use err_chk after command execution, or err_exit for immediate abort"

# Missing:
.. mcp:see-also:: err_exit
   :type: alternative
```

### 🚩 Example-Reality Gap
When examples don't match actual production code:
```bash
# Example shows:
export err=$?
err_chk

# Production actually does:
export err=$?; err_chk  # Same line - should example match?
```

---

## Impact of Your Review

### What SME Refinement Enables

**Before (Text Search):**
Query: "How do I check for errors?"
Result: Returns all text containing "error" (hundreds of hits)

**After (Intent-Aware):**
Query: "How do I check for errors?"
Result: Returns err_chk with:
- Intent: rapid_error_detection
- Pattern: error_check_pattern
- Examples: err_chk_usage, err_chk_in_loop
- Related: err_exit (alternative for immediate abort)
- Priority: critical
- Severity: must

**Before:**
System flags: `if [ $err -ne 0 ]; then exit 1; fi`
Reason: Doesn't match "err_chk" keyword

**After:**
System understands:
- This implements error_check_pattern intent
- Uses exit instead of err_exit → flags missing "FATAL ERROR:" prefix
- Suggests: Use err_exit for consistent operational messaging

---

## Review Output Format

### Template for Feedback

```markdown
## Section: [Error Handling / Production Utilities]

### Intent Accuracy
- ✅ rapid_error_detection - rationale correct
- ⚠️ descriptive_error_messages - add "enables automated log parsing" to rationale
- ❌ atomic_file_operations - enforcement should be "automated" not "manual"

### Priority/Severity
- ✅ error_handling: critical priority appropriate
- ⚠️ messaging: should be "low" not "medium" - not production-critical
- ✅ Severity levels match standard language

### Examples
- ✅ err_chk_usage - good basic example
- ⚠️ Add example: err_chk inside loop
- ⚠️ Add example: pipeline error handling (command1 | command2)
- ❌ err_exit_usage - example should show time-stamping feature

### Missing Annotations
- Add mcp:pattern for "silent_failure" anti-pattern
- Add mcp:example for prep_step before multiple Fortran programs
- Add mcp:see-also linking err_chk to $err variable definition

### Questions/Clarifications
1. Is prep_step truly "required: yes" or just recommended?
2. Should getsystem be marked "deprecated: yes" or keep as "must-not use"?
3. What's the operational impact if cpfs fails mid-copy?
```

---

## Ready to Review!

**Files to Review:**
1. `sdd_framework/templates/mcp_rst_directive_templates.md` - Directive definitions
2. `sdd_framework/templates/pilot_annotation_error_handling.md` - Sample annotation

**Timeline:**
- Review pilot annotations
- Provide feedback
- Iterate on 1-2 more sections
- Scale to full standards.rst

**Questions?** Flag anything unclear - this is a collaborative refinement process!
