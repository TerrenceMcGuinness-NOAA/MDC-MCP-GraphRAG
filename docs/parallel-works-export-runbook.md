# Parallel Works S3 Export Runbook

## Overview

This runbook covers exporting the legacy ChromaDB and Neo4j data from the Parallel Works VM
to the S3 staging bucket (`mdc-mcp-rag-migration`) in AWS account 903050880929. The export
scripts run on PW and write to S3 using your AWS credentials. No CDK or AWS-native services
are needed on the PW side.

## Prerequisites

### On the AWS EC2 side (must be done FIRST)

1. Admin completes CDK bootstrap (ticket submitted)
2. `cdk deploy MdcDataStack` — creates the S3 bucket `mdc-mcp-rag-migration`
3. Verify bucket exists: `aws s3 ls s3://mdc-mcp-rag-migration/`

### On the Parallel Works side

1. Git pull the latest `develop_aws` branch
2. Node.js 18+ installed
3. npm dependencies installed (includes new `@aws-sdk/client-s3`)
4. AWS credentials configured with S3 write access
5. ChromaDB running and accessible (default: `http://localhost:8080`)
6. Neo4j running and accessible (default: `bolt://localhost:7687`)

## Step-by-Step

### Step 1: Pull latest code

```bash
cd /mcp_rag_eib/eib-mcp-rag-server
git checkout develop_aws
git pull origin develop_aws
```

### Step 2: Install dependencies

```bash
cd mcp_server_node
npm install
```

### Step 3: Configure AWS credentials

Your AWS credentials from the EC2 side work here too. Set them up:

```bash
# Option A: Named profile (RECOMMENDED — preserves PW default credentials)
aws configure --profile noaa-aws
# Access Key ID: (your 903050880929 key)
# Secret Access Key: (your 903050880929 secret)
# Default region: us-east-1
# Output format: json

# Then set the profile for the session
export AWS_PROFILE=noaa-aws

# Option B: Environment variables (temporary, session only)
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_REGION="us-east-1"
```

Verify credentials work and can reach the bucket:

```bash
aws s3 ls s3://mdc-mcp-rag-migration/ 2>&1
```

When done with the export, restore PW default credentials:

```bash
unset AWS_PROFILE
```

If you see "NoSuchBucket" — the CDK deploy hasn't happened yet. Wait for Step 2 in the
AWS EC2 prerequisites above.

### Step 4: Verify legacy databases are running

```bash
# Check ChromaDB
curl -s http://localhost:8080/api/v2/heartbeat | head -1

# Check Neo4j
echo "RETURN 1" | cypher-shell -u neo4j -p gfsworkflow2025 2>&1 | head -3
```

### Step 5: Run the vector export (ChromaDB → S3)

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node

# Dry run first to see what will be exported
node scripts/migrate-to-aws.js --phase export-vectors --dry-run

# If dry run looks good, run for real
node scripts/migrate-to-aws.js --phase export-vectors
```

Expected output:
```
[PHASE 1] Export ChromaDB → S3
[INFO]  Exporting code-with-context-v8-0-0...
[OK]    code-with-context-v8-0-0 — 60576 docs → s3://mdc-mcp-rag-migration/vectors/code-with-context-v8-0-0.json.gz
[INFO]  Exporting global-workflow-docs-v8-0-0...
[OK]    global-workflow-docs-v8-0-0 — 22498 docs → s3://mdc-mcp-rag-migration/vectors/...
...
```

This exports ~86K documents across 6 collections as gzipped JSON to S3.
Embeddings are transferred bitwise (768-dim MPNet) — no re-generation needed.

### Step 6: Run the graph export (Neo4j → S3)

```bash
node scripts/migrate-to-aws.js --phase export-graph
```

Expected output:
```
[PHASE 2] Export Neo4j → S3
[OK]    Graph — ~X nodes, ~Y rels → s3://mdc-mcp-rag-migration/graph/neo4j-dump.json.gz
```

### Step 7: Verify exports landed in S3

```bash
aws s3 ls s3://mdc-mcp-rag-migration/vectors/ --human-readable
aws s3 ls s3://mdc-mcp-rag-migration/graph/ --human-readable
aws s3 ls s3://mdc-mcp-rag-migration/watermarks/ --human-readable
```

You should see:
- 5-6 gzipped JSON files under `vectors/`
- 1 gzipped JSON file under `graph/`
- 1 watermark state file under `watermarks/`

## Idempotency

The export uses S3 watermarks. If it fails mid-way, just re-run the same command.
It will skip already-exported collections and pick up where it left off.

## Environment Variables Reference

| Variable | Default | Purpose |
|----------|---------|---------|
| CHROMADB_URL | http://127.0.0.1:8080 | ChromaDB endpoint on PW |
| NEO4J_URI | bolt://localhost:7687 | Neo4j endpoint on PW |
| NEO4J_PASSWORD | gfsworkflow2025 | Neo4j password |
| AWS_REGION | us-east-1 | AWS region for S3 |
| MIGRATION_BUCKET | mdc-mcp-rag-migration | S3 bucket name |

## What Happens Next (back on AWS EC2)

After the exports complete, switch back to the AWS EC2 and run the load phases:

```bash
# Load vectors into OpenSearch
node scripts/migrate-to-aws.js --phase load-vectors

# Load graph into Neptune
node scripts/migrate-to-aws.js --phase load-graph

# Verify count parity
node scripts/migrate-to-aws.js --phase verify
```

## Troubleshooting

- "NoSuchBucket" — CDK deploy hasn't created the S3 bucket yet
- "AccessDenied" — AWS credentials don't have s3:PutObject on the bucket
- "ECONNREFUSED on 8080" — ChromaDB not running, start it first
- "ServiceUnavailable on 7687" — Neo4j not running, start it first
- Export hangs — large collections (60K+ docs) take several minutes, be patient
