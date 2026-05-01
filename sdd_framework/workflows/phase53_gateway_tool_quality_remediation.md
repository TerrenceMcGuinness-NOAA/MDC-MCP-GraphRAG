# Phase 53: Gateway Tool Quality Remediation

**Version**: 1.0.0
**Status**: Draft
**Created**: 2026-05-01
**Author**: AI Assistant + Terry McGuinness
**Dependency**: Phase 51 (Gateway Health/Explain/Architecture Fixes), Phase 27B (J-Job graph)
**Related**: [docs/MCP_TOOL_QUALITY_REPORT.md](../../docs/MCP_TOOL_QUALITY_REPORT.md), Phase 29 (Tool Usability), Phase 43 (Self-Diagnosis)

---

## 1. Executive Summary

The 2026-05-01 empirical exercise of all 52 EIB MCP Gateway tools (see
[docs/MCP_TOOL_QUALITY_REPORT.md](../../docs/MCP_TOOL_QUALITY_REPORT.md))
identified **10 reproducible defects** that degrade tool output quality even
though the underlying data is healthy (Neo4j: 5,174 nodes / 2.65M edges;
ChromaDB: 85,995 docs / 6 collections; mcp_health_check: 8/8 components OK,
5/6 functional probes pass).

The defects span four classes:
1. **Serialization bugs** — graph entities rendered as `[object Object]`,
   `Unknown`, or `null` in user-facing strings.
2. **Counter / data disagreement** — header counts contradict the underlying
   data table in the same response.
3. **Schema-vs-server contract drift** — declared parameters are not honored
   or are required under a different name.
4. **Threshold and resolution defaults** — paths, similarity floors, and
   topic resolution that silently produce empty or wrong-component results.

This phase fixes each defect at the source, adds regression unit tests so the
report's probes become permanent fixtures, rebuilds the
`eib-mcp-rag:latest` image, and re-runs the full report as the acceptance
gate.

## 2. Scope

**In scope** — every defect listed in §3 of
[docs/MCP_TOOL_QUALITY_REPORT.md](../../docs/MCP_TOOL_QUALITY_REPORT.md):

| # | Tool | Defect (one-line) |
|---|------|-------------------|
| D1 | `find_dependencies` | Imports rendered as `[object Object]` placeholders |
| D2 | `find_related_files` | Every related file labelled `Unknown` |
| D3 | `get_code_context` | Header shows `null` for the symbol name |
| D4 | `analyze_code_structure` | Cannot resolve `scripts/exglobal_forecast.sh` (other tools can) |
| D5 | `find_env_dependencies` | Header reports 0 deps while GGSR table has rows |
| D6 | `scan_repository_compliance` | Errors `"Repository not found: undefined"` when `files=[…]` is supplied |
| D7 | `explain_with_context` | Returns only header, no body content |
| D8 | `explain_workflow_component` | Returns nearest doc instead of requested component |
| D9 | `get_operational_guidance` | Schema documents `topic`; server requires `operation` |
| D10 | `search_architecture` | Default similarity floor 0.2 / level ≥ 1 too aggressive for broad queries |

**Out of scope**
* Embedding re-ingestion (handled by stale-embeddings warning in Phase 38 / 46).
* New tool development.
* Changes to ChromaDB v2 / Neo4j schemas.
* Live RAG benchmark recalibration (Phase 44 owns that).

## 3. Acceptance Criteria

The phase is complete when the following hold simultaneously:

| # | Probe | Pre-fix | Post-fix |
|---|-------|---------|----------|
| A1 | `find_dependencies({target:"scripts/exglobal_forecast.py"})` | `[object Object]` lines | Each import line shows file path + symbol |
| A2 | `find_related_files({file_path:"scripts/exglobal_forecast.py"})` | rows labelled `Unknown` | Rows labelled with file path |
| A3 | `get_code_context({symbol:"exglobal_forecast"})` | `# Code Context: \`null\`` | `# Code Context: \`exglobal_forecast\`` |
| A4 | `analyze_code_structure({file_path:"scripts/exglobal_forecast.py"})` | `File not found` | Returns full structure (matches `find_callers_callees` content) |
| A5 | `find_env_dependencies({variable_name:"HOMEgfs"})` | 0 deps reported, GGSR shows rows | Header count matches GGSR table row count |
| A6 | `scan_repository_compliance({files:[{name,…}]})` | `Repository not found: undefined` | Returns per-file compliance findings |
| A7 | `explain_with_context({query:"…", topic:"…"})` | Header only | Multi-section body (semantic + graph context) |
| A8 | `explain_workflow_component({component:"JGLOBAL_FORECAST"})` | Returns EE2 file-naming doc | Returns J-job sourced scripts + inputs/outputs (mirrors `get_job_details` summary) |
| A9 | `get_operational_guidance({topic:"…"})` | Server error requires `operation` | Accepts `topic` (alias) and returns guidance |
| A10 | `search_architecture({query:"data assimilation subsystem"})` | "No matches" | Returns ≥ 1 L1/L2 community summary |
| A11 | `npx vitest run src/__tests__` | passing | passing + 10 new regression tests |
| A12 | `mcp_health_check({functional:true})` | 5/6 functional probes | 5/6 (stale-embedding warning unchanged) |
| A13 | Re-run of `MCP_TOOL_QUALITY_REPORT.md` probes | 10 ★/★★ rows | All 10 raised to ★★★★ or ★★★★★ |

## 4. Investigation & Implementation Plan

Each defect gets a research → implement → validate triplet. All file paths are
under `mcp_server_node/` unless noted.

---

### Step 1 — Reproduce the report locally
**Tag**: `research`
**Target**: `mcp_server_node/`

Reproduce all 10 failing tool calls in native (stdio) mode against the same
ChromaDB/Neo4j to confirm the bugs are in source, not in the snapshotted
Docker image.

```bash
npm start &
# Then issue the 10 probes via the test harness or vitest fixtures
```

Record exact request/response for each to seed the regression test fixtures.

---

### Step 2 — D1 fix: `find_dependencies` `[object Object]` rendering
**Tag**: `implement`
**Target**: `src/tools/CodeAnalysisTools.js#findDependencies`

Root-cause hypothesis: imports come back as `{ name, file }` objects but a
template literal does `${imp}` instead of `${imp.name}` (or `${imp.file}::${imp.name}`).

Fix: render `\`${imp.file ?? '?'}\` :: \`${imp.name ?? imp.toString()}\``.
Add a defensive coercion for legacy string entries.

---

### Step 3 — D2 fix: `find_related_files` `Unknown` labels
**Tag**: `implement`
**Target**: `src/tools/SemanticSearchTools.js#findRelatedFiles`

Root-cause hypothesis: result rows pull `node.path` but graph query alias is
`f.path`, leaving `node.path` undefined → falls back to `'Unknown'`.

Fix: align Cypher RETURN aliases with the JS post-processor; add a unit test
that mocks a query result and asserts every label is non-empty.

---

### Step 4 — D3 fix: `get_code_context` `null` symbol header
**Tag**: `implement`
**Target**: `src/tools/CodeAnalysisTools.js#getCodeContext` (also referenced from `GraphRAGTools.js`)

Root-cause hypothesis: when the symbol resolves to a `:File` node, the header
formatter reads `node.name`, but file nodes only carry `path`. Should fall
back to `path.split('/').pop()` or echo the user-supplied `symbol` argument.

---

### Step 5 — D4 fix: `analyze_code_structure` path resolver
**Tag**: `implement`
**Target**: `src/tools/CodeAnalysisTools.js#analyzeCodeStructure`

Root-cause hypothesis: lookup is exact-match against `:File.path`. Other
tools (`trace_execution_path`, `find_callers_callees`) succeed because they
match by basename. `scripts/exglobal_forecast.sh` fails because the actual
node path includes the supported_repos prefix or the script is under
`dev/scripts/`.

Fix:
1. Normalize input by stripping leading `scripts/`, `ush/`, `jobs/`.
2. Try exact match → suffix match (`ENDS WITH path`) → basename match.
3. If still no match, fall back to a 1-shot ChromaDB filename search.

