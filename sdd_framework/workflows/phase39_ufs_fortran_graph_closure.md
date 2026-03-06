# Phase 39: UFS Fortran Graph Gap Closure

**Version**: 1.0.0
**Status**: Planned
**Created**: 2026-03-06
**Author**: AI Assistant + Terry McGuinness
**Dependency**: Phase 38 (data quality normalization must complete first)
**Gap Analysis**: [docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md](../../docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md) §3, §7-B

---

## 1. Executive Summary

The Neo4j Fortran call graph currently covers **5 of 14** top-level `sorc/` submodules (gdas.cd, gsi_enkf.fd, gsi_utils.fd, gsi_monitor.fd, gfs_utils.fd) with 13,537 FortranSubroutines. The entire **UFS coupled model tree** — the code that runs the actual forecast — has **zero** graph nodes despite containing 3,503 Fortran files.

This phase fixes the Fortran graph ingestion pipeline to handle UFS/MOM6/CMEPS source files and ingests them, adding an estimated **10,000+ new FortranSubroutine/Function/Module nodes** and **50,000+ CALLS/USES relationships** to Neo4j.

### Impact

| Metric | Before Phase 39 | After Phase 39 |
|--------|-----------------|----------------|
| FortranSubroutine nodes | 13,537 | ~23,000+ |
| FortranModule nodes | 1,539 | ~3,000+ |
| CALLS relationships | 439,919 | ~500,000+ |
| Submodule coverage | 5/14 (36%) | 12/14 (86%) |
| Scientific code graph coverage | ~40% | ~90% |

### Root Cause Analysis

Two bugs in `ingest_fortran_graph.py` prevent UFS ingestion:

1. **fparser2 cannot handle C preprocessor directives** — UFS/MOM6/CMEPS Fortran files extensively use `#ifdef`, `#include`, `#define`, and `#ifndef` macros. `fparser2.FortranFileReader` chokes on these, causing silent parse failures. Solution: preprocess with `cpp -traditional-cpp` before parsing.

2. **SUBMODULE_PATHS config has wrong names** — The config lists `gsi.fd` (should be `gsi_enkf.fd`), `gdas.fd` (should be `gdas.cd`), `gfs_wafs.fd` (doesn't exist), and `fit2obs.fd` (doesn't exist).

---

## 2. Problem Detail

### 2.1 UFS Fortran Files by Component

| Component | Path (under `sorc/ufs_model.fd/`) | Fortran Files | Graph Nodes | Gap |
|-----------|-------------------------------------|--------------|-------------|-----|
| **UFSATM** (FV3 atmosphere) | `UFSATM/` | 1,286 | 0 | CRITICAL |
| **MOM6** (ocean model) | `MOM6-interface/MOM6/` | 526 | 0 | CRITICAL |
| **AQM/CMAQ** (air quality) | `AQM/` | 853 | 0 | HIGH |
| **WW3** (wave model) | `WW3/` | 298 | 0 | HIGH |
| **CICE** (sea ice) | `CICE-interface/CICE/` | 180 | 17 | HIGH |
| **CMEPS** (mediator) | `CMEPS-interface/CMEPS/` | 69 | 0 | CRITICAL |
| **LM4** (land model) | `LM4-interface/` | 59 | 0 | MEDIUM |
| **CDEPS** (data components) | `CDEPS-interface/CDEPS/` | 53 | 0 | MEDIUM |
| **HYCOM** (hybrid ocean) | `HYCOM-interface/` | 69 | 0 | MEDIUM |
| **GOCART** (aerosol) | `GOCART-interface/` | 33 | 0 | LOW |
| **NOAHMP** (land surface) | `NOAHMP-interface/` | 21 | 0 | LOW |
| **stochastic_physics** | `stochastic_physics/` | 26 | 0 | LOW |
| **fire_behavior** | `fire_behavior_model/` | 28 | 0 | LOW |
| **UFS driver** | `*.F90` (top level) | 2 | 0 | CRITICAL |
| **TOTAL** | | **3,503** | **17** | |

### 2.2 Additional sorc/ Submodules Not in Graph

