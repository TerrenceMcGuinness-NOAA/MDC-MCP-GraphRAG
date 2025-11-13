#!/usr/bin/env node

/**
 * @file test-cmake-queries.js
 * @description Test queries to validate CMake graph ingestion
 * 
 * USAGE:
 *   node scripts/test-cmake-queries.js [--verbose]
 * 
 * QUERIES:
 *   1. Build orchestration overview
 *   2. Component build dependencies
 *   3. Library dependency chains
 *   4. Executable build requirements
 *   5. CMake files per component
 *   6. Cross-component dependencies
 *   7. Build parallelization analysis
 *   8. Orphaned CMake targets
 * 
 * @author Claude Code CLI + GitHub Copilot
 * @version 1.0.0
 * @since 2025-01-15
 */

import { Neo4jClient } from '../dev/ci/scripts/utils/Copilot/mcp_server_node/src/ingestion/neo4j/Neo4jClient.js';

/**
 * Test queries for CMake graph validation
 */
const TEST_QUERIES = [
  {
    name: 'Build Orchestration Overview',
    description: 'Show build_all.sh orchestration structure',
    query: `
      MATCH (bo:BuildOrchestrator)-[r:BUILD_ORCHESTRATES]->(c:Component)
      RETURN bo.name as orchestrator,
             r.systemName as system,
             c.name as component,
             r.buildScript as buildScript,
             r.parallelJobs as jobs
      ORDER BY r.systemName, c.name
      LIMIT 20
    `,
    formatter: (records) => {
      console.log('\nSystem → Component Build Mappings:');
      let currentSystem = null;
      records.forEach(record => {
        const system = record.get('system');
        const component = record.get('component');
        const buildScript = record.get('buildScript');
        const jobs = record.get('jobs');
        
        if (system !== currentSystem) {
          console.log(`\n  [${system}]`);
          currentSystem = system;
        }
        console.log(`    → ${component} (${buildScript}, ${jobs} jobs)`);
      });
    }
  },
  
  {
    name: 'Component Build Dependencies',
    description: 'Show which components are managed by build orchestrator',
    query: `
      MATCH (bo:BuildOrchestrator)-[:BUILD_ORCHESTRATES]->(c:Component)
      RETURN c.name as component,
             count(*) as buildConfigs,
             collect(DISTINCT bo.name) as orchestrators
      ORDER BY c.name
    `,
    formatter: (records) => {
      console.log('\nComponents Managed by Build Orchestrator:');
      records.forEach(record => {
        const component = record.get('component');
        const buildConfigs = record.get('buildConfigs');
        console.log(`  ${component}: ${buildConfigs} build configuration(s)`);
      });
    }
  },
  
  {
    name: 'Library Dependency Chains',
    description: 'Show library → library dependencies',
    query: `
      MATCH (lib1:Library)-[d:DEPENDS_ON]->(lib2:Library)
      RETURN lib1.name as library,
             lib2.name as dependsOn,
             d.cmakeFile as definedIn
      ORDER BY lib1.name
      LIMIT 20
    `,
    formatter: (records) => {
      console.log('\nLibrary Dependencies:');
      if (records.length === 0) {
        console.log('  (No library dependencies found)');
      }
      records.forEach(record => {
        const lib = record.get('library');
        const dep = record.get('dependsOn');
        const file = record.get('definedIn');
        console.log(`  ${lib} → ${dep}`);
        console.log(`    defined in: ${file}`);
      });
    }
  },
  
  {
    name: 'Executable Build Requirements',
    description: 'Show executable → library dependencies',
    query: `
      MATCH (exe:Executable)-[d:DEPENDS_ON]->(lib:Library)
      RETURN exe.name as executable,
             collect(lib.name) as libraries,
             count(lib) as libraryCount
      ORDER BY libraryCount DESC
      LIMIT 10
    `,
    formatter: (records) => {
      console.log('\nExecutables and Their Library Dependencies:');
      if (records.length === 0) {
        console.log('  (No executable dependencies found)');
      }
      records.forEach(record => {
        const exe = record.get('executable');
        const libs = record.get('libraries');
        const count = record.get('libraryCount');
        console.log(`  ${exe} (${count} libraries)`);
        libs.slice(0, 5).forEach(lib => {
          console.log(`    → ${lib}`);
        });
        if (libs.length > 5) {
          console.log(`    ... and ${libs.length - 5} more`);
        }
      });
    }
  },
  
  {
    name: 'CMake Files Per Component',
    description: 'Count CMakeLists.txt files per component',
    query: `
      MATCH (lib:Library)-[:BUILT_BY]->(c:Component)
      WITH c, count(DISTINCT lib.cmakeFile) as cmakeFiles, count(lib) as libraries
      MATCH (exe:Executable)-[:BUILT_BY]->(c)
      WITH c, cmakeFiles, libraries, count(exe) as executables
      RETURN c.name as component,
             cmakeFiles,
             libraries,
             executables,
             (libraries + executables) as totalTargets
      ORDER BY totalTargets DESC
    `,
    formatter: (records) => {
      console.log('\nCMake Build Targets Per Component:');
      records.forEach(record => {
        const component = record.get('component');
        const cmakeFiles = record.get('cmakeFiles');
        const libraries = record.get('libraries');
        const executables = record.get('executables');
        const total = record.get('totalTargets');
        console.log(`  ${component}:`);
        console.log(`    CMakeLists.txt files: ${cmakeFiles}`);
        console.log(`    Libraries: ${libraries}`);
        console.log(`    Executables: ${executables}`);
        console.log(`    Total targets: ${total}`);
      });
    }
  },
  
  {
    name: 'Cross-Component Dependencies',
    description: 'Identify dependencies between different components',
    query: `
      MATCH (target1)-[:BUILT_BY]->(c1:Component),
            (target2)-[:BUILT_BY]->(c2:Component)
      WHERE c1 <> c2
      MATCH (target1)-[:DEPENDS_ON]->(target2)
      RETURN c1.name as fromComponent,
             c2.name as toComponent,
             count(*) as dependencies
      ORDER BY dependencies DESC
    `,
    formatter: (records) => {
      console.log('\nCross-Component Dependencies:');
      if (records.length === 0) {
        console.log('  (No cross-component dependencies found)');
      }
      records.forEach(record => {
        const from = record.get('fromComponent');
        const to = record.get('toComponent');
        const deps = record.get('dependencies');
        console.log(`  ${from} → ${to}: ${deps} dependencies`);
      });
    }
  },
  
  {
    name: 'Build Parallelization Analysis',
    description: 'Analyze parallel job allocation across components',
    query: `
      MATCH (bo:BuildOrchestrator)-[r:BUILD_ORCHESTRATES]->(c:Component)
      WITH r.systemName as system,
           sum(r.parallelJobs) as totalJobs,
           count(c) as componentCount,
           collect({component: c.name, jobs: r.parallelJobs}) as components
      RETURN system,
             totalJobs,
             componentCount,
             components
      ORDER BY totalJobs DESC
    `,
    formatter: (records) => {
      console.log('\nParallel Build Job Allocation:');
      records.forEach(record => {
        const system = record.get('system');
        const totalJobs = record.get('totalJobs');
        const componentCount = record.get('componentCount');
        const components = record.get('components');
        
        console.log(`\n  ${system} system: ${totalJobs} total jobs across ${componentCount} components`);
        components.forEach(comp => {
          console.log(`    ${comp.component}: ${comp.jobs} jobs`);
        });
      });
    }
  },
  
  {
    name: 'Orphaned CMake Targets',
    description: 'Find targets not linked to any component',
    query: `
      MATCH (target)
      WHERE (target:Library OR target:Executable)
        AND NOT (target)-[:BUILT_BY]->(:Component)
      RETURN labels(target)[0] as type,
             target.name as name,
             target.cmakeFile as cmakeFile
      ORDER BY type, name
      LIMIT 10
    `,
    formatter: (records) => {
      console.log('\nOrphaned CMake Targets (not linked to components):');
      if (records.length === 0) {
        console.log('  ✓ No orphaned targets found');
      } else {
        records.forEach(record => {
          const type = record.get('type');
          const name = record.get('name');
          const file = record.get('cmakeFile');
          console.log(`  ${type}: ${name}`);
          console.log(`    in ${file}`);
        });
      }
    }
  }
];

