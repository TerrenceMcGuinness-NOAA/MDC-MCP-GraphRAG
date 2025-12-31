#!/usr/bin/env node
/**
 * Smoke test for Docker MCP Gateway (HTTP streaming /mcp).
 *
 * - Sends JSON-RPC requests to the gateway endpoint
 * - Parses "SSE-style" framed responses (event:/id:/data:)
 * - Demonstrates request correlation, timeouts, and cancellation
 */

const DEFAULT_URL = process.env.MCP_GATEWAY_URL || 'http://localhost:18888/mcp';
const DEFAULT_TOKEN = process.env.MCP_GATEWAY_AUTH_TOKEN || '';
const DEFAULT_PROTOCOL_VERSION = process.env.MCP_PROTOCOL_VERSION || '2025-06-18';

function parseArgs(argv) {
  const args = argv.slice(2);
  const config = {
    url: DEFAULT_URL,
    token: DEFAULT_TOKEN,
    protocolVersion: DEFAULT_PROTOCOL_VERSION,
    timeoutMs: 15000,
    cancelAfterMs: 0,
    verbose: false,
    dryRun: false
  };

  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    const next = args[i + 1];

    if (a === '--url' && next) {
      config.url = next;
      i++;
    } else if (a === '--token' && next) {
      config.token = next;
      i++;
    } else if (a === '--protocol-version' && next) {
      config.protocolVersion = next;
      i++;
    } else if (a === '--timeout-ms' && next) {
      config.timeoutMs = Number.parseInt(next, 10);
      i++;
    } else if (a === '--cancel-after-ms' && next) {
      config.cancelAfterMs = Number.parseInt(next, 10);
      i++;
    } else if (a === '--verbose') {
      config.verbose = true;
    } else if (a === '--dry-run') {
      config.dryRun = true;
    } else if (a === '--help' || a === '-h') {
      config.help = true;
    }
  }

  return config;
}

function printHelp() {
  console.log(`Usage: node scripts/test-gateway-mcp-streaming.js [options]

Options:
  --url URL                 Gateway URL (default: ${DEFAULT_URL})
  --token TOKEN             Bearer token (or env MCP_GATEWAY_AUTH_TOKEN)
  --protocol-version VER    MCP protocol version (default: ${DEFAULT_PROTOCOL_VERSION})
  --timeout-ms N            Request timeout (default: 15000)
  --cancel-after-ms N       Abort request after N ms (default: 0 = disabled)
  --verbose                 Print raw response payload
  --dry-run                 Print equivalent curl commands and exit
  -h, --help                Show help

Env:
  MCP_GATEWAY_URL
  MCP_GATEWAY_AUTH_TOKEN
  MCP_PROTOCOL_VERSION
`);
}

function parseSseFramedText(text) {
  const events = [];
  let current = { event: null, id: null, dataLines: [] };

  const lines = text.split(/\r?\n/);
  for (const line of lines) {
    if (line === '') {
      if (current.event || current.id || current.dataLines.length) {
        events.push({
          event: current.event,
          id: current.id,
          data: current.dataLines.join('\n')
        });
      }
      current = { event: null, id: null, dataLines: [] };
      continue;
    }

    if (line.startsWith('event:')) {
      current.event = line.slice('event:'.length).trim();
    } else if (line.startsWith('id:')) {
      current.id = line.slice('id:'.length).trim();
    } else if (line.startsWith('data:')) {
      current.dataLines.push(line.slice('data:'.length).trimStart());
    }
  }

  if (current.event || current.id || current.dataLines.length) {
    events.push({
      event: current.event,
      id: current.id,
      data: current.dataLines.join('\n')
    });
  }

  return events;
}

function extractJsonFromGatewayResponse(rawText) {
  const trimmed = rawText.trim();
  if (!trimmed) {
    throw new Error('Empty response body');
  }

  // Some implementations may return pure JSON.
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    const parsed = JSON.parse(trimmed);
    const messages = Array.isArray(parsed) ? parsed : [parsed];
    return { messages, sessionId: null, framed: false };
  }

  // Otherwise, treat as SSE-framed text.
  const events = parseSseFramedText(rawText);
  const withData = events.filter(e => e.data && e.data.trim());
  if (withData.length === 0) {
    throw new Error('No SSE data: payload found in response');
  }

  const messages = withData.map(e => JSON.parse(e.data));
  const sessionId = withData[withData.length - 1].id || null;
  return { messages, sessionId, framed: true };
}

