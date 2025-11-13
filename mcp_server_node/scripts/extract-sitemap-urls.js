#!/usr/bin/env node
/**
 * Extract URLs from sitemaps for targeted documentation ingestion
 * 
 * Usage:
 *   node scripts/extract-sitemap-urls.js <base-url> [--output file.txt] [--format json|txt]
 * 
 * Examples:
 *   node scripts/extract-sitemap-urls.js https://spack.readthedocs.io/en/latest/
 *   node scripts/extract-sitemap-urls.js https://ufs-weather-model.readthedocs.io/ --output ufs-urls.txt
 */

import { SitemapParser } from '../src/ingestion/SitemapParser.js';
import { RobotsTxtParser } from '../src/ingestion/RobotsTxtParser.js';
import fs from 'fs/promises';
import path from 'path';

/**
 * Parse command line arguments
 */
function parseArgs() {
  const args = process.argv.slice(2);
  
  if (args.length === 0 || args[0] === '--help' || args[0] === '-h') {
    console.log(`
URL Extraction from Sitemaps

Usage:
  node scripts/extract-sitemap-urls.js <base-url> [options]

Options:
  --output, -o <file>     Output file path (default: stdout)
  --format <json|txt>     Output format (default: txt)
  --filter <pattern>      Filter URLs by regex pattern
  --exclude <pattern>     Exclude URLs matching regex pattern
  --limit <n>             Limit number of URLs
  --show-metadata         Include sitemap metadata (priority, lastmod)
  --check-robots          Check robots.txt first

Examples:
  # Extract Spack URLs to stdout
  node scripts/extract-sitemap-urls.js https://spack.readthedocs.io/en/latest/

  # Save UFS URLs to file
  node scripts/extract-sitemap-urls.js https://ufs-weather-model.readthedocs.io/ -o ufs-urls.txt

  # Extract with metadata as JSON
  node scripts/extract-sitemap-urls.js https://example.com/ -o urls.json --format json --show-metadata

  # Filter for specific content
  node scripts/extract-sitemap-urls.js https://example.com/ --filter "guide|tutorial|howto"

  # Exclude certain sections
  node scripts/extract-sitemap-urls.js https://example.com/ --exclude "api/internal|changelog"
`);
    process.exit(0);
  }

  const config = {
    baseUrl: args[0],
    output: null,
    format: 'txt',
    filter: null,
    exclude: null,
    limit: null,
    showMetadata: false,
    checkRobots: false
  };

  for (let i = 1; i < args.length; i++) {
    if ((args[i] === '--output' || args[i] === '-o') && args[i + 1]) {
      config.output = args[i + 1];
      i++;
    } else if (args[i] === '--format' && args[i + 1]) {
      config.format = args[i + 1];
      i++;
    } else if (args[i] === '--filter' && args[i + 1]) {
      config.filter = new RegExp(args[i + 1], 'i');
      i++;
    } else if (args[i] === '--exclude' && args[i + 1]) {
      config.exclude = new RegExp(args[i + 1], 'i');
      i++;
    } else if (args[i] === '--limit' && args[i + 1]) {
      config.limit = parseInt(args[i + 1]);
      i++;
    } else if (args[i] === '--show-metadata') {
      config.showMetadata = true;
    } else if (args[i] === '--check-robots') {
      config.checkRobots = true;
    }
  }

  return config;
}

/**
 * Check robots.txt for sitemap URLs
 */
async function checkRobotsTxt(baseUrl) {
  console.error('🤖 Checking robots.txt for sitemap URLs...');
  
  try {
    const robots = await RobotsTxtParser.fetchAndParse(baseUrl);
    const sitemaps = robots.getSitemaps();
    
    if (sitemaps.length > 0) {
      console.error(`✅ Found ${sitemaps.length} sitemap(s) in robots.txt:`);
      sitemaps.forEach(url => console.error(`   ${url}`));
      return sitemaps;
    } else {
      console.error('⚠️  No sitemaps found in robots.txt, will try default locations');
      return [];
    }
  } catch (error) {
    console.error(`⚠️  Could not fetch robots.txt: ${error.message}`);
    return [];
  }
}

