# EIB MCP Knowledge Base — Complete Gap Analysis

**Date:** March 6, 2026  
**Version:** 1.0.0  
**Author:** EIB MCP Team  
**Scope:** Full survey of ingestion scripts, current vector/graph state, submodule coverage, and external library gaps

---

## Executive Summary

The EIB MCP knowledge base contains **66,552 ChromaDB documents** across 5 collections and **589,396 Neo4j relationships** covering Fortran, Python, Shell, and documentation. However, significant gaps exist:

1. **Neo4j Fortran graph covers only 5 of 14 sorc/ submodules** — the entire `ufs_model.fd` tree (UFSATM, MOM6, CICE, CMEPS, WW3, etc.) has **zero** Fortran graph nodes despite having 3,503 Fortran files
2. **ChromaDB vectors exist for all submodules** but with **inconsistent path prefixes** — 50.2% use `global-workflow/` (checkout-specific), 49.7% use `sorc/` (correct)
3. **Neo4j File nodes use absolute paths** from an old checkout (`/mcp_rag_eib/global-workflow_MCP_node.js-RAG/`)
4. **149 config files**, **78 CI YAML files**, and **155 parm files** are not ingested into any collection
5. **External library documentation** is partially covered (NCEPLIBS docs ingested) but the **ESMF/NUOPC framework** — the coupling backbone — has no dedicated documentation ingestion

---

## 1. Current Knowledge Base State

### 1.1 ChromaDB Collections

| Collection | Documents | Content |
|-----------|-----------|---------|
| `code-with-context-v8-0-0` | 58,761 | Code chunks (Fortran/Python/Shell) with MPNet 768-dim embeddings |
| `jjobs-v8-0-0` | 700 | J-Job scripts (dev/jobs/) |
| `community-summaries` | 1,648 | GraphRAG hierarchical community summaries |
| `global-workflow-docs-v8-0-0` | 5,409 | External documentation (24 sources, 623 unique URLs) |
| `ee2-standards-v5-0-0-enhanced` | 34 | EE2/NCO production standards |
| **TOTAL** | **66,552** | |

### 1.2 Neo4j Graph Nodes

| Label | Count | Notes |
|-------|-------|-------|
| FortranSubroutine | 13,537 | Only gdas.cd, gsi_enkf, gsi_utils, gsi_monitor, gfs_utils |
| FortranModule | 1,539 | Same 5 submodules only |
| FortranFunction | 2,355 | |
| FortranProgram | 169 | Includes placeholder nodes from cross-language bridges |
| PythonModule | 624 | Good coverage of ush/, dev/, sorc/gdas.cd, wxflow |
| PythonClass | 248 | |
| PythonFunction | 3,267 | |
| ShellScript | 264 | J-Jobs (89), ush (63), ex-scripts (40), sourced (51) |
| EnvironmentVariable | 2,489 | |
| Community | 1,036 | L0: 694, L1: 175, L2: 86, L3: 81 |
| File | 2,744 | All 178 use absolute paths from old checkout |

### 1.3 Relationship Counts

| Type | Count | What it connects |
|------|-------|-----------------|
| CALLS | 439,919 | Function-to-function call graph |
| USES | 91,285 | Fortran USE module dependencies |
| MEMBER_OF | 21,559 | Community membership |
| DEFINES | 9,753 | Module/class defines function |
| IMPORTS | 8,034 | Python imports |
| DEPENDS_ON_ENV | 5,522 | Script→environment variable |
| AUTHORED | 2,880 | Developer→commit |
| HAS_METHOD | 2,579 | Class→method |
| DOC_REFERENCES | 1,906 | Documentation cross-references |
| INTERACTS_WITH | 1,297 | Component interactions |
| INVOKES | 243 | Shell→Python cross-language |
| EXECUTES | 65 | Shell→Fortran cross-language |

---

## 2. Ingestion Script Inventory

### 2.1 Active Scripts (28 total)

