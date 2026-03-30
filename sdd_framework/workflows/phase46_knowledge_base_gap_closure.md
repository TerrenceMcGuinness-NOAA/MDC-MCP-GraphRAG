# Phase 46: Knowledge Base Gap Closure — SDD Workflow Spec

## Context

The EIB MCP Knowledge Base Gap Analysis (`docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md`) identifies remaining open items after Phases 38-42 resolved the major structural gaps. A systematic audit reveals:

- **Phases A, B, C, D, E** in the remediation plan are fully or mostly resolved (A1-A3, B1-B6, C1-C5, D1-D3, E1-E3 all done)
- **6 ReadTheDocs sources** are configured but rate-limited (HTTP 429) — trivial retry
- **3 documentation sources** are not configured at all (pyioda, FMS/MPP, CMAQ)
- **42 Python ex-scripts** lack J-Job INVOKES edges (orchestration chain gap)
- **Ex-scripts + USH** have low ChromaDB vector counts (61 + "few" chunks)
- **External library graph stubs** (ESMF, NUOPC, MPI, NetCDF, FMS) have zero Neo4j nodes
- **4 scorecard domains** are below B grade: MOM6 (C+), CICE (C+), AQM (C), JEDI (C-)
- **Gap analysis report itself** has stale entries (Phases A/B/E listed as open but are resolved)

This phase closes all remaining actionable gaps in a single sweep, upgrading the scorecard to have no domain below B-.

**Dependencies**: Phase 40 (configs/CI), Phase 41 (external docs), Phase 42 (JEDI)
**Downstream**: Scorecard upgrade, benchmark improvement expected for Semantic Search and Code Structure categories

---

## Open Gaps Inventory (16 items, 10 unique work items)

| # | Gap | Category | Effort | Scorecard Impact |
|---|-----|----------|--------|-----------------|
| 1 | Retry 6 rate-limited ReadTheDocs (MOM6, CICE, GOCART, CCPP, UPP, METplus) | Docs | Trivial | MOM6 C+->B+, CICE C+->B, AQM C->B- |
| 2 | Add pyioda/ioda-converters docs source | Docs | Low | JEDI C-->B- |
| 3 | Add FMS/MPP/GFDL wiki docs source | Docs | Low | External libs B->B+ |
| 4 | Add CMAQ/EPA AQM docs source | Docs | Low | AQM C->B- |
| 5 | Re-run ChromaDB vectors for ex-scripts + USH | Vectors | Low | Orchestration A-->A |
| 6 | Verify/fix Python graph for dev/workflow/ (37 of 45+) | Graph | Low | Orchestration |
| 7 | Ensure verif-global.fd coverage in graph+vectors | Graph+Vectors | Low | DA/GSI domain |
| 8 | Add Python ex-script INVOKES edges from J-Jobs | Graph | Medium | Orchestration chain complete |
| 9 | Create ExternalLibrary stubs for ESMF, NUOPC, FMS (88 already exist for NCEPLIBS/MPI/NetCDF) | Graph | Medium | External libs B->A- |
| 10 | Clean up stale gap analysis entries + update scorecard | Document | Low | Report accuracy |

---

## SDD Session Plan

```
Phase:  phase46_knowledge_base_gap_closure
Steps:  11
```

### Step 46-1: Audit stale remediation entries
**Tag**: validate
**Target**: `docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md`

Audit and mark as resolved:
- Phase A tasks A1-A3 (path fix, stale nodes, spurious scripts) — all resolved by Phase 38
- Phase B tasks B1-B6 (Fortran graph) — all resolved by Phase 39
- Phase E tasks E1-E3 (JEDI deep coverage) — all resolved by Phase 42
- Phase D tasks D4-D6 partial items — will be resolved by this phase's doc retries

Update ChromaDB/Neo4j counts in sections 1.1-1.3 to reflect current state (82,944 docs, 2.6M rels).

### Step 46-2: Retry 6 rate-limited documentation sources
**Tag**: ingest
**Target**: `mcp_server_node/scripts/ingest_documentation_v8.py`

Re-run documentation ingestion for the 6 configured-but-429'd sources with staggered delays. The script uses `--tiers` to filter by tier group:

The 6 rate-limited sources are in:
- `tier3_models`: mom6, cice, gocart
- `tier4_build`: ccpp-techdoc
- `tier5_standards`: upp, metplus

```bash
python3 ingest_documentation_v8.py --tiers tier3_models
python3 ingest_documentation_v8.py --tiers tier4_build
python3 ingest_documentation_v8.py --tiers tier5_standards
```

