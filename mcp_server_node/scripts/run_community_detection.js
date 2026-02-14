#!/usr/bin/env node

/**
 * run_community_detection.js - Phase 24E Pipeline Runner
 *
 * Runs CommunityDetection (24E-1) + CommunitySummarizer (24E-2)
 * to populate communityId on Neo4j nodes and store summaries in ChromaDB.
 *
 * Usage: node scripts/run_community_detection.js
 */

import { GraphDatabase } from '../src/data/GraphDatabase.js';
import { VectorDatabase } from '../src/data/VectorDatabase.js';
import CommunityDetection from '../src/graphrag/CommunityDetection.js';
import CommunitySummarizer from '../src/graphrag/CommunitySummarizer.js';

async function main() {
  console.log('============================================================');
  console.log('Phase 24E: Community Detection + Summarization Pipeline');
  console.log('============================================================');

  // Initialize databases
  const graphDB = new GraphDatabase();
  const vectorDB = new VectorDatabase();

  try {
    // Connect to databases
    console.log('[INFO] Connecting to databases...');
    await graphDB.connect();
    await vectorDB.connect();
    console.log('[OK] Connected to Neo4j and ChromaDB');

    // Phase 24E-1: Community Detection
    const cd = new CommunityDetection(graphDB);

    // Check GDS
    const gds = await cd.checkGDS();
    if (!gds.available) {
      console.error('[ERROR] Neo4j GDS plugin not available. Cannot run community detection.');
      process.exit(1);
    }
    console.log(`[OK] GDS ${gds.version} available`);

    // Run full Leiden pipeline
    const result = await cd.runFullPipeline();
    console.log(`[OK] Communities: ${result.leiden.communityCount}, Modularity: ${result.leiden.modularity.toFixed(4)}`);

    // Phase 24E-2: Community Summarization
    console.log('');
    const summarizer = new CommunitySummarizer({
      communityDetection: cd,
      vectorDB: vectorDB
    });

    const summaryResult = await summarizer.summarizeAll({
      minSize: 3,
      maxCommunities: 500
    });
    console.log(`[OK] Generated ${summaryResult.generated} summaries, stored in ChromaDB`);

    console.log('');
    console.log('============================================================');
    console.log('Phase 24E Complete');
    console.log(`  Communities: ${result.leiden.communityCount}`);
    console.log(`  Summaries:  ${summaryResult.generated}`);
    console.log(`  Total time: ${result.elapsedMs + summaryResult.elapsedMs}ms`);
    console.log('============================================================');

  } catch (err) {
    console.error('[ERROR]', err.message);
    console.error(err.stack);
    process.exit(1);
  } finally {
    await graphDB.close?.();
    await vectorDB.close?.();
  }
}

main();
