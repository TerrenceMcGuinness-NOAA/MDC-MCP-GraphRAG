#!/usr/bin/env node

/**
 * Documentation Ingestion Runner
 *
 * Complete pipeline runner for ingesting external documentation sources
 * into the Enhanced RAG system. This script orchestrates the entire process:
 *
 * 1. Load documentation-references.json configuration
 * 2. Initialize ingestion pipeline components
 * 3. Fetch and process all external documentation URLs
 * 4. Extract, clean, and chunk content
 * 5. Update the enhanced vector database
 * 6. Generate comprehensive reports
 *
 * Usage:
 *   node run-documentation-ingestion.js [options]
 *
 * Options:
 *   --categories <cat1,cat2>  Only ingest specific categories
 *   --validate               Validate URLs only (don't ingest)
 *   --incremental            Only process new/updated content
 *   --max-concurrent <n>     Maximum concurrent requests (default: 3)
 *   --dry-run                Show what would be processed without doing it
 *   --help                   Show this help message
 *
 * @version 1.0.0
 * @author NOAA EMC Global Workflow Team
 */

import { DocumentationIngester } from './src/ingestion/DocumentationIngester.js';
import { EnhancedVectorStore } from './src/rag/EnhancedVectorStore.js';
import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

class DocumentationIngestionRunner {
  constructor() {
    this.options = this.parseArguments();
    this.ingester = null;
    this.vectorStore = null;
  }

  /**
   * Parse command line arguments
   */
  parseArguments() {
    const args = process.argv.slice(2);
    const options = {
      categories: null,
      validateOnly: false,
      incremental: false,
      maxConcurrent: 3,
      dryRun: false,
      verbose: true,
      outputDir: path.join(__dirname, 'knowledge-base')
    };

    for (let i = 0; i < args.length; i++) {
      const arg = args[i];

      switch (arg) {
        case '--categories':
          options.categories = args[++i]?.split(',').map(c => c.trim()) || null;
          break;
        case '--validate':
          options.validateOnly = true;
          break;
        case '--incremental':
          options.incremental = true;
          break;
        case '--max-concurrent':
          options.maxConcurrent = parseInt(args[++i]) || 3;
          break;
        case '--dry-run':
          options.dryRun = true;
          break;
        case '--output':
          options.outputDir = args[++i] || options.outputDir;
          break;
        case '--quiet':
          options.verbose = false;
          break;
        case '--help':
          this.showHelp();
          process.exit(0);
          break;
        default:
          console.error(`❌ Unknown option: ${arg}`);
          this.showHelp();
          process.exit(1);
      }
    }

    return options;
  }

  /**
   * Show help message
   */
  showHelp() {
    console.log(`
📚 Documentation Ingestion Runner

Complete pipeline for ingesting external documentation sources into the Enhanced RAG system.

Usage:
  node run-documentation-ingestion.js [options]

Options:
  --categories <cat1,cat2>  Only ingest specific categories (comma-separated)
  --validate               Validate URLs only (don't ingest content)
  --incremental            Only process new/updated content
  --max-concurrent <n>     Maximum concurrent requests (default: 3)
  --output <path>          Output directory for knowledge base
  --dry-run                Show what would be processed without doing it
  --quiet                  Minimal output
  --help                   Show this help message

Examples:
  # Full ingestion of all external documentation
  node run-documentation-ingestion.js

  # Validate all URLs without ingesting
  node run-documentation-ingestion.js --validate

  # Ingest only UFS and Rocoto documentation
  node run-documentation-ingestion.js --categories "external.ufs,external.rocoto"

  # Dry run to see what would be processed
  node run-documentation-ingestion.js --dry-run

  # Incremental update with higher concurrency
  node run-documentation-ingestion.js --incremental --max-concurrent 5

Categories available:
  internal                    - Global Workflow documentation
  external.ufs               - UFS Weather Model documentation
  external.rocoto            - Rocoto workflow manager
  external.gsi               - GSI data assimilation
  external.spack_stack       - Spack-Stack build system
  external.hpc_systems       - NOAA HPC documentation
  external.noaa_tools        - NOAA libraries and utilities
  standards_and_policies     - Compliance standards and policies
`);
  }

