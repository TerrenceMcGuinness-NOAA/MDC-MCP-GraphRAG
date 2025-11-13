#!/usr/bin/env node
/**
 * Ingest documentation from a URL list file into ChromaDB
 * 
 * This script reads URLs from a text file and ingests them using either:
 * - Deep crawl mode: Crawl each URL as a seed (discovers related pages)
 * - Direct mode: Process only the listed URLs
 * 
 * Usage:
 *   node scripts/ingest-from-url-list.js <url-file> [options]
 * 
 * Examples:
 *   node scripts/ingest-from-url-list.js extracted-urls/spack-all-urls.txt
 *   node scripts/ingest-from-url-list.js urls.txt --mode direct --collection spack-docs
 *   node scripts/ingest-from-url-list.js urls.txt --crawl --depth 2 --max-pages 100
 */

import { DocumentationIngester } from '../src/ingestion/DocumentationIngester.js';
import { EnhancedVectorStore } from '../src/rag/EnhancedVectorStore.js';
import fs from 'fs/promises';
import path from 'path';

/**
 * Parse command line arguments
 */
function parseArgs() {
  const args = process.argv.slice(2);
  
  if (args.length === 0 || args[0] === '--help' || args[0] === '-h') {
    console.log(`
Documentation Ingestion from URL List

Usage:
  node scripts/ingest-from-url-list.js <url-file> [options]

Options:
  --mode <direct|crawl>       Ingestion mode (default: direct)
                              direct: Process only listed URLs
                              crawl: Use each URL as crawl seed
  
  --collection <name>         ChromaDB collection name (default: documentation)
  --batch-size <n>           Batch size for processing (default: 10)
  --depth <n>                Crawl depth (crawl mode only, default: 2)
  --max-pages <n>            Max pages per seed (crawl mode only, default: 50)
  --quality-threshold <n>     Min quality score 0-1 (default: 0.4)
  --dry-run                  Show what would be ingested without doing it
  --skip-existing            Skip URLs already in database
  --resume-from <n>          Resume from URL index n

Examples:
  # Direct ingestion of listed URLs only
  node scripts/ingest-from-url-list.js extracted-urls/spack-all-urls.txt

  # Crawl mode - use each URL as a seed to discover more
  node scripts/ingest-from-url-list.js extracted-urls/spack-all-urls.txt --mode crawl --depth 2

  # Custom collection with quality filtering
  node scripts/ingest-from-url-list.js urls.txt --collection my-docs --quality-threshold 0.6

  # Dry run to see what would happen
  node scripts/ingest-from-url-list.js urls.txt --dry-run

  # Resume from URL #50 after interruption
  node scripts/ingest-from-url-list.js urls.txt --resume-from 50
`);
    process.exit(0);
  }

  const config = {
    urlFile: args[0],
    mode: 'direct',
    collection: 'documentation',
    batchSize: 10,
    depth: 2,
    maxPages: 50,
    qualityThreshold: 0.4,
    dryRun: false,
    skipExisting: false,
    resumeFrom: 0
  };

  for (let i = 1; i < args.length; i++) {
    if (args[i] === '--mode' && args[i + 1]) {
      config.mode = args[i + 1];
      i++;
    } else if (args[i] === '--collection' && args[i + 1]) {
      config.collection = args[i + 1];
      i++;
    } else if (args[i] === '--batch-size' && args[i + 1]) {
      config.batchSize = parseInt(args[i + 1]);
      i++;
    } else if (args[i] === '--depth' && args[i + 1]) {
      config.depth = parseInt(args[i + 1]);
      i++;
    } else if (args[i] === '--max-pages' && args[i + 1]) {
      config.maxPages = parseInt(args[i + 1]);
      i++;
    } else if (args[i] === '--quality-threshold' && args[i + 1]) {
      config.qualityThreshold = parseFloat(args[i + 1]);
      i++;
    } else if (args[i] === '--dry-run') {
      config.dryRun = true;
    } else if (args[i] === '--skip-existing') {
      config.skipExisting = true;
    } else if (args[i] === '--resume-from' && args[i + 1]) {
      config.resumeFrom = parseInt(args[i + 1]);
      i++;
    } else if (args[i] === '--crawl') {
      config.mode = 'crawl';
    }
  }

  return config;
}

/**
 * Read URLs from file
 */
async function readUrlFile(filePath) {
  try {
    const content = await fs.readFile(filePath, 'utf-8');
    const lines = content.split('\n');
    
    const urls = [];
    for (const line of lines) {
      const trimmed = line.trim();
      // Skip empty lines and comments
      if (!trimmed || trimmed.startsWith('#')) continue;
      
      // Check if it's a valid URL
      if (trimmed.startsWith('http://') || trimmed.startsWith('https://')) {
        urls.push(trimmed);
      }
    }
    
    return urls;
  } catch (error) {
    throw new Error(`Failed to read URL file: ${error.message}`);
  }
}

/**
 * Check if vector store is accessible
 */
