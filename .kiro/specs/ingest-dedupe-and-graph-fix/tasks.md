# Implementation Plan

## Overview

Two separable code fixes plus a gated operational remediation for the `gw_v17`
collection-blind dedupe + empty-graph bug:

- **Fix A — re-key the registry by `(collection, sha)`** (`_ingest_dedupe.py`) so a SHA
  registered by one collection no longer masks the same SHA in another collection of the
  same tenant (Defect 1, C(X)).
- **Fix B — unconditional graph write** in `ingest_code_v8.py` / `ingest_jjobs_v8.py` so
  the `MERGE` runs for every file regardless of the dedupe decision (Defect 2).
- Supporting: a shared collection-token constant, a documentation pass kept graph-free,
  and a `--clear-registry-entries` rollback flag.
- **Operational remediation** (cleanup → re-ingest runbook) is operator-run with
  STOP-AND-CONFIRM gates before the destructive rollback and before re-ingest.

TDD ordering: bug-condition exploration test (1) → shared constant (2) → fixes (3, 4, 5,
6) → fix/preservation/graph property tests (7, 8, 9) → unit tests (10) → exploration test
flips fail→pass (11) → operational remediation (12, gated) → checkpoint (13). Pure-test
tasks are marked `[ ]*`. All paths are relative to the workspace root
`/mdc-mcp-rag/eib-mcp-rag-server/`.

## Tasks

- [ ]* 1. Write bug condition exploration test (BEFORE any fix)
  - **Property 1: Bug Condition** - Collection-Blind Dedupe Masks Code/JJobs Content
  - **CRITICAL**: This test MUST FAIL on the current unfixed code — the failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails** — a failure here is the success criterion for this task
  - **NOTE**: This test encodes the expected (fixed) behavior; it will validate the fix when it passes after implementation (re-run in task 11)
  - **GOAL**: Surface counterexamples that demonstrate `C(X)` — a SHA registered by a *different* collection of the *same* tenant is wrongly treated as a duplicate, suppressing both embedding and the graph node
  - **Scoped PBT Approach**: this is a deterministic structural bug — scope the property to concrete failing cases (one SHA per collection pair) rather than broad generation
  - Create a new test file `mcp_server_python/tests/properties/test_ingest_dedupe_graph_fix.py` to keep the bugfix tests grouped
  - Use an in-memory stub registry (and a stub graph) as described in design Testing Strategy → Exploratory Bug Condition Checking
  - **Test case 1 — docs-then-code masking**: register a file's SHA under `collection="documentation"`, then run the code-pass dedupe+graph logic over the SAME SHA under `collection="code"`; assert `is_reference == False` AND `graph_node_created == True`. On UNFIXED code this FAILS (`is_reference` comes back `True`, no graph node) — from Bug Condition `isBugCondition(X)` in design / bugfix.md
  - **Test case 2 — docs-then-jjobs masking**: same as above for the jjobs pass (`collection="jjobs"`); expect `is_reference == False` + graph node; unfixed yields reference + no node
  - **Test case 3 — 100% dedupe collapse**: a small tree registered by docs then re-walked by code → assert `nodes_created_by_label` non-empty; unfixed yields `{}`
  - Run the test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (this is correct — it proves the bug exists). If it unexpectedly PASSES, the root-cause hypothesis is wrong and must be re-derived (design Exploratory section)
  - Document the counterexamples found (e.g. "code-pass file registered by docs returns `is_duplicate=True`, `embedding: None`, zero graph nodes") to confirm root cause
  - Mark this task complete when the test is written, run, and the failure is documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [ ] 2. Define a stable shared collection-token constant
  - Add a single canonical token per collection — `"documentation"`, `"code"`, `"jjobs"` — as a module-level constant (e.g. `COLLECTION_DOCUMENTATION`, `COLLECTION_CODE`, `COLLECTION_JJOBS`, or a small frozen mapping) in `mcp_server_python/scripts/_ingest_common.py` (fallback `_ingest_dedupe.py` if `_ingest_common.py` is not the natural import root)
  - Each entry script (`ingest_documentation_v8.py`, `ingest_code_v8.py`, `ingest_jjobs_v8.py`) imports its token from this constant rather than using a per-script string literal, so a typo cannot silently regress dedupe
  - Rationale: the token MUST be stable across runs or dedupe silently regresses (design Change 1 step 3)
  - _Requirements: 2.5, 2.6_

