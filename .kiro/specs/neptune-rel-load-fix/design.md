# Neptune Relationship Load Fix — Bugfix Design

## Overview

The `loadGraph` function in `migrate-to-aws.js` silently swallows every relationship MERGE batch failure via `.catch()`, advances the watermark loop, and unconditionally writes `load:graph: "done"` — resulting in zero relationships in Neptune despite reporting 2,633,374 loaded. Additionally, 45,296 orphan nodes from a crashed first run (no `_mergeId` property) inflate the node count from 98,813 to 107,418, degrading MATCH performance and contributing to batch timeouts.

The fix has four parts: (1) purge orphan nodes, (2) replace `.catch()` with error accumulation and conditional watermark writing, (3) reset S3 watermarks for the rel phase, and (4) re-run relationship loading with the fixed code.

## Glossary

- **Bug_Condition (C)**: A relationship MERGE batch fails after exhausting retries, but the error is swallowed by `.catch()` and the watermark loop continues as if the batch succeeded
- **Property (P)**: Failed batches are accumulated, reported, and prevent the `load:graph: "done"` watermark from being written
- **Preservation**: Successful runs (zero failures) continue to write the "done" watermark; node loading, dry-run, phase filtering, and verify behavior are unchanged
- **`loadGraph`**: The Phase 4 function in `migrate-to-aws.js` that downloads the Neo4j dump from S3 and loads nodes + relationships into Neptune via openCypher MERGE over Bolt with SigV4 IAM auth
- **`WriterPool`**: The parallel writer pool class that manages N Neptune driver/session pairs, distributes batches round-robin, and refreshes SigV4 tokens every 4 minutes
- **`runWithRetry`**: The retry wrapper that catches retriable Neptune errors (Operation terminated, conflicting concurrent, please retry, internal error) with exponential backoff up to 5 attempts
- **`_mergeId`**: The composite key property assigned to every node for deterministic MERGE — derived from `id || path || name || base64(properties)`
- **Orphan nodes**: 45,296 nodes from the crashed first run that lack `_mergeId` properties, inflating Neptune's node count and degrading MATCH scans
- **Watermark**: JSON state persisted to `s3://mdc-mcp-rag-migration/watermarks/migration-state.json` for idempotent re-execution

## Bug Details

### Bug Condition

The bug manifests when any relationship MERGE batch fails after exhausting `runWithRetry`'s 5 retries. The `.catch()` handler on the `runWithRetry` call logs the error to stderr but does not propagate it — the batch is counted as processed, the progress watermark advances, and the loop continues. When all batches fail (likely due to query timeouts from scanning 107K nodes including 45K orphans without `_mergeId`), the function completes with zero relationships created but writes `wm['load:graph'] = 'done'` with `relsLoaded: 2633374`.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type { batchResult: BatchOutcome, errorHandling: ErrorStrategy }
  OUTPUT: boolean

  RETURN input.batchResult = FAILURE_AFTER_RETRIES
         AND input.errorHandling = CATCH_AND_SWALLOW
         AND watermarkWrittenAs('done') = true
         AND actualRelsCreated = 0
