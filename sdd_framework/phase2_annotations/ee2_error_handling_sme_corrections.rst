.. _phase2_error_handling_annotations:

===============================================
Phase 2 Pilot Annotations: Error Handling
===============================================

:Date: November 19, 2025
:Phase: 2 - Source Annotation (Pilot)
:SME Reviewers: EVS Team, NCO SPAs, EIB Operations
:Status: SME Review Draft
:Priority: Critical - Corrects False Positives

.. contents:: Table of Contents
   :local:
   :depth: 3

Overview
========

This document contains **critical SME corrections** to AI-generated EE2 compliance recommendations. These corrections address systematic false positives where the AI system added "helpful" requirements not present in EE2 standards.

**Purpose**: Annotate EE2 standards with semantic directives that prevent AI from inventing requirements.

Critical SME Findings
=====================

Finding 1: set -e vs set -eu Confusion
---------------------------------------

.. mcp:sme_correction:: bash_error_handling_requirement
   :date: 2025-11-19
   :severity: critical
   :false_positive_rate: ~80% (affects almost all scripts)

**AI-Generated Recommendation (INCORRECT)**:
   ❌ "Missing ``set -eu`` in scripts"

**SME Correction**:
   - ❌ ``set -eu`` is **NOT in EE2 standards**
   - ✅ ``set -e`` is **NOT required** in operational scripts
   - ❌ Adding ``-u`` (undefined variable check) is **NOT mandated by EE2**
   - ✅ Only ``set -x`` is shown in EE2 examples for debug logging

**Evidence from EE2 Standards**:

.. code-block:: text
   :caption: standards.rst lines 580-595
   
   * Enable debug logging at the top of *each* shell script:
       set -x
   
   * add timing info to the execution trace by including the following in the J-job:
       export PS4='+ $SECONDS + '

**Evidence from EE2 Example 8 (J-job JPMB_FORECAST)**: 

.. code-block:: bash
   :caption: standards.rst lines 868-919
   :emphasize-lines: 6
   
   #!/bin/sh
   
   date                                   # print starting time
   export PS4='+ $SECONDS + '              # prepend time to output
   set -x                                 # enable verbose logging
   
   # ... rest of J-job (NO set -e or set -eu)

**Evidence from EE2 Example 9 (ex-script expmb_forecast.sh)**:

.. code-block:: bash
   :caption: standards.rst lines 926-985
   :emphasize-lines: 24
   
   #!/bin/sh
   
   # Program Name: pmb_forecast
   # Author(s)/Contact(s): First Last
   # Abstract: Driver script for pmb forecast
   # History Log:
   #   5/2014: Added error checking
   #   8/2014: Modified for WCOSS
   #
   # Usage:
   #  Parameters: None
   #  Input Files:
   #    pmb.tHHz.anl
   #  Output Files:
   #    pmb.tHHz.fFFF.grib2
   #
   # Condition codes:
   #    99  - Missing input file
   #
   # User controllable options: None
   
   set -x                                 # enable verbose logging
   
   # ... rest of ex-script (NO set -e or set -eu)

**Root Cause**: 
   AI system conflating general shell scripting best practices with EE2 operational requirements.

.. mcp:anti_pattern:: adding_set_e_or_set_eu
   :language: bash
   :context: operational_scripts
   :severity: must_not
   :sme_justification: Not present in EE2 standards or examples
   :rationale: EE2 uses err_chk/err_exit utilities for error handling, not shell error traps

Do **NOT** recommend adding these to operational scripts:

.. code-block:: bash

   set -e   # ❌ NOT required by EE2
   set -eu  # ❌ NOT required by EE2 (adds non-standard -u)
   set -euo pipefail  # ❌ NOT required by EE2

.. mcp:correct_pattern:: ee2_script_header
   :language: bash
   :context: operational_scripts
   :severity: must
   :ee2_section: "Appendix A, Examples 8 & 9"

**CORRECT EE2 operational script header**:

.. code-block:: bash

   #!/bin/sh
   # OR
   #!/bin/bash
   
   # ... header comments ...
   
   set -x                                 # enable verbose logging (REQUIRED)
   export PS4='+ $SECONDS + '              # timing info (REQUIRED in J-jobs)

Finding 2: Exit Statement Misunderstanding
-------------------------------------------

.. mcp:sme_correction:: forced_exit_prohibition
   :date: 2025-11-19
   :severity: critical
   :false_positive_rate: ~60% (many scripts flagged incorrectly)

