#!/usr/bin/env bash
#
# Check MCP Infrastructure Status
#

# Load MCP environment
source "$(dirname "${BASH_SOURCE[0]}")/mcp-env.sh" --quiet

echo "╔════════════════════════════════════════════════════════════╗"
echo "║     MCP Infrastructure Status Check                        ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Check ChromaDB
echo "🔍 ChromaDB 1.1.1 (${CHROMADB_URL}):"
if curl -sf "${CHROMADB_URL}/api/v1/heartbeat" > /dev/null 2>&1; then
    echo "   ✅ Running and responsive (API v1)"
    
    # Check API v2 as well
    if curl -sf "${CHROMADB_URL}/api/v2" > /dev/null 2>&1; then
        echo "   ✅ API v2 endpoint available"
    fi
    
    # Get version info
    HEARTBEAT=$(curl -s "${CHROMADB_URL}/api/v1/heartbeat")
    echo "   💓 Heartbeat: ${HEARTBEAT}"
    
    # Get collections count
    COLLECTIONS=$(curl -s "${CHROMADB_URL}/api/v1/collections" 2>/dev/null | jq length 2>/dev/null || echo "unknown")
    echo "   📊 Collections: ${COLLECTIONS}"
else
    echo "   ❌ Not responding"
fi

# Check MCP REST API (port 3000)
echo ""
echo "🔍 MCP REST API (port 3000):"
if curl -sf http://127.0.0.1:3000/health > /dev/null 2>&1; then
    echo "   ✅ Running and responsive"
    curl -s http://127.0.0.1:3000/health | jq -r '   "   Service: " + .service + " v" + .version'
else
    echo "   ❌ Not responding"
fi

# Check n8n (port 5678) - if running from docker-compose.devops.yaml
echo ""
echo "🔍 n8n Workflow Automation (port 5678):"
if curl -sf http://127.0.0.1:5678 > /dev/null 2>&1; then
    echo "   ✅ Running and responsive"
    echo "   Access: http://localhost:5678"
else
    echo "   ℹ️  Not running (optional - see docker-compose.devops.yaml)"
fi

# Check systemd services
echo ""
echo "📋 Systemd Services:"
echo -n "   chromadb-persistent:  "
systemctl is-active chromadb-persistent.service
echo -n "   mcp-server-persistent: "
systemctl is-active mcp-server-persistent.service

# Check Docker containers
echo ""
echo "🐳 Docker Containers:"
if docker ps --format "table {{.Names}}\t{{.Status}}" | grep -q n8n; then
    docker ps --format "   {{.Names}}: {{.Status}}" | grep n8n
else
    echo "   ℹ️  n8n not running (available in docker-compose.devops.yaml)"
fi

echo ""
echo "╚════════════════════════════════════════════════════════════╝"
