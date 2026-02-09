# MCP Server Changelog

## [7.4.0] - Phase 24 Gap 1+2: EnvironmentVariable Graph & Graph-to-Vector Enrichment (February 9, 2026)

### Added
- **EnvironmentVariable node schema in Neo4j** (Gap 1 - Phase 24):
  - New `(:EnvironmentVariable)` label with properties: `name`, `is_ee2_standard`, `is_home_model`, `first_seen_in`
  - New relationship types: `(:CodeFile)-[:EXPORTS]->(:EnvironmentVariable)`, `(:CodeFile)-[:SETS]->(:EnvironmentVariable)`, `(:CodeFile)-[:DEPENDS_ON_ENV]->(:EnvironmentVariable)`
  - 2,730 EnvironmentVariable nodes created from 218 shell scripts
  - 9,077 total relationships (1,669 EXPORTS + 1,401 SETS + 6,007 DEPENDS_ON_ENV)
  - 18 EE2 standard variables tagged (DATA, RUN, PDY, DATAROOT, KEEPDATA, etc.)
  - 2 HOMEmodel variables tagged (HOMEgfs, HOMEobsproc)

- **`ingest_env_variables.py`** ingestion script (`mcp_server_node/scripts/`):
  - Parses `export VAR=value`, `VAR=value`, `${VAR}`, `$VAR` patterns from shell scripts
  - Mixed-case variable support (HOMEgfs, cyc, envir, pgm, etc.)
  - EE2 standard variable tagging per NCO standards Table 1
  - HOMEmodel pattern recognition (`^HOME[a-z]+$`)
  - Modes: `--dry-run`, `--test FILE`, `--sample`, `--var NAME`, `--stats`
  - Scans: jobs, dev/jobs, ush, scripts, parm/config, env, ecf directories

- **Graph-to-Vector enrichment** (`enrichGraphResults()`) in `UnifiedDataAccess.js` (Gap 2):
  - Reverse hybrid query: takes Neo4j graph node names → fetches ChromaDB content
  - Parallel ChromaDB queries with configurable batch size (`maxIdentifiers`)
  - Non-fatal: returns empty map if vector DB unavailable
  - Wired into `find_env_dependencies` tool for semantic context section

### Fixed
- **`find_env_dependencies` MCP tool returned 0 results** (Critical):
  - **Root cause**: Cypher queries used `(:ShellScript)` label which never existed in Neo4j. Shell scripts are `(:CodeFile {language: 'shell'})`
  - **Fix**: Updated all Cypher in `CodeAnalysisTools.js` and `GraphDatabase.js`: `ShellScript` → `CodeFile`, property `type` → `script_type`
  - **Result**: `HOMEgfs` now returns 109 dependents, 2 exporters, with `HOMEmodel` classification

- **`trace_execution_path` shell fallback query** also used `ShellScript` → fixed to `CodeFile`

- **`getScriptGraphStats()` in `GraphDatabase.js`**: Updated all 4 queries from `ShellScript` to `CodeFile` with correct property names

### Changed
- **`CodeAnalysisTools.js`**: `findEnvDependencies()` now includes EE2 metadata (classification, first_seen_in) in summary output
- **`GraphDatabase.js`**: `findScriptEnvDeps()` updated to include `SETS` relationship type and `is_ee2_standard` property

## [7.3.12] - ChromaDB Persistent Volume Mount Fix (February 9, 2026)

### Fixed
- **ChromaDB Docker bind mount race condition** (Critical - 0 collections visible):
  - **Problem**: ChromaDB container started at boot (13:43:13) before persistent disk `/dev/nvme2n1` was mounted at `/mcp_rag_eib` (13:43:18), 5-second race
  - **Root Cause**: `chromadb-persistent.service` depended on `docker.service` but NOT on `mcp_rag_eib.mount`. Docker evaluated `-v /mcp_rag_eib/data/chromadb:/data:Z` against the empty ephemeral root filesystem (`/dev/nvme0n1p4`), creating a fresh 168KB SQLite DB instead of binding to the 478MB persistent one
  - **Evidence**: Container `/data` on `/dev/nvme0n1p4` (249G ephemeral), host data on `/dev/nvme2n1` (516G persistent). Inodes confirmed different files
  - **Fix**: Added `mcp_rag_eib.mount` to `After=` and `Requires=` in systemd unit
  - **Result**: All 4 collections restored (code-with-context-v8, jjobs-v8, global-workflow-docs-v8, ee2-standards-v5-enhanced)

- **Docker compose ChromaDB mount path mismatch** (3 files):
  - **Problem**: devops, staging, and production compose files mounted to `/chroma/chroma` (old ChromaDB path). Current `chromadb/chroma:latest` uses `/data` as persist directory
  - **Fix**: Updated volume destination from `/chroma/chroma` to `/data` in all compose files. Added `IS_PERSISTENT=TRUE` and `PERSIST_DIRECTORY=/data` environment variables
  - **Note**: This is the same issue documented in v3.5.1 (Nov 30, 2025) but the compose files were never updated to match

### Changed
- **`SETUP/chromadb-docker.service`**:
  - Added `After=mcp_rag_eib.mount` and `Requires=mcp_rag_eib.mount` to `[Unit]`
  - Ensures persistent disk is mounted before container starts
  - Installed to `/etc/systemd/system/chromadb-persistent.service`

- **`docker-compose.devops.yaml`**: ChromaDB volume `/chroma/chroma` → `/data`, added persistence env vars
- **`docker-compose.staging.yaml`**: ChromaDB volume `/chroma/chroma` → `/data`, added persistence env vars
- **`docker-compose.production.yaml`**: ChromaDB volume `/chroma/chroma` → `/data`, added persistence env vars
- **`SETUP/docker-compose.yml`**: Updated commented-out ChromaDB section with correct mount path and env vars

### Lessons Learned
- VM boot ordering: systemd services depending on cloud-attached disks MUST have explicit mount unit dependencies
- `docker inspect` can show a bind mount configuration that appears correct but is bound to the wrong filesystem if the mount point changed after container start
- n8n and Neo4j also failed to start for the same reason (logged `"no such file or directory"` at 13:43:13)

---

## [7.3.11] - Phase 24F-0: Python Graph Ingestion (February 7, 2026)

### Added
- **`ingest_python_graph.py`** - Full Python AST → Neo4j graph ingestion pipeline (Phase 24F-0)
  - Inline Python AST parser (mirrors `parse-python-ast.py`, no subprocess overhead)
  - Creates PythonModule (362), PythonClass (220), PythonFunction (2376) nodes
  - Creates DEFINES (2596), IMPORTS (3170), CALLS, INHERITS (139) relationships
  - Shell→Python INVOKES bridge (auto-creates when ShellScript nodes present)
  - CLI modes: `--test`, `--sample`, `--dry-run`, `--skip-bridge`
  - 100% parse success rate across 362 Python files
  - Phase 24F-0 targets met: 362/200 modules, 220/150 classes, 3170/3000 imports

### Changed
- **Neo4j graph** - Now includes Python layer alongside Fortran/Shell:
  - Total nodes: 37,283 (was ~20,500 pre-Python)
  - Total relationships: 475,817 (was ~369,000 pre-Python)
  - Top inherited classes: Task (23 subclasses), Analysis (24), ObsBuilder (12)

## [7.3.10] - Neo4j Provisioning Consolidation (February 6, 2026)

### Fixed
- **Neo4j container configuration** - Consolidated two conflicting Neo4j containers into single compose-managed instance
  - Root cause: Standalone `neo4j` container (created Feb 5 for Phase 10 ingestion) diverged from compose-managed `global-workflow-neo4j`
  - Standalone held all Phase 10 Fortran data (1.4 GB); compose container had stale 13 MB database
  - Compose container crashed on start (exit code 3) due to `graph-data-science` plugin incompatibility with Neo4j 5.26.20

### Changed
- **`SETUP/docker-compose.yml`**:
  - Image: `neo4j:5.15.0` → `neo4j:5-community` (tracks latest 5.x community)
  - Container name: `global-workflow-neo4j` → `neo4j` (matches standalone convention)
  - Plugins: Removed `graph-data-science` (GDS 2.6.9 incompatible with Neo4j 5.26.20 community)
  - Memory: Adjusted heap from 1G–4G to 512m–1G (matching working config)
  - Volume: Changed `neo4j-data` from bind mount to external Docker volume `neo4j_data` (preserves Phase 10 data)

- **`SETUP/provisioning/08-services.sh`**:
  - Ensures external Docker volume `neo4j_data` exists before compose up
  - Removes stale `global-workflow-neo4j` containers that conflict with new `neo4j` name
  - Removed `data/` from directory creation (data lives in Docker volume, not bind mount)

### Removed
- **`graph-data-science.jar`** from `/mcp_rag_eib/data/neo4j/plugins/` — 60 MB incompatible JAR was preventing Neo4j startup even after removing from compose env
- Stale containers: `global-workflow-neo4j` (old compose), `neo4j` (standalone) — replaced by single compose-managed `neo4j`

### Verified
- All Phase 10 Fortran graph data intact: 20,496 nodes, 369,013 relationships
- Neo4j healthy via compose: `docker compose up -d neo4j` from SETUP/

---

## [7.3.9] - Phase 10 M6: Validation Complete (February 5, 2026)

### Validated
**All Phase 10 milestones complete** - Fortran call tree ingestion verified against success criteria:

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| Fortran nodes | >8,000 | **17,575** | ✅ 2.2x |
| CALLS relationships | >15,000 | **268,666** | ✅ 17.9x |
| USES relationships | >5,000 | **91,285** | ✅ 18.3x |
| Shell→Fortran links | >50 | **35** | ⚠️ 70% |
| Query response time | <500ms | **39ms** | ✅ 12.8x faster |

### Verified Queries
- **Fortran call tracing**: `find_callers_callees({function_name: "enkf_main"})` → 100 callees, 17 module dependencies
- **Cross-language path**: J-job → Shell → Fortran → Subroutine working
- **Full trace example**: `JGLOBAL_ATMOS_ANALYSIS_CALC → exglobal_atmos_analysis_calc.sh → enkf_main → mpi_cleanup`

### Fixed
- Cross-language path display in `trace_execution_path` - corrected field mapping from `traceCrossLanguagePath()` results

---

## [7.3.8] - Phase 10 M5: MCP Tool Integration for Fortran Graph (February 5, 2026)

### Added
- **6 Fortran query methods in `GraphDatabase.js`**:
  - `findFortranCallers(name)` - Find what calls a Fortran subroutine
  - `traceFortranCallChain(name, depth)` - Trace CALLS relationships
  - `findFortranModuleUses(name)` - Find USES module dependencies
  - `traceCrossLanguagePath(script, depth)` - Shell→EXECUTES→Fortran→CALLS
  - `getFortranGraphStats()` - Node/relationship statistics

### Changed
- **`find_callers_callees` tool** now supports three graph types:
  - Python functions (existing)
  - Fortran subroutines/functions (new)
  - Shell scripts (existing)
  - Auto-detects entity type and displays type-specific formatting

- **`trace_execution_path` tool** enhanced:
  - Detects Fortran entities and traces CALLS relationships
  - Cross-language path tracing: Shell→EXECUTES→Fortran→CALLS
  - Shows module USES dependencies for Fortran entities

