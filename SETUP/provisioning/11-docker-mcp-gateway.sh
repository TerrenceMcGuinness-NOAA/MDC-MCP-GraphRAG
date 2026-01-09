#!/bin/bash
################################################################################
# 11-docker-mcp-gateway.sh - Docker MCP Gateway Plugin Setup
# Part of modular provisioning system v4.0.0
#
# This script:
#   1. Installs Go compiler (required for building docker-mcp)
#   2. Clones the docker/mcp-gateway repository
#   3. Builds the docker-mcp CLI plugin
#   4. Installs plugin to ~/.docker/cli-plugins/
#   5. Creates MCP server catalog configuration
#   6. Builds the eib-mcp-rag container image
#
# Reference: Phase 11 SDD - sdd_framework/workflows/phase11_docker_mcp_gateway_langflow.md
################################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

# Can run as root or as user
USER_NAME=$(get_actual_user)
USER_HOME=$(eval echo ~"${USER_NAME}")

log_section "Docker MCP Gateway Setup"

################################################################################
# Install Go Compiler
################################################################################

log_subsection "Go Compiler Installation"

GO_VERSION="1.23.4"
GO_INSTALL_DIR="/usr/local/go"

if command_exists go; then
    CURRENT_GO=$(go version 2>/dev/null | awk '{print $3}' | sed 's/go//')
    log_info "Go already installed: ${CURRENT_GO}"
else
    log_info "Installing Go ${GO_VERSION}..."
    
    # Download and install Go
    cd /tmp
    curl -sLO "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz"
    
    # Remove any existing Go installation
    rm -rf "${GO_INSTALL_DIR}"
    
    # Extract to /usr/local
    tar -C /usr/local -xzf "go${GO_VERSION}.linux-amd64.tar.gz"
    rm -f "go${GO_VERSION}.linux-amd64.tar.gz"
    
    # Add to system PATH
    cat > /etc/profile.d/golang.sh << 'EOF'
export PATH=$PATH:/usr/local/go/bin
export GOPATH=$HOME/go
export PATH=$PATH:$GOPATH/bin
EOF
    
    log_success "Go ${GO_VERSION} installed"
fi

# Ensure Go is in PATH for this script
export PATH=$PATH:/usr/local/go/bin
export GOPATH="${USER_HOME}/go"
export PATH=$PATH:${GOPATH}/bin

# Verify Go
if go version &>/dev/null; then
    log_success "Go compiler: $(go version | awk '{print $3}')"
else
    log_error "Go not found in PATH after installation"
    exit 1
fi

################################################################################
# Clone MCP Gateway Repository
################################################################################

log_subsection "MCP Gateway Repository"

MCP_GATEWAY_REPO="${EIB_REPO}/supported_repos/mcp-gateway"

if [[ -d "${MCP_GATEWAY_REPO}/.git" ]]; then
    log_info "MCP Gateway repo exists, updating..."
    cd "${MCP_GATEWAY_REPO}"
    run_as_user "${USER_NAME}" "cd ${MCP_GATEWAY_REPO} && git pull --ff-only" || true
else
    log_info "Cloning MCP Gateway repository..."
    mkdir -p "$(dirname ${MCP_GATEWAY_REPO})"
    run_as_user "${USER_NAME}" "git clone https://github.com/docker/mcp-gateway.git ${MCP_GATEWAY_REPO}"
fi

# Verify clone
if [[ -f "${MCP_GATEWAY_REPO}/Makefile" ]]; then
    log_success "MCP Gateway repo ready: ${MCP_GATEWAY_REPO}"
else
    log_error "MCP Gateway repo incomplete"
    exit 1
fi

################################################################################
# Build docker-mcp Plugin
################################################################################

log_subsection "Building docker-mcp Plugin"

cd "${MCP_GATEWAY_REPO}"

# Build the plugin
log_info "Building docker-mcp CLI plugin (this may take a few minutes)..."
run_as_user "${USER_NAME}" "cd ${MCP_GATEWAY_REPO} && go build -o docker-mcp ./cmd/docker-mcp" || {
    log_error "Failed to build docker-mcp"
    exit 1
}