---

### Step 6 — D5 fix: `find_env_dependencies` counter mismatch
**Tag**: `implement`
**Target**: `src/tools/CodeAnalysisTools.js#findEnvDependencies`

Root-cause hypothesis: the header counts come from a `DEPENDS_ON_ENV` /
`SETS_ENV` Cypher query restricted to specific labels, but the GGSR table is
built by a separate, broader query. The two are not in sync.

Fix: derive the header count from the same result set that populates the
GGSR table (single source of truth). Document the relationship type in the
header.

---

### Step 7 — D6 fix: `scan_repository_compliance` `files=[]` mode
**Tag**: `implement`
**Target**: `src/tools/EE2ComplianceTools.js#scanRepositoryCompliance`

Root-cause hypothesis: handler does
`const repoPath = args.repository_path; if (!fs.existsSync(repoPath)) throw …`
without first checking `args.files`.

Fix: branch on `args.files?.length > 0` first → run per-file analysis loop
(reusing logic from `extract_code_for_analysis`) → aggregate results. Only
fall through to filesystem mode when `files` is absent.

Add a remote-MCP test asserting the `files`-only path returns findings.

---

### Step 8 — D7 fix: `explain_with_context` empty body
**Tag**: `implement`
**Target**: `src/tools/SemanticSearchTools.js#explainWithContext`

Root-cause hypothesis: the function builds section objects but only emits
the heading; the section-rendering loop is gated on a `sources` array that
is never populated when the user passes only `query` + `topic`.

Fix:
1. Always populate `sources` with `['vector','graph','community']` by default.
2. For each non-empty source, render its top-3 results with similarity score.
3. Document the `topic` parameter clearly (currently under-described).

---

### Step 9 — D8 fix: `explain_workflow_component` topic mismatch
**Tag**: `implement`
**Target**: `src/tools/OperationalTools.js#explainWorkflowComponent`

This is the **same class** of bug Phase 51 fixed for J-jobs in
`multiSourceSearch`, but the response renderer is still falling back to the
nearest semantic hit when the direct Cypher query returns rows.

Fix: when `directHit` is non-empty, render its sourced scripts / inputs /
outputs (mirror `get_job_details`) and skip the generic semantic fallback.
Use `get_job_details(name, include_chromadb=false, include_config=false)`
internally as a building block to avoid duplication.

---

### Step 10 — D9 fix: `get_operational_guidance` parameter name
**Tag**: `implement`
**Target**: `src/tools/OperationalTools.js#getOperationalGuidance`, plus `tools.json` schema

Decide canonical name (recommend `topic` since that is what the schema
already advertises and what
[`.github/instructions/eib-mcp-tools.instructions.md`](../../.github/instructions/eib-mcp-tools.instructions.md)
documents). Accept either input but emit a deprecation note when `operation`
is used.

---

### Step 11 — D10 fix: `search_architecture` floor relaxation
**Tag**: `implement`
**Target**: `src/tools/GraphRAGTools.js#searchArchitecture`

Phase 51 raised the floor to `similarity ≥ 0.2 AND level ≥ 1` to suppress
L0 noise. That correctly killed garbage but is now too strict for broad
queries (e.g. "data assimilation subsystem").

Fix:
1. Two-pass query — first pass with the strict floor; if 0 results, second
   pass with `similarity ≥ 0.15` and `level ≥ 1`.
2. If still 0, return the top-3 by `similarity * (1 + 0.25 * level)` with a
   "low-confidence" annotation rather than refusing to answer.
3. Unit test asserts non-empty result for the report's probe query.

---

### Step 12 — Add regression tests
**Tag**: `implement`
**Target**: `src/__tests__/CodeAnalysisTools.test.js`, `…/SemanticSearchTools.test.js`, `…/EE2ComplianceTools.test.js`, `…/OperationalTools.test.js`, `…/GraphRAGTools.test.js`

Each defect gets at least one regression test that fails on `develop`
HEAD and passes after its fix. Use mocked `UnifiedDataAccess` so tests run
without live Neo4j/ChromaDB.

