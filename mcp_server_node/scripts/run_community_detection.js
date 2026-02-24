#!/usr/bin/env node

/**
 * run_community_detection.js - Phase 24E Pipeline Runner
 *
 * Runs CommunityDetection (24E-1) + CommunitySummarizer (24E-2)
 * to populate communityId on Neo4j nodes and store summaries in ChromaDB.
 *
 * Usage:
 *   node scripts/run_community_detection.js                 # flat detection + summaries
 *   node scripts/run_community_detection.js --materialize   # full hierarchical pipeline (24E-5)
 */

import { GraphDatabase } from '../src/data/GraphDatabase.js';
import { VectorDatabase } from '../src/data/VectorDatabase.js';
import CommunityDetection from '../src/graphrag/CommunityDetection.js';
import CommunitySummarizer from '../src/graphrag/CommunitySummarizer.js';

const materialize = process.argv.includes('--materialize');

async function main() {
  console.log('============================================================');
  console.log(`Phase 24E: Community Detection + ${materialize ? 'Hierarchical Materialization' : 'Summarization'} Pipeline`);
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

    if (materialize) {
      // Full hierarchical pipeline (24E-5)
      console.log('');
      console.log('--- Phase 24E-5: Hierarchical Materialization ---');

      // Step 1: Project + hierarchical Leiden
      const proj = await cd.projectGraph();
      console.log(`[OK] Projected: ${proj.nodeCount} nodes, ${proj.relationshipCount} rels`);

      const leiden = await cd.runHierarchicalLeiden({ maxLevels: 5, gamma: 1.0 });
      console.log(`[OK] Hierarchical Leiden: ${leiden.nodesUpdated} nodes, ${leiden.topCommunities} top communities, depth=${leiden.maxDepth}`);

      await cd.dropProjection();

      // Step 2: Community nodes
      const nodes = await cd.materializeCommunityNodes();
      console.log(`[OK] Created ${nodes.communityNodesCreated} Community nodes across ${nodes.levels} levels`);

      // Step 3: MEMBER_OF
      const memberOf = await cd.createMemberOfRelationships();
      console.log(`[OK] Created ${memberOf.relationshipsCreated} MEMBER_OF relationships`);

      // Step 4: PARENT_OF
      const parentOf = await cd.createParentOfHierarchy();
      console.log(`[OK] Created ${parentOf.relationshipsCreated} PARENT_OF relationships`);

      // Step 5: INTERACTS_WITH
      const interacts = await cd.computeInteractsWith(3);
      console.log(`[OK] Created ${interacts.relationshipsCreated} INTERACTS_WITH relationships`);

      // Step 6: Metadata enrichment
      const enriched = await cd.enrichCommunityMetadata();
      console.log(`[OK] Enriched ${enriched.enriched} Community nodes`);

      // Step 7: Hierarchical summaries
      const summarizer = new CommunitySummarizer({ communityDetection: cd, vectorDB });
      const summaryResult = await summarizer.summarizeHierarchical({ minSize: 3, maxCommunities: 500 });
      console.log(`[OK] Generated ${summaryResult.generated} hierarchical summaries across ${summaryResult.levels} levels`);

      console.log('');
      console.log('============================================================');
      console.log('Phase 24E-5 Complete (Hierarchical Materialization)');
      console.log(`  Community nodes: ${nodes.communityNodesCreated}`);
      console.log(`  Hierarchy levels: ${nodes.levels}`);
      console.log(`  MEMBER_OF: ${memberOf.relationshipsCreated}`);
      console.log(`  PARENT_OF: ${parentOf.relationshipsCreated}`);
      console.log(`  INTERACTS_WITH: ${interacts.relationshipsCreated}`);
      console.log(`  Summaries: ${summaryResult.generated}`);
      console.log('============================================================');

    } else {
      // Original flat pipeline
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
    }

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