# Verify build
if [[ -f "${MCP_GATEWAY_REPO}/docker-mcp" ]]; then
    PLUGIN_VERSION=$("${MCP_GATEWAY_REPO}/docker-mcp" --version 2>&1 | head -1 || echo "unknown")
    log_success "Built docker-mcp: ${PLUGIN_VERSION}"
else
    log_error "docker-mcp binary not found after build"
    exit 1
fi

################################################################################
# Install Plugin
################################################################################

log_subsection "Installing docker-mcp Plugin"

DOCKER_CLI_PLUGINS="${USER_HOME}/.docker/cli-plugins"

# Create plugins directory
run_as_user "${USER_NAME}" "mkdir -p ${DOCKER_CLI_PLUGINS}"

# Install plugin
cp "${MCP_GATEWAY_REPO}/docker-mcp" "${DOCKER_CLI_PLUGINS}/docker-mcp"
chmod +x "${DOCKER_CLI_PLUGINS}/docker-mcp"
chown "$(get_ownership "${USER_NAME}")" "${DOCKER_CLI_PLUGINS}/docker-mcp"

# Verify installation
if run_as_user "${USER_NAME}" "docker mcp --version" &>/dev/null; then
    log_success "Plugin installed: ${DOCKER_CLI_PLUGINS}/docker-mcp"
else
    log_warning "Plugin installed but 'docker mcp' command not working yet"
fi

################################################################################
# Create MCP Configuration
################################################################################

log_subsection "MCP Gateway Configuration"

MCP_CONFIG_DIR="${USER_HOME}/.docker/mcp"
run_as_user "${USER_NAME}" "mkdir -p ${MCP_CONFIG_DIR}/catalogs"

# Create EIB MCP RAG catalog entry (v3 format with registry: key)
# SPOT: This is the single source of truth for MCP gateway catalog configuration
# Note: Uses 172.17.0.1 (Docker bridge gateway) for container-to-host DB access
cat > "${MCP_CONFIG_DIR}/catalogs/eib-local.yaml" << EOF
# EIB MCP RAG Server Catalog - v3 format (SPOT - Single Point of Truth)
# Created by: SETUP/provisioning/11-docker-mcp-gateway.sh
# Used by: sudo systemctl start mcp-gateway
# Transport: streaming (Streamable HTTP - MCP spec 2025-06-18)

version: 3
name: eib-local
displayName: EIB Local MCP Catalog

registry:
  eib-mcp-rag:
    title: EIB MCP RAG Server
    description: AI-powered code analysis and EE2 compliance checking for NOAA Global Workflow
    type: server
    image: eib-mcp-rag:latest
    env:
      - name: CHROMADB_HOST
        value: "172.17.0.1"
      - name: CHROMADB_PORT
        value: "8080"
      - name: CHROMADB_URL
        value: "http://172.17.0.1:8080"
      - name: NEO4J_URI
        value: "bolt://172.17.0.1:7687"
      - name: NEO4J_USER
        value: neo4j
      - name: NEO4J_PASSWORD
        value: gfsworkflow2025
      - name: MCP_WORKFLOW_ROOT
        value: "/app/supported_repos/global-workflow"
      - name: MCP_SCENARIO
        value: full
      - name: ENABLE_RAG
        value: "true"
      - name: ENABLE_GITHUB
        value: "true"
    volumes:
      - "${EIB_REPO}/supported_repos:/app/supported_repos:ro"
      - "${EIB_REPO}/sdd_framework:/app/sdd_framework:ro"
    metadata:
      category: devops
      tags:
        - noaa
        - gfs
        - mcp
        - rag
EOF

chown -R "$(get_ownership "${USER_NAME}")" "${MCP_CONFIG_DIR}"

log_success "MCP catalog file created: ${MCP_CONFIG_DIR}/catalogs/eib-local.yaml"

################################################################################
# Register Catalog with Docker MCP System
################################################################################

log_subsection "Registering Catalog with Docker MCP"

# The docker mcp catalog system requires explicit registration
# Simply having the YAML file in ~/.docker/mcp/catalogs/ is NOT sufficient
# We must: 1) Create catalog, 2) Add server to catalog, 3) Enable server

log_info "Creating eib-local catalog in docker mcp system..."

# Create the catalog (idempotent - will fail silently if exists)
run_as_user "${USER_NAME}" "docker mcp catalog create eib-local 2>/dev/null || true"

