# Phase 23: Static Mode Multi-User Gateway Architecture

**Description**: Refactor the MCP Gateway deployment from per-session container spawning (`--long-lived`) to static container mode (`--static`) with systemd management and health monitoring, enabling efficient multi-user access from RDHPCS platforms.

**Priority**: HIGH (Production stability)
**Timeline**: January 2025
**Status**: PLANNING
**Depends On**: Phase 11 (Docker MCP Gateway) ✅ COMPLETE

---

## Problem Statement

### Observed Issue

The current MCP Gateway configuration uses `--long-lived` mode, which spawns containers per-session:

```bash
# Current systemd service (problematic)
docker-mcp gateway run --catalog eib-local.yaml --servers eib-mcp-rag \
    --transport streaming --port 18888 --long-lived
```

**Symptoms**:
- Container accumulation over time (7 orphaned containers observed after 2 days)
- Containers not cleaned up when VS Code sessions disconnect ungracefully
- Memory consumption grows unbounded (2GB × N containers)

### Root Cause Analysis

From mcp-gateway source code analysis (`pkg/gateway/clientpool.go`):

```go
// Long-lived containers are keyed by {serverName, session}
keptClients map[clientKey]keptClient

// Cleanup only happens on explicit Session().Close()
func (cp *clientPool) ReleaseClient(client mcpclient.Client) {
    if !foundKept {
        client.Session().Close()  // Only called on graceful disconnect
    }
}
```

**The Gap**: When VS Code tunnels drop or windows close without proper MCP session termination, the gateway never receives `Session().Close()`, leaving orphaned containers.

### Multi-User Requirements

```
RDHPCS User Access Pattern
├── 5-10 active developers
├── Each with 1-3 VS Code instances (local, HPC tunnels)
├── Platforms: Hera, Orion, Hercules, WCOSS2, Gaea
├── Peak concurrent connections: 15-30
└── Tool calls: Bursty (heavy during active dev)
```

---

## Architecture Decision

### Rejected: Per-Session Containers (`--long-lived`)

| Aspect | Issue |
|--------|-------|
| Container lifecycle | Tied to session close events |
| Ungraceful disconnects | Leaves orphans |
| Memory scaling | 2GB × sessions |
| Complexity | Requires cleanup cron jobs |

### Selected: Static Mode (`--static`)

| Aspect | Benefit |
|--------|---------|
| Container lifecycle | Managed by systemd, not per-session |
| Connections | Gateway multiplexes to single container |
| Memory | Fixed (8GB for single container) |
| Scaling | Handles 15-30 concurrent users |

### Target Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Dev VM (eib-dev-1)                        │
│                                                              │
│  ┌────────────────┐     ┌──────────────────────────┐        │
│  │ mcp-gateway    │     │  eib-mcp-rag-static      │        │
│  │  (systemd)     │────▶│    (systemd)             │        │
│  │  Port 18888    │     │    8GB / 4 CPUs          │        │
│  └────────────────┘     └──────────────────────────┘        │
│         ▲                        │                           │
│         │                   ┌────┴────┐                      │
│         │                   ▼         ▼                      │
│    RDHPCS Users         ChromaDB   Neo4j                    │
│    (Hera, Orion,        (:8080)   (:7687)                   │
│     Hercules, etc)                                          │
└─────────────────────────────────────────────────────────────┘
```

---

## Implementation Plan

### Step 1: Create MCP RAG Container Service
**Type**: file_creation
**Target**: /etc/systemd/system/mcp-rag.service
**Description**: Systemd unit to manage the static MCP RAG container

```ini
[Unit]
Description=EIB MCP RAG Server (Static Container)
Documentation=https://github.com/NOAA-EMC/eib-mcp-rag-server
After=docker.service chromadb.service
Requires=docker.service
Wants=chromadb.service

[Service]
Type=simple
Restart=always
RestartSec=10
TimeoutStartSec=120
TimeoutStopSec=30

