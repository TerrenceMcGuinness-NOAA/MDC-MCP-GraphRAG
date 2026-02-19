# Phase 27: J-Job and Script RAG Enhancement

**Status**: IN PROGRESS  
**Created**: February 4, 2026  
**Updated**: February 4, 2026  
**Author**: Terrence McGuinness  
**Priority**: HIGH - Enables effective workflow component analysis via MCP tools

## Implementation Progress

| Phase | Status | Deliverable |
|-------|--------|-------------|
| 27A | ✅ COMPLETE | Path resolution fix for `dev/` structure |
| 27B | ✅ COMPLETE | Shell script parser for Neo4j ingestion (v8) |
| 27C | ✅ COMPLETE | J-Job ChromaDB ingestion with MPNet embeddings (768-dim) |
| 27D | ✅ COMPLETE | `list_job_scripts` search filter implementation |
| 27E | ✅ COMPLETE | Unified MPNet embeddings for Node.js/Python + `get_job_details` |
| 27F | ✅ COMPLETE | Shell graph ingestion + cross-language bridge re-run |
| 27G | ✅ COMPLETE | End-to-end validation of 27A-F against live databases |
| 27H | 🔲 NOT STARTED | `search_documentation` multi-collection routing |
| 27I | 🔲 NOT STARTED | External Fortran EXECUTES bridge resolution |

## Validation Evidence (February 4, 2026)

### Phase 27A: Path Resolution - VALIDATED

**Test**: `describe_component({ component: 'JGDAS_FIT2OBS', show_content: true })`

**Result**: ✅ PASS
- Found file at `${HOMEgfs}/dev/jobs/JGDAS_FIT2OBS`
- Returned 2928 bytes of content
- Script sources `jjob_header.sh`, uses prepbufr data, outputs to `ARCDIR/fits/`

### Phase 27D: Search Filter + Verification Category - VALIDATED

**Test 1**: `list_job_scripts({ search: 'fit2obs' })`
- **Result**: ✅ PASS - Returned 1 job (JGDAS_FIT2OBS) instead of all 89

**Test 2**: `list_job_scripts({ category: 'verification' })`
- **Result**: ✅ PASS - Returned 9 verification jobs:
  - JGDAS_ATMOS_VERFOZN, JGDAS_ATMOS_VERFRAD, JGDAS_FIT2OBS
  - JGEFS_WAVE_STAT, JGEFS_WAVE_STAT_PNT
  - JGFS_ATMOS_CYCLONE_GENESIS, JGFS_ATMOS_CYCLONE_TRACKER
  - JGLOBAL_ANALYSIS_STATS, JGLOBAL_ATMOS_ENSSTAT

### Bonus: Enhanced Health Check with Functional Validation

**Problem Identified**: Health checks reported "HEALTHY" when tools were actually ineffective. 14,968 documents + 12 collections meant nothing if queries couldn't find J-Jobs.

**Solution**: Added `functional: true` parameter to `mcp_health_check` that runs 5 effectiveness tests:

| Test | Tool | What It Validates |
|------|------|-------------------|
| Path Resolution | `describe_component` | Can find J-Jobs in `dev/jobs/` |
| Search Filter | `list_job_scripts` | Search parameter actually filters |
| Search Relevance | `search_documentation` | Returns relevant documentation |
| Graph Relationships | `find_callers_callees` | Neo4j has code relationships |
| J-Job Content | `search_documentation` | J-Jobs indexed in ChromaDB |

**Usage**:
```javascript
mcp_health_check({ detailed: true, functional: true })
```

**Reports**: PASS/PARTIAL/FAIL with specific remediation guidance for each failed test.

### Phase 27B: Neo4j Shell Script Parser - IMPLEMENTED

**Implementation Details**:

1. **Search Paths Enhanced** (`CodeStructureIngester.getDefaultSearchPaths`):
   - Added `dev/jobs/` - 89 J-Jobs (JGDAS_*, JGFS_*, JGLOBAL_*)
   - Added `dev/scripts/` - 41 ex-scripts (exgdas_*, exgfs_*)
   - Retained `scripts/` and `ush/` for legacy paths

2. **J-Job File Discovery** (`findFilesRecursive`):
   - New `includeJJobs` option for extensionless files
   - Pattern: `/^J[A-Z]+/` matches J-Job naming convention
   - Handles files without `.sh` extension

3. **Enhanced Shell Parser** (`parseShellContent`):
   ```javascript
   // J-Job specific patterns added:
   jjobHeaderPattern: /source.*jjob_header\.sh.*-e\s*["']?([^"'\s]+)["']?.*-c\s*["']?([^"']+)["']?/
   exScriptPattern: /\$\{SCRIPT[S]?[a-zA-Z_]*\}\/([a-zA-Z_][a-zA-Z0-9_]*\.sh)/
   ```

4. **New Neo4j Structures**:
   - `JJob` label on File nodes for J-Job files
   - `EXECUTES` relationship: J-Job → ex-script
   - Properties: `task`, `configs[]`, `isJJob`

**Files Modified**:
- `mcp_server_node/src/ingestion/neo4j/CodeStructureIngester.js`
- `mcp_server_node/src/ingestion/neo4j/GraphSchema.js`

**Pending**: Run ingestion to populate Neo4j with 130 shell files

---

## Problem Statement

Investigation of `JGDAS_FIT2OBS` job using 8 MCP tools revealed **complete tool ineffectiveness** - none provided useful information about the specific job script.

### Tool Effectiveness Audit (February 4, 2026)

| Tool | Result | Issue |
|------|--------|-------|
| `describe_component` | **FAILED** | Searched `jobs/` but files are in `dev/jobs/` |
| `explain_workflow_component` | **FAILED** | Returned empty content - no data indexed |
| `search_documentation` | **FAILED** | 10 results, 0 about JGDAS_FIT2OBS; 3 duplicates |
| `analyze_code_structure` | **FAILED** | File not found - path resolution mismatch |
| `find_callers_callees` | **PARTIAL** | Found name but 0 relationships (Neo4j has no shell analysis) |
| `trace_execution_path` | **FAILED** | "Function not found" (inconsistent with above) |
| `find_dependencies` | **FAILED** | No imports/importers found |
| `find_related_files` | **FAILED** | 0 related files |
| `list_job_scripts` | **PARTIAL** | Listed 89 jobs but `search` filter was ignored |
| `get_workflow_structure` | **FAILED** | Invalid input error (enum mismatch) |

### Impact

