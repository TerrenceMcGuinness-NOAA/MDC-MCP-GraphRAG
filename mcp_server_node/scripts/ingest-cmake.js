#!/usr/bin/env node

/**
 * @file ingest-cmake.js
 * @description CLI tool to ingest CMake build system metadata into Neo4j graph database
 * 
 * USAGE:
 *   node scripts/ingest-cmake.js [options]
 * 
 * OPTIONS:
 *   --clear              Clear existing CMake data before ingestion
 *   --verbose            Enable verbose logging
 *   --root-dir <path>    Root directory of global-workflow (default: auto-detect)
 *   --help               Show this help message
 * 
 * EXAMPLES:
 *   # Standard ingestion with verbose output
 *   node scripts/ingest-cmake.js --verbose
 * 
 *   # Clear existing data and re-ingest
 *   node scripts/ingest-cmake.js --clear --verbose
 * 
 *   # Specify custom root directory
 *   node scripts/ingest-cmake.js --root-dir /path/to/global-workflow
 * 
 * PREREQUISITES:
 *   - Neo4j database running (localhost:7687)
 *   - Phase 0 submodule ingestion completed (Component nodes must exist)
 *   - Neo4j credentials configured in environment or .env file
 * 
 * ARCHITECTURE NOTES:
 *   This tool ingests TWO types of build system metadata:
 * 
 *   1. Build Orchestration (sorc/build_all.sh)
 *      - System build mappings (gfs -> components)
 *      - Build scripts and execution order
 *      - Parallel job configuration
 * 
 *   2. CMake Dependencies (individual CMakeLists.txt)
 *      - Library targets (add_library)
 *      - Executable targets (add_executable)
 *      - Link dependencies (target_link_libraries)
 * 
 * @author Claude Code CLI + GitHub Copilot
 * @version 1.0.0
 * @since 2025-01-15
 */

import { fileURLToPath } from 'url';
import path from 'path';
import { Neo4jClient } from '../dev/ci/scripts/utils/Copilot/mcp_server_node/src/ingestion/neo4j/Neo4jClient.js';
import { CMakeGraphIngester } from '../dev/ci/scripts/utils/Copilot/mcp_server_node/src/ingestion/neo4j/CMakeGraphIngester.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

/**
 * Parse command line arguments
 */
function parseArgs() {
  const args = {
    clear: false,
    verbose: false,
    rootDir: path.resolve(__dirname, '..'),
    help: false
  };
  
  for (let i = 2; i < process.argv.length; i++) {
    const arg = process.argv[i];
    
    switch (arg) {
      case '--clear':
        args.clear = true;
        break;
      case '--verbose':
        args.verbose = true;
        break;
      case '--root-dir':
        args.rootDir = process.argv[++i];
        break;
      case '--help':
      case '-h':
        args.help = true;
        break;
      default:
        console.error(`Unknown argument: ${arg}`);
        args.help = true;
    }
  }
  
  return args;
}

/**
 * Show help message
 */
function showHelp() {
  console.log(`
CMake Graph Ingestion Tool
===========================

Ingests CMake build system metadata into Neo4j graph database.

USAGE:
  node scripts/ingest-cmake.js [options]

OPTIONS:
  --clear              Clear existing CMake data before ingestion
  --verbose            Enable verbose logging
  --root-dir <path>    Root directory of global-workflow (default: auto-detect)
  --help               Show this help message

EXAMPLES:
  # Standard ingestion with verbose output
  node scripts/ingest-cmake.js --verbose

  # Clear existing data and re-ingest
  node scripts/ingest-cmake.js --clear --verbose

  # Specify custom root directory
  node scripts/ingest-cmake.js --root-dir /path/to/global-workflow

GRAPH STRUCTURE:
  - BuildOrchestrator (sorc/build_all.sh metadata)
    └─ BUILD_ORCHESTRATES → Component (from system_builds mapping)
  
  - Library/Executable (CMake targets)
    ├─ DEPENDS_ON → Other Library/Executable (from target_link_libraries)
    └─ BUILT_BY → Component (links target to owning component)

PREREQUISITES:
  - Neo4j database running on localhost:7687
  - Phase 0 submodule ingestion completed (Component nodes must exist)
  - Environment variables: NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD
  `);
}

/**
 * Clear existing CMake data from Neo4j
 */
