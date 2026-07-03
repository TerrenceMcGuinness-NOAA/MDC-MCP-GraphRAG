#!/bin/bash
# DEPRECATED (Phase 63c, 2026-07-03): pairs with the retired eib-mcp-rag-static
# container. This script calls `systemctl restart mcp-rag` when the container
# is missing, so leaving it wired to cron resurrects the retired service. Kept
# in-tree only as Phase 63b rollback material. Do NOT install to /opt/mcp/bin/
# on new hosts. See .kiro/specs/retire-static-node-container/.

# MCP Gateway Health Check Script
# Runs via cron every 5 minutes
# Phase 23: Static Mode Multi-User Gateway

set -euo pipefail

CONTAINER_NAME="eib-mcp-rag-static"
GATEWAY_PORT=18888
LOG_FILE="/var/log/mcp-health.log"
ALERT_EMAIL="${MCP_ALERT_EMAIL:-}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "${LOG_FILE}"
}

alert() {
    log "ALERT: $1"
    if [[ -n "${ALERT_EMAIL}" ]]; then
        echo "$1" | mail -s "MCP Health Alert" "${ALERT_EMAIL}" 2>/dev/null || true
    fi
}

# Check 1: Container running
if ! docker ps --filter "name=${CONTAINER_NAME}" --filter "status=running" -q | grep -q .; then
    alert "Container ${CONTAINER_NAME} not running - restarting mcp-rag.service"
    systemctl restart mcp-rag
    sleep 30
fi

# Check 2: Gateway port responding
if ! ss -tlnp | grep -q ":${GATEWAY_PORT}"; then
    alert "Gateway port ${GATEWAY_PORT} not listening - restarting mcp-gateway.service"
    systemctl restart mcp-gateway
    sleep 10
fi

# Check 3: Container memory usage (warn at 75%, restart at 90%)
MEMORY_USAGE=$(docker stats --no-stream --format "{{.MemPerc}}" "${CONTAINER_NAME}" 2>/dev/null | tr -d '%')
if [[ -n "${MEMORY_USAGE}" ]]; then
    MEMORY_INT=${MEMORY_USAGE%.*}
    if (( MEMORY_INT > 90 )); then
        alert "Container memory at ${MEMORY_USAGE}% - restarting to clear"
        systemctl restart mcp-rag
    elif (( MEMORY_INT > 75 )); then
        log "WARN: Container memory at ${MEMORY_USAGE}%"
    fi
fi

# Check 4: ChromaDB connectivity (from container perspective)
if ! docker exec "${CONTAINER_NAME}" curl -sf "http://172.17.0.1:18080/api/v2/heartbeat" > /dev/null 2>&1; then
    log "WARN: ChromaDB heartbeat failed from container"
fi

# Check 5: Neo4j connectivity
if ! docker exec "${CONTAINER_NAME}" curl -sf "http://172.17.0.1:7474" > /dev/null 2>&1; then
    log "WARN: Neo4j web interface not responding"
fi

log "OK: All health checks passed"
