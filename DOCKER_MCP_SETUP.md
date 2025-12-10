# Docker MCP Gateway Setup - Phase 11

**Status**: Partial Implementation
**Date**: December 9, 2025
**Phase**: 11 - Docker MCP Gateway Integration

## Overview

This document describes the Docker-based MCP server deployment for the Global Workflow MCP RAG system. Phase 11 aimed to containerize the MCP server and integrate it with Docker MCP Gateway for multi-client access and LangFlow integration.

## What Was Accomplished

### ✅ Core Infrastructure

1. **Dockerized MCP Server**
   - Created production-ready Dockerfile (`mcp_server_node/Dockerfile`)
   - Image size: 1.66GB (Node.js 20-slim base)
   - All 32 MCP tools functional in container
   - Proper health checks and environment configuration

2. **Docker Compose Configurations**
   - `docker-compose.mcp.yaml`: Full stack with Neo4j
   - `docker-compose.mcp-standalone.yaml`: MCP server only (connects to existing services)
   - Proper volume mounts for code analysis
   - Network integration with existing services

3. **MCP Server Catalog**
   - Created `docker-mcp-catalog.yaml` with all tool definitions
   - Documented 32 tools across 7 categories
   - Environment variable and secrets configuration

4. **Container Deployment**
   - Container `eib-mcp-rag` running and healthy
   - Connected to:
     - ChromaDB: via `host.docker.internal:8080` (systemd service)
     - Neo4j: via Docker network (`global-workflow-neo4j:7687`)
   - Mounted workspace for file analysis tools

### 🔧 Docker MCP CLI Plugin

- Successfully built from source (`github.com/docker/mcp-gateway`)
- Binary installed to `~/.docker/cli-plugins/docker-mcp`
- **Limitation**: Requires Docker Desktop with MCP Toolkit feature enabled
- **Server Environment**: Not available without Docker Desktop

## Current Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     Host System                               │
│  ┌────────────────────┐  ┌────────────────────┐              │
│  │ ChromaDB (systemd) │  │ LangFlow (Docker)  │              │
│  │ Port: 8080         │  │ Port: 7860         │              │
│  └────────────────────┘  └────────────────────┘              │
│                                                                │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │         Docker Network: global-workflow-mcp-rag         │ │
│  │  ┌──────────────────┐  ┌──────────────────┐             │ │
│  │  │ eib-mcp-rag      │  │ Neo4j            │             │ │
│  │  │ (MCP Server)     │──│ Port: 7687       │             │ │
│  │  │ stdio transport  │  │                  │             │ │
│  │  └──────────────────┘  └──────────────────┘             │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

## Usage

### Start the MCP RAG Server

```bash
# Using docker-compose (standalone mode - recommended)
cd /mcp_rag_eib/eib-mcp-rag-server
docker compose -f docker-compose.mcp-standalone.yaml up -d

# Verify container is running
docker ps | grep eib-mcp-rag

# Check logs
docker logs eib-mcp-rag

# Stop the container
docker compose -f docker-compose.mcp-standalone.yaml down
```

### Interact with MCP Server (Direct)

```bash
# Execute MCP server in stdio mode (manual testing)
docker exec -i eib-mcp-rag node src/UnifiedMCPServer.js core

# Test with a simple MCP request
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | \
  docker exec -i eib-mcp-rag node src/UnifiedMCPServer.js core

# Health check
docker exec eib-mcp-rag node -e "process.exit(0)"
```

### Environment Variables

The container respects these environment variables:

```bash
# Scenario selection
MCP_SCENARIO=full  # Options: full, core, rag, github

# Database connections
CHROMA_SERVER_URL=http://host.docker.internal:8080
NEO4J_URI=bolt://global-workflow-neo4j:7687
NEO4J_PASSWORD=gfsworkflow2025

# Repository paths
MCP_WORKFLOW_ROOT=/mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow
MCP_WORKSPACE_ROOT=/mcp_rag_eib/eib-mcp-rag-server
SDD_FRAMEWORK_ROOT=/mcp_rag_eib/eib-mcp-rag-server/sdd_framework

# Feature flags
ENABLE_RAG=true
ENABLE_GITHUB=true

# Secrets
GITHUB_TOKEN=<your-token>
```

## Limitations and Known Issues

### Docker Desktop Dependency

**Issue**: Docker MCP Gateway requires Docker Desktop with MCP Toolkit feature enabled.

**Impact**: Cannot use `docker mcp` commands in server/cloud environments.

**Workarounds**:

1. **Direct stdio Access**:
   ```bash
   # Connect directly via docker exec
   docker exec -i eib-mcp-rag node src/UnifiedMCPServer.js full < input.json
   ```

2. **HTTP Wrapper** (Future):
   - Create a simple HTTP/SSE server wrapper
   - Expose MCP protocol over HTTP
   - LangFlow can connect via HTTP instead of stdio

3. **VS Code MCP Integration** (Current Production):
   - Continue using `.mcp.json` configuration
   - MCP server runs natively (not in container)
   - No changes needed to current workflow

### ChromaDB API Version

ChromaDB v2 API is required. The container is configured for:
- `http://host.docker.internal:8080` (ChromaDB systemd service)
- Endpoints: `/api/v2/heartbeat`, `/api/v2/collections`

### File System Access

The container mounts the workspace as read-only:
- Code analysis tools can read files
- Cannot modify files from within container
- Use volume mounts for write operations if needed

## Alternative Architectures

### Option 1: MCP Server as Systemd Service (Current Production)

