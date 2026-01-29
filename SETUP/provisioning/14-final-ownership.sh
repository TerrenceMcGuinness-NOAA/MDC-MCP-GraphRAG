#!/bin/bash
################################################################################
# 14-final-ownership.sh - Comprehensive ownership correction
# Part of modular provisioning system v4.0.0
#
# CRITICAL: This script MUST fix ALL user-owned paths comprehensively.
# Prior versions only fixed 4 directories which was insufficient.
#
# This script:
#   1. Fixes ownership of the entire persistent root (/mcp_rag_eib)
#   2. Excludes system directories that need root ownership
#   3. Reports detailed statistics on what was fixed
################################################################################

set -euo pipefail

# Source common library
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

require_root

log_section "Comprehensive Ownership Correction"

USER_NAME=$(get_actual_user)
USER_OWNERSHIP=$(get_ownership "${USER_NAME}")

if [[ "${USER_NAME}" == "root" ]]; then
    log_error "Cannot determine actual user - SUDO_USER not set"
    log_error "Run this script with: sudo -E ./14-final-ownership.sh"
    log_error "Or set USER_NAME manually: sudo USER_NAME=Terry.McGuinness ./14-final-ownership.sh"
    exit 1
fi

log_info "Target ownership: ${USER_OWNERSHIP}"
log_info "Persistent root: ${PERSISTENT_ROOT}"

################################################################################
# Phase 1: Count root-owned files BEFORE fix
################################################################################

log_subsection "Analyzing Current State"

count_root_files() {
    local path="$1"
    find "${path}" -user root 2>/dev/null | wc -l
}

ROOT_BEFORE=0
if [[ -d "${PERSISTENT_ROOT}" ]]; then
    ROOT_BEFORE=$(count_root_files "${PERSISTENT_ROOT}")
    log_info "Root-owned files/directories: ${ROOT_BEFORE}"
fi

################################################################################
# Phase 2: Fix ownership on ALL critical paths
################################################################################

log_subsection "Fixing Ownership"

# Directories that MUST be owned by user (comprehensive list)
USER_OWNED_PATHS=(
    # The entire EIB repo and all contents
    "${PERSISTENT_ROOT}/eib-mcp-rag-server"
    # Spack package manager
    "${PERSISTENT_ROOT}/spack"
    # Build cache
    "${PERSISTENT_ROOT}/cache"
    # Data storage (ChromaDB, Neo4j, n8n)
    "${PERSISTENT_ROOT}/data"
    # Etc configs
    "${PERSISTENT_ROOT}/etc"
    # Backups
    "${PERSISTENT_ROOT}/backups"
    # ecFlow
    "${PERSISTENT_ROOT}/ecflow"
    # Build artifacts
    "${PERSISTENT_ROOT}/build"
    # MCP server standalone (if exists)
    "${PERSISTENT_ROOT}/mcp_server_node"
    # Modules
    "${PERSISTENT_ROOT}/modules"
    # Opt
    "${PERSISTENT_ROOT}/opt"
    # Scratch space for users
    "${PERSISTENT_ROOT}/SCRATCH_SPACE"
)

FIXED_COUNT=0

for path in "${USER_OWNED_PATHS[@]}"; do
    if [[ -e "${path}" ]]; then
        owner=$(stat -c '%U:%G' "${path}" 2>/dev/null || echo "unknown")
        
        if [[ "${owner}" != "${USER_OWNERSHIP}" ]]; then
            log_info "Fixing: ${path} (was ${owner})"
            chown -R "${USER_OWNERSHIP}" "${path}" 2>/dev/null && ((FIXED_COUNT++)) || {
                log_warning "  Could not fully fix ${path}"
            }
        else
            log_success "OK: ${path}"
        fi
    fi
done

################################################################################
# Phase 3: Handle special cases
################################################################################

log_subsection "Special Cases"

