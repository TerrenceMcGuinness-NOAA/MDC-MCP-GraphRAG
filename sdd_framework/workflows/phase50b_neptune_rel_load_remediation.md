# Phase 50b: Neptune Relationship Load Remediation

## Overview

The Phase 50 `load-graph` phase reported success (watermark `load:graph: "done"`, `relsLoaded: 2633374`) but Neptune contains **zero relationships**. All 98,813 nodes loaded correctly with `_mergeId` composite keys, and manual relationship creation works. The relationship MERGE batches silently failed — the `.catch()` handler on each batch logged errors to stderr but did not halt execution or mark the watermark as failed.

Additionally, 45,296 orphan nodes from the first crashed run (Phase 50, pre-fix) remain in Neptune without `_mergeId` properties, inflating the node count from 98,813 to 107,418.

## Approach: Neptune Bulk Loader (Fix 1 from crash assessment)

After evaluating both Bolt-based retry (Fix 2) and Neptune's native bulk loader (Fix 1), we are going with the **bulk loader approach**. The Bolt-based approach failed silently on all 2.6M relationships due to query timeouts scanning 107K nodes. The bulk loader bypasses Bolt entirely, uses Neptune's internal parallel loading engine, and reads openCypher CSV directly from S3.

**Advantages over Bolt:**
- 10-100x faster (Neptune internal parallelism vs client-side Bolt)
- No SigV4 token expiry issues (single API call)
- No MERGE scan overhead (direct CREATE)
- Built-in resume on failure
- Clean slate — no orphan node complications

## Prerequisites

- Phase 50 vector load — COMPLETE (85,921 docs in OpenSearch, verified)
- S3 graph dump — available at `s3://mdc-mcp-rag-migration/graph/neo4j-dump.json.gz`
- IAM role `mdc-mcp-rag-neptune-s3-loader` — EXISTS but NOT attached to Neptune cluster
  - Admin request: `docs/neptune-bulk-loader-role-request.txt`
  - Requires `iam:PassRole` (PowerUser denied, admin must run)

## Execution Environment

- All steps run on the AWS EC2 instance
- Neptune endpoint: `mdc-mcp-rag-neptune.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182`
- OpenSearch endpoint: `vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com`
- Working directory: `mcp_server_node/`

## Steps

### Step 0: Admin attaches IAM role to Neptune cluster
- Tag: configure
- Admin runs: `aws neptune add-role-to-db-cluster --db-cluster-identifier mdc-mcp-rag-neptune --role-arn arn:aws:iam::903050880929:role/service-role/mdc-mcp-rag-neptune-s3-loader`
- Verify: `aws neptune describe-db-clusters --db-cluster-identifier mdc-mcp-rag-neptune --query 'DBClusters[0].AssociatedRoles'`
- Status should show `ACTIVE`
- **BLOCKER**: Cannot proceed until this is done

### Step 1: Purge Neptune (clean slate)
- Tag: implement
- Drop all nodes and relationships from Neptune
- `MATCH (n) DETACH DELETE n` (batched, 10K at a time to avoid timeout)
- Verify: `MATCH (n) RETURN count(n)` returns 0
- This removes both the 98,813 good nodes and 45,296 orphans — bulk loader will recreate everything

### Step 2: Write openCypher CSV converter script
- Tag: implement
- Create `mcp_server_node/scripts/convert-to-opencypher-csv.js`
- Downloads `s3://mdc-mcp-rag-migration/graph/neo4j-dump.json.gz`
- Converts to openCypher CSV format:
  - `nodes.csv`: `:ID,:LABEL,prop1:Type,prop2:Type,...`
  - `relationships.csv`: `:START_ID,:END_ID,:TYPE,prop1:Type,...`
- Node `:ID` = `nodeMergeId()` (same composite key: `id || path || name || hash`)
- Rel `:START_ID`/`:END_ID` = resolved via nodeIdMap (same as current code)
- Skip unresolvable rels (log count)
- `sanitizeProps()` for Neptune property type compliance
- Gzip output files
- Upload to `s3://mdc-mcp-rag-migration/graph-csv/nodes.csv.gz` and `relationships.csv.gz`

### Step 3: Upload CSVs to S3
- Tag: implement
- Part of the converter script (Step 2) — uploads directly to S3
- Verify: `aws s3 ls s3://mdc-mcp-rag-migration/graph-csv/ --human-readable`

### Step 4: Run Neptune bulk loader — nodes
- Tag: implement
- Call Neptune `/loader` API via HTTP POST with SigV4:
  ```
  POST https://<neptune-endpoint>:8182/loader
  {
    "source": "s3://mdc-mcp-rag-migration/graph-csv/nodes.csv.gz",
    "format": "opencypher",
    "iamRoleArn": "arn:aws:iam::903050880929:role/service-role/mdc-mcp-rag-neptune-s3-loader",
    "region": "us-east-1",
    "failOnError": "TRUE",
    "parallelism": "OVERSUBSCRIBE",
    "updateSingleCardinalityProperties": "TRUE"
  }
  ```
- Poll loader status until complete
- Verify node count matches expected (~98,813)

### Step 5: Run Neptune bulk loader — relationships
- Tag: implement
- Same `/loader` API call with `relationships.csv.gz`
- Poll loader status until complete
- Verify rel count matches expected (~2,633,374)

### Step 6: Fix Bolt error handling (defense in depth)
- Tag: implement
- Even though we're using bulk loader for this migration, fix the `.catch()` swallowing in `loadGraph` for future incremental updates:
  - Replace `.catch()` with error accumulation counters
  - Add conditional watermark write (only "done" if zero failures)
  - Keep as fallback for post-migration incremental graph updates

### Step 7: Reset watermarks and verify graph parity
- Tag: validate
- Reset `load:graph*` watermarks in S3 to reflect bulk loader results
- `node scripts/migrate-to-aws.js --phase verify`
- Nodes: should match ~98,813
- Rels: should match ~2,633,374
- Spot-check: query a known node and verify it has relationships

### Step 8: Run cross-environment verification
- Tag: validate
- `node scripts/verify-migration.js`
- Compare counts against legacy system (ChromaDB↔OpenSearch, Neo4j↔Neptune)

## Total Steps: 9 (Steps 0-8)

## Acceptance Criteria

1. Neptune relationship count > 2,600,000 (within 1% of 2,633,374)
2. Neptune node count within 1% of 98,813
3. Verify phase passes for both vectors and graph
4. At least one end-to-end query (e.g., `trace_full_execution_chain`) returns graph-traversal results from Neptune
5. Error handling in loadGraph no longer silently swallows batch failures (defense in depth)
6. Bulk loader completes in < 30 minutes (vs hours for Bolt approach)

## Current State

| Component | Status | Count |
|-----------|--------|-------|
| S3 Exports | ✅ Complete | 5 vector collections + 1 graph dump |
| OpenSearch Load | ✅ Complete | 85,921 docs across 5 indices (verified) |
| Neptune Nodes | ⚠️ Inflated | 107,418 (98,813 good + 45,296 orphans) |
| Neptune Rels | ❌ Zero | 0 / 2,633,374 expected |
| IAM Role | ⚠️ Exists but not attached | Admin request submitted |
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
- Admin request: `docs/neptune-bulk-loader-role-request.txt`
- Migration script: `mcp_server_node/scripts/migrate-to-aws.js`
- Phase 50 SDD: `sdd_framework/workflows/phase50_parallel_works_s3_migration_export.md`
- Verify script: `mcp_server_node/scripts/verify-migration.js`
- Kiro bugfix spec: `.kiro/specs/neptune-rel-load-fix/`

## Branch

`develop_aws`
