# Error Handling Section - Pilot Annotation
**Demonstrating semantic tagging for EE2 compliance**

This is an annotated version of the Error Handling section from `standards.rst` showing how MCP directives add semantic metadata without affecting the rendered documentation.

---

## Original Section with MCP Annotations

```rst
.. _error_handling:

.. mcp:compliance:: error_handling
   :priority: critical
   :type: mandatory
   :scope: global

.. mcp:intent:: rapid_error_detection
   :description: Enable immediate error detection and recovery for 99% on-time delivery
   :enforcement: runtime_check
   :rationale: Operational reliability requires catching failures at earliest point

C. Production Utilities
-----------------------

The utilities listed below must be used to assist in accomplishing certain tasks for all WCOSS models.
They are accessible through the ``prod_util`` module.
This module will put the below utility scripts in your environment's ``PATH`` and define other useful environment variables.
The module is automatically loaded in all production jobs and should be loaded in development job cards.
See `Appendix A: Workflow Examples`_ for examples of these utilities in use.

.. mcp:utility:: prep_step
   :module: prod_util
   :category: initialization
   :required: yes
   :deprecated: no

``prep_step``
  ``prep_step`` unsets the ``FORT##`` variables used to pass unit assignments to Intel Fortran executables.
  Since there may be multiple Fortran programs running in a job, these variables must be reset before each program execution.

.. mcp:utility:: startmsg
   :module: prod_util
   :category: messaging
   :required: no
   :deprecated: partial

``startmsg`` *
  ``startmsg`` posts the start time of a program to ``stdout``.

.. mcp:utility:: postmsg
   :module: prod_util
   :category: messaging
   :required: no
   :deprecated: partial

``postmsg`` *
  ``postmsg`` writes a message to a log file.
  The first argument is the log file name and the second is the message.
  The log file will default to stdout.

*startmsg and postmsg are no longer required in operations but the utilities will continue to be maintained.

.. mcp:compliance:: error_handling
   :priority: critical
   :type: mandatory
   :scope: global

.. mcp:intent:: descriptive_error_messages
   :description: Fatal errors must use FATAL ERROR prefix, warnings use WARNING prefix
   :enforcement: runtime_check
   :rationale: Rapid log analysis requires standardized error message format

.. mcp:severity:: must
   :rationale: Critical for operational stability and rapid troubleshooting
   :exceptions: None

``err_chk`` / ``err_exit``
  It is imperative that all production code and scripts broadly employ error checking to catch and recover from errors as quickly as possible.
  The context of the error must be communicated as descriptively as possible and prefaced with "WARNING:" or "FATAL ERROR:".
  
.. mcp:pattern:: fail_fast_pattern
   :category: error-handling
   :anti-pattern: no
   :alternatives: []

  Failures must not be allowed to propagate downstream of the point where the problem can first be detected;
  jobs should fail with ``err_chk`` or ``err_exit`` as soon as a fatal error is encountered.
  
.. mcp:utility:: err_chk
   :module: prod_util
   :category: error-handling
   :required: yes
   :deprecated: no

  ``err_chk`` is used to check and handle the ``$err`` variable which has been set to a program's return code and exported into the environment.
  If ``$err=0``, err_chk does nothing and job execution continues.
  If ``$err`` is non-zero, the job is aborted.
  
.. mcp:example:: err_chk_usage
   :language: bash
   :context: error_checking_after_command
   :demonstrates: Standard error checking pattern with err_chk

   .. code-block:: bash
   
      # Execute potentially failing command
      some_critical_command arg1 arg2
      export err=$?
      err_chk

.. mcp:utility:: err_exit
   :module: prod_util
   :category: error-handling
   :required: yes
   :deprecated: no

  ``err_exit`` will write an error message with the time of the error, and immediately abort the job in PBS Pro.
  It accepts an error string as input to which it will prepend "FATAL ERROR."

.. mcp:example:: err_exit_usage
   :language: bash
   :context: immediate_fatal_error
   :demonstrates: Aborting job with descriptive error message

   .. code-block:: bash
   
      if [ ! -f "$required_input_file" ]; then
          err_exit "Required input file not found: $required_input_file"
      fi

.. mcp:see-also:: file_operations
   :related: [cpreq, cpfs]
   :type: reference

.. mcp:compliance:: data_integrity
   :priority: high
   :type: mandatory
   :scope: global

.. mcp:utility:: cpreq
   :module: prod_util
   :category: data-management
   :required: yes
   :deprecated: no

``cpreq``
  ``cpreq`` is used to copy files that are essential to an application.
  If the copy is unsuccessful for any reason, then a FATAL ERROR will be printed and the job will abort immediately.
  It has the same usage as the standard ``cp`` command.

.. mcp:severity:: must
   :rationale: Essential files must be verified on copy to prevent silent data corruption
   :exceptions: None

.. mcp:example:: cpreq_usage
   :language: bash
   :context: copying_essential_files
   :demonstrates: Safe copy operation with automatic error checking

   .. code-block:: bash
   
      # Copy essential input file - job aborts if copy fails
      cpreq $COMIN/gfs.t${cyc}z.pgrb2.0p25.f000 $DATA/

.. mcp:utility:: cpfs
   :module: prod_util
   :category: data-management
   :required: yes
   :deprecated: no

.. mcp:intent:: atomic_file_operations
   :description: Ensure files are completely written before becoming accessible
   :enforcement: automated
   :rationale: Prevent downstream jobs from reading partial/incomplete files

``cpfs``
  ``cpfs`` is used to copy files while ensuring that the whole file has been copied before it becomes accessible so that downstream applications will not attempt to copy or read a partial file.
  It has the same usage as the standard ``cp`` command with the limitation that it may only copy one file at a time (no globbing).
  It is most useful for copies across file systems or for very large files.
  ``cpfs $COMIN/$file $new_file`` will execute the following:

.. mcp:example:: cpfs_implementation
   :language: bash
   :context: atomic_copy_pattern
   :demonstrates: Internal implementation of atomic file copy

   .. code-block:: bash

      cpreq $COMIN/$file $new_file.cptmp
      $FSYNC $new_file.cptmp
      mv $new_file.cptmp $new_file

.. mcp:pattern:: check_before_cpfs
   :category: error-handling
   :anti-pattern: no
   :alternatives: []

.. mcp:severity:: should
   :rationale: Prevents unnecessary fatal errors when optional files missing
   :exceptions: When file is truly required, use err_exit directly

  ``cpfs`` calls the ``err_exit`` utility if either the cp or mv step returns non-zero status.
  However, as a further check, verify that a source file exists before calling ``cpfs``.
  If the job should continue without the file, skip the ``cpfs`` call and continue.
  If the job should fail if the source file does not exist, call err_exit directly.

.. mcp:example:: cpfs_with_validation
   :language: bash
   :context: optional_file_copy
   :demonstrates: Pre-checking file existence before cpfs

   .. code-block:: bash
   
      # For optional files - check before copying
      if [ -f "$COMIN/optional_file.dat" ]; then
          cpfs $COMIN/optional_file.dat $DATA/
      fi
      
      # For required files - fail explicitly
      if [ ! -f "$COMIN/required_file.dat" ]; then
          err_exit "Required file missing: $COMIN/required_file.dat"
      fi
      cpfs $COMIN/required_file.dat $DATA/

.. mcp:compliance:: messaging
   :priority: medium
   :type: recommended
   :scope: global

.. mcp:intent:: operational_notification
   :description: Notify production staff of non-fatal issues requiring attention
   :enforcement: manual
   :rationale: Quality issues with backup data must be escalated even if job succeeds

.. mcp:utility:: mail.py
   :module: prod_util
   :category: messaging
   :required: no
   :deprecated: no

  When nonfatal errors occur that may impact the quality of the model output, such as when backup data is used, it is important to notify the appropriate parties so that the error can be addressed.
  The ``mail.py`` utility is used to send an e-mail notification from any node on the system.
  To notify production staff of a nonfatal but significant issue with a production job, one might execute:

.. mcp:example:: mail_py_warning
   :language: bash
   :context: quality_degradation_notification
   :demonstrates: Notifying staff of non-fatal quality issues

   .. code-block:: bash

      msg="WARNING: Primary data source unavailable. Backup data is being used."
      echo "$msg" | mail.py

.. mcp:example:: mail_py_with_cc
   :language: bash
   :context: email_with_copy
   :demonstrates: Sending notification with carbon copy

   .. code-block:: bash

      echo "$msg" | mail.py –c <someones_email_address>

.. mcp:envvar:: MAILTO
   :set-by: j-job
   :required: no
   :scope: per-job
   :format: comma-separated_email_list

  An addressee list can be included on the command line or set in advance via environment variable ``$MAILTO``.
  To copy someone, use the "-c" flag:

  Run ``mail.py -h`` after loading the ``prod_util`` module to see additional options.
  Note that e-mail is only sent in jobs run by NCO.
  Jobs run by others will merely print the message to stdout.

.. mcp:utility:: getsystem
   :module: prod_util
   :category: system-info
   :required: no
   :deprecated: no

.. mcp:severity:: must-not
   :rationale: System-specific logic must use standard environment variables
   :exceptions: Command-line debugging only

``getsystem``
  ``getsystem`` simply tells you which WCOSS system you are on.
  This utility exists for command line execution and must not be used in any operational packages.
  Table 2 shows what you can expect to receive when running this utility on a given system with a given set of option flags:

**Table 2: getsystem output**

.. csv-table::
   :header-rows: 1
   :stub-columns: 0
   :widths: auto

   "System","no flags","–p"
   "Dogwood phase 1","Dogwood","Dogwood-p1"
   "Cactus phase 1","Cactus","Cactus-p1"

.. mcp:see-also:: environment_variables
   :related: [MACHINE, wcoss_cray_ver]
   :type: alternative
```

