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
#   langflow:latest      - LangFlow AI workflow builder
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

log_success "Docker setup complete"

exit 0
