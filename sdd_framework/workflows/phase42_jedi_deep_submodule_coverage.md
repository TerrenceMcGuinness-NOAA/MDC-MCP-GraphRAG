# Phase 42: Deep Submodule Coverage — JEDI/GDAS Ecosystem

**Version**: 1.0.0
**Status**: Planned
**Created**: 2026-03-06
**Author**: AI Assistant + Terry McGuinness
**Dependency**: Phase 39 (UFS Fortran graph closure — reuses the cpp preprocessing pipeline)
**Gap Analysis**: [docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md](../../docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md) §3, §7-E

---

## 1. Executive Summary

The `sorc/gdas.cd/` submodule is the **data assimilation hub** of the Global Workflow. While the top-level gdas.cd code has good graph coverage (5,723 FortranSubroutines, 769 FortranModules), its deeply nested sub-submodules — the JEDI ecosystem — have partial vector coverage but **no Fortran call graph** in Neo4j.

These sub-submodules contain the actual DA algorithms (variational minimization, ensemble filters, observation operators, CRTM radiative transfer) that are called thousands of times per cycle. Without graph coverage, the expert system cannot trace execution from a J-Job through GSI/JEDI into the scientific kernels.

### Scope

| Sub-Submodule | Location | Fortran Files | Neo4j Status |
|--------------|----------|--------------|-------------|
| **fv3-jedi** | `sorc/gdas.cd/sorc/fv3-jedi/` | ~200 | NO graph |
| **soca** (ocean DA) | `sorc/gdas.cd/sorc/soca/` | ~80 | NO graph |
| **ioda** (observation database) | `sorc/gdas.cd/sorc/ioda/` | ~150 | NO graph |
| **oops** (abstract DA framework) | `sorc/gdas.cd/sorc/oops/` | ~100 | NO graph |
| **saber** (background error) | `sorc/gdas.cd/sorc/saber/` | ~120 | NO graph |
| **ufo** (observation operators) | `sorc/gdas.cd/sorc/ufo/` | ~300 | NO graph |
| **vader** (variable transforms) | `sorc/gdas.cd/sorc/vader/` | ~50 | NO graph |
| **CRTM** (radiative transfer) | `sorc/gdas.cd/sorc/crtm/` | ~500+ | NO graph |
| **gsw** (seawater toolbox) | `sorc/gdas.cd/sorc/gsw/` | ~30 | NO graph |
| **femps** (mesh partitioning) | `sorc/gdas.cd/sorc/femps/` | ~20 | NO graph |

Estimated new nodes: **5,000-8,000 FortranSubroutines**, **500-800 FortranModules**, **30,000+ CALLS/USES relationships**.

### Motivation

The JEDI stack is the most complex scientific code in the repository:
- **oops** defines abstract interfaces (Increment, State, Geometry, ObsOperator)
- **fv3-jedi** and **soca** implement those interfaces for atmosphere and ocean
- **ufo** provides 50+ observation operators (radiance, surface, profile)
- **CRTM** has 90+ Fortran modules used in radiance assimilation (accounts for >96 USE statements in GSI)
- **ioda** manages observation data (reads BUFR, NetCDF, writes IODA format)

Without this graph, asking "What observation operators are used in the GDAS analysis?" returns nothing useful.

---

## 2. JEDI Architecture Overview

```
oops (abstract framework)
  │
  ├── fv3-jedi (atmosphere implementation)
  │     ├── uses: oops interfaces
  │     ├── uses: ufo observation operators
  │     └── uses: CRTM for radiance
  │
  ├── soca (ocean implementation)
  │     ├── uses: oops interfaces
  │     ├── uses: ufo observation operators
  │     └── uses: gsw (seawater equations)
  │
  ├── ufo (observation operators)
  │     ├── conventional: aircraft, radiosonde, surface
  │     ├── radiance: CRTM-based satellite obs
  │     └── profile: GNSS-RO, ozone, wind
  │
  ├── ioda (observation data)
  │     ├── BUFR → IODA converters
  │     └── NetCDF + HDF5 I/O
  │
  ├── saber (background error covariance)
  │     ├── BUMP (NICAS localization)
  │     └── spectral transforms
  │
  └── vader (variable transforms)
        ├── virtual temperature ↔ temperature + moisture
        └── hydrostatic pressure from thermodynamic state
```

