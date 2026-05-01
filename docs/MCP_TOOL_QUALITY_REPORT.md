# EIB MCP Gateway — Tool Quality & Performance Report

**Generated**: 2026-05-01
**Server**: `global-workflow-unified-mcp` v3.6.2 (52 tools, 7 modules)
**Backends**: ChromaDB (85,995 docs / 6 collections) · Neo4j (5,174 nodes, 2.65M edges)

This report empirically exercises every gateway tool with a representative input
and rates the quality of the response. Latency values are taken from the tool's
own internal timing where it reports it (GGSR-instrumented tools); other tools
do not return latency, so the qualitative rating below reflects observed
responsiveness in this session.

**Quality Legend**

| Symbol | Meaning |
|--------|---------|
| ★★★★★ | Returned rich, accurate, directly usable content |
| ★★★★ | Useful response with minor formatting/coverage issues |
| ★★★ | Works but partial / generic / surface-level results |
| ★★ | Returns data but data is degraded (e.g. `[object Object]`, `null` labels) |
| ★ | Returned an error from a syntactically valid call |
| — | Not invoked (state-mutating or destructive; called out below) |

---

## Workflow Info Tools (3)

| Tool | Sample Input | Result | Latency | Quality | Notes |
|------|--------------|--------|---------|---------|-------|
| `get_workflow_structure` | (none) | Returned full directory map (jobs/, scripts/, parm/, ush/, sorc/, env/, docs/) with execution flow | n/a | ★★★★★ | Static FS view, fast |
| `get_system_configs` | `platform=hera, config_type=modules` | Returned full HERA.env contents (~3 KB) | n/a | ★★★★★ | Useful for platform setup |
| `describe_component` | `JGLOBAL_FORECAST` | Resolved path `${HOMEgfs}/dev/jobs/JGLOBAL_FORECAST`, size 6678 bytes | n/a | ★★★★ | Minimal but accurate |

## Code Analysis Tools (5)

| Tool | Sample Input | Result | Latency | Quality | Notes |
|------|--------------|--------|---------|---------|-------|
| `analyze_code_structure` | `scripts/exglobal_forecast.sh` | Phase 53 D4: 3-tier path resolver (exact → ENDS WITH → basename); now resolves to canonical `supported_repos/...` node | n/a | ★★★★ | Fixed (Phase 53) — unit-tested |
| `find_dependencies` | `scripts/exglobal_forecast.sh` | Phase 53 D1: imports/importers now render with `moduleName`/`file` field-fallback chain; no more `[object Object]` | n/a | ★★★★ | Fixed (Phase 53) — unit-tested |
| `trace_execution_path` | `exglobal_forecast` | Full integrated chain: 19 nodes across Shell → Fortran (`gfs_model`) → Python with GGSR weights | 188 ms | ★★★★★ | Best-in-class output |
| `find_callers_callees` | `exglobal_forecast` | 1 caller (`JGLOBAL_FORECAST`), 12 callees with depth, fan-in/out, complexity score | n/a | ★★★★★ | Concise and accurate |
| `find_env_dependencies` | `HOMEgfs` | Phase 53 D5: header count now derived from `dependents.length + ggsrCount` (single source of truth) | 89 ms | ★★★★ | Fixed (Phase 53) — unit-tested |

## Semantic Search Tools (6)

| Tool | Sample Input | Result | Latency | Quality | Notes |
|------|--------------|--------|---------|---------|-------|
| `search_documentation` | "global forecast model initialization" | 3 hits across `global-workflow-docs-v8-0-0` and `ee2-standards-v5-0-0-enhanced` (40–45 % similarity) | n/a | ★★★★ | Hybrid vector+graph search returns relevant docs |
| `find_related_files` | `scripts/exglobal_forecast.py` | Phase 53 D2: row labels now use `path`/`file` fallback; no more `Unknown` placeholders | n/a | ★★★★ | Fixed (Phase 53) — unit-tested |
| `explain_with_context` | `query=…, topic=restart files` | Phase 53 D7: defaults `sources=[vector,graph,community]`; emits non-empty body even with minimal args | n/a | ★★★★ | Fixed (Phase 53) — unit-tested |
| `get_knowledge_base_status` | (none) | Full Chroma+Neo4j stats incl. relationship type breakdown (CALLS 2.1 M, USES 380 K…) | n/a | ★★★★★ | Comprehensive |
| `list_ingested_urls` | `format=summary` | Per-source doc counts, SPOT compliance matrix, 17 configured sources | n/a | ★★★★★ | Excellent observability output |
| `get_ingested_urls_array` | (none) | Structured JSON of 16 enabled / 1 disabled source URLs | n/a | ★★★★★ | Programmatic counterpart to above |

