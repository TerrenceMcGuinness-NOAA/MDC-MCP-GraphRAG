#!/bin/bash
################################################################################
# 08-services.sh - Docker Compose services (Neo4j, ecFlow) and systemd
# Part of modular provisioning system v4.0.0
################################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

require_root

log_subsection "Docker Compose Services"

USER_NAME=$(get_actual_user)
USER_OWNERSHIP=$(get_ownership "${USER_NAME}")
USER_GROUP=$(get_user_group "${USER_NAME}")
COMPOSE_FILE="${SETUP_DIR}/docker-compose.yml"

# Check if docker-compose.yml exists
if [[ ! -f "${COMPOSE_FILE}" ]]; then
    log_error "docker-compose.yml not found: ${COMPOSE_FILE}"
    exit 1
fi

cd "${SETUP_DIR}"

################################################################################
# Neo4j Setup
################################################################################

log_subsection "Neo4j Graph Database"

NEO4J_DATA="${DATA_ROOT}/neo4j"

# Ensure Neo4j directories exist
mkdir -p "${NEO4J_DATA}"/{data,logs,import,plugins}
chown -R "${USER_OWNERSHIP}" "${NEO4J_DATA}"

# Start Neo4j
log_info "Starting Neo4j container..."
docker compose up -d neo4j || {
    log_warning "Neo4j start failed, trying to build first..."
    docker compose build neo4j
    docker compose up -d neo4j
}

# Wait for Neo4j
log_info "Waiting for Neo4j to be ready..."
if wait_for_service "http://localhost:${NEO4J_HTTP_PORT}" 90; then
    log_success "Neo4j is ready at http://localhost:${NEO4J_HTTP_PORT}"
else
    log_warning "Neo4j may not be fully ready yet"
fi

################################################################################
# LangFlow - REMOVED (January 2026)
# Reason: Inherent bugs in workflow import functionality
# Replacement: n8n in docker-compose.devops.yaml (JSON workflow API)
# See: Phase 11E in sdd_framework/PRIORITY_ROADMAP.md
################################################################################

log_subsection "Workflow Automation (n8n)"
log_info "n8n workflow automation available in docker-compose.devops.yaml"
log_info "For DevOps/CI pipelines: docker compose -f docker-compose.devops.yaml up -d n8n"

################################################################################
# MCP Server Systemd Service
################################################################################

log_subsection "MCP Server Systemd Service"

SERVICE_FILE="/etc/systemd/system/mcp-server-persistent.service"

cat > "${SERVICE_FILE}" << EOF
[Unit]
Description=MCP RAG Server (Node.js)
After=network.target chromadb-persistent.service docker.service
Wants=chromadb-persistent.service

[Service]
Type=simple
User=${USER_NAME}
Group=${USER_GROUP}
WorkingDirectory=${MCP_ROOT}
Environment=NODE_ENV=production
Environment=CHROMADB_URL=${CHROMADB_URL}
Environment=MCP_ROOT=${MCP_ROOT}
Environment=PERSISTENT_ROOT=${PERSISTENT_ROOT}
ExecStart=/usr/bin/node ${MCP_ROOT}/src/UnifiedMCPServer.js full
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

log_info "Created systemd service: mcp-server-persistent.service"

# Reload systemd
systemctl daemon-reload

# Enable but don't start (VS Code MCP handles startup)
systemctl enable mcp-server-persistent.service

log_success "MCP server systemd service configured (not started - VS Code MCP will manage)"

################################################################################
# Show Service Status
################################################################################

log_subsection "Service Status"

echo ""
docker compose ps 2>/dev/null || true
echo ""

log_success "Services setup complete"
log_info "  Neo4j: http://localhost:${NEO4J_HTTP_PORT} (neo4j/${NEO4J_PASSWORD})"
log_info "  ChromaDB: ${CHROMADB_URL}"
log_info "  MCP Server: systemctl status mcp-server-persistent.service"

exit 0
