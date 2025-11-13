#!/usr/bin/env node

/**
 * Enhanced RAG System Test Suite
 *
 * Comprehensive testing framework for the enhanced RAG system including:
 * - URL ingestion pipeline validation
 * - Content extraction quality testing
 * - Vector database functionality verification
 * - Multi-source search accuracy testing
 * - Performance benchmarking
 * - Integration testing with MCP tools
 *
 * Usage:
 *   node test-enhanced-rag-system.js [test-suite]
 *
 * Test Suites:
 *   --quick         Basic functionality tests (5 min)
 *   --full          Complete test suite (30 min)
 *   --ingestion     Test URL ingestion pipeline
 *   --search        Test search functionality
 *   --performance   Performance benchmarks
 *   --integration   MCP integration tests
 *
 * @version 1.0.0
 * @author NOAA EMC Global Workflow Team
 */

import { DocumentationIngester } from './src/ingestion/DocumentationIngester.js';
import { EnhancedVectorStore } from './src/rag/EnhancedVectorStore.js';
import { EnhancedRAGTools } from './src/tools/EnhancedRAGTools.js';
import { URLFetcher } from './src/ingestion/URLFetcher.js';
import { ContentExtractor } from './src/ingestion/ContentExtractor.js';
import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

class EnhancedRAGTestSuite {
  constructor() {
    this.testResults = {
      startTime: new Date(),
      endTime: null,
      totalTests: 0,
      passed: 0,
      failed: 0,
      skipped: 0,
      errors: [],
      performance: {},
      coverage: {}
    };

    this.testConfig = {
      outputDir: path.join(__dirname, 'test-output'),
      sampleUrls: [
        'https://ufs-weather-model.readthedocs.io/en/latest/',
        'https://christopherwharrop.github.io/rocoto/',
        'https://github.com/NOAA-EMC/GSI',
        'https://nws-hpc-standards.readthedocs.io/en/latest/'
      ],
      testQueries: [
        'UFS weather model installation',
        'Rocoto workflow dependencies',
        'GSI data assimilation',
        'EE2 compliance standards',
        'global workflow job scripts',
        'NOAA HPC systems'
      ]
    };

    this.components = {
      urlFetcher: null,
      contentExtractor: null,
      documentationIngester: null,
      vectorStore: null,
      ragTools: null
    };
  }

  /**
   * Parse command line arguments and run tests
   */
  async run() {
    const args = process.argv.slice(2);
    const testSuite = args[0] || '--quick';

    console.error('🧪 Enhanced RAG System Test Suite');
    console.error('═══════════════════════════════════════');
    console.error(`Test Suite: ${testSuite}`);
    console.error(`Start Time: ${this.testResults.startTime.toISOString()}\n`);

    try {
      await this.setupTestEnvironment();

      switch (testSuite) {
        case '--quick':
          await this.runQuickTests();
          break;
        case '--full':
          await this.runFullTests();
          break;
        case '--ingestion':
          await this.runIngestionTests();
          break;
        case '--search':
          await this.runSearchTests();
          break;
        case '--performance':
          await this.runPerformanceTests();
          break;
        case '--integration':
          await this.runIntegrationTests();
          break;
        default:
          console.error(`❌ Unknown test suite: ${testSuite}`);
          this.showHelp();
          process.exit(1);
      }

      await this.generateTestReport();
      this.showFinalResults();

    } catch (error) {
      console.error(`💥 Test suite failed: ${error.message}`);
      console.error(error.stack);
      process.exit(1);
    }
  }

  /**
   * Show help information
   */
  showHelp() {
    console.log(`
Usage: node test-enhanced-rag-system.js [test-suite]

Test Suites:
  --quick         Basic functionality tests (~5 minutes)
  --full          Complete test suite (~30 minutes)
  --ingestion     Test URL ingestion pipeline
  --search        Test search functionality
  --performance   Performance benchmarks
  --integration   MCP integration tests

Examples:
  node test-enhanced-rag-system.js --quick
  node test-enhanced-rag-system.js --ingestion
  node test-enhanced-rag-system.js --full
`);
  }