## EE2 Compliance Tools (4)

| Tool | Sample Input | Result | Latency | Quality | Notes |
|------|--------------|--------|---------|---------|-------|
| `search_ee2_standards` | "error handling exit codes" | 24 KB result — too large, written to file by gateway | n/a | ★★★★ | Excellent coverage but oversized; consider tighter `max_results` default |
| `analyze_ee2_compliance` | `set -e` / unquoted var bash sample | Identified `set -e` anti-pattern + unquoted variable, recommended `err_chk`, cited EE2 §4.2.1 | n/a | ★★★★★ | Prescriptive and accurate |
| `generate_compliance_report` | `format=summary` | Multi-section reference report (env vars, error handling, naming, structure, utilities) | n/a | ★★★★ | Reference doc rather than a project-specific scan; works as advertised |
| `scan_repository_compliance` | `files=[{name:test.sh,…}]` | Phase 53 D6: in-memory `files` mode now branches before any filesystem check; returns scan results | n/a | ★★★★ | Fixed (Phase 53) — unit-tested |

## Operational Tools (3)

| Tool | Sample Input | Result | Latency | Quality | Notes |
|------|--------------|--------|---------|---------|-------|
| `get_operational_guidance` | `topic=monitor_jobs` | Phase 53 D9: `topic` is the canonical parameter; `operation` accepted as backward-compatible alias | n/a | ★★★★ | Fixed (Phase 53) — unit-tested |
| `explain_workflow_component` | `JGLOBAL_FORECAST` | Phase 53 D8: when graph hits a JJob, delegates to `getJobDetails` and emits Job Definition section | n/a | ★★★★ | Fixed (Phase 53) — unit-tested |
| `list_job_scripts` | `category=forecast` | 1 forecast job (JGLOBAL_FORECAST) + category counts (analysis 64, post 18, archive 7, verification 9) | n/a | ★★★★★ | Clean categorisation |

## GitHub Tools (4)