- [ ] 3. Re-key `SHAIndex` by `(collection, sha)`
  - **File**: `mcp_server_python/scripts/_ingest_dedupe.py`
  - Change `lookup` to take a keyword-only `collection` parameter and query the registry with a bool filter on BOTH `collection` AND `sha` (replacing the `{"term": {"sha": sha}}` query) — see design Change 1 step 1 pseudocode
  - Change `register` to take a keyword-only `collection` parameter, add `collection` to the indexed doc body, and write the composite id `id=f"{collection}:{sha}"` (e.g. `"code:9f8e…"`) — see design Change 1 step 2 pseudocode
  - The composite id makes `register` an upsert per `(collection, sha)` so same-tenant, same-collection re-runs are idempotent; lookup matches `(collection, sha)` regardless of tenant so the cross-tenant optimization is preserved
  - Use the shared constant from task 2 for the collection token
  - _Bug_Condition: isBugCondition(X) — `existing.collection ≠ c AND existing.tenant = T` from design/bugfix.md_
  - _Expected_Behavior: a SHA seen only under a different collection is NOT a duplicate (Property 1, expectedBehavior from design)_
  - _Preservation: cross-tenant-within-collection dedupe and reference-document shape unchanged (Preservation Requirements 3.1, 3.4)_
  - _Requirements: 2.5, 2.6_

- [ ] 4. Make the graph write unconditional in the code and jjobs passes
  - **Files**: `mcp_server_python/scripts/ingest_code_v8.py`, `mcp_server_python/scripts/ingest_jjobs_v8.py`
  - Pass `collection="code"` / `collection="jjobs"` (via the task-2 constant) into both `lookup` and `register`
  - Move the `MERGE` cypher and `report.increment(f"nodes:{label}")` OUT of the dedupe `else` (non-duplicate) branch so they run unconditionally after the `if result.is_duplicate / else` block — see design Change 2 step 2 pseudocode
  - The graph node carries `name`, `path`, `tenant_id`, `sha` (all available regardless of the dedupe branch); `MERGE` keeps it idempotent across re-runs
  - _Bug_Condition: isBugCondition(X) with c ∈ {code, jjobs} — graph MERGE currently gated on the dedupe else branch (bugfix.md 1.3)_
  - _Expected_Behavior: for any code/jjobs file, MERGE the graph node and increment nodes:{label} regardless of embed/reference decision (design Property 3, expectedBehavior)_
  - _Preservation: documentation creates no graph nodes; reference-document shape unchanged (3.2, 3.4)_
  - _Requirements: 2.3, 2.4, 2.7, 2.8_

- [ ] 5. Make the documentation pass collection-keyed but still graph-free
  - **File**: `mcp_server_python/scripts/ingest_documentation_v8.py`
  - Pass `collection="documentation"` (via the task-2 constant) into both `lookup` and `register`
  - Add NO graph write — the documentation pass MUST continue to create zero graph nodes (design Change 3)
  - _Bug_Condition: isBugCondition(X) — docs pass registers SHAs first and masks later collections (bugfix.md 1.1, 1.2)_
  - _Expected_Behavior: documentation registers under its own collection token so it no longer masks code/jjobs (Property 1)_
  - _Preservation: documentation creates no graph nodes (Preservation Requirement 3.2)_
  - _Requirements: 2.5, 3.2_

- [ ] 6. Add `--clear-registry-entries` rollback flag for the shared registry
  - **File**: `mcp_server_python/scripts/delete_tenant_indices.py`
  - Add a `--clear-registry-entries` flag; when set (and not a dry run), after deleting the tenant's prefixed indices and `label_prefix` graph nodes, issue a delete-by-query against `mdc-content-sha-registry` for docs where `tenant_id == <tenant>` — see design Change 4 step 1 pseudocode
  - The registry **index itself is never deleted** — only the tenant's own entries
  - Surface the planned registry deletion in the `--dry-run` plan output so an operator can review it before mutating
  - The existing `gw` empty-prefix guard (R7.3) must still refuse `gw`, so a `--tenant gw_v17 --clear-registry-entries` run never touches `tenant_id == "gw"` rows
  - _Bug_Condition: stale `gw_v17` rows keyed by bare sha block clean remediation (design Hypothesized Root Cause 3)_
  - _Expected_Behavior: rollback can clear a tenant's own registry entries without deleting the shared index_
  - _Preservation: `mdc-content-sha-registry` stays a system-level, unprefixed index; `gw` baseline entries untouched (Preservation Requirement 3.6)_
  - _Requirements: 3.6_

