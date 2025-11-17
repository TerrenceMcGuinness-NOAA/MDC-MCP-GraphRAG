#!/bin/bash
# ChromaDB Service Startup Script (System Python)
# Uses Rocky 9 system Python 3.11 with system-wide ChromaDB installation

set -e

# ChromaDB environment
export PERSIST_DIRECTORY="${PERSIST_DIRECTORY:-/mcp_rag_eib/data/chromadb}"
export CHROMA_SERVER_HOST="${CHROMA_SERVER_HOST:-0.0.0.0}"
export CHROMA_SERVER_HTTP_PORT="${CHROMA_SERVER_HTTP_PORT:-8080}"
export ALLOW_RESET="${ALLOW_RESET:-true}"

echo "[START] Starting ChromaDB server with system Python..."
echo "[INFO] Python: /usr/bin/python3.11"
echo "[INFO] ChromaDB: system-wide installation"
echo "[INFO] Persist directory: ${PERSIST_DIRECTORY}"
echo "[INFO] Host: ${CHROMA_SERVER_HOST}:${CHROMA_SERVER_HTTP_PORT}"

# Start ChromaDB with system Python
exec /usr/bin/python3.11 -m chromadb.cli.cli run \
    --host "${CHROMA_SERVER_HOST}" \
    --port "${CHROMA_SERVER_HTTP_PORT}" \
    --path "${PERSIST_DIRECTORY}"
