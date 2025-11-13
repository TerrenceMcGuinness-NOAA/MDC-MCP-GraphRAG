/**
 * VectorDatabase.js - ChromaDB Vector Database Client
 * 
 * Provides connection and query methods for ChromaDB vector database.
 * Handles semantic search, document storage, and embedding generation.
 * 
 * Features:
 * - Collection management (create, list, delete)
 * - Document ingestion with automatic embeddings
 * - Semantic search with filters
 * - Batch operations for performance
 * - Health checks and metrics
 * 
 * @version 1.0.0
 * @author NOAA EMC Global Workflow Team
 */

import { ChromaClient } from 'chromadb';
import { pipeline } from '@xenova/transformers';

// Singleton embedding model instance (shared across all VectorDatabase instances)
let sharedEmbedder = null;
let embeddingModelName = null;
let embeddingModelPromise = null;

export class VectorDatabase {
  constructor(config = {}) {
    this.config = {
      host: config.host || process.env.CHROMADB_HOST || '127.0.0.1',
      port: config.port || process.env.CHROMADB_PORT || 8080,
      path: config.path || process.env.CHROMADB_PATH || '/api/v2',  // Updated to v2 API
      embeddingModel: config.embeddingModel || 'Xenova/all-mpnet-base-v2',  // 768-dim embeddings (upgraded from MiniLM 384-dim)
      batchSize: config.batchSize || 100,
      ...config
    };

    this.client = null;
    this.connected = false;
    this.collections = new Map(); // Cache collection instances
    
    this.metrics = {
      queriesExecuted: 0,
      documentsAdded: 0,
      embeddingsGenerated: 0,
      avgQueryTime: 0,
      lastQueryTime: null
    };
  }

  /**
   * Initialize connection to ChromaDB and load embedding model (singleton)
   */
  async connect() {
    if (this.connected) {
      return;
    }

    try {
      // Initialize ChromaDB client
      const url = `http://${this.config.host}:${this.config.port}${this.config.path}`;
      this.client = new ChromaClient({ path: url });

      // Verify connection with heartbeat
      const heartbeat = await this.client.heartbeat();
      console.log('[OK] ChromaDB heartbeat:', heartbeat);

      // Initialize singleton embedding model (lazy loading)
      if (!sharedEmbedder || embeddingModelName !== this.config.embeddingModel) {
        // If another instance is already loading, wait for it
        if (embeddingModelPromise) {
          console.log(`⏳ Waiting for shared embedding model to load...`);
          await embeddingModelPromise;
        } else {
          // This instance will load the model
          console.log(`[LOAD] Loading singleton embedding model: ${this.config.embeddingModel}`);
          embeddingModelName = this.config.embeddingModel;
          
          // Store the promise so other instances can await it
          embeddingModelPromise = pipeline('feature-extraction', this.config.embeddingModel)
            .then(model => {
              sharedEmbedder = model;
              console.log('[OK] Singleton embedding model loaded');
              embeddingModelPromise = null; // Clear promise after loading
              return model;
            })
            .catch(error => {
              embeddingModelPromise = null; // Clear promise on error
              sharedEmbedder = null;
              embeddingModelName = null;
              throw error;
            });
          
          await embeddingModelPromise;
        }
      } else {
        console.log(`[OK] Using existing singleton embedding model: ${embeddingModelName}`);
      }

      this.connected = true;
      console.log('[OK] Connected to ChromaDB:', url);
    } catch (error) {
      console.error('[ERROR] Failed to connect to ChromaDB:', error.message);
      throw error;
    }
  }