| Submodule | Fortran Files | Status |
|-----------|--------------|--------|
| `sorc/ufs_utils.fd` | 506 | NOT ingested — fparser2 failures |
| `sorc/nexus.fd` | 86 | NOT ingested — not in SUBMODULE_PATHS |
| `sorc/gsi_enkf.fd` | 799 | Listed as wrong name `gsi.fd` — actually works because fallback scan |
| `sorc/gdas.cd` | 1,647 | Listed as wrong name `gdas.fd` — actually works because fallback scan |

### 2.3 Preprocessor Directive Examples

Typical UFS Fortran file with CPP directives (from `UFSATM/atmos_model.F90`):
```fortran
#ifdef INTERNAL_FILE_NML
  read(input_nml_file, nml=atmos_model_nml, iostat=io)
#else
  open(newunit=unit, file='input.nml', status='old')
  read(unit, nml=atmos_model_nml, iostat=io)
  close(unit)
#endif
```

`FortranFileReader` treats `#ifdef` as a syntax error and aborts the entire file.

### 2.4 Prior Art: ingest_code_v8.py Succeeds

The ChromaDB vector ingestion (`ingest_code_v8.py`) uses a simpler regex-based Fortran parser that ignores preprocessor directives and successfully creates 13,601 chunks for ufs_model.fd. This confirms the files are structurally valid Fortran — the issue is purely fparser2's strict parsing.

---

## 3. Technical Architecture

### 3.1 Preprocessing Pipeline

```
Fortran Source (.F90)
    │
    ▼
cpp -traditional-cpp -nostdinc -P  ──►  Clean Fortran (.f90)
    │                                         │
    │  (files without #ifdef)                 │  (files with #ifdef)
    │                                         │
    ▼                                         ▼
fparser2.FortranFileReader  ◄────────  Temp preprocessed file
    │
    ▼
AST Walk → Extract CALL/USE/MODULE/SUBROUTINE
    │
    ▼
Neo4j Ingestion (MERGE nodes, CREATE relationships)
```

### 3.2 cpp Flags Explained

| Flag | Purpose |
|------|---------|
| `-traditional-cpp` | Fortran-friendly mode — preserves fixed-form layout, no C99 features |
| `-nostdinc` | Don't search system C headers (Fortran `#include` targets are local) |
| `-P` | Suppress `#line` directives in output (would confuse fparser2) |
| `-I<dir>` | Add include search paths for `#include "foo.h"` directives |

### 3.3 Include Path Discovery

UFS Fortran files `#include` headers from various locations:
```
sorc/ufs_model.fd/UFSATM/atmos_cubed_sphere/include/
sorc/ufs_model.fd/FMS/include/
sorc/ufs_model.fd/MOM6-interface/MOM6/src/framework/
sorc/ufs_model.fd/CICE-interface/CICE/icepack/columnphysics/
```

The preprocessing step must discover these include directories or fall back to ignoring missing includes (`-D` undefined macros resolve to empty).

---

## 4. Implementation Steps

### Step 39-1: Fix SUBMODULE_PATHS Configuration
**Tag**: implement
**Target**: `mcp_server_node/scripts/ingest_fortran_graph.py`

Update the `SUBMODULE_PATHS` list to match actual directory names:

```python
# Before (buggy):
SUBMODULE_PATHS = [
    'sorc/ufs_model.fd',
    'sorc/gsi.fd',          # WRONG — actual: gsi_enkf.fd
    'sorc/gdas.fd',         # WRONG — actual: gdas.cd
    'sorc/ufs_utils.fd',
    'sorc/gfs_wafs.fd',     # DOES NOT EXIST
    'sorc/fit2obs.fd',      # DOES NOT EXIST
]

# After (corrected + expanded):
SUBMODULE_PATHS = [
    'sorc/ufs_model.fd',
    'sorc/gsi_enkf.fd',     # was gsi.fd
    'sorc/gdas.cd',         # was gdas.fd (note: .cd not .fd)
    'sorc/ufs_utils.fd',
    'sorc/gsi_utils.fd',
    'sorc/gsi_monitor.fd',
    'sorc/gfs_utils.fd',
    'sorc/nexus.fd',        # NEW — air quality emissions
    'sorc/verif-global.fd', # NEW — verification (mostly Python)
    'sorc/wxflow',          # NEW — workflow library (Python)
]
```

