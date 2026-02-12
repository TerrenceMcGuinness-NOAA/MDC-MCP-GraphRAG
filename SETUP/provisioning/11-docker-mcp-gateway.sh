#!/bin/bash
################################################################################
# 11-docker-mcp-gateway.sh - Docker MCP Gateway Plugin Setup
# Part of modular provisioning system v4.1.0
#
# This script:
#   1. Installs Go compiler (required for building docker-mcp)
#   2. Clones the docker/mcp-gateway repository
#   3. Builds the docker-mcp CLI plugin
#   4. Installs plugin to ~/.docker/cli-plugins/
#   5. Creates MCP server catalog configuration on PERSISTENT DRIVE
#   6. Builds the eib-mcp-rag container image
#
# Config Storage Strategy (v4.1.0):
#   - Canonical configs stored on persistent drive at SETUP/docker-mcp/
#   - Gateway uses --catalog/--registry/--config/--tools-config with
#     absolute paths (bypasses ~/.docker/mcp/ for these 4 files)
#   - Ephemeral state (mcp.db, catalog_index/) stays in ~/.docker/mcp/
#     and regenerates on new VM spin-up — no data loss
#   - No symlinks needed — native docker-mcp absolute path support
#
# Reference: Phase 11 SDD - sdd_framework/workflows/phase11_docker_mcp_gateway_langflow.md
################################################################################

set -eo pipefail

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

# Check if plugin needs updating (idempotent)
PLUGIN_INSTALLED="${DOCKER_CLI_PLUGINS}/docker-mcp"
PLUGIN_BUILT="${MCP_GATEWAY_REPO}/docker-mcp"

if [[ -f "${PLUGIN_INSTALLED}" ]]; then
    # Compare checksums to see if update needed
    INSTALLED_SUM=$(md5sum "${PLUGIN_INSTALLED}" 2>/dev/null | awk '{print $1}' || echo "none")
    BUILT_SUM=$(md5sum "${PLUGIN_BUILT}" 2>/dev/null | awk '{print $1}' || echo "new")
    
    if [[ "${INSTALLED_SUM}" == "${BUILT_SUM}" ]]; then
        log_info "Plugin already up-to-date, skipping install"
    else
        # Try to copy, handling "Text file busy" if gateway is running
        if cp "${PLUGIN_BUILT}" "${PLUGIN_INSTALLED}" 2>/dev/null; then
            chmod +x "${PLUGIN_INSTALLED}"
            chown "$(get_ownership "${USER_NAME}")" "${PLUGIN_INSTALLED}"
            log_success "Plugin updated: ${PLUGIN_INSTALLED}"
        else
            log_warning "Plugin in use (gateway running), will use existing version"
        fi
    fi
else
    # Fresh install
    cp "${PLUGIN_BUILT}" "${PLUGIN_INSTALLED}"
    chmod +x "${PLUGIN_INSTALLED}"
    chown "$(get_ownership "${USER_NAME}")" "${PLUGIN_INSTALLED}"
    log_success "Plugin installed: ${PLUGIN_INSTALLED}"
fi

# Verify installation
if run_as_user "${USER_NAME}" "docker mcp --version" &>/dev/null; then
    log_success "Plugin verified: $(run_as_user "${USER_NAME}" "docker mcp --version 2>&1" | head -1)"
else
    log_warning "Plugin installed but 'docker mcp' command not working yet"
fi

################################################################################
# Create MCP Configuration (Persistent Drive - SPOT)
################################################################################

log_subsection "MCP Gateway Configuration (Persistent Drive)"

# SPOT: Canonical configs live on the persistent drive so they survive VM replacement.
# The gateway uses absolute-path CLI flags (--catalog, --registry, --config,
# --tools-config) which bypass ~/.docker/mcp/ resolution entirely.
# Ephemeral runtime state (mcp.db, catalog_index/) stays in ~/.docker/mcp/
# and is regenerated automatically by the gateway on first start.

PERSISTENT_MCP_DIR="${SETUP_DIR}/docker-mcp"
PERSISTENT_CATALOGS_DIR="${PERSISTENT_MCP_DIR}/catalogs"
HOME_MCP_DIR="${USER_HOME}/.docker/mcp"

mkdir -p "${PERSISTENT_CATALOGS_DIR}"
run_as_user "${USER_NAME}" "mkdir -p ${HOME_MCP_DIR}/catalogs"

