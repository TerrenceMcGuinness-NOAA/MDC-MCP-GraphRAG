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
export EIB_REPO="${PERSISTENT_ROOT}/eib-mcp-rag-server"
export SETUP="${EIB_REPO}/SETUP"
export MCP_ROOT="${EIB_REPO}/mcp_server_node"
export GW_REPO="${EIB_REPO}/supported_repos/global-workflow_develop"
export GITHUB_TOKEN="${GITHUB_TOKEN:-}"

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
export MCP_WORKFLOW_ROOT="${GW_REPO}"
export MCP_SOURCE="${EIB_REPO}/mcp_server_node"
export MCP_KNOWLEDGE_BASE="${MCP_ROOT}/knowledge-base"
export MCP_DATABASE="${MCP_ROOT}/database"
export MCP_LOGS="${MCP_ROOT}/logs"

# Cache directories
export CACHE_ROOT="${PERSISTENT_ROOT}/cache"
export HF_HOME="${CACHE_ROOT}/huggingface"                # Hugging Face cache (transformers v5+)
export TRANSFORMERS_CACHE="${HF_HOME}"                    # Deprecated in transformers v5, use HF_HOME
export NPM_CONFIG_CACHE="${CACHE_ROOT}/npm"
export PIP_CACHE_DIR="${CACHE_ROOT}/pip"

# Node.js configuration
export NODE_ENV=production
export NODE_PATH="${MCP_ROOT}/node_modules"

# Module system initialization (Rocky 9 Architecture)
# Priority: System Lmod (dnf) > /apps Lmod (mount) > Environment Modules
if ! command -v module >/dev/null 2>&1; then
    # No module system initialized - set one up
    if [ -f /usr/share/lmod/lmod/init/bash ]; then
        # Use system Lmod from dnf package
        set +u 2>/dev/null || true
        source /usr/share/lmod/lmod/init/bash
        set -u 2>/dev/null || true
        module use /apps/modules/modulefiles &>/dev/null
    elif [ -f /apps/lmod/lmod/init/bash ]; then
        # Use Lmod from /apps mount (external HPC environment)
        set +u 2>/dev/null || true
        source /apps/lmod/lmod/init/bash
        set -u 2>/dev/null || true
        module use /apps/modules/modulefiles &>/dev/null
    elif [ -f /usr/share/Modules/init/bash ]; then
        # Fallback to Environment Modules (can't use Spack Lmod modules)
        source /usr/share/Modules/init/bash
        module use /apps/modules/modulefiles &>/dev/null
    fi
fi

# Spack package manager (for spack command)
if [ -f /mcp_rag_eib/spack/share/spack/setup-env.sh ]; then
    source /mcp_rag_eib/spack/share/spack/setup-env.sh
fi

# Python configuration - only load if not already loaded AND Spack is provisioned
# Guard: Check that Spack gcc modules exist before attempting to load
SPACK_GCC_MODULES="/mcp_rag_eib/spack/share/spack/lmod/linux-rocky9-x86_64/gcc/11.5.0"

if command -v module >/dev/null 2>&1 && ! module list 2>&1 | grep -q python; then
    # Only attempt Spack module loading if provisioning is complete
    if [ -d "${SPACK_GCC_MODULES}" ]; then
        # Load gcc to expose compiler-dependent modules (py-* packages from spack)
        # Then load all ChromaDB and Neo4j dependencies from spack
        if command -v ml >/dev/null 2>&1; then
            ml gcc/11.5.0 &>/dev/null || true
            ml python/3.11 py-pip &>/dev/null || true
            # Neo4j driver
            ml py-neo4j &>/dev/null || true
            # ChromaDB dependencies (chromadb itself installed via pip --user)
            ml py-pydantic py-idna py-httpx py-requests py-certifi py-anyio py-sniffio &>/dev/null || true
            # Sentence-transformers dependencies
            ml py-pillow py-scipy py-numpy py-tokenizers py-tqdm py-pyyaml &>/dev/null || true
            # TODO: py-beautifulsoup4 and py-lxml have gcc-runtime hash conflicts with py-pydantic
            # The spack builds use gcc-runtime/11.5.0-qa4ruhy but pydantic uses gcc-runtime/11.5.0-kfpu42e
            # Loading py-lxml causes Lmod to swap gcc-runtime versions, breaking pydantic imports.
            # WORKAROUND: Install via pip instead (see PIP-ONLY section below)
            # FUTURE FIX: Rebuild py-lxml and py-beautifulsoup4 with same gcc-runtime as py-pydantic
            # ml py-beautifulsoup4 py-lxml &>/dev/null || true  # DISABLED - conflicts
        else
            module load gcc/11.5.0 &>/dev/null || true
            module load python/3.11 py-pip &>/dev/null || true
            # Neo4j driver
            module load py-neo4j &>/dev/null || true
            # Fortran parser for Phase 10 call tree ingestion
            module load py-fparser &>/dev/null || true
            # ChromaDB dependencies (chromadb itself installed via pip --user)
            module load py-pydantic py-idna py-httpx py-requests py-certifi py-anyio py-sniffio &>/dev/null || true
            # Sentence-transformers dependencies
            module load py-pillow py-scipy py-numpy py-tokenizers py-tqdm py-pyyaml &>/dev/null || true
            # NOTE: py-beautifulsoup4 and py-lxml have gcc-runtime conflicts with py-pydantic
            # They are installed via pip --user instead (see PIP-ONLY section below)
            # module load py-beautifulsoup4 py-lxml &>/dev/null || true  # DISABLED - conflicts with pydantic
        fi
    fi
    # Note: If Spack not provisioned, Python packages will need to be sourced from system or pip
fi

################################################################################
# PIP-ONLY DEPENDENCIES (Not available in Spack or have conflicts)
# These packages MUST be installed via: python3 -m pip install --user <package>
#
# Required pip --user packages:
#   - chromadb             : Vector database client (connects to Docker container)
#   - sentence-transformers: Embedding model library (requires torch)
#   - lxml                 : XML/HTML parser (gcc-runtime conflict with py-pydantic in spack)
#   - beautifulsoup4       : HTML parsing library (depends on lxml)
#
# Installation command:
#   python3 -m pip install --user chromadb sentence-transformers lxml beautifulsoup4
#
# Why pip --user?
#   - chromadb: Not packaged in Spack, client for Docker-based ChromaDB server
#   - sentence-transformers: Not in Spack, complex ML library with torch dependency
#   - lxml/beautifulsoup4: Spack modules have gcc-runtime hash mismatch with py-pydantic
#                          causing module conflicts that break chromadb imports
#
# All other dependencies should be loaded via Spack modules above.
################################################################################

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
    echo "  EIB_REPO:             ${EIB_REPO}"
    echo "  MCP_ROOT:             ${MCP_ROOT}"
    echo "  GW_REPO:              ${GW_REPO}"
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
    echo "  HF_HOME:              ${HF_HOME}"
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