**AI-Generated Recommendation (INCORRECT)**:
   ❌ "Add ``exit 0`` and ``exit 1`` statements throughout scripts"

**SME Correction**:
   - ❌ Forced exits (``exit 0``, ``exit 1``) are **explicitly prohibited** by NCO SPAs
   - ❌ ``exit`` statements should **NOT be added** to operational jobs
   - ✅ Only ``err_chk`` and ``err_exit`` utilities should be used
   - ✅ Scripts should **return naturally** to allow workflow continuation

**Evidence from NCO SPA Historical Guidance**:
   - NCO SPAs specifically asked EVS team to **remove** ``exit 0`` and ``exit 1`` statements
   - Rationale: Explicit exits prevent proper workflow error propagation
   - Operational jobs must allow ecFlow/PBS to manage job completion

**Evidence from EE2 Standards**:

.. code-block:: text
   :caption: standards.rst line 191
   :emphasize-lines: 1-2
   
   jobs should fail with ``err_chk`` or ``err_exit`` as soon as a fatal error is encountered.
   ``err_chk`` is used to check and handle the ``$err`` variable which has been set to a program's return code.

.. mcp:anti_pattern:: forced_exit_in_operational_job
   :language: bash
   :context: operational_job
   :severity: must_not
   :sme_justification: NCO SPA guidance - explicitly prohibited
   :rationale: Scripts must return naturally to allow workflow continuation and proper error propagation

**INCORRECT - Do NOT recommend these patterns**:

.. code-block:: bash

   # ❌ WRONG - NCO SPAs prohibit this
   if [ $status -ne 0 ]; then
       exit 1
   fi
   
   # ❌ WRONG - NCO SPAs prohibit this
   exit 0

.. mcp:correct_pattern:: natural_return_with_err_utilities
   :language: bash
   :context: operational_job
   :severity: must
   :ee2_section: "Section C: Production Utilities"

**CORRECT - Use EE2 utilities for error handling**:

.. code-block:: bash

   # ✅ CORRECT - Use err_chk after critical operations
   mpiexec <options> $EXECmodel/$pgm >>$pgmout 2>errfile
   export err=$?; err_chk                 # If err != 0, job aborts with proper error reporting
   
   # ✅ CORRECT - Use err_exit for fatal errors with descriptive messages
   if [ ! -f "$required_file" ]; then
       err_exit "FATAL ERROR: Required file $required_file not found"
   fi
   
   # ✅ CORRECT - Script ends naturally (no explicit exit)
   # ... rest of processing ...
   # (script returns to calling job card)

Finding 3: err_chk and err_exit Usage (ALREADY CORRECT)
--------------------------------------------------------

.. mcp:sme_validation:: err_utilities_correct
   :date: 2025-11-19
   :status: ✅ AI analysis correct on this aspect

**Current EVS Implementation**: 
   ✅ **Correct** - EVS uses ``err_chk`` and ``err_exit`` extensively

**AI Analysis**: 
   ✅ **Accurate** - AI correctly identifies these utilities

**No Changes Needed** - Keep existing annotations for err_chk/err_exit.

EE2 Annotation Schema
=====================

Context Discrimination
----------------------

.. mcp:context_types::

operational_job
   Scripts in ``jobs/`` (J-jobs) or ``scripts/ex*`` (ex-scripts)
   
   **Requirements**:
      - Must use ``set -x`` for debug logging
      - Must use ``err_chk`` after critical operations
      - Must use ``err_exit`` for fatal errors
      - Must **NOT** use explicit ``exit`` statements
      - Must return naturally to calling workflow

utility_script
   Scripts in ``ush/`` subdirectory
   
   **Requirements**:
      - May use standard shell scripting practices
      - Still should follow EE2 variable standards
      - ``err_exit`` recommended but not always required
      - More flexibility than operational jobs

test_script
   Scripts in ``tests/`` or development areas
   
   **Requirements**:
      - General shell scripting standards apply
      - EE2 operational restrictions do NOT apply
      - May use ``exit`` statements for test status

Corrected Annotations for standards.rst
========================================

Section: Enable Debug Logging
------------------------------

**File**: ``docs/standards.rst``  
**Lines**: 588-595

