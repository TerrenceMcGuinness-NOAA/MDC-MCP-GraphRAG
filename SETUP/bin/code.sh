 #!/bin/bash
set -e
################################################################################
# VS Code Tunnel Startup Script
# 
# Purpose: Start VS Code tunnel with user-specific default name
# Usage: code.sh [rndtag]
#
# If no rndtag provided, generates a random 6-character alphanumeric string
# Example: For user Anna.Smoot, server name is pw_Anna_<rndtag>
#
# VS Code CLI Downloads (auto-updates to latest stable):
#   https://code.visualstudio.com/#alt-downloads
#   Direct link: https://code.visualstudio.com/sha/download?build=stable&os=cli-alpine-x64
################################################################################

# Get the first name from the current username (e.g., Anna.Smoot -> Anna)
get_first_name() {
    local username="$USER"
    echo "${username%%.*}"
}

# Find existing code CLI executable
find_code_cli() {
    # Check if 'code' is in PATH and supports tunnel command
    if command -v code &>/dev/null; then
        if code tunnel --help &>/dev/null 2>&1; then
            echo "code"
            return 0
        fi
    fi
    
    # Check ~/bin/code
    if [[ -x "${HOME}/bin/code" ]]; then
        echo "${HOME}/bin/code"
        return 0
    fi
    
    # Check local ./code CLI binary
    if [[ -x "${PWD}/code" ]]; then
        echo "${PWD}/code"
        return 0
    fi
    
    return 1
}

# Download VS Code CLI if not found
download_code_cli() {
    local install_dir="${1:-${PWD}}"
    
    echo "[INFO] Downloading VS Code CLI..." >&2
    
    # Official stable CLI download URL (auto-redirects to latest version)
    # Alpine build is statically linked and works on all Linux distros
    # For manual updates, check: https://code.visualstudio.com/#alt-downloads
    local download_url="https://code.visualstudio.com/sha/download?build=stable&os=cli-alpine-x64"
    local tarball="vscode_cli.tar.gz"
    
    curl -Lk "${download_url}" --output "${install_dir}/${tarball}"
    tar -xf "${install_dir}/${tarball}" -C "${install_dir}"
    rm -f "${install_dir}/${tarball}"
    
    # The CLI extracts as just 'code' binary
    if [[ -x "${install_dir}/code" ]]; then
        echo "[OK] VS Code CLI installed to ${install_dir}/code" >&2
        echo "${install_dir}/code"
        return 0
    fi
    
    echo "[ERROR] Failed to install VS Code CLI" >&2
    return 1
}

# Main: Find or download code CLI
CODE_CLI=""
if CODE_CLI=$(find_code_cli); then
    echo "[OK] Found existing VS Code CLI: ${CODE_CLI}" >&2
else
    echo "[INFO] VS Code CLI not found in PATH, ~/bin, or current directory" >&2
    CODE_CLI=$(download_code_cli "${PWD}")
fi

# Verify we have a working CLI
if [[ -z "${CODE_CLI}" ]] || [[ ! -x "${CODE_CLI}" ]]; then
    echo "[ERROR] Could not find or install VS Code CLI" >&2
    exit 1
fi


# Default server name: pw_<FirstName>_<rndtag>
FIRST_NAME=$(get_first_name)
rndtag=${1:-$(head /dev/urandom | tr -dc a-z0-9 | head -c 6)}
DEFAULT_SERVER_NAME="pw_${FIRST_NAME}_${rndtag}"

# Use generated server name
server_name="$DEFAULT_SERVER_NAME"

# Output file location
OUTPUT_FILE="${HOME}/${server_name}.out"

# Remove old output file
rm -f "${OUTPUT_FILE}"

echo "=========================================="
echo "  Starting VS Code Tunnel"
echo "=========================================="
echo "Server Name: ${server_name}"
echo "Output File: ${OUTPUT_FILE}"
echo "User: ${USER}"
echo "Code CLI: ${CODE_CLI}"
echo "=========================================="
echo ""
echo "Starting tunnel in background..."

# Start VS Code tunnel in background
nohup "${CODE_CLI}" tunnel --name "${server_name}" --accept-server-license-terms > "${OUTPUT_FILE}" 2>&1 &

TUNNEL_PID=$!

echo "Tunnel started with PID: ${TUNNEL_PID}"
echo ""
echo "To check status:"
echo "  cat ${OUTPUT_FILE}"
echo ""
echo "To stop tunnel:"
echo "  pkill -f 'code tunnel'"
echo ""
echo "To view tunnel URL:"
echo "  sleep 5 && tail -20 ${OUTPUT_FILE}"
echo ""
