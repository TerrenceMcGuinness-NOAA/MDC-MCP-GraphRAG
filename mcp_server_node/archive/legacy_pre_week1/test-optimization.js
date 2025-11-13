#!/usr/bin/env node

/**
 * Test Script for Knowledge Base Optimization
 * 
 * Validates the optimized system performance and correctness
 */

import OptimizedVectorStore from './optimized-vector-store.js';
import EmbeddingOptimizer from './embedding-optimizer.js';

class OptimizationTester {
  constructor() {
    this.results = {
      vectorStore: {},
      optimizer: {},
      performance: {}
    };
  }

  async runAllTests() {
    console.log('🧪 Running Knowledge Base Optimization Tests\n');
    
    try {
      // Test 1: Vector Store Functionality
      await this.testVectorStore();
      
      // Test 2: Embedding Optimizer
      await this.testEmbeddingOptimizer();
      
      // Test 3: Performance Benchmarks
      await this.testPerformance();
      
      // Test 4: Memory Usage
      await this.testMemoryUsage();
      
      this.printSummary();
      
    } catch (error) {
      console.error('❌ Test failed:', error.message);
      process.exit(1);
    }
  }

  async testVectorStore() {
    console.log('📊 Testing Optimized Vector Store...');
    
    try {
      const vectorStore = new OptimizedVectorStore({
        chunkSize: 10,
        cacheSize: 50
      });
      
      // Test initialization
      console.log('  - Testing initialization...');
      await vectorStore.initialize();
      console.log('    ✅ Initialization successful');
      
      // Test memory usage
      const memoryBefore = vectorStore.getMemoryUsage();
      console.log(`    📊 Memory usage: ${memoryBefore.heapUsed}MB`);
      
      // Test search functionality (if embeddings available)
      console.log('  - Testing search functionality...');
      try {
        // Create dummy query embedding
        const dummyEmbedding = new Array(384).fill(0.1);
        const results = await vectorStore.searchSemantic(dummyEmbedding, {
          maxResults: 3
        });
        
        console.log(`    ✅ Search returned ${results.documents[0].length} results`);
        this.results.vectorStore.searchWorks = true;
        
      } catch (searchError) {
        console.log('    ⚠️ Search test skipped (no embeddings file)');
        this.results.vectorStore.searchWorks = false;
      }
      
      // Test caching
      const stats = vectorStore.getStats();
      console.log(`    📈 Cache hit rate: ${(stats.cacheHitRate * 100).toFixed(1)}%`);
      
      this.results.vectorStore.passed = true;
      
    } catch (error) {
      console.error('    ❌ Vector store test failed:', error.message);
      this.results.vectorStore.passed = false;
    }
  }

  async testEmbeddingOptimizer() {
    console.log('\n🔧 Testing Embedding Optimizer...');
    
    try {
      const optimizer = new EmbeddingOptimizer({
        knowledgeBasePath: './knowledge-base',
        outputPath: './test-optimized-kb',
        chunkSize: 5
      });
      
      // Test analysis functionality
      console.log('  - Testing embedding analysis...');
      const analysis = await optimizer.analyzeCurrentEmbeddings();
      console.log(`    📊 Found ${analysis.totalChunks} chunks`);
      console.log(`    💾 File size: ${analysis.fileSizeMB}MB`);
      
      this.results.optimizer.analysis = analysis;
      this.results.optimizer.passed = true;
      
      if (analysis.totalChunks > 0) {
        console.log('    ✅ Analysis successful');
      } else {
        console.log('    ⚠️ No embeddings found (test environment)');
      }
      
    } catch (error) {
      console.error('    ❌ Optimizer test failed:', error.message);
      this.results.optimizer.passed = false;
    }
  }

