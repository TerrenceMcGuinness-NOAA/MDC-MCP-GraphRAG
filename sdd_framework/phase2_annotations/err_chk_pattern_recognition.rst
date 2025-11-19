========================================================================
Phase 2 Annotation: err_chk Pattern Recognition and Gap Detection
========================================================================

:Document Type: Semantic Annotation (Phase 2)
:Category: error_handling
:Directive Type: correct_pattern, anti_pattern, ai_guidance_rule
:Version: 2.0
:Last Updated: 2025-11-19
:SME: Terry McGuinness (terry.mcguinness@noaa.gov)
:Purpose: Teach AI to recognize proper err_chk usage AND identify specific gaps

========================================================================
Context: Two Compliance Scenarios in EVS Repository
========================================================================

**Scenario A: Compliant Pattern (rtofs_prep_regions.sh)**
   EVS repository file ``ush/rtofs/rtofs_prep_regions.sh`` demonstrates 
   CORRECT EE2 error handling with consistent ``err_chk`` usage after 
   critical operations (26 occurrences across 430 lines).

**Scenario B: Gap Pattern (evs_href_prepare.sh)**
   EVS repository file ``ush/cam/evs_href_prepare.sh`` has INCONSISTENT 
   error handling - many ``cp`` commands without ``err_chk`` (lines 42-43, 
   56, 65, 74, 83, 92, 101, 110, 119, 131-133, etc.).

**AI Challenge:**
   Previous scans flagged ALL files with generic "missing error handling" 
   without distinguishing between:
   
   1. Files that consistently use ``err_chk`` (compliant)
   2. Files with partial usage (gaps to fix)
   3. Files with no error handling (critical issues)

========================================================================
CORRECT PATTERN: Consistent err_chk After Critical Operations
========================================================================

.. mcp:correct_pattern:: err_chk_after_critical_operations
   :category: error_handling
   :severity: required
   :evidence: standards.rst line 191, EVS ush/rtofs/rtofs_prep_regions.sh
   :ee2_section: Error Handling Utilities

**Pattern Description:**
   After every critical operation (file operations, data processing, 
   external commands), immediately capture exit status and call ``err_chk``.

**Critical Operations Requiring err_chk:**
   - File operations: ``cp``, ``mv``, ``ln``, ``rm``
   - Data processing: ``gen_vx_mask``, ``ncks``, ``ncrcat``, ``cdo``, ``wgrib2``
   - Python scripts: ``python script.py`` or ``${USHevs}/script.py``
   - MET tools: ``grid_stat``, ``point_stat``, ``ensemble_stat``
   - Archive operations: Commands writing to ``$COMOUT`` directories

**Compliant Example (rtofs_prep_regions.sh lines 17-22):**

.. code-block:: bash

   # Generate ice mask using MET tool
   gen_vx_mask \
   $EVSINprep/$RUN.$INITDATE/$OBTYPE/rtofs_glo_2ds_f000_ice.$OBTYPE.nc \
   $EVSINprep/$RUN.$INITDATE/$OBTYPE/rtofs_glo_2ds_f000_ice.$OBTYPE.nc \
   $DATA/$RUN.$INITDATE/$OBTYPE/ice_mask.nc \
   -type data -mask_field 'name="ice_coverage"; level="(0,*,*)";' -thresh lt0.15 -name ice_mask
   export err=$?; err_chk  # ✅ CORRECT: Error checking immediately after critical operation

**Why This is Correct:**
   - Operation failure detected immediately
   - ``err_chk`` function logs error context and handles job notification
   - Prevents downstream failures from bad/missing outputs
   - Provides operator visibility into failure point

**Consistency Pattern (rtofs_prep_regions.sh):**
   File has 26 ``err_chk`` calls across 20+ regions (north_atlantic, 
   south_pacific, indian, mediterranean, arctic) - demonstrates systematic 
   application of error handling throughout entire script.

========================================================================
ANTI-PATTERN: File Operations Without err_chk
========================================================================

