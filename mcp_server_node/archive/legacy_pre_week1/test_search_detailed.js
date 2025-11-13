#!/usr/bin/env node
import { RAGTools } from './src/tools/RAGTools.js';

async function test() {
  const ragTools = new RAGTools();
  await ragTools.initialize();
  
  console.log('\n🔍 Testing: "rocoto workflow configuration"\n');
  const result = await ragTools.searchDocumentation({
    query: 'rocoto workflow configuration',
    max_results: 2,
    similarity_threshold: 0.1
  });
  console.log(result.substring(0, 800) + '\n...\n');
  
  console.log('='.repeat(60) + '\n');
  console.log('🔍 Testing: "spack-stack HPC installation"\n');
  const result2 = await ragTools.searchDocumentation({
    query: 'spack-stack HPC installation',
    max_results: 2,
    similarity_threshold: 0.1
  });
  console.log(result2.substring(0, 800) + '\n...\n');
}

test();
