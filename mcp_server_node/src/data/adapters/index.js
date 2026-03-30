/**
 * adapters/index.js - Barrel Export for Database Adapters
 *
 * Clean import point for all adapter modules.
 *
 * Usage:
 *   import { selectDatabaseBackend } from './adapters/index.js';
 *   import { VectorDatabaseAdapter, GraphDatabaseAdapter } from './adapters/index.js';
 *
 * @version 1.0.0
 * @author Phase 48 — AWS Infrastructure Port
 */

export { VectorDatabaseAdapter } from './VectorDatabaseAdapter.js';
export { GraphDatabaseAdapter } from './GraphDatabaseAdapter.js';
export { ChromaDBLegacyAdapter } from './ChromaDBLegacyAdapter.js';
export { Neo4jLegacyAdapter } from './Neo4jLegacyAdapter.js';
export { selectDatabaseBackend } from './backend-selector.js';