### Example Query
```javascript
// Query Fortran callers
find_callers_callees({ function_name: "gsi" })
// Returns: FortranSubroutines that call gsi with [type] annotations

// Cross-language trace
trace_execution_path({ function_name: "exglobal_fcst_gefs.sh" })
// Returns: Shell chain + EXECUTES→Fortran→CALLS paths
```

---

## [7.3.7] - Phase 24: GraphRAG Architecture Consolidation (February 5, 2026)

### Added
- **Consolidated Phase 24 Architecture** (`phase24_consolidated_architecture.md`)
  - Reconciles three supplement documents into coherent roadmap
  - Defines sub-phases 24A through 24J
  - Updated Neo4j statistics: 368K relationships (post-Phase 10)

- **Phase 24F: Cross-Language Integration** (new sub-phase)
  - Leverages Phase 10 Fortran graph for GGSR
  - Shell→Fortran EXECUTES relationship traversal
  - End-to-end trace: J-Job → Shell → Fortran → Subroutine

- **Phase 24G: Benchmark & Validation** (new sub-phase)
  - Defines success criteria before agentic tool deployment
  - 50-query test corpus across local/global/trace categories
  - Go/no-go gate for Phase 24H

### Changed
- Renamed Phase 24 files for consistency:
  - `Phase24E _HierarchicalCommunit.md` → `phase24e_hierarchical_communities.md`
  - `phase24h_supplement_graphRAG.md` → `phase24h_agentic_tool_surface.md`

### Architecture Overview
```
Phase 24: True GraphRAG Fusion (Q2-Q4 2026)
├── 24A-D: GGSR Foundation (Q2)
├── 24E: Community Summarization (Q2-Q3)
├── 24F: Cross-Language Integration (Q2-Q3) [NEW]
├── 24G: Benchmark Validation (Q3) [NEW]
├── 24H: Agentic Tool Surface (Q3)
├── 24I: Learned Graph Embeddings (Q4)
└── 24J: Subgraph Retrieval (Q4)
```

---

## [7.3.6] - Phase 10 M4: Shell-Fortran EXECUTES Bridge (February 5, 2026)

### Added
- **`create_shell_fortran_bridge.py`** - Cross-language execution tracing
  - Parses shell scripts for `$EXEC*/name.x` patterns
  - 5 matching strategies for executable→program mapping
  - Creates EXECUTES relationships between ShellScript and FortranProgram nodes

### Results
| Metric | Value |
|--------|-------|
| Shell files scanned | 104 |
| Unique executables | 23 |
| EXECUTES relationships | 35 |

### Verified Query
```cypher
(ShellScript)-[:EXECUTES]->(FortranProgram)-[:CALLS]->(FortranSubroutine)
```

---

## [7.3.5] - Phase 10 M3: Full Fortran Ingestion (February 5, 2026)

### Completed
- **Full Fortran call graph ingested to Neo4j** from 7,214 files (85% parse rate)

### Results (Exceeded All Projections)
| Entity | Projected | Actual | Factor |
|--------|-----------|--------|--------|
| FortranModule | 500+ | **1,539** | 3.0x |
| FortranSubroutine | 5,000+ | **13,537** | 2.7x |
| FortranFunction | 3,000+ | **2,355** | 0.8x |
| FortranProgram | ~100 | **144** | 1.4x |
| CALLS relationships | 20,000+ | **268,666** | 13.4x |
| USES relationships | 10,000+ | **91,285** | 9.1x |

### Total Graph
- **Nodes**: 20,496
- **Relationships**: 368,978

---

## [7.3.4] - Phase 10 Milestone 2: Fortran Prototype Parser (February 5, 2026)

### Added
- **`ingest_fortran_graph.py`** - Complete Fortran ingestion script
  - Uses fparser2 with FortranFileReader (key M1 discovery)
  - Extracts: Modules, Subroutines, Functions, Programs
  - Extracts: CALL statements, USE statements
  - Neo4j integration with dry-run mode
  - CLI: `--test FILE`, `--sample`, `--dry-run`

### Validated (100-file sample)
- **Parse success rate**: 84%
- **Entities extracted**: 48 modules, 319 subroutines, 122 functions
- **Relationships**: 1,905 CALLS, 697 USES

### Projected (7,214 files)
- **CALLS**: ~139,000 relationships
- **USES**: ~51,000 relationships

---

## [7.3.3] - Phase 10 Milestone 1: fparser Integration (February 5, 2026)

### Added
- **py-fparser@0.2.0** installed via Spack for Fortran AST parsing
- **Spack requirements documentation** (`SETUP/provisioning/spack-packages.md`)
  - Documents all required Spack packages with install commands
  - Documents pip-only packages (chromadb, sentence-transformers, etc.)
  - Verification commands included

### Changed
- **`SETUP/mcp-env.sh`**: Added `module load py-fparser` to runtime environment
- **`SETUP/bash_profile_template`**: Added `py-fparser` to module loads

### Validated
- **fparser2 parse rate**: 85% success on 100-file Global Workflow sample
- **Key discovery**: Must use `FortranFileReader` (not raw strings)
- **Projected extraction**: ~169,000 CALL relationships, ~40,000 USE relationships

---

## [7.3.2] - Phase 10 SDD: Fortran Call Tree Ingestion Plan (February 5, 2026)

### Added
- **Updated Phase 10 SDD** (`phase10_fortran_call_tree_ingestion.md`)
  - Status changed from BACKLOG to IN PROGRESS
  - Selected fparser2 as the Fortran parsing tool (pure Python, F2008 support)
  - Added 6 implementation milestones with time estimates (12 hours total)
  - Defined Neo4j schema for Fortran nodes:
    - FortranModule, FortranSubroutine, FortranFunction, FortranProgram
  - Defined relationships: CALLS, USES, CONTAINS, EXECUTES (shell→Fortran bridge)
  - Added quantitative success criteria with validation queries
  - Added Quick Start Execution Checklist

### Planned Capability
Once implemented, enables full execution tracing:
```
J-Job → Shell Script → Fortran Program → Subroutine Call Tree
```

Example query:
```cypher
MATCH path = (j:ShellScript {name: 'JGLOBAL_FORECAST'})-[:SOURCES|INVOKES*1..3]->
              ()-[:EXECUTES]->(p:FortranProgram)-[:CALLS*1..5]->(f:FortranSubroutine)
RETURN path
```

---

## [7.3.1] - New find_env_dependencies MCP Tool (February 5, 2026)

### Added
- **`find_env_dependencies` MCP tool** - Query Neo4j for environment variable usage
  - Find all scripts that depend on a specific variable (e.g., `HOMEgfs`, `DATAROOT`)
  - Find all scripts that export a variable
  - Groups results by script type (j-job, ex-script, ush-script)
  - Shows impact level (HIGH/MEDIUM/LOW based on dependency count)
  - Uses Neo4j DEPENDS_ON_ENV and EXPORTS relationships from Phase 27B

### Changed
- Code Analysis Tools: Updated count from 4 to 5 tools

### Usage
```
find_env_dependencies variable_name:"HOMEgfs"
find_env_dependencies variable_name:"DATAROOT" show_exports:true
```

---

## [7.3.0] - Phase 27B: Shell Script Neo4j Graph (February 5, 2026)

### Added
- **Full shell script call tree in Neo4j**
  - New `ingest_shell_graph_v8.py` script for shell script graph ingestion
  - Created 384 ShellScript nodes (89 J-Jobs, 131 ex-scripts, USH scripts)
  - Created 2,473 EnvironmentVariable nodes
  - Created 9,027 relationships:
    - SOURCES (244): script sourcing relationships (`source`, `.`)
    - INVOKES (345): script execution relationships (`${HOMEgfs}/scripts/`)
    - EXPORTS (1,182): environment variable exports
    - DEPENDS_ON_ENV (7,192): environment variable dependencies
    - DEFINES (63): shell function definitions
    - READS_CONFIG (1): config file reads

- **Enhanced `find_callers_callees` MCP tool**
  - Now queries both Function graph (Python/Fortran) AND ShellScript graph
  - Automatically detects script type and shows appropriate relationships
  - Shows environment variable exports/dependencies for shell scripts
  - Works with J-Job names (e.g., `JGFS_ATMOS_ANALYSIS`)

- **Enhanced `get_knowledge_base_status` MCP tool**
  - Added Phase 27B Shell Script Graph section
  - Shows script type breakdown (J-Jobs, Ex-Scripts, USH)
  - Shows relationship type breakdown
  - Updated health check: graph healthy if relationships > 0 (not just File nodes)

- **New GraphDatabase methods**
  - `findScriptCallers()`: Find scripts that source/invoke a script
  - `traceScriptChain()`: Trace call chain through shell scripts
  - `findScriptEnvDeps()`: Find environment variables a script depends on
  - `getScriptGraphStats()`: Get shell script graph statistics

### Fixed
- **Neo4j password hardcoding**: Changed default from `gfsworkflow2025` to `password`
  - Matches container `NEO4J_AUTH=neo4j/password` setting
  - Fixed in `GraphDatabase.js`

### Tech Notes
- Shell script parser extracts: source statements, script invocations, exports, env deps
- Script type detection: j-job, ex-script, ush-script based on path
- Category detection: forecast, analysis, verification, etc. based on name patterns

---

## [7.2.0] - Phase 27E: Unified MPNet Embeddings (February 4, 2026)

### Added
- **Unified MPNet embeddings (768-dim) across Python and Node.js**
  - New `src/utils/embeddings.js` module using `@xenova/transformers`
  - Consistent `all-mpnet-base-v2` model for best semantic search quality
  - `embed()`, `embedBatch()`, `queryWithEmbeddings()` functions
  - Pre-computed embeddings for queries (avoids dimension mismatch)

- **Enhanced `get_job_details` tool with embedding-based search**
  - Semantic search fallback when exact match not found
  - MPNet embeddings for ChromaDB queries
  - Returns category, system, and relevance scores

### Changed
- **OperationalTools.js v2.1.0**: Now uses MPNet embeddings module
- **ingest_jjobs_v8.py**: Re-ingested with 768-dim MPNet embeddings
- **jjobs-v8-0-0 collection**: 700 documents with MPNet embeddings

### Deleted
- 9 old ChromaDB collections (v4, v5, v6 versions) - cleaned up ~10K stale documents
- Kept: `global-workflow-docs-v7-0-0`, `code-with-context-v7-0-0`, `ee2-standards-v5-0-0-enhanced`, `jjobs-v8-0-0`

### Tech Notes
- Installed `@xenova/transformers` for Node.js ONNX-based inference

---

## [7.2.1] - ONNX Segfault Fixed (February 4, 2026)

### Fixed
- **ONNX Runtime segfault on process exit - ROOT CAUSE IDENTIFIED AND FIXED**
  - **Cause**: Conflicting `onnxruntime-node` versions in dependency tree
    - `@xenova/transformers@2.17.2` → `onnxruntime-node@1.14.0`
    - `@chroma-core/default-embed@0.1.9` → `@huggingface/transformers@3.8.1` → `onnxruntime-node@1.21.0`
  - Two incompatible native binaries loaded = segfault during cleanup
  - **Fix**: Removed unused `@chroma-core/default-embed` from package.json
  - Package count reduced: 448 → 237 dependencies
  - Single ONNX version now: `onnxruntime-node@1.14.0`
  - Exit code now 0 (was 139/SIGSEGV)

### Changed
- **package.json**: Removed `@chroma-core/default-embed` dependency (never imported)
- **embeddings.js**: Removed unnecessary 50ms delay workaround

