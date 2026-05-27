#!/bin/bash
################################################################################
# 02-system-deps.sh — Install system packages (git, jq, curl, build tools)
# Idempotent: dnf install -y skips already-installed packages
################################################################################
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
require_root

log_section "System Dependencies"

PACKAGES=(
  git
  jq
  curl
  wget
  tar
  unzip
  gcc
  gcc-c++
  make
  openssl-devel
  bzip2-devel
  libffi-devel
  zlib-devel
  # ─ EFS client tooling ──────────────────────────────────────────
  # amazon-efs-utils provides the `mount.efs` helper used by
  # operator-host scripts that mount EFS file systems with TLS +
  # IAM auth (notably mcp_server_python/scripts/populate_workflow_efs*.sh).
  # Without this package, `mount -t efs` fails because the kernel
  # has no EFS handler. Pulls in stunnel as a dependency.
  # See SETUP_AWS/DRIFT_REGISTER.md for context.
  amazon-efs-utils
)

log_info "Installing packages: ${PACKAGES[*]}"
dnf install -y "${PACKAGES[@]}"

log_success "System dependencies installed"
