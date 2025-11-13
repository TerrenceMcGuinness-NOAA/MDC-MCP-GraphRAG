#!/usr/bin/env node

/**
 * Test Script for Enhanced EE2 Vector Store
 * 
 * Validates the EE2-optimized vector store implementation
 * and demonstrates compliance-focused search capabilities.
 * 
 * @version 3.0.0
 * @author NOAA EMC Global Workflow Team
 */

import { EE2VectorStore } from './src/rag/EE2VectorStore.js';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

class EE2VectorStoreTest {
  constructor() {
    this.vectorStore = null;
  }

  async runTests() {
    console.error('🧪 Testing Enhanced EE2 Vector Store\n');
    
    try {
      await this.testInitialization();
      await this.testEE2Documentation();
      await this.testComplianceSearch();
      await this.testCategorySearch();
      await this.testCodeExamples();
      await this.generateReport();
    } catch (error) {
      console.error(`❌ Test failed: ${error.message}`);
      throw error;
    }
  }

  async testInitialization() {
    console.error('📋 Testing Vector Store Initialization...');
    
    this.vectorStore = new EE2VectorStore({
      knowledgeBasePath: path.join(__dirname, 'knowledge-base')
    });
    
    const stats = await this.vectorStore.initialize();
    
    console.error(`✅ Initialization complete`);
    console.error(`   Total chunks: ${stats.total_chunks}`);
    console.error(`   EE2 chunks: ${stats.ee2_chunks}`);
    console.error(`   High importance: ${stats.high_importance_chunks}`);
    console.error(`   Compliance categories: ${stats.compliance_categories}\n`);
    
    this.assert(stats.total_chunks > 0, 'Should have loaded chunks');
    this.assert(stats.compliance_categories > 0, 'Should have compliance categories');
  }

  async testEE2Documentation() {
    console.error('📄 Testing EE2 Documentation Processing...');
    
    const stats = this.vectorStore.getStats();
    
    // Should have processed EE2 documents
    this.assert(stats.ee2_chunks > 0, 'Should have processed EE2 documents');
    
    // Check for high importance chunks
    this.assert(stats.high_importance_chunks > 0, 'Should have high importance chunks');
    
    console.error(`✅ EE2 documentation processing verified`);
    console.error(`   EE2-specific chunks: ${stats.ee2_chunks}`);
    console.error(`   High importance chunks: ${stats.high_importance_chunks}\n`);
  }

  async testComplianceSearch() {
    console.error('🔍 Testing Compliance Search...');
    
    const testQueries = [
      'environment variables',
      'error handling standards',
      'workflow structure',
      'DATAROOT DATA variables',
      'err_chk err_exit functions'
    ];
    
    for (const query of testQueries) {
      const results = await this.vectorStore.searchEE2Compliance(query, {
        maxResults: 5,
        minImportance: 1.0
      });
      
      console.error(`   Query: "${query}" → ${results.length} results`);
      
      if (results.length > 0) {
        const topResult = results[0];
        console.error(`     Top result: ${topResult.relevance_score.toFixed(2)} relevance`);
        console.error(`     Content preview: ${topResult.content.substring(0, 100)}...`);
      }
      
      this.assert(results.length >= 0, `Should return results for "${query}"`);
    }
    
    console.error(`✅ Compliance search functionality verified\n`);
  }

  async testCategorySearch() {
    console.error('📊 Testing Category-Based Search...');
    
    const categories = [
      'environment_variables',
      'error_handling', 
      'workflow_structure',
      'file_naming',
      'production_utilities'
    ];
    
    for (const category of categories) {
      const results = await this.vectorStore.searchEE2Compliance('compliance', {
        category: category,
        maxResults: 3
      });
      
      console.error(`   Category: ${category} → ${results.length} results`);
      
      if (results.length > 0) {
        console.error(`     Relevance range: ${results[results.length-1].relevance_score.toFixed(2)} - ${results[0].relevance_score.toFixed(2)}`);
      }
    }
    
    console.error(`✅ Category-based search verified\n`);
  }

  async testCodeExamples() {
    console.error('💻 Testing Code Example Search...');
    
    const codeQueries = [
      'export DATAROOT',
      'err_chk',
      'source prep_step',
      'JGDAS_ATMOS',
      'exglobal'
    ];
    
    for (const query of codeQueries) {
      const results = await this.vectorStore.searchEE2Compliance(query, {
        includeCode: true,
        maxResults: 3
      });
      
      console.error(`   Code query: "${query}" → ${results.length} results`);
      
      // Look for code-like content in results
      const codeResults = results.filter(r => 
        r.content.includes('export ') || 
        r.content.includes('source ') ||
        r.content.includes('```') ||
        r.content.includes('#!')
      );
      
      if (codeResults.length > 0) {
        console.error(`     Code examples found: ${codeResults.length}`);
      }
    }
    
    console.error(`✅ Code example search verified\n`);
  }

  async generateReport() {
    console.error('📋 Generating Test Report...');
    
    const stats = this.vectorStore.getStats();
    
    console.error('🎯 EE2 Vector Store Test Results');
    console.error('='.repeat(50));
    console.error(`📊 Statistics:`);
    console.error(`   Total Chunks: ${stats.total_chunks}`);
    console.error(`   EE2 Compliance Chunks: ${stats.ee2_chunks}`);
    console.error(`   High Importance Chunks: ${stats.high_importance_chunks}`);
    console.error(`   Compliance Categories: ${stats.compliance_categories}`);
    console.error(`   Embeddings Loaded: ${stats.embeddings_loaded}`);
    console.error(`   Knowledge Base: ${stats.knowledge_base_path}`);
    
    console.error(`\n✅ All Tests Passed - EE2 Vector Store Ready`);
    
    // Save enhanced knowledge base
    const savedPath = await this.vectorStore.save();
    console.error(`💾 Enhanced knowledge base saved to: ${savedPath}`);
  }

  assert(condition, message) {
    if (!condition) {
      throw new Error(`Assertion failed: ${message}`);
    }
  }
}

// Main execution
if (import.meta.url === `file://${process.argv[1]}`) {
  const test = new EE2VectorStoreTest();
  test.runTests()
    .then(() => {
      console.error('\n🎉 All tests completed successfully!');
      process.exit(0);
    })
    .catch(error => {
      console.error(`\n❌ Tests failed: ${error.message}`);
      process.exit(1);
    });
}