---

## Semantic Metadata Extracted

When this annotated RST is processed by the ingestion pipeline, the following structured metadata is extracted:

### Compliance Categories Identified
```json
{
  "error_handling": {
    "priority": "critical",
    "type": "mandatory",
    "scope": "global",
    "utilities": ["err_chk", "err_exit", "prep_step"],
    "intents": ["rapid_error_detection", "descriptive_error_messages"],
    "patterns": ["fail_fast_pattern", "check_before_cpfs"],
    "examples": ["err_chk_usage", "err_exit_usage"]
  },
  "data_integrity": {
    "priority": "high",
    "type": "mandatory",
    "scope": "global",
    "utilities": ["cpreq", "cpfs"],
    "intents": ["atomic_file_operations"],
    "patterns": ["check_before_cpfs"],
    "examples": ["cpreq_usage", "cpfs_implementation", "cpfs_with_validation"]
  },
  "messaging": {
    "priority": "medium",
    "type": "recommended",
    "scope": "global",
    "utilities": ["mail.py"],
    "intents": ["operational_notification"],
    "examples": ["mail_py_warning", "mail_py_with_cc"]
  }
}
```

### Intent Graph
```
rapid_error_detection
  ├── requires: prod_util module
  ├── utilities: [err_chk, err_exit, prep_step]
  ├── enforcement: runtime_check
  └── rationale: 99% on-time delivery requires immediate failure detection

descriptive_error_messages
  ├── format: "FATAL ERROR:" prefix for fatal, "WARNING:" for non-fatal
  ├── utilities: [err_exit]
  ├── enforcement: runtime_check
  └── rationale: Rapid log analysis for operational troubleshooting

atomic_file_operations
  ├── prevents: downstream jobs reading partial files
  ├── utilities: [cpfs]
  ├── enforcement: automated
  └── pattern: copy to .cptmp, fsync, move to final name

operational_notification
  ├── use_case: non-fatal issues requiring attention
  ├── utilities: [mail.py]
  ├── enforcement: manual
  └── rationale: Quality degradation must be escalated
```

