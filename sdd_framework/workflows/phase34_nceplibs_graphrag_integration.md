# SDD: Phase 34 — NCEPLIBS GraphRAG Integration

**Version:** 1.0.0
**Created:** 2026-02-26
**Author:** Terry McGuinness + AI Assistants
**Status:** SPEC COMPLETE — Ready for Execution
**Execution Mode:** ISD (Interactive Supervised Development)
**Builds On:** Phase 24 (GraphRAG Fusion), Phase 24E (Hierarchical Communities), Phase 24F (Cross-Language Integration), Phase 28 (GraphRAG Acceleration)
**Audience:** NCEPLIBS Team, MCP-RAG Development Team, Global Workflow Developers

---

## 1. Executive Summary

This phase integrates the NCEPLIBS library ecosystem into the MCP-RAG GraphRAG knowledge graph, enabling AI coding agents to trace execution paths from Global Workflow J-Jobs through to the individual NCEPLIBS Fortran subroutines they ultimately call. Today, NCEPLIBS exists as an invisible boundary in the graph — code on the consumer side (Global Workflow) and documentation on the API side (Doxygen) are disconnected. This phase bridges that gap by ingesting NCEPLIBS source code directly into Neo4j and linking it to the existing 589K-relationship Global Workflow graph.

### What This Enables

| Question | Today | After Phase 34 |
|----------|-------|----------------|
| "What does `ufbint` do?" | ChromaDB returns Doxygen description | Graph shows every GW subroutine that CALLS it + Doxygen docs |
| "What breaks if we upgrade NCEPLIBS-bufr?" | No answer | Traces ExternalLibrary → DEPENDS_ON → Executable → Component |
| "Show the execution chain from JGFS_ATMOS_ANALYSIS to BUFR encoding" | Stops at GW boundary | Full cross-repo trace: J-Job → Shell → Executable → Fortran USE → NCEPLIBS subroutine |
| "Which NCEPLIBS functions does NCEPpost use?" | Manual CMakeLists.txt reading | `find_dependencies("ncep_post")` returns complete library list with API functions |
| "What version of w3emc does WCOSS2 use vs Hera?" | Manual .ver file comparison | Graph query: platform-specific version edges |

---

## 2. Current State Assessment

### 2.1 What We Have Today (completed Feb 26, 2026)

#### ChromaDB — NCEPLIBS API Documentation (1,747 docs)

Ingested via `ingest_documentation_v8.py` with Doxygen-aware filtering (`ingestion_base.py` v4.3.0):

| Source | Docs | Max Pages | URL |
|--------|------|-----------|-----|
| nceplibs-bufr | 487 | 100 | noaa-emc.github.io/NCEPLIBS-bufr/ |
| nceplibs-ip | 366 | 80 | noaa-emc.github.io/NCEPLIBS-ip/ |
| nceplibs-g2 | 255 | 80 | noaa-emc.github.io/NCEPLIBS-g2/ |
| nceplibs-w3emc | 220 | 80 | noaa-emc.github.io/NCEPLIBS-w3emc/ |
| nceplibs-g2tmpl | 158 | 40 | noaa-emc.github.io/NCEPLIBS-g2tmpl/ |
| wgrib2 | 156 | 30 | cpc.ncep.noaa.gov/products/wesley/wgrib2/ |
| nceplibs-bacio | 95 | 30 | noaa-emc.github.io/NCEPLIBS-bacio/ |
| nceplibs-nemsio | 9 | 40 | noaa-emc.github.io/NCEPLIBS-nemsio/ |
| nceplibs-sigio | 1 | 20 | noaa-emc.github.io/NCEPLIBS-sigio/ |

**Total**: 1,747 vector documents in `global-workflow-docs-v8-0-0` collection (MPNet 768-dim embeddings). Collection grew from 3,514 → 5,409 docs.

**Doxygen filtering** (`ingestion_base.py` v4.3.0):
- `_strip_doxygen_boilerplate()`: Removes nav bars, footers, search overlays, sync icons
- 6 new SKIP_PATTERNS for Doxygen noise text
- 15 new URL exclude patterns for auto-generated index pages

#### Neo4j — Global Workflow Graph (589K relationships)

| Metric | Count |
|--------|-------|
| Total Relationships | 589,396 |
| FortranSubroutine nodes | 13,537 |
| FortranFunction nodes | 2,355 |
| FortranModule nodes | 1,539 |
| CALLS edges | 439,919 |
| USES edges | 91,285 |
| Library nodes (internal only) | 214 |
| DEPENDS_ON edges | 752 |
| Communities (L0-L3) | 1,036 |
| LLM Community Summaries | 820 |