# Add the server to the catalog from our YAML file
# This imports the server definition into the docker mcp registry
log_info "Adding eib-mcp-rag server to catalog..."
run_as_user "${USER_NAME}" "docker mcp catalog add eib-local eib-mcp-rag ${MCP_CONFIG_DIR}/catalogs/eib-local.yaml --force" || {
    log_warning "Failed to add server to catalog, may already exist"
}

# Enable the server so it's available to the gateway
log_info "Enabling eib-mcp-rag server..."
run_as_user "${USER_NAME}" "docker mcp server enable eib-mcp-rag" || {
    log_warning "Failed to enable server, may already be enabled"
}

# Verify registration
log_info "Verifying catalog registration..."
CATALOG_LIST=$(run_as_user "${USER_NAME}" "docker mcp catalog ls 2>&1" || echo "")
if echo "${CATALOG_LIST}" | grep -q "eib-local"; then
    log_success "Catalog 'eib-local' registered in docker mcp system"
else
    log_warning "Catalog registration may have issues - check 'docker mcp catalog ls'"
fi

SERVER_LIST=$(run_as_user "${USER_NAME}" "docker mcp server ls 2>&1" || echo "")
if echo "${SERVER_LIST}" | grep -q "eib-mcp-rag"; then
    log_success "Server 'eib-mcp-rag' enabled and ready"
else
    log_warning "Server may not be enabled - check 'docker mcp server ls'"
fi

################################################################################
# Build MCP RAG Container Image
################################################################################

log_subsection "Building MCP RAG Container Image"

# Option 1: Pull pre-built image from GitLab registry (faster)
# docker login registry.gitlab-licensed.vlab.noaa.gov
# docker pull registry.gitlab-licensed.vlab.noaa.gov/nws/operations/ncep/emc/eib/eib-mcp-rag-server/mcp-server:stable
# docker tag registry.gitlab-licensed.vlab.noaa.gov/nws/operations/ncep/emc/eib/eib-mcp-rag-server/mcp-server:stable eib-mcp-rag:latest

# Option 2: Build locally (current behavior)
COMPOSE_FILE="${EIB_REPO}/docker-compose.mcp-standalone.yaml"
DOCKERFILE="${SETUP_DIR}/dockerfiles/Dockerfile.mcp-server"

if [[ ! -f "${DOCKERFILE}" ]]; then
    log_error "Dockerfile not found: ${DOCKERFILE}"
    exit 1
fi

if [[ ! -f "${COMPOSE_FILE}" ]]; then
    log_error "Compose file not found: ${COMPOSE_FILE}"
    exit 1
fi

log_info "Building eib-mcp-rag:latest image..."
cd "${EIB_REPO}"

run_as_user "${USER_NAME}" "docker compose -f ${COMPOSE_FILE} build eib-mcp-rag" || {
    log_error "Failed to build eib-mcp-rag image"
    exit 1
}

# Verify image
if docker images eib-mcp-rag:latest --format "{{.Repository}}:{{.Tag}}" | grep -q "eib-mcp-rag:latest"; then
    IMAGE_SIZE=$(docker images eib-mcp-rag:latest --format "{{.Size}}")
    log_success "Image built: eib-mcp-rag:latest (${IMAGE_SIZE})"
else
    log_error "Image eib-mcp-rag:latest not found after build"
    exit 1
fi

# Verify gateway metadata label
METADATA_LABEL=$(docker inspect eib-mcp-rag:latest --format '{{index .Config.Labels "io.docker.server.metadata"}}' 2>/dev/null || echo "")
if [[ -n "${METADATA_LABEL}" ]]; then
    log_success "Gateway metadata label present"
else
    log_warning "Gateway metadata label missing from image"
fi

################################################################################
# Create Systemd Service for MCP Gateway
################################################################################

log_subsection "MCP Gateway Systemd Service"

GATEWAY_SERVICE="/etc/systemd/system/mcp-gateway.service"
SERVICE_TEMPLATE="${SETUP_DIR}/systemd/mcp-gateway.service.template"

