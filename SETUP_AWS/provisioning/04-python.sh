#!/bin/bash
################################################################################
# 04-python.sh — Verify Python 3.12, validate Spack mcp-venv, install uvx
#
# Python package dependencies (boto3, fastmcp, opensearch-py, etc.) are now
# managed via the shared Spack venv at /mnt/mdc-mcp-rag/spack/var/mcp-venv.
# This script NO LONGER runs pip install --user. To update the shared env, run:
#   /mnt/mdc-mcp-rag/spack/var/mcp-venv/bin/pip install <pkg>   (as ec2-user)
# Idempotent: checks versions before installing
################################################################################
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
require_root

log_section "Python 3.12 and Spack mcp-venv"

OWNER=$(get_actual_user)
MIN_PYTHON_MINOR=12
SPACK_VENV="/mnt/mdc-mcp-rag/spack/var/mcp-venv"
SPACK_ACTIVATE="/mnt/mdc-mcp-rag/spack/mcp-env-activate.sh"

# ── 1. Verify system Python 3.12 ──────────────────────────────────────────────
if command_exists python3.12; then
  log_info "Python 3.12 present: $(python3.12 --version)"
else
  log_info "python3.12 not found — installing..."
  dnf install -y python3.12 python3.12-pip python3.12-devel
  log_info "Installed: $(python3.12 --version)"
fi

# Verify minimum version (3.12+)
CURRENT_MINOR=$(python3.12 -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || echo 0)
if [[ "${CURRENT_MINOR}" -lt "${MIN_PYTHON_MINOR}" ]]; then
  log_error "python3.12 is version 3.${CURRENT_MINOR} — need 3.${MIN_PYTHON_MINOR}+"
  exit 1
fi

# ── 2. Validate Spack mcp-venv ────────────────────────────────────────────────
# The venv is provisioned once by ec2-user (via 09-spack-mcp-env.sh).
# This script only validates it is present and functional — it does NOT
# pip install into ~/.local or the venv itself.
if [[ -f "${SPACK_VENV}/bin/python3" ]]; then
  VENV_BOTO=$(${SPACK_VENV}/bin/python3 -c "import boto3; print(boto3.__version__)" 2>/dev/null || echo "MISSING")
  VENV_FMCP=$(${SPACK_VENV}/bin/python3 -c "import fastmcp; print(fastmcp.__version__)" 2>/dev/null || echo "MISSING")
  if [[ "${VENV_BOTO}" == "MISSING" || "${VENV_FMCP}" == "MISSING" ]]; then
    log_error "Spack venv found but key packages missing (boto3=${VENV_BOTO} fastmcp=${VENV_FMCP})"
    log_error "Re-run: sudo -u ec2-user bash SETUP_AWS/provisioning/09-spack-mcp-env.sh"
    exit 1
  fi
  log_info "Spack mcp-venv OK — boto3=${VENV_BOTO} fastmcp=${VENV_FMCP}"
  log_info "Activate script: ${SPACK_ACTIVATE}"
else
  log_error "Spack mcp-venv not found at ${SPACK_VENV}"
  log_error "Run 09-spack-mcp-env.sh first (as ec2-user, not root)."
  exit 1
fi

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

log_success "Python 3.12 + Spack mcp-venv ready"