#### GGSR Weighted Traversal (Phase 28)

23-type relationship weight matrix operational. All CodeAnalysisTools wired to GGSR. Traversals <100ms on 485K+ graph.

### 2.2 What's Missing — The NCEPLIBS Gap

#### Gap 1: Zero NCEPLIBS Nodes in the Graph

The 214 Library nodes in Neo4j are all **internal** `add_library()` targets (ccpp_physics, chgres_cube_lib, etc.). NCEPLIBS enter the build via `find_package()` which the CMake ingester does not parse. Result: **NCEPLIBS are invisible to every graph query**.

```
# This returns NOTHING today:
MATCH (l:Library) WHERE l.name =~ '(?i).*(bufr|bacio|w3emc|nemsio).*'
RETURN l  → 0 results
```

#### Gap 2: No Fortran USE → Library Bridge

91,285 Fortran `USES` edges exist (e.g., `File:gsi.f90 -[:USES]-> FortranModule:nemsio_module`), and 1,539 FortranModule nodes exist, but **no edge connects FortranModule to the ExternalLibrary that provides it**.

When GW code does `USE bufr_interface`, there's no way to know that module comes from the NCEPLIBS-bufr package.

#### Gap 3: No Version Tracking

Library versions live in shell files (`versions/spack.ver`, `versions/build.wcoss2.ver`) but are NOT in the graph. Critical version divergences exist:

| Library | Spack Default | WCOSS2 Override |
|---------|---------------|-----------------|
| w3emc | 2.10.0 | 2.12.0 |
| nemsio | 2.5.4 | 2.5.2 |
| sigio | 2.3.3 | 2.3.2 |

#### Gap 4: No ChromaDB ↔ Neo4j Bridge

1,747 NCEPLIBS API docs in ChromaDB and ~91K Fortran USES edges in Neo4j are **completely disconnected**. When code calls `CALL ufbint()`, neither system knows the other has relevant information.

#### Gap 5: Duplicate Library/Executable Nodes

Multiple ingestion runs created duplicate nodes — every Library and Executable node appears 2-4x (214 Library nodes → ~107 unique). The ingest script uses `CREATE` instead of `MERGE`.

### 2.3 NCEPLIBS Usage in Global Workflow

Based on CMakeLists.txt analysis across the GW build tree:

| NCEPLIBS Library | Version (spack) | GW Components Using It |
|------------------|----------------|------------------------|
| bacio | 2.4.1 | UFS Atmosphere, WW3, NCEPpost, GFS Utils |
| bufr | 12.1.0 | GFS Utils (GFS_bufr, tocsbufr executables) |
| w3emc | 2.10.0 | UFS Dycore, Physics, WW3, NCEPpost, GFS Utils |
| w3nco | 2.4.1 | Top-level (sorc/CMakeLists.txt) |
| sigio | 2.3.3 | NCEPpost, GFS Utils (conditional) |
| nemsio | 2.5.4 | GFS Utils, NCEPpost (depends transitively on w3emc + bacio) |
| g2 | 3.5.1 | WW3, NCEPpost |
| g2tmpl | 1.13.0 | NCEPpost |
| sp | 2.5.0 | UFS top-level |
| ip | 5.1.0 | GFS Utils, NCEPpost, UFS top-level |
| landsfcutil | — | GFS Utils |

**Key transitive dependency** (gfs_utils.fd/CMakeLists.txt line 54):
```cmake
# NEMSIO depends on w3emc and bacio at link time
target_link_libraries(nemsio::nemsio INTERFACE w3emc::w3emc_d bacio::bacio_4)
```

### 2.4 NCEPLIBS Source Repository Metrics

All repos are public under `github.com/NOAA-EMC/`. They are **small** — the entire collection is ~233 MB:

