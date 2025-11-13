/**
 * UnifiedDataAccess.test.js - Unit Tests for UnifiedDataAccess
 * 
 * Tests hybrid queries combining graph and vector operations.
 */

import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { UnifiedDataAccess } from '../UnifiedDataAccess.js';

describe('UnifiedDataAccess', () => {
  let unified;
  const testCollection = 'unified_test_' + Date.now();

  beforeAll(async () => {
    unified = new UnifiedDataAccess({
      neo4j: {
        uri: process.env.NEO4J_URI || 'bolt://localhost:7687',
        username: process.env.NEO4J_USERNAME || 'neo4j',
        password: process.env.NEO4J_PASSWORD || 'gfsworkflow2025'
      },
      chromadb: {
        host: process.env.CHROMADB_HOST || '127.0.0.1',
        port: process.env.CHROMADB_PORT || 8080
      }
    });
    await unified.connect();

    // Add test documents
    await unified.vectorDB.addDocuments(testCollection, [
      {
        id: 'test1_' + Date.now(),
        text: 'Python function for data processing in workflow system',
        metadata: { filePath: '/test/workflow.py', type: 'code' }
      },
      {
        id: 'test2_' + Date.now(),
        text: 'Global Forecast System operational documentation',
        metadata: { type: 'documentation' }
      }
    ]);
  });

  afterAll(async () => {
    try {
      await unified.vectorDB.deleteCollection(testCollection);
    } catch (e) {
      // May not exist
    }
    await unified.close();
  });

  describe('Connection', () => {
    it('should connect to both databases', () => {
      expect(unified.connected).toBe(true);
      expect(unified.graphDB.connected).toBe(true);
      expect(unified.vectorDB.connected).toBe(true);
    });
  });

  describe('Hybrid Query', () => {
    it('should perform basic hybrid query', async () => {
      const results = await unified.hybridQuery('workflow processing', {
        collection: testCollection,
        nResults: 5,
        includeGraphContext: false
      });

      expect(Array.isArray(results)).toBe(true);
      expect(results.length).toBeGreaterThan(0);
    });

    it('should enrich results with graph context', async () => {
      // Get a real file from the graph
      const files = await unified.graphDB.findFilesByLanguage('python');
      
      if (files.length > 0) {
        // Add a document with that file path
        const docId = 'enrichment_test_' + Date.now();
        await unified.vectorDB.addDocuments(testCollection, [{
          id: docId,
          text: 'Test code for enrichment',
          metadata: { filePath: files[0].filePath }
        }]);

        const results = await unified.hybridQuery('test code', {
          collection: testCollection,
          nResults: 5,
          includeGraphContext: true,
          includeDependencies: true,
          includeCallers: false
        });

        // Check if any result has graph context
        const enriched = results.find(r => r.graphContext);
        if (enriched) {
          expect(enriched.graphContext).toHaveProperty('imports');
          expect(enriched.graphContext).toHaveProperty('functions');
        }
      }
    });

    it('should track hybrid query metrics', async () => {
      const beforeMetrics = unified.getMetrics();
      await unified.hybridQuery('test query', {
        collection: testCollection,
        nResults: 1
      });
      const afterMetrics = unified.getMetrics();

      expect(afterMetrics.unified.hybridQueries).toBeGreaterThan(
        beforeMetrics.unified.hybridQueries
      );
    });
  });

  describe('Code with Dependencies', () => {
    it('should find code with dependencies for a file', async () => {
      const files = await unified.graphDB.findFilesByLanguage('python');
      
      if (files.length > 0) {
        const result = await unified.findCodeWithDependencies(files[0].filePath, {
          maxDepth: 1,
          includeSemanticSimilar: false
        });

        expect(result).toHaveProperty('identifier');
        expect(result).toHaveProperty('filePath');
        expect(result).toHaveProperty('imports');
        expect(result).toHaveProperty('functions');
        expect(result).toHaveProperty('dependencyGraph');
      }
    });

    it('should find code with semantic similarity', async () => {
      const files = await unified.graphDB.findFilesByLanguage('python');
      
      if (files.length > 0) {
        const result = await unified.findCodeWithDependencies(files[0].filePath, {
          maxDepth: 1,
          includeSemanticSimilar: true
        });

        expect(result).toHaveProperty('similarCode');
        expect(Array.isArray(result.similarCode)).toBe(true);
      }
    });

    it('should handle function name identifier', async () => {
      const functions = await unified.graphDB.query(
        'MATCH (f:Function) RETURN f.name as name LIMIT 1'
      );
      
      if (functions.length > 0) {
        const result = await unified.findCodeWithDependencies(functions[0].name, {
          maxDepth: 1,
          includeSemanticSimilar: false
        });

        expect(result).toHaveProperty('identifier');
        expect(result.identifier).toBe(functions[0].name);
      }
    });
  });

  describe('Multi-Source Search', () => {
    it('should search across multiple collections', async () => {
      const results = await unified.multiSourceSearch('workflow', {
        collections: [testCollection],
        nResults: 5,
        enrichWithGraph: false
      });

      expect(Array.isArray(results)).toBe(true);
      expect(results.length).toBeGreaterThan(0);
      results.forEach(result => {
        expect(result).toHaveProperty('collection');
      });
    });

    it('should enrich multi-source results with graph', async () => {
      const files = await unified.graphDB.findFilesByLanguage('python');
      
      if (files.length > 0) {
        const docId = 'multi_enrich_' + Date.now();
        await unified.vectorDB.getOrCreateCollection('code_with_context');
        await unified.vectorDB.addDocuments('code_with_context', [{
          id: docId,
          text: 'Multi-source test code',
          metadata: { filePath: files[0].filePath }
        }]);

        const results = await unified.multiSourceSearch('test', {
          collections: ['code_with_context'],
          nResults: 5,
          enrichWithGraph: true
        });

        const enriched = results.find(r => r.graphContext);
        if (enriched) {
          expect(enriched.graphContext).toHaveProperty('imports');
        }
      }
    });
  });

  describe('Related Code', () => {
    it('should find related code', async () => {
      const files = await unified.graphDB.findFilesByLanguage('python');
      
      if (files.length > 0) {
        const result = await unified.findRelatedCode(files[0].filePath, {
          includeDocumentation: false,
          maxResults: 10
        });

        expect(result).toHaveProperty('filePath');
        expect(result).toHaveProperty('imports');
        expect(result).toHaveProperty('dependencyGraph');
        expect(result).toHaveProperty('relatedFiles');
        expect(Array.isArray(result.relatedFiles)).toBe(true);
      }
    });

    it('should include documentation when requested', async () => {
      const files = await unified.graphDB.findFilesByLanguage('python');
      
      if (files.length > 0) {
        const result = await unified.findRelatedCode(files[0].filePath, {
          includeDocumentation: true,
          maxResults: 5
        });

        expect(result).toHaveProperty('documentation');
        expect(Array.isArray(result.documentation)).toBe(true);
      }
    });
  });

  describe('Execution Path Tracing', () => {
    it('should trace execution path', async () => {
      const functions = await unified.graphDB.query(
        'MATCH (f:Function) RETURN f.name as name LIMIT 1'
      );
      
      if (functions.length > 0) {
        const result = await unified.traceExecutionPath(functions[0].name, {
          maxDepth: 2,
          includeCode: false
        });

        expect(result).toHaveProperty('functionName');
        expect(result).toHaveProperty('callChain');
        expect(result).toHaveProperty('callers');
        expect(Array.isArray(result.callChain)).toBe(true);
        expect(Array.isArray(result.callers)).toBe(true);
      }
    });

    it('should include code snippets when requested', async () => {
      const functions = await unified.graphDB.query(
        'MATCH (f:Function) RETURN f.name as name LIMIT 1'
      );
      
      if (functions.length > 0) {
        const result = await unified.traceExecutionPath(functions[0].name, {
          maxDepth: 1,
          includeCode: true
        });

        expect(result).toHaveProperty('codeSnippets');
        expect(typeof result.codeSnippets).toBe('object');
      }
    });
  });

  describe('Statistics', () => {
    it('should get comprehensive statistics', async () => {
      const stats = await unified.getStatistics();

      expect(stats).toHaveProperty('graph');
      expect(stats).toHaveProperty('vector');
      expect(stats).toHaveProperty('unified');

      expect(stats.graph).toHaveProperty('fileCount');
      expect(stats.graph).toHaveProperty('relationships');
      expect(stats.vector).toHaveProperty('collections');
      expect(stats.unified).toHaveProperty('hybridQueries');
    });
  });

  describe('Health Check', () => {
    it('should perform unified health check', async () => {
      const health = await unified.healthCheck();

      expect(health.status).toBe('healthy');
      expect(health.connected).toBe(true);
      expect(health).toHaveProperty('graph');
      expect(health).toHaveProperty('vector');
      expect(health.graph.status).toBe('healthy');
      expect(health.vector.status).toBe('healthy');
    });
  });

  describe('Metrics', () => {
    it('should provide comprehensive metrics', () => {
      const metrics = unified.getMetrics();

      expect(metrics).toHaveProperty('unified');
      expect(metrics).toHaveProperty('graph');
      expect(metrics).toHaveProperty('vector');

      expect(metrics.unified).toHaveProperty('hybridQueries');
      expect(metrics.unified).toHaveProperty('graphQueries');
      expect(metrics.unified).toHaveProperty('vectorQueries');
    });
  });

  describe('Cache', () => {
    it('should track cache hits and misses', () => {
      const metrics = unified.getMetrics();
      expect(metrics.unified).toHaveProperty('cacheHits');
      expect(metrics.unified).toHaveProperty('cacheMisses');
    });

    it('should clear cache', () => {
      unified.clearCache();
      const stats = unified.getStatistics();
      // Cache should be empty after clear
      expect(unified.cache.size).toBe(0);
    });
  });

  describe('Error Handling', () => {
    it('should handle non-existent code gracefully', async () => {
      await expect(
        unified.findCodeWithDependencies('/nonexistent/file.py', {
          maxDepth: 1,
          includeSemanticSimilar: false
        })
      ).rejects.toThrow();
    });

    it('should handle invalid function name', async () => {
      const result = await unified.traceExecutionPath('nonexistent_function_xyz', {
        maxDepth: 1,
        includeCode: false
      });

      expect(result.callChain).toEqual([]);
      expect(result.callers).toEqual([]);
    });
  });
});
