/**
 * Unit Tests for SemanticSearchTools
 * Updated: Phase 52 — aligned with current multiSourceSearch/hybridQuery API
 *
 * Tests 4 core tools (EE2 compliance + findSimilarCode moved to separate modules):
 * 1. search_documentation  (uses multiSourceSearch or hybridQuery)
 * 2. explain_with_context   (uses multiSourceSearch)
 * 3. get_knowledge_base_status (uses dataAccess.getStatistics)
 * 4. find_related_files     (uses dataAccess.findRelatedCode)
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import SemanticSearchTools from '../tools/SemanticSearchTools.js';

describe('SemanticSearchTools', () => {
  let tools;
  let mockDataAccess;

  beforeEach(() => {
    mockDataAccess = {
      vectorDB: {
        query: vi.fn().mockResolvedValue([]),
        listCollections: vi.fn().mockResolvedValue([]),
        client: { getCollection: vi.fn() }
      },
      graphDB: {
        query: vi.fn().mockResolvedValue([]),
        getScriptGraphStats: vi.fn().mockResolvedValue({}),
        healthCheck: vi.fn().mockResolvedValue(true)
      },
      hybridQuery: vi.fn().mockResolvedValue([]),
      multiSourceSearch: vi.fn().mockResolvedValue([]),
      findRelatedCode: vi.fn().mockResolvedValue([]),
      getStatistics: vi.fn().mockResolvedValue({
        vector: { totalCollections: 2, collections: { 'global-workflow-docs': 490, 'code-with-context': 1000 } },
        graph: { fileCount: 937, functionCount: 500, classCount: 20, relationships: [] }
      }),
      connect: vi.fn().mockResolvedValue(),
      close: vi.fn().mockResolvedValue()
    };

    tools = new SemanticSearchTools(mockDataAccess);
    // Mark as initialized to skip real DB connections
    tools.isInitialized = true;
    tools.initializationError = null;
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe('search_documentation', () => {
    it('should return semantic search results via multiSourceSearch', async () => {
      mockDataAccess.multiSourceSearch.mockResolvedValue([
        {
          document: 'Sample workflow documentation about running GFS',
          metadata: { source: 'global-workflow', title: 'GFS Guide' },
          distance: 0.85,
          collection: 'global-workflow-docs'
        }
      ]);

      const result = await tools.searchDocumentation({
        query: 'How do I run the global workflow?',
        max_results: 3
      });

      expect(mockDataAccess.multiSourceSearch).toHaveBeenCalled();
      expect(result.content[0].text).toContain('Sample workflow documentation');
    });

    it('should handle empty results gracefully', async () => {
      mockDataAccess.multiSourceSearch.mockResolvedValue([]);

      const result = await tools.searchDocumentation({
        query: 'nonexistent query',
        max_results: 3
      });

      expect(result.content[0].text).toContain('No results found');
    });

    it('should use hybridQuery when collection is specified', async () => {
      mockDataAccess.hybridQuery.mockResolvedValue([
        {
          document: 'Targeted collection result',
          metadata: { source: 'test' },
          distance: 0.7
        }
      ]);

      const result = await tools.searchDocumentation({
        query: 'test query',
        max_results: 3,
        collection: 'global-workflow-docs-v8-2-0'
      });

      expect(mockDataAccess.hybridQuery).toHaveBeenCalled();
      expect(result.content[0].text).toContain('Targeted collection result');
    });
  });

  describe('explain_with_context', () => {
    it('should provide contextual explanations using multiSourceSearch', async () => {
      mockDataAccess.multiSourceSearch.mockResolvedValue({
        vector: [
          {
            document: 'The forecast task runs after analysis completes...',
            metadata: { source: 'global-workflow' }
          }
        ],
        graph: [
          { name: 'JGLOBAL_FORECAST', type: 'JJob' }
        ]
      });

      const result = await tools.explainWithContext({
        topic: 'forecast task execution',
        detail_level: 'intermediate'
      });

      expect(mockDataAccess.multiSourceSearch).toHaveBeenCalled();
      expect(result.content[0].text).toContain('forecast');
    });

    it('should handle empty multi-source results', async () => {
      mockDataAccess.multiSourceSearch.mockResolvedValue({
        vector: [],
        graph: []
      });

      const result = await tools.explainWithContext({
        topic: 'nonexistent topic'
      });

      const text = result.content[0].text;
      expect(text).toBeDefined();
      expect(text).toContain('Explanation');
    });
  });

  describe('get_knowledge_base_status', () => {
    it('should return comprehensive system status', async () => {
      mockDataAccess.getStatistics.mockResolvedValue({
        vector: {
          totalCollections: 6,
          collections: {
            'global-workflow-docs-v8-2-0': 23624,
            'code-with-context-v8-0-0': 60574
          }
        },
        graph: {
          fileCount: 2758,
          functionCount: 2012,
          classCount: 54,
          relationships: [
            { relationshipType: 'CALLS', count: 2116421 }
          ]
        }
      });

      const result = await tools.getKnowledgeBaseStatus({});

      const text = result.content[0].text;
      expect(text).toContain('Knowledge Base Status');
      expect(text).toContain('2758');
      expect(text).toContain('2012');
      expect(text).toContain('Healthy');
    });

    it('should detect unhealthy vector DB', async () => {
      mockDataAccess.getStatistics.mockResolvedValue({
        vector: { totalCollections: 0, collections: {} },
        graph: { fileCount: 100, functionCount: 50, classCount: 5, relationships: [] }
      });

      const result = await tools.getKnowledgeBaseStatus({});

      const text = result.content[0].text;
      expect(text).toContain('Unhealthy');
    });
  });

  describe('find_related_files', () => {
    it('should find files with similar dependencies', async () => {
      mockDataAccess.findRelatedCode.mockResolvedValue([
        { file: 'scripts/exgdas_analysis.py', similarity: 0.85 },
        { file: 'scripts/exgfs_forecast.py', similarity: 0.72 }
      ]);

      const result = await tools.findRelatedFiles({
        file_path: 'scripts/exglobal_forecast.py',
        max_results: 5
      });

      const text = result.content[0].text;
      expect(text).toBeDefined();
    });

    it('Phase 53 D2: renders file path label, not "Unknown"', async () => {
      // findRelatedCode returns { relatedFiles, imports }; rows use `path`.
      mockDataAccess.findRelatedCode.mockResolvedValue({
        relatedFiles: [
          { path: 'scripts/foo.py', similarity: 0.9 }
        ],
        imports: []
      });

      const result = await tools.findRelatedFiles({
        file_path: 'scripts/exglobal_forecast.py'
      });

      const text = result.content[0].text;
      expect(text).toContain('scripts/foo.py');
      expect(text).not.toMatch(/Unknown/);
    });
  });

  describe('Phase 53 D7: explain_with_context body population', () => {
    it('emits a non-empty body when only `query` and `topic` are supplied', async () => {
      mockDataAccess.multiSourceSearch.mockResolvedValue([
        { document: 'Forecast jobs are sourced from JGLOBAL_FORECAST', metadata: { source: 'docs' }, distance: 0.4 },
        { document: 'Inputs include initial conditions and lateral BCs', metadata: { source: 'docs' }, distance: 0.5 }
      ]);

      const result = await tools.explainWithContext({
        topic: 'GFS forecast pipeline',
        detail_level: 'intermediate'
      });

      const text = result.content[0].text;
      // Body must contain at least one source result, not just a heading
      expect(text.length).toBeGreaterThan(200);
      expect(text).toMatch(/Forecast jobs|Inputs/);
    });
  });

  describe('Error Handling', () => {
    it('should handle database connection errors', async () => {
      mockDataAccess.multiSourceSearch.mockRejectedValue(new Error('Connection refused'));

      const result = await tools.searchDocumentation({
        query: 'test',
        max_results: 3
      });

      expect(result.content[0].text).toMatch(/error/i);
      expect(result.content[0].text).toContain('Connection refused');
    });

    it('should handle initialization errors', async () => {
      tools.initializationError = new Error('ChromaDB not available');

      const result = await tools.searchDocumentation({
        query: 'test',
        max_results: 3
      });

      expect(result.content[0].text).toMatch(/not available/i);
    });
  });
});