  /**
   * Setup test environment
   */
  async setupTestEnvironment() {
    console.error('🔧 Setting up test environment...');

    // Create test output directory
    await fs.mkdir(this.testConfig.outputDir, { recursive: true });

    // Initialize components
    this.components.urlFetcher = new URLFetcher({
      enableCaching: true,
      cacheDirectory: path.join(this.testConfig.outputDir, 'cache'),
      rateLimit: 5 // Higher rate for testing
    });

    this.components.contentExtractor = new ContentExtractor({
      chunkSize: 500, // Smaller chunks for testing
      chunkOverlap: 100
    });

    this.components.documentationIngester = new DocumentationIngester({
      outputDirectory: this.testConfig.outputDir,
      maxConcurrentFetches: 2,
      enableProgressLogging: false // Quiet during tests
    });

    this.components.vectorStore = new EnhancedVectorStore({
      knowledgeBasePath: this.testConfig.outputDir,
      enableExternalSources: true
    });

    this.components.ragTools = new EnhancedRAGTools(this.testConfig.outputDir);

    console.error('✅ Test environment ready\n');
  }

  /**
   * Run quick functionality tests
   */
  async runQuickTests() {
    console.error('⚡ Running Quick Tests...\n');

    await this.testURLFetcher();
    await this.testContentExtractor();
    await this.testVectorStoreBasics();
    await this.testSearchFunctionality();
  }

  /**
   * Run complete test suite
   */
  async runFullTests() {
    console.error('🔬 Running Full Test Suite...\n');

    await this.testURLFetcher();
    await this.testContentExtractor();
    await this.testDocumentationIngester();
    await this.testVectorStoreBasics();
    await this.testMultiSourceSearch();
    await this.testEE2Compliance();
    await this.testSearchFunctionality();
    await this.runPerformanceTests();
    await this.runIntegrationTests();
  }

  /**
   * Run ingestion pipeline tests
   */
  async runIngestionTests() {
    console.error('🔄 Running Ingestion Tests...\n');

    await this.testURLFetcher();
    await this.testContentExtractor();
    await this.testDocumentationIngester();
  }

  /**
   * Run search functionality tests
   */
  async runSearchTests() {
    console.error('🔍 Running Search Tests...\n');

    await this.testVectorStoreBasics();
    await this.testMultiSourceSearch();
    await this.testSearchFunctionality();
    await this.testEE2Compliance();
  }

  /**
   * Run performance benchmarks
   */
  async runPerformanceTests() {
    console.error('⏱️ Running Performance Tests...\n');

    await this.benchmarkURLFetching();
    await this.benchmarkContentExtraction();
    await this.benchmarkSearchPerformance();
  }

  /**
   * Run MCP integration tests
   */
  async runIntegrationTests() {
    console.error('🔗 Running Integration Tests...\n');

    await this.testMCPToolIntegration();
  }

  // Individual test methods

  async testURLFetcher() {
    const testName = 'URL Fetcher';
    console.error(`📡 Testing ${testName}...`);

    try {
      await this.components.urlFetcher.initialize();

      // Test basic URL fetching
      const testUrl = 'https://httpbin.org/json';
      const result = await this.components.urlFetcher.fetch(testUrl);

      this.assert(result.success, 'URL fetch should succeed');
      this.assert(result.content, 'Should have content');
      this.assert(result.metadata, 'Should have metadata');

      // Test caching
      const cachedResult = await this.components.urlFetcher.fetch(testUrl);
      this.assert(cachedResult.success, 'Cached fetch should succeed');

      // Test validation
      const validation = await this.components.urlFetcher.validateUrl(testUrl);
      this.assert(validation.accessible, 'URL should be accessible');

      this.pass(testName);

    } catch (error) {
      this.fail(testName, error);
    }
  }

