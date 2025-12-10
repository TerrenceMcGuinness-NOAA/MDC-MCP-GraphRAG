#!/bin/bash
################################################################################
# gitlab-registry-login.sh - Login to NOAA VLab GitLab Container Registry
#
# This script authenticates to the GitLab registry to enable pulling
# pre-built Docker images for the MCP RAG system.
#
# Usage:
#   ./gitlab-registry-login.sh                   # Interactive login
#   ./gitlab-registry-login.sh --check           # Check login status
#   ./gitlab-registry-login.sh --images          # List available images
#
# Registry: registry.gitlab-licensed.vlab.noaa.gov
# Project:  /nws/operations/ncep/emc/eib/eib-mcp-rag-server
#
# Available images:
#   - eib-mcp-rag-server:latest    (MCP Server - 32 tools)
#   - chromadb:latest              (Vector database)
#   - neo4j:5.15.0                 (Graph database)
#   - langflow:latest              (LangFlow UI)
################################################################################

set -euo pipefail

# GitLab registry configuration
GITLAB_REGISTRY="registry.gitlab-licensed.vlab.noaa.gov"
GITLAB_PROJECT="nws/operations/ncep/emc/eib/eib-mcp-rag-server"
REGISTRY_BASE="${GITLAB_REGISTRY}/${GITLAB_PROJECT}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

show_help() {
    echo ""
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --check     Check if already logged in to GitLab registry"
    echo "  --images    List images available in the registry"
    echo "  --pull      Pull all images from registry"
    echo "  --help      Show this help message"
    echo ""
    echo "Registry: ${GITLAB_REGISTRY}"
    echo "Project:  ${GITLAB_PROJECT}"
    echo ""
}

check_login() {
    log_info "Checking GitLab registry login status..."
    
    # Try to pull a small test (just the manifest)
    if docker manifest inspect "${REGISTRY_BASE}/chromadb:latest" > /dev/null 2>&1; then
        log_success "Logged in to ${GITLAB_REGISTRY}"
        return 0
    else
        log_warning "Not logged in or no access to ${GITLAB_REGISTRY}"
        return 1
    fi
}

list_images() {
    echo ""
    echo "=== Available Images in GitLab Registry ==="
    echo ""
    echo "Registry: ${GITLAB_REGISTRY}"
    echo "Project:  ${GITLAB_PROJECT}"
    echo ""
    echo "Images:"
    echo "  ${REGISTRY_BASE}:latest"
    echo "    - MCP Server with 32 tools (1.66GB / 452MB compressed)"
    echo ""
    echo "  ${REGISTRY_BASE}/chromadb:latest"
    echo "    - ChromaDB vector database (741MB / 153MB compressed)"
    echo ""
    echo "  ${REGISTRY_BASE}/neo4j:5.15.0"
    echo "    - Neo4j graph database (796MB / 292MB compressed)"
    echo ""
    echo "  ${REGISTRY_BASE}/langflow:latest"
    echo "    - LangFlow UI (15.7GB / 5.12GB compressed)"
    echo ""
    echo "Pull commands:"
    echo "  docker pull ${REGISTRY_BASE}:latest"
    echo "  docker pull ${REGISTRY_BASE}/chromadb:latest"
    echo "  docker pull ${REGISTRY_BASE}/neo4j:5.15.0"
    echo "  docker pull ${REGISTRY_BASE}/langflow:latest"
    echo ""
}

pull_images() {
    log_info "Pulling all images from GitLab registry..."
    echo ""
    
    local images=(
        "${REGISTRY_BASE}:latest"
        "${REGISTRY_BASE}/chromadb:latest"
        "${REGISTRY_BASE}/neo4j:5.15.0"
        "${REGISTRY_BASE}/langflow:latest"
    )
    
    local failed=0
    
    for image in "${images[@]}"; do
        log_info "Pulling ${image}..."
        if docker pull "${image}"; then
            log_success "Pulled: ${image}"
        else
            log_error "Failed: ${image}"
            ((failed++))
        fi
        echo ""
    done
    
    if [[ $failed -eq 0 ]]; then
        log_success "All images pulled successfully!"
    else
        log_warning "${failed} image(s) failed to pull"
    fi
    
    return $failed
}

do_login() {
    echo ""
    echo "=== GitLab Container Registry Login ==="
    echo ""
    echo "Registry: ${GITLAB_REGISTRY}"
    echo ""
    echo "Use your NOAA VLab GitLab credentials (username and access token)"
    echo "To create an access token:"
    echo "  1. Go to GitLab -> User Settings -> Access Tokens"
    echo "  2. Create token with 'read_registry' and 'write_registry' scopes"
    echo ""
    
    docker login "${GITLAB_REGISTRY}"
    
    if [[ $? -eq 0 ]]; then
        log_success "Login successful!"
        echo ""
        echo "You can now pull images:"
        echo "  docker pull ${REGISTRY_BASE}:latest"
        echo "  docker pull ${REGISTRY_BASE}/chromadb:latest"
        echo "  docker pull ${REGISTRY_BASE}/neo4j:5.15.0"
        echo "  docker pull ${REGISTRY_BASE}/langflow:latest"
        echo ""
        echo "Or use the provisioning scripts which will auto-pull."
    else
        log_error "Login failed"
        exit 1
    fi
}

# Main
case "${1:-}" in
    --check)
        check_login
        ;;
    --images)
        list_images
        ;;
    --pull)
        pull_images
        ;;
    --help|-h)
        show_help
        ;;
    *)
        do_login
        ;;
esac
