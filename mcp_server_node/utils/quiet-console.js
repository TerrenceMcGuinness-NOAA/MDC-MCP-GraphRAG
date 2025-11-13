/**
 * Quiet Console Wrapper for MCP Protocol Compliance
 * 
 * MCP protocol requires ONLY JSON-RPC messages on stdout.
 * This module redirects all console.log/error/warn to a log file
 * to prevent protocol corruption.
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Log file location
const LOG_FILE = process.env.MCP_LOG_FILE || '/mcp_rag_eib/mcp_server_node/logs/mcp-console.log';

// Ensure log directory exists
const logDir = path.dirname(LOG_FILE);
if (!fs.existsSync(logDir)) {
  fs.mkdirSync(logDir, { recursive: true });
}

// Create write stream
const logStream = fs.createWriteStream(LOG_FILE, { flags: 'a' });

// Save original console methods
const originalConsole = {
  log: console.log,
  error: console.error,
  warn: console.warn,
  info: console.info,
  debug: console.debug
};

/**
 * Format log message with timestamp
 */
function formatMessage(level, args) {
  const timestamp = new Date().toISOString();
  const message = args.map(arg => 
    typeof arg === 'object' ? JSON.stringify(arg, null, 2) : String(arg)
  ).join(' ');
  return `[${timestamp}] [${level}] ${message}\n`;
}

/**
 * Enable quiet mode - redirect all console output to log file
 */
export function enableQuietMode() {
  console.log = (...args) => {
    logStream.write(formatMessage('LOG', args));
  };

  console.error = (...args) => {
    logStream.write(formatMessage('ERROR', args));
  };

  console.warn = (...args) => {
    logStream.write(formatMessage('WARN', args));
  };

  console.info = (...args) => {
    logStream.write(formatMessage('INFO', args));
  };

  console.debug = (...args) => {
    logStream.write(formatMessage('DEBUG', args));
  };

  // Write startup message to log
  logStream.write(formatMessage('INFO', ['Quiet mode enabled - console output redirected to', LOG_FILE]));
}

/**
 * Disable quiet mode - restore original console
 */
export function disableQuietMode() {
  console.log = originalConsole.log;
  console.error = originalConsole.error;
  console.warn = originalConsole.warn;
  console.info = originalConsole.info;
  console.debug = originalConsole.debug;
}

/**
 * Close log stream on process exit
 */
process.on('exit', () => {
  logStream.end();
});

process.on('SIGINT', () => {
  logStream.end();
  process.exit(0);
});

process.on('SIGTERM', () => {
  logStream.end();
  process.exit(0);
});

// Auto-enable if MCP_QUIET_MODE is set
if (process.env.MCP_QUIET_MODE === 'true') {
  enableQuietMode();
}