  /**
   * Initialize the ingestion pipeline
   */
  async initialize() {
    console.error('🚀 Initializing Documentation Ingestion Pipeline...');
    console.error('═══════════════════════════════════════════════════════════\n');

    // Create output directory
    await fs.mkdir(this.options.outputDir, { recursive: true });

    // Initialize documentation ingester
    this.ingester = new DocumentationIngester({
      outputDirectory: this.options.outputDir,
      maxConcurrentFetches: this.options.maxConcurrent,
      enableProgressLogging: this.options.verbose
    });

    await this.ingester.initialize();

    // Initialize enhanced vector store
    this.vectorStore = new EnhancedVectorStore({
      knowledgeBasePath: this.options.outputDir,
      enableExternalSources: true
    });

    console.error('\n✅ Pipeline initialization complete\n');
  }

  /**
   * Run the complete ingestion process
   */
  async run() {
    try {
      await this.initialize();

      if (this.options.validateOnly) {
        await this.runValidation();
      } else if (this.options.dryRun) {
        await this.runDryRun();
      } else {
        await this.runIngestion();
      }

      await this.generateFinalReport();

    } catch (error) {
      console.error(`❌ Ingestion failed: ${error.message}`);
      console.error(error.stack);
      process.exit(1);
    }
  }

  /**
   * Run URL validation only
   */
  async runValidation() {
    console.error('🔍 VALIDATION MODE - Checking URL accessibility\n');

    const results = await this.ingester.validateAllUrls();

    const accessible = results.filter(r => r.accessible);
    const inaccessible = results.filter(r => !r.accessible);

    console.error('\n📊 VALIDATION RESULTS');
    console.error('════════════════════════');
    console.error(`✅ Accessible: ${accessible.length}`);
    console.error(`❌ Inaccessible: ${inaccessible.length}`);
    console.error(`📊 Success Rate: ${((accessible.length / results.length) * 100).toFixed(1)}%`);

    if (inaccessible.length > 0) {
      console.error('\n❌ INACCESSIBLE URLS:');
      inaccessible.slice(0, 20).forEach(result => {
        console.error(`  ${result.url}`);
        console.error(`    Error: ${result.error}`);
      });

      if (inaccessible.length > 20) {
        console.error(`  ... and ${inaccessible.length - 20} more`);
      }
    }

    // Save validation report
    const reportPath = path.join(this.options.outputDir, 'url_validation_report.json');
    await fs.writeFile(reportPath, JSON.stringify({
      timestamp: new Date().toISOString(),
      summary: {
        total: results.length,
        accessible: accessible.length,
        inaccessible: inaccessible.length,
        successRate: (accessible.length / results.length) * 100
      },
      results
    }, null, 2));

    console.error(`\n💾 Validation report saved to: ${reportPath}`);
  }

  /**
   * Run dry run to show what would be processed
   */
  async runDryRun() {
    console.error('🔍 DRY RUN MODE - Showing what would be processed\n');

    const stats = this.ingester.getStats();
    console.error('📊 INGESTION PLAN');
    console.error('═════════════════');
    console.error(`Total URLs: ${stats.totalUrls}`);
    console.error(`Categories: ${Object.keys(stats.categoryStats).length}`);
    console.error(`Max concurrent: ${this.options.maxConcurrent}`);

    if (this.options.categories) {
      console.error(`Filter categories: ${this.options.categories.join(', ')}`);
    }

    console.error('\n📋 CATEGORIES TO PROCESS:');
    Object.entries(stats.categoryStats).forEach(([category, categoryStats]) => {
      if (!this.options.categories || this.options.categories.includes(category)) {
        console.error(`  ${category}: ${categoryStats.count} URLs`);
      }
    });

    console.error('\n🔧 PIPELINE COMPONENTS:');
    console.error('  URLFetcher: Rate limited to 2 req/s with caching');
    console.error('  ContentExtractor: HTML, PDF, Markdown, JSON support');
    console.error('  EnhancedVectorStore: Multi-source with intelligent routing');

    console.error('\n💡 To run actual ingestion, remove --dry-run flag');
  }

  /**
   * Run the full ingestion process
   */
  async runIngestion() {
    console.error('📚 INGESTION MODE - Processing all documentation sources\n');

    let results;

    if (this.options.categories) {
      console.error(`🎯 Processing specific categories: ${this.options.categories.join(', ')}\n`);
      results = await this.ingester.ingestCategories(this.options.categories);
    } else {
      console.error('🌍 Processing all documentation sources\n');
      results = await this.ingester.ingestDocumentation();
    }

    // Update enhanced vector store
    if (results.chunks.length > 0) {
      console.error('\n🔄 Updating Enhanced Vector Store...');

      await this.vectorStore.initialize();
      await this.vectorStore.refreshExternalDocumentation();

      console.error('✅ Enhanced Vector Store updated');
    }

    // Generate usage examples
    if (results.successful.length > 0) {
      await this.generateUsageExamples();
    }

    return results;
  }