---

### Step 13 — Validate locally
**Tag**: `validate`

```bash
cd mcp_server_node
npx vitest run src/__tests__
./run-unit-tests.sh --coverage   # if available
npm start                        # smoke
```

Replay all 10 probes from the report; confirm output matches §3 acceptance
criteria.

---

### Step 14 — Rebuild gateway image and restart
**Tag**: `configure`

```bash
docker build -f SETUP/dockerfiles/Dockerfile.mcp-server -t eib-mcp-rag:latest ./mcp_server_node
pkill -f "docker-mcp gateway"
docker stop $(docker ps -q  --filter "label=docker-mcp-name=eib-mcp-rag") 2>/dev/null
docker rm   $(docker ps -aq --filter "label=docker-mcp-name=eib-mcp-rag") 2>/dev/null
MCP_GATEWAY_AUTH_TOKEN="eib-mcp-gateway-token-2025" docker mcp gateway run \
  --catalog eib-local.yaml --servers eib-mcp-rag \
  --transport streaming --port 18888 --long-lived &
```

---

### Step 15 — Re-run the quality report
**Tag**: `validate`
**Target**: [docs/MCP_TOOL_QUALITY_REPORT.md](../../docs/MCP_TOOL_QUALITY_REPORT.md)

Re-execute every probe in the report against the rebuilt gateway. Update the
quality column for the 10 fixed rows. Phase is complete only when all 10
move to ★★★★ or ★★★★★.

---

### Step 16 — Update CHANGELOG.md
**Tag**: `document`
**Target**: `CHANGELOG.md` (root)

```
## [8.3.0] - Phase 53: Gateway Tool Quality Remediation (2026-05-01)
- Fixed 10 tool-output defects identified in MCP_TOOL_QUALITY_REPORT.md
  (D1-D10). See sdd_framework/workflows/phase53_gateway_tool_quality_remediation.md
  for per-defect file references.
- Added 10 regression tests pinning each fix.
- Image rebuild required (eib-mcp-rag:latest).
```

---

## 5. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Path-resolution change in D4 introduces false matches | Restrict basename fallback to `:File` nodes only; require unique match or return ranked list |
| `search_architecture` two-pass query degrades latency | Cache the second pass per-query; current quality benchmark P50 = 42 ms leaves headroom |
| `get_operational_guidance` alias breaks downstream callers | Maintain `operation` as accepted alias for one release; deprecation warning only |
| `scan_repository_compliance` `files` mode duplicates `extract_code_for_analysis` | Refactor shared analysis into `EE2ComplianceTools._analyzeFile()` helper |

## 6. Rollback Plan

All changes are isolated to 5 source files plus tests. If post-rebuild
validation fails:

```bash
git revert <phase53-commit-sha>
docker tag eib-mcp-rag:8.2.2 eib-mcp-rag:latest    # previous good image
# restart gateway as in Step 14
```

## 7. Open Questions

1. Should D8 reuse `get_job_details` directly or share a helper? (Implementation choice — defer to PR.)
2. For D5 — is the GGSR table the source of truth, or is the header? (Recommend table; needs SME confirmation.)
3. Should `search_architecture` two-pass behavior be opt-in via a `strict` flag, or always-on? (Recommend always-on with annotation.)

## 8. References

* [docs/MCP_TOOL_QUALITY_REPORT.md](../../docs/MCP_TOOL_QUALITY_REPORT.md) — empirical evidence
* [sdd_framework/workflows/phase51_gateway_health_explain_search_fixes.md](phase51_gateway_health_explain_search_fixes.md) — predecessor; established the J-job graph integration pattern reused in D8
* [sdd_framework/workflows/phase29_tool_usability_improvements.md](phase29_tool_usability_improvements.md) — prior tool usability sweep
* [sdd_framework/workflows/phase43_expert_system_self_diagnosis.md](phase43_expert_system_self_diagnosis.md) — health-trend infrastructure (informs A12)
* [.github/copilot-instructions.md](../../.github/copilot-instructions.md) — image rebuild requirement after source change
