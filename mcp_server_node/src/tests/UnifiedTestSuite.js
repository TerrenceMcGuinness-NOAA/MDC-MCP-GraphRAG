#!/usr/bin/env node

/**
 * Unified Test Suite for MCP Server
 * 
 * Consolidates all testing functionality into a single, comprehensive
 * test framework that validates all components of the unified server.
 * 
 * @version 2.0.0
 * @author NOAA EMC Global Workflow Team
 */

import { UnifiedMCPServer } from '../UnifiedMCPServer.js';
import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export class UnifiedTestSuite {
  constructor(options = {}) {
    this.options = {
      verbose: options.verbose || false,
      timeout: options.timeout || 30000,
      ...options
    };
    
    this.results = {
      total: 0,
      passed: 0,
      failed: 0,
      skipped: 0,
      errors: []
    };
    
    this.server = null;
  }

  /**
   * Run all test suites
   */
  async runAll() {
    console.error('🧪 Running Unified MCP Server Test Suite\n');
    
    const testSuites = [
      { name: 'Server Initialization', fn: this.testServerInitialization.bind(this) },
      { name: 'Core Workflow Tools', fn: this.testWorkflowTools.bind(this) },
      { name: 'RAG Components', fn: this.testRAGTools.bind(this) },
      { name: 'GitHub Integration', fn: this.testGitHubTools.bind(this) },
      { name: 'Error Handling', fn: this.testErrorHandling.bind(this) },
      { name: 'Performance', fn: this.testPerformance.bind(this) }
    ];

    for (const suite of testSuites) {
      console.error(`\n[INFO] Testing: ${suite.name}`);
      console.error('='.repeat(50));
      
      try {
        await suite.fn();
      } catch (error) {
        this.recordError(suite.name, error);
      }
    }

    await this.generateReport();
    return this.results;
  }

  /**
   * Test server initialization and configuration
   */
  async testServerInitialization() {
    // Test 1: Default configuration
    await this.runTest('Default Configuration', async () => {
      this.server = new UnifiedMCPServer();
      const stats = this.server.server.getStats();
      this.assert(stats.toolCount > 0, 'Server should have tools registered');
      this.assert(stats.name.includes('unified'), 'Server should have unified name');
    });

    // Test 2: Core-only configuration
    await this.runTest('Core-only Configuration', async () => {
      const coreServer = new UnifiedMCPServer({ enableRAG: false, enableGitHub: false });
      const stats = coreServer.server.getStats();
      this.assert(stats.toolCount >= 4, 'Core server should have at least 4 tools');
    });

    // Test 3: Configuration scenarios
    await this.runTest('Configuration Scenarios', async () => {
      const configs = ['full', 'core', 'rag', 'github'];
      for (const scenario of configs) {
        const config = UnifiedMCPServer.getConfiguration(scenario);
        this.assert(typeof config === 'object', `Configuration ${scenario} should be an object`);
      }
    });
  }

  /**
   * Test core workflow tools
   */
  async testWorkflowTools() {
    if (!this.server) {
      this.server = new UnifiedMCPServer();
    }

    // Test 1: get_workflow_structure
    await this.runTest('get_workflow_structure', async () => {
      const result = await this.callTool('get_workflow_structure', {});
      this.assert(result.includes('NOAA Global Workflow'), 'Should return workflow overview');
      this.assert(result.includes('components'), 'Should include components information');
    });

    // Test 2: list_job_scripts  
    await this.runTest('list_job_scripts', async () => {
      const result = await this.callTool('list_job_scripts', { format: 'summary' });
      this.assert(result.includes('Job Scripts'), 'Should return job scripts summary');
    });

    // Test 3: get_system_configs
    await this.runTest('get_system_configs', async () => {
      const result = await this.callTool('get_system_configs', {});
      this.assert(result.includes('configs') || result.includes('Error'), 'Should return configs or handle error gracefully');
    });

    // Test 4: explain_workflow_component
    await this.runTest('explain_workflow_component', async () => {
      const result = await this.callTool('explain_workflow_component', { component: 'jobs' });
      this.assert(result.includes('Component') || result.includes('not found'), 'Should explain component or handle missing gracefully');
    });
  }

  /**
   * Test RAG tools functionality
   */
  async testRAGTools() {
    const ragServer = new UnifiedMCPServer({ enableRAG: true, enableGitHub: false });
    
    // Test 1: search_documentation
    await this.runTest('search_documentation', async () => {
      const result = await this.callTool('search_documentation', { query: 'workflow' }, ragServer);
      this.assert(result.length > 0, 'Should return search results');
      this.assert(!result.includes('undefined'), 'Should not contain undefined values');
    });

    // Test 2: explain_with_context
    await this.runTest('explain_with_context', async () => {
      const result = await this.callTool('explain_with_context', { topic: 'analysis' }, ragServer);
      this.assert(result.includes('analysis') || result.includes('Analysis'), 'Should explain analysis concept');
    });

    // Test 3: find_similar_code
    await this.runTest('find_similar_code', async () => {
      const result = await this.callTool('find_similar_code', { code_pattern: 'function' }, ragServer);
      this.assert(result.length > 0, 'Should return results or appropriate message');
    });

    // Test 4: get_operational_guidance
    await this.runTest('get_operational_guidance', async () => {
      const result = await this.callTool('get_operational_guidance', { 
        operation: 'restart workflow',
        platform: 'hera'
      }, ragServer);
      this.assert(result.includes('Operational Guidance'), 'Should return guidance format');
      this.assert(result.includes('hera'), 'Should include platform-specific info');
    });
  }

  /**
   * Test GitHub integration tools
   */
  async testGitHubTools() {
    const githubServer = new UnifiedMCPServer({ 
      enableRAG: false, 
      enableGitHub: true,
      githubToken: process.env.GITHUB_TOKEN 
    });

    // Test 1: analyze_workflow_dependencies
    await this.runTest('analyze_workflow_dependencies', async () => {
      const result = await this.callTool('analyze_workflow_dependencies', { 
        component: 'JGDAS_ATMOS_ANALYSIS' 
      }, githubServer);
      this.assert(result.includes('Dependency Analysis') || result.includes('not available'), 
        'Should return dependency analysis or unavailable message');
    });

    // Test 2: search_issues (if GitHub token available)
    if (process.env.GITHUB_TOKEN) {
      await this.runTest('search_issues', async () => {
        const result = await this.callTool('search_issues', { 
          query: 'workflow',
          repository: 'global-workflow'
        }, githubServer);
        this.assert(result.includes('Issues') || result.includes('Found'), 'Should return issue search results');
      });
    } else {
      this.skipTest('search_issues', 'No GitHub token available');
    }

    // Test 3: get_pull_requests (if GitHub token available)
    if (process.env.GITHUB_TOKEN) {
      await this.runTest('get_pull_requests', async () => {
        const result = await this.callTool('get_pull_requests', { 
          repository: 'global-workflow',
          limit: 5
        }, githubServer);
        this.assert(result.includes('Pull Requests') || result.includes('No'), 'Should return PR results');
      });
    } else {
      this.skipTest('get_pull_requests', 'No GitHub token available');
    }
  }

  /**
   * Test error handling and edge cases
   */
  async testErrorHandling() {
    if (!this.server) {
      this.server = new UnifiedMCPServer();
    }

    // Test 1: Invalid tool call
    await this.runTest('Invalid Tool Name', async () => {
      try {
        await this.callTool('nonexistent_tool', {});
        this.assert(false, 'Should throw error for invalid tool');
      } catch (error) {
        this.assert(error.message.includes('not found') || error.message.includes('Tool'), 
          'Should return appropriate error message');
      }
    });

    // Test 2: Missing required parameters
    await this.runTest('Missing Required Parameters', async () => {
      try {
        const result = await this.callTool('explain_workflow_component', {});
        this.assert(result.includes('error') || result.includes('Error'), 
          'Should handle missing parameters gracefully');
      } catch (error) {
        // Expected behavior
        this.assert(true, 'Should handle missing parameters');
      }
    });

    // Test 3: Health check functionality
    await this.runTest('Health Check', async () => {
      const result = await this.callTool('health_check', { detailed: true });
      this.assert(result.includes('Health Check'), 'Should return health check results');
      this.assert(result.includes('components'), 'Should include component status');
    });
  }

  /**
   * Test performance characteristics
   */
  async testPerformance() {
    if (!this.server) {
      this.server = new UnifiedMCPServer();
    }

    // Test 1: Response time for basic operations
    await this.runTest('Response Time', async () => {
      const start = Date.now();
      await this.callTool('get_server_info', {});
      const duration = Date.now() - start;
      
      this.assert(duration < 5000, `Server info should respond within 5s (took ${duration}ms)`);
    });

    // Test 2: Concurrent tool calls
    await this.runTest('Concurrent Operations', async () => {
      const promises = [
        this.callTool('get_server_info', {}),
        this.callTool('health_check', {}),
        this.callTool('get_workflow_structure', {})
      ];

      const start = Date.now();
      const results = await Promise.all(promises);
      const duration = Date.now() - start;

      this.assert(results.length === 3, 'All concurrent operations should complete');
      this.assert(duration < 10000, `Concurrent operations should complete within 10s (took ${duration}ms)`);
    });
  }

  /**
   * Helper methods for test execution
   */
  async runTest(testName, testFn) {
    this.results.total++;
    
    try {
      if (this.options.verbose) {
        console.error(`  [SEARCH] ${testName}`);
      }
      
      await testFn();
      this.results.passed++;
      
      if (this.options.verbose) {
        console.error(`  [OK] ${testName} - PASSED`);
      } else {
        process.stderr.write('[OK] ');
      }
    } catch (error) {
      this.results.failed++;
      this.results.errors.push({ test: testName, error: error.message });
      
      if (this.options.verbose) {
        console.error(`  [ERROR] ${testName} - FAILED: ${error.message}`);
      } else {
        process.stderr.write('[ERROR] ');
      }
    }
  }

  skipTest(testName, reason) {
    this.results.total++;
    this.results.skipped++;
    
    if (this.options.verbose) {
      console.error(`  [SKIP] ${testName} - SKIPPED: ${reason}`);
    } else {
      process.stderr.write('[SKIP] ');
    }
  }

  async callTool(toolName, args, server = null) {
    const targetServer = server || this.server;
    const tool = targetServer.server.tools.get(toolName);
    
    if (!tool) {
      throw new Error(`Tool not found: ${toolName}`);
    }
    
    return await tool.handler(args);
  }

  assert(condition, message) {
    if (!condition) {
      throw new Error(message);
    }
  }

  recordError(suiteName, error) {
    this.results.failed++;
    this.results.errors.push({ 
      test: suiteName, 
      error: error.message,
      stack: error.stack
    });
  }

  /**
   * Generate comprehensive test report
   */
  async generateReport() {
    console.error('\n\n[STATS] Test Results Summary');
    console.error('='.repeat(50));
    
    const passRate = ((this.results.passed / this.results.total) * 100).toFixed(1);
    
    console.error(`Total Tests: ${this.results.total}`);
    console.error(`[OK] Passed: ${this.results.passed}`);
    console.error(`[ERROR] Failed: ${this.results.failed}`);
    console.error(`[SKIP] Skipped: ${this.results.skipped}`);
    console.error(`📈 Pass Rate: ${passRate}%`);
    
    if (this.results.failed > 0) {
      console.error('\n[ERROR] Failed Tests:');
      console.error('-'.repeat(30));
      
      this.results.errors.forEach((error, index) => {
        console.error(`${index + 1}. ${error.test}: ${error.error}`);
      });
    }

    // Generate detailed report file
    const report = {
      timestamp: new Date().toISOString(),
      summary: this.results,
      passRate: parseFloat(passRate),
      environment: {
        nodeVersion: process.version,
        platform: process.platform,
        githubToken: !!process.env.GITHUB_TOKEN
      }
    };

    try {
      const reportPath = path.join(__dirname, '../../test-results.json');
      await fs.writeFile(reportPath, JSON.stringify(report, null, 2));
      console.error(`\n[INFO] Detailed report saved to: ${reportPath}`);
    } catch (error) {
      console.error(`[WARN] Could not save report: ${error.message}`);
    }

    console.error('\n🎯 Test Suite Complete\n');
  }
}

// Main execution when run as script
if (import.meta.url === `file://${process.argv[1]}`) {
  const verbose = process.argv.includes('--verbose') || process.argv.includes('-v');
  const suite = new UnifiedTestSuite({ verbose });
  
  suite.runAll()
    .then(results => {
      const exitCode = results.failed > 0 ? 1 : 0;
      process.exit(exitCode);
    })
    .catch(error => {
      console.error(`[ERROR] Test suite failed: ${error.message}`);
      process.exit(1);
    });
}