  async testContentExtractor() {
    const testName = 'Content Extractor';
    console.error(`📝 Testing ${testName}...`);

    try {
      // Test HTML extraction
      const htmlContent = `
        <html>
          <head><title>Test Document</title></head>
          <body>
            <h1>Introduction</h1>
            <p>This is a comprehensive test document for content extraction. It contains multiple paragraphs of text to ensure that the content extraction system can properly process HTML documents and create meaningful chunks of searchable content. The document includes various sections with different types of information.</p>
            <h2>Technical Details</h2>
            <p>Some technical information here about the system architecture, implementation details, and configuration options. This section provides in-depth coverage of the technical aspects that users need to understand.</p>
            <h3>Configuration</h3>
            <p>Configuration parameters and setup instructions are provided here. This includes environment variables, file paths, and system requirements that must be met for proper operation.</p>
          </body>
        </html>
      `;

      const mockResponse = {
        url: 'https://example.com/test.html',
        content: htmlContent,
        metadata: {
          contentType: 'text/html',
          contentLength: htmlContent.length,
          lastModified: new Date().toISOString()
        }
      };

      const result = await this.components.contentExtractor.extractContent(mockResponse);

      this.assert(result.extractedData, 'Should extract data');
      this.assert(result.chunks.length > 0, 'Should create chunks');
      this.assert(result.extractedData.title, 'Should extract title');
      this.assert(result.extractedData.cleanText, 'Should have clean text');

      // Test quality scoring
      const firstChunk = result.chunks[0];
      this.assert(firstChunk.qualityScore >= 0, 'Quality score should be non-negative');
      this.assert(firstChunk.metadata, 'Chunk should have metadata');

      this.pass(testName);

    } catch (error) {
      this.fail(testName, error);
    }
  }

  async testDocumentationIngester() {
    const testName = 'Documentation Ingester';
    console.error(`🔄 Testing ${testName}...`);

    try {
      await this.components.documentationIngester.initialize();

      // Test URL validation
      const validationResults = await this.components.documentationIngester.validateAllUrls();
      this.assert(Array.isArray(validationResults), 'Should return validation array');

      // Test ingestion planning
      const stats = this.components.documentationIngester.getStats();
      this.assert(stats.totalUrls > 0, 'Should find URLs to ingest');
      this.assert(Object.keys(stats.categoryStats).length > 0, 'Should categorize URLs');

      this.pass(testName);

    } catch (error) {
      this.fail(testName, error);
    }
  }

  async testVectorStoreBasics() {
    const testName = 'Vector Store Basics';
    console.error(`🗄️ Testing ${testName}...`);

    try {
      await this.components.vectorStore.initialize();

      const stats = this.components.vectorStore.getStats();
      this.assert(typeof stats === 'object', 'Should return stats object');

      // Test health check
      const health = this.components.vectorStore.getSourceHealth();
      this.assert(health.timestamp, 'Health check should have timestamp');
      this.assert(health.sources, 'Health check should have sources');

      this.pass(testName);

    } catch (error) {
      this.fail(testName, error);
    }
  }

  async testMultiSourceSearch() {
    const testName = 'Multi-Source Search';
    console.error(`🔍 Testing ${testName}...`);

    try {
      await this.components.vectorStore.initialize();

      // Test basic search
      const searchResults = await this.components.vectorStore.searchDocumentation('workflow configuration', {
        maxResults: 5
      });

      this.assert(Array.isArray(searchResults), 'Should return array of results');

      // Test source-specific search
      const localResults = await this.components.vectorStore.searchSource('local', 'job script', {
        maxResults: 3
      });

      this.assert(Array.isArray(localResults), 'Should return local search results');

      // Test search with attribution
      const attributedResults = await this.components.vectorStore.searchWithAttribution('analysis system', {
        maxResults: 3
      });

      if (attributedResults.length > 0) {
        this.assert(attributedResults[0].attribution, 'Results should have attribution');
      }

      this.pass(testName);

    } catch (error) {
      this.fail(testName, error);
    }
  }

  async testEE2Compliance() {
    const testName = 'EE2 Compliance Tools';
    console.error(`📋 Testing ${testName}...`);

    try {
      await this.components.vectorStore.initialize();

      // Test compliance analysis
      const testCode = `#!/bin/bash
        export DATA=/tmp/test
        if [[ ! -d "\${DATA}" ]]; then
          mkdir -p "\${DATA}"
        fi
        echo "Test completed successfully"
      `;

      const analysisResult = await this.components.ragTools.analyzeEE2Compliance({
        content: testCode,
        analysis_type: 'comprehensive'
      });

      this.assert(typeof analysisResult === 'string', 'Should return analysis string');
      this.assert(analysisResult.includes('EE2'), 'Should mention EE2');

      // Test standards search
      const standardsResult = await this.components.ragTools.searchEE2Standards({
        query: 'environment variables'
      });

      this.assert(typeof standardsResult === 'string', 'Should return standards search string');

      this.pass(testName);

    } catch (error) {
      this.fail(testName, error);
    }
  }

