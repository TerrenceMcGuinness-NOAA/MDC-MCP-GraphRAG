#!/usr/bin/env node

/**
 * Ingest Submodules CLI - Phase 0 POC
 *
 * Ingests global-workflow submodule structure into Neo4j graph database
 *
 * Usage:
 *   node scripts/ingest-submodules.js [options]
 *
 * Options:
 *   --root-path <path>   Repository root path (default: $GIT_REPO or auto-detect)
 *   --clear              Clear existing graph data before ingestion
 *   --no-language        Skip language detection (faster)
 *   --no-loc             Skip LOC counting (faster)
 *   --verbose            Verbose output
 *   --help               Show this help
 *
 * Examples:
 *   node scripts/ingest-submodules.js
 *   node scripts/ingest-submodules.js --clear --verbose
 *   node scripts/ingest-submodules.js --root-path /path/to/repo
 *
 * @version 1.0.0
 */

import { Neo4jClient } from '../src/ingestion/neo4j/Neo4jClient.js';
import { applySchema, validateSchema } from '../src/ingestion/neo4j/GraphSchema.js';
import { SubmoduleGraphIngester } from '../src/ingestion/neo4j/SubmoduleGraphIngester.js';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Parse command line arguments
function parseArgs() {
  const args = {
    rootPath: process.env.GIT_REPO || '/mcp_rag_eib/global-workflow_MCP_node.js-RAG',
    clear: false,
    extractLanguageInfo: true,
    extractLOC: true,
    verbose: false,
    help: false
  };

  for (let i = 2; i < process.argv.length; i++) {
    const arg = process.argv[i];

    if (arg === '--help' || arg === '-h') {
      args.help = true;
    } else if (arg === '--clear') {
      args.clear = true;
    } else if (arg === '--verbose' || arg === '-v') {
      args.verbose = true;
    } else if (arg === '--no-language') {
      args.extractLanguageInfo = false;
    } else if (arg === '--no-loc') {
      args.extractLOC = false;
    } else if (arg === '--root-path') {
      args.rootPath = process.argv[++i];
    }
  }

  return args;
}

// Show help
function showHelp() {
  console.log(`
╔════════════════════════════════════════════════════════════════════════════╗
║          Submodule Graph Ingestion - Phase 0 POC                          ║
╚════════════════════════════════════════════════════════════════════════════╝

Ingests global-workflow submodule structure into Neo4j graph database.

USAGE:
  node scripts/ingest-submodules.js [options]

OPTIONS:
  --root-path <path>   Repository root path
                       Default: $GIT_REPO or /mcp_rag_eib/global-workflow_MCP_node.js-RAG

  --clear              Clear existing graph data before ingestion
                       WARNING: This deletes ALL data in Neo4j!

  --no-language        Skip language detection (faster ingestion)
  --no-loc             Skip LOC counting (faster ingestion)

  --verbose, -v        Show detailed progress information
  --help, -h           Show this help message

EXAMPLES:
  # Basic ingestion
  node scripts/ingest-submodules.js

  # Clear database and re-ingest with verbose output
  node scripts/ingest-submodules.js --clear --verbose

  # Fast ingestion (skip language detection and LOC counting)
  node scripts/ingest-submodules.js --no-language --no-loc

  # Ingest from custom repository path
  node scripts/ingest-submodules.js --root-path /path/to/repo

AFTER INGESTION:
  1. Open Neo4j Browser: http://localhost:7474
  2. Run demo queries: node scripts/demo-graph-queries.js
  3. Visualize the component graph!

CONNECTION:
  Neo4j URI:      $NEO4J_URI (default: bolt://127.0.0.1:7687)
  Neo4j User:     $NEO4J_USER (default: neo4j)
  Neo4j Password: $NEO4J_PASSWORD (default: gfsworkflow2025)
`);
}

// Main execution
async function main() {
  const args = parseArgs();

  if (args.help) {
    showHelp();
    process.exit(0);
  }

  console.log(`
╔════════════════════════════════════════════════════════════════════════════╗
║          Submodule Graph Ingestion - Phase 0 POC                          ║
╚════════════════════════════════════════════════════════════════════════════╝
`);

  const neo4jClient = new Neo4jClient();

  try {
    // Step 1: Connect to Neo4j
    console.error('🔌 Step 1: Connecting to Neo4j...');
    await neo4jClient.connect();

    // Step 2: Clear database if requested
    if (args.clear) {
      console.error('\n⚠️  Step 2: Clearing database...');
      console.error('⚠️  WARNING: This will delete ALL existing data!');
      console.error('⚠️  Press Ctrl+C within 3 seconds to cancel...\n');

      await new Promise(resolve => setTimeout(resolve, 3000));

      await neo4jClient.clearDatabase();
      console.error('✅ Database cleared\n');
    } else {
      console.error('\n✅ Step 2: Using existing database (--clear not specified)\n');
    }

    // Step 3: Apply schema
    console.error('🏗️  Step 3: Applying graph schema...');
    await applySchema(neo4jClient);

    // Step 4: Ingest submodules
    console.error('📦 Step 4: Ingesting submodules...');
    const ingester = new SubmoduleGraphIngester(neo4jClient, {
      rootPath: args.rootPath,
      extractLanguageInfo: args.extractLanguageInfo,
      extractLOC: args.extractLOC,
      verbose: args.verbose
    });

    const result = await ingester.ingest();

    if (!result.success) {
      throw new Error('Ingestion failed');
    }

    // Step 5: Validate schema
    console.error('🔍 Step 5: Validating graph...');
    await validateSchema(neo4jClient);

    // Step 6: Success summary
    console.log(`
╔════════════════════════════════════════════════════════════════════════════╗
║                          🎉 INGESTION SUCCESSFUL 🎉                        ║
╚════════════════════════════════════════════════════════════════════════════╝

📊 NEXT STEPS:

  1️⃣  Open Neo4j Browser:
     http://localhost:7474

  2️⃣  Login with:
     Username: neo4j
     Password: gfsworkflow2025

  3️⃣  Run demo queries:
     node scripts/demo-graph-queries.js

  4️⃣  Explore the graph:
     MATCH (c:Component) RETURN c LIMIT 25

  5️⃣  Visualize dependencies:
     MATCH path = (root:Component)-[:CONTAINS*]->()
     WHERE root.name = 'global-workflow_MCP_node.js-RAG'
     RETURN path LIMIT 50

🚀 Phase 0 POC Complete! Graph RAG foundation is ready.
`);

    process.exit(0);

  } catch (error) {
    console.error(`\n❌ Fatal Error: ${error.message}\n`);
    console.error(error.stack);
    process.exit(1);
  } finally {
    await neo4jClient.disconnect();
  }
}

// Run
main().catch(error => {
  console.error('💥 Unhandled error:', error);
  process.exit(1);
});
