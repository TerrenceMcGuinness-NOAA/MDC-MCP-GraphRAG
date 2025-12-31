#!/bin/bash
# start-ecflow.sh - Start ecFlow server and UI services
# Part of Global Workflow MCP RAG provisioning system

# Source environment
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/mcp-env.sh"

# Configuration
ECFLOW_DATA_DIR="${PERSISTENT_ROOT}/data/ecflow"
ECFLOW_SERVER_CONTAINER="global-workflow-ecflow-server"
ECFLOW_UI_CONTAINER="global-workflow-ecflow-ui"

echo "[INFO] Starting ecFlow services for Global Workflow..."

# Create data directories if they don't exist
sudo mkdir -p "${ECFLOW_DATA_DIR}"/{server,suites,logs}
sudo chown -R 1000:1000 "${ECFLOW_DATA_DIR}"

echo "[INFO] Data directories created at: ${ECFLOW_DATA_DIR}"

# Build and start ecFlow services via docker-compose
cd "${SCRIPT_DIR}"

echo "[INFO] Building ecFlow server container..."
docker compose build ecflow-server

echo "[INFO] Building ecFlow UI container (X11 forwarding)..."  
docker compose build ecflow-ui

echo "[INFO] Starting ecFlow server..."
docker compose up -d ecflow-server

# Wait for server to be healthy
echo "[INFO] Waiting for ecFlow server to be ready..."
timeout=60
while [ $timeout -gt 0 ]; do
    if docker compose exec ecflow-server ecflow_client --ping 2>/dev/null; then
        echo "[OK] ecFlow server is ready!"
        break
    fi
    echo "    Waiting for server... (${timeout}s remaining)"
    sleep 2
    timeout=$((timeout-2))
done

if [ $timeout -le 0 ]; then
    echo "[ERROR] ecFlow server failed to start within 60 seconds"
    docker compose logs ecflow-server
    exit 1
fi

echo "[INFO] Starting ecFlow UI (X11 container)..."
docker compose up -d ecflow-ui

# Display service status
echo ""
echo "=== ecFlow Services Status ==="
docker compose ps | grep ecflow

echo ""
echo "=== Service Endpoints ==="
echo "ecFlow Server:  localhost:3141"
echo "ecFlow UI:      SSH with X11 forwarding (see usage below)"
echo ""
echo "=== ecFlow UI Usage (X11 Forwarding) ==="
echo "1. Connect with X11 forwarding:"
echo "   ssh -X anna@44.200.18.186"
echo "   ssh -X georgios@44.200.18.186"  
echo "   ssh -X brian@44.200.18.186"
echo ""
echo "2. Launch ecFlow UI:"
echo "   docker exec -e DISPLAY=\$DISPLAY global-workflow-ecflow-ui ecflow_ui"
echo ""
echo "=== Alternative: Direct X11 Setup ==="
echo "If running locally with X11:"
echo "   export DISPLAY=:0"
echo "   docker exec -e DISPLAY=\$DISPLAY global-workflow-ecflow-ui ecflow_ui"
echo ""
echo "=== Quick Test ==="
echo "Test server: docker exec ${ECFLOW_SERVER_CONTAINER} ecflow_client --ping"
echo "View logs:   docker compose logs ecflow-server"
echo "Test X11:    docker exec global-workflow-ecflow-ui xeyes"
echo ""

# Test the server connection
if docker exec "${ECFLOW_SERVER_CONTAINER}" ecflow_client --ping >/dev/null 2>&1; then
    echo "[OK] ecFlow server responding to ping"
else
    echo "[WARN] ecFlow server not responding - check logs"
fi

echo "[INFO] ecFlow services startup complete!"