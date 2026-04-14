#!/usr/bin/env node
/**
 * MCP HTTP Server — Stateless Streamable HTTP transport.
 * Creates a fresh MCP Server + Transport per request (stateless mode).
 * Based on AWS AgentCore pattern: 0.0.0.0:PORT/mcp
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

import { createServer } from 'node:http';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { UnifiedMCPServer } from './UnifiedMCPServer.js';

const PORT = parseInt(process.argv[2]) || 3000;
const scenario = process.argv[3] || 'full';

process.on('unhandledRejection', (reason) => { console.error('[ERROR] Unhandled:', reason); });
process.on('uncaughtException', (error) => { console.error('[ERROR] Uncaught:', error); });

const config = UnifiedMCPServer.getConfiguration(scenario);
console.error(`[MCP-HTTP] Starting '${scenario}' on port ${PORT} (stateless mode)`);

// Shared data access — connect once, reuse across all requests
let sharedDataAccess = null;
let sharedGGSR = null;
let sharedRetrieval = null;

const httpServer = createServer(async (req, res) => {
  console.error(`[MCP-HTTP] ${req.method} ${req.url}`);

  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization, Mcp-Session-Id');
  res.setHeader('Access-Control-Expose-Headers', 'Mcp-Session-Id');

  if (req.method === 'OPTIONS') { res.writeHead(204); res.end(); return; }

  if (req.url === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'ok', tools: 51, dataAccess: !!sharedDataAccess }));
    return;
  }

  if (req.url === '/mcp' || req.url === '/mcp/') {
    // Stateless: fresh MCP instance + transport per request
    try {
      const mcp = new UnifiedMCPServer(config);

      // Inject shared data access if available
      if (sharedDataAccess) {
        mcp.dataAccess = sharedDataAccess;
        if (mcp.semanticSearchTools) { mcp.semanticSearchTools.dataAccess = sharedDataAccess; mcp.semanticSearchTools.isInitialized = true; }
        if (mcp.operationalTools) { mcp.operationalTools.dataAccess = sharedDataAccess; mcp.operationalTools.isInitialized = true; }
        if (mcp.codeAnalysisTools) { mcp.codeAnalysisTools.dataAccess = sharedDataAccess; mcp.codeAnalysisTools.isInitialized = true; }
        if (mcp.graphRAGTools) { mcp.graphRAGTools.dataAccess = sharedDataAccess; mcp.graphRAGTools.isInitialized = true; }
      }

      // Inject shared GGSR into per-request tool modules
      if (sharedGGSR) {
        if (mcp.codeAnalysisTools) { mcp.codeAnalysisTools.ggsr = sharedGGSR; mcp.codeAnalysisTools.retrieval = sharedRetrieval; }
        if (mcp.graphRAGTools) { mcp.graphRAGTools.ggsr = sharedGGSR; mcp.graphRAGTools.retrieval = sharedRetrieval; }
      }

      // Stateless transport — no session ID generator
      const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
      await mcp.server.server.connect(transport);
      await transport.handleRequest(req, res);
    } catch (err) {
      console.error(`[MCP-HTTP] Request error: ${err.message}`);
      if (!res.headersSent) {
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: err.message }));
      }
    }
    return;
  }

  res.writeHead(404);
  res.end(JSON.stringify({ error: 'Use /mcp or /health' }));
});

// Initialize shared data access in background
const initMcp = new UnifiedMCPServer(config);
initMcp.dataAccess.connect().then(async () => {
  sharedDataAccess = initMcp.dataAccess;
  console.error('[MCP-HTTP] [OK] Shared data access connected');
  if (sharedDataAccess.graphDB) {
    try {
      const { GGSRTraversalPrototypes } = await import('./graphrag/GGSRTraversalPrototypes.js');
      sharedGGSR = new GGSRTraversalPrototypes(sharedDataAccess.graphDB);
      const { GraphGuidedRetrieval } = await import('./graphrag/GraphGuidedRetrieval.js');
      sharedRetrieval = new GraphGuidedRetrieval({
        dataAccess: sharedDataAccess, ggsr: sharedGGSR,
        vectorDB: sharedDataAccess.vectorDB || null,
      });
      console.error('[MCP-HTTP] [OK] GGSR initialized');
    } catch (err) {
      console.error(`[MCP-HTTP] [WARN] GGSR: ${err.message}`);
    }
  }
}).catch(err => {
  console.error(`[MCP-HTTP] [ERROR] Data access: ${err.message}`);
});

httpServer.listen(PORT, '0.0.0.0', () => {
  console.error(`[MCP-HTTP] Listening on http://0.0.0.0:${PORT}/mcp`);
});
