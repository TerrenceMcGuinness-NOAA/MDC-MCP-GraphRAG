/**
 * backend-selector.js - Database Backend Selector
 *
 * Routes database construction to the appropriate adapter based on
 * the DB_BACKEND configuration. Currently supports 'legacy' (ChromaDB + Neo4j).
 * AWS adapters (OpenSearch + Neptune) will be added in Phase 48B Steps 7, 9.
 *
 * @version 1.0.0
 * @author Phase 48 — AWS Infrastructure Port
 */

import { ChromaDBLegacyAdapter } from './ChromaDBLegacyAdapter.js';
import { Neo4jLegacyAdapter } from './Neo4jLegacyAdapter.js';

/**
 * Select and instantiate database adapters based on configuration.
 *
 * @param {object} config - Configuration object
 * @param {string} [config.dbBackend] - Backend type: 'legacy' or 'aws' (default: 'legacy')
 * @param {object} [config.neo4j] - Neo4j connection config (passed to Neo4jLegacyAdapter)
 * @param {object} [config.chromadb] - ChromaDB connection config (passed to ChromaDBLegacyAdapter)
 * @returns {{ vectorDB: VectorDatabaseAdapter, graphDB: GraphDatabaseAdapter }}
 */
export function selectDatabaseBackend(config = {}) {
  const backend = config.dbBackend || process.env.DB_BACKEND || 'legacy';

  switch (backend) {
    case 'legacy': {
      console.log(`[OK] Database backend: legacy (ChromaDB + Neo4j)`);
      return {
        vectorDB: new ChromaDBLegacyAdapter(config.chromadb || {}),
        graphDB: new Neo4jLegacyAdapter(config.neo4j || {})
      };
    }

    case 'aws':
      throw new Error('AWS backend not yet implemented — Phase 48B Steps 7,9');

    default:
      throw new Error(`Unknown DB_BACKEND: ${backend}`);
  }
}

export default selectDatabaseBackend;