**Acceptance**: `SUBMODULE_PATHS` lists only directories that exist in `supported_repos/global-workflow/sorc/`.

---

### Step 39-2: Implement C Preprocessor Stage
**Tag**: implement
**Target**: `mcp_server_node/scripts/ingest_fortran_graph.py`

Add a `preprocess_fortran()` function that detects CPP directives and runs `cpp` before passing to fparser2:

```python
import subprocess
import tempfile

def needs_preprocessing(file_path: str) -> bool:
    """Check if a Fortran file uses C preprocessor directives."""
    with open(file_path, 'r', errors='replace') as f:
        for line in f:
            stripped = line.lstrip()
            if stripped.startswith('#') and any(
                stripped.startswith(d) for d in 
                ['#ifdef', '#ifndef', '#if ', '#include', '#define', '#else', '#endif', '#undef']
            ):
                return True
    return False

def preprocess_fortran(file_path: str, include_dirs: list = None) -> str:
    """Run cpp -traditional-cpp on a Fortran file, return path to cleaned file."""
    cmd = ['cpp', '-traditional-cpp', '-nostdinc', '-P']
    if include_dirs:
        for d in include_dirs:
            cmd.extend(['-I', d])
    cmd.append(file_path)
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        # Fall back to simple directive stripping
        return strip_directives_fallback(file_path)
    
    # Write to temp file for FortranFileReader
    suffix = '.f90'
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix=suffix, delete=False)
    tmp.write(result.stdout)
    tmp.close()
    return tmp.name

def strip_directives_fallback(file_path: str) -> str:
    """Simple fallback: comment out all # directives."""
    with open(file_path, 'r', errors='replace') as f:
        lines = f.readlines()
    
    cleaned = []
    for line in lines:
        if line.lstrip().startswith('#'):
            cleaned.append('! CPP: ' + line)
        else:
            cleaned.append(line)
    
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.f90', delete=False)
    tmp.writelines(cleaned)
    tmp.close()
    return tmp.name
```

**Acceptance**: `preprocess_fortran('sorc/ufs_model.fd/UFSATM/atmos_model.F90')` returns a temp file that fparser2 can parse.

---

### Step 39-3: Discover Include Directories
**Tag**: implement
**Target**: `mcp_server_node/scripts/ingest_fortran_graph.py`

Add automatic include-directory discovery for the UFS tree:

```python
def discover_include_dirs(workflow_root: str) -> list:
    """Find all directories containing .h or .inc files in sorc/."""
    include_dirs = set()
    sorc_dir = os.path.join(workflow_root, 'sorc')
    for root, dirs, files in os.walk(sorc_dir):
        for f in files:
            if f.endswith(('.h', '.inc', '.fh')):
                include_dirs.add(root)
    return sorted(include_dirs)
```

Cache the result per run (typically ~20-30 directories).

**Acceptance**: Include directories discovered for FMS, UFSATM, MOM6, CICE.

---

### Step 39-4: Update Parse Loop to Use Preprocessing
**Tag**: implement
**Target**: `mcp_server_node/scripts/ingest_fortran_graph.py`

Modify `FortranParser.parse_file()` to conditionally preprocess:

```python
def parse_file(self, file_path: str, include_dirs: list = None) -> dict:
    """Parse a Fortran file, preprocessing if needed."""
    actual_path = file_path
    temp_path = None
    
    try:
        if needs_preprocessing(file_path):
            temp_path = preprocess_fortran(file_path, include_dirs)
            actual_path = temp_path
        
        reader = FortranFileReader(actual_path, ignore_comments=True)
        parse_tree = self.parser(reader)
        # ... existing AST walk logic ...
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
```

**Acceptance**: Files with `#ifdef` directives parse successfully via the preprocessing path.

---

### Step 39-5: Test Preprocessing on UFS Sample Files
**Tag**: validate
**Target**: Terminal

Test the preprocessing pipeline on representative files from each UFS component:

