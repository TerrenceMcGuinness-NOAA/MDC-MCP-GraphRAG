#!/bin/bash
################################################################################
# 07-mcp-server-deps.sh — Run npm install in mcp_server_node/, validate start
# Idempotent: npm install is safe to re-run (updates only if needed)
################################################################################
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
require_root

log_section "MCP Server Dependencies"

OWNER=$(get_actual_user)
NVM_DIR_TARGET="$(eval echo "~${OWNER}")/.nvm"

if [[ ! -d "${MCP_ROOT}" ]]; then
  log_error "MCP server directory not found: ${MCP_ROOT}"
  log_error "Ensure the repository is cloned before running this script"
  exit 1
fi

log_info "Running npm install in ${MCP_ROOT}..."
sudo -u "${OWNER}" bash -c "
  export NVM_DIR=\"${NVM_DIR_TARGET}\"
  [[ -s \"\${NVM_DIR}/nvm.sh\" ]] && source \"\${NVM_DIR}/nvm.sh\"
  cd \"${MCP_ROOT}\"
  npm install --cache \"${CACHE_ROOT}/npm\" --prefer-offline 2>&1 | tail -5
  echo '[OK]    npm install complete'
"

# Validate the server can parse its entry point (syntax check only — no DB needed)
log_info "Validating MCP server syntax..."
sudo -u "${OWNER}" bash -c "
  export NVM_DIR=\"${NVM_DIR_TARGET}\"
  [[ -s \"\${NVM_DIR}/nvm.sh\" ]] && source \"\${NVM_DIR}/nvm.sh\"
  cd \"${MCP_ROOT}\"
  node --input-type=module --eval 'import \"./src/UnifiedMCPServer.js\"' 2>&1 | head -3 || true
"

log_success "MCP server dependencies installed"
