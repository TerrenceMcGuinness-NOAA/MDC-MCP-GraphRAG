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
# Beyond provisioning, three read-mostly modes inspect and repair existing
# accounts without going through the create path
# (spec: .kiro/specs/aws-user-provisioning-drift-remediation/):
#   --status      read-only integrity report for every user in users.conf
#   --dry-run     render the plan, mutate nothing
#   --remediate   apply only the surgical fixes a user's drift set calls for
#
# Usage:
#   sudo ./provision-user-accounts.sh                    # provision all users
#   sudo ./provision-user-accounts.sh --force            # overwrite existing configs
#   sudo ./provision-user-accounts.sh --user <name>      # one user (repeatable)
#   sudo ./provision-user-accounts.sh --status           # integrity report only
#   sudo ./provision-user-accounts.sh --dry-run          # plan only, no mutation
#   sudo ./provision-user-accounts.sh --remediate <name> # fix drift (repeatable)
#   sudo ./provision-user-accounts.sh --add <user>       # advisory: edit users.conf
################################################################################
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# shellcheck source=SETUP_AWS/provisioning/common.sh
source "${SCRIPT_DIR}/common.sh"
# shellcheck source=SETUP_AWS/provisioning/user_config.sh
source "${SCRIPT_DIR}/user_config.sh"

USERS_CONF="${SCRIPT_DIR}/users.conf"
TEMPLATES_DIR="${SCRIPT_DIR}/user-templates"
EC2_USER_KEYS="/home/ec2-user/.ssh/authorized_keys"
CREDS_RUNBOOK="RUNBOOK_developer_aws_credentials.md"

# SHARED_GROUP, WORKSPACE, SCRATCH_ROOT and the PROVISION_* knobs come from
# user_config.sh (the SPOT). users.conf remains the SPOT for the user list.

FORCE=false
STATUS_ONLY=false
DRY_RUN=false
TARGET_USERS=()
REMEDIATE_USERS=()

usage() {
  cat << 'EOF'
Usage:
  sudo ./provision-user-accounts.sh                     # Provision all users in users.conf
  sudo ./provision-user-accounts.sh --user <name>       # Provision a specific user (repeatable)
  sudo ./provision-user-accounts.sh --remediate <name>  # Fix drift on an existing user (repeatable)
  sudo ./provision-user-accounts.sh --status            # Read-only integrity report
  sudo ./provision-user-accounts.sh --status --user <name>       # ...scoped to one user
  sudo ./provision-user-accounts.sh --dry-run           # Print the plan; do NOT mutate the host

Options:
  --force                 Overwrite existing ~/.kiro configs, .bashrc, .gitconfig
  --user <username>       Provision only this user (can be repeated).
                          Also scopes --status to the named user(s).
  --remediate <username>  Fix drift on an existing user; refuses to create (repeatable).
                          Mutually exclusive with --user. Also scopes --status.
  --status                Per-user integrity report, no changes
  --dry-run               Render the plan without any mutations
  --add <username>        Advisory: append the user to users.conf, then re-run
  -h, --help              Show this help
EOF
}

# Reject a missing or option-looking value for a flag that takes a username, so
# a misplaced or mistyped flag is never silently consumed as one. Without this,
# `--user --help` bound the username "--help" and then fell through into a real
# provisioning run instead of printing usage.
require_value() {
  local flag="$1"
  local value="${2:-}"
  if [[ -z "${value}" ]]; then
    echo "[ERROR] ${flag} requires a username"
    usage
    exit 2
  fi
  if [[ "${value}" == -* ]]; then
    echo "[ERROR] ${flag} requires a username, got the option '${value}'"
    usage
    exit 2
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force)
      FORCE=true
      shift
      ;;
    --user)
      require_value "--user" "${2:-}"
      TARGET_USERS+=("$2")
      shift 2
      ;;
    --remediate)
      require_value "--remediate" "${2:-}"
      REMEDIATE_USERS+=("$2")
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
    --add)
      echo "Add user: append to ${USERS_CONF} then re-run without --add"
      exit 0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[ERROR] Unknown arg: $1"
      usage
      exit 2
      ;;
  esac
done