  /**
   * Generate embeddings for text using singleton model
   * @param {string|Array<string>} text - Text or array of texts
   * @returns {Promise<Array>} Embeddings
   */
  async generateEmbeddings(text) {
    if (!sharedEmbedder) {
      console.error('[WARN]  Singleton embedder not loaded, connecting...');
      await this.connect();
    }

    console.error(`[CALC] generateEmbeddings: input type=${Array.isArray(text) ? 'array' : 'string'}, length=${Array.isArray(text) ? text.length : text.length}`);
    const startTime = Date.now();
    
    try {
      const texts = Array.isArray(text) ? text : [text];
      console.error(`📝 Calling singleton embedder with ${texts.length} text(s)...`);
      const output = await sharedEmbedder(texts, { pooling: 'mean', normalize: true });
      console.error(`[OK] Singleton embedder returned, converting to array...`);
      
      // Convert tensor to array
      const embeddings = Array.isArray(text) 
        ? output.tolist() 
        : [output.tolist()];

      const embeddingTime = Date.now() - startTime;
      this.metrics.embeddingsGenerated += texts.length;
      console.error(`[OK] Embeddings generated in ${embeddingTime}ms`);
      
      return Array.isArray(text) ? embeddings : embeddings[0];
    } catch (error) {
      console.error('[ERROR] Failed to generate embeddings:', error.message);
      console.error('Stack:', error.stack);
      throw error;
    }
  }

  /**
   * Get or create a collection
   * @param {string} name - Collection name
   * @param {object} metadata - Collection metadata
   * @returns {Promise<object>} Collection instance
   */
  async getOrCreateCollection(name, metadata = {}) {
    if (!this.connected) {
      await this.connect();
    }

    // Check cache first
    if (this.collections.has(name)) {
      return this.collections.get(name);
    }

    try {
      // Use custom embedding function to avoid DefaultEmbeddingFunction dependency
      const collection = await this.client.getOrCreateCollection({
        name,
        metadata: {
          description: metadata.description || `Collection: ${name}`,
          ...metadata
        },
        embeddingFunction: {
          generate: async (texts) => {
            return await this.generateEmbeddings(texts);
          }
        }
      });

      this.collections.set(name, collection);
      return collection;
    } catch (error) {
      console.error(`Failed to get/create collection ${name}:`, error.message);
      throw error;
    }
  }

  /**
   * List all collections
   * @returns {Promise<Array>} List of collection names
   */
  async listCollections() {
    if (!this.connected) {
      await this.connect();
    }

    try {
      const collections = await this.client.listCollections();
      return collections.map(c => c.name);
    } catch (error) {
      console.error('Failed to list collections:', error.message);
      throw error;
    }
  }

  /**
   * Delete a collection
   * @param {string} name - Collection name
   */
  async deleteCollection(name) {
    if (!this.connected) {
      await this.connect();
    }

    try {
      await this.client.deleteCollection({ name });
      this.collections.delete(name);
      console.log(`[OK] Deleted collection: ${name}`);
    } catch (error) {
      console.error(`Failed to delete collection ${name}:`, error.message);
      throw error;
    }
  }

  /**
   * Add documents to a collection
   * @param {string} collectionName - Collection name
   * @param {Array<object>} documents - Documents to add
   * @returns {Promise<void>}
   */
  async addDocuments(collectionName, documents) {
    if (!this.connected) {
      await this.connect();
    }

    const collection = await this.getOrCreateCollection(collectionName);
    const startTime = Date.now();

    try {
      // Process in batches for performance
      for (let i = 0; i < documents.length; i += this.config.batchSize) {
        const batch = documents.slice(i, i + this.config.batchSize);
        
        const ids = batch.map(doc => doc.id);
        const texts = batch.map(doc => doc.text);
        const metadatas = batch.map(doc => doc.metadata || {});
        
        // Generate embeddings
        const embeddings = await this.generateEmbeddings(texts);

        // Add to collection
        await collection.add({
          ids,
          documents: texts,
          metadatas,
          embeddings
        });

        this.metrics.documentsAdded += batch.length;
      }

      const addTime = Date.now() - startTime;
      console.log(`[OK] Added ${documents.length} documents to ${collectionName} in ${addTime}ms`);
    } catch (error) {
      console.error(`Failed to add documents to ${collectionName}:`, error.message);
      throw error;
    }
  }

