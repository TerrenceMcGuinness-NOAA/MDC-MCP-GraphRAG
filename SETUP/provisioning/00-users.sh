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

# Upstream repository (SPOT for provisioning-side clones only). Each new user's
# initial clone is performed as the invoking operator (SUDO_USER) whose SSH key
# already has GitLab access, then chown'd to the target user. This retired the
# earlier on-disk bare-repo scheme (2026-07-15 remediation) which required root
# SSH keys to fetch, cross-user `safe.directory` workarounds, and a stale-fetch
# fallback path — all obviated by cloning directly from the source of truth.
UPSTREAM_REPO_URL="ssh://git@gitlab-community.vlab.noaa.gov:29418/NWS/Operations/NCEP/EMC/eib-mcp-rag-server.git"

usage() {
  cat << 'EOF'
Usage:
  sudo ./00-users.sh                 # Provision all PROVISION_USERS
  sudo ./00-users.sh --user <name>   # Provision a specific user (repeatable)
  sudo ./00-users.sh --dry-run       # Print the plan; do NOT mutate the host
  sudo ./00-users.sh --status        # Show configured vs existing users

Options:
  --user <username>      Provision only this user (can be repeated)
  --dry-run              Render the provisioning plan without any mutations
  --status               Print a quick status summary (no changes)
  -h, --help             Show this help
EOF
}

