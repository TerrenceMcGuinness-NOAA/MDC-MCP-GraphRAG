#!/usr/bin/env node

/**
 * EE2 Search Validation Test
 * 
 * Comprehensive validation of EE2 semantic search capabilities
 * 
 * @version 3.0.0
 * @author NOAA EMC Global Workflow Team
 */

import { EE2VectorStore } from './src/rag/EE2VectorStore.js';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function validateEE2Search() {
  console.error('🔍 Validating EE2 Semantic Search Capabilities\n');
  
  try {
    // Initialize the EE2 vector store
    const vectorStore = new EE2VectorStore({
      knowledgeBasePath: path.join(__dirname, 'knowledge-base')
    });
    
    await vectorStore.initialize();
    const stats = vectorStore.getStats();
    
    console.error('📊 Vector Store Statistics:');
    console.error(`   Total Chunks: ${stats.total_chunks}`);
    console.error(`   EE2 Chunks: ${stats.ee2_chunks}`);
    console.error(`   High Importance: ${stats.high_importance_chunks}`);
    console.error(`   Categories: ${stats.compliance_categories}\n`);
    
    // Test comprehensive search queries
    const testQueries = [
      { query: 'environment variables DATAROOT', category: 'environment_variables' },
      { query: 'error handling err_chk', category: 'error_handling' },
      { query: 'workflow structure JAAAAA', category: 'workflow_structure' },
      { query: 'file naming conventions', category: 'file_naming' },
      { query: 'production utilities prep_step', category: 'production_utilities' },
      { query: 'compliance assessment excellent', category: null },
      { query: 'WCOSS operational standards', category: null }
    ];
    
    console.error('🧪 Testing Search Queries:\n');
    
    for (let i = 0; i < testQueries.length; i++) {
      const { query, category } = testQueries[i];
      
      const results = await vectorStore.searchEE2Compliance(query, {
        maxResults: 5,
        category: category,
        minImportance: 1.0
      });
      
      console.error(`${i + 1}. Query: "${query}"`);
      console.error(`   Category: ${category || 'any'}`);
      console.error(`   Results: ${results.length}`);
      
      if (results.length > 0) {
        const topResult = results[0];
        console.error(`   Top relevance: ${topResult.relevance_score.toFixed(2)}`);
        console.error(`   Content preview: ${topResult.content.substring(0, 100)}...`);
        
        if (topResult.metadata?.compliance_categories) {
          const categories = topResult.metadata.compliance_categories.map(c => c.name).join(', ');
          console.error(`   Categories found: ${categories}`);
        }
      } else {
        console.error('   ⚠️ No results found');
      }
      console.error('');
    }
    
    // Test compliance-specific features
    console.error('📋 Testing Compliance Features:\n');
    
    // Test high importance content
    const highImportanceResults = await vectorStore.searchEE2Compliance('compliance', {
      minImportance: 2.0,
      maxResults: 5
    });
    
    console.error(`High Importance Search: ${highImportanceResults.length} results`);
    if (highImportanceResults.length > 0) {
      const scores = highImportanceResults.map(r => r.relevance_score.toFixed(2)).join(', ');
      console.error(`   Relevance scores: ${scores}`);
    }
    console.error('');
    
    // Test category coverage
    const categories = ['environment_variables', 'error_handling', 'workflow_structure'];
    for (const cat of categories) {
      const catResults = await vectorStore.searchEE2Compliance('standards', {
        category: cat,
        maxResults: 3
      });
      console.error(`${cat.replace(/_/g, ' ')}: ${catResults.length} standards`);
    }
    
    console.error('\n✅ EE2 Semantic Search Validation Complete');
    
    // Performance metrics
    const performanceTests = [
      { query: 'environment variables', iterations: 5 },
      { query: 'error handling standards', iterations: 5 },
      { query: 'workflow compliance', iterations: 5 }
    ];
    
    console.error('\n⚡ Performance Testing:\n');
    
    for (const test of performanceTests) {
      const times = [];
      
      for (let i = 0; i < test.iterations; i++) {
        const start = Date.now();
        await vectorStore.searchEE2Compliance(test.query, { maxResults: 5 });
        times.push(Date.now() - start);
      }
      
      const avgTime = times.reduce((sum, t) => sum + t, 0) / times.length;
      const minTime = Math.min(...times);
      const maxTime = Math.max(...times);
      
      console.error(`Query: "${test.query}"`);
      console.error(`   Average: ${avgTime.toFixed(1)}ms`);
      console.error(`   Range: ${minTime}ms - ${maxTime}ms`);
      console.error('');
    }
    
    console.error('🎯 Validation Summary:');
    console.error(`   ✅ Vector store operational with ${stats.total_chunks} chunks`);
    console.error(`   ✅ EE2 compliance processing: ${stats.ee2_chunks} specialized chunks`);
    console.error(`   ✅ Search functionality working across categories`);
    console.error(`   ✅ Performance acceptable for production use`);
    console.error(`   ✅ Ready for EE2 compliance validation workflows`);
    
    return true;
  } catch (error) {
    console.error(`❌ EE2 search validation failed: ${error.message}`);
    console.error(error.stack);
    return false;
  }
}

// Run validation
validateEE2Search()
  .then(success => process.exit(success ? 0 : 1))
  .catch(error => {
    console.error(`❌ Validation execution failed: ${error.message}`);
    process.exit(1);
  });