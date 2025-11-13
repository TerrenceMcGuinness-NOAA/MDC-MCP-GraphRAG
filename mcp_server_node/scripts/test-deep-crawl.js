#!/usr/bin/env node
/**
 * Test script for deep web crawling with semantic chunking
 * 
 * This script validates the integration of:
 * - WebCrawler: Deep crawling with robots.txt and sitemap support
 * - SemanticChunker: Context7-inspired semantic chunking
 * - DocumentationIngester: crawlAndIngest() orchestration
 * 
 * Usage:
 *   node scripts/test-deep-crawl.js [--depth N] [--pages N] [--url URL]
 */

import { DocumentationIngester } from '../src/ingestion/DocumentationIngester.js';
import path from 'path';
import fs from 'fs/promises';

/**
 * Parse command line arguments
 */
function parseArgs() {
  const args = process.argv.slice(2);
  const config = {
    maxDepth: 2,
    maxPages: 20,
    seedUrls: [
      'https://spack.readthedocs.io/en/latest/getting_started.html'
    ]
  };

  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--depth' && args[i + 1]) {
      config.maxDepth = parseInt(args[i + 1]);
      i++;
    } else if (args[i] === '--pages' && args[i + 1]) {
      config.maxPages = parseInt(args[i + 1]);
      i++;
    } else if (args[i] === '--url' && args[i + 1]) {
      config.seedUrls = [args[i + 1]];
      i++;
    }
  }

  return config;
}

/**
 * Analyze crawl results for quality and structure
 */
function analyzeResults(results) {
  const analysis = {
    totalChunks: 0,
    chunksByType: {},
    qualityScores: [],
    hasCode: 0,
    hasTable: 0,
    hasList: 0,
    avgChunkSize: 0,
    sectionDepths: [],
    exampleChunks: 0
  };

  // Handle empty or invalid results
  if (!results || !Array.isArray(results)) {
    return analysis;
  }

  for (const result of results) {
    if (result.success && result.chunks) {
      analysis.totalChunks += result.chunks.length;

      for (const chunk of result.chunks) {
        // Quality scores
        if (chunk.qualityScore !== undefined) {
          analysis.qualityScores.push(chunk.qualityScore);
        }

        // Chunk types
        const chunkType = chunk.metadata?.chunkType || 'unknown';
        analysis.chunksByType[chunkType] = (analysis.chunksByType[chunkType] || 0) + 1;

        // Content features
        if (chunk.metadata?.hasCode) analysis.hasCode++;
        if (chunk.metadata?.hasTable) analysis.hasTable++;
        if (chunk.metadata?.hasList) analysis.hasList++;

        // Section depth
        if (chunk.metadata?.sectionPath) {
          const depth = chunk.metadata.sectionPath.split(' > ').length;
          analysis.sectionDepths.push(depth);
        }

        // Example preservation
        if (chunk.metadata?.chunkType === 'example') {
          analysis.exampleChunks++;
        }

        // Chunk size
        analysis.avgChunkSize += chunk.content.length;
      }
    }
  }

  // Calculate averages
  if (analysis.totalChunks > 0) {
    analysis.avgChunkSize = Math.round(analysis.avgChunkSize / analysis.totalChunks);
    analysis.avgQualityScore = analysis.qualityScores.length > 0
      ? (analysis.qualityScores.reduce((a, b) => a + b, 0) / analysis.qualityScores.length).toFixed(3)
      : 0;
    analysis.avgSectionDepth = analysis.sectionDepths.length > 0
      ? (analysis.sectionDepths.reduce((a, b) => a + b, 0) / analysis.sectionDepths.length).toFixed(2)
      : 0;
  }

  return analysis;
}

/**
 * Validate semantic chunking features
 */
