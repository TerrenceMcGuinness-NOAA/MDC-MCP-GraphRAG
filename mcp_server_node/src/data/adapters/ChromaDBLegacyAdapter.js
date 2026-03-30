/**
 * ChromaDBLegacyAdapter.js - ChromaDB Legacy Adapter
 *
 * Wraps the existing VectorDatabase (ChromaDB) implementation behind
 * the VectorDatabaseAdapter interface. Every method is a pure passthrough
 * to the wrapped instance — return formats are identical.
 *
 * Usage:
 *   // Dependency injection (wrap existing instance)
 *   const adapter = new ChromaDBLegacyAdapter(existingVectorDB);
 *
 *   // Config-based construction (creates VectorDatabase internally)
 *   const adapter = new ChromaDBLegacyAdapter({ host: '127.0.0.1', port: 8080 });
 *
 * @version 1.0.0
 * @author Phase 48 — AWS Infrastructure Port
 */

import { VectorDatabaseAdapter } from './VectorDatabaseAdapter.js';
import { VectorDatabase } from '../VectorDatabase.js';

export class ChromaDBLegacyAdapter extends VectorDatabaseAdapter {
  /**
   * @param {VectorDatabase|object} configOrInstance - Existing VectorDatabase instance or config object
   */
  constructor(configOrInstance = {}) {
    super();
    if (configOrInstance instanceof VectorDatabase) {
      this.db = configOrInstance;
    } else {
      this.db = new VectorDatabase(configOrInstance);
    }
  }

  /** @inheritdoc */
  async connect() {
    return this.db.connect();
  }

  /** @inheritdoc */
  async generateEmbeddings(text) {
    return this.db.generateEmbeddings(text);
  }

  /** @inheritdoc */
  async getOrCreateCollection(name, metadata = {}) {
    return this.db.getOrCreateCollection(name, metadata);
  }

  /** @inheritdoc */
  async listCollections() {
    return this.db.listCollections();
  }

  /** @inheritdoc */
  async deleteCollection(name) {
    return this.db.deleteCollection(name);
  }

  /** @inheritdoc */
  async addDocuments(collectionName, documents) {
    return this.db.addDocuments(collectionName, documents);
  }

  /** @inheritdoc */
  async query(collectionName, queryText, options = {}) {
    return this.db.query(collectionName, queryText, options);
  }

  /** @inheritdoc */
  async multiCollectionQuery(collectionNames, queryText, options = {}) {
    return this.db.multiCollectionQuery(collectionNames, queryText, options);
  }

  /** @inheritdoc */
  async getDocument(collectionName, id) {
    return this.db.getDocument(collectionName, id);
  }

  /** @inheritdoc */
  async updateMetadata(collectionName, id, metadata) {
    return this.db.updateMetadata(collectionName, id, metadata);
  }

  /** @inheritdoc */
  async deleteDocuments(collectionName, ids) {
    return this.db.deleteDocuments(collectionName, ids);
  }

  /** @inheritdoc */
  async getCollectionCount(collectionName) {
    return this.db.getCollectionCount(collectionName);
  }

  /** @inheritdoc */
  async peekCollection(collectionName, limit = 10) {
    return this.db.peekCollection(collectionName, limit);
  }

  /** @inheritdoc */
  async healthCheck(options = {}) {
    return this.db.healthCheck(options);
  }

  /** @inheritdoc */
  getMetrics() {
    return this.db.getMetrics();
  }

  /** @inheritdoc */
  async close() {
    return this.db.close();
  }
}

export default ChromaDBLegacyAdapter;