| Script | Target | Database | Status |
|--------|--------|----------|--------|
| **ingest_code_v8.py** | All code (F90/py/sh) → vectors | ChromaDB | Active, SPOT v8 |
| **ingest_fortran_graph.py** | Fortran AST → graph (fparser2) | Neo4j | Active, Phase 10 |
| **ingest_shell_graph_v8.py** | Shell scripts → graph | Neo4j | Active, Phase 27B |
| **ingest_python_graph.py** | Python AST → graph | Neo4j | Active, Phase 24F |
| **ingest_cross_language_bridges.py** | Shell→Fortran/Python edges | Neo4j | Active, Phase 27I/J |
| **ingest_jjobs_v8.py** | J-Job scripts → vectors | ChromaDB | Active, v8 |
| **ingest_documentation_v8.py** | External docs → vectors | ChromaDB | Active, v8 |
| **ingest_ee2_enhanced_v5.py** | EE2 standards → vectors | ChromaDB | Active, v5 |
| **ingest_env_variables.py** | Env vars → graph | Neo4j | Active |
| **ingest_ci_test_cases.py** | CI test YAML → vectors | ChromaDB | Active |
| **ingest-submodules.js** | Submodule structure → graph | Neo4j | Active, Phase 0 |
| **ingest-code.js** | Legacy JS code ingestion | Neo4j | Superseded by v8.py |
| **ingest-cmake.js** | CMake build targets → graph | Neo4j | Active |
| **ingest-github-metadata.js** | GitHub commits/PRs → graph | Neo4j | Active |
| **ingest_code_embeddings.py** | Code → vector embeddings | ChromaDB | Superseded by v8 |
| **ingest_code_graph_enriched_v6.py** | Older graph-enriched code | Both | Superseded by v8 |
| **documentation_sources_config.py** | SPOT config for all doc URLs | Config | Active, v7 |
| **reingest_all_with_phase2.sh** | Full re-ingestion orchestrator | Both | Active |

### 2.2 Code v8 Scan Directories

```python
CODE_DIRECTORIES = [
    'dev/scripts',   # ex-scripts (exgdas_*, exgfs_*)
    'dev/jobs',      # J-Jobs
    'ush',           # Utility shell scripts
    'sorc',          # Source code (Fortran, C) — recursive
    'workflow',      # Workflow Python code
    'scripts',       # Legacy scripts
]
```

### 2.3 Fortran Graph Scan Directories

```python
FORTRAN_DIRECTORIES = ['sorc', 'ush']
SUBMODULE_PATHS = [
    'sorc/ufs_model.fd',   # BUG: fparser2 fails on many UFS files
    'sorc/gsi.fd',         # BUG: wrong name (actual: gsi_enkf.fd)
    'sorc/gdas.fd',        # BUG: wrong name (actual: gdas.cd)
    'sorc/ufs_utils.fd',
    'sorc/gfs_wafs.fd',    # Does not exist in current repo
    'sorc/fit2obs.fd',     # Does not exist in current repo
]
```

---

## 3. Submodule Coverage Analysis

### 3.1 Global-Workflow Submodule Tree (64 recursive submodules)

#### Top-Level Submodules (14 direct under sorc/)

| Submodule | Actual Files | ChromaDB Vectors | Neo4j Fortran Graph | Gap |
|-----------|-------------|-----------------|-------------------|-----|
| **sorc/gdas.cd** | 2,036 (1647 F, 229 py, 160 sh) | 8,197 chunks, 1,410 files | 5,723 subs, 769 mods | **GOOD** |
| **sorc/gsi_enkf.fd** | 827 (799 F, 2 py, 26 sh) | 2,945 chunks, 455 files | 3,279 subs, 410 mods | **GOOD** |
| **sorc/ufs_model.fd** | 3,910 (3503 F, 217 py, 190 sh) | 13,601 chunks | **13,320 subs, 2,186 mods** (Phase 39) | **GOOD** |
| **sorc/ufs_utils.fd** | 644 (506 F, 8 py, 130 sh) | 1,913 chunks | **1,810 subs, 398 mods** (Phase 39) | **GOOD** |
| **sorc/gsi_utils.fd** | 449 (395 F, 22 py, 32 sh) | 1,137 chunks, 302 files | 505 subs, 47 mods | **GOOD** |
| **sorc/gsi_monitor.fd** | 251 (134 F, 0 py, 117 sh) | 326 chunks, 143 files | 339 subs, 10 mods | **GOOD** |
| **sorc/nexus.fd** | 112 (86 F, 16 py, 10 sh) | 609 chunks | **661 subs, 74 mods** (Phase 39) | **GOOD** |
| **sorc/gfs_utils.fd** | 83 (74 F, 0 py, 9 sh) | small | 149 subs, 20 mods | **GOOD** |
| **sorc/wxflow** | 46 (0 F, 46 py, 0 sh) | 332 chunks | N/A (Python only) | **GOOD** |
| **sorc/verif-global.fd** | 47 (0 F, 31 py, 16 sh) | small | N/A (Python only) | PARTIAL |

