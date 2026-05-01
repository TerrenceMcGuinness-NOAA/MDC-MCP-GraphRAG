---
mode: agent
description: "Phase 53: Fix the 10 tool-output bugs identified in MCP_TOOL_QUALITY_REPORT.md. Runs SDD session, implements fixes, adds regression tests, rebuilds image."
tools:
  - read_file
  - replace_string_in_file
  - multi_replace_string_in_file
  - create_file
  - run_in_terminal
  - grep_search
  - file_search
  - semantic_search
  - mcp_eib-mcp-gatew_start_sdd_session
  - mcp_eib-mcp-gatew_record_sdd_step
  - mcp_eib-mcp-gatew_get_sdd_session
  - mcp_eib-mcp-gatew_complete_sdd_session
  - mcp_eib-mcp-gatew_run_unit_tests
  - mcp_eib-mcp-gatew_mcp_health_check
---

# Phase 53 — Gateway Tool Quality Remediation

You are executing the SDD specification at:
`sdd_framework/workflows/phase53_gateway_tool_quality_remediation.md`

All source files are under `mcp_server_node/`.
The defect evidence is in `docs/MCP_TOOL_QUALITY_REPORT.md`.
Project coding rules: `.github/copilot-instructions.md` (no emoji in console.log, 2-space indent, ES modules).

---

## Ground Rules

- Run `npm run validate` in `mcp_server_node/` after every file you edit to catch syntax errors early.
- Run `npx vitest run src/__tests__` before committing anything — do NOT commit on test failure.
- Each defect fix is a separate logical unit; commit after each one passes its regression test.
- Do not change tool parameter schemas or Cypher queries unless required by the defect fix.
- Keep fixes minimal — do not refactor surrounding code.

---

## Step 0 — Start the SDD session

```
start_sdd_session({ phase: "phase53_gateway_tool_quality_remediation" })
```

Then confirm no active session is blocking you with `get_sdd_session()`.

---

## Step 1 — Reproduce all 10 defects (research)

Read and understand these files before writing a single line of code:

1. `docs/MCP_TOOL_QUALITY_REPORT.md` — the bug table (§ Bugs / gaps observed)
2. `sdd_framework/workflows/phase53_gateway_tool_quality_remediation.md` — root-cause hypotheses per defect
3. `mcp_server_node/src/tools/CodeAnalysisTools.js` — owns D1, D3, D4, D5
4. `mcp_server_node/src/tools/SemanticSearchTools.js` — owns D2, D7
5. `mcp_server_node/src/tools/EE2ComplianceTools.js` — owns D6
6. `mcp_server_node/src/tools/OperationalTools.js` — owns D8, D9
7. `mcp_server_node/src/tools/GraphRAGTools.js` — owns D10

For each file, search for the specific function named in the Phase 53 spec.
Confirm the root-cause hypothesis matches the actual code before proceeding to fix.

```
record_sdd_step({ step: 1, name: "Reproduce all 10 defects", tag: "research",
  notes: "Root-cause confirmed for D1-D10" })
```

---

## Step 2 — D1: `find_dependencies` renders `[object Object]`

**File**: `mcp_server_node/src/tools/CodeAnalysisTools.js`
**Function**: `findDependencies`

Find the line that renders import entries into the output string. It likely does
`${imp}` or `${item}` on an object. Fix to `${imp.file ?? imp.path ?? '?'} :: ${imp.name ?? JSON.stringify(imp)}`.
Add a coercion guard for legacy string entries.

Write a regression test in `src/__tests__/CodeAnalysisTools.test.js` that
mocks a query returning `[{ name: 'wxflow', file: 'ush/wxflow.sh' }]` and
asserts the output does NOT contain `[object Object]`.

```
record_sdd_step({ step: 2, name: "Fix find_dependencies [object Object]", tag: "implement" })
```

---

## Step 3 — D2: `find_related_files` labels every match `Unknown`

**File**: `mcp_server_node/src/tools/SemanticSearchTools.js`
**Function**: `findRelatedFiles`

Find where the result row label is constructed. The Cypher RETURN alias
likely does not match the field name the JS formatter reads. Fix the alias
mismatch so each row shows its file path instead of `'Unknown'`.

Write a regression test that mocks a graph result with `f.path = 'scripts/foo.py'`
and asserts the output contains `scripts/foo.py`.

```
record_sdd_step({ step: 3, name: "Fix find_related_files Unknown labels", tag: "implement" })
```

---

## Step 4 — D3: `get_code_context` header shows `null`

**File**: `mcp_server_node/src/tools/CodeAnalysisTools.js`
**Function**: `getCodeContext`

