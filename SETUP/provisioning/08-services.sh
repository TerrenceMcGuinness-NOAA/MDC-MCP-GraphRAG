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

# Ensure Neo4j support directories exist (data is in Docker volume neo4j_data)
mkdir -p "${NEO4J_DATA}"/{logs,import,plugins}
chown -R "${USER_OWNERSHIP}" "${NEO4J_DATA}"

# Ensure the external Docker volume exists (contains Phase 10 Fortran graph data)
if ! docker volume inspect neo4j_data &>/dev/null; then
    log_warning "Docker volume 'neo4j_data' not found - creating empty volume"
    docker volume create neo4j_data
fi

# Remove stale containers that conflict with the compose-managed 'neo4j' container
for stale in "global-workflow-neo4j"; do
    if docker ps -a --format '{{.Names}}' | grep -q "^${stale}$"; then
        log_info "Removing stale container: ${stale}"
        docker rm -f "${stale}" 2>/dev/null || true
    fi
done

# Start Neo4j via compose
log_info "Starting Neo4j container..."
docker compose up -d neo4j || {
    log_warning "Neo4j start failed, retrying after removing conflicting container..."
    docker rm -f neo4j 2>/dev/null || true
    docker compose up -d neo4j
}

# Wait for Neo4j
log_info "Waiting for Neo4j to be ready..."
if wait_for_service "http://localhost:${NEO4J_HTTP_PORT}" 90; then
    log_success "Neo4j is ready at http://localhost:${NEO4J_HTTP_PORT}"
else
    log_warning "Neo4j may not be fully ready yet"
fi

# Install cypher-shell CLI (matches Neo4j 5.x in Docker)
log_info "Installing cypher-shell CLI..."
if command_exists cypher-shell; then
    log_info "cypher-shell already installed: $(cypher-shell --version 2>&1)"
else
    rpm --import https://debian.neo4j.com/neotechnology.gpg.key 2>/dev/null || true
    if [[ ! -f /etc/yum.repos.d/neo4j.repo ]]; then
        cat > /etc/yum.repos.d/neo4j.repo <<'REPO'
[neo4j]
name=Neo4j RPM Repository
baseurl=https://yum.neo4j.com/stable/5
enabled=1
gpgcheck=1
gpgkey=https://debian.neo4j.com/neotechnology.gpg.key
REPO
    fi
    if dnf install -y cypher-shell &>/dev/null; then
        log_success "cypher-shell installed: $(cypher-shell --version 2>&1)"
    else
        log_warning "Failed to install cypher-shell - manual install may be required"
    fi
fi

################################################################################
# n8n Workflow Automation (Replaced LangFlow - January 2026)
# Reason: LangFlow had bugs in workflow import; n8n has superior JSON API
# See: Phase 11E in sdd_framework/PRIORITY_ROADMAP.md
################################################################################

log_subsection "n8n Workflow Automation"

# Check if n8n is defined in docker-compose
if docker compose config --services 2>/dev/null | grep -q "n8n"; then
    log_info "Starting n8n container..."
    docker compose up -d n8n || log_warning "n8n start failed"
    
    if wait_for_service "http://localhost:5678/healthz" 60; then
        log_success "n8n is ready at http://localhost:5678"
        log_info "Credentials: admin / eib-n8n-2025"
    else
        log_warning "n8n may not be fully ready yet"
    fi
else
    log_info "n8n not defined in docker-compose.yml, skipping"
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