### CRTM Dependency Chain

CRTM (Community Radiative Transfer Model) is the largest single dependency:
```
GSI: radiance observation operator
  → CRTM_Forward (crtm_forward_module)
    → CRTM_AtmAbsorption (gas absorption)
    → CRTM_SfcOptics (surface emissivity)
    → CRTM_RTSolution (radiative transfer solver)
      → ADA_Module (adding-doubling algorithm)
      → SOI_Module (successive order of interaction)
```

90+ Fortran modules, ~500 source files. Currently zero graph presence.

---

## 3. Technical Specification

### Prerequisites

- **Phase 39** must be complete — the cpp preprocessing pipeline is required since JEDI Fortran also uses `#ifdef` extensively
- **Phase 38** should be complete — clean paths before adding new data

### Target Scripts

| File | Purpose | Changes |
|------|---------|---------|
| `mcp_server_node/scripts/ingest_fortran_graph.py` | Fortran→Neo4j | **MODIFY**: Add JEDI sub-submodule paths to `SUBMODULE_PATHS` |
| `mcp_server_node/scripts/ingest_python_graph.py` | Python→Neo4j | **MODIFY**: Add JEDI Python paths to `PYTHON_DIRECTORIES` |

### New SUBMODULE_PATHS Entries

```python
# JEDI DA ecosystem (under sorc/gdas.cd/sorc/)
'sorc/gdas.cd/sorc/fv3-jedi',
'sorc/gdas.cd/sorc/soca',
'sorc/gdas.cd/sorc/ioda',
'sorc/gdas.cd/sorc/oops',
'sorc/gdas.cd/sorc/saber',
'sorc/gdas.cd/sorc/ufo',
'sorc/gdas.cd/sorc/vader',
'sorc/gdas.cd/sorc/crtm',
'sorc/gdas.cd/sorc/gsw',
'sorc/gdas.cd/sorc/femps',
```

### New PYTHON_DIRECTORIES Entries

```python
'sorc/gdas.cd/sorc/ioda/src/engines',       # IODA Python bindings
'sorc/gdas.cd/sorc/ioda/tools',             # IODA converter tools
'sorc/gdas.cd/sorc/soca/test',              # SOCA test harnesses
'sorc/gdas.cd/sorc/ufo/tools',              # UFO Python utilities
```

### Neo4j Expected Additions

| Node Type | Estimated New | Source |
|-----------|--------------|--------|
| FortranSubroutine | 5,000-8,000 | All JEDI sub-submodules |
| FortranModule | 500-800 | Module-heavy codebase |
| FortranFunction | 300-500 | |
| PythonModule | 50-100 | IODA tools, test harnesses |
| CALLS relationships | 30,000+ | Dense call graphs |
| USES relationships | 10,000+ | Heavy cross-module deps |

---

## 4. Implementation Steps

### Step 42-1: Inventory JEDI Sub-Submodule File Counts
**Tag**: validate
**Target**: Terminal

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow
for dir in sorc/gdas.cd/sorc/fv3-jedi sorc/gdas.cd/sorc/soca \
           sorc/gdas.cd/sorc/ioda sorc/gdas.cd/sorc/oops \
           sorc/gdas.cd/sorc/saber sorc/gdas.cd/sorc/ufo \
           sorc/gdas.cd/sorc/vader sorc/gdas.cd/sorc/crtm \
           sorc/gdas.cd/sorc/gsw sorc/gdas.cd/sorc/femps; do
    if [[ -d "$dir" ]]; then
        f90=$(find "$dir" -name "*.F90" -o -name "*.f90" -o -name "*.F" -o -name "*.f" 2>/dev/null | wc -l)
        py=$(find "$dir" -name "*.py" 2>/dev/null | wc -l)
        echo "$dir: F90=$f90 PY=$py"
    else
        echo "$dir: NOT INITIALIZED (submodule not checked out)"
    fi
