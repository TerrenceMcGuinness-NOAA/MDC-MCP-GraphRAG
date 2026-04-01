#!/usr/bin/env node
/**
 * cutover-mcp-client.js — Step 24: MCP Client Cutover to AWS
 *
 * Updates .kiro/settings/mcp.json to point to the AWS CloudFront endpoint.
 * Preserves the legacy eib-mcp-gateway entry as a read-only fallback.
 *
 * Usage:
 *   node scripts/cutover-mcp-client.js --endpoint https://<cf-domain>/mcp --token <bearer>
 *   node scripts/cutover-mcp-client.js --rollback   # restore legacy-only config
 *
 * The legacy system is retained as read-only fallback for 2 weeks post-cutover
 * per Requirement 16.1.
 */

import { readFileSync, writeFileSync, copyFileSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const MCP_JSON  = join(__dirname, '../../.kiro/settings/mcp.json');
const BACKUP    = `${MCP_JSON}.pre-cutover.bak`;

const args     = process.argv.slice(2);
const ROLLBACK = args.includes('--rollback');
const endpoint = args[args.indexOf('--endpoint') + 1] || '';
const token    = args[args.indexOf('--token')    + 1] || '';

function readConfig() {
  return JSON.parse(readFileSync(MCP_JSON, 'utf8'));
}

function writeConfig(cfg) {
  writeFileSync(MCP_JSON, JSON.stringify(cfg, null, 2) + '\n');
}

if (ROLLBACK) {
  if (!existsSync(BACKUP)) {
    console.error('[ERROR] No backup found at', BACKUP);
    process.exit(1);
  }
  copyFileSync(BACKUP, MCP_JSON);
  console.log('[OK]  Rolled back to legacy config');
  process.exit(0);
}

if (!endpoint || !token) {
  console.error('[ERROR] --endpoint and --token are required');
  console.error('Usage: node cutover-mcp-client.js --endpoint https://<cf>/mcp --token <bearer>');
  process.exit(1);
}

// Backup current config
copyFileSync(MCP_JSON, BACKUP);
console.log('[OK]  Backed up current config to', BACKUP);

const cfg = readConfig();

// Add AWS endpoint as primary
cfg.mcpServers['mdc-mcp-rag'] = {
  type: 'http',
  url: endpoint,
  headers: { Authorization: `Bearer ${token}` },
  autoApprove: cfg.mcpServers['eib-mcp-gateway']?.autoApprove || [],
};

// Demote legacy to read-only fallback (disable write tools)
if (cfg.mcpServers['eib-mcp-gateway']) {
  cfg.mcpServers['eib-mcp-gateway']._note = 'Legacy fallback — read-only for 2 weeks post-cutover (Req 16.1)';
  cfg.mcpServers['eib-mcp-gateway'].disabled = false;  // keep accessible
}

writeConfig(cfg);
console.log('[OK]  MCP config updated:');
console.log(`      Primary:  mdc-mcp-rag → ${endpoint}`);
console.log('      Fallback: eib-mcp-gateway (legacy, read-only)');
console.log('\nTo rollback: node scripts/cutover-mcp-client.js --rollback');
