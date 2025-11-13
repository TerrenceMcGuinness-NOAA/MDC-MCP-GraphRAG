#!/usr/bin/env node

/**
 * Demo Graph Queries - Phase 0 POC Value Demonstration
 *
 * Demonstrates the power of Neo4j Graph RAG by running queries that are
 * impossible or difficult with ChromaDB vector search alone.
 *
 * These queries prove the value of the graph database approach:
 * - Structural relationships
 * - Dependency chains
 * - Component hierarchies
 * - Impact analysis
 *
 * Usage:
 *   node scripts/demo-graph-queries.js [query-number]
 *
 * @version 1.0.0
 */

import { Neo4jClient } from '../src/ingestion/neo4j/Neo4jClient.js';

class GraphQueryDemo {
  constructor() {
    this.client = new Neo4jClient();
  }

  async connect() {
    await this.client.connect();
  }

  async disconnect() {
    await this.client.disconnect();
  }

  /**
   * Query 1: List all components in the system
   */
  async query1_ListAllComponents() {
    console.log('\n' + '═'.repeat(70));
    console.log('📦 Query 1: List All Components');
    console.log('═'.repeat(70));
    console.log('What it answers: "What are all the components in the system?"\n');

    const result = await this.client.runQuery(`
      MATCH (c:Component)
      RETURN c.name as name, c.language as language, c.loc as loc, c.description as description
      ORDER BY c.name
    `);

    console.log(`Found ${result.records.length} components:\n`);

    result.records.forEach((record, index) => {
      const name = record.get('name');
      const language = record.get('language') || 'Unknown';
      const loc = record.get('loc') || 0;
      const description = record.get('description');

      console.log(`${index + 1}. ${name}`);
      console.log(`   Language: ${language}`);
      if (loc > 0) console.log(`   LOC: ${loc.toLocaleString()}`);
      if (description) console.log(`   ${description.substring(0, 80)}...`);
      console.log();
    });

    return result.records.length;
  }

  /**
   * Query 2: Show submodule hierarchy
   */
  async query2_SubmoduleHierarchy() {
    console.log('\n' + '═'.repeat(70));
    console.log('🌳 Query 2: Submodule Hierarchy');
    console.log('═'.repeat(70));
    console.log('What it answers: "What is the containment structure of submodules?"\n');

    const result = await this.client.runQuery(`
      MATCH path = (root:Component)-[:CONTAINS*1..3]->(child:Component)
      WHERE NOT (()-[:CONTAINS]->(root))
      RETURN root.name as root, child.name as child, length(path) as depth
      ORDER BY depth, child
      LIMIT 50
    `);

    console.log(`Found ${result.records.length} submodule relationships:\n`);

    let currentDepth = 0;
    result.records.forEach(record => {
      const root = record.get('root');
      const child = record.get('child');
      const depth = record.get('depth').toNumber();

      if (depth !== currentDepth) {
        console.log(`\n${'─'.repeat(depth * 2)} Level ${depth}:`);
        currentDepth = depth;
      }

      console.log(`${'  '.repeat(depth)}└─ ${child}`);
    });

    console.log();
    return result.records.length;
  }

  /**
   * Query 3: Find components with most submodules
   */
  async query3_MostSubmodules() {
    console.log('\n' + '═'.repeat(70));
    console.log('📊 Query 3: Components with Most Submodules');
    console.log('═'.repeat(70));
    console.log('What it answers: "Which components have the most dependencies?"\n');

    const result = await this.client.runQuery(`
      MATCH (c:Component)-[:CONTAINS]->(sub:Component)
      WITH c, COUNT(sub) as submoduleCount
      WHERE submoduleCount > 0
      RETURN c.name as component, submoduleCount
      ORDER BY submoduleCount DESC
      LIMIT 10
    `);

    console.log(`Top ${result.records.length} components by submodule count:\n`);

    result.records.forEach((record, index) => {
      const component = record.get('component');
      const count = record.get('submoduleCount').toNumber();
      const bar = '█'.repeat(Math.min(count, 50));

      console.log(`${index + 1}. ${component.padEnd(40)} ${bar} ${count}`);
    });

    console.log();
    return result.records.length;
  }