.. mcp:anti_pattern:: cp_mv_without_err_chk
   :category: error_handling
   :severity: must_fix
   :false_positive_rate: <5%
   :evidence: EVS ush/cam/evs_href_prepare.sh lines 42-43, 56, 65, 74, 83, etc.
   :sme_justification: File operations (cp, mv, ln) can fail silently due to disk space, permissions, network issues. Without err_chk, script continues with missing/incomplete data causing downstream failures that are hard to diagnose.
   :context: operational_scripts

**Anti-Pattern Description:**
   File operations (``cp``, ``mv``, ``ln``) executed without subsequent 
   ``err_chk`` call, allowing silent failures to propagate.

**Non-Compliant Example (evs_href_prepare.sh lines 42-43):**

.. code-block:: bash

   if [ -s $COMCCPA/ccpa.${vday}/00/ccpa.t00z.03h.hrap.conus.gb2 ] && \
      [ -s $COMCCPA/ccpa.${vday}/00/ccpa.t00z.01h.hrap.conus.gb2 ] ; then
      for vhr in 00 ; do
         # ❌ WRONG: cp without error checking
         cp $COMCCPA/ccpa.${vday}/00/ccpa.t${vhr}z.01h.hrap.conus.gb2  $ccpadir/ccpa01h.t${vhr}z.G240.grib2
         # ❌ WRONG: Another cp without error checking
         cp $COMCCPA/ccpa.${vday}/00/ccpa.t${vhr}z.03h.hrap.conus.gb2  $ccpadir/ccpa03h.t${vhr}z.G240.grib2
      done
      has_ccpa=$((has_ccpa + 1 ))
   fi

**Why This is Wrong:**
   - ``cp`` can fail (disk full, permissions, I/O error, network timeout)
   - Script increments ``has_ccpa`` counter assuming success
   - Downstream processing uses incomplete/missing data
   - Operators don't receive notification of copy failure
   - Root cause analysis difficult ("where did data disappear?")

**Correct Implementation:**

.. code-block:: bash

   if [ -s $COMCCPA/ccpa.${vday}/00/ccpa.t00z.03h.hrap.conus.gb2 ] && \
      [ -s $COMCCPA/ccpa.${vday}/00/ccpa.t00z.01h.hrap.conus.gb2 ] ; then
      for vhr in 00 ; do
         cp $COMCCPA/ccpa.${vday}/00/ccpa.t${vhr}z.01h.hrap.conus.gb2  $ccpadir/ccpa01h.t${vhr}z.G240.grib2
         export err=$?; err_chk  # ✅ Check first copy
         cp $COMCCPA/ccpa.${vday}/00/ccpa.t${vhr}z.03h.hrap.conus.gb2  $ccpadir/ccpa03h.t${vhr}z.G240.grib2
         export err=$?; err_chk  # ✅ Check second copy
      done
      has_ccpa=$((has_ccpa + 1 ))
   fi

========================================================================
AI GUIDANCE RULE: Pattern Recognition for Gap Detection
========================================================================

.. mcp:ai_guidance_rule:: recognize_err_chk_gaps_not_absence
   :category: error_handling
   :priority: high
   :applies_to: scan_repository_compliance, analyze_ee2_compliance

**Rule Description:**
   When analyzing error handling compliance, AI must distinguish between:
   
   **Level 1: Fully Compliant (No Issues)**
      File consistently uses ``err_chk`` after ALL critical operations.
      Example: ``ush/rtofs/rtofs_prep_regions.sh`` (26 err_chk calls, 
      comprehensive coverage).
      
      **AI Action:** Mark as compliant, do NOT flag as violation.
   
   **Level 2: Partial Compliance (Gaps)**
      File uses ``err_chk`` in some places but missing in others.
      Example: ``ush/cam/evs_href_prepare.sh`` (some err_chk usage 
      at lines 197, 293, 370 but missing at lines 42-43, 56, 65, etc.).
      
      **AI Action:** Report as "Inconsistent error handling - missing 
      err_chk after file operations" with SPECIFIC line numbers where 
      gaps exist.
   
   **Level 3: Non-Compliant (Absent)**
      File has NO ``err_chk`` usage despite critical operations.
      
      **AI Action:** Report as "Missing error handling - no err_chk usage 
      found" with recommendation to add throughout.