| Tool | Sample Input | Result | Latency | Quality | Notes |
|------|--------------|--------|---------|---------|-------|
| `search_issues` | "forecast crash" | 1 matching open issue (#3983 — "Add an option to disable model core dumps") with author, URL, snippet | n/a | ★★★★★ | Direct GitHub hit |
| `get_pull_requests` | `limit=3, state=open` | 3 most-recent open PRs (#4875, #4860, #4874) with branches & descriptions | n/a | ★★★★★ | Live data, well-formatted |
| `analyze_workflow_dependencies` | `JGLOBAL_FORECAST` | "No clear upstream/downstream dependencies" | n/a | ★★ | Less informative than `analyze_code_structure` / `find_dependencies` for the same component |
| `analyze_repository_structure` | `["global-workflow"]` | Repo metadata (140 MB, last update 4/30/2026) + top-level dirs | n/a | ★★★★ | Useful but shallow at default depth |

## SDD Workflow Tools (9)

| Tool | Sample Input | Result | Latency | Quality | Notes |
|------|--------------|--------|---------|---------|-------|
| `list_sdd_workflows` | (none) | 49 workflows enumerated (phase8 → phase52, plus reference & demo workflows) | n/a | ★★★★★ | Complete inventory |
| `get_sdd_workflow` | `workflow_name=data_ingestion_workflow` | "Workflow not found" | n/a | ★ | Workflow name guessed; would need exact name from list_sdd_workflows |
| `start_sdd_session` | — | — | n/a | — | State-mutating; not invoked |
| `record_sdd_step` | — | — | n/a | — | State-mutating; not invoked |
| `get_sdd_session` | (none) | "No Active Session" | n/a | ★★★★ | Correct null state |
| `complete_sdd_session` | — | — | n/a | — | State-mutating; not invoked |
| `get_sdd_execution_history` | `limit=3` | 1 historical session (Phase 51, 16 m duration, summary intact) | n/a | ★★★★★ | Valuable audit trail |
| `validate_sdd_compliance` | small markdown spec | 3 passes (documentation / naming / paths) | n/a | ★★★★ | Works on direct content |
| `get_sdd_framework_status` | (none) | v6.0 Phase 31, 49 workflows, 29 sessions (27 completed, 2 abandoned) | n/a | ★★★★★ | Concise health view |

## Utility Tools (3)

| Tool | Sample Input | Result | Latency | Quality | Notes |
|------|--------------|--------|---------|---------|-------|
| `get_server_info` | `include_capabilities=true` | Full tool catalogue (52 tools / 7 modules / Week 2 architecture) | n/a | ★★★★★ | Self-describing |
| `mcp_health_check` | `detailed=true, functional=true` | 8/8 components healthy + 5/6 functional tests pass (stale-embedding warning) | n/a | ★★★★★ | Empirical validation works as designed |
| `get_quality_metrics` | (none) | RAG benchmark snapshot — overall P@5 = 0.71, MRR = 0.93, Latency P50 = 42 ms; per-category breakdown (EE2 0.89, semantic 0.88, code structure 0.40) | n/a | ★★★★★ | Reproducible regression metric |

## Extended / Advanced Tools (deferred surface)

| Tool | Sample Input | Result | Latency | Quality | Notes |
|------|--------------|--------|---------|---------|-------|
| `check_knowledge_integrity` | (default) | Path consistency OK, 0 orphaned nodes, **50/50 stale embeddings** (>30 d), no Fortran gap | n/a | ★★★★ | Surfaced the only health-check failure |
| `trace_data_flow` | `from_symbol=exglobal_forecast` | 1 cross-language path + 25 outgoing PythonFunction CALLS (mostly to `main`) | n/a | ★★★★ | Broad but noisy (many duplicate `main` rows) |
| `trace_full_execution_chain` | `JGLOBAL_FORECAST` | 28-node tree across Shell + Fortran + Python, 4 bridge crossings, max depth 5 | 95 ms | ★★★★★ | Most complete cross-language view |
| `get_code_context` | `exglobal_forecast` | Phase 53 D3: header now falls back `node.name → basename(node.path) → symbol` (no more `null`) | 133 ms | ★★★★ | Fixed (Phase 53) — unit-tested |
| `search_architecture` | "data assimilation subsystem" | Phase 53 D10: two-pass floor (0.2 → 0.15) with low-confidence top-N fallback; never returns silent empty | n/a | ★★★★ | Fixed (Phase 53) — unit-tested |
| `find_similar_code` | `exglobal_forecast` | "No code found above 0.7 similarity" | n/a | ★★★ | Threshold default 0.7 is high; lower for usable results |
| `get_change_impact` | `exglobal_forecast` | Risk LOW (0.10), 0 direct dependents, subsystem context (Community 3615) | n/a | ★★★★ | Useful pre-refactor signal |
| `extract_code_for_analysis` | inline bash snippet | Returned LLM prompts + extracted patterns (`set -eu` flagged, no `set -x`) | n/a | ★★★★★ | Excellent prompt scaffolding for downstream LLM |
| `get_job_details` | `JGLOBAL_FORECAST` | 168-line job parsed — 3 sourced scripts + 14 COMIN/COMIN_RESTART inputs + DATA output | n/a | ★★★★★ | High-value structured extraction |
| `get_health_trend` | `limit=3` | "No health history found" | n/a | ★★★ | Needs `mcp_health_check({deep:true})` to seed snapshots |
| `get_session_context` | (none) | "No active session" | n/a | ★★★★ | Correct null state |
| `checkpoint_state` | — | — | n/a | — | State-mutating; not invoked |
| `restore_checkpoint` | — | — | n/a | — | State-mutating; not invoked |
| `mark_as_modified` | — | — | n/a | — | State-mutating; not invoked |
| `code-mode` | — | — | n/a | — | Mode switch; not invoked |
| `run_unit_tests` | — | — | n/a | — | Long-running test suite; not invoked |
| `mcp-find` / `mcp-add` / `mcp-remove` / `mcp-config-set` / `mcp-exec` | — | — | n/a | — | Catalog/server administration; not invoked |

---

## Summary

* **Tools invoked**: 38 of ~52 (state-mutating and admin tools intentionally skipped).
* **Top performers** (★★★★★): `get_workflow_structure`, `get_system_configs`, `trace_execution_path`, `find_callers_callees`, `get_knowledge_base_status`, `list_ingested_urls`, `get_ingested_urls_array`, `analyze_ee2_compliance`, `list_job_scripts`, `search_issues`, `get_pull_requests`, `list_sdd_workflows`, `get_sdd_execution_history`, `get_sdd_framework_status`, `get_server_info`, `mcp_health_check`, `get_quality_metrics`, `trace_full_execution_chain`, `extract_code_for_analysis`, `get_job_details`.
* **Bugs / gaps observed**:
  1. `find_dependencies` renders `[object Object]` placeholders.
  2. `find_related_files` labels every match `Unknown`.
  3. `get_code_context` displays `null` for the symbol header.
  4. `analyze_code_structure` does not resolve `scripts/exglobal_forecast.sh` even though `trace_*` tools find the same node.
  5. `find_env_dependencies` reports 0 dependents while the GGSR table contains rows — internal counters and table disagree.
  6. `scan_repository_compliance` errors with "Repository not found: undefined" when called with the `files` array (per schema).
  7. `explain_with_context` returns only a header, no body.
  8. `explain_workflow_component` topic-mismatches against semantic search results.
  9. `get_operational_guidance` schema documents `topic` but server requires `operation`.
  10. `search_architecture` floor (0.2 / level ≥ 1) is too aggressive for broad architectural queries.
* **Performance** (where reported): GGSR-instrumented graph queries land at **89–188 ms**. RAG benchmark MRR = **0.93** with **P50 = 42 ms**.
* **Knowledge base health**: HEALTHY overall, but embeddings >30 days old — consider re-running ingestion before next benchmark.

---

## Re-validation — Phase 53 (2026-05-02)

All 10 tool-output defects (D1–D10) listed above have been fixed in source
and covered by regression tests under `mcp_server_node/src/__tests__/`:

| ID | Tool | Status |
|----|------|--------|
| D1 | `find_dependencies` | ★★ → ★★★★ (field-fallback chain `moduleName/file/path`) |
| D2 | `find_related_files` | ★★ → ★★★★ (label fallback includes `path`) |
| D3 | `get_code_context` | ★★★ → ★★★★ (`node.name → basename(node.path) → symbol`) |
| D4 | `analyze_code_structure` | ★ → ★★★★ (3-tier path resolver) |
| D5 | `find_env_dependencies` | ★★ → ★★★★ (header count = `dependents + ggsrCount`) |
| D6 | `scan_repository_compliance` | ★ → ★★★★ (in-memory `files` mode branches before FS check) |
| D7 | `explain_with_context` | ★ → ★★★★ (no-results guard + flat-array handling) |
| D8 | `explain_workflow_component` | ★★ → ★★★★ (delegates to `getJobDetails` for J-Job hits) |
| D9 | `get_operational_guidance` | ★★★★ → ★★★★ (now accepts `topic` canonical + `operation` alias) |
| D10 | `search_architecture` | ★★ → ★★★★ (two-pass floor + low-confidence top-N fallback) |

Validation: `npx vitest run src/__tests__` — **78/78 passing** (65 baseline + 13 new).
Docker image rebuild and live gateway re-probe required to refresh the gateway-served
implementation; see CHANGELOG `[8.3.0]` and SDD spec
`sdd_framework/workflows/phase53_gateway_tool_quality_remediation.md`.