# Write EIB MCP RAG catalog to PERSISTENT drive (v3 format with registry: key)
# SPOT: This is the single source of truth for MCP gateway catalog configuration
# Note: Uses 172.17.0.1 (Docker bridge gateway) for container-to-host DB access
cat > "${PERSISTENT_CATALOGS_DIR}/eib-local.yaml" << EOF
# EIB MCP RAG Server Catalog - v3 format (SPOT - Single Point of Truth)
# Canonical location: SETUP/docker-mcp/catalogs/eib-local.yaml (persistent drive)
# Created by: SETUP/provisioning/11-docker-mcp-gateway.sh
# Used by: docker mcp gateway run --catalog <this-file>
# Transport: streaming (Streamable HTTP - MCP spec 2025-06-18)
#
# IMPORTANT: The 'docker mcp catalog create' command OVERWRITES files in
# ~/.docker/mcp/. This file on the persistent drive is the canonical copy.
# The gateway --catalog flag accepts absolute paths, bypassing ~/.docker/mcp/.

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

log_success "MCP catalog (SPOT): ${PERSISTENT_CATALOGS_DIR}/eib-local.yaml"

# Write registry.yaml to persistent drive
cat > "${PERSISTENT_MCP_DIR}/registry.yaml" << 'EOF'
# Docker MCP Registry - EIB server enabled
# Canonical location: SETUP/docker-mcp/registry.yaml (persistent drive)
registry:
  eib-mcp-rag:
    ref: ""
EOF

log_success "MCP registry (SPOT): ${PERSISTENT_MCP_DIR}/registry.yaml"

# Write config.yaml and tools.yaml placeholders to persistent drive
touch "${PERSISTENT_MCP_DIR}/config.yaml"
touch "${PERSISTENT_MCP_DIR}/tools.yaml"

chown -R "$(get_ownership "${USER_NAME}")" "${PERSISTENT_MCP_DIR}"

log_success "All MCP configs on persistent drive: ${PERSISTENT_MCP_DIR}/"

################################################################################
# Seed Home Dir with Ephemeral Copies (for docker mcp CLI commands)
################################################################################

log_subsection "Seeding Home Dir MCP Config (ephemeral)"

# The 'docker mcp catalog ls', 'docker mcp server ls' CLI commands read from
# ~/.docker/mcp/ — they don't accept --catalog flags. We copy the configs
# there so those CLI commands work, but the GATEWAY itself uses absolute paths
# to the persistent drive (see systemd service below).
#
# IMPORTANT: 'docker mcp catalog create' OVERWRITES the catalog YAML in
# ~/.docker/mcp/catalogs/. We write the home dir copies AFTER any such calls.

# Copy persistent configs to home dir for CLI compatibility
cp "${PERSISTENT_CATALOGS_DIR}/eib-local.yaml" "${HOME_MCP_DIR}/catalogs/eib-local.yaml"
cp "${PERSISTENT_MCP_DIR}/registry.yaml" "${HOME_MCP_DIR}/registry.yaml"
cp "${PERSISTENT_MCP_DIR}/config.yaml" "${HOME_MCP_DIR}/config.yaml" 2>/dev/null || true
cp "${PERSISTENT_MCP_DIR}/tools.yaml" "${HOME_MCP_DIR}/tools.yaml" 2>/dev/null || true

# Write catalog.json (index of known catalogs — this is ephemeral runtime state)
cat > "${HOME_MCP_DIR}/catalog.json" << 'CATJSON'
{
  "catalogs": {
    "docker-mcp": {
      "displayName": "Docker MCP Catalog",
      "url": "https://desktop.docker.com/mcp/catalog/v2/catalog.yaml"
    },
    "eib-local": {
      "displayName": "eib-local"
    }
  }
}
CATJSON

chown -R "$(get_ownership "${USER_NAME}")" "${HOME_MCP_DIR}"

log_success "Home dir seeded: ${HOME_MCP_DIR}/ (ephemeral copies)"

# Verify CLI sees the server
log_info "Verifying docker mcp CLI registration..."
SERVER_LIST=$(run_as_user "${USER_NAME}" "docker mcp server ls 2>&1" || echo "")
if echo "${SERVER_LIST}" | grep -q "eib-mcp-rag"; then
    log_success "Server 'eib-mcp-rag' visible in docker mcp CLI"
else
    log_warning "Server not visible in CLI - this is OK, gateway uses absolute paths"
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
# All config files use ABSOLUTE paths to the persistent drive (SETUP/docker-mcp/)
# so they survive VM replacement. The gateway resolves absolute paths directly,
# bypassing the ~/.docker/mcp/ directory for these 4 files.
# Port 18888 to avoid conflicts with common services on RDHPCS systems
ExecStart=${USER_HOME}/.docker/cli-plugins/docker-mcp gateway run \\
    --catalog ${SETUP_DIR}/docker-mcp/catalogs/eib-local.yaml \\
    --registry ${SETUP_DIR}/docker-mcp/registry.yaml \\
    --config ${SETUP_DIR}/docker-mcp/config.yaml \\
    --tools-config ${SETUP_DIR}/docker-mcp/tools.yaml \\
    --enable-all-servers \\
    --transport streaming \\
    --port 18888 \\
    --long-lived \\
    --verbose

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

