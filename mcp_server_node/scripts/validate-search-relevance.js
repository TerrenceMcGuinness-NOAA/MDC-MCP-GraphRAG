/**
 * validate-search-relevance.js — Step 19: Search Relevance Validation (5% tolerance)
 *
 * Runs the same queries against both ChromaDB (legacy) and OpenSearch (AWS),
 * compares top-k rankings with epsilon=0.05 tolerance.
 *
 * Validates:
 *   - Single-collection query ranking similarity
 *   - Metadata filter equivalence
 *   - Multi-collection query equivalence
 *
 * Usage:
 *   node scripts/validate-search-relevance.js [--epsilon 0.05] [--top-k 5]
 *
 * Env vars:
 *   CHROMADB_URL, OPENSEARCH_ENDPOINT, AWS_REGION
 */

import { Client as OpenSearchClient } from '@opensearch-project/opensearch';
import { AwsSigv4Signer } from '@opensearch-project/opensearch/lib/aws/index-v3.js';
import { defaultProvider } from '@aws-sdk/credential-provider-node';
import { ChromaClient } from 'chromadb';
import { pipeline } from '@xenova/transformers';

const REGION      = process.env.AWS_REGION       || 'us-east-1';
const CHROMA_URL  = process.env.CHROMADB_URL     || 'http://127.0.0.1:8080';
const OS_ENDPOINT = process.env.OPENSEARCH_ENDPOINT || '';

const args      = process.argv.slice(2);
const EPSILON   = parseFloat(args[args.indexOf('--epsilon') + 1] || '0.05');
const TOP_K     = parseInt(args[args.indexOf('--top-k') + 1]    || '5', 10);

const COLLECTION_TO_INDEX = {
  'code-with-context-v8-0-0':      'mdc-code-context',
  'global-workflow-docs-v8-0-0':   'mdc-workflow-docs',
  'jjobs-v8-0-0':                  'mdc-jjobs',
  'community-summaries':           'mdc-community-summaries',
  'ee2-standards-v5-0-0-enhanced': 'mdc-ee2-standards',
};

// Test queries: single-collection, with filter, multi-collection
const TEST_QUERIES = [
  { type: 'single', collection: 'global-workflow-docs-v8-0-0', query: 'GFS forecast initialization' },
  { type: 'single', collection: 'code-with-context-v8-0-0',    query: 'setuprad radiation parameterization' },
  { type: 'single', collection: 'jjobs-v8-0-0',                query: 'JGLOBAL_FORECAST job script' },
  { type: 'filter', collection: 'code-with-context-v8-0-0',    query: 'python task class', where: { language: 'python' } },
  { type: 'multi',  collections: ['global-workflow-docs-v8-0-0', 'code-with-context-v8-0-0'], query: 'enkf ensemble Kalman filter' },
];

// ── Ranking similarity metric ─────────────────────────────────────────────────
// Normalized Discounted Cumulative Gain overlap: fraction of top-k IDs in common,
// weighted by position. Simple overlap@k is sufficient for 5% tolerance check.

function overlapAtK(legacyIds, awsIds, k) {
  const legacySet = new Set(legacyIds.slice(0, k));
  const awsSet    = new Set(awsIds.slice(0, k));
  let overlap = 0;
  for (const id of legacySet) if (awsSet.has(id)) overlap++;
  return overlap / Math.max(legacySet.size, 1);
}

// ── ChromaDB queries ──────────────────────────────────────────────────────────

async function queryChroma(chroma, q) {
  if (q.type === 'multi') {
    const allResults = [];
    for (const col of q.collections) {
      const collection = await chroma.getCollection({ name: col });
      const r = await collection.query({ queryTexts: [q.query], nResults: TOP_K, include: ['distances'] });
      r.ids[0].forEach((id, i) => allResults.push({ id, distance: r.distances[0][i] }));
    }
    allResults.sort((a, b) => a.distance - b.distance);
    return allResults.slice(0, TOP_K).map(r => r.id);
  }

  const collection = await chroma.getCollection({ name: q.collection });
  const opts = { queryTexts: [q.query], nResults: TOP_K, include: ['distances'] };
  if (q.where) opts.where = q.where;
  const r = await collection.query(opts);
  return r.ids[0];
}

// ── OpenSearch queries ────────────────────────────────────────────────────────

async function queryOpenSearch(os, embedder, q) {
  const texts = Array.isArray(q.collections) ? [q.query] : [q.query];
  const output = await embedder(texts, { pooling: 'mean', normalize: true });
  const vector = output.tolist()[0];

  const indices = q.collections
    ? q.collections.map(c => COLLECTION_TO_INDEX[c]).join(',')
    : COLLECTION_TO_INDEX[q.collection];

  const knnQuery = { vector, k: TOP_K };
  let body;

  if (q.where) {
    const filters = Object.entries(q.where).map(([k, v]) => ({ term: { [`metadata.${k}`]: v } }));
    body = { size: TOP_K, query: { bool: { must: [{ knn: { embedding: knnQuery } }], filter: filters } } };
  } else {
    body = { size: TOP_K, query: { knn: { embedding: knnQuery } } };
  }

  const resp = await os.search({ index: indices, body });
  return resp.body.hits.hits.map(h => h._id);
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  console.log(`[START] Search Relevance Validation (epsilon=${EPSILON}, top-k=${TOP_K})\n`);

  if (!OS_ENDPOINT) { console.error('[ERROR] OPENSEARCH_ENDPOINT required'); process.exit(1); }

  const chroma = new ChromaClient({ path: `${CHROMA_URL}/api/v2` });
  const os = new OpenSearchClient({
    ...AwsSigv4Signer({ region: REGION, service: 'es', getCredentials: defaultProvider() }),
    node: OS_ENDPOINT,
  });

  console.log('[INFO] Loading embedding model...');
  const embedder = await pipeline('feature-extraction', 'Xenova/all-mpnet-base-v2');

  const results = [];
  let passed = 0, failed = 0;

  for (const q of TEST_QUERIES) {
    try {
      const [legacyIds, awsIds] = await Promise.all([
        queryChroma(chroma, q),
        queryOpenSearch(os, embedder, q),
      ]);

      const similarity = overlapAtK(legacyIds, awsIds, TOP_K);
      const ok = similarity >= (1 - EPSILON);
      if (ok) passed++; else failed++;

      const label = q.type === 'multi' ? q.collections.join('+') : q.collection;
      console.log(`  ${ok ? '[OK]  ' : '[FAIL]'} [${q.type}] ${label} "${q.query.slice(0, 40)}" — overlap@${TOP_K}=${(similarity * 100).toFixed(1)}%`);
      results.push({ query: q, legacyIds, awsIds, similarity, passed: ok });
    } catch (err) {
      console.error(`  [WARN] ${q.query.slice(0, 40)}: ${err.message}`);
      failed++;
    }
  }

  console.log(`\nResults: ${passed} passed, ${failed} failed (epsilon=${EPSILON})`);

  // Write report
  const report = { timestamp: new Date().toISOString(), epsilon: EPSILON, topK: TOP_K, results, passed, failed };
  const { writeFileSync } = await import('node:fs');
  writeFileSync('search-relevance-report.json', JSON.stringify(report, null, 2));
  console.log('[OK]  Report saved to search-relevance-report.json');

  process.exit(failed > 0 ? 1 : 0);
}

main().catch(err => { console.error('[FATAL]', err.message); process.exit(1); });
