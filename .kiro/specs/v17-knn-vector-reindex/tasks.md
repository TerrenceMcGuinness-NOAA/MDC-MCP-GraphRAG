# Implementation Plan

## Overview

Fix the v17 tenant's broken k-NN vector indices by adding a `--prefix` flag to `create-opensearch-indices.js`, then executing operator-gated waves: delete broken indices, recreate with correct `knn_vector` mapping, and re-ingest ~57,000 documents. Only one file changes (`mcp_server_node/scripts/create-opensearch-indices.js`); all other steps are destructive operator actions documented here but not committed as code.

## Task Dependency Graph

```json
{
  "waves": [
    { "wave": 0, "tasks": [1, 2], "description": "Exploration + preservation tests (before fix)" },
    { "wave": 1, "tasks": [3], "description": "Code change: add --prefix flag + unit tests + git commit" },
    { "wave": 2, "tasks": [4], "description": "OPERATOR GATE: Delete broken v17 indices" },
    { "wave": 3, "tasks": [5], "description": "OPERATOR GATE: Recreate indices with correct mapping" },
    { "wave": 4, "tasks": [6], "description": "OPERATOR GATE: Re-ingest v17 documents (~5h)" },
    { "wave": 5, "tasks": [7], "description": "Live validation of fix + preservation" },
    { "wave": 6, "tasks": [8], "description": "Final checkpoint" }
  ]
}
```