/**
 * Extract URLs from sitemaps
 */
async function extractUrls(config) {
  console.error(`🗺️  Extracting URLs from sitemaps for: ${config.baseUrl}\n`);

  const startTime = Date.now();

  // Check robots.txt if requested
  let sitemapUrls = [];
  if (config.checkRobots) {
    sitemapUrls = await checkRobotsTxt(config.baseUrl);
  }

  // Discover and parse sitemaps
  console.error('📄 Discovering sitemaps...');
  const parser = await SitemapParser.discoverAndParse(config.baseUrl, {
    sitemapUrls: sitemapUrls.length > 0 ? sitemapUrls : undefined
  });

  // Get URLs - parser.urls contains full metadata
  const urls = config.showMetadata ? parser.urls : parser.getUrls();
  console.error(`✅ Found ${urls.length} URLs in sitemap(s)\n`);

  let filteredUrls = urls;

  // Apply filter
  if (config.filter) {
    filteredUrls = filteredUrls.filter(item => {
      const url = typeof item === 'string' ? item : item.url;
      return config.filter.test(url);
    });
    console.error(`🔍 After filter: ${filteredUrls.length} URLs`);
  }

  // Apply exclude
  if (config.exclude) {
    filteredUrls = filteredUrls.filter(item => {
      const url = typeof item === 'string' ? item : item.url;
      return !config.exclude.test(url);
    });
    console.error(`🚫 After exclude: ${filteredUrls.length} URLs`);
  }

  // Apply limit
  if (config.limit && filteredUrls.length > config.limit) {
    filteredUrls = filteredUrls.slice(0, config.limit);
    console.error(`📊 Limited to: ${config.limit} URLs`);
  }

  const duration = ((Date.now() - startTime) / 1000).toFixed(2);
  console.error(`⏱️  Extraction time: ${duration}s\n`);

  return filteredUrls;
}

/**
 * Format URLs for output
 */
function formatUrls(urls, format, showMetadata) {
  if (format === 'json') {
    return JSON.stringify(urls, null, 2);
  } else if (format === 'txt') {
    if (showMetadata && typeof urls[0] === 'object') {
      // Format with metadata as comments
      return urls.map(item => {
        const lines = [item.url];
        if (item.priority) lines.push(`# priority: ${item.priority}`);
        if (item.lastmod) lines.push(`# lastmod: ${item.lastmod}`);
        if (item.changefreq) lines.push(`# changefreq: ${item.changefreq}`);
        return lines.join('\n');
      }).join('\n\n');
    } else {
      // Simple list
      return urls.map(item => typeof item === 'string' ? item : item.url).join('\n');
    }
  }
}

/**
 * Main function
 */
async function main() {
  try {
    const config = parseArgs();

    // Extract URLs
    const urls = await extractUrls(config);

    if (urls.length === 0) {
      console.error('❌ No URLs found!');
      return 1;
    }

    // Format output
    const output = formatUrls(urls, config.format, config.showMetadata);

    // Write or print
    if (config.output) {
      const outputPath = path.resolve(config.output);
      await fs.mkdir(path.dirname(outputPath), { recursive: true });
      await fs.writeFile(outputPath, output + '\n');
      console.error(`💾 Saved ${urls.length} URLs to: ${outputPath}`);
    } else {
      console.log(output);
    }

    // Summary
    console.error('\n' + '='.repeat(60));
    console.error('📊 EXTRACTION SUMMARY');
    console.error('='.repeat(60));
    console.error(`Total URLs: ${urls.length}`);
    console.error(`Output Format: ${config.format}`);
    if (config.output) {
      console.error(`Output File: ${config.output}`);
    }
    console.error('='.repeat(60) + '\n');

    return 0;

  } catch (error) {
    console.error('❌ Error:', error.message);
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