The header formatter reads `node.name` but File nodes only carry `path`.
Fix: fall back chain → `node.name ?? node.path?.split('/').pop() ?? args.symbol`.

Write a regression test asserting the header contains the user-supplied symbol
string when the node has no `name` field.

```
record_sdd_step({ step: 4, name: "Fix get_code_context null header", tag: "implement" })
```

---

## Step 5 — D4: `analyze_code_structure` returns "File not found"

**File**: `mcp_server_node/src/tools/CodeAnalysisTools.js`
**Function**: `analyzeCodeStructure`

The lookup is exact-match on `:File.path`. Other tools find the same node
by basename. Implement a three-tier resolver:
1. Exact match on `path`
2. `ENDS WITH` suffix match
3. Basename match (`path` ends with the last path segment)

If multiple nodes match tier 2 or 3, return ranked by path length (shortest = most canonical).

Write a regression test asserting `scripts/exglobal_forecast.sh` resolves to
the same node as `supported_repos/global-workflow/scripts/exglobal_forecast.sh`.

```
record_sdd_step({ step: 5, name: "Fix analyze_code_structure path resolver", tag: "implement" })
```

---

## Step 6 — D5: `find_env_dependencies` header count = 0 while table has rows

**File**: `mcp_server_node/src/tools/CodeAnalysisTools.js`
**Function**: `findEnvDependencies`

The header count and the GGSR table are built from separate queries. Derive
the header count from `results.length` after the table is built — single
source of truth.

Write a regression test asserting header count equals the number of GGSR
table rows in the same response.

```
record_sdd_step({ step: 6, name: "Fix find_env_dependencies counter mismatch", tag: "implement" })
```

---

## Step 7 — D6: `scan_repository_compliance` rejects `files=[]` input

**File**: `mcp_server_node/src/tools/EE2ComplianceTools.js`
**Function**: `scanRepositoryCompliance`

The function currently reads `args.repository_path` first and throws if the
directory doesn't exist, before ever checking `args.files`.

Fix: add a branch at the top — if `args.files?.length > 0`, run the
per-file analysis loop and skip the filesystem path entirely. Reuse the
`_analyzeFile` or `extract_code_for_analysis` helper so logic is not
duplicated.

Write a regression test passing `files=[{name:'test.sh', content:'…'}]` and
asserting findings are returned without a filesystem path.

```
record_sdd_step({ step: 7, name: "Fix scan_repository_compliance files mode", tag: "implement" })
```

---

## Step 8 — D7: `explain_with_context` returns only a heading

**File**: `mcp_server_node/src/tools/SemanticSearchTools.js`
**Function**: `explainWithContext`

Find the `sources` array population logic. It is likely gated on a condition
that is never true when only `query` + `topic` are supplied. Fix: default
`sources` to `['vector', 'graph', 'community']` when not explicitly set.
Ensure the render loop emits top-3 results per source with similarity scores.

Write a regression test asserting the output contains at least one result
section body (not just the heading).

```
record_sdd_step({ step: 8, name: "Fix explain_with_context empty body", tag: "implement" })
```

---

## Step 9 — D8: `explain_workflow_component` returns wrong topic

**File**: `mcp_server_node/src/tools/OperationalTools.js`
**Function**: `explainWorkflowComponent`

When `directHit` is non-empty (J-job matched via the Phase 51 fix), render
the hit's sourced scripts, inputs, and outputs — do not fall through to the
generic semantic fallback. Use the same field extraction as `get_job_details`.

Write a regression test mocking `directHit = [{ name:'JGLOBAL_FORECAST', … }]`
and asserting the output contains "Sourced Scripts" or "Inputs".

```
record_sdd_step({ step: 9, name: "Fix explain_workflow_component topic mismatch", tag: "implement" })
```

---

## Step 10 — D9: `get_operational_guidance` requires `operation`, schema says `topic`

**File**: `mcp_server_node/src/tools/OperationalTools.js`
**Function**: `getOperationalGuidance`

Normalize the incoming parameter: `const topic = args.topic ?? args.operation`.
Accept both. Log a deprecation warning to stderr (not stdout — MCP stdio) when
`args.operation` is used and `args.topic` is absent.

Also update the tool's JSON schema entry so `topic` is marked as the primary
parameter.

```
record_sdd_step({ step: 10, name: "Fix get_operational_guidance parameter alias", tag: "implement" })
```

---

## Step 11 — D10: `search_architecture` floor too aggressive

**File**: `mcp_server_node/src/tools/GraphRAGTools.js`
**Function**: `searchArchitecture`

