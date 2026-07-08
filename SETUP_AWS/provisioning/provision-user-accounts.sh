#!/bin/bash
################################################################################
# provision-user-accounts.sh — Create and maintain individual developer accounts
#
# Reads users.conf for the user list. For each user:
#   - Creates the Linux account (if missing)
#   - Copies matching SSH keys from ec2-user's authorized_keys
#   - Sets up ~/.kiro/ with MCP configs and steering files
#   - Adds to the 'developers' group for shared workspace access
#
# Idempotent: safe to re-run. Existing configs are not overwritten (use --force).
#
# Usage:
#   sudo ./provision-user-accounts.sh              # provision all users in users.conf
#   sudo ./provision-user-accounts.sh --force      # overwrite existing .kiro configs
#   sudo ./provision-user-accounts.sh --add <user> # add a single new user interactively
################################################################################
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
USERS_CONF="${SCRIPT_DIR}/users.conf"
TEMPLATES_DIR="${SCRIPT_DIR}/user-templates"
EC2_USER_KEYS="/home/ec2-user/.ssh/authorized_keys"
SHARED_GROUP="developers"
WORKSPACE="/mdc-mcp-rag/eib-mcp-rag-server"
FORCE=false

# Parse flags
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force) FORCE=true; shift ;;
    --add) echo "Add user: append to ${USERS_CONF} then re-run without --add"; exit 0 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

# Must be root
if [[ $EUID -ne 0 ]]; then
  echo "[ERROR] Run with sudo"; exit 1
fi

echo "============================================================"
echo " User Account Provisioning"
echo " Config: ${USERS_CONF}"
echo " Force overwrite: ${FORCE}"
echo "============================================================"
echo ""

# Create shared group
if ! getent group "${SHARED_GROUP}" &>/dev/null; then
  groupadd "${SHARED_GROUP}"
  echo "[OK] Created group '${SHARED_GROUP}'"
else
  echo "[OK] Group '${SHARED_GROUP}' exists"
fi

# Ensure workspace is group-accessible
chgrp -R "${SHARED_GROUP}" "${WORKSPACE}" 2>/dev/null || true
chmod -R g+rX "${WORKSPACE}" 2>/dev/null || true