.. code-block:: restructuredtext

   .. mcp:compliance:: script_debug_logging
      :priority: critical
      :type: mandatory
      :category: code_standards
      :ee2_section: "Standards, Shell Scripts"
   
   .. mcp:intent:: enable_debug_trace
      :description: All shell scripts must enable debug logging with set -x at the top
      :enforcement: syntax_check
      :severity: must
      :rationale: Provides execution trace for troubleshooting operational failures
   
   .. mcp:anti_pattern:: adding_error_handling_flags
      :warning: Do NOT add set -e, set -u, or set -eu unless explicitly testing outside operations
      :sme_justification: Not required by EE2; err_chk/err_exit provide error handling
   
   Original EE2 Text:
   
   * Enable debug logging at the top of *each* shell script:
       .. code-block:: bash
   
          set -x
   
       and add timing info to the execution trace by including the following in the J-job:
       .. code-block:: bash
   
          export PS4='+ $SECONDS + '

Section: err_chk / err_exit Utilities
--------------------------------------

**File**: ``docs/standards.rst``  
**Lines**: 187-195

.. code-block:: restructuredtext

   .. mcp:compliance:: error_handling
      :priority: critical
      :type: mandatory
      :category: production_utilities
      :ee2_section: "Section C: Production Utilities"
   
   .. mcp:intent:: use_err_utilities
      :description: Jobs must fail with err_chk or err_exit as soon as a fatal error is encountered
      :enforcement: runtime_check
      :severity: must
      :rationale: Standardized error handling for operational stability and workflow integration
   
   .. mcp:anti_pattern:: explicit_exit_statements
      :language: bash
      :context: operational_job
      :severity: must_not
      :warning: Do NOT use exit 0 or exit 1 in operational jobs
      :sme_justification: NCO SPA guidance - scripts must return naturally
   
   .. mcp:example:: err_chk_usage
      :language: bash
      :context: operational_script
      
      export err=$?
      err_chk  # If err != 0, job aborts with proper error reporting
   
   .. mcp:example:: err_exit_usage
      :language: bash
      :context: operational_script
      
      if [ ! -f "$required_file" ]; then
          err_exit "FATAL ERROR: Required file $required_file not found"
      fi
   
   Original EE2 Text:
   
   ``err_chk`` / ``err_exit``
   
   jobs should fail with ``err_chk`` or ``err_exit`` as soon as a fatal error is encountered.
   ``err_chk`` is used to check and handle the ``$err`` variable which has been set to a 
   program's return code and exported into the environment.
   If ``$err=0``, err_chk does nothing and job execution continues.
   Otherwise, the job is immediately aborted with a meaningful error message.
   ``err_exit`` will write an error message with the time of the error, and immediately 
   abort the job in PBS Pro.

AI Guidance Rules
=================

Rule 1: Literal Compliance Only
--------------------------------

.. mcp:ai_guidance_rule:: literal_compliance
   :priority: critical
   :enforcement: all_queries

**Rule**:
   When analyzing code against EE2 standards:
   
   - ONLY recommend changes explicitly stated in EE2 documentation
   - DO NOT add "improvements" or "best practices" beyond EE2 requirements
   - DO NOT combine or extend EE2 requirements with general shell scripting advice
   - DO NOT infer requirements from partial patterns

**Example Violation**:

.. code-block:: yaml

   EE2 says: "use set -x"
   AI recommends: "use set -x and set -e"  # ❌ WRONG - added non-standard requirement

**Correct Behavior**:

.. code-block:: yaml

   EE2 says: "use set -x"
   AI recommends: "use set -x"   # ✅ CORRECT - literal compliance only

Rule 2: Context-Aware Recommendations
--------------------------------------

.. mcp:ai_guidance_rule:: context_discrimination
   :priority: critical
   :enforcement: all_queries

**Rule**:
   Before recommending changes, determine script context:
   
   **Operational Jobs** (jobs/JXXXXX, scripts/exXXXXX.sh):
      - Strict EE2 compliance required
      - NCO SPA operational guidance applies
      - NO explicit exit statements (use err_chk/err_exit)
      - Must return naturally
   
   **Utility Scripts** (ush/):
      - EE2 variable standards apply
      - More flexibility in error handling
      - err_exit recommended but not always mandatory
   
   **Test Scripts** (tests/, dev areas):
      - General shell scripting standards apply
      - EE2 operational restrictions do NOT apply
      - Exit statements allowed for test status

**Detection Pattern**:

