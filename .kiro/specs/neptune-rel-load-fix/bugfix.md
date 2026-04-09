# Bugfix Requirements Document

## Introduction

The Phase 50 `load-graph` phase of `migrate-to-aws.js` reports success (watermark `load:graph: "done"`, `relsLoaded: 2633374`) but Neptune contains zero relationships. All 98,813 nodes loaded correctly with `_mergeId` composite keys, and manual relationship creation works fine. The root cause is that the `.catch()` handler on each relationship MERGE batch swallows errors — every batch failure is silently ignored, the watermark loop advances, and the function completes with zero rels created but writes the watermark as "done". A secondary issue is that 45,296 orphan nodes from a crashed first run remain in Neptune without `_mergeId` properties, inflating the node count to 107,418 and degrading MATCH performance for relationship resolution.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN a relationship MERGE batch fails with a Neptune error (timeout, internal error, auth expiry) THEN the system swallows the error via `.catch(err => console.error(...))` and continues to the next batch without recording the failure

1.2 WHEN all relationship MERGE batches fail silently THEN the system writes the watermark `load:graph: "done"` with `relsLoaded: 2633374` even though zero relationships were actually created in Neptune

1.3 WHEN the `loadGraph` function completes THEN the system unconditionally writes `wm['load:graph'] = 'done'` regardless of how many node or relationship batches actually succeeded

1.4 WHEN a node MERGE batch fails with a Neptune error THEN the system swallows the error via `.catch(err => console.error(...))` on the node loading loop using the same pattern as relationships

1.5 WHEN the migration is re-run after a false "done" watermark THEN the system skips the `load-graph` phase entirely because `wm['load:graph'] === 'done'` evaluates to true, making recovery impossible without manual watermark editing

1.6 WHEN relationship MERGE queries execute against Neptune containing 45,296 orphan nodes (no `_mergeId` property) from a crashed first run THEN the system performs full scans across 107,418 nodes instead of 98,813, increasing query time and contributing to batch timeouts

### Expected Behavior (Correct)

2.1 WHEN a relationship MERGE batch fails after exhausting retries THEN the system SHALL accumulate the error into a failure counter and continue processing remaining batches, logging each failure with batch index and error details

2.2 WHEN the relationship loading loop completes THEN the system SHALL report the total number of failed batches versus successful batches, and SHALL NOT write `load:graph: "done"` if any relationship batches failed

2.3 WHEN the `loadGraph` function completes THEN the system SHALL only write `wm['load:graph'] = 'done'` if both node loading and relationship loading completed with zero batch failures (or failures below a configurable threshold)

2.4 WHEN a node MERGE batch fails after exhausting retries THEN the system SHALL accumulate the error into a failure counter, consistent with the relationship batch error handling

2.5 WHEN the migration is re-run after a failed load THEN the system SHALL detect that `load:graph` is not marked "done" and SHALL resume from the last successful progress watermark (`load:graph:relProgress` or `load:graph:nodeProgress`)

2.6 WHEN the `loadGraph` function starts THEN the system SHALL purge orphan nodes (nodes without `_mergeId` property) from Neptune before loading relationships, or the orphan purge SHALL be available as a prerequisite step, to ensure MATCH queries only scan valid nodes

### Unchanged Behavior (Regression Prevention)

3.1 WHEN all relationship MERGE batches succeed without errors THEN the system SHALL CONTINUE TO write `wm['load:graph'] = 'done'` and report the correct relationship count

3.2 WHEN all node MERGE batches succeed without errors THEN the system SHALL CONTINUE TO load nodes using the parallel writer pool with `_mergeId`-based MERGE and progress watermarking

3.3 WHEN the `load-graph` phase has already completed successfully (watermark is legitimately "done") THEN the system SHALL CONTINUE TO skip the phase on re-run with the `[SKIP] Graph already loaded` message

3.4 WHEN relationship endpoints cannot be resolved (fromName/toName not in nodeIdMap) THEN the system SHALL CONTINUE TO skip those relationships and log the count of skipped rels

3.5 WHEN the `--dry-run` flag is passed THEN the system SHALL CONTINUE TO skip all Neptune writes and watermark updates

3.6 WHEN the `--phase` flag targets a phase other than `load-graph` THEN the system SHALL CONTINUE TO execute only the specified phase without affecting graph loading behavior

3.7 WHEN the verify phase runs after a successful load THEN the system SHALL CONTINUE TO compare exported counts against Neptune counts and upload a parity report to S3