# Process each user
while IFS=: read -r username fullname email; do
  # Skip comments and empty lines
  [[ -z "$username" || "$username" == \#* ]] && continue

  echo "--- Provisioning: ${username} (${fullname}) ---"

  # 1. Create Linux user
  if ! id "${username}" &>/dev/null; then
    useradd -m -s /bin/bash -G "${SHARED_GROUP}" "${username}"
    echo "  [OK] Created user '${username}'"
  else
    usermod -aG "${SHARED_GROUP}" "${username}" 2>/dev/null || true
    echo "  [OK] User '${username}' exists (group updated)"
  fi

  HOME_DIR="/home/${username}"

  # 2. Copy SSH keys matching this user's email or hostname patterns
  SSH_DIR="${HOME_DIR}/.ssh"
  AUTH_KEYS="${SSH_DIR}/authorized_keys"
  mkdir -p "${SSH_DIR}"
  chmod 700 "${SSH_DIR}"

  # Match keys by email prefix (case-insensitive) or common hostname patterns
  name_prefix="${email%%@*}"
  if [[ -f "${EC2_USER_KEYS}" ]]; then
    grep -i "${name_prefix}" "${EC2_USER_KEYS}" > "${AUTH_KEYS}.new" 2>/dev/null || true
    if [[ -s "${AUTH_KEYS}.new" ]]; then
      # Merge (don't replace — preserve any keys the user added manually)
      if [[ -f "${AUTH_KEYS}" ]]; then
        cat "${AUTH_KEYS}" "${AUTH_KEYS}.new" | sort -u > "${AUTH_KEYS}.merged"
        mv "${AUTH_KEYS}.merged" "${AUTH_KEYS}"
        rm -f "${AUTH_KEYS}.new"
      else
        mv "${AUTH_KEYS}.new" "${AUTH_KEYS}"
      fi
      key_count=$(wc -l < "${AUTH_KEYS}")
      echo "  [OK] ${key_count} SSH key(s) configured"
    else
      rm -f "${AUTH_KEYS}.new"
      echo "  [WARN] No SSH keys matched for '${name_prefix}' in ec2-user keys"
    fi
  fi
  chmod 600 "${AUTH_KEYS}" 2>/dev/null || true
  chown -R "${username}:${username}" "${SSH_DIR}"

  # 3. Set up ~/.kiro directory
  KIRO_DIR="${HOME_DIR}/.kiro"
  KIRO_SETTINGS="${KIRO_DIR}/settings"
  KIRO_STEERING="${KIRO_DIR}/steering"
  KIRO_SKILLS="${KIRO_DIR}/skills"

  mkdir -p "${KIRO_SETTINGS}" "${KIRO_STEERING}" "${KIRO_SKILLS}"

  # MCP config (only write if missing or --force)
  MCP_JSON="${KIRO_SETTINGS}/mcp.json"
  if [[ ! -f "${MCP_JSON}" ]] || [[ "${FORCE}" == "true" ]]; then
    cp "${TEMPLATES_DIR}/mcp.json" "${MCP_JSON}"
    echo "  [OK] MCP config installed"
  else
    echo "  [SKIP] MCP config exists (use --force to overwrite)"
  fi

  # Steering files (only write if missing or --force)
  for steer_file in "${TEMPLATES_DIR}"/steering/*.md; do
    [[ -f "${steer_file}" ]] || continue
    dest="${KIRO_STEERING}/$(basename "${steer_file}")"
    if [[ ! -f "${dest}" ]] || [[ "${FORCE}" == "true" ]]; then
      cp "${steer_file}" "${dest}"
    fi
  done
  steer_count=$(ls "${KIRO_STEERING}"/*.md 2>/dev/null | wc -l)
  echo "  [OK] ${steer_count} steering file(s)"

  # Skills (only write if missing or --force)
  for skill_file in "${TEMPLATES_DIR}"/skills/*.md; do
    [[ -f "${skill_file}" ]] || continue
    dest="${KIRO_SKILLS}/$(basename "${skill_file}")"
    if [[ ! -f "${dest}" ]] || [[ "${FORCE}" == "true" ]]; then
      cp "${skill_file}" "${dest}"
    fi
  done

  # 4. Set up git identity
  GIT_CONFIG="${HOME_DIR}/.gitconfig"
  if [[ ! -f "${GIT_CONFIG}" ]] || [[ "${FORCE}" == "true" ]]; then
    cat > "${GIT_CONFIG}" <<EOF
[user]
    name = ${fullname}
    email = ${email}
[safe]
    directory = ${WORKSPACE}
    directory = ${WORKSPACE}/supported_repos/global-workflow_develop
    directory = ${WORKSPACE}/supported_repos/global-workflow_dev-gfs.v17
[init]
    defaultBranch = develop
EOF
    echo "  [OK] Git config installed"
  fi

  # 5. Set up .bashrc (PATH, env vars, aliases, prompt)
  BASHRC="${HOME_DIR}/.bashrc"
  if [[ ! -f "${BASHRC}" ]] || [[ "${FORCE}" == "true" ]]; then
    cp "${TEMPLATES_DIR}/bashrc" "${BASHRC}"
    # Derive CamelCase scratch dir name from full name (First.Last)
    first=$(echo "${fullname}" | awk '{print $1}')
    last=$(echo "${fullname}" | awk '{print $NF}')
    SCRATCH_NAME="${first}.${last}"
    echo "export SCRATCH=/mdc-mcp-rag/SCRATCH/${SCRATCH_NAME}" >> "${BASHRC}"
    echo "  [OK] .bashrc installed"
  else
    echo "  [SKIP] .bashrc exists (use --force to overwrite)"
  fi

  # 6. Create scratch workspace (CamelCase: First.Last)
  first=$(echo "${fullname}" | awk '{print $1}')
  last=$(echo "${fullname}" | awk '{print $NF}')
  SCRATCH_DIR="/mdc-mcp-rag/SCRATCH/${first}.${last}"
  mkdir -p "${SCRATCH_DIR}"
  chown "${username}:${username}" "${SCRATCH_DIR}"
  echo "  [OK] scratch: ${SCRATCH_DIR}"

  # 7. Set ownership
  chown -R "${username}:${username}" "${HOME_DIR}"

  echo ""
done < "${USERS_CONF}"

echo "============================================================"
echo " Provisioning complete"
echo " Users can connect via SSH: ssh <username>@<host>"
echo " Shared workspace: ${WORKSPACE} (group: ${SHARED_GROUP})"
echo "============================================================"
