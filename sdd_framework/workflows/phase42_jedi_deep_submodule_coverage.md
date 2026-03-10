# Phase 42: Deep Submodule Coverage — JEDI/GDAS Ecosystem

**Version**: 3.0.0
**Status**: Complete
**Created**: 2026-03-06
**Updated**: 2026-03-10 (execution complete — all ingestion, community detection, and validation done)
**Completed**: 2026-03-10
**SDD Session**: session_2026-03-10_3kfxj3
**Author**: AI Assistant + Terry McGuinness
**Dependency**: Phase 39 (UFS Fortran graph closure — reuses the cpp preprocessing pipeline)
**Gap Analysis**: [docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md](../../docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md) §3, §7-E

---

## 1. Executive Summary

The `sorc/gdas.cd/` submodule is the **data assimilation hub** of the Global Workflow. While the top-level gdas.cd code has good graph coverage (5,723 FortranSubroutines, 769 FortranModules), its deeply nested sub-submodules — the JEDI ecosystem — have partial vector coverage but **no Fortran call graph** in Neo4j.

These sub-submodules contain the actual DA algorithms (variational minimization, ensemble filters, observation operators, CRTM radiative transfer) that are called thousands of times per cycle. Without graph coverage, the expert system cannot trace execution from a J-Job through GSI/JEDI into the scientific kernels.

### Scope (verified from disk 2026-03-09)

All 17 sub-submodules under `sorc/gdas.cd/sorc/` are checked out. File counts are actuals from `find`.

| Sub-Submodule | Location | F90 Files | C++ Files | Python | Fortran LOC | Primary Lang | Neo4j Status |
|---------------|----------|-----------|-----------|--------|-------------|-------------|-------------|
| **crtm** (radiative transfer) | `sorc/gdas.cd/sorc/crtm/` | **813** | 0 | 1 | 569K | Fortran | **IN GRAPH** (109 modules) |
| **fv3-jedi-lm** (linearized model) | `sorc/gdas.cd/sorc/fv3-jedi-lm/` | **106** | 0 | 0 | 266K | Fortran | **IN GRAPH** |
| **gsw** (seawater toolbox) | `sorc/gdas.cd/sorc/gsw/` | **196** | 0 | 2 | 191K | Fortran | **IN GRAPH** |
| **gsibec** (GSI background error) | `sorc/gdas.cd/sorc/gsibec/` | **108** | 0 | 0 | 92K | Fortran | **IN GRAPH** (1,052 nodes) |
| **ufo** (observation operators) | `sorc/gdas.cd/sorc/ufo/` | 210 | 1,089 | 2 | 68K | **C++ primary** | **IN GRAPH** (F90 interfaces, 1,072 nodes) |
| **fv3-jedi** (atmosphere DA) | `sorc/gdas.cd/sorc/fv3-jedi/` | 69 | 122 | 5 | 50K | Mixed | **IN GRAPH** (613 nodes) |
| **oops** (abstract DA framework) | `sorc/gdas.cd/sorc/oops/` | 77 | 849 | 14 | 20K | **C++ primary** | **IN GRAPH** (F90 interfaces, 174 nodes) |
| **ioda** (observation database) | `sorc/gdas.cd/sorc/ioda/` | 27 | 495 | 33 | 6K | **C++ primary** | **IN GRAPH** (F90+Python) |
| **soca** (ocean DA) | `sorc/gdas.cd/sorc/soca/` | 21 | 114 | 5 | 6K | **C++ primary** | **IN GRAPH** (F90+Python) |
| **saber** (background error) | `sorc/gdas.cd/sorc/saber/` | 12 | 221 | 19 | 5K | **C++ primary** | **IN GRAPH** (F90+Python) |
| **vader** (variable transforms) | `sorc/gdas.cd/sorc/vader/` | 2 | 170 | 1 | 316 | **C++ primary** | **IN GRAPH** (F90 interfaces) |
| **bufr-query** (obs query library) | `sorc/gdas.cd/sorc/bufr-query/` | 7 | 112 | 20 | — | C++ | **IN GRAPH** (F90+Python) |
| **da-utils** (DA utilities) | `sorc/gdas.cd/sorc/da-utils/` | 0 | 25 | 8 | — | C++ | **IN GRAPH** (Python) |
| **jcb** (JEDI config builder) | `sorc/gdas.cd/sorc/jcb/` | 0 | 0 | 18 | — | Python | **IN GRAPH** (Python) |
| **spoc** (dump scripts) | `sorc/gdas.cd/sorc/spoc/` | 0 | 0 | 35 | — | Python | **IN GRAPH** (Python) |
| **land-jediincr** (land DA incr.) | `sorc/gdas.cd/sorc/land-jediincr/` | 2 | 0 | 0 | — | Fortran | **IN GRAPH** |
| **jedicmake** (cmake modules) | `sorc/gdas.cd/sorc/jedicmake/` | 0 | 0 | 0 | — | CMake | N/A |

