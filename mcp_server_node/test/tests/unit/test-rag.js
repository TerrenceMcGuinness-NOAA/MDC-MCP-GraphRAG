#!/usr/bin/env node

/**
 * Test script for RAG functionality
 */

import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function testDocumentIngestion() {
  console.log('Testing Document Ingestion...');

  try {
    // Import the DocumentIngester
    const DocumentIngesterModule = await import('../../document-ingester.js');
    const DocumentIngester = DocumentIngesterModule.default;

    // Create ingester instance pointing to a small subset of the repository
    const testDir = path.join(__dirname, '../../../../../..'); // Point to global-workflow root
    const ingester = new DocumentIngester(testDir);

    console.log(`Target directory: ${testDir}`);
    console.log('✓ Document ingester module loaded and instantiated');

    // Note: Full ingestion would take too long for testing
    console.log('Note: Skipping full ingestion for now (would process entire repository)');

  } catch (error) {
    console.error('✗ Document ingestion failed:', error.message);
    console.error(error.stack);
  }
}

async function testRAGServer() {
  console.log('\nTesting RAG Server...');

  try {
    // Import the RAG server module
    const RAGServerModule = await import('../../mcp-server-rag.js');
    console.log('✓ RAG server module loaded successfully');

  } catch (error) {
    console.error('✗ RAG server test failed:', error.message);
  }
}

async function main() {
  console.log('=== RAG System Test ===\n');

  await testDocumentIngestion();
  await testRAGServer();

  console.log('\n=== Test Complete ===');
  console.log('\nNext steps:');
  console.log('1. Convert document-ingester.js to ES modules');
  console.log('2. Convert mcp-server-rag.js to ES modules');
  console.log('3. Test vector database integration');
  console.log('4. Run full document ingestion');
}

main().catch(console.error);
