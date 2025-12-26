#!/bin/bash
# start-mcp-gateway.sh - Start Docker MCP Gateway for LangFlow integration
#
# Usage:
#   ./start-mcp-gateway.sh [--port PORT] [--transport TRANSPORT] [--background]
#
# Options:
#   --port PORT       Gateway port (default: 8888)
#   --transport TYPE  Transport type: sse, streamable-http, stdio (default: sse)
#   --background      Run gateway in background
#   --help            Show this help message
#
# Requirements:
#   - Docker MCP CLI plugin installed (~/.docker/cli-plugins/docker-mcp)
#   - eib-mcp-rag:latest image built
#   - MCP catalog configured (~/.docker/mcp/catalogs/eib-local.yaml)
#
# Part of Phase 11: Docker MCP Gateway + LangFlow Integration
# See: sdd_framework/workflows/phase11_docker_mcp_gateway_langflow.md

set -euo pipefail

# =============================================================================
# Configuration
# =============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Defaults
GATEWAY_PORT="${GATEWAY_PORT:-8888}"
TRANSPORT="${TRANSPORT:-sse}"
BACKGROUND=false
SERVER_NAME="eib-mcp-rag"

# Fixed token for VS Code mcp.json (avoids token changing on each restart)
# Set MCP_GATEWAY_AUTH_TOKEN env var to override this default
export MCP_GATEWAY_AUTH_TOKEN="${MCP_GATEWAY_AUTH_TOKEN:-eib-mcp-gateway-token-2025}"

# Colors for output (ASCII only - no emoji)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# =============================================================================
# Functions
# =============================================================================
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

show_help() {
    head -25 "$0" | grep "^#" | sed 's/^# \?//'
    exit 0
}

check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check docker-mcp plugin
    if ! docker mcp --version &>/dev/null; then
        log_error "Docker MCP CLI plugin not installed"
        log_info "Install with: cd supported_repos/mcp-gateway && make docker-mcp"
        exit 1
    fi
    log_success "Docker MCP plugin: $(docker mcp --version 2>&1 | head -1)"
    
    # Check eib-mcp-rag image
    if ! docker image inspect eib-mcp-rag:latest &>/dev/null; then
        log_error "eib-mcp-rag:latest image not found"
        log_info "Build with: docker compose -f docker-compose.mcp-standalone.yaml build"
        exit 1
    fi
    log_success "eib-mcp-rag:latest image found"
    
    # Check MCP catalog
    local catalog_file="$HOME/.docker/mcp/catalogs/eib-local.yaml"
    if [[ ! -f "$catalog_file" ]]; then
        log_warn "MCP catalog not found, creating..."
        setup_mcp_catalog
    fi
    log_success "MCP catalog configured"
    
    # Check if port is in use
    if lsof -i ":${GATEWAY_PORT}" &>/dev/null; then
        log_warn "Port ${GATEWAY_PORT} is in use"
        local pid=$(lsof -ti ":${GATEWAY_PORT}" 2>/dev/null | head -1)
        log_info "Process using port: $(ps -p $pid -o comm= 2>/dev/null || echo 'unknown')"
        read -p "Kill existing process? [y/N] " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            pkill -f "docker-mcp.*${GATEWAY_PORT}" 2>/dev/null || true
            sleep 2
        else
            log_error "Cannot start gateway - port in use"
            exit 1
        fi
    fi
    log_success "Port ${GATEWAY_PORT} is available"
}

setup_mcp_catalog() {
    local catalog_dir="$HOME/.docker/mcp/catalogs"
    local catalog_file="${catalog_dir}/eib-local.yaml"
    
    mkdir -p "$catalog_dir"
    
    cat > "$catalog_file" << 'EOF'
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
        value: chromadb
      - name: CHROMADB_PORT
        value: "8000"
      - name: NEO4J_URI
        value: bolt://global-workflow-neo4j:7687
      - name: NEO4J_USER
        value: neo4j
      - name: NEO4J_PASSWORD
        value: gfsworkflow2025
      - name: MCP_SCENARIO
        value: full
    metadata:
      category: devops
EOF
    
    log_success "Created MCP catalog: $catalog_file"
}