---

## [7.1.10] - Phase 27C: J-Job ChromaDB Ingestion (February 4, 2026)

### Added
- **Phase 27C: J-Job ChromaDB ingestion with structured metadata**
  - New `ingest_jjobs_v8.py` script for J-Job semantic search
  - New ChromaDB collection `jjobs-v8-0-0` with 700 documents from 89 J-Jobs
  - Structured metadata extraction:
    - `job_name` from `jjob_header.sh -e` parameter
    - `category`/`subcategory`/`system` classification (gdas/gfs/gefs/global)
    - `config_files` from `jjob_header.sh -c` parameter
    - `inputs`/`outputs` from file checks and mkdir patterns
    - `environment_variables` from export statements
    - `com_templates` from declare_from_tmpl patterns
  - Semantic chunking: full document + section-based chunks
  - Query test: "fit2obs verification" → Returns JGDAS_FIT2OBS (correct)
  - File created: `mcp_server_node/scripts/ingest_jjobs_v8.py`

### Validated
- `jjobs-v8-0-0` collection created with 700 documents
- Query "fit2obs verification" correctly returns JGDAS_FIT2OBS job
- All 89 J-Jobs ingested (0 errors)
- Metadata extraction stats: 22 inputs, 86 outputs, 225 env vars

### SDD Reference
- Phase 27C: J-Job ChromaDB Ingestion (✅ COMPLETE)
- Progress: 27A, 27B, 27C, 27D complete; 27E, 27F, 27G pending

---

## [7.1.9] - Phase 27: J-Job RAG Enhancement (February 4, 2026)

### Added
- **Phase 27A: Path resolution fix for `dev/` directory structure**
  - `describe_component` now searches `dev/jobs/`, `dev/scripts/`, `dev/parm/config/gfs/`, `dev/parm/config/gcafs/`, `dev/job_cards/`
  - Resolves issue where J-Jobs couldn't be found after global-workflow repository restructuring
  - File modified: `mcp_server_node/src/tools/WorkflowInfoTools.js`

- **Phase 27D: Search filter for `list_job_scripts` tool**
  - New `search` parameter to filter job scripts by name substring
  - New `verification` category for validation/stats jobs (fit2obs, verf, cyclone, stat)
  - File modified: `mcp_server_node/src/tools/OperationalTools.js`

- **Enhanced `mcp_health_check` with functional validation tests**
  - New `functional: true` parameter runs 5 effectiveness tests:
    1. Path Resolution - Can `describe_component` find J-Jobs in `dev/jobs/`?
    2. Search Filter - Does `list_job_scripts` filter by search term?
    3. Search Relevance - Does `search_documentation` return relevant results?
    4. Graph Relationships - Does Neo4j have code relationships?
    5. J-Job Content - Are J-Jobs indexed in ChromaDB?
  - Reports PASS/PARTIAL/FAIL with specific remediation guidance
  - File modified: `mcp_server_node/src/UnifiedMCPServer.js`

- **Phase 27B: Enhanced Neo4j Shell Script Ingestion (v8 preparation)**
  - CodeStructureIngester now discovers J-Jobs in `dev/jobs/` (89 files, no extension)
  - CodeStructureIngester now discovers ex-scripts in `dev/scripts/` (41 `.sh` files)
  - J-Job parser captures: task name, config files, ex-script executions
  - New `JJob` label for Neo4j File nodes with J-Job metadata
  - New `EXECUTES` relationship: J-Job → ex-script
  - Enhanced shell parser patterns:
    - `jjob_header.sh -e "<task>" -c "<configs>"` extraction
    - `${SCRIPTS*}/*.sh` ex-script execution detection
  - Files modified: `CodeStructureIngester.js`, `GraphSchema.js`

### Changed
- Health checks now distinguish between **infrastructure health** (connectivity, counts) and **tool effectiveness** (actual query results)
- Previous health checks could report "HEALTHY" when tools were ineffective for real queries

### Validated
- `describe_component JGDAS_FIT2OBS` → Found at `dev/jobs/`, returned 2928 bytes content
- `list_job_scripts({ search: 'fit2obs' })` → Returns 1 result (filtered from 89 total)
- `list_job_scripts({ category: 'verification' })` → Returns 9 verification jobs

### SDD Reference
- Phase 27: J-Job and Script RAG Enhancement (`sdd_framework/workflows/phase27_jjob_script_rag_enhancement.md`)
- Status: Phases 27A, 27B, 27D complete; 27C, 27E, 27F, 27G pending

---

## [7.1.8] - Docker MCP Gateway Systemd Service Fix (January 27, 2026)

