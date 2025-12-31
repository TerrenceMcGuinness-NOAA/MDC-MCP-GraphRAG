#!/usr/bin/env bash
#
# Test MCP Server Startup
# Tests that the MCP server can initialize and respond to basic requests
#

set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "=========================================="
echo "  MCP Server Startup Test"
echo "=========================================="
echo ""

# Load environment
echo -e "${YELLOW}1. Loading environment...${NC}"
source "$(dirname "${BASH_SOURCE[0]}")/mcp_env.sh"
echo ""

# Check ChromaDB
echo -e "${YELLOW}2. Checking ChromaDB connection...${NC}"
if curl -s "${CHROMADB_URL}/api/v1/heartbeat" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ ChromaDB is running at ${CHROMADB_URL}${NC}"
else
    echo -e "${RED}✗ ChromaDB is not responding at ${CHROMADB_URL}${NC}"
    exit 1
fi
echo ""

# Check Node.js
echo -e "${YELLOW}3. Checking Node.js...${NC}"
cd "${MCP_ROOT}"
NODE_VERSION=$(node --version)
echo -e "${GREEN}✓ Node.js ${NODE_VERSION}${NC}"
echo ""

# Check if UnifiedMCPServer.js exists
echo -e "${YELLOW}4. Checking MCP server file...${NC}"
if [[ -f "${MCP_ROOT}/src/UnifiedMCPServer.js" ]]; then
    echo -e "${GREEN}✓ UnifiedMCPServer.js found${NC}"
else
    echo -e "${RED}✗ UnifiedMCPServer.js not found at ${MCP_ROOT}/src/UnifiedMCPServer.js${NC}"
    exit 1
fi
echo ""

# Check environment variables
echo -e "${YELLOW}5. Checking environment variables...${NC}"
echo "   CHROMADB_URL: ${CHROMADB_URL}"
echo "   MCP_ROOT: ${MCP_ROOT}"
echo "   EIB_REPO: ${EIB_REPO}"
echo "   GW_REPO: ${GW_REPO}"
echo "   MCP_WORKFLOW_ROOT: ${MCP_WORKFLOW_ROOT}"
echo "   MCP_KNOWLEDGE_BASE: ${MCP_KNOWLEDGE_BASE}"
echo "   MCP_DATABASE: ${MCP_DATABASE}"

if [[ -n "${GH_TOKEN:-}" ]]; then
    echo -e "   GH_TOKEN: ${GREEN}✓ Set${NC}"
else
    echo -e "   GH_TOKEN: ${YELLOW}⚠ Not set (GitHub tools will be limited)${NC}"
fi
echo ""

# Test MCP server initialization (send initialize request)
echo -e "${YELLOW}6. Testing MCP server initialization...${NC}"
echo "   Starting server in background..."

# Create a temporary file for communication
TEMP_INPUT=$(mktemp)
TEMP_OUTPUT=$(mktemp)

# Cleanup on exit
trap "rm -f ${TEMP_INPUT} ${TEMP_OUTPUT}" EXIT

# Send an initialize request to the MCP server
cat > "${TEMP_INPUT}" <<'EOF'
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test-client","version":"1.0.0"}}}
EOF

echo "   Sending initialize request..."

# Start the server and send the request (with timeout)
timeout 10s node "${MCP_ROOT}/src/UnifiedMCPServer.js" < "${TEMP_INPUT}" > "${TEMP_OUTPUT}" 2>&1 || true

# Check if we got a response
if grep -q "jsonrpc" "${TEMP_OUTPUT}" 2>/dev/null; then
    echo -e "${GREEN}✓ MCP server responded to initialize request${NC}"
    echo ""
    echo "   Response preview:"
    head -n 5 "${TEMP_OUTPUT}" | sed 's/^/     /'
    echo ""
    echo -e "${GREEN}=========================================="
    echo "  ✓ MCP Server Test PASSED"
    echo "==========================================${NC}"
else
    echo -e "${RED}✗ MCP server did not respond correctly${NC}"
    echo ""
    echo "   Output:"
    cat "${TEMP_OUTPUT}" | sed 's/^/     /'
    echo ""
    echo -e "${RED}=========================================="
    echo "  ✗ MCP Server Test FAILED"
    echo "==========================================${NC}"
    exit 1
fi

echo ""
echo "Next steps:"
echo "  1. Test with VS Code: Open VS Code and check Copilot MCP integration"
echo "  2. Create systemd service: For automatic startup on VM boot"
echo ""
