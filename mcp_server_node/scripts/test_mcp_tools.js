#!/usr/bin/env node
/**
 * MCP Tools Test Script (via Docker MCP Gateway)
 *
 * Runs a small set of tool checks through the gateway HTTP endpoint (`/mcp`).
 * The gateway enforces MCP init ordering, so each request is sent as a JSON-RPC
 * batch: initialize -> notifications/initialized -> tools/call
 */

const DEFAULT_URL = process.env.MCP_GATEWAY_URL || 'http://localhost:18888/mcp';
const DEFAULT_TOKEN = process.env.MCP_GATEWAY_AUTH_TOKEN || '';
const DEFAULT_PROTOCOL_VERSION = process.env.MCP_PROTOCOL_VERSION || '2025-06-18';

const TEST_TIMEOUT_MS = Number.parseInt(process.env.MCP_GATEWAY_TEST_TIMEOUT_MS || '30000', 10);

const TESTS = [
    {
        name: 'get_workflow_structure',
        tool: 'get_workflow_structure',
        args: {},
        expected: 'jobs'
    },
    {
        name: 'list_job_scripts',
        tool: 'list_job_scripts',
        args: { category: 'all', format: 'summary' },
        expected: 'JGLOBAL'
    },
    {
        name: 'get_system_configs',
        tool: 'get_system_configs',
        args: { platform: 'hera', config_type: 'all' },
        expected: 'hera'
    }
];