# Use template if available (SPOT), otherwise generate inline
if [[ -f "${SERVICE_TEMPLATE}" ]]; then
    log_info "Installing from template: ${SERVICE_TEMPLATE}"
    # Substitute variables in template
    sed -e "s|\${USER_NAME}|${USER_NAME}|g" \
        -e "s|\${USER_HOME}|${USER_HOME}|g" \
        -e "s|\${USER_GROUP}|$(get_user_group "${USER_NAME}")|g" \
        "${SERVICE_TEMPLATE}" > "${GATEWAY_SERVICE}"
else
    log_info "Template not found, generating inline..."
    cat > "${GATEWAY_SERVICE}" << EOF
[Unit]
Description=Docker MCP Gateway (Streamable HTTP transport)
After=network.target docker.service chromadb-persistent.service
Requires=docker.service
Wants=chromadb-persistent.service

[Service]
Type=simple
User=${USER_NAME}
Group=$(get_user_group "${USER_NAME}")
Environment=MCP_GATEWAY_AUTH_TOKEN=eib-mcp-gateway-token-2025
Environment=PATH=/usr/local/go/bin:/usr/bin:/bin:${USER_HOME}/.docker/cli-plugins
WorkingDirectory=${USER_HOME}

# Use streaming transport (Streamable HTTP - bidirectional, MCP spec 2025-06-18)
# Server is registered via 'docker mcp catalog add' + 'docker mcp server enable'
# Port 18888 to avoid conflicts with common services on RDHPCS systems
ExecStart=${USER_HOME}/.docker/cli-plugins/docker-mcp gateway run --servers eib-mcp-rag --transport streaming --port 18888 --long-lived

Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
fi

log_info "Created systemd service: mcp-gateway.service"

# Reload systemd and enable service
systemctl daemon-reload
systemctl enable mcp-gateway.service

log_success "MCP Gateway systemd service configured"
log_info "  Start with: sudo systemctl start mcp-gateway"
log_info "  Status: sudo systemctl status mcp-gateway"

################################################################################
# Summary
################################################################################

log_section "Docker MCP Gateway Setup Complete"

log_info "Components installed:"
log_success "  Go compiler: $(go version | awk '{print $3}')"
log_success "  docker-mcp plugin: ${DOCKER_CLI_PLUGINS}/docker-mcp"
log_success "  MCP catalog file: ${MCP_CONFIG_DIR}/catalogs/eib-local.yaml"
log_success "  Container image: eib-mcp-rag:latest"
log_success "  Systemd service: mcp-gateway.service"

log_info ""
log_info "Catalog registration status:"
run_as_user "${USER_NAME}" "docker mcp catalog ls" || true
log_info ""
run_as_user "${USER_NAME}" "docker mcp server ls" || true

# Verify tool discovery with dry-run
log_info ""
log_info "Testing tool discovery (dry-run)..."
TOOL_COUNT=$(run_as_user "${USER_NAME}" "docker mcp gateway run --servers eib-mcp-rag --dry-run 2>&1" | grep -oP '\(\d+ tools\)' | grep -oP '\d+' || echo "0")
if [[ "${TOOL_COUNT}" -gt 0 ]]; then
    log_success "Gateway discovers ${TOOL_COUNT} tools from eib-mcp-rag server"
else
    log_warning "Tool discovery returned 0 tools - check catalog registration"
    log_info "Debug: docker mcp gateway run --servers eib-mcp-rag --dry-run --verbose"
fi

log_info ""
log_info "Start the gateway service:"
log_info "  sudo systemctl start mcp-gateway"
log_info "  sudo systemctl status mcp-gateway"
log_info ""
log_info "Or run manually:"
log_info "  export MCP_GATEWAY_AUTH_TOKEN=\"eib-mcp-gateway-token-2025\""
log_info "  docker mcp gateway run --servers eib-mcp-rag --transport streaming --port 18888 --long-lived --verbose"
log_info ""
log_info "Verify tools available:"
log_info "  docker mcp tools ls"
log_info ""
log_info "Remote Access (from client machine):"
log_info "  1. SSH tunnel: ssh -L 18888:localhost:18888 user@server -N"
log_info "  2. VS Code mcp.json: type=http, url=http://localhost:18888/mcp"
log_info "  3. Bearer token: eib-mcp-gateway-token-2025"

record_result "11-docker-mcp-gateway.sh" "success" "${TOOL_COUNT} tools"
exit 0
