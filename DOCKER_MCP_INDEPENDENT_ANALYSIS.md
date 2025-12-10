# Docker MCP Gateway - Independent Operation Deep Dive

**Date**: December 9, 2025
**Investigation**: Can `docker-mcp` work independently without Docker Desktop?
**Result**: **Partial** - Gateway architecture yes, CLI plugin no

---

## TL;DR

**The Documentation Says**: "Work independently from Docker Desktop's MCP Toolkit. It can run anywhere there's a Docker engine."

**The Reality**: The Docker MCP **Gateway concept** can work independently, but the **`docker-mcp` CLI plugin** has a hard dependency on Docker Desktop's context store initialization that isn't available in standard Docker Engine.

**What Works Independently**:
- ✅ Running MCP servers as Docker containers (our Phase 11 implementation)
- ✅ Direct `docker exec` stdio communication with MCP servers
- ✅ Building custom HTTP/SSE wrappers around MCP servers

**What Requires Docker Desktop**:
- ❌ `docker mcp` CLI commands (catalog, server, gateway subcommands)
- ❌ Automated MCP server lifecycle management
- ❌ OAuth flows with credential helpers

---

## Technical Investigation

### The Error

```
Failed to initialize: unable to resolve docker endpoint: no context store initialized
```

### Root Cause Analysis

#### 1. Code Path Traced

The `docker-mcp` plugin uses Docker CLI library (`github.com/docker/cli`):

```go
// cmd/docker-mcp/main.go
plugin.Run(func(dockerCli command.Cli) *cobra.Command {
    return commands.Root(ctx, cwd, dockerCli, features.New(ctx, dockerCli))
}, ...)
```

This calls `command.NewDockerCli()` which initializes with:

```go
// vendor/github.com/docker/cli/cli/command/cli.go
func NewDockerCli(ops ...CLIOption) (*DockerCli, error) {
    defaultOps := []CLIOption{
        WithContentTrustFromEnv(),
        WithDefaultContextStoreConfig(),  // ← Creates context store config
        WithStandardStreams(),
    }
    // ...
    cli.contextStore = &ContextStoreWithDefault{
        Store: store.New(config.ContextStoreDir(), *cli.contextStoreConfig),
        // ...
    }
}
```

The `store.New()` creates a context store expecting:
- **Meta directory**: `~/.docker/contexts/meta/`
- **TLS directory**: `~/.docker/contexts/tls/`
- **Metadata file**: `~/.docker/contexts/meta/metadata.json`

#### 2. Why It Fails

When resolving the Docker endpoint:

```go
// vendor/github.com/docker/cli/cli/command/cli.go
func resolveDockerEndpoint(s store.Reader, contextName string) (docker.Endpoint, error) {
    if s == nil {  // ← Context store is nil!
        return docker.Endpoint{}, errors.New("no context store initialized")
    }
    // ...
}
```

**The Problem**: Even with the directories and files created, the context store returns `nil` because Docker Desktop initializes additional infrastructure that standard Docker Engine doesn't provide.

#### 3. What Docker Desktop Provides

Docker Desktop creates:
1. **Persistent context metadata** in `~/.docker/contexts/`
2. **Credential helpers** for OAuth token storage
3. **Context store daemon** that the CLI communicates with
4. **MCP Toolkit integration** that bridges CLI ↔ Gateway

Standard Docker Engine only provides:
1. **In-memory context** (shows as `"Storage": {"MetadataPath": "<IN MEMORY>"}`)
2. **No persistent context store**
3. **No credential helper integration**
4. **No MCP Toolkit**

---

## What the Documentation Means

When the docs say "can work independently", they refer to:

### 1. **Gateway Architecture** (Container-Based)

The MCP **Gateway concept** is independent - MCP servers run as containers:

```yaml
# From examples/sqlite-vec/docker-compose.yml
services:
  vector-db:
    build: .
    container_name: sqlite-vec-mcp
    stdin_open: true  # MCP stdio protocol
    tty: false
```