/**
 * Run all test queries
 */
async function runTestQueries(neo4jClient, verbose) {
  console.log('\nRunning CMake Graph Test Queries');
  console.log('=================================\n');
  
  let successCount = 0;
  let failCount = 0;
  
  for (const testQuery of TEST_QUERIES) {
    console.log(`\n[${ TEST_QUERIES.indexOf(testQuery) + 1}/${TEST_QUERIES.length}] ${testQuery.name}`);
    console.log(`    ${testQuery.description}`);
    
    try {
      const result = await neo4jClient.runQuery(testQuery.query);
      
      if (result.records.length === 0) {
        console.log('    ⚠ No results returned');
      } else {
        if (verbose) {
          console.log(`    ✓ ${result.records.length} results`);
        }
        
        // Use custom formatter if provided
        if (testQuery.formatter) {
          testQuery.formatter(result.records);
        } else {
          // Default formatter
          result.records.slice(0, 5).forEach(record => {
            console.log('   ', JSON.stringify(record.toObject()));
          });
          if (result.records.length > 5) {
            console.log(`    ... and ${result.records.length - 5} more results`);
          }
        }
      }
      
      successCount++;
      
    } catch (error) {
      console.error(`    ❌ Query failed: ${error.message}`);
      failCount++;
    }
  }
  
  // Summary
  console.log('\n\n=== Test Summary ===');
  console.log(`Successful: ${successCount}/${TEST_QUERIES.length}`);
  console.log(`Failed: ${failCount}/${TEST_QUERIES.length}`);
  
  return { successCount, failCount };
}

