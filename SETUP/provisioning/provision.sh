#!/bin/bash
################################################################################
# provision.sh - Master MCP RAG Provisioning Orchestrator
# Version: 4.2.0
#
# This script orchestrates all provisioning subscripts and provides a unified
# summary report at the end, continuing even if individual scripts fail.
#
# Usage:
#   sudo ./provision.sh              # Run all scripts
#   sudo ./provision.sh --skip 09    # Skip script 09 (VNC/desktop)
#   sudo ./provision.sh --only 06    # Only run script 06 (ChromaDB)
#   sudo ./provision.sh --list       # List available scripts
#   sudo ./provision.sh --fresh      # Clean start (wipe caches)
#
################################################################################

set -uo pipefail  # Note: removed -e to continue on errors

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source common library
source "${SCRIPT_DIR}/common.sh"

################################################################################
# Script Configuration
################################################################################

# Ordered list of provisioning scripts
declare -a SCRIPTS=(
    "00-users.sh:User Accounts"
    "01-directories.sh:Directory Structure"
    "02-system-deps.sh:System Dependencies"
    "03-docker.sh:Docker Installation"
    "04-nodejs.sh:Node.js Environment"
    "05-python-spack.sh:Python & Spack"
    "06-chromadb.sh:ChromaDB Database"
    "07-mcp-server.sh:MCP Server Setup"
    "08-services.sh:Docker Compose Services"
    "09-desktop-vnc.sh:Desktop VNC (TigerVNC + MATE for PW noVNC)"
    "10-verification.sh:Final Verification"
    "11-docker-mcp-gateway.sh:Docker MCP Gateway"
    "12-static-mode-gateway.sh:Phase 23 Static Mode (DEPRECATED Phase 63c — no-op unless MCP_ALLOW_STATIC_MODE_ROLLBACK=1)"
    "13-container-cleanup.sh:Smart Container Cleanup Timer"
    "14-final-ownership.sh:Final Ownership Correction"
    "15-github-copilot-cli.sh:GitHub Copilot CLI"
)

################################################################################
# Command Line Parsing
################################################################################

SKIP_SCRIPTS=()
ONLY_SCRIPTS=()
FRESH_START=false
LIST_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip)
            shift
            SKIP_SCRIPTS+=("$1")
            shift
            ;;
        --only)
            shift
            ONLY_SCRIPTS+=("$1")
            shift
            ;;
        --fresh)
            FRESH_START=true
            shift
            ;;
        --list)
            LIST_ONLY=true
            shift
            ;;
        --help|-h)
            echo "MCP RAG Provisioning Orchestrator v${PROVISION_VERSION}"
            echo ""
            echo "Usage: sudo $0 [options]"
            echo ""
            echo "Options:"
            echo "  --skip NN     Skip script with prefix NN (can use multiple times)"
            echo "  --only NN     Only run script with prefix NN (can use multiple times)"
            echo "  --fresh       Clean start - wipe caches before provisioning"
            echo "  --list        List available scripts and exit"
            echo "  --help        Show this help message"
            echo ""
            echo "Examples:"
            echo "  sudo $0                    # Run all scripts"
            echo "  sudo $0 --skip 09          # Skip VNC/desktop setup"
            echo "  sudo $0 --only 06 --only 07  # Only ChromaDB and MCP server"
            echo "  sudo $0 --fresh            # Clean start"
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

################################################################################
# List Scripts Mode
################################################################################

if [[ "${LIST_ONLY}" == true ]]; then
    echo ""
    echo "Available Provisioning Scripts:"
    echo "================================"
    for entry in "${SCRIPTS[@]}"; do
        script="${entry%%:*}"
        description="${entry#*:}"
        prefix="${script:0:2}"
        printf "  %s  %-25s  %s\n" "${prefix}" "${script}" "${description}"
    done
    echo ""
    exit 0
fi

################################################################################
# Pre-flight Checks
################################################################################

require_root

log_section "MCP RAG Provisioning System v${PROVISION_VERSION}"