# Cleanup any existing container before start
ExecStartPre=-/usr/bin/docker stop eib-mcp-rag-static
ExecStartPre=-/usr/bin/docker rm eib-mcp-rag-static

# Run container with resource limits
ExecStart=/usr/bin/docker run \
    --name eib-mcp-rag-static \
    --memory=8g \
    --cpus=4 \
    --init \
    --security-opt no-new-privileges \
    -e CHROMADB_HOST=172.17.0.1 \
    -e CHROMADB_PORT=8080 \
    -e NEO4J_URI=bolt://172.17.0.1:7687 \
    -e NEO4J_USER=neo4j \
    -e NEO4J_PASSWORD=${NEO4J_PASSWORD} \
    -e MCP_WORKFLOW_ROOT=/app/supported_repos/global-workflow \
    -v /mcp_rag_eib/eib-mcp-rag-server/supported_repos:/app/supported_repos:ro \
    -v /mcp_rag_eib/eib-mcp-rag-server/sdd_framework:/app/sdd_framework:ro \
    --label docker-mcp=true \
    --label docker-mcp-name=eib-mcp-rag \
    --label docker-mcp-transport=stdio \
    eib-mcp-rag:latest

ExecStop=/usr/bin/docker stop eib-mcp-rag-static
ExecStopPost=-/usr/bin/docker rm eib-mcp-rag-static

[Install]
WantedBy=multi-user.target
```

---

### Step 2: Create MCP Gateway Service (Static Mode)
**Type**: file_creation
**Target**: /etc/systemd/system/mcp-gateway.service
**Description**: Systemd unit for the gateway in static mode

```ini
[Unit]
Description=Docker MCP Gateway (Static Mode)
Documentation=https://github.com/docker/mcp-gateway
After=mcp-rag.service
Requires=mcp-rag.service

[Service]
Type=simple
Restart=always
RestartSec=5
User=Terry.McGuinness
Environment=HOME=/home/Terry.McGuinness

ExecStart=/home/Terry.McGuinness/.docker/cli-plugins/docker-mcp gateway run \
    --catalog eib-local.yaml \
    --servers eib-mcp-rag \
    --transport streaming \
    --port 18888 \
    --static=true \
    --verbose

# Clean up orphaned containers on stop (safety net)
ExecStopPost=-/usr/bin/docker ps -q --filter "label=docker-mcp-name=eib-mcp-rag" | xargs -r docker stop
ExecStopPost=-/usr/bin/docker ps -aq --filter "label=docker-mcp-name=eib-mcp-rag" | xargs -r docker rm

[Install]
WantedBy=multi-user.target
```

---

### Step 3: Create Health Check Script
**Type**: file_creation
**Target**: /opt/mcp/bin/health-check.sh
**Description**: Health monitoring script for cron integration

```bash
#!/bin/bash
# MCP Gateway Health Check Script
# Runs via cron every 5 minutes

set -euo pipefail

CONTAINER_NAME="eib-mcp-rag-static"
GATEWAY_PORT=18888
LOG_FILE="/var/log/mcp-health.log"
ALERT_EMAIL="${MCP_ALERT_EMAIL:-}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "${LOG_FILE}"
}

alert() {
    log "ALERT: $1"
    if [[ -n "${ALERT_EMAIL}" ]]; then
        echo "$1" | mail -s "MCP Health Alert" "${ALERT_EMAIL}" 2>/dev/null || true
    fi
}

# Check 1: Container running
if ! docker ps --filter "name=${CONTAINER_NAME}" --filter "status=running" -q | grep -q .; then
    alert "Container ${CONTAINER_NAME} not running - restarting mcp-rag.service"
    systemctl restart mcp-rag
    sleep 30
fi

# Check 2: Gateway port responding
if ! ss -tlnp | grep -q ":${GATEWAY_PORT}"; then
    alert "Gateway port ${GATEWAY_PORT} not listening - restarting mcp-gateway.service"
    systemctl restart mcp-gateway
    sleep 10
fi