  /**
   * Query 4: Find leaf components (no submodules)
   */
  async query4_LeafComponents() {
    console.log('\n' + '═'.repeat(70));
    console.log('🍃 Query 4: Leaf Components (No Submodules)');
    console.log('═'.repeat(70));
    console.log('What it answers: "Which components are at the bottom of the hierarchy?"\n');

    const result = await this.client.runQuery(`
      MATCH (c:Component)
      WHERE NOT (c)-[:CONTAINS]->()
      RETURN c.name as name, c.language as language, c.loc as loc
      ORDER BY c.loc DESC
      LIMIT 20
    `);

    console.log(`Found ${result.records.length} leaf components:\n`);

    result.records.forEach((record, index) => {
      const name = record.get('name');
      const language = record.get('language') || 'Unknown';
      const loc = record.get('loc') || 0;

      console.log(`${index + 1}. ${name.padEnd(40)} [${language.padEnd(8)}] ${loc.toLocaleString()} LOC`);
    });

    console.log();
    return result.records.length;
  }

  /**
   * Query 5: Component depth analysis
   */
  async query5_DepthAnalysis() {
    console.log('\n' + '═'.repeat(70));
    console.log('📏 Query 5: Submodule Depth Analysis');
    console.log('═'.repeat(70));
    console.log('What it answers: "How deep does our submodule nesting go?"\n');

    const result = await this.client.runQuery(`
      MATCH path = (root:Component)-[:CONTAINS*]->(leaf:Component)
      WHERE NOT (()-[:CONTAINS]->(root)) AND NOT (leaf)-[:CONTAINS]->()
      WITH root.name as root, leaf.name as leaf, length(path) as depth
      ORDER BY depth DESC
      RETURN root, leaf, depth
      LIMIT 10
    `);

    console.log(`Deepest submodule paths:\n`);

    result.records.forEach((record, index) => {
      const root = record.get('root');
      const leaf = record.get('leaf');
      const depth = record.get('depth').toNumber();

      console.log(`${index + 1}. Depth ${depth}: ${root} → ... → ${leaf}`);
    });

    console.log();
    return result.records.length;
  }

  /**
   * Query 6: Language distribution
   */
  async query6_LanguageDistribution() {
    console.log('\n' + '═'.repeat(70));
    console.log('🌐 Query 6: Language Distribution');
    console.log('═'.repeat(70));
    console.log('What it answers: "What languages are used across components?"\n');

    const result = await this.client.runQuery(`
      MATCH (c:Component)
      WHERE c.language IS NOT NULL
      WITH c.language as language, COUNT(*) as count, SUM(c.loc) as totalLOC
      ORDER BY count DESC
      RETURN language, count, totalLOC
    `);

    console.log(`Language distribution:\n`);

    let totalComponents = 0;
    let totalLOC = 0;

    result.records.forEach(record => {
      const language = record.get('language');
      const count = record.get('count').toNumber();
      const loc = record.get('totalLOC').toNumber();

      totalComponents += count;
      totalLOC += loc;

      const bar = '█'.repeat(Math.min(count * 2, 40));
      console.log(`${language.padEnd(12)} ${bar} ${count} components (${loc.toLocaleString()} LOC)`);
    });

    console.log(`\nTotal: ${totalComponents} components, ${totalLOC.toLocaleString()} LOC\n`);
    return result.records.length;
  }

  /**
   * Query 7: Path between two components
   */
  async query7_PathBetweenComponents() {
    console.log('\n' + '═'.repeat(70));
    console.log('🛤️  Query 7: Path Between Components');
    console.log('═'.repeat(70));
    console.log('What it answers: "How are two components connected?"\n');

    // Get two random components
    const components = await this.client.runQuery(`
      MATCH (c:Component)
      RETURN c.name as name
      ORDER BY rand()
      LIMIT 2
    `);

    if (components.records.length < 2) {
      console.log('Not enough components to demonstrate path query\n');
      return 0;
    }

    const comp1 = components.records[0].get('name');
    const comp2 = components.records[1].get('name');

    console.log(`Finding path from "${comp1}" to "${comp2}"...\n`);

    const result = await this.client.runQuery(`
      MATCH path = shortestPath((a:Component {name: $comp1})-[:CONTAINS*]-(b:Component {name: $comp2}))
      RETURN [node in nodes(path) | node.name] as pathNodes, length(path) as pathLength
      LIMIT 1
    `, { comp1, comp2 });

    if (result.records.length > 0) {
      const pathNodes = result.records[0].get('pathNodes');
      const pathLength = result.records[0].get('pathLength').toNumber();

      console.log(`Path found (length ${pathLength}):\n`);
      console.log(pathNodes.join(' → '));
    } else {
      console.log('No path found (components not connected)\n');
    }

    console.log();
    return result.records.length;
  }