  /**
   * Generate usage examples with the new knowledge base
   */
  async generateUsageExamples() {
    console.error('\n🧪 Generating usage examples...');

    try {
      const testQueries = [
        'UFS weather model installation',
        'Rocoto workflow dependencies',
        'GSI data assimilation configuration',
        'NOAA HPC system setup',
        'EE2 compliance standards',
        'Global workflow operational procedures'
      ];

      const examples = [];

      for (const query of testQueries) {
        try {
          const results = await this.vectorStore.searchWithAttribution(query, {
            maxResults: 3,
            includeMetadata: true
          });

          examples.push({
            query,
            resultCount: results.length,
            topSource: results[0]?.attribution?.source_url || 'None',
            topCategory: results[0]?.attribution?.category || 'None',
            confidence: results[0]?.attribution?.confidence || 0
          });

        } catch (error) {
          examples.push({
            query,
            error: error.message
          });
        }
      }

      // Save examples
      const examplesPath = path.join(this.options.outputDir, 'usage_examples.json');
      await fs.writeFile(examplesPath, JSON.stringify({
        generatedAt: new Date().toISOString(),
        examples,
        vectorStoreStats: this.vectorStore.getStats()
      }, null, 2));

      console.error(`✅ Usage examples saved to: ${examplesPath}`);

    } catch (error) {
      console.warn(`⚠️ Could not generate usage examples: ${error.message}`);
    }
  }

  /**
   * Generate final comprehensive report
   */
  async generateFinalReport() {
    console.error('\n📋 GENERATING FINAL REPORT');
    console.error('═════════════════════════════');

    const ingesterStats = this.ingester.getStats();
    const timestamp = new Date().toISOString();

    const report = {
      timestamp,
      configuration: {
        mode: this.options.validateOnly ? 'validation' :
              this.options.dryRun ? 'dry-run' : 'ingestion',
        categories: this.options.categories,
        maxConcurrent: this.options.maxConcurrent,
        outputDirectory: this.options.outputDir
      },
      results: ingesterStats,
      recommendations: []
    };

    // Add recommendations based on results
    if (ingesterStats.failedUrls > 0) {
      const failureRate = (ingesterStats.failedUrls / ingesterStats.totalUrls) * 100;
      report.recommendations.push({
        type: 'error_handling',
        message: `${failureRate.toFixed(1)}% of URLs failed - review error log for broken links`,
        priority: failureRate > 20 ? 'high' : 'medium'
      });
    }

    if (ingesterStats.averageQualityScore < 0.6) {
      report.recommendations.push({
        type: 'quality',
        message: `Average quality score is ${(ingesterStats.averageQualityScore * 100).toFixed(1)}% - consider improving content extraction`,
        priority: 'medium'
      });
    }

    if (ingesterStats.totalChunks > 20000) {
      report.recommendations.push({
        type: 'performance',
        message: `Large knowledge base (${ingesterStats.totalChunks.toLocaleString()} chunks) - consider implementing advanced indexing`,
        priority: 'low'
      });
    }

    // Save final report
    const reportPath = path.join(this.options.outputDir, `final_report_${timestamp.replace(/[:.]/g, '-')}.json`);
    await fs.writeFile(reportPath, JSON.stringify(report, null, 2));

    console.error(`📄 Final report saved to: ${reportPath}`);
    console.error('\n🎉 Documentation ingestion pipeline complete!');

    if (!this.options.validateOnly && !this.options.dryRun) {
      console.error('\n💡 Next steps:');
      console.error('  1. Test the enhanced RAG system with the new knowledge base');
      console.error('  2. Update MCP tools to leverage the expanded knowledge sources');
      console.error('  3. Set up periodic refresh schedule for external documentation');
      console.error('  4. Monitor query performance and optimize as needed');
    }
  }
}

// Run the ingestion pipeline
if (import.meta.url === `file://${process.argv[1]}`) {
  const runner = new DocumentationIngestionRunner();
  runner.run().catch(error => {
    console.error('💥 Fatal error:', error.message);
    process.exit(1);
  });
}

export { DocumentationIngestionRunner };