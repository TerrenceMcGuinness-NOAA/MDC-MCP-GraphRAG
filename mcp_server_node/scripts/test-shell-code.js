#!/usr/bin/env node

/**
 * Test Shell Code Structure Queries
 * 
 * Validates the shell script structure graph after ingestion:
 * - Function nodes and relationships
 * - Source/. command relationships
 * - Call graphs
 * - File-to-Component linkage
 */

import { Neo4jClient } from '../src/ingestion/neo4j/Neo4jClient.js';

const queries = [
  {
    name: 'Shell Code Structure Statistics',
    query: `
      RETURN 
        count{(f:Function {language: 'shell'})} AS shell_functions,
        count{(f:File {language: 'shell'})} AS shell_files,
        count{()-[:CALLS]->() WHERE EXISTS {
          MATCH (caller:Function {language: 'shell'})-[:CALLS]->()
        }} AS shell_calls,
        count{()-[:SOURCES]->()} AS source_commands
    `,
    description: 'Overall shell code structure statistics'
  },
  {
    name: 'Shell Files Ingested',
    query: `
      MATCH (f:File {language: 'shell'})
      RETURN f.path AS file, 
             count{(f)-[:DEFINES]->(fn:Function)} AS functions,
             count{(f)-[:SOURCES]->()} AS sources
      ORDER BY functions DESC
      LIMIT 15
    `,
    description: 'Shell files by function count'
  },
  {
    name: 'Most Common Shell Functions',
    query: `
      MATCH (f:Function {language: 'shell'})
      RETURN f.name AS function_name,
             count{(file:File)-[:DEFINES]->(f)} AS defined_in_files,
             count{(f)-[:CALLS]->()} AS calls_out
      ORDER BY defined_in_files DESC, calls_out DESC
      LIMIT 20
    `,
    description: 'Functions defined across multiple files (utility functions)'
  },
  {
    name: 'Shell Source Dependencies',
    query: `
      MATCH (f:File)-[s:SOURCES]->(target:File)
      RETURN f.path AS source_file,
             target.path AS sourced_file,
             s.type AS source_type,
             s.lineNumber AS line
      ORDER BY f.path
      LIMIT 30
    `,
    description: 'Shell script source/. dependencies'
  },
  {
    name: 'Most Sourced Files',
    query: `
      MATCH (target:File)<-[s:SOURCES]-()
      RETURN target.path AS file,
             count(s) AS times_sourced
      ORDER BY times_sourced DESC
      LIMIT 15
    `,
    description: 'Most frequently sourced utility files'
  },
  {
    name: 'Functions with Most Calls',
    query: `
      MATCH (f:Function {language: 'shell'})
      WHERE NOT f.isExternal
      RETURN f.name AS function,
             count{(f)-[:CALLS]->()} AS calls_out,
             count{()-[:CALLS]->(f)} AS calls_in
      ORDER BY calls_out DESC
      LIMIT 15
    `,
    description: 'Shell functions making the most calls'
  },
  {
    name: 'Script Entry Points',
    query: `
      MATCH (f:File {language: 'shell'})
      WHERE f.path STARTS WITH 'scripts/ex'
      RETURN f.path AS entry_point,
             count{(f)-[:DEFINES]->(fn:Function)} AS functions,
             count{(f)-[:SOURCES]->()} AS sources
      ORDER BY f.path
      LIMIT 20
    `,
    description: 'Execution script entry points (scripts/ex*.sh)'
  },
  {
    name: 'Utility Script Files',
    query: `
      MATCH (f:File {language: 'shell'})
      WHERE f.path STARTS WITH 'ush/'
      RETURN f.path AS utility_file,
             count{(f)-[:DEFINES]->(fn:Function)} AS functions,
             count{()<-[:SOURCES]-(f)} AS sourced_by_count
      ORDER BY functions DESC
      LIMIT 20
    `,
    description: 'Utility scripts in ush/ directory'
  },
  {
    name: 'Shell Function Call Chains',
    query: `
      MATCH (f1:Function {language: 'shell'})-[:CALLS]->(f2:Function {language: 'shell'})
      WHERE NOT f1.isExternal AND NOT f2.isExternal
      RETURN f1.name AS caller, f2.name AS callee, count(*) AS call_count
      ORDER BY call_count DESC
      LIMIT 20
    `,
    description: 'Most common function call patterns in shell scripts'
  },
  {
    name: 'Files by Language Distribution',
    query: `
      MATCH (f:File)
      WITH f.language AS language, count(f) AS file_count
      RETURN language, file_count
      ORDER BY file_count DESC
    `,
    description: 'Overall language distribution in codebase'
  }
];

async function runQuery(client, queryInfo, index, total) {
  console.log(`\n[${index + 1}/${total}] ${queryInfo.name}`);
  console.log(`Description: ${queryInfo.description}`);
  console.log('─'.repeat(80));
  
  try {
    const result = await client.runQuery(queryInfo.query, {});
    
    if (result.records.length === 0) {
      console.log('No results found');
      return;
    }
    
    // Print results
    const records = result.records.slice(0, 20); // Limit display to 20 rows
    for (const record of records) {
      const values = {};
      record.keys.forEach(key => {
        const value = record.get(key);
        // Handle Neo4j types
        if (value?.toNumber) {
          values[key] = value.toNumber();
        } else if (Array.isArray(value)) {
          values[key] = value.join(', ');
        } else {
          values[key] = value;
        }
      });
      console.log(JSON.stringify(values, null, 2));
    }
    
    if (result.records.length > records.length) {
      console.log(`... (${result.records.length - records.length} more results)`);
    }
    
  } catch (error) {
    console.error(`❌ Query failed: ${error.message}`);
  }
}

async function main() {
  console.log('=== Shell Code Structure Validation ===\n');
  
  let client = null;
  
  try {
    client = new Neo4jClient();
    await client.connect();
    console.log('✓ Connected to Neo4j\n');
    
    // Run all validation queries
    for (let i = 0; i < queries.length; i++) {
      await runQuery(client, queries[i], i, queries.length);
    }
    
    console.log('\n' + '='.repeat(80));
    console.log('Validation Complete');
    
  } catch (error) {
    console.error('\n❌ Validation failed:', error.message);
    process.exit(1);
  } finally {
    if (client) {
      await client.close();
    }
  }
}

main();
