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
chown "${USER_NAME}:${USER_NAME}" "${DOCKER_CLI_PLUGINS}/docker-mcp"

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

# Create EIB MCP RAG catalog entry
cat > "${MCP_CONFIG_DIR}/catalogs/eib-mcp-rag.yaml" << 'EOF'
# EIB MCP RAG Server Catalog Entry
# Used by: docker mcp gateway run --catalog ~/.docker/mcp/catalogs/eib-mcp-rag.yaml

servers:
  eib-mcp-rag:
    name: eib-mcp-rag
    title: EIB MCP RAG Server
    description: AI-powered MCP server with RAG for NOAA Global Workflow
    type: image
    image: eib-mcp-rag:latest
    longLived: false
    env:
      - name: CHROMADB_HOST
        value: chromadb
      - name: CHROMADB_PORT
        value: "8000"
      - name: NEO4J_URI
        value: bolt://neo4j:7687
      - name: NEO4J_USER
        value: neo4j
      - name: NEO4J_PASSWORD
        value: gfsworkflow2025
EOF

chown -R "${USER_NAME}:${USER_NAME}" "${MCP_CONFIG_DIR}"

log_success "MCP catalog created: ${MCP_CONFIG_DIR}/catalogs/eib-mcp-rag.yaml"

################################################################################
# Build MCP RAG Container Image
################################################################################

log_subsection "Building MCP RAG Container Image"

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
# Summary
################################################################################

log_section "Docker MCP Gateway Setup Complete"

log_info "Components installed:"
log_success "  Go compiler: $(go version | awk '{print $3}')"
log_success "  docker-mcp plugin: ${DOCKER_CLI_PLUGINS}/docker-mcp"
log_success "  MCP catalog: ${MCP_CONFIG_DIR}/catalogs/eib-mcp-rag.yaml"
log_success "  Container image: eib-mcp-rag:latest"

log_info ""
log_info "Usage:"
log_info "  # Test gateway discovery (dry-run)"
log_info "  docker mcp gateway run --servers docker://eib-mcp-rag:latest --dry-run --verbose"
log_info ""
log_info "  # Start gateway with HTTP transport"
log_info "  export MCP_GATEWAY_AUTH_TOKEN=\"your-secret-token\""
log_info "  docker mcp gateway run --servers docker://eib-mcp-rag:latest --port 8888 --transport streamable-http"
log_info ""
log_info "  # Run container directly with DB network (for RAG features)"
log_info "  docker run -d --name eib-mcp-standalone \\"
log_info "    --network global-workflow-mcp-rag \\"
log_info "    -e CHROMADB_HOST=chromadb -e CHROMADB_PORT=8000 \\"
log_info "    -e NEO4J_URI=bolt://neo4j:7687 \\"
log_info "    -e NEO4J_USER=neo4j -e NEO4J_PASSWORD=gfsworkflow2025 \\"
log_info "    eib-mcp-rag:latest"

exit 0
