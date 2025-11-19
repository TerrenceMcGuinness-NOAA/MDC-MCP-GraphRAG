# Phase 2 Workflow Visualization

```
+-----------------------------------------------------------------------+
|                  PHASE 2: SME-DRIVEN ANNOTATION                       |
|                 (November 19, 2025 - INITIATED)                       |
+-----------------------------------------------------------------------+

+-----------------------------------------------------------------------+
|  STEP 1: SME FEEDBACK COLLECTION                                      |
+-----------------------------------------------------------------------+
|                                                                       |
|  SME Report #1: "set -eu" False Positives                             |
|  +---------------------------------------------------------------+    |
|  | "AI says set -eu is missing in almost every script in EVS,    |    |
|  |  but this line is not listed once in NCO EE2 documentation"   |    |
|  +---------------------------------------------------------------+    |
|                                |                                      |
|  SME Report #2: Forced Exit False Positives                           |
|  +---------------------------------------------------------------+    |
|  | "AI says to add forced exits everywhere. But NCO SPAs         |    |
|  |  specifically asked us to REMOVE exit 0 and exit 1 lines"     |    |
|  +---------------------------------------------------------------+    |
|                                |                                      |
|  SME Validation #3: err_chk/err_exit Correct                          |
|  +---------------------------------------------------------------+    |
|  | "We do use err_chk extensively throughout EVS - AI is         |    |
|  |  correct when it detects these utilities"                     |    |
|  +---------------------------------------------------------------+    |
|                                                                       |
|  Impact Assessment:                                                   |
|    - False Positive #1: ~80% of scripts                               |
|    - False Positive #2: ~60% of scripts                               |
|    - Overall FP Rate: ~70% (CRITICAL ISSUE)                           |
+-----------------------------------------------------------------------+
                                |
+-----------------------------------------------------------------------+
|  STEP 2: EVIDENCE GATHERING (EE2 Documentation Analysis)              |
+-----------------------------------------------------------------------+
|                                                                       |
|  Research EE2 Standards (standards.rst)                               |
|                                                                       |
|  Evidence for Issue #1 (set -eu):                                     |
|  +---------------------------------------------------------------+    |
|  | Line 588-595: "Enable debug logging...set -x"                 |    |
|  | Line 873:      J-job Example 8 -> "set -x" ONLY               |    |
|  | Line 950:      ex-script Example 9 -> "set -x" ONLY           |    |
|  |                                                               |    |
|  | [OK] PROOF: NO "set -e" or "set -eu" in any EE2 example       |    |
|  +---------------------------------------------------------------+    |
|                                                                       |
|  Evidence for Issue #2 (forced exits):                                |
|  +---------------------------------------------------------------+    |
|  | Line 187-195: "jobs should fail with err_chk or err_exit"     |    |
|  | Line 912:      Example shows "export err=$?; err_chk"         |    |
|  | Line 978:      Example shows "err_exit 'message'"             |    |
|  |                                                               |    |
|  | [OK] PROOF: ONLY err_chk/err_exit documented (no exit 0/1)    |    |
|  +---------------------------------------------------------------+    |
|                                                                       |
|  Evidence Chain Validated:                                            |
|    --> EE2 examples are authoritative source                          |
+-----------------------------------------------------------------------+
                                |
+-----------------------------------------------------------------------+
|  STEP 3: ANNOTATION DESIGN (MCP Directive Creation)                   |
+-----------------------------------------------------------------------+
|                                                                       |
|  Create RST File with MCP Semantic Directives                         |
|                                                                       |
|  Correction #1: set -x (NOT set -eu)                                  |
|  +---------------------------------------------------------------+    |
|  | .. mcp:sme_correction:: bash_error_handling_requirement       |    |
|  |    :date: 2025-11-19                                          |    |
|  |    :severity: critical                                        |    |
|  |    :false_positive_rate: ~80%                                 |    |
|  |                                                               |    |
|  | .. mcp:anti_pattern:: adding_set_e_or_set_eu                  |    |
|  |    :severity: must_not                                        |    |
|  |    :sme_justification: Not in EE2 standards                   |    |
|  |                                                               |    |
|  | .. mcp:correct_pattern:: ee2_script_header                    |    |
|  |    :ee2_section: "Examples 8 & 9"                             |    |
|  |    set -x  # THIS IS CORRECT                                  |    |
|  +---------------------------------------------------------------+    |
|                                                                       |
|  Correction #2: Natural Returns (NOT forced exits)                    |
|  +---------------------------------------------------------------+    |
|  | .. mcp:anti_pattern:: forced_exit_in_operational_job          |    |
|  |    :sme_justification: NCO SPA guidance                       |    |
|  |    exit 0  # [X] WRONG - prohibited                           |    |
|  |                                                               |    |
|  | .. mcp:correct_pattern:: natural_return_with_err_utilities    |    |
|  |    export err=$?; err_chk  # [OK] CORRECT                     |    |
|  |    err_exit "message"      # [OK] CORRECT                     |    |
|  +---------------------------------------------------------------+    |
|                                                                       |
|  Context Discrimination Added:                                        |
|  +---------------------------------------------------------------+    |
|  | .. mcp:context_types::                                        |    |
|  |                                                               |    |
|  | operational_job (jobs/, scripts/ex*)                          |    |
|  |    - Strict EE2 compliance                                    |    |
|  |    - NO exit statements                                       |    |
|  |    - MUST use err_chk/err_exit                                |    |
|  |                                                               |    |
|  | utility_script (ush/)                                         |    |
|  |    - EE2 variable standards                                   |    |
|  |    - More flexibility                                         |    |
|  |                                                               |    |
|  | test_script (tests/)                                          |    |
|  |    - Standard shell practices OK                              |    |
|  |    - Exit statements allowed                                  |    |
|  +---------------------------------------------------------------+    |
|                                                                       |
|  AI Guidance Rules Embedded:                                          |
|    - Rule 1: Literal compliance only (no "helpful" additions)         |
|    - Rule 2: Context-aware recommendations (detect script type)       |
|    - Rule 3: Anti-pattern enforcement (flag violations)               |
+-----------------------------------------------------------------------+
                                |
+-----------------------------------------------------------------------+
|  STEP 4: DOCUMENTATION PACKAGE                                        |
+-----------------------------------------------------------------------+
|                                                                       |
|  Files Created (Total: ~53KB)                                         |
|                                                                       |
|  +---------------------------------------------------------------+    |
|  | FILE: ee2_error_handling_sme_corrections.rst                  |    |
|  |    - 2 mcp:sme_correction directives                          |    |
|  |    - 3 mcp:anti_pattern directives                            |    |
|  |    - 2 mcp:correct_pattern directives                         |    |
|  |    - 3 mcp:ai_guidance_rule directives                        |    |
|  |    - Evidence with line numbers                               |    |
|  |    - SME sign-off block (4 reviewers)                         |    |
|  |       21,445 bytes                                            |    |
|  +---------------------------------------------------------------+    |
|                                                                       |
|  +---------------------------------------------------------------+    |
|  | DOC: PHASE_2_ANNOTATION_TRACKER.md                            |    |
|  |    - Status tracking                                          |    |
|  |    - Impact analysis (55-75% FP reduction)                    |    |
|  |    - SME review schedule                                      |    |
|  |    - Next steps checklist                                     |    |
|  |       ~8KB                                                    |    |
|  +---------------------------------------------------------------+    |
|                                                                       |
|  +---------------------------------------------------------------+    |
|  | TEST: PHASE_2_TESTING_PROTOCOL.md                             |    |
|  |    - 5 test queries (before/after)                            |    |
|  |    - Expected behavior changes                                |    |
|  |    - Validation metrics                                       |    |
|  |    - SME validation questions                                 |    |
|  |       ~11KB                                                   |    |
|  +---------------------------------------------------------------+    |
|                                                                       |
|  +---------------------------------------------------------------+    |
|  | REF: mcp_rst_enhanced_directives_phase2.md                    |    |
|  |    - Directive catalog (9 types)                              |    |
|  |    - Parser requirements                                      |    |
|  |    - Embedding strategy                                       |    |
|  |    - Validation rules                                         |    |
|  |       ~13KB                                                   |    |
|  +---------------------------------------------------------------+    |
|                                                                       |
|  +---------------------------------------------------------------+    |
|  | SUMMARY: PHASE_2_SUMMARY.md (this file)                       |    |
|  |    - Executive summary                                        |    |
|  |    - Impact metrics                                           |    |
|  |    - Next steps                                               |    |
|  |    - SME review questions                                     |    |
|  |       ~9KB                                                    |    |
|  +---------------------------------------------------------------+    |
|                                                                       |
|  NOTE: CHANGELOG.md (updated with Phase 2 entry)                     |
+-----------------------------------------------------------------------+
                                |
+-----------------------------------------------------------------------+
|  CURRENT STATUS: [PENDING] PENDING SME REVIEW                         |
+-----------------------------------------------------------------------+
|                                                                       |
|  Target Date: November 22, 2025 (3 business days)                     |
|                                                                       |
|  Required Sign-Offs:                                                  |
|  +---------------------------------------------------------------+    |
|  | [ ] EVS Development Team Lead                                 |    |
|  |   - Validates: False positive accuracy                        |    |
|  |                                                               |    |
|  | [ ] NCO SPA (Site Preparation Analyst)                        |    |
|  |   - Validates: Anti-pattern documentation                     |    |
|  |                                                               |    |
|  | [ ] EIB Operations Representative                             |    |
|  |   - Validates: No operational disruption                      |    |
|  |                                                               |    |
|  | [ ] EMC Global Workflow Maintainers                           |    |
|  |   - Validates: global-workflow compatibility                  |    |
|  +---------------------------------------------------------------+    |
+-----------------------------------------------------------------------+
                                |
+-----------------------------------------------------------------------+
|  PHASE 3: ENHANCED INGESTION (After SME Sign-Off)                     |
+-----------------------------------------------------------------------+
|                                                                       |
|  Step 1: Enhanced Ingestion Script                                    |
|  +---------------------------------------------------------------+    |
|  | $ python3 ingest_ee2_enhanced_v5.py \                         |    |
|  |     --source phase2_annotations/ \                            |    |
|  |     --collection ee2-standards-v6-0-0-corrected               |    |
|  |                                                               |    |
|  | Output:                                                       |    |
|  | [OK] 15 documents created                                     |    |
|  | [OK] 45 metadata fields populated                             |    |
|  | [OK] 10 directives parsed (2 corrections, 3 anti-patterns,    |    |
|  |                           2 correct-patterns, 3 rules)        |    |
|  | [OK] 3 anti_pattern -> correct_pattern links                  |    |
|  +---------------------------------------------------------------+    |
|                                                                       |
|  Step 2: Query Testing (5 Test Cases)                                 |
|  +---------------------------------------------------------------+    |
|  | Test Query 1: "Bash script error handling requirements"       |    |
|  | Test Query 2: "Should I add set -eu?"                         |    |
|  | Test Query 3: "Exit statement usage"                          |    |
|  | Test Query 4: "Test script error handling"                    |    |
|  | Test Query 5: "Utility script error handling"                 |    |
|  |                                                               |    |
|  | Expected: [X]->[OK] transformation on all queries             |    |
|  +---------------------------------------------------------------+    |
|                                                                       |
|  Step 3: Validation & Measurement                                     |
|  +---------------------------------------------------------------+    |
|  | Baseline FP Rate:   70%                                       |    |
|  | Target FP Rate:     <15%                                      |    |
|  | Expected Reduction: 55%                                       |    |
|  |                                                               |    |
|  | Metrics:                                                      |    |
|  | - set -eu recommendations:  80% -> <5%  (75% reduction)       |    |
|  | - Forced exit recommendations: 60% -> <10% (50% reduction)    |    |
|  +---------------------------------------------------------------+    |
+-----------------------------------------------------------------------+
                                |
+-----------------------------------------------------------------------+
|  SUCCESS CRITERIA                                                     |
+-----------------------------------------------------------------------+
|                                                                       |
|  Phase 2 Complete:                                                    |
|  [OK] Annotations created with SME evidence                           |
|  [PENDING] 4 SME reviews with sign-off                                |
|  [PENDING] Validation testing shows >50% FP reduction                 |
|  [PENDING] No operational objections                                  |
|  [PENDING] Documentation updated                                      |
|                                                                       |
|  Phase 3 Ready:                                                       |
|  [PENDING] Enhanced ingestion script tested                           |
|  [PENDING] ChromaDB collection created                                |
|  [PENDING] Query testing framework prepared                           |
|  [PENDING] Measurement methodology documented                         |
+-----------------------------------------------------------------------+

KEY ACHIEVEMENTS TODAY:
========================
[OK] Documented 2 critical false positives affecting 60-80% of scripts
[OK] Established evidence chain from EE2 standards with line numbers
[OK] Created semantic annotations using 5 new MCP directive types
[OK] Embedded AI guidance rules for literal compliance and context awareness
[OK] Produced complete documentation package (~53KB)
[OK] Designed testing protocol with 5 before/after test cases
[OK] Expected impact: 55-75% reduction in false positive rate

NEXT MILESTONE:
===============
SME Review Sign-Off (Target: November 22, 2025)
```