TARGET_USERS=()
STATUS_ONLY=false
DRY_RUN=false

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
    --dry-run)
      DRY_RUN=true
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
  local group="${PROVISION_PRIMARY_GROUP}"
  local useradd_args=(-m -s /bin/bash)

  log_info "Creating user account: ${username}"

  if getent group "${group}" > /dev/null 2>&1; then
    useradd_args+=(-g "${group}")
  else
    log_warning "Primary group '${group}' missing — falling back to private group for ${username}"
  fi

  if id "${username}" &>/dev/null; then
    log_warning "User ${username} already exists; skipping creation"
    return 0
  fi

  # Pre-flight the password source BEFORE useradd so a bad password
  # configuration (missing file, wrong mode, empty file, no TTY, generator
  # failure) fails cleanly with zero host mutation. If we called useradd first
  # and password resolution then errored, we would leave a passwordless
  # partial account behind — the exact class of half-created state that
  # motivated this reorder.
  local password
  if ! password="$(resolve_initial_password "${username}")"; then
    log_error "Aborting ${username} provisioning: no valid initial password source"
    log_error "Set PROVISION_INITIAL_PASSWORD_FILE (mode 0600, non-empty), run"
    log_error "interactively in a TTY, or unset it to fall through to the generator."
    return 1
  fi

  useradd "${useradd_args[@]}" "${username}"
  echo "${username}:${password}" | chpasswd
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
  local owner_group
  owner_group="$(resolve_ownership "${username}")"

  log_info "Creating scratch space for ${username}: ${workspace_dir}"
  mkdir -p "${SCRATCH_ROOT}" "${workspace_dir}"

  # R3: enumerate operator-pre-staged paths (entries not owned by the target user)
  # and either preserve them (default) or adopt them (PROVISION_ADOPT_PRESTAGED=yes).
  mapfile -t prestaged < <(list_prestaged_paths "${workspace_dir}" "${username}")

  if [[ ${#prestaged[@]} -eq 0 ]]; then
    chown -R "${owner_group}" "${workspace_dir}"
  elif [[ "${PROVISION_ADOPT_PRESTAGED}" == "yes" ]]; then
    log_warning "Adopting ${#prestaged[@]} pre-staged path(s) into ${username}"
    chown -R "${owner_group}" "${workspace_dir}"
  else
    log_warning "Preserving ${#prestaged[@]} pre-staged path(s); set PROVISION_ADOPT_PRESTAGED=yes to adopt:"
    printf '  [PRESERVED] %s\n' "${prestaged[@]}"
    # chown only the workspace_dir itself (not -R) so the top-level entry is
    # user-writable while the pre-staged children retain their existing ownership.
    chown "${owner_group}" "${workspace_dir}"
  fi

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
- The EIB MCP RAG Server repo is cloned at: ${workspace_dir}/eib-mcp-rag-server

Default tunnel name: pw_${first_name}

## Repository

The EIB MCP RAG Server repository has been cloned to your workspace.
To update it:

    cd ${workspace_dir}/eib-mcp-rag-server
    git pull origin develop

EOF

  local user_group
  user_group=$(get_user_group "${username}")
  chown "${username}:${user_group}" "${readme}" 2>/dev/null || true
}

update_bare_repo() {
  # RETIRED 2026-07-15 — the on-disk bare repo scheme was replaced with a
  # direct upstream clone in clone_mcp_rag_repo(). This shim remains only so any
  # out-of-tree caller does not error; it is a no-op.
  return 0
}

clone_mcp_rag_repo() {
  local username="$1"
  local workspace_dir="${SCRATCH_ROOT}/${username}"
  local repo_dir="${workspace_dir}/eib-mcp-rag-server"
  local owner_group
  owner_group="$(resolve_ownership "${username}")"
  local operator="${SUDO_USER:-$(get_actual_user)}"

  log_info "Setting up EIB MCP RAG repository for ${username}"

  if [[ -d "${repo_dir}/.git" ]]; then
    log_warning "Repository already exists at ${repo_dir}; leaving as-is"
    return 0
  fi

  if [[ -z "${operator}" ]] || [[ "${operator}" == "root" ]]; then
    log_error "Cannot determine an operator with GitLab access (SUDO_USER unset"
    log_error "or is root). Set SUDO_USER=<operator> or run via 'sudo -u <op>'."
    return 1
  fi

  # Clone as the invoking operator whose SSH key already has GitLab access.
  # New users don't have their SSH key registered with GitLab yet, so cloning
  # as ${username} directly would fail with 'Permission denied (publickey)'.
  # GIT_SSH_COMMAND auto-accepts the host key so a first-time SSH does not hang
  # on an interactive prompt.
  #
  # Filesystem note: ${workspace_dir} is owned by ${username} mode 755 (set by
  # create_scratch_space), so the operator cannot create ${repo_dir} on its
  # own. Root (the script runs under sudo) pre-creates ${repo_dir} chown'd to
  # the operator so `git clone` has a writable target; we hand the finished
  # tree back to ${username} immediately after.
  log_info "Cloning ${UPSTREAM_REPO_URL} as ${operator} → ${repo_dir}"
  install -d -m 755 -o "${operator}" -g pwuser "${repo_dir}" || {
    log_error "Could not pre-create ${repo_dir} as ${operator}:pwuser"
    return 1
  }
  sudo -u "${operator}" -H \
    env GIT_SSH_COMMAND='ssh -o StrictHostKeyChecking=accept-new' \
    git clone "${UPSTREAM_REPO_URL}" "${repo_dir}" || {
    log_error "Clone failed. Confirm ${operator} has SSH access to ${UPSTREAM_REPO_URL}."
    # Roll back the empty pre-created dir so a subsequent re-run does not hit
    # the 'Repository already exists' short-circuit at the top of this function.
    rmdir "${repo_dir}" 2>/dev/null || true
    return 1
  }

  # Transfer ownership to the target user.
  chown -R "${owner_group}" "${repo_dir}"

  # Check out develop as the target user (their key isn't on GitLab yet, so any
  # future fetch/push waits until they upload one — documented in the README).
  sudo -u "${username}" git -C "${repo_dir}" checkout develop 2>/dev/null \
    || log_warning "Could not check out 'develop' — branch may not exist or default is different"

  log_success "Repository cloned and owned by ${username}"
}

setup_vscode_mcp_config() {
  local username="$1"
  local workspace_dir="${SCRATCH_ROOT}/${username}"
  local vscode_dir="${workspace_dir}/.vscode"
  local mcp_json="${vscode_dir}/mcp.json"
  local repo_dir="${workspace_dir}/eib-mcp-rag-server"
  local user_group
  user_group=$(get_user_group "${username}")

  log_info "Setting up VS Code MCP configuration for ${username}"

  mkdir -p "${vscode_dir}"

  cat > "${mcp_json}" << EOF
{
  "servers": {
    // EIB MCP RAG Server - Full Mode (34 tools)
    // Configured for user: ${username}
    // Workspace: ${workspace_dir}
    "eib-mcp-rag-full": {
      "command": "node",
      "args": [
        "${repo_dir}/mcp_server_node/src/UnifiedMCPServer.js",
        "full"
      ],
      "type": "stdio",
      "env": {
        "MCP_WORKSPACE_ROOT": "${repo_dir}",
        "MCP_WORKFLOW_ROOT": "${repo_dir}/supported_repos/global-workflow_develop",
        "SDD_FRAMEWORK_ROOT": "${repo_dir}/sdd_framework",
        "CHROMA_SERVER_URL": "http://localhost:8080",
        "CHROMADB_URL": "http://127.0.0.1:8080",
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_PASSWORD": "gfsworkflow2025",
        "ENABLE_RAG": "true",
        "ENABLE_GITHUB": "false"
      }
    }
  }
}
EOF

  chown -R "${username}:${user_group}" "${vscode_dir}" 2>/dev/null || true
  log_success "VS Code MCP configuration created at ${mcp_json}"
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

  # R6: dry-run gate — render the plan and short-circuit before any mutation.
  if [[ "${DRY_RUN}" == true ]]; then
    render_provisioning_plan "${username}"
    return 0
  fi

  log_subsection "Provisioning user: ${username}"

  # Halt the whole chain if create_user returns non-zero — the most likely
  # cause is a bad PROVISION_INITIAL_PASSWORD_FILE (missing / wrong mode /
  # empty), which is pre-flighted inside create_user() before useradd runs.
  if ! create_user "${username}"; then
    log_error "Aborting provision_user(${username}) after create_user failure"
    return 1
  fi

  setup_ssh "${username}"
  create_scratch_space "${username}"
  setup_bin_directory "${username}"
  setup_bash_environment "${username}"
  clone_mcp_rag_repo "${username}"
  setup_vscode_mcp_config "${username}"
  create_workspace_readme "${username}"
  add_to_groups "${username}"

  log_success "User provisioned: ${username}"
}

# render_provisioning_plan — R6 (dry-run)
#
# Prints the mutating steps provision_user() would perform for <username>,
# with rendered variable substitution and no side effects. Includes the
# R3 [PRESERVED] section when the scratch dir holds operator-pre-staged
# content that the default (PROVISION_ADOPT_PRESTAGED=no) branch would skip.
#
# Usage:   render_provisioning_plan <username>
# Prints:  the plan on stdout; nothing is written to the host.
render_provisioning_plan() {
  local username="$1"
  local group="${PROVISION_PRIMARY_GROUP}"
  local workspace_dir="${SCRATCH_ROOT}/${username}"
  local home_dir="/home/${username}"
  local repo_dir="${workspace_dir}/eib-mcp-rag-server"
  local vscode_dir="${workspace_dir}/.vscode"
  local first_name
  first_name="$(get_first_name "${username}")"
  local owner_group
  owner_group="$(resolve_ownership "${username}")"

  echo ""
  echo "═══════════════════════════════════════════════════════════════════"
  echo "  DRY-RUN PLAN for user: ${username}"
  echo "  (no mutations will be performed)"
  echo "═══════════════════════════════════════════════════════════════════"
  echo ""

  # [1] User account (R1, R2, R5)
  echo "[1] User account"
  if id "${username}" &>/dev/null; then
    echo "    (user already exists on host; useradd/chpasswd/chage would be skipped)"
  else
    if getent group "${group}" > /dev/null 2>&1; then
      echo "    useradd -g ${group} -m -s /bin/bash ${username}"
    else
      echo "    # WARN: primary group '${group}' missing on host — private-group fallback"
      echo "    useradd -m -s /bin/bash ${username}"
    fi
    echo "    echo '${username}:<initial-password-from-R5-precedence>' | chpasswd"
    echo "    chage -d 0 ${username}    # force password change on first login"
  fi
  echo ""

  # [2] SSH keypair
  echo "[2] SSH keypair"
  echo "    mkdir -p ${home_dir}/.ssh"
  echo "    chmod 700 ${home_dir}/.ssh"
  echo "    chown ${owner_group} ${home_dir}/.ssh"
  echo "    ssh-keygen -t rsa -b 4096 -f ${home_dir}/.ssh/id_rsa -N '' -C '${username}@mcp-rag-dev'"
  echo "    touch ${home_dir}/.ssh/authorized_keys"
  echo "    chmod 600 ${home_dir}/.ssh/authorized_keys"
  echo "    chown -R ${owner_group} ${home_dir}/.ssh"
  echo ""

  # [3] Scratch workspace (R3 preserve/adopt decision)
  echo "[3] Scratch workspace: ${workspace_dir}"
  echo "    mkdir -p ${SCRATCH_ROOT} ${workspace_dir}"

  local -a prestaged=()
  mapfile -t prestaged < <(list_prestaged_paths "${workspace_dir}" "${username}")

  if [[ ${#prestaged[@]} -eq 0 ]]; then
    echo "    chown -R ${owner_group} ${workspace_dir}    # (no pre-staged content)"
  elif [[ "${PROVISION_ADOPT_PRESTAGED}" == "yes" ]]; then
    echo "    chown -R ${owner_group} ${workspace_dir}    # ADOPT ${#prestaged[@]} pre-staged path(s)"
  else
    echo "    chown ${owner_group} ${workspace_dir}    # top-level only; children preserved"
    echo ""
    echo "    [PRESERVED] ${#prestaged[@]} pre-staged path(s) will NOT be re-owned"
    echo "                (set PROVISION_ADOPT_PRESTAGED=yes to adopt instead):"
    printf '      [PRESERVED] %s\n' "${prestaged[@]}"
  fi
  echo "    chmod 755 ${workspace_dir}"
  echo ""

  # [4] Bin directory and code.sh template
  echo "[4] Bin directory and code-tunnel helper"
  echo "    mkdir -p ${home_dir}/bin"
  echo "    cp ${SETUP_DIR}/bin/code.sh ${home_dir}/bin/code.sh"
  echo "    chmod 755 ${home_dir}/bin/code.sh"
  echo "    chown ${owner_group} ${home_dir}/bin/code.sh"
  echo ""

  # [5] Bash environment templates
  echo "[5] Bash environment templates"
  echo "    cp ${SETUP_DIR}/bashrc_template       ${home_dir}/.bashrc"
  echo "    cp ${SETUP_DIR}/bash_profile_template ${home_dir}/.bash_profile"
  echo "    (append user-specific WORKSPACE=${workspace_dir} block to .bashrc)"
  echo "    (rewrite 'alias work=' in .bash_profile → cd ${workspace_dir})"
  echo "    chown ${owner_group} ${home_dir}/.bashrc ${home_dir}/.bash_profile"
  echo ""

  # [6] Repository clone from upstream (as operator, then chown to target user)
  local operator="${SUDO_USER:-$(get_actual_user)}"
  echo "[6] Clone EIB MCP RAG repo (direct from upstream, retire bare-repo scheme)"
  echo "    sudo -u ${operator} -H \\"
  echo "      env GIT_SSH_COMMAND='ssh -o StrictHostKeyChecking=accept-new' \\"
  echo "      git clone ${UPSTREAM_REPO_URL} ${repo_dir}"
  echo "    chown -R ${owner_group} ${repo_dir}"
  echo "    sudo -u ${username} git -C ${repo_dir} checkout develop"
  echo ""

  # [7] VS Code MCP config
  echo "[7] VS Code MCP configuration"
  echo "    mkdir -p ${vscode_dir}"
  echo "    write ${vscode_dir}/mcp.json    # eib-mcp-rag-full server, workspace=${repo_dir}"
  echo "    chown -R ${owner_group} ${vscode_dir}"
  echo ""

  # [8] Workspace README
  echo "[8] Workspace README"
  echo "    write ${workspace_dir}/README.md    # tunnel name: pw_${first_name}"
  echo "    chown ${owner_group} ${workspace_dir}/README.md"
  echo ""

  # [9] Supplementary group memberships (R7)
  echo "[9] Supplementary group memberships"
  if getent group docker > /dev/null 2>&1; then
    echo "    usermod -aG docker ${username}"
  else
    echo "    (docker group not present on host; skip)"
  fi
  if getent group kasmvnc-cert > /dev/null 2>&1; then
    echo "    usermod -aG kasmvnc-cert ${username}"
  else
    echo "    (kasmvnc-cert group not present on host; skip)"
  fi
  echo ""
  echo "═══════════════════════════════════════════════════════════════════"
  echo "  END DRY-RUN PLAN — nothing was written to the host"
  echo "═══════════════════════════════════════════════════════════════════"
  echo ""
}

# _fmt_mode — format a 3-digit octal mode with a leading zero for display
# (stat -c '%a' emits "700"; we want "0700" for parity with the design block).
_fmt_mode() {
  local mode="$1"
  if [[ ${#mode} -eq 3 ]]; then
    echo "0${mode}"
  else
    echo "${mode}"
  fi
}

# check_user_integrity — R7/R8 per-user integrity block (design.md § "--status upgrade").
#
# Emits a six-line report for <username>. Every check is read-only:
#   1. account exists         (id <user>)
#   2. primary group          matches ${PROVISION_PRIMARY_GROUP}
#   3. scratch dir            exists and is owned by resolve_ownership <user>
#   4. ~/.ssh mode            0700
#   5. ~/.ssh/authorized_keys mode 0600
#   6. supplementary groups   include docker + kasmvnc-cert (only those groups
#                             that actually exist on this host)
#
# Emits "[OK]" for a matching check and
# "[DRIFT expected=X actual=Y]" for a mismatch. No mutations.
check_user_integrity() {
  local username="$1"
  local expected_group="${PROVISION_PRIMARY_GROUP}"

  echo ""
  echo "User: ${username}"

  # [1] Account existence — every downstream check needs a real UID/GID/home.
  if ! id "${username}" &>/dev/null; then
    echo "  account: [DRIFT expected=exists actual=missing]"
    return 0
  fi
  echo "  account: [OK]"

  # [2] Primary group
  local actual_group
  actual_group="$(get_user_group "${username}")"
  if [[ "${actual_group}" == "${expected_group}" ]]; then
    echo "  primary group: ${expected_group} [OK]"
  else
    echo "  primary group: [DRIFT expected=${expected_group} actual=${actual_group}]"
  fi

  # [3] Scratch dir + ownership
  local scratch_dir="${SCRATCH_ROOT}/${username}"
  local expected_owner
  expected_owner="$(resolve_ownership "${username}")"
  if [[ ! -d "${scratch_dir}" ]]; then
    echo "  scratch: ${scratch_dir} [DRIFT expected=exists actual=missing]"
  else
    local actual_owner
    actual_owner="$(stat -c '%U:%G' "${scratch_dir}" 2>/dev/null || echo "unknown:unknown")"
    if [[ "${actual_owner}" == "${expected_owner}" ]]; then
      echo "  scratch: ${scratch_dir} [OK]"
    else
      echo "  scratch: ${scratch_dir} [DRIFT expected=${expected_owner} actual=${actual_owner}]"
    fi
  fi

  # [4] ~/.ssh mode
  local home_dir
  home_dir="$(getent passwd "${username}" | cut -d: -f6)"
  local ssh_dir="${home_dir}/.ssh"
  local auth_keys="${ssh_dir}/authorized_keys"

  if [[ ! -d "${ssh_dir}" ]]; then
    echo "  ~/.ssh mode: [DRIFT expected=0700 actual=missing]"
  else
    local ssh_mode
    ssh_mode="$(stat -c '%a' "${ssh_dir}" 2>/dev/null || echo "unknown")"
    if [[ "${ssh_mode}" == "700" ]]; then
      echo "  ~/.ssh mode: 0700 [OK]"
    else
      echo "  ~/.ssh mode: [DRIFT expected=0700 actual=$(_fmt_mode "${ssh_mode}")]"
    fi
  fi

  # [5] ~/.ssh/authorized_keys mode
  if [[ ! -f "${auth_keys}" ]]; then
    echo "  ~/.ssh/authorized_keys mode: [DRIFT expected=0600 actual=missing]"
  else
    local ak_mode
    ak_mode="$(stat -c '%a' "${auth_keys}" 2>/dev/null || echo "unknown")"
    if [[ "${ak_mode}" == "600" ]]; then
      echo "  ~/.ssh/authorized_keys mode: 0600 [OK]"
    else
      echo "  ~/.ssh/authorized_keys mode: [DRIFT expected=0600 actual=$(_fmt_mode "${ak_mode}")]"
    fi
  fi

  # [6] Supplementary groups — only check the groups that actually exist on host.
  local -a expected_supp=()
  local g
  for g in docker kasmvnc-cert; do
    if getent group "${g}" > /dev/null 2>&1; then
      expected_supp+=("${g}")
    fi
  done

  if [[ ${#expected_supp[@]} -eq 0 ]]; then
    echo "  supplementary groups: (none applicable on this host) [OK]"
    return 0
  fi

  local expected_str
  expected_str="$(IFS=,; echo "${expected_supp[*]}")"

  # id -Gn returns space-separated group names; wrap for whole-word matching.
  local user_groups
  user_groups=" $(id -Gn "${username}" 2>/dev/null || echo "") "

  local -a missing=()
  local -a has=()
  for g in "${expected_supp[@]}"; do
    if [[ "${user_groups}" == *" ${g} "* ]]; then
      has+=("${g}")
    else
      missing+=("${g}")
    fi
  done

  if [[ ${#missing[@]} -eq 0 ]]; then
    echo "  supplementary groups: ${expected_str} [OK]"
  else
    local has_str="(none)"
    if [[ ${#has[@]} -gt 0 ]]; then
      has_str="$(IFS=,; echo "${has[*]}")"
    fi
    echo "  supplementary groups: [DRIFT expected=${expected_str} actual=${has_str}]"
  fi
}

print_status() {
  log_subsection "User Provisioning Status"
  echo "Configured default users (PROVISION_USERS):"
  printf "  - %s\n" "${PROVISION_USERS[@]}"
  echo ""
  echo "Existing local users (UID>=1000):"
  getent passwd | awk -F: '$3 >= 1000 && $3 < 65534 {print "  - " $1}'

  echo ""
  log_subsection "Per-user Integrity Check"
  local username
  for username in "${PROVISION_USERS[@]}"; do
    check_user_integrity "${username}"
  done
}

log_subsection "Provisioning Linux User Accounts"

if [[ "${STATUS_ONLY}" == true ]]; then
  print_status
  exit 0
fi

# Bare-repo pre-fetch retired 2026-07-15 — clone_mcp_rag_repo now pulls directly
# from ${UPSTREAM_REPO_URL} as the invoking operator (SUDO_USER). No pre-step
# needed here; the dry-run gate is also unnecessary for a no-op.

for username in "${USERS_TO_PROVISION[@]}"; do
  provision_user "${username}"
done

log_success "User provisioning step complete"
