#!/bin/bash
################################################################################
# 16-lmod.sh - Configure Lmod for Spack Integration
# Version: 1.0.0
#
# This script configures the system Lmod installation to work with
# the local Spack stack at /mcp_rag_eib/spack
#
# Prerequisites:
#   - Lmod package installed (dnf install Lmod)
#   - Spack installed at /mcp_rag_eib/spack with lmod modules generated
################################################################################

source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

SCRIPT_NAME="16-lmod"

log_info "Configuring Lmod for Spack integration..."

# Define paths
LMOD_SYSTEM_INIT="/usr/share/lmod/lmod/init/bash"
SPACK_ROOT="/mcp_rag_eib/spack"
SPACK_LMOD_CORE="${SPACK_ROOT}/share/spack/lmod/linux-rocky9-x86_64/Core"
LMOD_RC_DIR="/mcp_rag_eib/etc/lmod"
LMOD_RC_FILE="${LMOD_RC_DIR}/lmodrc.lua"

# Check if Lmod is installed
if [ ! -f "${LMOD_SYSTEM_INIT}" ]; then
    log_warn "Lmod not found at ${LMOD_SYSTEM_INIT}"
    log_info "Installing Lmod..."
    dnf install -y Lmod
    if [ $? -ne 0 ]; then
        log_error "Failed to install Lmod"
        exit 1
    fi
fi

log_info "[OK] Lmod installed at /usr/share/lmod/lmod"

# Check if Spack lmod modules exist
if [ ! -d "${SPACK_LMOD_CORE}" ]; then
    log_warn "Spack Lmod modules not found at ${SPACK_LMOD_CORE}"
    log_info "You may need to run: spack module lmod refresh"
else
    log_info "[OK] Spack Lmod modules found at ${SPACK_LMOD_CORE}"
    MODULE_COUNT=$(find "${SPACK_LMOD_CORE}" -name "*.lua" 2>/dev/null | wc -l)
    log_info "    Found ${MODULE_COUNT} core module files"
fi

# Create Lmod configuration directory
mkdir -p "${LMOD_RC_DIR}"

# Create lmodrc.lua for site configuration
cat > "${LMOD_RC_FILE}" << 'EOF'
-- /mcp_rag_eib/etc/lmod/lmodrc.lua
-- Site-specific Lmod configuration for MCP RAG development environment
--
-- This file configures Lmod behavior for the Spack-based module system

-- Reduce verbosity of module spider
spider_quiet_mode = true

-- Don't show module unavailable messages during shell init
quiet_on_missing_module = true

-- Property definitions for module display
propT = {
   arch = {
      validT = { mic = 1, offload = 1, gpu = 1, },
      displayT = {
         mic     = { short = "(m)",  long = "(mic)",     },
         offload = { short = "(o)",  long = "(offload)", },
         gpu     = { short = "(g)",  long = "(gpu)",     },
      },
   },
}

-- Site message displayed with 'module list'
siteMsg = [[
MCP RAG Development Environment - Lmod Configuration
Spack modules: /mcp_rag_eib/spack/share/spack/lmod/linux-rocky9-x86_64
]]
EOF

log_info "[OK] Created Lmod site configuration at ${LMOD_RC_FILE}"

# Create modulefiles directory for any custom modules
CUSTOM_MODULES="/mcp_rag_eib/etc/modulefiles"
mkdir -p "${CUSTOM_MODULES}"
log_info "[OK] Created custom modulefiles directory at ${CUSTOM_MODULES}"

# Create a test module to verify Lmod is working
cat > "${CUSTOM_MODULES}/mcp-env.lua" << 'EOF'
-- MCP RAG Environment Module
-- Load with: module load mcp-env

help([[
MCP RAG Development Environment
Loads common paths and environment variables for MCP development
]])

whatis("Name: mcp-env")
whatis("Version: 1.0")
whatis("Description: MCP RAG Development Environment")

-- Set MCP environment variables
setenv("PERSISTENT_ROOT", "/mcp_rag_eib")
setenv("EIB_REPO", "/mcp_rag_eib/eib-mcp-rag-server")
setenv("MCP_ROOT", "/mcp_rag_eib/eib-mcp-rag-server/mcp_server_node")
setenv("GW_REPO", "/mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow")

-- Add MCP bin to PATH
prepend_path("PATH", "/mcp_rag_eib/eib-mcp-rag-server/mcp_server_node/bin")
EOF

log_info "[OK] Created mcp-env module"

# Set ownership
chown -R "${MCP_USER}:${MCP_GROUP}" "${LMOD_RC_DIR}"
chown -R "${MCP_USER}:${MCP_GROUP}" "${CUSTOM_MODULES}"

# Verify installation
log_info "Verifying Lmod configuration..."
if su - "${MCP_USER}" -c "source ${LMOD_SYSTEM_INIT} && module --version" &>/dev/null; then
    LMOD_VERSION=$(su - "${MCP_USER}" -c "source ${LMOD_SYSTEM_INIT} && module --version 2>&1 | head -1")
    log_info "[OK] Lmod verified: ${LMOD_VERSION}"
else
    log_warn "Could not verify Lmod - may need shell restart"
fi

# Summary
echo ""
log_info "=========================================="
log_info "Lmod Configuration Summary"
log_info "=========================================="
log_info "Lmod Init:        ${LMOD_SYSTEM_INIT}"
log_info "Lmod RC:          ${LMOD_RC_FILE}"
log_info "Spack Modules:    ${SPACK_LMOD_CORE}"
log_info "Custom Modules:   ${CUSTOM_MODULES}"
log_info ""
log_info "Shell initialization will use:"
log_info "  source /usr/share/lmod/lmod/init/bash"
log_info "  module use ${SPACK_LMOD_CORE}"
log_info "  module use ${CUSTOM_MODULES}"
log_info "=========================================="

mark_completed "${SCRIPT_NAME}"
log_info "[OK] Lmod configuration complete"