async function checkDatabase(vectorStore) {
  try {
    await vectorStore.initialize();
    console.log('✅ Vector store initialized successfully\n');
    return true;
  } catch (error) {
    console.error('❌ Vector store initialization failed:', error.message);
    console.error('\nMake sure the knowledge base directory exists\n');
    return false;
  }
}

/**
 * Direct ingestion mode - process listed URLs only
 */
async function ingestDirect(urls, config, vectorStore) {
  console.log('📄 DIRECT INGESTION MODE');
  console.log(`   Processing ${urls.length} URLs directly\n`);

  const ingester = new DocumentationIngester({
    enableDeepCrawl: false,
    enableSemanticChunking: true,
    semanticChunkTargetSize: 1500,
    semanticChunkMaxSize: 3000,
    minQualityScore: config.qualityThreshold,
    maxConcurrentFetches: config.batchSize
  });

  // Format URLs for ingester and set prioritizedUrls directly
  const urlList = urls.map(url => ({
    url,
    category: 'external',
    subcategory: 'documentation',
    priority: 5
  }));

  console.log(`📋 Formatted ${urlList.length} URLs for ingestion`);

  // Set prioritizedUrls directly since ingestDocumentation() uses it
  ingester.prioritizedUrls = urlList;
  ingester.stats.totalUrls = urlList.length;

  console.log(`📤 Starting ingestion of ${urlList.length} URLs\n`);

  const results = await ingester.ingestDocumentation();

  return results;
}

/**
 * Crawl mode - use each URL as a seed
 */
async function ingestCrawl(urls, config, vectorStore) {
  console.log('🕷️  CRAWL INGESTION MODE');
  console.log(`   Using ${urls.length} URLs as crawl seeds`);
  console.log(`   Max Depth: ${config.depth}, Max Pages per seed: ${config.maxPages}\n`);

  const ingester = new DocumentationIngester({
    enableDeepCrawl: true,
    crawlMaxDepth: config.depth,
    crawlMaxPages: config.maxPages,
    crawlStrategy: 'bfs',
    respectRobotsTxt: true,
    enableSemanticChunking: true,
    semanticChunkTargetSize: 1500,
    semanticChunkMaxSize: 3000,
    minQualityScore: config.qualityThreshold,
    maxConcurrentFetches: config.batchSize
  });

  const results = await ingester.crawlAndIngest(urls);

  return results;
}

/**
 * Store chunks in vector store
 */
async function storeChunks(chunks, vectorStore, config) {
  if (chunks.length === 0) {
    console.log('⚠️  No chunks to store\n');
    return { stored: 0, failed: 0 };
  }

  console.log(`\n💾 Storing ${chunks.length} chunks in vector store...`);

  if (config.dryRun) {
    console.log('🔍 DRY RUN - Would store but skipping actual storage\n');
    return { stored: chunks.length, failed: 0 };
  }

  try {
    // Format chunks for EnhancedVectorStore
    const formattedChunks = chunks.map(chunk => ({
      content: chunk.content,
      metadata: {
        source: chunk.metadata.source || 'unknown',
        sourceType: 'external_documentation',
        category: chunk.metadata.category || 'documentation',
        subcategory: chunk.metadata.subcategory || 'general',
        title: chunk.metadata.title || '',
        ...chunk.metadata
      },
      qualityScore: chunk.qualityScore || 0.5
    }));

    // Save to external_documentation_chunks.json
    const chunksPath = path.join(
      vectorStore.options.knowledgeBasePath,
      'external_documentation_chunks.json'
    );

    // Load existing chunks if any
    let existingChunks = [];
    try {
      const existingData = await fs.readFile(chunksPath, 'utf-8');
      existingChunks = JSON.parse(existingData);
    } catch (error) {
      // File doesn't exist yet, that's okay
    }

    // Merge with new chunks (avoid duplicates by source+chunkIndex)
    const existingChunkMap = new Map(
      existingChunks.map(c => [`${c.metadata.source}:${c.metadata.chunkIndex}`, c])
    );
    
    formattedChunks.forEach(chunk => {
      const key = `${chunk.metadata.source}:${chunk.metadata.chunkIndex}`;
      existingChunkMap.set(key, chunk);
    });
    
    const allChunks = Array.from(existingChunkMap.values());

    // Ensure directory exists
    await fs.mkdir(path.dirname(chunksPath), { recursive: true });

    // Save updated chunks
    await fs.writeFile(chunksPath, JSON.stringify(allChunks, null, 2));

    console.log(`✅ Saved ${formattedChunks.length} new chunks to ${chunksPath}`);
    console.log(`📊 Total chunks in store: ${allChunks.length}\n`);
    
    return { stored: formattedChunks.length, failed: 0 };

  } catch (error) {
    console.error(`❌ Storage failed: ${error.message}\n`);
    return { stored: 0, failed: chunks.length };
  }
}

/**
 * Main ingestion function
 */