- [ ]* 7. Write the Fix Checking property test
  - **Property 1: Expected Behavior** - Collection-Scoped Dedupe + Unconditional Graph Write
  - **IMPORTANT**: This is the Fix Checking property from design Testing Strategy → Fix Checking
  - For all inputs where `isBugCondition(X)` holds: assert `F'(X).is_reference == False` AND `embedded_real_content == True` AND (`X.collection IN {code, jjobs}` IMPLIES `graph_node_created == True`)
  - Add to `mcp_server_python/tests/properties/test_ingest_dedupe_graph_fix.py`
  - Run on FIXED code → **EXPECTED OUTCOME**: Test PASSES
  - _Requirements: 2.1, 2.2, 2.3, 2.5, 2.6_

- [ ]* 8. Write the Preservation Checking property test
  - **Property 2: Preservation** - Non-Buggy Inputs Behave Identically
  - **IMPORTANT**: Follow observation-first methodology — extend the P5 dedupe property test in `mcp_server_python/tests/properties/test_v17_pilot.py` with a **collection dimension** (stub registry key becomes `(collection, sha)`; `lookup`/`register` take a `collection` argument)
  - For all inputs where `isBugCondition(X)` is false, assert `F(X) == F'(X)`, covering the design Preservation Checking test cases:
    - **Cross-tenant-within-collection dedupe preserved**: register `(code, sha)` under tenant A, ingest same `(code, sha)` under tenant B → still a reference doc with the existing shape (3.1, 3.4)
    - **Never-seen `(collection, sha)` embedded**: absent from registry → embedded as real content (2.1/2.2 baseline)
    - **Documentation graph-free preserved**: documentation pass over any file → no graph node (3.2)
    - **Different collections, same SHA, same tenant → both embedded**: confirms one embedding per collection (2.6)
    - **Reference shape unchanged**: `is_reference: True`, `canonical_index`, `canonical_id`, `canonical_tenant`, `embedding: None`, `content: "<reference: see canonical doc>"` (3.4)
  - Property-based testing generates many `(tenant, collection, sha)` combinations for strong preservation guarantees
  - Run on FIXED code → **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [ ]* 9. Write the unconditional-graph-write property test
  - **Property 3: Unconditional Graph Modeling** - Every Code/JJobs File Yields One Graph Node
  - For a generated mix of duplicate and non-duplicate code/jjobs files, assert every file yields exactly one graph node and `nodes_created_by_label` is non-empty whenever ≥1 file is processed (design Property 3 / Property-Based Tests)
  - Add to `mcp_server_python/tests/properties/test_ingest_dedupe_graph_fix.py`
  - Run on FIXED code → **EXPECTED OUTCOME**: Test PASSES
  - _Requirements: 2.3, 2.4, 2.7, 2.8_

- [ ]* 10. Write unit tests for the re-keyed registry, composite id, and rollback flag
  - **Files**: `mcp_server_python/tests/unit/test_ingest_dedupe.py` (registry) and `mcp_server_python/tests/unit/test_delete_tenant_indices.py` (rollback)
  - `SHAIndex` `(collection, sha)` round-trip: a SHA registered under one collection is NOT found under another, and IS found under the same collection
  - Composite id format is exactly `f"{collection}:{sha}"`; the registry doc body carries the `collection` field
  - `delete_tenant_indices --clear-registry-entries` issues a delete-by-query scoped to `tenant_id`; without the flag the registry is untouched; the registry index is never deleted; the `gw` empty-prefix guard still refuses
  - Run on FIXED code → **EXPECTED OUTCOME**: Tests PASS
  - _Requirements: 2.5, 2.6, 3.6_

- [ ] 11. Verify the bug condition exploration test now passes on fixed code
  - **Property 1: Expected Behavior** - Collection-Blind Dedupe Bug Resolved
  - **IMPORTANT**: Re-run the SAME test from task 1 (`test_ingest_dedupe_graph_fix.py`) — do NOT write a new test
  - The task-1 test encodes the expected behavior; when it passes it confirms the bug is fixed
  - Run the bug condition exploration test from task 1 on the FIXED code
  - **EXPECTED OUTCOME**: Test PASSES (flips fail→pass — confirms `is_reference == False` and graph node created for the docs-then-code/jjobs cases)
  - Also run tasks 7, 8, 9, 10 and confirm the full bugfix + preservation suite passes with no regressions
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