END FUNCTION
```

### Examples

- **All batches fail, watermark says "done"**: 6,584 rel batches each fail with "Operation terminated (internal error)" after 5 retries. `.catch()` logs each error. Loop completes. `wm['load:graph'] = 'done'` is written. Neptune has 0 rels. Re-run skips the phase entirely.
- **Partial batch failure, watermark says "done"**: 3,000 of 6,584 batches succeed (creating ~300K rels), 3,584 fail. `.catch()` swallows the failures. `wm['load:graph'] = 'done'` is written with `relsLoaded: 2633374` (the pre-filter count, not the actual count). Re-run skips the phase.
- **Orphan node scan overhead**: MATCH queries scan 107,418 nodes instead of 98,813. The 45,296 orphans without `_mergeId` never match but still consume scan time, pushing batch execution past the SigV4 token expiry window and triggering cascading failures.
- **Node batch failure (same pattern)**: A node MERGE batch fails. `.catch()` swallows it. The node is never created, but the loop continues and the watermark advances.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- When all relationship MERGE batches succeed, the system writes `wm['load:graph'] = 'done'` and reports the correct relationship count
- Node loading uses the parallel WriterPool with `_mergeId`-based MERGE and progress watermarking exactly as before
- When `load:graph` watermark is legitimately "done", re-run skips the phase with `[SKIP] Graph already loaded`
- Relationships with unresolvable endpoints (fromName/toName not in nodeIdMap) are filtered and the skip count is logged
- `--dry-run` skips all Neptune writes and watermark updates
- `--phase` targeting other phases does not affect graph loading
- The verify phase compares exported counts against Neptune counts and uploads a parity report to S3

**Scope:**
All inputs that do NOT involve batch failures in the relationship or node loading loops should be completely unaffected by this fix. This includes:
- Successful batch execution (the happy path)
- S3 download and JSON parsing of the graph dump
- Node pre-processing (_mergeId assignment, nodeIdMap construction)
- Relationship pre-filtering (unresolvable endpoint detection)
- WriterPool lifecycle (init, refresh, close)
- SigV4 token signing and refresh logic

## Hypothesized Root Cause

Based on the bug description and code analysis, the root causes are:

1. **`.catch()` swallows batch errors**: Lines in the rel loading loop use `.catch(err => console.error(...))` which converts a rejected promise into a resolved one. The `await Promise.all(workerTasks)` sees all tasks as resolved, so the loop continues. The same pattern exists in the node loading loop.

2. **Unconditional watermark write**: After the rel loading loop, `wm['load:graph'] = 'done'` is written unconditionally — there is no check on how many batches actually succeeded vs failed.

3. **Orphan nodes from crashed first run**: The first run (Phase 50, pre-fix) crashed at 48.5% node loading, leaving 45,296 nodes in Neptune without `_mergeId` properties. The second run loaded all 98,813 nodes with `_mergeId` via MERGE, but the orphans remain. MATCH queries on `{_mergeId: r.fromId}` must scan all 107,418 nodes, increasing query time and contributing to batch timeouts.

4. **No failure threshold or abort mechanism**: The code has no concept of "too many failures" — even if 100% of batches fail, the function completes normally and writes the success watermark.

## Correctness Properties

Property 1: Bug Condition — Failed Batches Prevent "Done" Watermark

_For any_ execution of `loadGraph` where one or more relationship MERGE batches fail after exhausting retries, the function SHALL NOT write `wm['load:graph'] = 'done'`, SHALL report the count of failed vs successful batches, and SHALL leave the watermark in a state that allows re-run to resume from the last successful progress point.

**Validates: Requirements 2.1, 2.2, 2.3, 2.5**

Property 2: Preservation — Successful Runs Write "Done" Watermark

_For any_ execution of `loadGraph` where all relationship and node MERGE batches succeed (zero failures), the function SHALL write `wm['load:graph'] = 'done'` with the correct relationship count, preserving the existing happy-path behavior identical to the original code.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

## Fix Implementation

### Changes Required

All changes are in `mcp_server_node/scripts/migrate-to-aws.js`, specifically the `loadGraph` function.

**File**: `mcp_server_node/scripts/migrate-to-aws.js`

**Function**: `loadGraph`

**Specific Changes**:

1. **Add orphan purge step at start of `loadGraph`**: Before loading relationships, execute a batched DELETE of nodes where `_mergeId IS NULL`. Use batches of 10,000 with `runWithRetry` to avoid Neptune timeout on large deletes. Log the count of purged nodes.
   ```
   MATCH (n) WHERE n._mergeId IS NULL
   WITH n LIMIT 10000
   DETACH DELETE n
   RETURN count(n) AS deleted
   ```
   Repeat until `deleted = 0`.

2. **Replace `.catch()` with error accumulation in rel loop**: Remove the `.catch()` on `runWithRetry` calls in the relationship loading loop. Instead, wrap each batch in a try/catch that increments a `failedRelBatches` counter and logs the error with batch index, rel type, and error message.
   ```javascript
   let failedRelBatches = 0;
   // In the worker task:
   try {
     await runWithRetry(pool.sessionFn(w), query, params);
   } catch (err) {
     failedRelBatches++;
     console.error(`[ERROR] Rels batch ${batchStart} type=${relType}: ${err.message.substring(0, 100)}`);
   }
   ```

3. **Replace `.catch()` with error accumulation in node loop**: Same pattern for the node loading loop — replace `.catch()` with try/catch and a `failedNodeBatches` counter.

4. **Add failure threshold and conditional watermark**: After the rel loading loop, check `failedRelBatches` against a threshold (default: 0 — any failure prevents "done"). Only write `wm['load:graph'] = 'done'` if both `failedNodeBatches === 0` and `failedRelBatches === 0`. Log a summary:
   ```
   [RESULT] Nodes: X batches succeeded, Y failed. Rels: A batches succeeded, B failed.
   ```
   If failures > 0, log:
   ```
   [WARN] load:graph NOT marked done — N batch failures. Re-run to retry.
   ```

5. **Watermark reset for rel phase**: Provide a mechanism (or document the manual step) to reset only the rel-related watermark keys: `load:graph`, `load:graph:relProgress`, `load:graph:relsLoaded`. Keep `load:graph:nodeProgress`, `load:graph:nodes`, and all vector watermarks intact.

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write tests that mock `runWithRetry` to throw on relationship batches and verify that the current code (a) swallows the error, (b) advances the watermark, and (c) writes `load:graph: "done"` despite zero rels created. Run these tests on the UNFIXED code to observe the silent failure.

**Test Cases**:
1. **All-batches-fail test**: Mock `runWithRetry` to always throw for rel batches. Verify `wm['load:graph']` is still set to `'done'` and `failedRelBatches` is not tracked (will fail on unfixed code — confirms the bug)
2. **Partial-failure test**: Mock `runWithRetry` to throw on 50% of rel batches. Verify watermark still says "done" (will fail on unfixed code)
3. **Node-batch-failure test**: Mock `runWithRetry` to throw on node batches. Verify `.catch()` swallows the error (will fail on unfixed code)
4. **Re-run-after-false-done test**: Set `wm['load:graph'] = 'done'` with zero rels in Neptune. Verify `loadGraph` skips entirely (confirms the re-run problem)

**Expected Counterexamples**:
- `wm['load:graph']` is `'done'` even when all batches failed
- No failure counter exists in the current code
- Re-run skips the phase because the watermark says "done"

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds (batch failures occur), the fixed function accumulates errors and does NOT write the "done" watermark.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := loadGraph_fixed(input)
  ASSERT result.failedBatches > 0
  ASSERT result.watermark['load:graph'] !== 'done'
  ASSERT result.watermark['load:graph:relProgress'] reflects actual progress
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold (all batches succeed), the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT loadGraph_original(input).watermark = loadGraph_fixed(input).watermark
  ASSERT loadGraph_original(input).relsCreated = loadGraph_fixed(input).relsCreated
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many combinations of batch sizes, parallelism levels, and node/rel counts
- It catches edge cases like empty dumps, single-node graphs, or all-unresolvable rels
- It provides strong guarantees that the happy path is unchanged

**Test Plan**: Observe behavior on UNFIXED code first for successful batch execution, then write property-based tests capturing that behavior.

**Test Cases**:
1. **Happy-path watermark preservation**: Verify that when all batches succeed, `wm['load:graph'] = 'done'` is written with correct counts — same as original code
2. **Node loading preservation**: Verify that node MERGE with `_mergeId`, parallel WriterPool, and progress watermarking produce identical results
3. **Unresolvable rel filtering preservation**: Verify that rels with missing fromName/toName are still filtered and the skip count is logged
4. **Dry-run preservation**: Verify that `--dry-run` still skips all Neptune writes

### Unit Tests

- Test error accumulation: mock `runWithRetry` to throw, verify `failedRelBatches` increments
- Test conditional watermark: verify "done" is NOT written when `failedRelBatches > 0`
- Test conditional watermark: verify "done" IS written when `failedRelBatches === 0`
- Test orphan purge: mock Neptune session, verify batched DELETE query is issued until `deleted = 0`
- Test watermark reset: verify only rel-related keys are removed, node and vector keys preserved

### Property-Based Tests

- Generate random (successCount, failureCount) pairs and verify watermark is "done" iff failureCount === 0
- Generate random graph dumps (varying node/rel counts, label distributions) and verify the happy path produces identical watermarks to the original code
- Generate random batch failure patterns (which batches fail, which succeed) and verify the failure counter matches the actual number of thrown errors

### Integration Tests

- Run `loadGraph` against a test Neptune instance with a small graph dump (100 nodes, 500 rels) and verify all rels are created
- Run `loadGraph` with orphan nodes present and verify the purge step removes them before rel loading
- Run the full `--phase load-graph` → `--phase verify` pipeline and confirm parity report passes