echo ""
echo "Configuration:"
echo "  PERSISTENT_ROOT: ${PERSISTENT_ROOT}"
echo "  SETUP_DIR: ${SETUP_DIR}"
echo "  Fresh Start: ${FRESH_START}"

if [[ ${#SKIP_SCRIPTS[@]} -gt 0 ]]; then
    echo "  Skipping: ${SKIP_SCRIPTS[*]}"
fi

if [[ ${#ONLY_SCRIPTS[@]} -gt 0 ]]; then
    echo "  Only running: ${ONLY_SCRIPTS[*]}"
fi

echo ""

################################################################################
# Fresh Start Mode
################################################################################

if [[ "${FRESH_START}" == true ]]; then
    log_section "Fresh Start - Cleaning Previous Installation"
    
    log_warning "This will remove caches and reset services. Continue? (y/N)"
    read -r response
    if [[ "${response}" != "y" && "${response}" != "Y" ]]; then
        log_info "Aborted."
        exit 0
    fi
    
    # Stop services
    log_info "Stopping services..."
    systemctl stop chromadb-persistent.service 2>/dev/null || true
    systemctl stop mcp-server-persistent.service 2>/dev/null || true
    docker compose -f "${SETUP_DIR}/docker-compose.yml" down 2>/dev/null || true
    
    # Clean caches
    log_info "Cleaning caches..."
    rm -rf "${CACHE_ROOT}/npm" 2>/dev/null || true
    rm -rf "${CACHE_ROOT}/pip" 2>/dev/null || true
    rm -rf "${MCP_ROOT}/node_modules" 2>/dev/null || true
    
    log_success "Clean-up complete"
fi

################################################################################
# Initialize Status Tracking
################################################################################

clear_status_file

################################################################################
# Execute Scripts
################################################################################

log_section "Executing Provisioning Scripts"

FAILED_COUNT=0

for entry in "${SCRIPTS[@]}"; do
    script="${entry%%:*}"
    description="${entry#*:}"
    prefix="${script:0:2}"
    
    # Check if we should skip this script
    if [[ ${#SKIP_SCRIPTS[@]} -gt 0 ]]; then
        for skip in "${SKIP_SCRIPTS[@]}"; do
            if [[ "${prefix}" == "${skip}" ]]; then
                log_info "Skipping: ${script} (${description})"
                record_result "${script}" "skipped" "User requested skip"
                continue 2
            fi
        done
    fi
    
    # Check if we should only run specific scripts
    if [[ ${#ONLY_SCRIPTS[@]} -gt 0 ]]; then
        found=false
        for only in "${ONLY_SCRIPTS[@]}"; do
            if [[ "${prefix}" == "${only}" ]]; then
                found=true
                break
            fi
        done
        if [[ "${found}" == false ]]; then
            log_info "Skipping: ${script} (not in --only list)"
            record_result "${script}" "skipped" "Not in --only list"
            continue
        fi
    fi
    
    # Run the script
    if run_subscript "${script}" "${description}"; then
        : # Success - already logged
    else
        ((FAILED_COUNT++))
        log_warning "Continuing despite failure..."
    fi
    
    echo ""
done

################################################################################
# Summary Report
################################################################################

print_summary_report

################################################################################
# Final Status
################################################################################

echo ""
if [[ ${FAILED_COUNT} -eq 0 ]]; then
    log_section "Provisioning Complete! 🚀"
    echo ""
    echo "Next steps:"
    echo "  1. Log out and back in (for docker group membership)"
    echo "  2. Source environment: source ${SETUP_DIR}/mcp-env.sh"
    echo "  3. Verify services: ${SCRIPT_DIR}/10-verification.sh"
    echo ""
    exit 0
else
    log_section "Provisioning Completed with ${FAILED_COUNT} Failures"
    echo ""
    echo "Review the summary above and re-run failed scripts individually:"
    echo "  sudo ${SCRIPT_DIR}/<script-name>.sh"
    echo ""
    exit 1
fi