  /**
   * Query 8: Database statistics
   */
  async query8_DatabaseStatistics() {
    console.log('\n' + '═'.repeat(70));
    console.log('📊 Query 8: Database Statistics');
    console.log('═'.repeat(70));
    console.log('What it answers: "What is the overall structure of our graph?"\n');

    const stats = await this.client.getDatabaseStats();

    console.log(`Total Nodes: ${stats.totalNodes}`);
    console.log(`Total Relationships: ${stats.totalRelationships}\n`);

    if (Object.keys(stats.nodesByLabel).length > 0) {
      console.log('Nodes by Label:');
      Object.entries(stats.nodesByLabel).forEach(([label, count]) => {
        console.log(`  ${label.padEnd(20)} ${count}`);
      });
    }

    if (Object.keys(stats.relationshipsByType).length > 0) {
      console.log('\nRelationships by Type:');
      Object.entries(stats.relationshipsByType).forEach(([type, count]) => {
        console.log(`  ${type.padEnd(20)} ${count}`);
      });
    }

    console.log();
    return 1;
  }

  /**
   * Run all demo queries
   */
  async runAllQueries() {
    console.log(`
╔════════════════════════════════════════════════════════════════════════════╗
║              Neo4j Graph RAG Demo Queries - Phase 0 POC                   ║
║                                                                            ║
║  These queries demonstrate structural analysis impossible with            ║
║  vector embeddings alone. ChromaDB is great for semantic search,          ║
║  but Neo4j excels at relationships and dependencies.                      ║
╚════════════════════════════════════════════════════════════════════════════╝
`);

    const results = {
      query1: await this.query1_ListAllComponents(),
      query2: await this.query2_SubmoduleHierarchy(),
      query3: await this.query3_MostSubmodules(),
      query4: await this.query4_LeafComponents(),
      query5: await this.query5_DepthAnalysis(),
      query6: await this.query6_LanguageDistribution(),
      query7: await this.query7_PathBetweenComponents(),
      query8: await this.query8_DatabaseStatistics()
    };

    console.log('═'.repeat(70));
    console.log('🎉 Demo Complete!');
    console.log('═'.repeat(70));
    console.log('\nThese queries prove Neo4j can answer structural questions that');
    console.log('ChromaDB cannot. This validates our Graph RAG approach!\n');
    console.log('Next Steps:');
    console.log('  1. Open Neo4j Browser: http://localhost:7474');
    console.log('  2. Try your own Cypher queries');
    console.log('  3. Visualize the component graph');
    console.log('  4. Proceed to Phase 1: CMake dependency parsing\n');

    return results;
  }
}

// Main execution
async function main() {
  const demo = new GraphQueryDemo();

  try {
    await demo.connect();

    // If query number provided, run specific query
    const queryNum = process.argv[2];
    if (queryNum) {
      const num = parseInt(queryNum);
      if (num >= 1 && num <= 8) {
        await demo[`query${num}_${Object.keys(demo).find(k => k.startsWith(`query${num}_`))?.split('_')[1]}`]();
      } else {
        console.error('Invalid query number. Must be 1-8');
        process.exit(1);
      }
    } else {
      // Run all queries
      await demo.runAllQueries();
    }

    process.exit(0);

  } catch (error) {
    console.error(`\n❌ Error: ${error.message}`);
    console.error(error.stack);
    process.exit(1);
  } finally {
    await demo.disconnect();
  }
}

// Run
main().catch(error => {
  console.error('💥 Unhandled error:', error);
  process.exit(1);
});
