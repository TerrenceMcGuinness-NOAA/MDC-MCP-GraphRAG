# CI Test Case Documentation Workflow

**Purpose**: Automatically discover, analyze, and document all CI test case YAML files to enable expert-level understanding of test configurations

**Created**: November 15, 2025  
**Priority**: HIGH - Key capability gap identified  
**Estimated Time**: 2-3 hours

---

## Problem Statement

**Gap Identified**: MCP tools cannot answer questions about CI test cases because:
- CI YAML files in `dev/ci/cases/` are not ingested
- No documentation exists for test case configurations
- Test case knowledge is tribal/manual

**User Request**: "What does C96C48mx500_S2SW_cyc_gfs.yaml test and why is it important?"
**Current Response**: Empty - no data available

---

## Phase 1: Discovery and Analysis

### Step 1: Scan CI Test Cases
**Type**: command
**Required**: Yes
**Component**: file_system

Find all CI test case YAML files in the global-workflow repository.

```bash
find /mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow/dev/ci/cases -name "*.yaml" -type f
```

**Expected Output**: ~50-100 YAML test case files

### Step 2: Parse YAML Structure
**Type**: ingestion
**Required**: Yes
**Source**: CI YAML files

Extract key configuration from each YAML:
- Test name (filename)
- Experiment type (app, mode, net)
- Resolutions (atmos, ocean, ensemble)
- Date range (idate, edate)
- System configuration
- Skip conditions

### Step 3: Categorize Test Cases
**Type**: validation
**Required**: Yes
**Target**: test_case_categories

Group test cases by:
- **Application** (S2S, S2SW, ATM, etc.)
- **Mode** (cycled, forecast-only)
- **Resolution** (C96, C384, C768)
- **Duration** (short CI, medium, long validation)
- **Platform** (all, specific hosts)

---

## Phase 2: Documentation Generation

### Step 4: Generate Test Case Docs
**Type**: command
**Required**: Yes
**Component**: documentation_generator

For each test case, create markdown documentation:

```markdown
# Test Case: [Filename]

## Configuration
- **Application**: S2SW (Subseasonal to Seasonal Weather)
- **Mode**: Cycled (continuous DA cycles)
- **Atmosphere Resolution**: C96 (~100km)
- **Ensemble Resolution**: C48 (~200km)
- **Ocean Resolution**: 0.5 degrees (mx500)
- **Start Date**: 2021-12-20 12Z
- **End Date**: 2021-12-21 00Z
- **Cycles**: 3 cycles (12Z, 18Z, 00Z)
- **Ensemble Members**: 2

## Purpose
Tests the coupled atmosphere-ocean-ice system in cycled mode with:
- Medium resolution atmosphere (C96)
- Coarser ensemble (C48)
- Medium resolution ocean (0.5°)
- Short 12-hour runtime for CI validation

## Key Validations
- Data assimilation cycle completion
- Ocean-atmosphere coupling
- Ensemble generation
- Product creation

## Platform Notes
- Skipped on: gaeac5
- Runs on: hera, orion, hercules, wcoss2

## Related Tests
- Similar: C96C48mx100_S2SW_cyc_gfs.yaml (finer ocean)
- Parent: gfs_cyc_defaults_ci.yaml (base config)
```

### Step 5: Create CI Knowledge Collection
**Type**: ingestion
**Required**: Yes
**Target**: chromadb

Ingest generated documentation into new ChromaDB collection:
- **Collection Name**: `ci-test-cases-v1-0-0`
- **Documents**: ~50-100 test case docs
- **Embeddings**: all-mpnet-base-v2 (768-dim)
- **Metadata**: test_name, app, mode, resolution, duration

---

## Phase 3: Integration and Testing

### Step 6: Update MCP Tools
**Type**: command
**Required**: Yes
**Component**: SemanticSearchTools

Add CI test case search capability:
- Update `search_documentation` to include ci-test-cases collection
- Create dedicated `search_ci_test_cases` tool
- Enable multi-collection search (docs + CI cases)

### Step 7: Test Expert Queries
**Type**: validation
**Required**: Yes
**Target**: mcp_tools

Validate the system can answer:
- "What does C96C48mx500_S2SW_cyc_gfs.yaml test?"
- "Which test cases use S2SW application?"
- "What's the difference between C96 and C384 tests?"
- "Why is this test skipped on gaeac5?"
- "Find all cycled mode test cases"

### Step 8: Graph Enrichment
**Type**: ingestion
**Required**: No
**Component**: neo4j

Optional: Create relationships in Neo4j:
- TEST_CASE → USES → CONFIG_FILE
- TEST_CASE → VALIDATES → COMPONENT
- TEST_CASE → SIMILAR_TO → TEST_CASE

---

## Phase 4: Automation (Future)

### Step 9: Auto-Update on Changes
**Type**: command
**Required**: No
**Component**: git_hooks

Watch for CI YAML changes and auto-regenerate docs:
- Git hook on `dev/ci/cases/*.yaml` modifications
- Automatic re-ingestion pipeline
- Version tracking in ChromaDB metadata

---

## Success Criteria

**Completion Checklist**:
- ✅ All CI YAML files discovered
- ✅ Documentation generated for each test case
- ✅ ChromaDB collection populated (50+ docs)
- ✅ MCP tools can answer CI test case questions
- ✅ Expert-level understanding achieved

**Validation Queries**:
```bash
# Should return detailed explanation
explain_workflow_component("C96C48mx500_S2SW_cyc_gfs.yaml")

# Should find all S2SW tests
search_ci_test_cases("S2SW application coupled test")

# Should explain resolution differences
search_ci_test_cases("C96 vs C384 resolution comparison")
```

---

## Implementation Script

**Location**: `mcp_server_node/scripts/ingest_ci_test_cases.py`

**Features**:
- YAML parsing with PyYAML
- Documentation template generation
- ChromaDB ingestion
- Progress reporting
- Dry-run mode for validation

**Usage**:
```bash
# Discovery only
python3 scripts/ingest_ci_test_cases.py --discover

# Generate docs (no ingestion)
python3 scripts/ingest_ci_test_cases.py --generate-docs --dry-run

# Full ingestion
python3 scripts/ingest_ci_test_cases.py --full

# Update existing
python3 scripts/ingest_ci_test_cases.py --update
```

---

## Metadata

**Priority**: HIGH  
**Effort**: 2-3 hours  
**Dependencies**: ChromaDB, sentence-transformers, PyYAML  
**Assignee**: Self-directed (SDD bootstrap capability)  
**Status**: READY TO EXECUTE

**Related Workflows**:
- `data_ingestion_workflow.md` - Base ingestion patterns
- `rag_enhancement_workflow.md` - Collection management
- `test_health_check_workflow.md` - Validation approach

---

## Notes

This workflow demonstrates **SDD Phase 3A capability** - the system can:
1. Read this workflow (parse markdown)
2. Understand the steps (extract metadata)
3. Execute the workflow (run commands, ingest data)
4. Validate completion (check success criteria)

This is a **perfect test case** for the newly implemented workflow automation!