#### ufs_model.fd Sub-Components (Phase 39: CLOSED — 81.4% parse rate)

| Component | Fortran Files | Python | Shell | ChromaDB | Neo4j Graph |
|-----------|--------------|--------|-------|----------|-------------|
| **UFSATM** (FV3 atmosphere) | 1,286 | 161 | 82 | 5,575 chunks | **~4,800 nodes** |
| **MOM6** (ocean) | 526 | 10 | 23 | 2,893 chunks | **~3,200 nodes** |
| **AQM/CMAQ** (air quality) | 853 | 2 | 0 | 1,573 chunks | **~2,500 nodes** |
| **WW3** (wave) | 298 | 3 | 28 | 954 chunks | **~1,800 nodes** |
| **CICE** (sea ice) | 180 | 6 | 9 | 529 chunks | **~900 nodes** |
| **CMEPS** (mediator) | 69 | 7 | 0 | 197 chunks | **~400 nodes** |
| **LM4** (land) | 59 | 0 | 0 | 765 chunks | **~350 nodes** |
| **CDEPS** (data components) | 53 | 2 | 0 | 301 chunks | **~300 nodes** |
| **HYCOM** (hybrid ocean) | 69 | 0 | 1 | 138 chunks | **~400 nodes** |
| **GOCART** (aerosol) | 33 | 2 | 0 | 140 chunks | **~200 nodes** |
| **NOAHMP** (land surface) | 21 | 1 | 1 | small | **~130 nodes** |
| **stochastic_physics** | 26 | 1 | 7 | small | **~160 nodes** |
| **fire_behavior** | 28 | 0 | 3 | 124 chunks | **~170 nodes** |
| **driver** (UFS.F90, UFSDriver) | 2 | 0 | 0 | small | **~10 nodes** |

**Phase 39 resolution:** Added CPP preprocessing pipeline (`cpp -traditional-cpp -nostdinc -P`) to `ingest_fortran_graph.py` v1.2.0, with `strip_directives_fallback()` for files where `cpp` fails. Also caught fparser2 `SystemExit(1)` on template files. Total: 2,905/3,570 files parsed (81.4%), yielding 13,320 subroutines, 2,186 modules, 3,463 functions, 100 programs, 87,602 CALLS, 22,454 USES edges. Cross-component coupling confirmed: MOM6→FMS (2,364), CMEPS→CDEPS (310), UFS→ufs-utils (6,078).

### 3.2 Orchestration Layer Coverage

| Area | Total Files | In Graph | In Vectors | Gap |
|------|------------|----------|-----------|-----|
| J-Jobs (`dev/jobs/`) | 90 | 89 ShellScript nodes | 700 chunks | **GOOD** |
| Ex-Scripts (`dev/scripts/`) | 82 | 40 ShellScript nodes | 61 chunks | **PARTIAL** — 42 ex-scripts missing from graph |
| USH scripts (`ush/`) | 63 shell | 63 ShellScript nodes | few | **GOOD** for graph, LOW vectors |
| Config files (`dev/parm/`) | 155 | **0** | **0** | **MISSING** |
| Workflow Python (`dev/workflow/`) | 45 | 37 PythonModule nodes | few | **PARTIAL** |
| CI YAML (`dev/ci/`) | 78 | **0** | **0** | **MISSING** |

---

## 4. Data Quality Issues

> **Status: RESOLVED (Phase 38, 2026-03-06)**
> All critical data quality issues below have been fixed. See remediation notes.

### 4.1 Path Prefix Inconsistency — FIXED

~~The same file appears with different path prefixes depending on which ingestion script created the entry.~~

| Database | Node/Doc Type | Path Convention | Count | Status |
|----------|--------------|----------------|-------|--------|
| ChromaDB code | file_path | `global-workflow/sorc/...` | ~~29,495~~ → 0 | **FIXED** by `fix_chromadb_paths.py` |
| ChromaDB code | file_path | `sorc/...`, `dev/...`, `ush/...` | 58,761 (100%) | Correct |
| Neo4j File | path | relative (`scripts/`, `ush/`, `sorc/`, `dev/`) | 2,709 (98.7%) | Correct |
| Neo4j File | path | variable refs (`${USHgfs}/...`) | 35 (1.3%) | Expected (shell variable references) |
| Neo4j Fortran | file_path | `sorc/...` | ~13,000 | Correct |
| Neo4j Python | file_path | `sorc/`, `dev/`, `ush/` | ~362 | Correct |
| Neo4j Shell | path | `dev/`, `ush/`, `scripts/` | 274 | Correct |

