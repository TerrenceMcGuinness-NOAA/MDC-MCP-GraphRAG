/**
 * GraphDatabase.test.js - Unit Tests for GraphDatabase
 * 
 * Tests Neo4j connection, query methods, and graph operations.
 */

import { describe, it, expect, beforeAll, afterAll, vi } from 'vitest';
import { GraphDatabase } from '../GraphDatabase.js';

describe('GraphDatabase', () => {
  let db;

  beforeAll(async () => {
    db = new GraphDatabase({
      uri: process.env.NEO4J_URI || 'bolt://localhost:7687',
      username: process.env.NEO4J_USERNAME || 'neo4j',
      password: process.env.NEO4J_PASSWORD || 'gfsworkflow2025'
    });
    await db.connect();
  });

  afterAll(async () => {
    await db.close();
  });

  describe('Connection', () => {
    it('should connect to Neo4j', async () => {
      expect(db.connected).toBe(true);
    });

    it('should execute basic query', async () => {
      const result = await db.query('RETURN 1 as test');
      expect(result).toEqual([{ test: 1 }]);
    });

    it('should handle connection pooling', async () => {
      const queries = Array(10).fill(null).map(() => 
        db.query('RETURN 1 as test')
      );
      const results = await Promise.all(queries);
      expect(results).toHaveLength(10);
      expect(results[0]).toEqual([{ test: 1 }]);
    });
  });

  describe('Statistics', () => {
    it('should get code structure statistics', async () => {
      const stats = await db.getStatistics();
      expect(stats).toHaveProperty('fileCount');
      expect(stats).toHaveProperty('functionCount');
      expect(stats).toHaveProperty('classCount');
      expect(stats).toHaveProperty('moduleCount');
      expect(typeof stats.fileCount).toBe('number');
    });

    it('should get relationship statistics', async () => {
      const relStats = await db.getRelationshipStats();
      expect(Array.isArray(relStats)).toBe(true);
      if (relStats.length > 0) {
        expect(relStats[0]).toHaveProperty('relationshipType');
        expect(relStats[0]).toHaveProperty('count');
      }
    });
  });

  describe('File Operations', () => {
    it('should find files by language', async () => {
      const pythonFiles = await db.findFilesByLanguage('python');
      expect(Array.isArray(pythonFiles)).toBe(true);
      if (pythonFiles.length > 0) {
        expect(pythonFiles[0]).toHaveProperty('filePath');
      }
    });

    it('should search files by pattern', async () => {
      const results = await db.searchFiles('.py');
      expect(Array.isArray(results)).toBe(true);
      if (results.length > 0) {
        expect(results[0].filePath).toContain('.py');
      }
    });

    it('should find file functions', async () => {
      const files = await db.findFilesByLanguage('python');
      if (files.length > 0) {
        const functions = await db.findFileFunctions(files[0].filePath);
        expect(Array.isArray(functions)).toBe(true);
      }
    });

    it('should find file classes', async () => {
      const files = await db.findFilesByLanguage('python');
      if (files.length > 0) {
        const classes = await db.findFileClasses(files[0].filePath);
        expect(Array.isArray(classes)).toBe(true);
      }
    });
  });

  describe('Import Operations', () => {
    it('should find file imports', async () => {
      const files = await db.findFilesByLanguage('python');
      if (files.length > 0) {
        const imports = await db.findFileImports(files[0].filePath);
        expect(Array.isArray(imports)).toBe(true);
        if (imports.length > 0) {
          expect(imports[0]).toHaveProperty('moduleName');
        }
      }
    });

    it('should find module importers', async () => {
      // Find a module that has imports
      const stats = await db.getStatistics();
      if (stats.moduleCount > 0) {
        const modules = await db.query('MATCH (m:Module) RETURN m.name as name LIMIT 1');
        if (modules.length > 0) {
          const importers = await db.findImporters(modules[0].name);
          expect(Array.isArray(importers)).toBe(true);
        }
      }
    });

    it('should analyze module usage', async () => {
      const modules = await db.query('MATCH (m:Module) RETURN m.name as name LIMIT 1');
      if (modules.length > 0) {
        const usage = await db.analyzeModuleUsage(modules[0].name);
        expect(usage).toHaveProperty('moduleName');
        expect(usage).toHaveProperty('importCount');
        expect(usage).toHaveProperty('files');
      }
    });
  });

  describe('Function Call Operations', () => {
    it('should find function callers', async () => {
      const functions = await db.query('MATCH (f:Function) RETURN f.name as name LIMIT 1');
      if (functions.length > 0) {
        const callers = await db.findCallers(functions[0].name);
        expect(Array.isArray(callers)).toBe(true);
      }
    });

    it('should trace call chain', async () => {
      const functions = await db.query('MATCH (f:Function) RETURN f.name as name LIMIT 1');
      if (functions.length > 0) {
        const callChain = await db.traceCallChain(functions[0].name, 2);
        expect(Array.isArray(callChain)).toBe(true);
      }
    });
  });

  describe('Dependency Analysis', () => {
    it('should find dependency graph', async () => {
      const files = await db.findFilesByLanguage('python');
      if (files.length > 0) {
        const depGraph = await db.findDependencyGraph(files[0].filePath, 2);
        expect(Array.isArray(depGraph)).toBe(true);
      }
    });

    it('should detect circular dependencies', async () => {
      const circular = await db.findCircularDependencies(3);
      expect(Array.isArray(circular)).toBe(true);
    });
  });

  describe('Chunk ID Management', () => {
    it('should add chunk ID to file', async () => {
      const files = await db.findFilesByLanguage('python');
      if (files.length > 0) {
        const testChunkId = 'test_chunk_' + Date.now();
        const result = await db.addChunkIdToFile(files[0].filePath, testChunkId);
        expect(Array.isArray(result)).toBe(true);
      }
    });

    it('should add chunk ID to function', async () => {
      const functions = await db.query(`
        MATCH (f:File)-[:DEFINES]->(func:Function)
        RETURN f.path as filePath, func.name as funcName
        LIMIT 1
      `);
      if (functions.length > 0) {
        const testChunkId = 'test_func_chunk_' + Date.now();
        const result = await db.addChunkIdToFunction(
          functions[0].funcName,
          functions[0].filePath,
          testChunkId
        );
        expect(Array.isArray(result)).toBe(true);
      }
    });
  });

  describe('Metrics', () => {
    it('should track query metrics', async () => {
      const beforeMetrics = db.getMetrics();
      await db.query('RETURN 1');
      const afterMetrics = db.getMetrics();
      
      expect(afterMetrics.queriesExecuted).toBeGreaterThan(beforeMetrics.queriesExecuted);
      expect(afterMetrics.lastQueryTime).toBeGreaterThan(0);
    });

    it('should calculate average query time', async () => {
      await db.query('RETURN 1');
      await db.query('RETURN 1');
      const metrics = db.getMetrics();
      
      expect(metrics.avgQueryTime).toBeGreaterThan(0);
    });
  });

  describe('Health Check', () => {
    it('should perform health check', async () => {
      const health = await db.healthCheck();
      expect(health.status).toBe('healthy');
      expect(health.connected).toBe(true);
      expect(health).toHaveProperty('metrics');
      expect(health).toHaveProperty('statistics');
    });

    it('should include timestamp in health check', async () => {
      const health = await db.healthCheck();
      expect(health.timestamp).toBeDefined();
      expect(new Date(health.timestamp).getTime()).toBeGreaterThan(0);
    });
  });

  describe('Error Handling', () => {
    it('should handle invalid Cypher query', async () => {
      await expect(db.query('INVALID QUERY')).rejects.toThrow();
    });

    it('should track failed queries', async () => {
      const beforeMetrics = db.getMetrics();
      try {
        await db.query('INVALID QUERY');
      } catch (e) {
        // Expected to fail
      }
      const afterMetrics = db.getMetrics();
      
      expect(afterMetrics.queriesFailed).toBeGreaterThan(beforeMetrics.queriesFailed);
    });

    it('should handle non-existent file gracefully', async () => {
      const result = await db.findFileFunctions('/nonexistent/file.py');
      expect(result).toEqual([]);
    });
  });
});
