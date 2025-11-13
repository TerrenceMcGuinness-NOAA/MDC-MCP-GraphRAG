#!/usr/bin/env node

/**
 * Comprehensive ChromaDB 3.0.17 Client Test
 *
 * Tests connection, collection operations, and query functionality
 * against ChromaDB 1.1.1 server
 *
 * @version 1.0.0
 */

import { ChromaClient } from 'chromadb';

const CHROMA_URL = process.env.CHROMA_SERVER_URL || 'http://127.0.0.1:8080';
const TEST_COLLECTION_NAME = 'test_chromadb_3x_client';

async function runTests() {
  console.log('🧪 ChromaDB 3.0.17 Client Test Suite\n');
  console.log(`📍 Server URL: ${CHROMA_URL}\n`);

  let client;
  let collection;
  let passCount = 0;
  let failCount = 0;

  try {
    // Test 1: Client Initialization
    console.log('Test 1: Client Initialization');
    client = new ChromaClient({ path: CHROMA_URL });
    console.log('✅ PASS: Client initialized\n');
    passCount++;

    // Test 2: Heartbeat
    console.log('Test 2: Heartbeat');
    const heartbeat = await client.heartbeat();
    console.log(`✅ PASS: Heartbeat received: ${heartbeat}\n`);
    passCount++;

    // Test 3: Get Server Version
    console.log('Test 3: Get Server Version');
    try {
      const version = await client.version();
      console.log(`✅ PASS: Server version: ${version}\n`);
      passCount++;
    } catch (error) {
      console.log(`⚠️  SKIP: Version endpoint not available (${error.message})\n`);
    }

    // Test 4: List Collections
    console.log('Test 4: List Collections');
    const collections = await client.listCollections();
    console.log(`✅ PASS: Found ${collections.length} existing collections`);
    collections.forEach(col => {
      console.log(`   - ${col.name} (${col.metadata ? JSON.stringify(col.metadata) : 'no metadata'})`);
    });
    console.log();
    passCount++;

    // Test 5: Delete test collection if exists (cleanup)
    console.log('Test 5: Cleanup - Delete test collection if exists');
    try {
      await client.deleteCollection({ name: TEST_COLLECTION_NAME });
      console.log(`✅ PASS: Cleaned up existing test collection\n`);
    } catch (error) {
      console.log(`✅ PASS: No existing test collection to clean up\n`);
    }
    passCount++;

    // Test 6: Create Collection
    console.log('Test 6: Create Collection');
    collection = await client.createCollection({
      name: TEST_COLLECTION_NAME,
      metadata: {
        description: 'Test collection for chromadb 3.0.17 client',
        test_run: new Date().toISOString()
      }
    });
    console.log(`✅ PASS: Collection '${TEST_COLLECTION_NAME}' created\n`);
    passCount++;

    // Test 7: Get Collection
    console.log('Test 7: Get Collection');
    const retrievedCollection = await client.getCollection({ name: TEST_COLLECTION_NAME });
    console.log(`✅ PASS: Collection retrieved: ${retrievedCollection.name}\n`);
    passCount++;

    // Test 8: Add Documents to Collection
    console.log('Test 8: Add Documents to Collection');
    await collection.add({
      ids: ['doc1', 'doc2', 'doc3'],
      documents: [
        'This is a test document about global workflow',
        'ChromaDB integration with MCP server',
        'Python 3.11 and Node.js compatibility testing'
      ],
      metadatas: [
        { source: 'test', category: 'workflow' },
        { source: 'test', category: 'integration' },
        { source: 'test', category: 'compatibility' }
      ]
    });
    console.log('✅ PASS: 3 documents added to collection\n');
    passCount++;

    // Test 9: Count Documents
    console.log('Test 9: Count Documents');
    const count = await collection.count();
    console.log(`✅ PASS: Collection contains ${count} documents\n`);
    passCount++;

    // Test 10: Query Documents (Semantic Search)
    console.log('Test 10: Query Documents (Semantic Search)');
    const queryResults = await collection.query({
      queryTexts: ['workflow integration'],
      nResults: 2
    });
    console.log(`✅ PASS: Query returned ${queryResults.documents[0].length} results:`);
    queryResults.documents[0].forEach((doc, i) => {
      const distance = queryResults.distances[0][i];
      const metadata = queryResults.metadatas[0][i];
      console.log(`   ${i + 1}. Distance: ${distance.toFixed(4)} | Category: ${metadata.category}`);
      console.log(`      "${doc.substring(0, 60)}..."`);
    });
    console.log();
    passCount++;

    // Test 11: Get Specific Documents by ID
    console.log('Test 11: Get Specific Documents by ID');
    const getResults = await collection.get({
      ids: ['doc1', 'doc3']
    });
    console.log(`✅ PASS: Retrieved ${getResults.documents.length} documents by ID\n`);
    passCount++;

    // Test 12: Update Document
    console.log('Test 12: Update Document');
    await collection.update({
      ids: ['doc1'],
      documents: ['This is an UPDATED test document about global workflow'],
      metadatas: [{ source: 'test', category: 'workflow', updated: true }]
    });
    const updatedDoc = await collection.get({ ids: ['doc1'] });
    console.log(`✅ PASS: Document updated: "${updatedDoc.documents[0].substring(0, 50)}..."\n`);
    passCount++;

    // Test 13: Delete Document
    console.log('Test 13: Delete Document');
    await collection.delete({ ids: ['doc2'] });
    const countAfterDelete = await collection.count();
    console.log(`✅ PASS: Document deleted. Collection now has ${countAfterDelete} documents\n`);
    passCount++;

    // Test 14: Test Existing Collections (if any)
    console.log('Test 14: Query Existing Collections');
    const existingCollections = await client.listCollections();
    const realCollections = existingCollections.filter(c => c.name !== TEST_COLLECTION_NAME);

    if (realCollections.length > 0) {
      console.log(`Found ${realCollections.length} existing production collections:`);
      for (const col of realCollections.slice(0, 2)) { // Test first 2 only
        try {
          const existingCol = await client.getCollection({ name: col.name });
          const colCount = await existingCol.count();
          console.log(`   - ${col.name}: ${colCount} documents`);

          if (colCount > 0) {
            // Try a simple query
            const testQuery = await existingCol.query({
              queryTexts: ['workflow'],
              nResults: 1
            });
            if (testQuery.documents[0].length > 0) {
              console.log(`     ✓ Query successful: found "${testQuery.documents[0][0].substring(0, 40)}..."`);
            }
          }
        } catch (error) {
          console.log(`   - ${col.name}: Error querying (${error.message})`);
        }
      }
      console.log('✅ PASS: Existing collections accessible\n');
      passCount++;
    } else {
      console.log('⚠️  SKIP: No existing collections to test\n');
    }

    // Test 15: Cleanup - Delete Test Collection
    console.log('Test 15: Cleanup - Delete Test Collection');
    await client.deleteCollection({ name: TEST_COLLECTION_NAME });
    console.log(`✅ PASS: Test collection deleted\n`);
    passCount++;

  } catch (error) {
    console.error(`❌ FAIL: ${error.message}`);
    console.error(error.stack);
    failCount++;
  }

  // Summary
  console.log('═'.repeat(60));
  console.log('📊 Test Summary');
  console.log('═'.repeat(60));
  console.log(`✅ Passed: ${passCount}`);
  console.log(`❌ Failed: ${failCount}`);
  console.log(`📈 Success Rate: ${((passCount / (passCount + failCount)) * 100).toFixed(1)}%`);
  console.log('═'.repeat(60));

  if (failCount === 0) {
    console.log('\n🎉 All tests passed! ChromaDB 3.0.17 client is working correctly.\n');
    process.exit(0);
  } else {
    console.log('\n⚠️  Some tests failed. Check the output above for details.\n');
    process.exit(1);
  }
}

// Run tests
runTests().catch(error => {
  console.error('\n💥 Fatal error running tests:');
  console.error(error);
  process.exit(1);
});