**Prevention:** Path normalization guard added to `ingest_code_v8.py` to strip leading repo directory names on future ingestions.

### 4.2 Shell Script Parse Artifacts — FIXED

~~The ShellScript graph contained ~60 spurious nodes from regex parsing errors.~~

**Remediation:** 42 spurious nodes purged by `purge_shell_artifacts.py`. Source regex in `ingest_shell_graph_v8.py` tightened to require path-like structure (must contain `/` or shell extension). Post-filter added to reject flags, wildcards, and error messages.

### 4.3 Stale File Nodes — ALREADY RESOLVED

~~178 `File` nodes referenced an old checkout path.~~ Audit found 0 stale nodes — this issue was resolved in a prior phase. All 2,744 File nodes now use correct relative paths.

---

## 5. External Library Gaps

### 5.1 Fortran External Libraries (USE'd but not in codebase)

| Library | USE Count | Doc Ingested? | Code Available? | Priority |
|---------|-----------|--------------|----------------|----------|
| **ESMF** (Earth System Modeling Framework) | 69+ | **NO** | External | **CRITICAL** — coupling backbone |
| **NUOPC** (National Unified Operational Prediction Capability) | 5+ | **NO** | External | **CRITICAL** — component model interface |
| **MPI** / MPI_F08 | 93+ | **NO** | System library | HIGH — all parallel comms |
| **NetCDF** | 362+ | **NO** | System library | HIGH — all I/O |
| **CRTM** (Community Radiative Transfer Model) | 96+ (90 submodules) | **NO** | In gdas.cd/sorc/crtm | MEDIUM — in submodule |
| **FMS/MPP** (GFDL Flexible Modeling System) | 50+ | **NO** | External | HIGH — MOM6/FV3 dependency |
| **NEMSIO** | 62+ | Partial (9 chunks) | External | MEDIUM |
| **NCEPLIBS set** (BUFR, IP, W3EMC, G2, BACIO, SIGIO, SFCIO, SP) | varies | **YES** (docs ingested) | External build deps | **GOOD** |
| **HDF5** | referenced via NetCDF | **NO** | System library | LOW |
| **OpenMP** (omp_lib) | used in FV3/MOM6 | **NO** | System | LOW |

### 5.2 Python External Libraries

| Library | Import Count | Doc Ingested? | Priority |
|---------|-------------|--------------|----------|
| **wxflow** | 176 | YES (92 chunks) | GOOD |
| **numpy** | 98 | NO | LOW (well-known) |
| **matplotlib** | 49 | NO | LOW |
| **pyiodaconv** / **pyioda** | 35 / 31 | NO | HIGH — JEDI I/O layer |
| **netCDF4** | 12 | NO | MEDIUM |
| **yaml** (PyYAML) | 14 | NO | LOW |
| **cartopy** | 12 | NO | LOW |
| **pandas** | 15 | NO | LOW |
| **metplus** | 8 | NO | HIGH — verification framework |

---

## 6. Documentation Coverage

### 6.1 Ingested Sources (35 sources, ~1,050 URLs, 19,741 chunks)

| Source | Chunks | URLs | Status |
|--------|--------|------|--------|
| **esmf-user-guide** | ~10,000 | ~150 | **NEW (Phase 41)** — ESMF API + NUOPC coupling |
| spack | 1,933 | 97 | Over-represented |
| nceplibs-bufr | 487+ | ~100 | Good (expanded Phase 41) |
| nceplibs-ip | 366+ | ~80 | Good (expanded Phase 41) |
| nceplibs-g2 | 255+ | ~80 | Good (expanded Phase 41) |
| ufs-weather-model | 249 | 38 | Good |
| ecflow | 223 | 42 | Good |
| nceplibs-w3emc | 220+ | ~80 | Good (expanded Phase 41) |
| **ww3-wiki** | ~200 | 50 | **NEW (Phase 41)** — WW3 wave model wiki |
| **fv3-docs** | ~200 | 50 | **NEW (Phase 41)** — FV3/GFDL cubed sphere wiki |
| global-workflow | 171 | 21 | **LOW** — only 21 pages |
| fortran-best-practices | 162 | 18 | OK |
| spack-stack | 162 | 35 | Good |
| nceplibs-g2tmpl | 158+ | ~16 | Good |
| wgrib2 | 156+ | ~30 | Good |
| ee2-standards | 116 | 3 | Supplemented by RST local ingest |
| jedi-docs | 107 | 30 | Good |
| pyflow | 103 | 7 | Good |
| nceplibs-bacio | 95+ | ~20 | Good |
| wxflow | 92 | 22 | Good |
| ufs-utils | 90 | 3 | **LOW** — only 3 pages |
| rocoto | 74 | 1 | **LOW** — only 1 page |
| fv3-dynamical-core | 71 | 17 | Deprecated — replaced by fv3-docs |
| pep8 | 42 | 1 | OK |
| google-shell-style | 36 | 1 | OK |
| numpy-docstrings | 31 | 1 | OK |
| nceplibs-nemsio | 9 | few | **LOW** |
| **nuopc-layer-reference** | ~500 | ~20 | **NEW (Phase 41)** — NUOPC reference |
| **cmeps** | ~10 | 1 | **NEW (Phase 41)** — small site |
| nceplibs-sfcio | 1 | 1 | **VERY LOW** |
| nceplibs-sigio | 1 | 1 | **VERY LOW** |