async function clearCMakeData(neo4jClient, verbose) {
  if (verbose) {
    console.log('Clearing existing CMake data...');
  }
  
  const queries = [
    // Delete BUILD_ORCHESTRATES relationships
    'MATCH ()-[r:BUILD_ORCHESTRATES]->() DELETE r',
    
    // Delete DEPENDS_ON relationships (CMake-specific)
    'MATCH ()-[r:DEPENDS_ON {linkType: "cmake_target_link"}]->() DELETE r',
    
    // Delete BUILT_BY relationships
    'MATCH ()-[r:BUILT_BY]->() DELETE r',
    
    // Delete BuildOrchestrator nodes
    'MATCH (bo:BuildOrchestrator) DETACH DELETE bo',
    
    // Delete Library nodes
    'MATCH (l:Library) DETACH DELETE l',
    
    // Delete Executable nodes
    'MATCH (e:Executable) DETACH DELETE e'
  ];
  
  for (const query of queries) {
    try {
      const result = await neo4jClient.runQuery(query);
      if (verbose) {
        console.log(`Executed: ${query}`);
      }
    } catch (error) {
      console.error(`Error executing query: ${error.message}`);
    }
  }
  
  if (verbose) {
    console.log('CMake data cleared successfully');
  }
}

/**
 * Validate prerequisites before ingestion
 */
async function validatePrerequisites(neo4jClient, verbose) {
  if (verbose) {
    console.log('Validating prerequisites...');
  }
  
  // Check if Component nodes exist (from Phase 0 submodule ingestion)
  const query = 'MATCH (c:Component) RETURN count(c) as componentCount';
  const result = await neo4jClient.runQuery(query);
  const componentCount = result.records[0]?.get('componentCount')?.toNumber() || 0;
  
  if (componentCount === 0) {
    throw new Error(
      'No Component nodes found in Neo4j. ' +
      'Please run Phase 0 submodule ingestion first: node scripts/ingest-submodules.js'
    );
  }
  
  if (verbose) {
    console.log(`✓ Found ${componentCount} Component nodes`);
  }
  
  return { componentCount };
}

/**
 * Main execution function
 */
async function main() {
  const args = parseArgs();
  
  if (args.help) {
    showHelp();
    process.exit(0);
  }
  
  console.log('CMake Graph Ingestion Tool');
  console.log('==========================\n');
  
  let neo4jClient;
  
  try {
    // Initialize Neo4j client
    console.log('Connecting to Neo4j...');
    neo4jClient = new Neo4jClient({
      uri: process.env.NEO4J_URI || 'bolt://localhost:7687',
      username: process.env.NEO4J_USERNAME || 'neo4j',
      password: process.env.NEO4J_PASSWORD || 'gfsworkflow2025'
    });
    
    await neo4jClient.connect();
    console.log('✓ Connected to Neo4j\n');
    
    // Validate prerequisites
    const prereqs = await validatePrerequisites(neo4jClient, args.verbose);
    console.log(`✓ Prerequisites validated (${prereqs.componentCount} components found)\n`);
    
    // Clear existing data if requested
    if (args.clear) {
      await clearCMakeData(neo4jClient, args.verbose);
      console.log('✓ Existing CMake data cleared\n');
    }
    
    // Create CMake ingester
    const ingester = new CMakeGraphIngester(neo4jClient, {
      rootDir: args.rootDir,
      verbose: args.verbose
    });
    
    // Run ingestion
    console.log('Starting CMake ingestion...\n');
    const stats = await ingester.ingest();
    
    // Print summary
    console.log('\n=== Ingestion Summary ===');
    console.log(`Root directory: ${args.rootDir}`);
    console.log(`BuildOrchestrator nodes: ${stats.buildOrchestratorNodes}`);
    console.log(`Library nodes: ${stats.libraryNodes}`);
    console.log(`Executable nodes: ${stats.executableNodes}`);
    console.log(`CMakeLists.txt files: ${stats.cmakeFiles}`);
    console.log(`BUILD_ORCHESTRATES relationships: ${stats.buildOrchestrationRelationships}`);
    console.log(`DEPENDS_ON relationships: ${stats.dependencyRelationships}`);
    console.log(`BUILT_BY relationships: ${stats.builtByRelationships}`);
    console.log(`Processing time: ${stats.processingTime}s`);
    
    if (stats.errors.length > 0) {
      console.log(`\n⚠ Errors: ${stats.errors.length}`);
      stats.errors.slice(0, 5).forEach((err, i) => {
        console.log(`  ${i + 1}. ${err}`);
      });
      if (stats.errors.length > 5) {
        console.log(`  ... and ${stats.errors.length - 5} more`);
      }
    }
    
    console.log('\n✓ CMake ingestion completed successfully!');
    console.log('\nNext Steps:');
    console.log('1. Verify data: Open Neo4j Browser at http://localhost:7474');
    console.log('2. Run test queries: node scripts/test-cmake-queries.js');
    console.log('3. Continue to Phase 1: Code structure ingestion');
    
  } catch (error) {
    console.error('\n❌ Fatal error:', error.message);
    if (args.verbose) {
      console.error(error.stack);
    }
    process.exit(1);
    
  } finally {
    // Clean up
    if (neo4jClient) {
      await neo4jClient.disconnect();
      console.log('\n✓ Disconnected from Neo4j');
    }
  }
}

// Run main function
main().catch(error => {
  console.error('Unhandled error:', error);
  process.exit(1);
});
