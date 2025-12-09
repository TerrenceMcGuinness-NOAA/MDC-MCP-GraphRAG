#!/bin/bash
################################################################################
# 04-nodejs.sh - Node.js installation and configuration
# Part of modular provisioning system v4.0.0
################################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

require_root

log_subsection "Node.js Installation"

USER_NAME=$(get_actual_user)
NODE_VERSION="20"

# Check if Node.js is already installed with correct version
if command_exists node; then
    CURRENT_VERSION=$(node --version | cut -d'v' -f2 | cut -d'.' -f1)
    if [[ "${CURRENT_VERSION}" -ge "${NODE_VERSION}" ]]; then
        log_info "Node.js already installed: $(node --version)"
    else
        log_warning "Node.js version too old: $(node --version), need v${NODE_VERSION}+"
    fi
fi

# Install Node.js via dnf module
log_info "Setting up Node.js ${NODE_VERSION} module..."

# Reset any existing Node.js module
dnf module reset -y nodejs 2>/dev/null || true

# Enable Node.js 20 module
dnf module enable -y nodejs:${NODE_VERSION} || {
    log_warning "Module enable failed, trying direct install..."
}

# Install Node.js
dnf install -y nodejs npm || {
    log_error "Failed to install Node.js"
    exit 1
}

# Verify installation
if command_exists node; then
    log_success "Node.js: $(node --version)"
else
    log_error "Node.js installation failed"
    exit 1
fi

if command_exists npm; then
    log_success "npm: $(npm --version)"
else
    log_error "npm installation failed"
    exit 1
fi

# Configure npm for user
log_subsection "Configuring npm"

# Set npm cache directory
NPM_CACHE="${CACHE_ROOT}/npm"
log_info "Setting npm cache: ${NPM_CACHE}"
npm config set cache "${NPM_CACHE}" --global

# Set npm prefix for global packages (user-local)
NPM_PREFIX="/home/${USER_NAME}/.npm-global"
run_as_user "mkdir -p ${NPM_PREFIX}"
run_as_user "npm config set prefix ${NPM_PREFIX}"

log_info "npm global prefix: ${NPM_PREFIX}"

# Install common global packages
log_subsection "Installing Global npm Packages"

GLOBAL_PACKAGES=(
    typescript
    ts-node
    @anthropic-ai/sdk
    @anthropic-ai/claude-code
)

for pkg in "${GLOBAL_PACKAGES[@]}"; do
    if npm list -g "${pkg}" &>/dev/null; then
        log_info "Already installed: ${pkg}"
    else
        log_info "Installing: ${pkg}..."
        npm install -g "${pkg}" --cache "${NPM_CACHE}" || log_warning "Failed to install ${pkg}"
    fi
done

log_success "Node.js setup complete"

exit 0