Note: These tiers also contain already-ingested sources (which will be skipped or upserted). The script will hit the 6 rate-limited sources among them. If rate-limiting persists, we may need to add a `--delay` flag or a per-page sleep to the ingestion script.

All 6 are already configured in `documentation_sources_config.py` (lines ~213-444). Expected yield: ~2,500 new chunks.

**Acceptance**: `global-workflow-docs-v8-0-0` collection grows by 1,500+.

### Step 46-3: Add 3 new documentation sources
**Tag**: configure
**Target**: `mcp_server_node/scripts/documentation_sources_config.py`

Add entries for:
1. **pyioda/ioda-converters** — JEDI observation I/O (35+ imports in codebase). URL: `https://jointcenterforsatellitedataassimilation-jedi-docs.readthedocs-hosted.com/` ioda section, or dedicated site.
2. **FMS/MPP** — GFDL infrastructure (50+ USE statements). URL: `https://github.com/NOAA-GFDL/FMS/wiki`
3. **CMAQ/EPA** — Air quality model docs. URL: `https://github.com/USEPA/CMAQ/wiki` or EPA site.

Then run ingestion for the 3 new sources.

**Acceptance**: 3 new source entries in config, docs ingested into `global-workflow-docs-v8-0-0`.

### Step 46-4: Re-run ChromaDB vector ingestion for ex-scripts + USH
**Tag**: ingest
**Target**: `mcp_server_node/scripts/ingest_code_v8.py`

Re-run code vector ingestion targeting `dev/scripts/` and `ush/` directories to improve chunk density. Currently: 61 chunks for 82 ex-scripts, "few" for 63 USH scripts. Target: 400+ chunks each.

Check `ingest_code_v8.py` scan config — verify `dev/scripts` and `ush` are in `CODE_DIRECTORIES` and chunk size is appropriate for these operational scripts.

**Acceptance**: Ex-scripts grow from 61 to 300+ chunks, USH from ~50 to 200+ chunks.

### Step 46-5: Verify and fix Python graph coverage for dev/workflow/
**Tag**: validate
**Target**: `mcp_server_node/scripts/ingest_python_graph.py`

Query Neo4j: `MATCH (p:PythonModule) WHERE p.file_path STARTS WITH 'dev/workflow/' RETURN COUNT(p)`.
Compare against actual files on disk (`find dev/workflow/ -name "*.py" | wc -l`).

If gap exists (37 of 45+ covered), re-run `ingest_python_graph.py` targeting `dev/workflow/` to capture:
- `dev/workflow/applications/` (GFS/GEFS/GCAFS/SFS application factories)
- `dev/workflow/hosts/` (HPC host configurations)
- `setup_expt.py`, `setup_workflow.py`, `create_experiment.py`

**Acceptance**: All Python files in `dev/workflow/` have PythonModule nodes.

### Step 46-6: Ensure verif-global.fd coverage
**Tag**: validate
**Target**: `sorc/verif-global.fd/`

Verify `sorc/verif-global.fd/` (47 files: 31 py, 16 sh) has:
- PythonModule nodes for `ush/*.py` scripts (METplus verification wrappers)
- ShellScript nodes for `scripts/` ex-scripts
- ChromaDB vectors for all files

Re-run relevant ingestion scripts if gaps found.

**Acceptance**: verif-global.fd goes from PARTIAL to GOOD in gap analysis.

### Step 46-7: Add Python ex-script INVOKES edges
**Tag**: implement
**Target**: `mcp_server_node/scripts/ingest_cross_language_bridges.py`

Enhance the cross-language bridge script to detect J-Job lines that invoke Python ex-scripts:
```bash
# Pattern in J-Jobs:
python3 ${SCRIPTSgfs}/exglobal_aero_analysis_finalize.py
${USHgfs}/python/exglobal_analysis_stats.py
```

Create `(:ShellScript)-[:INVOKES]->(:PythonModule)` edges for the 42 Python ex-scripts.

Scan `dev/jobs/` J-Job files for patterns:
- `python3? \${SCRIPTSgfs}/ex.*\.py`
- `\${USHgfs}/python/.*\.py`
- Direct python script invocations

**Acceptance**: `MATCH (j:ShellScript)-[:INVOKES]->(p:PythonModule) WHERE p.file_path STARTS WITH 'dev/scripts/' RETURN COUNT(*)` returns 30+.

### Step 46-8: Create ExternalLibrary API stub nodes for ESMF/NUOPC/FMS
**Tag**: implement
**Target**: Cypher script or Python script extending existing 88 ExternalLibrary nodes

88 ExternalLibrary nodes already exist (Phase 34: NCEPLIBS + mpi + netcdf + openmp). Missing: **ESMF** (69+ USE refs), **NUOPC** (5+ USE refs), **FMS/MPP** (50+ USE refs).

