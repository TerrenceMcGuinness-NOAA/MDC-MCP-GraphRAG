#!/usr/bin/env bash
#
# Install and Start MCP Server as Systemd Service
#

set -euo pipefail

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     MCP Server Systemd Service Installation               ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check if running as root or with sudo
if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}This script must be run with sudo${NC}"
    echo "Usage: sudo $0"
    exit 1
fi

# Load MCP environment (preserve sudo environment)
SCRIPT_DIR="$(dirname "${BASH_SOURCE[0]}")"
if [[ -f "${SCRIPT_DIR}/mcp_env.sh" ]]; then
    source "${SCRIPT_DIR}/mcp_env.sh" --quiet
else
    echo -e "${RED}✗ mcp_env.sh not found in ${SCRIPT_DIR}${NC}"
    exit 1
fi

# Get the actual user (not root)
ACTUAL_USER="${SUDO_USER:-$(whoami)}"
echo -e "${YELLOW}Installing service for user: ${ACTUAL_USER}${NC}"
echo ""

# Check if service file exists
SERVICE_FILE="${SETUP}/mcp-server-persistent.service"
if [[ ! -f "${SERVICE_FILE}" ]]; then
    echo -e "${RED}✗ Service file not found: ${SERVICE_FILE}${NC}"
    exit 1
fi

# Check if ChromaDB service is running
echo -e "${YELLOW}1. Checking ChromaDB service...${NC}"
if systemctl is-active --quiet chromadb-persistent.service; then
    echo -e "${GREEN}   ✓ ChromaDB service is running at ${CHROMADB_URL}${NC}"
else
    echo -e "${RED}   ✗ ChromaDB service is not running${NC}"
    echo -e "${YELLOW}   Starting ChromaDB service...${NC}"
    systemctl start chromadb-persistent.service
    sleep 2
    if systemctl is-active --quiet chromadb-persistent.service; then
        echo -e "${GREEN}   ✓ ChromaDB service started at ${CHROMADB_URL}${NC}"
    else
        echo -e "${RED}   ✗ Failed to start ChromaDB service${NC}"
        exit 1
    fi
fi
echo ""

# Copy service file to systemd
echo -e "${YELLOW}2. Installing service file...${NC}"
cp "${SERVICE_FILE}" /etc/systemd/system/
chmod 644 /etc/systemd/system/mcp-server-persistent.service
echo -e "${GREEN}   ✓ Service file installed${NC}"
echo ""

# Reload systemd
echo -e "${YELLOW}3. Reloading systemd daemon...${NC}"
systemctl daemon-reload
echo -e "${GREEN}   ✓ Systemd daemon reloaded${NC}"
echo ""

# Enable service (auto-start on boot)
echo -e "${YELLOW}4. Enabling service (auto-start on boot)...${NC}"
systemctl enable mcp-server-persistent.service
echo -e "${GREEN}   ✓ Service enabled${NC}"
echo ""

# Start service
echo -e "${YELLOW}5. Starting MCP server service...${NC}"
systemctl start mcp-server-persistent.service
sleep 2
echo ""

# Check status
echo -e "${YELLOW}6. Checking service status...${NC}"
if systemctl is-active --quiet mcp-server-persistent.service; then
    echo -e "${GREEN}   ✓ MCP server is running${NC}"
    echo ""
    
    # Show service info
    echo -e "${BLUE}Service Information:${NC}"
    systemctl status mcp-server-persistent.service --no-pager | head -15
    echo ""
    
    # Show recent logs
    echo -e "${BLUE}Recent Logs:${NC}"
    journalctl -u mcp-server-persistent.service -n 20 --no-pager
    echo ""
    
    echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║     ✓ MCP Server Successfully Installed & Running         ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo "Service commands:"
    echo "  Status:  sudo systemctl status mcp-server-persistent.service"
    echo "  Stop:    sudo systemctl stop mcp-server-persistent.service"
    echo "  Start:   sudo systemctl start mcp-server-persistent.service"
    echo "  Restart: sudo systemctl restart mcp-server-persistent.service"
    echo "  Logs:    sudo journalctl -u mcp-server-persistent.service -f"
    echo ""
else
    echo -e "${RED}   ✗ MCP server failed to start${NC}"
    echo ""
    echo -e "${YELLOW}Checking logs for errors:${NC}"
    journalctl -u mcp-server-persistent.service -n 50 --no-pager
    exit 1
fi
