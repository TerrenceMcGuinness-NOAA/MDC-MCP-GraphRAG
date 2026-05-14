# Failure Analysis Report — PR #4575, `gcdas_fcst_seg0.log`

**Log:** [`PR_4575_C96_gcafs_cycled_noDA/gcdas_fcst_seg0.log`](https://github.com/TerrenceMcGuinness-NOAA/ci-global-workflows/blob/error_logs/ci/error_logs/PR_4575_C96_gcafs_cycled_noDA/gcdas_fcst_seg0.log)
**PR:** [NOAA-EMC/global-workflow#4575](https://github.com/NOAA-EMC/global-workflow/pull/4575) — *"Perform forecast output copies to COM using MPMD"*
**CI Build tag:** `pr_cases_4575_733bbf3e_9636`
**Job:** SLURM `21988301` on `h6c51` (Hera)
**Failure timestamp:** `2026-02-25T21:26:40Z`
**Analyst:** EIB MCP-RAG investigation (May 14, 2026)
**Status:** **RESOLVED in develop** by a later commit on the same PR (`159017d0`, 2026-03-06)

---

## 1. Executive Summary

The `gcdas` forecast segment 0 job failed during the **post-forecast restart-file copy step**, not during the forecast model run itself. The model finished cleanly (`EGRESS` written at 21:26, `gocart.inst_aod.20211220_2100z.nc4` produced). The failure was in the **MPMD-driven parallel copy** of FV3 restart files from the run directory back to COM.

The proximate fault is a malformed `srun` invocation in `ush/run_mpmd.sh` line 142 (of the PR-`733bbf3e` revision):

```
srun -l --export=ALL --hint=nomultithread --multi-prog --output=mpmd.%j.%t.out -n <PATH_TO_CHUNK_FILE>
```

`-n` (alias for `--ntasks`) was passed the chunk-file path because the task-count expression was missing/empty. SLURM rejected the launch:

```
srun: error: Invalid numeric value ".../mpmd_cmdfile.chunk0" for --ntasks.
```

`run_mpmd.sh` returned 1, `forecast_postdet.sh` line 438 called `err_exit 'run_mpmd.sh failed to copy FV3 restart files!'`, and SLURM signalled the job. The trailing `JOB ... CANCELLED ... DUE to SIGNAL Terminated` is a downstream effect of `err_exit`, not the cause.

This regression existed only on PR #4575's branch at SHA `733bbf3e` and has since been **fixed by the same PR before merge** — the merged revision (`159017d0`, currently in `develop`) computes `n_mpmd_tasks=$(grep -v -c "^ *#" < "${chunk_file}")` and uses `-n "${n_mpmd_tasks}"` (verified with `git blame ush/run_mpmd.sh` lines 215–225).

---

## 2. Evidence Chain

### 2.1 Forecast model succeeded
From log tail (run-directory listing, `21:26`):
- `EGRESS` (zero-byte) — UFS clean-exit marker
- `cap_restart` (16 bytes) — written by NUOPC at end of forecast
- `gocart.inst_aod.20211220_2100z.nc4` (25 MB) — diagnostic output
- `logfile.000000.out` (167 KB) — model log

### 2.2 The MPMD copy step is what blew up
Log lines 7820–7882:

```
+ run_mpmd.sh[131] cp .../mpmd_cmdfile .../mpmd_cmdfile.tmp
+ run_mpmd.sh[133] chunk_file=.../mpmd_cmdfile.chunk0
+ run_mpmd.sh[134] chunk_mpmd .../mpmd_cmdfile.tmp 30 .../mpmd_cmdfile.chunk0
...
INFO: Number of MPMD tasks (38) is greater than the maximum tasks per node (30).
      Running MPMD job in chunks of 30 tasks per node.
+ run_mpmd.sh[142] srun -l --export=ALL --hint=nomultithread --multi-prog \
                       --output=mpmd.%j.%t.out -n .../mpmd_cmdfile.chunk0
srun: error: Invalid numeric value ".../mpmd_cmdfile.chunk0" for --ntasks.
+ run_mpmd.sh[145] echo 'ERROR: MPMD job failed for .../mpmd_cmdfile.chunk0'
+ run_mpmd.sh[218] exit 1
+ forecast_postdet.sh[438] err_exit 'run_mpmd.sh failed to copy FV3 restart files!'
    -- FATAL ERROR: run_mpmd.sh failed to copy FV3 restart files! RETURN CODE 1
```

The `chunk_mpmd` helper had built `chunk0` correctly (38 lines of `cpfs` commands seen in trace at lines 7820+) — only the *launch* failed.

### 2.3 The fix already in develop
`develop` HEAD `ush/run_mpmd.sh` lines 215–222 (blame attribution: commit `159017d0`, "Copilot 2026-03-06"):

```bash
chmod 755 "${chunk_file}"
# Count the number of lines not including commented lines (i.e. shebangs)
n_mpmd_tasks=$(grep -v -c "^ *#" < "${chunk_file}")
if [[ "${_mpmd_launcher}" == "srun" ]]; then
    source "${USHglobal}/unset_strict.sh"
    # shellcheck disable=SC2086
    ${launcher:-} ${mpmd_opt:-} -n "${n_mpmd_tasks}" "${chunk_file}"
```

`git log -- ush/run_mpmd.sh` confirms `159017d0` is the merge commit of PR #4575 itself — i.e. PR #4575 introduced both the bug and (in a later push) the fix. CI run `733bbf3e` predates the fix.

### 2.4 Misleading downstream noise
- `cat: OUTPUT.2396430: No such file or directory` — Rocoto's wait-for-OUTPUT poll, harmless after the real failure.
- `[2026-02-25T21:26:40] error: *** JOB ... CANCELLED ... DUE to SIGNAL Terminated ***` — caused by `err_exit` exiting non-zero, which Rocoto/SLURM reports as a SIGTERM cancellation in epilogue.
- `Job ... finished ... with exit code 0:0` — SLURM-level epilog sees the *batch script* (after `err_exit`'s `exit 1` was swallowed by `set +e` in `err_exit`) as exit 0. Misleading; ignore in favor of the FATAL ERROR banner.

---

## 3. Resolution

| Item | Status |
|------|--------|
| Bug present in PR #4575 commit `733bbf3e` | Confirmed |
| Fix added in PR #4575 commit `159017d0` (Copilot, 2026-03-06) | Confirmed in develop |
| Fix landed in `develop` | Yes — current `ush/run_mpmd.sh` line 222 |
| Regression risk | None for current `develop`; cherry-pick if any release branch lacks `159017d0` |
| Recommended action | Re-run failed CI case against current `develop` HEAD to close the loop on PR_4575 error_logs |

---

## 4. MCP Tool Call Log & Assessment

Each call below was issued against the EIB MCP gateway during this investigation. **Usefulness** is rated on a 1–5 scale: 5 = directly produced root cause; 1 = no signal.

| # | Tool | Inputs (key) | Useful? | What it gave us | Improvement opportunity |
|---|------|--------------|---------|-----------------|------------------------|
| 1 | `mcp_health_check` | — | 5 | 8/8 components healthy → confirms graph + vector + GitHub probes will work | Could include collection name + chunk count of *currently selected* docs collection in the same response (avoid second call) |
| 2 | `get_server_info` | — | 3 | Tool inventory, helpful to plan calls | Surface tool **schemas** (param names) inline so I don't have to discover snake_case vs camelCase by trial — see issue below |
| 3 | `get_knowledge_base_status` | — | 4 | Confirmed live collection `global-workflow-docs-v8-2-0` = 23,624 docs | Add a `selected_docs_collection` field highlighting the active one |
| 4 | `check_knowledge_integrity` | — | 4 | All 4 checks PASS → trust-the-RAG signal before relying on it | Stale-Embeddings sample (50/50) is too small for an authoritative drift answer — see "System improvements" below |
| 5 | `describe_component` | `component=ush/run_mpmd.sh` | 2 | File exists, 9638 bytes — that's it | **Should expose first ~40 lines of header docblock + functions list**; right now it duplicates `ls -l`. Also: rejected my first call because I used `path=` instead of `component=` — schema discoverability problem |
| 6 | `find_related_files` | `file_path=ush/run_mpmd.sh, depth=1` | 2 | Self-link + a leaked GEOS-Chem doc snippet (irrelevant) | Result included a wiki-style doc that has nothing to do with `run_mpmd.sh` — relevance ranker is too permissive when `Files with Similar Dependencies` is empty. Should suppress the doc section if no high-confidence hit |
| 7 | `analyze_code_structure` | `file_path=ush/run_mpmd.sh` | 4 | Reported 23 callers in the GGSR table, fan-in 23 / fan-out 5, complexity score 115 ([WARN]) | "Functions: 0" is wrong — `run_mpmd.sh` defines `chunk_mpmd` and `cat_outputs` (bash funcs). The graph extractor doesn't model bash function definitions; would have helped me locate the chunk logic |
| 8 | `find_callers_callees` | `function_name=run_mpmd.sh, direction=both` | 5 | All 23 callers + 5 callees with line numbers — gold for understanding blast radius if we needed to revert | Excellent. Worth surfacing the same view for **bash function** symbols once #7's gap is closed |
| 9 | `find_callers_callees` | `function_name=chunk_mpmd` | 1 | "0 callers / 0 callees" — symbol not modelled | Same root cause as #7: bash functions aren't ingested. High-value fix |
| 10 | `search_documentation` | "run_mpmd.sh chunked srun --multi-prog ntasks chunk_size" | 4 | Returned MPMD architecture & troubleshooting docs, including a prior failure analysis with the **exact same line-222 srun pattern** | Proof the v8-2-0 ingest is paying off (`source_type=local`/wiki). Could rank **prior failure analyses** higher when the query mentions an error symptom |
| 11 | `search_documentation` | "forecast_postdet copy FV3 restart files MPMD" | 4 | 17 KB of relevant operational docs about restart copy step | Same comment — prior diagnoses should rank above general docs when query is symptom-shaped |
| 12 | `get_pull_requests` | `repository=global-workflow, search_terms=run_mpmd chunk srun ntasks` | 2 | 5 PRs returned, **none related** — just the most-recently-updated open PRs | `search_terms` appears to be ignored or only matched against title; PR #4575 is closed/merged so wasn't returned even when explicitly searched. Need to honor the search filter and include closed/merged states properly |
| 13 | `get_pull_requests` | `search_terms=4575, state=all` | 2 | Same 5 unrelated PRs | Confirms #12 — `search_terms` is not driving the API query. **Bug.** Should pass to GitHub `q=` parameter |
| 14 | `search_issues` | "srun ntasks chunk_size mpmd_cmdfile.chunk0" | 2 | "No issues found" | Either no matching issues exist (plausible) **or** the same query-parameter problem as #12. Worth verifying with a known-hit query |
| 15 | `explain_with_context` | topic = "run_mpmd.sh srun ... FV3 restart copy failure" | 5 | Returned a prior MCP analysis chunk that contains the **exact same error pattern** ("`run_mpmd.sh line 222 ... -n 8 ... mpmd_cmdfile.chunk1`") from a wave-init failure — strong corroboration | This is the killer feature. Add an explicit "prior incident reports" facet so it's easy to retrieve only the post-mortem chunks |
| 16 | `trace_execution_path` | `from_file=scripts/exgfs_atmos_postsnd.sh, function_name=run_mpmd.sh` | 2 | Traced `run_mpmd.sh`'s callees only; `from_file` was silently ignored | The `from_file` parameter doesn't filter the trace; should either honor it or be removed. Otherwise the tool is just a duplicate of `find_callers_callees` direction=down |
| 17 | `find_env_dependencies` | `env_var=USE_CFP` | — | **Rejected** — required prop is `variable_name`, not `env_var` | Schema-discoverability bug; the JSON schema and tool description should agree on the field name. Same for `find_callers_callees` (`function_name`), `describe_component` (`component`), `analyze_code_structure` (`file_path`) |
| 18 | `find_env_dependencies` | `variable_name=USE_CFP` (retry) | 4 | 13 deps via GGSR; correctly identified `run_mpmd.sh` as a `DEPENDS_ON_ENV` consumer | Useful. The header table says "0 scripts" but the GGSR table shows 13 — the two summaries disagree, fix the count |
| 19 | `find_env_dependencies` | `variable_name=max_tasks_per_node` | 2 | "0 dependencies" — but `run_mpmd.sh` literally consumes `${max_tasks_per_node:-1}` four times | The env-extractor likely missed defaults using `${VAR:-X}` syntax. Common bash pattern; needs handling |
| 20 | `get_operational_guidance` | topic = "forecast restart copy MPMD failure recovery" | 3 | 26 KB of procedural HPC guidance | Useful breadth; a `format=summary` mode (3-bullet TL;DR) would be more actionable for incident triage |

**Score totals:** 5×4, 4×6, 3×2, 2×7, 1×1, schema-rejection×1 → average **3.0/5**, with `find_callers_callees`, `explain_with_context`, and the integrity/health stack carrying most of the weight.

---

## 5. System & Tool Improvement Recommendations

### 5.1 Schema discoverability (highest ROI)
Three tools rejected my first call because the parameter name in the description didn't match the schema (`path` vs `component`, `function_name` vs `symbol`, `env_var` vs `variable_name`). Recommend:
1. Normalize all tool inputs to **snake_case** (the majority convention in this server).
2. Have `get_server_info` emit each tool's full JSON schema, not just a category list.
3. On rejection, return the **expected schema** in the error body so the next call is one-shot.

### 5.2 Bash-function modelling gap
`chunk_mpmd` and `cat_outputs` are defined inside `run_mpmd.sh` but invisible to `find_callers_callees` and `analyze_code_structure`. Extending the shell-graph ingest (Phase 27B) to capture `function name() { ... }` and `name () { ... }` patterns would have let me query the chunk logic directly without `read_file`. **Estimated effort:** small — regex addition in the bash AST extractor + DEFINES edges.

### 5.3 GitHub PR/issue search filter is broken
`get_pull_requests(search_terms=...)` and `search_issues(query=...)` returned the same generic "recently updated" set regardless of input. The search terms are not being passed to the GitHub Search API's `q=` parameter. This makes failure-triage workflows (e.g. "did anyone else hit this?") nearly useless. **Action:** add an integration test that asserts a known PR title returns ≥1 hit.

### 5.4 Stale-Embeddings sampling
Today's integrity check sampled 50/50 docs. With 23,624 chunks and four upstream submodules that change daily, 50 samples gives wide error bars. Recommend:
- Add a `full_drift_scan` mode that compares **every** local chunk's `submodule_commit` against current submodule HEAD SHAs (cheap — one Cypher query + one git rev-parse per submodule, no embedding recompute).
- Surface drift-candidate file paths so the operator can re-ingest only what changed.

### 5.5 Surface prior incident reports
`explain_with_context` was the most valuable tool of this session because it retrieved a prior MCP analysis of an analogous failure. Recommend a dedicated metadata flag (`source_type=incident_report`) and a `search_incident_reports` tool — or at minimum a UI hint when ranking results.

### 5.6 `trace_execution_path` `from_file` parameter
Either honor the parameter as a filter on the trace's anchor or remove it from the schema; right now it's silently ignored, which is worse than a clear "not supported" error.

### 5.7 Result deduplication / relevance for sparse hits
`find_related_files` returned a GEOS-Chem `run@` symlink doc as a "related file" for `run_mpmd.sh` — pure lexical confusion (`run`). When the dependency-similarity score is ≤ threshold, suppress the documentation block instead of showing the next-best (irrelevant) hit.

### 5.8 Integrity / health unification
Three calls (`mcp_health_check`, `get_knowledge_base_status`, `check_knowledge_integrity`) cover overlapping ground. A single `get_full_status` (or `--verbose` flag on `mcp_health_check`) would reduce round-trips and give one canonical view for incident reports.

---

## 6. Conclusion

- **What broke:** PR #4575 commit `733bbf3e` shipped a `run_mpmd.sh` whose `srun` line lacked the `n_mpmd_tasks` count, causing `-n` to consume the chunk-file path and SLURM to reject the launch.
- **Where it broke:** Post-forecast FV3 restart copy step in `forecast_postdet.sh` line 438 (the model itself completed normally).
- **Status:** Fixed in the same PR's later commit `159017d0` and merged to `develop`. No action required for current builds.
- **Recommended follow-up:** rerun the CI case against `develop` HEAD to mark the regression closed; address the schema and PR-search bugs in §5.1 and §5.3 to make future MCP-driven log triage faster.

---

*Generated using the EIB MCP-RAG gateway (gateway image `eib-mcp-rag:latest`, docs collection `global-workflow-docs-v8-2-0`, 23,624 chunks). 20 MCP tool calls logged in §4.*