function validateSemanticFeatures(results) {
  const validations = {
    codePreservation: false,
    examplePreservation: false,
    contextWindows: false,
    headerBoundaries: false,
    listIntegrity: false
  };

  // Handle empty or invalid results
  if (!results || !Array.isArray(results)) {
    return validations;
  }

  for (const result of results) {
    if (result.success && result.chunks) {
      for (const chunk of result.chunks) {
        const meta = chunk.metadata || {};

        // Check for code blocks
        if (meta.hasCode && chunk.content.includes('```')) {
          validations.codePreservation = true;
        }

        // Check for examples (explanation + code together)
        if (meta.chunkType === 'example') {
          validations.examplePreservation = true;
        }

        // Check for context windows (section paths)
        if (meta.sectionPath && meta.sectionPath.includes('>')) {
          validations.contextWindows = true;
        }

        // Check for header boundaries
        if (meta.chunkType === 'section' || meta.chunkType === 'subsection') {
          validations.headerBoundaries = true;
        }

        // Check for list integrity
        if (meta.hasList) {
          validations.listIntegrity = true;
        }
      }
    }
  }

  return validations;
}

/**
 * Main test function
 */
async function testDeepCrawl() {
  console.log('🧪 Testing Deep Web Crawling with Semantic Chunking\n');

  const config = parseArgs();
  console.log('Configuration:');
  console.log(`  Max Depth: ${config.maxDepth}`);
  console.log(`  Max Pages: ${config.maxPages}`);
  console.log(`  Seed URLs: ${config.seedUrls.join(', ')}\n`);

  try {
    // Initialize ingester with deep crawl enabled
    const ingester = new DocumentationIngester({
      enableDeepCrawl: true,
      crawlMaxDepth: config.maxDepth,
      crawlMaxPages: config.maxPages,
      crawlStrategy: 'bfs',
      respectRobotsTxt: true,
      enableSemanticChunking: true,
      semanticChunkTargetSize: 1500,
      semanticChunkMaxSize: 3000,
      minQualityScore: 0.4,
      maxConcurrentFetches: 3
    });

    console.log('📡 Starting deep crawl...\n');
    const startTime = Date.now();

    // Run deep crawl and ingestion
    const results = await ingester.crawlAndIngest(config.seedUrls);

    const duration = ((Date.now() - startTime) / 1000).toFixed(2);

    // Check if crawl was successful
    if (!results || !results.crawlStats || results.crawlStats.crawled === 0) {
      console.log('\n❌ No pages were successfully crawled.');
      console.log('\nPossible issues:');
      console.log('  - URL may be incorrect or inaccessible');
      console.log('  - Site may be blocking crawlers (check robots.txt)');
      console.log('  - Network connectivity issues');
      console.log('\nTry a different URL or check the site accessibility.\n');
      return 1;
    }

    // Display results
    console.log('\n' + '='.repeat(70));
    console.log('📊 CRAWL RESULTS');
    console.log('='.repeat(70));

    if (results.crawlStats) {
      console.log('\nCrawl Statistics:');
      console.log(`  Pages Discovered: ${results.crawlStats.discovered || 0}`);
      console.log(`  Pages Crawled: ${results.crawlStats.crawled || 0}`);
      console.log(`  Pages Skipped: ${results.crawlStats.skipped || 0}`);
      console.log(`  Errors: ${results.crawlStats.errors || 0}`);
      console.log(`  Duration: ${duration}s`);
      console.log(`  Speed: ${((results.crawlStats.crawled || 0) / parseFloat(duration)).toFixed(2)} pages/sec`);
    }

    console.log('\nIngestion Statistics:');
    const totalProcessed = (results.successful?.length || 0) + (results.failed?.length || 0);
    console.log(`  Total Processed: ${totalProcessed}`);
    console.log(`  Successful: ${results.successful?.length || 0}`);
    console.log(`  Failed: ${results.failed?.length || 0}`);

    // Analyze results - use successful array
    const analysis = analyzeResults(results.successful || []);

    console.log('\n' + '='.repeat(70));
    console.log('🔍 CONTENT ANALYSIS');
    console.log('='.repeat(70));

    console.log(`\nTotal Chunks: ${analysis.totalChunks}`);
    console.log(`Average Chunk Size: ${analysis.avgChunkSize} chars`);
    console.log(`Average Quality Score: ${analysis.avgQualityScore}`);
    console.log(`Average Section Depth: ${analysis.avgSectionDepth}`);

    console.log('\nChunk Types:');
    for (const [type, count] of Object.entries(analysis.chunksByType)) {
      const percentage = ((count / analysis.totalChunks) * 100).toFixed(1);
      console.log(`  ${type}: ${count} (${percentage}%)`);
    }

    console.log('\nContent Features:');
    console.log(`  Chunks with Code: ${analysis.hasCode}`);
    console.log(`  Chunks with Tables: ${analysis.hasTable}`);
    console.log(`  Chunks with Lists: ${analysis.hasList}`);
    console.log(`  Example Chunks: ${analysis.exampleChunks}`);

    // Validate semantic features
    const validations = validateSemanticFeatures(results.successful || []);

    console.log('\n' + '='.repeat(70));
    console.log('✅ SEMANTIC CHUNKING VALIDATION');
    console.log('='.repeat(70));

    console.log('\nContext7 Features:');
    console.log(`  Code Preservation: ${validations.codePreservation ? '✓' : '✗'}`);
    console.log(`  Example Preservation: ${validations.examplePreservation ? '✓' : '✗'}`);
    console.log(`  Context Windows: ${validations.contextWindows ? '✓' : '✗'}`);
    console.log(`  Header Boundaries: ${validations.headerBoundaries ? '✓' : '✗'}`);
    console.log(`  List Integrity: ${validations.listIntegrity ? '✓' : '✗'}`);

    // Sample chunks
    console.log('\n' + '='.repeat(70));
    console.log('📄 SAMPLE CHUNKS');
    console.log('='.repeat(70));

    let samplesShown = 0;
    const resultsArray = results.successful || [];
    for (const result of resultsArray) {
      if (result.success && result.chunks && samplesShown < 3) {
        for (const chunk of result.chunks) {
          if (chunk.metadata?.chunkType === 'example' || chunk.metadata?.hasCode) {
            console.log(`\nChunk Type: ${chunk.metadata.chunkType}`);
            console.log(`Section Path: ${chunk.metadata.sectionPath || 'N/A'}`);
            console.log(`Quality Score: ${chunk.qualityScore?.toFixed(3) || 'N/A'}`);
            console.log(`Content Preview (${chunk.content.length} chars):`);
            console.log(chunk.content.substring(0, 300) + '...\n');
            samplesShown++;
            if (samplesShown >= 3) break;
          }
        }
      }
      if (samplesShown >= 3) break;
    }

    // Save detailed results
    const outputPath = path.join(process.cwd(), 'test-results', `crawl-test-${Date.now()}.json`);
    await fs.mkdir(path.dirname(outputPath), { recursive: true });
    await fs.writeFile(outputPath, JSON.stringify(results, null, 2));

    console.log('\n' + '='.repeat(70));
    console.log(`📁 Detailed results saved to: ${outputPath}`);
    console.log('='.repeat(70) + '\n');

    // Summary
    const allFeaturesValid = Object.values(validations).every(v => v === true);
    if (allFeaturesValid) {
      console.log('✅ ALL SEMANTIC CHUNKING FEATURES VALIDATED SUCCESSFULLY!\n');
    } else {
      console.log('⚠️  Some semantic features not detected (may need more content or different URLs)\n');
    }

    return 0;

  } catch (error) {
    console.error('❌ Test failed:', error);
    console.error(error.stack);
    return 1;
  }
}

// Run test
testDeepCrawl()
  .then(exitCode => process.exit(exitCode))
  .catch(error => {
    console.error('Fatal error:', error);
    process.exit(1);
  });
