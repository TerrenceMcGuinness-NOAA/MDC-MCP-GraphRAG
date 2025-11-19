# MCP RST Directive Reference for EE2 Enhanced Embeddings

**Purpose**: This document defines the MCP semantic annotation directives used in Phase 2 EE2 annotations. These directives are parsed during enhanced ingestion to create semantically rich embeddings in ChromaDB.

**Target Parser**: `ingest_ee2_enhanced_v5.py` (Week 3 enhanced ingestion)

---

## Directive Catalog

### Core MCP Directives (Phase 1 Schema)

#### mcp:compliance
Marks a section as containing compliance requirements.

```rst
.. mcp:compliance:: requirement_identifier
   :priority: critical|high|medium|low
   :type: mandatory|recommended|optional
   :category: error_handling|environment_variables|file_naming|workflow_structure|production_utilities|code_standards|directory_structure|restart_capability
   :ee2_section: "Document section reference"
```

**Example**:
```rst
.. mcp:compliance:: error_handling
   :priority: critical
   :type: mandatory
   :category: production_utilities
   :ee2_section: "Section C: Production Utilities"
```

---

#### mcp:intent
Describes the purpose and rationale of a requirement.

```rst
.. mcp:intent:: intent_identifier
   :description: Human-readable description of requirement
   :enforcement: syntax_check|runtime_check|code_review|automated_test
   :severity: must|must_not|should|should_not|may
   :rationale: Why this requirement exists
```

**Example**:
```rst
.. mcp:intent:: use_err_utilities
   :description: Jobs must fail with err_chk or err_exit as soon as fatal error is encountered
   :enforcement: runtime_check
   :severity: must
   :rationale: Standardized error handling for operational stability and workflow integration
```

---

#### mcp:example
Provides code examples (correct patterns).

```rst
.. mcp:example:: example_identifier
   :language: bash|python|perl|fortran|c
   :context: operational_script|utility_script|test_script|j_job|ex_script
   
   <code block>
```

**Example**:
```rst
.. mcp:example:: err_chk_usage
   :language: bash
   :context: operational_script
   
   export err=$?
   err_chk  # If err != 0, job aborts with proper error reporting
```

---

### Phase 2 Enhancement Directives

#### mcp:sme_correction
Documents systematic false positives identified by SMEs.

```rst
.. mcp:sme_correction:: correction_identifier
   :date: YYYY-MM-DD
   :severity: critical|high|medium|low
   :false_positive_rate: Percentage of scripts affected
```

**Purpose**: Track what AI was getting wrong and why.

**Example**:
```rst
.. mcp:sme_correction:: bash_error_handling_requirement
   :date: 2025-11-19
   :severity: critical
   :false_positive_rate: ~80%

AI recommended "set -eu" but EE2 only requires "set -x".
Evidence: standards.rst lines 588-595, Examples 8 & 9 show NO set -e usage.
```

---

#### mcp:anti_pattern
Explicitly marks prohibited patterns (what NOT to do).

```rst
.. mcp:anti_pattern:: pattern_identifier
   :language: bash|python|perl|etc
   :context: operational_job|utility_script|test_script|all_scripts
   :severity: must_not|should_not
   :warning: User-facing warning message
   :sme_justification: SME/organizational guidance reference
   :rationale: Technical reason for prohibition
```

**Purpose**: Prevent AI from recommending prohibited patterns.

**Example**:
```rst
.. mcp:anti_pattern:: forced_exit_in_operational_job
   :language: bash
   :context: operational_job
   :severity: must_not
   :warning: Do NOT use exit 0 or exit 1 in operational jobs
   :sme_justification: NCO SPA guidance - explicitly prohibited
   :rationale: Scripts must return naturally for proper workflow error propagation

# INCORRECT - Do NOT recommend this
if [ $status -ne 0 ]; then
    exit 1  # ❌ NCO SPAs prohibit this
fi
```

---

#### mcp:correct_pattern
Shows approved alternatives to anti-patterns.

```rst
.. mcp:correct_pattern:: pattern_identifier
   :language: bash|python|etc
   :context: operational_job|utility_script|test_script
   :severity: must|should|may
   :ee2_section: "Document reference"

<code block showing correct approach>
```

**Purpose**: Provide replacement for anti-patterns.

**Example**:
```rst
.. mcp:correct_pattern:: natural_return_with_err_utilities
   :language: bash
   :context: operational_job
   :severity: must
   :ee2_section: "Section C: Production Utilities"

# CORRECT - Use EE2 utilities
mpiexec $EXECmodel/$pgm >>$pgmout 2>errfile
export err=$?; err_chk

if [ ! -f "$required_file" ]; then
    err_exit "Required file not found"
fi

# Script ends naturally (no explicit exit)
```

---

#### mcp:context_types
Defines different script contexts with different requirements.

```rst
.. mcp:context_types::

context_name
   Description of context
   
   **Requirements**:
      - Requirement 1
      - Requirement 2
```

**Purpose**: Enable context-aware recommendations.

