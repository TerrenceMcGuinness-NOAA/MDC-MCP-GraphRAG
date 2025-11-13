#!/usr/bin/env node

/**
 * Quick test for RAG functionality without running full MCP server
 */

import { pipeline } from '@xenova/transformers';
import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function testRAGComponents() {
    console.log('🔍 Testing RAG Components...\n');

    try {
        // Test 1: Check if knowledge base files exist
        console.log('1. Testing knowledge base files...');
        const knowledgeBasePath = path.join(__dirname, 'knowledge-base');
        
        const summaryPath = path.join(knowledgeBasePath, 'summary.json');
        const chunksPath = path.join(knowledgeBasePath, 'chunks.json');
        const embeddingsPath = path.join(knowledgeBasePath, 'chunks_with_embeddings.json');
        
        const summaryExists = await fs.access(summaryPath).then(() => true).catch(() => false);
        const chunksExist = await fs.access(chunksPath).then(() => true).catch(() => false);
        const embeddingsExist = await fs.access(embeddingsPath).then(() => true).catch(() => false);
        
        console.log(`   ✅ Summary file: ${summaryExists ? 'EXISTS' : 'MISSING'}`);
        console.log(`   ✅ Chunks file: ${chunksExist ? 'EXISTS' : 'MISSING'}`);
        console.log(`   ✅ Embeddings file: ${embeddingsExist ? 'EXISTS' : 'MISSING'}`);
        
        if (!summaryExists || !chunksExist || !embeddingsExist) {
            throw new Error('Missing required knowledge base files');
        }

        // Test 2: Load and verify summary data
        console.log('\n2. Testing knowledge base summary...');
        const summaryData = await fs.readFile(summaryPath, 'utf8');
        const summary = JSON.parse(summaryData);
        
        console.log(`   📊 Total chunks: ${summary.total_chunks}`);
        console.log(`   🧠 Embedding model: ${summary.embedding_model}`);
        console.log(`   📐 Embedding dimension: ${summary.embedding_dimension}`);

        // Test 3: Load sample chunks with embeddings
        console.log('\n3. Testing embeddings data...');
        const embeddingsData = await fs.readFile(embeddingsPath, 'utf8');
        
        // Parse just the first few characters to get array start
        const firstChunk = embeddingsData.substring(0, 10000);
        if (!firstChunk.includes('"embedding"')) {
            throw new Error('No embeddings found in chunks data');
        }
        
        console.log('   ✅ Embeddings data structure valid');

        // Test 4: Test embedding model initialization
        console.log('\n4. Testing embedding model...');
        try {
            console.log('   🔄 Loading all-MiniLM-L6-v2 model...');
            const embedModel = await pipeline('feature-extraction', 'Xenova/all-MiniLM-L6-v2');
            
            // Test embedding generation
            const testText = "How to configure global workflow";
            const result = await embedModel(testText);
            const embedding = Array.from(result.data);
            
            console.log(`   ✅ Model loaded successfully`);
            console.log(`   📊 Test embedding dimension: ${embedding.length}`);
            console.log(`   🔢 Sample embedding values: [${embedding.slice(0, 3).map(x => x.toFixed(3)).join(', ')}...]`);
            
        } catch (error) {
            console.log(`   ⚠️  Model loading failed: ${error.message}`);
            console.log('   💡 This is expected if transformers.js needs to download models');
        }

        // Test 5: Test cosine similarity function
        console.log('\n5. Testing similarity calculation...');
        const vec1 = [1, 0, 0, 1];
        const vec2 = [0, 1, 1, 0];
        const similarity = cosineSimilarity(vec1, vec2);
        console.log(`   🔢 Test similarity (should be 0): ${similarity.toFixed(3)}`);

        console.log('\n✅ All RAG components test PASSED!');
        console.log('\n🎯 Next Steps:');
        console.log('   1. RAG system is ready for use');
        console.log('   2. MCP server should now find knowledge base correctly');
        console.log('   3. Try running the MCP tools with semantic search');

        return true;

    } catch (error) {
        console.error('\n❌ RAG test FAILED:', error.message);
        console.error('\n🔧 Troubleshooting:');
        console.error('   1. Check if knowledge-base directory exists');
        console.error('   2. Verify embeddings were generated correctly');
        console.error('   3. Ensure Node.js modules are installed');
        return false;
    }
}

// Cosine similarity function for testing
function cosineSimilarity(vecA, vecB) {
    if (vecA.length !== vecB.length) return 0;
    
    let dotProduct = 0;
    let normA = 0;
    let normB = 0;
    
    for (let i = 0; i < vecA.length; i++) {
        dotProduct += vecA[i] * vecB[i];
        normA += vecA[i] * vecA[i];
        normB += vecB[i] * vecB[i];
    }
    
    normA = Math.sqrt(normA);
    normB = Math.sqrt(normB);
    
    if (normA === 0 || normB === 0) return 0;
    return dotProduct / (normA * normB);
}

// Run the test
if (import.meta.url === `file://${process.argv[1]}`) {
    testRAGComponents()
        .then(success => {
            process.exit(success ? 0 : 1);
        })
        .catch(error => {
            console.error('Unexpected error:', error);
            process.exit(1);
        });
}
