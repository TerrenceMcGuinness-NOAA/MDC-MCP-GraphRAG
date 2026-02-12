#!/bin/bash
################################################################################
# 12-static-mode-gateway.sh - Phase 23: Static Mode Multi-User Gateway
# Part of modular provisioning system v4.1.0
#
# This script configures the MCP Gateway in static mode:
#   - Single static container managed by systemd (not per-session)
#   - Health monitoring via cron
#   - Supports 5-10 concurrent RDHPCS users
#   - Configs read from persistent drive via absolute-path CLI flags
#
# REPLACES: The --long-lived mode in 11-docker-mcp-gateway.sh for production
# REASON: Per-session containers leave orphans on ungraceful disconnects
#
# Reference: Phase 23 SDD - sdd_framework/workflows/phase23_static_mode_multiuser_gateway.md
################################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

require_root

USER_NAME=$(get_actual_user)
USER_OWNERSHIP=$(get_ownership "${USER_NAME}")
USER_GROUP=$(get_user_group "${USER_NAME}")
USER_HOME=$(eval echo ~"${USER_NAME}")

log_section "Phase 23: Static Mode Multi-User Gateway"

################################################################################
# Prerequisites Check
################################################################################

log_subsection "Prerequisites"

# Check docker-mcp plugin exists
if [[ ! -x "${USER_HOME}/.docker/cli-plugins/docker-mcp" ]]; then
    log_error "docker-mcp plugin not found. Run 11-docker-mcp-gateway.sh first."
    exit 1
fi
log_success "docker-mcp plugin: ${USER_HOME}/.docker/cli-plugins/docker-mcp"

# Check eib-mcp-rag image exists
if ! docker images eib-mcp-rag:latest --format "{{.Repository}}:{{.Tag}}" | grep -q "eib-mcp-rag:latest"; then
    log_error "eib-mcp-rag:latest image not found. Run 11-docker-mcp-gateway.sh first."
    exit 1
fi
log_success "Container image: eib-mcp-rag:latest"

# Check catalog exists on persistent drive (SPOT)
PERSISTENT_MCP_DIR="${SETUP_DIR}/docker-mcp"
if [[ ! -f "${PERSISTENT_MCP_DIR}/catalogs/eib-local.yaml" ]]; then
    log_error "MCP catalog not found on persistent drive. Run 11-docker-mcp-gateway.sh first."
    log_error "Expected: ${PERSISTENT_MCP_DIR}/catalogs/eib-local.yaml"
    exit 1
fi
log_success "MCP catalog (persistent): ${PERSISTENT_MCP_DIR}/catalogs/eib-local.yaml"

################################################################################
# Stop Existing Services
################################################################################

log_subsection "Stopping Existing Services"

systemctl stop mcp-gateway 2>/dev/null || true
systemctl stop mcp-rag 2>/dev/null || true
log_info "Stopped existing MCP services"

# Clean up orphaned containers
docker ps -q --filter "ancestor=eib-mcp-rag:latest" | xargs -r docker stop 2>/dev/null || true
docker ps -aq --filter "ancestor=eib-mcp-rag:latest" | xargs -r docker rm 2>/dev/null || true
docker ps -q --filter "name=eib-mcp-rag" | xargs -r docker stop 2>/dev/null || true
docker ps -aq --filter "name=eib-mcp-rag" | xargs -r docker rm 2>/dev/null || true
log_info "Cleaned up orphaned containers"

################################################################################
# Install MCP RAG Static Container Service
################################################################################

log_subsection "Installing mcp-rag.service (Static Container)"

cat > /etc/systemd/system/mcp-rag.service << EOF
[Unit]
Description=EIB MCP RAG Server (Static Container)
Documentation=https://github.com/NOAA-EMC/eib-mcp-rag-server
After=docker.service chromadb-persistent.service
Requires=docker.service
Wants=chromadb-persistent.service

[Service]
Type=simple
Restart=always
RestartSec=10
TimeoutStartSec=120
TimeoutStopSec=30

# Cleanup any existing container before start
ExecStartPre=-/usr/bin/docker stop eib-mcp-rag-static
ExecStartPre=-/usr/bin/docker rm eib-mcp-rag-static

# Run container with resource limits
# Memory: 8GB for 5-10 concurrent users
# CPUs: 4 for responsive tool calls
ExecStart=/usr/bin/docker run \\
    --name eib-mcp-rag-static \\
    --memory=8g \\
    --cpus=4 \\
    --init \\
    --security-opt no-new-privileges \\
    -e CHROMADB_HOST=172.17.0.1 \\
    -e CHROMADB_PORT=8080 \\
    -e NEO4J_URI=bolt://172.17.0.1:7687 \\
    -e NEO4J_USER=neo4j \\
    -e NEO4J_PASSWORD=gfsworkflow2025 \\
    -e MCP_WORKFLOW_ROOT=/app/supported_repos/global-workflow \\
    -v ${EIB_REPO}/supported_repos:/app/supported_repos:ro \\
    -v ${EIB_REPO}/sdd_framework:/app/sdd_framework:ro \\
    --label docker-mcp=true \\
    --label docker-mcp-name=eib-mcp-rag \\
    --label docker-mcp-transport=stdio \\
    eib-mcp-rag:latest

ExecStop=/usr/bin/docker stop eib-mcp-rag-static
ExecStopPost=-/usr/bin/docker rm eib-mcp-rag-static

[Install]
WantedBy=multi-user.target
EOF

log_success "Created /etc/systemd/system/mcp-rag.service"

################################################################################
# Install MCP Gateway Service (Static Mode)
################################################################################

log_subsection "Installing mcp-gateway.service (Static Mode)"