### Utility Relationship Map
```
prod_util module
  ├── error_handling (critical)
  │   ├── prep_step (initialization)
  │   ├── err_chk (checks $err, aborts if non-zero)
  │   └── err_exit (immediate abort with FATAL ERROR message)
  ├── data_management (high)
  │   ├── cpreq (copy essential files, abort on failure)
  │   └── cpfs (atomic copy with fsync)
  ├── messaging (medium)
  │   ├── mail.py (notify staff of non-fatal issues)
  │   ├── startmsg (deprecated-partial)
  │   └── postmsg (deprecated-partial)
  └── system_info (low)
      └── getsystem (must-not use in production)
```

### Code Pattern Database
```yaml
patterns:
  - id: err_chk_usage
    category: error-handling
    language: bash
    demonstrates: "Standard error checking after command execution"
    code: |
      some_critical_command arg1 arg2
      export err=$?
      err_chk
    
  - id: err_exit_usage
    category: error-handling
    language: bash
    demonstrates: "Immediate fatal error with descriptive message"
    code: |
      if [ ! -f "$required_input_file" ]; then
          err_exit "Required input file not found: $required_input_file"
      fi
    
  - id: cpfs_with_validation
    category: data-integrity
    language: bash
    demonstrates: "Pre-check file existence before atomic copy"
    code: |
      # Optional file
      if [ -f "$COMIN/optional_file.dat" ]; then
          cpfs $COMIN/optional_file.dat $DATA/
      fi
      
      # Required file
      if [ ! -f "$COMIN/required_file.dat" ]; then
          err_exit "Required file missing: $COMIN/required_file.dat"
      fi
      cpfs $COMIN/required_file.dat $DATA/
```

