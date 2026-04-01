#!/bin/bash
################################################################################
# 00-users.sh — Validate ec2-user, set up SSH authorized_keys
# Idempotent: safe to re-run
################################################################################
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
require_root

log_section "User Accounts"

TARGET_USER="ec2-user"

# Verify ec2-user exists (standard on Amazon Linux / AL2023)
if ! id "${TARGET_USER}" &>/dev/null; then
  log_error "Expected user '${TARGET_USER}' not found — is this an EC2 instance?"
  exit 1
fi
log_success "User '${TARGET_USER}' exists"

# Ensure .ssh directory and authorized_keys exist with correct permissions
SSH_DIR="/home/${TARGET_USER}/.ssh"
AUTH_KEYS="${SSH_DIR}/authorized_keys"

mkdir -p "${SSH_DIR}"
touch "${AUTH_KEYS}"
chmod 700 "${SSH_DIR}"
chmod 600 "${AUTH_KEYS}"
chown -R "${TARGET_USER}:${TARGET_USER}" "${SSH_DIR}"

log_success "SSH directory configured for ${TARGET_USER}"
