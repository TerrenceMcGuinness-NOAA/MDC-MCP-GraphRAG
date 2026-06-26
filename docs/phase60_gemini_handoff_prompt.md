# Gemini CLI Task Prompt — Phase 60 Code-Awareness Tool Gap Solver

> Paste this whole block as the task prompt for the Gemini CLI session.
> The CLI is already connected to the `eib-mcp-rag-full` MCP server
> (native Python stdio via `mcp_server_python/scripts/run_mcp_stdio.sh`,
> legacy backend: Neo4j @7687 + ChromaDB @8080). Tool writes to
> `sdd_framework/execution_state/` are verified working.

---

## Gate Status — 2026-06-24 (after step 4: Driver harness)

- **Harness verified working** end-to-end; writes `code_awareness_gaps.json`
  + `code_awareness_summary.md`.
- **v17 relationships RESOLVED out-of-band.** The 1,566,646 `gw_v17` edges were
  loaded into Neo4j (the original reingest marked the rel files done but loaded
  0 edges — node-before-rel ordering bug; see
  `mcp_server_python/scripts/load_v17_rels_local.py`). `branch_isolation` now
  PASSES. Do NOT re-load v17 rels. Sanity check:
  `MATCH (n)-[r]-() WHERE any(l IN labels(n) WHERE l STARTS WITH 'GW_V17_') RETURN count(r)` ≈ 1.57M.
- **Gap count dropped 16 → 5.** Remaining gaps (fix the TOOLS, not the harness):
  1. `search_architecture` — FAIL on **both** `gw` and `gw_v17` (genuine tool/relevance issue; cf. Phase 51 `level>=1 AND similarity>=0.2` rerank).
  2. `find_similar_code` — FAIL on **both** tenants (threshold / tenant-scoped collection).
  3. `find_env_dependencies` — **isolation** FAIL. Caution: env-var NAMES are legitimately shared across develop/v17, so a name-based isolation assertion may be a false positive — anchor on a v17-unique env var or exempt with documented rationale (spec-first).
- Parity stays SKIP (Node baseline offline / `RUN_PARITY` unset) — by design.

## Role

You are an autonomous engineering agent working in the
`/mcp_rag_eib/eib-mcp-rag-server` repo on the `develop_aws_startpoint`
branch. You execute **SDD Phase 60** end-to-end: build a validation
harness for the recently ported Python code-awareness MCP tools, run it,
and **fix each gap then re-validate, iterating until the acceptance
criteria pass**.

## First, load the spec and start tracking

1. `get_sdd_workflow({ workflow_name: "phase60_code_awareness_tool_parity_branch_validation" })`
   — read the full spec; it is the source of truth for scope, the 3
   validation axes, the acceptance-criteria table, and the artifact list.
2. `start_sdd_session({ phase: "phase60_code_awareness_tool_parity_branch_validation", total_steps: 7 })`
3. After each spec step, `record_sdd_step({ step, name, tag, notes })`
   (tags: research, design, implement, configure, validate, document).
4. `complete_sdd_session({ summary })` at the end (gaps found/fixed,
   residual skips). Use `get_sdd_session({ resume: true })` if interrupted.

## Mission (the gap-solver loop)

For each **code-awareness tool**, validate the response along three axes,
log every mismatch to a machine-readable report, fix the root cause in the
Python tool/adapter, and re-run until green:

- **Parity axis** — Python result matches the Node.js baseline. Reuse
  `mcp_server_python/tests/parity/parity_runner.py` (modes: `exact`,
  `set_equality`, `tolerance`).
- **Ground-truth axis** — answer agrees with the real source in the
  on-disk branch checkout (`gw` → `develop`, `gw_v17` → `dev/gfs.v17`).
  Use subset assertions on graph-enriched answers to avoid false negatives.
- **Isolation axis** — a `gw_v17`-only symbol is invisible to `gw` and
  vice-versa (extend the existing `_smoke_branch_isolation` probe in
  `mcp_server_python/src/tools/smoke_queries.py`).

### Tools under test (12)

`analyze_code_structure`, `find_dependencies`, `trace_execution_path`,
`find_callers_callees`, `trace_full_execution_chain`, `find_env_dependencies`
(code_analysis); `get_code_context`, `search_architecture`,
`find_similar_code`, `get_change_impact`, `trace_data_flow` (graph_rag);
`find_related_files` (semantic_search).

