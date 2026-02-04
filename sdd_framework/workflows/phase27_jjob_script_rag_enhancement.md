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
| 27F | 🔲 NOT STARTED | Full RAG re-ingestion |
| 27G | 🔲 NOT STARTED | Validation and testing |

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

### Phase 27F: Full RAG Re-Ingestion

**Prerequisite**: Phases 27A-27E complete and tested.

**Ingestion Order**:
1. **Neo4j shell script graph** (27B) - Run first for relationship data
2. **J-Job ChromaDB collection** (27C) - New `jjobs-v7-0-0` collection
3. **Config files collection** - New `config-files-v7-0-0` collection
4. **Cross-reference enrichment** - Add Neo4j relationships to ChromaDB metadata

**Ingestion Script**: `mcp_server_node/scripts/full_rag_reingestion_v27.sh`

```bash
#!/bin/bash
set -e

echo "[Phase 27F] Full RAG Re-Ingestion"
echo "================================="

# 1. Neo4j shell script ingestion
echo "[1/4] Ingesting shell scripts to Neo4j..."
node scripts/ingest_shell_scripts_to_neo4j.js \
  --source /app/supported_repos/global-workflow/dev/jobs \
  --source /app/supported_repos/global-workflow/dev/scripts \
  --source /app/supported_repos/global-workflow/ush \
  --clear-existing

# 2. J-Job ChromaDB collection
echo "[2/4] Ingesting J-Jobs to ChromaDB..."
python3 scripts/ingest_jjobs_to_chromadb.py \
  --collection jjobs-v7-0-0 \
  --source /app/supported_repos/global-workflow/dev/jobs \
  --metadata-enriched

# 3. Config files collection
echo "[3/4] Ingesting config files to ChromaDB..."
python3 scripts/ingest_configs_to_chromadb.py \
  --collection config-files-v7-0-0 \
  --source /app/supported_repos/global-workflow/dev/parm/config

# 4. Cross-reference enrichment
echo "[4/4] Enriching ChromaDB with Neo4j relationships..."
node scripts/enrich_chromadb_with_neo4j.js \
  --collection jjobs-v7-0-0 \
  --add-callers --add-callees --add-dependencies

echo "[OK] Full RAG re-ingestion complete"
echo "Collections updated:"
echo "  - jjobs-v7-0-0: $(curl -s localhost:8080/api/v2/collections/jjobs-v7-0-0 | jq .count) documents"
echo "  - config-files-v7-0-0: $(curl -s localhost:8080/api/v2/collections/config-files-v7-0-0 | jq .count) documents"
```

---

### Phase 27G: Validation and Testing

**Test Suite**: `mcp_server_node/tests/phase27_jjob_rag.test.js`

**Test Cases**:

```javascript
describe('Phase 27: J-Job RAG Enhancement', () => {
  
  describe('27A: Path Resolution', () => {
    it('describe_component finds J-Job in dev/jobs/', async () => {
      const result = await tools.describe_component({ component: 'JGDAS_FIT2OBS' });
      expect(result).toContain('excfs_gdas_vrfyfits.sh');
    });
    
    it('describe_component finds config in dev/parm/config/', async () => {
      const result = await tools.describe_component({ component: 'config.fit2obs' });
      expect(result).toContain('VBACKUP_FITS');
    });
  });
  
  describe('27B: Neo4j Shell Script Graph', () => {
    it('find_callers_callees returns shell script relationships', async () => {
      const result = await tools.find_callers_callees({ function_name: 'JGDAS_FIT2OBS' });
      expect(result.callees).toContain('excfs_gdas_vrfyfits.sh');
      expect(result.sources).toContain('jjob_header.sh');
    });
  });
  
  describe('27C: ChromaDB J-Job Collection', () => {
    it('search_documentation finds J-Job content', async () => {
      const result = await tools.search_documentation({ 
        query: 'JGDAS_FIT2OBS fit to observations verification' 
      });
      expect(result.some(r => r.name === 'JGDAS_FIT2OBS')).toBe(true);
    });
    
    it('J-Job metadata includes structured fields', async () => {
      const result = await chromadb.get('jjobs-v7-0-0', { ids: ['JGDAS_FIT2OBS'] });
      expect(result.metadatas[0]).toHaveProperty('inputs');
      expect(result.metadatas[0]).toHaveProperty('outputs');
      expect(result.metadatas[0]).toHaveProperty('calls');
    });
  });
  
  describe('27D: list_job_scripts Search Filter', () => {
    it('filters jobs by search term', async () => {
      const result = await tools.list_job_scripts({ search: 'fit2obs' });
      expect(result.jobs.length).toBe(1);
      expect(result.jobs[0].name).toBe('JGDAS_FIT2OBS');
    });
  });
  
  describe('27E: get_job_details Tool', () => {
    it('returns comprehensive job information', async () => {
      const result = await tools.get_job_details({ job_name: 'JGDAS_FIT2OBS' });
      
      expect(result.name).toBe('JGDAS_FIT2OBS');
      expect(result.category).toBe('verification');
      expect(result.inputs).toHaveLength(3);
      expect(result.outputs).toHaveLength(2);
      expect(result.invokes).toContainEqual(
        expect.objectContaining({ script: 'excfs_gdas_vrfyfits.sh' })
      );
    });
  });
});
```

**End-to-End Validation Checklist**:

- [ ] `describe_component JGDAS_FIT2OBS` returns script content
- [ ] `explain_workflow_component JGDAS_FIT2OBS` returns meaningful explanation
- [ ] `search_documentation "fit2obs verification"` returns JGDAS_FIT2OBS
- [ ] `find_callers_callees JGDAS_FIT2OBS` shows excfs_gdas_vrfyfits.sh
- [ ] `list_job_scripts search=fit2obs` returns 1 result
- [ ] `get_job_details JGDAS_FIT2OBS` returns structured metadata
- [ ] All 89 J-Jobs indexed in ChromaDB
- [ ] Neo4j has SOURCES/INVOKES relationships for shell scripts

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

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-02-04 | 0.1.0 | Initial SDD creation from tool effectiveness audit |
