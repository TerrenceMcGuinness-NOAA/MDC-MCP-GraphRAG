#!/bin/bash
################################################################################
# 02-system-deps.sh - Install system dependencies
# Part of modular provisioning system v4.0.0
################################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

require_root

log_subsection "Installing System Dependencies"

# Enable EPEL repository
if ! dnf repolist | grep -q epel; then
    log_info "Enabling EPEL repository..."
    dnf install -y epel-release
fi

# Core development tools
log_info "Installing development tools..."
dnf groupinstall -y "Development Tools" || log_warning "Some dev tools may have failed"

# Essential packages
PACKAGES=(
    # Build tools
    git
    wget
    curl
    jq
    unzip
    tar
    
    # Development libraries
    openssl-devel
    bzip2-devel
    libffi-devel
    zlib-devel
    readline-devel
    sqlite-devel
    
    # Python build dependencies
    python3-devel
    python3-pip
    
    # Module system
    lmod
    
    # Utilities
    htop
    tmux
    neofetch
    tree
    nc
    
    # X11 (for VNC)
    xorg-x11-xauth
    xorg-x11-fonts-Type1
    xorg-x11-fonts-misc
    mesa-libGL
    
    # Network tools
    net-tools
    bind-utils
)

# GitHub CLI requires separate repo setup on RHEL/Rocky
log_subsection "Installing GitHub CLI (gh)"
if command -v gh &>/dev/null; then
    log_info "GitHub CLI already installed: $(gh --version | head -1)"
else
    log_info "Adding GitHub CLI repository..."
    dnf install -y 'dnf-command(config-manager)' &>/dev/null || true
    dnf config-manager --add-repo https://cli.github.com/packages/rpm/gh-cli.repo &>/dev/null || true
    if dnf install -y gh &>/dev/null; then
        log_success "GitHub CLI installed: $(gh --version | head -1)"
    else
        log_warning "Failed to install GitHub CLI - manual install may be required"
    fi
fi

log_info "Installing essential packages..."
for pkg in "${PACKAGES[@]}"; do
    if rpm -q "${pkg}" &>/dev/null; then
        log_info "  Already installed: ${pkg}"
    else
        if dnf install -y "${pkg}" &>/dev/null; then
            log_success "  Installed: ${pkg}"
        else
            log_warning "  Failed to install: ${pkg}"
        fi
    fi
done

# Verify critical tools
log_subsection "Verifying Critical Tools"

CRITICAL_TOOLS=(git curl wget jq)
for tool in "${CRITICAL_TOOLS[@]}"; do
    if command_exists "${tool}"; then
        log_success "${tool}: $(${tool} --version 2>&1 | head -1)"
    else
        log_error "${tool} not found!"
        exit 1
    fi
done

log_success "System dependencies installed"

exit 0
