#!/bin/bash
################################################################################
# common.sh - Shared functions and variables for MCP RAG provisioning
# Version: 4.0.0
# 
# This library provides:
#   - Color output functions
#   - Logging utilities
#   - Environment variable definitions
#   - Common helper functions
#
# Usage: source /path/to/provisioning/common.sh
################################################################################

# Prevent multiple sourcing
[[ -n "${_COMMON_SH_LOADED:-}" ]] && return 0
export _COMMON_SH_LOADED=1

################################################################################
# Color Definitions
################################################################################
export RED='\033[0;31m'
export GREEN='\033[0;32m'
export YELLOW='\033[1;33m'
export BLUE='\033[0;34m'
export CYAN='\033[0;36m'
export MAGENTA='\033[0;35m'
export NC='\033[0m' # No Color

################################################################################
# Environment Variables
################################################################################
export PERSISTENT_ROOT="${PERSISTENT_ROOT:-/mcp_rag_eib}"
export EIB_REPO="${PERSISTENT_ROOT}/eib-mcp-rag-server"
export GW_REPO="${EIB_REPO}/supported_repos/global-workflow_develop"
export MCP_ROOT="${EIB_REPO}/mcp_server_node"
export CACHE_ROOT="${PERSISTENT_ROOT}/cache"
export DATA_ROOT="${PERSISTENT_ROOT}/data"
export ETC_ROOT="${PERSISTENT_ROOT}/etc"
export SETUP_DIR="${EIB_REPO}/SETUP"

# ChromaDB Configuration
export CHROMADB_PORT="${CHROMADB_PORT:-8080}"
export CHROMADB_URL="http://127.0.0.1:${CHROMADB_PORT}"

# Neo4j Configuration
export NEO4J_HTTP_PORT="${NEO4J_HTTP_PORT:-7474}"
export NEO4J_BOLT_PORT="${NEO4J_BOLT_PORT:-7687}"
export NEO4J_PASSWORD="${NEO4J_PASSWORD:-gfsworkflow2025}"

# Version
export PROVISION_VERSION="4.0.0"

################################################################################
# Logging Functions
################################################################################

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_section() {
    echo ""
    echo -e "${CYAN}════════════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}════════════════════════════════════════════════════════════════${NC}"
}

log_subsection() {
    echo ""
    echo -e "${MAGENTA}── $1 ──${NC}"
}

################################################################################
# Script Result Tracking
################################################################################

# Associative array to track script results (bash 4+)
declare -gA SCRIPT_RESULTS

# Record script result
# Usage: record_result "script_name" "success|failure|skipped" "optional message"
record_result() {
    local script_name="$1"
    local status="$2"
    local message="${3:-}"
    
    SCRIPT_RESULTS["${script_name}"]="${status}:${message}"
    
    # Also write to a status file for cross-script communication
    local status_file="${SETUP_DIR}/provisioning/.provision_status"
    echo "${script_name}|${status}|${message}" >> "${status_file}"
}

# Clear status file (call at start of master script)
clear_status_file() {
    local status_file="${SETUP_DIR}/provisioning/.provision_status"
    : > "${status_file}"
}

# Read all results from status file
read_all_results() {
    local status_file="${SETUP_DIR}/provisioning/.provision_status"
    if [[ -f "${status_file}" ]]; then
        cat "${status_file}"
    fi
}

################################################################################
# Helper Functions
################################################################################

# Check if running as root
require_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root (use sudo)"
        exit 1
    fi
}

# Check if a command exists
command_exists() {
    command -v "$1" &> /dev/null
}

# Check if a service is running
service_running() {
    systemctl is-active --quiet "$1" 2>/dev/null
}

# Wait for a service to be ready (with timeout)
wait_for_service() {
    local url="$1"
    local timeout="${2:-60}"
    local interval="${3:-2}"
    
    local elapsed=0
    while [[ $elapsed -lt $timeout ]]; do
        if curl -sf "$url" > /dev/null 2>&1; then
            return 0
        fi
        sleep $interval
        elapsed=$((elapsed + interval))
    done
    return 1
}

