#!/bin/bash
################################################################################
# fix-ownership.sh - Quick ownership fix for /mcp_rag_eib
#
# Run with: sudo ./fix-ownership.sh [username]
#
# If username not provided, uses SUDO_USER or prompts
################################################################################

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Must be root
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root (use sudo)"
    exit 1
fi

# Determine target user
TARGET_USER="${1:-${SUDO_USER:-}}"

if [[ -z "${TARGET_USER}" ]]; then
    log_error "Cannot determine target user"
    echo "Usage: sudo $0 <username>"
    echo "   or: sudo -E $0"
    exit 1
fi

# Get user's primary group
TARGET_GROUP=$(id -gn "${TARGET_USER}" 2>/dev/null || echo "${TARGET_USER}")
OWNERSHIP="${TARGET_USER}:${TARGET_GROUP}"

echo ""
echo "=============================================="
echo "  Ownership Fix Script"
echo "=============================================="
echo ""
log_info "Target user: ${TARGET_USER}"
log_info "Target group: ${TARGET_GROUP}"
log_info "Ownership: ${OWNERSHIP}"
echo ""

PERSISTENT_ROOT="/mcp_rag_eib"

if [[ ! -d "${PERSISTENT_ROOT}" ]]; then
    log_error "Directory not found: ${PERSISTENT_ROOT}"
    exit 1
fi

# Count before
ROOT_BEFORE=$(find "${PERSISTENT_ROOT}" -user root 2>/dev/null | wc -l)
log_info "Root-owned items before: ${ROOT_BEFORE}"

# Directories to fix
PATHS=(
    "${PERSISTENT_ROOT}/eib-mcp-rag-server"
    "${PERSISTENT_ROOT}/spack"
    "${PERSISTENT_ROOT}/cache"
    "${PERSISTENT_ROOT}/data"
    "${PERSISTENT_ROOT}/etc"
    "${PERSISTENT_ROOT}/backups"
    "${PERSISTENT_ROOT}/ecflow"
    "${PERSISTENT_ROOT}/build"
    "${PERSISTENT_ROOT}/mcp_server_node"
    "${PERSISTENT_ROOT}/modules"
    "${PERSISTENT_ROOT}/opt"
    "${PERSISTENT_ROOT}/SCRATCH_SPACE"
)

echo ""
log_info "Fixing ownership..."

for path in "${PATHS[@]}"; do
    if [[ -e "${path}" ]]; then
        echo -n "  ${path}... "
        if chown -R "${OWNERSHIP}" "${path}" 2>/dev/null; then
            echo -e "${GREEN}done${NC}"
        else
            echo -e "${YELLOW}partial${NC}"
        fi
    fi
done

# Fix user home directory caches
USER_HOME="/home/${TARGET_USER}"
if [[ -d "${USER_HOME}" ]]; then
    echo ""
    log_info "Fixing user home caches..."
    for subdir in .npm .npm-global .cache .local .docker .copilot; do
        if [[ -d "${USER_HOME}/${subdir}" ]]; then
            echo -n "  ${USER_HOME}/${subdir}... "
            if chown -R "${OWNERSHIP}" "${USER_HOME}/${subdir}" 2>/dev/null; then
                echo -e "${GREEN}done${NC}"
            else
                echo -e "${YELLOW}partial${NC}"
            fi
        fi
    done
fi

# Mark git directory as safe
if [[ -d "${PERSISTENT_ROOT}/eib-mcp-rag-server/.git" ]]; then
    git config --global --add safe.directory "${PERSISTENT_ROOT}/eib-mcp-rag-server" 2>/dev/null || true
fi

# Count after (excluding lost+found)
ROOT_AFTER=$(find "${PERSISTENT_ROOT}" -user root -not -path "${PERSISTENT_ROOT}/lost+found/*" 2>/dev/null | wc -l)

echo ""
echo "=============================================="
log_info "Root-owned items after: ${ROOT_AFTER}"
FIXED=$((ROOT_BEFORE - ROOT_AFTER))
log_success "Fixed approximately ${FIXED} items"
echo "=============================================="

# Verify key paths
echo ""
log_info "Verification:"
for path in "${PERSISTENT_ROOT}/eib-mcp-rag-server" "${PERSISTENT_ROOT}/data" "/home/${TARGET_USER}"; do
    if [[ -d "${path}" ]]; then
        owner=$(stat -c '%U:%G' "${path}" 2>/dev/null || echo "unknown")
        if [[ "${owner}" == "${OWNERSHIP}" ]]; then
            log_success "  ${path}: ${owner}"
        else
            log_warning "  ${path}: ${owner} (expected ${OWNERSHIP})"
        fi
    fi
done

echo ""
log_success "Ownership fix complete!"
echo ""
