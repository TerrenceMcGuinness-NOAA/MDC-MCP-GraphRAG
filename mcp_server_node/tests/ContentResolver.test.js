/**
 * ContentResolver Tests
 * 
 * Tests for Phase 19A Content Abstraction Layer
 */

import { ContentResolver, ContentResolverError } from '../src/utils/ContentResolver.js';
import { strict as assert } from 'assert';

// Test content samples
const BASH_CONTENT = `#!/bin/bash
set -x
export err=0
echo "Hello World"
err_chk
`;

const PYTHON_CONTENT = `#!/usr/bin/env python3
import os
from pathlib import Path

def main():
    print("Hello")

if __name__ == "__main__":
    main()
`;

const YAML_CONTENT = `name: test-workflow
version: 1.0
steps:
  - name: build
    command: make
`;

async function testDirectContent() {
  console.log('\n[TEST] Direct content resolution...');
  
  const resolver = new ContentResolver();
  
  // Test bash content
  const result = await resolver.resolve({
    content: BASH_CONTENT,
    content_type: 'bash'
  });
  
  assert.equal(result.type, 'single');
  assert.equal(result.contentType, 'bash');
  assert.equal(result.source, 'direct');
  assert.ok(result.metadata.providedDirectly);
  assert.ok(result.content.includes('#!/bin/bash'));
  
  console.log('  [OK] Bash content resolved');
  
  // Test auto-detection
  const pythonResult = await resolver.resolve({
    content: PYTHON_CONTENT
  });
  
  assert.equal(pythonResult.contentType, 'python');
  console.log('  [OK] Python auto-detected');
  
  // Test YAML auto-detection
  const yamlResult = await resolver.resolve({
    content: YAML_CONTENT
  });
  
  assert.equal(yamlResult.contentType, 'yaml');
  console.log('  [OK] YAML auto-detected');
}

async function testFilesArray() {
  console.log('\n[TEST] Files array resolution...');
  
  const resolver = new ContentResolver();
  
  const result = await resolver.resolve({
    files: [
      { name: 'script1.sh', path: 'scripts/script1.sh', content: BASH_CONTENT },
      { name: 'main.py', path: 'src/main.py', content: PYTHON_CONTENT },
      { name: 'config.yaml', path: 'config/config.yaml', content: YAML_CONTENT }
    ]
  });
  
  assert.equal(result.type, 'multi');
  assert.equal(result.files.length, 3);
  assert.equal(result.metadata.fileCount, 3);
  assert.ok(result.metadata.fileTypes.includes('bash'));
  assert.ok(result.metadata.fileTypes.includes('python'));
  assert.ok(result.metadata.fileTypes.includes('yaml'));
  
  console.log('  [OK] Multi-file resolution works');
  console.log(`  [OK] File types detected: ${result.metadata.fileTypes.join(', ')}`);
}

async function testPathResolution() {
  console.log('\n[TEST] Path-based resolution...');
  
  const resolver = new ContentResolver();
  
  // Test reading this test file
  const result = await resolver.resolve({
    path: import.meta.url.replace('file://', '')
  });
  
  assert.equal(result.type, 'single');
  assert.equal(result.contentType, 'javascript');
  assert.equal(result.source, 'local_fs');
  assert.ok(result.metadata.originalPath);
  assert.ok(result.content.includes('ContentResolver Tests'));
  
  console.log('  [OK] File path resolution works');
  console.log(`  [OK] Detected type: ${result.contentType}`);
  console.log(`  [OK] Line count: ${result.metadata.lineCount}`);
}

async function testPathFallback() {
  console.log('\n[TEST] Path fallback error handling...');
  
  const resolver = new ContentResolver({ throwOnPathError: false });
  
  const result = await resolver.resolve({
    path: '/nonexistent/file/path.txt'
  });
  
  assert.equal(result.type, 'error');
  assert.ok(result.metadata.error);
  assert.ok(result.metadata.suggestion.includes('content'));
  
  console.log('  [OK] Graceful error handling works');
  console.log(`  [OK] Error message: ${result.metadata.error.substring(0, 50)}...`);
}

async function testLooksLikeContent() {
  console.log('\n[TEST] Content vs path detection...');
  
  const resolver = new ContentResolver();
  
  // Should detect as content (multi-line)
  assert.ok(resolver.looksLikeContent('line1\nline2'));
  
  // Should detect as content (shebang)
  assert.ok(resolver.looksLikeContent('#!/bin/bash'));
  
  // Should detect as content (code pattern)
  assert.ok(resolver.looksLikeContent('import os'));
  assert.ok(resolver.looksLikeContent('def main():'));
  assert.ok(resolver.looksLikeContent('function test() {'));
  
  // Should NOT detect as content (looks like path)
  assert.ok(!resolver.looksLikeContent('/usr/local/bin'));
  assert.ok(!resolver.looksLikeContent('scripts/test.sh'));
  
  console.log('  [OK] Content vs path heuristics work');
}

async function testStaticHelpers() {
  console.log('\n[TEST] Static helper methods...');
  
  const resolver = new ContentResolver();
  
  // Test isResolved
  const goodResult = await resolver.resolve({ content: 'test' });
  assert.ok(ContentResolver.isResolved(goodResult));
  
  // Test getAllContent for single
  const singleResult = await resolver.resolve({ content: 'hello world' });
  assert.equal(ContentResolver.getAllContent(singleResult), 'hello world');
  
  // Test getAllContent for multi
  const multiResult = await resolver.resolve({
    files: [
      { name: 'a.txt', content: 'content a' },
      { name: 'b.txt', content: 'content b' }
    ]
  });
  const combined = ContentResolver.getAllContent(multiResult);
  assert.ok(combined.includes('content a'));
  assert.ok(combined.includes('content b'));
  
  // Test iterateFiles
  let fileCount = 0;
  for (const file of ContentResolver.iterateFiles(multiResult)) {
    fileCount++;
    assert.ok(file.content);
  }
  assert.equal(fileCount, 2);
  
  console.log('  [OK] Static helpers work correctly');
}

async function testMissingInput() {
  console.log('\n[TEST] Missing input error...');
  
  const resolver = new ContentResolver();
  
  try {
    await resolver.resolve({});
    assert.fail('Should have thrown');
  } catch (err) {
    assert.ok(err instanceof ContentResolverError);
    assert.equal(err.code, 'MISSING_INPUT');
    console.log('  [OK] Missing input throws ContentResolverError');
  }
}

// Run all tests
async function runTests() {
  console.log('='.repeat(60));
  console.log('ContentResolver Test Suite - Phase 19A');
  console.log('='.repeat(60));
  
  try {
    await testDirectContent();
    await testFilesArray();
    await testPathResolution();
    await testPathFallback();
    await testLooksLikeContent();
    await testStaticHelpers();
    await testMissingInput();
    
    console.log('\n' + '='.repeat(60));
    console.log('[OK] ALL TESTS PASSED');
    console.log('='.repeat(60));
    process.exit(0);
  } catch (err) {
    console.error('\n[FAIL] Test failed:', err.message);
    console.error(err.stack);
    process.exit(1);
  }
}

runTests();
