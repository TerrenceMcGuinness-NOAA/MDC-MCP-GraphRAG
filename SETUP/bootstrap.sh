#!/bin/bash
################################################################################
# Bootstrap Script for MCP RAG Persistent Infrastructure
# Version: 2.0.0
# Location: /mcp_rag_eib/SETUP/bootstrap.sh
################################################################################

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source centralized environment configuration
source "${SCRIPT_DIR}/mcp-env.sh" --quiet

echo "=========================================="
echo "MCP RAG Bootstrap Environment"
echo "=========================================="
echo "SETUP:           ${SETUP}"
echo "PERSISTENT_ROOT: ${PERSISTENT_ROOT}"
echo "MCP_ROOT:        ${MCP_ROOT}"
echo "GIT_REPO:        ${GIT_REPO}"
echo "=========================================="

# Copy shell configuration files
echo "Configuring shell environment..."
cp "${SETUP}/bashrc_template" ~/.bashrc
cp "${SETUP}/bash_profile_template" ~/.bash_profile
echo "✅ Shell configuration files installed"

# Copy user utilities
cp -R "${SETUP}/bin" $HOME
cp "${SETUP}/gvimrc" $HOME/.gvimrc 2>/dev/null || true

# Setup Claude CLI directories (no symlink)
mkdir -p ~/.claude/debug
echo "✅ Claude CLI directories created"

# Setup GitHub CLI authentication
if [ -f "${SETUP}/gh.txt" ]; then
    ~/bin/gh auth login --with-token < "${SETUP}/gh.txt"
fi

# Install Code
sudo rpm --import https://packages.microsoft.com/keys/microsoft.asc
sudo sh -c 'echo -e "[code]\nname=Visual Studio Code\nbaseurl=https://packages.microsoft.com/yumrepos/vscode\nenabled=1\ngpgcheck=1\ngpgkey=https://packages.microsoft.com/keys/microsoft.asc" > /etc/yum.repos.d/vscode.repo'
sudo dnf check-update
yes | sudo dnf install code
yes | sudo dnf install code-insiders

# Add multiple SSH keys without duplicates
if [ -f "${SETUP}/ssh/pubkeys.pub" ]; then
    while IFS= read -r key; do
        # Skip empty lines and comments
        [[ -z "$key" || "$key" =~ ^[[:space:]]*# ]] && continue
        # Add if not already present
        grep -qxF "$key" ~/.ssh/authorized_keys 2>/dev/null || echo "$key" >> ~/.ssh/authorized_keys
    done < "${SETUP}/ssh/pubkeys.pub"
fi

# Install Spack if not present (for package management)
if [ ! -d "${PERSISTENT_ROOT}/spack" ]; then
    echo "=========================================="
    echo "Installing Spack Package Manager..."
    echo "=========================================="
    git clone -c feature.manyFiles=true --depth=2 https://github.com/spack/spack.git "${PERSISTENT_ROOT}/spack"
    echo "✅ Spack installed to ${PERSISTENT_ROOT}/spack"
else
    echo "✅ Spack already installed"
fi

# Run MCP server provisioning script
echo "=========================================="
echo "Running MCP Server Provisioning..."
echo "=========================================="
sudo "${SETUP}/provision_mcp_rag_persistent.sh"
