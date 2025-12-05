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
export MCP_ROOT="${PERSISTENT_ROOT}/mcp_server_node"
export CACHE_ROOT="${PERSISTENT_ROOT}/cache"
export DATA_ROOT="${PERSISTENT_ROOT}/data"
export ETC_ROOT="${PERSISTENT_ROOT}/etc"
export SETUP_DIR="${PERSISTENT_ROOT}/eib-mcp-rag-server/SETUP"
export GIT_REPO="${PERSISTENT_ROOT}/eib-mcp-rag-server"

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
    echo "${SUDO_USER:-${USER:-$(whoami)}}"
}

# Run command as actual user (not root)
run_as_user() {
    local user=$(get_actual_user)
    su - "${user}" -c "$*"
}

# Create directory with proper ownership
create_dir_as_user() {
    local dir="$1"
    local user=$(get_actual_user)
    
    mkdir -p "${dir}"
    chown -R "${user}:${user}" "${dir}"
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
export -f get_actual_user run_as_user create_dir_as_user
export -f load_spack_env load_modules
export -f run_subscript print_summary_report

log_info "Common library loaded (v${PROVISION_VERSION})"
