# Phase 82: Shell Variable Expansion Resolution for Graph Ingestion

**Version**: 1.0.0
**Date**: 2026-09-01
**Status**: Proposed
**Priority**: Medium
**Depends on**: graph-port-shell-ops (RESOLVED), bounded-graph-traversal [8.36.0]
**Branch**: TBD

---

## 1. Problem Statement

The shell graph ingester (`ingest_shell_graph_v8.py` and its `ShellScriptParser`)
extracts SOURCES, INVOKES, and EXECUTES relationships from shell scripts using
regex pattern matching. When a source or invocation target contains a bash
variable reference, the ingester records the **literal unexpanded string** as the
target node name. This creates graph nodes like `config.${config}`,
`${machine}.env`, `${SCRgfs}/exglobal_forecast.sh`, and
`${EXECglobal}/gfs_model.x` that cannot join to the nodes representing the
actual files.

### Evidence from Today's Parity Check (2026-09-01)

`trace_full_execution_chain("JGLOBAL_FORECAST")` on the freshly deployed AWS
runtime (v44, BFS walker) returned nodes named:

- `config.${config}` — should resolve to `config.base`, `config.fcst`, etc.
- `${machine}.env` — should resolve to `hera.env`, `hercules.env`, etc.
- `ush/jjob_standard_vars.sh` — partial path, resolved correctly
- `PDY` — an env var, not a file — should not be a SOURCES target

The July 2026 gap analysis (`GraphRAG-Gaps-Detected-Jul-2026.md`, Gap G7)
documented the downstream consequence: only 97 EXECUTES edges on Neptune vs
129 on COTS, with 36 unmatched refs — most due to unexpanded `${EXECglobal}`
or `${EXECgfs}` prefixes in executable paths.

### Original Documentation

The January 2025 ingestion milestone
(`archive/documentation/ingestion_milestones/SHELL_CODE_INGESTION_COMPLETE.md`)
documented this under "Known Limitations → Source Resolution":

> - Environment variable expansion not performed
> - `${VAR}/file.sh` style paths not expanded
> - Workaround: Post-processing could normalize paths and resolve variables.

The workaround was never implemented.

---

## 2. Scope of the Gap

The global-workflow uses six layers of bash variable expansion patterns, each
progressively harder to resolve statically:

### Layer 1 — Simple variable-prefixed paths (HIGH frequency, EASY to resolve)

```bash
source "${HOMEgfs}/ush/preamble.sh"
source "${SCRgfs}/exglobal_forecast.sh"
${EXECglobal}/gfs_model.x
```

These use well-known path-prefix variables (`HOMEgfs`, `SCRgfs`, `USHgfs`,
`EXECgfs`, `EXECglobal`, `FIXgfs`, `PARMgfs`, `HOMEobsproc`) whose values
are deterministic from the repo layout. `HOMEgfs` is the repo root. `SCRgfs`
is `${HOMEgfs}/scripts`. `USHgfs` is `${HOMEgfs}/ush`. These are set in
`config.base` and never overridden per-job.

**Count**: ~70% of all unresolved references.
**Resolution**: Static lookup table derived from `config.base`.

### Layer 2 — Default/fallback assignments (`:=` and `:-` patterns)

```bash
export EXPDIR="${EXPDIR:-${HOMEglobal}/dev/parm/config}"
: "${STRICT:=YES}"
export MCP_WORKFLOW_ROOT="${MCP_WORKFLOW_ROOT:-/mnt/workflow}"
```

The colon-assign (`:=`) and colon-default (`:-`) patterns set a variable only
if it's unset or empty. For ingestion purposes, the default value IS the
resolved value since the ingester runs outside the operational environment.

**Count**: ~50 instances across config and preamble files.
**Resolution**: Parse the default-value expression from the `:-` / `:=` syntax.

### Layer 3 — Loop-based config cascade (`jjob_header.sh`)

```bash
# Called as: jjob_header.sh -e "fcst" -c "base fcst"
for config in "${configs[@]:-''}"; do
    source "${EXPDIR}/config.${config}" && true
done
```

The J-Job passes a `-c "base fcst"` argument list to `jjob_header.sh`, which
iterates over those names and sources `config.base` then `config.fcst`. The
ingester sees `source "${EXPDIR}/config.${config}"` and creates one node
named `config.${config}` instead of the N concrete config files.