- Users asking "What does JGDAS_FIT2OBS do?" get no useful MCP response
- Manual `grep_search` and `file_search` required to locate scripts
- RAG investment not providing value for core workflow analysis use case

---

## Root Cause Analysis

### 1. Repository Structure Refactoring (HIGH PRIORITY)

**Background**: Global Workflow repository was refactored to place operational scripts under `dev/` directory.

**Current structure**:
```
supported_repos/global-workflow/
├── dev/
│   ├── jobs/           # ← J-JOB scripts (JGDAS_*, JGFS_*, JGLOBAL_*)
│   │   └── JGDAS_FIT2OBS
│   ├── scripts/        # ← ex-scripts (exgdas_*, exgfs_*)
│   ├── parm/           # ← Parameter/config files
│   │   └── config/
│   │       ├── gfs/
│   │       └── gcafs/
│   └── job_cards/      # ← Rocoto integration
├── jobs/               # ← EMPTY or symlinks (tools searching here)
├── scripts/            # ← EMPTY or symlinks
└── ush/                # ← Utility shell scripts (some remain here)
```

**Tool Hardcoded Paths** (from `describe_component`):
```javascript
// WorkflowInfoTools.js
const searchPaths = [
  "/app/supported_repos/global-workflow/jobs/",      // ✗ Empty
  "/app/supported_repos/global-workflow/scripts/",   // ✗ Empty  
  "/app/supported_repos/global-workflow/ush/",       // Partial
  "/app/supported_repos/global-workflow/parm/"       // ✗ Wrong level
];
// MISSING: dev/jobs/, dev/scripts/, dev/parm/config/
```

### 2. Job Scripts Not Indexed in ChromaDB (HIGH PRIORITY)

ChromaDB has 14,968 documents across 12 collections, but **zero J-Job script content**:

| Collection | Documents | Contains J-Jobs? |
|------------|-----------|------------------|
| global-workflow-docs-v7-0-0 | 3,788 | ❌ Documentation only |
| code-with-context-v7-0-0 | 1,543 | ❌ Python/ufs-weather-model |
| code_with_context_v6_graph_enriched | 4,658 | ❌ No shell scripts |
| ee2-standards-v5-0-0-enhanced | 34 | ❌ EE2 standards only |

**Evidence**: `search_documentation` for "JGDAS_FIT2OBS" returned:
- UFS utils documentation (unrelated)
- EE2 example J-job `JPMB_FORECAST` (3x duplicate)
- Generic workflow testing docs
- **Zero** results from actual JGDAS_FIT2OBS content

### 3. Neo4j Missing Shell Script Analysis (MEDIUM PRIORITY)

Neo4j graph contains:
- 2,744 files
- 1,540 functions  
- 63,790 CALLS relationships

But these are **Python/Fortran/C only**. Shell script relationships are not captured:

```bash
# From JGDAS_FIT2OBS - NOT in Neo4j
source "${HOMEgfs}/ush/jjob_header.sh"              # → IMPORTS relationship
"${SCRIPTSfit2obs}/excfs_gdas_vrfyfits.sh"          # → CALLS relationship
export PRPI=${COMIN_OBS}/${RUN}.t${vcyc}z.prepbufr  # → DEPENDS_ON relationship
```

### 4. `list_job_scripts` Search Filter Non-Functional (MEDIUM PRIORITY)

Tool schema accepts `search` parameter but implementation ignores it:

```javascript
// Called with: { category: "all", search: "fit2obs" }
// Expected: 1 result (JGDAS_FIT2OBS)
// Actual: 89 results (all jobs, unfiltered)
```

### 5. Parameter Name Inconsistencies (LOW PRIORITY)

| Tool | Path Parameter |
|------|----------------|
| `describe_component` | `component` |
| `analyze_code_structure` | `file_path` |
| `trace_execution_path` | `function_name` |
| `find_dependencies` | `target` |
| `get_workflow_structure` | (enum, not free text) |

---

## Implementation Plan

### Phase 27A: Path Resolution Fix

**Files to modify**:
- [mcp_server_node/src/tools/WorkflowInfoTools.js](../../mcp_server_node/src/tools/WorkflowInfoTools.js)
- [mcp_server_node/src/tools/CodeAnalysisTools.js](../../mcp_server_node/src/tools/CodeAnalysisTools.js)

**Changes**:
```javascript
// WorkflowInfoTools.js - describe_component
const WORKFLOW_ROOT = process.env.MCP_WORKFLOW_ROOT || '/app/supported_repos/global-workflow';

const searchPaths = [
  // Primary paths (dev/ structure - current)
  `${WORKFLOW_ROOT}/dev/jobs/`,
  `${WORKFLOW_ROOT}/dev/scripts/`,
  `${WORKFLOW_ROOT}/dev/parm/`,
  `${WORKFLOW_ROOT}/dev/parm/config/gfs/`,
  `${WORKFLOW_ROOT}/dev/parm/config/gcafs/`,
  `${WORKFLOW_ROOT}/dev/job_cards/`,
  
  // Secondary paths (legacy structure - fallback)
  `${WORKFLOW_ROOT}/jobs/`,
  `${WORKFLOW_ROOT}/scripts/`,
  `${WORKFLOW_ROOT}/ush/`,
  `${WORKFLOW_ROOT}/parm/`,
  
  // Include GCAFS if available
  '/app/supported_repos/GCAFS/jobs/',
  '/app/supported_repos/GCAFS/dev/jobs/'
];
```

**Validation**:
```bash
# Test describe_component finds J-Job
describe_component({ component: "JGDAS_FIT2OBS" })
# Expected: Returns script content from dev/jobs/JGDAS_FIT2OBS
```

---

### Phase 27B: Shell Script Parser for Neo4j

**New file**: `mcp_server_node/scripts/ingest_shell_scripts_to_neo4j.js`

**Parser capabilities**:
1. **Source detection**: `source "path"`, `. path`
2. **Script invocation**: `${VAR}/script.sh`, `./script.sh`
3. **Environment dependencies**: `export VAR=...`, `${VAR}`
4. **Function definitions**: `function_name() {`
5. **Configuration reads**: `config.${component}`

**Neo4j Schema Extensions**:
```cypher
// New node types
(:ShellScript {name, path, type: "j-job"|"ex-script"|"ush"})
(:EnvironmentVariable {name, default_value})
(:ConfigFile {name, path})

// New relationships
(script)-[:SOURCES]->(other_script)
(script)-[:INVOKES]->(ex_script)
(script)-[:READS_CONFIG]->(config)
(script)-[:EXPORTS]->(env_var)
(script)-[:DEPENDS_ON_ENV]->(env_var)
```

