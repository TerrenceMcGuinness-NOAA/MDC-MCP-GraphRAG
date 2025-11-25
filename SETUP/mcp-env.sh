#!/bin/bash
################################################################################
# MCP RAG Persistent Environment Configuration
# Version: 3.1.0
# Location: /mcp_rag_eib/eib-mcp-rag-server/SETUP/mcp-env.sh
#
# v3.1.0: ChromaDB 1.1.1, Node.js client chromadb@3.0.17, API v2 support
# Usage: source /mcp_rag_eib/eib-mcp-rag-server/SETUP/mcp-env.sh
################################################################################

# Core persistent storage paths
export PERSISTENT_ROOT="/mcp_rag_eib"
export SETUP="${PERSISTENT_ROOT}/eib-mcp-rag-server/SETUP"
export MCP_ROOT="${PERSISTENT_ROOT}/eib-mcp-rag-server/mcp_server_node"
export GIT_REPO="${PERSISTENT_ROOT}/eib-mcp-rag-server/supported_repos/global-workflow"

# ChromaDB configuration
export CHROMADB_ROOT="${PERSISTENT_ROOT}/etc/chromadb"
export CHROMADB_DATA="${PERSISTENT_ROOT}/data/chromadb"
export CHROMADB_URL="http://127.0.0.1:8080"
export CHROMADB_PORT=8080

# GitHub MCP Server Configuration
# Set this to your GitHub Personal Access Token (PAT)
# Generate at: https://github.com/settings/tokens
# Required scopes: repo, read:org, read:user
export GITHUB_TOKEN="${GITHUB_TOKEN:-}" # Set via: export GITHUB_TOKEN="ghp_your_token_here"

# MCP infrastructure paths
export MCP_WORKFLOW_ROOT="${GIT_REPO}"
export MCP_SOURCE="${PERSISTENT_ROOT}/eib-mcp-rag-server/mcp_server_node"
export MCP_KNOWLEDGE_BASE="${MCP_ROOT}/knowledge-base"
export MCP_DATABASE="${MCP_ROOT}/database"
export MCP_LOGS="${MCP_ROOT}/logs"

# Cache directories
export CACHE_ROOT="${PERSISTENT_ROOT}/cache"
export TRANSFORMERS_CACHE="${CACHE_ROOT}/transformers"
export NPM_CONFIG_CACHE="${CACHE_ROOT}/npm"
export PIP_CACHE_DIR="${CACHE_ROOT}/pip"
export HF_HOME="${CACHE_ROOT}/huggingface"

# Node.js configuration
export NODE_ENV=production
export NODE_PATH="${MCP_ROOT}/node_modules"

# Module system initialization (Rocky 9 Architecture)
# This is a fallback - bash_profile should have already initialized modules
if ! command -v module >/dev/null 2>&1; then
    # No module system initialized - set one up
    if [ -f /apps/lmod/lmod/init/bash ]; then
        # Use system Lmod - temporarily disable unbound variable check
        # (Lmod init script may reference unset variables like FPATH)
        set +u 2>/dev/null || true
        source /apps/lmod/lmod/init/bash
        set -u 2>/dev/null || true
        module use /apps/modules/modulefiles 2>/dev/null
        # DO NOT add Spack hierarchical modules here - they require gcc to be loaded first
        # Spack modules will be added later in the provisioning script after gcc is loaded
    elif [ -f /usr/share/Modules/init/bash ]; then
        # Fallback to Environment Modules
        source /usr/share/Modules/init/bash
        module use /apps/modules/modulefiles 2>/dev/null
    fi
fi

# Spack package manager (for spack command)
if [ -f /mcp_rag_eib/spack/share/spack/setup-env.sh ]; then
    source /mcp_rag_eib/spack/share/spack/setup-env.sh
fi

