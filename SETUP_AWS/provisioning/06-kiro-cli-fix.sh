#!/bin/bash
################################################################################
# 06-kiro-cli-fix.sh — Fix Kiro CLI shell integration
#
# Problem: `kiro-cli init` appends an eval hook to ~/.bashrc that calls
# `kiro-cli init` on every shell start, which exits with code -1 and breaks
# non-interactive shells (e.g. SSH commands, provisioning scripts).
#
# Fix: Comment out the eval line in ~/.bashrc / ~/.bash_profile so Kiro CLI
# is still available as a command but its shell hook does not auto-execute.
# Idempotent: only patches if the hook is present and not already patched.
################################################################################
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
# Runs as root to patch all relevant user files

log_section "Kiro CLI Shell Hook Fix"

OWNER=$(get_actual_user)
OWNER_HOME=$(eval echo "~${OWNER}")

patch_file() {
  local file="$1"
  [[ -f "${file}" ]] || return 0

  # Pattern: eval "$(kiro-cli init ...)" or eval $(kiro-cli init)
  if grep -qE 'eval.*kiro-cli init' "${file}" 2>/dev/null; then
    if grep -qE '^#.*eval.*kiro-cli init' "${file}" 2>/dev/null; then
      log_info "Already patched: ${file}"
    else
      # Comment out the eval line
      sed -i 's|^\(.*eval.*kiro-cli init.*\)$|# [kiro-cli-fix] \1|g' "${file}"
      log_success "Patched kiro-cli init hook in: ${file}"
    fi
  else
    log_info "No kiro-cli init hook found in: ${file}"
  fi
}

patch_file "${OWNER_HOME}/.bashrc"
patch_file "${OWNER_HOME}/.bash_profile"
patch_file "${OWNER_HOME}/.profile"

# Also patch root's files if running under sudo
if [[ "${OWNER}" != "root" ]]; then
  patch_file "/root/.bashrc"
  patch_file "/root/.bash_profile"
fi

log_success "Kiro CLI shell hook fix complete"
