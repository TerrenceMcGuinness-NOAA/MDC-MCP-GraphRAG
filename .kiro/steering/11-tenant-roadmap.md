# Tenant Roadmap — Future Code Repositories

Potential code repositories to onboard as tenants in the multi-tenant
MCP-RAG system. These would follow the same treatment as `gw_v17`:
checkout the repo, run the code/shell/Fortran ingesters, and make the
codebase queryable via the MCP tools.

Note: these are **code indexing** candidates (graph + embeddings), NOT
documentation URLs. Documentation for these projects is handled
separately via the URL crawl manifest (see `unified_manifest.json`).

## JEDI Core Components (JCSDA)

The Joint Effort for Data Assimilation Integration. These repos
implement the DA algorithms used by GFS/GDAS via the gdas.cd submodule.

| Proposed tenant_id | Repo | Language | Purpose | Priority |
|---|---|---|---|---|
| `jedi_oops` | JCSDA/oops | C++/Fortran | Object-Oriented Prediction System — core DA framework (minimization, cost functions, increments) | High |
| `jedi_ufo` | JCSDA/ufo | C++/Fortran | Unified Forward Operator — obs-to-model-space transforms | High |
| `jedi_saber` | JCSDA/saber | C++/Fortran | Background error representation (B-matrix, localization, BUMP) | Medium |
| `jedi_ioda` | JCSDA/ioda | C++/Python | Observation data access (ObsSpace, ioda-converters) | Medium |
| `jedi_fv3` | JCSDA/fv3-jedi | C++/Fortran | FV3 model interface to JEDI (geometry, state, increment) | High |
| `jedi_soca` | JCSDA/soca | C++/Fortran | Ocean DA interface (MOM6 geometry, marine obs) | Medium |
| `jedi_vader` | JCSDA/vader | C++/Fortran | Variable derivation (transforms between DA variables) | Low |

## ECMWF Foundation Libraries

Backend infrastructure that JEDI is built on top of. Understanding
these helps with debugging build issues and grid-related questions.

| Proposed tenant_id | Repo | Language | Purpose | Priority |
|---|---|---|---|---|
| `ecmwf_atlas` | ecmwf/atlas | C++/Fortran | Grid/mesh library (unstructured grids, function spaces, interpolation) | Medium |
| `ecmwf_eckit` | ecmwf/eckit | C++ | ECMWF C++ toolkit (MPI, serialization, configuration, logging) | Low |
| `ecmwf_fckit` | ecmwf/fckit | Fortran/C++ | Fortran-C++ interop toolkit | Low |

## Prerequisites for Onboarding

Each tenant requires:
1. Repo checked out under `supported_repos/` (or a dedicated tenant worktree)
2. Entry in `tenants.yaml` (tenant_id, branch, label_prefix, index_prefix)
3. Run the ingestion pipeline: `ingest_code_v8.py` → `ingest_shell_graph_v8.py` → `ingest_fortran_graph_v8.py` (if Fortran)
4. For C++ repos: a separate C++ AST ingester would be needed (not yet built — Fortran and shell only today)

## C++ Gap

The current ingestion pipeline handles:
- Shell scripts (bash/ksh) ✅
- Fortran (F90/F95/F03/F08) ✅
- Python (planned, `graph-port-python-community`) 🔜

It does NOT yet handle:
- C++ ❌ — most JEDI/ECMWF repos are primarily C++

To fully index the JEDI repos, we'd need a C++ AST ingester (using
libclang or tree-sitter). This is a significant effort and would be
its own spec. The Fortran portions of these repos (model interfaces,
physics routines) can be indexed today.

## Sequencing Recommendation

1. **First:** `jedi_fv3` (JCSDA/fv3-jedi) — directly relevant to GFS DA, has Fortran components, researchers actively work on it
2. **Second:** `jedi_oops` + `jedi_ufo` — core DA algorithms, high question frequency
3. **Later:** SABER, SOCA, ECMWF libs — useful but less frequently queried
4. **Needs C++ ingester:** Full JEDI indexing (the C++ core of OOPS/UFO/SABER)
