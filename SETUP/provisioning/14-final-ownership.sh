#!/bin/bash
################################################################################
# 14-final-ownership.sh - Ownership verification and targeted fixes
# Part of modular provisioning system v4.0.0
#
# This script verifies ownership is correct and only fixes specific issues
# if found. The root causes have been fixed so files should be created with
# correct ownership from the start.
################################################################################

set -euo pipefail

# Source common library
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

require_root

log_subsection "Ownership Verification"

USER_NAME=$(get_actual_user)
USER_OWNERSHIP=$(get_ownership "${USER_NAME}")

# Directories that should be owned by user (not root)
CRITICAL_DIRS=(
    "${PERSISTENT_ROOT}/eib-mcp-rag-server"
    "${PERSISTENT_ROOT}/spack"
    "${PERSISTENT_ROOT}/cache"
    "${MCP_ROOT}"
)

log_info "Checking ownership of critical directories..."
echo ""

ISSUES_FOUND=0

for dir in "${CRITICAL_DIRS[@]}"; do
    if [[ -d "${dir}" ]]; then
        owner=$(stat -c '%U:%G' "${dir}" 2>/dev/null || echo "unknown")
        
        if [[ "${owner}" == "${USER_OWNERSHIP}" ]]; then
            log_success "✓ ${dir}: ${owner}"
        else
            log_warning "✗ ${dir}: ${owner} (expected ${USER_OWNERSHIP})"
            ((ISSUES_FOUND++))
            
            # Fix only this specific directory
            log_info "  Fixing ownership on ${dir}..."
            chown -R "${USER_OWNERSHIP}" "${dir}" 2>/dev/null || true
        fi
    else
        log_info "  ${dir}: does not exist (skipping)"
    fi
done

echo ""

if [[ ${ISSUES_FOUND} -eq 0 ]]; then
    log_success "All ownership checks passed! No root-owned files found."
    log_info "The provisioning scripts are creating files with correct ownership."
else
    log_warning "Fixed ${ISSUES_FOUND} ownership issue(s)"
    log_info "Note: If issues persist, check which provisioning script is creating root-owned files"
fi

exit 0