### Fixed
- **Systemd service GROUP error (exit code 216)** - Service now starts successfully:
  - Changed `Group=Terry.McGuinness` to `Group=pwuser` (user's actual primary group)
  - Root cause: Username does not have a matching group name on this system
  
- **Docker Desktop secrets dependency removed**:
  - Removed `--additional-catalog docker-mcp.yaml` flag
  - Removed `--enable-all-servers` flag (was causing secrets lookup)
  - Changed to explicit `--servers eib-mcp-rag` for headless Linux compatibility
  - Root cause: docker-mcp.yaml catalog requires Docker Desktop secrets store (`/.s0` socket)
  
- **xargs compatibility** - Changed `-r` to `--no-run-if-empty` for portability

### Changed
- `/etc/systemd/system/mcp-gateway.service` - Complete rewrite for headless Linux:
  - Explicit server list instead of dynamic catalog search
  - No Docker Desktop dependencies
  - Proper group configuration

### Verified Working
- Gateway: `systemctl status mcp-gateway` → `active (running)`
- Port 18888 listening
- 35 tools discovered via `docker mcp tools ls`
- VS Code can call gateway tools (`mcp_eib-mcp-gatew_*`)
- Bearer token authentication working

### Reverts Dynamic Tools Mode (v7.1.6)
This fix **reverts the dynamic tools capability** added in v7.1.6:
- The `--enable-all-servers` and `--additional-catalog docker-mcp.yaml` flags from v7.1.6 require Docker Desktop
- Third-party MCP server discovery (`mcp-find`, `mcp-add`) is **not available** on headless Linux
- Future work needed: Alternative approach for dynamic MCP server provisioning without Docker Desktop secrets
- See: Future Phase for "Headless Dynamic MCP Server Discovery"

### SDD Reference
- Phase 26: Docker MCP Gateway Systemd Service Fix (`sdd_framework/workflows/phase26_docker_mcp_gateway_systemd_fix.md`)

---

## [7.1.7] - LangFlow Removal, n8n Consolidation (January 22, 2026)

### Removed
- **LangFlow completely removed from provisioning stack**:
  - SETUP/docker-compose.yml - LangFlow service commented out with deprecation note
  - SETUP/provisioning/08-services.sh - LangFlow startup removed
  - SETUP/provisioning/01-directories.sh - langflow directory removed, n8n directory added
  - SETUP/check-mcp-status.sh - LangFlow check replaced with n8n check
  - Reason: Inherent bugs in LangFlow's workflow import functionality
  - Replacement: n8n (JSON workflow API via REST is superior)

### Changed
- Consolidated on **n8n** for workflow automation (docker-compose.devops.yaml)
- n8n advantages over LangFlow:
  - JSON workflow injection via REST API (upload workflows programmatically)
  - No import bugs (LangFlow had dict race condition, asyncio scoping issues)
  - Better MCP Gateway integration via HTTP Request nodes
  - Documented in Phase 4C ISD/USD Architecture as form factor for USD sub-agent dispatch

### SDD References
- Phase 11E: n8n replaces LangFlow (sdd_framework/PRIORITY_ROADMAP.md)
- Phase 4C: n8n as ISD orchestrator form factor (sdd_framework/workflows/phase4c_isd_usd_architecture.md)
- Phase 12: DevOps GitFlow uses docker-compose.devops.yaml (sdd_framework/workflows/phase12_devops_gitflow_containerization.md)

---

## [7.1.6] - Dynamic Tools Mode + EIB Auto-Load (January 22, 2026)

> **⚠️ REVERTED in v7.1.8** - This approach requires Docker Desktop secrets store (`/.s0` socket)
> which is unavailable on headless Linux servers. See v7.1.8 for the fix that reverts to
> explicit `--servers eib-mcp-rag` mode. Future work needed for alternative dynamic discovery.

### Fixed
- **Dynamic tools mode WITH EIB tools** - Both capabilities now work together:
  - Added `--enable-all-servers` flag to auto-load servers from `registry.yaml`
  - Removed `--servers eib-mcp-rag` flag (was disabling dynamic tools)
  - Gateway now provides `mcp-find`, `mcp-add`, `mcp-remove`, `mcp-config-set`, `mcp-exec`
  - EIB tools (35) load automatically from registry on gateway startup
  - LLM agents can discover and add additional MCP servers on-demand (e.g., arxiv-mcp-server)
  - Reference: [Dynamic_MCP_Server_Self_Provisioning wiki](https://github.com/TerrenceMcGuinness-NOAA/global-workflow/wiki/Dynamic_MCP_Server_Self_Provisioning)

### Changed
- `SETUP/provisioning/12-static-mode-gateway.sh` - Added `--enable-all-servers` flag
- `SETUP/systemd/mcp-gateway.service.template` - Updated for dynamic tools + auto-load
- Live `/etc/systemd/system/mcp-gateway.service` - Updated and restarted
- Root's `/root/.docker/mcp/registry.yaml` - Must contain `eib-mcp-rag` entry

### Tool Count
- **42 tools total** = 35 EIB tools + 7 gateway management tools
- Gateway tools: `mcp-find`, `mcp-add`, `mcp-remove`, `mcp-config-set`, `mcp-exec`, `mcp-create-profile`, `code-mode`

---

## [7.1.5] - Docker MCP Gateway Tool Discovery Fix (January 22, 2026)

### Fixed
- **Gateway tool discovery** - MCP gateway service now discovers 35 tools correctly:
  - Replaced `--static=true` with `--long-lived` flag in systemd service
  - Added full catalog path `/root/.docker/mcp/catalogs/eib-local.yaml` instead of relative path
  - Static mode failed because it expected pre-connected containers, but catalog type was `server`
  - Long-lived mode correctly spawns containers on-demand from catalog image
  
- **Container cleanup** - Fixed transient `container: unbound variable` error:
  - Cleanup script properly handles empty container lists with bash strict mode
  - Timer is working correctly (runs every 15min, 30min grace period)

- **File ownership after provisioning** - Fixed ROOT CAUSE of files owned by root:
  - **05-python-spack.sh**: `git clone spack` now runs as user (was running as root)
  - **07-mcp-server.sh**: `cp` and `npm install` now run as user (were running as root)
  - **00-users.sh**: `git clone` for user repos now runs as that user (was running as root)
  - Added `14-final-ownership.sh` as verification script (fixes only if issues found)
  - Eliminates "permission denied" errors when editing files in VS Code
  - Prevents recurring ownership issues after provisioning runs

### Changed
- Gateway mode changed from static pre-connected to on-demand spawning
- Cleanup responsibility now handled by `mcp-container-cleanup.timer` (15min interval)
- Service file: `SETUP/provisioning/12-static-mode-gateway.sh` updated
- Provisioning now runs final ownership correction as last step

---

## [7.1.4] - EE2 Compliance Tool Bug Fixes (January 15, 2026)

### Fixed
- **Variable scoping bug** in `scan_repository_compliance`:
  - `basename` variable now computed once per file at loop start
  - Previously caused "basename is not defined" errors in shebang_compliance category

- **Output filename false positive** in `file_naming` category:
  - Replaced multiline regex with line-by-line parsing to avoid capturing comments
  - Now correctly identifies uppercase in actual output filenames, not comments

- **Debug logging** added for issue tracking:
  - Per-file debug output shows issues found and category assignments
  - Post-scan summary shows issues by category before filtering

### Changed
- Increased robustness of COM/COMOUT pattern matching for output file naming

---

## [7.1.3] - EE2 Compliance Tool Enhancement (January 15, 2026)

### Added
- **`shebang_compliance` category** in `scan_repository_compliance`:
  - Validates shebang is on line 1 (no blank lines before)
  - Checks for valid shell types (bash, sh, ksh per SME corrections)
  - Verifies J-jobs have `PS4` timing export per standards.rst lines 868-919

- **`production_utilities` category** in `scan_repository_compliance`:
  - Checks for `err_chk`/`err_exit` usage instead of explicit `exit N` statements
  - Validates `set -x` debug logging presence in operational scripts
  - Checks `SENDCOM` default value pattern
  - Warns on missing `postmsg` calls in J-jobs (info severity)

- **Enhanced `file_naming` category**:
  - Ex-script prefix validation (scripts in scripts/ must start with 'ex')
  - Output filename case checking (no uppercase in resolved filenames)
  - COM/COMOUT pattern analysis

### Changed
- Tool schema now lists all 5 implemented categories with enum constraint
- Default categories expanded from 3 to 5 (error_handling, environment_variables, file_naming, shebang_compliance, production_utilities)
- Improved category documentation in tool description

### Fixed
- Categories `shebang_compliance` and `production_utilities` were listed in schema but not implemented (now fixed)

---

## [7.1.2] - Academic Citations for Forward-Looking Documents (January 15, 2026)

### Added
- **Phase 24 SDD References**: Added 16 peer-reviewed citations to `phase24_graph_guided_speculative_retrieval.md`
  - GraphRAG Foundations: LEGO-GraphRAG, AGRAG, XGraphRAG, TERAG, GraphRAG Survey
  - Token-Efficient Retrieval: CORAG, HiRAG, Plan*RAG
  - Code Knowledge Graphs: CKGFuzzer, GraphGen4Code
  - Weather/NWP AI Context: Pangu-Weather, FuXi-2.0

- **ADVANCED_FUTURE_WORK.md Section 7**: Comprehensive references section with 5 categories
  - GraphRAG and Knowledge Graph-Enhanced Retrieval (6 papers)
  - Token Budget and Cost-Constrained Retrieval (4 papers)
  - Code Knowledge Graphs (4 papers)
  - Weather Forecasting AI (5 papers)
  - Multi-Modal and Visual Understanding (2 papers)

### Changed
- Converted placeholder external references to actual arXiv citations with links
- Added table format for all citations with arXiv IDs and relevance notes

### Documentation
All citations sourced via MCP paper discovery tools (`search_papers`) using arXiv API:
- GraphRAG query: 15 results analyzed
- Token budget query: 10 results analyzed
- Code knowledge graph query: 10 results analyzed
- Weather forecasting ML query: 8 results analyzed

---

## [7.1.1] - Docker MCP Catalog Registration & Systemd Service (January 9, 2026)

### Added
- **Docker MCP Catalog Registration** (`SETUP/provisioning/11-docker-mcp-gateway.sh`):
  - `docker mcp catalog create eib-local` - Creates catalog in docker mcp system
  - `docker mcp catalog add eib-local eib-mcp-rag` - Imports server from YAML
  - `docker mcp server enable eib-mcp-rag` - Enables server for gateway discovery
  - Tool discovery verification with dry-run test
  - **Critical insight**: YAML files in `~/.docker/mcp/catalogs/` are NOT sufficient - explicit registration required

- **Systemd Service Templates** (`SETUP/systemd/`):
  - `mcp-gateway.service.template` - Streamable HTTP gateway service (SPOT)
  - `mcp-rag.service.template` - Static container service for multi-user RDHPCS
  - Variable substitution: `${USER_NAME}`, `${USER_HOME}`, `${USER_GROUP}`

- **Gateway Helper Script** (`SETUP/bin/start-mcp-gateway.sh`):
  - Commands: `start`, `stop`, `status`, `restart`, `foreground`
  - Port configuration via `--port` flag or `MCP_GATEWAY_PORT` env
  - Colorized status output with tool count verification

### Changed
- **Transport Protocol**: Changed from SSE to Streamable HTTP (`--transport streaming`)
  - SSE is server→client only (not bidirectional)
  - Streamable HTTP provides full MCP protocol support via `/mcp` endpoint
  - POST requests for tool calls, SSE responses for results

- **Gateway Port**: Changed from 8888 to 18888
  - Avoids conflicts with common services on RDHPCS systems
  - Updated in: mcp.json, provisioning scripts, systemd templates, copilot-instructions

- **Authentication Token**: Static token via `MCP_GATEWAY_AUTH_TOKEN` environment variable
  - Token: `eib-mcp-gateway-token-2025`
  - Removed dynamic token generation for predictable multi-client access

### Fixed
- **Provisioning Status File**: Added `SETUP/provisioning/.provision_status` to `.gitignore`
  - Machine-specific runtime state should not be committed

### Configuration
```bash
# Start gateway via systemd (production)
sudo systemctl start mcp-gateway

# Or via helper script
SETUP/bin/start-mcp-gateway.sh start

# Manual foreground mode (development)
export MCP_GATEWAY_AUTH_TOKEN="eib-mcp-gateway-token-2025"
docker mcp gateway run --servers eib-mcp-rag --transport streaming --port 18888 --long-lived --verbose

# Verify tools
docker mcp tools ls  # Should show 42 tools (35 EIB + 7 gateway)
```

### VS Code MCP Configuration
```json
{
  "eib-mcp-gateway": {
    "type": "http",
    "url": "http://localhost:18888/mcp",
    "headers": {
      "Authorization": "Bearer eib-mcp-gateway-token-2025"
    }
  }
}
```

### References
- Docker MCP Gateway: https://github.com/docker/mcp-gateway
- MCP Streamable HTTP: https://spec.modelcontextprotocol.io/specification/basic/transports/

---

## [7.1.0] - Phase 11E n8n Workflow Automation (December 31, 2025)

### Added
- **n8n Docker Service** (`docker-compose.devops.yaml`):
  - Image: `n8nio/n8n:latest` on port 5678
  - Container name: `global-workflow-n8n`
  - Basic auth: admin / eib-n8n-2025
  - Persistent volume: `n8n-devops-data`
  - Health check via `/healthz` endpoint

- **Provisioning Script** (`SETUP/bin/start-n8n.sh`):
  - Start/stop/status commands
  - Background mode support
  - MCP Gateway integration instructions

### Rationale
- LangFlow v1.6.9 has critical bugs in MCP client (dict race condition, asyncio scoping)
- n8n provides stable, production-ready workflow automation
- HTTP Request node connects to MCP Gateway for tool invocation

### Usage
```bash
# Start n8n
SETUP/bin/start-n8n.sh --background

# Web UI: http://localhost:5678
# Credentials: admin / eib-n8n-2025

# MCP Gateway integration via HTTP Request node:
# URL: http://host.docker.internal:8888/sse
# Auth: Bearer token from gateway startup
```

### References
- Phase 11E SDD: `sdd_framework/workflows/phase11_docker_mcp_gateway_langflow.md`
- n8n Documentation: https://docs.n8n.io/

---

## [7.0.6] - Phase 11 Container DB Connectivity Fix (December 15, 2025)

### Fixed
- **Container Environment Variables**:
  - Changed `CHROMA_SERVER_URL` to `CHROMADB_HOST` + `CHROMADB_PORT` (matches VectorDatabase.js)
  - Updated Neo4j password from `password` to `gfsworkflow2025` (matches running container)

### Validated
- **Container Testing**:
  - ChromaDB connectivity: 12 collections, 14,854 documents
  - Neo4j connectivity: 85,894 relationships, 2,730 files, 1,481 functions
  - MCP tools tested: `get_knowledge_base_status`, `search_documentation`

### Technical Details
- Container must be on `global-workflow-mcp-rag` network to reach DBs
- Gateway runs containers in isolation (security feature) - direct network needed for RAG

---

## [7.0.5] - Phase 11 Docker MCP Gateway Integration (December 15, 2025)

### Added
- **Docker MCP Gateway Support**:
  - `Dockerfile.mcp-server` - Production Dockerfile with gateway metadata labels
  - `docker-compose.mcp-standalone.yaml` - Standalone MCP stack compose file
  - `io.docker.server.metadata` label enables `docker mcp gateway` discovery
  - JSON format metadata label for reliable cross-platform parsing

- **Gateway Integration**:
  - Rebuilt `docker-mcp` plugin v0.34.0 from source (includes Docker CE fix PR #301)
  - Gateway successfully discovers 32 MCP tools from containerized server
  - Supports stdio transport for MCP protocol communication
  - Enables multi-client access via gateway (LangFlow, Claude Desktop, VS Code)

### Changed
- **Container Architecture**:
  - MCP server container uses stdio transport (no HTTP ports exposed by design)
  - Gateway acts as protocol bridge for HTTP/SSE clients
  - Container labels follow Docker MCP Gateway specification

### Technical Details
- Gateway CLI: `docker mcp gateway run --servers docker://eib-mcp-rag:latest`
- Plugin location: `~/.docker/cli-plugins/docker-mcp`
- Image: `eib-mcp-rag:latest` with 32 tools available
- Build: `docker compose -f docker-compose.mcp-standalone.yaml build`

### References
- Phase 11 SDD: `sdd_framework/workflows/phase11_docker_mcp_gateway_integration.md`
- mcp-gateway repo: `supported_repos/mcp-gateway/` (cloned for plugin build)

---

## [7.0.4] - Phase 4B Interactive Supervised Execution & Paper Updates (January 14, 2025)

### Added
- **Phase 4B SDD Workflow** - `phase4b_interactive_supervised_execution.md`:
  - Interactive Supervised Execution mode for human-in-the-loop workflow execution
  - ApprovalProvider interface with multi-CLI environment support
  - Four execution modes: dry_run, supervised (default), auto_approved, autonomous
  - Implementations: MCPApprovalProvider, CLIApprovalProvider, ManifestApprovalProvider, GitHubActionsProvider
  - Multi-turn MCP approval flow for VS Code Copilot and Claude Desktop

- **Vendor Independence Documentation**:
  - New subsection in master paper: "Vendor Independence: A Federal Imperative"
  - FAR/COTS compliance rationale for custom SDD Framework
  - Explains why Claude /plan, GitHub Copilot agents, AWS Bedrock, etc. are insufficient
  - Government control and procurement flexibility requirements

### Changed
- **Priority Roadmap Updates**:
  - Added "Bootstrap Capability (Phase 4) - ON HOLD" section
  - Phase 4B added as CRITICAL priority
  - Documented intentional pause on autonomous execution

- **Master Technical Paper Updates**:
  - Added Phase 4B Interactive Supervised Execution subsection
  - Added Phase 4B to Deployment Priority Roadmap table
  - Updated document count: 3,761 → 13,423 documents
  - Updated relationship count: 78,339 → 82,338 relationships
  - Updated tool count: 20+ → 30+ tools
  - Added note explaining Phase 4 Bootstrap ON HOLD status

### Documentation
- Paper now reflects current ChromaDB v1.1.1 state (11 collections, 13,423 documents)
- Paper now reflects current Neo4j state (82,338 relationships)
- SDD Framework status: 17 workflows defined, 0 executions (by design)

---

## [7.0.3] - Comprehensive Technical Paper & Documentation (January 14, 2025)

### Added
- **Master Technical Paper** - `MCP_RAG_Complete_System_Paper.tex`:
  - 1,300+ lines of LaTeX comprehensive system specification
  - 12 major sections covering complete MCP-RAG architecture
  - Mathematical foundations for embedding spaces (768-dimensional vectors, cosine similarity)
  - Hybrid search algorithm formalization (Algorithm 1)
  - Seven-directive semantic annotation schema with complete specification
  - Five-component architecture diagrams
  - Empirical evaluation results (3.8× retrieval improvement, 77% false positive reduction)
  - SME refinement methodology with linguistic parallels
  - Complete deployment architecture with Docker containerization roadmap
  - Future work sections including Phase 10 Fortran call tree ingestion
  - Target venues: NOAA Technical Memo, arXiv, JOSS

- **Copilot Instructions Enhancements**:
  - Glossary of Acronyms: 14 key terms (SPOT, SOC, RST, SDD, SME, EE2, etc.)
  - Model Selection Guide: Opus vs Sonnet vs Haiku with task-specific recommendations
  - Empirical Accuracy Principle documentation

- **Phase 10 SDD Workflow** - `phase10_fortran_call_tree_ingestion.md`:
  - Fortran AST extraction using fparser
  - Shell-to-Fortran call boundary detection
  - Four new planned MCP tools for Fortran navigation
  - BACKLOG status (post-Phase 5 Docker containerization)

- **Priority Roadmap** - `sdd_framework/PRIORITY_ROADMAP.md`:
  - Executive stakeholder communication document
  - Three-tier priority structure (Critical, High, Strategic)
  - Value proposition and ROI documentation
  - Risk mitigation strategies

### Papers Directory Update
- Updated `papers/README.md` to document master paper
- Established paper hierarchy with MCP_RAG_Complete_System_Paper.tex as authoritative source

---

## [7.0.2] - Complete NCO Compliance Report (January 14, 2025)

### Added
- **Complete NCO EE2 Compliance Report** for seaice-concentration repository:
  - `docs/SEAICE_CONCENTRATION_NCO_COMPLIANCE_REPORT.md`
  - Full repository traversal: 14 shell scripts analyzed
  - ~1,850 lines of code reviewed
  - Line-by-line analysis with specific line numbers
  - 8 critical, 12 major, 15 minor issues documented

### Analysis Results
- **Overall Compliance Score**: 72%
- **J-Jobs Analyzed**: JSEAICE_ANALYSIS, JSEAICE_FILTER, JSEAICE_GEMPAK, JSEAICE_VIIRS
- **Ex-Scripts Analyzed**: exseaice_analysis.sh (30KB), exseaice_filter.sh, exseaice_viirs.sh, exice_nawips.sh
- **USH Scripts Analyzed**: noice.sh, imsice.sh, ice_edge_vgf.sh

### Critical Findings
- 4 scripts use non-portable `#!/bin/ksh` or `#!/bin/bash` shebangs (WCOSS2 issue)
- Missing `err_chk` after script calls in JSEAICE_GEMPAK
- Missing `prep_step` before executables in exseaice_filter.sh
- 50+ uses of `cp` instead of `cpreq` in exseaice_analysis.sh

### MCP Annotations Applied
- Used 29 semantic annotations from v7.0.1 knowledge base
- Annotations guided: shebang validation, err_chk placement, prep_step usage
- SME corrections prevented false positives on set -eu requirements

---

## [7.0.1] - Enhanced Semantic Annotations (December 4, 2025)

### Added
- **20 New MCP Semantic Annotations** in `standards.rst`:
  - 6 AI Guidance Rules (`literal_compliance`, `context_discrimination`, `anti_pattern_enforcement`, `recognize_err_chk_gaps_not_absence`, `cite_compliant_examples_for_context`, `report_compliance_distribution`)
  - 2 SME Corrections (`bash_error_handling_requirement`, `forced_exit_prohibition`)
  - 3 Correct Patterns (`natural_return_with_err_utilities`, `err_chk_after_critical_operations`, `ee2_script_header`)
  - 2 Platform Guidance (`hera_environment`, `wcoss2_environment`)
  - 1 Context Types definition (operational_job, utility_script, test_script)
  - Environment variable validation annotations

- **In-Place Collection Update**:
  - Updated `global-workflow-docs-v7-0-0` collection without creating new version
  - Deleted 19 old standards.rst documents, added 34 new chunks
  - Total collection: 3,761 documents

- **Updated EE2 Compliance Report**:
  - `SEAICE_CONCENTRATION_EE2_COMPLIANCE_REPORT_annotation_updates.md`
  - Demonstrates SME correction usage preventing false positives
  - 3-level compliance scoring (Level 1/2/3 vs binary)
  - Compliance score improved from 78% to 82%

### Changed
- **supported_repos/nws-hpc-standards/docs/standards.rst**:
  - Annotation count: 9 → 29 (20 new annotations)
  - All SDD framework phase2_annotations translated to source document
  - Annotations embedded as RST comments (invisible to RTD, parsed by MCP)

- **sdd_framework/workflows/ee2_enhanced_embeddings_workflow.md**:
  - Updated all 4 phases to COMPLETE status
  - Added Current System State table with component status
  - Added validation proof and implementation details

### Technical Notes
- SME corrections prevent 80% false positive rate (set -eu issue)
- AI guidance rules control recommendation behavior
- SDD framework files retained for development reference
- Branch: `mcp_enhanced_embedings` in nws-hpc-standards submodule

---

## [7.0.0] - SPOT Configuration & V7 Collection (December 2025)

### Added
- **SPOT Directive (Single Point of Truth)**:
  - Established `documentation_sources_config.py` as the authoritative source for all documentation URLs
  - Added prominent SPOT directive box in header with import instructions
  - Added validation function `validate_sources()` with comprehensive checks
  - Added new helper functions: `get_sources_by_priority()`, `get_total_source_count(enabled_only)`

- **V7 Documentation Collection**:
  - New collection: `global-workflow-docs-v7-0-0` (2,280+ documents)
  - 17 documentation sources across 5 tiers
  - Incremental ingestion support via `_load_existing_ids()`

- **New Tier Organization**:
  - tier1_critical: Core workflow docs (global-workflow, ee2-standards, ufs-utils)
  - tier2_workflow: Orchestration tools (rocoto, ecflow, wxflow, pyflow)
  - tier3_models: UFS models and components (ufs-weather-model, jedi-docs, fv3-dynamical-core)
  - tier4_build: Build systems (spack-stack, spack, hpc-stack)
  - tier5_standards: Coding style guides (google-shell-style, pep8, numpy-docstrings, fortran-best-practices)

- **New Documentation Sources**:
  - `spack` - Spack package manager documentation (LLNL)
  - `fv3-dynamical-core` - FV3 cubed sphere dynamics
  - `fortran-best-practices` - Fortran-lang best practices

### Changed
- **documentation_sources_config.py** (SPOT):
  - Version: 4.2.1 → 7.0.0
  - Reorganized from 4 tiers to 5 tiers
  - Added `enabled` field for per-source control
  - Enhanced docstrings with SPOT compliance requirements
  - Collection name: `global-workflow-docs-v7-0-0`

- **ingest_documentation_v7.py**:
  - Now imports from SPOT config instead of inline `DOCUMENTATION_SOURCES`
  - Added SPOT compliance header comment box
  - Removed all inline URL configuration

- **.github/copilot-instructions.md**:
  - Added SPOT Directive section with rules and examples
  - Documents correct import pattern and anti-patterns

### Technical Notes
- SPOT ensures all ingestion scripts use the same source definitions
- Use `python3 documentation_sources_config.py` to validate and view sources
- Use `python3 list_documentation_sources.py --format detailed` for formatted output
- All URL changes MUST be made in `documentation_sources_config.py`

---

## [3.6.3] - Spack Dependency Documentation (December 2025)

### Added
- **Pip-Only Dependencies Documentation**:
  - Documented packages not available in Spack that MUST use `pip install --user`
  - `chromadb` - Vector database client (connects to Docker container)
  - `sentence-transformers` - Embedding model library (all-mpnet-base-v2)

- **STEP 6.6 in Provisioning Script**:
  - New step to install pip-only Python dependencies automatically
  - Runs `python3 -m pip install --user chromadb sentence-transformers`
  - Verifies installations before proceeding

- **Web Scraping Modules**:
  - Added `py-beautifulsoup4` and `py-lxml` to Spack module loads
  - Required for HTML parsing in documentation ingestion scripts

### Changed
- **SETUP/mcp-env.sh**:
  - Added `ml py-beautifulsoup4 py-lxml` to both `ml` and `module load` blocks
  - Added documentation section explaining pip-only packages
  - Version bumped to document pip-only dependencies

- **SETUP/provision_mcp_rag_persistent.sh**:
  - Added STEP 6.6 for pip-only Python dependencies
  - Loads Spack module dependencies before pip install
  - Verifies chromadb and sentence-transformers after installation
  - Version bumped to 3.6.3

- **.github/copilot-instructions.md**:
  - Added "PIP-ONLY PACKAGES" section to Python Package Management
  - Clear documentation of which packages require pip vs Spack

### Technical Notes
- Spack-First Policy: All dependencies should use Spack modules when available
- Only `chromadb` and `sentence-transformers` require pip --user
- All other Python dependencies (lxml, beautifulsoup4, requests, numpy, etc.) are Spack modules
- The ingestion scripts (ingest_documentation_v7.py, etc.) now have all required dependencies

---

## [3.6.2] - ONNX Runtime Conflict Fix (December 2025)

### Fixed
- **SIGSEGV Crash on Health Check** - Critical fix for segmentation fault:
  - **Root Cause**: Conflicting `onnxruntime-node` versions
    - `onnxruntime-node@1.14.0` from `@xenova/transformers@2.17.2`
    - `onnxruntime-node@1.21.0` from `@huggingface/transformers@3.8.0` (via `@chroma-core/default-embed@0.1.9`)
  - **Solution**: Removed `@chroma-core/default-embed` dependency (was never actually imported in code)
  - Server now uses single ONNX Runtime version (1.14.0)
  - Deep health checks with embedding generation now work without crashing

- **Embedding Dimension Mismatch in Health Check**:
  - Health check sample query was picking first collection alphabetically
  - Some legacy collections use 384-dim embeddings (different model)
  - Current model (all-mpnet-base-v2) produces 768-dim embeddings
  - Added preferred collection list for 768-dim collections

### Changed
- **VectorDatabase.js** - `healthCheck()` method enhanced:
  - Now prefers known 768-dimension collections for sample query
  - Collections: `global-workflow-docs-v5-0-0-consolidated`, `global-workflow-docs-v4-*`, `ee2-standards-v5-*`
  - Falls back to first available collection if none match

### Removed
- `@chroma-core/default-embed` from package.json dependencies (unused, caused ONNX conflict)

### Technical Notes
- NPM package hoisting can cause native library conflicts even if a package isn't imported
- ONNX Runtime SIGSEGV issues are often version conflicts, not CPU instruction set problems
- Comment in VectorDatabase.js already said "avoid DefaultEmbeddingFunction dependency" - package.json now aligns

---

## [3.6.1] - GitHub CLI Provisioning Support (December 2025)

### Added
- **GitHub CLI (gh) Installation** in provisioning script:
  - Added STEP 6.5 in `SETUP/provision_mcp_rag_persistent.sh`
  - Installs `gh@2.79.0` via Spack
  - Required for MCP GitHub tools to function
  - Makes `gh` command available after `module load gh`

### Changed
- `SETUP/provision_mcp_rag_persistent.sh` updated to v3.6.1

---

## [3.6.0] - EE2 Compliance Module Extraction (December 1, 2025)

### Added
- **New EE2ComplianceTools Module** (`mcp_server_node/src/tools/EE2ComplianceTools.js`):
  - Dedicated module for EE2 standards compliance validation
  - Extracted 4 tools from SemanticSearchTools for better Separation of Concerns (SOC)
  - Preserves Phase 2 semantic annotation integration
  - ~700 lines with complete implementation

### Changed
- **SemanticSearchTools.js** - Reduced from ~700 to ~384 lines:
  - Removed EE2-specific tools (now in EE2ComplianceTools)
  - Retained 4 search-focused tools:
    - `search_documentation` - Hybrid semantic + graph search
    - `find_related_files` - Dependency relationship search
    - `explain_with_context` - Multi-source RAG explanations
    - `get_knowledge_base_status` - Vector + graph DB statistics
  - Updated header with SOC documentation note (v3.0.0)

- **UnifiedMCPServer.js** - Updated to v3.6.0:
  - Added EE2ComplianceTools import and registration
  - Updated server version from 3.1.0 to 3.6.0
  - Updated getServerInfo() with accurate tool counts
  - 7 tool modules now registered (was 6)

### Tool Organization (v3.6.0)

| Module | Tools | Focus |
|--------|-------|-------|
| WorkflowInfoTools | 3 | Static workflow info |
| CodeAnalysisTools | 4 | Graph-based code analysis |
| SemanticSearchTools | 4 | Hybrid vector+graph search |
| **EE2ComplianceTools** | **4** | **EE2 compliance validation** |
| OperationalTools | 3 | HPC operational guidance |
| SDDWorkflowTools | 6 | SDD automation |
| Utility Tools | 2 | Server info, health check |

### EE2ComplianceTools (4 tools)
- `search_ee2_standards` - Search EE2 documentation and standards
- `analyze_ee2_compliance` - Analyze code/docs for EE2 compliance
- `generate_compliance_report` - Generate structured compliance reports
- `scan_repository_compliance` - Full repository EE2 scanning

### Impact
- **SOC Improvement**: Clear separation between search and compliance tools
- **Maintainability**: EE2 tools can evolve independently
- **EVS Collaboration**: Easier handoff for EVS team work (next week)
- **No Breaking Changes**: Tool names and behavior unchanged

### SDD Workflow
- Followed: `sdd_framework/workflows/ee2_compliance_module_extraction.md`
- Status: ✅ COMPLETED

---

## [3.5.2] - Empirical Health Check Validation (November 30, 2025)

### Added
- **Empirical Data Validation in Health Checks**:
  - **Problem**: Previous health check only validated heartbeat (service running), not data accessibility
  - **False Positive**: Health check reported "healthy" when ChromaDB had 0 collections accessible
  - **Solution**: Enhanced health checks with empirical validation:
    1. **Heartbeat Check**: Service is responding
    2. **Collection Count Check**: Minimum collections present (default: 1)
    3. **Document Count Check**: Minimum documents present (default: 100)
    4. **Sample Query Check**: Optional deep validation (queries work)

### Changed
- **VectorDatabase.healthCheck()** (`src/data/VectorDatabase.js`):
  - Now accepts options: `{ deep, minCollections, minDocuments }`
  - Returns detailed validation results with pass/fail for each check
  - Includes per-collection document counts
  - Reports `statusReason` explaining health status

- **UnifiedMCPServer.healthCheck()** (`src/UnifiedMCPServer.js`):
  - Integrates VectorDatabase empirical validation
  - Shows data validation table in detailed mode
  - Includes troubleshooting section for data issues
  - New `deep` parameter for thorough validation with sample queries

- **mcp_health_check Tool**:
  - New `deep` parameter for thorough validation
  - Enhanced output with data validation table
  - Specific troubleshooting guidance for common issues

### Impact
- **Before**: Health check showed "3/6 healthy" when data was inaccessible
- **After**: Health check correctly shows "degraded" or "unhealthy" with specific reasons:
  - "Only 0 collections (expected >= 1) - possible mount path issue"
  - "Only 0 documents (expected >= 100) - data may not be ingested"

### Example Output
```
Status: healthy
Reason: All validations passed

| Check | Status | Details |
|-------|--------|---------|
| Heartbeat | [OK] | ChromaDB responding |
| Collections | [OK] | 10 found (min: 1) |
| Documents | [OK] | 9637 total (min: 100) |
```

---

## [3.5.1] - ChromaDB Docker Mount Path Fix (November 30, 2025)

### Fixed
- **ChromaDB Docker Mount Path Mismatch** (Critical - Collections Not Loading):
  - **Problem**: ChromaDB container showed 0 collections via API despite SQLite containing 10 collections with 9,637 embeddings
  - **Root Cause**: Mount path `/chroma/chroma` was outdated; ChromaDB `latest` uses `/data` as default persist path
  - **Evidence**: Container logs showed `persist_path: "/data"` but volume was mounted to `/chroma/chroma`
  - **Fix**: Updated mount from `-v .../chromadb:/chroma/chroma` to `-v .../chromadb:/data:Z`
  - **Files Changed**:
    - `SETUP/chromadb-docker.service` - Fixed volume mount and persist directory
    - `SETUP/provision_mcp_rag_persistent.sh` - Same fix for fresh provisioning
  - **SELinux**: Added `:Z` flag for proper SELinux label on RHEL/Rocky systems
  - **Result**: All 10 collections now accessible via ChromaDB v2 API

### Technical Details
- ChromaDB version: latest (1.2.2+)
- Container persist path changed in newer versions: `/chroma/chroma` → `/data`
- Old config worked with older ChromaDB versions but broke after container upgrades
- This is a recurring issue - document mount path in provisioning comments

---

## [3.0.2] - Bug Fixes & Planning (November 21, 2025)

### Fixed
- **Logic Error in Compliance Scan** (`scan_repository_compliance`):
  - **Problem**: Empty environment variable rules caused early exit, skipping subsequent checks and result aggregation.
  - **Fix**: Corrected logic to ensure all categories are processed even if one has no rules.
  - **Commit**: `7a08c13`

### Added
- **SDD Plan: Configurable Report Templates**:
  - **New Workflow**: `sdd_framework/workflows/configurable_report_templates.md`
  - **Purpose**: Enable SME-driven report formatting via markdown templates.
  - **Status**: Planned Enhancement (Target v3.1.0+)
  - **Commit**: `f95a58b`

---

## [3.0.1] - Phase 2 Compliance Fix: Remove Best Practice Hallucinations (November 20, 2025)

**CRITICAL FIX**: Removed hard-coded best practice checks that were bypassing Phase 2 annotation system

### Fixed
- **Variable Quoting Hallucination** (730 files / 92% affected):
  - **Problem**: Scan tool reported "Quote variables per EE2 standard" for 730 files
  - **Reality**: NO such EE2 standard exists for bash variable quoting
  - **Evidence**: Searched EE2 standards - found NO explicit quoting requirements
  - **Root Cause**: Hard-coded regex checks in `SemanticSearchTools.js` (lines 1019-1051)
  - **Fix**: Removed all hard-coded environment variable checks
  - **Impact**: 681 false positives eliminated

- **Hardcoded Path Checks** (unknown count affected):
  - **Problem**: Flagging absolute paths without EE2 basis
  - **Reality**: Best practice recommendation, NOT an EE2 requirement
  - **Fix**: Removed hard-coded path validation

### Changed
- **Phase 2-Only Enforcement** (`SemanticSearchTools.js`):
  - Environment variable category now skipped if no Phase 2 rules exist
  - All checks must have explicit `phase2Config` entries with EE2 evidence
  - Added logging: "No Phase 2 rules - skipping category"
  - Rules without evidence chains are skipped with warnings

- **Evidence Chain Requirement**:
  - Every violation MUST cite EE2 line numbers (e.g., "standards.rst:588-595")
  - No exceptions: No evidence = No enforcement
  - Prevents future hallucinations of non-existent requirements

### Architecture Impact
- **Before**: 743/792 files (93.8%) with issues (mostly false positives)
- **After**: ~62/792 files (7.8%) with issues (genuine EE2 violations only)
- **Trust Restored**: Every violation traceable to actual EE2 standards
- **Phase 2 Integrity**: Semantic annotations now single source of truth

### Documentation
- Added `PHASE_2_COMPLIANCE_FIX_PLAN.md` - Detailed implementation plan
- Added `PHASE_2_COMPLIANCE_FIX_SUMMARY.md` - Executive summary
- Updated semantic annotation principles in copilot instructions

### Lessons Learned
- Hard-coded checks bypass Phase 2 annotations → architectural violation
- "Best practices" must NEVER be presented as "EE2 standards"
- Evidence chain validation is critical for system integrity
- SME trust depends on accurate, traceable compliance reporting

---

## [Unreleased] - Phase 2 Annotation: EE2 SME Corrections (November 19, 2025)

**Critical Fix**: Systematic false positives in EE2 compliance recommendations (affecting 60-80% of EVS scripts)

### Added
- **SME-Corrected Annotations** (`ee2_error_handling_sme_corrections.rst`):
  - Evidence-based corrections with direct quotes from EE2 standards.rst
  - Line numbers: 588-595 (set -x requirement), 868-919 (Example 8 J-job), 926-985 (Example 9 ex-script)
  - Proves EE2 requires `set -x` for debug logging, NOT `set -e` or `set -eu`
  
- **New MCP Directive Types**:
  - `mcp:sme_correction` - Documents false positives with severity ratings
  - `mcp:anti_pattern` - Explicitly marks prohibited patterns with SME justifications
  - `mcp:correct_pattern` - Shows approved alternatives with working examples
  - `mcp:context_types` - Distinguishes operational/utility/test script contexts
  - `mcp:ai_guidance_rule` - Machine-readable rules for AI query processing

- **Context Discrimination System**:
  - Operational jobs (`jobs/`, `scripts/ex*`): Strict EE2, no exit statements, must use err_chk/err_exit
  - Utility scripts (`ush/`): EE2 variables apply, more flexibility in error handling
  - Test scripts (`tests/`): General shell scripting practices allowed

- **AI Guidance Rules**:
  - **Rule 1: Literal Compliance Only** - Prevent AI from adding "helpful" requirements beyond EE2
  - **Rule 2: Context-Aware Recommendations** - Script context detection before recommendations
  - **Rule 3: Anti-Pattern Enforcement** - Flag violations, reference SME justification, suggest corrections

- **Phase 2 Documentation**:
  - `PHASE_2_ANNOTATION_TRACKER.md` - Status, impact metrics, SME review schedule
  - SME sign-off block requiring 4 reviewers (EVS Lead, NCO SPA, EIB Ops, EMC GW)
  - Expected impact: 55-75% reduction in false positives after Phase 3 ingestion

### Fixed
- **False Positive #1: set -eu Recommendations** (~80% of scripts affected):
  - **Problem**: AI recommends `set -eu` everywhere
  - **Evidence**: EE2 standards.rst ONLY shows `set -x` in examples (lines 588-595)
  - **Evidence**: Example 8 (J-job) uses `set -x`, NO `set -e` (line 873)
  - **Evidence**: Example 9 (ex-script) uses `set -x`, NO `set -e` (line 950)
  - **Root Cause**: AI conflating shell scripting best practices with EE2 requirements
  - **Correction**: Added `mcp:anti_pattern` directive prohibiting `set -e`/`set -eu` recommendations

- **False Positive #2: Forced Exit Statements** (~60% of scripts affected):
  - **Problem**: AI recommends adding `exit 0` and `exit 1` to operational jobs
  - **Evidence**: NCO SPAs explicitly asked EVS to REMOVE these statements historically
  - **Evidence**: EE2 standards.rst only mentions `err_chk` and `err_exit` utilities (lines 187-195)
  - **Root Cause**: AI not aware of NCO operational culture (scripts must return naturally)
  - **Correction**: Added `mcp:anti_pattern` directive prohibiting explicit exits in operational contexts

- **Context Confusion**:
  - **Problem**: AI applies general shell scripting advice to EE2 operational requirements
  - **Correction**: Context detection logic distinguishes operational/utility/test scripts
  - **Correction**: Different requirements enforced based on script location and purpose

### Changed
- **Annotation Strategy**: Shifted from implicit learning to explicit anti-pattern marking
- **Validation Requirements**: SME review now required before Phase 3 ingestion
- **Evidence Standards**: All annotations must cite EE2 document sections with line numbers

### Impact Analysis
| Issue | Scripts Affected | Baseline False Positive Rate | Target Rate | Expected Improvement |
|-------|------------------|------------------------------|-------------|---------------------|
| `set -eu` warnings | ~80% of EVS | 80% | <5% | 75% reduction |
| Forced exit recommendations | ~60% of EVS | 60% | <10% | 50% reduction |
| **Overall false positives** | **Most scripts** | **70%** | **<15%** | **55% reduction** |

### Next Steps - Phase 3
- [ ] SME review and sign-off (target: November 22, 2025)
- [ ] Enhanced ingestion with corrected annotations
- [ ] Create new collection: `ee2-standards-v6-0-0-corrected`
- [ ] Query testing on 10 known false positive cases
- [ ] Measure actual false positive reduction
- [ ] Update SDD Framework status with Phase 2 results

---

## Version 4.0.0 - Phase 4: Bootstrap Capability (December 21, 2024)

**Milestone Achievement**: The MCP system can now modify its own code based on SDD workflow specifications - true autonomous development capability.

### New Core Components

**SelfModificationEngine.js** (440 lines):
- Transaction-based code modification with automatic rollback
- Safe file generation and modification
- Method addition to existing classes
- Tool registration with MCP server
- Backup creation before every change
- Change tracking and audit logging
- Validation gates before applying changes

**SpecificationParser.js** (356 lines):
- Parse SDD workflow markdown into structured modification specs
- Extract code generation requirements
- Identify code modification operations
- Parse validation and testing criteria
- Generate execution plans from natural language specs

**WorkflowExecutor.js** - Enhanced (788 lines):
- `executeCodeGeneration()` - Generate new files from specifications
- `executeCodeModification()` - Safely modify existing code
- `executeIngestion()` - Trigger RAG re-ingestion after changes
- `executeCommand()` - Execute system commands with safety checks
- Transaction management (begin/commit/rollback)
- Integration with SelfModificationEngine and SpecificationParser

### Features

**Code Generation**:
- Generate complete files from templates or raw content
- Variable interpolation in generated code
- Automatic directory creation
- Backup of existing files before overwrite

**Code Modification**:
- Add methods to existing classes
- Register new tools with UnifiedMCPServer
- Insert code at specific positions
- Replace/append/prepend operations
- Graph database analysis for code structure

**Safety Mechanisms**:
- 🔒 Transaction system with atomic rollback
- 🔒 Backup creation before all changes
- 🔒 Syntax validation before applying
- 🔒 Command sandboxing (allowlist-based)
- 🔒 Dangerous command blocking (rm -rf, sudo)
- 🔒 Dry-run mode for testing
- 🔒 Change history and audit trail

**RAG Integration**:
- Automatic knowledge base re-ingestion after code changes
- Selective ingestion (documentation, code, EE2 standards)
- Document count tracking
- Parallel ingestion script execution
- Error handling and partial success reporting

### New Workflow: bootstrap_capability_demo.md

Demonstrates autonomous code generation:
1. Generate new tool class from specification
2. Validate syntax automatically
3. Update knowledge base
4. Cleanup/rollback as needed

**Example**: System generates `ExampleBootstrapTool.js` including:
- Complete class definition
- MCP tool registration
- Method implementations
- Documentation

### Command Execution Safety

**Allowed Commands** (sandbox mode):
- `npm` - Package management and testing
- `git` - Version control operations  
- `node` - Syntax validation
- `python3` - Ingestion scripts
- `test` - Test execution

**Blocked Commands**:
- `rm -rf /` and `rm -rf ~` - Dangerous deletions
- `sudo` - Privilege escalation
- Any command not in allowlist (when sandbox=true)

### Ingestion Script Integration

**executeIngestion()** now triggers:
- `ingest_documentation_v4_2_unified.py` - Documentation ingestion
- `ingest_code_graph_enriched_v6.py` - Code analysis and graph
- `ingest_ee2_enhanced_v5.py` - EE2 standards

**Features**:
- Selective target ingestion (all, documentation, code, ee2)
- 5-minute timeout per script
- Document count extraction from output
- Parallel execution support
- Comprehensive error reporting

### Transaction System

**Transaction Lifecycle**:
```javascript
// Begin transaction
await beginSelfModification('add_new_feature');

// Make changes (tracked automatically)
await executeCodeGeneration(step, params);
await executeCodeModification(step, params);

// Validate changes
const validation = await validateModifications();

// Commit or rollback
if (validation.syntaxCheck && validation.tests) {
  await commitSelfModification();  // ✅ Apply changes
} else {
  await rollbackSelfModification(); // ❌ Undo everything
}
```

**Backup Strategy**:
- Timestamped backup directories
- Original files preserved before modification
- Max 10 backups retained (configurable)
- Atomic restoration on rollback

### Development Maturity Metrics

| Metric | v3.7.0 | v4.0.0 | Change |
|--------|---------|---------|---------|
| `bootstrap_capability` | false ❌ | true ✅ | **COMPLETE** |
| `system_maturity_score` | 85% | 100% | +15% |
| `tool_autonomy_level` | 2 | 3 | Self-modifying |
| `self_modification_capability` | functional | autonomous | **FULL** |

### Phase Complete

- ✅ Phase 1: Infrastructure (Neo4j + ChromaDB)
- ✅ Phase 2: RAG Enhancement  
- ✅ Phase 3A: SDD Framework Structure
- ✅ Phase 3B: SDD Tool Implementation
- ✅ Phase 3C: Runtime Integration
- ✅ **Phase 4: Bootstrap Capability** ← THIS RELEASE

### What This Enables

**Before v4.0.0**:
```
Human writes SDD workflow → System executes steps → Human writes code
```

**After v4.0.0**:
```
Human writes SDD workflow → System generates code → System validates → System commits
```

**The system is now its own developer.**

### Example: Autonomous Tool Addition

Write this workflow:
```markdown
# Add Performance Monitor

## Step 1: Generate Tool
**Type**: code_generation
**Target**: src/tools/PerformanceMonitor.js
**Content**: [tool code]

## Step 2: Register Tool
**Type**: code_modification
**File**: src/UnifiedMCPServer.js
**Action**: Import and register PerformanceMonitor

## Step 3: Validate
**Type**: command
**Command**: npm test -- PerformanceMonitor.test.js

## Step 4: Update Knowledge Base
**Type**: ingestion
**Target**: code
```

Execute:
```javascript
execute_sdd_workflow({ 
  workflow_name: 'add_performance_monitor',
  dry_run: false 
})
```

**System automatically**:
1. ✅ Generates `PerformanceMonitor.js`
2. ✅ Modifies `UnifiedMCPServer.js` to register it
3. ✅ Runs tests to validate
4. ✅ Updates ChromaDB + Neo4j with new code
5. ✅ Commits changes to git (if specified)

**No human coding required.**

### Safety First

All self-modification includes:
- Automatic backups before changes
- Syntax validation (node --check)
- Test execution (npm test)
- Rollback on any failure
- Complete audit trail
- Human approval option (configurable)

### Known Limitations

**Not Implemented**:
- Git auto-commit (command execution available, not default workflow)
- Complex refactoring (safe for additions, careful with modifications)
- Dependency installation (manual npm install still required)
- Multi-file atomic transactions (one transaction = multiple files, but no distributed transactions)

**Recommended**:
- Always run with `dry_run: true` first
- Review generated code before committing
- Keep backups of critical files
- Use version control
- Test in development environment first

### Testing

```javascript
// Demo the capability
await execute_sdd_workflow({
  workflow_name: 'bootstrap_capability_demo',
  dry_run: true  // Safe test mode
});

// Check what would be changed
await get_transaction_status();

// Real execution
await execute_sdd_workflow({
  workflow_name: 'bootstrap_capability_demo',
  dry_run: false  // Actually generate code
});
```

### Future Enhancements (v4.1.0+)

- Template library for common tool patterns
- LLM-assisted code generation (GPT-4 integration)
- Automated test generation
- Complex refactoring support
- Distributed transactions across repos
- Git auto-commit workflows
- Continuous validation during development
- Self-optimization (system improves its own code)

### Impact

**This release achieves the original vision**: An AI development system that can read specifications, implement features autonomously, validate its work, and maintain its own knowledge base - all with comprehensive safety guarantees.

**The MCP system has become self-bootstrapping.**

---

## Version 3.7.0 - Phase 3C: SDD Framework Runtime Integration (December 21, 2024)

### CRITICAL: Workflow Execution Capability Complete

**Milestone Achievement**: SDD Framework now connected to MCP runtime - workflows can execute real operations, not just parse.

### Phase 3C Completion

**Before (v3.6.0)**:
- ❌ `workflow_integration: false` - WorkflowExecutor disconnected from runtime
- ❌ `structural_integrity: compromised` - Framework could parse but not execute
- ❌ `mcp_runtime: disconnected` - No data access or health monitoring

**After (v3.7.0)**:
- ✅ `workflow_integration: true` - WorkflowExecutor connected to UnifiedDataAccess
- ✅ `structural_integrity: healthy` - Real execution methods implemented
- ✅ `mcp_runtime: connected` - Full data access and health monitoring active

### Changes

**UnifiedMCPServer.js**:
- Import `UnifiedDataAccess` class
- Initialize `this.dataAccess = new UnifiedDataAccess()` 
- Pass `this.dataAccess` to SDDWorkflowTools (replaces null)
- Updated Phase marker: "Phase 3C: Connected to runtime"

**WorkflowExecutor.js**:
- `executeHealthCheck()`: Use `dataAccess.healthCheck()` instead of null healthMonitor
  - Returns real ChromaDB + Neo4j health status
  - Includes metrics, connection status, timestamps
  - Graceful error handling
- `executeValidation()`: Implement 4 validation types
  - `result_count`: Verify query results meet minimum threshold
  - `health_status`: Validate system health is "healthy"
  - `data_freshness`: Check data age within acceptable limits
  - `pattern_match`: Validate content matches expected patterns
- `executeDataQuery()`: Already working (uses `dataAccess.hybridQuery()`)

### Impact

**Workflows Now Execute**:
- `test_health_check_workflow.md` - Can validate system health and perform queries
- Health checks query actual ChromaDB heartbeat and Neo4j connectivity
- Validations verify results against criteria (counts, freshness, patterns)
- Query steps perform hybrid semantic + graph search

**Development Maturity**:
- System maturity: 70% → 85%+ (estimated)
- Tool autonomy level: 1 → 2 (can execute multi-step workflows)
- Self-modification capability: "emerging" → "functional" (can validate changes)

### Phase Status

- ✅ Phase 3A: SDD Framework Structure (v3.1.0) - Workflow parsing, metadata extraction
- ✅ Phase 3B: SDD Tools Implementation (v3.2.0) - Tool registration, list/get workflows
- ✅ Phase 3C: Runtime Integration (v3.7.0) - **THIS RELEASE** - Connected execution
- 🔄 Phase 4: Bootstrap Capability (pending) - Self-modification engine

### Remaining Placeholders

**Not Critical for Phase 3C**:
- `executeIngestion()` - Triggers RAG re-ingestion (Phase 4)
- `executeCommand()` - System command execution (Phase 4 with safety checks)

These are intentionally deferred to Phase 4 (Bootstrap Capability) as they enable system self-modification.

### Testing

**Validation Commands**:
```javascript
// Check framework status (should show "connected")
mcp_eib-sdd-valid_framework_integrity()

// Check development status (should show workflow_integration: true)
mcp_eib-sdd-valid_development_status()

// Execute test workflow
execute_sdd_workflow({ 
  workflow_name: 'test_health_check_workflow',
  dry_run: false 
})
```

**Note**: MCP server restart required to activate runtime connection. If using VS Code MCP integration, reload window or restart MCP server process.

---

## Version 3.5.0 - ChromaDB Docker Migration (November 17, 2025)

### Critical Architecture Change
- **ChromaDB Migration**: Switched from Spack Python installation to Docker container
  - **Problem**: Spack Python venv wrapper prevented proper user site-packages installation
  - **Problem**: Rocky 9 system Python has SQLite 3.x < 3.35.0 (ChromaDB requires >= 3.35.0)
  - **Solution**: Docker container (chromadb/chroma:latest) eliminates all dependency conflicts
  
### Benefits of Docker ChromaDB
- ✅ **No Python version conflicts** - Self-contained environment
- ✅ **No SQLite version issues** - Container has correct SQLite version
- ✅ **No venv/site-packages confusion** - Isolated from host Python
- ✅ **Easy upgrades** - `docker pull chromadb/chroma:latest`
- ✅ **Persistent storage** - Volume mount `/mcp_rag_eib/data/chromadb`
- ✅ **Systemd integration** - `chromadb-docker.service`
- ✅ **Clean separation** - ChromaDB separate from development environment

### Files Changed
- `SETUP/provision_mcp_rag_persistent.sh` (v3.5.0)
  - STEP 7: Replaced Spack pip installation with Docker pull
  - STEP 8: Replaced chromadb-spack.service with chromadb-docker.service
  - Updated version header and documentation
- `SETUP/chromadb-docker.service` - New systemd service file (reference copy)
- `mcp_server_node/start-chromadb-system.sh` - Created (unused, for reference)
- `/etc/systemd/system/chromadb-docker.service` - Active service definition

### Service Configuration
```bash
# Service: chromadb-docker.service
# Port mapping: 8080 (host) -> 8000 (container)
# Volume: /mcp_rag_eib/data/chromadb -> /chroma/chroma
# Image: chromadb/chroma:latest
# API: v2 (http://localhost:8080/api/v2/heartbeat)
```

### Deployment Notes
- Old `chromadb-spack.service` disabled and stopped
- Existing ChromaDB data preserved and accessible via volume mount
- Startup time reduced from 90s to 30s max
- Startup health checks use API v2 endpoints

---

## Version 3.2.0 - CI Test Case Expert System (November 15, 2025)

### Major Features
- **GFS Expert System**: Complete CI test case documentation with comprehensive meteorological and operational context
  - Created `ingest_ci_test_cases.py` - Intelligent CI test case ingestion with GFS system knowledge
  - Created `ci_test_case_documentation_workflow.md` - Complete SDD workflow specification
  - Ingested 66 CI test cases across 7 categories with expert-level documentation

### CI Test Case Coverage
- **7 Categories Documented**:
  - `pr/` (18 files) - Pull Request fast CI tests
  - `gfsv17/` (20 files) - GFS v17 operational configurations
  - `gcafsv1/` (6 files) - GCAFS coupled system tests
  - `sfs/` (1 file) - Subseasonal Forecast System
  - `weekly/` (2 files) - Weekly high-resolution tests
  - `hires/` (2 files) - Very high-resolution tests (C768/C1152)
  - `yamls/` (17 files) - Base configuration templates

### GFS System Context (Expert-Level Knowledge)
Each test case now includes comprehensive context:
- **GFS Overview**: Mission-critical NOAA system, 4x/day operations, international distribution
- **Meteorological Science**: S2S forecasting, MJO, ENSO, ocean-atmosphere coupling rationale
- **Data Assimilation**: Hybrid 4D-EnVar, 10M obs/cycle, SOCA marine DA, quality control
- **Resolution Hierarchy**: C96/C384/C768 trade-offs, physics validity, operational constraints
- **Ocean Components**: MOM6 mx050/mx025/mx100, eddy resolution, hurricane intensity impacts
- **GFS v17 Upgrades**: Marine DA, extended forecasts, physics improvements, v16 comparison
- **Operational Stakes**: $500M+/day economic impact, hurricane evacuations, aviation dependencies
- **CI/CD Context**: Protecting operational reliability, bitwise reproducibility, regression testing
- **GFS Ecosystem**: Downstream users (NAM, HRRR, HWRF), international role, WMO distribution

### Technical Implementation
- **Jinja2-Aware Parsing**: Text-based extraction handles templated YAML (`{{ var }}`, `!INC` directives)
- **Category Intelligence**: Automatic categorization by test type, duration, resolution tier
- **Rich Metadata**: 8+ metadata fields per test case for semantic search
- **Documentation Generation**: Auto-generated 12,000+ character expert docs per test case
- **ChromaDB Collection**: `ci-test-cases-v2-0-0-gfs-expert` with 66 documents

### Knowledge Base Impact
- **Total documents**: 9,637 (up from 9,571)
- **CI test case docs**: +66 expert-level documents
- **Average doc size**: ~12KB with full GFS context
- **Search capability**: Can now answer complex meteorological + operational questions about any CI test

### SDD Framework Demonstration
This capability demonstrates **Phase 3A workflow automation**:
1. System identified knowledge gap (CI test cases not documented)
2. Planned solution (8-step workflow specification)
3. Implemented ingestion script (1,100+ LOC with GFS expertise)
4. Executed workflow autonomously
5. Validated completion (66/66 test cases ingested)

### Real-World Impact
System can now answer:
- "What does C96C48mx500_S2SW_cyc_gfs test and why does it matter?"
- "How does ocean resolution affect hurricane intensity forecasts?"
- "What's the difference between PR tests and gfsv17 operational validation?"
- "Why is hybrid 4D-EnVar critical for GFS v17?"
- "What would happen if GFS failed operationally?"

### Files Added
- `mcp_server_node/scripts/ingest_ci_test_cases.py` - CI test case ingestion engine
- `sdd_framework/workflows/ci_test_case_documentation_workflow.md` - Workflow specification

---

## Version 3.1.0 - Phase 3A: SDD Workflow Automation (November 14, 2025)

### Major Features
- **SDD Workflow Automation**: Implemented complete workflow parsing and execution engine
  - Created `WorkflowExecutor.js` - Core workflow engine with health monitoring integration
  - Created `SDDWorkflowTools.js` - 6 new MCP tools for SDD workflow management
  - Integrated with `UnifiedMCPServer.js` v3.1.0

### New MCP Tools (6 total)
1. `list_sdd_workflows` - List all available SDD framework workflows
2. `get_sdd_workflow` - Get detailed information about a specific workflow
3. `execute_sdd_workflow` - Execute workflow with parameters (dry-run support)
4. `get_sdd_execution_history` - View execution history with filtering
5. `validate_sdd_compliance` - SDD compliance validation (placeholder)
6. `get_sdd_framework_status` - Framework status and metrics

### Technical Implementation
- **Workflow Parsing**: Supports both `### Step N:` and `1. **Step**` markdown formats
- **Step Types**: health_check, data_query, validation, ingestion, command, manual
- **Metadata Extraction**: Automatic extraction of Type, Required, Component, Query, Target fields
- **Execution Framework**: Step-by-step execution with status tracking
- **History Tracking**: In-memory execution history with filtering
- **Health Integration**: Hooks for health monitor integration (to be connected)

### Workflow Support
- Successfully parses all 6 existing workflows:
  - data_ingestion_workflow
  - ee2_enhanced_embeddings_workflow
  - mcp_code_migration_checklist
  - mcp_integration_todo
  - rag_enhancement_workflow
  - rag_major_upgrade_workflow
- Added test_health_check_workflow for validation

### Architecture Updates
- Updated `UnifiedMCPServer.js` to v3.1.0
- Total tool count: 27 tools (up from 21)
- Maintained backward compatibility with Week 2 architecture

### Next Steps (Phase 3B)
- Connect health monitoring to WorkflowExecutor
- Implement actual data access layer integration
- Enable real workflow execution (currently placeholders)
- Add workflow validation before execution
- Implement workflow composition and chaining

---

## Version 3.0.0 - Week 2 Consolidation (November 2025)

### Major Refactor
- Consolidated 3 separate servers into unified architecture
- Eliminated 8 duplicate tools
- Implemented modular tool system with 5 tool modules

### Tool Modules
- **WorkflowInfoTools** (3 tools) - Static workflow information
- **CodeAnalysisTools** (4 tools) - Graph-based code analysis
- **SemanticSearchTools** (7 tools) - Vector + graph hybrid search
- **OperationalTools** (3 tools) - HPC operational guidance
- **GitHubTools** (4 tools) - Repository integration

### Infrastructure
- Total tools: 21 (reduced from 29 with duplicates)
- Clear separation of concerns
- Improved maintainability and error handling
- Consistent tool registration pattern

---

## Version 2.0.0 - Week 1 Data Layer (October 2025)

### Foundation
- Created unified data access layer
- Integrated ChromaDB and Neo4j
- Established graph + vector hybrid architecture

### Components
- `UnifiedDataAccess.js` - Single source for all data operations
- `VectorDatabase.js` - ChromaDB client interface
- `GraphDatabase.js` - Neo4j client interface
- Health monitoring framework

---

## Version 1.0.0 - Initial Release (September 2025)

### Initial Implementation
- Basic MCP server functionality
- Separate servers for RAG, GitHub, and workflow
- Initial tool set (29 tools with duplicates)
- ChromaDB integration
- Basic documentation search
