#!/usr/bin/env node

/**
 * Ingest GitHub Metadata CLI
 *
 * Ingests GitHub/Git metadata into Neo4j graph database:
 * - Git commit history from local repositories
 * - Developer nodes from commit authors
 * - Commit-Component-Developer relationships
 *
 * Usage:
 *   node scripts/ingest-github-metadata.js [options]
 *
 * Options:
 *   --max-commits <n>    Maximum commits per repository (default: 100)
 *   --no-github-api      Skip GitHub API features (Issues/PRs)
 *   --verbose            Verbose output
 *   --help               Show this help
 *
 * Environment:
 *   GH_TOKEN or GITHUB_TOKEN - GitHub API token (optional, for Issues/PRs)
 *
 * Examples:
 *   node scripts/ingest-github-metadata.js
 *   node scripts/ingest-github-metadata.js --max-commits 50 --verbose
 *   node scripts/ingest-github-metadata.js --no-github-api
 *
 * @version 1.0.0
 */

import { Neo4jClient } from '../src/ingestion/neo4j/Neo4jClient.js';
import { GitHubGraphIngester } from '../src/ingestion/neo4j/GitHubGraphIngester.js';
import { validateSchema } from '../src/ingestion/neo4j/GraphSchema.js';

// Parse command line arguments
function parseArgs() {
  const args = {
    maxCommitsPerRepo: 100,
    includeGitHubAPI: true,
    verbose: false,
    help: false
  };

  for (let i = 2; i < process.argv.length; i++) {
    const arg = process.argv[i];

    if (arg === '--help' || arg === '-h') {
      args.help = true;
    } else if (arg === '--verbose' || arg === '-v') {
      args.verbose = true;
    } else if (arg === '--no-github-api') {
      args.includeGitHubAPI = false;
    } else if (arg === '--max-commits') {
      args.maxCommitsPerRepo = parseInt(process.argv[++i], 10);
    }
  }

  return args;
}

// Show help
function showHelp() {
  console.log(`
╔════════════════════════════════════════════════════════════════════════════╗
║               GitHub Metadata Ingestion - Phase 1                          ║
╚════════════════════════════════════════════════════════════════════════════╝

Ingests Git commit history and GitHub metadata into Neo4j graph database.

FEATURES:
  ✅ Git commit history from local repositories
  ✅ Developer nodes from commit authors
  ✅ Commit-Component-Developer relationships
  ⚠️  GitHub Issues/PRs (requires GH_TOKEN)

USAGE:
  node scripts/ingest-github-metadata.js [options]

OPTIONS:
  --max-commits <n>    Maximum commits per repository (default: 100)
                       Lower values = faster, Higher values = more complete

  --no-github-api      Skip GitHub API features (Issues/PRs)
                       Use if you don't have a GitHub token

  --verbose, -v        Show detailed progress information
  --help, -h           Show this help message

ENVIRONMENT VARIABLES:
  GH_TOKEN             GitHub personal access token (optional)
  GITHUB_TOKEN         Alternative to GH_TOKEN (optional)
                       Required for Issues/PRs ingestion

EXAMPLES:
  # Basic ingestion (100 commits per repo)
  node scripts/ingest-github-metadata.js

  # Fast ingestion (only recent 50 commits)
  node scripts/ingest-github-metadata.js --max-commits 50

  # Full verbose output
  node scripts/ingest-github-metadata.js --max-commits 200 --verbose

  # Skip GitHub API (no token needed)
  node scripts/ingest-github-metadata.js --no-github-api

WHAT THIS CREATES:
  📝 Commit nodes with messages and timestamps
  👥 Developer nodes with names and emails
  🔗 AUTHORED relationships (Developer → Commit)
  🔗 CONTRIBUTED_TO relationships (Developer → Component)

AFTER INGESTION:
  1. Open Neo4j Browser: http://localhost:7474
  2. Run demo queries: node scripts/demo-graph-queries.js
  3. Visualize developer graph!

EXAMPLE QUERIES:
  # Show top contributors
  MATCH (d:Developer)-[r:CONTRIBUTED_TO]->(c:Component)
  RETURN d.name, d.email, sum(r.commits) as total_commits
  ORDER BY total_commits DESC
  LIMIT 10

  # Show commit history for a component
  MATCH (d:Developer)-[:AUTHORED]->(commit:Commit)
  MATCH (c:Component {name: 'ufs_model.fd'})
  WHERE exists((d)-[:CONTRIBUTED_TO]->(c))
  RETURN d.name, commit.message, commit.timestamp
  ORDER BY commit.timestamp DESC
  LIMIT 20

CONNECTION:
  Neo4j URI:      bolt://127.0.0.1:7687
  Neo4j User:     neo4j
  Neo4j Password: gfsworkflow2025
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
║               GitHub Metadata Ingestion - Phase 1                          ║
╚════════════════════════════════════════════════════════════════════════════╝
`);

  const neo4jClient = new Neo4jClient();

  try {
    // Step 1: Connect to Neo4j
    console.error('🔌 Step 1: Connecting to Neo4j...');
    await neo4jClient.connect();

    // Step 2: Verify components exist
    console.error('\n🔍 Step 2: Checking for existing components...');
    const componentCount = await neo4jClient.getNodeCount('Component');

    if (componentCount === 0) {
      console.error(`\n❌ Error: No Component nodes found in database!`);
      console.error(`\nYou must run submodule ingestion first:`);
      console.error(`  node scripts/ingest-submodules.js\n`);
      process.exit(1);
    }

    console.error(`✅ Found ${componentCount} components\n`);

    // Step 3: Ingest GitHub metadata
    console.error('📚 Step 3: Ingesting GitHub metadata...');
    const ingester = new GitHubGraphIngester(neo4jClient, {
      maxCommitsPerRepo: args.maxCommitsPerRepo,
      includeGitHubAPI: args.includeGitHubAPI,
      verbose: args.verbose
    });

    const result = await ingester.ingest();

    if (!result.success) {
      throw new Error('Ingestion failed');
    }

    // Step 4: Validate graph
    console.error('🔍 Step 4: Validating graph...');
    await validateSchema(neo4jClient);

    // Step 5: Success summary
    console.log(`
╔════════════════════════════════════════════════════════════════════════════╗
║                          🎉 INGESTION SUCCESSFUL 🎉                        ║
╚════════════════════════════════════════════════════════════════════════════╝

📊 RESULTS:
  📝 Commits: ${result.stats.commitsCreated.toLocaleString()}
  👥 Developers: ${result.stats.developersCreated.toLocaleString()}
  🔗 Relationships: ${result.stats.relationshipsCreated.toLocaleString()}
  ⏱️  Time: ${(result.stats.processingTime / 1000).toFixed(1)}s

📊 NEXT STEPS:

  1️⃣  Open Neo4j Browser:
     http://localhost:7474

  2️⃣  Query top contributors:
     MATCH (d:Developer)-[r:CONTRIBUTED_TO]->(c:Component)
     RETURN d.name, sum(r.commits) as commits
     ORDER BY commits DESC LIMIT 10

  3️⃣  Visualize developer-component graph:
     MATCH path = (d:Developer)-[:CONTRIBUTED_TO]->(c:Component)
     RETURN path LIMIT 50

  4️⃣  Show commit history:
     MATCH (d:Developer)-[:AUTHORED]->(commit:Commit)
     RETURN d.name, commit.message, commit.timestamp
     ORDER BY commit.timestamp DESC LIMIT 20

  5️⃣  Run updated demo queries:
     node scripts/demo-graph-queries.js

🚀 Phase 1: Developer Graph Complete!
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
