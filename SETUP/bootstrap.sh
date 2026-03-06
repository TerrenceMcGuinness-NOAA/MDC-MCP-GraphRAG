#!/bin/bash
################################################################################
# Bootstrap Script for MCP RAG Persistent Infrastructure
# Version: 2.0.0
# Location: /mcp_rag_eib/eib-mcp-rag-server/SETUP/bootstrap.sh
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
echo "EIB_REPO:        ${EIB_REPO}"
echo "MCP_ROOT:        ${MCP_ROOT}"
echo "GW_REPO:         ${GW_REPO}"
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

# ── OpenSSL version lock ──────────────────────────────────────────────────────
# KasmVNC 1.4.0 (used by Parallel Works desktop) has three compounding defects
# triggered by OpenSSL >= 3.5.x: CA:TRUE cert rejection, WebUDP null-pointer
# segfault, and JS client defaulting WebRTC to enabled.
# OpenSSL 3.2.2 (the Rocky 9.6 base image version) works perfectly.
# We downgrade to 3.2.2 from the Rocky 9.6 vault repo and versionlock it so
# neither our dnf update nor PW's own dnf update can ever re-upgrade it.
# See: supported_repos/global-workflow.wiki/KasmVNC-SSL-Certificate-Failure-on-EL9-OpenSSL-3.md
# ──────────────────────────────────────────────────────────────────────────────

OPENSSL_SAFE_VERSION="3.2.2-6.el9_5.1"
VAULT_BASEOS="https://dl.rockylinux.org/vault/rocky/9.6/BaseOS/x86_64/os/"
VAULT_APPSTREAM="https://dl.rockylinux.org/vault/rocky/9.6/AppStream/x86_64/os/"

current_ssl=$(rpm -q openssl-libs --qf '%{VERSION}-%{RELEASE}' 2>/dev/null || echo "unknown")
echo "Current OpenSSL: ${current_ssl}"
echo "Target OpenSSL:  ${OPENSSL_SAFE_VERSION}"

if [[ "${current_ssl}" == "${OPENSSL_SAFE_VERSION}" ]]; then
    echo "[OK] OpenSSL already at safe version ${OPENSSL_SAFE_VERSION}"
else
    echo "Downgrading OpenSSL from ${current_ssl} to ${OPENSSL_SAFE_VERSION}..."

    # Remove openssl-fips-provider first — it has an exact version pin on 3.5.x
    sudo rpm -e --nodeps openssl-fips-provider 2>/dev/null || true

    # Downgrade openssl, openssl-libs, openssl-devel from the Rocky 9.6 vault
    sudo dnf downgrade -y \
        --repofrompath=vault96baseos,"${VAULT_BASEOS}" \
        --repofrompath=vault96appstream,"${VAULT_APPSTREAM}" \
        --repo=vault96baseos --repo=vault96appstream \
        "openssl-1:${OPENSSL_SAFE_VERSION}" \
        "openssl-libs-1:${OPENSSL_SAFE_VERSION}" \
        "openssl-devel-1:${OPENSSL_SAFE_VERSION}" \
    || echo "[WARN] OpenSSL downgrade had issues — may already be at target version"

    echo "[OK] OpenSSL downgraded to ${OPENSSL_SAFE_VERSION}"
fi

# Apply versionlock so no future dnf update (ours or PW's) can upgrade OpenSSL
if ! sudo dnf versionlock list 2>/dev/null | grep -q "openssl"; then
    echo "Applying dnf versionlock on openssl packages..."
    sudo dnf versionlock add openssl openssl-libs openssl-devel 2>/dev/null || true
    echo "[OK] OpenSSL versionlocked"
else
    echo "[OK] OpenSSL versionlock already in place"
fi

# Update system (except kernel)
echo "Current kernel version:"
uname -a
echo "Updating system packages (excluding kernel)..."
sudo dnf -y update --nobest --exclude='kernel*'

# The fix-kasmvnc-openssl3.sh script is still run as a safety net — it's
# idempotent and handles cert regeneration + WebRTC/STUN config regardless
# of OpenSSL version. With 3.2.x these are mostly no-ops.
if command -v vncserver &>/dev/null; then
    echo "Running KasmVNC compatibility check..."
    sudo "${SETUP}/scripts/fix-kasmvnc-openssl3.sh" || true
fi

# Install Code
sudo rpm --import https://packages.microsoft.com/keys/microsoft.asc
sudo sh -c 'echo -e "[code]\nname=Visual Studio Code\nbaseurl=https://packages.microsoft.com/yumrepos/vscode\nenabled=1\ngpgcheck=1\ngpgkey=https://packages.microsoft.com/keys/microsoft.asc" > /etc/yum.repos.d/vscode.repo'
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

# Run modular provisioning scripts
echo "=========================================="
echo "Running MCP Server Provisioning..."
echo "=========================================="
sudo "${SETUP}/provisioning/provision.sh"