# Mutual-exclusion guard: --user (create/refresh) and --remediate (fix existing)
# express opposing intents in one invocation. Reject up front rather than letting
# one silently override the other.
if [[ ${#TARGET_USERS[@]} -gt 0 ]] && [[ ${#REMEDIATE_USERS[@]} -gt 0 ]]; then
  echo "[ERROR] --user and --remediate are mutually exclusive in the same invocation"
  exit 2
fi

require_root

if [[ ! -r "${USERS_CONF}" ]]; then
  log_error "Cannot read ${USERS_CONF}"
  exit 2
fi

################################################################################
# users.conf accessors
#
# users.conf format: username:full_name:email
# The scratch directory leaf is CamelCase First.Last derived from the full-name
# field — it cannot be derived from the lowercase login name.
################################################################################

# Print field <n> of <username>'s users.conf line; empty when the user is absent.
user_field() {
  local username="$1" field="$2"
  awk -F: -v u="${username}" -v f="${field}" \
    '$1 == u { print $f; exit }' "${USERS_CONF}"
}

user_fullname() { user_field "$1" 2; }
user_email()    { user_field "$1" 3; }

# "Terry McGuinness" -> "Terry.McGuinness"
scratch_name_for() {
  local fullname="$1"
  local first last
  first=$(echo "${fullname}" | awk '{print $1}')
  last=$(echo "${fullname}" | awk '{print $NF}')
  echo "${first}.${last}"
}

# Absolute scratch directory for <username>; empty when not in users.conf.
user_scratch_dir() {
  local username="$1" fullname
  fullname="$(user_fullname "${username}")"
  [[ -n "${fullname}" ]] || return 0
  echo "${SCRATCH_ROOT}/$(scratch_name_for "${fullname}")"
}

in_list() {
  local needle="$1"
  shift
  local item
  for item in "$@"; do
    [[ "${item}" == "${needle}" ]] && return 0
  done
  return 1
}

user_is_kiro_exempt() {
  local username="$1"
  [[ ${#PROVISION_KIRO_EXEMPT_USERS[@]} -eq 0 ]] && return 1
  in_list "${username}" "${PROVISION_KIRO_EXEMPT_USERS[@]}"
}

################################################################################
# Shared-checkout git access
#
# AWS deliberately has NO per-user clone of this repo in scratch: the MCP server
# runs remotely in AgentCore, so a developer's only local need is the proxy script
# and tooling read out of the ONE shared checkout at ${WORKSPACE}. See
# RUNBOOK_user_drift_remediation.md § "Why there is no per-user clone".
#
# That model has one hard requirement: the shared tree is owned by ec2-user, so
# every other account needs a git `safe.directory` exception for it, or git
# refuses to operate there at all ("detected dubious ownership"). The entries are
# enumerated FROM DISK rather than hardcoded — the previous hardcoded list named
# supported_repos/global-workflow and .../global-workflow_dev-v17, neither of
# which has existed since the multi-tenant rename, which left all of the real
# checkouts unusable for every developer.
################################################################################

# Print every shared git repository a developer needs an exception for: the
# workspace itself plus each supported_repos entry that is a git repo (submodules
# carry a .git *file*, standalone clones a .git *directory* — -e covers both).
shared_git_repos() {
  echo "${WORKSPACE}"
  local d
  for d in "${WORKSPACE}"/supported_repos/*; do
    [[ -e "${d}/.git" ]] && echo "${d}"
  done
}

# Print the shared repos NOT covered by <username>'s ~/.gitconfig safe.directory
# entries. A wildcard entry (`directory = *`) covers everything.
missing_safe_dirs() {
  local username="$1"
  local gitconfig="/home/${username}/.gitconfig"

  if [[ ! -f "${gitconfig}" ]]; then
    shared_git_repos
    return 0
  fi
  if grep -qE '^[[:space:]]*directory[[:space:]]*=[[:space:]]*\*[[:space:]]*$' "${gitconfig}" 2>/dev/null; then
    return 0
  fi

  local repo
  while read -r repo; do
    grep -qF "directory = ${repo}" "${gitconfig}" 2>/dev/null || echo "${repo}"
  done < <(shared_git_repos)
}

# Print the AWS_PROFILE env value configured in an mcp.json, or nothing when no
# server declares one. Prints __PARSE_ERROR__ when the file is not valid JSON so
# an unparseable config is reported honestly instead of looking like "absent".
mcp_json_profile() {
  local file="$1"
  [[ -f "${file}" ]] || return 0
  python3 - "${file}" << 'PY' 2>/dev/null || true
import json
import sys

try:
    with open(sys.argv[1]) as handle:
        cfg = json.load(handle)
except Exception:
    print("__PARSE_ERROR__")
    sys.exit(0)

for server in (cfg.get("mcpServers") or {}).values():
    env = server.get("env") or {}
    if "AWS_PROFILE" in env:
        print(env["AWS_PROFILE"])
        break
PY
}

################################################################################
# Provisioning stages reused by remediation
#
# The remaining six stages stay inline in the provisioning loop below; only the
# two that remediation needs to reuse are functions (design.md § "The two
# extractions").
################################################################################

# Deploy ~/.kiro/{settings/mcp.json, steering/*.md, skills/*.md} from the
# templates. Existing files are left alone unless FORCE=true.
install_kiro_assets() {
  local username="$1"
  local home_dir="/home/${username}"
  local kiro_dir="${home_dir}/.kiro"
  local kiro_settings="${kiro_dir}/settings"
  local kiro_steering="${kiro_dir}/steering"
  local kiro_skills="${kiro_dir}/skills"
  local owner_group
  owner_group="$(resolve_ownership "${username}")"

  mkdir -p "${kiro_settings}" "${kiro_steering}" "${kiro_skills}"

  local mcp_json="${kiro_settings}/mcp.json"
  if [[ ! -f "${mcp_json}" ]] || [[ "${FORCE}" == "true" ]]; then
    cp "${TEMPLATES_DIR}/mcp.json" "${mcp_json}"
    echo "  [OK] MCP config installed"
  else
    echo "  [SKIP] MCP config exists (use --force to overwrite)"
  fi

  local steer_file skill_file dest
  for steer_file in "${TEMPLATES_DIR}"/steering/*.md; do
    [[ -f "${steer_file}" ]] || continue
    dest="${kiro_steering}/$(basename "${steer_file}")"
    if [[ ! -f "${dest}" ]] || [[ "${FORCE}" == "true" ]]; then
      cp "${steer_file}" "${dest}"
    fi
  done
  local steer_count
  steer_count=$(find "${kiro_steering}" -maxdepth 1 -name '*.md' 2>/dev/null | wc -l)
  echo "  [OK] ${steer_count} steering file(s)"

  for skill_file in "${TEMPLATES_DIR}"/skills/*.md; do
    [[ -f "${skill_file}" ]] || continue
    dest="${kiro_skills}/$(basename "${skill_file}")"
    if [[ ! -f "${dest}" ]] || [[ "${FORCE}" == "true" ]]; then
      cp "${skill_file}" "${dest}"
    fi
  done

  # The provisioning loop also chowns all of ${HOME_DIR} at stage 8, but
  # remediation does not run that stage — so own our output here.
  chown -R "${owner_group}" "${kiro_dir}"
}

# Create ~/.aws with a config + credentials skeleton.
# NEVER overwrites an existing file: a real access key pasted by the user is
# unrecoverable if clobbered. Each file is written only when absent.
install_aws_skeleton() {
  local username="$1"
  local aws_dir="/home/${username}/.aws"
  local owner_group
  owner_group="$(resolve_ownership "${username}")"

  mkdir -p "${aws_dir}"
  chmod 700 "${aws_dir}"

  if [[ ! -f "${aws_dir}/config" ]]; then
    cat > "${aws_dir}/config" << EOF
[default]
region = us-east-1
output = json
EOF
    chmod 600 "${aws_dir}/config"
    echo "  [OK] ~/.aws/config created"
  fi

  if [[ ! -f "${aws_dir}/credentials" ]]; then
    cat > "${aws_dir}/credentials" << EOF
[${PROVISION_AWS_PROFILE}]
# Create an access key in the AWS Console:
#   https://903050880929.signin.aws.amazon.com/console
#   → Security credentials → Access keys → Create access key
# See: SETUP_AWS/provisioning/${CREDS_RUNBOOK}
aws_access_key_id = ${PROVISION_AWS_CRED_PLACEHOLDER}
aws_secret_access_key = PASTE_YOUR_SECRET_ACCESS_KEY_HERE
EOF
    chmod 600 "${aws_dir}/credentials"
    echo "  [OK] ~/.aws/credentials created (user must add access keys — see ${CREDS_RUNBOOK})"
  fi

  chown -R "${owner_group}" "${aws_dir}"
}

# Write ~/.gitconfig: git identity plus a safe.directory exception for every
# shared repo. Called only when the file is absent (or with --force) — see
# add_missing_safe_dirs() for the non-destructive repair path used on existing
# accounts, which appends the missing entries instead of rewriting the file.
write_gitconfig() {
  local username="$1"
  local fullname="$2"
  local email="$3"
  local gitconfig="/home/${username}/.gitconfig"
  local repo

  {
    echo "[user]"
    echo "    name = ${fullname}"
    echo "    email = ${email}"
    echo "[safe]"
    while read -r repo; do
      echo "    directory = ${repo}"
    done < <(shared_git_repos)
    echo "[init]"
    echo "    defaultBranch = develop"
  } > "${gitconfig}"

  chown "$(resolve_ownership "${username}")" "${gitconfig}"
}

# Append the missing safe.directory entries to an EXISTING ~/.gitconfig, one
# `git config --global --add` at a time, run as the user. Surgical and idempotent:
# aliases, credential helpers, and anything else the developer has added are
# preserved. This is why safe.directory drift needs no --force.
add_missing_safe_dirs() {
  local username="$1"
  local repo count=0

  while read -r repo; do
    [[ -n "${repo}" ]] || continue
    sudo -u "${username}" git config --global --add safe.directory "${repo}" \
      && count=$((count + 1)) \
      || log_error "could not add safe.directory ${repo} for ${username}"
  done < <(missing_safe_dirs "${username}")

  echo "  [OK] ${count} safe.directory entr(ies) added"
}

################################################################################
# Read-only inspection
################################################################################

# Format a 3-digit octal mode with a leading zero for display
# (stat -c '%a' emits "700"; we want "0700").
_fmt_mode() {
  local mode="$1"
  if [[ ${#mode} -eq 3 ]]; then
    echo "0${mode}"
  else
    echo "${mode}"
  fi
}

# check_user_integrity — human-facing per-user report used by --status and by the
# post-remediation re-check. Every check is read-only.
#
# Rows are OMITTED rather than faked when the underlying condition does not apply
# on this host: the primary-group row is absent while PROVISION_PRIMARY_GROUP is
# empty (the AWS default), and all ~/.kiro rows are absent for users on
# PROVISION_KIRO_EXEMPT_USERS.
check_user_integrity() {
  local username="$1"
  local fullname
  fullname="$(user_fullname "${username}")"

  echo ""
  if [[ -n "${fullname}" ]]; then
    echo "User: ${username} (${fullname})"
  else
    echo "User: ${username}"
    echo "  users.conf: [DRIFT expected=present actual=missing]"
    return 0
  fi

  # [1] Account existence — every downstream check needs a real UID/GID/home.
  if ! id "${username}" &> /dev/null; then
    echo "  account: [DRIFT expected=exists actual=missing]"
    return 0
  fi
  echo "  account: [OK]"

  # [2] Primary group — only meaningful when the SPOT names a shared group.
  if [[ -n "${PROVISION_PRIMARY_GROUP}" ]]; then
    local actual_group
    actual_group="$(get_user_group "${username}")"
    if [[ "${actual_group}" == "${PROVISION_PRIMARY_GROUP}" ]]; then
      echo "  primary group: ${PROVISION_PRIMARY_GROUP} [OK]"
    else
      echo "  primary group: [DRIFT expected=${PROVISION_PRIMARY_GROUP} actual=${actual_group}]"
    fi
  fi

  # [3] Supplementary groups — only those that exist on this host.
  local -a expected_supp=()
  local g
  for g in "${PROVISION_SUPP_GROUPS[@]}"; do
    if getent group "${g}" > /dev/null 2>&1; then
      expected_supp+=("${g}")
    fi
  done
  if [[ ${#expected_supp[@]} -eq 0 ]]; then
    echo "  supplementary groups: (none applicable on this host) [OK]"
  else
    local expected_str user_groups
    expected_str="$(IFS=,; echo "${expected_supp[*]}")"
    user_groups=" $(id -Gn "${username}" 2>/dev/null || echo "") "
    local -a missing=() has=()
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
      [[ ${#has[@]} -gt 0 ]] && has_str="$(IFS=,; echo "${has[*]}")"
      echo "  supplementary groups: [DRIFT expected=${expected_str} actual=${has_str}]"
    fi
  fi

  # [4] Scratch dir + ownership
  local scratch_dir expected_owner
  scratch_dir="$(user_scratch_dir "${username}")"
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

  # [5]/[6] ~/.ssh and ~/.ssh/authorized_keys modes
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

  # [7]/[8] ~/.aws directory and credentials modes
  local aws_dir="${home_dir}/.aws"
  local aws_creds="${aws_dir}/credentials"

  if [[ ! -d "${aws_dir}" ]]; then
    echo "  ~/.aws mode: [DRIFT expected=0700 actual=missing]"
  else
    local aws_mode
    aws_mode="$(stat -c '%a' "${aws_dir}" 2>/dev/null || echo "unknown")"
    if [[ "${aws_mode}" == "700" ]]; then
      echo "  ~/.aws mode: 0700 [OK]"
    else
      echo "  ~/.aws mode: [DRIFT expected=0700 actual=$(_fmt_mode "${aws_mode}")]"
    fi
  fi

  if [[ ! -f "${aws_creds}" ]]; then
    echo "  ~/.aws/credentials mode: [DRIFT expected=0600 actual=missing]"
  else
    local creds_mode
    creds_mode="$(stat -c '%a' "${aws_creds}" 2>/dev/null || echo "unknown")"
    if [[ "${creds_mode}" == "600" ]]; then
      echo "  ~/.aws/credentials mode: 0600 [OK]"
    else
      echo "  ~/.aws/credentials mode: [DRIFT expected=0600 actual=$(_fmt_mode "${creds_mode}")]"
    fi
    # Placeholder detection is a boolean grep; file contents are never echoed.
    if grep -q "${PROVISION_AWS_CRED_PLACEHOLDER}" "${aws_creds}" 2>/dev/null; then
      echo "  ~/.aws/credentials: [PENDING user action — placeholder key; see ${CREDS_RUNBOOK}]"
    fi
  fi

  # [9]/[10] git access to the shared checkout — the shared-workspace model's
  # hard requirement (no per-user clone exists; see the RUNBOOK).
  local gitconfig="${home_dir}/.gitconfig"
  if [[ ! -f "${gitconfig}" ]]; then
    echo "  ~/.gitconfig: [DRIFT expected=present actual=missing]"
  else
    echo "  ~/.gitconfig: [OK]"
    local -a missing_dirs=()
    mapfile -t missing_dirs < <(missing_safe_dirs "${username}")
    local total_repos
    total_repos=$(shared_git_repos | wc -l)
    if [[ ${#missing_dirs[@]} -eq 0 ]]; then
      echo "  git safe.directory: ${total_repos}/${total_repos} shared repo(s) [OK]"
    else
      echo "  git safe.directory: [DRIFT expected=${total_repos} shared repo(s) actual=$((total_repos - ${#missing_dirs[@]}))]"
      echo "      ${#missing_dirs[@]} unlisted → git refuses to operate in them (dubious ownership)"
    fi
  fi

  # [11]-[13] ~/.kiro assets (omitted entirely for exempt users)
  if user_is_kiro_exempt "${username}"; then
    return 0
  fi

  local mcp_json="${home_dir}/.kiro/settings/mcp.json"
  local steering_dir="${home_dir}/.kiro/steering"

  if [[ -f "${mcp_json}" ]]; then
    echo "  ~/.kiro/settings/mcp.json: [OK]"
  else
    echo "  ~/.kiro/settings/mcp.json: [DRIFT expected=present actual=missing]"
  fi

  local steer_count=0
  if [[ -d "${steering_dir}" ]]; then
    steer_count=$(find "${steering_dir}" -maxdepth 1 -name '*.md' 2>/dev/null | wc -l)
  fi
  if [[ "${steer_count}" -gt 0 ]]; then
    echo "  ~/.kiro/steering: ${steer_count} file(s) [OK]"
  else
    echo "  ~/.kiro/steering: [DRIFT expected=>=1 file actual=${steer_count}]"
  fi

  if [[ -f "${mcp_json}" ]]; then
    local actual_profile
    actual_profile="$(mcp_json_profile "${mcp_json}")"
    local expected_profile="${PROVISION_AWS_PROFILE:-(none)}"
    local shown_profile="${actual_profile:-(none)}"
    [[ "${actual_profile}" == "__PARSE_ERROR__" ]] && shown_profile="(unparseable JSON)"
    if [[ "${actual_profile}" == "${PROVISION_AWS_PROFILE}" ]]; then
      echo "  mcp.json AWS_PROFILE: ${shown_profile} [OK]"
    else
      echo "  mcp.json AWS_PROFILE: [DRIFT expected=${expected_profile} actual=${shown_profile}]"
    fi
  fi
}

# check_user_drifts — machine-parseable drift feed consumed by remediate_user.
#
# Sibling of check_user_integrity: the two MUST report the same drift set, one
# as prose and one as tag lines. Emits one tag line per drift on stdout:
#
#   primary_group <actual>          scratch_missing
#   scratch_owner <actual>          supp_groups <a,b>
#   ssh_dir_mode <actual>          auth_keys_mode <actual>
#   aws_dir_mode <actual>          aws_creds_mode <actual>
#   missing_kiro_mcp               missing_kiro_steering
#   stale_kiro_profile <actual>    aws_creds_placeholder
#   missing_gitconfig              stale_git_safe_dirs <count>
#
# A clean user emits nothing — the caller distinguishes "no drift" from "some
# drift" by testing for an empty result. Every check is read-only.
check_user_drifts() {
  local username="$1"
  local -a drifts=()

  # primary group (inert while PROVISION_PRIMARY_GROUP is empty)
  if [[ -n "${PROVISION_PRIMARY_GROUP}" ]]; then
    local actual_group
    actual_group="$(get_user_group "${username}")"
    [[ "${actual_group}" != "${PROVISION_PRIMARY_GROUP}" ]] \
      && drifts+=("primary_group ${actual_group}")
  fi

  # scratch dir presence + top-level owner
  local scratch expected_owner
  scratch="$(user_scratch_dir "${username}")"
  expected_owner="$(resolve_ownership "${username}")"
  if [[ -z "${scratch}" ]]; then
    : # user not in users.conf; check_user_integrity reports it
  elif [[ ! -d "${scratch}" ]]; then
    drifts+=("scratch_missing")
  else
    local actual_owner
    actual_owner="$(stat -c '%U:%G' "${scratch}" 2>/dev/null || echo "")"
    [[ "${actual_owner}" != "${expected_owner}" ]] \
      && drifts+=("scratch_owner ${actual_owner}")
  fi

  # supplementary groups — only those that exist on host
  local -a missing=()
  local g
  for g in "${PROVISION_SUPP_GROUPS[@]}"; do
    if getent group "${g}" > /dev/null 2>&1; then
      id -nG "${username}" 2>/dev/null | tr ' ' '\n' | grep -qx "${g}" \
        || missing+=("${g}")
    fi
  done
  [[ ${#missing[@]} -gt 0 ]] && drifts+=("supp_groups $(IFS=,; echo "${missing[*]}")")

  local home_dir
  home_dir="$(getent passwd "${username}" | cut -d: -f6)"

  # ~/.ssh + authorized_keys modes
  local ssh_dir="${home_dir}/.ssh"
  local auth_keys="${ssh_dir}/authorized_keys"
  if [[ ! -d "${ssh_dir}" ]]; then
    drifts+=("ssh_dir_mode missing")
  else
    local ssh_mode
    ssh_mode="$(stat -c '%a' "${ssh_dir}" 2>/dev/null || echo "")"
    [[ "${ssh_mode}" != "700" ]] && drifts+=("ssh_dir_mode ${ssh_mode}")
  fi
  if [[ ! -f "${auth_keys}" ]]; then
    drifts+=("auth_keys_mode missing")
  else
    local ak_mode
    ak_mode="$(stat -c '%a' "${auth_keys}" 2>/dev/null || echo "")"
    [[ "${ak_mode}" != "600" ]] && drifts+=("auth_keys_mode ${ak_mode}")
  fi

  # ~/.aws dir + credentials modes, then the placeholder-key condition
  local aws_dir="${home_dir}/.aws"
  local aws_creds="${aws_dir}/credentials"
  if [[ ! -d "${aws_dir}" ]]; then
    drifts+=("aws_dir_mode missing")
  else
    local aws_mode
    aws_mode="$(stat -c '%a' "${aws_dir}" 2>/dev/null || echo "")"
    [[ "${aws_mode}" != "700" ]] && drifts+=("aws_dir_mode ${aws_mode}")
  fi
  if [[ ! -f "${aws_creds}" ]]; then
    drifts+=("aws_creds_mode missing")
  else
    local creds_mode
    creds_mode="$(stat -c '%a' "${aws_creds}" 2>/dev/null || echo "")"
    [[ "${creds_mode}" != "600" ]] && drifts+=("aws_creds_mode ${creds_mode}")
    grep -q "${PROVISION_AWS_CRED_PLACEHOLDER}" "${aws_creds}" 2>/dev/null \
      && drifts+=("aws_creds_placeholder")
  fi

  # git access to the shared checkout
  local gitconfig="${home_dir}/.gitconfig"
  if [[ ! -f "${gitconfig}" ]]; then
    drifts+=("missing_gitconfig")
  else
    local -a missing_dirs=()
    mapfile -t missing_dirs < <(missing_safe_dirs "${username}")
    [[ ${#missing_dirs[@]} -gt 0 ]] && drifts+=("stale_git_safe_dirs ${#missing_dirs[@]}")
  fi

  # ~/.kiro assets (skipped entirely for exempt users)
  if ! user_is_kiro_exempt "${username}"; then
    local mcp_json="${home_dir}/.kiro/settings/mcp.json"
    local steering_dir="${home_dir}/.kiro/steering"

    [[ -f "${mcp_json}" ]] || drifts+=("missing_kiro_mcp")

    local steer_count=0
    if [[ -d "${steering_dir}" ]]; then
      steer_count=$(find "${steering_dir}" -maxdepth 1 -name '*.md' 2>/dev/null | wc -l)
    fi
    [[ "${steer_count}" -gt 0 ]] || drifts+=("missing_kiro_steering")

    if [[ -f "${mcp_json}" ]]; then
      local actual_profile
      actual_profile="$(mcp_json_profile "${mcp_json}")"
      [[ "${actual_profile}" != "${PROVISION_AWS_PROFILE}" ]] \
        && drifts+=("stale_kiro_profile ${actual_profile:-(none)}")
    fi
  fi

  # Guard the empty-array case so the expansion does not trip `set -u`, and
  # preserve the "clean user prints nothing" contract.
  if [[ ${#drifts[@]} -gt 0 ]]; then
    printf '%s\n' "${drifts[@]}"
  fi
}

# print_status — the --status report.
#
# With no arguments, reports every user in users.conf. With arguments, reports
# only the named users, so `--status --user <name>` narrows the report instead of
# dumping the whole host. Names not present in users.conf still produce a block
# (with a users.conf drift row) rather than being silently dropped.
print_status() {
  local -a users=("$@")
  local username

  if [[ ${#users[@]} -eq 0 ]]; then
    while IFS=: read -r username _; do
      [[ -z "${username}" || "${username}" == \#* ]] && continue
      users+=("${username}")
    done < "${USERS_CONF}"
  fi

  log_subsection "User Provisioning Status"
  if [[ $# -gt 0 ]]; then
    echo "Scoped to ${#users[@]} requested user(s):"
    printf '  - %s\n' "${users[@]}"
  else
    echo "Configured users (${USERS_CONF}):"
    awk -F: '!/^[[:space:]]*#/ && NF >= 2 { print "  - " $1 "  (" $2 ")" }' "${USERS_CONF}"
    echo ""
    echo "Existing local users (UID>=1000):"
    getent passwd | awk -F: '$3 >= 1000 && $3 < 65534 {print "  - " $1}'
  fi
  echo ""
  echo "Scratch root:      ${SCRATCH_ROOT}"
  echo "Shared workspace:  ${WORKSPACE} (group: ${SHARED_GROUP})"
  if [[ -n "${PROVISION_PRIMARY_GROUP}" ]]; then
    echo "Primary group:     ${PROVISION_PRIMARY_GROUP} (shared)"
  else
    echo "Primary group:     (per-user private group — AWS default)"
  fi

  log_subsection "Per-user Integrity Check"
  for username in "${users[@]}"; do
    check_user_integrity "${username}"
  done
  echo ""
}

################################################################################
# Plan renderers (--dry-run)
################################################################################

# Mirror of the eight numbered stages the provisioning loop performs, with
# resolved substitution and no side effects.
render_provisioning_plan() {
  local username="$1"
  local fullname="$2"
  local home_dir="/home/${username}"
  local scratch_dir owner_group email
  scratch_dir="${SCRATCH_ROOT}/$(scratch_name_for "${fullname}")"
  owner_group="$(resolve_ownership "${username}")"
  email="$(user_email "${username}")"

  echo ""
  echo "═══════════════════════════════════════════════════════════════════"
  echo "  DRY-RUN PLAN for user: ${username} (${fullname})"
  echo "  (no mutations will be performed)"
  echo "═══════════════════════════════════════════════════════════════════"
  echo ""

  echo "[1] Linux account"
  if id "${username}" &> /dev/null; then
    echo "    (user exists; useradd skipped)"
    echo "    usermod -aG ${SHARED_GROUP} ${username}"
  else
    echo "    useradd -m -s /bin/bash -G ${SHARED_GROUP} ${username}"
  fi
  echo ""

  echo "[2] SSH authorized_keys"
  echo "    mkdir -p ${home_dir}/.ssh && chmod 700 ${home_dir}/.ssh"
  echo "    grep -i '${email%%@*}' ${EC2_USER_KEYS} >> ${home_dir}/.ssh/authorized_keys  # merged, sort -u"
  echo "    chmod 600 ${home_dir}/.ssh/authorized_keys"
  echo "    chown -R ${username}:${username} ${home_dir}/.ssh"
  echo ""

  echo "[3] Kiro assets (install_kiro_assets)"
  echo "    mkdir -p ${home_dir}/.kiro/{settings,steering,skills}"
  echo "    cp ${TEMPLATES_DIR}/mcp.json ${home_dir}/.kiro/settings/mcp.json    # if missing or --force"
  echo "    cp ${TEMPLATES_DIR}/steering/*.md ${home_dir}/.kiro/steering/       # if missing or --force"
  echo "    cp ${TEMPLATES_DIR}/skills/*.md   ${home_dir}/.kiro/skills/         # if missing or --force"
  echo "    chown -R ${owner_group} ${home_dir}/.kiro"
  echo ""

  echo "[4] Git identity + shared-checkout access"
  echo "    write ${home_dir}/.gitconfig    # user.name='${fullname}' user.email='${email}'"
  echo "                                    # safe.directory x $(shared_git_repos | wc -l) (workspace + every"
  echo "                                    # supported_repos checkout, enumerated from disk)"
  echo "    (existing file: appended to, never rewritten)"
  echo ""

  echo "[5] Bash environment"
  echo "    cp ${TEMPLATES_DIR}/bashrc ${home_dir}/.bashrc    # if missing or --force"
  echo "    append: export SCRATCH=${scratch_dir}"
  echo ""

  echo "[6] AWS CLI skeleton (install_aws_skeleton)"
  echo "    mkdir -p ${home_dir}/.aws && chmod 700 ${home_dir}/.aws"
  echo "    write ${home_dir}/.aws/config       # if absent (region=us-east-1)"
  echo "    write ${home_dir}/.aws/credentials  # if absent ([${PROVISION_AWS_PROFILE}] + placeholder keys)"
  echo "    chmod 600 on both; never overwrites an existing file"
  echo ""

  echo "[7] Scratch workspace"
  echo "    mkdir -p ${scratch_dir}"
  echo "    chown ${owner_group} ${scratch_dir}"
  echo ""

  echo "[8] Home ownership"
  echo "    chown -R ${username}:${username} ${home_dir}"
  echo ""
  echo "═══════════════════════════════════════════════════════════════════"
  echo "  END DRY-RUN PLAN — nothing was written to the host"
  echo "═══════════════════════════════════════════════════════════════════"
  echo ""
}

# Render the surgical fixes remediate_user would apply, one numbered section per
# drift row actually present. A user with a single drift sees a single section
# numbered [1].
render_remediation_plan() {
  local username="$1"
  local drifts="$2"
  local home_dir="/home/${username}"
  local scratch owner_group
  scratch="$(user_scratch_dir "${username}")"
  owner_group="$(resolve_ownership "${username}")"

  echo ""
  echo "═══════════════════════════════════════════════════════════════════"
  echo "  DRY-RUN REMEDIATION PLAN for user: ${username}"
  echo "  (no mutations will be performed)"
  echo "═══════════════════════════════════════════════════════════════════"
  echo ""

  local n=0

  if grep -q '^primary_group ' <<< "${drifts}"; then
    n=$((n + 1))
    echo "[${n}] Primary group"
    if getent group "${PROVISION_PRIMARY_GROUP}" > /dev/null 2>&1; then
      echo "    usermod -g ${PROVISION_PRIMARY_GROUP} ${username}"
    else
      echo "    # WARN: primary group '${PROVISION_PRIMARY_GROUP}' missing on host — would skip"
    fi
    echo ""
  fi

  if grep -q '^scratch_missing' <<< "${drifts}"; then
    n=$((n + 1))
    echo "[${n}] Scratch workspace (missing)"
    echo "    mkdir -p ${scratch}"
    echo "    chown ${owner_group} ${scratch}"
    echo "    chmod 755 ${scratch}"
    echo ""
  fi

  if grep -q '^scratch_owner ' <<< "${drifts}"; then
    n=$((n + 1))
    echo "[${n}] Scratch dir top-level: ${scratch}"
    echo "    chown ${owner_group} ${scratch}    # top-level only (preserve-safe)"

    local -a prestaged=()
    mapfile -t prestaged < <(list_prestaged_paths "${scratch}" "${username}")
    if [[ ${#prestaged[@]} -gt 0 ]]; then
      if [[ "${PROVISION_ADOPT_PRESTAGED}" == "yes" ]]; then
        echo "    chown -R ${owner_group} ${scratch}    # ADOPT ${#prestaged[@]} pre-staged path(s)"
      else
        echo ""
        echo "    [PRESERVED] ${#prestaged[@]} pre-staged child path(s) will NOT be re-owned"
        echo "                (set PROVISION_ADOPT_PRESTAGED=yes to adopt instead):"
        printf '      [PRESERVED] %s\n' "${prestaged[@]}"
      fi
    fi
    echo ""
  fi

  if grep -q '^supp_groups ' <<< "${drifts}"; then
    n=$((n + 1))
    echo "[${n}] Supplementary group memberships"
    local missing_line missing g
    missing_line="$(grep '^supp_groups ' <<< "${drifts}")"
    missing="${missing_line#supp_groups }"
    for g in ${missing//,/ }; do
      if getent group "${g}" > /dev/null 2>&1; then
        echo "    usermod -aG ${g} ${username}"
      else
        echo "    # WARN: supplementary group '${g}' missing on host — would skip"
      fi
    done
    echo ""
  fi

  if grep -q '^ssh_dir_mode ' <<< "${drifts}"; then
    n=$((n + 1))
    echo "[${n}] ~/.ssh permissions"
    echo "    mkdir -p ${home_dir}/.ssh    # if missing"
    echo "    chmod 700 ${home_dir}/.ssh"
    echo "    chown ${owner_group} ${home_dir}/.ssh"
    echo ""
  fi

  if grep -q '^auth_keys_mode ' <<< "${drifts}"; then
    n=$((n + 1))
    echo "[${n}] ~/.ssh/authorized_keys permissions"
    echo "    touch ${home_dir}/.ssh/authorized_keys    # if missing"
    echo "    chmod 600 ${home_dir}/.ssh/authorized_keys"
    echo "    chown ${owner_group} ${home_dir}/.ssh/authorized_keys"
    echo ""
  fi

  if grep -qE '^aws_(dir|creds)_mode ' <<< "${drifts}"; then
    n=$((n + 1))
    echo "[${n}] ~/.aws skeleton and permissions (install_aws_skeleton)"
    echo "    mkdir -p ${home_dir}/.aws && chmod 700 ${home_dir}/.aws"
    echo "    write ${home_dir}/.aws/config       # ONLY if absent"
    echo "    write ${home_dir}/.aws/credentials  # ONLY if absent — never clobbers a real key"
    echo "    chmod 600 ${home_dir}/.aws/{config,credentials}"
    echo "    chown -R ${owner_group} ${home_dir}/.aws"
    echo ""
  fi

  if grep -qE '^missing_gitconfig|^stale_git_safe_dirs ' <<< "${drifts}"; then
    n=$((n + 1))
    if grep -q '^missing_gitconfig' <<< "${drifts}"; then
      echo "[${n}] ~/.gitconfig (missing)"
      echo "    write ${home_dir}/.gitconfig    # identity + safe.directory for"
      echo "                                    # $(shared_git_repos | wc -l) shared repo(s)"
    else
      local -a missing_dirs=()
      mapfile -t missing_dirs < <(missing_safe_dirs "${username}")
      echo "[${n}] git safe.directory — ${#missing_dirs[@]} shared repo(s) unlisted"
      echo "    (appended one at a time as ${username}; ~/.gitconfig is NOT rewritten,"
      echo "     so aliases and other settings are preserved)"
      local d
      for d in "${missing_dirs[@]}"; do
        echo "    sudo -u ${username} git config --global --add safe.directory ${d}"
      done
    fi
    echo ""
  fi

  if grep -qE '^missing_kiro_(mcp|steering)' <<< "${drifts}"; then
    n=$((n + 1))
    echo "[${n}] ~/.kiro assets (install_kiro_assets)"
    echo "    mkdir -p ${home_dir}/.kiro/{settings,steering,skills}"
    echo "    cp ${TEMPLATES_DIR}/mcp.json ${home_dir}/.kiro/settings/mcp.json"
    echo "    cp ${TEMPLATES_DIR}/steering/*.md ${home_dir}/.kiro/steering/"
    echo "    chown -R ${owner_group} ${home_dir}/.kiro"
    echo ""
  fi

  if grep -q '^stale_kiro_profile ' <<< "${drifts}"; then
    n=$((n + 1))
    echo "[${n}] mcp.json AWS_PROFILE mismatch (expected '${PROVISION_AWS_PROFILE}')"
    if [[ "${FORCE}" == "true" ]]; then
      echo "    cp ${home_dir}/.kiro/settings/mcp.json ${home_dir}/.kiro/settings/mcp.json.bak.<UTC>"
      echo "    cp ${TEMPLATES_DIR}/mcp.json ${home_dir}/.kiro/settings/mcp.json"
      echo "    chown ${owner_group} ${home_dir}/.kiro/settings/mcp.json"
    else
      echo "    (report only — re-run with --force to redeploy the template;"
      echo "     a redeploy DROPS user customisations such as edited autoApprove"
      echo "     lists or extra servers. A timestamped backup is written first.)"
    fi
    echo ""
  fi

  if grep -q '^aws_creds_placeholder' <<< "${drifts}"; then
    n=$((n + 1))
    echo "[${n}] ~/.aws/credentials still holds the placeholder access key"
    echo "    (no operator action — ${username} must paste their own IAM key;"
    echo "     see SETUP_AWS/provisioning/${CREDS_RUNBOOK})"
    echo ""
  fi

  echo "═══════════════════════════════════════════════════════════════════"
  echo "  END DRY-RUN REMEDIATION PLAN — nothing was written to the host"
  echo "═══════════════════════════════════════════════════════════════════"
  echo ""
}

################################################################################
# Remediation
################################################################################

# remediate_user — apply only the surgical fixes the drift set calls for.
#
# Refuses to touch a non-existent user (this path is not for creation). Honors
# the --dry-run gate by delegating to render_remediation_plan. On a real run,
# ends with a check_user_integrity re-check so the operator sees the
# post-remediation state.
#
# Usage:  remediate_user <username>
# Return: 0 on success or clean no-op; 1 on refusal or unrecoverable error.
remediate_user() {
  local username="$1"

  log_subsection "Remediating user: ${username}"

  # Refuse on a non-existent user. Pre-flighted before drift detection so the
  # refusal fires under --dry-run as well.
  if ! id "${username}" &> /dev/null; then
    log_error "user ${username} does not exist; --remediate is not for creation"
    return 1
  fi

  # The scratch path is derived from the users.conf full name; without an entry
  # we would have to guess it. Refuse rather than guess.
  if [[ -z "$(user_fullname "${username}")" ]]; then
    log_error "user ${username} is not listed in ${USERS_CONF}; cannot resolve"
    log_error "their scratch directory name. Add the entry first."
    return 1
  fi

  local drifts
  drifts="$(check_user_drifts "${username}")"
  if [[ -z "${drifts}" ]]; then
    log_info "No drift detected for ${username}; nothing to remediate"
    return 0
  fi

  if [[ "${DRY_RUN}" == true ]]; then
    render_remediation_plan "${username}" "${drifts}"
    return 0
  fi

  local home_dir owner_group scratch
  home_dir="$(getent passwd "${username}" | cut -d: -f6)"
  owner_group="$(resolve_ownership "${username}")"
  scratch="$(user_scratch_dir "${username}")"

  # Primary group
  if grep -q '^primary_group ' <<< "${drifts}"; then
    if getent group "${PROVISION_PRIMARY_GROUP}" > /dev/null 2>&1; then
      log_info "usermod -g ${PROVISION_PRIMARY_GROUP} ${username}"
      usermod -g "${PROVISION_PRIMARY_GROUP}" "${username}" || log_error "usermod -g failed"
    else
      log_warning "Primary group '${PROVISION_PRIMARY_GROUP}' missing on host; skipping"
    fi
  fi

  # Scratch dir missing
  if grep -q '^scratch_missing' <<< "${drifts}"; then
    log_info "mkdir -p ${scratch}; chown ${owner_group}; chmod 755"
    mkdir -p "${scratch}"
    chown "${owner_group}" "${scratch}" || log_error "scratch chown failed"
    chmod 755 "${scratch}"
  fi

  # Scratch top-level owner (preserve-safe: top level only unless adopt opt-in)
  if grep -q '^scratch_owner ' <<< "${drifts}"; then
    log_info "chown ${owner_group} ${scratch}    # top-level only (preserve-safe)"
    chown "${owner_group}" "${scratch}" || log_error "scratch chown failed"

    local -a prestaged=()
    mapfile -t prestaged < <(list_prestaged_paths "${scratch}" "${username}")
    if [[ ${#prestaged[@]} -gt 0 ]]; then
      if [[ "${PROVISION_ADOPT_PRESTAGED}" == "yes" ]]; then
        log_warning "Adopting ${#prestaged[@]} pre-staged path(s) into ${username}"
        chown -R "${owner_group}" "${scratch}"
      else
        log_warning "Preserving ${#prestaged[@]} pre-staged path(s) (set PROVISION_ADOPT_PRESTAGED=yes to adopt):"
        printf '  [PRESERVED] %s\n' "${prestaged[@]}"
      fi
    fi
  fi

  # Supplementary groups — missing names are a comma-separated payload
  if grep -q '^supp_groups ' <<< "${drifts}"; then
    local missing_line missing g
    missing_line="$(grep '^supp_groups ' <<< "${drifts}")"
    missing="${missing_line#supp_groups }"
    for g in ${missing//,/ }; do
      if getent group "${g}" > /dev/null 2>&1; then
        log_info "usermod -aG ${g} ${username}"
        usermod -aG "${g}" "${username}" || log_error "usermod -aG ${g} failed"
      else
        log_warning "Supplementary group '${g}' missing on host; skipping"
      fi
    done
  fi

  # ~/.ssh permissions
  if grep -q '^ssh_dir_mode ' <<< "${drifts}"; then
    log_info "chmod 700 ${home_dir}/.ssh"
    mkdir -p "${home_dir}/.ssh"
    chmod 700 "${home_dir}/.ssh"
    chown "${owner_group}" "${home_dir}/.ssh"
  fi

  if grep -q '^auth_keys_mode ' <<< "${drifts}"; then
    log_info "chmod 600 ${home_dir}/.ssh/authorized_keys"
    mkdir -p "${home_dir}/.ssh"
    touch "${home_dir}/.ssh/authorized_keys"
    chmod 600 "${home_dir}/.ssh/authorized_keys"
    chown "${owner_group}" "${home_dir}/.ssh/authorized_keys"
  fi

  # ~/.aws skeleton + permissions (never clobbers an existing credentials file)
  if grep -qE '^aws_(dir|creds)_mode ' <<< "${drifts}"; then
    log_info "install_aws_skeleton ${username}"
    install_aws_skeleton "${username}"
    chmod 600 "${home_dir}/.aws/credentials" 2>/dev/null || true
    chmod 600 "${home_dir}/.aws/config" 2>/dev/null || true
  fi

  # git access to the shared checkout. A missing file is written whole; a
  # present-but-incomplete file is appended to, never rewritten.
  if grep -q '^missing_gitconfig' <<< "${drifts}"; then
    log_info "write_gitconfig ${username}"
    write_gitconfig "${username}" "$(user_fullname "${username}")" "$(user_email "${username}")"
  elif grep -q '^stale_git_safe_dirs ' <<< "${drifts}"; then
    log_info "adding missing git safe.directory entries for ${username}"
    add_missing_safe_dirs "${username}"
  fi

  # ~/.kiro assets
  if grep -qE '^missing_kiro_(mcp|steering)' <<< "${drifts}"; then
    log_info "install_kiro_assets ${username}"
    install_kiro_assets "${username}"
  fi

  # Stale AWS_PROFILE in mcp.json — --force-gated because a template redeploy
  # drops any user customisations in the file.
  if grep -q '^stale_kiro_profile ' <<< "${drifts}"; then
    local mcp_json="${home_dir}/.kiro/settings/mcp.json"
    if [[ "${FORCE}" == "true" ]]; then
      local backup
      backup="${mcp_json}.bak.$(date -u +%Y%m%dT%H%M%SZ)"
      log_warning "Redeploying mcp.json from template (backup: ${backup##*/})"
      cp -p "${mcp_json}" "${backup}"
      cp "${TEMPLATES_DIR}/mcp.json" "${mcp_json}"
      chown "${owner_group}" "${mcp_json}" "${backup}"
    else
      log_warning "mcp.json AWS_PROFILE differs from '${PROVISION_AWS_PROFILE}';"
      log_warning "  re-run with --force to redeploy from the template (drops user edits)."
    fi
  fi

  # Placeholder credentials — the user's action, not the operator's.
  if grep -q '^aws_creds_placeholder' <<< "${drifts}"; then
    log_warning "${username} has not pasted an IAM access key into ~/.aws/credentials;"
    log_warning "  point them at SETUP_AWS/provisioning/${CREDS_RUNBOOK} (no operator fix)."
  fi

  log_info "Post-remediation integrity for ${username}:"
  check_user_integrity "${username}"

  log_success "Remediation complete for ${username}"
}

################################################################################
# Dispatch
################################################################################

if [[ "${STATUS_ONLY}" == true ]]; then
  # --status honours an explicit user list from --user or --remediate (they are
  # mutually exclusive, so at most one is populated); with neither, it reports
  # every user in users.conf.
  STATUS_USERS=()
  if [[ ${#TARGET_USERS[@]} -gt 0 ]]; then
    STATUS_USERS=("${TARGET_USERS[@]}")
  elif [[ ${#REMEDIATE_USERS[@]} -gt 0 ]]; then
    STATUS_USERS=("${REMEDIATE_USERS[@]}")
  fi
  print_status ${STATUS_USERS[@]+"${STATUS_USERS[@]}"}
  exit 0
fi

if [[ ${#REMEDIATE_USERS[@]} -gt 0 ]]; then
  echo "============================================================"
  echo " User Drift Remediation"
  echo " Config: ${USERS_CONF}"
  echo " Dry run: ${DRY_RUN}   Adopt pre-staged: ${PROVISION_ADOPT_PRESTAGED}"
  echo "============================================================"
  remediate_failures=0
  for username in "${REMEDIATE_USERS[@]}"; do
    remediate_user "${username}" || remediate_failures=$((remediate_failures + 1))
  done
  echo ""
  if [[ "${remediate_failures}" -eq 0 ]]; then
    log_success "Remediation step complete"
    exit 0
  fi
  log_error "Remediation completed with ${remediate_failures} failure(s)"
  exit 1
fi

echo "============================================================"
echo " User Account Provisioning"
echo " Config: ${USERS_CONF}"
echo " Force overwrite: ${FORCE}"
echo " Dry run: ${DRY_RUN}"
echo "============================================================"
echo ""

if [[ "${DRY_RUN}" != true ]]; then
  # Create shared group
  if ! getent group "${SHARED_GROUP}" &> /dev/null; then
    groupadd "${SHARED_GROUP}"
    echo "[OK] Created group '${SHARED_GROUP}'"
  else
    echo "[OK] Group '${SHARED_GROUP}' exists"
  fi

  # Ensure workspace is group-accessible
  chgrp -R "${SHARED_GROUP}" "${WORKSPACE}" 2>/dev/null || true
  chmod -R g+rX "${WORKSPACE}" 2>/dev/null || true
fi

# Process each user
while IFS=: read -r username fullname email; do
  # Skip comments and empty lines
  [[ -z "$username" || "$username" == \#* ]] && continue

  # --user filter: provision only the named users when the flag is present.
  if [[ ${#TARGET_USERS[@]} -gt 0 ]] && ! in_list "${username}" "${TARGET_USERS[@]}"; then
    continue
  fi

  # --dry-run gate: render the plan and short-circuit before any mutation.
  if [[ "${DRY_RUN}" == true ]]; then
    render_provisioning_plan "${username}" "${fullname}"
    continue
  fi

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

  # 3. Set up ~/.kiro directory (mcp.json, steering, skills)
  install_kiro_assets "${username}"

  # 4. Set up git identity + safe.directory for the shared checkout
  GIT_CONFIG="${HOME_DIR}/.gitconfig"
  if [[ ! -f "${GIT_CONFIG}" ]] || [[ "${FORCE}" == "true" ]]; then
    write_gitconfig "${username}" "${fullname}" "${email}"
    echo "  [OK] Git config installed ($(shared_git_repos | wc -l) safe.directory entries)"
  else
    # Never rewrite an existing file (it may carry the developer's own aliases);
    # append only the entries that are missing.
    add_missing_safe_dirs "${username}"
  fi

  # 5. Set up .bashrc (PATH, env vars, aliases, prompt)
  BASHRC="${HOME_DIR}/.bashrc"
  if [[ ! -f "${BASHRC}" ]] || [[ "${FORCE}" == "true" ]]; then
    cp "${TEMPLATES_DIR}/bashrc" "${BASHRC}"
    # Derive CamelCase scratch dir name from full name (First.Last)
    SCRATCH_NAME="$(scratch_name_for "${fullname}")"
    echo "export SCRATCH=${SCRATCH_ROOT}/${SCRATCH_NAME}" >> "${BASHRC}"
    echo "  [OK] .bashrc installed"
  else
    echo "  [SKIP] .bashrc exists (use --force to overwrite)"
  fi

  # 6. Set up AWS CLI credentials directory
  install_aws_skeleton "${username}"

  # 7. Create scratch workspace (CamelCase: First.Last)
  SCRATCH_DIR="${SCRATCH_ROOT}/$(scratch_name_for "${fullname}")"
  mkdir -p "${SCRATCH_DIR}"
  chown "${username}:${username}" "${SCRATCH_DIR}"
  echo "  [OK] scratch: ${SCRATCH_DIR}"

  # 8. Set ownership
  chown -R "${username}:${username}" "${HOME_DIR}"

  echo ""
done < "${USERS_CONF}"

if [[ "${DRY_RUN}" == true ]]; then
  echo "============================================================"
  echo " Dry run complete — nothing was written to the host"
  echo "============================================================"
  exit 0
fi

echo "============================================================"
echo " Provisioning complete"
echo " Users can connect via SSH: ssh <username>@<host>"
echo " Shared workspace: ${WORKSPACE} (group: ${SHARED_GROUP})"
echo "============================================================"
