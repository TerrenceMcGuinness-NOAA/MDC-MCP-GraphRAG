#!/bin/bash
################################################################################
# VS Code Tunnel Startup Script 
# 
# Purpose: Start VS Code tunnel with user-specific default name
# Usage: code.sh [server_name_suffix]
#
# Server name format: pw_<FirstName>_[<hostname>_]<suffix>
# Hostname included only if <= 10 characters
# If no suffix provided, generates a random 6-character alphanumeric string
#
# Environment Variables:
#   VSCODE_SERVER_DIR - Directory for VS Code server files (default: $HOME)
#                       Set this if $HOME has limited storage
#                       Example: export VSCODE_SERVER_DIR=/scratch/$USER/vscode
#
# Prerequisites: VS Code with tunnel support (code --version >= 1.80)
#   - System install: /usr/bin/code (preferred)
#   - Or standalone CLI: https://code.visualstudio.com/sha/download?build=stable&os=cli-alpine-x64
################################################################################
set -e
export VSCODE_SERVER_DIR=$PWD
# VS Code server directory - use env var or default to HOME
VSCODE_DIR="${VSCODE_SERVER_DIR:-${HOME}}"

# Set VS Code's native environment variables for alternate storage
if [[ "${VSCODE_DIR}" != "${HOME}" ]]; then
    mkdir -p "${VSCODE_DIR}"
    export VSCODE_CLI_DATA_DIR="${VSCODE_DIR}/.vscode-cli"
    export VSCODE_SERVER_DIR="${VSCODE_DIR}/.vscode-server"
    echo "[INFO] VS Code server files: ${VSCODE_DIR}"
fi

# Get the first name from username (e.g., Anna.Smoot -> Anna)
FIRST_NAME="${USER%%.*}"

# Get short hostname (first part before any dots) - only use if <= 10 chars
SHORT_HOST="${HOSTNAME%%.*}"
if [[ ${#SHORT_HOST} -gt 10 ]]; then
    SHORT_HOST=""
fi

# Generate server name: pw_<FirstName>_[<hostname>_]<suffix>
SUFFIX="${1:-$(head /dev/urandom | tr -dc a-z0-9 | head -c 6)}"
if [[ -n "${SHORT_HOST}" ]]; then
    SERVER_NAME="pw_${FIRST_NAME}_${SHORT_HOST}_${SUFFIX}"
else
    SERVER_NAME="pw_${FIRST_NAME}_${SUFFIX}"
fi

# Output file for tunnel logs (use VSCODE_DIR to keep logs with server files)
OUTPUT_FILE="${VSCODE_DIR}/${SERVER_NAME}.out"

# Find VS Code CLI - prefer system install, fallback to local
find_code() {
    # System VS Code with tunnel support (installed via RPM/DEB)
    if command -v code &>/dev/null && code tunnel --help &>/dev/null 2>&1; then
        command -v code
        return 0
    fi
    # Local standalone CLI
    for path in "${HOME}/bin/code" "${PWD}/code"; do
        [[ -x "$path" ]] && echo "$path" && return 0
    done
    return 1
}

# Find or fail
CODE_CLI=$(find_code) || {
    echo "[ERROR] VS Code CLI not found. Install via:" >&2
    echo "  sudo dnf install code  # RHEL/Rocky" >&2
    echo "  # Or download standalone CLI:" >&2
    echo "  curl -Lk 'https://code.visualstudio.com/sha/download?build=stable&os=cli-alpine-x64' | tar xz -C ~/bin" >&2
    exit 1
}

# Check for existing running tunnel
TUNNEL_STATUS=$("${CODE_CLI}" tunnel status 2>/dev/null) || true
if echo "${TUNNEL_STATUS}" | grep -qi "connected\|running\|started_at"; then
    # Parse JSON status for clean output
    TUNNEL_STATE=$(echo "${TUNNEL_STATUS}" | grep -oP '"tunnel"\s*:\s*"\K[^"]+' || echo "unknown")
    STARTED_AT=$(echo "${TUNNEL_STATUS}" | grep -oP '"started_at"\s*:\s*"\K[^"]+' | cut -d'T' -f1,2 | tr 'T' ' ' | cut -d'.' -f1 || echo "unknown")
    TUNNEL_NAME=$(echo "${TUNNEL_STATUS}" | grep -oP '"name"\s*:\s*"\K[^"]+' || echo "none")
    
    echo "[INFO] Tunnel process detected"
    echo "  Status:  ${TUNNEL_STATE}"
    echo "  Name:    ${TUNNEL_NAME}"
    echo "  Started: ${STARTED_AT}"
    echo ""
    echo "To stop:   code tunnel kill"
    echo "To restart: code tunnel kill && $0"
    exit 0
fi

# Clean up old output
rm -f "${OUTPUT_FILE}"

# Display startup info
cat <<EOF
==========================================
  VS Code Tunnel
==========================================
Server Name: ${SERVER_NAME}
VS Code CLI: ${CODE_CLI}
Output File: ${OUTPUT_FILE}
EOF

if [[ "${VSCODE_DIR}" != "${HOME}" ]]; then
    echo "Server Dir:  ${VSCODE_DIR}"
fi

echo "------------------------------------------"

# Start tunnel in background
nohup "${CODE_CLI}" tunnel --name "${SERVER_NAME}" --accept-server-license-terms > "${OUTPUT_FILE}" 2>&1 &
TUNNEL_PID=$!

cat <<EOF
Tunnel started with PID: ${TUNNEL_PID}

Commands:
  cat ${OUTPUT_FILE}              # View logs
  code tunnel status              # Check status
  code tunnel kill                # Stop tunnel
EOF
