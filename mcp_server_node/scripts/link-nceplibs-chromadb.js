#!/usr/bin/env node
/**
 * Phase 34D: Link NCEPLIBS FortranSubroutine nodes to ChromaDB documentation.
 *
 * Queries Neo4j for all NCEPLIBS Fortran nodes, searches ChromaDB for matching
 * API documentation, and sets `chromadb_doc_id` + `documented: true` on matches
 * with similarity distance < 0.3 (high confidence).
 *
 * Usage: node scripts/link-nceplibs-chromadb.js [--dry-run] [--threshold 0.3]
 */

import neo4j from 'neo4j-driver';
import { ChromaClient } from 'chromadb';

const CHROMADB_URL = process.env.CHROMADB_URL || 'http://localhost:8080';
const NEO4J_URI = process.env.NEO4J_URI || 'bolt://localhost:7687';
const NEO4J_USER = process.env.NEO4J_USER || 'neo4j';
const NEO4J_PASS = process.env.NEO4J_PASSWORD || 'gfsworkflow2025';

const args = process.argv.slice(2);
const DRY_RUN = args.includes('--dry-run');
const thresholdIdx = args.indexOf('--threshold');
const THRESHOLD = thresholdIdx >= 0 ? parseFloat(args[thresholdIdx + 1]) : 0.3;

async function main() {
  console.log(`[INFO] Phase 34D ChromaDB Linkage`);
  console.log(`[INFO] Threshold: ${THRESHOLD}, Dry run: ${DRY_RUN}`);

  const driver = neo4j.driver(NEO4J_URI, neo4j.auth.basic(NEO4J_USER, NEO4J_PASS));
  const chroma = new ChromaClient({ path: CHROMADB_URL });

  // Find the docs collection
  const collections = await chroma.listCollections();
  const docsCol = collections.find(c =>
    (c.name || c).toString().includes('global-workflow-docs')
  );
  if (!docsCol) {
    console.log('[WARN] No global-workflow-docs collection found in ChromaDB');
    console.log('[INFO] Available collections:', collections.map(c => c.name || c));
    await driver.close();
    return;
  }
  const colName = docsCol.name || docsCol;
  console.log(`[OK] Using ChromaDB collection: ${colName}`);
  const collection = await chroma.getCollection({ name: colName });

  // Get all NCEPLIBS Fortran nodes from Neo4j
  const session = driver.session();
  const result = await session.run(`
    MATCH (n)
    WHERE n.repo STARTS WITH 'nceplibs-'
      AND (n:FortranSubroutine OR n:FortranFunction OR n:FortranModule)
    RETURN n.name AS name, labels(n)[0] AS label, n.repo AS repo, elementId(n) AS eid
    ORDER BY n.repo, n.name
  `);

  const nodes = result.records.map(r => ({
    name: r.get('name'),
    label: r.get('label'),
    repo: r.get('repo'),
    eid: r.get('eid')
  }));
  console.log(`[OK] Found ${nodes.length} NCEPLIBS Fortran nodes to match`);

  // Batch query ChromaDB (batches of 20 to avoid overwhelming)
  const BATCH = 20;
  let linked = 0;
  let skipped = 0;

  for (let i = 0; i < nodes.length; i += BATCH) {
    const batch = nodes.slice(i, i + BATCH);
    const queries = batch.map(n => {
      const libName = n.repo.replace('nceplibs-', '');
      return `${libName} ${n.name} Fortran ${n.label.replace('Fortran', '').toLowerCase()}`;
    });

    try {
      const results = await collection.query({
        queryTexts: queries,
        nResults: 1
      });

      for (let j = 0; j < batch.length; j++) {
        const distances = results.distances[j];
        const ids = results.ids[j];

        if (distances && distances[0] < THRESHOLD) {
          const docId = ids[0];
          const distance = distances[0].toFixed(4);
          const node = batch[j];

          if (!DRY_RUN) {
            await session.run(`
              MATCH (n)
              WHERE n.name = $name AND n.repo = $repo
                AND (n:FortranSubroutine OR n:FortranFunction OR n:FortranModule)
              SET n.chromadb_doc_id = $docId, n.documented = true
            `, { name: node.name, repo: node.repo, docId });
          }

          linked++;
          if (linked <= 10 || linked % 50 === 0) {
            console.log(`  [LINK] ${node.repo}/${node.name} -> ${docId} (dist=${distance})`);
          }
        } else {
          skipped++;
        }
      }
    } catch (err) {
      console.log(`[WARN] ChromaDB query error for batch ${i}: ${err.message}`);
      skipped += batch.length;
    }

    // Progress
    if ((i + BATCH) % 100 === 0 || i + BATCH >= nodes.length) {
      console.log(`[INFO] Progress: ${Math.min(i + BATCH, nodes.length)}/${nodes.length} processed`);
    }
  }

  // Create DOCUMENTED_BY edges from linked nodes to a virtual doc node
  if (!DRY_RUN && linked > 0) {
    const docResult = await session.run(`
      MATCH (n)
      WHERE n.chromadb_doc_id IS NOT NULL
        AND n.repo STARTS WITH 'nceplibs-'
      RETURN count(n) AS cnt
    `);
    console.log(`[OK] ${docResult.records[0].get('cnt')} nodes now have chromadb_doc_id set`);
  }

  console.log(`\n[SUMMARY]`);
  console.log(`  Total nodes:  ${nodes.length}`);
  console.log(`  Linked:       ${linked} (distance < ${THRESHOLD})`);
  console.log(`  Skipped:      ${skipped}`);
  console.log(`  Link rate:    ${(linked / nodes.length * 100).toFixed(1)}%`);
  if (DRY_RUN) console.log(`  [DRY RUN] No Neo4j writes performed`);

  await session.close();
  await driver.close();
}

main().catch(err => {
  console.error('[ERROR]', err.message);
  process.exit(1);
});