setup_mcp_registry() {
    local registry_file="$HOME/.docker/mcp/registry.yaml"
    
    cat > "$registry_file" << 'EOF'
registry:
  eib-mcp-rag:
    type: image
    ref: eib-mcp-rag:latest
    description: "EIB MCP RAG Server - AI-powered code analysis and compliance checking"
    config:
      network: global-workflow-mcp-rag
      environment:
        CHROMADB_HOST: chromadb
        CHROMADB_PORT: "8000"
        NEO4J_URI: bolt://global-workflow-neo4j:7687
        NEO4J_USER: neo4j
        NEO4J_PASSWORD: gfsworkflow2025
        MCP_SCENARIO: full
        ENABLE_RAG: "true"
        ENABLE_GITHUB: "true"
EOF
    
    log_success "Created MCP registry: $registry_file"
}

start_gateway() {
    log_info "Starting Docker MCP Gateway..."
    log_info "  Server: ${SERVER_NAME}"
    log_info "  Port: ${GATEWAY_PORT}"
    log_info "  Transport: ${TRANSPORT}"
    
    local cmd="docker mcp gateway run"
    cmd+=" --servers ${SERVER_NAME}"
    cmd+=" --transport ${TRANSPORT}"
    cmd+=" --port ${GATEWAY_PORT}"
    cmd+=" --long-lived"
    cmd+=" --verbose"
    
    if [[ "$BACKGROUND" == "true" ]]; then
        log_info "Starting in background..."
        nohup $cmd > /tmp/mcp-gateway.log 2>&1 &
        local pid=$!
        sleep 5
        
        if ps -p $pid &>/dev/null; then
            log_success "Gateway started (PID: $pid)"
            log_info "Logs: /tmp/mcp-gateway.log"
            
            # Extract bearer token from log
            local token=$(grep -o "Bearer [a-z0-9]*" /tmp/mcp-gateway.log 2>/dev/null | head -1 | cut -d' ' -f2)
            if [[ -n "$token" ]]; then
                echo ""
                log_success "Gateway URL: http://localhost:${GATEWAY_PORT}/${TRANSPORT}"
                log_success "Bearer Token: $token"
                echo ""
                log_info "LangFlow Configuration:"
                echo "  URL: http://host.docker.internal:${GATEWAY_PORT}/${TRANSPORT}"
                echo "  Headers: Authorization: Bearer $token"
            fi
        else
            log_error "Gateway failed to start"
            cat /tmp/mcp-gateway.log
            exit 1
        fi
    else
        log_info "Starting in foreground (Ctrl+C to stop)..."
        echo ""
        exec $cmd
    fi
}

configure_langflow() {
    local langflow_url="${LANGFLOW_URL:-http://localhost:7860}"
    local gateway_token="$1"
    
    log_info "Configuring LangFlow MCP server..."
    
    # Login to LangFlow
    local lf_token=$(curl -s -X POST "${langflow_url}/api/v1/login" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "username=admin&password=admin123" 2>/dev/null | \
        python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)
    
    if [[ -z "$lf_token" ]]; then
        log_warn "Could not login to LangFlow - configure manually"
        return
    fi
    
    # Delete existing server config
    curl -s -X DELETE "${langflow_url}/api/v2/mcp/servers/${SERVER_NAME}" \
        -H "Authorization: Bearer $lf_token" &>/dev/null || true
    
    # Create new server config
    local result=$(curl -s -X POST "${langflow_url}/api/v2/mcp/servers/${SERVER_NAME}" \
        -H "Authorization: Bearer $lf_token" \
        -H "Content-Type: application/json" \
        -d "{
            \"transport\": \"sse\",
            \"url\": \"http://host.docker.internal:${GATEWAY_PORT}/sse\",
            \"headers\": {
                \"Authorization\": \"Bearer ${gateway_token}\"
            }
        }" 2>/dev/null)
    
    if [[ -n "$result" ]]; then
        log_success "LangFlow MCP server configured"
    else
        log_warn "Could not configure LangFlow - configure manually"
    fi
}

# =============================================================================
# Main
# =============================================================================
main() {
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --port)
                GATEWAY_PORT="$2"
                shift 2
                ;;
            --transport)
                TRANSPORT="$2"
                shift 2
                ;;
            --background)
                BACKGROUND=true
                shift
                ;;
            --help|-h)
                show_help
                ;;
            *)
                log_error "Unknown option: $1"
                show_help
                ;;
        esac
    done
    
    echo ""
    echo "=================================="
    echo "  Docker MCP Gateway Startup"
    echo "  Phase 11: LangFlow Integration"
    echo "=================================="
    echo ""
    
    check_prerequisites
    setup_mcp_registry
    start_gateway
}

main "$@"
