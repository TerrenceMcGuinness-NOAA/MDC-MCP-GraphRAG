#!/usr/bin/env node

/**
 * Quick test to verify ChromaDB connection and RAG search
 */

import { RAGTools } from './src/tools/RAGTools.js';

async function testRAGConnection() {
  console.log('🧪 Testing RAG Tools Connection\n');
  console.log('=' .repeat(60));

  const ragTools = new RAGTools();

  try {
    console.log('\n1️⃣ Initializing RAG components...');
    await ragTools.initialize();

    console.log('\n2️⃣ Testing semantic search...');
    const testQueries = [
      'rocoto workflow configuration',
      'spack-stack installation',
      'GSI data assimilation'
    ];

    for (const query of testQueries) {
      console.log(`\n   Query: "${query}"`);
      const result = await ragTools.searchDocumentation({
        query,
        max_results: 3,
        similarity_threshold: 0.1
      });

      if (result && !result.includes('No documentation found')) {
        console.log(`   ✅ Found results (${result.split('##').length - 1} documents)`);
      } else {
        console.log(`   ⚠️  No results found`);
      }
    }

    console.log('\n' + '='.repeat(60));
    console.log('✅ RAG connection test completed\n');

  } catch (error) {
    console.error('\n❌ Test failed:', error.message);
    console.error(error.stack);
    process.exit(1);
  }
}

testRAGConnection();