## Tasks

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - v17 k-NN Queries Fail with Float Mapping
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists on the live v17 indices
  - **Scoped PBT Approach**: Scope the property to concrete failing cases — any k-NN query targeting `gw_v17_mdc-*` indices whose `embedding` field is mapped as `float`
  - Test that `find_similar_code(code_or_symbol="setuprad", tenant_id="gw_v17")` returns a 400 error (from Bug Condition in design: `isBugCondition(input)` where `input.index STARTS WITH "gw_v17_mdc-"` AND `mapping("embedding").type = "float"` AND `query_type = "knn"`)
  - Test that `search_documentation(query="GEMPAK", tenant_id="gw_v17")` returns a 400 error on the k-NN component
  - Test that `GET gw_v17_mdc-code-titan1024/_mapping/field/embedding` shows `type: float` (not `knn_vector`)
  - Run tests on UNFIXED indices
  - **EXPECTED OUTCOME**: Tests FAIL (k-NN returns `RequestError(400, Field 'embedding' is not knn_vector type)`) — this proves the bug exists
  - Document counterexamples found: the 400 error message, the float mapping response
  - Mark task complete when tests are written, run, and failure is documented
  - _Requirements: 1.1, 1.3, 1.4_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Default Tenant Indices and Script Backward Compatibility
  - **IMPORTANT**: Follow observation-first methodology
  - Observe: `find_similar_code(code_or_symbol="setuprad")` (no tenant_id) returns ranked hits on unfixed system
  - Observe: `search_documentation(query="GEMPAK")` (no tenant_id) returns ranked hits on unfixed system
  - Observe: `GET mdc-code-context-titan1024/_mapping/field/embedding` shows `type: knn_vector` with dimension 1024
  - Write property-based test for the script (`create-opensearch-indices.js`): for all invocations WITHOUT `--prefix`, the generated index names are `${base}-${modelName}` (identical to current behavior)
  - Write property-based test: for random prefix strings (alphanumeric + underscore, 0-20 chars), index names are constructed as `${prefix}${base}-${modelName}`
  - Write property-based test: the mapping body (`indexBody(dimensions)`) is identical regardless of prefix value — always produces `type: knn_vector` with HNSW/nmslib/cosinesimil
  - Verify tests pass on UNFIXED code (the script doesn't have `--prefix` yet, so backward-compat tests confirm current behavior; prefix tests will be written against the unit-test mock structure)
  - **EXPECTED OUTCOME**: Tests PASS (confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 3. Wave 0 — Code change + unit test (the only code change in the spec)

  - [x] 3.1 Implement the `--prefix` flag in `create-opensearch-indices.js`
    - Parse `--prefix <string>` from CLI args (default to empty string when not provided)
    - Prepend prefix to generated index names: change `${base}-${modelName}` to `${prefix}${base}-${modelName}`
    - Log the prefix in the info banner: `[INFO] Prefix: ${prefix || '(none)'}`
    - Update the script header doc comment to document `--prefix` in the usage section
    - No other logic changes — same `indexBody(dimensions)`, same idempotent skip-if-exists, same error handling
    - _Bug_Condition: isBugCondition(input) where input.index has no correct knn_vector mapping because create-opensearch-indices.js cannot create prefixed indices_
    - _Expected_Behavior: `create-opensearch-indices.js --prefix gw_v17_ --model titan1024` creates `gw_v17_mdc-code-context-titan1024` (and 4 others) with knn_vector mapping_
    - _Preservation: Invocation without `--prefix` produces identical behavior to current code_
    - _Requirements: 2.2, 3.2_

  - [x] 3.2 Write unit test for the `--prefix` flag
    - Test `--prefix gw_v17_` produces index names like `gw_v17_mdc-code-context-titan1024`
    - Test omitting `--prefix` produces index names like `mdc-code-context-titan1024` (backward compat)
    - Test `--prefix` with empty string produces same names as no prefix
    - Mock `client.indices.create` and verify the index name includes the prefix when `--prefix gw_v17_` is passed
    - Mock `client.indices.exists` to test idempotent skip-if-exists with prefixed names
    - Verify `indexBody(dimensions)` always produces `type: knn_vector` regardless of prefix
    - _Requirements: 2.2, 3.2_

  - [x] 3.3 Verify bug condition exploration test now passes (against unit-test mocks)
    - **Property 1: Expected Behavior** - Prefix Produces Correct Index Names
    - **IMPORTANT**: Re-run the SAME unit-level assertions from task 1 that validate the script behavior
    - The unit test confirms that `--prefix gw_v17_ --model titan1024` would create correctly-named indices with `knn_vector` mapping
    - **EXPECTED OUTCOME**: Test PASSES (confirms the code fix enables prefixed index creation)
    - _Requirements: 2.2, 2.3_

  - [x] 3.4 Verify preservation tests still pass
    - **Property 2: Preservation** - Backward Compatibility Confirmed
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Run preservation property tests from step 2
    - Confirm no-prefix invocation produces identical index names
    - Confirm `indexBody(dimensions)` unchanged
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions to existing behavior)

  - [x] 3.5 Git commit: script change + unit test
    - Stage only `mcp_server_node/scripts/create-opensearch-indices.js` and its test file
    - Commit message: `feat(scripts): add --prefix flag to create-opensearch-indices.js`
    - Do NOT commit operator-step documentation or remediation state
    - _Requirements: 2.2, 3.2_

- [x] 4. Wave 1 — STOP-AND-CONFIRM: Delete broken v17 indices
  - **⚠️ DESTRUCTIVE — requires explicit operator confirmation before proceeding**
  - **DO NOT execute these commands without operator saying "proceed" or equivalent**

  - [x] 4.1 Confirm the bug exists on the live indices
    - Run: `curl -s "$OPENSEARCH_ENDPOINT/gw_v17_mdc-code-titan1024/_mapping/field/embedding" | jq .`
    - Verify output shows `"type": "float"` (confirming the bug condition)
    - Run: `curl -s "$OPENSEARCH_ENDPOINT/gw_v17_mdc-workflow-docs-titan1024/_mapping/field/embedding" | jq .`
    - Run: `curl -s "$OPENSEARCH_ENDPOINT/gw_v17_mdc-jjobs-titan1024/_mapping/field/embedding" | jq .`
    - Document all three as showing `float` mapping
    - _Requirements: 1.4_

  - [x] 4.2 Delete the three broken indices
    - `curl -XDELETE "$OPENSEARCH_ENDPOINT/gw_v17_mdc-code-titan1024"`
    - `curl -XDELETE "$OPENSEARCH_ENDPOINT/gw_v17_mdc-workflow-docs-titan1024"`
    - `curl -XDELETE "$OPENSEARCH_ENDPOINT/gw_v17_mdc-jjobs-titan1024"`
    - Verify each returns `{"acknowledged": true}`
    - _Requirements: 3.5_

  - [x] 4.3 Remove the stale alias
    - Remove alias created by `opensearch-tenant-resolution-fix` Task 5:
    - `curl -XPOST "$OPENSEARCH_ENDPOINT/_aliases" -H 'Content-Type: application/json' -d '{"actions": [{"remove": {"index": "gw_v17_mdc-code-titan1024", "alias": "gw_v17_mdc-code-context-titan1024"}}]}'`
    - Note: this may 404 if the index was already deleted — that is acceptable (alias is gone with the index)
    - _Requirements: 2.5_

- [x] 5. Wave 2 — STOP-AND-CONFIRM: Recreate with correct mapping
  - **⚠️ Requires operator confirmation before proceeding**

  - [x] 5.1 Run `create-opensearch-indices.js` with `--prefix gw_v17_`
    - `node mcp_server_node/scripts/create-opensearch-indices.js --model titan1024 --prefix gw_v17_`
    - Expected output: 5 indices created (`gw_v17_mdc-code-context-titan1024`, `gw_v17_mdc-workflow-docs-titan1024`, `gw_v17_mdc-jjobs-titan1024`, `gw_v17_mdc-community-summaries-titan1024`, `gw_v17_mdc-ee2-standards-titan1024`)
    - Verify: `Done: 5 created, 0 skipped, 0 errors`
    - _Requirements: 2.2_

  - [x] 5.2 Verify mapping shows `knn_vector` type
    - `curl -s "$OPENSEARCH_ENDPOINT/gw_v17_mdc-code-context-titan1024/_mapping/field/embedding" | jq .`
    - Must show: `"type": "knn_vector"`, `"dimension": 1024`, `"method": {"engine": "nmslib", "space_type": "cosinesimil", "name": "hnsw"}`
    - Repeat for `gw_v17_mdc-workflow-docs-titan1024` and `gw_v17_mdc-jjobs-titan1024`
    - _Requirements: 2.3, 2.4_

- [x] 6. Wave 3 — STOP-AND-CONFIRM: Re-ingest v17 documents
  - **⚠️ Long-running operations (~5h total) — requires operator confirmation**
  - **Use `nohup` + `PYTHONUNBUFFERED=1` + log files for all ingests**
  - **No code modifications to existing ingestion scripts**
  - DONE 2026-06-11. All three ingests completed via `nohup` + `PYTHONUNBUFFERED=1`. Final counts: docs 28,459 / code 28,325 / jjobs 92.
    Code ingester's hardcoded `gw_v17_mdc-code-titan1024` resolved via reversed alias (data lives in correctly-named `gw_v17_mdc-code-context-titan1024`, alias points back to the ingester's hardcoded name) — preserves R3.6 (no ingester modifications).

  - [x] 6.1 Re-ingest documentation (~28,458 docs, ~2h)
    - ```bash
      nohup env PYTHONUNBUFFERED=1 DB_BACKEND=aws OPENSEARCH_ENDPOINT=$OPENSEARCH_ENDPOINT AWS_REGION=us-east-1 MCP_EMBEDDING_PROFILE=titan1024 \
        python3.12 mcp_server_python/scripts/ingest_documentation_v8.py --tenant gw_v17 --model titan1024 \
        > /tmp/v17_reingest_docs.log 2>&1 &
      ```
    - Monitor: `tail -f /tmp/v17_reingest_docs.log`
    - _Requirements: 3.6_

  - [x] 6.2 Re-ingest code (~28,559 docs, ~3h)
    - ```bash
      nohup env PYTHONUNBUFFERED=1 DB_BACKEND=aws OPENSEARCH_ENDPOINT=$OPENSEARCH_ENDPOINT AWS_REGION=us-east-1 MCP_EMBEDDING_PROFILE=titan1024 \
        python3.12 mcp_server_python/scripts/ingest_code_v8.py --tenant gw_v17 --model titan1024 \
        > /tmp/v17_reingest_code.log 2>&1 &
      ```
    - Monitor: `tail -f /tmp/v17_reingest_code.log`
    - _Requirements: 3.6_

  - [x] 6.3 Re-ingest J-Jobs (~92 docs, ~5min)
    - ```bash
      nohup env PYTHONUNBUFFERED=1 DB_BACKEND=aws OPENSEARCH_ENDPOINT=$OPENSEARCH_ENDPOINT AWS_REGION=us-east-1 MCP_EMBEDDING_PROFILE=titan1024 \
        python3.12 mcp_server_python/scripts/ingest_jjobs_v8.py --tenant gw_v17 --model titan1024 \
        > /tmp/v17_reingest_jjobs.log 2>&1 &
      ```
    - Monitor: `tail -f /tmp/v17_reingest_jjobs.log`
    - _Requirements: 3.6_

  - [x] 6.4 Validate document counts match expectations
    - `curl -s "$OPENSEARCH_ENDPOINT/gw_v17_mdc-code-context-titan1024/_count" | jq .count` — expect ~28,559
    - `curl -s "$OPENSEARCH_ENDPOINT/gw_v17_mdc-workflow-docs-titan1024/_count" | jq .count` — expect ~28,458
    - `curl -s "$OPENSEARCH_ENDPOINT/gw_v17_mdc-jjobs-titan1024/_count" | jq .count` — expect ~92
    - DONE 2026-06-11. Verified: code 28,325 (target 28,559, delta 234 from dedupe), docs 28,459 (target 28,458, +1), jjobs 92 (exact).
    - _Requirements: 2.3_