async function main() {
  console.log('📚 Documentation Ingestion from URL List\n');
  console.log('='.repeat(70) + '\n');

  const startTime = Date.now();

  try {
    const config = parseArgs();

    // Validate URL file
    const urlFilePath = path.resolve(config.urlFile);
    console.log(`📋 URL File: ${urlFilePath}`);
    
    try {
      await fs.access(urlFilePath);
    } catch {
      console.error(`❌ URL file not found: ${urlFilePath}\n`);
      return 1;
    }

    // Read URLs
    console.log('📖 Reading URLs...');
    const allUrls = await readUrlFile(urlFilePath);
    
    if (allUrls.length === 0) {
      console.error('❌ No valid URLs found in file\n');
      return 1;
    }

    // Apply resume-from
    const urls = config.resumeFrom > 0 ? allUrls.slice(config.resumeFrom) : allUrls;
    
    console.log(`✅ Found ${allUrls.length} URLs`);
    if (config.resumeFrom > 0) {
      console.log(`   Resuming from URL #${config.resumeFrom} (${urls.length} remaining)`);
    }
    console.log('');

    // Display configuration
    console.log('⚙️  Configuration:');
    console.log(`   Mode: ${config.mode}`);
    console.log(`   Collection: ${config.collection}`);
    console.log(`   Batch Size: ${config.batchSize}`);
    console.log(`   Quality Threshold: ${config.qualityThreshold}`);
    if (config.mode === 'crawl') {
      console.log(`   Crawl Depth: ${config.depth}`);
      console.log(`   Max Pages: ${config.maxPages}`);
    }
    if (config.dryRun) {
      console.log('   🔍 DRY RUN MODE - No data will be stored');
    }
    console.log('');

    // Initialize vector store
    const vectorStore = new EnhancedVectorStore({
      collectionName: config.collection,
      enableExternalSources: true
    });

    if (!config.dryRun) {
      const dbOk = await checkDatabase(vectorStore);
      if (!dbOk) {
        return 1;
      }
    } else {
      console.log('🔍 Skipping database check (dry run mode)\n');
    }

    // Sample URLs
    console.log('📄 Sample URLs (first 5):');
    urls.slice(0, 5).forEach((url, i) => {
      console.log(`   ${i + 1}. ${url}`);
    });
    if (urls.length > 5) {
      console.log(`   ... and ${urls.length - 5} more`);
    }
    console.log('');

    // Ingest based on mode
    console.log('🚀 Starting ingestion...\n');
    console.log('='.repeat(70) + '\n');

    let results;
    if (config.mode === 'direct') {
      results = await ingestDirect(urls, config, vectorStore);
    } else if (config.mode === 'crawl') {
      results = await ingestCrawl(urls, config, vectorStore);
    } else {
      console.error(`❌ Invalid mode: ${config.mode}\n`);
      return 1;
    }

    // Collect all chunks
    const allChunks = [];
    if (results.successful) {
      for (const result of results.successful) {
        if (result.chunks) {
          allChunks.push(...result.chunks);
        }
      }
    } else if (results.chunks) {
      allChunks.push(...results.chunks);
    }

    // Store in ChromaDB
    const storageResults = await storeChunks(allChunks, vectorStore, config);

    // Final summary
    const duration = ((Date.now() - startTime) / 1000).toFixed(2);

    console.log('='.repeat(70));
    console.log('📊 INGESTION SUMMARY');
    console.log('='.repeat(70));
    console.log(`⏱️  Total Time: ${duration}s`);
    console.log(`📋 URLs Processed: ${urls.length}`);
    
    if (results.successful) {
      console.log(`✅ Successful: ${results.successful.length}`);
      console.log(`❌ Failed: ${results.failed?.length || 0}`);
    }
    
    console.log(`📄 Total Chunks Generated: ${allChunks.length}`);
    console.log(`💾 Chunks Stored: ${storageResults.stored}`);
    console.log(`❌ Storage Failures: ${storageResults.failed}`);
    
    if (allChunks.length > 0) {
      const avgQuality = allChunks.reduce((sum, c) => sum + (c.qualityScore || 0), 0) / allChunks.length;
      const avgSize = Math.round(allChunks.reduce((sum, c) => sum + c.content.length, 0) / allChunks.length);
      console.log(`⭐ Average Quality: ${(avgQuality * 100).toFixed(1)}%`);
      console.log(`📏 Average Chunk Size: ${avgSize} chars`);
    }
    
    if (config.mode === 'crawl' && results.crawlStats) {
      console.log(`\n🕷️  Crawl Statistics:`);
      console.log(`   Pages Discovered: ${results.crawlStats.pagesDiscovered || 0}`);
      console.log(`   Pages Crawled: ${results.crawlStats.pagesCrawled || 0}`);
      console.log(`   Pages Skipped: ${results.crawlStats.pagesSkipped || 0}`);
      console.log(`   Crawl Errors: ${results.crawlStats.errorCount || 0}`);
    }

    console.log('='.repeat(70));

    if (config.dryRun) {
      console.log('\n🔍 DRY RUN COMPLETE - No data was actually stored\n');
    } else {
      console.log('\n✅ INGESTION COMPLETE!\n');
    }

    return 0;

  } catch (error) {
    console.error('\n❌ Error:', error.message);
    console.error(error.stack);
    return 1;
  }
}

// Run
main()
  .then(exitCode => process.exit(exitCode))
  .catch(error => {
    console.error('Fatal error:', error);
    process.exit(1);
  });