**Example extraction from JGDAS_FIT2OBS**:
```cypher
// Create J-Job node
CREATE (j:ShellScript {
  name: 'JGDAS_FIT2OBS',
  path: 'dev/jobs/JGDAS_FIT2OBS',
  type: 'j-job',
  category: 'verification'
})

// Source relationship
MATCH (j:ShellScript {name: 'JGDAS_FIT2OBS'})
MATCH (h:ShellScript {name: 'jjob_header.sh'})
CREATE (j)-[:SOURCES {line: 3}]->(h)

// Invokes relationship  
MATCH (j:ShellScript {name: 'JGDAS_FIT2OBS'})
CREATE (ex:ShellScript {
  name: 'excfs_gdas_vrfyfits.sh',
  path: '${SCRIPTSfit2obs}/excfs_gdas_vrfyfits.sh',
  type: 'external',
  package: 'Fit2Obs'
})
CREATE (j)-[:INVOKES {line: 55}]->(ex)

// Environment dependencies
MATCH (j:ShellScript {name: 'JGDAS_FIT2OBS'})
CREATE (e:EnvironmentVariable {name: 'PRPI', description: 'PrepBUFR input file'})
CREATE (j)-[:DEPENDS_ON_ENV]->(e)
```

---

### Phase 27C: J-Job ChromaDB Ingestion

**Ingestion script**: `mcp_server_node/scripts/ingest_jjobs_to_chromadb.py`

**Structured Metadata Schema**:
```json
{
  "document_type": "j-job",
  "name": "JGDAS_FIT2OBS",
  "category": "verification",
  "subcategory": "fit2obs",
  "system": "gdas",
  
  "inputs": [
    {"name": "prepbufr", "variable": "PRPI", "description": "Observation data"},
    {"name": "analysis.atm.a006.nc", "variable": "sig1", "description": "6-hour atmospheric analysis"},
    {"name": "cnvstat.tar", "variable": "CNVS", "description": "Conventional observation statistics"}
  ],
  
  "outputs": [
    {"name": "fits/", "variable": "FIT_DIR", "description": "Fit statistics"},
    {"name": "horiz/", "variable": "HORZ_DIR", "description": "Horizontal verification data"}
  ],
  
  "calls": [
    {"script": "excfs_gdas_vrfyfits.sh", "package": "Fit2Obs", "type": "external"}
  ],
  
  "sources": [
    {"script": "jjob_header.sh", "path": "${HOMEgfs}/ush/jjob_header.sh"}
  ],
  
  "config_files": [
    {"name": "config.fit2obs", "path": "parm/config/gfs/config.fit2obs"}
  ],
  
  "environment_variables": [
    {"name": "VBACKUP_FITS", "description": "Hours to look back for verification"},
    {"name": "ARCDIR", "description": "Archive directory root"},
    {"name": "SCRIPTSfit2obs", "description": "Fit2Obs scripts directory"}
  ],
  
  "dependencies": {
    "external_packages": ["Fit2Obs"],
    "modules": ["fit2obs/${fit2obs_ver}"]
  },
  
  "workflow_position": {
    "stage": "post-analysis",
    "predecessors": ["JGDAS_ATMOS_ANALYSIS"],
    "timing": "VBACKUP_FITS hours after analysis"
  },
  
  "hpc_requirements": {
    "partition": "serial",
    "nodes": 1,
    "walltime": "00:30:00"
  },
  
  "source_file": "dev/jobs/JGDAS_FIT2OBS",
  "source_repo": "global-workflow",
  "last_indexed": "2026-02-04T00:00:00Z"
}
```

**ChromaDB Collection Structure**:
```python
# New collection: jjobs-v7-0-0 (matches global-workflow-docs-v7-0-0 versioning)
collection = chroma_client.create_collection(
    name="jjobs-v7-0-0",
    metadata={
        "description": "Global Workflow J-Job scripts with structured metadata",
        "version": "7.0.0",
        "source": "global-workflow/dev/jobs",
        "document_count": 89,
        "indexed_date": "2026-02-04"
    }
)
```

