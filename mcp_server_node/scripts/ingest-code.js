#!/usr/bin/env node

/**
 * Code Structure Ingestion CLI
 * 
 * Ingests source code structure into Neo4j graph database:
 * - Python: Functions, classes, imports, call graphs
 * - Shell: Functions, source commands, invocations
 * - Fortran: Subroutines, modules, use statements, call graphs
 * 
 * Usage:
 *   node ingest-code.js --language python [--clear] [--verbose]
 *   node ingest-code.js --language shell --paths scripts,ush [--verbose]
 *   node ingest-code.js --language fortran --paths sorc/gdas.cd,sorc/ufs_model.fd
 * 
 * Options:
 *   --language    Language to parse (python|shell|fortran)
 *   --paths       Comma-separated paths to parse (relative to root)
 *   --root-dir    Repository root directory (default: auto-detect)
 *   --clear       Clear existing code structure data before ingestion
 *   --verbose     Detailed logging
 *   --batch-size  Files to process per batch (default: 50)
 * 
 * Examples:
 *   # Python workflow scripts (default scope)
 *   node ingest-code.js --language python
 * 
 *   # Shell scripts in specific directories
 *   node ingest-code.js --language shell --paths scripts,ush/jobs
 * 
 *   # Fortran core components
 *   node ingest-code.js --language fortran --paths sorc/gdas.cd,sorc/ufs_model.fd
 */

import { Neo4jClient } from '../src/ingestion/neo4j/Neo4jClient.js';
import { CodeStructureIngester } from '../src/ingestion/neo4j/CodeStructureIngester.js';
import path from 'path';
import { fileURLToPath } from 'url';

// Calculate root directory (7 levels up from this script)
// Script location: dev/ci/scripts/utils/Copilot/mcp_server_node/scripts/ingest-code.js
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const DEFAULT_ROOT_DIR = path.resolve(__dirname, '../../../../../../../');


/**
 * Parse command line arguments
 */
function parseArgs() {
  const args = {
    language: null,
    paths: null,
    rootDir: DEFAULT_ROOT_DIR,
    clear: false,
    verbose: false,
    batchSize: 50
  };
  
  for (let i = 2; i < process.argv.length; i++) {
    const arg = process.argv[i];
    
    switch (arg) {
      case '--language':
        args.language = process.argv[++i];
        break;
      case '--paths':
        args.paths = process.argv[++i].split(',').map(p => p.trim());
        break;
      case '--root-dir':
        args.rootDir = process.argv[++i];
        break;
      case '--clear':
        args.clear = true;
        break;
      case '--verbose':
        args.verbose = true;
        break;
      case '--batch-size':
        args.batchSize = parseInt(process.argv[++i]);
        break;
      case '--help':
      case '-h':
        printUsage();
        process.exit(0);
        break;
      default:
        console.error(`Unknown option: ${arg}`);
        printUsage();
        process.exit(1);
    }
  }
  
  // Validate required arguments
  if (!args.language) {
    console.error('Error: --language is required');
    printUsage();
    process.exit(1);
  }
  
  if (!['python', 'shell', 'fortran'].includes(args.language)) {
    console.error(`Error: Invalid language '${args.language}'. Must be python, shell, or fortran.`);
    process.exit(1);
  }
  
  return args;
}

/**
 * Print usage information
 */
function printUsage() {
  console.log(`
Code Structure Ingestion CLI

Usage:
  node ingest-code.js --language <language> [options]

Options:
  --language <lang>      Language to parse (python|shell|fortran) [required]
  --paths <paths>        Comma-separated paths to parse (relative to root)
  --root-dir <dir>       Repository root directory (default: auto-detect)
  --clear                Clear existing code structure data before ingestion
  --verbose              Detailed logging
  --batch-size <num>     Files to process per batch (default: 50)
  --help, -h             Show this help message

Examples:
  # Python workflow scripts (default scope: scripts, ush/python)
  node ingest-code.js --language python --verbose

  # Shell scripts with custom paths
  node ingest-code.js --language shell --paths scripts,ush/jobs

  # Fortran core components (large - may take 30-60 minutes)
  node ingest-code.js --language fortran --paths sorc/gdas.cd,sorc/ufs_model.fd --batch-size 100

  # Clear and re-ingest Python
  node ingest-code.js --language python --clear --verbose
  `);
}

/**
 * Main execution
 */
async function main() {
  const args = parseArgs();
  
  console.log('=== Code Structure Ingestion ===');
  console.log(`Language: ${args.language.toUpperCase()}`);
  console.log(`Root directory: ${args.rootDir}`);
  if (args.paths) {
    console.log(`Target paths: ${args.paths.join(', ')}`);
  }
  console.log(`Batch size: ${args.batchSize}`);
  console.log(`Clear existing data: ${args.clear ? 'YES' : 'NO'}`);
  console.log('');
  
  let client = null;
  
  try {
    // Initialize Neo4j client
    client = new Neo4jClient();
    await client.connect();
    console.log('Connected to Neo4j');
    
    // Create ingester
    const ingester = new CodeStructureIngester(client, args.rootDir);
    
    // Clear existing data if requested
    if (args.clear) {
      await ingester.clearCodeStructureData();
    }
    
    // Run ingestion
    const stats = await ingester.ingestCodeStructure(
      args.language,
      args.paths,
      {
        verbose: args.verbose,
        batchSize: args.batchSize
      }
    );
    
    console.log('\n=== Ingestion Summary ===');
    console.log(`Total files processed: ${stats.filesProcessed}`);
    console.log(`Files failed: ${stats.filesFailed}`);
    console.log(`Functions created: ${stats.functionsCreated}`);
    console.log(`Classes created: ${stats.classesCreated}`);
    console.log(`Import relationships: ${stats.importsCreated}`);
    console.log(`Call relationships: ${stats.callsCreated}`);
    console.log(`Defines relationships: ${stats.definesCreated}`);
    
    process.exit(0);
    
  } catch (error) {
    console.error('\n❌ Ingestion failed:', error.message);
    if (args.verbose) {
      console.error(error.stack);
    }
    process.exit(1);
  } finally {
    if (client) {
      await client.close();
    }
  }
}

// Run if executed directly
if (import.meta.url === `file://${process.argv[1]}`) {
  main();
}