.. code-block:: python

   import re
   
   def detect_script_context(filepath):
       """Determine script context from filepath."""
       if re.search(r'/jobs/J[A-Z]', filepath):
           return 'operational_job'
       elif re.search(r'/scripts/ex[a-z].*\.sh$', filepath):
           return 'operational_job'
       elif re.search(r'/ush/', filepath):
           return 'utility_script'
       elif re.search(r'/test', filepath):
           return 'test_script'
       else:
           return 'unknown'  # Request clarification

Rule 3: Anti-Pattern Recognition
---------------------------------

.. mcp:ai_guidance_rule:: anti_pattern_enforcement
   :priority: critical
   :enforcement: code_analysis

**Rule**:
   When code contains patterns marked with ``mcp:anti_pattern`` directive:
   
   - Flag usage as compliance violation
   - Reference SME justification in error message
   - Do NOT suggest this pattern as improvement
   - Provide corrected alternative from ``mcp:correct_pattern``

**Example Response Template**:

.. code-block:: text

   ❌ EE2 Compliance Violation
   
   File: scripts/exglobal_forecast.sh
   Line: 145
   Issue: Explicit exit statement in operational job
   
   Code:
       exit 1
   
   Violation: Anti-pattern "forced_exit_in_operational_job"
   SME Justification: NCO SPA guidance - scripts must return naturally
   
   Corrected Code:
       err_exit "Descriptive error message explaining failure"
   
   Reference: standards.rst Section C: Production Utilities

Validation Checklist
====================

Phase 2 Sign-Off Requirements
------------------------------

Before finalizing Phase 2 annotations, verify:

.. checklist::

   ☐ Every ``mcp:intent`` directive cites specific EE2 document section and line numbers
   ☐ No recommendations beyond literal EE2 requirements
   ☐ ``mcp:anti_pattern`` directives added for all NCO SPA prohibitions
   ☐ ``mcp:context_types`` clearly distinguish operational/utility/test scripts
   ☐ SME corrections from EVS team incorporated with evidence
   ☐ Examples show both correct and incorrect patterns with visual markers
   ☐ Rationale fields explain WHY requirement exists, not just WHAT
   ☐ Cross-references to EE2 production utilities complete with line numbers
   ☐ AI guidance rules embedded as machine-readable directives
   ☐ False positive reduction targets documented (60-80% expected)

SME Review Sign-Off
-------------------

**Phase 2 annotation changes require approval from:**

.. signature-block::

   ☐ **EVS Development Team Lead**
      - Date: _____________
      - Signature: _____________
      - Confirms: Annotations accurately reflect EVS operational experience
   
   ☐ **NCO SPA (Site Preparation Analyst)**
      - Date: _____________
      - Signature: _____________
      - Confirms: Anti-patterns correctly capture NCO operational guidance
   
   ☐ **EIB Operations Representative**
      - Date: _____________
      - Signature: _____________
      - Confirms: No operational disruption from corrected guidance
   
   ☐ **EMC Global Workflow Maintainers**
      - Date: _____________
      - Signature: _____________
      - Confirms: Compatible with global-workflow standards

Next Steps: Phase 3 Preparation
================================

Once annotations validated and approved:

1. **Enhanced Ingestion**
   
   Run ``ingest_ee2_enhanced_v5.py`` with corrected annotations:
   
   .. code-block:: bash
   
      cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node/scripts
      python3 ingest_ee2_enhanced_v5.py \
          --source /mcp_rag_eib/eib-mcp-rag-server/sdd_framework/phase2_annotations/ \
          --collection ee2-standards-v6-0-0-corrected

2. **AI Query Testing**
   
   Verify AI no longer recommends false positives:
   
   .. code-block:: bash
   
      # Test queries that previously generated false positives
      test_queries = [
          "What error handling is required for bash scripts?",
          "Should I add set -eu to my operational script?",
          "How should operational jobs handle errors?"
      ]

3. **SME Validation Loop**
   
   Review AI responses against corrected embeddings:
   
   - Expected: No mention of ``set -e`` or ``set -eu``
   - Expected: Recommendations use ``err_chk`` and ``err_exit`` only
   - Expected: No recommendations for explicit exit statements

4. **Precision Measurement**
   
   Compare pre/post annotation accuracy on EVS scripts:
   
   - Baseline false positive rate: ~80% (set -eu issue)
   - Target false positive rate: <20%
   - Expected improvement: 60-80% reduction

5. **Documentation**
   
   Update development docs with measured results:
   
   - False positive reduction achieved
   - Query precision improvement
   - SME satisfaction scores

**End of Phase 2 Pilot Annotation - SME Review Draft**