```bash
# Test files (one per major component):
python scripts/ingest_fortran_graph.py --test sorc/ufs_model.fd/UFS.F90
python scripts/ingest_fortran_graph.py --test sorc/ufs_model.fd/UFSATM/atmos_model.F90
python scripts/ingest_fortran_graph.py --test sorc/ufs_model.fd/MOM6-interface/MOM6/src/core/MOM.F90
python scripts/ingest_fortran_graph.py --test sorc/ufs_model.fd/CMEPS-interface/CMEPS/mediator/med_phases_prep_ocn_mod.F90
python scripts/ingest_fortran_graph.py --test sorc/ufs_model.fd/WW3/model/src/w3initmd.F90
python scripts/ingest_fortran_graph.py --test sorc/ufs_model.fd/CICE-interface/CICE/cicecore/cicedyn/dynamics/ice_dyn_evp.F90
python scripts/ingest_fortran_graph.py --test sorc/ufs_utils.fd/sorc/chgres_cube.fd/chgres_cube.F90
```

**Acceptance**: >= 6 of 7 test files parse successfully (some may have complex macros that need iteration).

---

### Step 39-6: Dry-Run on Full ufs_model.fd Tree
**Tag**: validate
**Target**: Terminal

```bash
python scripts/ingest_fortran_graph.py --dry-run --directory sorc/ufs_model.fd
```

Expect:
- 3,503 files attempted
- ~2,800+ files parsed successfully (80%+ success rate)
- ~500-700 files failing (complex macros, non-standard extensions)
- Report on modules/subroutines/functions discovered

**Acceptance**: >= 80% parse success rate. Identified failures are documented for future iteration.

---

### Step 39-7: Ingest ufs_model.fd into Neo4j
**Tag**: execute
**Target**: `mcp_server_node/scripts/ingest_fortran_graph.py`

Full ingestion run for the UFS model tree:

```bash
python scripts/ingest_fortran_graph.py --directory sorc/ufs_model.fd 2>&1 | tee logs/phase39_ufs_ingest.log
```

Expected new nodes:
- ~5,000-8,000 FortranSubroutine
- ~1,000-1,500 FortranModule
- ~500-1,000 FortranFunction
- ~30,000+ CALLS relationships
- ~10,000+ USES relationships

**Acceptance**: `MATCH (n:FortranSubroutine) RETURN COUNT(n)` shows significant increase from 13,537 baseline.

---

### Step 39-8: Ingest ufs_utils.fd into Neo4j
**Tag**: execute
**Target**: `mcp_server_node/scripts/ingest_fortran_graph.py`

```bash
python scripts/ingest_fortran_graph.py --directory sorc/ufs_utils.fd 2>&1 | tee logs/phase39_utils_ingest.log
```

Expected: ~400-600 new subroutines (chgres_cube, grid generation, surface utilities).

**Acceptance**: ufs_utils.fd subroutines visible in Neo4j.

---

### Step 39-9: Ingest nexus.fd into Neo4j
**Tag**: execute
**Target**: `mcp_server_node/scripts/ingest_fortran_graph.py`

```bash
python scripts/ingest_fortran_graph.py --directory sorc/nexus.fd 2>&1 | tee logs/phase39_nexus_ingest.log
```

Expected: ~100-200 new subroutines (emissions processing for AQM).

**Acceptance**: nexus.fd subroutines visible in Neo4j.

---

### Step 39-10: Verify Cross-Component USES Relationships
**Tag**: validate
**Target**: Terminal (Cypher queries)

Verify that inter-component USE dependencies are captured:

```cypher
-- CMEPS using ESMF
MATCH (n)-[:USES]->(m:FortranModule)
WHERE m.name = 'esmf' AND n.file_path CONTAINS 'CMEPS'
RETURN n.name, n.file_path LIMIT 10;

-- MOM6 using FMS
MATCH (n)-[:USES]->(m:FortranModule)
WHERE m.name STARTS WITH 'fms' AND n.file_path CONTAINS 'MOM6'
RETURN n.name, n.file_path LIMIT 10;

-- Component coupling graph
MATCH (n)-[:USES]->(m:FortranModule)
WHERE n.file_path CONTAINS 'ufs_model.fd'
WITH SPLIT(n.file_path, '/')[2] AS component, m.name AS module
RETURN component, COUNT(DISTINCT module) AS used_modules
ORDER BY used_modules DESC;
```

