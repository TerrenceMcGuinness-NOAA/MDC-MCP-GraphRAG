#!/usr/bin/env node
/**
 * MCP AgentCore Entrypoint — Bedrock AgentCore Runtime adapter.
 *
 * Starts a Streamable HTTP MCP server on 0.0.0.0:8000/mcp (AgentCore convention)
 * with a /ping health endpoint returning {"status":"Healthy"}.
 *
 * Based on mcp-http-server.js but adapted for AgentCore Runtime requirements:
 *   - Port 8000 (AgentCore MCP protocol default)
 *   - /ping health check (AgentCore liveness probe)
 *   - Shared data access across stateless requests
 *
 * Usage (container): CMD ["node", "src/mcp-agentcore-entrypoint.js"]
 * Usage (local):     node src/mcp-agentcore-entrypoint.js [port]
 */

import { createServer } from 'node:http';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { UnifiedMCPServer } from './UnifiedMCPServer.js';

const PORT = parseInt(process.env.MCP_PORT || process.argv[2]) || 8000;
const scenario = process.env.MCP_SCENARIO || 'full';

process.on('unhandledRejection', (reason) => { console.error('[ERROR] Unhandled:', reason); });
process.on('uncaughtException', (error) => { console.error('[ERROR] Uncaught:', error); });

const config = UnifiedMCPServer.getConfiguration(scenario);
console.error(`[AgentCore] Starting '${scenario}' on port ${PORT}`);

// Shared data access — connect once, reuse across all requests
let sharedDataAccess = null;
let sharedGGSR = null;
let sharedRetrieval = null;

const httpServer = createServer(async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization, Mcp-Session-Id');
  res.setHeader('Access-Control-Expose-Headers', 'Mcp-Session-Id');

  if (req.method === 'OPTIONS') { res.writeHead(204); res.end(); return; }

  // AgentCore health probe
  if (req.url === '/ping') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'Healthy' }));
    return;
  }

  if (req.url === '/mcp' || req.url === '/mcp/') {
    try {
      const mcp = new UnifiedMCPServer(config);

      // Inject shared data access if available
      if (sharedDataAccess) {
        mcp.dataAccess = sharedDataAccess;
        for (const mod of ['semanticSearchTools', 'operationalTools', 'codeAnalysisTools', 'graphRAGTools']) {
          if (mcp[mod]) { mcp[mod].dataAccess = sharedDataAccess; mcp[mod].isInitialized = true; }
        }
      }

      // Inject shared GGSR
      if (sharedGGSR) {
        for (const mod of ['codeAnalysisTools', 'graphRAGTools']) {
          if (mcp[mod]) { mcp[mod].ggsr = sharedGGSR; mcp[mod].retrieval = sharedRetrieval; }
        }
      }

      const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
      await mcp.server.server.connect(transport);
      await transport.handleRequest(req, res);
    } catch (err) {
      console.error(`[AgentCore] Request error: ${err.message}`);
      if (!res.headersSent) {
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: err.message }));
      }
    }
    return;
  }

  res.writeHead(404);
  res.end(JSON.stringify({ error: 'Use /mcp or /ping' }));
});

// Initialize shared data access in background
const initMcp = new UnifiedMCPServer(config);
initMcp.dataAccess.connect().then(async () => {
  sharedDataAccess = initMcp.dataAccess;
  console.error('[AgentCore] [OK] Shared data access connected');
  if (sharedDataAccess.graphDB) {
    try {
      const { GGSRTraversalPrototypes } = await import('./graphrag/GGSRTraversalPrototypes.js');
      sharedGGSR = new GGSRTraversalPrototypes(sharedDataAccess.graphDB);
      const { GraphGuidedRetrieval } = await import('./graphrag/GraphGuidedRetrieval.js');
      sharedRetrieval = new GraphGuidedRetrieval({
        dataAccess: sharedDataAccess, ggsr: sharedGGSR,
        vectorDB: sharedDataAccess.vectorDB || null,
      });
      console.error('[AgentCore] [OK] GGSR initialized');
    } catch (err) {
      console.error(`[AgentCore] [WARN] GGSR: ${err.message}`);
    }
  }
}).catch(err => {
  console.error(`[AgentCore] [ERROR] Data access: ${err.message}`);
});

httpServer.listen(PORT, '0.0.0.0', () => {
  console.error(`[AgentCore] Listening on http://0.0.0.0:${PORT}/mcp`);
  console.error(`[AgentCore] Health check: http://0.0.0.0:${PORT}/ping`);
});
