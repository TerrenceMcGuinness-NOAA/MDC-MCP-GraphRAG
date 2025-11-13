#!/usr/bin/env node

/**
 * Drop all Neo4j constraints - useful for schema changes
 */

import { Neo4jClient } from '../src/ingestion/neo4j/Neo4jClient.js';

async function main() {
  const client = new Neo4jClient();

  try {
    await client.connect();

    console.log('🗑️  Dropping all constraints...\n');

    // Drop all constraints
    const constraints = await client.runQuery('SHOW CONSTRAINTS');

    for (const record of constraints.records) {
      const name = record.get('name');
      try {
        await client.runWriteQuery(`DROP CONSTRAINT ${name} IF EXISTS`);
        console.log(`✅ Dropped: ${name}`);
      } catch (error) {
        console.error(`⚠️  Failed to drop ${name}: ${error.message}`);
      }
    }

    console.log('\n✅ All constraints dropped');
    await client.disconnect();
    process.exit(0);
  } catch (error) {
    console.error('❌ Error:', error.message);
    await client.disconnect();
    process.exit(1);
  }
}

main();
