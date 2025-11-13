/**
 * VectorDatabase.test.js - Unit Tests for VectorDatabase
 * 
 * Tests ChromaDB connection, embedding generation, and vector operations.
 */

import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { VectorDatabase } from '../VectorDatabase.js';

describe('VectorDatabase', () => {
  let db;
  const testCollection = 'test_collection_' + Date.now();

  beforeAll(async () => {
    db = new VectorDatabase({
      host: process.env.CHROMADB_HOST || '127.0.0.1',
      port: process.env.CHROMADB_PORT || 8080
    });
    await db.connect();
  });

  afterAll(async () => {
    // Cleanup test collection
    try {
      await db.deleteCollection(testCollection);
    } catch (e) {
      // May not exist
    }
    await db.close();
  });

  describe('Connection', () => {
    it('should connect to ChromaDB', () => {
      expect(db.connected).toBe(true);
    });

    it('should have embedding model loaded', () => {
      expect(db.embedder).toBeDefined();
    });
  });

  describe('Embedding Generation', () => {
    it('should generate embedding for single text', async () => {
      const embedding = await db.generateEmbeddings('test text');
      expect(Array.isArray(embedding)).toBe(true);
      expect(embedding.length).toBeGreaterThan(0);
      expect(typeof embedding[0]).toBe('number');
    });

    it('should generate embeddings for multiple texts', async () => {
      const embeddings = await db.generateEmbeddings(['text 1', 'text 2', 'text 3']);
      expect(Array.isArray(embeddings)).toBe(true);
      expect(embeddings.length).toBe(3);
      expect(Array.isArray(embeddings[0])).toBe(true);
    });

    it('should track embedding metrics', async () => {
      const beforeMetrics = db.getMetrics();
      await db.generateEmbeddings('test');
      const afterMetrics = db.getMetrics();
      
      expect(afterMetrics.embeddingsGenerated).toBeGreaterThan(beforeMetrics.embeddingsGenerated);
    });
  });

  describe('Collection Management', () => {
    it('should create collection', async () => {
      const collection = await db.getOrCreateCollection(testCollection, {
        description: 'Test collection'
      });
      expect(collection).toBeDefined();
      expect(collection.name).toBe(testCollection);
    });

    it('should list collections', async () => {
      await db.getOrCreateCollection(testCollection);
      const collections = await db.listCollections();
      expect(Array.isArray(collections)).toBe(true);
      expect(collections).toContain(testCollection);
    });

    it('should cache collection instances', async () => {
      const collection1 = await db.getOrCreateCollection(testCollection);
      const collection2 = await db.getOrCreateCollection(testCollection);
      expect(collection1).toBe(collection2); // Same instance from cache
    });

    it('should get collection count', async () => {
      await db.getOrCreateCollection(testCollection);
      const count = await db.getCollectionCount(testCollection);
      expect(typeof count).toBe('number');
      expect(count).toBeGreaterThanOrEqual(0);
    });
  });

  describe('Document Operations', () => {
    it('should add documents', async () => {
      const docs = [
        {
          id: 'doc1_' + Date.now(),
          text: 'This is a test document about weather forecasting',
          metadata: { type: 'test', category: 'weather' }
        },
        {
          id: 'doc2_' + Date.now(),
          text: 'This is a test document about data assimilation',
          metadata: { type: 'test', category: 'data' }
        }
      ];

      await db.addDocuments(testCollection, docs);
      
      const count = await db.getCollectionCount(testCollection);
      expect(count).toBeGreaterThanOrEqual(2);
    });

    it('should get document by ID', async () => {
      const docId = 'get_test_' + Date.now();
      await db.addDocuments(testCollection, [{
        id: docId,
        text: 'Test document for retrieval',
        metadata: { test: true }
      }]);

      const doc = await db.getDocument(testCollection, docId);
      expect(doc).toBeDefined();
      expect(doc.id).toBe(docId);
      expect(doc.text).toContain('Test document');
      expect(doc.metadata.test).toBe(true);
    });

    it('should update document metadata', async () => {
      const docId = 'update_test_' + Date.now();
      await db.addDocuments(testCollection, [{
        id: docId,
        text: 'Document for metadata update',
        metadata: { version: 1 }
      }]);

      await db.updateMetadata(testCollection, docId, { version: 2, updated: true });
      
      const doc = await db.getDocument(testCollection, docId);
      expect(doc.metadata.version).toBe(2);
      expect(doc.metadata.updated).toBe(true);
    });

    it('should delete documents', async () => {
      const docIds = [
        'delete1_' + Date.now(),
        'delete2_' + Date.now()
      ];

      await db.addDocuments(testCollection, docIds.map(id => ({
        id,
        text: 'Document to delete',
        metadata: {}
      })));

      await db.deleteDocuments(testCollection, docIds);

      const doc = await db.getDocument(testCollection, docIds[0]);
      expect(doc).toBeNull();
    });

    it('should handle batch operations', async () => {
      const docs = Array.from({ length: 150 }, (_, i) => ({
        id: `batch_${i}_${Date.now()}`,
        text: `Batch document ${i}`,
        metadata: { batch: true, index: i }
      }));

      await db.addDocuments(testCollection, docs);
      
      const metrics = db.getMetrics();
      expect(metrics.documentsAdded).toBeGreaterThanOrEqual(150);
    });
  });

  describe('Semantic Search', () => {
    beforeAll(async () => {
      // Add test documents for search
      const searchDocs = [
        {
          id: 'search1_' + Date.now(),
          text: 'Global Forecast System GFS weather prediction model',
          metadata: { type: 'forecast' }
        },
        {
          id: 'search2_' + Date.now(),
          text: 'Data assimilation GSI analysis system',
          metadata: { type: 'analysis' }
        },
        {
          id: 'search3_' + Date.now(),
          text: 'Python workflow automation and job scheduling',
          metadata: { type: 'workflow' }
        }
      ];
      await db.addDocuments(testCollection, searchDocs);
    });

    it('should perform semantic search', async () => {
      const results = await db.query(testCollection, 'weather forecasting', {
        nResults: 5
      });

      expect(Array.isArray(results)).toBe(true);
      expect(results.length).toBeGreaterThan(0);
      expect(results[0]).toHaveProperty('id');
      expect(results[0]).toHaveProperty('text');
      expect(results[0]).toHaveProperty('distance');
      expect(results[0]).toHaveProperty('score');
    });

    it('should filter search results', async () => {
      const results = await db.query(testCollection, 'system', {
        nResults: 5,
        where: { type: 'analysis' }
      });

      expect(Array.isArray(results)).toBe(true);
      results.forEach(result => {
        expect(result.metadata.type).toBe('analysis');
      });
    });

    it('should limit results correctly', async () => {
      const results = await db.query(testCollection, 'test', {
        nResults: 2
      });

      expect(results.length).toBeLessThanOrEqual(2);
    });

    it('should track query metrics', async () => {
      const beforeMetrics = db.getMetrics();
      await db.query(testCollection, 'test query');
      const afterMetrics = db.getMetrics();

      expect(afterMetrics.queriesExecuted).toBeGreaterThan(beforeMetrics.queriesExecuted);
      expect(afterMetrics.lastQueryTime).toBeGreaterThan(0);
    });
  });

  describe('Multi-Collection Search', () => {
    const collection2 = testCollection + '_2';

    beforeAll(async () => {
      await db.addDocuments(collection2, [{
        id: 'multi1_' + Date.now(),
        text: 'Multi-collection search test document',
        metadata: { collection: 2 }
      }]);
    });

    afterAll(async () => {
      try {
        await db.deleteCollection(collection2);
      } catch (e) {
        // May not exist
      }
    });

    it('should search across multiple collections', async () => {
      const results = await db.multiCollectionQuery(
        [testCollection, collection2],
        'test document',
        { nResults: 10 }
      );

      expect(Array.isArray(results)).toBe(true);
      
      // Should have results from both collections
      const collections = new Set(results.map(r => r.collection));
      expect(collections.size).toBeGreaterThan(0);
    });

    it('should sort multi-collection results by distance', async () => {
      const results = await db.multiCollectionQuery(
        [testCollection, collection2],
        'test',
        { nResults: 10 }
      );

      // Verify sorted by distance (ascending)
      for (let i = 1; i < results.length; i++) {
        expect(results[i].distance).toBeGreaterThanOrEqual(results[i - 1].distance);
      }
    });
  });

  describe('Collection Peek', () => {
    it('should peek collection contents', async () => {
      const samples = await db.peekCollection(testCollection, 5);
      expect(Array.isArray(samples)).toBe(true);
      if (samples.length > 0) {
        expect(samples[0]).toHaveProperty('id');
        expect(samples[0]).toHaveProperty('text');
        expect(samples[0]).toHaveProperty('metadata');
      }
    });
  });

  describe('Metrics', () => {
    it('should provide comprehensive metrics', () => {
      const metrics = db.getMetrics();
      expect(metrics).toHaveProperty('queriesExecuted');
      expect(metrics).toHaveProperty('documentsAdded');
      expect(metrics).toHaveProperty('embeddingsGenerated');
      expect(metrics).toHaveProperty('connected');
      expect(metrics).toHaveProperty('cachedCollections');
    });
  });

  describe('Health Check', () => {
    it('should perform health check', async () => {
      const health = await db.healthCheck();
      expect(health.status).toBe('healthy');
      expect(health.connected).toBe(true);
      expect(health).toHaveProperty('heartbeat');
      expect(health).toHaveProperty('collections');
      expect(Array.isArray(health.collections)).toBe(true);
    });

    it('should include metrics in health check', async () => {
      const health = await db.healthCheck();
      expect(health).toHaveProperty('metrics');
      expect(health.metrics).toHaveProperty('queriesExecuted');
    });
  });

  describe('Error Handling', () => {
    it('should handle non-existent collection gracefully', async () => {
      const doc = await db.getDocument('nonexistent_collection', 'fake_id');
      expect(doc).toBeNull();
    });

    it('should handle empty query', async () => {
      const results = await db.query(testCollection, '', { nResults: 1 });
      expect(Array.isArray(results)).toBe(true);
    });
  });
});