> **Note**: `femps` does NOT exist in this checkout — removed from scope.

**Totals**: ~1,650 Fortran files (1.27M LOC) + ~3,197 C++ files (402K LOC) + ~163 Python files.

**Actual ingestion results (2026-03-10)**:
- **Fortran**: 7,214 files → 38,694 nodes (4,254 modules, 27,207 subroutines, 6,838 functions, 395 programs) + 213,224 relationships (82.7% success)
- **Python**: 459 files → 4,035 nodes (459 modules, 285 classes, 3,291 functions) + 14,976 relationships (100% success)
- **JEDI-specific**: 8,990 Fortran nodes + 188 Python modules under `gdas.cd/sorc/`
- **Communities**: 1,753 Community nodes across 5 hierarchical levels, 2,113 summaries in ChromaDB
- **Cross-package USES**: 4,971 inter-submodule edges (UFO→OOPS: 1,168, FV3-JEDI→OOPS: 533)
- **Final graph**: 95,565 nodes / 2,635,130 relationships / 2,418 community nodes

### Language Gap: C++ Core

A critical finding from the disk audit: **oops, ufo, ioda, saber, and vader are primarily C++** with thin Fortran interface layers. The Fortran parser will capture the `.F90` interfaces (which is where the cross-language CALLS/USES edges originate), but the C++ implementation code (402K LOC) requires a future C++ parser (potential Phase 45+). For now, the Fortran interfaces provide sufficient graph connectivity.

### Local-First Documentation Strategy

All sub-submodules are **checked out on disk** — no internet access needed for source code or local docs:
- **56 Python files** in `gdas.cd/ush/` (bufr2ioda converters, SOCA utilities)
- **67 YAML configs** in `gdas.cd/parm/` (operational DA templates)
- **1,921 YAML test configs** across submodules (executable documentation)
- **~70 README/doc files** (RST, Markdown) across all submodules
- **Sphinx docs** in `bufr-query/docs/` (7 RST files with full API docs)
- **Doxygen configs** in ioda, oops, saber, soca, ufo (extractable from source comments)

The only web-dependent source is the top-level JEDI ReadTheDocs (already configured in Phase 41).

### Motivation

The JEDI stack is the most complex scientific code in the repository:
- **oops** defines abstract interfaces (Increment, State, Geometry, ObsOperator)
- **fv3-jedi** and **soca** implement those interfaces for atmosphere and ocean
- **fv3-jedi-lm** provides the tangent linear and adjoint models (266K LOC — essential for 4D-Var)
- **gsibec** implements GSI background error covariance (92K LOC — bridge between legacy GSI and JEDI)
- **ufo** provides 50+ observation operators (radiance, surface, profile)
- **CRTM** has 90+ Fortran modules used in radiance assimilation (accounts for >96 USE statements in GSI)
- **ioda** manages observation data (reads BUFR, NetCDF, writes IODA format)
- **jcb** configures JEDI experiments via Python (18 files, pure-Python tool)

Without this graph, asking "What observation operators are used in the GDAS analysis?" returns nothing useful.

---

## 2. JEDI Architecture Overview