### 6.2 Missing/Incomplete Documentation Sources

| Source | Priority | URL | Status |
|--------|----------|-----|--------|
| **MOM6 Documentation** | HIGH | https://mom6.readthedocs.io/en/main/ | Rate-limited (429) — retry needed |
| **CICE Documentation** | HIGH | https://cice-consortium-cice.readthedocs.io/ | Rate-limited (429) — retry needed |
| **GOCART Documentation** | MEDIUM | https://geos-chem.readthedocs.io/ | Rate-limited (429) — retry needed |
| **CCPP Tech Docs** | MEDIUM | https://ccpp-techdoc.readthedocs.io/ | Rate-limited (429) — retry needed |
| **UPP Documentation** | MEDIUM | https://upp.readthedocs.io/ | Rate-limited (429) — retry needed |
| **METplus Documentation** | MEDIUM | https://metplus.readthedocs.io/ | Rate-limited (429) — retry needed |
| **pyioda/ioda-converters** | MEDIUM | JEDI project docs | Data assimilation I/O |

> **Note**: 6 ReadTheDocs-hosted sources were rate-limited (HTTP 429) during Phase 41 ingestion.
> These sources are configured in `documentation_sources_config.py` and will be ingested on next run.

---

## 7. Prioritized Remediation Plan

### Phase A: Fix Data Quality (No new ingestion needed)

| Task | Impact | Effort |
|------|--------|--------|
| **A1.** Normalize ChromaDB paths — strip `global-workflow/` prefix from 29,495 docs | Fixes 50% of path mismatches | Script |
| **A2.** Update Neo4j File nodes — replace old absolute paths with repo-relative | Fixes 178 stale nodes | Script |
| **A3.** Purge spurious ShellScript nodes (~60 garbage entries) | Cleaner graph queries | Cypher DELETE |
| **A4.** Add missing ex-scripts to graph (42 of 82 missing) | Better orchestration tracing | Re-run shell ingestion |

### Phase B: Close Neo4j Fortran Graph Gap (~3,500 Fortran files)

| Task | Impact | Effort |
|------|--------|--------|
| **B1.** Fix `ingest_fortran_graph.py` SUBMODULE_PATHS (wrong names: `gsi.fd` → `gsi_enkf.fd`, `gdas.fd` → `gdas.cd`) | Config fix | Trivial |
| **B2.** Handle C preprocessor directives in fparser2 pipeline — run `cpp -traditional-cpp` before parsing | Unblocks UFS/MOM6/CMEPS Fortran parsing | Medium |
| **B3.** Ingest `sorc/ufs_model.fd/` Fortran into Neo4j graph | +3,503 files, UFSATM/MOM6/CICE/CMEPS/WW3 call graphs | Large |
| **B4.** Ingest `sorc/ufs_utils.fd/` Fortran into Neo4j graph | +506 files, chgres_cube and utility call graphs | Medium |
| **B5.** Ingest `sorc/nexus.fd/` Fortran into Neo4j graph | +86 files, AQM/emissions | Small |
| **B6.** Re-run community detection after new Fortran nodes added | Updated L0-L3 community summaries | Medium |

### Phase C: Ingest Missing File Types

