# Docker MCP Gateway Multi-User Architecture Analysis

**Document Version**: 1.0  
**Date**: January 12, 2026  
**Author**: EIB MCP Team  
**Status**: Analysis Complete - Awaiting Implementation Decision

---

## Executive Summary

This document analyzes the Docker MCP Gateway architecture options for multi-user RDHPCS deployments where Subject Matter Expert (SME) developers access the MCP/RAG system via VS Code Remote Tunnels. After comprehensive investigation of the Docker MCP Gateway v0.35.0 source code, documentation, and design patterns, we present four architecture options with a recommended hybrid approach.

**Key Finding**: Container spawning per MCP session is the **intended design** of Docker MCP Gateway, not a bug. For multi-user VS Code scenarios, direct stdio connections provide better resource efficiency than gateway-mediated container spawning.

---

## Background

### Current Infrastructure

| Component | Status | Details |
|-----------|--------|---------|
| **MCP Server** | v7.1.1 | 35 tools, Node.js UnifiedMCPServer |
| **ChromaDB** | Healthy | 12 collections, 14,968 documents |
| **Neo4j** | Healthy | 2,744 files, 86,189 relationships |
| **Docker MCP Gateway** | v0.35.0 | Streamable HTTP transport, port 18888 |
| **Target Users** | 5-10 | SME developers via VS Code tunnels |

### Observed Issue

During production use, we observed container accumulation:

```
docker ps --filter "label=docker-mcp=true"
NAMES                STATUS
practical_golick     Up 12 minutes (healthy)   # Gateway-spawned
relaxed_mendeleev    Up 38 minutes (healthy)   # Gateway-spawned
stoic_grothendieck   Up 2 days (healthy)       # Gateway-spawned
eib-mcp-rag-static   Up 3 days (healthy)       # Systemd-managed
```

Each gateway-spawned container consumes 2GB memory, leading to resource exhaustion with multiple concurrent users.

---

## Root Cause Analysis

### Docker MCP Gateway Design Philosophy

From `mcp-gateway/pkg/gateway/clientpool.go`:

```go
// Default behavior: spawn container per session
client = mcpclient.NewStdioCmdClient(cg.serverConfig.Name, "docker", env, runArgs...)

// With --long-lived: containers persist for gateway lifetime
return serverConfig.Spec.LongLived || cp.LongLived

// With --static: connect to pre-existing container via TCP
client = mcpclient.NewStdioCmdClient(cg.serverConfig.Name, "socat", nil, 
    "STDIO", fmt.Sprintf("TCP:mcp-%s:4444", cg.serverConfig.Name))
```

### Mode Comparison

| Mode | Container Lifecycle | Connection Method | Cleanup |
|------|---------------------|-------------------|---------|
| **Default** | Per tool call | `docker run` | Immediate |
| **--long-lived** | Per gateway session | `docker run` | Gateway stop |
| **--static** | Pre-started | `socat TCP:4444` | Manual |
| **type: remote** | External | HTTP/SSE | N/A |

### Why --static Didn't Work

Our attempt to use `--static` mode failed because:

1. Static mode expects container named `mcp-{server-name}` (e.g., `mcp-eib-mcp-rag`)
2. Container must run `docker-mcp-bridge` entrypoint
3. Bridge listens on TCP port 4444
4. Gateway connects via `socat STDIO TCP:mcp-{name}:4444`

Our container uses native stdio transport, not the TCP bridge.

---

## Architecture Options

### Option A: `type: remote` - Gateway Proxies to HTTP Server

**How it works:**
```yaml
# ~/.docker/mcp/catalogs/eib-local.yaml
registry:
  eib-mcp-rag:
    name: eib-mcp-rag
    type: remote                    # No container spawning
    remote:
      transport_type: streaming
      url: http://localhost:3000    # Pre-existing HTTP server
    title: EIB MCP RAG Server
```

**Implementation Requirements:**
- Add HTTP/Streaming transport to `UnifiedMCPServer.js`
- Run MCP server as systemd service on port 3000
- Gateway proxies all requests to single server