done
```

**Acceptance**: File counts documented. Any uninitialized submodules identified for `git submodule update --init`.

---

### Step 42-2: Initialize Missing Submodules
**Tag**: execute
**Target**: Terminal

If any JEDI sub-submodules are not checked out:

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow
git submodule update --init --recursive sorc/gdas.cd/sorc/fv3-jedi
git submodule update --init --recursive sorc/gdas.cd/sorc/soca
git submodule update --init --recursive sorc/gdas.cd/sorc/ioda
git submodule update --init --recursive sorc/gdas.cd/sorc/oops
git submodule update --init --recursive sorc/gdas.cd/sorc/saber
git submodule update --init --recursive sorc/gdas.cd/sorc/ufo
git submodule update --init --recursive sorc/gdas.cd/sorc/vader
git submodule update --init --recursive sorc/gdas.cd/sorc/crtm
```

**Acceptance**: All JEDI sub-submodules checked out with source files present.

---

### Step 42-3: Add JEDI Paths to Fortran Ingestion Config
**Tag**: implement
**Target**: `mcp_server_node/scripts/ingest_fortran_graph.py`

Append JEDI sub-submodule paths to `SUBMODULE_PATHS`:

```python
SUBMODULE_PATHS = [
    # ... existing entries from Phase 39 ...
    # JEDI DA ecosystem (Phase 42)
    'sorc/gdas.cd/sorc/fv3-jedi',
    'sorc/gdas.cd/sorc/soca',
    'sorc/gdas.cd/sorc/ioda',
    'sorc/gdas.cd/sorc/oops',
    'sorc/gdas.cd/sorc/saber',
    'sorc/gdas.cd/sorc/ufo',
    'sorc/gdas.cd/sorc/vader',
    'sorc/gdas.cd/sorc/crtm',
    'sorc/gdas.cd/sorc/gsw',
    'sorc/gdas.cd/sorc/femps',
]
```

**Acceptance**: Config updated. `--dry-run --directory sorc/gdas.cd/sorc/oops` reports Fortran files found.

---

### Step 42-4: Add JEDI Python Paths to Python Ingestion Config
**Tag**: implement
**Target**: `mcp_server_node/scripts/ingest_python_graph.py`

Add JEDI Python directories to `PYTHON_DIRECTORIES`:

```python
PYTHON_DIRECTORIES = [
    # ... existing entries ...
    # JEDI Python tools (Phase 42)
    'sorc/gdas.cd/sorc/ioda/src/engines',
    'sorc/gdas.cd/sorc/ioda/tools',
    'sorc/gdas.cd/sorc/soca/test',
    'sorc/gdas.cd/sorc/ufo/tools',
]
```

**Acceptance**: Config updated.

---

### Step 42-5: Test Preprocessing on JEDI Fortran Files
**Tag**: validate
**Target**: Terminal

JEDI Fortran uses `#ifdef` for platform portability and optional features. Test the Phase 39 preprocessing pipeline on JEDI samples:

```bash
# Test representative files from each sub-submodule
python scripts/ingest_fortran_graph.py --test sorc/gdas.cd/sorc/oops/src/oops/base/State.h
python scripts/ingest_fortran_graph.py --test sorc/gdas.cd/sorc/fv3-jedi/src/fv3jedi/Model/fv3jedi_model_mod.F90
python scripts/ingest_fortran_graph.py --test sorc/gdas.cd/sorc/ufo/src/ufo/ObsOperator.h
python scripts/ingest_fortran_graph.py --test sorc/gdas.cd/sorc/crtm/src/CRTM_Forward_Module.f90
python scripts/ingest_fortran_graph.py --test sorc/gdas.cd/sorc/soca/src/soca/Model/soca_model_mod.F90
```

Note: oops and ufo use C++ with Fortran interfaces. The `.h` files are C++ headers — the parser should skip these and only process `.F90`/`.f90` files.

**Acceptance**: Fortran files parse successfully. C++ headers are correctly skipped.

