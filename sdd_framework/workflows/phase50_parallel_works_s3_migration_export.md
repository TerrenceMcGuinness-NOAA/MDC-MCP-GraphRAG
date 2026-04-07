# Phase 50: Parallel Works S3 Migration Export

## Overview

Export the legacy ChromaDB vector store (~86K documents, 6 collections) and Neo4j graph database (~2.6M relationships) from the Parallel Works VM to the S3 staging bucket (`mdc-mcp-rag-migration`) in AWS account 903050880929. This is the data handoff step between the legacy system and the new AWS-native infrastructure deployed in Phase 49.

## Prerequisites

All must be complete before starting:

- Phase 48 (AWS Infrastructure Port) — COMPLETE
- Phase 49 (Ingestion Pipeline Restructure) — COMPLETE
- CDK Deploy (MdcDataStack) — COMPLETE
  - S3 bucket: `mdc-mcp-rag-migration`
  - Neptune: `mdc-mcp-rag-neptune.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com`
  - OpenSearch: `vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com`
- VPC Endpoints — COMPLETE (10/10)
- AWS credentials available for PW VM (same access key as EC2)

## Execution Environment

- All steps run on the Parallel Works VM
- AWS credentials authenticate to account 903050880929
- ChromaDB must be running at localhost:8080
- Neo4j must be running at localhost:7687
- No CDK or AWS-native services needed on PW

## Steps

### Step 0: Pull latest code and install dependencies
- Tag: configure
- `git checkout develop_aws && git pull origin develop_aws`
- `cd mcp_server_node && npm install`
- Verify `@aws-sdk/client-s3` and `@aws-sdk/credential-provider-node` installed

### Step 1: Configure AWS credentials
- Tag: configure
- Set `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION=us-east-1`
- Verify: `aws s3 ls s3://mdc-mcp-rag-migration/`

### Step 2: Verify legacy databases are running
- Tag: validate
- ChromaDB: `curl -s http://localhost:8080/api/v2/heartbeat`
- Neo4j: `echo "RETURN 1" | cypher-shell -u neo4j -p gfsworkflow2025`

### Step 3: Dry run vector export
- Tag: validate
- `node scripts/migrate-to-aws.js --phase export-vectors --dry-run`
- Verify collection list and document counts match expected (~86K total)

### Step 4: Export vectors (ChromaDB to S3)
- Tag: implement
- `node scripts/migrate-to-aws.js --phase export-vectors`
- Exports 6 collections as gzipped JSON to `s3://mdc-mcp-rag-migration/vectors/`
- Embeddings transferred bitwise (768-dim MPNet, no re-generation)
- Expected collections:
  - code-with-context-v8-0-0 (~60,576 docs)
  - global-workflow-docs-v8-0-0 (~22,498 docs)
  - community-summaries (~2,113 docs)
  - jjobs-v8-0-0 (~700 docs)
  - ci-test-cases-v1-0-0 (~74 docs)
  - ee2-standards-v5-0-0-enhanced (~34 docs)

### Step 5: Export graph (Neo4j to S3)
- Tag: implement
- `node scripts/migrate-to-aws.js --phase export-graph`
- Exports nodes and relationships as gzipped JSON to `s3://mdc-mcp-rag-migration/graph/`

### Step 6: Verify exports in S3
- Tag: validate
- `aws s3 ls s3://mdc-mcp-rag-migration/vectors/ --human-readable`
- `aws s3 ls s3://mdc-mcp-rag-migration/graph/ --human-readable`
- `aws s3 ls s3://mdc-mcp-rag-migration/watermarks/ --human-readable`
- Confirm: 5-6 gzipped files under vectors/, 1 under graph/, 1 watermark

## Total Steps: 7 (Steps 0-6)

## Idempotency

S3 watermarks track progress per collection. If export fails mid-way, re-run the same command and it skips completed collections.

## What Happens Next (back on AWS EC2)

After exports complete, return to the AWS EC2 and run:

1. `node scripts/migrate-to-aws.js --phase load-vectors` (S3 to OpenSearch)
2. `node scripts/migrate-to-aws.js --phase load-graph` (S3 to Neptune)
3. `node scripts/migrate-to-aws.js --phase verify` (count parity check)
4. `node scripts/verify-migration.js` (cross-environment parity)

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| CHROMADB_URL | http://127.0.0.1:8080 | ChromaDB endpoint on PW |
| NEO4J_URI | bolt://localhost:7687 | Neo4j endpoint on PW |
| NEO4J_PASSWORD | gfsworkflow2025 | Neo4j password |
| AWS_REGION | us-east-1 | AWS region for S3 |
| MIGRATION_BUCKET | mdc-mcp-rag-migration | S3 bucket name |

## Reference

- Full runbook: `docs/parallel-works-export-runbook.md`
- Migration script: `mcp_server_node/scripts/migrate-to-aws.js`
- Kiro spec: `.kiro/specs/ingestion-pipeline-restructure/requirements.md` (Reqs 14, 16, 18, 19)

## Branch

`develop_aws`
