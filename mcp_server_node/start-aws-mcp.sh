#!/bin/bash
# Start the MDC MCP RAG AWS server on port 3000
# Usage: ./start-aws-mcp.sh        (foreground)
#        ./start-aws-mcp.sh --bg   (background with nohup)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export DB_BACKEND=aws
export AWS_REGION=us-east-1
export OPENSEARCH_ENDPOINT=https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com
export NEPTUNE_ENDPOINT=wss://mdc-mcp-rag-neptune.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182

# Kill any existing instance
if lsof -i :3000 -t &>/dev/null; then
    echo "[INFO] Killing existing process on port 3000..."
    kill $(lsof -i :3000 -t) 2>/dev/null
    sleep 1
fi

if [[ "$1" == "--bg" ]]; then
    echo "[INFO] Starting mdc-mcp-rag-aws in background (port 3000)..."
    nohup node src/mcp-http-server.js 3000 full > /tmp/mdc-mcp-rag-aws.log 2>&1 &
    echo $! > /tmp/mdc-mcp-rag-aws.pid
    sleep 5
    if curl -s http://localhost:3000/health | grep -q '"status":"ok"'; then
        echo "[OK] Server running (PID $(cat /tmp/mdc-mcp-rag-aws.pid))"
    else
        echo "[ERROR] Server failed to start. Check /tmp/mdc-mcp-rag-aws.log"
    fi
else
    echo "[INFO] Starting mdc-mcp-rag-aws in foreground (port 3000)..."
    exec node src/mcp-http-server.js 3000 full
fi
