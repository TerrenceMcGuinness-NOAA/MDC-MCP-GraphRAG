#!/bin/bash
################################################################################
# 07-mcp-server.sh - MCP Server Node.js setup and configuration
# Part of modular provisioning system v4.0.0
################################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

require_root

log_subsection "MCP Server Setup"

USER_NAME=$(get_actual_user)
MCP_SOURCE="${EIB_REPO}/mcp_server_node"

# Verify source exists
if [[ ! -d "${MCP_SOURCE}" ]]; then
    log_error "MCP server source not found: ${MCP_SOURCE}"
    exit 1
fi

# Check if MCP_ROOT already has files
if [[ -d "${MCP_ROOT}/src" ]]; then
    log_info "MCP server already deployed at ${MCP_ROOT}"
else
    log_info "Deploying MCP server from ${MCP_SOURCE}..."
    
    # Copy server files
    cp -r "${MCP_SOURCE}/src" "${MCP_ROOT}/"
    cp -r "${MCP_SOURCE}/scripts" "${MCP_ROOT}/" 2>/dev/null || true
    cp "${MCP_SOURCE}/package.json" "${MCP_ROOT}/"
    cp "${MCP_SOURCE}/package-lock.json" "${MCP_ROOT}/" 2>/dev/null || true
    
    log_success "MCP server files deployed"
fi

# Set ownership
chown -R "${USER_NAME}:${USER_NAME}" "${MCP_ROOT}"

################################################################################
# Install npm dependencies
################################################################################

log_subsection "Installing npm Dependencies"

cd "${MCP_ROOT}"

# Check if node_modules exists
if [[ -d "${MCP_ROOT}/node_modules" ]]; then
    log_info "node_modules already exists, running npm install to update..."
else
    log_info "Installing npm dependencies (this may take a few minutes)..."
fi

# Install dependencies
npm install --cache "${CACHE_ROOT}/npm" || {
    log_error "npm install failed"
    exit 1
}

# Count installed packages
PKG_COUNT=$(ls -1 "${MCP_ROOT}/node_modules" 2>/dev/null | wc -l)
log_success "Installed ${PKG_COUNT} npm packages"

################################################################################
# Verify MCP Server
################################################################################

log_subsection "Verifying MCP Server"

# Check main server file exists
if [[ -f "${MCP_ROOT}/src/UnifiedMCPServer.js" ]]; then
    log_success "UnifiedMCPServer.js found"
else
    log_error "UnifiedMCPServer.js not found!"
    exit 1
fi

# Check critical dependencies
CRITICAL_DEPS=("chromadb" "@modelcontextprotocol/sdk" "neo4j-driver")
for dep in "${CRITICAL_DEPS[@]}"; do
    if [[ -d "${MCP_ROOT}/node_modules/${dep}" ]]; then
        log_success "Dependency: ${dep}"
    else
        log_warning "Missing dependency: ${dep}"
    fi
done

log_success "MCP server setup complete"
log_info "  Location: ${MCP_ROOT}"
log_info "  Main: src/UnifiedMCPServer.js"

exit 0