  async testSearchFunctionality() {
    const testName = 'Search Functionality';
    console.error(`🎯 Testing ${testName}...`);

    try {
      await this.components.ragTools.initialize();

      for (const query of this.testConfig.testQueries.slice(0, 3)) { // Test first 3 queries
        const result = await this.components.ragTools.searchDocumentation({ query });

        this.assert(typeof result === 'string', `Search for "${query}" should return string`);
        this.assert(result.length > 50, `Search for "${query}" should return substantial content`);
      }

      this.pass(testName);

    } catch (error) {
      this.fail(testName, error);
    }
  }

  async testMCPToolIntegration() {
    const testName = 'MCP Tool Integration';
    console.error(`🔗 Testing ${testName}...`);

    try {
      await this.components.ragTools.initialize();

      // Test knowledge base status
      const statusResult = await this.components.ragTools.getKnowledgeBaseStatus({
        include_detailed_stats: true
      });

      this.assert(typeof statusResult === 'string', 'Status should return string');
      this.assert(statusResult.includes('Knowledge Base Status'), 'Should include status header');

      // Test contextual explanation
      const explanationResult = await this.components.ragTools.explainWithContext({
        topic: 'workflow job scheduling',
        detail_level: 'basic'
      });

      this.assert(typeof explanationResult === 'string', 'Explanation should return string');
      this.assert(explanationResult.length > 100, 'Explanation should be substantial');

      this.pass(testName);

    } catch (error) {
      this.fail(testName, error);
    }
  }

  // Performance benchmarking

  async benchmarkURLFetching() {
    const testName = 'URL Fetching Performance';
    console.error(`⏱️ Benchmarking ${testName}...`);

    try {
      const startTime = Date.now();
      const promises = this.testConfig.sampleUrls.slice(0, 2).map(url =>
        this.components.urlFetcher.validateUrl(url)
      );

      const results = await Promise.all(promises);
      const endTime = Date.now();

      const duration = endTime - startTime;
      const avgTime = duration / results.length;

      this.testResults.performance.urlFetchingMs = avgTime;

      console.error(`   Average URL validation time: ${avgTime.toFixed(0)}ms`);

      this.pass(testName);

    } catch (error) {
      this.fail(testName, error);
    }
  }

  async benchmarkContentExtraction() {
    const testName = 'Content Extraction Performance';
    console.error(`⏱️ Benchmarking ${testName}...`);

    try {
      const sampleContent = 'Lorem ipsum '.repeat(1000); // ~10KB of text
      const mockResponse = {
        url: 'https://example.com/large-doc.html',
        content: `<html><body><h1>Test</h1>${sampleContent}</body></html>`,
        metadata: {
          contentType: 'text/html',
          contentLength: sampleContent.length
        }
      };

      const startTime = Date.now();
      const result = await this.components.contentExtractor.extractContent(mockResponse);
      const endTime = Date.now();

      const duration = endTime - startTime;
      this.testResults.performance.contentExtractionMs = duration;

      console.error(`   Content extraction time: ${duration}ms for ${result.chunks.length} chunks`);

      this.pass(testName);

    } catch (error) {
      this.fail(testName, error);
    }
  }

  async benchmarkSearchPerformance() {
    const testName = 'Search Performance';
    console.error(`⏱️ Benchmarking ${testName}...`);

    try {
      await this.components.ragTools.initialize();

      const queries = this.testConfig.testQueries.slice(0, 3);
      const searchTimes = [];

      for (const query of queries) {
        const startTime = Date.now();
        await this.components.ragTools.searchDocumentation({ query, max_results: 5 });
        const endTime = Date.now();

        searchTimes.push(endTime - startTime);
      }

      const avgSearchTime = searchTimes.reduce((a, b) => a + b, 0) / searchTimes.length;
      this.testResults.performance.avgSearchMs = avgSearchTime;

      console.error(`   Average search time: ${avgSearchTime.toFixed(0)}ms`);

      this.pass(testName);

    } catch (error) {
      this.fail(testName, error);
    }
  }