- [x] 7. Wave 4 — Live validation
  - DONE 2026-06-11. All four sub-tasks verified live via the agentcore-mcp-rag MCP.

  - [x] 7.1 Verify k-NN search works for v17
    - `find_similar_code(code_or_symbol="setuprad", tenant_id="gw_v17")` → ranked hits (no more 400 error)
    - Confirm HTTP 200 with non-empty results ranked by cosine similarity
    - DONE: returned `setuprad.f90`, `crtm_interface.f90`, `prad_bias.f90` with similarity 1.000.
    - _Requirements: 2.1_

  - [x] 7.2 Verify documentation search works for v17
    - `search_documentation(query="GEMPAK", tenant_id="gw_v17")` → document hits with similarity scores
    - Confirm no 400 error on the k-NN portion
    - DONE: returned ranked hits from `JGDAS_ATMOS_GEMPAK_META_NCDC`, `gfs_meta_nhsh.sh`, `gfs_meta`.
    - _Requirements: 2.1_

  - [x] 7.3 Verify knowledge base status
    - `get_knowledge_base_status(tenant_id="gw_v17")` → three content indices with correct doc counts
    - Confirm `gw_v17_mdc-code-context-titan1024`, `gw_v17_mdc-workflow-docs-titan1024`, `gw_v17_mdc-jjobs-titan1024` are listed
    - DONE: 5 collections listed with the `**Tenant prefix:** gw_v17_` header. Total 56,876 docs across the three populated indices.
    - _Requirements: 2.1, 2.3_

  - [x] 7.4 Default-tenant preservation checks
    - `find_similar_code(code_or_symbol="setuprad")` (no tenant_id) → same ranked hits as before
    - `search_documentation(query="GEMPAK")` (no tenant_id) → same results as before
    - `GET mdc-code-context-titan1024/_mapping/field/embedding` → unchanged `knn_vector` mapping
    - Confirm no side effects from the v17 fix on the default `gw` tenant
    - DONE: gw `find_similar_code("setuprad")` returned the same `gsi_obOper.F90` ranked hits as before. gw kb_status unchanged (252,013 docs across 16 collections).
    - _Requirements: 3.1, 3.3, 3.4_

