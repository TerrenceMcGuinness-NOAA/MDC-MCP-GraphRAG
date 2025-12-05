#!/bin/bash
################################################################################
# 08-services.sh - Docker Compose services (Neo4j, LangFlow) and systemd
# Part of modular provisioning system v4.0.0
################################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

require_root

log_subsection "Docker Compose Services"

USER_NAME=$(get_actual_user)
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
chown -R "${USER_NAME}:${USER_NAME}" "${NEO4J_DATA}"

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
# LangFlow Setup (Optional)
################################################################################

log_subsection "LangFlow (Optional)"

# Check if LangFlow is defined in docker-compose
if docker compose config --services 2>/dev/null | grep -q "langflow"; then
    log_info "Starting LangFlow container..."
    docker compose up -d langflow || log_warning "LangFlow start failed"
    
    if wait_for_service "http://localhost:7860/api/v1/health" 60; then
        log_success "LangFlow is ready at http://localhost:7860"
    else
        log_warning "LangFlow may not be fully ready yet"
    fi
else
    log_info "LangFlow not defined in docker-compose.yml, skipping"
fi

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
Group=${USER_NAME}
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