Create 3 new ExternalLibrary nodes and populate API entry stubs by scanning the codebase for `USE esmf`, `USE NUOPC`, `USE fms_*`/`USE mpp_*` patterns and collecting the imported symbols. This creates graph endpoints so that coupling traces don't terminate at missing nodes.

Pattern reference: Existing 88 ExternalLibrary nodes have 27-97 relationships each. The `mpi` and `netcdf` nodes already exist with proper CALLS edges.

**Acceptance**: `MATCH (e:ExternalLibrary) WHERE e.name IN ['esmf', 'nuopc', 'fms'] RETURN e.name, count{(e)<--()} AS rels` shows 3 new libraries with 50+ relationships each.

### Step 46-9: Run validation queries
**Tag**: validate

Run comprehensive validation:
1. New doc counts in `global-workflow-docs-v8-0-0` collection
2. Python ex-script INVOKES edge count
3. ExternalLibrary + ExternalAPIEntry node counts
4. verif-global.fd node coverage
5. dev/workflow/ PythonModule completeness
6. ChromaDB vector counts for ex-scripts and USH

### Step 46-10: Run MCP benchmark with regression comparison
**Tag**: validate

Run `get_quality_metrics` with `compare: true`. Expected improvements:
- Semantic Search P@5: should improve from 0.88 (new docs boost retrieval)
- Code Structure P@5: may improve from 0.40 (better ex-script + workflow vectors)
- Overall MRR should hold at 0.93+

### Step 46-11: Update gap analysis report and scorecard
**Tag**: document
**Target**: `docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md`

Final updates:
- Mark Phase A, B, E as fully RESOLVED (not stale anymore)
- Update Phase D partial items (D4-D6) with retry results
- Update scorecard:
  - UFS Ocean (MOM6): C+ -> B+ (docs now ingested)
  - UFS Sea Ice (CICE): C+ -> B (docs now ingested)
  - Air Quality (AQM): C -> B- (GOCART + CMAQ docs)
  - JEDI ecosystem: C- -> B- (Phase 42 graph + pyioda docs)
  - External libs: B -> A- (API stubs + FMS docs)
  - Orchestration: A- -> A (complete INVOKES chain, better vectors)
- Update doc/vector/node counts to current state
- Bottom line: "No domain below B-"

---

## Critical Files

| File | Action |
|------|--------|
| `docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md` | UPDATE — stale entries, scorecard |
| `mcp_server_node/scripts/documentation_sources_config.py` | UPDATE — add 3 sources |
| `mcp_server_node/scripts/ingest_documentation_v8.py` | RUN — retry 6 rate-limited |
| `mcp_server_node/scripts/ingest_code_v8.py` | RUN — re-ingest ex-scripts/USH vectors |
| `mcp_server_node/scripts/ingest_python_graph.py` | RUN — verify/fix dev/workflow/ |
| `mcp_server_node/scripts/ingest_cross_language_bridges.py` | MODIFY — add J-Job scan for Python ex-script INVOKES |
| `mcp_server_node/scripts/ingest_external_lib_stubs.py` | NEW or Cypher — ExternalLibrary stubs for ESMF/NUOPC/FMS |
| `sdd_framework/workflows/phase46_knowledge_base_gap_closure.md` | NEW — this spec |

---

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| ReadTheDocs rate-limiting again (429) | Use `--delay 5` between pages; stagger source runs 60s apart |
| pyioda docs may not have standalone site | Fall back to JEDI umbrella docs ioda section |
| CMAQ wiki may be sparse | Supplement with EPA technical documents if wiki is thin |
| ExternalLibrary stubs may create orphan nodes | Only create stubs for APIs that have existing unresolved CALLS from UFS/MOM6/CICE code |
| Vector re-ingestion may create duplicates | Use `upsert` mode or delete-then-add for target directories |

---

## Verification Plan

1. **Benchmark regression**: `get_quality_metrics(compare: true)` — no degradation, Semantic Search P@5 >= 0.88
2. **Document count**: `global-workflow-docs-v8-0-0` grows by 2,000+
3. **INVOKES chain**: `MATCH (j:ShellScript)-[:INVOKES]->(p:PythonModule) RETURN COUNT(*)` increases by 30+
4. **ExternalLibrary**: `MATCH (e:ExternalLibrary) WHERE e.name IN ['esmf','nuopc','fms'] RETURN COUNT(e)` shows 3 new (total 91)
5. **Scorecard**: No domain below B-
6. **Health check**: `mcp_health_check(deep: true)` remains HEALTHY
