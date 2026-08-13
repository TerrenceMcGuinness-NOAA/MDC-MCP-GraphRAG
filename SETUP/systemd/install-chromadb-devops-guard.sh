#!/usr/bin/env bash
# =============================================================================
# install-chromadb-devops-guard.sh
# =============================================================================
# Installs the ChromaDB bind-mount safeguard: a systemd wrapper that enforces
# `After=mcp_rag_eib.mount`, runs a preflight against the persist dir, and
# manages the compose service instead of leaving startup to Docker's own
# `restart: unless-stopped` (which is the source of the boot-time race).
#
# Also flips the running container's Docker-side restart policy to `no` so
# only the systemd unit governs boot startup. The compose file itself is not
# modified — CI paths using `docker compose up -d` still work.
#
# Usage:
#   sudo bash SETUP/systemd/install-chromadb-devops-guard.sh
#   sudo bash SETUP/systemd/install-chromadb-devops-guard.sh --uninstall
#
# Idempotent: safe to re-run.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SYSTEMD_DIR="/etc/systemd/system"
UNIT_NAME="chromadb-devops.service"
UNIT_SRC="${SCRIPT_DIR}/${UNIT_NAME}"
VERIFY_SRC="${REPO_ROOT}/SETUP/scripts/verify-chromadb-bind.sh"
CONTAINER_NAME="chromadb-devops"

log_ok()   { printf '[OK] %s\n'    "$*"; }
log_warn() { printf '[WARN] %s\n'  "$*" >&2; }
log_err()  { printf '[ERROR] %s\n' "$*" >&2; }

require_root() {
  if [[ ${EUID} -ne 0 ]]; then
    log_err "This script must be run as root (sudo)."
    exit 1
  fi
}

do_uninstall() {
  require_root
  log_ok "Uninstalling ${UNIT_NAME}..."
  systemctl disable --now "${UNIT_NAME}" 2>/dev/null || true
  rm -f "${SYSTEMD_DIR}/${UNIT_NAME}"
  systemctl daemon-reload
  # Restore Docker-side restart policy so plain `docker compose up` keeps
  # working the way the compose file declares (unless-stopped).
  if docker inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
    docker update --restart=unless-stopped "${CONTAINER_NAME}" >/dev/null
    log_ok "Restored ${CONTAINER_NAME} restart policy to unless-stopped"
  fi
  log_ok "Uninstalled."
}

do_install() {
  require_root

  if [[ ! -f "${UNIT_SRC}" ]]; then
    log_err "Unit file not found: ${UNIT_SRC}"
    exit 1
  fi
  if [[ ! -x "${VERIFY_SRC}" ]]; then
    log_warn "Making ${VERIFY_SRC} executable"
    chmod +x "${VERIFY_SRC}"
  fi

  # Sanity: preflight must succeed before we hand boot startup to the unit.
  log_ok "Running preflight verification..."
  if ! "${VERIFY_SRC}"; then
    log_err "Preflight failed. Fix the volume state first, then re-run this installer."
    exit 1
  fi

  log_ok "Installing ${UNIT_NAME} to ${SYSTEMD_DIR}/"
  # Use absolute path so bash resolves coreutils install, never this script's function.
  /usr/bin/install -m 0644 "${UNIT_SRC}" "${SYSTEMD_DIR}/${UNIT_NAME}"

  systemctl daemon-reload
  systemctl enable "${UNIT_NAME}"
  log_ok "Enabled ${UNIT_NAME}"

  # Disable Docker's own boot-time restart of this container so only the unit
  # controls startup ordering. The compose file is untouched.
  if docker inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
    docker update --restart=no "${CONTAINER_NAME}" >/dev/null
    log_ok "Set ${CONTAINER_NAME} Docker restart policy to 'no' (unit is now authoritative)"
  else
    log_warn "Container ${CONTAINER_NAME} not present yet — will be created on unit start."
  fi

  systemctl start "${UNIT_NAME}"
  log_ok "Started ${UNIT_NAME}"

  echo ""
  echo "Unit status:"
  systemctl status "${UNIT_NAME}" --no-pager || true
}

case "${1:-install}" in
  install)               do_install ;;
  --uninstall|uninstall) do_uninstall ;;
  *) log_err "Unknown arg: $1 (expected: install|--uninstall)"; exit 2 ;;
esac
