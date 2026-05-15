/**
 * verify-migration.js — Step 17: Migration Verification + Count Parity (multi-model)
 *
 * Checks count parity for every model-aware index in OpenSearch.
 * Reports per-model, per-collection counts.
 * Uploads parity report to S3 with timestamp.
 * Exits non-zero on any model-specific count mismatch.
 *
 * Usage:
 *   node scripts/verify-migration.js [--fail-fast]
 *
 * Env vars:
 *   CHROMADB_URL, NEO4J_URI, NEO4J_PASSWORD  — legacy source
 *   OPENSEARCH_ENDPOINT, NEPTUNE_ENDPOINT    — AWS target
 *   AWS_REGION, MIGRATION_BUCKET
 *
 * Requirements: 17.1, 17.2, 17.3, 17.4
 */

import { S3Client, PutObjectCommand } from '@aws-sdk/client-s3';
import { Client as OpenSearchClient } from '@opensearch-project/opensearch';
import { AwsSigv4Signer } from '@opensearch-project/opensearch/lib/aws/index-v3.js';
import { defaultProvider } from '@aws-sdk/credential-provider-node';
import neo4j from 'neo4j-driver';
import { ChromaClient } from 'chromadb';

const REGION      = process.env.AWS_REGION       || 'us-east-1';
const BUCKET      = process.env.MIGRATION_BUCKET || 'mdc-mcp-rag-migration';
const CHROMA_URL  = process.env.CHROMADB_URL     || 'http://127.0.0.1:8080';
const NEO4J_URI   = process.env.NEO4J_URI        || 'bolt://localhost:7687';
const NEO4J_PASS  = process.env.NEO4J_PASSWORD   || 'gfsworkflow2025';
const OS_ENDPOINT = process.env.OPENSEARCH_ENDPOINT || '';
const NEPTUNE_EP  = process.env.NEPTUNE_ENDPOINT    || '';
const FAIL_FAST   = process.argv.includes('--fail-fast');

// Legacy collection → base index mapping (preserved for backward compat)
const COLLECTION_TO_INDEX = {
  'code-with-context-v8-0-0':      'mdc-code-context',
  'global-workflow-docs-v8-0-0':   'mdc-workflow-docs',
  'jjobs-v8-0-0':                  'mdc-jjobs',
  'community-summaries':           'mdc-community-summaries',
  'ee2-standards-v5-0-0-enhanced': 'mdc-ee2-standards',
};

// Known model suffixes (mirrors embedding_registry.py)
const KNOWN_MODEL_SUFFIXES = ['mpnet768', 'titan1024', 'nova256', 'nova512', 'nova1024', 'nova3072'];

// ── Data source helpers ───────────────────────────────────────────────────────

async function getChromaCounts() {
  const chroma = new ChromaClient({ path: `${CHROMA_URL}/api/v2` });
  const cols = await chroma.listCollections();
  const counts = {};
  for (const c of cols) {
    if (COLLECTION_TO_INDEX[c.name]) {
      const col = await chroma.getCollection({ name: c.name });
      const meta = col.metadata || {};
      // Determine model suffix from metadata
      let modelSuffix = 'mpnet768';
      if (meta.model_profile) modelSuffix = meta.model_profile;
      else if (meta.embedding_model?.includes('titan')) modelSuffix = 'titan1024';
      const key = `${c.name}:${modelSuffix}`;
      counts[key] = await col.count();
    }
  }
  return counts;
}

async function getNeo4jCounts() {
  const driver = neo4j.driver(NEO4J_URI, neo4j.auth.basic('neo4j', NEO4J_PASS), { disableLosslessIntegers: true });
  const session = driver.session({ defaultAccessMode: neo4j.session.READ });
  try {
    const [nr, rr] = await Promise.all([
      session.run('MATCH (n) RETURN count(n) AS c'),
      session.run('MATCH ()-[r]->() RETURN count(r) AS c'),
    ]);
    return { nodes: nr.records[0].get('c'), rels: rr.records[0].get('c') };
  } finally { await session.close(); await driver.close(); }
}