| Repository | Disk | Fortran | C | CMake | Primary Purpose |
|------------|------|---------|---|-------|-----------------|
| NCEPLIBS-bufr | 25 MB | 1.3 MB | 224 KB | Yes | BUFR format encode/decode |
| NCEPLIBS-ip | 119 MB | 1.0 MB | 36 KB | Yes | General interpolation |
| NCEPLIBS-w3emc | 17 MB | 2.2 MB | 14 KB | Yes | GRIB1 decoder/encoder |
| NCEPLIBS-g2 | 12 MB | 1.5 MB | — | Yes | GRIB2 codec |
| NCEPLIBS-g2tmpl | 2 MB | 271 KB | 10 KB | Yes | GRIB2 templates |
| NCEPLIBS-bacio | 0.7 MB | 42 KB | 24 KB | Yes | Binary I/O |
| NCEPLIBS-nemsio | 52 MB | 547 KB | — | Yes | NEMS I/O |
| NCEPLIBS-sigio | 0.5 MB | 197 KB | 2 KB | Yes | Sigma I/O |
| NCEPLIBS-sfcio | 0.3 MB | 88 KB | — | Yes | Surface I/O |
| NCEPLIBS-landsfcutil | 0.2 MB | 184 KB | — | Yes | Land surface init |
| NCEPLIBS-ncio | 4 MB | 101 KB | — | Yes | NC read utilities |
| **Total** | **~233 MB** | **7.5 MB** | **~311 KB** | | |

All repos use CMake build system, are predominantly Fortran (75-99%) with some C in bufr, bacio, and ip.

---

## 3. Technical Specification

### 3.1 Architecture Overview

```
                          ┌──────────────────────────────────┐
                          │          Neo4j Graph             │
                          │                                  │
  global-workflow ───────►│  File ─USES──► FortranModule     │
  (existing 589K rels)    │   │                │             │
                          │  CALLS         PROVIDED_BY ◄──┐  │
                          │   │                │          │  │
                          │   ▼                ▼          │  │
  NCEPLIBS repos ────────►│  FortranSub    FortranModule  │  │
  (NEW: Phase 34A)        │   │            (from bufr,    │  │
                          │  CALLS         w3emc, ip..)   │  │
                          │   ▼                           │  │
                          │  ExternalLibrary ◄─ BUILT_BY ─┘  │
                          │  {family:"NCEPLIBS"              │
                          │   version:"12.1.0"               │
                          │   platforms:{spack,wcoss2}}      │
                          └──────────────┬───────────────────┘
                                         │
                               DOCUMENTED_BY
                                         │
                          ┌──────────────▼───────────────────┐
                          │       ChromaDB Vectors           │
                          │    1,747 NCEPLIBS API docs       │
                          │    (ingested Feb 26, 2026)       │
                          └──────────────────────────────────┘
```

### 3.2 New Node Types

| Node Label | Properties | Source |
|------------|-----------|--------|
| `ExternalLibrary` | name, family ("NCEPLIBS"), version, cmake_target, repo_url | `find_package()` in CMakeLists.txt |
| `PlatformVersion` | platform, version, ver_file | `.ver` files in `versions/` |

### 3.3 New Relationship Types

| Relationship | Source → Target | Purpose |
|-------------|-----------------|---------|
| `PROVIDED_BY` | FortranModule → ExternalLibrary | Links Fortran USE to owning library |
| `REQUIRES_VERSION` | Component → PlatformVersion → ExternalLibrary | Version pinning per platform |
| `DOCUMENTED_BY` | FortranSubroutine → DocRef(chromadb_id) | Links graph nodes to ChromaDB docs |
| `TRANSITIVELY_DEPENDS` | ExternalLibrary → ExternalLibrary | e.g., nemsio → w3emc, nemsio → bacio |

### 3.4 Modified Existing Components

| Component | Change | File |
|-----------|--------|------|
| `CMakeGraphIngester.js` | Add `find_package()` regex parser → ExternalLibrary nodes | `src/ingestion/neo4j/CMakeGraphIngester.js` |
| `CMakeGraphIngester.js` | Handle `bufr::bufr_4` namespace syntax in `target_link_libraries()` | Same |
| `CMakeGraphIngester.js` | Use `MERGE` instead of `CREATE` to prevent duplicates | Same |
| `ingest_fortran_graph.py` | Accept `--repo-name` prefix for multi-repo node IDs | `scripts/ingest_fortran_graph.py` |
| `GraphDatabase.js` | Add NCEPLIBS-aware query methods | `src/data/GraphDatabase.js` |
| `GGSRTraversalPrototypes.js` | Add weight for `PROVIDED_BY` (0.6) and `DOCUMENTED_BY` (0.4) | `src/data/GGSRTraversalPrototypes.js` |

---

## 4. Execution Plan

### Phase 34A — Clone + Fortran Source Ingestion (Day 1)

**Objective**: Get NCEPLIBS source code into Neo4j as Fortran function/subroutine/module nodes.