  /**
   * Query a collection with semantic search
   * @param {string} collectionName - Collection name
   * @param {string} queryText - Query text
   * @param {object} options - Query options
   * @returns {Promise<Array>} Search results
   */
  async query(collectionName, queryText, options = {}) {
    if (!this.connected) {
      await this.connect();
    }

    console.error(`[SEARCH] VectorDB.query: collection="${collectionName}"`);
    
    // Use getCollection to avoid creating new collection, provide custom embedding function
    let collection;
    try {
      collection = await this.client.getCollection({
        name: collectionName,
        embeddingFunction: {
          generate: async (texts) => {
            return await this.generateEmbeddings(texts);
          }
        }
      });
    } catch (error) {
      console.error(`Failed to get collection ${collectionName}:`, error.message);
      throw error;
    }
    
    console.error(`[OK] Collection retrieved`);
    const startTime = Date.now();

    try {
      const {
        nResults = 10,
        where = null,
        whereDocument = null,
        include = ['documents', 'metadatas', 'distances']
      } = options;

      // Execute query using queryTexts - let the embedding function handle it
      console.error(`[QUERY] Executing ChromaDB query with queryTexts...`);
      const results = await collection.query({
        queryTexts: [queryText],
        nResults,
        where,
        whereDocument,
        include
      });
      console.error(`[OK] ChromaDB query returned`);

      const queryTime = Date.now() - startTime;

      // Update metrics
      this.metrics.queriesExecuted++;
      this.metrics.lastQueryTime = queryTime;
      this.metrics.avgQueryTime = 
        (this.metrics.avgQueryTime * (this.metrics.queriesExecuted - 1) + queryTime) / 
        this.metrics.queriesExecuted;

      // Format results
      return this._formatQueryResults(results);
    } catch (error) {
      console.error(`Failed to query collection ${collectionName}:`, error.message);
      throw error;
    }
  }

  /**
   * Multi-collection search
   * @param {Array<string>} collectionNames - Collection names to search
   * @param {string} queryText - Query text
   * @param {object} options - Query options
   * @returns {Promise<Array>} Combined search results
   */
  async multiCollectionQuery(collectionNames, queryText, options = {}) {
    if (!this.connected) {
      await this.connect();
    }

    const allResults = [];

    for (const collectionName of collectionNames) {
      try {
        const results = await this.query(collectionName, queryText, options);
        
        // Add collection name to each result
        results.forEach(result => {
          result.collection = collectionName;
        });
        
        allResults.push(...results);
      } catch (error) {
        console.error(`Failed to query ${collectionName}:`, error.message);
        // Continue with other collections
      }
    }

    // Sort by distance (ascending - lower is better)
    allResults.sort((a, b) => a.distance - b.distance);

    // Return top N results
    const nResults = options.nResults || 10;
    return allResults.slice(0, nResults);
  }

  /**
   * Get document by ID
   * @param {string} collectionName - Collection name
   * @param {string} id - Document ID
   * @returns {Promise<object>} Document
   */
  async getDocument(collectionName, id) {
    if (!this.connected) {
      await this.connect();
    }

    const collection = await this.getOrCreateCollection(collectionName);

    try {
      const results = await collection.get({
        ids: [id],
        include: ['documents', 'metadatas']
      });

      if (results.ids.length === 0) {
        return null;
      }

      return {
        id: results.ids[0],
        text: results.documents[0],
        metadata: results.metadatas[0]
      };
    } catch (error) {
      console.error(`Failed to get document ${id}:`, error.message);
      throw error;
    }
  }

  /**
   * Update document metadata
   * @param {string} collectionName - Collection name
   * @param {string} id - Document ID
   * @param {object} metadata - New metadata
   */
  async updateMetadata(collectionName, id, metadata) {
    if (!this.connected) {
      await this.connect();
    }

    const collection = await this.getOrCreateCollection(collectionName);

    try {
      await collection.update({
        ids: [id],
        metadatas: [metadata]
      });
      console.log(`[OK] Updated metadata for ${id}`);
    } catch (error) {
      console.error(`Failed to update metadata for ${id}:`, error.message);
      throw error;
    }
  }