**Example**:
```rst
.. mcp:context_types::

operational_job
   Scripts in jobs/ (J-jobs) or scripts/ex* (ex-scripts)
   
   **Requirements**:
      - Must use set -x for debug logging
      - Must use err_chk after critical operations
      - Must NOT use explicit exit statements

utility_script
   Scripts in ush/ subdirectory
   
   **Requirements**:
      - EE2 variable standards apply
      - More flexibility than operational jobs
```

---

#### mcp:ai_guidance_rule
Machine-readable rules for AI query processing.

```rst
.. mcp:ai_guidance_rule:: rule_identifier
   :priority: critical|high|medium|low
   :enforcement: all_queries|code_analysis|documentation_search

**Rule**:
   Natural language rule description

**Example Violation** (optional):
   Example of incorrect behavior

**Correct Behavior**:
   Example of correct behavior
```

**Purpose**: Embed processing rules directly in documentation.

**Example**:
```rst
.. mcp:ai_guidance_rule:: literal_compliance
   :priority: critical
   :enforcement: all_queries

**Rule**:
   When analyzing code against EE2 standards:
   - ONLY recommend changes explicitly stated in EE2 documentation
   - DO NOT add "improvements" beyond EE2 requirements

**Example Violation**:
   EE2 says: "use set -x"
   AI recommends: "use set -eu"  # ❌ WRONG

**Correct Behavior**:
   EE2 says: "use set -x"
   AI recommends: "use set -x"   # ✅ CORRECT
```

---

#### mcp:sme_validation
Marks content that SMEs have validated as correct.

```rst
.. mcp:sme_validation:: validation_identifier
   :date: YYYY-MM-DD
   :status: ✅ validation_status

Description of what was validated and confirmation.
```

**Purpose**: Track SME-approved content.

**Example**:
```rst
.. mcp:sme_validation:: err_utilities_correct
   :date: 2025-11-19
   :status: ✅ AI analysis correct on this aspect

EVS uses err_chk and err_exit extensively. AI correctly identifies these utilities.
No changes needed.
```

---

## Semantic Enrichment Strategy

### Embedding Generation

When parsing RST with MCP directives, enhanced ingestion creates:

**Base Embedding** (text content):
```python
{
    "text": "jobs should fail with err_chk or err_exit...",
    "source": "standards.rst",
    "lines": "187-195"
}
```

**Enhanced Metadata** (from MCP directives):
```python
{
    "compliance_category": "production_utilities",
    "priority": "critical",
    "intent": "use_err_utilities",
    "severity": "must",
    "enforcement": "runtime_check",
    "examples": ["err_chk_usage", "err_exit_usage"],
    "anti_patterns": ["forced_exit_in_operational_job"],
    "correct_patterns": ["natural_return_with_err_utilities"],
    "context": "operational_job",
    "ee2_section": "Section C: Production Utilities"
}
```

**Result**: Queries can filter by metadata AND semantic similarity.

### Query Routing

**Anti-Pattern Detection**:
```python
# Query: "Should I add exit 1 to my operational script?"

# Enhanced search finds:
1. anti_pattern: forced_exit_in_operational_job
2. context: operational_job
3. severity: must_not

# Response includes:
- Warning: "Do NOT use exit statements"
- SME justification: "NCO SPA guidance"
- Alternative: correct_pattern with err_exit example
```

**Context-Aware Recommendations**:
```python
# Query: "Error handling in ush/stage_data.sh"

# Enhanced search finds:
1. context_types: utility_script detected from filepath
2. Different requirements than operational_job
3. More flexibility noted

# Response adjusted for utility context
```

---

## Directive Parsing Logic

### Expected Parser Behavior

**ingest_ee2_enhanced_v5.py** should:

1. **Parse RST Structure**:
   - Extract directive blocks with `.. mcp:*::`
   - Parse directive options (`:option: value`)
   - Capture directive content (indented text below)

2. **Build Metadata**:
   ```python
   metadata = {
       'directive_type': 'anti_pattern',
       'identifier': 'forced_exit_in_operational_job',
       'language': 'bash',
       'context': 'operational_job',
       'severity': 'must_not',
       'warning': 'Do NOT use exit statements...',
       'sme_justification': 'NCO SPA guidance...',
   }
   ```

3. **Create Embeddings**:
   - Combine directive text + metadata
   - Generate vector embedding
   - Store in ChromaDB with metadata as filters

4. **Link Related Directives**:
   ```python
   # Link anti_pattern to correct_pattern
   if directive_type == 'anti_pattern':
       find_related('correct_pattern', same_context)
   
   # Link examples to intents
   if directive_type == 'example':
       find_related('intent', same_category)
   ```

---

## Validation Rules

### Directive Consistency Checks

**Required Directive Chains**:
- Every `mcp:anti_pattern` must have corresponding `mcp:correct_pattern`
- Every `mcp:intent` should have at least one `mcp:example`
- Every `mcp:sme_correction` should reference specific EE2 lines

**Metadata Validation**:
```python
# Check required fields
assert 'severity' in directive_options
assert 'context' in directive_options

# Check valid values
assert severity in ['must', 'must_not', 'should', 'should_not', 'may']
assert context in ['operational_job', 'utility_script', 'test_script']
```

