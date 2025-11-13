#!/usr/bin/env node

/**
 * URL Validation Script for Global Workflow RAG Components
 * Validates all URLs in documentation-references.json and updates status
 */

import fs from 'fs/promises';
import fetch from 'node-fetch';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

class URLValidator {
  constructor() {
    this.configPath = join(__dirname, 'documentation-references.json');
    this.resultsPath = join(__dirname, 'validation', 'url-validation-results.json');
    this.relevancePath = join(__dirname, 'url-relevance-check.json');
    this.timeout = 30000; // 30 second timeout
    this.retries = 3;
    this.results = {
      valid: [],
      invalid: [],
      questionable: []
    };
  }

  async loadConfiguration() {
    try {
      const configData = await fs.readFile(this.configPath, 'utf8');
      this.config = JSON.parse(configData);
      console.log('✓ Loaded configuration file');
    } catch (error) {
      console.error('❌ Failed to load configuration:', error.message);
      throw error;
    }
  }

  async validateUrl(url, category, key, displayName) {
    console.log(`🔍 Validating: ${url}`);
    
    for (let attempt = 1; attempt <= this.retries; attempt++) {
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), this.timeout);

        const response = await fetch(url, {
          method: 'HEAD',
          signal: controller.signal,
          headers: {
            'User-Agent': 'Global-Workflow-MCP-Validator/1.0'
          },
          redirect: 'follow'
        });

        clearTimeout(timeoutId);

        const result = {
          url,
          category,
          key,
          displayName,
          valid: response.ok,
          status: response.status,
          error: response.ok ? null : `HTTP ${response.status}: ${response.statusText}`
        };

        if (response.ok) {
          console.log(`  ✅ Valid (${response.status})`);
          this.results.valid.push(result);
        } else if (response.status >= 400) {
          console.log(`  ❌ Invalid (${response.status})`);
          this.results.invalid.push(result);
        } else {
          console.log(`  ⚠️  Questionable (${response.status})`);
          this.results.questionable.push(result);
        }

