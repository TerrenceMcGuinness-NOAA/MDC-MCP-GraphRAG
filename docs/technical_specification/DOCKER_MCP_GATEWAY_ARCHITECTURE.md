# Docker MCP Gateway Architecture

**Date**: December 29, 2025  
**Status**: Operational  
**Transport**: Streamable HTTP (upgraded from SSE)

## Overview

The **docker-mcp gateway** is a Docker CLI plugin that acts as an HTTP bridge to containerized MCP servers, enabling AI clients to communicate with MCP tools via standard HTTP rather than stdio.

## Architecture Diagram

```
┌────────────────────────────────────────────────────────────────┐
│  AI Clients (VS Code, LangFlow, Claude Desktop)                │
│                        │                                       │
│                        ▼ HTTP/Streaming                        │
│            ┌─────────────────────────────┐                     │
│            │ docker-mcp gateway          │ ← Port 18888        │
│            │ (PID 955735)                │                     │
│            │ --catalog eib-mcp-rag.yaml  │                     │
│            │ --transport streaming       │                     │
│            │ --long-lived                │                     │
│            └─────────────────────────────┘                     │
│                        │ spawns containers                     │
│           ┌────────────┴────────────┐                          │
│           ▼                         ▼                          │
│  ┌─────────────────┐      ┌─────────────────┐                  │
│  │ MCP Worker 1    │      │ MCP Worker 2    │  ← Auto-scaled   │
│  │ eib-mcp-rag     │      │ eib-mcp-rag     │                  │
│  └─────────────────┘      └─────────────────┘                  │
│           │                         │                          │
│           └─────────┬───────────────┘                          │
│                     ▼                                          │
│      ┌─────────────────────────────────────┐                   │
│      │ ChromaDB (8080) + Neo4j (7687)      │                   │
│      └─────────────────────────────────────┘                   │
└────────────────────────────────────────────────────────────────┘
```

## Transport Protocol History

| Version | Transport | Endpoint | Notes |
|---------|-----------|----------|-------|
| Phase 11 (Dec 17) | SSE | `/sse` | Server-Sent Events for LangFlow |
| Phase 19 (Dec 29) | Streaming HTTP | `/mcp` | MCP spec 2025-06-18 compliant |

### SSE vs Streaming HTTP

- **SSE (Server-Sent Events)**: Unidirectional server→client push. Required `/sse` endpoint.
- **Streaming HTTP**: Bidirectional, uses standard HTTP POST with streaming responses. Uses `/mcp` endpoint.

## Gateway Components

### 1. Gateway Process

```bash
/home/Terry.McGuinness/.docker/cli-plugins/docker-mcp gateway run \
  --catalog eib-mcp-rag.yaml \
  --servers eib-mcp-rag \
  --transport streaming \
  --port 18888 \
  --long-lived
```

| Flag | Purpose |
|------|---------|
| `--catalog` | YAML file defining server images and config |
| `--servers` | Which server(s) from catalog to expose |
| `--transport` | Protocol: `streaming` (HTTP) or `sse` |
| `--port` | HTTP port to listen on |
| `--long-lived` | Keep containers running between requests |

### 2. Catalog Configuration

Location: `~/.docker/mcp/catalogs/eib-mcp-rag.yaml`

```yaml
name: eib-mcp-rag-catalog
displayName: EIB MCP RAG Server

registry:
  eib-mcp-rag:
    description: "AI-powered MCP server with RAG for NOAA Global Workflow"
    image: "eib-mcp-rag:latest"
    
    env:
      - name: CHROMADB_URL
        value: "http://172.17.0.1:8080"
      - name: NEO4J_URI
        value: "bolt://172.17.0.1:7687"
      - name: MCP_WORKFLOW_ROOT
        value: "/app/supported_repos/global-workflow"
    
    volumes:
      - "/mcp_rag_eib/eib-mcp-rag-server/supported_repos:/app/supported_repos:ro"
      - "/mcp_rag_eib/eib-mcp-rag-server/sdd_framework:/app/sdd_framework:ro"
```

### 3. Worker Containers

The gateway spawns `eib-mcp-rag:latest` containers with:
- Resource limits: 1 CPU, 2GB memory
- Security: `--security-opt no-new-privileges`
- Labels: `docker-mcp=true`, `docker-mcp-name=eib-mcp-rag`

## Client Configuration

### VS Code (mcp.json)

```json
{
  "eib-mcp-gateway-direct": {
    "type": "http",
    "url": "http://44.200.110.34:18888/mcp",
    "headers": {
      "Authorization": "Bearer eib-mcp-gateway-token-2025"
    }
  },
  "eib-mcp-gateway-tunnel": {
    "type": "http", 
    "url": "http://localhost:18888/mcp",
    "headers": {
      "Authorization": "Bearer eib-mcp-gateway-token-2025"
    }
  }
}
```

### LangFlow

- **URL**: `http://host.docker.internal:18888/mcp`
- **Transport**: HTTP (was SSE)
- **Authorization**: `Bearer eib-mcp-gateway-token-2025`

## HTTP Endpoint Testing

**Tested**: December 29, 2025 ✅

### Important: Stateless Sessions

The gateway treats each HTTP request as a **new session**. This means:
- Each request triggers `initialize` → `initialized` → method internally
- No session cookies or persistent connection required
- Response format is SSE-style (`event:` + `data:` lines) even for HTTP transport

### Initialize (Required Headers)
```bash
curl -s -X POST http://localhost:18888/mcp \
  -H "Authorization: Bearer eib-mcp-gateway-token-2025" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}},"id":1}'
```

**Response** (verified working):
```
event: message
id: JNPVN7RX5QD5KNVPNZT26AEIA3_0
data: {"jsonrpc":"2.0","id":1,"result":{"capabilities":{"logging":{},...},"protocolVersion":"2025-06-18","serverInfo":{"name":"Docker AI MCP Gateway","version":"2.0.1"}}}
```

### Parse SSE Response
```bash
curl ... | grep -oP 'data: \K{.*}' | jq .
```

## Management Commands

### Start Gateway
```bash
docker mcp gateway run \
  --catalog eib-mcp-rag.yaml \
  --servers eib-mcp-rag \
  --transport streaming \
  --port 18888 \
  --long-lived &
```

### Stop Gateway
```bash
pkill -f "docker-mcp gateway"
docker stop $(docker ps -q --filter "label=docker-mcp-name=eib-mcp-rag")
```

### View Logs
```bash
# Gateway logs
journalctl -u docker-mcp-gateway  # if systemd

# Container logs
docker logs <container-name> --tail 50
```

### Cleanup Orphan Containers
```bash
docker ps --filter "label=docker-mcp=true" --format "{{.Names}}"
docker stop <container-name>
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Port already in use | `ss -tlnp \| grep 18888` then kill process |
| Container not connecting to DBs | Check `172.17.0.1` bridge IP accessibility |
| Authorization failed | Verify Bearer token matches catalog config |
| Tools not loading | Check container logs for startup errors |

## Security Notes

1. **Bearer Token**: Travels in plain text over HTTP. Use HTTPS proxy for production.
2. **SSH Tunnel**: More secure option - `ssh -L 18888:localhost:18888 server -N`
3. **Volume Mounts**: Read-only to prevent container from modifying host files.
4. **No scripts/ mount**: Tool internals baked into image, not exposed to external LLMs.
