#!/usr/bin/env node

/**
 * Test Hugging Face Integration with RAG System
 */

import { HuggingFaceRAGUtils } from './huggingface-rag-utils.js';
import fs from 'fs/promises';
import path from 'path';

async function testHuggingFaceIntegration() {
  console.log('Testing Hugging Face Integration...');

  try {
    // Load configuration
    const configPath = path.join(process.cwd(), 'config', 'huggingface.json');
    const configData = await fs.readFile(configPath, 'utf8');
    const config = JSON.parse(configData);

    // Initialize utils
    const hfUtils = new HuggingFaceRAGUtils(config);

    // Test model search
    console.log('\n1. Testing model search...');
    const embeddingModels = await hfUtils.findRelevantModels('embeddings', 'sentence embedding');
    console.log('Found embedding models:', embeddingModels);

    // Test dataset search
    console.log('\n2. Testing dataset search...');
    const weatherDatasets = await hfUtils.findRelevantDatasets('weather');
    console.log('Found weather datasets:', weatherDatasets);

    // Test paper search (placeholder)
    console.log('\n3. Testing paper search...');
    await hfUtils.searchRelevantPapers('weather prediction models');

    // Test content generation (placeholder)
    console.log('\n4. Testing content generation...');
    await hfUtils.generateContent('# Documentation for weather model', 'text');

    console.log('\n✓ Hugging Face integration test completed successfully');
    return true;

  } catch (error) {
    console.error('❌ Integration test failed:', error.message);
    return false;
  }
}

// Run test if called directly
if (import.meta.url === `file://${process.argv[1]}`) {
  testHuggingFaceIntegration()
    .then(success => process.exit(success ? 0 : 1))
    .catch(error => {
      console.error('Test execution failed:', error);
      process.exit(1);
    });
}

export { testHuggingFaceIntegration };
