#!/bin/bash

################################################################################
# MCP RAG Persistent Infrastructure Provisioning Script
# Version: 3.6.0
# 
# Purpose: Complete infrastructure provisioning for MCP/RAG development
#          on dedicated /mcp_rag_eib mount (25GB) with co-located architecture
# 
# Changelog: v3.6.0 - Removed legacy deployment/copy logic (co-located architecture)
#                   - Git submodules for analysis targets (global-workflow, nws-hpc-standards)
#                   - VS Code config in eib-mcp-rag-server root (not submodule)
#                   - Source = Runtime (no deployment/sync needed)
#            v3.5.0 - Migrated ChromaDB to Docker (resolves SQLite/venv issues)
#            v3.4.1 - Updated ChromaDB health checks to use v2 API endpoints
#            v3.4.0 - Migrated to Spack module system (no venv)
#            v3.3.1 - Added ONNX Runtime validation test (pre-built binaries)
#            v3.3.0 - Added automated deployment with manifest system
#            v3.2.0 - Added Neo4j graph database + LangFlow via Docker Compose
#            v3.1.0 - Upgraded ChromaDB 0.4.15 → 1.1.1 with dependencies
#
# Co-located Architecture (v3.6.0+):
#   - Spack: /mcp_rag_eib/spack (package manager with Lmod modules)
#   - ChromaDB: Docker container (chromadb/chroma:latest, port 8080, v2 API)
#   - MCP Repo: /mcp_rag_eib/eib-mcp-rag-server (tracked git repository)
#     ├── mcp_server_node/        (MCP servers - source = runtime, no deployment)
#     ├── SETUP/                  (provisioning scripts)
#     └── supported_repos/        (git submodules for analysis targets)
#         ├── global-workflow/    (submodule: UFS Global Workflow - analysis only)
#         └── nws-hpc-standards/  (submodule: EE2 compliance docs - analysis only)
#   - Data/Cache: /mcp_rag_eib/data, /mcp_rag_eib/cache
#
# Usage:
#   cd /mcp_rag_eib/eib-mcp-rag-server/SETUP
#   sudo ./provision_mcp_rag_persistent.sh           # Normal run (preserves caches)
#   sudo ./provision_mcp_rag_persistent.sh --fresh   # Complete fresh start
#
# Author: NOAA EMC Global Workflow Team
# Contributors: Terry McGuinness, Claude Sonnet 4.5
# Date: 2025-11-24
################################################################################

set -euo pipefail

# Parse command line arguments
FRESH_START=false
if [[ "${1:-}" == "--fresh" ]]; then
    FRESH_START=true
    echo "🔥 FRESH START MODE: Will clean all caches and rebuild from scratch"
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Logging functions
log_section() {
    echo -e "\n${CYAN}═══════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════${NC}\n"
}

log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Configuration - Must source environment file first
MCP_ENV_FILE="${PWD}/mcp-env.sh"
if [ ! -f "${MCP_ENV_FILE}" ]; then
    log_error "Environment configuration not found: ${MCP_ENV_FILE}"
    log_error "Current directory: ${PWD}"
    log_error "Expected: /mcp_rag_eib/eib-mcp-rag-server/SETUP/mcp-env.sh"
    exit 1
fi

log_info "Sourcing environment configuration..."
# Temporarily disable unbound variable check for Lmod initialization
set +u
source "${MCP_ENV_FILE}"
set -u

# Verify critical variables are set
if [ -z "${PERSISTENT_ROOT}" ] || [ -z "${CHROMADB_ROOT}" ] || [ -z "${MCP_ROOT}" ]; then
    log_error "Critical environment variables not set after sourcing ${MCP_ENV_FILE}"
    log_info "PERSISTENT_ROOT=${PERSISTENT_ROOT}"
    log_info "CHROMADB_ROOT=${CHROMADB_ROOT}"
    log_info "MCP_ROOT=${MCP_ROOT}"
    exit 1
fi

USER="Terry.McGuinness"

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    log_error "Please run as root or with sudo"
    exit 1
fi

# Verify persistent mount
if ! mountpoint -q "${PERSISTENT_ROOT}"; then
    log_error "${PERSISTENT_ROOT} is not mounted!"
    log_info "Please ensure the 25GB persistent volume is mounted"
    exit 1
fi

log_section "MCP RAG Persistent Infrastructure Setup v3.6.0"
log_info "Persistent Root: ${PERSISTENT_ROOT}"
log_info "Spack Root: ${SPACK_ROOT}"
log_info "Available Space: $(df -h ${PERSISTENT_ROOT} | tail -1 | awk '{print $4}')"
log_info "Fresh Start Mode: ${FRESH_START}"