async function getOpenSearchCounts() {
  if (!OS_ENDPOINT) return {};
  const os = new OpenSearchClient({
    ...AwsSigv4Signer({ region: REGION, service: 'es', getCredentials: defaultProvider() }),
    node: OS_ENDPOINT,
  });
  const counts = {};
  // Check all model-aware indices
  for (const [col, baseIndex] of Object.entries(COLLECTION_TO_INDEX)) {
    for (const suffix of KNOWN_MODEL_SUFFIXES) {
      const index = `${baseIndex}-${suffix}`;
      const key = `${col}:${suffix}`;
      try {
        const r = await os.count({ index });
        counts[key] = r.body.count;
      } catch { counts[key] = null; }
    }
  }
  return counts;
}

async function getNeptuneCounts() {
  if (!NEPTUNE_EP) return null;
  const boltUri = NEPTUNE_EP.startsWith('wss://') ? NEPTUNE_EP.replace('wss://', 'bolt+s://') : NEPTUNE_EP;
  const driver = neo4j.driver(boltUri, neo4j.auth.none(), { disableLosslessIntegers: true });
  const session = driver.session({ defaultAccessMode: neo4j.session.READ });
  try {
    const [nr, rr] = await Promise.all([
      session.run('MATCH (n) RETURN count(n) AS c'),
      session.run('MATCH ()-[r]->() RETURN count(r) AS c'),
    ]);
    return { nodes: nr.records[0].get('c'), rels: rr.records[0].get('c') };
  } finally { await session.close(); await driver.close(); }
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  console.log('[START] Migration Verification (multi-model)\n');
  const report = {
    timestamp: new Date().toISOString(),
    vectors: {},
    graph: {},
    passed: true,
  };

  // ── Vector parity (per model, per collection) ──────────────────────────────
  console.log('Vector counts (per model):');
  const [chromaCounts, osCounts] = await Promise.all([getChromaCounts(), getOpenSearchCounts()]);

  // Report on all collection+model combinations that exist in either source
  const allKeys = new Set([...Object.keys(chromaCounts), ...Object.keys(osCounts)]);
  for (const key of [...allKeys].sort()) {
    const legacy = chromaCounts[key] ?? 'N/A';
    const aws    = osCounts[key]     ?? 'N/A';
    const match  = legacy !== 'N/A' && aws !== 'N/A' && legacy === aws;
    report.vectors[key] = { legacy, aws, match };
    if (!match && legacy !== 'N/A') report.passed = false;  // only fail if legacy has data
    const status = match ? '[OK]  ' : (legacy === 'N/A' ? '[INFO]' : '[FAIL]');
    console.log(`  ${status} ${key}: legacy=${legacy}, aws=${aws}`);
    if (!match && legacy !== 'N/A' && FAIL_FAST) {
      console.error('\n[ABORT] --fail-fast');
      process.exit(1);
    }
  }

  // ── Graph parity ───────────────────────────────────────────────────────────
  console.log('\nGraph counts:');
  const [neo4jCounts, neptuneCounts] = await Promise.all([getNeo4jCounts(), getNeptuneCounts()]);

  const nodesMatch = neptuneCounts && neo4jCounts.nodes === neptuneCounts.nodes;
  const relsMatch  = neptuneCounts && neo4jCounts.rels  === neptuneCounts.rels;
  report.graph = {
    legacy: neo4jCounts,
    aws: neptuneCounts,
    nodesMatch: !!nodesMatch,
    relsMatch:  !!relsMatch,
  };
  if (!nodesMatch || !relsMatch) report.passed = false;

  console.log(`  ${nodesMatch ? '[OK]  ' : '[FAIL]'} Nodes: legacy=${neo4jCounts.nodes}, aws=${neptuneCounts?.nodes ?? 'N/A'}`);
  console.log(`  ${relsMatch  ? '[OK]  ' : '[FAIL]'} Rels:  legacy=${neo4jCounts.rels},  aws=${neptuneCounts?.rels  ?? 'N/A'}`);

  // ── Upload report ──────────────────────────────────────────────────────────
  const s3 = new S3Client({ region: REGION });
  const reportKey = `reports/verification-${Date.now()}.json`;
  await s3.send(new PutObjectCommand({
    Bucket: BUCKET,
    Key: reportKey,
    Body: JSON.stringify(report, null, 2),
    ContentType: 'application/json',
  }));
  console.log(`\n[INFO]  Report uploaded: s3://${BUCKET}/${reportKey}`);

  console.log(`\n${report.passed ? '[OK]    All counts match' : '[FAIL]  Count parity FAILED'}`);
  process.exit(report.passed ? 0 : 1);
}

main().catch(err => { console.error('[FATAL]', err.message); process.exit(1); });
