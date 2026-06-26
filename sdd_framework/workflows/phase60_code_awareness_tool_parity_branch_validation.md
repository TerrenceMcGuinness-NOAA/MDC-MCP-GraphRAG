# Phase 60 — Code-Awareness Tool Parity & Branch Validation (Python MCP Port)

**Version**: 1.0.0
**Status**: ready
**Created**: 2026-06-24
**Author**: AI Assistant + Terry McGuinness
**Depends on**: Phase 48 (AWS Infrastructure Port), `python-mcp-pw-integration` spec,
`omd-tenants-2-v17-pilot` (multi-tenant `gw` / `gw_v17` ingestion)
**Related**: Phase 51 (gateway health/explain/search fixes), Phase 44 (RAG QA framework),
Phase 33 (per-user SDD state)

---

## 1. Executive Summary

The Python MCP server (`mcp_server_python/`) was ported from the Node.js baseline
(`mcp_server_node/`) and reached functional-smoke parity in legacy mode
(CHANGELOG 8.36.x). What is **not** yet systematically verified is whether the
ported **code-awareness** tools — the graph/AST/call-chain tools that reason over
actual source — return answers that (a) match the Node.js baseline (parity), and
(b) match the *ground truth* of the two live branch checkouts: `develop` (tenant
`gw`) and GFS `v17` (tenant `gw_v17`, branch `dev/gfs.v17`).

This phase builds a repeatable **driver harness** that, for each code-awareness
tool, invokes the tool, then validates the response along two axes:

1. **Ground-truth axis** — compare the tool's claim (callers, dependencies,
   structure, env-var lineage) against the real source in the on-disk branch
   checkout (`workflow_subdir: develop` and `workflow_subdir: dev-v17`).
2. **Isolation axis** — confirm a `gw_v17`-only symbol is invisible to `gw` and
   vice-versa (no cross-tenant label/index bleed), extending the existing
   `_smoke_branch_isolation` probe to every code-awareness tool.

Each detected gap is logged, fixed in the Python tool (or its adapter), and the
harness is re-run until the gap closes — the **fix-and-iterate** loop. The Node.js
server is the parity oracle; the branch checkouts are the ground-truth oracle.

---

## 2. Scope

### 2.1 Tools under test (code-awareness surface)

| Module | Tool | Backend | Ground-truth check |
|--------|------|---------|--------------------|
| `code_analysis` | `analyze_code_structure` | Graph | functions/classes match AST of the file in branch |
| `code_analysis` | `find_dependencies` | Graph | imports match source `import`/`use`/`source` stmts |
| `code_analysis` | `trace_execution_path` | Graph | call chain reachable from real call sites |
| `code_analysis` | `find_callers_callees` | Graph | caller/callee set == real call sites |
| `code_analysis` | `trace_full_execution_chain` | Graph | cross-language hops exist in source |
| `code_analysis` | `find_env_dependencies` | Graph | env-var exports/uses match `export`/`$VAR` in scripts |
| `graph_rag` | `get_code_context` | Graph+Vector | neighborhood symbols exist in branch |
| `graph_rag` | `search_architecture` | Graph+Vector | community members are real files |
| `graph_rag` | `find_similar_code` | Graph+Vector | returned symbols resolve to branch files |
| `graph_rag` | `get_change_impact` | Graph | blast-radius symbols are real dependents |
| `graph_rag` | `trace_data_flow` | Graph | flow path edges exist in source |
| `semantic_search` | `find_related_files` | Vector+Graph | related files exist in branch |

### 2.2 Out of scope

- Non-code-awareness tools (pure docs search, EE2 text scan, SDD, GitHub,
  utility) — covered by the existing functional-smoke suite.
- Re-ingestion of branch data (assumed present; harness **skips gracefully** when
  a tenant is absent, per `omd-tenants-2-v17-pilot` R4.2).
- AWS/Neptune backend (this phase runs against the legacy ChromaDB+Neo4j backend
  on Parallel Works; AWS parity is a follow-up).