################################################################################
# STEP 0: Pre-Flight Cleanup (Fresh Start Mode)
################################################################################
if [ "${FRESH_START}" = true ]; then
    log_section "STEP 0: Pre-Flight Cleanup (FRESH START)"
    
    log_warning "This will delete all caches, old installations, and ChromaDB data!"
    log_info "Sleeping 5 seconds... (Ctrl-C to cancel)"
    sleep 5
    
    log_info "Stopping any running services..."
    systemctl stop chromadb-spack.service 2>/dev/null || true
    systemctl stop chromadb-persistent.service 2>/dev/null || true
    systemctl stop mcp-server-persistent.service 2>/dev/null || true
    
    log_info "Cleaning old ChromaDB venv (if exists)..."
    rm -rf "${PERSISTENT_ROOT}/etc/chromadb"
    
    log_info "Cleaning old MCP node_modules..."
    rm -rf "${MCP_ROOT}/node_modules"
    rm -rf "${MCP_ROOT}/package-lock.json"
    
    log_info "Cleaning ChromaDB data..."
    rm -rf "${CHROMADB_DATA}"/*
    
    log_info "Cleaning all caches..."
    rm -rf "${CACHE_ROOT}"/*
    
    log_info "Resetting DNF module states..."
    dnf module reset nodejs -y 2>/dev/null || true
    
    log_success "Pre-flight cleanup complete - starting fresh!"
else
    log_section "STEP 0: Pre-Flight Check (Incremental Mode)"
    
    log_info "Stopping services if running..."
    systemctl stop chromadb-spack.service 2>/dev/null || true
    systemctl stop chromadb-persistent.service 2>/dev/null || true
    systemctl stop mcp-server-persistent.service 2>/dev/null || true
    
    log_info "Cleaning only old installations (preserving caches)..."
    rm -rf "${PERSISTENT_ROOT}/etc/chromadb"
    rm -rf "${MCP_ROOT}/node_modules"
    rm -rf "${MCP_ROOT}/package-lock.json"
    
    log_success "Pre-flight check complete - caches preserved"
fi

################################################################################
# STEP 1: Create Directory Structure
################################################################################
log_section "STEP 1: Creating Directory Structure"

log_info "Creating persistent directory structure..."
mkdir -p "${CHROMADB_DATA}"
mkdir -p "${MCP_ROOT}/src"
mkdir -p "${MCP_ROOT}/database"
mkdir -p "${MCP_ROOT}/knowledge-base"
mkdir -p "${MCP_ROOT}/logs"
mkdir -p "${CACHE_ROOT}/transformers"
mkdir -p "${CACHE_ROOT}/npm"
mkdir -p "${CACHE_ROOT}/pip"

# Neo4j graph database directories
log_info "Creating Neo4j persistent directories..."
mkdir -p "${PERSISTENT_ROOT}/data/neo4j/data"
mkdir -p "${PERSISTENT_ROOT}/data/neo4j/logs"
mkdir -p "${PERSISTENT_ROOT}/data/neo4j/import"
mkdir -p "${PERSISTENT_ROOT}/data/neo4j/plugins"

log_success "Directory structure created"

################################################################################
# STEP 2: System Dependencies
################################################################################
log_section "STEP 2: Installing System Dependencies"

log_info "Checking module system availability..."
if [ -f /usr/share/Modules/init/bash ]; then
    source /usr/share/Modules/init/bash
    module use /apps/modules/modulefiles 2>/dev/null || true
    
    log_info "Available modules:"
    # Suppress errors from Spack hierarchical modules (they need gcc loaded first)
    module avail 2>&1 | grep -v "Magic cookie" | grep -v "Module ERROR" | grep -E "(python|node|git|gcc|hpc)" || log_info "  (standard modules only)"
    
    # Check if Python 3.11 is available as module
    if module avail python/3.11 2>&1 | grep -q "python/3.11"; then
        log_success "Python 3.11 module available"
        module load python/3.11
        PYTHON_CMD="python3.11"
    else
        log_warning "Python 3.11 module not found in /apps/modules"
        log_info "Will check system Python installations..."
    fi
else
    log_warning "Module system not available"
fi

# Verify Python availability
if ! command -v python3.11 &> /dev/null; then
    log_warning "Python 3.11 not found - attempting DNF install..."
    dnf install -y python3.11 python3.11-pip python3.11-devel
fi

# Verify Python is working
log_info "Python verification: $(python3.11 --version 2>&1 || echo 'Python 3.11 not available')"

log_info "Updating system packages (this may take a few minutes)..."
timeout 300 dnf update -y || log_warning "DNF update timed out or failed (non-fatal)"

log_info "Installing system dependencies..."
log_info "  - Development tools (gcc, make, git)"
log_info "  - Docker components"
log_info "  - Node.js (will be installed via module system)"
log_info "  - Utilities (curl, wget, jq)"

timeout 600 dnf install -y \
    gcc-c++ \
    make \
    curl \
    wget \
    git \
    jq \
    docker-ce \
    docker-ce-cli \
    containerd.io \
    docker-compose-plugin \
    || log_warning "Some DNF packages failed (may already be installed)"

log_success "System dependencies processed"

################################################################################
# STEP 3: Docker Setup
################################################################################
log_section "STEP 3: Docker Setup"

log_info "Configuring Docker service..."
systemctl start docker
systemctl enable docker

log_info "Adding ${USER} to docker group..."
usermod -aG docker ${USER}

log_info "Testing Docker installation..."
if docker run --rm hello-world > /dev/null 2>&1; then
    log_success "Docker verified"
else
    log_error "Docker installation failed"
    exit 1
fi

log_warning "Note: ${USER} must log out/in for docker group to take effect"

################################################################################
# STEP 4: Node.js Environment
################################################################################
log_section "STEP 4: Node.js Environment Setup"

log_info "Checking for Node.js via module system first..."
MODULE_NODEJS_AVAILABLE=false
if command -v module &> /dev/null; then
    if module avail nodejs 2>&1 | grep -q "nodejs"; then
        log_info "Node.js module found in module system"
        module load nodejs 2>/dev/null && MODULE_NODEJS_AVAILABLE=true
    fi
fi

if [ "$MODULE_NODEJS_AVAILABLE" = false ]; then
    log_info "Installing Node.js 20 via DNF module system..."
    
    # Reset any existing nodejs module state
    dnf module reset nodejs -y || true
    
    log_info "Enabling Node.js 20 module..."
    timeout 120 dnf module enable nodejs:20 -y || {
        log_warning "DNF module enable timed out - trying direct install"
    }
    
    log_info "Installing Node.js 20..."
    timeout 300 dnf module install nodejs:20 -y || {
        log_error "Node.js installation failed or timed out"
        log_info "Attempting fallback: direct nodejs package install"
        dnf install -y nodejs npm || exit 1
    }
fi

# Verify Node.js installation
if command -v node &> /dev/null; then
    log_success "Node.js $(node --version) installed"
    log_success "npm $(npm --version) installed"
    
    log_info "Updating npm to latest..."
    npm install -g npm@latest || log_warning "npm update failed (non-fatal)"
    hash -r
else
    log_error "Node.js installation verification failed"
    exit 1
fi

log_success "Node.js environment ready"

################################################################################
# STEP 5: Python Environment
################################################################################
log_section "STEP 5: Python Environment Setup"

log_info "Loading Python 3.11 module..."
if [ -f /usr/share/Modules/init/bash ]; then
    source /usr/share/Modules/init/bash
    module use /apps/modules/modulefiles
    
    if module avail python/3.11 2>&1 | grep -q "python/3.11"; then
        module load python/3.11
        log_success "Python 3.11 module loaded"
    else
        log_warning "Python 3.11 module not found - using system python3.11"
    fi
fi

# Verify Python
if ! command -v python3.11 &> /dev/null; then
    log_error "Python 3.11 not available after module load attempt"
    exit 1
fi

log_info "Python: $(python3.11 --version)"
log_info "pip: $(python3.11 -m pip --version 2>&1 | head -1)"

log_info "Upgrading pip..."
python3.11 -m pip install --upgrade pip --cache-dir "${CACHE_ROOT}/pip"

log_info "Installing minimal Python packages for ChromaDB..."
log_info "  (Heavy packages like torch, transformers will be in venv only)"
python3.11 -m pip install --cache-dir "${CACHE_ROOT}/pip" \
    'setuptools>=65.0.0' \
    'wheel>=0.38.0'

log_success "Python environment configured"

################################################################################
# STEP 6: Spack Module System Setup
################################################################################
log_section "STEP 6: Spack Module System Setup"

log_info "Checking Spack installation at ${SPACK_ROOT}..."

if [ ! -f "${SPACK_ROOT}/bin/spack" ]; then
    log_error "Spack not found at ${SPACK_ROOT}"
    log_error "Please install Spack first or run from existing Spack-enabled system"
    exit 1
fi

log_info "Initializing Spack environment..."
source "${SPACK_ROOT}/share/spack/setup-env.sh"

log_info "Verifying Lmod module system..."
if [ ! -f /usr/share/lmod/lmod/init/bash ]; then
    log_error "Lmod not found - installing..."
    dnf install -y lmod
fi

log_info "Checking for Spack-generated Lmod modules..."
MODULE_DIR="${SPACK_ROOT}/share/spack/lmod/linux-rocky9-x86_64/Core"
if [ ! -d "${MODULE_DIR}" ]; then
    log_warning "Spack modules not generated - running spack module lmod refresh..."
    spack module lmod refresh --delete-tree -y
fi

log_info "Available Spack modules:"
source /usr/share/lmod/lmod/init/bash
module use "${MODULE_DIR}"
module avail python 2>&1 | grep "python/" || log_warning "Python modules not found"

log_success "Spack environment initialized"

################################################################################
# STEP 7: ChromaDB Docker Setup
################################################################################
log_section "STEP 7: ChromaDB Docker Setup (Port ${CHROMADB_PORT})"

log_info "Pulling ChromaDB Docker image..."
if docker pull chromadb/chroma:latest; then
    log_success "ChromaDB Docker image pulled successfully"
else
    log_error "Failed to pull ChromaDB Docker image"
    exit 1
fi

log_info "Creating ChromaDB data directory: ${CHROMADB_DATA}"
mkdir -p "${CHROMADB_DATA}"
chown -R ${USER}:${USER} "${CHROMADB_DATA}"

log_info "Verifying Docker daemon is running..."
if ! systemctl is-active --quiet docker; then
    log_error "Docker service is not running"
    exit 1
fi

log_success "ChromaDB Docker image ready"

################################################################################
# STEP 8: ChromaDB Docker Systemd Service
################################################################################
log_section "STEP 8: ChromaDB Docker Systemd Service Configuration"

log_info "Creating ChromaDB Docker service for port ${CHROMADB_PORT}..."

cat > /etc/systemd/system/chromadb-docker.service << 'EOF'
[Unit]
Description=ChromaDB Vector Database Server (Docker)
After=docker.service
Requires=docker.service
Documentation=https://docs.trychroma.com/

[Service]
Type=simple
User=root
Group=root

# Stop and remove any existing container
ExecStartPre=-/usr/bin/docker stop chromadb
ExecStartPre=-/usr/bin/docker rm chromadb

# Start ChromaDB in Docker
ExecStart=/usr/bin/docker run --name chromadb \
    --rm \
    -p 8080:8000 \
    -v /mcp_rag_eib/data/chromadb:/chroma/chroma \
    -e IS_PERSISTENT=TRUE \
    -e PERSIST_DIRECTORY=/chroma/chroma \
    -e ANONYMIZED_TELEMETRY=FALSE \
    chromadb/chroma:latest

# Stop container on service stop
ExecStop=/usr/bin/docker stop chromadb

# Restart policy
Restart=always
RestartSec=10
StartLimitInterval=200
StartLimitBurst=5

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=chromadb-docker

[Install]
WantedBy=multi-user.target
EOF

# Disable old service if it exists
if systemctl is-enabled chromadb-spack.service &>/dev/null; then
    log_info "Disabling old chromadb-spack.service..."
    systemctl disable chromadb-spack.service || true
    systemctl stop chromadb-spack.service || true
fi

systemctl daemon-reload
systemctl enable chromadb-docker.service
systemctl start chromadb-docker.service

log_info "Waiting for ChromaDB Docker container to start (can take up to 30 seconds)..."
RETRY_COUNT=0
MAX_RETRIES=10  # 10 * 3 seconds = 30 seconds max wait
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -s "http://127.0.0.1:${CHROMADB_PORT}/api/v2/heartbeat" > /dev/null 2>&1; then
        log_success "ChromaDB running on port ${CHROMADB_PORT} (API v2, Docker)"
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
        echo -n "."
        sleep 3
    fi
done
echo ""

# Final check
if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    log_error "ChromaDB failed to start after 30 seconds"
    log_info "Check logs: journalctl -u chromadb-docker.service -n 50"
    log_info "Check container: docker logs chromadb"
    log_info "Service status: systemctl status chromadb-docker.service"
    exit 1
fi

################################################################################
# STEP 9: MCP Server Node.js Setup
################################################################################
log_section "STEP 9: MCP Server Node.js Environment"

log_info "Setting up MCP server in ${MCP_ROOT}..."
log_info "  Co-located architecture: Source and runtime in same location"

cd "${MCP_ROOT}"

# In co-located architecture, MCP_SOURCE and MCP_ROOT are the same
# No copying needed - just verify the repository is in place
log_info "MCP Server Location: ${MCP_ROOT}"

if [ ! -d "${MCP_ROOT}" ]; then
    log_error "MCP_ROOT not found at ${MCP_ROOT}"
    log_error "Expected: eib-mcp-rag-server should be cloned to ${PERSISTENT_ROOT}/eib-mcp-rag-server"
    exit 1
fi

# Verify package.json exists
if [ ! -f "${MCP_ROOT}/package.json" ]; then
    log_error "package.json not found in ${MCP_ROOT}"
    log_error "MCP server repository may not be properly cloned"
    exit 1
fi

log_success "MCP server directory verified (co-located runtime/source)"

# Install Node.js dependencies
log_info "Installing Node.js dependencies (this may take 5-10 minutes)..."
log_info "  Cache location: ${CACHE_ROOT}/npm"
log_info "  ChromaDB Node.js client will be chromadb@3.0.17 (for ChromaDB 1.1.1)"

# First ensure we have the latest package.json with chromadb@^3.0.17
npm install --cache "${CACHE_ROOT}/npm" --loglevel=info

# Explicitly install critical MCP dependencies
log_info "Ensuring critical MCP dependencies..."
npm install --cache "${CACHE_ROOT}/npm" \
    @modelcontextprotocol/sdk@latest \
    chromadb@^3.1.4 \
    @xenova/transformers@latest \
    @octokit/rest@latest \
    glob@latest \
    neo4j-driver@latest

log_info "Installed packages: $(find node_modules -maxdepth 1 -type d | wc -l) packages"
log_info "ChromaDB client: $(npm list chromadb 2>/dev/null | grep chromadb || echo 'Check manually')"

log_success "Node.js dependencies installed"

################################################################################
# STEP 10: Environment Configuration
################################################################################
log_section "STEP 10: Environment Configuration"

log_info "Using centralized environment configuration from ${SETUP}/mcp-env.sh"

# Verify canonical environment file exists
if [ ! -f "${SETUP}/mcp-env.sh" ]; then
    log_error "Canonical mcp-env.sh not found at ${SETUP}/mcp-env.sh"
    exit 1
fi

# Add to user's bash profile (if not already there)
if ! grep -q "mcp-env.sh" /home/${USER}/.bash_profile 2>/dev/null; then
    echo "" >> /home/${USER}/.bash_profile
    echo "# MCP RAG Environment (Auto-configured $(date +%Y-%m-%d))" >> /home/${USER}/.bash_profile
    echo "source ${SETUP}/mcp-env.sh" >> /home/${USER}/.bash_profile
    log_success "Environment added to .bash_profile"
else
    log_info "Environment already configured in .bash_profile"
fi

log_success "Environment configuration references canonical ${SETUP}/mcp-env.sh"

################################################################################
# STEP 11: Git Submodules Verification
################################################################################
log_section "STEP 11: Git Submodules Verification"

log_info "Verifying git submodules in eib-mcp-rag-server repository..."

# eib-mcp-rag-server uses git submodules for analysis target repositories
# supported_repos/global-workflow - Global Workflow operational code (analysis target)
# supported_repos/nws-hpc-standards - EE2 compliance standards (analysis target)

if [ ! -d "${GIT_REPO}/.git" ]; then
    log_warning "Git submodule not initialized: global-workflow"
    log_info "Initializing git submodules..."
    su - ${USER} -c "cd ${PERSISTENT_ROOT}/eib-mcp-rag-server && git submodule update --init --recursive" || {
        log_error "Failed to initialize git submodules"
        log_info "Ensure eib-mcp-rag-server is a proper git repository with submodules configured"
        exit 1
    }
    log_success "Git submodules initialized"
else
    log_info "Git submodule exists: ${GIT_REPO}"
    log_info "Current branch: $(cd ${GIT_REPO} && git branch --show-current 2>/dev/null || echo 'detached HEAD')"
fi

# Set ownership for submodule
chown -R ${USER}:${USER} "${PERSISTENT_ROOT}/eib-mcp-rag-server/supported_repos" 2>/dev/null || true

log_success "Git submodules verified"
log_info "Analysis target: ${GIT_REPO}"

################################################################################
# STEP 12: Claude CLI Installation
################################################################################
log_section "STEP 12: Claude CLI Installation"

log_info "Installing Claude CLI globally..."
npm install -g @anthropic-ai/claude-code

log_info "Claude CLI version: $(claude --version 2>/dev/null || echo 'Not in PATH yet')"

log_success "Claude CLI installed"

################################################################################
# STEP 12.6: Validate Pre-built ONNX Runtime
################################################################################
log_section "STEP 12.6: Validate Pre-built ONNX Runtime"

log_info "Testing pre-built ONNX Runtime on this hardware..."

cat > "${MCP_ROOT}/test-onnx-validation.js" << 'EONXTEST'
// Quick validation test for pre-built ONNX Runtime from npm packages
import { pipeline } from '@xenova/transformers';

console.log('🔍 Testing pre-built ONNX Runtime compatibility...');
console.log('   CPU Architecture:', process.arch);
console.log('   Node.js Version:', process.version);

try {
    console.log('\n1. Loading embedding pipeline...');
    const embedder = await pipeline('feature-extraction', 'Xenova/all-MiniLM-L6-v2');
    
    console.log('2. Generating test embedding...');
    const output = await embedder('Hello world', { pooling: 'mean', normalize: true });
    
    console.log('3. Success! Embedding shape:', output.dims);
    console.log('4. Sample values:', Array.from(output.data.slice(0, 3)));
    console.log('\n✅ Pre-built ONNX Runtime validated successfully!');
    console.log('   No custom build required - using npm packages.');
    process.exit(0);
} catch (error) {
    console.error('\n❌ Pre-built ONNX Runtime validation failed:');
    console.error('   Error:', error.message);
    console.error('\n   This may indicate hardware incompatibility.');
    console.error('   Consider building ONNX Runtime from source for this platform.');
    process.exit(1);
}
EONXTEST

chown ${USER}:${USER} "${MCP_ROOT}/test-onnx-validation.js"

# Run validation as user
log_info "Running ONNX validation test..."
if su - ${USER} -c "cd ${MCP_ROOT} && node test-onnx-validation.js" 2>&1 | tee /tmp/onnx_validation.log; then
    log_success "ONNX Runtime validation passed!"
    log_info "Using pre-built binaries from @xenova/transformers"
    
    # Clean up test file
    rm -f "${MCP_ROOT}/test-onnx-validation.js"
else
    log_error "ONNX Runtime validation failed"
    log_warning "See /tmp/onnx_validation.log for details"
    log_warning "Pre-built binaries may be incompatible with this hardware"
    log_info "Consider building ONNX Runtime from source if RAG functionality fails"
    
    # Don't fail provisioning - just warn
    sleep 3
fi

################################################################################
# STEP 13: MCP Server Systemd Service
################################################################################
log_section "STEP 13: MCP Server Systemd Service"

log_info "Creating MCP server service..."

cat > /etc/systemd/system/mcp-server-persistent.service << EOF
[Unit]
Description=MCP Server with RAG (Persistent Storage)
After=network.target chromadb-persistent.service
Requires=chromadb-persistent.service

[Service]
Type=simple
User=${USER}
Group=${USER}
WorkingDirectory=${MCP_ROOT}
Environment=NODE_ENV=production
Environment=MCP_ROOT=${MCP_ROOT}
Environment=MCP_WORKFLOW_ROOT=${GIT_REPO}
Environment=MCP_KNOWLEDGE_BASE=${MCP_ROOT}/knowledge-base
Environment=MCP_DATABASE=${MCP_ROOT}/database
Environment=CHROMADB_URL=http://127.0.0.1:${CHROMADB_PORT}
Environment=TRANSFORMERS_CACHE=${CACHE_ROOT}/transformers
Environment=NPM_CONFIG_CACHE=${CACHE_ROOT}/npm
Environment=NODE_PATH=${MCP_ROOT}/node_modules
Environment=PATH=/usr/local/bin:/usr/bin:/bin:${MCP_ROOT}/node_modules/.bin
ExecStart=/usr/bin/node ${MCP_ROOT}/src/UnifiedMCPServer.js full
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable mcp-server-persistent.service

log_info "MCP server service configured (not started yet)"
log_info "Start with: systemctl start mcp-server-persistent.service"

log_success "MCP server service ready"

################################################################################
# STEP 14: VS Code Workspace Configuration
################################################################################
log_section "STEP 14: VS Code Workspace Configuration"

log_info "Creating VS Code MCP configuration in eib-mcp-rag-server repository..."

# VS Code config goes in the eib-mcp-rag-server repo root (not in the submodule)
VSCODE_CONFIG_DIR="${PERSISTENT_ROOT}/eib-mcp-rag-server/.vscode"
mkdir -p "${VSCODE_CONFIG_DIR}"

cat > "${VSCODE_CONFIG_DIR}/mcp.json" << EOF
{
  "servers": {
    "global-workflow-full": {
      "command": "node",
      "args": [
        "${MCP_ROOT}/src/UnifiedMCPServer.js",
        "full"
      ],
      "type": "stdio",
      "env": {
        "MCP_WORKFLOW_ROOT": "${GIT_REPO}",
        "CHROMA_SERVER_URL": "http://localhost:${CHROMADB_PORT}"
      }
    },
    "global-workflow-rag": {
      "command": "node",
      "args": [
        "${MCP_ROOT}/src/UnifiedMCPServer.js",
        "rag"
      ],
      "type": "stdio",
      "env": {
        "MCP_WORKFLOW_ROOT": "${GIT_REPO}",
        "CHROMA_SERVER_URL": "http://localhost:${CHROMADB_PORT}"
      }
    },
    "global-workflow-core": {
      "command": "node",
      "args": [
        "${MCP_ROOT}/src/UnifiedMCPServer.js",
        "core"
      ],
      "type": "stdio",
      "env": {
        "MCP_WORKFLOW_ROOT": "${GIT_REPO}"
      }
    }
  }
}
EOF

chown ${USER}:${USER} "${VSCODE_CONFIG_DIR}/mcp.json"

log_success "VS Code MCP configuration created at ${VSCODE_CONFIG_DIR}/mcp.json"
log_info "Open ${PERSISTENT_ROOT}/eib-mcp-rag-server in VS Code to use MCP tools"

################################################################################
# STEP 15: Docker Compose Services (Neo4j + LangFlow)
################################################################################
log_section "STEP 15: Docker Compose Services (Neo4j + LangFlow)"

# Use SETUP variable from mcp-env.sh (already sourced at top of script)
SETUP_DIR="${SETUP}"
DOCKER_COMPOSE_FILE="${SETUP_DIR}/docker-compose.yml"

if [ ! -f "${DOCKER_COMPOSE_FILE}" ]; then
    log_error "docker-compose.yml not found at ${DOCKER_COMPOSE_FILE}"
    exit 1
fi

log_info "Changing to SETUP directory: ${SETUP_DIR}"
cd "${SETUP_DIR}"

# Set PERSISTENT_ROOT for docker-compose volume mounts
export PERSISTENT_ROOT="${PERSISTENT_ROOT}"

log_info "Stopping any existing containers..."
docker compose down 2>/dev/null || true

log_info "Building and starting Neo4j graph database..."
docker compose up -d neo4j

log_info "Waiting for Neo4j to become healthy (this may take 60+ seconds)..."
WAIT_COUNT=0
MAX_WAIT=20
while [ $WAIT_COUNT -lt $MAX_WAIT ]; do
    if docker compose ps neo4j | grep -q "healthy"; then
        log_success "Neo4j is healthy and ready"
        break
    fi
    echo -n "."
    sleep 3
    WAIT_COUNT=$((WAIT_COUNT + 1))
done
echo ""

if [ $WAIT_COUNT -eq $MAX_WAIT ]; then
    log_warning "Neo4j health check timed out - check logs: docker compose logs neo4j"
else
    log_info "Neo4j Browser UI: http://localhost:7474"
    log_info "Neo4j Bolt: bolt://localhost:7687"
    log_info "Neo4j credentials: neo4j / gfsworkflow2025"
fi

log_info "Building and starting LangFlow RAG visualizer..."
docker compose up -d langflow

log_info "Waiting for LangFlow to become healthy..."
WAIT_COUNT=0
while [ $WAIT_COUNT -lt $MAX_WAIT ]; do
    if docker compose ps langflow | grep -q "healthy"; then
        log_success "LangFlow is healthy and ready"
        break
    fi
    echo -n "."
    sleep 3
    WAIT_COUNT=$((WAIT_COUNT + 1))
done
echo ""

if [ $WAIT_COUNT -eq $MAX_WAIT ]; then
    log_warning "LangFlow health check timed out - check logs: docker compose logs langflow"
else
    log_info "LangFlow UI: http://localhost:7860"
fi

log_info "Docker Compose services status:"
docker compose ps

log_success "Docker Compose services started"

################################################################################
# STEP 15.5: Remote Access (VNC/noVNC) Setup
################################################################################
log_section "STEP 15.5: Remote Access (VNC/noVNC) Setup"

log_info "Installing VNC and noVNC packages..."
# Use --allowerasing to handle potential conflicts with kasmvncserver
dnf install -y tigervnc-server novnc python3-websockify --allowerasing || log_warning "VNC packages installation failed"

# SSL Cert generation
CERT_PATH="/home/${USER}/novnc.pem"
if [ ! -f "${CERT_PATH}" ]; then
    log_info "Generating self-signed SSL certificate for noVNC..."
    # Use system openssl to avoid Spack library conflicts
    /usr/bin/openssl req -x509 -nodes -newkey rsa:2048 -keyout "${CERT_PATH}" -out "${CERT_PATH}" -days 365 -subj "/CN=localhost" 2>/dev/null || log_warning "Certificate generation failed"
    chown ${USER}:${USER} "${CERT_PATH}"
fi

# Websockify Service
log_info "Configuring websockify systemd service..."
cat > /etc/systemd/system/websockify.service << EOF
[Unit]
Description=Websockify for noVNC
After=network.target

[Service]
Type=simple
User=${USER}
Group=${USER}
ExecStart=/usr/bin/websockify --web=/usr/share/novnc/ --cert=${CERT_PATH} 6080 localhost:5901
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable websockify.service
systemctl start websockify.service

log_success "Remote Access (noVNC) configured on port 6080"

################################################################################
# STEP 15.6: Desktop Applications (Google Chrome)
################################################################################
log_section "STEP 15.6: Desktop Applications"

if ! command -v google-chrome &> /dev/null; then
    log_info "Installing Google Chrome..."
    wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_x86_64.rpm
    dnf install -y ./google-chrome-stable_current_x86_64.rpm || log_warning "Google Chrome installation failed"
    rm -f google-chrome-stable_current_x86_64.rpm
else
    log_info "Google Chrome is already installed"
fi

################################################################################
# STEP 16: Verification and Summary
################################################################################
log_section "STEP 16: Installation Verification"

log_info "Checking installed components..."

echo -e "\n${CYAN}System Components:${NC}"
echo "  Node.js: $(node --version)"
echo "  npm: $(npm --version)"
echo "  Python: $(python3.11 --version 2>&1 | head -1)"
echo "  Docker: $(docker --version)"

echo -e "\n${CYAN}Services Status:${NC}"
systemctl is-active chromadb-persistent.service && echo "  ✅ ChromaDB: Running" || echo "  ❌ ChromaDB: Not running"

echo -e "\n${CYAN}ChromaDB Connection:${NC}"
if curl -s "http://127.0.0.1:${CHROMADB_PORT}/api/v2/heartbeat" > /dev/null 2>&1; then
    echo "  ✅ ChromaDB accessible at http://127.0.0.1:${CHROMADB_PORT} (v2 API)"
    COLLECTIONS=$(curl -s "http://127.0.0.1:${CHROMADB_PORT}/api/v1/collections" | jq -r 'length' 2>/dev/null || echo "0")
    echo "  📊 Collections: ${COLLECTIONS}"
else
    echo "  ❌ ChromaDB not accessible"
fi

echo -e "\n${CYAN}Persistent Storage:${NC}"
df -h "${PERSISTENT_ROOT}" | tail -1 | awk '{printf "  Storage: %s used of %s (Available: %s)\n", $3, $2, $4}'

echo -e "\n${CYAN}Directory Structure:${NC}"
echo "  ${CHROMADB_ROOT} (ChromaDB installation)"
echo "  ${CHROMADB_DATA} (ChromaDB data)"
echo "  ${MCP_ROOT} (MCP server)"
echo "  ${GIT_REPO} (Git repository)"
echo "  ${CACHE_ROOT} (Cache storage)"

################################################################################
# STEP 17: Installation Verification
################################################################################
log_section "STEP 17: Installation Verification"

log_info "Checking installed components..."

echo -e "\n${CYAN}System Components:${NC}"
echo "  Node.js: $(node --version)"
echo "  npm: $(npm --version)"
echo "  Python: $(python3.11 --version 2>&1 | head -1)"
echo "  Docker: $(docker --version)"
echo "  jq: $(jq --version 2>/dev/null || echo 'not installed')"

echo -e "\n${CYAN}Services Status:${NC}"
systemctl is-active chromadb-spack.service && echo "  ✅ ChromaDB: Running" || echo "  ❌ ChromaDB: Not running"
systemctl is-active websockify.service && echo "  ✅ noVNC: Running (Port 6080)" || echo "  ❌ noVNC: Not running"
docker ps --filter "name=neo4j" --format "{{.Names}}: {{.Status}}" | grep -q "healthy" && echo "  ✅ Neo4j: Running" || echo "  ❌ Neo4j: Not running"
docker ps --filter "name=langflow" --format "{{.Names}}: {{.Status}}" | grep -q "healthy" && echo "  ✅ LangFlow: Running" || echo "  ⚠️  LangFlow: Not running"

echo -e "\n${CYAN}ChromaDB Connection:${NC}"
if curl -s "http://127.0.0.1:${CHROMADB_PORT}/api/v2/heartbeat" > /dev/null 2>&1; then
    echo "  ✅ ChromaDB accessible at http://127.0.0.1:${CHROMADB_PORT} (v2 API)"
    COLLECTIONS=$(curl -s "http://127.0.0.1:${CHROMADB_PORT}/api/v1/collections" | jq -r 'length' 2>/dev/null || echo "0")
    echo "  📊 Collections: ${COLLECTIONS}"
else
    echo "  ❌ ChromaDB not accessible"
fi

echo -e "\n${CYAN}MCP Server Status:${NC}"
if [ -d "${MCP_ROOT}/src" ]; then
    echo "  ✅ MCP Server: Source code present"
    echo "  📁 Location: ${MCP_ROOT}"
    [ -f "${MCP_ROOT}/mcp-server-full.js" ] && echo "     • mcp-server-full.js ✓"
    [ -f "${MCP_ROOT}/mcp-server-sdd.js" ] && echo "     • mcp-server-sdd.js ✓"
    [ -f "${MCP_ROOT}/mcp-server-workflow-core.js" ] && echo "     • mcp-server-workflow-core.js ✓"
else
    echo "  ⚠️  MCP Server: Source code missing"
fi

echo -e "\n${CYAN}NPM Dependencies:${NC}"
if [ -d "${MCP_ROOT}/node_modules" ]; then
    PKG_COUNT=$(find "${MCP_ROOT}/node_modules" -maxdepth 1 -type d | wc -l)
    echo "  ✅ node_modules: Present ($((PKG_COUNT - 1)) packages)"
else
    echo "  ❌ node_modules: Missing (run npm install)"
fi

echo -e "\n${CYAN}Persistent Storage:${NC}"
df -h "${PERSISTENT_ROOT}" | tail -1 | awk '{printf "  Storage: %s used of %s (Available: %s)\n", $3, $2, $4}'

echo -e "\n${CYAN}Directory Structure:${NC}"
echo "  ${CHROMADB_ROOT} (ChromaDB installation)"
echo "  ${CHROMADB_DATA} (ChromaDB data)"
echo "  ${MCP_ROOT} (MCP server - co-located runtime/source)"
echo "  ${GIT_REPO} (Global workflow source - for analysis)"
echo "  ${CACHE_ROOT} (Cache storage)"

################################################################################
# STEP 18: Post-Installation Instructions
################################################################################
log_section "Installation Complete! 🚀"

echo -e "${GREEN}✅ MCP RAG Persistent Infrastructure Ready${NC}\n"

echo -e "${CYAN}Architecture Overview (v3.4.0):${NC}"
echo -e "  📁 Persistent Root: ${PERSISTENT_ROOT} (25GB)"
echo -e "  � Spack Modules: ${SPACK_ROOT}"
echo -e "  �🗄️  ChromaDB Server: Port ${CHROMADB_PORT} (Spack-managed)"
echo -e "  🔧 MCP Server: ${MCP_ROOT}"
echo -e "  📚 Git Repository: ${GIT_REPO}"
echo -e "  💾 Cache Storage: ${CACHE_ROOT} (reused across rebuilds)"
echo -e "  🕸️  Neo4j Graph DB: Port 7474 (UI), 7687 (Bolt)"
echo -e "  🌊 LangFlow: Port 7860 (RAG Visualizer)"
echo -e "  🖥️  noVNC Desktop: Port 6080 (HTTPS)"
echo -e "  🌐 Google Chrome: Installed"

echo -e "\n${CYAN}Key Improvements in v3.4.0:${NC}"
echo -e "  ✅ Migrated to Spack module system (no virtual environments)"
echo -e "  ✅ ChromaDB installed to Spack Python 3.11.14 (~59MB)"
echo -e "  ✅ Lmod module integration for reproducible HPC environments"
echo -e "  ✅ chromadb-spack.service replaces chromadb-persistent.service"
echo -e "  ✅ Eliminated 7.1GB venv bloat"
echo -e "  ✅ Simplified environment setup with setup-spack-chromadb.sh"

echo -e "\n${CYAN}Previous Updates (v3.3.1):${NC}"
echo -e "  ✅ ONNX Runtime validation test added (pre-built binary compatibility)"
echo -e "  ✅ Automatic detection of hardware compatibility issues"
echo -e "  ✅ No custom ONNX build required on modern hardware (Ice Lake+)"

echo -e "\n${CYAN}Previous Updates (v3.3):${NC}"
echo -e "  ✅ Automated deployment with manifest system"
echo -e "  ✅ Week 1 Data Access Layer deployed (GraphDatabase, VectorDatabase, UnifiedDataAccess)"
echo -e "  ✅ Legacy scripts archived to contrib/"
echo -e "  ✅ Deployment versioning and audit trail"
echo -e "  ✅ Automated npm dependency installation"
echo -e "  ✅ Repository → Runtime sync automation"

echo -e "\n${CYAN}Previous Updates (v3.2):${NC}"
echo -e "  ✅ Neo4j graph database added (Phase 0 POC ready)"
echo -e "  ✅ LangFlow RAG visualizer via Docker Compose"
echo -e "  ✅ Hybrid triple-store architecture (ChromaDB + Neo4j)"
echo -e "  ✅ APOC and GDS plugins enabled for Neo4j"
echo -e "  ✅ Persistent volumes for all Docker services"

echo -e "\n${CYAN}Previous Updates (v3.1):${NC}"
echo -e "  ✅ ChromaDB upgraded: 0.4.15 → 1.1.1 (API v2 support)"
echo -e "  ✅ Node.js client: chromadb@3.0.17 (breaking API changes)"
echo -e "  ✅ FastAPI 0.95.2 → 0.119.0 (Pydantic v2 support)"
echo -e "  ✅ Pydantic 1.10.9 → 2.12.2 (major version upgrade)"
echo -e "  ✅ OpenTelemetry instrumentation added"
echo -e "  ✅ No /contrib dependencies (fully persistent)"
echo -e "  ✅ Lightweight venv (~480MB vs 7.1GB bloat)"
echo -e "  ✅ Module system integration (Python 3.11)"
echo -e "  ✅ Fresh start option: --fresh flag"

echo -e "\n${CYAN}What is Spack?${NC}"
echo -e "  Spack = HPC Package Manager with Module System"
echo -e "  - Eliminates need for virtual environments"
echo -e "  - Provides reproducible, relocatable Python installations"
echo -e "  - Module-based dependency loading (Lmod/Environment Modules)"
echo -e "  - ChromaDB installed to Spack Python: ${SPACK_ROOT}/opt/..."
echo -e "  - Contains ChromaDB 1.3.0 + dependencies (~59MB)"
echo -e "  - No venv bloat - direct installation to Spack site-packages"

echo -e "\n${CYAN}Next Steps:${NC}"
echo -e "  1. ${YELLOW}Log out and back in${NC} (for docker group membership)"
echo -e "  2. ${YELLOW}Source environment:${NC} source ${SETUP}/mcp-env.sh"
echo -e "  3. ${YELLOW}Load Spack modules:${NC} source ${MCP_ROOT}/setup-spack-chromadb.sh"
echo -e "  4. ${YELLOW}Verify ChromaDB:${NC} curl http://127.0.0.1:${CHROMADB_PORT}/api/v2/heartbeat"
echo -e "  4. ${YELLOW}Access Neo4j Browser:${NC} http://localhost:7474 (neo4j / gfsworkflow2025)"
echo -e "  5. ${YELLOW}Access LangFlow UI:${NC} http://localhost:7860"
echo -e "  6. ${YELLOW}Start ecFlow services:${NC} cd ${MCP_SOURCE}/SETUP && ./start-ecflow.sh"
echo -e "  7. ${YELLOW}Test Data Access Layer:${NC} cd ${MCP_ROOT} && node test-data-access.js"
echo -e "  8. ${YELLOW}Verify deployment:${NC} cat ${MCP_ROOT}/DEPLOYMENT_LOG.json | jq '.deployments[-1]'"
echo -e "  9. ${YELLOW}Populate ChromaDB:${NC} Run ingestion scripts"
echo -e " 10. ${YELLOW}Start Phase 0 POC:${NC} Neo4j graph ingestion (submodules, CMakeLists)"
echo -e " 11. ${YELLOW}Start MCP service:${NC} systemctl start mcp-server-persistent.service"

echo -e "\n${CYAN}Deployment System:${NC}"
echo -e "  ${BLUE}Deploy updates:${NC}         cd ${MCP_SOURCE} && ./deploy-to-runtime.sh"
echo -e "  ${BLUE}Dry run test:${NC}           cd ${MCP_SOURCE} && ./deploy-to-runtime.sh --dry-run"
echo -e "  ${BLUE}Skip backup:${NC}            ./deploy-to-runtime.sh --skip-backup"
echo -e "  ${BLUE}View manifest:${NC}          cat ${MCP_SOURCE}/deployment-manifest.json | jq"
echo -e "  ${BLUE}Check deployment log:${NC}   cat ${MCP_ROOT}/DEPLOYMENT_LOG.json | jq"
echo -e "  ${BLUE}View legacy archive:${NC}    ls -lh ${GIT_REPO}/contrib/Terry.McGuinness/temp/legacy_MCP_scripts/"

echo -e "\n${CYAN}Useful Commands:${NC}"
echo -e "  ${BLUE}Fresh rebuild:${NC}          sudo ./provision_mcp_rag_persistent.sh --fresh"
echo -e "  ${BLUE}ChromaDB status:${NC}        systemctl status chromadb-spack.service"
echo -e "  ${BLUE}ChromaDB logs:${NC}          journalctl -u chromadb-spack.service -f"
echo -e "  ${BLUE}Neo4j status:${NC}           docker compose ps neo4j"
echo -e "  ${BLUE}Neo4j logs:${NC}             docker compose logs neo4j -f"
echo -e "  ${BLUE}LangFlow logs:${NC}          docker compose logs langflow -f"
echo -e "  ${BLUE}noVNC status:${NC}           systemctl status websockify.service"
echo -e "  ${BLUE}ecFlow server status:${NC}   docker compose ps ecflow-server"
echo -e "  ${BLUE}ecFlow server logs:${NC}     docker compose logs ecflow-server -f"
echo -e "  ${BLUE}ecFlow UI logs:${NC}         docker compose logs ecflow-ui -f"
echo -e "  ${BLUE}Launch ecFlow UI:${NC}       ssh -X [user]@host, then docker exec -e DISPLAY=\$DISPLAY global-workflow-ecflow-ui ecflow_ui"
echo -e "  ${BLUE}All Docker services:${NC}    docker compose ps"
echo -e "  ${BLUE}Stop Docker services:${NC}   docker compose down"
echo -e "  ${BLUE}MCP server logs:${NC}        journalctl -u mcp-server-persistent.service -f"
echo -e "  ${BLUE}Check space:${NC}            df -h ${PERSISTENT_ROOT}"
echo -e "  ${BLUE}Check venv size:${NC}        du -sh ${CHROMADB_ROOT}/venv"

echo -e "\n${CYAN}Configuration Files:${NC}"
echo -e "  Environment:       ${MCP_ROOT}/mcp-env.sh"
echo -e "  Spack setup:       ${MCP_ROOT}/setup-spack-chromadb.sh"
echo -e "  VS Code MCP:       ${GIT_REPO}/.vscode/mcp.json"
echo -e "  ChromaDB service:  /etc/systemd/system/chromadb-spack.service"
echo -e "  MCP service:       /etc/systemd/system/mcp-server-persistent.service"

echo -e "\n${CYAN}Troubleshooting:${NC}"
echo -e "  ${YELLOW}ChromaDB won't start:${NC}  Check logs with journalctl -u chromadb-spack.service"
echo -e "  ${YELLOW}Module not found:${NC}      Source setup-spack-chromadb.sh"
echo -e "  ${YELLOW}Node modules issues:${NC}   rm -rf node_modules && npm install"
echo -e "  ${YELLOW}Python not found:${NC}      module load python/3.11.14"
echo -e "  ${YELLOW}ChromaDB import fails:${NC} Ensure Spack modules loaded (39 total)"
echo -e "  ${YELLOW}API v2 errors:${NC}         ChromaDB 1.3.0 uses API v2 by default"

log_success "Provisioning complete! Environment ready for MCP RAG operations"
