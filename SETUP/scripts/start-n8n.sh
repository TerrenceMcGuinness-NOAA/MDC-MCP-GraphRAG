#!/bin/bash
# start-n8n.sh - Start n8n workflow automation container
# Phase 11E: n8n as LangFlow alternative for MCP Gateway integration
#
# Usage:
#   ./start-n8n.sh [--background]
#   ./start-n8n.sh --stop
#   ./start-n8n.sh --status
#
# n8n Web UI: http://localhost:5678
# Default credentials: admin / eib-n8n-2025

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
COMPOSE_FILE="${PROJECT_ROOT}/docker-compose.devops.yaml"
CONTAINER_NAME="global-workflow-n8n"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

show_status() {
    echo "=== n8n Container Status ==="
    if docker ps --filter "name=${CONTAINER_NAME}" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -q "${CONTAINER_NAME}"; then
        docker ps --filter "name=${CONTAINER_NAME}" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
        echo ""
        log_info "n8n Web UI: http://localhost:5678"
        log_info "Credentials: admin / eib-n8n-2025"
    else
        log_warn "n8n container is not running"
        echo ""
        echo "To start: $0"
    fi
}

stop_n8n() {
    log_info "Stopping n8n container..."
    docker compose -f "${COMPOSE_FILE}" stop n8n
    log_info "n8n stopped"
}

start_n8n() {
    local background="${1:-false}"
    
    log_info "Starting n8n workflow automation..."
    
    # Check if already running
    if docker ps --filter "name=${CONTAINER_NAME}" --format "{{.Names}}" | grep -q "${CONTAINER_NAME}"; then
        log_warn "n8n is already running"
        show_status
        return 0
    fi
    
    # Pull latest image if needed
    log_info "Ensuring n8n image is available..."
    docker compose -f "${COMPOSE_FILE}" pull n8n
    
    # Start container
    if [[ "${background}" == "true" ]]; then
        log_info "Starting n8n in background..."
        docker compose -f "${COMPOSE_FILE}" up -d n8n
    else
        log_info "Starting n8n (foreground - Ctrl+C to stop)..."
        docker compose -f "${COMPOSE_FILE}" up n8n
    fi
    
    # Wait for health check (only in background mode)
    if [[ "${background}" == "true" ]]; then
        log_info "Waiting for n8n to be healthy..."
        sleep 5
        
        if docker ps --filter "name=${CONTAINER_NAME}" --filter "health=healthy" --format "{{.Names}}" | grep -q "${CONTAINER_NAME}"; then
            log_info "n8n is healthy and ready!"
        else
            log_warn "n8n is starting (health check may take a moment)"
        fi
        
        show_status
    fi
}

# Parse arguments
case "${1:-}" in
    --stop)
        stop_n8n
        ;;
    --status)
        show_status
        ;;
    --background|-d)
        start_n8n true
        ;;
    --help|-h)
        echo "Usage: $0 [OPTIONS]"
        echo ""
        echo "Options:"
        echo "  --background, -d  Start in background (detached)"
        echo "  --stop            Stop n8n container"
        echo "  --status          Show container status"
        echo "  --help, -h        Show this help"
        echo ""
        echo "n8n Web UI: http://localhost:5678"
        echo "Default credentials: admin / eib-n8n-2025"
        echo ""
        echo "MCP Gateway Integration:"
        echo "  Use HTTP Request node with:"
        echo "  - URL: http://host.docker.internal:8888/sse"
        echo "  - Auth: Bearer token from gateway startup"
        ;;
    *)
        start_n8n true
        ;;
esac