#### Step 1: Clone NCEPLIBS Repos
```bash
mkdir -p supported_repos/nceplibs
cd supported_repos/nceplibs
for lib in bufr ip w3emc g2 bacio g2tmpl nemsio sfcio sigio landsfcutil ncio; do
  git clone --depth 1 https://github.com/NOAA-EMC/NCEPLIBS-${lib}.git
done
```
**Expected**: ~233 MB disk, 11 repos, ~7.5 MB Fortran source.

#### Step 2: Run Fortran Graph Ingestion
```bash
cd mcp_server_node
for lib in bufr ip w3emc g2 bacio g2tmpl nemsio sfcio sigio landsfcutil ncio; do
  python3 scripts/ingest_fortran_graph.py \
    --repo-name "nceplibs-${lib}" \
    --root-dir "../supported_repos/nceplibs/NCEPLIBS-${lib}"
done
```
**Expected**: ~5,000-8,000 new FortranSubroutine/Function/Module nodes. Estimated runtime: 15-20 minutes.

#### Step 3: Validate
```cypher
MATCH (n) WHERE n.repo = 'nceplibs-bufr' AND n:FortranSubroutine
RETURN count(n) as bufr_subroutines
-- Expected: 200-400 subroutines
```

**Tag**: `v34a` | **SDD Step**: `CLONE_AND_INGEST_FORTRAN`

---

### Phase 34B — CMake Enhancement + ExternalLibrary Nodes (Day 2)

**Objective**: Make NCEPLIBS visible in the CMake dependency graph with version tracking.

#### Step 4: Enhance CMakeGraphIngester — `find_package()` Support
Add parser for:
```cmake
find_package(bufr 12.1.0 REQUIRED)
find_package(w3emc REQUIRED)
```
Creates `ExternalLibrary` nodes with version constraints.

#### Step 5: Enhance CMakeGraphIngester — Namespace Target Resolution
Handle `target_link_libraries()` with CMake namespace syntax:
```cmake
target_link_libraries(ncep_post bacio::bacio_4 w3emc::w3emc_4 bufr::bufr_4)
```
Resolves `bufr::bufr_4` → ExternalLibrary `bufr`, precision variant `4`.

#### Step 6: Fix Duplicate Nodes
Change `CREATE` → `MERGE` in all ingestion scripts to prevent duplicate Library/Executable/ExternalLibrary nodes.

#### Step 7: Parse .ver Files for Platform Versions
```bash
# versions/spack.ver → PlatformVersion nodes
export bacio_ver=2.4.1    →  (PlatformVersion {platform:"spack", version:"2.4.1"})
# versions/build.wcoss2.ver → PlatformVersion nodes
export w3emc_ver=2.12.0   →  (PlatformVersion {platform:"wcoss2", version:"2.12.0"})
```

#### Step 8: Re-ingest Global Workflow CMake
```bash
node scripts/ingest-cmake.js --verbose
```
Creates ExternalLibrary nodes + DEPENDS_ON edges from Executables to NCEPLIBS.

**Tag**: `v34b` | **SDD Step**: `CMAKE_EXTERNAL_LIBS`

---

### Phase 34C — Graph Bridge Edges (Day 3)

**Objective**: Connect Global Workflow → NCEPLIBS across the repository boundary.

#### Step 9: Create PROVIDED_BY Relationships
Post-ingestion Cypher to match GW FortranModule USES to NCEPLIBS FortranModule providers:
```cypher
// Match GW code that USES a module also defined in NCEPLIBS
MATCH (gwMod:FortranModule)<-[:USES]-(gwFile:File)
WHERE gwMod.repo IS NULL OR gwMod.repo = 'global-workflow'
WITH gwMod
MATCH (ncepMod:FortranModule {name: gwMod.name})
WHERE ncepMod.repo STARTS WITH 'nceplibs-'
MATCH (ncepMod)<-[:CONTAINS]-(ncepFile:File)-[:BUILT_BY]->(lib:ExternalLibrary)
MERGE (gwMod)-[:PROVIDED_BY]->(lib)
```

#### Step 10: Create Transitive Dependencies
```cypher
// nemsio depends on w3emc and bacio (from CMakeLists.txt line 54)
MATCH (nemsio:ExternalLibrary {name: "nemsio"})
MATCH (w3emc:ExternalLibrary {name: "w3emc"})
MATCH (bacio:ExternalLibrary {name: "bacio"})
MERGE (nemsio)-[:TRANSITIVELY_DEPENDS {source: "gfs_utils.fd/CMakeLists.txt"}]->(w3emc)
MERGE (nemsio)-[:TRANSITIVELY_DEPENDS {source: "gfs_utils.fd/CMakeLists.txt"}]->(bacio)
```