```
oops (abstract framework — 77 F90, 849 C++)
  │
  ├── fv3-jedi (atmosphere DA — 69 F90, 122 C++)
  │     ├── uses: oops interfaces
  │     ├── uses: ufo observation operators
  │     └── uses: CRTM for radiance
  │
  ├── fv3-jedi-lm (linearized model — 106 F90, pure Fortran)
  │     ├── tangent linear model for 4D-Var
  │     └── adjoint model (266K LOC)
  │
  ├── soca (ocean DA — 21 F90, 114 C++)
  │     ├── uses: oops interfaces
  │     ├── uses: ufo observation operators
  │     └── uses: gsw (seawater equations)
  │
  ├── gsibec (GSI background error — 108 F90, pure Fortran)
  │     ├── bridge between legacy GSI and JEDI
  │     └── spectral/grid transforms (92K LOC)
  │
  ├── ufo (observation operators — 210 F90, 1,089 C++)
  │     ├── conventional: aircraft, radiosonde, surface
  │     ├── radiance: CRTM-based satellite obs
  │     └── profile: GNSS-RO, ozone, wind
  │
  ├── ioda (observation data — 27 F90, 495 C++)
  │     ├── BUFR → IODA converters (Python + C++)
  │     ├── NetCDF + HDF5 I/O
  │     └── bufr-query (obs query library — 7 F90, 112 C++)
  │
  ├── saber (background error covariance — 12 F90, 221 C++)
  │     ├── BUMP (NICAS localization)
  │     └── spectral transforms
  │
  ├── vader (variable transforms — 2 F90, 170 C++)
  │     ├── virtual temperature ↔ temperature + moisture
  │     └── hydrostatic pressure from thermodynamic state
  │
  ├── jcb (JEDI config builder — 18 Python files)
  │     └── experiment configuration generation
  │
  └── CRTM (radiative transfer — 813 F90, pure Fortran)
        └── 569K LOC, largest single dependency
```

> **Language note**: oops, ufo, ioda, saber, soca, and vader are **C++-primary** with Fortran
> interface modules. The Fortran parser captures the `.F90` interface layer which contains the
> USE/CALL edges needed for cross-package graph connectivity. crtm, fv3-jedi-lm, gsibec, and
> gsw are **pure Fortran** and will be fully covered.

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

90+ Fortran modules, **813 source files** (verified from disk). Currently zero graph presence.

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

