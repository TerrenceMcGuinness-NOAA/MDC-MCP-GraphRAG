# Implementation Plan

- [ ] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Failed Batches Silently Swallowed, Watermark Written as "Done"
  - **DEFERRED**: Bulk loader approach bypasses the Bolt loadGraph code path entirely
  - **NOTE**: Still valuable for future incremental Bolt updates — defer to post-migration
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
  - Observe on UNFIXED code: relationships with unresolvable endpoints (fromName/toName not in nodeIdMap) are filtered and `skippedRels` count is logged
  - Observe on UNFIXED code: `--dry-run` skips all Neptune writes and watermark updates
  - Write property-based tests with fast-check
  - Verify all preservation tests PASS on UNFIXED code
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [ ] 3. Fix loadGraph Bolt error handling (defense in depth)

  - [ ] 3.1 Replace .catch() with error accumulation in relationship loading loop
    - Remove `.catch(err => console.error(...))` from the `runWithRetry` call in the rel loading worker tasks
    - Wrap each batch in try/catch that increments a `failedRelBatches` counter
    - Log each failure with batch index, rel type, and truncated error message (existing format preserved)
    - _Requirements: 1.1, 2.1_

  - [ ] 3.2 Replace .catch() with error accumulation in node loading loop
    - Apply the same pattern as 3.1 to the node loading worker tasks
    - Add a `failedNodeBatches` counter
    - _Requirements: 1.4, 2.4_

  - [ ] 3.3 Add conditional watermark write based on failure counts
    - Only write `wm['load:graph'] = 'done'` if BOTH `failedNodeBatches === 0` AND `failedRelBatches === 0`
    - Log summary: `[RESULT] Nodes: X succeeded, Y failed. Rels: A succeeded, B failed.`
    - If failures > 0: `[WARN] load:graph NOT marked done — N batch failures. Re-run to retry.`
    - _Requirements: 1.2, 1.3, 2.2, 2.3, 2.5, 3.1_

  - [ ] 3.4 Verify bug condition exploration test now passes
    - Re-run the SAME test from task 1 on FIXED code
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.1, 2.2, 2.3, 2.5_

  - [ ] 3.5 Verify preservation tests still pass
    - Re-run the SAME tests from task 2 on FIXED code
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 4. Neptune bulk loader — CSV converter and data load

  - [x] 4.1 Write openCypher CSV converter script
    - Create `mcp_server_node/scripts/convert-to-opencypher-csv.js`
    - Download `s3://mdc-mcp-rag-migration/graph/neo4j-dump.json.gz`
    - Convert nodes to openCypher CSV: `:ID,:LABEL,name:String,path:String,...`
    - Convert relationships to openCypher CSV: `:START_ID,:END_ID,:TYPE,weight:Float,...`
    - Node `:ID` = `nodeMergeId()` (composite key: `id || path || name || hash`)
    - Rel `:START_ID`/`:END_ID` resolved via nodeIdMap (skip unresolvable, log count)
    - `sanitizeProps()` for Neptune property type compliance
    - Gzip output, upload to `s3://mdc-mcp-rag-migration/graph-csv/`
    - Support `--dry-run` flag

  - [x] 4.2 Purge Neptune (clean slate)
    - Batched `MATCH (n) WITH n LIMIT 10000 DETACH DELETE n` until count is 0
    - Removes both 98,813 good nodes and 45,296 orphans
    - Verify: `MATCH (n) RETURN count(n)` returns 0
    - _Requirements: 1.6, 2.6_

  - [x] 4.3 Run CSV converter and upload to S3
    - `node scripts/convert-to-opencypher-csv.js`
    - Verify: `aws s3 ls s3://mdc-mcp-rag-migration/graph-csv/ --human-readable`
    - Expected: `nodes.csv.gz` + `relationships.csv.gz`

  - [x] 4.4 Run Neptune bulk loader — nodes
    - **COMPLETE**: 59,759 unique nodes loaded (98,813 deduplicated), 746,247 records, 0 errors
    - POST to `https://<neptune>:8182/loader` with SigV4 auth
    - Source: `s3://mdc-mcp-rag-migration/graph-csv/nodes.csv.gz`
    - Format: `opencypher`, parallelism: `OVERSUBSCRIBE`, failOnError: `TRUE`
    - Poll `/loader/<loadId>` until status is `LOAD_COMPLETED`
    - Verify node count: ~98,813

  - [x] 4.5 Run Neptune bulk loader — relationships
    - **COMPLETE**: 2,633,374 rels loaded, 4,591,152 records, 0 errors, ~8 min
    - POST to `https://<neptune>:8182/loader` with SigV4 auth
    - Source: `s3://mdc-mcp-rag-migration/graph-csv/relationships.csv.gz`
    - Same loader params as 4.4
    - Poll until `LOAD_COMPLETED`
    - Verify rel count: ~2,633,374

  - [x] 4.6 Update watermarks to reflect bulk loader results
    - **COMPLETE**: Watermarks updated in S3 with method=neptune-bulk-loader
    - Reset `load:graph*` keys in S3 watermark
    - Set `load:graph: "done"`, `load:graph:nodes`, `load:graph:rels`, `load:graph:relsLoaded`

- [ ] 5. Verify migration parity

  - [ ] 5.1 Run verify phase
    - `OPENSEARCH_ENDPOINT=... NEPTUNE_ENDPOINT=... node scripts/migrate-to-aws.js --phase verify`
    - All 5 vector collections: exact count match
    - Graph nodes: within 1% of 98,813
    - Graph rels: within 1% of 2,633,374

  - [ ] 5.2 Run cross-environment verification
    - `node scripts/verify-migration.js`
    - Compare legacy (ChromaDB + Neo4j) vs AWS (OpenSearch + Neptune)

  - [ ] 5.3 Spot-check graph queries
    - Query a known node and verify it has relationships
    - Test `trace_full_execution_chain` or similar graph traversal against Neptune
