# Phase 55: Log-Triage Tooling Gaps

**Version**: 1.0.0
**Status**: In Progress
**Created**: 2026-05-14
**Author**: AI Assistant + Terry McGuinness
**Dependency**: Phase 27B (Shell-script graph), Phase 48 (Local-first doc migration), Phase 53 (Gateway Tool Quality Remediation)
**Related**:
- [docs/log_reviews/PR4575_gcdas_fcst_seg0_failure_analysis.md](../../docs/log_reviews/PR4575_gcdas_fcst_seg0_failure_analysis.md) — origin incident report
- [docs/MCP_TOOL_QUALITY_REPORT.md](../../docs/MCP_TOOL_QUALITY_REPORT.md)
- `.github/instructions/eib-mcp-tools.instructions.md` (the "Diagnose a job/run failure log" recipe)

---

## 1. Executive Summary

Driving the EIB MCP toolset through a real CI failure log (PR #4575,
`gcdas_fcst_seg0.log`) on 2026-05-14 surfaced **seven actionable gaps** that
limit how effectively the gateway supports job-failure triage. Five of the
seven are independent of the defects already enumerated in Phase 53; two
(D5-style header/body counter mismatch, schema/server contract drift) are
restated here only as cross-references.

Each gap is small in isolation; together they are the difference between
"MCP tools accelerated the diagnosis" and "MCP tools just confirmed what
`grep` already showed." The phase exists because the underlying data
(graph + v8-2-0 docs corpus) is ready — the value is being left on the
floor by surface-level tool behavior.

## 2. Scope

**In scope** — the seven gaps below.

| # | Area | One-line statement |
|---|------|--------------------|
| G1 | Shell graph: bash function modelling | `function name() { … }` definitions are not ingested → `find_callers_callees` and `analyze_code_structure` cannot see in-script helpers (e.g. `chunk_mpmd`, `cat_outputs` in `ush/run_mpmd.sh`) |
| G2 | GitHub tools: search filter not honored | `get_pull_requests({search_terms})` and `search_issues({query})` ignore the filter and return the most-recently-updated set regardless of input |
| G3 | Drift detection: full-coverage scan mode | `check_knowledge_integrity` samples 50/50 docs against git; for a 23,624-chunk live collection that is too coarse — need an opt-in `full_drift_scan` |
| G4 | Incident-report retrieval | Prior failure post-mortems are searchable only by chance via `search_documentation`; no `source_type=incident_report` flag and no dedicated retrieval tool |
| G5 | `trace_execution_path` `from_file` parameter | Optional `file_path` is silently ignored; either honor it as a trace anchor or remove from the schema |
| G6 | `find_related_files` relevance floor | When dependency-similarity has no hits, the tool falls back to a documentation result that is often lexically (not semantically) related (e.g. GEOS-Chem `run@` symlink doc returned for `ush/run_mpmd.sh`) |
| G7 | Bash default-value env extraction | `find_env_dependencies` misses consumers that use `${VAR:-default}` (confirmed for `max_tasks_per_node`); needs a regex/AST update in the env-extractor |

**Cross-references (already owned by Phase 53; do not re-fix here)**
- D5 — `find_env_dependencies` header count vs GGSR table mismatch.
- D9-class issues — schema/server parameter contract drift (now mostly closed by the `eib-mcp-tools.instructions.md` table; no further work in this phase).

**Out of scope**
- Re-ingestion of any collection.
- New tool development beyond G3 and G4 (and an *alias* on G5 if chosen over silent-ignore).
- UI/UX polish of report formatting (separate phase).

## 3. Acceptance Criteria

The phase is complete when the following hold simultaneously:

| # | Probe | Pre-fix | Post-fix |
|---|-------|---------|----------|
| A1 | `find_callers_callees({function_name:"chunk_mpmd"})` | "0 callers / 0 callees" | Lists `run_mpmd.sh` as definer + the for-loop call site (line ~134) |
| A2 | `analyze_code_structure({file_path:"ush/run_mpmd.sh"})` | `Functions: 0` | `Functions: 2` (`chunk_mpmd`, `cat_outputs`) with line refs |
| A3 | `get_pull_requests({repository:"global-workflow", search_terms:"run_mpmd ntasks"})` | 5 most-recent PRs (filter ignored) | Returns PR #4575 (or other PRs whose title/body matches) regardless of state |
| A4 | `search_issues({repository:"global-workflow", query:"<known-hit-string>"})` | "No issues found" | Returns the known-hit issue |
| A5 | `check_knowledge_integrity({mode:"full_drift_scan", collection:"global-workflow-docs-v8-2-0"})` | (mode unsupported) | Per-submodule report: chunks-with-stale-`submodule_commit` count, list of file_path candidates needing re-ingest |
| A6a | New `search_incident_reports({query:"…"})` | (tool absent) | Returns ≤ N matches restricted to `source_type=incident_report` chunks |
| A6b | `ingest_local_docs_v8.py` for `docs/log_reviews/**/*.md` writes `source_type=incident_report` | (no such source) | Confirmed in chunk metadata after ingest |
| A7 | `trace_execution_path({function_name:"run_mpmd.sh", from_file:"scripts/exgfs_atmos_postsnd.sh"})` | `from_file` silently ignored | Either (a) trace is anchored at the named caller, or (b) the parameter is removed from the schema |
| A8 | `find_related_files({file_path:"ush/run_mpmd.sh"})` | Returns GEOS-Chem `run@` doc as related | Documentation block omitted when no hit clears configurable similarity floor (default 0.65) |
| A9 | `find_env_dependencies({variable_name:"max_tasks_per_node"})` | "0 dependencies" | `run_mpmd.sh` listed as a `DEPENDS_ON_ENV` consumer |
| A10 | `run_unit_tests` | passing | passing + 7 new regression tests (one per gap) |
| A11 | Re-run of [docs/log_reviews/PR4575_gcdas_fcst_seg0_failure_analysis.md](../../docs/log_reviews/PR4575_gcdas_fcst_seg0_failure_analysis.md) §4 tool table | 7 gaps logged | All 7 close (rated ★★★★ or better) |