**Pros**:
- No Docker overhead
- Direct file system access
- Works with VS Code MCP integration
- Current `.mcp.json` configuration works

**Cons**:
- No isolation
- Manual dependency management
- Not portable

### Option 2: Docker Container with HTTP Wrapper

**Pros**:
- Container isolation
- Multi-client access (HTTP/SSE)
- Works without Docker Desktop

**Cons**:
- Requires custom HTTP server implementation
- Additional complexity
- Need to handle authentication

### Option 3: Docker Desktop + MCP Toolkit (Ideal)

**Pros**:
- Native Docker MCP Gateway support
- LangFlow integration out-of-the-box
- Tool catalog management
- OAuth support

**Cons**:
- Requires Docker Desktop (not available on servers)
- Only works on developer workstations

## Files Created

```
eib-mcp-rag-server/
├── mcp_server_node/
│   ├── Dockerfile                        # Production container image
│   ├── .dockerignore                     # Build context exclusions
│   └── docker-mcp-catalog.yaml           # MCP Gateway catalog entry
├── docker-compose.mcp.yaml               # Full stack (MCP + Neo4j)
├── docker-compose.mcp-standalone.yaml    # MCP only (recommended)
└── DOCKER_MCP_SETUP.md                   # This file
```

## Testing

### Verify Container Health

```bash
# Check container status
docker ps --filter name=eib-mcp-rag --format "{{.Status}}"

# Expected: Up X seconds (healthy)

# View EE2 compliance tools loading
docker logs eib-mcp-rag | grep "EE2"

# Expected: [OK] EE2ComplianceTools: Loaded Phase 2 config (6 anti-patterns)
```

### Test MCP Protocol

```bash
# List available tools
echo '{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/list"
}' | docker exec -i eib-mcp-rag node src/UnifiedMCPServer.js core | jq '.result.tools[].name'

# Expected output:
# get_workflow_structure
# get_system_configs
# describe_component
# ... (all 32 tools)
```

### Test Database Connectivity

```bash
# Test ChromaDB connection
docker exec eib-mcp-rag curl -f http://host.docker.internal:8080/api/v2/heartbeat

# Test Neo4j connection
docker exec eib-mcp-rag \
  node -e "import('neo4j-driver').then(m => {
    const driver = m.default.driver('bolt://global-workflow-neo4j:7687',
      m.default.auth.basic('neo4j', 'gfsworkflow2025'));
    driver.verifyConnectivity().then(() => console.log('OK')).catch(console.error);
  })"
```

## Next Steps

### Immediate: Document and Use Current Setup

1. Use dockerized MCP server for testing/development
2. Continue using native MCP server for VS Code integration
3. Document stdio-based LangFlow integration (if needed)

### Short-term: HTTP Wrapper Implementation

1. Create Express/Fastify HTTP server wrapper
2. Implement MCP protocol over HTTP/SSE
3. Deploy as separate service for LangFlow
4. Add authentication and rate limiting

### Long-term: Full Docker MCP Gateway (Desktop Only)

1. Test on Docker Desktop environment
2. Validate `docker mcp` commands
3. Configure LangFlow SSE integration
4. Document developer workstation setup

## Provisioning Script Integration

To be added to `SETUP/provision_mcp_rag_persistent.sh`:

```bash
# Phase 11: Docker MCP Server Setup
echo "[INFO] Setting up Docker MCP server..."

# Build MCP server image
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node
docker build -t eib-mcp-rag:latest .

# Start MCP server container
cd /mcp_rag_eib/eib-mcp-rag-server
docker compose -f docker-compose.mcp-standalone.yaml up -d

echo "[OK] Docker MCP server started"
echo "[INFO] Container: eib-mcp-rag"
echo "[INFO] Status: docker logs eib-mcp-rag"
```

## Troubleshooting

### Container Won't Start

```bash
# Check build logs
docker build -t eib-mcp-rag:test ./mcp_server_node

# Check for missing files
docker run --rm eib-mcp-rag:latest ls -la /app

# Verify environment
docker exec eib-mcp-rag env | grep MCP
```

### Can't Connect to ChromaDB

```bash
# Test from host
curl http://localhost:8080/api/v2/heartbeat

# Test from container
docker exec eib-mcp-rag curl http://host.docker.internal:8080/api/v2/heartbeat

# Check extra_hosts configuration
docker inspect eib-mcp-rag | jq '.[].HostConfig.ExtraHosts'
```

### Can't Connect to Neo4j

```bash
# Verify Neo4j is running
docker ps | grep neo4j

# Check network connection
docker exec eib-mcp-rag ping -c 3 global-workflow-neo4j

# Verify password
docker exec global-workflow-neo4j cypher-shell -u neo4j -p gfsworkflow2025 'RETURN 1'
```

## References

- [Docker MCP Gateway](https://github.com/docker/mcp-gateway)
- [MCP Specification](https://spec.modelcontextprotocol.io/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- Phase 11 SDD: `sdd_framework/workflows/phase11_docker_mcp_gateway_langflow.md`

## Conclusion

Phase 11 successfully containerized the MCP RAG server and created the infrastructure for Docker MCP Gateway integration. While the Gateway requires Docker Desktop (unavailable in server environments), the containerized server provides:

- ✅ Isolation and reproducibility
- ✅ Easy deployment and scaling
- ✅ Consistent environment across systems
- ✅ Foundation for future HTTP/SSE wrapper

The current setup enables continued development and testing while providing a clear migration path to full Docker MCP Gateway integration when Docker Desktop is available.
