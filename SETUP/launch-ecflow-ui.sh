#!/bin/bash
# launch-ecflow-ui.sh - Helper script for launching ecFlow UI with X11 forwarding
# Usage: ./launch-ecflow-ui.sh

# Source environment
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/mcp-env.sh"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}Launching ecFlow UI with X11 Forwarding${NC}"
echo "========================================"

# Check if DISPLAY is set
if [[ -z "$DISPLAY" ]]; then
    echo -e "${RED}❌ DISPLAY variable not set${NC}"
    echo -e "${YELLOW}Make sure you connected with: ssh -X [user]@host${NC}"
    exit 1
fi

echo -e "${GREEN}✅ DISPLAY set to: $DISPLAY${NC}"

# Check if ecFlow server is running
if ! docker exec global-workflow-ecflow-server ecflow_client --ping >/dev/null 2>&1; then
    echo -e "${RED}❌ ecFlow server not responding${NC}"
    echo -e "${YELLOW}Start services with: ./start-ecflow.sh${NC}"
    exit 1
fi

echo -e "${GREEN}✅ ecFlow server is responding${NC}"

# Check if UI container is running
if ! docker ps | grep -q global-workflow-ecflow-ui; then
    echo -e "${RED}❌ ecFlow UI container not running${NC}"
    echo -e "${YELLOW}Start services with: ./start-ecflow.sh${NC}"
    exit 1
fi

echo -e "${GREEN}✅ ecFlow UI container is running${NC}"

# Test X11 forwarding with a simple app first
echo -e "\n${BLUE}Testing X11 forwarding...${NC}"

# Since xeyes works, let's try the same approach for ecflow_ui
# The key insight is that xeyes works, so the X11 forwarding is functional

if docker exec -e DISPLAY="$DISPLAY" global-workflow-ecflow-ui xeyes -geometry 100x100 2>/dev/null &
then
    XEYES_PID=$!
    echo -e "${GREEN}✅ X11 forwarding working (xeyes launched)${NC}"
    sleep 2
    kill $XEYES_PID 2>/dev/null || true
else
    echo -e "${RED}❌ X11 forwarding not working${NC}"
    echo -e "${YELLOW}Troubleshooting:${NC}"
    echo -e "  1. Ensure SSH connection used: ssh -X [user]@host"
    echo -e "  2. Check X11 forwarding: echo \$DISPLAY"
    echo -e "  3. Test basic X11: xeyes"
    exit 1
fi

# Launch ecFlow UI
echo -e "\n${BLUE}Launching ecFlow UI...${NC}"
echo -e "${YELLOW}Note: This will run in foreground. Press Ctrl+C to exit.${NC}"
echo ""

# Try multiple approaches for ecFlow UI
echo -e "${BLUE}Attempting ecFlow UI launch (method 1: same as xeyes)...${NC}"
if docker exec -e DISPLAY="$DISPLAY" -it global-workflow-ecflow-ui ecflow_ui 2>&1 | head -20 | grep -q "qt.qpa.screen"; then
    echo -e "${YELLOW}Method 1 failed, trying as root user...${NC}"
    docker exec -u root -e DISPLAY="$DISPLAY" -it global-workflow-ecflow-ui ecflow_ui
else
    echo -e "${GREEN}ecFlow UI launching with method 1${NC}"
    docker exec -e DISPLAY="$DISPLAY" -it global-workflow-ecflow-ui ecflow_ui
fi