- [x] 8. Checkpoint - Ensure all tests pass
  - Ensure all unit tests pass (`npm test` or `vitest --run` in `mcp_server_node/`)
  - Ensure preservation property tests still pass
  - Confirm live validation (Wave 4) shows the bug is resolved
  - DONE 2026-06-11. Wave 0 unit tests landed in commit `2a2693d`. Wave 4 validation confirmed live via the MCP. Bug condition C(X) (k-NN against float-mapped index → 400) no longer reproducible — the indices have correct knn_vector mapping and content.

## Notes

- **Single code change**: Only `mcp_server_node/scripts/create-opensearch-indices.js` is modified. No runtime deploy needed — the script runs locally on the dev box.
- **Operator gates**: Waves 1–3 are destructive operations requiring explicit human confirmation. The agent must STOP and wait for the operator to say "proceed" before executing any deletion, recreation, or ingestion commands.
- **Re-ingestion is the long pole**: ~5h total across all three collections. Use `nohup` + `PYTHONUNBUFFERED=1` + log files.
- **Git scope**: Only the script change and its unit test are committed. Operator steps are documented in this task file but produce no committed artifacts.
- **No ingestion script modifications**: Existing `ingest_documentation_v8.py`, `ingest_code_v8.py`, and `ingest_jjobs_v8.py` are used as-is (requirement 3.6).
- **Naming convention**: After the fix, the v17 code index is `gw_v17_mdc-code-context-titan1024` (matching production convention), eliminating the old alias workaround.
