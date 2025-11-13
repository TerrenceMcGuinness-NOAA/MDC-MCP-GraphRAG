#!/usr/bin/env node

/**
 * WebCrawler - Deep web crawling with respect for robots.txt and rate limits
 *
 * Implements comprehensive web crawling for documentation ingestion:
 * - BFS (breadth-first) or DFS (depth-first) traversal
 * - Robots.txt compliance with RobotsTxtParser
 * - Sitemap.xml discovery and parsing
 * - URL normalization and deduplication
 * - Domain and path filtering
 * - Depth limiting and progress tracking
 * - Respectful rate limiting with crawl-delay
 *
 * @version 1.0.0
 * @author NOAA EMC Global Workflow Team
 */

import * as cheerio from 'cheerio';
import { RobotsTxtParser } from './RobotsTxtParser.js';
import { SitemapParser } from './SitemapParser.js';

export class WebCrawler {
  constructor(options = {}) {
    this.options = {
      // Crawl strategy
      strategy: options.strategy || 'bfs', // 'bfs' or 'dfs'
      maxDepth: options.maxDepth || 3,
      maxPages: options.maxPages || 1000,

      // Filtering
      allowedDomains: options.allowedDomains || [],
      disallowedDomains: options.disallowedDomains || [],
      urlPatterns: options.urlPatterns || [], // Regex patterns to match
      excludePatterns: options.excludePatterns || [
        /\.(pdf|zip|tar|gz|exe|dmg|pkg|deb|rpm)$/i,
        /\.(jpg|jpeg|png|gif|svg|ico|webp)$/i,
        /\.(mp4|avi|mov|wmv|flv|webm)$/i,
        /\.(mp3|wav|ogg|flac)$/i,
        /\/api\//i, // API endpoints
        /\?.*page=/i, // Pagination query params
        /#/i // Fragment identifiers
      ],

      // Robots.txt compliance
      respectRobotsTxt: options.respectRobotsTxt !== false,
      userAgent: options.userAgent || 'NOAA-Global-Workflow-RAG/1.0 (+https://github.com/NOAA-EMC/global-workflow)',

      // Rate limiting
      crawlDelay: options.crawlDelay || 1000, // Default 1 second between requests
      maxConcurrentRequests: options.maxConcurrentRequests || 3,

      // Sitemap usage
      useSitemaps: options.useSitemaps !== false,

      // Content validation
      followExternalLinks: options.followExternalLinks || false,
      maxContentSizeBytes: options.maxContentSizeBytes || 10 * 1024 * 1024,

      ...options
    };

    // State tracking
    this.queue = []; // URLs to visit: { url, depth, sourceUrl }
    this.visited = new Set(); // Normalized URLs already visited
    this.discovered = new Map(); // All discovered URLs with metadata
    this.results = []; // Successfully crawled pages
    this.errors = [];

    // Robots.txt cache: domain -> RobotsTxtParser
    this.robotsCache = new Map();

    // Statistics
    this.stats = {
      startTime: null,
      endTime: null,
      pagesDiscovered: 0,
      pagesCrawled: 0,
      pagesSkipped: 0,
      errorCount: 0,
      byDepth: {},
      byDomain: {}
    };

    this.isRunning = false;
  }

  /**
   * Start crawling from seed URLs
   */
  async crawl(seedUrls) {
    if (this.isRunning) {
      throw new Error('Crawler is already running');
    }

    this.isRunning = true;
    this.stats.startTime = new Date();

    console.error('[CRAWL]  Starting web crawl...');
    console.error(`[INFO] Seed URLs: ${seedUrls.length}`);
    console.error(`[CONFIG]  Strategy: ${this.options.strategy}, Max Depth: ${this.options.maxDepth}, Max Pages: ${this.options.maxPages}`);

    // Add seed URLs to queue
    for (const url of seedUrls) {
      this.addToQueue(url, 0, null);
    }

    // Try to use sitemaps first for comprehensive coverage
    if (this.options.useSitemaps) {
      await this._discoverFromSitemaps(seedUrls);
    }

    // Process queue
    await this._processQueue();

    this.stats.endTime = new Date();
    this.isRunning = false;

    this._logFinalReport();

    return {
      results: this.results,
      discovered: Array.from(this.discovered.values()),
      errors: this.errors,
      stats: this.getStats()
    };
  }

