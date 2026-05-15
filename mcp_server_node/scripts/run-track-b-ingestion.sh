#!/bin/bash
# Phase 53 Track B — Full re-ingestion suite (background-safe)
# Run with: nohup bash scripts/run-track-b-ingestion.sh > /tmp/track-b-ingestion.log 2>&1 &
# Monitor:  tail -f /tmp/track-b-ingestion.log

set -x
export DB_BACKEND=aws
export NEPTUNE_ENDPOINT="wss://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182"
export OPENSEARCH_ENDPOINT="https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com"
export AWS_REGION=us-east-1
export WORKFLOW_ROOT="/mnt/mdc-mcp-rag/eib-mcp-rag-server/supported_repos/global-workflow"

# Use python3.12 — packages (fparser, sentence-transformers, opensearch-py) are installed here
PYTHON=python3.12

cd /mnt/mdc-mcp-rag/eib-mcp-rag-server/mcp_server_node || exit 1

echo "=== Track B Ingestion Started: $(date) ==="
echo "=== Python: $($PYTHON --version) ==="
echo "=== DB_BACKEND=$DB_BACKEND ==="

# Step 3: Fortran
echo "=== [3/6] Fortran graph ingestion: $(date) ==="
$PYTHON scripts/ingest_fortran_graph.py 2>&1
echo "=== Fortran exit=$?: $(date) ==="

# Step 4: Shell scripts
echo "=== [4/6] Shell graph ingestion: $(date) ==="
$PYTHON scripts/ingest_shell_graph_v8.py 2>&1
echo "=== Shell exit=$?: $(date) ==="

# Step 5: Cross-language bridges
echo "=== [5/6] Cross-language bridges: $(date) ==="
$PYTHON scripts/ingest_cross_language_bridges.py 2>&1
echo "=== Bridges exit=$?: $(date) ==="

# Step 6: Python graph
echo "=== [6/6] Python graph ingestion: $(date) ==="
$PYTHON scripts/ingest_code_v8.py --model mpnet768 2>&1
echo "=== Python exit=$?: $(date) ==="

# Post-ingestion count check
echo "=== Post-ingestion Neptune counts: $(date) ==="
$PYTHON -c "
import boto3, json
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import urllib3
urllib3.disable_warnings()
session = boto3.Session(region_name='us-east-1')
creds = session.get_credentials().get_frozen_credentials()
host = 'mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com'
url = f'https://{host}:8182/opencypher'
http = urllib3.PoolManager(cert_reqs='CERT_NONE')
for label, q in [('Nodes', 'MATCH (n) RETURN count(n) AS c'), ('Rels', 'MATCH ()-[r]->() RETURN count(r) AS c')]:
    body = f'query={q}'
    req = AWSRequest(method='POST', url=url, data=body, headers={'Content-Type': 'application/x-www-form-urlencoded'})
    SigV4Auth(creds, 'neptune-db', 'us-east-1').add_auth(req)
    resp = http.request('POST', url, body=body, headers=dict(req.headers))
    print(f'{label}: {json.loads(resp.data.decode())[\"results\"][0][\"c\"]:,}')
" 2>&1

echo "=== Track B Ingestion COMPLETE: $(date) ==="
