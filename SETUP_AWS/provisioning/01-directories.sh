#!/bin/bash
################################################################################
# 01-directories.sh — Create /mdc-mcp-rag persistent root and subdirectories
# Idempotent: mkdir -p is safe to re-run
################################################################################
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
require_root

log_section "Directory Structure"

OWNER=$(get_actual_user)

DIRS=(
  "${PERSISTENT_ROOT}"
  "${DATA_ROOT}"
  "${DATA_ROOT}/opensearch"
  "${DATA_ROOT}/neptune"
  "${DATA_ROOT}/mcp-server"
  "${DATA_ROOT}/mcp-server/logs"
  "${ETC_ROOT}"
  "${CACHE_ROOT}"
  "${CACHE_ROOT}/npm"
  "${CACHE_ROOT}/pip"
  "${CACHE_ROOT}/huggingface"
  "${MCP_ROOT}/logs"
  "${MCP_ROOT}/database"
)

for dir in "${DIRS[@]}"; do
  if [[ ! -d "${dir}" ]]; then
    mkdir -p "${dir}"
    log_info "Created: ${dir}"
  else
    log_info "Exists:  ${dir}"
  fi
done

chown -R "${OWNER}:${OWNER}" "${PERSISTENT_ROOT}"
log_success "Persistent root ready: ${PERSISTENT_ROOT} (owner: ${OWNER})"