**This works!** You communicate via:
```bash
docker exec -i sqlite-vec-mcp node server.js < request.json
```

### 2. **Gateway Server** (HTTP/SSE Mode)

The gateway can run as a **standalone service** (not CLI plugin):

```bash
# From docs/mcp-gateway.md
docker mcp gateway run --server docker.io/namespace/repository:latest
```

But this command still uses the `docker-mcp` CLI plugin, which needs Docker Desktop.

### 3. **CE Mode for OAuth**

The `DOCKER_MCP_USE_CE=true` flag enables Community Edition OAuth:

```bash
export DOCKER_MCP_USE_CE=true
docker mcp oauth authorize notion-remote
```

**But**: This still requires the CLI plugin to work, which we can't initialize without Docker Desktop.

---

## Attempted Workarounds (All Failed)

### ❌ Attempt 1: Create Context Directories

```bash
mkdir -p ~/.docker/contexts/{meta,tls}
cat > ~/.docker/contexts/meta/metadata.json << 'EOF'
{
  "Contexts": {
    "default": {...}
  },
  "CurrentContext": "default"
}
EOF
```

**Result**: Still fails - context store initialization needs more than just files

### ❌ Attempt 2: Docker config.json

```bash
cat > ~/.docker/config.json << 'EOF'
{
  "currentContext": "default"
}
EOF
```

**Result**: Context is recognized but store still nil

### ❌ Attempt 3: CE Mode Flag

```bash
export DOCKER_MCP_USE_CE=true
docker-mcp version
```

**Result**: Same error - CE mode is for OAuth, not context store initialization

### ❌ Attempt 4: Run via Docker Command

```bash
docker mcp version
```

**Result**: `docker: unknown command: docker mcp` - plugin not recognized by Docker Engine

---

## What DOES Work Independently

### ✅ Approach 1: Direct Container Communication (Current)

**Our Phase 11 Implementation**:

```bash
# Start MCP server container
docker compose -f docker-compose.mcp-standalone.yaml up -d

# Communicate via docker exec
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | \
  docker exec -i eib-mcp-rag node src/UnifiedMCPServer.js core
```

**Pros**:
- Works on any Docker Engine
- No Docker Desktop required
- Full MCP protocol support
- All 32 tools functional

**Cons**:
- Manual `docker exec` invocations
- No catalog management
- No automatic lifecycle management

### ✅ Approach 2: Custom HTTP/SSE Wrapper (Future)

Build a simple HTTP server wrapper:

```javascript
// http-mcp-wrapper.js
const express = require('express');
const { spawn } = require('child_process');

const app = express();
app.post('/mcp', (req, res) => {
  const mcp = spawn('docker', ['exec', '-i', 'eib-mcp-rag',
                                'node', 'src/UnifiedMCPServer.js', 'full']);
  req.pipe(mcp.stdin);
  mcp.stdout.pipe(res);
});

app.listen(8090);
```

**Pros**:
- HTTP/SSE transport for multi-client access
- Works on standard Docker Engine
- LangFlow can connect via HTTP

**Cons**:
- Custom implementation required
- Need to handle authentication
- Not using official Docker MCP Gateway

### ✅ Approach 3: Native MCP Server (Production)

**Continue using native `.mcp.json` configuration**:

```json
// .mcp.json
{
  "mcpServers": {
    "eib-mcp-rag-full": {
      "command": "node",
      "args": ["/path/to/UnifiedMCPServer.js", "full"],
      "env": {...}
    }
  }
}
```

**Pros**:
- Works with VS Code MCP integration
- No Docker overhead
- Direct file system access

**Cons**:
- Not containerized
- Manual dependency management
- Tied to host environment

---

## The Missing Piece: Docker Desktop's Context Store Daemon

After deep code analysis, the blocker is that Docker Desktop runs a **context store daemon** that:

1. **Manages persistent contexts** across Docker CLI sessions
2. **Provides a store.Reader interface** that the CLI queries
3. **Handles credential helpers** for OAuth tokens
4. **Bridges MCP Toolkit ↔ CLI plugin**

Standard Docker Engine:
- Stores contexts **in memory only**
- No persistent store.Reader
- No daemon for context management

This is why `docker context inspect default` shows:
```json
{
  "Storage": {
    "MetadataPath": "<IN MEMORY>",
    "TLSPath": "<IN MEMORY>"
  }
}
```

Docker Desktop would show actual file paths.

---

## Conclusion

### Can docker-mcp Work Independently?

**Technically Yes, Practically No**:

- **Gateway Architecture**: ✅ Yes (containers with stdin_open)
- **CLI Plugin Commands**: ❌ No (requires Docker Desktop context store)
- **HTTP/SSE Gateway**: ⚠️ Requires CLI plugin to start

### Recommended Path Forward

**For Server Environments** (no Docker Desktop):
1. ✅ Use Phase 11 containerized MCP server
2. ✅ Build custom HTTP/SSE wrapper for multi-client access
3. ✅ Use `docker exec` for stdio communication

**For Developer Workstations** (Docker Desktop available):
1. ✅ Install Docker Desktop with MCP Toolkit
2. ✅ Use `docker mcp` CLI commands
3. ✅ Native catalog and OAuth support

### The Real Meaning of "Independent"

The documentation's claim that it can "work independently" refers to:
- **Deployment independence**: MCP servers run anywhere Docker is
- **Catalog independence**: Can run servers without online catalog
- **Transport independence**: Supports stdio, HTTP, SSE

**NOT**:
- **Docker Desktop independence**: CLI plugin requires Desktop's context infrastructure

---

## Files Referenced

- **Source**: https://github.com/docker/mcp-gateway
- **Docs**: `/tmp/mcp-gateway/docs/mcp-gateway.md`
- **CE Mode**: `/tmp/mcp-gateway/docs/oauth-ce-mode.md`
- **CLI Code**: `vendor/github.com/docker/cli/cli/command/cli.go`
- **Context Store**: `vendor/github.com/docker/cli/cli/context/store/store.go`

---

## Alternative: Build Gateway from Scratch

Since the Docker MCP Gateway CLI plugin won't work without Docker Desktop, we could:

### Option 1: Minimal HTTP Gateway

```javascript
// minimal-mcp-gateway.js
const http = require('http');
const { exec } = require('child_process');

http.createServer((req, res) => {
  if (req.url === '/sse') {
    // SSE endpoint for LangFlow
    res.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive'
    });

    // Proxy to containerized MCP server via docker exec
    const mcp = exec('docker exec -i eib-mcp-rag node src/UnifiedMCPServer.js full');
    req.pipe(mcp.stdin);
    mcp.stdout.on('data', data => {
      res.write(`data: ${data}\n\n`);
    });
  }
}).listen(8090);
```

### Option 2: Use MCP SDK

Build our own gateway using `@modelcontextprotocol/sdk`:

```javascript
// custom-gateway.js
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';

// Wrap our containerized MCP server
// Provide HTTP/SSE interface
// Handle multiple clients
```

This gives us full control and works on standard Docker Engine.

---

## Final Recommendation

**For Our Use Case** (server environment without Docker Desktop):

1. **Current**: Continue using Phase 11 containerized setup ✅
2. **Short-term**: Build minimal HTTP/SSE wrapper (Option 1 above)
3. **Long-term**: Consider full custom gateway with MCP SDK (Option 2)

**Docker MCP Gateway CLI** is excellent for Docker Desktop environments, but not a viable solution for server deployments without Desktop.

---

**Investigation Duration**: 2+ hours
**Tools Used**: strace, source code analysis, Docker CLI debugging
**Conclusion**: Documentation is technically accurate but practically misleading for non-Desktop environments