**Acceptance**: Cross-component USE relationships visible. ESMF/NUOPC modules referenced by CMEPS, UFSATM, MOM6.

---

### Step 39-11: Re-Run Community Detection
**Tag**: execute
**Target**: `mcp_server_node/scripts/run_community_detection.py` (or equivalent)

With ~10,000+ new nodes, the community structure will change significantly. Re-run Leiden community detection at all 4 levels (L0-L3) and regenerate community summaries.

```bash
python scripts/ingest_communities.py
```

Expected: New communities for UFS atmosphere, ocean, sea ice, waves, mediator subsystems.

**Acceptance**: New communities visible at L0-L2. Community count increases from 1,036 baseline.

---

### Step 39-12: Regenerate Community Summaries
**Tag**: execute
**Target**: ChromaDB `community-summaries` collection

Generate LLM summaries for new communities and update the `community-summaries` ChromaDB collection.

**Acceptance**: `community-summaries` collection count increases from 1,648. New summaries describe UFS model subsystems.

---

### Step 39-13: Validate with MCP Tools
**Tag**: validate
**Target**: EIB MCP tools

Test that the new graph data is accessible through MCP tools:

```
find_callers_callees({ function_name: "atmos_model_init" })
trace_execution_path({ function_name: "ocean_model_init" })
find_dependencies({ target: "sorc/ufs_model.fd/CMEPS-interface/CMEPS/mediator/med.F90" })
get_code_context({ symbol: "MOM_initialize" })
search_architecture({ query: "UFS coupled model initialization" })
```

**Acceptance**: All 5 queries return meaningful results with UFS model data.

---

### Step 39-14: Update Gap Analysis Report
**Tag**: document
**Target**: `docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md`

Update §3 (Submodule Coverage) and §8 (Coverage Scorecard) to reflect new UFS graph coverage. Update grades for UFS Atmosphere, Ocean, Coupling, Sea Ice, Waves from D/F to B/C range.

**Acceptance**: Scorecard reflects Phase 39 improvements.

---

## 5. Validation Criteria

| Criterion | Before | After | Method |
|-----------|--------|-------|--------|
| FortranSubroutine node count | 13,537 | ~23,000+ | `MATCH (n:FortranSubroutine) RETURN COUNT(n)` |
| FortranModule node count | 1,539 | ~3,000+ | `MATCH (n:FortranModule) RETURN COUNT(n)` |
| sorc/ submodules with graph data | 5/14 | 12/14 | Cypher per-submodule count |
| ufs_model.fd graph nodes | 0 | 8,000+ | `WHERE file_path CONTAINS 'ufs_model'` |
| Community count | 1,036 | 1,200+ | `MATCH (c:Community) RETURN COUNT(c)` |
| `find_callers_callees` for UFS symbols | empty | results | MCP tool test |

## 6. Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|-----------|
| `cpp` not available on VM | Blocks preprocessing | `which cpp` — GCC includes it. If missing: `sudo yum install cpp` |
| fparser2 still fails after cpp | Some files unparseable | Fallback to directive stripping. Accept 80% success rate. |
| Neo4j memory pressure from ~10K new nodes | Slow queries | Monitor heap. 10K nodes is modest for Neo4j. |
| Community detection takes too long | Delays completion | Run as background task. Can defer to separate step. |
| Some UFS modules are auto-generated | Parser metadata misleading | Tag auto-generated files in metadata. |

## 7. Cross-References

- **Prerequisite**: Phase 38 (data quality — clean paths before new ingestion)
- **Gap Analysis**: `docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md` §3 (Submodule Coverage), §7-B (Remediation Phase B)
- **Original**: Phase 10 (initial Fortran graph ingestion)
- **Related**: Phase 24E (community detection), Phase 24F (cross-language bridges)
- **Downstream**: Phase 42 (JEDI sub-submodule ingestion builds on this pipeline)