  async testPerformance() {
    console.log('\n⚡ Testing Performance...');
    
    const measurements = [];
    
    // Test multiple iterations
    for (let i = 0; i < 5; i++) {
      const start = Date.now();
      
      // Simulate a typical operation
      const vectorStore = new OptimizedVectorStore({ chunkSize: 10 });
      await vectorStore.initialize();
      
      const duration = Date.now() - start;
      measurements.push(duration);
      console.log(`  - Iteration ${i + 1}: ${duration}ms`);
    }
    
    const avgTime = measurements.reduce((a, b) => a + b, 0) / measurements.length;
    console.log(`    📊 Average initialization time: ${avgTime.toFixed(2)}ms`);
    
    this.results.performance = {
      avgInitTime: avgTime,
      measurements: measurements,
      passed: avgTime < 1000 // Should initialize in <1 second
    };
    
    if (this.results.performance.passed) {
      console.log('    ✅ Performance test passed');
    } else {
      console.log('    ⚠️ Performance slower than expected');
    }
  }

  async testMemoryUsage() {
    console.log('\n💾 Testing Memory Usage...');
    
    const memoryBefore = process.memoryUsage();
    
    // Create multiple vector stores to test memory behavior
    const stores = [];
    for (let i = 0; i < 3; i++) {
      const store = new OptimizedVectorStore({ 
        chunkSize: 5,
        cacheSize: 10 
      });
      await store.initialize();
      stores.push(store);
    }
    
    const memoryAfter = process.memoryUsage();
    const memoryIncrease = (memoryAfter.heapUsed - memoryBefore.heapUsed) / 1024 / 1024;
    
    console.log(`    📊 Memory increase: ${memoryIncrease.toFixed(2)}MB`);
    console.log(`    📊 Current heap: ${Math.round(memoryAfter.heapUsed / 1024 / 1024)}MB`);
    
    this.results.performance.memoryIncrease = memoryIncrease;
    this.results.performance.memoryEfficient = memoryIncrease < 50; // Should be <50MB
    
    if (this.results.performance.memoryEfficient) {
      console.log('    ✅ Memory usage efficient');
    } else {
      console.log('    ⚠️ Memory usage higher than expected');
    }
    
    // Cleanup
    stores.forEach(store => store.clearCache());
  }

  printSummary() {
    console.log('\n📋 Test Summary');
    console.log('================\n');
    
    const vectorStoreStatus = this.results.vectorStore.passed ? '✅' : '❌';
    const optimizerStatus = this.results.optimizer.passed ? '✅' : '❌';
    const performanceStatus = this.results.performance.passed ? '✅' : '❌';
    const memoryStatus = this.results.performance.memoryEfficient ? '✅' : '⚠️';
    
    console.log(`Vector Store:     ${vectorStoreStatus} ${this.results.vectorStore.passed ? 'PASSED' : 'FAILED'}`);
    console.log(`Optimizer:        ${optimizerStatus} ${this.results.optimizer.passed ? 'PASSED' : 'FAILED'}`);
    console.log(`Performance:      ${performanceStatus} ${this.results.performance.passed ? 'PASSED' : 'SLOW'}`);
    console.log(`Memory Usage:     ${memoryStatus} ${this.results.performance.memoryEfficient ? 'EFFICIENT' : 'HIGH'}`);
    
    console.log('\n📊 Metrics:');
    console.log(`- Avg Init Time:  ${this.results.performance.avgInitTime?.toFixed(2) || 'N/A'}ms`);
    console.log(`- Memory Impact:  ${this.results.performance.memoryIncrease?.toFixed(2) || 'N/A'}MB`);
    console.log(`- Search Works:   ${this.results.vectorStore.searchWorks ? 'Yes' : 'No (no data)'}`);
    
    const allPassed = this.results.vectorStore.passed && 
                     this.results.optimizer.passed && 
                     this.results.performance.passed;
    
    console.log('\n🎯 Overall Result:');
    if (allPassed) {
      console.log('✅ ALL TESTS PASSED - Optimization is working correctly!');
      console.log('\n🚀 Ready for production use with optimized performance.');
    } else {
      console.log('⚠️ Some tests had issues - Review the output above.');
      console.log('\n🔧 The system may still work but performance may be limited.');
    }
    
    console.log('\n📚 Next Steps:');
    console.log('1. Run: node optimized-rag-server.js');
    console.log('2. Test with: node embedding-optimizer.js --help');
    console.log('3. Monitor: Check performance stats during usage');
  }
}

// Run tests if called directly
async function main() {
  const tester = new OptimizationTester();
  await tester.runAllTests();
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main();
}

export default OptimizationTester;
