#!/bin/bash
################################################################################
# start-mcp-gateway.sh - Start/Stop/Status MCP Gateway
# 
# Usage:
#   ./start-mcp-gateway.sh [start|stop|status|restart|foreground]
#
# Options:
#   start      - Start gateway via systemd (production)
#   stop       - Stop gateway
#   status     - Show gateway status
#   restart    - Restart gateway
#   foreground - Run gateway in foreground (development/debugging)
#   --port N   - Override port (default: 18888)
#
# Environment:
#   MCP_GATEWAY_AUTH_TOKEN - Bearer token for authentication (default: eib-mcp-gateway-token-2025)
################################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Defaults
PORT="${MCP_GATEWAY_PORT:-18888}"
AUTH_TOKEN="${MCP_GATEWAY_AUTH_TOKEN:-eib-mcp-gateway-token-2025}"
ACTION="${1:-status}"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        start|stop|status|restart|foreground)
            ACTION="$1"
            shift
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        -h|--help)
            head -20 "$0" | tail -18
            exit 0
            ;;
        *)
            shift
            ;;
    esac
done

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_ok() { echo -e "[${GREEN}OK${NC}] $1"; }
log_error() { echo -e "[${RED}ERROR${NC}] $1"; }
log_warn() { echo -e "[${YELLOW}WARN${NC}] $1"; }
log_info() { echo -e "[INFO] $1"; }

check_prereqs() {
    # Check docker-mcp plugin
    if [[ ! -x "${HOME}/.docker/cli-plugins/docker-mcp" ]]; then
        log_error "docker-mcp plugin not found. Run provisioning script 11-docker-mcp-gateway.sh"
        exit 1
    fi

    # Check if server is registered
    if ! docker mcp server ls 2>/dev/null | grep -q "eib-mcp-rag"; then
        log_warn "eib-mcp-rag server not registered in catalog"
        log_info "Run: docker mcp catalog create eib-local && docker mcp catalog add eib-local eib-mcp-rag ~/.docker/mcp/catalogs/eib-local.yaml && docker mcp server enable eib-mcp-rag"
    fi
}

start_systemd() {
    log_info "Starting MCP Gateway via systemd..."
    
    if [[ $EUID -ne 0 ]]; then
        sudo systemctl start mcp-gateway
    else
        systemctl start mcp-gateway
    fi
    
    sleep 3
    show_status
}

stop_gateway() {
    log_info "Stopping MCP Gateway..."
    
    # Try systemd first
    if systemctl is-active mcp-gateway &>/dev/null; then
        if [[ $EUID -ne 0 ]]; then
            sudo systemctl stop mcp-gateway
        else
            systemctl stop mcp-gateway
        fi
        log_ok "Stopped systemd service"
    fi
    
    # Kill any manual processes
    if pkill -f "docker-mcp.*gateway" 2>/dev/null; then
        log_ok "Stopped manual gateway process"
    fi
    
    sleep 2
    
    if lsof -i ":${PORT}" &>/dev/null; then
        log_warn "Port ${PORT} still in use"
    else
        log_ok "Port ${PORT} is free"
    fi
}

show_status() {
    echo ""
    echo "=== MCP Gateway Status ==="
    echo ""
    
    # Check systemd service
    if systemctl is-active mcp-gateway &>/dev/null; then
        log_ok "systemd service: active"
    else
        log_warn "systemd service: inactive"
    fi
    
    # Check port
    if lsof -i ":${PORT}" &>/dev/null; then
        log_ok "Port ${PORT}: listening"
        PID=$(lsof -t -i ":${PORT}" 2>/dev/null | head -1)
        log_info "  PID: ${PID}"
    else
        log_warn "Port ${PORT}: not listening"
    fi
    
    # Check tool count
    TOOL_COUNT=$(docker mcp tools ls 2>/dev/null | grep -c "^" || echo "0")
    if [[ "${TOOL_COUNT}" -gt 7 ]]; then
        log_ok "Tools registered: ${TOOL_COUNT} (${TOOL_COUNT} - 7 = $((TOOL_COUNT - 7)) EIB tools)"
    else
        log_warn "Tools registered: ${TOOL_COUNT} (only gateway built-ins)"
    fi
    
    # Connection info
    echo ""
    echo "=== Connection Info ==="
    echo "  URL: http://localhost:${PORT}/mcp"
    echo "  Token: ${AUTH_TOKEN}"
    echo "  Transport: Streamable HTTP (bidirectional)"
    echo ""
}

run_foreground() {
    check_prereqs
    stop_gateway
    
    log_info "Starting gateway in foreground on port ${PORT}..."
    log_info "Press Ctrl+C to stop"
    echo ""
    
    export MCP_GATEWAY_AUTH_TOKEN="${AUTH_TOKEN}"
    exec docker mcp gateway run \
        --servers eib-mcp-rag \
        --transport streaming \
        --port "${PORT}" \
        --long-lived \
        --verbose
}

case "${ACTION}" in
    start)
        check_prereqs
        start_systemd
        ;;
    stop)
        stop_gateway
        ;;
    status)
        show_status
        ;;
    restart)
        stop_gateway
        sleep 2
        start_systemd
        ;;
    foreground)
        run_foreground
        ;;
    *)
        log_error "Unknown action: ${ACTION}"
        echo "Usage: $0 [start|stop|status|restart|foreground]"
        exit 1
        ;;
esac