**Detection Algorithm:**

.. code-block:: python

   def analyze_err_chk_compliance(file_content, file_path):
       """
       Analyze err_chk usage patterns to distinguish compliance levels.
       """
       critical_ops = find_critical_operations(file_content)  # cp, mv, gen_vx_mask, etc.
       err_chk_calls = find_err_chk_patterns(file_content)    # export err=$?; err_chk
       
       if not critical_ops:
           return "no_critical_operations"  # Not applicable
       
       coverage_ratio = len(err_chk_calls) / len(critical_ops)
       
       if coverage_ratio >= 0.9:
           # 90%+ coverage = compliant
           return {
               "status": "compliant",
               "level": 1,
               "message": f"Consistent err_chk usage ({len(err_chk_calls)}/{len(critical_ops)} operations covered)",
               "example_file": file_path
           }
       elif coverage_ratio > 0:
           # Some coverage = partial compliance (gaps)
           missing_lines = find_critical_ops_without_err_chk(file_content)
           return {
               "status": "partial_compliance",
               "level": 2,
               "message": f"Inconsistent err_chk usage - {len(missing_lines)} critical operations missing error checks",
               "gaps": missing_lines,
               "fix": "Add 'export err=$?; err_chk' after operations at lines: " + ", ".join(str(line) for line in missing_lines)
           }
       else:
           # No coverage = non-compliant
           return {
               "status": "non_compliant",
               "level": 3,
               "message": f"No err_chk usage found - {len(critical_ops)} critical operations without error handling",
               "recommendation": "Add err_chk pattern throughout script"
           }

========================================================================
AI GUIDANCE RULE: Positive Examples in Recommendations
========================================================================

.. mcp:ai_guidance_rule:: cite_compliant_examples_for_context
   :category: error_handling
   :priority: medium
   :applies_to: generate_compliance_report, explain_workflow_component

**Rule Description:**
   When recommending error handling fixes, AI should cite existing 
   compliant files as positive examples to provide actionable guidance.

**Recommendation Template:**

.. code-block:: text

   **Issue**: Inconsistent error handling in ush/cam/evs_href_prepare.sh
   
   **Gap Details**: 
   - Lines 42-43: cp commands without err_chk
   - Lines 56, 65, 74, 83: Additional cp commands without err_chk
   - Lines 131-133: COMOUT archive operations without err_chk
   
   **Total**: 50+ file operations missing error checks
   
   **Compliant Example** (from same repository):
   See ush/rtofs/rtofs_prep_regions.sh lines 17-22 for correct pattern:
   
   ```bash
   gen_vx_mask \
   $EVSINprep/$RUN.$INITDATE/$OBTYPE/rtofs_glo_2ds_f000_ice.$OBTYPE.nc \
   $EVSINprep/$RUN.$INITDATE/$OBTYPE/rtofs_glo_2ds_f000_ice.$OBTYPE.nc \
   $DATA/$RUN.$INITDATE/$OBTYPE/ice_mask.nc \
   -type data -mask_field 'name="ice_coverage"; level="(0,*,*)";' -thresh lt0.15 -name ice_mask
   export err=$?; err_chk
   ```
   
   **Fix Strategy**:
   Apply rtofs_prep_regions.sh pattern to evs_href_prepare.sh:
   1. After every cp command, add: export err=$?; err_chk
   2. After Python script calls, add: export err=$?; err_chk
   3. After MET tool invocations, add: export err=$?; err_chk
   
   **Why This Matters**:
   rtofs_prep_regions.sh has 26 err_chk calls providing comprehensive 
   error detection. Applying same pattern to evs_href_prepare.sh will 
   catch silent failures and improve operational reliability.

