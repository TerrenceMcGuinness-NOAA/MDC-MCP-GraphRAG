#!/usr/bin/env node

/**
 * import_llm_summaries.js - Phase 24E-6 Step 3
 *
 * Imports LLM-generated summaries from Step 2 into Neo4j (Community nodes)
 * and ChromaDB (community-summaries collection). Sets metadata fields
 * for tracking: summarySource, summaryModel, summaryTimestamp.
 *
 * Usage:
 *   node scripts/import_llm_summaries.js
 *   node scripts/import_llm_summaries.js --input data/llm_summaries.json
 *   node scripts/import_llm_summaries.js --dry-run   # preview without writing
 *   node scripts/import_llm_summaries.js --skip-chromadb  # Neo4j only
 *   node scripts/import_llm_summaries.js --skip-neo4j     # ChromaDB only
 *
 * @phase Phase 24E-6
 * @author Terry McGuinness + AI Assistants
 * @date 2026-02-25
 */

import { readFileSync, existsSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { GraphDatabase } from '../src/data/GraphDatabase.js';
import { VectorDatabase } from '../src/data/VectorDatabase.js';
import neo4j from 'neo4j-driver';

const __dirname = dirname(fileURLToPath(import.meta.url));
const DATA_DIR = resolve(__dirname, '..', 'data');

const args = process.argv.slice(2);
function getArg(name, fallback) {
  const idx = args.indexOf(`--${name}`);
  return idx !== -1 && args[idx + 1] ? args[idx + 1] : fallback;
}

const inputPath = getArg('input', resolve(DATA_DIR, 'llm_summaries.json'));
const dryRun = args.includes('--dry-run');
const skipChromadb = args.includes('--skip-chromadb');
const skipNeo4j = args.includes('--skip-neo4j');

const COLLECTION_NAME = 'community-summaries';
const CHROMADB_BATCH_SIZE = 50;

async function importToNeo4j(graphDB, summaries) {
  console.log(`[INFO] Importing ${summaries.length} summaries to Neo4j...`);

  let updated = 0;
  let errors = 0;

  for (const s of summaries) {
    const session = graphDB.driver.session({
      database: graphDB.config.database,
      defaultAccessMode: neo4j.session.WRITE
    });
    try {
      await session.run(`
        MATCH (c:Community {communityId: $communityId})
        SET c.summary = $summary,
            c.summarySource = 'llm',
            c.summaryModel = $model,
            c.summaryTimestamp = $timestamp
        RETURN c.communityId AS id
      `, {
        communityId: s.communityId,
        summary: s.summary,
        model: s.model || 'gpt-4o-mini',
        timestamp: s.timestamp || new Date().toISOString()
      });
      updated++;
    } catch (err) {
      errors++;
      console.error(`[ERROR] Neo4j update failed for ${s.communityId}: ${err.message}`);
    } finally {
      await session.close();
    }

    if (updated % 100 === 0 && updated > 0) {
      console.log(`[INFO] Neo4j: ${updated} updated...`);
    }
  }

  console.log(`[OK] Neo4j: ${updated} updated, ${errors} errors`);
  return { updated, errors };
}

async function importToChromaDB(vectorDB, summaries) {
  console.log(`[INFO] Importing ${summaries.length} summaries to ChromaDB collection '${COLLECTION_NAME}'...`);
  console.log(`[INFO] Embeddings will be auto-generated via Xenova/all-mpnet-base-v2`);

  const documents = summaries.map(s => ({
    id: `community-${s.communityId}`,
    text: s.summary,
    metadata: {
      communityId: String(s.communityId),
      level: s.level,
      name: s.name || `community-${s.communityId}`,
      memberCount: s.memberCount || 0,
      summarySource: 'llm',
      summaryModel: s.model || 'gpt-4o-mini',
      summaryTimestamp: s.timestamp || new Date().toISOString(),
      type: 'community-summary'
    }
  }));

  let imported = 0;
  let errors = 0;

  // Process in batches
  for (let i = 0; i < documents.length; i += CHROMADB_BATCH_SIZE) {
    const batch = documents.slice(i, i + CHROMADB_BATCH_SIZE);
    try {
      await vectorDB.addDocuments(COLLECTION_NAME, batch);
      imported += batch.length;
      console.log(`[INFO] ChromaDB: ${imported}/${documents.length} imported...`);
    } catch (err) {
      errors += batch.length;
      console.error(`[ERROR] ChromaDB batch ${i}-${i + batch.length} failed: ${err.message}`);
    }
  }

  console.log(`[OK] ChromaDB: ${imported} imported, ${errors} errors`);
  return { imported, errors };
}

async function main() {
  console.log('============================================================');
  console.log('Phase 24E-6 Step 3: Import LLM Summaries');
  console.log(`  Input: ${inputPath}`);
  console.log(`  Dry run: ${dryRun}`);
  console.log(`  Neo4j: ${skipNeo4j ? 'SKIP' : 'YES'}`);
  console.log(`  ChromaDB: ${skipChromadb ? 'SKIP' : 'YES'}`);
  console.log('============================================================');

  if (!existsSync(inputPath)) {
    console.error(`[ERROR] Input not found: ${inputPath}`);
    console.error('       Run generate_llm_summaries.js first (Step 2).');
    process.exit(1);
  }

  const allResults = JSON.parse(readFileSync(inputPath, 'utf8'));
  const summaries = allResults.filter(r => r.summary);
  const failed = allResults.filter(r => !r.summary);

  console.log(`[INFO] Total entries: ${allResults.length}`);
  console.log(`[INFO] With summaries: ${summaries.length}`);
  console.log(`[INFO] Failed/missing: ${failed.length}`);

  if (summaries.length === 0) {
    console.error('[ERROR] No valid summaries to import');
    process.exit(1);
  }

  // Summary by level
  const byLevel = {};
  for (const s of summaries) {
    byLevel[s.level] = (byLevel[s.level] || 0) + 1;
  }
  for (const [level, count] of Object.entries(byLevel).sort((a, b) => a[0] - b[0])) {
    console.log(`[INFO]   Level ${level}: ${count} summaries`);
  }

  if (dryRun) {
    console.log('');
    console.log('[DRY RUN] Preview of first 3 summaries:');
    for (const s of summaries.slice(0, 3)) {
      console.log(`  L${s.level} ${s.name || s.communityId}: ${s.summary.slice(0, 120)}...`);
    }
    console.log('');
    console.log('[DRY RUN] No data written. Remove --dry-run to execute.');
    return;
  }

  const startTime = Date.now();
  let graphDB = null;
  let vectorDB = null;
  const stats = { neo4j: null, chromadb: null };

  try {
    // Neo4j import
    if (!skipNeo4j) {
      graphDB = new GraphDatabase();
      await graphDB.connect();
      console.log('[OK] Connected to Neo4j');
      stats.neo4j = await importToNeo4j(graphDB, summaries);
    }

    // ChromaDB import
    if (!skipChromadb) {
      vectorDB = new VectorDatabase();
      await vectorDB.connect();
      console.log('[OK] Connected to ChromaDB');
      stats.chromadb = await importToChromaDB(vectorDB, summaries);
    }

    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);

    console.log('');
    console.log('============================================================');
    console.log(`Phase 24E-6 Step 3 Complete: Import`);
    if (stats.neo4j) {
      console.log(`  Neo4j: ${stats.neo4j.updated} updated, ${stats.neo4j.errors} errors`);
    }
    if (stats.chromadb) {
      console.log(`  ChromaDB: ${stats.chromadb.imported} imported, ${stats.chromadb.errors} errors`);
    }
    console.log(`  Elapsed: ${elapsed}s`);
    console.log('============================================================');

  } catch (err) {
    console.error(`[ERROR] Import failed: ${err.message}`);
    process.exit(1);
  } finally {
    try { if (graphDB) await graphDB.close(); } catch {}
  }
}

main();