---

## 3. Ground-Truth & Oracle Model

```
                 code-awareness tool (Python port)
                              │
              ┌───────────────┼────────────────┐
              ▼               ▼                ▼
      Parity oracle    Ground-truth oracle   Isolation oracle
      (Node baseline)  (branch source on    (gw vs gw_v17
       same args         disk: develop /      label/index
       compared via       dev-v17 checkout)   non-leak)
       parity_runner)
```

- **Parity oracle**: `mcp_server_python/tests/parity/parity_runner.py` already
  supports `exact`, `set_equality`, and `tolerance` comparison modes. Reuse it.
- **Ground-truth oracle**: lightweight source extractors (grep/AST) that derive
  the expected answer directly from the branch checkout referenced by the
  tenant's `workflow_subdir`.
- **Isolation oracle**: tenant-scoped queries asserting a `GW_V17_`-prefixed
  symbol never surfaces under `gw` and an unprefixed develop-only symbol never
  surfaces under `gw_v17`.

Tenant → branch mapping (from `mcp_server_python/src/config/tenants.yaml`):

| Tenant | Branch | `workflow_subdir` | `label_prefix` |
|--------|--------|-------------------|----------------|
| `gw` | `develop` | `develop` | (none) |
| `gw_v17` | `dev/gfs.v17` | `dev-v17` | `GW_V17_` |

---

## 4. Acceptance Criteria

| # | Probe | Pass condition |
|---|-------|----------------|
| 1 | Harness runs all 12 code-awareness tools × 2 tenants | every tool reports pass / skip (never silent error) |
| 2 | Ground-truth axis | each tool's answer ⊆ / == source-derived expectation (per comparison mode) |
| 3 | Parity axis (`gw`/develop) | Python result matches Node baseline under declared mode |
| 4 | Isolation axis | 0 cross-tenant leaks (`gw_v17` symbol absent under `gw`, and vice-versa) |
| 5 | Graceful skip | missing tenant or missing checkout → `skip` with reason, not `fail` |
| 6 | Gap log | machine-readable report (JSON) of every mismatch with tool, tenant, expected vs actual |
| 7 | Re-validation | after each fix cycle, the previously-failing probe flips to pass with no new regressions |
| 8 | Unit tests | `pytest mcp_server_python/tests` stays green |

---

## 5. Implementation Plan

### Step 1 — Inventory & baseline (research)
- Enumerate the 12 tools above and confirm each is registered in the Python
  server (`code_analysis.py`, `graph_rag.py`, `semantic_search.py`).
- Run the existing parity suite (`tests/parity/`) for `code_analysis` and
  `graph_rag` against the Node baseline to capture a starting pass/fail matrix.
- **Test**: parity runner executes; record the baseline matrix as the gap report
  seed.

### Step 2 — Branch checkout availability probe (design + configure)
- Resolve each tenant's `workflow_subdir` to an on-disk checkout root.
- For each tenant, verify the checkout exists and is on the expected branch
  (`git -C <root> rev-parse --abbrev-ref HEAD`). Missing → mark tenant `skip`.
- **Test**: probe prints a 2-row table (gw, gw_v17) with branch + status.

### Step 3 — Ground-truth extractors (implement)
- Add `mcp_server_python/scripts/branch_ground_truth.py` with small, dependency-free
  extractors that, given a symbol/file and a checkout root, derive the expected:
  - callers/callees (regex over call sites + def sites),
  - imports/dependencies (`import` / `use` / `source` / `.` lines),
  - file structure (top-level defs/classes/subroutines),
  - env-var lineage (`export VAR` / `${VAR}` / `$VAR`).
- Keep extractors conservative (subset assertions) to avoid false negatives on
  graph-enriched answers.
- **Test**: extractors return non-empty expectations for a known anchor symbol in
  each branch (e.g. a J-Job present in both, plus a v17-only J-Job
  `JGDAS_ATMOS_ANALYSIS_WDQMS`).