################################################################################
# Start Gateway Service (Idempotent)
################################################################################

log_subsection "Starting MCP Gateway Service"

# Check if gateway is already running and healthy
GATEWAY_HEALTHY=false

if systemctl is-active --quiet mcp-gateway.service; then
    # Service is running, check if port is responding
    if ss -tlnp 2>/dev/null | grep -q ":18888"; then
        # Port is listening, verify MCP protocol response
        HEALTH_CHECK=$(curl -s --max-time 5 "http://localhost:18888/mcp" \
            -H "Authorization: Bearer eib-mcp-gateway-token-2025" \
            -H "Content-Type: application/json" \
            -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"healthcheck","version":"1.0"}}}' 2>/dev/null || echo "")
        
        if echo "${HEALTH_CHECK}" | grep -q '"protocolVersion"'; then
            GATEWAY_HEALTHY=true
            log_success "Gateway already running and healthy on port 18888"
        else
            log_warning "Gateway running but not responding to MCP protocol, restarting..."
        fi
    else
        log_warning "Gateway service active but port 18888 not listening, restarting..."
    fi
else
    log_info "Gateway service not running, starting..."
fi

# Start or restart if not healthy
if [[ "${GATEWAY_HEALTHY}" == false ]]; then
    systemctl restart mcp-gateway.service
    
    # Wait for startup (up to 15 seconds)
    log_info "Waiting for gateway to start..."
    for i in {1..15}; do
        sleep 1
        if ss -tlnp 2>/dev/null | grep -q ":18888"; then
            # Verify MCP response
            HEALTH_CHECK=$(curl -s --max-time 3 "http://localhost:18888/mcp" \
                -H "Authorization: Bearer eib-mcp-gateway-token-2025" \
                -H "Content-Type: application/json" \
                -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"healthcheck","version":"1.0"}}}' 2>/dev/null || echo "")
            
            if echo "${HEALTH_CHECK}" | grep -q '"protocolVersion"'; then
                log_success "Gateway started and responding on port 18888"
                GATEWAY_HEALTHY=true
                break
            fi
        fi
        printf "."
    done
    echo ""
    
    if [[ "${GATEWAY_HEALTHY}" == false ]]; then
        log_warning "Gateway may not be fully healthy - check: systemctl status mcp-gateway"
    fi
fi

################################################################################
# Summary
################################################################################

log_section "Docker MCP Gateway Setup Complete"

log_info "Components installed:"
log_success "  Go compiler: $(go version | awk '{print $3}')"
log_success "  docker-mcp plugin: ${DOCKER_CLI_PLUGINS}/docker-mcp"
log_success "  MCP catalog (persistent): ${PERSISTENT_CATALOGS_DIR}/eib-local.yaml"
log_success "  MCP registry (persistent): ${PERSISTENT_MCP_DIR}/registry.yaml"
log_success "  Container image: eib-mcp-rag:latest"
log_success "  Systemd service: mcp-gateway.service"
log_info ""
log_info "Persistent drive config (survives VM replacement):"
log_info "  ${PERSISTENT_MCP_DIR}/"
log_info "  ├── catalogs/eib-local.yaml  (--catalog absolute path)"
log_info "  ├── registry.yaml            (--registry absolute path)"
log_info "  ├── config.yaml              (--config absolute path)"
log_info "  └── tools.yaml               (--tools-config absolute path)"
log_info ""
log_info "Ephemeral home dir (regenerates on new VM):"
log_info "  ${HOME_MCP_DIR}/  (copies for docker mcp CLI compatibility)"

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
log_info "Gateway management:"
log_info "  Status:  sudo systemctl status mcp-gateway"
log_info "  Restart: sudo systemctl restart mcp-gateway"
log_info "  Logs:    sudo journalctl -u mcp-gateway -f"
log_info ""
log_info "Verify tools available:"
log_info "  docker mcp tools ls"
log_info ""
log_info "Remote Access (from client machine):"
log_info "  1. SSH tunnel: ssh -L 18888:localhost:18888 user@server -N"
log_info "  2. VS Code mcp.json: type=http, url=http://localhost:18888/mcp"
log_info "  3. Bearer token: eib-mcp-gateway-token-2025"

if [[ "${GATEWAY_HEALTHY}" == true ]]; then
    record_result "11-docker-mcp-gateway.sh" "success" "${TOOL_COUNT} tools, gateway running"
else
    record_result "11-docker-mcp-gateway.sh" "warning" "${TOOL_COUNT} tools, gateway may need manual start"
fi
exit 0
