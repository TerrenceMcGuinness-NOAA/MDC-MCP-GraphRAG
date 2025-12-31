#!/bin/bash
################################################################################
# 03-docker.sh - Docker installation and configuration
# Part of modular provisioning system v4.0.0
################################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

require_root

log_subsection "Docker Installation"

USER_NAME=$(get_actual_user)

# Check if Docker is already installed
if command_exists docker; then
    DOCKER_VERSION=$(docker --version)
    log_info "Docker already installed: ${DOCKER_VERSION}"
else
    log_info "Installing Docker..."
    
    # Remove old versions
    dnf remove -y docker docker-client docker-client-latest docker-common \
        docker-latest docker-latest-logrotate docker-logrotate docker-engine 2>/dev/null || true
    
    # Install Docker CE
    dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo || true
    dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    
    log_success "Docker installed: $(docker --version)"
fi

# Start and enable Docker service
log_info "Configuring Docker service..."
systemctl enable docker
systemctl start docker

# Add user to docker group
if ! groups "${USER_NAME}" | grep -q docker; then
    log_info "Adding ${USER_NAME} to docker group..."
    usermod -aG docker "${USER_NAME}"
    log_warning "User added to docker group - log out and back in for changes to take effect"
else
    log_info "User ${USER_NAME} already in docker group"
fi

# Verify Docker
log_subsection "Verifying Docker"

if systemctl is-active --quiet docker; then
    log_success "Docker service: running"
else
    log_error "Docker service not running!"
    exit 1
fi

# Test Docker (run as user if possible)
if docker info &>/dev/null; then
    log_success "Docker daemon: accessible"
else
    log_warning "Docker daemon not accessible (may need re-login for group membership)"
fi

# Docker Compose
if docker compose version &>/dev/null; then
    log_success "Docker Compose: $(docker compose version --short)"
else
    log_warning "Docker Compose plugin not available"
fi

################################################################################
# GitLab Container Registry - Pre-built Images
################################################################################
# 
# Pre-built container images are available from the GitLab registry.
# This avoids lengthy build times on new machines.
#
# Registry: registry.gitlab-licensed.vlab.noaa.gov/nws/operations/ncep/emc/eib/eib-mcp-rag-server
#
# Available images:
#   mcp-server:stable    - MCP RAG Server (Phase 19 Content Abstraction)
#   mcp-server:clean     - Same as stable, alternate tag
#   chromadb:v134clean   - ChromaDB with v2 API compatibility
#   n8n:latest           - n8n workflow automation (Phase 11E)
#
# Pull commands (requires GitLab authentication):
#   docker login registry.gitlab-licensed.vlab.noaa.gov
#   docker pull registry.gitlab-licensed.vlab.noaa.gov/nws/operations/ncep/emc/eib/eib-mcp-rag-server/mcp-server:stable
#   docker pull registry.gitlab-licensed.vlab.noaa.gov/nws/operations/ncep/emc/eib/eib-mcp-rag-server/chromadb:v134clean
#
# Tag for local use:
#   docker tag registry.gitlab-licensed.vlab.noaa.gov/nws/operations/ncep/emc/eib/eib-mcp-rag-server/mcp-server:stable eib-mcp-rag:latest
#
# Build note: When building locally, disable BuildKit attestations to avoid
# manifest issues with GitLab registry:
#   docker build --provenance=false --sbom=false -t eib-mcp-rag:latest ...
#
# TODO: Add automatic pull option in provisioning (Phase 20+)
################################################################################

################################################################################
# n8n Workflow Automation (Phase 11E)
################################################################################
log_subsection "n8n Workflow Automation Setup"

N8N_IMAGE="n8nio/n8n:latest"

# Check if n8n image exists
if docker image inspect "${N8N_IMAGE}" &>/dev/null; then
    log_info "n8n image already available: ${N8N_IMAGE}"
else
    log_info "Pulling n8n image..."
    if docker pull "${N8N_IMAGE}"; then
        log_success "n8n image pulled: ${N8N_IMAGE}"
    else
        log_warning "Failed to pull n8n image - will be pulled on first start"
    fi
fi

# Create n8n data volume if needed
if docker volume inspect n8n-devops-data &>/dev/null; then
    log_info "n8n volume already exists: n8n-devops-data"
else
    log_info "Creating n8n data volume..."
    docker volume create n8n-devops-data
    log_success "Created volume: n8n-devops-data"
fi

log_info "n8n service configured in docker-compose.devops.yaml"
log_info "Start with: docker compose -f docker-compose.devops.yaml up -d n8n"
log_info "Web UI: http://localhost:5678 (admin / eib-n8n-2025)"

log_success "Docker setup complete"

exit 0
