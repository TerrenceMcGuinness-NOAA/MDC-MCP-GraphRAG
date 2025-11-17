#!/bin/bash
################################################################################
# MCP RAG Persistent Environment Configuration
# Version: 3.4.1
# 
# What is this?
#   - Sets up all environment variables for MCP RAG system
#   - Initializes Spack module system and loads ChromaDB dependencies
#   - Configures cache directories
#   - Makes Node.js and ChromaDB accessible
#
# Usage: source /mcp_rag_eib/mcp_server_node/mcp-env.sh
################################################################################

# Persistent storage paths
export PERSISTENT_ROOT="/mcp_rag_eib"
export SPACK_ROOT="${PERSISTENT_ROOT}/spack"
export MCP_ROOT="${PERSISTENT_ROOT}/mcp_server_node"
export CHROMADB_ROOT="${PERSISTENT_ROOT}/etc/chromadb"
export CHROMADB_DATA="${PERSISTENT_ROOT}/data/chromadb"
export CACHE_ROOT="${PERSISTENT_ROOT}/cache"

# Git repository (now at PERSISTENT_ROOT level, not under MCP_ROOT)
export GIT_REPO="${PERSISTENT_ROOT}/global-workflow_MCP_node.js-RAG"
export MCP_SOURCE="${GIT_REPO}/dev/ci/scripts/utils/Copilot/mcp_server_node"

# Service endpoints
export CHROMADB_URL="http://127.0.0.1:8080"
export CHROMADB_PORT=8080

# MCP configuration
export MCP_WORKFLOW_ROOT="${GIT_REPO}"
export MCP_KNOWLEDGE_BASE="${MCP_ROOT}/knowledge-base"
export MCP_DATABASE="${MCP_ROOT}/database"
export MCP_LOGS="${MCP_ROOT}/logs"

# Cache directories (for faster rebuilds)
export TRANSFORMERS_CACHE="${CACHE_ROOT}/transformers"
export NPM_CONFIG_CACHE="${CACHE_ROOT}/npm"
export PIP_CACHE_DIR="${CACHE_ROOT}/pip"
export HF_HOME="${CACHE_ROOT}/huggingface"

# Node.js configuration
export NODE_ENV=production
export NODE_PATH="${MCP_ROOT}/node_modules"

# Module system initialization (Rocky 9 Architecture)
# ARCHITECTURE: system Lmod + local Spack at /mcp_rag_eib/spack
# NOT using: /apps/spack or /contrib-epic/spack-stack-rocky8
if [ -f /apps/lmod/lmod/init/bash ]; then
    # Use system Lmod
    source /apps/lmod/lmod/init/bash
    module use /apps/modules/modulefiles 2>/dev/null
    if [ -d /mcp_rag_eib/spack/share/spack/lmod/linux-rocky9-x86_64/Core ]; then
        module use /mcp_rag_eib/spack/share/spack/lmod/linux-rocky9-x86_64/Core 2>/dev/null
    fi
    ml python/3.11 2>/dev/null || true
elif [ -f /usr/share/Modules/init/bash ]; then
    # Fallback to Environment Modules
    source /usr/share/Modules/init/bash
    module use /apps/modules/modulefiles 2>/dev/null
    module load python/3.11 2>/dev/null || true
fi

# Source Spack environment (for spack command)
if [ -f /mcp_rag_eib/spack/share/spack/setup-env.sh ]; then
    source /mcp_rag_eib/spack/share/spack/setup-env.sh
fi

# Update PATH
export PATH="${MCP_ROOT}/node_modules/.bin:${MCP_ROOT}/bin:${PATH}"

echo "══════════════════════════════════════════════════════════"
echo "  MCP RAG Environment Loaded (v3.4.0)"
echo "══════════════════════════════════════════════════════════"
echo ""
echo "Persistent Storage:"
echo "  Root:        ${PERSISTENT_ROOT}"
echo "  Spack:       ${SPACK_ROOT}"
echo "  MCP Server:  ${MCP_ROOT}"
echo "  Git Repo:    ${GIT_REPO}"
echo ""
echo "Services:"
echo "  ChromaDB:    ${CHROMADB_URL}"
echo "  Data Path:   ${CHROMADB_DATA}"
echo ""
echo "Configuration:"
echo "  Workflow:    ${MCP_WORKFLOW_ROOT}"
echo "  Knowledge:   ${MCP_KNOWLEDGE_BASE}"
echo "  Logs:        ${MCP_LOGS}"
echo ""
echo "Cache (reused across rebuilds):"
echo "  NPM:         ${NPM_CONFIG_CACHE}"
echo "  pip:         ${PIP_CACHE_DIR}"
echo "  Transformers: ${TRANSFORMERS_CACHE}"
echo "══════════════════════════════════════════════════════════"
