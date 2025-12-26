#!/bin/bash
################################################################################
# 01-directories.sh - Create MCP RAG directory structure
# Part of modular provisioning system v4.0.0
################################################################################

set -euo pipefail

# Source common library
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

require_root

log_subsection "Creating Directory Structure"

USER_NAME=$(get_actual_user)
USER_OWNERSHIP=$(get_ownership "${USER_NAME}")

# Core directories
DIRS=(
    "${PERSISTENT_ROOT}"
    "${DATA_ROOT}"
    "${DATA_ROOT}/chromadb"
    "${DATA_ROOT}/neo4j"
    "${DATA_ROOT}/neo4j/data"
    "${DATA_ROOT}/neo4j/logs"
    "${DATA_ROOT}/neo4j/import"
    "${DATA_ROOT}/neo4j/plugins"
    "${DATA_ROOT}/langflow"
    "${DATA_ROOT}/ecflow"
    "${ETC_ROOT}"
    "${CACHE_ROOT}"
    "${CACHE_ROOT}/npm"
    "${CACHE_ROOT}/pip"
    "${CACHE_ROOT}/transformers"
    "${CACHE_ROOT}/huggingface"
    "${MCP_ROOT}"
    "${MCP_ROOT}/logs"
    "${MCP_ROOT}/database"
)

for dir in "${DIRS[@]}"; do
    if [[ ! -d "${dir}" ]]; then
        mkdir -p "${dir}"
        log_info "Created: ${dir}"
    else
        log_info "Exists: ${dir}"
    fi
done

# Set ownership
log_info "Setting ownership to ${USER_OWNERSHIP}..."
chown -R "${USER_OWNERSHIP}" "${PERSISTENT_ROOT}"

# Verify
log_success "Directory structure created"
log_info "  Root: ${PERSISTENT_ROOT}"
log_info "  Data: ${DATA_ROOT}"
log_info "  Cache: ${CACHE_ROOT}"
log_info "  MCP Server: ${MCP_ROOT}"

exit 0