# Check 3: Container memory usage (warn at 75%, restart at 90%)
MEMORY_USAGE=$(docker stats --no-stream --format "{{.MemPerc}}" "${CONTAINER_NAME}" 2>/dev/null | tr -d '%')
if [[ -n "${MEMORY_USAGE}" ]]; then
    MEMORY_INT=${MEMORY_USAGE%.*}
    if (( MEMORY_INT > 90 )); then
        alert "Container memory at ${MEMORY_USAGE}% - restarting to clear"
        systemctl restart mcp-rag
    elif (( MEMORY_INT > 75 )); then
        log "WARN: Container memory at ${MEMORY_USAGE}%"
    fi
fi

# Check 4: ChromaDB connectivity (from container perspective)
if ! docker exec "${CONTAINER_NAME}" curl -sf "http://172.17.0.1:8080/api/v2/heartbeat" > /dev/null 2>&1; then
    log "WARN: ChromaDB heartbeat failed from container"
fi

# Check 5: Neo4j connectivity
if ! docker exec "${CONTAINER_NAME}" curl -sf "http://172.17.0.1:7474" > /dev/null 2>&1; then
    log "WARN: Neo4j web interface not responding"
fi

log "OK: All health checks passed"
```

---

### Step 4: Create Cron Configuration
**Type**: file_creation
**Target**: /etc/cron.d/mcp-health
**Description**: Cron job for regular health monitoring

```cron
# MCP Gateway Health Monitoring
# Runs every 5 minutes

SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin

*/5 * * * * root /opt/mcp/bin/health-check.sh 2>&1 | head -20

# Daily log rotation
0 0 * * * root find /var/log/mcp-health.log -size +10M -exec truncate -s 0 {} \;
```

---

### Step 5: Update Catalog for Static Mode
**Type**: file_modification
**Target**: ~/.docker/mcp/catalogs/eib-local.yaml
**Description**: Ensure catalog is compatible with static mode

```yaml
version: 3
name: eib-local
registry:
  eib-mcp-rag:
    title: EIB MCP RAG Server
    description: Global Workflow code analysis and documentation search
    type: server
    # Static mode uses pre-existing container, not image launching
    image: eib-mcp-rag:latest
    longLived: false  # Not needed in static mode
    env:
      - name: CHROMADB_HOST
        value: "172.17.0.1"
      - name: CHROMADB_PORT
        value: "8080"
      - name: NEO4J_URI
        value: "bolt://172.17.0.1:7687"
      - name: MCP_WORKFLOW_ROOT
        value: "/app/supported_repos/global-workflow"
    volumes:
      - /mcp_rag_eib/eib-mcp-rag-server/supported_repos:/app/supported_repos:ro
      - /mcp_rag_eib/eib-mcp-rag-server/sdd_framework:/app/sdd_framework:ro
    resources:
      memory: 8g
      cpus: 4
```

---

### Step 6: Create Deployment Script
**Type**: file_creation
**Target**: SETUP/bin/deploy-static-gateway.sh
**Description**: One-command deployment of the new architecture

```bash
#!/bin/bash
# Deploy Static Mode MCP Gateway Architecture
# Phase 23 Implementation

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

echo "[INFO] Phase 23: Deploying Static Mode Gateway Architecture"

# Step 1: Stop existing services
echo "[INFO] Stopping existing MCP services..."
sudo systemctl stop mcp-gateway 2>/dev/null || true
sudo systemctl stop mcp-rag 2>/dev/null || true

# Step 2: Clean up orphaned containers
echo "[INFO] Cleaning up orphaned containers..."
docker ps -q --filter "ancestor=eib-mcp-rag:latest" | xargs -r docker stop 2>/dev/null || true
docker ps -aq --filter "ancestor=eib-mcp-rag:latest" | xargs -r docker rm 2>/dev/null || true

