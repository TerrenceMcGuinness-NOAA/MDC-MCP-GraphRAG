#!/bin/bash
################################################################################
# Start LangFlow with Docker Compose
# Version: 1.0.0
# Location: ${SETUP}/start-langflow.sh
################################################################################

set -euo pipefail

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Starting LangFlow for Global Workflow MCP RAG${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════${NC}\n"

# Source environment if not already loaded
if [ -z "${SETUP:-}" ]; then
    export SETUP="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    source "${SETUP}/mcp_env.sh" --quiet
fi

echo -e "${GREEN}✓${NC} Environment loaded"
echo -e "  PERSISTENT_ROOT: ${PERSISTENT_ROOT}"
echo -e "  CHROMADB_PORT: ${CHROMADB_PORT}"
echo -e "  CHROMADB_URL: ${CHROMADB_URL}\n"

# Verify ChromaDB is running
echo -e "${BLUE}Checking ChromaDB...${NC}"
if curl -s "${CHROMADB_URL}/api/v1/heartbeat" > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} ChromaDB is responding on port ${CHROMADB_PORT}\n"
else
    echo -e "${YELLOW}⚠${NC}  ChromaDB not responding. Starting service...\n"
    sudo systemctl start chromadb-persistent.service
    sleep 5
fi

# Navigate to SETUP directory
cd "${SETUP}"

# Check if docker-compose.yml exists
if [ ! -f "docker-compose.yml" ]; then
    echo -e "${RED}✗${NC} docker-compose.yml not found in ${SETUP}"
    exit 1
fi

# Show configuration
echo -e "${BLUE}Docker Compose Configuration:${NC}"
docker compose config | grep -A3 "langflow:" | head -10

echo -e "\n${BLUE}Starting LangFlow container...${NC}\n"

# Start LangFlow
docker compose up -d langflow

echo -e "\n${BLUE}Waiting for LangFlow to start...${NC}"
sleep 10

# Check container status
echo -e "\n${BLUE}Container Status:${NC}"
docker compose ps langflow

# Try to access LangFlow
echo -e "\n${BLUE}Testing LangFlow endpoint...${NC}"
for i in {1..5}; do
    if curl -s http://127.0.0.1:7860/ > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} LangFlow is accessible at http://127.0.0.1:7860"
        echo -e "\n${GREEN}════════════════════════════════════════════════════════${NC}"
        echo -e "${GREEN}  LangFlow Started Successfully!${NC}"
        echo -e "${GREEN}════════════════════════════════════════════════════════${NC}\n"
        echo -e "Access LangFlow:"
        echo -e "  URL: ${BLUE}http://127.0.0.1:7860${NC}"
        echo -e "  Username: ${GREEN}admin${NC}"
        echo -e "  Password: ${GREEN}admin123${NC}\n"
        echo -e "ChromaDB Connection:"
        echo -e "  Host: ${BLUE}host.docker.internal${NC}"
        echo -e "  Port: ${GREEN}${CHROMADB_PORT}${NC}\n"
        echo -e "View logs: ${YELLOW}docker compose logs -f langflow${NC}"
        exit 0
    fi
    echo -e "  Attempt $i/5... waiting..."
    sleep 5
done

echo -e "${YELLOW}⚠${NC}  LangFlow may still be starting up"
echo -e "Check logs with: ${YELLOW}docker compose logs -f langflow${NC}"