**Evidence Requirements**:
- All `mcp:sme_correction` must cite line numbers
- All `mcp:anti_pattern` must have SME justification
- All `mcp:correct_pattern` must reference EE2 section

---

## Testing Directives

### Unit Test Examples

**Test 1: Anti-Pattern Detection**
```python
def test_anti_pattern_detection():
    query = "Should I use exit 1 in my ex-script?"
    results = search_ee2_standards(query)
    
    # Should find anti_pattern directive
    assert any(r['metadata']['directive_type'] == 'anti_pattern' for r in results)
    
    # Should include warning
    assert 'Do NOT use exit' in results[0]['text']
    
    # Should include SME justification
    assert 'NCO SPA' in results[0]['metadata']['sme_justification']
```

**Test 2: Context Awareness**
```python
def test_context_discrimination():
    query_operational = "Error handling in scripts/exglobal_forecast.sh"
    query_test = "Error handling in tests/unit/test_dataflow.sh"
    
    results_op = search_ee2_standards(query_operational)
    results_test = search_ee2_standards(query_test)
    
    # Operational should get strict requirements
    assert results_op[0]['metadata']['context'] == 'operational_job'
    assert 'must_not' in results_op[0]['metadata']['severity']
    
    # Test should get flexible requirements
    assert results_test[0]['metadata']['context'] == 'test_script'
    assert 'may' in results_test[0]['metadata']['severity']
```

**Test 3: Correct Pattern Linking**
```python
def test_anti_pattern_to_correct_pattern_linking():
    # Search for anti-pattern
    results = search_ee2_standards("forced exit statements")
    anti_pattern = next(r for r in results if r['metadata']['directive_type'] == 'anti_pattern')
    
    # Should have linked correct_pattern
    assert 'correct_pattern_ref' in anti_pattern['metadata']
    
    # Fetch correct pattern
    correct = get_correct_pattern(anti_pattern['metadata']['correct_pattern_ref'])
    assert 'err_exit' in correct['text']
```

---

## Integration with ChromaDB

### Collection Schema

**Collection Name**: `ee2-standards-v6-0-0-corrected`

**Document Structure**:
```python
{
    "id": "ee2_error_handling_001",
    "text": "jobs should fail with err_chk or err_exit...",
    "metadata": {
        "source": "standards.rst",
        "lines": "187-195",
        "directive_type": "intent",
        "identifier": "use_err_utilities",
        "compliance_category": "production_utilities",
        "priority": "critical",
        "severity": "must",
        "enforcement": "runtime_check",
        "context": "operational_job",
        "ee2_section": "Section C: Production Utilities",
        "has_examples": True,
        "has_anti_patterns": True,
        "sme_validated": True,
        "phase": 2,
        "date_annotated": "2025-11-19"
    }
}
```

### Query Patterns

**Filtered Query** (with context):
```python
results = collection.query(
    query_texts=["bash script error handling"],
    where={
        "$and": [
            {"context": "operational_job"},
            {"directive_type": {"$in": ["intent", "anti_pattern", "correct_pattern"]}}
        ]
    },
    n_results=5
)
```

**Similarity + Anti-Pattern**:
```python
# Find documents semantically similar to query
# Filter for anti-patterns to show warnings
results = collection.query(
    query_texts=["should I add exit statements"],
    where={"directive_type": "anti_pattern"},
    n_results=3
)
```

---

## Ingestion Script Requirements

### ingest_ee2_enhanced_v5.py Expected Features

**Command-Line Interface**:
```bash
python3 ingest_ee2_enhanced_v5.py \
    --source /path/to/phase2_annotations/ \
    --collection ee2-standards-v6-0-0-corrected \
    --validate-directives \
    --check-evidence \
    --link-patterns
```

**Processing Steps**:
1. Parse all `.rst` files in source directory
2. Extract MCP directives with full metadata
3. Validate directive consistency
4. Check for required evidence (line numbers, SME justifications)
5. Link anti_patterns to correct_patterns
6. Generate embeddings with enhanced metadata
7. Store in ChromaDB collection
8. Report statistics (directives parsed, documents created, validation errors)

**Output**:
```
Parsing: ee2_error_handling_sme_corrections.rst
  ✅ Found 2 mcp:sme_correction directives
  ✅ Found 3 mcp:anti_pattern directives
  ✅ Found 2 mcp:correct_pattern directives
  ✅ Found 3 mcp:ai_guidance_rule directives
  ✅ All anti_patterns have correct_pattern links
  ✅ All sme_corrections cite line numbers

Creating embeddings...
  ✅ 15 documents created
  ✅ 45 metadata fields populated
  ✅ 3 anti_pattern → correct_pattern links

Collection: ee2-standards-v6-0-0-corrected
  Documents: 15
  Avg metadata fields: 8.2
  Directives: 10 (2 corrections, 3 anti-patterns, 2 correct-patterns, 3 rules)

✅ Enhanced ingestion complete
```

---

**Last Updated**: November 19, 2025  
**Status**: Reference guide complete, awaiting ingest_ee2_enhanced_v5.py implementation