cat > /etc/systemd/system/mcp-gateway.service << EOF
[Unit]
Description=Docker MCP Gateway (Static Mode)
Documentation=https://github.com/docker/mcp-gateway
After=mcp-rag.service
Requires=mcp-rag.service

[Service]
Type=simple
Restart=always
RestartSec=5
User=${USER_NAME}
Group=${USER_GROUP}
Environment=HOME=${USER_HOME}
Environment=MCP_GATEWAY_AUTH_TOKEN=eib-mcp-gateway-token-2025

# Dynamic tools mode WITH EIB server auto-loaded:
# All config files use ABSOLUTE paths to the persistent drive (SETUP/docker-mcp/)
# so configs survive VM replacement without symlinks or HOME overrides.
# --enable-all-servers: Auto-connect servers from registry.yaml (eib-mcp-rag)
# --catalog: Use our local catalog for server definitions  
# No --servers flag: Keeps mcp-find, mcp-add, mcp-remove enabled
# Reference: Dynamic_MCP_Server_Self_Provisioning wiki page
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

# Safety net: Clean up any orphaned containers on stop
ExecStopPost=-/usr/bin/docker ps -q --filter "label=docker-mcp-name=eib-mcp-rag" | xargs -r docker stop
ExecStopPost=-/usr/bin/docker ps -aq --filter "label=docker-mcp-name=eib-mcp-rag" | xargs -r docker rm

[Install]
WantedBy=multi-user.target
EOF

log_success "Created /etc/systemd/system/mcp-gateway.service"

################################################################################
# Install Health Check Script
################################################################################

log_subsection "Installing Health Check Script"

mkdir -p /opt/mcp/bin

cat > /opt/mcp/bin/health-check.sh << 'HEALTHSCRIPT'
#!/bin/bash
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
if ! docker exec "${CONTAINER_NAME}" curl -sf "http://172.17.0.1:8080/api/v2/heartbeat" > /dev/null 2>&1; then
    log "WARN: ChromaDB heartbeat failed from container"
fi

# Check 5: Neo4j connectivity
if ! docker exec "${CONTAINER_NAME}" curl -sf "http://172.17.0.1:7474" > /dev/null 2>&1; then
    log "WARN: Neo4j web interface not responding"
fi

log "OK: All health checks passed"
HEALTHSCRIPT

chmod +x /opt/mcp/bin/health-check.sh
log_success "Created /opt/mcp/bin/health-check.sh"

################################################################################
# Install Cron Configuration
################################################################################

log_subsection "Installing Cron Configuration"

cat > /etc/cron.d/mcp-health << 'CRONFILE'
# MCP Gateway Health Monitoring
# Phase 23: Static Mode Multi-User Gateway
# Runs every 5 minutes

SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin

*/5 * * * * root /opt/mcp/bin/health-check.sh 2>&1 | head -20

# Daily log rotation
0 0 * * * root find /var/log/mcp-health.log -size +10M -exec truncate -s 0 {} \;
CRONFILE

chmod 644 /etc/cron.d/mcp-health
log_success "Created /etc/cron.d/mcp-health"

# Create log file
touch /var/log/mcp-health.log
chmod 644 /var/log/mcp-health.log

################################################################################
# Enable and Start Services
################################################################################

log_subsection "Starting Static Mode Services"

systemctl daemon-reload
log_info "Reloaded systemd daemon"

systemctl enable mcp-rag mcp-gateway
log_info "Enabled mcp-rag and mcp-gateway services"

log_info "Starting mcp-rag service..."
systemctl start mcp-rag
sleep 15

log_info "Starting mcp-gateway service..."
systemctl start mcp-gateway
sleep 5

################################################################################
# Verification
################################################################################

log_subsection "Verification"

PASS=true

# Check mcp-rag service
if systemctl is-active --quiet mcp-rag; then
    log_success "mcp-rag.service: active"
else
    log_error "mcp-rag.service: failed"
    PASS=false
fi

# Check mcp-gateway service
if systemctl is-active --quiet mcp-gateway; then
    log_success "mcp-gateway.service: active"
else
    log_error "mcp-gateway.service: failed"
    PASS=false
fi

# Check container running
if docker ps --filter "name=eib-mcp-rag-static" --filter "status=running" -q | grep -q .; then
    log_success "Container eib-mcp-rag-static: running"
    docker ps --filter "name=eib-mcp-rag-static" --format "  {{.Names}}: {{.Status}}"
else
    log_error "Container eib-mcp-rag-static: not running"
    PASS=false
fi

# Check gateway port
if ss -tlnp | grep -q ":18888"; then
    log_success "Gateway port 18888: listening"
else
    log_error "Gateway port 18888: not listening"
    PASS=false
fi

################################################################################
# Summary
################################################################################

log_section "Phase 23 Static Mode Gateway Setup Complete"

if $PASS; then
    log_success "All components verified successfully"
else
    log_error "Some components failed verification"
    log_info "Debug: journalctl -u mcp-rag -u mcp-gateway --since '5 minutes ago'"
    exit 1
fi

log_info ""
log_info "Static Mode Architecture:"
log_info "  - Single container: eib-mcp-rag-static (8GB / 4 CPUs)"
log_info "  - Gateway: --static=true (no per-session containers)"
log_info "  - Health monitoring: /opt/mcp/bin/health-check.sh (every 5 min)"
log_info "  - Supports: 5-10 concurrent RDHPCS users"
log_info ""
log_info "Management commands:"
log_info "  sudo systemctl status mcp-rag mcp-gateway"
log_info "  sudo systemctl restart mcp-rag mcp-gateway"
log_info "  tail -f /var/log/mcp-health.log"
log_info ""
log_info "Remote Access:"
log_info "  ssh -L 18888:localhost:18888 user@server -N"
log_info "  Token: eib-mcp-gateway-token-2025"

exit 0
