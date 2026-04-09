# Implementation Plan

- [ ] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Failed Batches Silently Swallowed, Watermark Written as "Done"
  - **CRITICAL**: This test MUST FAIL on unfixed code — failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior — it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the `.catch()` swallows batch errors and the watermark is unconditionally written as "done"
  - **Scoped PBT Approach**: Use fast-check to generate `{ failingBatchCount: nat, totalBatches: nat }` pairs where `failingBatchCount > 0`. For each, mock `runWithRetry` to throw on the specified batches and verify the watermark behavior.
  - Create test file at `mcp_server_node/test/tests/unit/loadGraph-bug-condition.test.js`
  - Extract the `loadGraph` relationship loading loop logic into a testable helper or mock the surrounding dependencies (S3 download, WriterPool, makeNeptuneDriver) to isolate the error-handling behavior
  - Mock `runWithRetry` to throw `new Error('Operation terminated (internal error)')` for relationship MERGE batches after retries exhausted
  - Mock `saveWatermarks` to capture the watermark state written
  - Mock S3 `GetObjectCommand` to return a small graph dump (e.g., 10 nodes, 50 rels)
  - Property assertion: for all inputs where `failingBatchCount > 0`, assert that `wm['load:graph']` is NOT `'done'` AND that the failure count is reported
  - On UNFIXED code: the property will FAIL because `.catch()` swallows errors and `wm['load:graph'] = 'done'` is written unconditionally — this confirms the bug exists
  - Document counterexamples found (e.g., "1 of 1 rel batches failed, but watermark says 'done' with relsLoaded: 50")
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3_

- [ ] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Successful Runs Write "Done" Watermark with Correct Counts
  - **IMPORTANT**: Follow observation-first methodology
  - Create test file at `mcp_server_node/test/tests/unit/loadGraph-preservation.test.js`
  - Observe on UNFIXED code: when all batches succeed (zero failures), `wm['load:graph']` is set to `'done'` and `wm['load:graph:rels']` equals `dump.relationships.length`
  - Observe on UNFIXED code: node loading with parallel WriterPool and `_mergeId`-based MERGE produces correct progress watermarks
  - Observe on UNFIXED code: relationships with unresolvable endpoints (fromName/toName not in nodeIdMap) are filtered and `skippedRels` count is logged
  - Observe on UNFIXED code: `--dry-run` skips all Neptune writes and watermark updates
  - Write property-based tests with fast-check:
    - Generate random graph dumps: `fc.record({ nodeCount: fc.nat({max: 200}), relCount: fc.nat({max: 500}), unresolvableRelCount: fc.nat({max: 50}) })`
    - For all generated dumps where all batches succeed: assert `wm['load:graph'] === 'done'` AND `wm['load:graph:nodes'] === nodeCount` AND `wm['load:graph:rels'] === totalRelCount`
    - For all generated dumps: assert unresolvable rels are filtered (validRels.length === relCount - unresolvableRelCount)
    - For dry-run mode: assert no watermark writes occur for Neptune operations
  - Verify all preservation tests PASS on UNFIXED code
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [ ] 3. Fix loadGraph error handling in migrate-to-aws.js

  - [ ] 3.1 Implement orphan node purge at start of loadGraph
    - Add a batched DELETE step before relationship loading: `MATCH (n) WHERE n._mergeId IS NULL WITH n LIMIT 10000 DETACH DELETE n RETURN count(n) AS deleted`
    - Repeat in a loop until `deleted === 0`
    - Use `runWithRetry` for each batch to handle transient Neptune errors
    - Log the total count of purged orphan nodes
    - _Bug_Condition: isBugCondition(input) where orphan nodes without _mergeId inflate scan time, contributing to batch timeouts_
    - _Expected_Behavior: Orphan nodes are removed before rel loading begins, reducing node count from ~107K to ~62K_
    - _Preservation: Node loading, dry-run, and phase filtering behavior unchanged_
    - _Requirements: 1.6, 2.6_

  - [ ] 3.2 Replace .catch() with error accumulation in relationship loading loop
    - Remove `.catch(err => console.error(...))` from the `runWithRetry` call in the rel loading worker tasks
    - Wrap each batch in try/catch that increments a `failedRelBatches` counter
    - Log each failure with batch index, rel type, and truncated error message (existing format preserved)
    - _Bug_Condition: isBugCondition(input) where batchResult = FAILURE_AFTER_RETRIES AND errorHandling = CATCH_AND_SWALLOW_
    - _Expected_Behavior: Failed batches increment failedRelBatches counter; errors are logged but not swallowed_
    - _Preservation: Successful batches continue to execute identically; logging format unchanged_
    - _Requirements: 1.1, 2.1_

  - [ ] 3.3 Replace .catch() with error accumulation in node loading loop
    - Apply the same pattern as 3.2 to the node loading worker tasks
    - Add a `failedNodeBatches` counter
    - Log each failure with batch index, label, and truncated error message
    - _Bug_Condition: isBugCondition(input) where node batch fails and error is swallowed by .catch()_
    - _Expected_Behavior: Failed node batches increment failedNodeBatches counter_
    - _Preservation: Successful node batches continue to execute identically_
    - _Requirements: 1.4, 2.4_

  - [ ] 3.4 Add conditional watermark write based on failure counts
    - After both node and rel loading loops complete, check `failedNodeBatches` and `failedRelBatches`
    - Only write `wm['load:graph'] = 'done'` if BOTH counters are zero
    - Log a summary: `[RESULT] Nodes: X batches succeeded, Y failed. Rels: A batches succeeded, B failed.`
    - If failures > 0, log: `[WARN] load:graph NOT marked done — N batch failures. Re-run to retry.`
    - Write `wm['load:graph:relsLoaded']` with the actual count of successfully processed rels (not the pre-filter total)
    - _Bug_Condition: isBugCondition(input) where watermarkWrittenAs('done') = true AND actualRelsCreated = 0_
    - _Expected_Behavior: wm['load:graph'] !== 'done' when failedRelBatches > 0 OR failedNodeBatches > 0_
    - _Preservation: When all batches succeed (failedRelBatches === 0 AND failedNodeBatches === 0), watermark is written as 'done' — identical to original happy path_
    - _Requirements: 1.2, 1.3, 2.2, 2.3, 2.5, 3.1_

  - [ ] 3.5 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Failed Batches Prevent "Done" Watermark
    - **IMPORTANT**: Re-run the SAME test from task 1 — do NOT write a new test
    - The test from task 1 encodes the expected behavior: for all inputs where batches fail, `wm['load:graph']` is NOT `'done'`
    - When this test passes, it confirms the expected behavior is satisfied
    - Run `npx vitest run test/tests/unit/loadGraph-bug-condition.test.js`
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.1, 2.2, 2.3, 2.5_

  - [ ] 3.6 Verify preservation tests still pass
    - **Property 2: Preservation** - Successful Runs Write "Done" Watermark with Correct Counts
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Run `npx vitest run test/tests/unit/loadGraph-preservation.test.js`
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm all preservation properties still hold after the fix: happy-path watermark, node loading, unresolvable rel filtering, dry-run behavior
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [ ] 4. Checkpoint — Ensure all tests pass
  - Run full test suite: `npx vitest run test/tests/unit/loadGraph-bug-condition.test.js test/tests/unit/loadGraph-preservation.test.js`
  - Verify Property 1 (Bug Condition) test PASSES on fixed code
  - Verify Property 2 (Preservation) tests PASS on fixed code
  - Ensure no regressions in existing test suite
  - Ask the user if questions arise