---

### Step 42-6: Dry-Run CRTM Ingestion
**Tag**: validate
**Target**: Terminal

CRTM is the largest sub-submodule (~500 files). Test it separately:

```bash
python scripts/ingest_fortran_graph.py --dry-run --directory sorc/gdas.cd/sorc/crtm
```

Expect:
- ~500 files attempted
- ~400+ parsed successfully (CRTM is mostly standard Fortran with few preprocessor directives)
- ~2,000+ subroutines, 90+ modules

**Acceptance**: >= 80% parse success rate for CRTM.

---

### Step 42-7: Ingest JEDI Core (oops, vader, saber)
**Tag**: execute
**Target**: Terminal

Start with the foundational abstract layer:

```bash
python scripts/ingest_fortran_graph.py --directory sorc/gdas.cd/sorc/oops \
    2>&1 | tee logs/phase42_oops_ingest.log
python scripts/ingest_fortran_graph.py --directory sorc/gdas.cd/sorc/vader \
    2>&1 | tee logs/phase42_vader_ingest.log
python scripts/ingest_fortran_graph.py --directory sorc/gdas.cd/sorc/saber \
    2>&1 | tee logs/phase42_saber_ingest.log
```

**Acceptance**: oops/vader/saber nodes and relationships visible in Neo4j.

---

### Step 42-8: Ingest CRTM
**Tag**: execute
**Target**: Terminal

```bash
python scripts/ingest_fortran_graph.py --directory sorc/gdas.cd/sorc/crtm \
    2>&1 | tee logs/phase42_crtm_ingest.log
```

Expected: ~2,000+ new subroutines, 90+ new modules. This fills the biggest single dependency gap.

**Acceptance**: `MATCH (m:FortranModule) WHERE m.name STARTS WITH 'crtm' RETURN COUNT(m)` >= 80.

---

### Step 42-9: Ingest Model-Specific DA (fv3-jedi, soca, ufo, ioda)
**Tag**: execute
**Target**: Terminal

```bash
for dir in fv3-jedi soca ufo ioda gsw femps; do
    python scripts/ingest_fortran_graph.py --directory "sorc/gdas.cd/sorc/$dir" \
        2>&1 | tee "logs/phase42_${dir}_ingest.log"
done
```

**Acceptance**: All 6 sub-submodules ingested. Total JEDI Fortran nodes >= 5,000.

---

### Step 42-10: Ingest JEDI Python Tools
**Tag**: execute
**Target**: Terminal

```bash
python scripts/ingest_python_graph.py 2>&1 | tee logs/phase42_python_ingest.log
```

The updated `PYTHON_DIRECTORIES` config will pick up the new JEDI paths.

**Acceptance**: New PythonModule nodes for IODA tools and UFO utilities.

---

### Step 42-11: Verify Cross-Package USES Relationships
**Tag**: validate
**Target**: Terminal (Cypher queries)

Verify that the JEDI layered architecture is captured:

```cypher
-- fv3-jedi using oops interfaces
MATCH (n)-[:USES]->(m:FortranModule)
WHERE n.file_path CONTAINS 'fv3-jedi' AND m.file_path CONTAINS 'oops'
RETURN n.name AS fv3jedi_entity, m.name AS oops_module
LIMIT 10;

-- UFO using CRTM
MATCH (n)-[:USES]->(m:FortranModule)
WHERE n.file_path CONTAINS 'ufo' AND m.name STARTS WITH 'crtm'
RETURN n.name AS ufo_entity, m.name AS crtm_module
LIMIT 10;

-- GSI calling CRTM
MATCH (n)-[:CALLS]->(c:FortranSubroutine)
WHERE n.file_path CONTAINS 'gsi_enkf' AND c.file_path CONTAINS 'crtm'
RETURN n.name AS gsi_caller, c.name AS crtm_callee
LIMIT 10;

-- Cross-package dependency summary
MATCH (n)-[:USES]->(m:FortranModule)
WHERE n.file_path CONTAINS 'gdas.cd/sorc'
WITH SPLIT(n.file_path, '/')[3] AS source_pkg, 
     SPLIT(m.file_path, '/')[3] AS target_pkg
WHERE source_pkg <> target_pkg
RETURN source_pkg, target_pkg, COUNT(*) AS use_count
ORDER BY use_count DESC;
```

