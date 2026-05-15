/**
 * capture-golden-files.js — Step 18: Capture Golden-File Baseline from Legacy System
 *
 * Runs a representative set of queries against the legacy system (ChromaDB + Neo4j)
 * and saves the results as golden files for regression testing after AWS cutover.
 *
 * Golden files are saved to: scripts/golden-files/<tool>/<query-hash>.json
 * and uploaded to: s3://mdc-mcp-rag-migration/golden-files/
 *
 * Usage:
 *   node scripts/capture-golden-files.js [--upload]
 *
 * Env vars:
 *   CHROMADB_URL, NEO4J_URI, NEO4J_PASSWORD
 *   AWS_REGION, MIGRATION_BUCKET (only needed with --upload)
 */

import { S3Client, PutObjectCommand } from '@aws-sdk/client-s3';
import { ChromaClient } from 'chromadb';
import neo4j from 'neo4j-driver';
import { createHash } from 'node:crypto';
import { mkdirSync, writeFileSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));

const CHROMA_URL = process.env.CHROMADB_URL  || 'http://127.0.0.1:8080';
const NEO4J_URI  = process.env.NEO4J_URI     || 'bolt://localhost:7687';
const NEO4J_PASS = process.env.NEO4J_PASSWORD || 'gfsworkflow2025';
const REGION     = process.env.AWS_REGION    || 'us-east-1';
const BUCKET     = process.env.MIGRATION_BUCKET || 'mdc-mcp-rag-migration';
const UPLOAD     = process.argv.includes('--upload');

const GOLDEN_DIR = join(__dirname, 'golden-files');

// Representative queries covering all 5 collections and graph traversal
const VECTOR_QUERIES = [
  { collection: 'global-workflow-docs-v8-0-0', query: 'GFS forecast model initialization', nResults: 5 },
  { collection: 'code-with-context-v8-0-0',    query: 'setuprad radiation setup function', nResults: 5 },
  { collection: 'jjobs-v8-0-0',                query: 'JGLOBAL_FORECAST job script', nResults: 5 },
  { collection: 'community-summaries',          query: 'data assimilation subsystem', nResults: 5 },
  { collection: 'ee2-standards-v5-0-0-enhanced', query: 'error handling set -eu pipefail', nResults: 5 },
  // Multi-collection
  { collections: ['global-workflow-docs-v8-0-0', 'code-with-context-v8-0-0'], query: 'enkf ensemble Kalman filter', nResults: 5 },
  // With metadata filter
  { collection: 'code-with-context-v8-0-0', query: 'python task class', nResults: 5, where: { language: 'python' } },
];

const GRAPH_QUERIES = [
  { name: 'findCallers:setuprad',       cypher: "MATCH (c)-[:CALLS]->(f {name: 'setuprad'}) RETURN c.name AS caller LIMIT 10" },
  { name: 'findImporters:numpy',        cypher: "MATCH (f)-[:IMPORTS]->(m:Module {name: 'numpy'}) RETURN f.path AS file LIMIT 10" },
  { name: 'getStatistics',              cypher: 'MATCH (n) RETURN count(n) AS nodeCount' },
  { name: 'findFilesByLanguage:python', cypher: "MATCH (f:File {language: 'python'}) RETURN f.path AS path LIMIT 10" },
];

function queryHash(q) {
  return createHash('md5').update(JSON.stringify(q)).digest('hex').slice(0, 8);
}

function saveGolden(category, name, data) {
  const dir = join(GOLDEN_DIR, category);
  mkdirSync(dir, { recursive: true });
  const file = join(dir, `${name}.json`);
  writeFileSync(file, JSON.stringify({ capturedAt: new Date().toISOString(), ...data }, null, 2));
  return file;
}

