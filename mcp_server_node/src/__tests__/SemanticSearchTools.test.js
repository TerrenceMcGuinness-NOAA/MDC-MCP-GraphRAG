/**
 * Unit Tests for SemanticSearchTools
 * Week 3 Phase 4: Test Suite Development
 * 
 * Tests 7 tools:
 * 1. search_documentation
 * 2. search_ee2_standards
 * 3. find_similar_code
 * 4. explain_with_context
 * 5. analyze_ee2_compliance
 * 6. generate_compliance_report
 * 7. get_knowledge_base_status
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import SemanticSearchTools from '../tools/SemanticSearchTools.js';

describe('SemanticSearchTools', () => {
  let tools;
  let mockDataAccess;

  beforeEach(() => {
    // Mock UnifiedDataAccess
    mockDataAccess = {
      vectorDb: {
        query: vi.fn(),
        getCollectionStats: vi.fn(),
        healthCheck: vi.fn()
      },
      graphDb: {
        query: vi.fn(),
        healthCheck: vi.fn()
      },
      hybridSearch: vi.fn()
    };

    tools = new SemanticSearchTools(mockDataAccess);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe('search_documentation', () => {
    it('should return semantic search results from ChromaDB', async () => {
      // Mock vector DB response
      mockDataAccess.vectorDb.query.mockResolvedValue({
        documents: [['Sample workflow documentation']],
        metadatas: [[{ source: 'global-workflow', url: 'https://...' }]],
        distances: [[0.85]]
      });

      const result = await tools.searchDocumentation({
        query: 'How do I run the global workflow?',
        maxResults: 3
      });

      expect(mockDataAccess.vectorDb.query).toHaveBeenCalledWith(
        expect.objectContaining({
          queryTexts: ['How do I run the global workflow?'],
          nResults: 3
        })
      );

      expect(result.content).toBeDefined();
      expect(result.content[0].type).toBe('text');
      expect(result.content[0].text).toContain('Sample workflow documentation');
    });

    it('should handle empty results gracefully', async () => {
      mockDataAccess.vectorDb.query.mockResolvedValue({
        documents: [[]],
        metadatas: [[]],
        distances: [[]]
      });

      const result = await tools.searchDocumentation({
        query: 'nonexistent query',
        maxResults: 3
      });

      expect(result.content[0].text).toContain('No results found');
    });

    it('should respect similarity threshold', async () => {
      mockDataAccess.vectorDb.query.mockResolvedValue({
        documents: [['Low relevance doc']],
        metadatas: [[{ source: 'test' }]],
        distances: [[0.95]] // High distance = low similarity
      });

      const result = await tools.searchDocumentation({
        query: 'test query',
        maxResults: 3,
        similarityThreshold: 0.3 // Only accept distances < 0.7 (similarity > 0.3)
      });

      // Should filter out low similarity results
      expect(result.content[0].text).toContain('No results found');
    });
  });

  describe('find_similar_code', () => {
    it('should find code patterns with vector similarity', async () => {
      mockDataAccess.hybridSearch.mockResolvedValue({
        vectorResults: [
          {
            text: 'def process_data(items): ...',
            metadata: { file: 'utils.py', type: 'function' },
            distance: 0.75
          }
        ],
        graphResults: []
      });

      const result = await tools.findSimilarCode({
        codePattern: 'function that processes data',
        maxResults: 5
      });

      expect(mockDataAccess.hybridSearch).toHaveBeenCalled();
      expect(result.content[0].text).toContain('def process_data');
    });

    it('should include graph context when available', async () => {
      mockDataAccess.hybridSearch.mockResolvedValue({
        vectorResults: [
          {
            text: 'def calculate_total(items): ...',
            metadata: { file: 'pricing.py' },
            distance: 0.8
          }
        ],
        graphResults: [
          {
            callers: ['processOrder', 'generateInvoice'],
            callees: ['validateItems', 'applyDiscount']
          }
        ]
      });

      const result = await tools.findSimilarCode({
        codePattern: 'calculate totals',
        includeContext: true
      });

      expect(result.content[0].text).toContain('processOrder');
      expect(result.content[0].text).toContain('validateItems');
    });
  });

  describe('get_knowledge_base_status', () => {
    it('should return comprehensive system status', async () => {
      mockDataAccess.vectorDb.getCollectionStats.mockResolvedValue({
        name: 'global-workflow-docs-v2-0-0',
        count: 490
      });

      mockDataAccess.graphDb.query.mockResolvedValue([
        { nodeCount: 937, relationshipCount: 4764 }
      ]);

      mockDataAccess.vectorDb.healthCheck.mockResolvedValue(true);
      mockDataAccess.graphDb.healthCheck.mockResolvedValue(true);

      const result = await tools.getKnowledgeBaseStatus();

      expect(result.content[0].text).toContain('490');
      expect(result.content[0].text).toContain('937');
      expect(result.content[0].text).toContain('4764');
      expect(result.content[0].text).toContain('healthy');
    });

    it('should detect unhealthy components', async () => {
      mockDataAccess.vectorDb.healthCheck.mockResolvedValue(false);
      mockDataAccess.graphDb.healthCheck.mockResolvedValue(true);

      const result = await tools.getKnowledgeBaseStatus();

      expect(result.content[0].text).toContain('ChromaDB: [ERROR]');
      expect(result.content[0].text).toContain('Neo4j: [OK]');
    });
  });

  describe('explain_with_context', () => {
    it('should provide contextual explanations using RAG', async () => {
      mockDataAccess.hybridSearch.mockResolvedValue({
        vectorResults: [
          {
            text: 'The forecast task runs after analysis completes...',
            metadata: { source: 'global-workflow' },
            distance: 0.7
          }
        ],
        graphResults: [
          {
            relatedComponents: ['GDAS', 'GFS', 'Rocoto']
          }
        ]
      });

      const result = await tools.explainWithContext({
        topic: 'forecast task execution',
        detailLevel: 'intermediate'
      });

      expect(mockDataAccess.hybridSearch).toHaveBeenCalled();
      expect(result.content[0].text).toContain('forecast');
      expect(result.content[0].text.length).toBeGreaterThan(100);
    });
  });

  describe('search_ee2_standards', () => {
    it('should search EE2 compliance documentation', async () => {
      mockDataAccess.vectorDb.query.mockResolvedValue({
        documents: [['EE2 standard: Environment variables must use ${VAR} syntax']],
        metadatas: [[{ source: 'ee2-standards', category: 'environment_variables' }]],
        distances: [[0.72]]
      });

      const result = await tools.searchEE2Standards({
        query: 'environment variable standards',
        category: 'environment_variables'
      });

      expect(result.content[0].text).toContain('Environment variables');
      expect(result.content[0].text).toContain('${VAR}');
    });
  });

  describe('analyze_ee2_compliance', () => {
    it('should analyze code for EE2 compliance', async () => {
      const testCode = `
export FOO=bar  # Non-compliant
export BAR=\${HOME}/data  # Compliant
      `;

      const result = await tools.analyzeEE2Compliance({
        content: testCode,
        analysisType: 'environment_variables'
      });

      expect(result.content[0].text).toContain('compliance');
      // Should detect issues
      expect(result.content[0].text).toMatch(/violation|non-compliant|issue/i);
    });
  });

  describe('generate_compliance_report', () => {
    it('should generate comprehensive compliance report', async () => {
      mockDataAccess.vectorDb.query.mockResolvedValue({
        documents: [['Standard 1'], ['Standard 2']],
        metadatas: [[{ category: 'env' }], [{ category: 'workflow' }]],
        distances: [[0.5], [0.6]]
      });

      const result = await tools.generateComplianceReport({
        scope: 'summary',
        format: 'markdown'
      });

      expect(result.content[0].text).toContain('Compliance Report');
      expect(result.content[0].text).toContain('##'); // Markdown headers
    });
  });

  describe('Error Handling', () => {
    it('should handle database connection errors', async () => {
      mockDataAccess.vectorDb.query.mockRejectedValue(new Error('Connection refused'));

      const result = await tools.searchDocumentation({
        query: 'test',
        maxResults: 3
      });

      expect(result.content[0].text).toContain('error');
      expect(result.content[0].text).toContain('Connection refused');
    });

    it('should validate required parameters', async () => {
      await expect(
        tools.searchDocumentation({}) // Missing query
      ).rejects.toThrow(/query.*required/i);
    });
  });
});