### Severity Enforcement Rules
```yaml
must:
  - "Fatal errors prefaced with 'FATAL ERROR:'"
  - "Warnings prefaced with 'WARNING:'"
  - "Essential file copies use cpreq"
  - "Failures detected at earliest possible point"

should:
  - "Verify file exists before cpfs if job can continue without it"
  - "Use cpfs for large files or cross-filesystem copies"

must-not:
  - "getsystem must not appear in operational packages"
  - "Failures must not propagate downstream"
```

---

## What SMEs Can Now Do

### 1. **Validate Intent Capture**
SMEs can review whether the `mcp:intent` directives accurately capture *why* each requirement exists:
```rst
.. mcp:intent:: rapid_error_detection
   :description: Enable immediate error detection and recovery for 99% on-time delivery
   :enforcement: runtime_check
   :rationale: Operational reliability requires catching failures at earliest point
```

**SME Question:** "Does this capture the real reason we require err_chk?"

### 2. **Refine Priority Levels**
```rst
.. mcp:compliance:: error_handling
   :priority: critical
   :type: mandatory
   :scope: global
```

**SME Question:** "Is error_handling truly 'critical' or should it be 'high'?"

### 3. **Add Missing Context**
SMEs can spot gaps like:
- "We should tag err_chk with the $err variable pattern"
- "The intent should mention PBS Pro abort behavior"
- "Add example showing err_chk in a loop"

### 4. **Improve Code Examples**
```rst
.. mcp:example:: err_chk_usage
   :demonstrates: Standard error checking pattern with err_chk
```

**SME Suggestion:** "Add a loop example and a pipeline example"

### 5. **Build Relationship Graph**
SMEs can validate the utility relationships:
```
prep_step → resets FORT## → must precede Fortran execution
err_chk → checks $err → must follow command execution
cpfs → atomic copy → prevents partial file reads downstream
```

### 6. **Intent-Aware Queries**
Once embeddings are enhanced, SMEs can ask:
- **"How do I handle optional input files?"** → cpfs_with_validation pattern
- **"What's the fail-fast philosophy?"** → fail_fast_pattern + err_exit
- **"When should I notify NCO vs abort?"** → Compare mail.py vs err_exit intents

---

## Benefits Over Web Crawling

| Aspect | Web Crawling | Source Annotation |
|--------|--------------|-------------------|
| **Intent Capture** | None - pattern matching only | Explicit intent directives |
| **Context** | Stripped during HTML→text | Preserved in semantic tags |
| **Relationships** | Must infer from text | Explicit see-also links |
| **Examples** | Mixed with prose | Tagged and categorizable |
| **Refinement** | Re-crawl entire site | Edit source, re-ingest |
| **SME Control** | None - what's on web is final | SMEs annotate as they write |
| **Version Control** | Snapshot dates | Git history of annotations |

---

## Next Steps

1. ✅ Directive templates created
2. ✅ Pilot section annotated (Production Utilities / Error Handling)
3. ⏳ SME review of pilot annotations
4. ⏳ Implement Sphinx directive classes in conf.py
5. ⏳ Test doc build with annotations
6. ⏳ Expand to remaining sections:
   - Environment Variables (Table 1)
   - Date Utilities (finddate.sh, ndate, setpdy.sh)
   - File Naming Conventions
   - Workflow Structure (J-jobs, ex-scripts)
7. ⏳ Build enhanced ingestion pipeline with RST parser
8. ⏳ Implement intent-aware compliance tools

---

**Ready for SME Review:** This pilot shows exactly what the enhanced system will look like!