# Get the actual user (not root when using sudo)
get_actual_user() {
    # 1. Allow explicit override via USER_NAME env var
    if [[ -n "${USER_NAME:-}" ]]; then
        echo "${USER_NAME}"
        return
    fi

    # 2. Try standard detections
    local user="${SUDO_USER:-${USER:-$(whoami)}}"
    
    # 3. If resolved to root, try to fallback to the configured primary user
    # This prevents accidental root ownership when running in automation/CI
    if [[ "${user}" == "root" ]]; then
        # Try to find user from config without sourcing (avoid side effects)
        local config_file="${SETUP_DIR}/provisioning/user_config.sh"
        if [[ -f "${config_file}" ]]; then
            # Extract first user from PROVISION_USERS array
            # matches: PROVISION_USERS=( "Terry.McGuinness"
            local default_user
            default_user=$(grep -m 1 -oP 'PROVISION_USERS=\(\s*"\K[^"]+' "${config_file}" || true)
            
            if [[ -n "${default_user}" ]]; then
                # Log to stderr so valid output (stdout) is preserved for assignment
                >&2 echo -e "${YELLOW}[WARN] Detected root user, falling back to default user: ${default_user}${NC}"
                echo "${default_user}"
                return
            fi
        fi
        
        # If no config/fallback found, warn but return root
        >&2 echo -e "${RED}[WARN] Running as root and could not determine actual user! Files will be owned by root.${NC}"
    fi

    echo "${user}"
}

# Get the primary group of a user (handles case where group name != username)
# Usage: get_user_group "username"
# Returns: primary group name (e.g., "pwuser" for Terry.McGuinness)
get_user_group() {
    local user="${1:-$(get_actual_user)}"
    # Get the primary GID, then resolve to group name
    local gid
    gid=$(id -g "${user}" 2>/dev/null)
    if [[ -n "${gid}" ]]; then
        # Try to get group name from GID
        local group_name
        group_name=$(getent group "${gid}" 2>/dev/null | cut -d: -f1)
        if [[ -n "${group_name}" ]]; then
            echo "${group_name}"
        else
            # Fallback: return GID if no group name exists
            echo "${gid}"
        fi
    else
        # Fallback: assume group matches username
        echo "${user}"
    fi
}

# Get user:group ownership string for chown commands
# Usage: get_ownership "username"
# Returns: "username:primary_group" (e.g., "Terry.McGuinness:pwuser")
get_ownership() {
    local user="${1:-$(get_actual_user)}"
    local group
    group=$(get_user_group "${user}")
    echo "${user}:${group}"
}