========================================================================
AI GUIDANCE RULE: Repository-Wide Compliance Metrics
========================================================================

.. mcp:ai_guidance_rule:: report_compliance_distribution
   :category: error_handling
   :priority: high
   :applies_to: scan_repository_compliance, generate_compliance_report

**Rule Description:**
   Compliance reports should show distribution across three levels, 
   not just binary compliant/non-compliant.

**Metrics Template:**

.. code-block:: text

   **Error Handling Compliance Summary** (EVS Repository)
   
   | Level | Status | Count | Percentage | Example Files |
   |-------|--------|-------|------------|---------------|
   | 1 | Fully Compliant | 180 | 47.7% | rtofs_prep_regions.sh, glwu_prep_regions.sh, evs_href_spcoutlook.sh |
   | 2 | Partial Compliance (Gaps) | 145 | 38.5% | evs_href_prepare.sh, evs_cam_plots_severe.sh |
   | 3 | Non-Compliant | 52 | 13.8% | [List files with no err_chk usage] |
   | - | Not Applicable | 0 | 0% | [No critical operations] |
   
   **Total Files Analyzed**: 377 shell scripts
   
   **Priority Fixes**:
   1. **Level 2 → Level 1** (145 files): Add err_chk to gaps (lower effort)
   2. **Level 3 → Level 1** (52 files): Implement comprehensive error handling (higher effort)
   
   **Positive Indicators**:
   - 47.7% of files already demonstrate correct pattern (180 compliant examples)
   - err_chk utility widely adopted and understood by development team
   - Pattern exists - need systematic application, not infrastructure changes

========================================================================
SEMANTIC SEARCH QUERIES (For Testing)
========================================================================

Test queries to validate this annotation in RAG system:

1. **"Show me examples of correct err_chk usage in EVS"**
   Expected: Returns rtofs_prep_regions.sh with line numbers

2. **"What files in EVS are missing err_chk after cp commands?"**
   Expected: Returns evs_href_prepare.sh with specific gap line numbers

3. **"How compliant is EVS repository with error handling standards?"**
   Expected: Returns Level 1/2/3 distribution metrics

4. **"What's the difference between rtofs_prep_regions.sh and evs_href_prepare.sh error handling?"**
   Expected: Explains consistent vs inconsistent patterns

5. **"Should I add err_chk after every cp command?"**
   Expected: Yes, with examples from compliant files

========================================================================
TRACEABILITY
========================================================================

:EE2 Evidence: standards.rst line 191 (err_chk and err_exit utilities)
:Positive Example: EVS ush/rtofs/rtofs_prep_regions.sh (26 err_chk calls)
:Gap Example: EVS ush/cam/evs_href_prepare.sh (50+ operations without err_chk)
:Related Annotations: forced_exit_in_operational_job.rst, ee2_script_header_correct.rst
:Phase: 2
:SME Review: November 19, 2025
:Implementation: Phase 2 Hybrid Architecture (generatePhase2Config.js)
:Config Output: phase2_anti_patterns.json (err_chk_pattern_recognition section)

========================================================================
IMPLEMENTATION NOTES
========================================================================

**For generatePhase2Config.js:**
   Add ``err_chk_pattern_recognition`` to correct_patterns with detection 
   logic that distinguishes compliance levels.

**For SemanticSearchTools.js:**
   Update ``analyzeErrorHandling()`` to count err_chk coverage ratio 
   and report Level 1/2/3 status instead of binary flag.

**Expected Outcome:**
   - rtofs_prep_regions.sh: Status = "Compliant (Level 1)"
   - evs_href_prepare.sh: Status = "Partial Compliance (Level 2) - 50+ gaps at lines [list]"
   - Compliance report shows distribution across 3 levels
   - Recommendations cite rtofs_prep_regions.sh as example to emulate

========================================================================
END OF SEMANTIC ANNOTATION
========================================================================