| Task | Impact | Effort |
|------|--------|--------|
| **C1.** Ingest `dev/parm/config.*` files (149 files) | Config→env var→script tracing | Medium |
| **C2.** Ingest CI YAML test definitions (78 files) | Test case searchability | Small |
| **C3.** Ingest Jinja2 templates (`.j2` files) | Template→config tracing | Small |
| **C4.** Ingest XML workflow definitions if present | Rocoto XML → job dependency graph | Small |

### Phase D: Close External Library Documentation Gaps — ✅ DONE (Phase 41)

| Task | Impact | Status |
|------|--------|--------|
| **D1.** Add ESMF User Guide to `documentation_sources_config.py` | Coupling framework knowledge | ✅ Done — ~10,000 chunks |
| **D2.** Add NUOPC Layer Reference | Component interface patterns | ✅ Done — ~500 chunks |
| **D3.** Add CMEPS mediator docs | Inter-model data exchange | ✅ Done — ~10 chunks (small site) |
| **D4.** Add MOM6, CICE, WW3 ReadTheDocs | Model-specific knowledge | ⚠️ Partial — WW3 + FV3 done; MOM6/CICE rate-limited |
| **D5.** Add CCPP tech docs | Physics parameterization framework | ⚠️ Rate-limited — configured, retry needed |
| **D6.** Add UPP and METplus docs | Post-processing and verification | ⚠️ Rate-limited — configured, retry needed |

### Phase E: Deep Submodule Coverage (JEDI/GDAS ecosystem)

| Task | Impact | Effort |
|------|--------|--------|
| **E1.** Ingest sorc/gdas.cd sub-submodules (fv3-jedi, soca, ioda, oops, saber, ufo, vader) | JEDI DA system call graphs | Large |
| **E2.** Ingest CRTM Fortran (sorc/gdas.cd/sorc/crtm) — 90+ modules used in GSI | Radiative transfer call graph | Medium |
| **E3.** Review sorc/nexus.fd/HEMCO (GEOS-Chem emissions) | Chemical emissions | Small |

---

## 8. Coverage Summary Scorecard

| Domain | Vector (ChromaDB) | Graph (Neo4j) | Documentation | Overall |
|--------|-------------------|---------------|--------------|---------|
| **Orchestration** (J-Jobs, ex-scripts, ush, configs) | 85% | 75% | 80% | **B+** |
| **DA/GSI/EnKF** (gsi_enkf.fd, gdas.cd) | 90% | 90% | 70% | **A-** |
| **UFS Atmosphere** (UFSATM, FV3, CCPP) | 70% vectors | **80% graph** (Phase 39) | **60%** (Phase 41) | **B+** |
| **UFS Ocean** (MOM6) | 65% vectors | **80% graph** (Phase 39) | **25%** (Phase 41, partial) | **C+** |
| **UFS Coupling** (CMEPS, CDEPS, driver) | 60% vectors | **75% graph** (Phase 39) | **80%** (Phase 41 ESMF/NUOPC) | **B** |
| **UFS Sea Ice** (CICE) | 55% vectors | **80% graph** (Phase 39) | **10%** (rate-limited) | **C+** |
| **UFS Waves** (WW3) | 50% vectors | **80% graph** (Phase 39) | **60%** (Phase 41 wiki) | **B-** |
| **UFS Utilities** (ufs_utils.fd) | 60% vectors | **85% graph** (Phase 39) | 50% | **B** |
| **Air Quality** (AQM/CMAQ) | 55% vectors | **75% graph** (Phase 39) | 0% | **C** |
| **JEDI ecosystem** (fv3-jedi, soca, ioda, etc.) | 40% vectors | partial | 50% | **C-** |
| **External libs** (ESMF, NUOPC, FMS, MPI) | **80%** (Phase 41) | 0% | **80%** (Phase 41) | **B** |
| **wxflow** | 95% | 90% | 90% | **A** |
| **Build system** (CMake, spack-stack) | 30% | CMake nodes | 90% | **B** |
| **Path consistency** | 100% correct | 99% correct | N/A | **A** |

### Bottom Line

The knowledge base is strong for **orchestration, data assimilation, and coupling frameworks** (ESMF/NUOPC). Phase 41 added **14,332 new documentation chunks** (265% growth) covering ESMF API references, NUOPC coupling patterns, WW3 wave model wiki, and FV3 dynamics wiki. Six ReadTheDocs sources (MOM6, CICE, GOCART, CCPP, UPP, METplus) were rate-limited during ingestion — these are configured and will be ingested on next retry. The UFS Fortran graph (Phase 39) combined with ESMF/NUOPC documentation (Phase 41) closes the critical coupling framework blind spot.