# Run command as actual user (not root)
# Usage: run_as_user "command"           - uses get_actual_user()
#        run_as_user "username" "command" - uses specified username
run_as_user() {
    local user
    local cmd
    if [[ $# -eq 1 ]]; then
        # Single argument: command only, use actual user
        user=$(get_actual_user)
        cmd="$1"
    else
        # Two arguments: username and command
        user="$1"
        cmd="$2"
    fi
    su - "${user}" -c "${cmd}"
}

# Create directory with proper ownership
create_dir_as_user() {
    local dir="$1"
    local user=$(get_actual_user)
    local ownership
    ownership=$(get_ownership "${user}")
    
    mkdir -p "${dir}"
    chown -R "${ownership}" "${dir}"
}

# Copy files/directories preserving ownership for target user
# This is the CORRECT way to copy files in provisioning scripts
# Usage: copy_as_user "source" "destination"
copy_as_user() {
    local src="$1"
    local dst="$2"
    local user=$(get_actual_user)
    local ownership
    ownership=$(get_ownership "${user}")
    
    # Copy as root (which has permissions), then fix ownership
    cp -r "${src}" "${dst}"
    chown -R "${ownership}" "${dst}"
}

# Ensure a path has correct user ownership
# Usage: ensure_user_ownership "/path/to/fix"
ensure_user_ownership() {
    local path="$1"
    local user=$(get_actual_user)
    local ownership
    ownership=$(get_ownership "${user}")
    
    if [[ -e "${path}" ]]; then
        current_owner=$(stat -c '%U:%G' "${path}" 2>/dev/null || echo "unknown")
        if [[ "${current_owner}" != "${ownership}" ]]; then
            chown -R "${ownership}" "${path}"
            return 0  # Fixed
        fi
    fi
    return 1  # No fix needed or path doesn't exist
}

# Source Spack environment if available
load_spack_env() {
    local spack_setup="${PERSISTENT_ROOT}/spack/share/spack/setup-env.sh"
    if [[ -f "${spack_setup}" ]]; then
        source "${spack_setup}"
        return 0
    fi
    return 1
}

# Load module system
load_modules() {
    if [[ -f /usr/share/lmod/lmod/init/bash ]]; then
        source /usr/share/lmod/lmod/init/bash
    elif [[ -f /etc/profile.d/modules.sh ]]; then
        source /etc/profile.d/modules.sh
    fi
    
    # Add Spack modules if available
    local spack_lmod="${PERSISTENT_ROOT}/spack/share/spack/lmod/linux-*-x86_64/Core"
    if ls ${spack_lmod} &>/dev/null 2>&1; then
        export MODULEPATH="${spack_lmod}:${MODULEPATH:-}"
    fi
}

################################################################################
# Provisioning Ownership & Password Helpers (spec: user-provisioning-ownership-hardening)
#
# These helpers collapse the four ownership-resolution schemes onto a single
# SPOT (R4), enumerate operator-pre-staged content that must not be re-owned
# (R3), and keep the initial password out of source (R5).
################################################################################

# Resolve user:group ownership honoring the PROVISION_PRIMARY_GROUP SPOT.
# Precedence (design.md § "common.sh additions"):
#   1. "${PROVISION_PRIMARY_GROUP}" iff that group exists on the host
#   2. get_user_group "<username>"  (current per-user primary group fallback)
# Usage:   resolve_ownership <username>
# Prints:  "username:group" on stdout
resolve_ownership() {
    local username="${1:-$(get_actual_user)}"
    local group="${PROVISION_PRIMARY_GROUP:-}"

    if [[ -n "${group}" ]] && getent group "${group}" > /dev/null 2>&1; then
        echo "${username}:${group}"
        return 0
    fi

    # Fallback: resolve via the target user's actual primary group.
    group="$(get_user_group "${username}")"
    echo "${username}:${group}"
}

# Enumerate direct children of <path> that are NOT owned by <owner>.
# Consumed by create_scratch_space (R3) to detect operator-pre-staged content
# so it is preserved instead of blindly chowned, and by render_provisioning_plan
# (R6) to include a "protected pre-staged paths" section in the dry-run plan.
# Usage:   list_prestaged_paths <path> <owner>
# Prints:  one absolute path per line on stdout, sorted; nothing when the path
#          is missing/empty or every entry is already owned by <owner>.
# Note:    When <owner> is not yet a resolvable user on the host (typical for a
#          first-time provisioning), every direct child is pre-staged by
#          definition — a not-yet-created UID cannot own anything.
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

# Resolve the initial password for a new user with R5 precedence:
#   (a) contents of "${PROVISION_INITIAL_PASSWORD_FILE}" (must be mode 0600),
#   (b) interactive `read -s` prompt when a TTY is attached to stdin,
#   (c) a randomly-generated 16-character password, echoed to stderr for the
#       operator to record (stdout is reserved for the caller's chpasswd pipe).
# The value is never persisted to the state file or the systemd journal.
# Usage:   resolve_initial_password <username>
# Prints:  the password on stdout; diagnostics and generator disclosure on stderr.
resolve_initial_password() {
    local username="$1"
    local pw_file="${PROVISION_INITIAL_PASSWORD_FILE:-}"
    local password=""

    # (a) File source
    if [[ -n "${pw_file}" ]]; then
        if [[ ! -f "${pw_file}" ]]; then
            log_error "PROVISION_INITIAL_PASSWORD_FILE=${pw_file} does not exist" >&2
            return 1
        fi
        local mode
        mode="$(stat -c '%a' "${pw_file}" 2>/dev/null || echo "")"
        if [[ "${mode}" != "600" ]]; then
            log_error "PROVISION_INITIAL_PASSWORD_FILE=${pw_file} must be mode 0600 (got ${mode:-unknown})" >&2
            return 1
        fi
        password="$(head -n 1 "${pw_file}")"
        if [[ -z "${password}" ]]; then
            log_error "PROVISION_INITIAL_PASSWORD_FILE=${pw_file} is empty" >&2
            return 1
        fi
        log_info "Using initial password for ${username} from ${pw_file}" >&2
        echo "${password}"
        return 0
    fi

    # (b) Interactive prompt (only when a real TTY is attached to BOTH stdin
    # and stderr — the second check excludes captured/piped contexts such as
    # VS Code's run_in_terminal tool, where stdin appears as a TTY but stderr
    # is redirected, previously causing `read -r -s` to accept stray buffer
    # bytes and silently set the password to an unknown value.)
    if [[ -t 0 && -t 2 ]]; then
        read -r -s -p "Initial password for ${username}: " password < /dev/tty
        echo "" >&2  # newline after the silent prompt
        if [[ -n "${password}" ]]; then
            log_info "Using operator-entered initial password for ${username}" >&2
            echo "${password}"
            return 0
        fi
        log_warning "Empty password entered; falling through to generator" >&2
    fi

    # (c) Generator: 16 characters drawn from an alphanumeric + symbol pool
    # broad enough to satisfy typical PAM policies.
    password="$(tr -dc 'A-Za-z0-9!@#%^_+=' </dev/urandom | head -c 16 || true)"
    if [[ -z "${password}" ]] || [[ "${#password}" -lt 16 ]]; then
        log_error "Failed to generate initial password for ${username}" >&2
        return 1
    fi
    log_warning "Generated initial password for ${username}: ${password}" >&2
    log_warning "  Record this value before the user's first login (chage -d 0 forces a change)." >&2
    echo "${password}"
}

################################################################################
# Script Execution Wrapper
################################################################################

# Run a provisioning subscript and track its result
# Usage: run_subscript "01-directories.sh" "Directory Setup"
run_subscript() {
    local script="$1"
    local description="$2"
    local script_path="${SETUP_DIR}/provisioning/${script}"
    
    log_section "${description}"
    
    if [[ ! -f "${script_path}" ]]; then
        log_error "Script not found: ${script_path}"
        record_result "${script}" "failure" "Script not found"
        return 1
    fi
    
    if [[ ! -x "${script_path}" ]]; then
        chmod +x "${script_path}"
    fi
    
    # Run the script and capture exit code
    local start_time=$(date +%s)
    
    if "${script_path}"; then
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        log_success "${description} completed in ${duration}s"
        record_result "${script}" "success" "${duration}s"
        return 0
    else
        local exit_code=$?
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        log_error "${description} failed (exit code: ${exit_code})"
        record_result "${script}" "failure" "Exit code ${exit_code}"
        return ${exit_code}
    fi
}

################################################################################
# Summary Report
################################################################################

print_summary_report() {
    local status_file="${SETUP_DIR}/provisioning/.provision_status"
    
    echo ""
    log_section "Provisioning Summary Report"
    echo ""
    
    local total=0
    local success=0
    local failed=0
    local skipped=0
    
    printf "%-35s %-12s %s\n" "Script" "Status" "Details"
    printf "%-35s %-12s %s\n" "-----------------------------------" "------------" "--------"
    
    while IFS='|' read -r script status message; do
        [[ -z "$script" ]] && continue
        ((total++))
        
        case "$status" in
            success)
                ((success++))
                printf "%-35s ${GREEN}%-12s${NC} %s\n" "$script" "SUCCESS" "$message"
                ;;
            failure)
                ((failed++))
                printf "%-35s ${RED}%-12s${NC} %s\n" "$script" "FAILED" "$message"
                ;;
            skipped)
                ((skipped++))
                printf "%-35s ${YELLOW}%-12s${NC} %s\n" "$script" "SKIPPED" "$message"
                ;;
        esac
    done < "${status_file}"
    
    echo ""
    echo -e "Total: ${total} | ${GREEN}Success: ${success}${NC} | ${RED}Failed: ${failed}${NC} | ${YELLOW}Skipped: ${skipped}${NC}"
    echo ""
    
    if [[ $failed -gt 0 ]]; then
        log_warning "Some scripts failed. Review the output above for details."
        return 1
    else
        log_success "All provisioning scripts completed successfully!"
        return 0
    fi
}

################################################################################
# Initialization
################################################################################

# Export all functions
export -f log_info log_success log_warning log_error log_section log_subsection
export -f record_result clear_status_file read_all_results
export -f require_root command_exists service_running wait_for_service
export -f get_actual_user get_user_group get_ownership run_as_user create_dir_as_user
export -f copy_as_user ensure_user_ownership
export -f resolve_ownership list_prestaged_paths resolve_initial_password
export -f load_spack_env load_modules
export -f run_subscript print_summary_report

log_info "Common library loaded (v${PROVISION_VERSION})"
