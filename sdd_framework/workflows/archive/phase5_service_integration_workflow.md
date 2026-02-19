# Phase 5: MCP Service Integration

**Description**: Transition the Unified MCP Server from a local stdio-based CLI tool to a network-accessible service using HTTP/SSE transport. This enables external systems (like web UIs, other agents, or remote IDEs) to consume the MCP tools.

## Phase 1: Transport Layer Implementation

### Step 1: Create HTTP Server Wrapper
**Type**: code_generation
**Target**: mcp_server_node/src/mcp-server-http.js
**Description**: Create an Express.js server that wraps the UnifiedMCPServer. It must handle SSE connections on `/sse` and message posting on `/messages`.
**Content**:
```javascript
import express from 'express';
import { SSEServerTransport } from '@modelcontextprotocol/sdk/server/sse.js';
import { UnifiedMCPServer } from './UnifiedMCPServer.js';

const app = express();
const port = process.env.PORT || 3000;

// Initialize the main UnifiedMCPServer
const scenario = process.env.MCP_SCENARIO || 'full';
const config = UnifiedMCPServer.getConfiguration(scenario);
const unifiedServer = new UnifiedMCPServer(config);

// Store active transports
const transports = new Map();

async function startServer() {
  await unifiedServer.initialize();
  
  app.get('/sse', async (req, res) => {
    const transport = new SSEServerTransport('/messages', res);
    transports.set(transport.sessionId, transport);
    
    // Connect a new server instance for this session
    // Note: In a real implementation, we might need a factory pattern
    // to create lightweight session-specific handlers while sharing the heavy RAG tools
    await unifiedServer.server.connect(transport);
    
    res.on('close', () => {
      transports.delete(transport.sessionId);
    });
  });

  app.post('/messages', async (req, res) => {
    const sessionId = req.query.sessionId;
    const transport = transports.get(sessionId);
    if (!transport) return res.status(404).send('Session not found');
    await transport.handlePostMessage(req, res);
  });

  app.listen(port, () => {
    console.log(`[HTTP] MCP Server running on port ${port}`);
  });
}

startServer();
```

### Step 2: Update BaseServer for Transport Injection
**Type**: code_modification
**File**: mcp_server_node/src/core/BaseServer.js
**Action**: Modify the `start()` method to accept an optional `transport` argument. If provided, use it instead of creating a default `StdioServerTransport`.

### Step 3: Update UnifiedMCPServer for Initialization
**Type**: code_modification
**File**: mcp_server_node/src/UnifiedMCPServer.js
**Action**: Split the `start()` method into `initialize()` (loading tools/DBs) and `start()` (connecting transport). This allows the HTTP wrapper to initialize components once and then handle multiple connections.

## Phase 2: Containerization & Deployment

### Step 4: Create Dockerfile
**Type**: code_generation
**Target**: mcp_server_node/Dockerfile
**Description**: Create a Dockerfile to package the Node.js server.
**Content**:
```dockerfile
FROM node:18-slim
WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production
COPY . .
ENV PORT=3000
EXPOSE 3000
CMD ["node", "src/mcp-server-http.js"]
```

### Step 5: Create Systemd Service
**Type**: code_generation
**Target**: SETUP/mcp-http-service.service
**Description**: Create a systemd unit file for managing the HTTP server process on the host.

## Phase 3: Validation & Documentation

### Step 6: Validate SSE Endpoint
**Type**: command
**Command**: curl -N -H "Accept: text/event-stream" http://localhost:3000/sse
**Description**: Verify that the server accepts connections and streams events.

### Step 7: Update Architecture Documentation
**Type**: ingestion
**Target**: documentation
**Description**: Update the knowledge base with the new service architecture details.
