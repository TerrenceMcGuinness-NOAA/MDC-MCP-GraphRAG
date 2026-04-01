#!/bin/bash
################################################################################
# 03-nodejs.sh — Install Node.js LTS via nvm, npm, and AWS CDK CLI globally
# Idempotent: nvm install is safe to re-run; cdk install skipped if present
################################################################################
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
require_root

log_section "Node.js via nvm"

OWNER=$(get_actual_user)
OWNER_HOME=$(eval echo "~${OWNER}")
NVM_DIR_TARGET="${OWNER_HOME}/.nvm"
NODE_LTS="--lts"

# Install nvm as the target user if not present
if [[ ! -s "${NVM_DIR_TARGET}/nvm.sh" ]]; then
  log_info "Installing nvm for ${OWNER}..."
  sudo -u "${OWNER}" bash -c \
    'curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash'
  log_success "nvm installed"
else
  log_info "nvm already installed at ${NVM_DIR_TARGET}"
fi

# Install Node.js LTS and set as default
log_info "Installing Node.js LTS..."
sudo -u "${OWNER}" bash -c "
  export NVM_DIR=\"${NVM_DIR_TARGET}\"
  source \"\${NVM_DIR}/nvm.sh\"
  nvm install ${NODE_LTS}
  nvm alias default node
  node --version
  npm --version
"

# Configure npm cache
log_info "Configuring npm cache..."
sudo -u "${OWNER}" bash -c "
  export NVM_DIR=\"${NVM_DIR_TARGET}\"
  source \"\${NVM_DIR}/nvm.sh\"
  npm config set cache \"${CACHE_ROOT}/npm\" --global
"

# Install AWS CDK CLI globally
log_info "Installing AWS CDK CLI..."
sudo -u "${OWNER}" bash -c "
  export NVM_DIR=\"${NVM_DIR_TARGET}\"
  source \"\${NVM_DIR}/nvm.sh\"
  if npm list -g aws-cdk &>/dev/null; then
    echo '[INFO]  aws-cdk already installed: '\$(cdk --version 2>/dev/null || echo unknown)
  else
    npm install -g aws-cdk
    echo '[OK]    aws-cdk installed: '\$(cdk --version)
  fi
"

log_success "Node.js + npm + CDK ready"