**Count**: Every J-Job (99 jobs × 2-4 configs each = ~300 config source edges).
**Resolution**: Two-pass ingestion — parse J-Job files first to extract the
`-c` argument list, then expand the config loop targets per job.

### Layer 4 — Machine-conditional sourcing

```bash
source "${HOMEgfs}/env/${machine}.env"
```

Six possible targets: `hera.env`, `hercules.env`, `orion.env`, `wcoss2.env`,
`gaea.env`, `jet.env`. The `${machine}` variable is set at runtime by the
scheduler. The current ingester creates one node `${machine}.env`.

**Count**: 1 per J-Job (99 jobs), but always the same 6 targets.
**Resolution**: Enumerate known machines from `env/*.env` file listing and
create one SOURCES edge per machine variant (with a `machine` property on the
relationship).

### Layer 5 — Template-based declaration (`declare_from_tmpl`)

```bash
MEMDIR="ensstat" RUN="enkf${GDUMP}" YMD=${gPDY} HH=${gcyc} \
    declare_from_tmpl -rx COMIN_ATMOS_HISTORY_ENS_STAT_PREV:COM_ATMOS_HISTORY_TMPL
```

This pattern:
1. Sets temporary env vars inline (`MEMDIR`, `RUN`, `YMD`, `HH`)
2. Looks up a template string from `COM_ATMOS_HISTORY_TMPL`
   (defined in `config.com` as `${ROTDIR}/${RUN}.${YMD}/${HH}/${MEMDIR}/...`)
3. Runs `envsubst` on the template to produce a concrete path
4. Declares the result as a readonly export

The ingester cannot follow this chain without executing bash or emulating
`envsubst` with the inline variable bindings.

**Count**: ~150 instances (being removed by PR #4555, replaced with explicit
`declare -rx` statements — but still present in v17 and older branches).
**Resolution**: OUT OF SCOPE for initial implementation. Track as a follow-up.
The PR #4555 de-templating effort makes this self-resolving for `develop`.

### Layer 6 — Nested/computed expansions

```bash
declare -x PS4='+ $(basename ${BASH_SOURCE[0]:-${FUNCNAME[0]:-"Unknown"}})[${LINENO}]'
${!prefix*}    # indirect expansion
```

Nested defaults-within-defaults, command substitution inside parameter
expansion, and indirect variable references.

**Count**: Rare (~10 instances).
**Resolution**: OUT OF SCOPE. These are debug/utility patterns, not
dependency-producing source/invoke statements.

---

## 3. Proposed Solution: Variable Resolution Table + Two-Pass Ingestion

### Architecture

```
Pass 1: Build Resolution Context
  ├── Parse config.base → extract HOMEgfs, SCRgfs, USHgfs, EXECgfs, etc.
  ├── Parse each J-Job → extract -c config list, -e env arg
  ├── Enumerate env/*.env → known machine targets
  └── Parse :- / := patterns → default value map

Pass 2: Re-resolve Source/Invoke Targets
  ├── For each SOURCES/INVOKES/EXECUTES edge with ${var} in the target:
  │   ├── Substitute known variables from the resolution table
  │   ├── If loop-expanded (config.${config}), fan out to concrete targets
  │   ├── If machine-conditional (${machine}.env), fan out to known machines
  │   └── If unresolvable, keep the literal (status quo) + add UNRESOLVED flag
  └── Write resolved edges via MERGE, delete or flag unresolved originals
```

### New Components

1. **`VariableResolutionTable`** — A class that builds and holds the
   variable-to-value mapping from config files and J-Job argument parsing.

2. **`ConfigBaseParser`** — Reads `parm/config/gfs/config.base` (or
   `parm/config/gcafs/config.base` depending on tenant) and extracts the
   canonical path-prefix variables. Uses the `:=` / `:-` aware parser from
   Layer 2.

3. **`JJobArgumentExtractor`** — Reads J-Job files and extracts the `-c`
   (config list) and `-e` (env name) arguments passed to `jjob_header.sh`.
   Returns a per-job map of `{job_name: [config_names]}`.

4. **`TargetResolver`** — Takes a literal target string (e.g.
   `${SCRgfs}/exglobal_forecast.sh`) and the `VariableResolutionTable`,
   returns the resolved path(s) or marks it UNRESOLVED.

### Integration Point

The resolver runs as a **post-processing step** after the existing
`ShellScriptParser` has produced its raw relationship list. This preserves
the existing ingestion pipeline — the parser continues to extract verbatim
targets, and the resolver normalizes them before graph writes. This means:

- No changes to `ShellScriptParser` regex patterns
- No changes to the graph schema
- Resolver is optional — `--skip-resolution` flag for backward compatibility
- Resolution failures are logged, not fatal

---

## 4. Expected Impact

### Quantitative

| Metric | Current (no resolution) | Expected (with resolution) |
|--------|------------------------|---------------------------|
| SOURCES edges with `${var}` in target | ~180 | ~20 (Layer 5/6 remnants) |
| INVOKES edges with `${var}` in target | ~45 | ~5 |
| EXECUTES edges (shell→fortran bridge) | 97 (AWS) / 129 (COTS) | ~140+ (both) |
| Unique `config.${config}` placeholder nodes | 1 per J-Job | 0 (replaced by concrete config.X nodes) |
| `${machine}.env` placeholder nodes | 1 per J-Job | 0 (replaced by hera.env, hercules.env, etc.) |

### Qualitative

- `trace_full_execution_chain("JGLOBAL_FORECAST")` will show
  `config.base` → `config.fcst` instead of `config.${config}`
- `find_dependencies("exglobal_forecast.sh")` will show the actual scripts
  sourced, not `${USHgfs}/preamble.sh` literals
- Shell→Fortran bridge match rate jumps from ~55% (97/~175 refs) to ~80%+
  because `${EXECgfs}/gsi.x` resolves to `gsi.x` which matches the
  FortranProgram node

---

## 5. Steps

### Research

- [ ] **Step 1**: Audit `config.base` across all 5 tenants for the canonical
  path-prefix variables (HOMEgfs/HOMEglobal, SCRgfs/SCRglobal, USHgfs/USHglobal,
  EXECgfs/EXECglobal, FIXgfs, PARMgfs). Document which are branch-specific
  (gfs vs gcafs vs global naming).
  - _Type: research_

- [ ] **Step 2**: Audit all J-Job files for the `-c` and `-e` argument patterns
  passed to `jjob_header.sh`. Produce a manifest: `{job_name → [config_list]}`.
  Count how many use the `for config in "${configs[@]}"` loop vs direct source.
  - _Type: research_

- [ ] **Step 3**: Catalog all `:-` and `:=` default-value patterns in
  `jjob_header.sh`, `preamble.sh`, `jjob_standard_vars.sh`, and
  `jjob_shell_setup.sh`. Determine which defaults are repo-layout-deterministic
  vs runtime-dependent.
  - _Type: research_

### Design

- [ ] **Step 4**: Design the `VariableResolutionTable` data structure and its
  load order (config.base first, then per-job overrides, then `:=`/`:-`
  defaults). Define the precedence rules when a variable appears at multiple
  layers.
  - _Type: design_

- [ ] **Step 5**: Design the `TargetResolver` algorithm — substitution strategy,
  loop fan-out for `config.${config}`, machine enumeration for `${machine}.env`,
  and the UNRESOLVED fallback. Define the relationship property schema for
  resolved edges (`resolved_from`, `resolution_method`).
  - _Type: design_

### Implement

