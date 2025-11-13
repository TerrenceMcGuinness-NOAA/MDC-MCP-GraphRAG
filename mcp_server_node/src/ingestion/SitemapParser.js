#!/usr/bin/env node

/**
 * SitemapParser - Parse XML sitemaps and sitemap indexes
 *
 * Extracts all URLs from XML sitemaps for comprehensive site coverage:
 * - Standard sitemap.xml parsing
 * - Sitemap index parsing (recursive)
 * - Priority and lastmod metadata extraction
 * - URL filtering and validation
 * - Support for compressed sitemaps (.xml.gz)
 *
 * @version 1.0.0
 * @author NOAA EMC Global Workflow Team
 */

import * as cheerio from 'cheerio';
import { gunzip } from 'zlib';
import { promisify } from 'util';

const gunzipAsync = promisify(gunzip);

export class SitemapParser {
  constructor(options = {}) {
    this.options = {
      maxUrls: options.maxUrls || 50000,
      followSitemapIndexes: options.followSitemapIndexes !== false,
      maxDepth: options.maxDepth || 3,
      userAgent: options.userAgent || 'NOAA-Global-Workflow-RAG/1.0',
      timeout: options.timeout || 10000,
      ...options
    };

    this.urls = [];
    this.processedSitemaps = new Set();
  }

  /**
   * Parse sitemap from URL
   */
  async parseFromUrl(sitemapUrl, depth = 0) {
    if (depth > this.options.maxDepth) {
      console.warn(`[WARN] Max sitemap depth ${this.options.maxDepth} reached`);
      return this.urls;
    }

    if (this.processedSitemaps.has(sitemapUrl)) {
      return this.urls; // Already processed
    }

    this.processedSitemaps.add(sitemapUrl);

    try {
      const response = await fetch(sitemapUrl, {
        headers: {
          'User-Agent': this.options.userAgent
        },
        signal: AbortSignal.timeout(this.options.timeout)
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const contentType = response.headers.get('content-type') || '';
      let content;

      if (contentType.includes('gzip') || sitemapUrl.endsWith('.gz')) {
        // Compressed sitemap
        const arrayBuffer = await response.arrayBuffer();
        const buffer = Buffer.from(arrayBuffer);
        const decompressed = await gunzipAsync(buffer);
        content = decompressed.toString('utf-8');
      } else {
        content = await response.text();
      }

      return await this.parseContent(content, sitemapUrl, depth);

    } catch (error) {
      console.error(`[ERROR] Failed to parse sitemap ${sitemapUrl}: ${error.message}`);
      return this.urls;
    }
  }

  /**
   * Parse sitemap content (XML string)
   */
  async parseContent(xml, baseUrl = '', depth = 0) {
    const $ = cheerio.load(xml, { xmlMode: true });

    // Check if this is a sitemap index
    const sitemapElements = $('sitemapindex > sitemap');
    if (sitemapElements.length > 0) {
      return await this._parseSitemapIndex($, sitemapElements, depth);
    }

    // Parse regular sitemap
    return this._parseUrlSet($);
  }

  /**
   * Parse sitemap index (contains links to other sitemaps)
   */
  async _parseSitemapIndex($, sitemapElements, depth) {
    if (!this.options.followSitemapIndexes) {
      console.warn('[WARN] Sitemap index found but followSitemapIndexes is disabled');
      return this.urls;
    }

    const sitemapUrls = [];
    sitemapElements.each((i, elem) => {
      const loc = $(elem).find('loc').text().trim();
      if (loc) {
        sitemapUrls.push(loc);
      }
    });

    console.error(`[INFO] Found sitemap index with ${sitemapUrls.length} sitemaps`);

    // Process each sitemap recursively
    for (const sitemapUrl of sitemapUrls) {
      await this.parseFromUrl(sitemapUrl, depth + 1);

      if (this.urls.length >= this.options.maxUrls) {
        console.warn(`[WARN] Reached max URLs limit (${this.options.maxUrls})`);
        break;
      }
    }

    return this.urls;
  }

  /**
   * Parse URL set (regular sitemap)
   */
  _parseUrlSet($) {
    const urlElements = $('urlset > url');

    urlElements.each((i, elem) => {
      const $elem = $(elem);
      const loc = $elem.find('loc').text().trim();

      if (!loc) return;

      // Extract metadata
      const urlData = {
        url: loc,
        lastmod: $elem.find('lastmod').text().trim() || null,
        changefreq: $elem.find('changefreq').text().trim() || null,
        priority: parseFloat($elem.find('priority').text().trim()) || 0.5
      };

      this.urls.push(urlData);

      if (this.urls.length >= this.options.maxUrls) {
        return false; // Stop iteration
      }
    });

    console.error(`📄 Extracted ${urlElements.length} URLs from sitemap`);
    return this.urls;
  }

  /**
   * Get all discovered URLs
   */
  getUrls() {
    return this.urls;
  }

  /**
   * Get URLs sorted by priority (descending)
   */
  getUrlsByPriority() {
    return [...this.urls].sort((a, b) => (b.priority || 0) - (a.priority || 0));
  }

  /**
   * Filter URLs by pattern
   */
  filterUrls(pattern) {
    const regex = pattern instanceof RegExp ? pattern : new RegExp(pattern);
    return this.urls.filter(urlData => regex.test(urlData.url));
  }

  /**
   * Get summary statistics
   */
  getSummary() {
    return {
      totalUrls: this.urls.length,
      processedSitemaps: this.processedSitemaps.size,
      priorityDistribution: this._getPriorityDistribution(),
      changefreqDistribution: this._getChangefreqDistribution()
    };
  }

  /**
   * Get priority distribution
   */
  _getPriorityDistribution() {
    const distribution = {};
    this.urls.forEach(urlData => {
      const priority = urlData.priority || 0.5;
      const bucket = Math.floor(priority * 10) / 10;
      distribution[bucket] = (distribution[bucket] || 0) + 1;
    });
    return distribution;
  }

  /**
   * Get changefreq distribution
   */
  _getChangefreqDistribution() {
    const distribution = {};
    this.urls.forEach(urlData => {
      const freq = urlData.changefreq || 'unknown';
      distribution[freq] = (distribution[freq] || 0) + 1;
    });
    return distribution;
  }

  /**
   * Static method to discover and parse sitemaps from domain
   */
  static async discoverAndParse(baseUrl, options = {}) {
    const parser = new SitemapParser(options);

    try {
      const urlObj = new URL(baseUrl);
      const sitemapUrls = [
        `${urlObj.protocol}//${urlObj.host}/sitemap.xml`,
        `${urlObj.protocol}//${urlObj.host}/sitemap_index.xml`,
        `${urlObj.protocol}//${urlObj.host}/sitemap-index.xml`
      ];

      // Try common sitemap locations
      for (const sitemapUrl of sitemapUrls) {
        try {
          await parser.parseFromUrl(sitemapUrl);
          if (parser.urls.length > 0) {
            console.error(`[OK] Found sitemap at ${sitemapUrl}`);
            break;
          }
        } catch (error) {
          // Try next location
          continue;
        }
      }

      if (parser.urls.length === 0) {
        console.warn(`[WARN] No sitemaps found for ${baseUrl}`);
      }

      return parser;

    } catch (error) {
      console.error(`[ERROR] Sitemap discovery failed for ${baseUrl}: ${error.message}`);
      return parser;
    }
  }
}