- [ ] 12. Operational remediation — cleanup → re-ingest runbook (OPERATOR-RUN, GATED)

  - [ ] 12.1 Dry-run the rollback to review the plan (read-only)
    - `python3.12 mcp_server_python/scripts/delete_tenant_indices.py --tenant gw_v17 --clear-registry-entries --dry-run`
    - Confirm the plan lists the 3 `gw_v17_*` indices, the `GW_V17_*` Neptune labels, and the scoped `mdc-content-sha-registry` delete-by-query (`tenant_id == gw_v17`)
    - _Requirements: 3.6_

  - [ ] 12.2 STOP-AND-CONFIRM gate — before destructive rollback delete
    - **Do not proceed** until the operator reviews the dry-run plan and explicitly confirms. This deletes tenant data and is hard to reverse.
    - _Requirements: 3.6_

  - [ ] 12.3 Execute rollback (destructive AWS writes)
    - Deletes the 3 `gw_v17_*` OpenSearch indices, the `GW_V17_*` Neptune labels, and the stale `gw_v17` rows in `mdc-content-sha-registry`; never deletes the shared index
    - `python3.12 mcp_server_python/scripts/delete_tenant_indices.py --tenant gw_v17 --clear-registry-entries`
    - _Requirements: 3.6_

  - [ ] 12.4 STOP-AND-CONFIRM gate — before re-ingest
    - **Do not proceed** until the operator confirms the rollback completed cleanly AND the fixed code (tasks 2–6) is deployed to the ingestion environment.
    - _Requirements: 2.4_

  - [ ] 12.5 Re-ingest in collection order (documentation → code → jjobs)
    - `python3.12 mcp_server_python/scripts/ingest_documentation_v8.py --tenant gw_v17`
    - `python3.12 mcp_server_python/scripts/ingest_code_v8.py --tenant gw_v17`
    - `python3.12 mcp_server_python/scripts/ingest_jjobs_v8.py --tenant gw_v17`
    - _Requirements: 2.4_

  - [ ] 12.6 Verify the remediation
    - code/jjobs reports show non-empty `nodes_created_by_label` (2.4)
    - cross-tenant dedupe ≈ 0% (gw is not in this pipeline); intra-collection dedupe small and legitimate
    - `find_dependencies` / `find_callers_callees` / `trace_execution_path` return populated results for `gw_v17` symbols (2.7)
    - branch-isolation smoke probe Assertion 1 (WDQMS J-Job visible under `gw_v17`) passes (2.8)
    - `gw` baseline queries unchanged (3.3)
    - _Requirements: 2.4, 2.7, 2.8, 3.3_

- [ ] 13. Checkpoint — Ensure all tests pass
  - Confirm task 1 (now passing) plus tasks 7, 8, 9, 10 all pass on the fixed code with no regressions across the existing suite.
  - Ask the user if questions arise.

## Notes

- **Two separable fixes.** Fix A (registry re-key, task 3) addresses Defect 1 / C(X); Fix B (unconditional graph write, task 4) addresses Defect 2. They can be reviewed independently but both are required to fully resolve the bug.
- **Bug condition methodology.** Task 1 is the exploration test that MUST fail on unfixed code (confirms the bug). Tasks 7 (Fix Checking) and 8 (Preservation Checking) encode the design's correctness properties. Task 11 re-runs the task-1 test to confirm fail→pass.
- **Operational remediation is operator-run, not autonomous.** Task 12 performs AWS writes (index/label deletes, registry delete-by-query, full re-ingestion) and is gated by two STOP-AND-CONFIRM checkpoints (12.2 before the destructive delete, 12.4 before re-ingest).
- **Preservation focus.** The legitimate cross-tenant-within-collection dedupe optimization, the documentation no-graph behavior, the reference-document shape, and the `gw` baseline must all remain unchanged (requirements 3.1–3.6).
- The corrected behavior should later be reflected back into `.kiro/specs/omd-tenants-2-v17-pilot/` design §2.4 / §2.5; this bugfix spec is the immediate vehicle.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2"] },
    { "id": 2, "tasks": ["3"] },
    { "id": 3, "tasks": ["4", "5", "6"] },
    { "id": 4, "tasks": ["7", "8", "9", "10"] },
    { "id": 5, "tasks": ["11"] },
    { "id": 6, "tasks": ["12.1"] },
    { "id": 7, "tasks": ["12.2"] },
    { "id": 8, "tasks": ["12.3"] },
    { "id": 9, "tasks": ["12.4"] },
    { "id": 10, "tasks": ["12.5"] },
    { "id": 11, "tasks": ["12.6"] },
    { "id": 12, "tasks": ["13"] }
  ]
}
```