## 4. Investigation & Implementation Plan

### 4.1 G1 — Bash function modelling (Shell graph extension)

- **Files**: `mcp_server_node/scripts/ingest_code_v8.py` (or wherever the shell-graph extractor lives — verify with `grep -rn "INVOKES" mcp_server_node/scripts/`).
- **Change**: extend the regex/AST pass to detect both bash function syntaxes:
  - `name() {` and `function name {` and `function name() {`
- **Graph emission**: add `(:Function {name, file_path, start_line, end_line, language:'bash'})` nodes and `(:File)-[:DEFINES]->(:Function)` edges. Reuse the existing `INVOKES` scan to detect calls to these names *within the same file* and emit `(:Function)-[:CALLS]->(:Function)` edges.
- **Re-ingest**: targeted re-run for `ush/`, `scripts/`, `dev/scripts/` only (no full graph rebuild needed).
- **Verification**: A1, A2.

### 4.2 G2 — GitHub search filter

- **File**: `mcp_server_node/src/tools/GitHubTools.js` (look for `getPullRequests`, `searchIssues`).
- **Bug**: `search_terms` / `query` are accepted in the schema but never appended to the GitHub Search API `q=` parameter. Likely a missed mapping when the tool was first wired.
- **Change**: thread the parameter through to `octokit.rest.search.issuesAndPullRequests({ q: \`${query} repo:NOAA-EMC/${repository}\` })`. Default `state:"all"` when caller omits it.
- **Tests**: integration test asserting a known-hit title returns ≥1 result; assert empty/no-arg call still works.
- **Verification**: A3, A4.

### 4.3 G3 — `full_drift_scan` mode

- **File**: `mcp_server_node/src/tools/SemanticSearchTools.js` (`check_knowledge_integrity`).
- **Change**: add optional `mode: "sample" | "full_drift_scan"` (default "sample") and `collection` arg.
- **Algorithm (full_drift_scan)**:
  1. Query Chroma for all chunks where `source_type == "local"`, project `(submodule, submodule_commit, file_path)`.
  2. For each unique `submodule`, run `git -C supported_repos/<submodule> rev-parse HEAD`.
  3. Aggregate: count chunks per submodule with stale `submodule_commit`, and list distinct `file_path`s that still exist on disk + need re-ingest.
- **Output**: per-submodule table (total chunks, stale chunks, % stale, top-10 stale file_paths).
- **Cost**: ~1 ChromaDB query + N git calls (N = number of submodules, currently 4). No embedding recomputation.
- **Verification**: A5.

### 4.4 G4 — Incident-report corpus + retrieval

- **Source addition (`documentation_sources_config.py`)**: new entry under `LOCAL_DOCUMENTATION_SOURCES`:
  ```python
  {
      "name": "incident-reports",
      "submodule": None,                 # not a submodule — repo-internal
      "paths": ["docs/log_reviews/"],
      "extensions": [".md"],
      "parser": "markdown",
      "tier": "post-mortem",
      "metadata_overrides": { "source_type": "incident_report" },
  }
  ```
  (Confirm metadata-overrides hook exists in `ingest_local_docs_v8.py`; if not, add it.)
- **New tool `search_incident_reports`** (in `SemanticSearchTools.js`): thin wrapper over `search_documentation` that hard-filters `where: {"source_type":"incident_report"}` on the Chroma query.
- **Re-ingest**: small (only `docs/log_reviews/*.md`).
- **Verification**: A6a, A6b.

### 4.5 G5 — `trace_execution_path.from_file` semantics

- **File**: `mcp_server_node/src/tools/CodeAnalysisTools.js` (`traceExecutionPath`).
- **Decision**: pick one
  - **Option A (preferred)** — use `from_file` as the anchor: the trace starts at `(:Function {name: function_name})-[:DEFINED_IN|MEMBER_OF]->(:File {path: from_file})` and walks `CALLS` edges from there.
  - **Option B** — remove the parameter from the schema; document that this tool always traces all definitions of the symbol.
- **Verification**: A7.