# Step 3: Install systemd services
echo "[INFO] Installing systemd service files..."
sudo cp "${PROJECT_ROOT}/SETUP/systemd/mcp-rag.service" /etc/systemd/system/
sudo cp "${PROJECT_ROOT}/SETUP/systemd/mcp-gateway.service" /etc/systemd/system/

# Step 4: Install health check
echo "[INFO] Installing health check script..."
sudo mkdir -p /opt/mcp/bin
sudo cp "${PROJECT_ROOT}/SETUP/bin/health-check.sh" /opt/mcp/bin/
sudo chmod +x /opt/mcp/bin/health-check.sh
sudo cp "${PROJECT_ROOT}/SETUP/cron.d/mcp-health" /etc/cron.d/

# Step 5: Create log file
sudo touch /var/log/mcp-health.log
sudo chmod 644 /var/log/mcp-health.log

# Step 6: Reload and start services
echo "[INFO] Starting services..."
sudo systemctl daemon-reload
sudo systemctl enable mcp-rag mcp-gateway
sudo systemctl start mcp-rag
sleep 10  # Wait for container to initialize
sudo systemctl start mcp-gateway

# Step 7: Verify
echo "[INFO] Verifying deployment..."
sleep 5

if systemctl is-active --quiet mcp-rag && systemctl is-active --quiet mcp-gateway; then
    echo "[OK] Services started successfully"
    echo ""
    echo "Container status:"
    docker ps --filter "name=eib-mcp-rag-static" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    echo ""
    echo "Gateway listening on port 18888"
else
    echo "[ERROR] Service startup failed"
    echo "Check: journalctl -u mcp-rag -u mcp-gateway --since '5 minutes ago'"
    exit 1
fi
```

---

## Scaling Considerations

### Resource Allocation

| Users | Connections | Container Memory | Container CPUs |
|-------|-------------|------------------|----------------|
| 1-5   | 1-15        | 4GB              | 2              |
| 5-10  | 15-30       | 8GB              | 4              |
| 10-20 | 30-60       | 16GB             | 8              |

### Monitoring Thresholds

| Metric | Warning | Critical | Action |
|--------|---------|----------|--------|
| Memory usage | >75% | >90% | Restart container |
| Response time | >5s | >30s | Investigate backends |
| Error rate | >5% | >20% | Alert + investigate |
| Concurrent connections | >20 | >40 | Plan horizontal scaling |

### Future Scaling Path (Phase 24)

If usage exceeds 10-20 concurrent users, implement horizontal scaling:

```
Load Balancer (HAProxy/Nginx)
    ├── mcp-gateway-1 → mcp-rag-1
    ├── mcp-gateway-2 → mcp-rag-2
    └── mcp-gateway-3 → mcp-rag-3
            │
    Shared ChromaDB + Neo4j
```

---

## Rollback Plan

If static mode causes issues, revert to per-session mode:

```bash
# Rollback script
sudo systemctl stop mcp-gateway mcp-rag
sudo systemctl disable mcp-gateway mcp-rag

# Restore old service file with --long-lived
sudo cp /etc/systemd/system/mcp-gateway.service.backup /etc/systemd/system/mcp-gateway.service
sudo systemctl daemon-reload
sudo systemctl start mcp-gateway
```

---

## Acceptance Criteria

- [ ] Single `eib-mcp-rag-static` container running at all times
- [ ] No container accumulation after 48 hours of multi-user usage
- [ ] Gateway accessible from all RDHPCS platforms via SSH tunnel
- [ ] Health check detects and recovers from container failures within 5 minutes
- [ ] Memory usage stays below 75% under normal load (5-10 users)
- [ ] All 38 MCP tools functional through static gateway

---

## References

- [Phase 11: Docker MCP Gateway](phase11_docker_mcp_gateway_langflow.md)
- [mcp-gateway static mode example](https://github.com/docker/mcp-gateway/tree/main/examples/compose-static)
- [mcp-gateway clientpool.go](https://github.com/docker/mcp-gateway/blob/main/pkg/gateway/clientpool.go)
- Container accumulation investigation: January 8, 2026 session