function parseArgs(argv) {
    const args = argv.slice(2);
    const config = {
        url: DEFAULT_URL,
        token: DEFAULT_TOKEN,
        protocolVersion: DEFAULT_PROTOCOL_VERSION,
        timeoutMs: TEST_TIMEOUT_MS,
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
    console.log(`Usage: node scripts/test_mcp_tools.js [options]

Options:
    --url URL                 Gateway URL (default: ${DEFAULT_URL})
    --token TOKEN             Bearer token (or env MCP_GATEWAY_AUTH_TOKEN)
    --protocol-version VER    MCP protocol version (default: ${DEFAULT_PROTOCOL_VERSION})
    --timeout-ms N            Request timeout (default: ${TEST_TIMEOUT_MS})
    --verbose                 Print raw response payload
    --dry-run                 Print a sample curl for one test and exit
    -h, --help                Show help

Env:
    MCP_GATEWAY_URL
    MCP_GATEWAY_AUTH_TOKEN
    MCP_PROTOCOL_VERSION
    MCP_GATEWAY_TEST_TIMEOUT_MS
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

function extractMessagesFromGatewayResponse(rawText) {
    const trimmed = rawText.trim();
    if (!trimmed) throw new Error('Empty response body');

    // Some implementations may return pure JSON.
    if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
        const parsed = JSON.parse(trimmed);
        const messages = Array.isArray(parsed) ? parsed : [parsed];
        return { messages, sessionId: null, framed: false };
    }

    // Otherwise, treat as SSE-framed text.
    const events = parseSseFramedText(rawText).filter(e => e.data && e.data.trim());
    if (events.length === 0) throw new Error('No SSE data: payload found in response');

    const messages = events.map(e => JSON.parse(e.data));
    const sessionId = events[events.length - 1].id || null;
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
    ].join(' \\\n+  ');
}

async function postJsonRpc({ url, token, payload, timeoutMs, verbose }) {
    const controller = new AbortController();

    const timeoutHandle = setTimeout(() => {
        controller.abort(new Error(`Timeout after ${timeoutMs}ms`));
    }, timeoutMs);

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
        if (verbose) {
            console.log('[DEBUG] Raw response:');
            console.log(text);
        }

        if (!res.ok) {
            const suffix = text ? `\n${text}` : '';
            throw new Error(`HTTP ${res.status} ${res.statusText}${suffix}`);
        }

        return extractMessagesFromGatewayResponse(text);
    } finally {
        clearTimeout(timeoutHandle);
    }
}

function resultToSearchableString(toolResult) {
    try {
        if (toolResult && Array.isArray(toolResult.content)) {
            return toolResult.content
                .map(c => {
                    if (!c) return '';
                    if (typeof c.text === 'string') return c.text;
                    return JSON.stringify(c);
                })
                .join('\n');
        }
    } catch {
        // ignore
    }

    return JSON.stringify(toolResult);
}

async function callToolViaGateway({ url, token, protocolVersion, timeoutMs, verbose, toolName, toolArgs }) {
    const initializePayload = {
        jsonrpc: '2.0',
        id: 1,
        method: 'initialize',
        params: {
            protocolVersion,
            capabilities: {},
            clientInfo: { name: 'gateway-tool-tests', version: '1.0.0' }
        }
    };

    const initializedNotification = {
        jsonrpc: '2.0',
        method: 'notifications/initialized',
        params: {}
    };

    const toolCallPayload = {
        jsonrpc: '2.0',
        id: 2,
        method: 'tools/call',
        params: {
            name: toolName,
            arguments: toolArgs
        }
    };

    const batchPayload = [initializePayload, initializedNotification, toolCallPayload];
    const response = await postJsonRpc({ url, token, payload: batchPayload, timeoutMs, verbose });

    const initResp = response.messages.find(m => m && m.id === 1) || null;
    const toolResp = response.messages.find(m => m && m.id === 2) || null;

    if (!initResp) throw new Error('Missing initialize response (id=1)');
    if (initResp.error) throw new Error(`initialize error: ${JSON.stringify(initResp.error)}`);

    if (!toolResp) throw new Error('Missing tools/call response (id=2)');
    if (toolResp.error) throw new Error(`tools/call error: ${JSON.stringify(toolResp.error)}`);

    return { sessionId: response.sessionId, toolResult: toolResp.result };
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

    if (config.dryRun) {
        const sample = TESTS[0];
        const payload = [
            {
                jsonrpc: '2.0',
                id: 1,
                method: 'initialize',
                params: {
                    protocolVersion: config.protocolVersion,
                    capabilities: {},
                    clientInfo: { name: 'gateway-tool-tests', version: '1.0.0' }
                }
            },
            { jsonrpc: '2.0', method: 'notifications/initialized', params: {} },
            {
                jsonrpc: '2.0',
                id: 2,
                method: 'tools/call',
                params: { name: sample.tool, arguments: sample.args }
            }
        ];

        console.log(buildCurl(config.url, config.token, payload));
        return 0;
    }

    console.log('='.repeat(60));
    console.log('MCP TOOLS TEST (via Docker MCP Gateway)');
    console.log('='.repeat(60));
    console.log(`Endpoint: ${config.url}`);
    console.log(`Protocol: ${config.protocolVersion}`);
    console.log(`Timeout:  ${config.timeoutMs}ms`);
    console.log('');

    let passed = 0;

    for (const t of TESTS) {
        const start = Date.now();
        try {
            const { sessionId, toolResult } = await callToolViaGateway({
                url: config.url,
                token: config.token,
                protocolVersion: config.protocolVersion,
                timeoutMs: config.timeoutMs,
                verbose: config.verbose,
                toolName: t.tool,
                toolArgs: t.args
            });

            const elapsedMs = Date.now() - start;
            const output = resultToSearchableString(toolResult);
            if (!output.toLowerCase().includes(String(t.expected).toLowerCase())) {
                throw new Error(`Expected to find ${JSON.stringify(t.expected)} in tool output`);
            }

            console.log(`[OK] ${t.name} (${elapsedMs}ms)${sessionId ? ` session=${sessionId}` : ''}`);
            passed++;
        } catch (err) {
            const elapsedMs = Date.now() - start;
            const msg = err && err.stack ? err.stack : String(err);
            console.error(`[ERROR] ${t.name} (${elapsedMs}ms): ${msg}`);
            return 1;
        }
    }

    console.log('');
    console.log(`[OK] Passed ${passed}/${TESTS.length} tests`);
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