  /**
   * Add URL to crawl queue
   */
  addToQueue(url, depth, sourceUrl) {
    try {
      const normalizedUrl = this._normalizeUrl(url);

      if (!normalizedUrl) return;
      if (this.visited.has(normalizedUrl)) return;
      if (depth > this.options.maxDepth) return;

      // Check if already in queue
      if (this.queue.some(item => item.url === normalizedUrl)) return;

      // Apply filtering
      if (!this._shouldCrawl(normalizedUrl, depth)) return;

      // Add to queue
      const queueItem = {
        url: normalizedUrl,
        depth,
        sourceUrl,
        addedAt: Date.now()
      };

      if (this.options.strategy === 'bfs') {
        this.queue.push(queueItem); // BFS: add to end
      } else {
        this.queue.unshift(queueItem); // DFS: add to front
      }

      // Track discovery
      if (!this.discovered.has(normalizedUrl)) {
        this.discovered.set(normalizedUrl, {
          url: normalizedUrl,
          depth,
          sourceUrl,
          discoveredAt: new Date().toISOString(),
          status: 'queued'
        });

        this.stats.pagesDiscovered++;

        // Update depth stats
        this.stats.byDepth[depth] = (this.stats.byDepth[depth] || 0) + 1;

        // Update domain stats
        const domain = new URL(normalizedUrl).hostname;
        this.stats.byDomain[domain] = (this.stats.byDomain[domain] || 0) + 1;
      }

    } catch (error) {
      console.warn(`[WARN] Failed to add URL to queue: ${url} - ${error.message}`);
    }
  }

  /**
   * Process the crawl queue
   */
  async _processQueue() {
    const activeRequests = new Map(); // URL -> Promise

    while (this.queue.length > 0 || activeRequests.size > 0) {
      // Check limits
      if (this.stats.pagesCrawled >= this.options.maxPages) {
        console.warn(`[WARN] Reached max pages limit (${this.options.maxPages})`);
        break;
      }

      // Process concurrent requests
      while (
        this.queue.length > 0 &&
        activeRequests.size < this.options.maxConcurrentRequests &&
        this.stats.pagesCrawled < this.options.maxPages
      ) {
        const item = this.queue.shift();
        const promise = this._crawlPage(item);
        activeRequests.set(item.url, promise);

        // Apply crawl delay
        if (this.queue.length > 0) {
          await this._delay(this.options.crawlDelay);
        }
      }

      // Wait for at least one request to complete
      if (activeRequests.size > 0) {
        const results = await Promise.race(
          Array.from(activeRequests.entries()).map(([url, promise]) =>
            promise.then(() => ({ url, error: null }))
                   .catch(error => ({ url, error }))
          )
        );

        activeRequests.delete(results.url);
      }
    }

    // Wait for remaining requests
    if (activeRequests.size > 0) {
      await Promise.allSettled(Array.from(activeRequests.values()));
    }
  }

