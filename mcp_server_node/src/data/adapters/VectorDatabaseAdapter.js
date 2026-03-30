/**
 * VectorDatabaseAdapter.js - Abstract Vector Database Adapter
 *
 * Base class for all vector database backends (ChromaDB, OpenSearch, etc.).
 * Every public method throws "Not implemented" by default — subclasses must
 * override each method they support.
 *
 * Method signatures are derived from VectorDatabase.js (ChromaDB client).
 *
 * @version 1.0.0
 * @author Phase 48 — AWS Infrastructure Port
 */

export class VectorDatabaseAdapter {
  /**
   * Initialize connection to the vector database
   * @returns {Promise<void>}
   */
  async connect() {
    throw new Error('Not implemented: connect');
  }

  /**
   * Generate embeddings for text input
   * @param {string|Array<string>} text - Text or array of texts
   * @returns {Promise<Array>} Embeddings
   */
  async generateEmbeddings(text) {
    throw new Error('Not implemented: generateEmbeddings');
  }

  /**
   * Get or create a collection
   * @param {string} name - Collection name
   * @param {object} metadata - Collection metadata
   * @returns {Promise<object>} Collection instance
   */
  async getOrCreateCollection(name, metadata = {}) {
    throw new Error('Not implemented: getOrCreateCollection');
  }

  /**
   * List all collections
   * @returns {Promise<Array>} List of collection names
   */
  async listCollections() {
    throw new Error('Not implemented: listCollections');
  }

  /**
   * Delete a collection
   * @param {string} name - Collection name
   * @returns {Promise<void>}
   */
  async deleteCollection(name) {
    throw new Error('Not implemented: deleteCollection');
  }

  /**
   * Add documents to a collection
   * @param {string} collectionName - Collection name
   * @param {Array<object>} documents - Documents to add
   * @returns {Promise<void>}
   */
  async addDocuments(collectionName, documents) {
    throw new Error('Not implemented: addDocuments');
  }

  /**
   * Semantic search within a collection
   * @param {string} collectionName - Collection name
   * @param {string} queryText - Query text
   * @param {object} options - Query options
   * @returns {Promise<Array>} Search results
   */
  async query(collectionName, queryText, options = {}) {
    throw new Error('Not implemented: query');
  }

  /**
   * Search across multiple collections
   * @param {Array<string>} collectionNames - Collection names to search
   * @param {string} queryText - Query text
   * @param {object} options - Query options
   * @returns {Promise<Array>} Combined search results
   */
  async multiCollectionQuery(collectionNames, queryText, options = {}) {
    throw new Error('Not implemented: multiCollectionQuery');
  }

  /**
   * Get a specific document by ID
   * @param {string} collectionName - Collection name
   * @param {string} id - Document ID
   * @returns {Promise<object>} Document
   */
  async getDocument(collectionName, id) {
    throw new Error('Not implemented: getDocument');
  }

  /**
   * Update metadata for a document
   * @param {string} collectionName - Collection name
   * @param {string} id - Document ID
   * @param {object} metadata - New metadata
   * @returns {Promise<void>}
   */
  async updateMetadata(collectionName, id, metadata) {
    throw new Error('Not implemented: updateMetadata');
  }

  /**
   * Delete documents by IDs
   * @param {string} collectionName - Collection name
   * @param {Array<string>} ids - Document IDs
   * @returns {Promise<void>}
   */
  async deleteDocuments(collectionName, ids) {
    throw new Error('Not implemented: deleteDocuments');
  }

  /**
   * Get document count in a collection
   * @param {string} collectionName - Collection name
   * @returns {Promise<number>} Document count
   */
  async getCollectionCount(collectionName) {
    throw new Error('Not implemented: getCollectionCount');
  }

  /**
   * Peek at sample documents in a collection
   * @param {string} collectionName - Collection name
   * @param {number} limit - Number of documents to peek
   * @returns {Promise<Array>} Sample documents
   */
  async peekCollection(collectionName, limit = 10) {
    throw new Error('Not implemented: peekCollection');
  }

  /**
   * Health check for the vector database
   * @param {object} options - Health check options
   * @returns {Promise<object>} Health status
   */
  async healthCheck(options = {}) {
    throw new Error('Not implemented: healthCheck');
  }

  /**
   * Get current metrics
   * @returns {object} Current metrics
   */
  getMetrics() {
    throw new Error('Not implemented: getMetrics');
  }

  /**
   * Close the database connection
   * @returns {Promise<void>}
   */
  async close() {
    throw new Error('Not implemented: close');
  }
}

export default VectorDatabaseAdapter;
