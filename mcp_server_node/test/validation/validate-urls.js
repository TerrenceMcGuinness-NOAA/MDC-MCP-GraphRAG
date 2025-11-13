#!/usr/bin/env node

/**
 * URL Validation Script
 * Check which documentation reference URLs are valid
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function checkUrl(url, timeout = 10000) {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeout);

    const response = await fetch(url, {
      method: 'HEAD',
      signal: controller.signal,
      headers: {
        'User-Agent': 'URL-Validator/1.0'
      }
    });

    clearTimeout(timeoutId);
    return {
      url,
      valid: response.ok,
      status: response.status,
      error: null
    };
  } catch (error) {
    return {
      url,
      valid: false,
      status: null,
      error: error.message
    };
  }
}

async function validateAllUrls() {
  const verbose = process.argv.includes('--verbose') || process.argv.includes('-v');
  
  console.log('🔍 === URL Validation Check ===\n');

  try {
    // Load documentation references from parent directory
const referencesPath = path.join(__dirname, '../documentation-references.json');
const referencesData = fs.readFileSync(referencesPath, 'utf8');
    const refs = JSON.parse(referencesData);

    const urls = [];

    // Extract all URLs with better naming
    function extractUrls(obj, category = '', parentKey = '') {
      Object.entries(obj).forEach(([key, value]) => {
        if (typeof value === 'string' && value.startsWith('http')) {
          const displayName = parentKey ? `${parentKey} - ${key}` : key;
          urls.push({ 
            url: value, 
            category: category || 'root', 
            key,
            displayName: displayName.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())
          });
        } else if (typeof value === 'object' && value !== null) {
          extractUrls(value, category || key, key);
        }
      });
    }

    extractUrls(refs.documentation_references);

    console.log(`Found ${urls.length} URLs to validate...\n`);

    const results = {
      valid: [],
      invalid: [],
      questionable: []
    };

    // Test each URL
    for (let i = 0; i < urls.length; i++) {
      const urlInfo = urls[i];
      
      const result = await checkUrl(urlInfo.url);

      if (result.valid) {
        console.log(`${i + 1}/${urls.length}: ✅ VALID - ${urlInfo.displayName} - ${urlInfo.url}`);
        results.valid.push({ ...urlInfo, ...result });
      } else if (result.error && result.error.includes('abort')) {
        console.log(`${i + 1}/${urls.length}: ⏱️ TIMEOUT - ${urlInfo.displayName} - ${urlInfo.url}`);
        results.questionable.push({ ...urlInfo, ...result, reason: 'timeout' });
      } else {
        console.log(`${i + 1}/${urls.length}: ❌ INVALID (${result.status || result.error}) - ${urlInfo.displayName} - ${urlInfo.url}`);
        results.invalid.push({ ...urlInfo, ...result });
      }

      // Small delay to be nice to servers
      await new Promise(resolve => setTimeout(resolve, 100));
    }

    // Report results summary
    console.log('\n📊 === VALIDATION RESULTS ===');
    console.log(`✅ Valid URLs: ${results.valid.length}`);
    console.log(`❌ Invalid URLs: ${results.invalid.length}`);
    console.log(`⏱️ Timeout/Questionable: ${results.questionable.length}`);

    // Show detailed results only if verbose flag is used
    if (verbose) {
      // Show VALID URLs first with full details
      if (results.valid.length > 0) {
        console.log('\n✅ === VALID URLs (Detailed) ===');
        results.valid.forEach((item, index) => {
          console.log(`${index + 1}. ✅ ${item.displayName}`);
          console.log(`   🔗 ${item.url}`);
          console.log(`   📁 Category: ${item.category}`);
          console.log(`   📊 Status: HTTP ${item.status}`);
          console.log('');
        });
      }

      if (results.invalid.length > 0) {
        console.log('\n❌ === INVALID URLs (Detailed) ===');
        results.invalid.forEach((item, index) => {
          console.log(`${index + 1}. ❌ ${item.displayName}`);
          console.log(`   🔗 ${item.url}`);
          console.log(`   📁 Category: ${item.category}`);
          console.log(`   ⚠️  Error: ${item.error || `HTTP ${item.status}`}`);
          console.log('');
        });
      }

      if (results.questionable.length > 0) {
        console.log('\n⏱️ === QUESTIONABLE URLs (Detailed - manual check needed) ===');
        results.questionable.forEach((item, index) => {
          console.log(`${index + 1}. ⏱️ ${item.displayName}`);
          console.log(`   🔗 ${item.url}`);
          console.log(`   📁 Category: ${item.category}`);
          console.log(`   ⚠️  Reason: ${item.reason}`);
          console.log('');
        });
      }
    } else {
      console.log('\n💡 Use --verbose or -v flag for detailed URL information');
    }

    // Save results
    await fs.writeFile(
      path.join(__dirname, 'url-validation-results.json'),
      JSON.stringify({ results, timestamp: new Date().toISOString() }, null, 2)
    );

    console.log('\n📁 Results saved to url-validation-results.json');

  } catch (error) {
    console.error('❌ Error during validation:', error.message);
  }
}

validateAllUrls().catch(console.error);