- [ ] **Step 6**: Implement `ConfigBaseParser` — reads config.base, extracts
  `export VAR=value` and `: "${VAR:=default}"` patterns, returns a dict.
  Tenant-aware (reads from the tenant's worktree).
  - _Type: implement_

- [ ] **Step 7**: Implement `JJobArgumentExtractor` — reads J-Job files, parses
  the `jjob_header.sh -e "..." -c "..."` invocation line, returns the per-job
  config list and env name.
  - _Type: implement_

- [ ] **Step 8**: Implement `VariableResolutionTable` — combines ConfigBaseParser
  output + JJobArgumentExtractor output + known-machines list + `:=`/`:-`
  defaults into a unified lookup.
  - _Type: implement_

- [ ] **Step 9**: Implement `TargetResolver` — takes a raw target string +
  resolution table + optional job context, returns resolved path(s).
  - _Type: implement_

- [ ] **Step 10**: Integrate the resolver into `ingest_shell_graph_v8.py` as a
  post-parse step. Add `--skip-resolution` flag. Emit resolution stats in the
  ingestion report (resolved/unresolved/fan-out counts).
  - _Type: implement_

- [ ] **Step 11**: Re-run the Shell→Fortran bridge (`create_shell_fortran_bridge.py`)
  after resolution to verify improved EXECUTES edge count.
  - _Type: implement_

### Validate

- [ ] **Step 12**: Unit tests for ConfigBaseParser — real config.base from each
  tenant, verify canonical variables extracted correctly.
  - _Type: validate_

- [ ] **Step 13**: Unit tests for JJobArgumentExtractor — sample J-Jobs with
  varying `-c` patterns (single config, multi-config, with/without `-e`).
  - _Type: validate_

- [ ] **Step 14**: Unit tests for TargetResolver — Layer 1 simple substitution,
  Layer 2 `:=`/`:-` defaults, Layer 3 config loop fan-out, Layer 4 machine
  enumeration, Layer 5/6 UNRESOLVED fallback.
  - _Type: validate_

- [ ] **Step 15**: Integration test — run the full pipeline on `gw` tenant's
  worktree with and without `--skip-resolution`, diff the graph edges. Verify
  `config.${config}` nodes are gone, `${machine}.env` nodes are gone, EXECUTES
  count increases.
  - _Type: validate_

- [ ] **Step 16**: Run the benchmark suite and compare `trace_full_execution_chain`
  output for JGLOBAL_FORECAST — verify unresolved literal nodes are replaced
  by concrete file nodes.
  - _Type: validate_

---

## 6. Acceptance Criteria

1. The `gw` baseline graph contains **zero** nodes named `config.${config}` or
   `${machine}.env` after a full re-ingest with resolution enabled.
2. SOURCES/INVOKES edges targeting `${HOMEgfs}/...`, `${SCRgfs}/...`,
   `${USHgfs}/...`, `${EXECgfs}/...` are resolved to concrete relative paths
   (e.g. `ush/preamble.sh`, `scripts/exglobal_forecast.sh`).
3. The Shell→Fortran bridge EXECUTES count is >= 120 (up from 97 on AWS).
4. `trace_full_execution_chain("JGLOBAL_FORECAST")` output shows `config.base`,
   `config.fcst`, `hera.env` (or equivalent) instead of `config.${config}`,
   `${machine}.env`.
5. Unresolvable targets (Layer 5/6) retain their literal form but carry an
   `unresolved: true` property on the relationship.
6. `--skip-resolution` flag preserves the current (no-resolution) behavior
   byte-for-byte.
7. Resolution adds < 30 seconds to a full `--mode full` ingestion run.

---

## 7. Risks and Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| config.base format varies across tenants (gfs vs gcafs vs global naming) | Medium | Step 1 audits all 5 tenants; ConfigBaseParser handles both naming conventions |
| J-Job argument parsing is fragile (multi-line, heredoc, variable args) | Low | JJobArgumentExtractor uses the same regex family as ShellScriptParser; falls back to UNRESOLVED |
| Resolution table grows stale if config.base changes | Low | Table is rebuilt on every ingestion run — no cached state |
| Over-resolution creates false edges (variable resolves to a different file than intended) | Low | Resolution is conservative — only substitutes variables with single deterministic values; fan-out only for known patterns (config loop, machine list) |
| Layers 5/6 remain unresolved | Expected | Documented as out of scope; PR #4555 removes most Layer 5 usage on `develop` |

---

## 8. Prior Art and References

- `archive/documentation/ingestion_milestones/SHELL_CODE_INGESTION_COMPLETE.md`
  — "Known Limitations → Source Resolution" (Jan 2025)
- `supported_repos/MDC-MCP-GraphRAG.wiki/GraphRAG-Gaps-Detected-Jul-2026.md`
  — Gap G7: Shell→Fortran bridge sparsity (36 unmatched refs)
- `.kiro/steering/12-multi-tenant-gap-tracker.md` — Gap B detail: v17 shell
  graph relationship density analysis
- `.kiro/specs/graph-port-shell-ops/` — ShellScriptParser regex patterns
- `.kiro/specs/graph-port-workflow-structure/` — ConfigFileParser and
  SOURCE_PATTERN (related but config-focused, not variable-resolution)
- `supported_repos/global-workflow.wiki/C48_gsienkf_atmDA-gdas_prep-Error-Analysis-PR4555.md`
  — `declare_from_tmpl` removal context (Layer 5)
- `supported_repos/global-workflow.wiki/EE2_COMPLIANCE_ANALYSIS_GLOBAL_WORKFLOW.md`
  — `declare_from_tmpl()` function analysis and recommended improvements