**Acceptance**: Cross-package USES visible. fv3-jedi→oops, ufo→crtm, soca→oops chains present.

---

### Step 42-12: Re-Run Community Detection
**Tag**: execute
**Target**: Terminal

With 5,000-8,000 new JEDI nodes, re-run Leiden community detection:

```bash
python scripts/ingest_communities.py 2>&1 | tee logs/phase42_communities.log
```

Expected new communities: CRTM radiative transfer, oops abstract DA, fv3-jedi atmosphere DA, soca ocean DA, UFO observation operators.

**Acceptance**: Community count increases. New L1/L2 communities for JEDI subsystems.

---

### Step 42-13: Validate with MCP Tools
**Tag**: validate
**Target**: EIB MCP tools

```
find_callers_callees({ function_name: "crtm_forward", cross_language: true })
trace_execution_path({ function_name: "fv3jedi_model_step" })
get_code_context({ symbol: "ufo_radiance" })
search_architecture({ query: "JEDI data assimilation observation operators" })
find_dependencies({ target: "sorc/gdas.cd/sorc/crtm/src/CRTM_Forward_Module.f90" })
```

**Acceptance**: All 5 queries return meaningful results with JEDI/CRTM data.

---

### Step 42-14: Update Gap Analysis Report
**Tag**: document
**Target**: `docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md`

Update §3 and §8 scorecard. "JEDI ecosystem" grade should improve from C- to B+. "DA/GSI/EnKF" should reach A.

**Acceptance**: Report reflects Phase 42 completions. All remediation phases marked as addressed.

---

## 5. Validation Criteria

| Criterion | Before | After | Method |
|-----------|--------|-------|--------|
| JEDI Fortran nodes (under gdas.cd/sorc/) | ~0 | 5,000-8,000 | `WHERE file_path CONTAINS 'gdas.cd/sorc/'` |
| CRTM modules in graph | 0 | 80+ | `WHERE name STARTS WITH 'crtm'` |
| Cross-package USES edges | ~0 | 1,000+ | Cypher cross-package query |
| JEDI Python modules | ~0 | 50-100 | `WHERE file_path CONTAINS 'gdas.cd/sorc/'` |
| `find_callers_callees('crtm_forward')` | empty | results | MCP tool test |
| JEDI ecosystem scorecard grade | C- | B+ | Gap analysis report |

## 6. Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|-----------|
| JEDI uses C++ with Fortran interfaces | C++ files not parseable by fparser2 | Skip C++/C files — only parse `.F90`/`.f90`. C++ interfaces captured as USE targets. |
| oops uses abstract classes (Fortran 2003) | fparser2 may not handle all F2003 features | fparser2 supports F2003 standard. Accept partial coverage for edge cases. |
| Some sub-submodules not checked out | Missing source files | Step 42-2 initializes them. May need `git submodule update --init --recursive`. |
| CRTM has auto-generated coefficient files | Large binary-adjacent Fortran | Skip files > 100KB or with repetitive patterns. |
| Neo4j memory with 5,000+ new nodes | Heap pressure | Monitor. 5K-8K nodes is moderate. Increase heap if needed. |

## 7. Cross-References

- **Prerequisite**: Phase 39 (UFS Fortran graph — provides the cpp preprocessing pipeline)
- **Prerequisite**: Phase 38 (data quality — clean paths)
- **Gap Analysis**: `docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md` §3.1, §7-E
- **Related**: Phase 10 (original Fortran ingestion), Phase 24E (community detection), Phase 24F (cross-language bridges)
- **Related**: Phase 41 (ESMF/NUOPC docs — provides context for the coupling code that JEDI interfaces with)
- **Downstream**: With Phases 38-42 complete, the expert system covers ~90%+ of the scientific codebase
