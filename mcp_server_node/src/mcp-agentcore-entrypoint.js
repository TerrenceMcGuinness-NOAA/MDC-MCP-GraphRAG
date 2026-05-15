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

// Shared data access — connect once, reuse across all requests
let sharedDataAccess = null;
let sharedGGSR = null;
let sharedRetrieval = null;
let httpServer = null;
let shuttingDown = false;

/**
 * Graceful shutdown — release all database connections before exit.
 *
 * Phase 56 fix: AgentCore microVMs receive SIGTERM when the idle timeout
 * fires (900s) or the runtime is stopped. Without this handler, the Node
 * process died without calling sharedDataAccess.close(), leaking Neptune
 * Bolt connections and OpenSearch HTTPS sockets. Over many cold-start /
 * reconnect cycles these accumulated toward the 1000-connection OpenSearch
 * cluster limit.
 *
 * We cap shutdown at 5s — AgentCore sends SIGKILL shortly after SIGTERM.
 */
async function gracefulShutdown(signal) {
  if (shuttingDown) return;
  shuttingDown = true;
  console.error(`[AgentCore] Received ${signal}, shutting down gracefully...`);

  const shutdownTimeout = setTimeout(() => {
    console.error('[AgentCore] [WARN] Shutdown timeout (5s) — forcing exit');
    process.exit(1);
  }, 5000);
  shutdownTimeout.unref();

  try {
    if (httpServer && httpServer.listening) {
      await new Promise((resolve) => httpServer.close(resolve));
      console.error('[AgentCore] [OK] HTTP server closed');
    }
    if (sharedDataAccess && typeof sharedDataAccess.close === 'function') {
      await sharedDataAccess.close();
      console.error('[AgentCore] [OK] Data access closed (Neptune + OpenSearch released)');
    }
  } catch (err) {
    console.error(`[AgentCore] [ERROR] Shutdown error: ${err.message}`);
  } finally {
    clearTimeout(shutdownTimeout);
    console.error('[AgentCore] Shutdown complete');
    process.exit(0);
  }
}

process.on('SIGTERM', () => gracefulShutdown('SIGTERM'));
process.on('SIGINT',  () => gracefulShutdown('SIGINT'));

const config = UnifiedMCPServer.getConfiguration(scenario);
console.error(`[AgentCore] Starting '${scenario}' on port ${PORT}`);

httpServer = createServer(async (req, res) => {
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

// Pre-warm database connections BEFORE accepting requests.
// On AgentCore microVMs, the first Neptune Bolt+SigV4 and OpenSearch HTTPS+SigV4
// connections take ~75s each. By awaiting them here, the cold-start cost moves to
// boot time rather than the first user query.
const initMcp = new UnifiedMCPServer(config);

async function prewarm() {
  const t0 = Date.now();
  try {
    await initMcp.dataAccess.connect();
    sharedDataAccess = initMcp.dataAccess;
    console.error(`[AgentCore] [OK] Data access connected (${Date.now() - t0}ms)`);

    // Pre-warm Neptune connection pool with a lightweight query
    if (sharedDataAccess.graphDB && sharedDataAccess.graphDB.query) {
      const tg = Date.now();
      try {
        await sharedDataAccess.graphDB.query('MATCH (n:File) RETURN count(n) AS c LIMIT 1');
        console.error(`[AgentCore] [OK] Neptune pre-warmed (${Date.now() - tg}ms)`);
      } catch (err) {
        console.error(`[AgentCore] [WARN] Neptune pre-warm: ${err.message}`);
      }
    }

    // Pre-warm OpenSearch connection with a lightweight query
    if (sharedDataAccess.vectorDB && sharedDataAccess.vectorDB.listCollections) {
      const tv = Date.now();
      try {
        await sharedDataAccess.vectorDB.listCollections();
        console.error(`[AgentCore] [OK] OpenSearch pre-warmed (${Date.now() - tv}ms)`);
      } catch (err) {
        console.error(`[AgentCore] [WARN] OpenSearch pre-warm: ${err.message}`);
      }
    }

    // Pre-warm embedding model (loads ONNX runtime + model weights into memory)
    if (sharedDataAccess.vectorDB && sharedDataAccess.vectorDB.generateEmbeddings) {
      const te = Date.now();
      try {
        await sharedDataAccess.vectorDB.generateEmbeddings('warmup');
        console.error(`[AgentCore] [OK] Embedding model pre-warmed (${Date.now() - te}ms)`);
      } catch (err) {
        console.error(`[AgentCore] [WARN] Embedding pre-warm: ${err.message}`);
      }
    }

    // Initialize GGSR
    if (sharedDataAccess.graphDB) {
      try {
        const { GGSRTraversalPrototypes } = await import('./graphrag/GGSRTraversalPrototypes.js');
        sharedGGSR = new GGSRTraversalPrototypes(sharedDataAccess.graphDB);
        const { GraphGuidedRetrieval } = await import('./graphrag/GraphGuidedRetrieval.js');
        sharedRetrieval = new GraphGuidedRetrieval({
          dataAccess: sharedDataAccess, ggsr: sharedGGSR,
          vectorDB: sharedDataAccess.vectorDB || null,
        });
        console.error(`[AgentCore] [OK] GGSR initialized`);
      } catch (err) {
        console.error(`[AgentCore] [WARN] GGSR: ${err.message}`);
      }
    }

    console.error(`[AgentCore] [OK] Pre-warm complete (${Date.now() - t0}ms total)`);
  } catch (err) {
    console.error(`[AgentCore] [ERROR] Pre-warm failed: ${err.message} — server will start anyway`);
  }
}

// Start listening FIRST so /ping responds within AgentCore's 120s init window,
// then pre-warm database connections in the background. Tools that arrive before
// pre-warm completes will connect on-demand (slower first call, but no init timeout).
httpServer.listen(PORT, '0.0.0.0', () => {
  console.error(`[AgentCore] Listening on http://0.0.0.0:${PORT}/mcp`);
  console.error(`[AgentCore] Health check: http://0.0.0.0:${PORT}/ping`);
  // Fire pre-warm in background — does not block request handling
  prewarm().catch((err) => {
    console.error(`[AgentCore] [WARN] Pre-warm failed (non-fatal): ${err.message}`);
  });
});
