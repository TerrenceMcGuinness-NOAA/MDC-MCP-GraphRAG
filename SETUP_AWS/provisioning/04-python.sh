#!/bin/bash
################################################################################
# 04-python.sh — Install Python 3.11+, pip, uvx
# Idempotent: checks versions before installing
################################################################################
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
require_root

log_section "Python 3.11+ and pip"

OWNER=$(get_actual_user)
MIN_PYTHON_MINOR=11

# Check if Python 3.11+ already available
if command_exists python3; then
  CURRENT_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || echo 0)
  if [[ "${CURRENT_MINOR}" -ge "${MIN_PYTHON_MINOR}" ]]; then
    log_info "Python already meets requirement: $(python3 --version)"
  else
    log_info "Python $(python3 --version) too old — installing python3.11"
    dnf install -y python3.11 python3.11-pip python3.11-devel || \
      dnf install -y python3 python3-pip python3-devel
  fi
else
  log_info "Installing python3.11..."
  dnf install -y python3.11 python3.11-pip python3.11-devel || \
    dnf install -y python3 python3-pip python3-devel
fi

# Ensure pip is up to date
log_info "Upgrading pip..."
sudo -u "${OWNER}" bash -c "
  python3 -m pip install --upgrade pip --cache-dir \"${CACHE_ROOT}/pip\" --quiet
"

# Install uvx (uv's tool runner — used by iam-policy-autopilot and other MCP tools)
log_info "Installing uv + uvx..."
sudo -u "${OWNER}" bash -c "
  if command -v uvx &>/dev/null; then
    echo '[INFO]  uvx already installed: '\$(uvx --version 2>/dev/null || echo unknown)
  else
    curl -LsSf https://astral.sh/uv/install.sh | sh
    echo '[OK]    uv/uvx installed'
  fi
"

log_success "Python + pip + uvx ready"
