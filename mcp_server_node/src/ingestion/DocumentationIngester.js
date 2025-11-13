#!/usr/bin/env node

/**
 * DocumentationIngester - Main orchestrator for external documentation ingestion
 *
 * Coordinates the complete pipeline for ingesting external documentation sources:
 * - Loads documentation-references.json configuration
 * - Fetches content from all external URLs with priority ordering
 * - Extracts and cleans content from multiple formats
 * - Generates embeddings and updates vector database
 * - Provides progress monitoring and error handling
 *
 * @version 1.0.0
 * @author NOAA EMC Global Workflow Team
 */

import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';
import { URLFetcher } from './URLFetcher.js';
import { ContentExtractor } from './ContentExtractor.js';
import { WebCrawler } from './WebCrawler.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export class DocumentationIngester {
  constructor(options = {}) {
    this.options = {
      // Configuration paths
      documentationReferencesPath: options.documentationReferencesPath ||
        path.join(__dirname, '../../test/documentation-references.json'),

      outputDirectory: options.outputDirectory ||
        path.join(__dirname, '../../knowledge-base'),

      // Processing options
      maxConcurrentFetches: options.maxConcurrentFetches || 3,
      enablePriorityOrdering: options.enablePriorityOrdering !== false,

      // Deep crawling options
      enableDeepCrawl: options.enableDeepCrawl !== false,
      crawlMaxDepth: options.crawlMaxDepth || 3,
      crawlMaxPages: options.crawlMaxPages || 1000,
      crawlStrategy: options.crawlStrategy || 'bfs',
      respectRobotsTxt: options.respectRobotsTxt !== false,

      // Content filtering
      enableContentFiltering: options.enableContentFiltering !== false,
      minQualityScore: options.minQualityScore || 0.3,

      // Semantic chunking
      enableSemanticChunking: options.enableSemanticChunking !== false,
      semanticChunkTargetSize: options.semanticChunkTargetSize || 1500,
      semanticChunkMaxSize: options.semanticChunkMaxSize || 3000,

      // Progress tracking
      enableProgressLogging: options.enableProgressLogging !== false,
      progressReportInterval: options.progressReportInterval || 10,

      ...options
    };

    this.urlFetcher = new URLFetcher({
      maxRetries: 3,
      timeoutMs: 30000,
      rateLimit: 2, // 2 requests per second to be respectful
      enableCaching: true,
      cacheDirectory: path.join(this.options.outputDirectory, 'cache')
    });

    this.contentExtractor = new ContentExtractor({
      chunkSize: this.options.semanticChunkTargetSize,
      chunkOverlap: 200,
      minContentLength: 100,
      enableSemanticChunking: this.options.enableSemanticChunking,
      semanticChunkMaxSize: this.options.semanticChunkMaxSize
    });

    // Initialize web crawler if deep crawl is enabled
    this.webCrawler = null;
    if (this.options.enableDeepCrawl) {
      this.webCrawler = new WebCrawler({
        strategy: this.options.crawlStrategy,
        maxDepth: this.options.crawlMaxDepth,
        maxPages: this.options.crawlMaxPages,
        respectRobotsTxt: this.options.respectRobotsTxt,
        useSitemaps: true,
        crawlDelay: 1000,
        maxConcurrentRequests: this.options.maxConcurrentFetches
      });
    }

    this.stats = {
      startTime: null,
      endTime: null,
      totalUrls: 0,
      successfulUrls: 0,
      failedUrls: 0,
      totalChunks: 0,
      totalBytes: 0,
      averageQualityScore: 0,
      categoryStats: {},
      errors: []
    };

    this.documentationConfig = null;
    this.prioritizedUrls = [];
  }

  /**
   * Initialize the ingester
   */
  async initialize() {
    console.error('[START] Initializing Documentation Ingester...');

    // Create output directory
    await fs.mkdir(this.options.outputDirectory, { recursive: true });

    // Initialize components
    await this.urlFetcher.initialize();

    // Load documentation configuration
    await this.loadDocumentationConfig();

    // Prepare prioritized URL list
    this.prepareUrlList();

    console.error(`[OK] Documentation Ingester initialized`);
    console.error(`[STATS] Found ${this.stats.totalUrls} URLs across ${Object.keys(this.stats.categoryStats).length} categories`);
  }

  /**
   * Load and validate documentation-references.json
   */
  async loadDocumentationConfig() {
    try {
      const configContent = await fs.readFile(this.options.documentationReferencesPath, 'utf-8');
      this.documentationConfig = JSON.parse(configContent);

      if (!this.documentationConfig.documentation_references) {
        throw new Error('Invalid configuration: missing documentation_references');
      }

      console.error('[OK] Documentation configuration loaded');
    } catch (error) {
      throw new Error(`Failed to load documentation configuration: ${error.message}`);
    }
  }

  /**
   * Prepare prioritized URL list from configuration
   */
  prepareUrlList() {
    const urlList = [];
    const searchPriorities = this.documentationConfig.search_priorities || {};
    const references = this.documentationConfig.documentation_references;

    // Extract all URLs with metadata
    this._extractUrlsFromSection(references, '', urlList, searchPriorities);

    // Sort by priority if enabled
    if (this.options.enablePriorityOrdering) {
      urlList.sort((a, b) => (b.priority || 0) - (a.priority || 0));
    }

    this.prioritizedUrls = urlList;
    this.stats.totalUrls = urlList.length;

    // Calculate category statistics
    const categoryStats = {};
    urlList.forEach(urlInfo => {
      const category = urlInfo.category;
      if (!categoryStats[category]) {
        categoryStats[category] = {
          count: 0,
          avgPriority: 0,
          urls: []
        };
      }
      categoryStats[category].count++;
      categoryStats[category].avgPriority += urlInfo.priority || 0;
      categoryStats[category].urls.push(urlInfo.url);
    });

    // Calculate average priorities
    Object.values(categoryStats).forEach(stat => {
      stat.avgPriority = stat.count > 0 ? stat.avgPriority / stat.count : 0;
    });

    this.stats.categoryStats = categoryStats;

    if (this.options.enableProgressLogging) {
      console.error('[STATS] URL Categories:');
      Object.entries(categoryStats).forEach(([category, stats]) => {
        console.error(`  ${category}: ${stats.count} URLs (priority: ${stats.avgPriority.toFixed(1)})`);
      });
    }
  }

  /**
   * Recursively extract URLs from configuration sections
   */
  _extractUrlsFromSection(section, pathPrefix, urlList, priorities, depth = 0) {
    if (depth > 10) return; // Prevent infinite recursion

    Object.entries(section).forEach(([key, value]) => {
      const currentPath = pathPrefix ? `${pathPrefix}.${key}` : key;

      if (typeof value === 'string' && (value.startsWith('http://') || value.startsWith('https://'))) {
        // Found a URL
        urlList.push({
          url: value,
          category: pathPrefix || key,
          subcategory: key,
          path: currentPath,
          priority: priorities[currentPath] || priorities[pathPrefix] || 0,
          source: 'external'
        });
      } else if (typeof value === 'object' && value !== null) {
        // Recurse into nested objects
        this._extractUrlsFromSection(value, currentPath, urlList, priorities, depth + 1);
      }
    });
  }

  /**
   * Ingest all documentation sources
   */
  async ingestDocumentation() {
    this.stats.startTime = new Date();
    console.error('📚 Starting documentation ingestion...');

    const results = {
      successful: [],
      failed: [],
      chunks: []
    };

    // Process URLs in batches to respect rate limiting
    const batchSize = this.options.maxConcurrentFetches;
    const batches = this._createBatches(this.prioritizedUrls, batchSize);

    for (let i = 0; i < batches.length; i++) {
      const batch = batches[i];

      if (this.options.enableProgressLogging) {
        console.error(`[LOAD] Processing batch ${i + 1}/${batches.length} (${batch.length} URLs)`);
      }

      const batchResults = await Promise.allSettled(
        batch.map(urlInfo => this.processSingleUrl(urlInfo))
      );

      // Process batch results
      batchResults.forEach((result, index) => {
        const urlInfo = batch[index];

        if (result.status === 'fulfilled' && result.value.success) {
          results.successful.push(result.value);
          results.chunks.push(...result.value.chunks);
          this.stats.successfulUrls++;
        } else {
          const error = result.status === 'rejected' ? result.reason : result.value.error;
          results.failed.push({
            url: urlInfo.url,
            category: urlInfo.category,
            error: error.message || error
          });
          this.stats.failedUrls++;
          this.stats.errors.push({
            url: urlInfo.url,
            error: error.message || error,
            timestamp: new Date().toISOString()
          });
        }
      });

      // Progress report
      if (this.options.enableProgressLogging &&
          (i + 1) % this.options.progressReportInterval === 0) {
        this._logProgress(i + 1, batches.length);
      }

      // Small delay between batches to be respectful
      if (i < batches.length - 1) {
        await this._delay(2000);
      }
    }

    this.stats.endTime = new Date();
    this.stats.totalChunks = results.chunks.length;

    // Calculate final statistics
    if (results.chunks.length > 0) {
      const totalQuality = results.chunks.reduce((sum, chunk) => sum + (chunk.qualityScore || 0), 0);
      this.stats.averageQualityScore = totalQuality / results.chunks.length;

      this.stats.totalBytes = results.chunks.reduce((sum, chunk) => sum + chunk.content.length, 0);
    }

    // Save results
    await this.saveResults(results);

    // Final report
    this._logFinalReport();

    return results;
  }

  /**
   * Crawl and ingest documentation sites with deep crawling
   */
  async crawlAndIngest(seedUrls, options = {}) {
    if (!this.options.enableDeepCrawl || !this.webCrawler) {
      throw new Error('Deep crawl not enabled. Set enableDeepCrawl: true in constructor options.');
    }

    this.stats.startTime = new Date();
    console.error('[CRAWL]  Starting deep crawl and ingestion...');

    // Configure crawler for specific domains if provided
    if (options.allowedDomains) {
      this.webCrawler.options.allowedDomains = options.allowedDomains;
    }
    if (options.urlPatterns) {
      this.webCrawler.options.urlPatterns = options.urlPatterns;
    }

    // Crawl sites
    const crawlResult = await this.webCrawler.crawl(seedUrls);

    console.error(`[OK] Crawl complete: ${crawlResult.results.length} pages discovered`);

    // Process crawled pages
    const results = {
      successful: [],
      failed: [],
      chunks: [],
      crawlStats: crawlResult.stats
    };

    // Process crawled pages in batches
    const batchSize = this.options.maxConcurrentFetches;
    const batches = this._createBatches(crawlResult.results, batchSize);

    for (let i = 0; i < batches.length; i++) {
      const batch = batches[i];

      if (this.options.enableProgressLogging) {
        console.error(`[LOAD] Processing batch ${i + 1}/${batches.length} (${batch.length} pages)`);
      }

      const batchResults = await Promise.allSettled(
        batch.map(crawledPage => this._processCrawledPage(crawledPage))
      );

      // Process batch results
      batchResults.forEach((result, index) => {
        const page = batch[index];

        if (result.status === 'fulfilled' && result.value.success) {
          results.successful.push(result.value);
          results.chunks.push(...result.value.chunks);
          this.stats.successfulUrls++;
        } else {
          const error = result.status === 'rejected' ? result.reason : result.value.error;
          results.failed.push({
            url: page.url,
            error: error.message || error
          });
          this.stats.failedUrls++;
          this.stats.errors.push({
            url: page.url,
            error: error.message || error,
            timestamp: new Date().toISOString()
          });
        }
      });

      // Progress report
      if (this.options.enableProgressLogging &&
          (i + 1) % this.options.progressReportInterval === 0) {
        this._logProgress(i + 1, batches.length);
      }
    }

    this.stats.endTime = new Date();
    this.stats.totalUrls = crawlResult.results.length;
    this.stats.totalChunks = results.chunks.length;

    // Calculate final statistics
    if (results.chunks.length > 0) {
      const totalQuality = results.chunks.reduce((sum, chunk) => sum + (chunk.qualityScore || 0), 0);
      this.stats.averageQualityScore = totalQuality / results.chunks.length;
      this.stats.totalBytes = results.chunks.reduce((sum, chunk) => sum + chunk.content.length, 0);
    }

    // Save results
    await this.saveResults(results);

    // Final report
    this._logFinalReport();

    console.error('\n[CRAWL]  CRAWL STATS:');
    console.error(`  Pages Discovered: ${crawlResult.stats.pagesDiscovered}`);
    console.error(`  Pages Crawled: ${crawlResult.stats.pagesCrawled}`);
    console.error(`  Pages Skipped: ${crawlResult.stats.pagesSkipped}`);
    console.error(`  Crawl Errors: ${crawlResult.stats.errorCount}`);

    return results;
  }

  /**
   * Process a crawled page (already has HTML content)
   */
  async _processCrawledPage(crawledPage) {
    try {
      const { url, html, metadata } = crawledPage;

      // Create a fetch response-like object for ContentExtractor
      const fetchResponse = {
        success: true,
        url,
        content: html,
        extractedText: html,
        metadata: {
          contentType: 'text/html',
          contentLength: html.length,
          ...metadata
        }
      };

      // Extract content
      const extractionResult = await this.contentExtractor.extractContent(fetchResponse);

      if (extractionResult.error) {
        throw new Error(`Extraction failed: ${extractionResult.error}`);
      }

      // Filter chunks by quality if enabled
      let chunks = extractionResult.chunks;
      if (this.options.enableContentFiltering) {
        const originalCount = chunks.length;
        chunks = chunks.filter(chunk => (chunk.qualityScore || 0) >= this.options.minQualityScore);

        if (chunks.length < originalCount) {
          console.warn(`[WARN] Filtered ${originalCount - chunks.length} low-quality chunks from ${url}`);
        }
      }

      // Add metadata to chunks
      chunks.forEach(chunk => {
        chunk.metadata.crawled = true;
        chunk.metadata.crawlDepth = metadata.depth || 0;
        chunk.metadata.ingestedAt = new Date().toISOString();
      });

      return {
        success: true,
        url,
        title: extractionResult.extractedData.title,
        chunks,
        stats: extractionResult.stats,
        metadata: metadata
      };

    } catch (error) {
      return {
        success: false,
        url: crawledPage.url,
        error: error.message
      };
    }
  }

  /**
   * Process a single URL through the entire pipeline
   */
  async processSingleUrl(urlInfo) {
    try {
      const { url, category, subcategory } = urlInfo;

      // Fetch content
      const fetchResponse = await this.urlFetcher.fetch(url);

      if (!fetchResponse.success) {
        throw new Error(`Fetch failed: ${fetchResponse.error || 'Unknown error'}`);
      }

      // Extract content
      const extractionResult = await this.contentExtractor.extractContent(fetchResponse);

      if (extractionResult.error) {
        throw new Error(`Extraction failed: ${extractionResult.error}`);
      }

      // Filter chunks by quality if enabled
      let chunks = extractionResult.chunks;
      if (this.options.enableContentFiltering) {
        const originalCount = chunks.length;
        chunks = chunks.filter(chunk => (chunk.qualityScore || 0) >= this.options.minQualityScore);

        if (chunks.length < originalCount) {
          console.warn(`[WARN] Filtered ${originalCount - chunks.length} low-quality chunks from ${url}`);
        }
      }

      // Add category metadata to chunks
      chunks.forEach(chunk => {
        chunk.metadata.category = category;
        chunk.metadata.subcategory = subcategory;
        chunk.metadata.priority = urlInfo.priority || 0;
        chunk.metadata.ingestedAt = new Date().toISOString();
      });

      return {
        success: true,
        url,
        category,
        subcategory,
        title: extractionResult.extractedData.title,
        chunks,
        stats: extractionResult.stats,
        metadata: fetchResponse.metadata
      };

    } catch (error) {
      return {
        success: false,
        url: urlInfo.url,
        category: urlInfo.category,
        error: error.message
      };
    }
  }

  /**
   * Save ingestion results to files
   */
  async saveResults(results) {
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');

    // Save chunks for vector database
    const chunksFile = path.join(this.options.outputDirectory, 'external_documentation_chunks.json');
    await fs.writeFile(chunksFile, JSON.stringify({
      metadata: {
        generatedAt: new Date().toISOString(),
        totalChunks: results.chunks.length,
        totalUrls: this.stats.totalUrls,
        successfulUrls: this.stats.successfulUrls,
        failedUrls: this.stats.failedUrls,
        averageQualityScore: this.stats.averageQualityScore,
        processingTimeMs: this.stats.endTime - this.stats.startTime
      },
      chunks: results.chunks
    }, null, 2));

    // Save ingestion summary
    const summaryFile = path.join(this.options.outputDirectory, `ingestion_summary_${timestamp}.json`);
    await fs.writeFile(summaryFile, JSON.stringify({
      stats: this.stats,
      successful: results.successful.map(r => ({
        url: r.url,
        category: r.category,
        title: r.title,
        chunkCount: r.chunks.length,
        totalLength: r.chunks.reduce((sum, chunk) => sum + chunk.content.length, 0)
      })),
      failed: results.failed
    }, null, 2));

    // Save detailed results for debugging
    const detailsFile = path.join(this.options.outputDirectory, `ingestion_details_${timestamp}.json`);
    await fs.writeFile(detailsFile, JSON.stringify(results, null, 2));

    console.error(`💾 Results saved to ${this.options.outputDirectory}`);
  }

  /**
   * Create batches from URL list
   */
  _createBatches(urls, batchSize) {
    const batches = [];
    for (let i = 0; i < urls.length; i += batchSize) {
      batches.push(urls.slice(i, i + batchSize));
    }
    return batches;
  }

  /**
   * Log progress information
   */
  _logProgress(completedBatches, totalBatches) {
    const completedUrls = Math.min(completedBatches * this.options.maxConcurrentFetches, this.stats.totalUrls);
    const percent = ((completedUrls / this.stats.totalUrls) * 100).toFixed(1);
    const elapsed = (new Date() - this.stats.startTime) / 1000;
    const rate = (completedUrls / elapsed).toFixed(2);

    console.error(`[STATS] Progress: ${completedUrls}/${this.stats.totalUrls} URLs (${percent}%) | ` +
                 `[OK] ${this.stats.successfulUrls} success | [ERROR] ${this.stats.failedUrls} failed | ` +
                 `[TIME] ${elapsed.toFixed(1)}s | 📈 ${rate} URLs/s`);
  }

  /**
   * Log final ingestion report
   */
  _logFinalReport() {
    const duration = (this.stats.endTime - this.stats.startTime) / 1000;
    const successRate = ((this.stats.successfulUrls / this.stats.totalUrls) * 100).toFixed(1);

    console.error('\n📚 DOCUMENTATION INGESTION COMPLETE');
    console.error('════════════════════════════════════');
    console.error(`[TIME]  Total Time: ${duration.toFixed(1)}s`);
    console.error(`[STATS] URLs Processed: ${this.stats.totalUrls}`);
    console.error(`[OK] Successful: ${this.stats.successfulUrls} (${successRate}%)`);
    console.error(`[ERROR] Failed: ${this.stats.failedUrls}`);
    console.error(`📄 Total Chunks: ${this.stats.totalChunks.toLocaleString()}`);
    console.error(`📏 Total Content: ${(this.stats.totalBytes / 1024 / 1024).toFixed(1)} MB`);
    console.error(`⭐ Avg Quality Score: ${(this.stats.averageQualityScore * 100).toFixed(1)}%`);
    console.error(`📈 Processing Rate: ${(this.stats.totalUrls / duration).toFixed(2)} URLs/s`);

    if (this.stats.failedUrls > 0) {
      console.error('\n[ERROR] FAILED URLS:');
      this.stats.errors.slice(0, 10).forEach(error => {
        console.error(`  ${error.url}: ${error.error}`);
      });
      if (this.stats.errors.length > 10) {
        console.error(`  ... and ${this.stats.errors.length - 10} more errors`);
      }
    }

    console.error('\n🎯 CATEGORY BREAKDOWN:');
    Object.entries(this.stats.categoryStats).forEach(([category, stats]) => {
      console.error(`  ${category}: ${stats.count} URLs`);
    });

    const fetcherStats = this.urlFetcher.getStats();
    const extractorStats = this.contentExtractor.getStats();

    console.error(`\n🔧 COMPONENT STATS:`);
    console.error(`  URLFetcher: ${fetcherStats.cacheHitRate} cache hit rate, ${fetcherStats.totalRequests} requests`);
    console.error(`  ContentExtractor: ${extractorStats.processed} documents, ${extractorStats.averageChunksPerDocument} avg chunks/doc`);
    console.error('════════════════════════════════════\n');
  }

  /**
   * Utility delay function
   */
  _delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  /**
   * Get current ingestion statistics
   */
  getStats() {
    return {
      ...this.stats,
      isRunning: this.stats.startTime && !this.stats.endTime,
      urlFetcherStats: this.urlFetcher.getStats(),
      contentExtractorStats: this.contentExtractor.getStats()
    };
  }

  /**
   * Validate all URLs in configuration (quick check)
   */
  async validateAllUrls() {
    console.error('[SEARCH] Validating all URLs...');

    const urls = this.prioritizedUrls.map(urlInfo => urlInfo.url);
    const validationResults = await this.urlFetcher.validateUrls(urls);

    const accessible = validationResults.filter(r => r.accessible).length;
    const inaccessible = validationResults.filter(r => !r.accessible);

    console.error(`[OK] URL Validation Complete: ${accessible}/${urls.length} accessible`);

    if (inaccessible.length > 0) {
      console.error('[ERROR] Inaccessible URLs:');
      inaccessible.slice(0, 10).forEach(result => {
        console.error(`  ${result.url}: ${result.error}`);
      });
    }

    return validationResults;
  }

  /**
   * Ingest specific categories only
   */
  async ingestCategories(categories) {
    const originalUrls = this.prioritizedUrls;
    this.prioritizedUrls = originalUrls.filter(urlInfo =>
      categories.includes(urlInfo.category)
    );

    this.stats.totalUrls = this.prioritizedUrls.length;

    try {
      const results = await this.ingestDocumentation();
      return results;
    } finally {
      // Restore original URL list
      this.prioritizedUrls = originalUrls;
      this.stats.totalUrls = originalUrls.length;
    }
  }
}