#!/usr/bin/env node
/**
 * test-data-access.js - Quick health check for Data Access Layer
 * 
 * Verifies connections and basic operations
 */

import { GraphDatabase, VectorDatabase, UnifiedDataAccess } from './src/data/index.js';

async function testDataAccessLayer() {
  console.log('\n🧪 Data Access Layer Health Check\n');
  console.log('='.repeat(60));

  // Test GraphDatabase
  console.log('\n1️⃣  Testing GraphDatabase (Neo4j)...');
  const graphDB = new GraphDatabase();
  try {
    await graphDB.connect();
    const health = await graphDB.healthCheck();
    console.log('   ✅ Neo4j connection:', health.status);
    console.log('   📊 Statistics:', health.statistics);
    console.log('   📈 Metrics:', health.metrics);
    await graphDB.close();
  } catch (error) {
    console.error('   ❌ GraphDatabase error:', error.message);
  }

  // Test VectorDatabase
  console.log('\n2️⃣  Testing VectorDatabase (ChromaDB)...');
  const vectorDB = new VectorDatabase();
  try {
    await vectorDB.connect();
    const health = await vectorDB.healthCheck();
    console.log('   ✅ ChromaDB connection:', health.status);
    console.log('   📚 Collections:', health.collections);
    console.log('   📈 Metrics:', health.metrics);
    await vectorDB.close();
  } catch (error) {
    console.error('   ❌ VectorDatabase error:', error.message);
  }

  // Test UnifiedDataAccess
  console.log('\n3️⃣  Testing UnifiedDataAccess (Hybrid)...');
  const unified = new UnifiedDataAccess();
  try {
    await unified.connect();
    const health = await unified.healthCheck();
    console.log('   ✅ Unified connection:', health.status);
    console.log('   🔗 Graph status:', health.graph.status);
    console.log('   🔗 Vector status:', health.vector.status);
    
    const stats = await unified.getStatistics();
    console.log('\n   📊 Combined Statistics:');
    console.log('      Graph:', stats.graph);
    console.log('      Vector:', stats.vector);
    console.log('      Unified:', stats.unified);
    
    await unified.close();
  } catch (error) {
    console.error('   ❌ UnifiedDataAccess error:', error.message);
  }

  console.log('\n' + '='.repeat(60));
  console.log('✅ Health check complete!\n');
}

testDataAccessLayer().catch(error => {
  console.error('\n❌ Health check failed:', error);
  process.exit(1);
});