#### Step 11: Update GGSR Weight Matrix
Add weights for new relationship types:
```javascript
PROVIDED_BY: 0.6,          // Links USE to library
TRANSITIVELY_DEPENDS: 0.5, // Indirect library deps
DOCUMENTED_BY: 0.4,        // Links to Doxygen docs
REQUIRES_VERSION: 0.3      // Version constraint
```

**Tag**: `v34c` | **SDD Step**: `GRAPH_BRIDGE_EDGES`

---

### Phase 34D — ChromaDB ↔ Neo4j API Linkage (Day 4)

**Objective**: Connect NCEPLIBS graph nodes to their Doxygen documentation in ChromaDB.

#### Step 12: Match Subroutine Names to ChromaDB Docs
```javascript
// For each NCEPLIBS FortranSubroutine node, search ChromaDB for matching doc
const subs = await neo4j.query(`
  MATCH (s:FortranSubroutine) WHERE s.repo STARTS WITH 'nceplibs-'
  RETURN s.name, s.repo
`);
for (const sub of subs) {
  const docs = await chromadb.query({
    collection: 'global-workflow-docs-v8-0-0',
    query: sub.name,
    nResults: 1,
    where: { source: sub.repo }
  });
  if (docs.distances[0] < 0.3) {
    // High confidence match
    await neo4j.query(`
      MATCH (s:FortranSubroutine {name: $name, repo: $repo})
      SET s.chromadb_doc_id = $docId, s.documented = true
    `, { name: sub.name, repo: sub.repo, docId: docs.ids[0] });
  }
}
```

#### Step 13: Validate End-to-End Queries
Test queries that span the full stack:
```
search_architecture("BUFR encoding subroutines used by GFS")
→ Returns both code (Neo4j: callers) AND documentation (ChromaDB: API docs)

get_change_impact("bufr")
→ Traces: ExternalLibrary:bufr ← DEPENDS_ON ← Executable:* ← BUILT_BY ← Component:*

trace_full_execution_chain("JGFS_ATMOS_POST")
→ J-Job → exgfs_atmos_post.sh → NCEPpost → bufr::bufr_4 → ufbint()
```

**Tag**: `v34d` | **SDD Step**: `CHROMADB_LINKAGE`

---

### Phase 34E — C Parser (Optional, Future)

**Objective**: Parse NCEPLIBS C source code for internal implementation details.

Only relevant for bufr (224KB C), bacio (24KB C), and ip (36KB C). The Fortran-facing API surface (what Global Workflow actually calls) is already captured in Phases 34A-D. The C layer is internal implementation.

**Approach**: tree-sitter C grammar integration into `CodeStructureIngester.js`.
**Effort**: ~16 hours development.
**Trigger**: Only if users need to trace INTO the C implementation layer.

---

## 5. Effort Estimates

| Phase | Description | Dev Hours | Compute Time | New Graph Nodes |
|-------|-------------|-----------|-------------|-----------------|
| 34A | Clone + Fortran Ingest | 4 hrs | 20 min | ~5,000-8,000 |
| 34B | CMake + ExternalLibrary | 8 hrs | 5 min | ~50-100 |
| 34C | Graph Bridge Edges | 6 hrs | 2 min | 0 (edges only: ~500-1,000) |
| 34D | ChromaDB ↔ Neo4j Linkage | 6 hrs | 10 min | 0 (properties only) |
| 34E | C Parser (optional) | 16 hrs | 15 min | ~200-500 |
| **Total (34A-D)** | | **~24 hrs** | **~37 min** | **~5,150-8,100** |

---

## 6. Acceptance Criteria

### Phase 34A
- [ ] 11 NCEPLIBS repos cloned under `supported_repos/nceplibs/`
- [ ] FortranSubroutine/Function/Module nodes created with `repo` property
- [ ] `MATCH (n:FortranSubroutine {repo: 'nceplibs-bufr'}) RETURN count(n)` > 100

### Phase 34B
- [ ] `ExternalLibrary` nodes exist for all 11 NCEPLIBS packages
- [ ] `DEPENDS_ON` edges from GW Executables to ExternalLibrary nodes
- [ ] `PlatformVersion` nodes with spack vs wcoss2 version differences
- [ ] Zero duplicate Library/Executable nodes after re-ingestion

