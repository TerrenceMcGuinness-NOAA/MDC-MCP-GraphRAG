#!/bin/bash
################################################################################
# common.sh — Shared functions for MDC MCP RAG AWS provisioning
# Version: 1.0.0
################################################################################

# Prevent multiple sourcing.
#
# Deliberately NOT exported: an exported guard leaks into every child process, so
# a subscript launched by provision.sh (which has already sourced this file) would
# see the guard set, return early from its own `source common.sh`, and end up with
# NONE of these functions defined — `require_root: command not found` at stage 00.
# Keeping the variable shell-local still guards repeated sourcing within one
# process, while each subprocess sources fresh.
[[ -n "${_AWS_COMMON_SH_LOADED:-}" ]] && return 0
_AWS_COMMON_SH_LOADED=1

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
log_subsection() { echo ""; echo -e "${CYAN}── $1 ──${NC}"; }

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

################################################################################
# Ownership helpers
#
# Ported from SETUP/provisioning/common.sh so the COTS and AWS provisioning
# trees read the same way. Consumed by provision-user-accounts.sh for drift
# detection and the preserve-vs-adopt scratch semantics.
# Spec: .kiro/specs/aws-user-provisioning-drift-remediation/
################################################################################

# Get the primary group of a user (handles group name != username).
# Usage:   get_user_group <username>
# Prints:  primary group name, falling back to the GID then the username.
get_user_group() {
  local user="${1:-$(get_actual_user)}"
  local gid
  gid=$(id -g "${user}" 2>/dev/null)
  if [[ -n "${gid}" ]]; then
    local group_name
    group_name=$(getent group "${gid}" 2>/dev/null | cut -d: -f1)
    if [[ -n "${group_name}" ]]; then
      echo "${group_name}"
    else
      echo "${gid}"
    fi
  else
    echo "${user}"
  fi
}

# Resolve user:group ownership honoring the PROVISION_PRIMARY_GROUP SPOT.
# Precedence:
#   1. "${PROVISION_PRIMARY_GROUP}" iff non-empty AND that group exists on host
#   2. get_user_group <username>  (the user's private group — the AWS default,
#      since PROVISION_PRIMARY_GROUP is empty here)
# Usage:   resolve_ownership <username>
# Prints:  "username:group" on stdout
resolve_ownership() {
  local username="${1:-$(get_actual_user)}"
  local group="${PROVISION_PRIMARY_GROUP:-}"

  if [[ -n "${group}" ]] && getent group "${group}" > /dev/null 2>&1; then
    echo "${username}:${group}"
    return 0
  fi

  group="$(get_user_group "${username}")"
  echo "${username}:${group}"
}

# Enumerate direct children of <path> that are NOT owned by <owner>.
# Used to detect pre-staged content so a scratch-owner fix preserves it instead
# of blindly chowning, and to render the [PRESERVED] section of a dry-run plan.
# Usage:   list_prestaged_paths <path> <owner>
# Prints:  one absolute path per line, sorted; nothing when the path is
#          missing/empty or every child is already owned by <owner>.
# Note:    When <owner> is not a resolvable user on the host, every direct child
#          is pre-staged by definition — a non-existent UID cannot own anything.
list_prestaged_paths() {
  local path="$1"
  local owner="$2"

  [[ -d "${path}" ]] || return 0

  local owner_uid
  owner_uid="$(id -u "${owner}" 2>/dev/null || true)"

  if [[ -z "${owner_uid}" ]]; then
    find "${path}" -mindepth 1 -maxdepth 1 -print 2>/dev/null | sort
    return 0
  fi

  # -not -uid: filter by resolved numeric UID so this works even in nsswitch
  # edge cases where the name lookup drifts from getpwuid.
  find "${path}" -mindepth 1 -maxdepth 1 -not -uid "${owner_uid}" -print 2>/dev/null | sort
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