  // Test utilities

  assert(condition, message) {
    if (!condition) {
      throw new Error(`Assertion failed: ${message}`);
    }
  }

  pass(testName) {
    this.testResults.totalTests++;
    this.testResults.passed++;
    console.error(`   ✅ ${testName} passed`);
  }

  fail(testName, error) {
    this.testResults.totalTests++;
    this.testResults.failed++;
    this.testResults.errors.push({
      test: testName,
      error: error.message,
      stack: error.stack
    });
    console.error(`   ❌ ${testName} failed: ${error.message}`);
  }

  skip(testName, reason) {
    this.testResults.totalTests++;
    this.testResults.skipped++;
    console.error(`   ⏭️ ${testName} skipped: ${reason}`);
  }

  /**
   * Generate comprehensive test report
   */
  async generateTestReport() {
    this.testResults.endTime = new Date();
    this.testResults.duration = this.testResults.endTime - this.testResults.startTime;

    const report = {
      summary: {
        testSuite: 'Enhanced RAG System',
        startTime: this.testResults.startTime.toISOString(),
        endTime: this.testResults.endTime.toISOString(),
        durationMs: this.testResults.duration,
        totalTests: this.testResults.totalTests,
        passed: this.testResults.passed,
        failed: this.testResults.failed,
        skipped: this.testResults.skipped,
        successRate: this.testResults.totalTests > 0
          ? (this.testResults.passed / this.testResults.totalTests * 100).toFixed(1) + '%'
          : '0%'
      },
      performance: this.testResults.performance,
      errors: this.testResults.errors,
      environment: {
        nodeVersion: process.version,
        platform: process.platform,
        architecture: process.arch,
        testOutputDir: this.testConfig.outputDir
      }
    };

    const reportPath = path.join(this.testConfig.outputDir, 'test-report.json');
    await fs.writeFile(reportPath, JSON.stringify(report, null, 2));

    console.error(`\n📄 Test report saved to: ${reportPath}`);
  }

  /**
   * Show final test results
   */
  showFinalResults() {
    const duration = (this.testResults.duration / 1000).toFixed(1);
    const successRate = this.testResults.totalTests > 0
      ? (this.testResults.passed / this.testResults.totalTests * 100).toFixed(1)
      : 0;

    console.error('\n🏁 TEST RESULTS');
    console.error('═══════════════════════════════════════');
    console.error(`⏱️  Total Time: ${duration}s`);
    console.error(`📊 Tests Run: ${this.testResults.totalTests}`);
    console.error(`✅ Passed: ${this.testResults.passed}`);
    console.error(`❌ Failed: ${this.testResults.failed}`);
    console.error(`⏭️ Skipped: ${this.testResults.skipped}`);
    console.error(`📈 Success Rate: ${successRate}%`);

    if (Object.keys(this.testResults.performance).length > 0) {
      console.error('\n⚡ PERFORMANCE METRICS');
      Object.entries(this.testResults.performance).forEach(([metric, value]) => {
        console.error(`  ${metric}: ${value.toFixed ? value.toFixed(0) : value}${metric.includes('Ms') ? 'ms' : ''}`);
      });
    }

    if (this.testResults.errors.length > 0) {
      console.error('\n❌ FAILED TESTS:');
      this.testResults.errors.forEach(error => {
        console.error(`  ${error.test}: ${error.error}`);
      });
    }

    console.error('\n💡 NEXT STEPS:');
    if (this.testResults.failed === 0) {
      console.error('  🎉 All tests passed! The Enhanced RAG System is ready for use.');
      console.error('  📚 Run full documentation ingestion: node run-documentation-ingestion.js');
      console.error('  🚀 Start the enhanced MCP server with the new RAG capabilities');
    } else {
      console.error('  🔧 Fix failing tests before deployment');
      console.error('  📋 Review error details in the test report');
      console.error('  🧪 Re-run tests after fixes');
    }
    console.error('═══════════════════════════════════════\n');

    process.exit(this.testResults.failed > 0 ? 1 : 0);
  }
}

// Run the test suite
if (import.meta.url === `file://${process.argv[1]}`) {
  const testSuite = new EnhancedRAGTestSuite();
  testSuite.run();
}

export { EnhancedRAGTestSuite };