        return result;

      } catch (error) {
        if (attempt === this.retries) {
          console.log(`  ❌ Failed after ${this.retries} attempts: ${error.message}`);
          const result = {
            url,
            category,
            key,
            displayName,
            valid: false,
            status: null,
            error: error.message
          };
          this.results.invalid.push(result);
          return result;
        } else {
          console.log(`  ⏳ Attempt ${attempt} failed, retrying...`);
          await new Promise(resolve => setTimeout(resolve, 1000 * attempt));
        }
      }
    }
  }

  extractUrls(obj, category = '', parentKey = '') {
    const urls = [];
    
    for (const [key, value] of Object.entries(obj)) {
      const fullKey = parentKey ? `${parentKey}.${key}` : key;
      
      if (typeof value === 'string' && (value.startsWith('http://') || value.startsWith('https://'))) {
        // Skip excluded URLs
        if (this.config.url_validation?.exclude_from_validation?.includes(fullKey)) {
          console.log(`⏭️  Skipping excluded URL: ${value}`);
          continue;
        }
        
        const displayName = this.generateDisplayName(category, parentKey, key);
        urls.push({ url: value, category: category || 'unknown', key, displayName });
      } else if (typeof value === 'object' && value !== null) {
        urls.push(...this.extractUrls(value, category || key, fullKey));
      }
    }
    
    return urls;
  }

  generateDisplayName(category, parentKey, key) {
    const categoryName = category.charAt(0).toUpperCase() + category.slice(1);
    const keyName = key.split('_').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
    const parentName = parentKey ? parentKey.split('.').pop().split('_').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ') : '';
    
    if (parentName && parentName !== categoryName) {
      return `${parentName} - ${keyName}`;
    }
    return `${categoryName} - ${keyName}`;
  }

  async validateAllUrls() {
    console.log('🚀 Starting URL validation...');
    console.log('=====================================\n');

    const allUrls = [];
    
    // Extract URLs from all categories
    for (const [category, content] of Object.entries(this.config.documentation_references)) {
      if (category === 'reference_metadata' || category === 'url_validation' || category === 'search_priorities') {
        continue; // Skip metadata sections
      }
      const urls = this.extractUrls(content, category);
      allUrls.push(...urls);
    }

    console.log(`📊 Found ${allUrls.length} URLs to validate\n`);

    // Validate each URL
    const validationPromises = allUrls.map(({ url, category, key, displayName }) => 
      this.validateUrl(url, category, key, displayName)
    );

    await Promise.all(validationPromises);

    console.log('\n=====================================');
    console.log('🏁 Validation complete!');
    console.log(`✅ Valid: ${this.results.valid.length}`);
    console.log(`❌ Invalid: ${this.results.invalid.length}`);
    console.log(`⚠️  Questionable: ${this.results.questionable.length}`);
  }

  async saveResults() {
    const results = {
      results: this.results,
      timestamp: new Date().toISOString()
    };

    try {
      // Ensure validation directory exists
      await fs.mkdir(dirname(this.resultsPath), { recursive: true });
      
      await fs.writeFile(this.resultsPath, JSON.stringify(results, null, 2));
      console.log(`💾 Results saved to: ${this.resultsPath}`);
    } catch (error) {
      console.error('❌ Failed to save results:', error.message);
    }
  }

  async updateRelevanceCheck() {
    try {
      // Load existing relevance data if it exists
      let relevanceData = {};
      try {
        const existingData = await fs.readFile(this.relevancePath, 'utf8');
        relevanceData = JSON.parse(existingData);
      } catch (error) {
        console.log('📝 Creating new relevance check file');
      }

      // Update with current valid URLs
      relevanceData.timestamp = Date.now() / 1000;
      relevanceData.total_checked = this.results.valid.length + this.results.invalid.length + this.results.questionable.length;
      
      // Add valid URLs to relevance data if not already present
      if (!relevanceData.relevant) {
        relevanceData.relevant = [];
      }

      this.results.valid.forEach(validUrl => {
        const existing = relevanceData.relevant.find(r => r.url === validUrl.url);
        if (!existing) {
          relevanceData.relevant.push({
            url: validUrl.url,
            label: validUrl.key,
            context: `${validUrl.category}.${validUrl.key}`,
            status: 'accessible',
            title: `${validUrl.displayName}`,
            content_sample: 'Content validation pending',
            word_count: 0,
            relevance_keywords: []
          });
        }
      });

      await fs.writeFile(this.relevancePath, JSON.stringify(relevanceData, null, 2));
      console.log(`🔄 Updated relevance check data`);
    } catch (error) {
      console.error('⚠️  Failed to update relevance data:', error.message);
    }
  }

  printSummary() {
    console.log('\n📋 VALIDATION SUMMARY');
    console.log('=====================\n');

    if (this.results.invalid.length > 0) {
      console.log('❌ INVALID URLs:');
      this.results.invalid.forEach(result => {
        console.log(`   • ${result.url}`);
        console.log(`     Category: ${result.category}`);
        console.log(`     Error: ${result.error}\n`);
      });
    }

    if (this.results.questionable.length > 0) {
      console.log('⚠️  QUESTIONABLE URLs:');
      this.results.questionable.forEach(result => {
        console.log(`   • ${result.url}`);
        console.log(`     Category: ${result.category}`);
        console.log(`     Status: ${result.status}\n`);
      });
    }

    if (this.results.invalid.length === 0 && this.results.questionable.length === 0) {
      console.log('🎉 All URLs are valid and accessible!');
    }
  }
}

// Main execution
async function main() {
  console.log('🌐 Global Workflow URL Validator');
  console.log('=================================\n');

  const validator = new URLValidator();

  try {
    await validator.loadConfiguration();
    await validator.validateAllUrls();
    await validator.saveResults();
    await validator.updateRelevanceCheck();
    validator.printSummary();
    
    // Exit with error code if there are invalid URLs
    const hasErrors = validator.results.invalid.length > 0;
    process.exit(hasErrors ? 1 : 0);
    
  } catch (error) {
    console.error('💥 Fatal error:', error.message);
    process.exit(1);
  }
}

// Allow running as script
if (import.meta.url === `file://${process.argv[1]}`) {
  main();
}

export default URLValidator;