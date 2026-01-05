/**
 * Environment Configuration for MCP Server
 * =========================================
 * 
 * Single Point of Truth (SPOT) for environment-aware database connections.
 * Mirrors the Python scripts/config/environment.py for consistency.
 * 
 * Usage:
 *   import { getConfig, MCP_ENV, isWriteAllowed } from './config/environment.js';
 *   
 *   const config = getConfig();
 *   const chromaHost = config.chromadb.host;
 * 
 * Environment Variables:
 *   MCP_ENV: development (default), devops, staging, production
 *   MCP_WORKFLOW_ROOT: Path to global-workflow repository (default: relative path)
 *   SDD_FRAMEWORK_ROOT: Path to sdd_framework directory (default: relative path)
 *     - Container: /app/sdd_framework (volume-mounted)
 *     - Local: ./sdd_framework (relative to repo root)
 * 
 * Data Isolation Strategy:
 *   - development: Feature branches, local experimentation
 *   - devops: env/dev-ops branch, containerized validation
 *   - staging: Pre-production validation (read-mostly)
 *   - production: CI/CD only, no manual access
 * 
 * @version 1.0.0
 */

// Environment detection
export const MCP_ENV = process.env.MCP_ENV || 'development';

// Valid environments
const VALID_ENVIRONMENTS = ['development', 'devops', 'staging', 'production'];

/**
 * Environment-specific configurations
 */
const ENVIRONMENT_CONFIGS = {
  development: {
    description: 'Feature branch development - local experimentation allowed',
    chromadb: {
      host: process.env.CHROMADB_HOST || '127.0.0.1',
      port: parseInt(process.env.CHROMADB_PORT || '8080', 10),
      // In development, can also use embedded mode
      clientMode: process.env.CHROMA_CLIENT_MODE || 'server',
      persistPath: process.env.CHROMA_PERSIST_DIRECTORY || '/mcp_rag_eib/data/chromadb',
    },
    neo4j: {
      uri: process.env.NEO4J_URI || 'bolt://localhost:7687',
      user: process.env.NEO4J_USER || 'neo4j',
      password: process.env.NEO4J_PASSWORD || 'password',
    },
    allowWrites: true,
    allowExperimentation: true,
  },

  devops: {
    description: 'env/dev-ops branch - containerized database validation',
    chromadb: {
      host: process.env.CHROMADB_HOST || 'localhost',
      port: parseInt(process.env.CHROMADB_PORT || '8080', 10),
      clientMode: 'server',  // Always use HTTP client in devops
      // Container provides persistence
    },
    neo4j: {
      uri: process.env.NEO4J_URI || 'bolt://localhost:7687',
      user: process.env.NEO4J_USER || 'neo4j',
      password: process.env.NEO4J_PASSWORD || 'devops_password',
    },
    allowWrites: true,  // CI/CD can re-ingest
    allowExperimentation: false,
  },

  staging: {
    description: 'env/staging branch - pre-production validation',
    chromadb: {
      host: process.env.STAGING_CHROMADB_HOST || 'staging-chromadb',
      port: parseInt(process.env.STAGING_CHROMADB_PORT || '8000', 10),
      clientMode: 'server',
    },
    neo4j: {
      uri: process.env.STAGING_NEO4J_URI || 'bolt://staging-neo4j:7687',
      user: process.env.NEO4J_USER || 'neo4j',
      password: process.env.NEO4J_STAGING_PASSWORD || '',
    },
    allowWrites: false,  // Read-only validation
    allowExperimentation: false,
  },

  production: {
    description: 'env/production branch - CI/CD access only',
    chromadb: {
      host: process.env.PROD_CHROMADB_HOST || '',
      port: parseInt(process.env.PROD_CHROMADB_PORT || '8000', 10),
      clientMode: 'server',
    },
    neo4j: {
      uri: process.env.PROD_NEO4J_URI || '',
      user: process.env.NEO4J_USER || 'neo4j',
      password: process.env.NEO4J_PRODUCTION_PASSWORD || '',
    },
    allowWrites: false,  // NEVER write directly
    allowExperimentation: false,
    requirePipelineAuth: true,
  },
};

/**
 * Get configuration for current environment
 * @returns {object} Environment configuration
 * @throws {Error} If MCP_ENV is invalid or production access is attempted manually
 */
export function getConfig() {
  if (!VALID_ENVIRONMENTS.includes(MCP_ENV)) {
    throw new Error(`Invalid MCP_ENV: ${MCP_ENV}. Valid values: ${VALID_ENVIRONMENTS.join(', ')}`);
  }

  const config = ENVIRONMENT_CONFIGS[MCP_ENV];

  // Production safety check
  if (MCP_ENV === 'production' && !process.env.CI_PIPELINE_ID) {
    throw new Error(
      'Production database access is restricted to CI/CD pipelines. ' +
      'Set MCP_ENV=development or MCP_ENV=devops for local work.'
    );
  }

  return config;
}

/**
 * Get ChromaDB configuration for current environment
 * @returns {object} ChromaDB config {host, port, clientMode, persistPath?}
 */
export function getChromaConfig() {
  return getConfig().chromadb;
}

/**
 * Get Neo4j configuration for current environment
 * @returns {object} Neo4j config {uri, user, password}
 */
export function getNeo4jConfig() {
  return getConfig().neo4j;
}

/**
 * Check if writes are allowed in current environment
 * @returns {boolean}
 */
export function isWriteAllowed() {
  try {
    return getConfig().allowWrites;
  } catch {
    return false;
  }
}

/**
 * Check if experimentation is allowed (creating test collections, etc.)
 * @returns {boolean}
 */
export function isExperimentationAllowed() {
  try {
    return getConfig().allowExperimentation;
  } catch {
    return false;
  }
}

/**
 * Log current environment configuration
 */
export function logEnvironment() {
  const config = ENVIRONMENT_CONFIGS[MCP_ENV] || {};
  console.error('='.repeat(60));
  console.error('MCP Environment Configuration');
  console.error('='.repeat(60));
  console.error(`MCP_ENV: ${MCP_ENV}`);
  console.error(`Description: ${config.description || 'Unknown'}`);
  console.error(`ChromaDB: ${config.chromadb?.host}:${config.chromadb?.port} (${config.chromadb?.clientMode})`);
  console.error(`Neo4j: ${config.neo4j?.uri}`);
  console.error(`Writes Allowed: ${config.allowWrites}`);
  console.error(`Experimentation: ${config.allowExperimentation}`);
  console.error('='.repeat(60));
}

// Export for CommonJS compatibility if needed
export default {
  MCP_ENV,
  getConfig,
  getChromaConfig,
  getNeo4jConfig,
  isWriteAllowed,
  isExperimentationAllowed,
  logEnvironment,
  VALID_ENVIRONMENTS,
};