  /**
   * Delete documents by IDs
   * @param {string} collectionName - Collection name
   * @param {Array<string>} ids - Document IDs
   */
  async deleteDocuments(collectionName, ids) {
    if (!this.connected) {
      await this.connect();
    }

    const collection = await this.getOrCreateCollection(collectionName);

    try {
      await collection.delete({ ids });
      console.log(`[OK] Deleted ${ids.length} documents from ${collectionName}`);
    } catch (error) {
      console.error(`Failed to delete documents:`, error.message);
      throw error;
    }
  }

  /**
   * Get collection count
   * @param {string} collectionName - Collection name
   * @returns {Promise<number>} Document count
   */
  async getCollectionCount(collectionName) {
    if (!this.connected) {
      await this.connect();
    }

    const collection = await this.getOrCreateCollection(collectionName);

    try {
      return await collection.count();
    } catch (error) {
      console.error(`Failed to get count for ${collectionName}:`, error.message);
      throw error;
    }
  }

  /**
   * Peek at collection contents
   * @param {string} collectionName - Collection name
   * @param {number} limit - Number of documents to peek
   * @returns {Promise<Array>} Sample documents
   */
  async peekCollection(collectionName, limit = 10) {
    if (!this.connected) {
      await this.connect();
    }

    const collection = await this.getOrCreateCollection(collectionName);

    try {
      const results = await collection.peek({ limit });
      return this._formatPeekResults(results);
    } catch (error) {
      console.error(`Failed to peek collection ${collectionName}:`, error.message);
      throw error;
    }
  }

  /**
   * Health check - verify connection and basic query
   * @returns {Promise<object>} Health status
   */
  async healthCheck() {
    try {
      if (!this.connected) {
        await this.connect();
      }

      const heartbeat = await this.client.heartbeat();
      const collections = await this.listCollections();

      return {
        status: 'healthy',
        connected: this.connected,
        heartbeat,
        collections,
        metrics: this.metrics,
        timestamp: new Date().toISOString()
      };
    } catch (error) {
      return {
        status: 'unhealthy',
        connected: false,
        error: error.message,
        timestamp: new Date().toISOString()
      };
    }
  }

  /**
   * Get metrics for monitoring
   * @returns {object} Current metrics
   */
  getMetrics() {
    return {
      ...this.metrics,
      connected: this.connected,
      cachedCollections: Array.from(this.collections.keys()),
      config: {
        host: this.config.host,
        port: this.config.port,
        embeddingModel: this.config.embeddingModel
      }
    };
  }

  /**
   * Format query results into clean structure
   * @private
   */
  _formatQueryResults(results) {
    if (!results || !results.ids || results.ids.length === 0) {
      return [];
    }

    const formatted = [];
    const numResults = results.ids[0].length;

    for (let i = 0; i < numResults; i++) {
      formatted.push({
        id: results.ids[0][i],
        text: results.documents?.[0]?.[i] || null,
        metadata: results.metadatas?.[0]?.[i] || {},
        distance: results.distances?.[0]?.[i] || null,
        score: results.distances?.[0]?.[i] 
          ? 1 - results.distances[0][i]  // Convert distance to similarity score
          : null
      });
    }

    return formatted;
  }

  /**
   * Format peek results
   * @private
   */
  _formatPeekResults(results) {
    if (!results || !results.ids) {
      return [];
    }

    const formatted = [];
    for (let i = 0; i < results.ids.length; i++) {
      formatted.push({
        id: results.ids[i],
        text: results.documents?.[i] || null,
        metadata: results.metadatas?.[i] || {}
      });
    }

    return formatted;
  }

  /**
   * Close connections and cleanup
   * Note: Singleton embedder is NOT cleaned up here as it may be used by other instances
   */
  async close() {
    this.collections.clear();
    this.connected = false;
    console.log('[OK] ChromaDB connection closed (singleton embedder retained)');
  }
}
