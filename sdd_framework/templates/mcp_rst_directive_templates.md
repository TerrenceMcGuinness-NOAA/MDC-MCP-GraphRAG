# MCP RST Directive Templates
**Semantic Annotation for EE2 Compliance**

## Custom Sphinx Directives for MCP

These directives add semantic metadata to RST source files without affecting the rendered documentation.

---

## 1. Compliance Category Directive

**Purpose:** Mark sections with compliance category and metadata

**Syntax:**
```rst
.. mcp:compliance:: <category_name>
   :priority: critical|high|medium|low
   :type: mandatory|recommended|optional
   :scope: global|system-specific|application-specific
```

**Example:**
```rst
.. mcp:compliance:: error_handling
   :priority: critical
   :type: mandatory
   :scope: global

Fatal errors must print a descriptive message beginning with "FATAL ERROR:".
Warnings or non-fatal error messages must be prefaced with "WARNING:".
```

**Categories:**
- `error_handling` - Error messages, error checking, recovery
- `environment_variables` - Standard variables, naming conventions
- `file_naming` - Directory structure, file extensions, naming patterns
- `workflow_structure` - Job card, J-job, ex-script patterns
- `production_utilities` - prep_step, err_check, err_exit, cpreq, etc.
- `code_standards` - Formatting, documentation, style
- `directory_structure` - Package layout, version files
- `restart_capability` - Cold start, checkpoints, recovery
- `dataflow` - COMOUT, COMIN, data handling
- `compilation` - Build scripts, makefiles, modules

---

## 2. Intent Directive

**Purpose:** Capture the intent/purpose of a requirement

**Syntax:**
```rst
.. mcp:intent:: <intent_name>
   :description: Brief description of the intent
   :enforcement: compile|runtime|manual|automated
   :rationale: Why this requirement exists
```

**Example:**
```rst
.. mcp:intent:: fatal_error_format
   :description: All fatal errors must begin with "FATAL ERROR:" prefix
   :enforcement: runtime_check
   :rationale: Enables rapid identification in logs for 99% on-time delivery

err_exit will write an error message with the time of the error, and immediately 
abort the job in PBS Pro. It accepts an error string as input to which it will 
prepend "FATAL ERROR."
```

---

## 3. Example Directive

**Purpose:** Mark code examples with context and metadata

**Syntax:**
```rst
.. mcp:example:: <example_id>
   :language: bash|python|fortran|c
   :context: <usage_context>
   :demonstrates: <what_it_shows>

   .. code-block:: <language>
   
      <code here>
```

**Example:**
```rst
.. mcp:example:: err_check_basic
   :language: bash
   :context: production_utility
   :demonstrates: Error checking after command execution

   .. code-block:: bash
   
      command_that_may_fail
      export err=$?
      err_chk
```

---

## 4. Cross-Reference Directive

**Purpose:** Link related sections and concepts

**Syntax:**
```rst
.. mcp:see-also:: <section_name>
   :related: [concept1, concept2, ...]
   :type: prerequisite|reference|alternative|example
```

**Example:**
```rst
.. mcp:see-also:: production_utilities
   :related: [err_exit, cpreq, startmsg]
   :type: prerequisite

Before using err_chk, ensure the prod_util module is loaded.
```

---

## 5. Severity Directive

**Purpose:** Mark requirement enforcement level (RFC 2119 style)

**Syntax:**
```rst
.. mcp:severity:: must|must-not|should|should-not|may
   :rationale: Why this severity level
   :exceptions: Conditions where different rules apply
```

**Example:**
```rst
.. mcp:severity:: must
   :rationale: Critical for operational reliability
   :exceptions: Data assimilation jobs exempt from 15-minute restart requirement

Any job that runs longer than 15 minutes is required to have restart capability 
built in such that the process picks up where it left off when rerun.
```

---

## 6. Variable Definition Directive

**Purpose:** Mark environment variable definitions with metadata

**Syntax:**
```rst
.. mcp:envvar:: <VARIABLE_NAME>
   :set-by: job-card|j-job|ex-script|module
   :required: yes|no
   :scope: per-cycle|per-job|global
   :format: <format_description>
```

**Example:**
```rst
.. mcp:envvar:: PDY
   :set-by: j-job
   :required: yes
   :scope: per-cycle
   :format: YYYYMMDD

Date in YYYYMMDD format representing the current processing day.
```

---

## 7. Utility Function Directive

**Purpose:** Document production utility functions