**Chunking Strategy**:
- **Full script**: Single document with complete content
- **Section chunks**: Split by major comment blocks (# ----)
- **Metadata-enriched**: Each chunk includes parent J-Job reference

---

### Phase 27D: `list_job_scripts` Search Filter

**File**: [mcp_server_node/src/tools/OperationalTools.js](../../mcp_server_node/src/tools/OperationalTools.js)

**Current implementation** (broken):
```javascript
async function listJobScripts(params) {
  const { category, search } = params;
  // search parameter is never used!
  const jobs = await scanJobsDirectory(category);
  return formatJobList(jobs);
}
```

**Fixed implementation**:
```javascript
async function listJobScripts(params) {
  const { category = 'all', search } = params;
  let jobs = await scanJobsDirectory(category);
  
  // Apply search filter
  if (search && search.trim()) {
    const searchLower = search.toLowerCase();
    jobs = jobs.filter(job => 
      job.name.toLowerCase().includes(searchLower) ||
      job.category.toLowerCase().includes(searchLower) ||
      (job.description && job.description.toLowerCase().includes(searchLower))
    );
  }
  
  return formatJobList(jobs);
}
```

**Validation**:
```javascript
// Test: list_job_scripts({ search: "fit2obs" })
// Expected: [ { name: "JGDAS_FIT2OBS", category: "verification" } ]
```

---

### Phase 27E: New `get_job_details` Tool

**File**: [mcp_server_node/src/tools/OperationalTools.js](../../mcp_server_node/src/tools/OperationalTools.js)

**Tool Schema**:
```javascript
{
  name: "get_job_details",
  description: "Get comprehensive details about a J-Job including inputs, outputs, dependencies, and related configuration",
  inputSchema: {
    type: "object",
    properties: {
      job_name: {
        type: "string",
        description: "J-Job name (e.g., JGDAS_FIT2OBS)"
      },
      include_content: {
        type: "boolean",
        default: false,
        description: "Include full script content in response"
      },
      include_config: {
        type: "boolean", 
        default: true,
        description: "Include related config file content"
      }
    },
    required: ["job_name"]
  }
}
```

**Implementation**:
```javascript
async function getJobDetails(params) {
  const { job_name, include_content = false, include_config = true } = params;
  
  // 1. Find J-Job file
  const jobPath = await findJobScript(job_name);
  if (!jobPath) {
    return { error: `J-Job ${job_name} not found` };
  }
  
  // 2. Parse script content
  const content = await fs.readFile(jobPath, 'utf8');
  const parsed = parseShellScript(content);
  
  // 3. Extract structured information
  const details = {
    name: job_name,
    path: jobPath,
    category: categorizeJob(job_name),
    
    // Extracted from script
    sources: parsed.sources,          // source "${path}" statements
    invokes: parsed.invokes,          // External script calls
    inputs: parsed.inputs,            // Input file references
    outputs: parsed.outputs,          // Output directory/file references
    environment: parsed.environment,  // Environment variable dependencies
    
    // Related files
    config_file: await findRelatedConfig(job_name),
    ex_script: await findExScript(job_name),
    
    // Optional content
    ...(include_content && { content }),
    ...(include_config && { config_content: await readConfigFile(job_name) })
  };
  
  // 4. Query Neo4j for relationships (if available)
  details.call_graph = await queryNeo4jRelationships(job_name);
  
  // 5. Query ChromaDB for documentation references
  details.documentation = await searchRelatedDocs(job_name);
  
  return details;
}
```

**Example Output**:
```json
{
  "name": "JGDAS_FIT2OBS",
  "path": "/app/supported_repos/global-workflow/dev/jobs/JGDAS_FIT2OBS",
  "category": "verification",
  
  "sources": [
    { "script": "jjob_header.sh", "path": "${HOMEgfs}/ush/jjob_header.sh", "line": 3 }
  ],
  
  "invokes": [
    { "script": "excfs_gdas_vrfyfits.sh", "variable": "SCRIPTSfit2obs", "line": 55 }
  ],
  
  "inputs": [
    { "name": "prepbufr", "variable": "PRPI", "pattern": "${RUN}.t${vcyc}z.prepbufr" },
    { "name": "analysis", "variable": "sig1", "pattern": "${RUN}.t${vcyc}z.analysis.atm.a006.nc" },
    { "name": "cnvstat", "variable": "CNVS", "pattern": "${RUN}.t${vcyc}z.cnvstat.tar" }
  ],
  
  "outputs": [
    { "name": "fits", "variable": "FIT_DIR", "path": "${ARCDIR}/fits" },
    { "name": "horiz", "variable": "HORZ_DIR", "path": "${ARCDIR}/horiz" }
  ],
  
  "environment": {
    "required": ["HOMEgfs", "PDY", "cyc", "RUN", "VBACKUP_FITS"],
    "exported": ["CDATE", "FIT_DIR", "HORZ_DIR", "PRPI", "sig1", "sfc1", "CNVS"]
  },
  
  "config_file": {
    "path": "dev/parm/config/gfs/config.fit2obs",
    "content": "# Fit2Obs configuration\nexport VBACKUP_FITS=24\n..."
  },
  
  "call_graph": {
    "callers": [],
    "callees": ["excfs_gdas_vrfyfits.sh"],
    "sources": ["jjob_header.sh"]
  },
  
  "documentation": [
    { "title": "Fit2Obs Verification", "source": "global-workflow-docs", "relevance": 0.89 }
  ]
}
```

---

### Phase 27F: Shell Graph Ingestion + Cross-Language Bridge Re-Run

**Prerequisite**: Phases 27A-27E complete and tested (all DONE).

**Audit Findings (February 19, 2026)**:
The v8 ingestion scripts exist in `mcp_server_node/scripts/` but `ingest_shell_graph_v8.py` was **never executed**. Current Neo4j state shows `ShellScript: 0` nodes. The cross-language bridge script ran but yielded only 7 edges because it had no shell nodes to link to.

#### Pre-Flight Fixes (REQUIRED before execution)

**Fix 1: Neo4j password default (SPOT violation)**
```python
# ingest_shell_graph_v8.py line ~30 — CURRENT (wrong):
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "password")

# CORRECT — must match mcp-env.sh:
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "gfsworkflow2025")
```

**Fix 2: Add `--dry-run` flag to `ingest_shell_graph_v8.py`**
The script runs `clear_shell_graph()` unconditionally on startup — destructive with no preview. Add:
```python
parser.add_argument('--dry-run', action='store_true',
                    help='Parse and report without writing to Neo4j')
```

**Fix 3: Duplicate session line in `ingest_cross_language_bridges.py`**
```python
# Remove duplicate: session = driver.session()
```

#### Execution Order

All scripts are in `mcp_server_node/scripts/`. Source environment first:
```bash
source mcp_server_node/mcp-env.sh
cd mcp_server_node
```

| Step | Script | Target | Expected Outcome |
|------|--------|--------|------------------|
| 1 | `python3 scripts/ingest_shell_graph_v8.py --dry-run` | Neo4j | Preview: count of ShellScript, ShellFunction, ConfigFile nodes |
| 2 | `python3 scripts/ingest_shell_graph_v8.py` | Neo4j | Creates :ShellScript, :ShellFunction, :ConfigFile + SOURCES, INVOKES, READS_CONFIG, EXPORTS, DEPENDS_ON_ENV, DEFINES |
| 3 | `python3 scripts/ingest_cross_language_bridges.py` | Neo4j | Re-run: should yield 50+ edges (was 7 without shell nodes) |
| 4 | Validate node counts | Neo4j | `ShellScript > 0`, `INVOKES > 4`, `EXECUTES > 3` |

**Note**: Steps 1-2 are the critical path. `ingest_jjobs_v8.py` (ChromaDB) and `ingest_code_v8.py` (Neo4j+ChromaDB) are already complete with current data (700 and 58,761 docs respectively).

#### Design: Ingestion Orchestrator (NEW)

No master script exists to run all 7 ingestion scripts in correct order. Create `mcp_server_node/scripts/run_full_ingestion.sh`:

```bash
#!/bin/bash
# run_full_ingestion.sh — Master orchestrator for all ingestion pipelines
# Correct execution order respects data dependencies
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/../mcp-env.sh"

echo "[Phase 27F] Full Ingestion Pipeline"
echo "===================================="

# Phase 1: Graph structure (Neo4j) — no cross-DB dependencies
echo "[1/7] Fortran graph..."
python3 "${SCRIPT_DIR}/ingest_fortran_graph.py" "$@"

echo "[2/7] Shell script graph..."
python3 "${SCRIPT_DIR}/ingest_shell_graph_v8.py" "$@"

echo "[3/7] Environment variables..."
python3 "${SCRIPT_DIR}/ingest_env_variables.py" "$@"

# Phase 2: Code + docs (ChromaDB + Neo4j)
echo "[4/7] Code with context..."
python3 "${SCRIPT_DIR}/ingest_code_v8.py" "$@"

echo "[5/7] J-Job scripts..."
python3 "${SCRIPT_DIR}/ingest_jjobs_v8.py" "$@"

echo "[6/7] Documentation..."
python3 "${SCRIPT_DIR}/ingest_documentation_v8.py" "$@"

# Phase 3: Cross-references (requires all above)
echo "[7/7] Cross-language bridges..."
python3 "${SCRIPT_DIR}/ingest_cross_language_bridges.py" "$@"

echo "[OK] Full ingestion complete"
```

This orchestrator:
- Sources `mcp-env.sh` (SPOT for database credentials)
- Runs graph-only scripts first (Fortran, shell, env vars — no ChromaDB dependency)
- Runs hybrid scripts next (code, jjobs, docs — write to both DBs)
- Runs bridges LAST (needs all node types present)
- Passes through `$@` so `--dry-run` works on supported scripts

---

### Phase 27G: End-to-End Validation

**Prerequisite**: Shell graph ingested (27F step 2) and bridges re-run (27F step 3).

#### Current Database Baseline (February 19, 2026)

Before 27F execution — these are the ACTUAL live metrics:

| Metric | Pre-27F Value | Post-27F Target |
|--------|---------------|-----------------|
| Neo4j total nodes | 40,207 | 40,207 + shell nodes |
| Neo4j ShellScript nodes | **0** | **> 300** (384 expected from spec) |
| Neo4j INVOKES edges | 4 | **> 20** |
| Neo4j EXECUTES edges | 3 | **> 10** |
| ChromaDB jjobs-v8-0-0 | 700 docs | 700 (unchanged) |
| ChromaDB total docs | 63,072 | 63,072 (unchanged) |
| Cross-language bridges | 7 | **> 50** |

#### Validation Test Suite

Run after 27F ingestion. Verify with Cypher queries and MCP tool calls.

**Neo4j Graph Integrity**:
```cypher
-- ShellScript nodes created
MATCH (s:ShellScript) RETURN count(s) AS shell_scripts;
-- Expected: > 300

-- SOURCES relationships (source/. statements)
MATCH ()-[r:SOURCES]->() RETURN count(r) AS sources_count;
-- Expected: > 148 (current baseline)

-- Cross-language INVOKES (shell → Fortran/Python)
MATCH ()-[r:INVOKES]->() RETURN count(r) AS invokes_count;
-- Expected: > 20 (was 4)

-- J-Job → ex-script chains
MATCH (j:ShellScript {type: 'j-job'})-[:INVOKES]->(e:ShellScript {type: 'ex-script'})
RETURN j.name, e.name LIMIT 10;
-- Expected: JGDAS_FIT2OBS → excfs_gdas_vrfyfits.sh, etc.
```

**MCP Tool Validation**:
```
1. find_callers_callees({ function_name: "JGDAS_FIT2OBS" })
   → Must show excfs_gdas_vrfyfits.sh in callees, jjob_header.sh in sources

2. trace_execution_path({ function_name: "JGDAS_FIT2OBS" })
   → Must trace through ex-script into Fortran subroutines (if cross-language bridges work)

3. find_env_dependencies({ variable_name: "PRPI" })
   → Must show JGDAS_FIT2OBS as a consumer

4. search_documentation({ query: "fit2obs verification" })
   → Must return JGDAS_FIT2OBS from jjobs-v8-0-0 collection

5. get_code_context({ symbol: "JGDAS_FIT2OBS" })
   → Must return GGSR neighborhood with community context
```

**Cross-Language Bridge Quality**:
```cypher
-- Full chain: J-Job → ex-script → Fortran subroutine
MATCH path = (j:ShellScript {type: 'j-job'})-[:INVOKES]->
             (e:ShellScript)-[:EXECUTES]->
             (f:FortranSubroutine)
RETURN j.name, e.name, f.name LIMIT 10;
-- This is the "holy grail" query — proves end-to-end cross-language tracing
```

#### Design: Bridge Yield Improvement Baseline

Before re-running `ingest_cross_language_bridges.py`, capture the current state:
```bash
# Save pre-run bridge counts
echo "Pre-27F bridge state:" > /tmp/bridge_baseline.txt
echo "EXECUTES: $(cypher-shell 'MATCH ()-[r:EXECUTES]->() RETURN count(r)')" >> /tmp/bridge_baseline.txt
echo "INVOKES: $(cypher-shell 'MATCH ()-[r:INVOKES]->() RETURN count(r)')" >> /tmp/bridge_baseline.txt
```

After re-running bridges with shell nodes present:
```bash
# Compare post-run
echo "Post-27F bridge state:" >> /tmp/bridge_baseline.txt
echo "EXECUTES: $(cypher-shell 'MATCH ()-[r:EXECUTES]->() RETURN count(r)')" >> /tmp/bridge_baseline.txt
echo "INVOKES: $(cypher-shell 'MATCH ()-[r:INVOKES]->() RETURN count(r)')" >> /tmp/bridge_baseline.txt
echo "Improvement factor: $(diff pre post)" >> /tmp/bridge_baseline.txt
```

This yields the empirical evidence for Phase 22 (Validation & Benchmarking).

**End-to-End Validation Checklist**:

- [ ] ShellScript node count > 300 in Neo4j
- [ ] Cross-language bridge count > 50 (up from 7)
- [ ] `describe_component JGDAS_FIT2OBS` returns script content
- [ ] `explain_workflow_component JGDAS_FIT2OBS` returns meaningful explanation
- [ ] `search_documentation "fit2obs verification"` returns JGDAS_FIT2OBS
- [ ] `find_callers_callees JGDAS_FIT2OBS` shows excfs_gdas_vrfyfits.sh
- [ ] `list_job_scripts search=fit2obs` returns 1 result
- [ ] `get_job_details JGDAS_FIT2OBS` returns structured metadata
- [ ] All 89 J-Jobs indexed in ChromaDB (already 700 docs in jjobs-v8-0-0)
- [ ] J-Job → ex-script → Fortran chain query returns results
- [ ] `get_code_context JGDAS_FIT2OBS` returns GGSR neighborhood

---

## Timeline

| Phase | Duration | Dependencies | Deliverable |
|-------|----------|--------------|-------------|
| 27A | 2 hours | - | Path resolution fix |
| 27B | 8 hours | 27A | Shell script parser + Neo4j ingestion |
| 27C | 6 hours | 27B | J-Job ChromaDB ingestion + metadata schema |
| 27D | 1 hour | - | list_job_scripts filter fix |
| 27E | 4 hours | 27A-27C | get_job_details tool |
| 27F | 4 hours | 27A-27E | Full RAG re-ingestion |
| 27G | 4 hours | 27F | Validation and testing |

**Total**: ~29 hours

---

## Dependencies

### Internal
- Phase 19: Content Abstraction Layer (for content parameter support)
- Phase 11: Docker MCP Gateway (container volume mounts)

### External
- [Fit2Obs package](https://github.com/NOAA-EMC/Fit2Obs) - External dependency not in repo

### Software
- Neo4j 4.4+
- ChromaDB v2 API
- Node.js 18+
- Python 3.11+

---

## Related SDDs

| SDD | Relationship |
|-----|--------------|
| Phase 10 | Fortran call tree ingestion (similar graph approach) |
| Phase 19 | Content abstraction (content parameter pattern) |
| Phase 22 | Validation subsystem (test infrastructure) |
| Phase 24 | Graph-guided retrieval (will benefit from shell graph) |

---

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| External Fit2Obs calls not resolvable | Medium | Document as external dependency, add placeholder nodes |
| Shell parsing edge cases | Medium | Start with common patterns, iterate |
| Large re-ingestion time | Low | Run during off-hours, incremental updates |
| Backwards compatibility | Low | Keep existing collections, add new ones |

---

## Design Concepts for 27F-G Facilitation

### 1. SPOT-Compliant Credential Resolution

All ingestion scripts must read Neo4j/ChromaDB credentials from `mcp-env.sh` — the Single Point of Truth. Currently `ingest_shell_graph_v8.py` hardcodes `"password"` as the default, violating SPOT. Pattern to enforce:

```python
import subprocess
def get_env_from_mcp_env():
    """Source mcp-env.sh and return environment dict."""
    result = subprocess.run(
        ['bash', '-c', 'source ../mcp-env.sh && env'],
        capture_output=True, text=True
    )
    return dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
```

All 7 scripts should use this pattern (or at minimum honor `NEO4J_PASSWORD` from environment).

### 2. Incremental vs. Full Ingestion

The `clear_shell_graph()` function in `ingest_shell_graph_v8.py` deletes all shell nodes before re-ingesting. This is wasteful for iterative development. Add an `--incremental` flag that:
- Skips files whose `mtime` hasn't changed since last ingestion
- Only creates/updates nodes for modified scripts
- Preserves manually-added relationships (e.g., SME annotations)

Store last-ingestion timestamps in a sidecar file (`mcp_server_node/scripts/.ingestion_state.json`).

### 3. Bridge Yield Amplification

The current 7-edge yield from `ingest_cross_language_bridges.py` is solely because ShellScript nodes don't exist. Once shell graph is populated, bridges should match on:

| Bridge Type | Match Pattern | Expected Yield |
|-------------|---------------|----------------|
| J-Job → ex-script | `:ShellScript {type:'j-job'} -[:INVOKES]-> :ShellScript {type:'ex-script'}` | ~89 (one per J-Job) |
| ex-script → Fortran | `:ShellScript -[:EXECUTES]-> :FortranSubroutine` | ~35 (shell→compiled) |
| Shell → Python | `:ShellScript -[:INVOKES]-> :PythonFunction` | ~20 (ush utilities) |
| Shell → env config | `:ShellScript -[:DEPENDS_ON_ENV]-> :EnvironmentVariable` | ~500+ |

### 4. Validation Harness for Phase 22 Integration

27G validation queries (Cypher counts, MCP tool calls) should be codified as a reusable test harness that Phase 22 (Validation & Benchmarking) can build on:

```javascript
// validation/graph_integrity.js
export const GRAPH_INTEGRITY_CHECKS = [
  { name: 'shell_scripts_exist', cypher: 'MATCH (s:ShellScript) RETURN count(s) > 0 AS ok' },
  { name: 'bridges_populated', cypher: 'MATCH ()-[r:INVOKES]->() RETURN count(r) > 10 AS ok' },
  { name: 'full_chain_exists', cypher: `
    MATCH (j:ShellScript)-[:INVOKES]->(e:ShellScript)-[:EXECUTES]->(f:FortranSubroutine)
    RETURN count(j) > 0 AS ok
  `},
];
```

This prevents duplication between 27G manual checks and 22's automated regression suite.

### 5. Ingestion Idempotency Contract

Each ingestion script should be safe to re-run without side effects. Current state:

| Script | Idempotent? | Issue |
|--------|-------------|-------|
| `ingest_fortran_graph.py` | Yes | Clears and rebuilds |
| `ingest_shell_graph_v8.py` | Yes* | *Destructive clear on every run |
| `ingest_env_variables.py` | Yes | Has `--delete-existing` flag |
| `ingest_code_v8.py` | Yes | Upserts |
| `ingest_jjobs_v8.py` | Yes | Has `--delete-existing` flag |
| `ingest_documentation_v8.py` | Unclear | Thin v8→v7 wrapper |
| `ingest_cross_language_bridges.py` | No | Creates duplicate edges on re-run |

Fix: `ingest_cross_language_bridges.py` should `MERGE` relationships instead of `CREATE`.

---

## Success Criteria

Post-implementation, the following query should return comprehensive results:

```
User: "What does JGDAS_FIT2OBS do?"

MCP Response (expected):
JGDAS_FIT2OBS is a GDAS verification job that compares model forecasts 
against observations using the Fit2Obs package.

**Inputs:**
- prepbufr (${RUN}.t${vcyc}z.prepbufr) - Observation data
- analysis.atm.a006.nc - 6-hour atmospheric analysis
- cnvstat.tar - Conventional observation statistics

**Outputs:**
- ${ARCDIR}/fits/ - Fit statistics
- ${ARCDIR}/horiz/ - Horizontal verification data

**External Dependencies:**
- Fit2Obs package (excfs_gdas_vrfyfits.sh)

**Configuration:**
- config.fit2obs (VBACKUP_FITS controls verification timing)

**Workflow Position:**
- Runs after JGDAS_ATMOS_ANALYSIS
- Category: verification
```

---

### Phase 27H: `search_documentation` Multi-Collection Routing

**Prerequisite**: Phase 27G complete (validated that search_documentation misses jjobs).

**Status**: NOT STARTED  
**Priority**: HIGH — Quick win, high impact  
**Estimated Effort**: 1-2 hours

#### Problem Statement

`search_documentation` only queries the `global-workflow-docs-v8-0-0` ChromaDB collection. When users search for J-Job-related content (e.g., "fit2obs verification"), the tool misses all 700 documents in `jjobs-v8-0-0`. Only `get_job_details` (hardcoded to `jjobs-v8-0-0`) can access J-Job data.

**Evidence from 27G validation**: `search_documentation({ query: "fit2obs verification" })` returned 0 J-Job results despite 700 indexed documents.

#### Root Cause

1. `SemanticSearchTools.js` → `searchDocumentation()` calls `this.dataAccess.hybridQuery(query, {...})` with **no `collection` override**
2. `UnifiedDataAccess.js` → `hybridQuery()` defaults to `collection = 'global-workflow-docs-v8-0-0'` — single collection only
3. `UnifiedDataAccess.js` → `multiSourceSearch()` exists and searches `['global-workflow-docs-v8-0-0', 'ee2-standards-v5-0-0-enhanced']` — but does NOT include `jjobs-v8-0-0` and is NOT used by `search_documentation`

File Locations:
- `mcp_server_node/src/tools/SemanticSearchTools.js` — tool handler (line ~193)
- `mcp_server_node/src/data/UnifiedDataAccess.js` — hybridQuery (line ~84), multiSourceSearch (line ~357)

#### Implementation Plan

**Option A (Recommended): Expand `multiSourceSearch` defaults and wire into `search_documentation`**

Step 1: Add `jjobs-v8-0-0` to `multiSourceSearch()` default collections:
```javascript
// UnifiedDataAccess.js → multiSourceSearch()
const {
  collections = [
    'global-workflow-docs-v8-0-0',
    'jjobs-v8-0-0',                    // ← ADD
    'ee2-standards-v5-0-0-enhanced'
  ],
  nResults = 10,
  enrichWithGraph = true
} = options;
```

Step 2: Switch `searchDocumentation()` from `hybridQuery` to `multiSourceSearch`:
```javascript
// SemanticSearchTools.js → searchDocumentation()
const results = await this.dataAccess.multiSourceSearch(query, {
  nResults: max_results,
  enrichWithGraph: include_graph
});
```

Step 3: Add optional `collection` parameter to `search_documentation` schema for targeted queries:
```javascript
// search_documentation schema
properties: {
  query: { type: 'string', description: 'Search query' },
  collection: { type: 'string', description: 'Target specific collection (default: search all)' },
  max_results: { type: 'number', default: 8 },
  // ...
}
```

When `collection` is specified, fall back to `hybridQuery` with that specific collection. When omitted, use `multiSourceSearch` across all collections.

**Option B (Minimal): Just add jjobs to `hybridQuery` default**

Change `hybridQuery()` to query multiple collections by default. Higher risk because `hybridQuery` is used by multiple callers and changing its default may affect other tools.

**Recommendation**: Option A — it's cleanly layered, doesn't change `hybridQuery` default (preserving other callers), and adds the `collection` override for power users.

#### Validation

```
1. search_documentation({ query: "fit2obs verification" })
   → MUST return JGDAS_FIT2OBS from jjobs-v8-0-0 collection

2. search_documentation({ query: "EE2 production standards" })
   → MUST still return results from ee2-standards-v5-0-0-enhanced

3. search_documentation({ collection: "jjobs-v8-0-0", query: "forecast" })
   → MUST return ONLY jjobs results (targeted override)

4. explain_with_context({ topic: "JGDAS_FIT2OBS" })
   → Should benefit from wider collection search if it also uses hybridQuery
```

#### Files Modified

| File | Change |
|------|--------|
| `mcp_server_node/src/data/UnifiedDataAccess.js` | Add `jjobs-v8-0-0` to `multiSourceSearch` defaults |
| `mcp_server_node/src/tools/SemanticSearchTools.js` | Switch `searchDocumentation` to `multiSourceSearch`, add `collection` schema param |

---

### Phase 27I: External Fortran EXECUTES Bridge Resolution

**Prerequisite**: Phase 27F complete (shell graph ingested, bridges re-run).

**Status**: NOT STARTED  
**Priority**: MEDIUM — Improves cross-language tracing completeness  
**Estimated Effort**: 4-6 hours

#### Problem Statement

`ingest_cross_language_bridges.py` found only 3 EXECUTES edges (Shell → Fortran) because 12 of 15 entries in the `EXEC_TO_PROGRAM` mapping are `None` — their Fortran PROGRAM nodes don't exist in Neo4j. These are executables from external packages (GSI, UFS_UTILS, etc.) whose source code was never ingested into the Fortran graph.

**Evidence from 27F-G**: After shell graph ingestion and bridge re-run, EXECUTES only went from 3 → 3 (no improvement). INVOKES improved from 4 → 5 (Python bridges). The bottleneck is external Fortran programs, not missing shell nodes.

#### Root Cause

The 12 unresolved executables and their source packages:

| Executable | Expected Source | In Neo4j? | Notes |
|------------|----------------|-----------|-------|
| `calc_analysis` | UFS_UTILS or GSI | No | Atmospheric analysis calculation |
| `gaussian_sfcanl` | UFS_UTILS | No | Gaussian surface analysis |
| `interp_inc` | UFS_UTILS | No | Interpolate increments |
| `enkf_chgres_recenter` | GSI (EnKF) | No | EnKF change resolution + recenter |
| `enkf_chgres_recenter_nc` | GSI (EnKF) | No | NetCDF variant |
| `getsigensmeanp_smooth` | GSI (EnKF) | No | Ensemble mean + smoothing |
| `getsfcensmeanp` | GSI (EnKF) | No | Surface ensemble mean |
| `recentersigp` | GSI (EnKF) | No | Sigma-pressure recentering |
| `fbwndgfs` | Fit2Obs (external) | No | Background wind GFS |
| `rdbfmsua` | Fit2Obs (external) | No | Read BUFR mandatory/significant upper air |
| `chgres_cube` | UFS_UTILS | No | Change resolution (cubed-sphere) |
| (3 resolved) | `gsi`, `enkf`, `calc_increment_ens` | Yes | Already matched via `ingest_fortran_graph.py` |

These Fortran programs live in submodules already registered under `supported_repos/`:
- `supported_repos/GSI/` — contains EnKF programs
- `supported_repos/UFS_utils/` — contains `chgres_cube`, surface analysis utilities
- Fit2Obs — NOT in submodules (external, NOAA-EMC/Fit2Obs)

#### Implementation Plan

**Approach: Two-track — Placeholder nodes + selective ingestion**

**Track 1: Create Placeholder FortranProgram Nodes**

For executables whose source is external or too complex to fully ingest, create `:FortranProgram` nodes with `external: true` metadata. This lets EXECUTES edges form without full source code analysis.

```python
# Add to ingest_cross_language_bridges.py or as separate script

EXTERNAL_PROGRAMS = [
    {'name': 'calc_analysis', 'package': 'UFS_UTILS', 'desc': 'Atmospheric analysis calculation'},
    {'name': 'gaussian_sfcanl', 'package': 'UFS_UTILS', 'desc': 'Gaussian surface analysis'},
    {'name': 'interp_inc', 'package': 'UFS_UTILS', 'desc': 'Interpolate increments'},
    {'name': 'chgres_cube', 'package': 'UFS_UTILS', 'desc': 'Change resolution cubed-sphere'},
    {'name': 'enkf_chgres_recenter', 'package': 'GSI', 'desc': 'EnKF change resolution + recenter'},
    {'name': 'enkf_chgres_recenter_nc', 'package': 'GSI', 'desc': 'EnKF chgres recenter (NetCDF)'},
    {'name': 'getsigensmeanp_smooth', 'package': 'GSI', 'desc': 'Ensemble mean + smoothing'},
    {'name': 'getsfcensmeanp', 'package': 'GSI', 'desc': 'Surface ensemble mean'},
    {'name': 'recentersigp', 'package': 'GSI', 'desc': 'Sigma-pressure recentering'},
    {'name': 'fbwndgfs', 'package': 'Fit2Obs', 'desc': 'Background wind GFS'},
    {'name': 'rdbfmsua', 'package': 'Fit2Obs', 'desc': 'Read BUFR mandatory/significant upper air'},
]

# Cypher to create placeholder nodes
for prog in EXTERNAL_PROGRAMS:
    session.run('''
        MERGE (p:FortranProgram {name: $name})
        SET p.external = true,
            p.package = $package,
            p.description = $desc,
            p.placeholder = true
    ''', name=prog['name'], package=prog['package'], desc=prog['desc'])
```

**Track 2: Curate `EXEC_TO_PROGRAM` Mappings**

Fill in the `None` entries with correct PROGRAM names that match the placeholder nodes:

```python
EXEC_TO_PROGRAM = {
    'gsi': 'gsi',
    'enkf': 'enkf_main',
    'calc_increment_ens': 'calc_increment_main',
    'calc_increment_ens_ncio': 'calc_increment_main',
    'calc_analysis': 'calc_analysis',                        # ← was None
    'gaussian_sfcanl': 'gaussian_sfcanl',                    # ← was None
    'interp_inc': 'interp_inc',                              # ← was None
    'enkf_chgres_recenter': 'enkf_chgres_recenter',          # ← was None
    'enkf_chgres_recenter_nc': 'enkf_chgres_recenter_nc',    # ← was None
    'getsigensmeanp_smooth': 'getsigensmeanp_smooth',        # ← was None
    'getsfcensmeanp': 'getsfcensmeanp',                      # ← was None
    'recentersigp': 'recentersigp',                          # ← was None
    'fbwndgfs': 'fbwndgfs',                                  # ← was None
    'rdbfmsua': 'rdbfmsua',                                  # ← was None
    'chgres_cube': 'chgres_cube',                            # ← was None
}
```

**Track 3 (Future): Full GSI/UFS_UTILS Fortran Ingestion**

Extend `ingest_fortran_graph.py` to scan additional submodule directories. This is heavier work and yields full call trees, but is not required for EXECUTES bridges to form.

```bash
# These repos are already git submodules:
supported_repos/GSI/           # EnKF executables
supported_repos/UFS_utils/     # chgres_cube, surface analysis
# Fit2Obs is NOT a submodule (external NOAA-EMC package)
```

This track is deferred — Track 1+2 provides EXECUTES edges immediately.

#### Execution Order

| Step | Action | Expected Outcome |
|------|--------|------------------|
| 1 | Create placeholder FortranProgram nodes (11 nodes) | Neo4j: +11 FortranProgram nodes with `external: true` |
| 2 | Update `EXEC_TO_PROGRAM` — fill all `None` entries | All 15 entries have valid mappings |
| 3 | Re-run `ingest_cross_language_bridges.py --dry-run` | Preview: 12+ new EXECUTES edges projected |
| 4 | Re-run live | EXECUTES: 3 → 15+ (5x improvement) |
| 5 | Validate cross-language chain query | J-Job → ex-script → FortranProgram (external) chains visible |

#### Validation

```cypher
-- Placeholder nodes exist and are labeled
MATCH (p:FortranProgram {external: true}) RETURN p.name, p.package;
-- Expected: 11 rows (GSI: 5, UFS_UTILS: 4, Fit2Obs: 2)

-- EXECUTES edges improved
MATCH ()-[r:EXECUTES]->() RETURN count(r) AS total_executes;
-- Expected: 15+ (was 3)

-- Full chain now traversable for external programs
MATCH (s:ShellScript)-[:EXECUTES]->(p:FortranProgram {external: true})
RETURN s.name, p.name, p.package LIMIT 10;
-- Expected: exgfs_forecast.sh → chgres_cube (UFS_UTILS), etc.
```

**MCP Tool Validation**:
```
1. find_callers_callees({ function_name: "chgres_cube" })
   → Should show shell scripts that execute it

2. get_code_context({ symbol: "enkf_chgres_recenter" })
   → Should return GGSR neighborhood (even for placeholders)

3. trace_execution_path({ function_name: "exgfs_atmos_chgres_forenkf.sh" })
   → Should show chgres_cube as downstream executable
```

#### Files Modified

| File | Change |
|------|--------|
| `mcp_server_node/scripts/ingest_cross_language_bridges.py` | Add placeholder node creation, fill `EXEC_TO_PROGRAM` |
| (Optional) New: `mcp_server_node/scripts/ingest_external_programs.py` | Standalone placeholder creator if kept separate |

#### Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Placeholder names don't match actual PROGRAM names | Low | Binary names used directly; actual matching only matters when full ingestion happens |
| Duplicate nodes if full GSI ingestion happens later | Low | Use MERGE, not CREATE; `external: true` flag distinguishes placeholders |
| Fit2Obs not in submodules | Low | Placeholder is sufficient; full ingestion deferred until Fit2Obs is added |

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-02-04 | 0.1.0 | Initial SDD creation from tool effectiveness audit |
| 2026-02-19 | 0.2.0 | 27F-G executed: shell graph ingested (383 nodes, 9155 rels), bridges re-run (8 edges) |
| 2026-02-19 | 0.3.0 | 27H-I specs added: multi-collection routing + external Fortran bridge resolution |