**Pros:**
- ✅ Single persistent server process
- ✅ No container spawning or lifecycle issues
- ✅ Remote clients automatically long-lived (v0.35.0 feature)
- ✅ Aligns with Docker's design for remote servers

**Cons:**
- ❌ Requires code changes to add HTTP transport
- ❌ Single point of failure (no container isolation)

**Estimated Effort:** 4-6 hours to add HTTP transport

---

### Option B: Accept Default Behavior + Cleanup

**How it works:**
```bash
# Keep current configuration
docker mcp gateway run --servers eib-mcp-rag --transport streaming \
    --port 18888 --long-lived

# Add cleanup cron (every hour)
0 * * * * docker ps -q --filter "label=docker-mcp=true" \
    --filter "status=exited" | xargs -r docker rm
```

**Pros:**
- ✅ Works immediately without changes
- ✅ Standard Docker MCP Gateway behavior
- ✅ Session isolation

**Cons:**
- ❌ 2GB memory per container × concurrent sessions
- ❌ Cleanup is reactive, not proactive
- ❌ Poor scalability for 5-10 users

**Estimated Effort:** 30 minutes (add cron job)

---

### Option C: Direct stdio (Skip Gateway for VS Code)

**How it works:**
```json
// .vscode/mcp.json
{
  "eib-mcp-rag-full": {
    "type": "stdio",
    "command": "node",
    "args": ["mcp_server_node/src/UnifiedMCPServer.js", "full"],
    "env": {
      "CHROMADB_HOST": "localhost",
      "CHROMADB_PORT": "8080",
      "NEO4J_URI": "bolt://localhost:7687"
    }
  }
}
```

**Pros:**
- ✅ No containers - direct Node.js process (~200MB vs 2GB)
- ✅ Already working (current `eib-mcp-rag-full` configuration)
- ✅ Lightweight per-session processes
- ✅ Shared databases (ChromaDB/Neo4j external)

**Cons:**
- ❌ No HTTP access for n8n/external clients
- ❌ No gateway security features
- ❌ Each session spawns Node.js process

**Estimated Effort:** None (already implemented)

---

### Option D: Hybrid Architecture (Recommended)

**How it works:**

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     Multi-User MCP Architecture                          │
│                                                                          │
│   VS Code Sessions (SME Developers via Tunnels)                         │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐                             │
│   │ Dev A    │  │ Dev B    │  │ Dev C    │                             │
│   │ (Tunnel) │  │ (Tunnel) │  │ (Tunnel) │                             │
│   └────┬─────┘  └────┬─────┘  └────┬─────┘                             │
│        │             │             │                                     │
│        └─────────────┼─────────────┘                                     │
│                      │                                                   │
│                      ▼                                                   │
│        ┌─────────────────────────────┐                                  │
│        │    Direct stdio (mcp.json)  │  ~200MB per session              │
│        │  node UnifiedMCPServer.js   │  Lightweight, fast               │
│        └─────────────┬───────────────┘                                  │
│                      │                                                   │
│   ════════════════════════════════════════════════════════════════════  │
│                      │                                                   │
│   External Clients (n8n, Claude Desktop, API)                           │
│   ┌──────────┐  ┌──────────┐                                           │
│   │   n8n    │  │  Claude  │                                           │
│   │  (5678)  │  │ Desktop  │                                           │
│   └────┬─────┘  └────┬─────┘                                           │
│        │             │                                                   │
│        └──────┬──────┘                                                   │
│               ▼                                                          │
│   ┌───────────────────────────────┐                                     │
│   │   Docker MCP Gateway (:18888) │                                     │
│   │   type: remote                │                                     │
│   └───────────────┬───────────────┘                                     │
│                   │                                                      │
│                   ▼                                                      │
│   ┌───────────────────────────────┐                                     │
│   │   HTTP MCP Server (:3000)     │  Single persistent server           │
│   │   UnifiedMCPServer.js         │  systemd managed                    │
│   └───────────────┬───────────────┘                                     │
│                   │                                                      │
│         ┌─────────┴─────────┐                                           │
│         ▼                   ▼                                           │
│   ┌──────────┐       ┌──────────┐                                       │
│   │ ChromaDB │       │  Neo4j   │                                       │
│   │  :8080   │       │  :7687   │                                       │
│   └──────────┘       └──────────┘                                       │
│                                                                          │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │              supported_repos/global-workflow                     │   │
│   │          (Git submodule - GFS/GEFS operational code)            │   │
│   └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