Verify all sub-submodules are checked out and count parseable files:

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow
for dir in sorc/gdas.cd/sorc/*/; do
    name=$(basename "$dir")
    f90=$(find "$dir" \( -name "*.F90" -o -name "*.f90" -o -name "*.F" -o -name "*.f" \) 2>/dev/null | wc -l)
    cpp=$(find "$dir" \( -name "*.cc" -o -name "*.cpp" -o -name "*.h" -o -name "*.hpp" \) 2>/dev/null | wc -l)
    py=$(find "$dir" -name "*.py" 2>/dev/null | wc -l)
    printf "%-20s F90=%-5s C++=%-5s PY=%-5s\n" "$name" "$f90" "$cpp" "$py"
done
# Also count gdas.cd top-level Python and YAML
echo "--- gdas.cd operational ---"
find sorc/gdas.cd/ush -name "*.py" 2>/dev/null | wc -l
find sorc/gdas.cd/parm -name "*.yaml" -o -name "*.yml" 2>/dev/null | wc -l
```

Expected (from 2026-03-09 audit): 17 sub-submodules present, ~1,650 F90 files, ~3,197 C++ files, ~163 Python files, 56 ush Python, 67 parm YAML.

**Acceptance**: File counts match expected. No uninitialized submodules. `femps` confirmed absent.

---

### Step 42-2: Initialize Missing Submodules (if needed)
**Tag**: execute
**Target**: Terminal

As of 2026-03-09, all submodules are already checked out. Run only if Step 42-1 finds gaps:

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow
# Only needed if any dirs are empty/missing:
git submodule update --init --recursive sorc/gdas.cd/sorc/crtm
git submodule update --init --recursive sorc/gdas.cd/sorc/fv3-jedi-lm
git submodule update --init --recursive sorc/gdas.cd/sorc/gsibec
git submodule update --init --recursive sorc/gdas.cd/sorc/fv3-jedi
git submodule update --init --recursive sorc/gdas.cd/sorc/soca
git submodule update --init --recursive sorc/gdas.cd/sorc/ioda
git submodule update --init --recursive sorc/gdas.cd/sorc/oops
git submodule update --init --recursive sorc/gdas.cd/sorc/saber
git submodule update --init --recursive sorc/gdas.cd/sorc/ufo
git submodule update --init --recursive sorc/gdas.cd/sorc/vader
git submodule update --init --recursive sorc/gdas.cd/sorc/gsw
git submodule update --init --recursive sorc/gdas.cd/sorc/bufr-query
```

**Acceptance**: All JEDI sub-submodules checked out with source files present.

---

### Step 42-3: Add JEDI Paths to Fortran Ingestion Config
**Tag**: implement
**Target**: `mcp_server_node/scripts/ingest_fortran_graph.py`

Append JEDI sub-submodule paths to `SUBMODULE_PATHS`. Ordered by Fortran LOC (largest first):

```python
SUBMODULE_PATHS = [
    # ... existing entries from Phase 39 ...
    # JEDI DA ecosystem — pure Fortran heavyweights (Phase 42)
    'sorc/gdas.cd/sorc/crtm',           # 813 F90, 569K LOC
    'sorc/gdas.cd/sorc/fv3-jedi-lm',    # 106 F90, 266K LOC
    'sorc/gdas.cd/sorc/gsw',            # 196 F90, 191K LOC
    'sorc/gdas.cd/sorc/gsibec',         # 108 F90,  92K LOC
    # JEDI DA ecosystem — mixed C++/Fortran (Phase 42)
    'sorc/gdas.cd/sorc/ufo',            # 210 F90,  68K LOC
    'sorc/gdas.cd/sorc/fv3-jedi',       #  69 F90,  50K LOC
    'sorc/gdas.cd/sorc/oops',           #  77 F90,  20K LOC
    'sorc/gdas.cd/sorc/ioda',           #  27 F90,   6K LOC
    'sorc/gdas.cd/sorc/soca',           #  21 F90,   6K LOC
    'sorc/gdas.cd/sorc/saber',          #  12 F90,   5K LOC
    'sorc/gdas.cd/sorc/vader',          #   2 F90
    'sorc/gdas.cd/sorc/bufr-query',     #   7 F90
    'sorc/gdas.cd/sorc/land-jediincr',  #   2 F90
    # NOTE: femps does NOT exist — omitted
    # NOTE: da-utils, jcb, jedicmake have 0 Fortran — Python/CMake only
]
```

**Acceptance**: Config updated. `--dry-run --directory sorc/gdas.cd/sorc/oops` reports 77 Fortran files found.

---

### Step 42-4: Add JEDI Python Paths to Python Ingestion Config
**Tag**: implement
**Target**: `mcp_server_node/scripts/ingest_python_graph.py`

Add all JEDI Python directories. The `gdas.cd/ush/` tree has the operational DA scripts:

```python
PYTHON_DIRECTORIES = [
    # ... existing entries (including sorc/gdas.cd/ush, sorc/gdas.cd/sorc/spoc) ...
    # JEDI operational Python — gdas.cd/ush/ subdirectories (Phase 42)
    'sorc/gdas.cd/ush/ioda',            # 20+ bufr2ioda converter scripts
    'sorc/gdas.cd/ush/ioda/bufr2ioda',  # individual converters
    'sorc/gdas.cd/ush/soca',            #  5 SOCA operational utilities
    'sorc/gdas.cd/ush/eva',             #  EVA observation YAML generators
    'sorc/gdas.cd/ush/ufoeval',         #  UFO evaluation setup scripts
    # JEDI sub-submodule Python tools (Phase 42)
    'sorc/gdas.cd/sorc/jcb/src/jcb',    # 18 files — JEDI config builder (pure Python)
    'sorc/gdas.cd/sorc/jcb/src/jcb/configuration',
    'sorc/gdas.cd/sorc/ioda/src/engines',# IODA engine Python bindings
    'sorc/gdas.cd/sorc/ioda/tools',     # IODA converter tools
    'sorc/gdas.cd/sorc/da-utils',       #  8 DA utility Python scripts
    'sorc/gdas.cd/sorc/saber',          # 19 Python files (test + tools)
    'sorc/gdas.cd/sorc/oops',           # 14 Python files (ctest harnesses)
    'sorc/gdas.cd/sorc/bufr-query',     # 20 Python files (query API + tests)
    # NOTE: sorc/gdas.cd/sorc/spoc already in config — skip
]
```

**Acceptance**: Config updated. Dry-run shows ~100+ new Python files discovered.

---

### Step 42-5: Test Preprocessing on JEDI Fortran Files
**Tag**: validate
**Target**: Terminal

JEDI Fortran uses `#ifdef` for platform portability and optional features. Test the Phase 39 preprocessing pipeline on representative **Fortran** files from each major submodule:

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node
# Pure Fortran heavyweights
python scripts/ingest_fortran_graph.py --test sorc/gdas.cd/sorc/crtm/src/CRTM_Forward_Module.f90
python scripts/ingest_fortran_graph.py --test sorc/gdas.cd/sorc/fv3-jedi-lm/src/fv3jedi_lm_mod.F90
python scripts/ingest_fortran_graph.py --test sorc/gdas.cd/sorc/gsibec/src/gsibec_mod.F90
python scripts/ingest_fortran_graph.py --test sorc/gdas.cd/sorc/gsw/toolbox/gsw_rho.f90
# Mixed C++/Fortran (test only the .F90 interfaces)
python scripts/ingest_fortran_graph.py --test sorc/gdas.cd/sorc/fv3-jedi/src/fv3jedi/Model/fv3jedi_model_mod.F90
python scripts/ingest_fortran_graph.py --test sorc/gdas.cd/sorc/soca/src/soca/Model/soca_model_mod.F90
python scripts/ingest_fortran_graph.py --test sorc/gdas.cd/sorc/oops/src/oops/generic/oops_variables_mod.F90
python scripts/ingest_fortran_graph.py --test sorc/gdas.cd/sorc/ufo/src/ufo/ufo_variables_mod.F90
```

> **Important**: Do NOT test `.h` or `.cc` files — those are C++ headers and will fail the
> Fortran parser. The parser should already skip non-Fortran extensions automatically.

**Acceptance**: All 8 Fortran files parse successfully. Any `#ifdef`-heavy files handled by the cpp pipeline.

---

### Step 42-6: Dry-Run CRTM + fv3-jedi-lm Ingestion
**Tag**: validate
**Target**: Terminal

CRTM (813 files) and fv3-jedi-lm (106 files) are the two largest pure-Fortran submodules. Test separately:

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node
python scripts/ingest_fortran_graph.py --dry-run --directory sorc/gdas.cd/sorc/crtm
python scripts/ingest_fortran_graph.py --dry-run --directory sorc/gdas.cd/sorc/fv3-jedi-lm
python scripts/ingest_fortran_graph.py --dry-run --directory sorc/gdas.cd/sorc/gsibec
```

Expect CRTM:
- 813 files attempted
- ~650+ parsed successfully (pure Fortran, some auto-generated coefficient files may be skipped)
- ~2,000+ subroutines, 90+ modules

Expect fv3-jedi-lm:
- 106 files attempted, ~90+ parsed
- tangent linear / adjoint routines

Expect gsibec:
- 108 files attempted, ~90+ parsed
- background error covariance routines

**Acceptance**: >= 80% parse success rate for each.

---

### Step 42-7: Ingest JEDI Core (oops, vader, saber, gsibec)
**Tag**: execute
**Target**: Terminal

Start with the foundational abstract layer + GSI bridge:

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node
python scripts/ingest_fortran_graph.py --directory sorc/gdas.cd/sorc/oops \
    2>&1 | tee logs/phase42_oops_ingest.log
python scripts/ingest_fortran_graph.py --directory sorc/gdas.cd/sorc/vader \
    2>&1 | tee logs/phase42_vader_ingest.log
python scripts/ingest_fortran_graph.py --directory sorc/gdas.cd/sorc/saber \
    2>&1 | tee logs/phase42_saber_ingest.log
python scripts/ingest_fortran_graph.py --directory sorc/gdas.cd/sorc/gsibec \
    2>&1 | tee logs/phase42_gsibec_ingest.log
```

**Acceptance**: oops/vader/saber/gsibec nodes and relationships visible in Neo4j. gsibec should add ~108 files worth of subroutines.

---

### Step 42-8: Ingest CRTM
**Tag**: execute
**Target**: Terminal

CRTM is the largest single submodule (813 Fortran files, 569K LOC). Ingest separately to monitor:

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node
python scripts/ingest_fortran_graph.py --directory sorc/gdas.cd/sorc/crtm \
    2>&1 | tee logs/phase42_crtm_ingest.log
```

Expected: ~2,000+ new subroutines, 90+ new modules. This fills the biggest single dependency gap.

**Acceptance**: `MATCH (m:FortranModule) WHERE m.name STARTS WITH 'crtm' RETURN COUNT(m)` >= 80.

---

### Step 42-9: Ingest Model-Specific DA + remaining submodules
**Tag**: execute
**Target**: Terminal

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node
for dir in fv3-jedi fv3-jedi-lm soca ufo ioda gsw bufr-query land-jediincr; do
    echo "=== Ingesting $dir ==="
    python scripts/ingest_fortran_graph.py --directory "sorc/gdas.cd/sorc/$dir" \
        2>&1 | tee "logs/phase42_${dir}_ingest.log"
done
```

**Acceptance**: All 8 sub-submodules ingested. fv3-jedi-lm alone should add ~100+ files. Total JEDI Fortran nodes >= 3,500.

---

### Step 42-10: Ingest JEDI Python Tools
**Tag**: execute
**Target**: Terminal

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node
python scripts/ingest_python_graph.py 2>&1 | tee logs/phase42_python_ingest.log
```

The updated `PYTHON_DIRECTORIES` config will pick up:
- `gdas.cd/ush/ioda/` — 20+ bufr2ioda converters
- `gdas.cd/ush/soca/` — SOCA operational utilities
- `gdas.cd/sorc/jcb/` — JEDI config builder (18 files)
- `gdas.cd/sorc/bufr-query/` — obs query Python API (20 files)
- `gdas.cd/sorc/da-utils/` — DA utility scripts (8 files)
- plus oops, saber, ioda Python test harnesses

**Acceptance**: ~100+ new PythonModule nodes. `jcb` and `bufr2ioda` converters visible in graph.

---

### Step 42-10b: Ingest Local Documentation into ChromaDB
**Tag**: execute
**Target**: Terminal

Ingest all on-disk documentation — **no internet needed**:

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node
# Ingest README files from all JEDI sub-submodules
find /mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow/sorc/gdas.cd/sorc \
    -maxdepth 2 -name "README*.md" -exec echo {} \;
# Ingest bufr-query Sphinx docs (RST)
find /mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow/sorc/gdas.cd/sorc/bufr-query/docs \
    -name "*.rst" -exec echo {} \;
# Ingest IODA engine docs
find /mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow/sorc/gdas.cd/sorc/ioda/src/engines/docs \
    -name "*.md" -exec echo {} \;
# Ingest operational YAML configs as documentation
find /mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow/sorc/gdas.cd/parm \
    -name "*.yaml" -exec echo {} \;
```

> Use the appropriate ingestion script for each format (markdown, RST, YAML).
> These are all local files — no web crawling or rate-limiting issues.

**Acceptance**: ~200+ new vector documents in ChromaDB. Search for "CRTM build" returns the CRTM README. Search for "bufr2ioda" returns the bufr-query docs.

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

With 3,500–5,500 new JEDI nodes, re-run Leiden community detection:

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node
python scripts/ingest_communities.py 2>&1 | tee logs/phase42_communities.log
```

Expected new communities: CRTM radiative transfer, oops abstract DA, fv3-jedi atmosphere DA, fv3-jedi-lm TL/AD, gsibec background error, soca ocean DA, UFO observation operators.

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
| JEDI Fortran nodes (under gdas.cd/sorc/) | ~0 | 3,500–5,500 | `WHERE file_path CONTAINS 'gdas.cd/sorc/'` |
| CRTM modules in graph | 0 | 80+ | `WHERE name STARTS WITH 'crtm'` |
| fv3-jedi-lm routines in graph | 0 | 100+ | `WHERE file_path CONTAINS 'fv3-jedi-lm'` |
| gsibec routines in graph | 0 | 100+ | `WHERE file_path CONTAINS 'gsibec'` |
| Cross-package USES edges | ~0 | 1,000+ | Cypher cross-package query |
| JEDI Python modules (incl. ush/) | ~0 | 100–160 | `WHERE file_path CONTAINS 'gdas.cd'` |
| Local docs in ChromaDB | ~0 | 200+ | Vector document count |
| `find_callers_callees('crtm_forward')` | empty | results | MCP tool test |
| JEDI ecosystem scorecard grade | C- | B+ | Gap analysis report |

## 6. Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|-----------|
| **C++ gap**: oops, ufo, ioda, saber, vader are C++-primary (402K LOC) | Core abstract DA interfaces not in graph | Fortran interface modules (`.F90`) still capture USE/CALL edges for graph connectivity. C++ parser is a potential Phase 45+ addition. |
| JEDI uses C++ with Fortran interfaces | C++ files not parseable by fparser2 | Parser auto-skips non-`.F90`/`.f90` extensions. No manual filtering needed. |
| oops uses abstract classes (Fortran 2003) | fparser2 may not handle all F2003 features | fparser2 supports F2003 standard. Accept partial coverage for edge cases. |
| fv3-jedi-lm has 266K LOC of generated TL/AD code | May include repetitive patterns | Monitor parse time. Skip files > 100KB if needed. |
| CRTM has auto-generated coefficient files (569K LOC) | Large file count, some binary-adjacent | Skip files > 100KB or with repetitive coefficient data patterns. |
| All submodules already checked out (verified 2026-03-09) | Low risk | Step 42-2 is a safety net only. |
| Neo4j memory with 3,500–5,500 new nodes | Moderate heap pressure | 5K nodes is well within limits. Monitor during CRTM ingestion (largest batch). |

## 7. Cross-References

- **Prerequisite**: Phase 39 (UFS Fortran graph — provides the cpp preprocessing pipeline)
- **Prerequisite**: Phase 38 (data quality — clean paths)
- **Gap Analysis**: `docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md` §3.1, §7-E
- **Related**: Phase 10 (original Fortran ingestion), Phase 24E (community detection), Phase 24F (cross-language bridges)
- **Related**: Phase 41 (ESMF/NUOPC docs — provides context for the coupling code that JEDI interfaces with)
- **Future**: Phase 45+ (C++ parser for oops/ufo/ioda/saber/vader core implementations)
- **Downstream**: With Phases 38-42 complete, the expert system covers ~90%+ of the scientific Fortran codebase + operational Python

## 8. Disk Audit Summary (2026-03-09)

All data for Phase 42 is available locally — **no internet access required**.

| Category | Files on Disk | Ingestion Target |
|----------|--------------|------------------|
| Fortran source (.F90/.f90/.F/.f) | 1,650 | Neo4j (graph) |
| Python source (.py) | 163 (submodules) + 56 (ush/) | Neo4j (graph) |
| YAML configs (parm/) | 67 | ChromaDB (vectors) |
| YAML test configs | 1,921 | ChromaDB (vectors, selective) |
| README/doc files (MD, RST) | ~70 | ChromaDB (vectors) |
| Sphinx docs (bufr-query) | 7 RST files | ChromaDB (vectors) |
| C++ source (future) | 3,197 files, 402K LOC | Deferred to Phase 45+ |
