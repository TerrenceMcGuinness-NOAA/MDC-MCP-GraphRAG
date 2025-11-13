#!/usr/bin/env node

/**
 * Test Neo4j Connection and Basic Operations
 *
 * Verifies Neo4j is running and accessible, then tests basic Cypher queries
 */

import neo4j from 'neo4j-driver';

const NEO4J_URI = process.env.NEO4J_URI || 'bolt://127.0.0.1:7687';
const NEO4J_USER = process.env.NEO4J_USER || 'neo4j';
const NEO4J_PASSWORD = process.env.NEO4J_PASSWORD || 'gfsworkflow2025';

async function testNeo4jConnection() {
  console.log('🧪 Testing Neo4j Connection\n');
  console.log(`📍 URI: ${NEO4J_URI}`);
  console.log(`👤 User: ${NEO4J_USER}\n`);

  const driver = neo4j.driver(
    NEO4J_URI,
    neo4j.auth.basic(NEO4J_USER, NEO4J_PASSWORD)
  );

  let session;
  let testsPassed = 0;
  let testsFailed = 0;

  try {
    // Test 1: Server Connectivity
    console.log('Test 1: Server Connectivity');
    session = driver.session();
    const serverInfo = await driver.getServerInfo();
    console.log(`✅ PASS: Connected to Neo4j ${serverInfo.protocolVersion}`);
    console.log(`   Server Address: ${serverInfo.address}`);
    console.log(`   Agent: ${serverInfo.agent}\n`);
    testsPassed++;
    await session.close();

    // Test 2: Database Query (count nodes)
    console.log('Test 2: Query Database');
    session = driver.session();
    const countResult = await session.run('MATCH (n) RETURN count(n) as count');
    const nodeCount = countResult.records[0].get('count').toNumber();
    console.log(`✅ PASS: Database query successful`);
    console.log(`   Current node count: ${nodeCount}\n`);
    testsPassed++;
    await session.close();

    // Test 3: Create Test Node
    console.log('Test 3: Create Test Node');
    session = driver.session();
    await session.run(
      'MERGE (t:TestNode {id: $id}) SET t.timestamp = $timestamp RETURN t',
      { id: 'test-connection', timestamp: new Date().toISOString() }
    );
    console.log('✅ PASS: Test node created\n');
    testsPassed++;
    await session.close();

    // Test 4: Query Test Node
    console.log('Test 4: Query Test Node');
    session = driver.session();
    const queryResult = await session.run(
      'MATCH (t:TestNode {id: $id}) RETURN t.timestamp as timestamp',
      { id: 'test-connection' }
    );
    if (queryResult.records.length > 0) {
      const timestamp = queryResult.records[0].get('timestamp');
      console.log('✅ PASS: Test node retrieved');
      console.log(`   Timestamp: ${timestamp}\n`);
      testsPassed++;
    } else {
      console.log('❌ FAIL: Test node not found\n');
      testsFailed++;
    }
    await session.close();

    // Test 5: Delete Test Node (cleanup)
    console.log('Test 5: Cleanup Test Node');
    session = driver.session();
    await session.run(
      'MATCH (t:TestNode {id: $id}) DELETE t',
      { id: 'test-connection' }
    );
    console.log('✅ PASS: Test node deleted\n');
    testsPassed++;
    await session.close();

    // Test 6: Check database version
    console.log('Test 6: Database Version');
    session = driver.session();
    const versionResult = await session.run('CALL dbms.components() YIELD versions RETURN versions[0] as version');
    const version = versionResult.records[0].get('version');
    console.log(`✅ PASS: Neo4j version ${version}\n`);
    testsPassed++;
    await session.close();

    // Summary
    console.log('═'.repeat(60));
    console.log('📊 Test Summary');
    console.log('═'.repeat(60));
    console.log(`✅ Passed: ${testsPassed}`);
    console.log(`❌ Failed: ${testsFailed}`);
    console.log(`📈 Success Rate: ${((testsPassed / (testsPassed + testsFailed)) * 100).toFixed(1)}%`);
    console.log('═'.repeat(60));

    if (testsFailed === 0) {
      console.log('\n🎉 All tests passed! Neo4j is ready for Graph RAG.\n');
      process.exit(0);
    } else {
      console.log('\n⚠️  Some tests failed. Check configuration.\n');
      process.exit(1);
    }

  } catch (error) {
    console.error('\n💥 Error during testing:');
    console.error(error.message);
    console.error(error.stack);
    process.exit(1);
  } finally {
    if (session) {
      await session.close();
    }
    await driver.close();
  }
}

// Run tests
testNeo4jConnection().catch(error => {
  console.error('\n💥 Unhandled error:');
  console.error(error);
  process.exit(1);
});