**Pros:**
- ✅ VS Code gets fast, lightweight connections (stdio)
- ✅ External clients get gateway features (HTTP)
- ✅ Single HTTP server handles all gateway requests
- ✅ No container spawning for either path
- ✅ Databases shared across all access methods

**Cons:**
- ❌ Requires adding HTTP transport to server
- ❌ Two code paths (stdio + HTTP)

**Estimated Effort:** 4-6 hours

---

## Recommendation

### Phased Implementation Plan

#### Phase 1: Immediate (Today)
**Use direct stdio for VS Code sessions**

1. Disable gateway service:
   ```bash
   sudo systemctl stop mcp-gateway
   sudo systemctl disable mcp-gateway
   ```

2. Clean up accumulated containers:
   ```bash
   docker ps -q --filter "label=docker-mcp=true" | xargs -r docker stop
   docker ps -aq --filter "label=docker-mcp=true" | xargs -r docker rm
   ```

3. Verify VS Code mcp.json uses `eib-mcp-rag-full` (stdio):
   ```json
   {
     "eib-mcp-rag-full": {
       "type": "stdio",
       "command": "node",
       "args": ["mcp_server_node/src/UnifiedMCPServer.js", "full"]
     }
   }
   ```

**Outcome:** Each developer's VS Code spawns lightweight Node.js process (~200MB)

#### Phase 2: Near-term (This Week)
**Add HTTP/Streaming transport to UnifiedMCPServer.js**

1. Implement MCP HTTP transport handler
2. Add `--transport http --port 3000` CLI option
3. Create systemd service for HTTP MCP server
4. Update gateway catalog to `type: remote`

#### Phase 3: Complete (Next Week)
**Full hybrid architecture operational**

- VS Code → stdio (direct)
- External → gateway → HTTP server
- Single codebase, two transport modes

---

## Technical References

### Docker MCP Gateway Documentation

| Document | Purpose |
|----------|---------|
| [mcp-gateway.md](https://github.com/docker/mcp-gateway/blob/main/docs/mcp-gateway.md) | Gateway usage guide |
| [server-entry-spec.md](https://github.com/docker/mcp-gateway/blob/main/docs/server-entry-spec.md) | Catalog entry specification |
| [examples/compose-static](https://github.com/docker/mcp-gateway/tree/main/examples/compose-static) | Static mode example |
| [profiles.md](https://github.com/docker/mcp-gateway/blob/main/docs/profiles.md) | v0.35.0 profiles feature |

### Key Source Files

| File | Relevance |
|------|-----------|
| `pkg/gateway/clientpool.go` | Container lifecycle management |
| `pkg/gateway/run.go` | Static mode implementation |
| `pkg/catalog/types.go` | `IsRemote()` helper for remote servers |

### Version Information

- **docker-mcp plugin**: v0.35.0 (built from source January 12, 2026)
- **Key commit**: `26d13965` - "Remote Clients should be long-lived"
- **Repository**: https://github.com/docker/mcp-gateway

---

## Appendix: Server Entry Types

### Type: server (Default)
```yaml
name: my-mcp
type: server
image: my-org/my-mcp:latest
# Gateway spawns container per session
```

### Type: remote (Recommended for Multi-User)
```yaml
name: my-mcp
type: remote
remote:
  transport_type: streaming
  url: http://localhost:3000
# Gateway proxies to existing HTTP server
```

### Type: poci (Per-Invocation)
```yaml
name: my-tool
type: poci
tools:
  - name: my-tool
    container:
      image: alpine:latest
# Gateway spawns container per tool call
```

---

## Change Log

| Date | Version | Change |
|------|---------|--------|
| 2026-01-12 | 1.0 | Initial analysis and recommendations |