function buildCurl(url, token, payload) {
  const body = JSON.stringify(payload).replace(/'/g, `'"'"'`);
  return [
    'curl -s -X POST ' + JSON.stringify(url),
    '-H ' + JSON.stringify(`Authorization: Bearer ${token}`),
    '-H ' + JSON.stringify('Content-Type: application/json'),
    '-H ' + JSON.stringify('Accept: application/json, text/event-stream'),
    `-d '${body}'`
  ].join(' \\\n  ');
}

async function postJsonRpc({ url, token, payload, timeoutMs, cancelAfterMs, verbose }) {
  const controller = new AbortController();

  const timeoutHandle = setTimeout(() => {
    controller.abort(new Error(`Timeout after ${timeoutMs}ms`));
  }, timeoutMs);

  let cancelHandle = null;
  if (cancelAfterMs && cancelAfterMs > 0) {
    cancelHandle = setTimeout(() => {
      controller.abort(new Error(`Cancelled after ${cancelAfterMs}ms`));
    }, cancelAfterMs);
  }

  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
        Accept: 'application/json, text/event-stream'
      },
      body: JSON.stringify(payload),
      signal: controller.signal
    });

    const text = await res.text();

    if (!res.ok) {
      const suffix = text ? `\n${text}` : '';
      throw new Error(`HTTP ${res.status} ${res.statusText}${suffix}`);
    }

    if (verbose) {
      console.log('[DEBUG] Raw response:');
      console.log(text);
    }

    return extractJsonFromGatewayResponse(text);
  } finally {
    clearTimeout(timeoutHandle);
    if (cancelHandle) clearTimeout(cancelHandle);
  }
}

async function main() {
  const config = parseArgs(process.argv);
  if (config.help) {
    printHelp();
    return 0;
  }

  if (!config.token) {
    console.error('[ERROR] Missing bearer token. Set MCP_GATEWAY_AUTH_TOKEN or pass --token.');
    return 2;
  }

  const initializePayload = {
    jsonrpc: '2.0',
    id: 1,
    method: 'initialize',
    params: {
      protocolVersion: config.protocolVersion,
      capabilities: {},
      clientInfo: { name: 'gateway-smoke-test', version: '1.0.0' }
    }
  };

  const initializedNotification = {
    jsonrpc: '2.0',
    method: 'notifications/initialized',
    params: {}
  };

  const toolsListPayload = {
    jsonrpc: '2.0',
    id: 2,
    method: 'tools/list',
    params: {}
  };

  // The Docker MCP Gateway enforces MCP initialization ordering. For HTTP tests,
  // batch `initialize` + `notifications/initialized` + the method into one request.
  const batchPayload = [initializePayload, initializedNotification, toolsListPayload];

  if (config.dryRun) {
    console.log('# Initialize');
    console.log(buildCurl(config.url, config.token, initializePayload));
    console.log('\n# initialize + initialized + tools/list (recommended)');
    console.log(buildCurl(config.url, config.token, batchPayload));
    console.log('\n# tools/list');
    console.log(buildCurl(config.url, config.token, toolsListPayload));
    return 0;
  }

  // Request correlation demo: fixed IDs 1 and 2, validated in responses.
  const batch = await postJsonRpc({
    url: config.url,
    token: config.token,
    payload: batchPayload,
    timeoutMs: config.timeoutMs,
    cancelAfterMs: config.cancelAfterMs,
    verbose: config.verbose
  });

  const initResp = batch.messages.find(m => m && m.id === 1) || null;
  const toolsResp = batch.messages.find(m => m && m.id === 2) || null;

  if (!initResp) {
    throw new Error('Missing initialize response (id=1) in batch');
  }
  if (initResp.error) {
    throw new Error(`initialize error: ${JSON.stringify(initResp.error)}`);
  }

  const serverName = initResp?.result?.serverInfo?.name || 'unknown';
  const serverVersion = initResp?.result?.serverInfo?.version || 'unknown';
  const negotiatedProto = initResp?.result?.protocolVersion || 'unknown';

  console.log(`[OK] initialize: server=${serverName} version=${serverVersion} protocol=${negotiatedProto}`);
  if (batch.sessionId) {
    console.log(`[OK] session: ${batch.sessionId}`);
  }

  if (!toolsResp) {
    throw new Error('Missing tools/list response (id=2) in batch');
  }
  if (toolsResp.error) {
    throw new Error(`tools/list error: ${JSON.stringify(toolsResp.error)}`);
  }

  const toolCount = Array.isArray(toolsResp?.result?.tools) ? toolsResp.result.tools.length : null;
  if (toolCount === null) {
    throw new Error('tools/list returned no tools array');
  }

  console.log(`[OK] tools/list: ${toolCount} tools`);
  return 0;
}

main().then(
  code => process.exit(code),
  err => {
    const msg = err && err.stack ? err.stack : String(err);
    console.error(`[ERROR] ${msg}`);
    process.exit(1);
  }
);
