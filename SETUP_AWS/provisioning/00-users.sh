#!/bin/bash
################################################################################
# 00-users.sh — Validate ec2-user, set up SSH authorized_keys
# Idempotent: safe to re-run
#
# SCOPE: this script handles the HOST BOOTSTRAP account (ec2-user) only. It is
# stage 00 of the provision.sh orchestrator.
#
# It does NOT provision individual developer accounts. That is
# provision-user-accounts.sh, which owns --user / --remediate / --status /
# --dry-run for the per-user surface.
#
# Note for anyone arriving from the COTS Parallel Works tree: there,
# SETUP/provisioning/00-users.sh IS the per-user provisioning script. On AWS the
# responsibilities are split, and this file is the narrow bootstrap half.
# Spec: .kiro/specs/aws-user-provisioning-drift-remediation/
################################################################################
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

TARGET_USER="ec2-user"
SSH_DIR="/home/${TARGET_USER}/.ssh"
AUTH_KEYS="${SSH_DIR}/authorized_keys"

PEER_SCRIPT="provision-user-accounts.sh"
STATUS_ONLY=false
DRY_RUN=false

usage() {
  cat << EOF
Usage:
  sudo ./00-users.sh              # Validate ${TARGET_USER}, fix its ~/.ssh permissions
  sudo ./00-users.sh --status     # Read-only check; no changes
  sudo ./00-users.sh --dry-run    # Print the plan; do NOT mutate the host

Options:
  --status     Report ${TARGET_USER} account + ~/.ssh permission state, then exit
  --dry-run    Render the plan without any mutations
  -h, --help   Show this help

Scope:
  This is stage 00 of provision.sh and covers the HOST BOOTSTRAP account
  (${TARGET_USER}) only.

  For individual developer accounts — creating them, inspecting drift, or
  repairing it — use the peer script:

    sudo ./${PEER_SCRIPT} --status
    sudo ./${PEER_SCRIPT} --status --user <name>
    sudo ./${PEER_SCRIPT} --dry-run --remediate <name>
    sudo ./${PEER_SCRIPT} --remediate <name>
    sudo ./${PEER_SCRIPT} --help

  (On the COTS Parallel Works host, 00-users.sh is the per-user script. On AWS
  the two roles are split across these two files.)
EOF
}

# Flags that belong to the peer script. Silently ignoring them would be the worst
# outcome: `00-users.sh --dry-run` previously mutated the host despite the flag,
# and `--user <name>` looked accepted while doing nothing for that user.
wrong_script() {
  local flag="$1"
  log_error "'${flag}' is not a ${0##*/} option — it belongs to ${PEER_SCRIPT}."
  log_error "This script covers the ${TARGET_USER} bootstrap account only."
  echo ""
  echo "  Did you mean:  sudo ./${PEER_SCRIPT} ${flag} ..."
  echo ""
  usage
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --status)
      STATUS_ONLY=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --user|--remediate|--force|--add)
      wrong_script "$1"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      log_error "Unknown option: $1"
      usage
      exit 2
      ;;
  esac
done

require_root

log_section "User Accounts (${TARGET_USER} bootstrap)"

# Verify ec2-user exists (standard on Amazon Linux / AL2023)
if ! id "${TARGET_USER}" &>/dev/null; then
  log_error "Expected user '${TARGET_USER}' not found — is this an EC2 instance?"
  exit 1
fi

# _mode — stat mode with a leading zero, or "missing" when the path is absent.
_mode() {
  local path="$1"
  [[ -e "${path}" ]] || { echo "missing"; return 0; }
  local mode
  mode="$(stat -c '%a' "${path}" 2>/dev/null || echo "unknown")"
  [[ ${#mode} -eq 3 ]] && mode="0${mode}"
  echo "${mode}"
}

if [[ "${STATUS_ONLY}" == true ]]; then
  log_subsection "Bootstrap Account Status"
  echo "User: ${TARGET_USER}"
  echo "  account: [OK]"

  ssh_mode="$(_mode "${SSH_DIR}")"
  if [[ "${ssh_mode}" == "0700" ]]; then
    echo "  ~/.ssh mode: 0700 [OK]"
  else
    echo "  ~/.ssh mode: [DRIFT expected=0700 actual=${ssh_mode}]"
  fi

  ak_mode="$(_mode "${AUTH_KEYS}")"
  if [[ "${ak_mode}" == "0600" ]]; then
    echo "  ~/.ssh/authorized_keys mode: 0600 [OK]"
  else
    echo "  ~/.ssh/authorized_keys mode: [DRIFT expected=0600 actual=${ak_mode}]"
  fi

  owner="$(stat -c '%U:%G' "${SSH_DIR}" 2>/dev/null || echo "missing")"
  if [[ "${owner}" == "${TARGET_USER}:${TARGET_USER}" ]]; then
    echo "  ~/.ssh owner: ${owner} [OK]"
  else
    echo "  ~/.ssh owner: [DRIFT expected=${TARGET_USER}:${TARGET_USER} actual=${owner}]"
  fi

  if [[ -f "${AUTH_KEYS}" ]]; then
    echo "  ~/.ssh/authorized_keys: $(grep -c . "${AUTH_KEYS}" 2>/dev/null || echo 0) key line(s)"
  fi
  echo ""
  echo "For individual developer accounts: sudo ./${PEER_SCRIPT} --status"
  exit 0
fi

if [[ "${DRY_RUN}" == true ]]; then
  echo ""
  echo "═══════════════════════════════════════════════════════════════════"
  echo "  DRY-RUN PLAN — ${TARGET_USER} bootstrap (no mutations)"
  echo "═══════════════════════════════════════════════════════════════════"
  echo ""
  echo "[1] Verify account"
  echo "    id ${TARGET_USER}    # [OK] present"
  echo ""
  echo "[2] SSH directory"
  echo "    mkdir -p ${SSH_DIR}    # current mode: $(_mode "${SSH_DIR}")"
  echo "    touch ${AUTH_KEYS}    # current mode: $(_mode "${AUTH_KEYS}")"
  echo "    chmod 700 ${SSH_DIR}"
  echo "    chmod 600 ${AUTH_KEYS}"
  echo "    chown -R ${TARGET_USER}:${TARGET_USER} ${SSH_DIR}"
  echo ""
  echo "═══════════════════════════════════════════════════════════════════"
  echo "  END DRY-RUN PLAN — nothing was written to the host"
  echo "═══════════════════════════════════════════════════════════════════"
  exit 0
fi

log_success "User '${TARGET_USER}' exists"

# Ensure .ssh directory and authorized_keys exist with correct permissions
mkdir -p "${SSH_DIR}"
touch "${AUTH_KEYS}"
chmod 700 "${SSH_DIR}"
chmod 600 "${AUTH_KEYS}"
chown -R "${TARGET_USER}:${TARGET_USER}" "${SSH_DIR}"

log_success "SSH directory configured for ${TARGET_USER}"
