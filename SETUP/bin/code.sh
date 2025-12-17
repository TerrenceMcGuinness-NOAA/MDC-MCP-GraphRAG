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
################################################################################

# Get the first name from the current username (e.g., Anna.Smoot -> Anna)
get_first_name() {
    local username="$USER"
    echo "${username%%.*}"
}

# Download and extract VS Code if not already present
# Note: Update the URL to the latest stable version as needed
if [[ ! -e "${PWD}/code-stable-x64-1765353460.tar.gz" ]]; then
  wget https://vscode.download.prss.microsoft.com/dbazure/download/stable/618725e67565b290ba4da6fe2d29f8fa1d4e3622/code-stable-x64-1765353460.tar.gz
  tar -xvf code-stable-x64-1765353460.tar.gz
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
echo "=========================================="
echo ""
echo "Starting tunnel in background..."

# Start VS Code tunnel in background
nohup VSCode-linux-x64/bin/code  tunnel --name "${server_name}" --accept-server-license-terms > "${OUTPUT_FILE}" 2>&1 &

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
