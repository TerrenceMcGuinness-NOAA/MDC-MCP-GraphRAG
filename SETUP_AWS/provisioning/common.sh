#!/bin/bash
################################################################################
# common.sh — Shared functions for MDC MCP RAG AWS provisioning
# Version: 1.0.0
################################################################################

# Prevent multiple sourcing
[[ -n "${_AWS_COMMON_SH_LOADED:-}" ]] && return 0
export _AWS_COMMON_SH_LOADED=1

# Colors (ASCII-safe for MCP stdio; used only in interactive terminals)
export RED='\033[0;31m'
export GREEN='\033[0;32m'
export YELLOW='\033[1;33m'
export CYAN='\033[0;36m'
export NC='\033[0m'

# Environment defaults
export PERSISTENT_ROOT="${PERSISTENT_ROOT:-/mdc-mcp-rag}"
export DATA_ROOT="${PERSISTENT_ROOT}/data"
export ETC_ROOT="${PERSISTENT_ROOT}/etc"
export CACHE_ROOT="${PERSISTENT_ROOT}/cache"
export NVM_DIR="${NVM_DIR:-${HOME}/.nvm}"

# Resolve repo root relative to this file
SCRIPT_DIR_COMMON="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export MDC_REPO="${MDC_REPO:-$(cd "${SCRIPT_DIR_COMMON}/../.." && pwd)}"
export MCP_ROOT="${MDC_REPO}/mcp_server_node"
export SETUP_AWS="${MDC_REPO}/SETUP_AWS"

export PROVISION_VERSION="1.0.0"

# Status tracking file
STATUS_FILE="/tmp/mdc-provision-status.$$"

log_info()    { echo -e "${CYAN}[INFO]${NC}  $1"; }
log_success() { echo -e "${GREEN}[OK]${NC}    $1"; }
log_warning() { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; }
log_section() { echo ""; echo -e "${CYAN}════════════════════════════════════════${NC}"; echo -e "${CYAN}  $1${NC}"; echo -e "${CYAN}════════════════════════════════════════${NC}"; }

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    log_error "This script must be run as root (use sudo)"
    exit 1
  fi
}

command_exists() { command -v "$1" &>/dev/null; }

get_actual_user() {
  # Return the non-root user who invoked sudo, or current user
  echo "${SUDO_USER:-${USER:-ec2-user}}"
}

run_as_user() {
  local user
  user=$(get_actual_user)
  sudo -u "${user}" bash -c "$1"
}

clear_status_file() { : > "${STATUS_FILE}"; }

record_result() {
  local script="$1" status="$2" msg="${3:-}"
  echo "${script}|${status}|${msg}" >> "${STATUS_FILE}"
}

run_subscript() {
  local script="$1" description="$2"
  local script_path="${SETUP_AWS}/provisioning/${script}"

  log_section "Running: ${description}"

  if [[ ! -f "${script_path}" ]]; then
    log_warning "Script not found: ${script_path} — skipping"
    record_result "${script}" "skipped" "file not found"
    return 0
  fi

  if bash "${script_path}"; then
    log_success "${description} — done"
    record_result "${script}" "ok" ""
    return 0
  else
    local rc=$?
    log_error "${description} — FAILED (exit ${rc})"
    record_result "${script}" "failed" "exit ${rc}"
    return "${rc}"
  fi
}

print_summary_report() {
  log_section "Provisioning Summary"
  if [[ ! -f "${STATUS_FILE}" ]]; then
    log_warning "No status file found"
    return
  fi
  while IFS='|' read -r script status msg; do
    case "${status}" in
      ok)      echo -e "  ${GREEN}[OK]${NC}      ${script}" ;;
      skipped) echo -e "  ${YELLOW}[SKIP]${NC}    ${script}  ${msg}" ;;
      failed)  echo -e "  ${RED}[FAILED]${NC}  ${script}  ${msg}" ;;
    esac
  done < "${STATUS_FILE}"
  rm -f "${STATUS_FILE}"
}