/**
 * Get overall graph statistics
 */
async function getGraphStatistics(neo4jClient) {
  console.log('\n\n=== CMake Graph Statistics ===');
  
  const queries = [
    { label: 'BuildOrchestrator nodes', query: 'MATCH (bo:BuildOrchestrator) RETURN count(bo) as count' },
    { label: 'Library nodes', query: 'MATCH (l:Library) RETURN count(l) as count' },
    { label: 'Executable nodes', query: 'MATCH (e:Executable) RETURN count(e) as count' },
    { label: 'BUILD_ORCHESTRATES relationships', query: 'MATCH ()-[r:BUILD_ORCHESTRATES]->() RETURN count(r) as count' },
    { label: 'DEPENDS_ON relationships', query: 'MATCH ()-[r:DEPENDS_ON {linkType: "cmake_target_link"}]->() RETURN count(r) as count' },
    { label: 'BUILT_BY relationships', query: 'MATCH ()-[r:BUILT_BY]->() RETURN count(r) as count' }
  ];
  
  for (const { label, query } of queries) {
    try {
      const result = await neo4jClient.runQuery(query);
      const count = result.records[0]?.get('count')?.toNumber() || 0;
      console.log(`${label}: ${count}`);
    } catch (error) {
      console.error(`${label}: Error - ${error.message}`);
    }
  }
}

/**
 * Main execution function
 */
async function main() {
  const verbose = process.argv.includes('--verbose');
  
  console.log('CMake Graph Test Queries');
  console.log('========================\n');
  
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
    console.log('✓ Connected to Neo4j');
    
    // Get graph statistics
    await getGraphStatistics(neo4jClient);
    
    // Run test queries
    const results = await runTestQueries(neo4jClient, verbose);
    
    // Overall result
    if (results.failCount === 0) {
      console.log('\n✓ All test queries completed successfully!');
      console.log('\nNext Steps:');
      console.log('1. Visualize in Neo4j Browser: http://localhost:7474');
      console.log('2. Run demo queries: node scripts/demo-graph-queries.js');
      console.log('3. Continue to Phase 1: Code structure ingestion');
    } else {
      console.log(`\n⚠ ${results.failCount} test(s) failed`);
      process.exit(1);
    }
    
  } catch (error) {
    console.error('\n❌ Fatal error:', error.message);
    if (verbose) {
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
