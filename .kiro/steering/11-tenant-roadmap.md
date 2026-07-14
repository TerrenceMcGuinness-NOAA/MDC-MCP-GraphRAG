# Tenant Roadmap — Future Code Repositories

Potential code repositories to onboard as tenants in the multi-tenant
MCP-RAG system. These would follow the same treatment as `gw_v17`:
checkout the repo, run the code/shell/Fortran ingesters, and make the
codebase queryable via the MCP tools.

Note: these are **code indexing** candidates (graph + embeddings), NOT
documentation URLs. Documentation for these projects is handled
separately via the URL crawl manifest (see `unified_manifest.json`).

## The Two-Axis Tenant Model (scope × repo)

A tenant is **any `(repo, branch)` pair the LLM should be code-aware of** —
global-workflow branches today (`gw`, `gw_v17`, `gw_sfs`, …), arbitrary
external repos tomorrow. Two independent axes govern how content is stored
(see `.kiro/specs/rag-data-plane-gap-closure/`, Phase 68):

- **Scope axis** (`scope: tenant | shared` on every manifest source): documentation,
  EE2 standards, and community summaries are **shared** — NWS-wide, ingested once
  into a single **unprefixed** collection (`mdc-{domain}-{profile}`). Code, jjobs,
  and config-derived graph are **tenant** — per `(repo, branch)`, stored in a
  **prefixed** collection (`{index_prefix}mdc-{domain}-{profile}`) and prefixed
  graph labels (`{label_prefix}File`, …). Docs are **NOT** tenant-scoped: a new
  tenant does not re-embed the doc space.
- **Repo axis**: a tenant's `workflow_subdir` is a **repo-relative filesystem
  anchor** under `MCP_WORKFLOW_MOUNT`, **not** necessarily a global-workflow branch
  checkout. Onboarding a non-global-workflow repo needs **no `tenants.yaml` schema
  change** — only a new catalog entry pointing at the repo's worktree.

### Worked example — adding a non-global-workflow tenant (`pw_mcp`)

Onboard the `parallel-works-mcp` repository (branch `main`) as a code-awareness
tenant. This is a plain external repo, not a global-workflow branch — it
demonstrates that `workflow_subdir` is just a repo anchor.

1. **Check out the repo** under the mount base as its worktree subdir:

   ```bash
   # ${MCP_WORKFLOW_MOUNT} defaults to <repo>/.pw_workflow_mount on COTS
   git clone -b main <parallel-works-mcp-url> \
     "${MCP_WORKFLOW_MOUNT}/parallel-works-mcp"
   # (or a symlink into supported_repos/parallel-works-mcp)
   ```

2. **Add a catalog entry** to `mcp_server_python/src/config/tenants.yaml`
   (no schema change — same fields as any global-workflow tenant):

   ```yaml
   - tenant_id: pw_mcp
     repo_ref: parallel-works/parallel-works-mcp
     branch: main
     index_prefix: "pw_mcp_"       # tenant-scoped collections → pw_mcp_mdc-code-context-<profile>
     label_prefix: "PW_MCP_"       # tenant-scoped graph labels → PW_MCP_File, …
     workflow_subdir: parallel-works-mcp   # repo-relative anchor under MCP_WORKFLOW_MOUNT
     lifecycle: experimental
     description: "Parallel Works MCP server codebase (non-global-workflow tenant)"
   ```

3. **Run only the tenant-scoped ingesters** (code / shell / Fortran-if-any /
   jjobs-if-any). Documentation is **shared** — do NOT run a per-tenant doc
   ingest; `pw_mcp` reads the same shared `mdc-workflow-docs-{profile}` collection
   every tenant reads:

   ```bash
   python3 scripts/ingest_code_v8.py  --tenant pw_mcp --mode full
   python3 scripts/ingest_shell_graph_v8.py --tenant pw_mcp --mode full
   # jjobs / config / fortran only if the repo has them (else the stage skips)
   ```

4. **Query it** by passing `tenant_id="pw_mcp"` to any data-plane tool. Code
   lands in `pw_mcp_mdc-code-context-{profile}` and `PW_MCP_*` graph labels;
   shared docs/standards resolve unprefixed.

Points illustrated:
- `workflow_subdir` is a repo anchor, not a global-workflow branch — no schema change.
- Only **tenant-scoped** stages run per tenant; **shared** stages (docs, EE2,
  community summaries) are ingested once for the whole platform.
- Stages whose source precondition is absent (e.g. no `sorc/`, no `jobs/`) `skip`
  cleanly rather than fail (see `reingest_stages.yaml`).

### EXPDIR is realtime + tenant-localized (not static repo config)

`expdir` / `rocoto` are a special **tenant-scoped** case: their source is the
**realtime** experiment tree materialized by `setup_expt` (resolved `config.*` +
Rocoto XML), **not** the static `parm/config` repo templates. It is materialized
only for a subset of tenants — today **gw** (`supported_repos/EXPDIR`) and
**gw_v17** (`supported_repos/EXPDIR_v17`).
`ingest_expdir_configs_v8.resolve_expdir_base(tenant)` is **tenant-derived**: it
returns the per-tenant base, honors `MCP_EXPDIR_BASE_OVERRIDE` as an explicit
per-run override, and returns `None` (→ the stage **skips**, never falls back to
another tenant's tree) when a tenant has no materialized EXPDIR. Tenant isolation
on the write side stays the graph label prefix (`{prefix}Experiment`,
`{prefix}EXPDIRConfig`). See `.kiro/specs/rag-data-plane-gap-closure/` R15.



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
