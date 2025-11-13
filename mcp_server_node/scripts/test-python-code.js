#!/usr/bin/env node

/**
 * Test Python Code Structure Queries
 * 
 * Validates the code structure graph after Python ingestion:
 * - Function nodes and relationships
 * - Class nodes and inheritance
 * - Import relationships
 * - Call graphs
 * - File-to-Component linkage
 */

import { Neo4jClient } from '../src/ingestion/neo4j/Neo4jClient.js';

const queries = [
  {
    name: 'Code Structure Statistics',
    query: `
      RETURN 
        count{(f:Function)} AS functions,
        count{(c:Class)} AS classes,
        count{(m:Module)} AS modules,
        count{(f:File)} AS files,
        count{()-[:CALLS]->()} AS calls,
        count{()-[:IMPORTS]->()} AS imports,
        count{()-[:DEFINES]->()} AS defines
    `,
    description: 'Overall code structure statistics'
  },
  {
    name: 'Python Files Ingested',
    query: `
      MATCH (f:File {language: 'python'})
      RETURN f.path AS file, 
             count{(f)-[:DEFINES]->(fn:Function)} AS functions,
             count{(f)-[:DEFINES]->(c:Class)} AS classes,
             count{(f)-[:IMPORTS]->()} AS imports
      ORDER BY functions DESC
      LIMIT 10
    `,
    description: 'Top 10 Python files by function count'
  },
  {
    name: 'Most Connected Functions',
    query: `
      MATCH (f:Function)
      WHERE f.isExternal IS NULL OR f.isExternal = false
      RETURN f.name AS function,
             count{(f)-[:CALLS]->()} AS calls_out,
             count{()-[:CALLS]->(f)} AS calls_in,
             count{(f)-[:CALLS]->()} + count{()-[:CALLS]->(f)} AS total_connections
      ORDER BY total_connections DESC
      LIMIT 10
    `,
    description: 'Functions with most connections (call graph hubs)'
  },
  {
    name: 'Class Hierarchy',
    query: `
      MATCH (c:Class)
      RETURN c.name AS class,
             c.baseClasses AS inherits_from,
             count{(f:File)-[:DEFINES]->(c)} AS defined_in_files,
             count{(c)<-[:DEFINES]-(f)-[:DEFINES]->(m:Function {className: c.name})} AS methods
      ORDER BY methods DESC
      LIMIT 10
    `,
    description: 'Classes with their inheritance and method counts'
  },
  {
    name: 'Most Imported Modules',
    query: `
      MATCH (m:Module)<-[:IMPORTS]-()
      RETURN m.name AS module,
             count{()<-[:IMPORTS]-(m)} AS import_count,
             m.isExternal AS is_external
      ORDER BY import_count DESC
      LIMIT 15
    `,
    description: 'Most frequently imported modules (dependencies)'
  },
  {
    name: 'Function Call Chains',
    query: `
      MATCH path = (f1:Function)-[:CALLS*2..3]->(f2:Function)
      WHERE f1.isExternal IS NULL AND f2.isExternal IS NULL
      WITH [node in nodes(path) | node.name] AS chain
      RETURN DISTINCT chain, length(chain) AS depth
      ORDER BY depth DESC
      LIMIT 10
    `,
    description: 'Function call chains (2-3 hops)'
  },
  {
    name: 'Functions by Language',
    query: `
      MATCH (f:Function)
      WITH f.language AS language, 
           count(f) AS function_count,
           count{(f)-[:CALLS]->()} AS total_calls,
           count{(f) WHERE f.isAsync = true} AS async_functions,
           count{(f) WHERE f.isMethod = true} AS methods
      RETURN language, function_count, total_calls, async_functions, methods
      ORDER BY function_count DESC
    `,
    description: 'Function breakdown by language'
  },
  {
    name: 'External Dependencies',
    query: `
      MATCH (m:Module {isExternal: true})
      RETURN m.name AS external_module,
             count{()-[:IMPORTS]->(m)} AS usage_count
      ORDER BY usage_count DESC
      LIMIT 20
    `,
    description: 'External module dependencies and usage'
  },
  {
    name: 'Files Without Functions',
    query: `
      MATCH (f:File {language: 'python'})
      WHERE NOT exists{(f)-[:DEFINES]->(:Function)}
      RETURN f.path AS file,
             count{(f)-[:IMPORTS]->()} AS imports,
             count{(f)-[:DEFINES]->(:Class)} AS classes
      LIMIT 10
    `,
    description: 'Python files without function definitions'
  },
  {
    name: 'Decorator Usage',
    query: `
      MATCH (f:Function)
      WHERE f.decorators IS NOT NULL AND size(f.decorators) > 0
      UNWIND f.decorators AS decorator
      RETURN decorator, count(*) AS usage_count
      ORDER BY usage_count DESC
      LIMIT 10
    `,
    description: 'Most common function decorators'
  }
];

async function runQuery(client, queryInfo, index, total) {
  console.log(`\n[${ index + 1}/${total}] ${queryInfo.name}`);
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
  console.log('=== Python Code Structure Validation ===\n');
  
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
