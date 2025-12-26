#!/bin/bash
################################################################################
# 00-users.sh - Provision Linux user accounts for MCP RAG environment
# Part of modular provisioning system v4.0.0
#
# This script is intentionally idempotent: it skips users that already exist.
################################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

require_root

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/user_config.sh"

usage() {
  cat << 'EOF'
Usage:
  sudo ./00-users.sh                 # Provision all PROVISION_USERS
  sudo ./00-users.sh --user <name>   # Provision a specific user (repeatable)
  sudo ./00-users.sh --status        # Show configured vs existing users

Options:
  --user <username>     Provision only this user (can be repeated)
  --status              Print a quick status summary (no changes)
  -h, --help             Show this help
EOF
}

TARGET_USERS=()
STATUS_ONLY=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user)
      [[ $# -ge 2 ]] || { log_error "--user requires a username"; exit 2; }
      TARGET_USERS+=("$2")
      shift 2
      ;;
    --status)
      STATUS_ONLY=true
      shift
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

USERS_TO_PROVISION=()
if [[ ${#TARGET_USERS[@]} -gt 0 ]]; then
  USERS_TO_PROVISION=("${TARGET_USERS[@]}")
else
  USERS_TO_PROVISION=("${PROVISION_USERS[@]}")
fi

get_first_name() {
  local username="$1"
  echo "${username%%.*}"
}

create_user() {
  local username="$1"

  log_info "Creating user account: ${username}"

  if id "${username}" &>/dev/null; then
    log_warning "User ${username} already exists; skipping creation"
    return 0
  fi

  useradd -m -s /bin/bash "${username}"

  echo "${username}:ChangeMe123!" | chpasswd
  chage -d 0 "${username}"

  log_success "User ${username} created"
}

setup_ssh() {
  local username="$1"
  local home_dir
  home_dir=$(eval echo ~"${username}")
  local ssh_dir="${home_dir}/.ssh"
  local user_group
  user_group=$(get_user_group "${username}")

  log_info "Setting up SSH for ${username}"

  mkdir -p "${ssh_dir}"
  chown "${username}:${user_group}" "${ssh_dir}"
  chmod 700 "${ssh_dir}"

  if [[ ! -f "${ssh_dir}/id_rsa" ]]; then
    sudo -u "${username}" HOME="${home_dir}" \
      ssh-keygen -t rsa -b 4096 -f "${ssh_dir}/id_rsa" -N "" -C "${username}@mcp-rag-dev"
    log_success "Generated SSH keypair for ${username}"
  else
    log_warning "SSH keys already exist for ${username}"
  fi

  touch "${ssh_dir}/authorized_keys"
  chmod 600 "${ssh_dir}/authorized_keys"
  chown "${username}:${user_group}" "${ssh_dir}/authorized_keys"
  chown -R "${username}:${user_group}" "${ssh_dir}"
}

create_scratch_space() {
  local username="$1"
  local workspace_dir="${SCRATCH_ROOT}/${username}"
  local user_group
  user_group=$(get_user_group "${username}")

  log_info "Creating scratch space for ${username}: ${workspace_dir}"
  mkdir -p "${SCRATCH_ROOT}"
  mkdir -p "${workspace_dir}"
  chown -R "${username}:${user_group}" "${workspace_dir}"
  chmod 755 "${workspace_dir}"
}

setup_bin_directory() {
  local username="$1"
  local home_dir
  home_dir=$(eval echo ~"${username}")
  local bin_dir="${home_dir}/bin"
  local user_code_script="${bin_dir}/code.sh"
  local code_tunnel_script="${SETUP_DIR}/bin/code.sh"
  local user_group
  user_group=$(get_user_group "${username}")

  log_info "Setting up bin directory for ${username}"
  mkdir -p "${bin_dir}"

  if [[ -f "${code_tunnel_script}" ]]; then
    cp "${code_tunnel_script}" "${user_code_script}"
    chmod 755 "${user_code_script}"
    chown "${username}:${user_group}" "${user_code_script}"
  else
    log_warning "code.sh not found at ${code_tunnel_script}; skipping"
  fi
}

setup_bash_environment() {
  local username="$1"
  local home_dir
  home_dir=$(eval echo ~"${username}")
  local bashrc="${home_dir}/.bashrc"
  local bash_profile="${home_dir}/.bash_profile"
  local workspace_dir="${SCRATCH_ROOT}/${username}"

  local bashrc_template="${SETUP_DIR}/bashrc_template"
  local bash_profile_template="${SETUP_DIR}/bash_profile_template"

  log_info "Configuring bash environment for ${username}"

  [[ -f "${bashrc}" ]] && cp "${bashrc}" "${bashrc}.backup.$(date +%Y%m%d)" || true
  [[ -f "${bash_profile}" ]] && cp "${bash_profile}" "${bash_profile}.backup.$(date +%Y%m%d)" || true

  if [[ -f "${bashrc_template}" ]]; then
    cp "${bashrc_template}" "${bashrc}"
  fi

  if [[ -f "${bash_profile_template}" ]]; then
    cp "${bash_profile_template}" "${bash_profile}"
  fi

  sed -i "s|alias work=.*|alias work='cd ${workspace_dir}'|g" "${bash_profile}" 2>/dev/null || true

  cat >> "${bashrc}" << EOF

# ============================================================
# User-Specific Workspace Configuration
# Added by 00-users.sh on $(date)
# ============================================================

export WORKSPACE="${workspace_dir}"

if [ -t 1 ]; then
    echo "================================================"
    echo "  MCP RAG Development Environment"
    echo "  User: ${username}"
    echo "  Workspace: ${workspace_dir}"
    echo "  Use 'work' to navigate to your workspace"
    echo "================================================"
fi

EOF

  local user_group
  user_group=$(get_user_group "${username}")
  chown "${username}:${user_group}" "${bashrc}" "${bash_profile}" 2>/dev/null || true
}

create_workspace_readme() {
  local username="$1"
  local first_name
  first_name=$(get_first_name "${username}")
  local workspace_dir="${SCRATCH_ROOT}/${username}"
  local readme="${workspace_dir}/README.md"

  log_info "Creating workspace README for ${username}"

  cat > "${readme}" << EOF
# Welcome to Your MCP RAG Development Workspace

**User**: ${username}
**Workspace**: ${workspace_dir}
**Created**: $(date)

## Quick Start

- Use the 'work' alias to jump to your workspace.
- Your VS Code tunnel helper is in ~/bin/code.sh (if installed).

Default tunnel name: pw_${first_name}

EOF

  local user_group
  user_group=$(get_user_group "${username}")
  chown "${username}:${user_group}" "${readme}" 2>/dev/null || true
}

add_to_groups() {
  local username="$1"

  if getent group docker > /dev/null 2>&1; then
    usermod -aG docker "${username}" || true
  fi

  if getent group kasmvnc-cert > /dev/null 2>&1; then
    usermod -aG kasmvnc-cert "${username}" || true
  fi
}

provision_user() {
  local username="$1"

  log_subsection "Provisioning user: ${username}"

  create_user "${username}"
  setup_ssh "${username}"
  create_scratch_space "${username}"
  setup_bin_directory "${username}"
  setup_bash_environment "${username}"
  create_workspace_readme "${username}"
  add_to_groups "${username}"

  log_success "User provisioned: ${username}"
}

print_status() {
  log_subsection "User Provisioning Status"
  echo "Configured default users (PROVISION_USERS):"
  printf "  - %s\n" "${PROVISION_USERS[@]}"
  echo ""
  echo "Existing local users (UID>=1000):"
  getent passwd | awk -F: '$3 >= 1000 && $3 < 65534 {print "  - " $1}'
}

log_subsection "Provisioning Linux User Accounts"

if [[ "${STATUS_ONLY}" == true ]]; then
  print_status
  exit 0
fi

for username in "${USERS_TO_PROVISION[@]}"; do
  provision_user "${username}"
done

log_success "User provisioning step complete"
