#!/usr/bin/env node

/**
 * URLFetcher - Robust URL fetching with caching, retry logic, and content validation
 *
 * Handles fetching content from external documentation sources with:
 * - Intelligent retry logic with exponential backoff
 * - Response caching to minimize external requests
 * - Content type detection and validation
 * - Rate limiting and respectful crawling
 * - Comprehensive error handling
 *
 * @version 1.0.0
 * @author NOAA EMC Global Workflow Team
 */

import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export class URLFetcher {
  constructor(options = {}) {
    this.options = {
      // Retry configuration
      maxRetries: options.maxRetries || 3,
      retryDelayMs: options.retryDelayMs || 1000,
      retryBackoffMultiplier: options.retryBackoffMultiplier || 2,

      // Request configuration
      timeoutMs: options.timeoutMs || 30000,
      userAgent: options.userAgent || 'NOAA-Global-Workflow-RAG/1.0 (+https://github.com/NOAA-EMC/global-workflow)',

      // Rate limiting (requests per second)
      rateLimit: options.rateLimit || 2,

      // Caching
      enableCaching: options.enableCaching !== false,
      cacheDirectory: options.cacheDirectory || path.join(__dirname, '../../cache'),
      cacheTtlHours: options.cacheTtlHours || 24,

      // Content validation
      maxContentSizeBytes: options.maxContentSizeBytes || 10 * 1024 * 1024, // 10MB
      allowedContentTypes: options.allowedContentTypes || [
        'text/html',
        'text/markdown',
        'text/plain',
        'application/pdf',
        'application/json',
        'text/xml',
        'application/xml'
      ],

      ...options
    };

    this.requestQueue = [];
    this.isProcessing = false;
    this.requestHistory = new Map(); // URL -> last request timestamp
    this.cache = new Map(); // URL -> cached response

    this.stats = {
      totalRequests: 0,
      cacheHits: 0,
      errors: 0,
      retries: 0,
      totalBytes: 0
    };
  }

  /**
   * Initialize the fetcher (create cache directory, load cached data)
   */
  async initialize() {
    if (this.options.enableCaching) {
      try {
        await fs.mkdir(this.options.cacheDirectory, { recursive: true });
        await this.loadCacheFromDisk();
        console.error('[OK] URLFetcher cache initialized');
      } catch (error) {
        console.error('[WARN] URLFetcher cache initialization failed:', error.message);
      }
    }

    console.error(`[OK] URLFetcher initialized (rate limit: ${this.options.rateLimit} req/s)`);
  }

  /**
   * Fetch content from URL with full retry and caching logic
   */
  async fetch(url, options = {}) {
    return new Promise((resolve, reject) => {
      this.requestQueue.push({
        url,
        options: { ...this.options, ...options },
        resolve,
        reject,
        timestamp: Date.now()
      });

      this.processQueue();
    });
  }

  /**
   * Process the request queue with rate limiting
   */
  async processQueue() {
    if (this.isProcessing || this.requestQueue.length === 0) {
      return;
    }

    this.isProcessing = true;
    const rateDelayMs = 1000 / this.options.rateLimit;

    while (this.requestQueue.length > 0) {
      const request = this.requestQueue.shift();

      try {
        const result = await this._fetchWithRetry(request.url, request.options);
        request.resolve(result);
      } catch (error) {
        request.reject(error);
      }

      // Rate limiting delay
      if (this.requestQueue.length > 0) {
        await this._delay(rateDelayMs);
      }
    }

    this.isProcessing = false;
  }

  /**
   * Internal fetch with retry logic
   */
  async _fetchWithRetry(url, options = {}, attemptNum = 0) {
    this.stats.totalRequests++;

    // Check cache first
    if (this.options.enableCaching) {
      const cached = await this._getCached(url);
      if (cached) {
        this.stats.cacheHits++;
        return cached;
      }
    }

    try {
      const response = await this._performRequest(url, options);

      // Cache successful response
      if (this.options.enableCaching && response.success) {
        await this._setCached(url, response);
      }

      return response;

    } catch (error) {
      const isRetryable = this._isRetryableError(error);
      const shouldRetry = attemptNum < this.options.maxRetries && isRetryable;

      if (shouldRetry) {
        this.stats.retries++;
        const delay = this.options.retryDelayMs * Math.pow(this.options.retryBackoffMultiplier, attemptNum);

        console.error(`[WARN] Retry ${attemptNum + 1}/${this.options.maxRetries} for ${url} after ${delay}ms: ${error.message}`);
        await this._delay(delay);

        return this._fetchWithRetry(url, options, attemptNum + 1);
      }

      this.stats.errors++;
      throw new Error(`Failed to fetch ${url} after ${attemptNum + 1} attempts: ${error.message}`);
    }
  }

  /**
   * Perform the actual HTTP request
   */
  async _performRequest(url, options) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), this.options.timeoutMs);

    try {
      const response = await fetch(url, {
        signal: controller.signal,
        headers: {
          'User-Agent': this.options.userAgent,
          'Accept': 'text/html,application/xhtml+xml,application/xml,text/plain,application/pdf,application/json',
          ...options.headers
        },
        ...options.fetchOptions
      });

      clearTimeout(timeoutId);

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      // Validate content type
      const contentType = response.headers.get('content-type') || '';
      const isAllowedType = this.options.allowedContentTypes.some(type =>
        contentType.toLowerCase().includes(type.toLowerCase())
      );

      if (!isAllowedType) {
        throw new Error(`Unsupported content type: ${contentType}`);
      }

      // Check content size
      const contentLength = parseInt(response.headers.get('content-length') || '0');
      if (contentLength > this.options.maxContentSizeBytes) {
        throw new Error(`Content too large: ${contentLength} bytes`);
      }

      // Get content based on type
      let content;
      let extractedText;

      if (contentType.includes('application/pdf')) {
        const arrayBuffer = await response.arrayBuffer();
        content = Buffer.from(arrayBuffer);
        extractedText = ''; // PDF parsing will happen in ContentExtractor
      } else if (contentType.includes('application/json')) {
        const jsonData = await response.json();
        content = JSON.stringify(jsonData, null, 2);
        extractedText = content;
      } else {
        content = await response.text();
        extractedText = content;
      }

      this.stats.totalBytes += content.length || content.byteLength || 0;

      return {
        success: true,
        url,
        content,
        extractedText,
        metadata: {
          contentType,
          contentLength: content.length || content.byteLength || 0,
          lastModified: response.headers.get('last-modified'),
          etag: response.headers.get('etag'),
          fetchedAt: new Date().toISOString(),
          responseHeaders: Object.fromEntries(response.headers.entries())
        }
      };

    } catch (error) {
      clearTimeout(timeoutId);

      if (error.name === 'AbortError') {
        throw new Error(`Request timeout after ${this.options.timeoutMs}ms`);
      }

      throw error;
    }
  }

  /**
   * Check if error is retryable
   */
  _isRetryableError(error) {
    const retryablePatterns = [
      /timeout/i,
      /network/i,
      /connection/i,
      /ECONNRESET/i,
      /ENOTFOUND/i,
      /HTTP 5\d\d/i,
      /HTTP 429/i, // Rate limited
      /HTTP 503/i  // Service unavailable
    ];

    return retryablePatterns.some(pattern => pattern.test(error.message));
  }

  /**
   * Get cached response if valid
   */
  async _getCached(url) {
    try {
      const cacheKey = this._getCacheKey(url);
      const cacheFilePath = path.join(this.options.cacheDirectory, `${cacheKey}.json`);

      const stat = await fs.stat(cacheFilePath);
      const age = (Date.now() - stat.mtime.getTime()) / (1000 * 60 * 60); // hours

      if (age > this.options.cacheTtlHours) {
        return null; // Cache expired
      }

      const cached = await fs.readFile(cacheFilePath, 'utf-8');
      return JSON.parse(cached);

    } catch (error) {
      return null; // No cache or error reading cache
    }
  }

  /**
   * Save response to cache
   */
  async _setCached(url, response) {
    try {
      const cacheKey = this._getCacheKey(url);
      const cacheFilePath = path.join(this.options.cacheDirectory, `${cacheKey}.json`);

      // Don't cache binary content like PDFs in JSON
      const cacheData = {
        ...response,
        content: response.metadata.contentType.includes('pdf') ? '[PDF_CONTENT]' : response.content
      };

      await fs.writeFile(cacheFilePath, JSON.stringify(cacheData, null, 2));
    } catch (error) {
      console.error(`Cache write failed for ${url}:`, error.message);
    }
  }

  /**
   * Generate cache key from URL
   */
  _getCacheKey(url) {
    return Buffer.from(url).toString('base64').replace(/[/+=]/g, '_');
  }

  /**
   * Load existing cache from disk
   */
  async loadCacheFromDisk() {
    try {
      const files = await fs.readdir(this.options.cacheDirectory);
      const cacheFiles = files.filter(file => file.endsWith('.json'));

      console.error(`📁 Found ${cacheFiles.length} cached responses`);
    } catch (error) {
      // Cache directory doesn't exist or is empty
    }
  }

  /**
   * Utility delay function
   */
  _delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  /**
   * Get fetcher statistics
   */
  getStats() {
    const cacheHitRate = this.stats.totalRequests > 0
      ? (this.stats.cacheHits / this.stats.totalRequests * 100).toFixed(1)
      : '0.0';

    return {
      ...this.stats,
      cacheHitRate: `${cacheHitRate}%`,
      avgBytesPerRequest: this.stats.totalRequests > 0
        ? Math.round(this.stats.totalBytes / this.stats.totalRequests)
        : 0
    };
  }

  /**
   * Clear cache
   */
  async clearCache() {
    if (!this.options.enableCaching) return;

    try {
      const files = await fs.readdir(this.options.cacheDirectory);
      const cacheFiles = files.filter(file => file.endsWith('.json'));

      for (const file of cacheFiles) {
        await fs.unlink(path.join(this.options.cacheDirectory, file));
      }

      console.error(`[CLEAN] Cleared ${cacheFiles.length} cached responses`);
    } catch (error) {
      console.error('Cache clear failed:', error.message);
    }
  }

  /**
   * Validate URL accessibility (lightweight check)
   */
  async validateUrl(url) {
    try {
      const response = await fetch(url, {
        method: 'HEAD',
        headers: { 'User-Agent': this.options.userAgent },
        timeout: 5000
      });

      return {
        url,
        accessible: response.ok,
        status: response.status,
        contentType: response.headers.get('content-type'),
        lastModified: response.headers.get('last-modified')
      };
    } catch (error) {
      return {
        url,
        accessible: false,
        error: error.message
      };
    }
  }

  /**
   * Batch validate multiple URLs
   */
  async validateUrls(urls) {
    const results = [];
    const concurrency = 5; // Validate 5 URLs at once

    for (let i = 0; i < urls.length; i += concurrency) {
      const batch = urls.slice(i, i + concurrency);
      const batchResults = await Promise.all(
        batch.map(url => this.validateUrl(url))
      );
      results.push(...batchResults);

      // Small delay between batches to be respectful
      if (i + concurrency < urls.length) {
        await this._delay(1000);
      }
    }

    return results;
  }
}