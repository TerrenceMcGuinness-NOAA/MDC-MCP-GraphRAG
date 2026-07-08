/**
 * Vitest Setup File - Global Test Configuration
 * Week 3 Phase 4: Test Suite Development
 */

import { beforeAll, afterAll, vi } from 'vitest';

// Mock environment variables for testing
process.env.MCP_WORKFLOW_ROOT = process.env.MCP_WORKFLOW_ROOT || '/mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow_develop';
process.env.CHROMA_SERVER_URL = process.env.CHROMA_SERVER_URL || 'http://localhost:8080';
process.env.NEO4J_URI = process.env.NEO4J_URI || 'bolt://localhost:7687';
process.env.NEO4J_USER = process.env.NEO4J_USER || 'neo4j';
process.env.NEO4J_PASSWORD = process.env.NEO4J_PASSWORD || 'gfsworkflow2025';

// Global test utilities
global.testHelpers = {
  /**
   * Wait for a condition to be true
   * @param {Function} condition - Function that returns boolean
   * @param {number} timeout - Max wait time in ms
   * @param {number} interval - Check interval in ms
   */
  async waitFor(condition, timeout = 5000, interval = 100) {
    const startTime = Date.now();
    while (Date.now() - startTime < timeout) {
      if (await condition()) {
        return true;
      }
      await new Promise(resolve => setTimeout(resolve, interval));
    }
    throw new Error(`Condition not met within ${timeout}ms`);
  },

  /**
   * Create a mock MCP tool response
   * @param {Object} content - Tool response content
   */
  mockToolResponse(content) {
    return {
      content: [
        {
          type: 'text',
          text: typeof content === 'string' ? content : JSON.stringify(content, null, 2)
        }
      ]
    };
  },

  /**
   * Mock database connection for offline testing
   */
  mockDatabaseConnection() {
    return {
      connected: true,
      query: vi.fn().mockResolvedValue([]),
      close: vi.fn().mockResolvedValue(undefined)
    };
  }
};

// Global setup
beforeAll(async () => {
  console.log('\n🧪 Test Suite Starting - Week 3 Phase 4');
  console.log('=====================================');
  console.log(`Environment: ${process.env.NODE_ENV || 'test'}`);
  console.log(`Workflow Root: ${process.env.MCP_WORKFLOW_ROOT}`);
  console.log(`ChromaDB URL: ${process.env.CHROMA_SERVER_URL}`);
  console.log(`Neo4j URI: ${process.env.NEO4J_URI}`);
  console.log('=====================================\n');
});

// Global teardown
afterAll(async () => {
  console.log('\n[OK] Test Suite Complete');
  console.log('=====================================\n');
});

export default {
  testHelpers: global.testHelpers
};
