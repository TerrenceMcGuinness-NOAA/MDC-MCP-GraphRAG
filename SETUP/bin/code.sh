 #!/bin/bash
################################################################################
# VS Code Tunnel Startup Script
# 
# Purpose: Start VS Code tunnel with user-specific default name
# Usage: code.sh [server_name]
#
# If no server_name provided, uses pw_<FirstName> as default
# Example: For user Anna.Smoot, default is pw_Anna
################################################################################

# Get the first name from the current username (e.g., Anna.Smoot -> Anna)
get_first_name() {
    local username="$USER"
    echo "${username%%.*}"
}

# Default server name: pw_<FirstName>
FIRST_NAME=$(get_first_name)
DEFAULT_SERVER_NAME="pw_${FIRST_NAME}"

# Use provided server name or default
server_name=${1:-"$DEFAULT_SERVER_NAME"}

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
nohup code tunnel --name "${server_name}" --accept-server-license-terms > "${OUTPUT_FILE}" 2>&1 &

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

exit 0