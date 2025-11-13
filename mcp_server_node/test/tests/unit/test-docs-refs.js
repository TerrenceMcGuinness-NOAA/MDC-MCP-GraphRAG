#!/usr/bin/env node

/**
 * Test Documentation References Tool
 */

import SimpleRAGServer from '../../simple-rag-server.js';

async function testDocumentationReferences() {
  console.log('=== Testing Documentation References Tool ===\n');

  const server = new SimpleRAGServer();
  await new Promise(resolve => setTimeout(resolve, 1000));

  console.log('✓ Server initialized\n');

  // Test different categories
  const testCases = [
    { category: "ufs", format: "detailed" },
    { category: "rocoto", format: "urls_only" },
    { category: "hpc_systems", format: "detailed" },
    { category: "all", format: "structured" }
  ];

  for (const testCase of testCases) {
    console.log(`Testing category: ${testCase.category}, format: ${testCase.format}`);
    try {
      const result = server.getDocumentationReferences(testCase.category, testCase.format);
      console.log(`✓ Success - Response length: ${result.content[0].text.length} characters`);

      // Show a snippet of the response
      const snippet = result.content[0].text.substring(0, 200);
      console.log(`   Preview: ${snippet}...`);
    } catch (error) {
      console.log(`✗ Failed: ${error.message}`);
    }
    console.log('');
  }

  console.log('=== Documentation References Test Complete ===');
}

testDocumentationReferences().catch(console.error);