async function captureVectorGoldens() {
  console.log('\n[PHASE 1] Capturing vector search golden files');
  const chroma = new ChromaClient({ path: `${CHROMA_URL}/api/v2` });
  const results = [];

  for (const q of VECTOR_QUERIES) {
    try {
      let queryResults;
      if (q.collections) {
        // Multi-collection: query each and merge
        const allResults = [];
        for (const col of q.collections) {
          const collection = await chroma.getCollection({ name: col });
          const r = await collection.query({ queryTexts: [q.query], nResults: q.nResults, include: ['documents', 'metadatas', 'distances'] });
          for (let i = 0; i < r.ids[0].length; i++) {
            allResults.push({ id: r.ids[0][i], text: r.documents[0][i], metadata: r.metadatas[0][i], distance: r.distances[0][i], collection: col });
          }
        }
        allResults.sort((a, b) => a.distance - b.distance);
        queryResults = allResults.slice(0, q.nResults);
      } else {
        const collection = await chroma.getCollection({ name: q.collection });
        const opts = { queryTexts: [q.query], nResults: q.nResults, include: ['documents', 'metadatas', 'distances'] };
        if (q.where) opts.where = q.where;
        const r = await collection.query(opts);
        queryResults = r.ids[0].map((id, i) => ({
          id, text: r.documents[0][i], metadata: r.metadatas[0][i], distance: r.distances[0][i],
        }));
      }

      const key = queryHash(q);
      const file = saveGolden('vectors', key, { query: q, results: queryResults });
      console.log(`  [OK]  ${q.collection || q.collections?.join('+')} "${q.query.slice(0, 40)}" → ${queryResults.length} results`);
      results.push({ key, file, resultCount: queryResults.length });
    } catch (err) {
      console.error(`  [WARN] ${q.query.slice(0, 40)}: ${err.message}`);
    }
  }
  return results;
}

async function captureGraphGoldens() {
  console.log('\n[PHASE 2] Capturing graph query golden files');
  const driver = neo4j.driver(NEO4J_URI, neo4j.auth.basic('neo4j', NEO4J_PASS), { disableLosslessIntegers: true });
  const session = driver.session({ defaultAccessMode: neo4j.session.READ });
  const results = [];

  try {
    for (const q of GRAPH_QUERIES) {
      try {
        const r = await session.run(q.cypher);
        const rows = r.records.map(rec => {
          const obj = {};
          rec.keys.forEach(k => { obj[k] = rec.get(k); });
          return obj;
        });
        const file = saveGolden('graph', q.name, { query: q, results: rows });
        console.log(`  [OK]  ${q.name} → ${rows.length} rows`);
        results.push({ name: q.name, file, resultCount: rows.length });
      } catch (err) {
        console.error(`  [WARN] ${q.name}: ${err.message}`);
      }
    }
  } finally {
    await session.close();
    await driver.close();
  }
  return results;
}

async function uploadGoldens() {
  const s3 = new S3Client({ region: REGION });
  const { readdirSync, readFileSync } = await import('node:fs');

  for (const category of ['vectors', 'graph']) {
    const dir = join(GOLDEN_DIR, category);
    if (!existsSync(dir)) continue;
    for (const file of readdirSync(dir)) {
      const body = readFileSync(join(dir, file));
      await s3.send(new PutObjectCommand({
        Bucket: BUCKET, Key: `golden-files/${category}/${file}`,
        Body: body, ContentType: 'application/json',
      }));
    }
  }
  console.log(`\n[OK]  Golden files uploaded to s3://${BUCKET}/golden-files/`);
}

async function main() {
  console.log('[START] Capturing golden-file baseline from legacy system');
  mkdirSync(GOLDEN_DIR, { recursive: true });

  const [vectorResults, graphResults] = await Promise.all([
    captureVectorGoldens(),
    captureGraphGoldens(),
  ]);

  // Write manifest
  const manifest = {
    capturedAt: new Date().toISOString(),
    vectors: vectorResults,
    graph: graphResults,
    totalFiles: vectorResults.length + graphResults.length,
  };
  writeFileSync(join(GOLDEN_DIR, 'manifest.json'), JSON.stringify(manifest, null, 2));
  console.log(`\n[OK]  ${manifest.totalFiles} golden files saved to ${GOLDEN_DIR}`);

  if (UPLOAD) await uploadGoldens();
}

main().catch(err => { console.error('[FATAL]', err.message); process.exit(1); });
