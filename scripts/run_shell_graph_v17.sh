#!/usr/bin/env bash
# Run the shell graph ingestion for gw_v17.
# Graph-only (no embeddings) — expected runtime ~5-15 minutes.
# Usage: nohup ./scripts/run_shell_graph_v17.sh > logs/shell_graph_v17.log 2>&1 &

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

export DB_BACKEND=aws
export OPENSEARCH_ENDPOINT=https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com
export NEPTUNE_ENDPOINT=https://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182
export AWS_REGION=us-east-1
export MCP_WORKTREE_ROOT_OVERRIDE=/mdc-mcp-rag/eib-mcp-rag-server/supported_repos

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting shell graph ingestion for gw_v17"
echo "  Worktree: $MCP_WORKTREE_ROOT_OVERRIDE/dev-v17"
echo "  Neptune: $NEPTUNE_ENDPOINT"
echo ""

python3.12 mcp_server_python/scripts/ingest_shell_graph_v8.py \
  --tenant gw_v17 \
  --mode full

EXIT_CODE=$?

echo ""
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Shell graph ingestion finished (exit=$EXIT_CODE)"

if [ $EXIT_CODE -eq 0 ]; then
  echo "[OK] Run the Fortran bridge next (once FortranProgram nodes exist):"
  echo "  python3.12 mcp_server_python/scripts/create_shell_fortran_bridge.py --tenant gw_v17"
fi

exit $EXIT_CODE
