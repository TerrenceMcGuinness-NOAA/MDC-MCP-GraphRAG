#!/bin/bash
# ChromaDB Service Startup Script
# Loads Spack modules and starts ChromaDB server with proper environment

set -e

# Source module system
source /apps/lmod/lmod/init/bash 2>/dev/null || true

# Load Spack
source /mcp_rag_eib/spack/share/spack/setup-env.sh 2>/dev/null || true

# Load required modules (gcc first for hierarchical modules)
module load gcc/11.5.0 2>/dev/null || true
module load py-numpy py-pydantic py-httpx py-requests 2>/dev/null || true

# ChromaDB environment
export PERSIST_DIRECTORY="${PERSIST_DIRECTORY:-/mcp_rag_eib/data/chromadb}"
export CHROMA_SERVER_HOST="${CHROMA_SERVER_HOST:-0.0.0.0}"
export CHROMA_SERVER_HTTP_PORT="${CHROMA_SERVER_HTTP_PORT:-8080}"
export ALLOW_RESET="${ALLOW_RESET:-true}"

# Find raw Spack Python
SPACK_PYTHON=$(find /mcp_rag_eib/spack/opt/spack/linux-skylake_avx512 -type f -path "*/python-3.11.*/bin/python3.11" | head -1)

if [[ -z "$SPACK_PYTHON" ]]; then
    echo "[ERROR] Could not find Spack Python binary"
    exit 1
fi

# Add ChromaDB location to PYTHONPATH (from pip install with raw Python)
CHROMADB_SITE_PACKAGES=$(find /mcp_rag_eib/spack/opt/spack/linux-skylake_avx512 -type d -path "*/python-venv-*/lib/python3.11/site-packages" | head -1)
export PYTHONPATH="${CHROMADB_SITE_PACKAGES}:${PYTHONPATH}"

echo "[START] Starting ChromaDB server..."
echo "[INFO] Python: ${SPACK_PYTHON}"
echo "[INFO] ChromaDB location: ${CHROMADB_SITE_PACKAGES}"
echo "[INFO] Persist directory: ${PERSIST_DIRECTORY}"
echo "[INFO] Host: ${CHROMA_SERVER_HOST}:${CHROMA_SERVER_HTTP_PORT}"

# Start ChromaDB
exec "${SPACK_PYTHON}" -m chromadb.cli.cli run \
    --host "${CHROMA_SERVER_HOST}" \
    --port "${CHROMA_SERVER_HTTP_PORT}" \
    --path "${PERSIST_DIRECTORY}"
