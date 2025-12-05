#!/bin/bash
################################################################################
# 06-chromadb.sh - ChromaDB Docker container setup
# Part of modular provisioning system v4.0.0
################################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

require_root

log_subsection "ChromaDB Docker Setup"

USER_NAME=$(get_actual_user)
CHROMADB_DATA="${DATA_ROOT}/chromadb"
CHROMADB_CONTAINER="chromadb-server"

# Ensure data directory exists
mkdir -p "${CHROMADB_DATA}"
chown -R "${USER_NAME}:${USER_NAME}" "${CHROMADB_DATA}"

# Check if container already exists
if docker ps -a --format '{{.Names}}' | grep -q "^${CHROMADB_CONTAINER}$"; then
    log_info "ChromaDB container already exists"
    
    if docker ps --format '{{.Names}}' | grep -q "^${CHROMADB_CONTAINER}$"; then
        log_info "ChromaDB container is running"
    else
        log_info "Starting existing ChromaDB container..."
        docker start "${CHROMADB_CONTAINER}"
    fi
else
    log_info "Creating ChromaDB container..."
    
    docker run -d \
        --name "${CHROMADB_CONTAINER}" \
        --restart unless-stopped \
        -p "${CHROMADB_PORT}:8000" \
        -v "${CHROMADB_DATA}:/chroma/chroma" \
        -e IS_PERSISTENT=TRUE \
        -e ANONYMIZED_TELEMETRY=FALSE \
        chromadb/chroma:latest
    
    log_success "ChromaDB container created"
fi

# Wait for ChromaDB to be ready
log_info "Waiting for ChromaDB to be ready..."
if wait_for_service "${CHROMADB_URL}/api/v1/heartbeat" 60; then
    log_success "ChromaDB is ready at ${CHROMADB_URL}"
else
    log_error "ChromaDB failed to start within 60 seconds"
    docker logs "${CHROMADB_CONTAINER}" --tail 20
    exit 1
fi

################################################################################
# ChromaDB Systemd Service
################################################################################

log_subsection "ChromaDB Systemd Service"

SERVICE_FILE="/etc/systemd/system/chromadb-persistent.service"

cat > "${SERVICE_FILE}" << EOF
[Unit]
Description=ChromaDB Docker Container
After=docker.service
Requires=docker.service

[Service]
Type=simple
Restart=always
RestartSec=5
ExecStartPre=-/usr/bin/docker stop ${CHROMADB_CONTAINER}
ExecStartPre=-/usr/bin/docker rm ${CHROMADB_CONTAINER}
ExecStart=/usr/bin/docker run --rm \\
    --name ${CHROMADB_CONTAINER} \\
    -p ${CHROMADB_PORT}:8000 \\
    -v ${CHROMADB_DATA}:/chroma/chroma \\
    -e IS_PERSISTENT=TRUE \\
    -e ANONYMIZED_TELEMETRY=FALSE \\
    chromadb/chroma:latest
ExecStop=/usr/bin/docker stop ${CHROMADB_CONTAINER}

[Install]
WantedBy=multi-user.target
EOF

log_info "Created systemd service: chromadb-persistent.service"

# Reload systemd and enable service
systemctl daemon-reload
systemctl enable chromadb-persistent.service

log_success "ChromaDB systemd service configured"

# Verify
log_subsection "Verifying ChromaDB"

HEARTBEAT=$(curl -s "${CHROMADB_URL}/api/v1/heartbeat" | jq -r '.["nanosecond heartbeat"]' 2>/dev/null || echo "error")
if [[ "${HEARTBEAT}" != "error" ]] && [[ "${HEARTBEAT}" != "null" ]]; then
    log_success "ChromaDB heartbeat: ${HEARTBEAT}"
else
    log_warning "ChromaDB heartbeat check failed"
fi

COLLECTIONS=$(curl -s "${CHROMADB_URL}/api/v1/collections" | jq 'length' 2>/dev/null || echo "0")
log_info "ChromaDB collections: ${COLLECTIONS}"

log_success "ChromaDB setup complete"
log_info "  URL: ${CHROMADB_URL}"
log_info "  Data: ${CHROMADB_DATA}"
log_info "  Service: chromadb-persistent.service"

exit 0
