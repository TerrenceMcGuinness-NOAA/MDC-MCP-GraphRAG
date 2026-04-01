/**
 * AWS Configuration Resolution for MDC MCP RAG Server
 * =====================================================
 *
 * Fetches credentials from Secrets Manager and endpoints from SSM Parameter Store.
 * Caches resolved values for the process lifetime (single API call per key).
 * Falls back to environment variables if AWS services are unavailable.
 *
 * SECURITY: Secret values are NEVER logged to stdout/stderr.
 *
 * Usage:
 *   import { resolveConfig } from './config/aws-config.js';
 *   const cfg = await resolveConfig();
 *   // cfg.neptune.endpoint, cfg.opensearch.endpoint, cfg.neptune.credentials (object)
 *
 * @module aws-config
 */

import {
  SecretsManagerClient,
  GetSecretValueCommand,
} from '@aws-sdk/client-secrets-manager';
import {
  SSMClient,
  GetParametersCommand,
} from '@aws-sdk/client-ssm';

const REGION = process.env.AWS_REGION || 'us-east-1';

// Process-lifetime cache — populated on first call to resolveConfig()
let _cache = null;

/**
 * Resolve all MDC MCP RAG configuration from AWS services.
 * Subsequent calls return the cached result without additional API calls.
 *
 * @returns {Promise<object>} Resolved configuration (no secret values in keys)
 */
export async function resolveConfig() {
  if (_cache) return _cache;

  const [secrets, params] = await Promise.all([
    _fetchSecrets(),
    _fetchSsmParams(),
  ]);

  _cache = {
    neptune: {
      endpoint: params['/mdc-mcp-rag/neptune/endpoint'],
      credentials: secrets['mdc-mcp-rag/neptune/credentials'],  // object {username, password}
    },
    opensearch: {
      endpoint: params['/mdc-mcp-rag/opensearch/endpoint'],
    },
    dbBackend: params['/mdc-mcp-rag/db-backend'] || 'legacy',
    github: {
      token: secrets['mdc-mcp-rag/github/token'],  // string
    },
  };

  return _cache;
}

/**
 * Clear the process-lifetime cache (for testing only).
 */
export function _clearCache() {
  _cache = null;
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

async function _fetchSecrets() {
  const secretNames = [
    'mdc-mcp-rag/neptune/credentials',
    'mdc-mcp-rag/github/token',
  ];

  const results = {};

  try {
    const client = new SecretsManagerClient({ region: REGION });
    await Promise.all(secretNames.map(async (name) => {
      try {
        const resp = await client.send(new GetSecretValueCommand({ SecretId: name }));
        const raw = resp.SecretString;
        try {
          results[name] = JSON.parse(raw);
        } catch {
          results[name] = raw;  // plain string secret (e.g. GitHub token)
        }
      } catch (err) {
        // Fall back to env vars — log key name only, never the value
        console.error(`[WARN] aws-config: Secrets Manager unavailable for "${name}", falling back to env vars (${err.name})`);
        results[name] = _envFallbackSecret(name);
      }
    }));
  } catch (err) {
    console.error(`[WARN] aws-config: SecretsManagerClient init failed, using env var fallbacks (${err.message})`);
    for (const name of secretNames) {
      results[name] = _envFallbackSecret(name);
    }
  }

  return results;
}

async function _fetchSsmParams() {
  const paramNames = [
    '/mdc-mcp-rag/neptune/endpoint',
    '/mdc-mcp-rag/opensearch/endpoint',
    '/mdc-mcp-rag/db-backend',
  ];

  const results = {};

  try {
    const client = new SSMClient({ region: REGION });
    const resp = await client.send(new GetParametersCommand({ Names: paramNames }));

    for (const p of (resp.Parameters || [])) {
      results[p.Name] = p.Value;
    }

    // Any missing params fall back to env vars
    for (const name of paramNames) {
      if (!(name in results)) {
        console.error(`[WARN] aws-config: SSM param "${name}" not found, falling back to env var`);
        results[name] = _envFallbackParam(name);
      }
    }
  } catch (err) {
    console.error(`[WARN] aws-config: SSM unavailable, using env var fallbacks (${err.message})`);
    for (const name of paramNames) {
      results[name] = _envFallbackParam(name);
    }
  }

  return results;
}

function _envFallbackSecret(secretName) {
  const map = {
    'mdc-mcp-rag/neptune/credentials': () => ({
      username: process.env.NEPTUNE_USER || 'neptune',
      password: process.env.NEPTUNE_PASSWORD || '',
    }),
    'mdc-mcp-rag/github/token': () => process.env.GITHUB_TOKEN || '',
  };
  return (map[secretName] || (() => null))();
}

function _envFallbackParam(paramName) {
  const map = {
    '/mdc-mcp-rag/neptune/endpoint': process.env.NEPTUNE_ENDPOINT || '',
    '/mdc-mcp-rag/opensearch/endpoint': process.env.OPENSEARCH_ENDPOINT || '',
    '/mdc-mcp-rag/db-backend': process.env.DB_BACKEND || 'legacy',
  };
  return map[paramName] ?? null;
}
