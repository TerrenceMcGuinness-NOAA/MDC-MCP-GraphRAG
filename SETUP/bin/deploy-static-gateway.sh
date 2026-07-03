#!/bin/bash
# DEPRECATED (Phase 63c, 2026-07-03): This deployer installs the retired static-
# mode stack (health-check.sh, /etc/cron.d/mcp-health, mcp-rag.service). Kept
# in-tree only as Phase 63b rollback material. Do NOT run on new hosts. See
# .kiro/specs/retire-static-node-container/.

# Deploy Static Mode MCP Gateway Architecture
# Phase 23 Implementation
#
# Usage: sudo ./deploy-static-gateway.sh

set -euo pipefail

# Short-circuit unless explicitly opted in for rollback.
if [[ "${MCP_ALLOW_STATIC_MODE_ROLLBACK:-0}" != "1" ]]; then
    echo "[SKIP] deploy-static-gateway.sh is DEPRECATED (Phase 63c)." >&2
    echo "       Rollback path: set MCP_ALLOW_STATIC_MODE_ROLLBACK=1 to run." >&2
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

echo "[INFO] Phase 23: Deploying Static Mode Gateway Architecture"
echo "[INFO] Project root: ${PROJECT_ROOT}"

# Check for root
if [[ $EUID -ne 0 ]]; then
   echo "[ERROR] This script must be run as root (sudo)"
   exit 1
fi

# Step 1: Stop existing services
echo "[INFO] Stopping existing MCP services..."
systemctl stop mcp-gateway 2>/dev/null || true
systemctl stop mcp-rag 2>/dev/null || true

# Step 2: Clean up orphaned containers
echo "[INFO] Cleaning up orphaned containers..."
docker ps -q --filter "ancestor=eib-mcp-rag:latest" | xargs -r docker stop 2>/dev/null || true
docker ps -aq --filter "ancestor=eib-mcp-rag:latest" | xargs -r docker rm 2>/dev/null || true
docker ps -q --filter "name=eib-mcp-rag" | xargs -r docker stop 2>/dev/null || true
docker ps -aq --filter "name=eib-mcp-rag" | xargs -r docker rm 2>/dev/null || true

# Step 3: Install systemd services
echo "[INFO] Installing systemd service files..."
cp "${PROJECT_ROOT}/SETUP/systemd/mcp-rag.service" /etc/systemd/system/
cp "${PROJECT_ROOT}/SETUP/systemd/mcp-gateway.service" /etc/systemd/system/

# Step 4: Install health check
echo "[INFO] Installing health check script..."
mkdir -p /opt/mcp/bin
cp "${PROJECT_ROOT}/SETUP/bin/health-check.sh" /opt/mcp/bin/
chmod +x /opt/mcp/bin/health-check.sh
cp "${PROJECT_ROOT}/SETUP/cron.d/mcp-health" /etc/cron.d/
chmod 644 /etc/cron.d/mcp-health

# Step 5: Create log file
touch /var/log/mcp-health.log
chmod 644 /var/log/mcp-health.log

# Step 6: Reload and start services
echo "[INFO] Reloading systemd daemon..."
systemctl daemon-reload

echo "[INFO] Enabling services..."
systemctl enable mcp-rag mcp-gateway

echo "[INFO] Starting mcp-rag service..."
systemctl start mcp-rag
echo "[INFO] Waiting for container to initialize..."
sleep 15

echo "[INFO] Starting mcp-gateway service..."
systemctl start mcp-gateway
sleep 5

# Step 7: Verify
echo "[INFO] Verifying deployment..."

if systemctl is-active --quiet mcp-rag && systemctl is-active --quiet mcp-gateway; then
    echo ""
    echo "[OK] Services started successfully"
    echo ""
    echo "Container status:"
    docker ps --filter "name=eib-mcp-rag-static" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    echo ""
    echo "Service status:"
    systemctl status mcp-rag --no-pager -l | head -10
    echo ""
    systemctl status mcp-gateway --no-pager -l | head -10
    echo ""
    echo "[OK] Gateway listening on port 18888"
    echo "[OK] Phase 23 deployment complete"
else
    echo ""
    echo "[ERROR] Service startup failed"
    echo ""
    echo "Debug commands:"
    echo "  journalctl -u mcp-rag --since '5 minutes ago'"
    echo "  journalctl -u mcp-gateway --since '5 minutes ago'"
    echo "  docker logs eib-mcp-rag-static"
    exit 1
fi