### Phase 34C
- [ ] `PROVIDED_BY` edges linking GW FortranModule USES to NCEPLIBS libraries
- [ ] `TRANSITIVELY_DEPENDS` edges for nemsio → w3emc, nemsio → bacio
- [ ] GGSR weight matrix includes all new relationship types
- [ ] `find_dependencies("ncep_post")` returns NCEPLIBS in results

### Phase 34D
- [ ] NCEPLIBS FortranSubroutine nodes have `chromadb_doc_id` references
- [ ] `search_architecture("BUFR encoding")` returns both code callers AND API docs
- [ ] `get_change_impact("bufr")` returns component blast radius

---

## 7. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| fparser2 fails on older Fortran syntax (F77 in w3emc/bacio) | Medium | Medium | Use `--ignore-errors` flag; fall back to regex for F77 files |
| Namespace collision (e.g., both GW and NCEPLIBS define a module `utils`) | Low | High | All NCEPLIBS nodes tagged with `repo` property for disambiguation |
| NCEPLIBS repos change structure upstream | Low | Low | Shallow clones pinned to release tags (e.g., `bufr@12.1.0`) |
| Neo4j memory pressure from additional nodes | Low | Low | Additional ~8K nodes is <2% of existing 45K node graph |

---

## 8. Dependencies

### Required (Already Operational)
- Neo4j graph database (bolt://localhost:7687) — 589K relationships
- ChromaDB vector database (http://localhost:8080) — 5,409 docs in v8 collection
- `ingest_fortran_graph.py` — fparser2-based Fortran ingestion
- `CMakeGraphIngester.js` — CMake add_library/target_link_libraries parsing
- GGSR weighted traversal (Phase 28) — 23-type weight matrix

### Required (New for Phase 34)
- Git access to `github.com/NOAA-EMC/NCEPLIBS-*` repos (public, no auth needed)
- ~300 MB disk for shallow clones
- `--repo-name` support in `ingest_fortran_graph.py` (Step 2)
- `find_package()` parser in `CMakeGraphIngester.js` (Step 4)

---

## 9. Appendix: NCEPLIBS Family Reference

### Repository URLs
| Library | GitHub Repository | Doxygen Docs |
|---------|-------------------|-------------|
| bufr | github.com/NOAA-EMC/NCEPLIBS-bufr | noaa-emc.github.io/NCEPLIBS-bufr/ |
| ip | github.com/NOAA-EMC/NCEPLIBS-ip | noaa-emc.github.io/NCEPLIBS-ip/ |
| w3emc | github.com/NOAA-EMC/NCEPLIBS-w3emc | noaa-emc.github.io/NCEPLIBS-w3emc/ |
| g2 | github.com/NOAA-EMC/NCEPLIBS-g2 | noaa-emc.github.io/NCEPLIBS-g2/ |
| g2tmpl | github.com/NOAA-EMC/NCEPLIBS-g2tmpl | noaa-emc.github.io/NCEPLIBS-g2tmpl/ |
| bacio | github.com/NOAA-EMC/NCEPLIBS-bacio | noaa-emc.github.io/NCEPLIBS-bacio/ |
| nemsio | github.com/NOAA-EMC/NCEPLIBS-nemsio | noaa-emc.github.io/NCEPLIBS-nemsio/ |
| sfcio | github.com/NOAA-EMC/NCEPLIBS-sfcio | noaa-emc.github.io/NCEPLIBS-sfcio/ |
| sigio | github.com/NOAA-EMC/NCEPLIBS-sigio | noaa-emc.github.io/NCEPLIBS-sigio/ |
| landsfcutil | github.com/NOAA-EMC/NCEPLIBS-landsfcutil | — |
| ncio | github.com/NOAA-EMC/NCEPLIBS-ncio | — |

### Deprecated Libraries (DO NOT INGEST)
- **NCEPLIBS-w3nco** — replaced by w3emc (since v2.8.0)
- **NCEPLIBS-ip2** — replaced by ip
- **NCEPLIBS-sp** — replaced by ip

### Language Composition
All NCEPLIBS repos are 75-99% Fortran. Significant C code exists only in:
- **bufr** (13% C, 224KB) — I/O, memory allocation, C bindings
- **bacio** (37% C, 24KB) — Low-level binary I/O
- **ip** (3% C, 36KB) — Performance-critical interpolation kernels

### Key Transitive Dependencies (within NCEPLIBS)
```
nemsio → w3emc → bacio
w3emc → bacio (optional: bufr when BUILD_WITH_BUFR=ON)
g2 → (standalone)
ip → (standalone)
bufr → (standalone)
```