### Step 4 — Driver harness (implement)
- Add `mcp_server_python/scripts/validate_code_awareness.py` that, for each tool ×
  tenant:
  1. invokes the tool with tenant context set,
  2. runs the **ground-truth** comparison (subset/equality),
  3. runs the **parity** comparison vs Node (reuse `parity_runner`, `gw` only),
  4. runs the **isolation** assertion,
  5. appends a `GapRecord` to a JSON report.
- Reuse `SkipProbe` semantics from `smoke_queries.py` for graceful skips.
- Emit a markdown summary + `code_awareness_gaps.json` artifact.
- **Test**: harness completes end-to-end and writes both artifacts; no
  unhandled exceptions.

### Step 5 — Fix-and-iterate loop (implement + validate, repeat)
- For each gap in `code_awareness_gaps.json`, triage root cause:
  parity bug (Python diverges from Node), ground-truth bug (tool wrong vs
  source), or isolation bug (label/index bleed).
- Apply the minimal fix in the Python tool/adapter; re-run **only** the affected
  probe, then the full harness to confirm no regression.
- Record each cycle as a `record_sdd_step` with tag `validate` (and `implement`
  for the fix).
- **Test**: failing probe → pass; full harness regression-free.

### Step 6 — Wire into smoke/health (configure)
- Register a condensed `code_awareness` probe in
  `mcp_server_python/src/tools/smoke_queries.py` so
  `mcp_health_check(functional=True)` exercises one representative tool per axis.
- **Test**: `mcp_health_check` functional mode includes the new probe and passes.

### Step 7 — Document & changelog (document)
- Update root `CHANGELOG.md` (new minor version) summarizing the harness, the
  gap counts found/fixed, and any deferred AWS-backend follow-ups.
- Cross-link this phase from the `python-mcp-pw-integration` spec tasks.
- **Test**: CHANGELOG entry present with dated header; phase status → `complete`.

---

## 6. Artifacts Produced

| Artifact | Path | Purpose |
|----------|------|---------|
| Ground-truth extractors | `mcp_server_python/scripts/branch_ground_truth.py` | derive expected answers from branch source |
| Driver harness | `mcp_server_python/scripts/validate_code_awareness.py` | 3-axis validation + fix loop driver |
| Gap report | `mcp_server_python/scripts/code_awareness_gaps.json` | machine-readable mismatch log |
| Smoke probe | `mcp_server_python/src/tools/smoke_queries.py` (extended) | health-check integration |
| Changelog | `CHANGELOG.md` | version + summary |

---

## 7. Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Branch checkout absent on PW | graceful `skip` with reason (R4.2 pattern) |
| Graph-enriched answers exceed source set | use **subset** assertions, not strict equality, on enriched axes |
| Node baseline unreachable (AgentCore proxy) | parity axis degrades to `skip`; ground-truth + isolation still run |
| False isolation failures from shared util files | anchor isolation on branch-unique symbols only (e.g. v17-only J-Jobs) |
| Re-ingestion drift vs checkout | record commit SHA of each checkout in the gap report for traceability |

---

## 8. SDD Session Tracking

```
start_sdd_session({ phase: "phase60_code_awareness_tool_parity_branch_validation", total_steps: 7 })
record_sdd_step({ step: 1, name: "Inventory & baseline parity matrix", tag: "research" })
record_sdd_step({ step: 2, name: "Branch checkout availability probe", tag: "configure" })
record_sdd_step({ step: 3, name: "Ground-truth extractors", tag: "implement" })
record_sdd_step({ step: 4, name: "Driver harness (3-axis)", tag: "implement" })
record_sdd_step({ step: 5, name: "Fix-and-iterate gap closure", tag: "validate" })
record_sdd_step({ step: 6, name: "Wire into smoke/health", tag: "configure" })
record_sdd_step({ step: 7, name: "Document & changelog", tag: "document" })
complete_sdd_session({ summary: "<gaps found/fixed, residual skips>" })
```