### Known starting gaps (from `mcp_health_check` + verified Neo4j counts)

- `branch_isolation` probe FAILS — but **NOT** because v17 is missing or tenancy
  is broken. Multi-tenancy works: the catalog defines 5 tenants and
  `neo4j_adapter._rewrite_cypher` prefixes labels per tenant
  (`:ShellScript` -> `:GW_V17_ShellScript`). Verified local Neo4j state:
  **1,401 `GW_V17_ShellScript` nodes** including the anchor
  `JGDAS_ATMOS_ANALYSIS_WDQMS`, correctly **absent** from develop's plain
  `:ShellScript`. The real gap: **v17 graph RELATIONSHIPS were never loaded** —
  **0** relationships touch any `GW_V17_*` node vs ~2.65M for develop. The probe
  matches `(f)-[r]-(m)`, so the edge-less anchor returns nothing. Root cause =
  incomplete `gw_v17` ingest (nodes loaded, rels skipped), NOT a missing repo
  (v17 source is on disk: `supported_repos/global-workflow_dev-v17`,
  `global-workflow.v17`, `EXPDIR_v17`).
  **Fix path**: re-run the relationship load for the `gw_v17` tenant so edges
  exist, then validate the isolation axis against real data. Graceful-skip
  (spec R4.2) is only the fallback if the v17 rel source is unavailable. Do NOT
  fabricate data. Confirm the gap first:
  ```cypher
  MATCH (n)-[r]-() WHERE any(l IN labels(n) WHERE l STARTS WITH 'GW_V17_')
  RETURN count(r)   // expect 0 before the fix, >0 after
  ```
- `github_tools` FAILS (HTTP 401) — unrelated placeholder token; out of
  scope for Phase 60.
- Tenant `workflow_root`s point at `/mnt/workflow/...` (AgentCore EFS, not
  mounted locally); filesystem tools fall back to `MCP_WORKFLOW_ROOT`.

## Deliverables

1. `mcp_server_python/scripts/branch_ground_truth.py` — source-derived
   expectation extractors (callers/callees, imports, structure, env-var
   lineage), conservative/subset-based.
2. `mcp_server_python/scripts/validate_code_awareness.py` — the 3-axis
   driver; emits a markdown summary + `code_awareness_gaps.json`.
3. Fixes in the Python tools/adapters for each triaged gap, with the
   failing probe flipped to pass and **no regressions**.
4. A condensed `code_awareness` probe wired into `smoke_queries.py` so
   `mcp_health_check(functional=true)` covers one tool per axis.
5. `CHANGELOG.md` entry (new minor version, dated header) summarizing
   gaps found/fixed and residual skips.

## Definition of done

All Phase 60 acceptance-criteria rows pass: every tool reports pass/skip
(never silent error), ground-truth + parity hold for `gw`, isolation has
0 leaks once the `gw_v17` relationships are loaded (graceful skip only if the
v17 rel source is unavailable), the gap report exists, each previously-failing
probe re-validates green, and `pytest mcp_server_python/tests` stays green.

## Hard constraints

- **SDD spec-first**: any change beyond a trivial fix must be reflected in
  the Phase 60 spec before the implementing commit.
- Run Python via the project env: `source /mcp_rag_eib/spack/share/spack/setup-env.sh`
  then `module load python/3.11.14 py-pip py-neo4j py-httpx py-pydantic`;
  invoke as `python -m ...` from `mcp_server_python/` (the package needs
  `requires-python>=3.12` only for pip install, which we bypass).
- ASCII-only console prefixes (`[OK]`, `[ERROR]`, `[WARN]`) — no emoji
  (breaks MCP stdio).
- Do **not** modify `supported_repos/` (read-only submodules).
- **Git**: stage changes for review; do NOT `git commit`/`push` or switch
  branches without explicit user approval.
- Prefer the MCP tools over shell for code analysis; use `read_file`/grep
  only for exact line-level reads.

## Suggested first actions

```
get_sdd_workflow({ workflow_name: "phase60_code_awareness_tool_parity_branch_validation" })
mcp_health_check({ detailed: true, functional: true })   # capture the baseline gap matrix
get_knowledge_base_status()                              # confirm which tenants/collections exist
start_sdd_session({ phase: "phase60_code_awareness_tool_parity_branch_validation", total_steps: 7 })
```