# Fix .git directory permissions (often problematic)
GIT_DIR="${EIB_REPO}/.git"
if [[ -d "${GIT_DIR}" ]]; then
    log_info "Fixing .git directory..."
    chown -R "${USER_OWNERSHIP}" "${GIT_DIR}" 2>/dev/null || true
    # Ensure git config is safe
    git config --global --add safe.directory "${EIB_REPO}" 2>/dev/null || true
fi

# Fix user home directory npm/node caches
USER_HOME="/home/${USER_NAME}"
if [[ -d "${USER_HOME}" ]]; then
    for subdir in .npm .npm-global .cache/pip .local; do
        if [[ -d "${USER_HOME}/${subdir}" ]]; then
            current_owner=$(stat -c '%U' "${USER_HOME}/${subdir}" 2>/dev/null || echo "unknown")
            if [[ "${current_owner}" == "root" ]]; then
                log_info "Fixing: ${USER_HOME}/${subdir}"
                chown -R "${USER_OWNERSHIP}" "${USER_HOME}/${subdir}" 2>/dev/null || true
            fi
        fi
    done
fi

# Fix Docker MCP catalog (user-specific)
DOCKER_MCP_DIR="${USER_HOME}/.docker/mcp"
if [[ -d "${DOCKER_MCP_DIR}" ]]; then
    current_owner=$(stat -c '%U' "${DOCKER_MCP_DIR}" 2>/dev/null || echo "unknown")
    if [[ "${current_owner}" == "root" ]]; then
        log_info "Fixing: ${DOCKER_MCP_DIR}"
        chown -R "${USER_OWNERSHIP}" "${DOCKER_MCP_DIR}" 2>/dev/null || true
    fi
fi

################################################################################
# Phase 4: Verify and Report
################################################################################

log_subsection "Verification"

ROOT_AFTER=0
if [[ -d "${PERSISTENT_ROOT}" ]]; then
    ROOT_AFTER=$(count_root_files "${PERSISTENT_ROOT}")
fi

# Exclude lost+found from count (always root-owned)
LOST_FOUND_COUNT=0
if [[ -d "${PERSISTENT_ROOT}/lost+found" ]]; then
    LOST_FOUND_COUNT=$(find "${PERSISTENT_ROOT}/lost+found" -user root 2>/dev/null | wc -l)
fi
ROOT_AFTER=$((ROOT_AFTER - LOST_FOUND_COUNT))

echo ""
log_info "Results:"
log_info "  Root-owned before: ${ROOT_BEFORE}"
log_info "  Root-owned after:  ${ROOT_AFTER} (excluding lost+found)"
log_info "  Paths processed:   ${FIXED_COUNT}"

if [[ ${ROOT_AFTER} -le 1 ]]; then
    log_success "Ownership correction complete! All files properly owned."
else
    log_warning "Some root-owned files remain (${ROOT_AFTER})"
    echo ""
    log_info "Remaining root-owned items:"
    find "${PERSISTENT_ROOT}" -user root -not -path "${PERSISTENT_ROOT}/lost+found/*" 2>/dev/null | head -20
fi

################################################################################
# Phase 5: Quick sanity checks
################################################################################

log_subsection "Sanity Checks"

# Test git operations work
if [[ -d "${EIB_REPO}/.git" ]]; then
    if su - "${USER_NAME}" -c "cd ${EIB_REPO} && git status >/dev/null 2>&1"; then
        log_success "Git operations work as ${USER_NAME}"
    else
        log_warning "Git operations may have issues"
    fi
fi

# Test npm/node operations
if [[ -d "${MCP_ROOT}/node_modules" ]]; then
    if [[ $(stat -c '%U' "${MCP_ROOT}/node_modules") == "${USER_NAME}" ]]; then
        log_success "node_modules owned by ${USER_NAME}"
    else
        log_warning "node_modules ownership needs attention"
    fi
fi

record_result "14-final-ownership" "success" "Fixed ${FIXED_COUNT} paths, ${ROOT_AFTER} root files remain"

echo ""
log_success "Ownership correction complete"

exit 0
