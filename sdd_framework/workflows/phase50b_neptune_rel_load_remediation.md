# Phase 50b: Neptune Relationship Load Remediation

## Overview

The Phase 50 `load-graph` phase reported success (watermark `load:graph: "done"`, `relsLoaded: 2633374`) but Neptune contains **zero relationships**. All 98,813 nodes loaded correctly with `_mergeId` composite keys, and manual relationship creation works. The relationship MERGE batches silently failed — the `.catch()` handler on each batch logged errors to stderr but did not halt execution or mark the watermark as failed.

Additionally, 45,296 orphan nodes from the first crashed run (Phase 50, pre-fix) remain in Neptune without `_mergeId` properties, inflating the node count from 98,813 to 107,418.

## Root Cause

The `loadGraph` relationship loading loop uses:
```javascript
await runWithRetry(pool.sessionFn(w),
  `UNWIND $rels AS r
   MATCH (a {_mergeId: r.fromId}), (b {_mergeId: r.toId})
   MERGE (a)-[rel:\`${relType}\`]->(b)
   ON CREATE SET rel += r.props`,
  { rels: sanitized }
).catch(err => console.error(`[ERROR] Rels batch ${batchStart} type=${relType}: ${err.message.substring(0, 100)}`));
```

The `.catch()` swallows the error — the batch is counted as processed, the watermark advances, and the loop continues. If every batch fails (likely due to query timeouts from scanning 107K nodes without an index on `_mergeId`), the entire rel load completes with zero rels created but the watermark says "done".

**Contributing factors:**
1. No index on `_mergeId` — Neptune auto-indexes some properties but MATCH on an unindexed property across 107K nodes is slow
2. 45K orphan nodes from crashed first run increase scan time
3. `.catch()` swallows errors instead of failing the batch/process
4. Watermark written as "done" regardless of actual success

## Prerequisites

- Phase 50 node load — COMPLETE (98,813 nodes with `_mergeId` in Neptune)
- Phase 50 vector load — COMPLETE (85,921 docs in OpenSearch, verified)
- S3 graph dump — available at `s3://mdc-mcp-rag-migration/graph/neo4j-dump.json.gz`

## Execution Environment

- All steps run on the AWS EC2 instance
- Neptune endpoint: `mdc-mcp-rag-neptune.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182`
- OpenSearch endpoint: `vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com`
- Working directory: `mcp_server_node/`

## Steps

### Step 0: Purge orphan nodes from crashed first run
- Tag: implement
- Delete all nodes where `_mergeId IS NULL` (45,296 orphans from pre-fix run)
- Verify node count drops from 107,418 to ~62,122 (98,813 - orphans that share names with good nodes)
- Use batched DELETE to avoid Neptune timeout on large deletes

### Step 1: Create Neptune index on `_mergeId`
- Tag: configure
- Neptune openCypher doesn't support CREATE INDEX, but we can use the Neptune `/propertygraph/statistics` endpoint or rely on auto-indexing
- Alternatively, verify that `_mergeId` is being auto-indexed by running an EXPLAIN on a MATCH query
- If not indexed, consider using the Neptune bulk loader approach from the crash assessment

### Step 2: Fix error handling in loadGraph rel loop
- Tag: implement
- Replace `.catch()` with proper error accumulation — track failed batches
- Add a failure threshold: if >5% of batches fail, abort and report
- Log actual error counts at completion
- Do NOT write `load:graph: "done"` watermark if any rels failed to load

### Step 3: Reset rel watermarks in S3
- Tag: configure
- Remove `load:graph`, `load:graph:relProgress`, `load:graph:relsLoaded` from watermark
- Keep `load:graph:nodeProgress` and `load:graph:nodes` (nodes are fine)
- Keep all `load:*` vector watermarks (vectors are fine)

### Step 4: Re-run relationship load
- Tag: implement
- `node scripts/migrate-to-aws.js --phase load-graph`
- With orphans purged and better error handling, this should complete in 45-90 min
- Monitor progress via watermark updates and console output

### Step 5: Verify graph parity
- Tag: validate
- `node scripts/migrate-to-aws.js --phase verify`
- Nodes: should match ~98,813 (or close, after orphan purge)
- Rels: should match ~2,633,374 (the resolvable subset)
- Spot-check: query a known node and verify it has relationships

### Step 6: Run cross-environment verification
- Tag: validate
- `node scripts/verify-migration.js`
- Compare counts against legacy system (ChromaDB↔OpenSearch, Neo4j↔Neptune)

## Total Steps: 7 (Steps 0-6)

## Acceptance Criteria

1. Neptune relationship count > 2,600,000 (within 1% of 2,633,374)
2. Neptune node count within 5% of 98,813 (orphans purged)
3. Verify phase passes for both vectors and graph
4. At least one end-to-end query (e.g., `trace_full_execution_chain`) returns graph-traversal results from Neptune
5. Error handling in loadGraph no longer silently swallows batch failures

## Current State

| Component | Status | Count |
|-----------|--------|-------|
| S3 Exports | ✅ Complete | 5 vector collections + 1 graph dump |
| OpenSearch Load | ✅ Complete | 85,921 docs across 5 indices (verified) |
| Neptune Nodes | ⚠️ Inflated | 107,418 (98,813 good + 45,296 orphans) |
| Neptune Rels | ❌ Zero | 0 / 2,633,374 expected |
| Verification | ❌ Failed | Vectors pass, graph fails |

## Environment Variables

| Variable | Value | Purpose |
|----------|-------|---------|
| OPENSEARCH_ENDPOINT | https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com | OpenSearch endpoint |
| NEPTUNE_ENDPOINT | wss://mdc-mcp-rag-neptune.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182 | Neptune endpoint |
| AWS_REGION | us-east-1 | AWS region |
| MIGRATION_BUCKET | mdc-mcp-rag-migration | S3 bucket |

## Reference

- Crash assessment: `docs/load-graph-crash-assessment.md`
- Migration script: `mcp_server_node/scripts/migrate-to-aws.js`
- Phase 50 SDD: `sdd_framework/workflows/phase50_parallel_works_s3_migration_export.md`
- Verify script: `mcp_server_node/scripts/verify-migration.js`

## Branch

`develop_aws`
