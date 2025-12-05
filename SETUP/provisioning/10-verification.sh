#!/bin/bash
################################################################################
# 10-verification.sh - Final verification and summary
# Part of modular provisioning system v4.0.0
################################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

# This script can run as root or user
log_subsection "Installation Verification"

################################################################################
# System Components
################################################################################

echo ""
echo -e "${CYAN}System Components:${NC}"

# Node.js
if command_exists node; then
    echo "  Node.js: $(node --version)"
else
    echo "  Node.js: NOT INSTALLED"
fi

# npm
if command_exists npm; then
    echo "  npm: $(npm --version)"
else
    echo "  npm: NOT INSTALLED"
fi

# Python
if command_exists python3; then
    echo "  Python: $(python3 --version 2>&1 | head -1)"
else
    echo "  Python: NOT INSTALLED"
fi

# Docker
if command_exists docker; then
    echo "  Docker: $(docker --version 2>&1 | cut -d',' -f1)"
else
    echo "  Docker: NOT INSTALLED"
fi

################################################################################
# Services Status
################################################################################

echo ""
echo -e "${CYAN}Services Status:${NC}"

# ChromaDB
if curl -sf "${CHROMADB_URL}/api/v1/heartbeat" > /dev/null 2>&1; then
    COLLECTIONS=$(curl -s "${CHROMADB_URL}/api/v1/collections" | jq 'length' 2>/dev/null || echo "?")
    echo -e "  ChromaDB: ${GREEN}Running${NC} (${COLLECTIONS} collections)"
else
    echo -e "  ChromaDB: ${RED}Not responding${NC}"
fi

# Neo4j
if curl -sf "http://localhost:${NEO4J_HTTP_PORT}" > /dev/null 2>&1; then
    echo -e "  Neo4j: ${GREEN}Running${NC}"
else
    echo -e "  Neo4j: ${YELLOW}Not responding${NC}"
fi

# Docker containers
echo ""
echo -e "${CYAN}Docker Containers:${NC}"
docker ps --format "  {{.Names}}: {{.Status}}" 2>/dev/null || echo "  Docker not accessible"

################################################################################
# Disk Usage
################################################################################

echo ""
echo -e "${CYAN}Disk Usage:${NC}"
df -h "${PERSISTENT_ROOT}" 2>/dev/null | tail -1 | awk '{printf "  Storage: %s used of %s (Available: %s)\n", $3, $2, $4}'

echo ""
echo -e "${CYAN}Directory Sizes:${NC}"
du -sh "${MCP_ROOT}" 2>/dev/null | awk '{print "  MCP Server: " $1}'
du -sh "${DATA_ROOT}" 2>/dev/null | awk '{print "  Data: " $1}'
du -sh "${CACHE_ROOT}" 2>/dev/null | awk '{print "  Cache: " $1}'

################################################################################
# Quick Commands Reference
################################################################################

echo ""
echo -e "${CYAN}Quick Commands:${NC}"
echo "  Check ChromaDB:    curl ${CHROMADB_URL}/api/v1/heartbeat"
echo "  Check Neo4j:       curl http://localhost:${NEO4J_HTTP_PORT}"
echo "  Docker status:     docker compose ps"
echo "  MCP logs:          journalctl -u mcp-server-persistent -f"
echo "  ChromaDB logs:     journalctl -u chromadb-persistent -f"

################################################################################
# Next Steps
################################################################################

echo ""
echo -e "${CYAN}Next Steps:${NC}"
echo "  1. Log out and back in (for docker group membership)"
echo "  2. Source environment: source ${SETUP_DIR}/mcp-env.sh"
echo "  3. Test MCP server: node ${MCP_ROOT}/src/UnifiedMCPServer.js --help"
echo "  4. Access Neo4j: http://localhost:${NEO4J_HTTP_PORT} (neo4j/${NEO4J_PASSWORD})"

echo ""
log_success "Verification complete"

exit 0
