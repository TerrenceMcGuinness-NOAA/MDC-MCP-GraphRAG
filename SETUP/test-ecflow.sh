#!/bin/bash
# test-ecflow.sh - Test ecFlow server connectivity and basic operations
# Part of Global Workflow MCP RAG test suite

# Source environment
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/mcp-env.sh"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}Testing ecFlow Services${NC}"
echo "==============================="

# Test 1: Check if containers are running
echo -e "\n${BLUE}1. Container Status${NC}"
ECFLOW_SERVER=$(docker ps --filter "name=global-workflow-ecflow-server" --format "{{.Names}}")
ECFLOW_UI=$(docker ps --filter "name=global-workflow-ecflow-ui" --format "{{.Names}}")

if [[ -n "$ECFLOW_SERVER" ]]; then
    echo -e "   ✅ ecFlow server container: ${GREEN}$ECFLOW_SERVER${NC}"
else
    echo -e "   ❌ ecFlow server container: ${RED}NOT RUNNING${NC}"
fi

if [[ -n "$ECFLOW_UI" ]]; then
    echo -e "   ✅ ecFlow UI container: ${GREEN}$ECFLOW_UI${NC}"
else
    echo -e "   ❌ ecFlow UI container: ${RED}NOT RUNNING${NC}"
fi

# Test 2: ecFlow server ping
echo -e "\n${BLUE}2. Server Connectivity${NC}"
if docker exec global-workflow-ecflow-server ecflow_client --ping >/dev/null 2>&1; then
    PING_TIME=$(docker exec global-workflow-ecflow-server ecflow_client --ping 2>/dev/null | grep -o '[0-9]*\.[0-9]*' | head -1)
    echo -e "   ✅ ecFlow server ping: ${GREEN}SUCCESS${NC} (${PING_TIME}ms)"
else
    echo -e "   ❌ ecFlow server ping: ${RED}FAILED${NC}"
fi

# Test 3: Port accessibility
echo -e "\n${BLUE}3. Port Accessibility${NC}"
if nc -z localhost 3141 2>/dev/null; then
    echo -e "   ✅ ecFlow server port 3141: ${GREEN}ACCESSIBLE${NC}"
else
    echo -e "   ❌ ecFlow server port 3141: ${RED}NOT ACCESSIBLE${NC}"
fi

# Test X11 instead of VNC
echo -e "\n${BLUE}4. X11 Support${NC}"
if docker exec global-workflow-ecflow-ui which xeyes >/dev/null 2>&1; then
    echo -e "   ✅ X11 apps available: ${GREEN}YES${NC}"
    echo -e "   ℹ️  Test with: docker exec -e DISPLAY=\$DISPLAY global-workflow-ecflow-ui xeyes"
else
    echo -e "   ❌ X11 apps: ${RED}NOT AVAILABLE${NC}"
fi

# Test 4: Server version and info
echo -e "\n${BLUE}5. Server Information${NC}"
if docker exec global-workflow-ecflow-server ecflow_server --version >/dev/null 2>&1; then
    VERSION=$(docker exec global-workflow-ecflow-server ecflow_server --version 2>/dev/null | head -1)
    echo -e "   ✅ ecFlow version: ${GREEN}${VERSION}${NC}"
else
    echo -e "   ❌ Failed to get ecFlow version"
fi

# Test 5: Basic client operations
echo -e "\n${BLUE}6. Basic Client Operations${NC}"
if docker exec global-workflow-ecflow-server ecflow_client --help >/dev/null 2>&1; then
    echo -e "   ✅ ecFlow client: ${GREEN}FUNCTIONAL${NC}"
    
    # Try to get server stats
    if docker exec global-workflow-ecflow-server ecflow_client --stats >/dev/null 2>&1; then
        echo -e "   ✅ Server stats: ${GREEN}AVAILABLE${NC}"
    else
        echo -e "   ⚠️  Server stats: ${YELLOW}NOT AVAILABLE${NC}"
    fi
else
    echo -e "   ❌ ecFlow client: ${RED}NOT FUNCTIONAL${NC}"
fi

# Test 6: Data directory mounting
echo -e "\n${BLUE}7. Data Directory Mounting${NC}"
if docker exec global-workflow-ecflow-server ls /home/ecflow/workspace >/dev/null 2>&1; then
    echo -e "   ✅ Workspace directory: ${GREEN}MOUNTED${NC}"
    
    # Check if we can create files
    if docker exec global-workflow-ecflow-server touch /home/ecflow/workspace/test_file 2>/dev/null; then
        echo -e "   ✅ Write permissions: ${GREEN}OK${NC}"
        docker exec global-workflow-ecflow-server rm -f /home/ecflow/workspace/test_file 2>/dev/null
    else
        echo -e "   ❌ Write permissions: ${RED}DENIED${NC}"
    fi
else
    echo -e "   ❌ Workspace directory: ${RED}NOT MOUNTED${NC}"
fi

# Test 7: Log accessibility
echo -e "\n${BLUE}8. Service Logs${NC}"
LOG_LINES=$(docker logs global-workflow-ecflow-server 2>&1 | wc -l)
if [[ $LOG_LINES -gt 0 ]]; then
    echo -e "   ✅ ecFlow server logs: ${GREEN}${LOG_LINES} lines${NC}"
else
    echo -e "   ⚠️  ecFlow server logs: ${YELLOW}EMPTY${NC}"
fi

UI_LOG_LINES=$(docker logs global-workflow-ecflow-ui 2>&1 | wc -l)
if [[ $UI_LOG_LINES -gt 0 ]]; then
    echo -e "   ✅ ecFlow UI logs: ${GREEN}${UI_LOG_LINES} lines${NC}"
else
    echo -e "   ⚠️  ecFlow UI logs: ${YELLOW}EMPTY${NC}"
fi

# Summary
echo -e "\n${BLUE}Test Summary${NC}"
echo "============"
echo -e "ecFlow Server:  http://localhost:3141"
echo -e "ecFlow UI:      SSH X11 forwarding (see instructions below)"
echo -e ""
echo -e "Quick commands:"
echo -e "  Test ping:    docker exec global-workflow-ecflow-server ecflow_client --ping"
echo -e "  View stats:   docker exec global-workflow-ecflow-server ecflow_client --stats"  
echo -e "  Server logs:  docker logs global-workflow-ecflow-server"
echo -e "  UI logs:      docker logs global-workflow-ecflow-ui"
echo -e "  Test X11:     docker exec -e DISPLAY=\$DISPLAY global-workflow-ecflow-ui xeyes"
echo -e ""
echo -e "X11 Forwarding Setup:"
echo -e "  1. ssh -X anna@44.200.18.186"
echo -e "  2. docker exec -e DISPLAY=\$DISPLAY global-workflow-ecflow-ui ecflow_ui"
echo -e ""

# Health check
if [[ -n "$ECFLOW_SERVER" ]] && docker exec global-workflow-ecflow-server ecflow_client --ping >/dev/null 2>&1; then
    echo -e "${GREEN}✅ ecFlow services are healthy and ready!${NC}"
    exit 0
else
    echo -e "${RED}❌ ecFlow services have issues - check logs${NC}"
    exit 1
fi