**Syntax:**
```rst
.. mcp:utility:: <function_name>
   :module: <module_name>
   :category: error-handling|messaging|data-management
   :required: yes|no
   :deprecated: no|yes (version)
```

**Example:**
```rst
.. mcp:utility:: err_chk
   :module: prod_util
   :category: error-handling
   :required: yes
   :deprecated: no

Checks the $err variable and aborts job if non-zero. Must be called 
immediately after any operation that could fail.
```

---

## 8. Pattern Directive

**Purpose:** Mark common patterns and idioms

**Syntax:**
```rst
.. mcp:pattern:: <pattern_name>
   :category: <pattern_category>
   :anti-pattern: no|yes
   :alternatives: [alt1, alt2, ...]
```

**Example:**
```rst
.. mcp:pattern:: error_check_pattern
   :category: error-handling
   :anti-pattern: no
   :alternatives: []

Standard error checking pattern:

.. code-block:: bash

   command_that_may_fail
   export err=$?
   err_chk
```

---

## Directive Configuration for Sphinx

Add to `conf.py`:

```python
# Custom MCP directives for semantic annotation
def setup(app):
    # Register custom directives
    app.add_directive('mcp:compliance', MCPComplianceDirective)
    app.add_directive('mcp:intent', MCPIntentDirective)
    app.add_directive('mcp:example', MCPExampleDirective)
    app.add_directive('mcp:see-also', MCPSeeAlsoDirective)
    app.add_directive('mcp:severity', MCPSeverityDirective)
    app.add_directive('mcp:envvar', MCPEnvVarDirective)
    app.add_directive('mcp:utility', MCPUtilityDirective)
    app.add_directive('mcp:pattern', MCPPatternDirective)
    
    # These directives are invisible in rendered output
    # Metadata extracted during ingestion pipeline
    return {'version': '1.0', 'parallel_read_safe': True}
```

---

## Usage Guidelines

### 1. Placement
- Place directives **before** the content they annotate
- Keep directives close to relevant text
- One primary `mcp:compliance` per major section
- Multiple supporting directives per section

### 2. Granularity
- **Coarse**: Annotate major sections (e.g., entire "Error Handling" section)
- **Fine**: Annotate specific requirements within sections
- Balance: Enough detail for precise analysis, not overwhelming

### 3. Consistency
- Use consistent category names across documents
- Follow severity level conventions (MUST/SHOULD/MAY)
- Maintain intent naming conventions

### 4. Testing
- Verify directives don't break doc builds
- Confirm invisibility in rendered output
- Test metadata extraction in ingestion pipeline

---

## Annotation Workflow

1. **Read section** to understand compliance requirements
2. **Add compliance directive** with category and priority
3. **Add intent directive** if requirement has specific purpose
4. **Mark examples** with example directive
5. **Link related** sections with see-also directive
6. **Set severity** for enforcement level
7. **Test build** to ensure no rendering issues
8. **Extract metadata** through ingestion pipeline

---

## Example: Fully Annotated Section

```rst
.. _error_handling:

.. mcp:compliance:: error_handling
   :priority: critical
   :type: mandatory
   :scope: global

.. mcp:intent:: descriptive_error_messages
   :description: Enable rapid troubleshooting through clear error context
   :enforcement: runtime_check
   :rationale: 99% on-time delivery rate requires fast failure diagnosis

Descriptive error messages
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. mcp:severity:: must
   :rationale: Critical for operational stability
   :exceptions: None

Fatal errors must print a descriptive message beginning with "FATAL ERROR:".
Warnings or non-fatal error messages must be prefaced with "WARNING:".

.. mcp:example:: fatal_error_usage
   :language: bash
   :context: error-handling
   :demonstrates: Proper fatal error format

   .. code-block:: bash
   
      if [ ! -f "$required_file" ]; then
          echo "FATAL ERROR: Required file not found: $required_file"
          exit 1
      fi

.. mcp:see-also:: production_utilities
   :related: [err_exit, err_chk]
   :type: reference

As with executable code, error messages in scripts must be written so that if 
an issue arises, the context of that error or failure is communicated as early 
and as clearly as possible.
```

---

## Next Steps

1. ✅ Directive templates created
2. ⏳ Add directive implementations to Sphinx conf.py
3. ⏳ Annotate pilot section (Error Handling)
4. ⏳ Test doc build with annotations
5. ⏳ Build ingestion parser for mcp:* directives
