#!/usr/bin/env node

import { Neo4jClient } from '../src/ingestion/neo4j/Neo4jClient.js';

async function main() {
  const client = new Neo4jClient();
  
  try {
    await client.connect();
    console.log('\n📊 Testing GitHub Metadata Queries\n');
    
    // Query 1: Top 10 Contributors
    console.log('═'.repeat(70));
    console.log('Query 1: Top 10 Contributors by Commit Count');
    console.log('═'.repeat(70));
    
    const topContributors = await client.runQuery(`
      MATCH (d:Developer)-[r:CONTRIBUTED_TO]->(c:Component)
      RETURN d.name as name, d.email as email, sum(r.commits) as total_commits, count(c) as components_touched
      ORDER BY total_commits DESC
      LIMIT 10
    `);
    
    console.log('\n');
    topContributors.records.forEach((record, idx) => {
      const name = record.get('name');
      const email = record.get('email');
      const commits = record.get('total_commits');
      const components = record.get('components_touched');
      console.log(`${idx + 1}. ${name} <${email}>`);
      console.log(`   Commits: ${commits}, Components: ${components}`);
    });
    
    // Query 2: Recent Commits
    console.log('\n\n' + '═'.repeat(70));
    console.log('Query 2: Most Recent 10 Commits');
    console.log('═'.repeat(70));
    
    const recentCommits = await client.runQuery(`
      MATCH (d:Developer)-[:AUTHORED]->(commit:Commit)
      RETURN d.name as name, commit.message as message, commit.timestamp as timestamp
      ORDER BY commit.timestamp DESC
      LIMIT 10
    `);
    
    console.log('\n');
    recentCommits.records.forEach((record, idx) => {
      const name = record.get('name');
      const message = record.get('message');
      const timestamp = record.get('timestamp');
      console.log(`${idx + 1}. [${timestamp}] ${name}`);
      console.log(`   ${message}`);
    });
    
    // Query 3: Developer Statistics
    console.log('\n\n' + '═'.repeat(70));
    console.log('Query 3: Developer Statistics');
    console.log('═'.repeat(70));
    
    const stats = await client.runQuery(`
      MATCH (d:Developer)
      RETURN count(d) as total_developers,
             avg(d.commitCount) as avg_commits_per_dev,
             max(d.commitCount) as max_commits
    `);
    
    const statsRecord = stats.records[0];
    console.log(`\nTotal Developers: ${statsRecord.get('total_developers')}`);
    console.log(`Average Commits per Developer: ${statsRecord.get('avg_commits_per_dev').toFixed(1)}`);
    console.log(`Most Active Developer: ${statsRecord.get('max_commits')} commits`);
    
    console.log('\n✅ All queries successful!\n');
    
  } catch (error) {
    console.error('❌ Error:', error.message);
    process.exit(1);
  } finally {
    await client.disconnect();
  }
}

main();
