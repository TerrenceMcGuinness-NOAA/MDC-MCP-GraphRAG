#!/bin/bash
# ChromaDB systemd startup script
# Uses Spack modules and proper persistent database location

set -e

# Load Spack modules
if [ -f /mcp_rag_eib/eib-mcp-rag-server/SETUP/mcp-env.sh ]; then
    set +u
    source /mcp_rag_eib/eib-mcp-rag-server/SETUP/mcp-env.sh > /dev/null 2>&1
    set -u
fi

# Database configuration
DB_PATH="${PERSIST_DIRECTORY:-/mcp_rag_eib/data/chromadb}"
PORT="${CHROMA_SERVER_HTTP_PORT:-8080}"
HOST="${CHROMA_SERVER_HOST:-0.0.0.0}"

echo "[START] ChromaDB Server"
echo "[INFO] Database: $DB_PATH"
echo "[INFO] Listening: http://$HOST:$PORT"

# Change to mcp_server_node directory
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node

# Start ChromaDB using the Python server script
exec python3 chromadb_server.py