  /**
   * Crawl a single page
   */
  async _crawlPage(item) {
    const { url, depth } = item;

    try {
      this.visited.add(url);

      // Check robots.txt
      if (this.options.respectRobotsTxt) {
        const isAllowed = await this._checkRobotsTxt(url);
        if (!isAllowed) {
          this.stats.pagesSkipped++;
          this.discovered.get(url).status = 'skipped_robots';
          console.warn(`🤖 Skipped by robots.txt: ${url}`);
          return;
        }
      }

      // Fetch page
      const response = await fetch(url, {
        headers: {
          'User-Agent': this.options.userAgent
        },
        signal: AbortSignal.timeout(30000)
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      // Validate content type
      const contentType = response.headers.get('content-type') || '';
      if (!contentType.includes('text/html')) {
        this.stats.pagesSkipped++;
        this.discovered.get(url).status = 'skipped_content_type';
        return;
      }

      const html = await response.text();

      // Extract links if not at max depth
      let extractedLinks = [];
      if (depth < this.options.maxDepth) {
        extractedLinks = this._extractLinks(html, url);

        // Add discovered links to queue
        for (const link of extractedLinks) {
          this.addToQueue(link, depth + 1, url);
        }
      }

      // Record successful crawl
      this.results.push({
        url,
        depth,
        html,
        metadata: {
          contentType,
          contentLength: html.length,
          lastModified: response.headers.get('last-modified'),
          etag: response.headers.get('etag'),
          crawledAt: new Date().toISOString(),
          linksFound: extractedLinks.length
        }
      });

      this.stats.pagesCrawled++;
      this.discovered.get(url).status = 'success';

      if (this.stats.pagesCrawled % 10 === 0) {
        this._logProgress();
      }

    } catch (error) {
      this.stats.errorCount++;
      this.errors.push({
        url,
        error: error.message,
        timestamp: new Date().toISOString()
      });

      if (this.discovered.has(url)) {
        this.discovered.get(url).status = 'error';
        this.discovered.get(url).error = error.message;
      }

      console.error(`[ERROR] Failed to crawl ${url}: ${error.message}`);
    }
  }

  /**
   * Extract links from HTML content
   */
  _extractLinks(html, baseUrl) {
    const links = [];

    try {
      const $ = cheerio.load(html);
      const urlObj = new URL(baseUrl);

      $('a[href]').each((i, elem) => {
        try {
          const href = $(elem).attr('href');
          if (!href) return;

          // Resolve relative URLs
          const absoluteUrl = new URL(href, baseUrl).href;

          // Basic validation
          if (!absoluteUrl.startsWith('http://') && !absoluteUrl.startsWith('https://')) {
            return;
          }

          links.push(absoluteUrl);
        } catch (error) {
          // Invalid URL, skip
        }
      });

    } catch (error) {
      console.warn(`[WARN] Link extraction failed for ${baseUrl}: ${error.message}`);
    }

    return links;
  }

  /**
   * Check if URL should be crawled based on filters
   */
  _shouldCrawl(url, depth) {
    try {
      const urlObj = new URL(url);
      const domain = urlObj.hostname;

      // Check depth
      if (depth > this.options.maxDepth) return false;

      // Check domain whitelist
      if (this.options.allowedDomains.length > 0) {
        if (!this.options.allowedDomains.some(d => domain === d || domain.endsWith(`.${d}`))) {
          return false;
        }
      }

      // Check domain blacklist
      if (this.options.disallowedDomains.length > 0) {
        if (this.options.disallowedDomains.some(d => domain === d || domain.endsWith(`.${d}`))) {
          return false;
        }
      }

      // Check exclude patterns
      if (this.options.excludePatterns.length > 0) {
        if (this.options.excludePatterns.some(pattern => pattern.test(url))) {
          return false;
        }
      }

      // Check URL patterns (if specified)
      if (this.options.urlPatterns.length > 0) {
        if (!this.options.urlPatterns.some(pattern => pattern.test(url))) {
          return false;
        }
      }

      return true;

    } catch (error) {
      return false;
    }
  }

  /**
   * Check robots.txt for URL
   */
  async _checkRobotsTxt(url) {
    try {
      const urlObj = new URL(url);
      const domain = urlObj.hostname;

      // Check cache
      if (!this.robotsCache.has(domain)) {
        const robotsParser = await RobotsTxtParser.fetchAndParse(url, this.options.userAgent);
        this.robotsCache.set(domain, robotsParser);

        // Use crawl-delay from robots.txt if specified
        const crawlDelay = robotsParser.getCrawlDelay();
        if (crawlDelay && crawlDelay > this.options.crawlDelay) {
          console.warn(`[WARN] Increasing crawl delay to ${crawlDelay}ms as specified in robots.txt`);
          this.options.crawlDelay = crawlDelay;
        }
      }

      const robotsParser = this.robotsCache.get(domain);
      return robotsParser.isAllowed(url);

    } catch (error) {
      // On error, allow to be cautious but not overly restrictive
      return true;
    }
  }

  /**
   * Discover URLs from sitemaps
   */
  async _discoverFromSitemaps(seedUrls) {
    console.error('[MAP] Discovering URLs from sitemaps...');

    for (const seedUrl of seedUrls) {
      try {
        const sitemapParser = await SitemapParser.discoverAndParse(seedUrl, {
          userAgent: this.options.userAgent
        });

        const sitemapUrls = sitemapParser.getUrlsByPriority();

        if (sitemapUrls.length > 0) {
          console.error(`[OK] Found ${sitemapUrls.length} URLs in sitemap for ${seedUrl}`);

          // Add sitemap URLs to queue with depth 0 (treat as seeds)
          for (const urlData of sitemapUrls) {
            this.addToQueue(urlData.url, 0, 'sitemap');
          }
        }

      } catch (error) {
        console.warn(`[WARN] Sitemap discovery failed for ${seedUrl}: ${error.message}`);
      }
    }
  }

  /**
   * Normalize URL for deduplication
   */
  _normalizeUrl(url) {
    try {
      const urlObj = new URL(url);

      // Remove fragment
      urlObj.hash = '';

      // Sort query parameters
      const params = new URLSearchParams(urlObj.search);
      const sortedParams = new URLSearchParams([...params.entries()].sort());
      urlObj.search = sortedParams.toString();

      // Remove trailing slash from pathname (except root)
      if (urlObj.pathname !== '/' && urlObj.pathname.endsWith('/')) {
        urlObj.pathname = urlObj.pathname.slice(0, -1);
      }

      return urlObj.href;

    } catch (error) {
      return null;
    }
  }

  /**
   * Delay utility
   */
  _delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  /**
   * Log progress
   */
  _logProgress() {
    const elapsed = (new Date() - this.stats.startTime) / 1000;
    const rate = (this.stats.pagesCrawled / elapsed).toFixed(2);

    console.error(
      `[STATS] Progress: ${this.stats.pagesCrawled}/${this.stats.pagesDiscovered} pages | ` +
      `🚫 ${this.stats.pagesSkipped} skipped | [ERROR] ${this.stats.errorCount} errors | ` +
      `[TIME] ${elapsed.toFixed(1)}s | 📈 ${rate} pages/s`
    );
  }

  /**
   * Log final report
   */
  _logFinalReport() {
    const duration = (this.stats.endTime - this.stats.startTime) / 1000;

    console.error('\n[CRAWL]  WEB CRAWL COMPLETE');
    console.error('════════════════════════════════════');
    console.error(`[TIME]  Total Time: ${duration.toFixed(1)}s`);
    console.error(`[STATS] Pages Discovered: ${this.stats.pagesDiscovered}`);
    console.error(`[OK] Pages Crawled: ${this.stats.pagesCrawled}`);
    console.error(`🚫 Pages Skipped: ${this.stats.pagesSkipped}`);
    console.error(`[ERROR] Errors: ${this.stats.errorCount}`);
    console.error(`📈 Crawl Rate: ${(this.stats.pagesCrawled / duration).toFixed(2)} pages/s`);

    console.error('\n[STATS] BY DEPTH:');
    Object.entries(this.stats.byDepth)
      .sort(([a], [b]) => parseInt(a) - parseInt(b))
      .forEach(([depth, count]) => {
        console.error(`  Depth ${depth}: ${count} pages`);
      });

    console.error('\n🌐 BY DOMAIN:');
    Object.entries(this.stats.byDomain)
      .sort(([, a], [, b]) => b - a)
      .slice(0, 10)
      .forEach(([domain, count]) => {
        console.error(`  ${domain}: ${count} pages`);
      });

    console.error('════════════════════════════════════\n');
  }

  /**
   * Get crawl statistics
   */
  getStats() {
    return {
      ...this.stats,
      queueSize: this.queue.length,
      visitedCount: this.visited.size,
      isRunning: this.isRunning
    };
  }

  /**
   * Get discovered URLs
   */
  getDiscoveredUrls() {
    return Array.from(this.discovered.values());
  }

  /**
   * Get successful results
   */
  getResults() {
    return this.results;
  }

  /**
   * Get errors
   */
  getErrors() {
    return this.errors;
  }
}
