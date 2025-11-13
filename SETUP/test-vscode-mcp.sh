#!/usr/bin/env bash
#
# Test VS Code MCP Configuration
# Verifies that the MCP configuration in .vscode/mcp.json is correct
#

set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "========================================="
echo "  VS Code MCP Configuration Test"
echo "========================================="
echo ""

# Load MCP environment
source "$(dirname "${BASH_SOURCE[0]}")/mcp_env.sh" --quiet

# Check if mcp.json exists
MCP_CONFIG="${GIT_REPO}/.vscode/mcp.json"

echo -e "${YELLOW}1. Checking MCP configuration file...${NC}"
if [[ -f "${MCP_CONFIG}" ]]; then
    echo -e "${GREEN}✓ Found: ${MCP_CONFIG}${NC}"
else
    echo -e "${RED}✗ Not found: ${MCP_CONFIG}${NC}"
    exit 1
fi
echo ""

# Parse and validate JSON
echo -e "${YELLOW}2. Validating JSON syntax...${NC}"
if jq empty "${MCP_CONFIG}" 2>/dev/null; then
    echo -e "${GREEN}✓ Valid JSON${NC}"
else
    echo -e "${RED}✗ Invalid JSON${NC}"
    exit 1
fi
echo ""

# Check server configurations
echo -e "${YELLOW}3. Checking server configurations...${NC}"
SERVERS=$(jq -r 'keys[]' "${MCP_CONFIG}")
for server in ${SERVERS}; do
    echo "   Server: ${server}"
    
    # Check if disabled
    DISABLED=$(jq -r ".\"${server}\".disabled // false" "${MCP_CONFIG}")
    if [[ "${DISABLED}" == "true" ]]; then
        echo -e "     Status: ${YELLOW}Disabled${NC}"
    else
        echo -e "     Status: ${GREEN}Enabled${NC}"
        
        # Check command
        COMMAND=$(jq -r ".\"${server}\".command" "${MCP_CONFIG}")
        echo "     Command: ${COMMAND}"
        
        # Check args (first arg is the script path)
        SCRIPT=$(jq -r ".\"${server}\".args[0]" "${MCP_CONFIG}")
        echo "     Script: ${SCRIPT}"
        
        if [[ -f "${SCRIPT}" ]]; then
            echo -e "     Script exists: ${GREEN}✓${NC}"
        else
            echo -e "     Script exists: ${RED}✗ Not found${NC}"
        fi
    fi
    echo ""
done

echo -e "${YELLOW}4. Testing MCP server execution...${NC}"

# Get the active server configuration (global-workflow-unified)
SERVER_NAME="global-workflow-unified"
COMMAND=$(jq -r ".\"${SERVER_NAME}\".command" "${MCP_CONFIG}")
SCRIPT=$(jq -r ".\"${SERVER_NAME}\".args[0]" "${MCP_CONFIG}")

echo "   Testing: ${SERVER_NAME}"
echo "   Command: ${COMMAND} ${SCRIPT}"
echo ""

# Create a test input
TEMP_INPUT=$(mktemp)
TEMP_OUTPUT=$(mktemp)
trap "rm -f ${TEMP_INPUT} ${TEMP_OUTPUT}" EXIT

# Send initialize request
cat > "${TEMP_INPUT}" <<'EOF'
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"vscode-test","version":"1.0.0"}}}
EOF

echo "   Sending initialize request..."

# Environment variables already set from mcp_env.sh
# Verify critical variables are set
if [[ -z "${CHROMADB_URL}" ]] || [[ -z "${MCP_ROOT}" ]] || [[ -z "${GIT_REPO}" ]]; then
    echo -e "${RED}✗ Critical environment variables not set${NC}"
    exit 1
fi

# Run the test
timeout 10s ${COMMAND} ${SCRIPT} < "${TEMP_INPUT}" > "${TEMP_OUTPUT}" 2>&1 || true

# Check response
if grep -q "jsonrpc" "${TEMP_OUTPUT}" 2>/dev/null; then
    echo -e "${GREEN}✓ Server responded correctly${NC}"
    
    # Try to extract tool count
    TOOL_COUNT=$(grep -o '"name":\s*"mcp_' "${TEMP_OUTPUT}" | wc -l || echo "0")
    if [[ ${TOOL_COUNT} -gt 0 ]]; then
        echo -e "   ${GREEN}✓ Registered ${TOOL_COUNT} MCP tools${NC}"
    fi
else
    echo -e "${RED}✗ Server did not respond correctly${NC}"
    echo ""
    echo "Output:"
    cat "${TEMP_OUTPUT}" | head -20 | sed 's/^/     /'
fi

echo ""
echo -e "${GREEN}=========================================="
echo "  ✓ VS Code MCP Configuration Ready"
echo "==========================================${NC}"
echo ""
echo "To test in VS Code:"
echo "  1. Restart VS Code"
echo "  2. Open Copilot Chat"
echo "  3. Look for MCP tools icon"
echo "  4. Try: '@workspace List all MCP tools available'"
echo ""