Implement two-pass query:
- Pass 1: `similarity >= 0.2 AND level >= 1` (current strict floor)
- Pass 2 (only if Pass 1 returns 0): `similarity >= 0.15 AND level >= 1`
- If still 0: return top-3 by `similarity * (1 + 0.25 * level)` with a
  `[low-confidence]` annotation — never refuse silently.

Write a regression test asserting a broad architectural query returns ≥ 1
result even when no community scores above 0.2.

```
record_sdd_step({ step: 11, name: "Fix search_architecture two-pass floor", tag: "implement" })
```

---

## Step 12 — Run the full test suite

```bash
cd mcp_server_node
npx vitest run src/__tests__
```

All pre-existing tests must still pass. All 10 new regression tests must pass.
Fix any failures before continuing.

```
record_sdd_step({ step: 12, name: "Full test suite green", tag: "validate",
  notes: "X pre-existing + 10 new tests passing" })
```

---

## Step 13 — Validate with live server (native stdio mode)

```bash
cd mcp_server_node
npm start &
# Wait for "MCP server running" then replay the 10 probes from the report
```

Confirm each of the 10 fixed tools now produces ★★★★ or ★★★★★ output.
Stop the server when done.

```
record_sdd_step({ step: 13, name: "Live validation 10 probes pass", tag: "validate" })
```

---

## Step 14 — Rebuild the Docker gateway image

```bash
docker build -f SETUP/dockerfiles/Dockerfile.mcp-server -t eib-mcp-rag:latest ./mcp_server_node
```

Then restart the gateway:

```bash
pkill -f "docker-mcp gateway" 2>/dev/null
docker stop $(docker ps -q  --filter "label=docker-mcp-name=eib-mcp-rag") 2>/dev/null
docker rm   $(docker ps -aq --filter "label=docker-mcp-name=eib-mcp-rag") 2>/dev/null
MCP_GATEWAY_AUTH_TOKEN="eib-mcp-gateway-token-2025" docker mcp gateway run \
  --catalog eib-local.yaml --servers eib-mcp-rag \
  --transport streaming --port 18888 --long-lived &
```

```
record_sdd_step({ step: 14, name: "Docker image rebuilt and gateway restarted", tag: "configure" })
```

---

## Step 15 — Re-run quality report probes against gateway

Replay all 10 failing probes via the gateway (not native mode). Update the
quality column in `docs/MCP_TOOL_QUALITY_REPORT.md` for all 10 rows.
Add a "Re-validation date: 2026-05-XX" footer to the report.

```
record_sdd_step({ step: 15, name: "Quality report updated — all 10 gaps resolved", tag: "validate" })
```

---

## Step 16 — Update CHANGELOG.md

Add an entry at the top of CHANGELOG.md:

```
## [8.3.0] - 2026-05-XX — Phase 53: Gateway Tool Quality Remediation

### Fixed
- D1: find_dependencies no longer renders [object Object] for import names
- D2: find_related_files no longer labels all results Unknown
- D3: get_code_context header no longer shows null for the symbol name
- D4: analyze_code_structure resolves scripts/ paths (suffix/basename fallback)
- D5: find_env_dependencies header count now derived from GGSR table row count
- D6: scan_repository_compliance accepts files=[] without a repository_path
- D7: explain_with_context always populates body sections (defaults sources)
- D8: explain_workflow_component renders J-job details instead of semantic fallback
- D9: get_operational_guidance accepts topic= (canonical) and operation= (alias)
- D10: search_architecture two-pass floor; never returns empty on broad queries

### Added
- 10 regression tests (one per defect) in src/__tests__/

### Notes
- Docker image rebuild required (eib-mcp-rag:latest)
- See sdd_framework/workflows/phase53_gateway_tool_quality_remediation.md
```

```
record_sdd_step({ step: 16, name: "CHANGELOG.md updated", tag: "document" })
```

---

## Step 17 — Complete the SDD session

```
complete_sdd_session({ summary: "Phase 53 complete. 10 tool-output defects fixed, 10 regression tests added, Docker image rebuilt, quality report updated." })
```

---

## Completion Checklist

- [ ] All 10 regression tests pass (`npx vitest run src/__tests__`)
- [ ] All pre-existing tests still pass
- [ ] Live server: 10 probes return ★★★★ or ★★★★★
- [ ] Gateway rebuilt with `eib-mcp-rag:latest`
- [ ] `docs/MCP_TOOL_QUALITY_REPORT.md` updated
- [ ] `CHANGELOG.md` updated with [8.3.0] entry
- [ ] SDD session completed
