#!/bin/bash
# Start ChromaDB HTTP server for MCP RAG integration
# This script starts the ChromaDB server to make the vector database accessible to the Node.js MCP server

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB_PATH="${SCRIPT_DIR}/knowledge-base/chroma_db"
PORT=8000

echo "============================================"
echo "ChromaDB Server Startup"
echo "============================================"
echo "Database path: ${DB_PATH}"
echo "Server will listen on: http://0.0.0.0:${PORT}"
echo ""

# Check if database exists
if [ ! -d "${DB_PATH}" ]; then
    echo "Error: Database directory not found at ${DB_PATH}"
    exit 1
fi

if [ ! -f "${DB_PATH}/chroma.sqlite3" ]; then
    echo "Error: ChromaDB database file not found at ${DB_PATH}/chroma.sqlite3"
    exit 1
fi

echo "✓ Database found ($(du -sh ${DB_PATH}/chroma.sqlite3 | cut -f1))"
echo ""

# Check if port is already in use
if netstat -tlnp 2>/dev/null | grep -q ":${PORT} "; then
    echo "Warning: Port ${PORT} is already in use"
    echo "Checking if ChromaDB is already running..."
    if python -c "import chromadb; client = chromadb.HttpClient(host='localhost', port=${PORT}); print('ChromaDB server is accessible')" 2>/dev/null; then
        echo "✓ ChromaDB server is already running and accessible"
        exit 0
    else
        echo "Error: Port ${PORT} is in use but ChromaDB is not responding"
        exit 1
    fi
fi

echo "Starting ChromaDB server..."
echo "Press Ctrl+C to stop the server"
echo ""

# Start ChromaDB server
# Note: This will run in foreground. For background operation, add & at the end
cd "${SCRIPT_DIR}"
python -m chromadb.cli.cli run --host 0.0.0.0 --port ${PORT} --path "${DB_PATH}"