# Python configuration - only load if not already loaded
if command -v module >/dev/null 2>&1 && ! module list 2>&1 | grep -q python; then
    # Load gcc to expose compiler-dependent modules (py-* packages from spack)
    # Then load all ChromaDB and Neo4j dependencies from spack
    if command -v ml >/dev/null 2>&1; then
        ml gcc/11.5.0 2>/dev/null || true
        ml python/3.11 py-pip 2>/dev/null || true
        # Neo4j driver
        ml py-neo4j 2>/dev/null || true
        # ChromaDB dependencies (chromadb itself installed via pip --user)
        ml py-pydantic py-idna py-httpx py-requests py-certifi py-anyio py-sniffio 2>/dev/null || true
        # Sentence-transformers dependencies
        ml py-pillow py-scipy py-numpy py-tokenizers py-tqdm py-pyyaml 2>/dev/null || true
    else
        module load gcc/11.5.0 2>/dev/null || true
        module load python/3.11 py-pip 2>/dev/null || true
        # Neo4j driver
        module load py-neo4j 2>/dev/null || true
        # ChromaDB dependencies (chromadb itself installed via pip --user)
        module load py-pydantic py-idna py-httpx py-requests py-certifi py-anyio py-sniffio 2>/dev/null || true
        # Sentence-transformers dependencies
        module load py-pillow py-scipy py-numpy py-tokenizers py-tqdm py-pyyaml 2>/dev/null || true
    fi
fi

# Ensure user site-packages is in Python path
export PYTHONUSERBASE="${HOME}/.local"
export PATH="${PYTHONUSERBASE}/bin:${PATH}"

# Update PATH
export PATH="${CHROMADB_ROOT}/venv/bin:${MCP_ROOT}/node_modules/.bin:${MCP_ROOT}/bin:${PATH}"

# Display environment
if [ "${1:-}" != "--quiet" ]; then
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║        MCP RAG Persistent Environment Loaded              ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo ""
    echo "Core Paths:"
    echo "  PERSISTENT_ROOT:      ${PERSISTENT_ROOT}"
    echo "  MCP_ROOT:             ${MCP_ROOT}"
    echo "  GIT_REPO:             ${GIT_REPO}"
    echo ""
    echo "Services:"
    echo "  ChromaDB:             ${CHROMADB_URL}"
    echo "  ChromaDB Data:        ${CHROMADB_DATA}"
    echo "  ChromaDB Version:     1.1.1 (API v1/v2)"
    echo "  Node Client Version:  chromadb@3.0.17"
    echo "  GitHub Token:         ${GITHUB_TOKEN:+Set (${#GITHUB_TOKEN} chars)}${GITHUB_TOKEN:-❌ NOT SET}"
    echo ""
    echo "MCP Configuration:"
    echo "  Workflow Root:        ${MCP_WORKFLOW_ROOT}"
    echo "  Knowledge Base:       ${MCP_KNOWLEDGE_BASE}"
    echo "  Database:             ${MCP_DATABASE}"
    echo ""
    echo "Cache:"
    echo "  Transformers:         ${TRANSFORMERS_CACHE}"
    echo "  NPM:                  ${NPM_CONFIG_CACHE}"
    echo "  pip:                  ${PIP_CACHE_DIR}"
    echo ""
    echo "Node.js:"
    echo "  NODE_ENV:             ${NODE_ENV}"
    echo "  NODE_PATH:            ${NODE_PATH}"
    echo ""
    
    # Check service status (try both possible service names)
    if systemctl is-active --quiet chromadb-spack.service 2>/dev/null || systemctl is-active --quiet chromadb-docker.service 2>/dev/null || systemctl is-active --quiet chromadb-persistent.service 2>/dev/null; then
        echo "✅ ChromaDB 1.1.1 service is running"
        # Quick version check
        HEARTBEAT=$(curl -s http://127.0.0.1:8080/api/v1/heartbeat 2>/dev/null)
        if [ -n "${HEARTBEAT}" ]; then
            echo "   💓 Heartbeat: ${HEARTBEAT}"
        fi
    else
        echo "❌ ChromaDB service is NOT running"
    fi
    
    if [ -d "${MCP_ROOT}/node_modules" ]; then
        echo "✅ MCP Node.js dependencies installed"
        # Check chromadb package version
        if [ -f "${MCP_ROOT}/package.json" ]; then
            CHROMA_VER=$(cat "${MCP_ROOT}/package.json" | grep '"chromadb"' | cut -d'"' -f4 || echo 'unknown')
            echo "   📦 chromadb package: ${CHROMA_VER}"
        fi
    else
        echo "⚠️  MCP Node.js dependencies not yet installed"
    fi
    
    echo "╚════════════════════════════════════════════════════════════╝"
fi
