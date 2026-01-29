#!/bin/bash
################################################################################
# 15-github-copilot-cli.sh - GitHub Copilot CLI installation
# Part of modular provisioning system v4.0.0
#
# Installs GitHub Copilot CLI for terminal-based AI-assisted development.
# The CLI provides agentic coding capabilities directly in the terminal.
#
# References:
#   - https://github.com/github/copilot-cli
#   - https://docs.github.com/copilot/concepts/agents/about-copilot-cli
################################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

log_subsection "GitHub Copilot CLI Installation"

USER_NAME=$(get_actual_user)
USER_HOME=$(eval echo ~"${USER_NAME}")

# Copilot CLI install location
COPILOT_BIN="${USER_HOME}/.local/bin/copilot"
COPILOT_INSTALL_URL="https://gh.io/copilot-install"

################################################################################
# Check if already installed
################################################################################

if [[ -x "${COPILOT_BIN}" ]]; then
    CURRENT_VERSION=$("${COPILOT_BIN}" --version 2>/dev/null | head -1 || echo "unknown")
    log_info "GitHub Copilot CLI already installed: v${CURRENT_VERSION}"
    
    # Optionally update to latest
    log_info "Checking for updates..."
fi

################################################################################
# Install GitHub Copilot CLI
################################################################################

log_info "Installing GitHub Copilot CLI for user ${USER_NAME}..."

# Ensure .local/bin exists
run_as_user "${USER_NAME}" "mkdir -p ${USER_HOME}/.local/bin"

# Install using official script (as the target user, not root)
# The script installs to ~/.local/bin by default for non-root users
log_info "Downloading and installing from ${COPILOT_INSTALL_URL}..."

run_as_user "${USER_NAME}" "curl -fsSL ${COPILOT_INSTALL_URL} | bash" || {
    log_error "GitHub Copilot CLI installation failed"
    exit 1
}

################################################################################
# Verify Installation
################################################################################

if [[ -x "${COPILOT_BIN}" ]]; then
    INSTALLED_VERSION=$("${COPILOT_BIN}" --version 2>/dev/null | head -1 || echo "unknown")
    log_success "GitHub Copilot CLI installed: v${INSTALLED_VERSION}"
else
    log_error "GitHub Copilot CLI binary not found at ${COPILOT_BIN}"
    exit 1
fi

################################################################################
# Ensure PATH includes ~/.local/bin
################################################################################

BASHRC="${USER_HOME}/.bashrc"
PATH_LINE='export PATH="${HOME}/.local/bin:${PATH}"'

if ! grep -q '\.local/bin' "${BASHRC}" 2>/dev/null; then
    log_info "Adding ~/.local/bin to PATH in .bashrc..."
    echo "" >> "${BASHRC}"
    echo "# GitHub Copilot CLI and local binaries" >> "${BASHRC}"
    echo "${PATH_LINE}" >> "${BASHRC}"
    chown "${USER_NAME}:${USER_NAME}" "${BASHRC}"
    log_success "PATH updated in .bashrc"
else
    log_info "~/.local/bin already in PATH"
fi

################################################################################
# Print usage instructions
################################################################################

log_info ""
log_info "GitHub Copilot CLI Installation Complete!"
log_info ""
log_info "Usage:"
log_info "  copilot                    # Start interactive session"
log_info "  copilot --help             # Show help"
log_info "  copilot --version          # Show version"
log_info ""
log_info "First-time setup:"
log_info "  1. Run 'copilot' to start"
log_info "  2. Type '/login' to authenticate with GitHub"
log_info "  3. Follow browser prompts to complete authentication"
log_info ""
log_info "Or authenticate with PAT:"
log_info "  export GH_TOKEN=your_token  # or GITHUB_TOKEN"
log_info ""

log_success "15-github-copilot-cli.sh completed"
