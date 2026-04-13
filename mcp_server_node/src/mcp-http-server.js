#!/usr/bin/env node
/**
 * MCP HTTP Server — Runs UnifiedMCPServer with StreamableHTTP transport.
 * Creates a fresh MCP Server instance per session to avoid the
 * "already connected" limitation of the MCP SDK.
 *
 * Usage: node src/mcp-http-server.js [port] [scenario]
 * Connect Kiro: { "type": "http", "url": "http://localhost:3000/mcp" }
 */

import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const quietConsole = await import(join(__dirname, '../utils/quiet-console.js'));
quietConsole.enableQuietMode();

import crypto from 'node:crypto';
import { createServer } from 'node:http';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { UnifiedMCPServer } from './UnifiedMCPServer.js';

const PORT = parseInt(process.argv[2]) || 3000;
const scenario = process.argv[3] || 'full';

process.on('unhandledRejection', (reason) => { console.error('[ERROR] Unhandled:', reason); });
process.on('uncaughtException', (error) => { console.error('[ERROR] Uncaught:', error); });

const config = UnifiedMCPServer.getConfiguration(scenario);
console.error(`[MCP-HTTP] Starting '${scenario}' on port ${PORT}`);

// Shared data access — initialized once, shared across all sessions
let sharedDataAccess = null;

// Create a fresh MCP server instance with tools registered
function createMCPInstance() {
  const mcp = new UnifiedMCPServer(config);
  if (sharedDataAccess) {
    // Inject the already-connected data access
    mcp.dataAccess = sharedDataAccess;
    if (mcp.semanticSearchTools) {
      mcp.semanticSearchTools.dataAccess = sharedDataAccess;
      mcp.semanticSearchTools.isInitialized = true;
    }
    if (mcp.operationalTools) {
      mcp.operationalTools.dataAccess = sharedDataAccess;
      mcp.operationalTools.isInitialized = true;
    }
    if (mcp.codeAnalysisTools) {
      mcp.codeAnalysisTools.dataAccess = sharedDataAccess;
      mcp.codeAnalysisTools.isInitialized = true;
    }
    if (mcp.graphRAGTools) {
      mcp.graphRAGTools.dataAccess = sharedDataAccess;
      mcp.graphRAGTools.isInitialized = true;
    }
  }
  return mcp;
}

// Session management
const sessions = new Map();

const httpServer = createServer(async (req, res) => {
  // Log EVERY request for debugging
  console.error(`[MCP-HTTP] ${req.method} ${req.url} from=${req.socket.remoteAddress}`);

  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization, Mcp-Session-Id');
  res.setHeader('Access-Control-Expose-Headers', 'Mcp-Session-Id');

  if (req.method === 'OPTIONS') { res.writeHead(204); res.end(); return; }

  if (req.url === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    const toolCount = createMCPInstance().server?.tools?.size || 0;
    res.end(JSON.stringify({ status: 'ok', tools: toolCount, sessions: sessions.size, dataAccess: !!sharedDataAccess }));
    return;
  }

  if (req.url === '/mcp' || req.url === '/mcp/') {
    const sessionId = req.headers['mcp-session-id'];
    console.error(`[MCP-HTTP] ${req.method} /mcp session=${sessionId || 'none'} accept=${req.headers.accept || 'none'}`);

    // Existing session — route all methods to its transport
    if (sessionId && sessions.has(sessionId)) {
      console.error(`[MCP-HTTP] Routing to existing session ${sessionId}`);
      try {
        await sessions.get(sessionId).transport.handleRequest(req, res);
      } catch (err) {
        console.error(`[MCP-HTTP] Session error: ${err.message}`);
        if (!res.headersSent) { res.writeHead(500); res.end(JSON.stringify({ error: err.message })); }
      }
      return;
    }

    // GET without session — route to most recent session if one exists (SSE stream)
    if (req.method === 'GET' && sessions.size > 0) {
      const lastSession = [...sessions.values()].pop();
      console.error(`[MCP-HTTP] GET routed to last session`);
      try {
        await lastSession.transport.handleRequest(req, res);
      } catch (err) {
        console.error(`[MCP-HTTP] GET session error: ${err.message}`);
        if (!res.headersSent) { res.writeHead(500); res.end(JSON.stringify({ error: err.message })); }
      }
      return;
    }

    // GET without any session — no sessions exist yet
    if (req.method === 'GET') {
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'No active session. POST initialize first.' }));
      return;
    }

    // New connection — create fresh MCP instance + transport
    try {
      const mcp = createMCPInstance();
      const transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: () => crypto.randomUUID(),
      });

      await mcp.server.server.connect(transport);

      const sid = transport.sessionId;
      if (sid) {
        sessions.set(sid, { mcp, transport });
        console.error(`[MCP-HTTP] New session: ${sid} (${sessions.size} active)`);
      }

      transport.onclose = () => {
        if (sid) sessions.delete(sid);
        console.error(`[MCP-HTTP] Session closed: ${sid} (${sessions.size} active)`);
      };

      await transport.handleRequest(req, res);
    } catch (err) {
      console.error(`[MCP-HTTP] New session error: ${err.message}`);
      if (!res.headersSent) { res.writeHead(500); res.end(JSON.stringify({ error: err.message })); }
    }
    return;
  }

  res.writeHead(404);
  res.end(JSON.stringify({ error: 'Use /mcp or /health' }));
});

// Initialize shared data access in background
if (config.enableRAG) {
  const initMcp = new UnifiedMCPServer(config);
  initMcp.dataAccess.connect().then(async () => {
    sharedDataAccess = initMcp.dataAccess;
    console.error('[MCP-HTTP] [OK] Shared data access connected');
    if (sharedDataAccess.graphDB) {
      try {
        const { GGSRTraversalPrototypes } = await import('./graphrag/GGSRTraversalPrototypes.js');
        const ggsr = new GGSRTraversalPrototypes(sharedDataAccess.graphDB);
        sharedDataAccess._ggsr = ggsr;
        console.error('[MCP-HTTP] [OK] GGSR initialized');
      } catch (err) {
        console.error(`[MCP-HTTP] [WARN] GGSR: ${err.message}`);
      }
    }
  }).catch(err => {
    console.error(`[MCP-HTTP] [ERROR] Data access: ${err.message}`);
  });
}

httpServer.listen(PORT, '0.0.0.0', () => {
  console.error(`[MCP-HTTP] Listening on http://127.0.0.1:${PORT}/mcp`);
});