### 4.6 G6 — `find_related_files` similarity floor

- **File**: `mcp_server_node/src/tools/SemanticSearchTools.js` (`findRelatedFiles`).
- **Change**: add optional `min_similarity` (default 0.65). When the documentation similarity score for the top hit is below this floor, omit the `## Related Documentation` section entirely instead of rendering a low-confidence match. Always return the dependency-graph rows regardless.
- **Verification**: A8.

### 4.7 G7 — Bash `${VAR:-default}` env extraction

- **File**: same shell-graph extractor as G1.
- **Bug**: current regex matches `${VAR}` and `$VAR` but skips `${VAR:-default}`, `${VAR:?msg}`, `${VAR-x}`, `${VAR=x}`.
- **Change**: extend the consumer-pattern regex to `\$\{[A-Za-z_][A-Za-z0-9_]*([:?=+\-][^}]*)?\}`.
- **Re-ingest**: same targeted scope as G1.
- **Verification**: A9.

## 5. Test Matrix

| Test ID | Module | Verifies |
|---------|--------|----------|
| T-G1-1 | `CodeAnalysisTools.test.js` | `chunk_mpmd` resolvable; lines in `(start_line, end_line)` |
| T-G1-2 | `CodeAnalysisTools.test.js` | `find_callers_callees` returns intra-file caller for `chunk_mpmd` |
| T-G2-1 | `GitHubTools.test.js` | `q` parameter forwarded; mock returns title-matched PR |
| T-G3-1 | `SemanticSearchTools.test.js` | `full_drift_scan` returns per-submodule structure with required keys |
| T-G4-1 | `SemanticSearchTools.test.js` | `search_incident_reports` hard-filters on `source_type` |
| T-G5-1 | `CodeAnalysisTools.test.js` | `from_file` anchors the trace (Option A) OR test removed (Option B) |
| T-G6-1 | `SemanticSearchTools.test.js` | doc block omitted below `min_similarity` floor |
| T-G7-1 | `CodeAnalysisTools.test.js` | `${VAR:-default}` consumer detected |

Acceptance gate: `run_unit_tests` reports all green before commit (per repo pre-commit policy).

## 6. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| G1 re-ingest churns CALLS edge count and breaks downstream tests | Targeted re-ingest of shell only; snapshot `MATCH (:Function)-[:CALLS]->() RETURN count(*)` before/after; expected delta is additive |
| G3 full scan blows up Chroma round-trip on a future 100k-doc collection | Stream paginated Chroma `get` calls (page = 5,000); cap `top-N stale` at 10 per submodule |
| G4 metadata override conflicts with existing source-name dedupe | Use `source_name="incident-reports"` distinct from other entries; SHA dedupe is already per-source |
| G6 floor too aggressive hides genuine hits | Floor is configurable per call; default chosen empirically (0.65 ≈ semantic-strong threshold from Phase 44) |
| G7 regex false-positives on shell expansions like `${10}` (positional args) | Restrict capture group to `[A-Za-z_]` start char (already in proposed regex) |

## 7. Deliverables

1. Code changes in:
   - `mcp_server_node/scripts/ingest_code_v8.py` (G1, G7)
   - `mcp_server_node/scripts/documentation_sources_config.py` (G4)
   - `mcp_server_node/scripts/ingest_local_docs_v8.py` (G4 — metadata-override hook if missing)
   - `mcp_server_node/src/tools/GitHubTools.js` (G2)
   - `mcp_server_node/src/tools/SemanticSearchTools.js` (G3, G4 new tool, G6)
   - `mcp_server_node/src/tools/CodeAnalysisTools.js` (G5)
2. New unit tests per §5.
3. Targeted re-ingest of shell scripts (G1, G7) and incident reports (G4).
4. Docker image rebuild + `systemctl restart mcp-rag mcp-gateway`.
5. Re-run [docs/log_reviews/PR4575_gcdas_fcst_seg0_failure_analysis.md](../../docs/log_reviews/PR4575_gcdas_fcst_seg0_failure_analysis.md) §4 tool table; update assessments.
6. CHANGELOG entry under next minor version.
7. `.github/instructions/eib-mcp-tools.instructions.md` updates:
   - Document `search_incident_reports` and `check_knowledge_integrity({mode:"full_drift_scan"})`.
   - Add G5 decision (Option A or B) to the `trace_execution_path` row.

## 8. Completion Checklist

- [ ] All 11 acceptance probes (A1–A11) pass.
- [ ] All 8 new unit tests pass via `run_unit_tests`.
- [ ] Docker image `eib-mcp-rag:latest` rebuilt; gateway restarted.
- [ ] `mcp_health_check` 8/8.
- [ ] `check_knowledge_integrity` (sample mode) still 4/4 PASS.
- [ ] PR4575 incident report re-validated with updated tool ratings.
- [ ] CHANGELOG, instructions file, and this SDD spec marked Complete.

---

*Origin: 2026-05-14 incident-driven exercise of MCP toolset against
`gcdas_fcst_seg0.log`. Authoritative recommendation list lives in §5 of
the corrected incident report (see Related links above).*
