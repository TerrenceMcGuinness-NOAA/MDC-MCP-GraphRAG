/**
 * verify-migration.js — Step 17: Migration Verification + Count Parity
 *
 * Standalone verification: compares counts between legacy (ChromaDB/Neo4j)
 * and AWS (OpenSearch/Neptune), generates a parity report.
 *
 * Usage:
 *   node scripts/verify-migration.js [--fail-fast]
 *
 * Env vars:
 *   CHROMADB_URL, NEO4J_URI, NEO4J_PASSWORD  — legacy source
 *   OPENSEARCH_ENDPOINT, NEPTUNE_ENDPOINT    — AWS target
 *   AWS_REGION, MIGRATION_BUCKET
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

const COLLECTION_TO_INDEX = {
  'code-with-context-v8-0-0':      'mdc-code-context',
  'global-workflow-docs-v8-0-0':   'mdc-workflow-docs',
  'jjobs-v8-0-0':                  'mdc-jjobs',
  'community-summaries':           'mdc-community-summaries',
  'ee2-standards-v5-0-0-enhanced': 'mdc-ee2-standards',
};

async function getChromaCounts() {
  const chroma = new ChromaClient({ path: `${CHROMA_URL}/api/v2` });
  const cols = await chroma.listCollections();
  const counts = {};
  for (const c of cols) {
    if (COLLECTION_TO_INDEX[c.name]) {
      const col = await chroma.getCollection({ name: c.name });
      counts[c.name] = await col.count();
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
  for (const index of Object.values(COLLECTION_TO_INDEX)) {
    try {
      const r = await os.count({ index });
      counts[index] = r.body.count;
    } catch { counts[index] = null; }
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

async function main() {
  console.log('[START] Migration Verification\n');
  const report = { timestamp: new Date().toISOString(), vectors: {}, graph: {}, passed: true };

  // ── Vector parity ──────────────────────────────────────────────────────────
  console.log('Vector counts:');
  const [chromaCounts, osCounts] = await Promise.all([getChromaCounts(), getOpenSearchCounts()]);

  for (const [col, index] of Object.entries(COLLECTION_TO_INDEX)) {
    const legacy = chromaCounts[col] ?? 'N/A';
    const aws    = osCounts[index]   ?? 'N/A';
    const match  = legacy !== 'N/A' && aws !== 'N/A' && legacy === aws;
    report.vectors[col] = { legacy, aws, match };
    if (!match) report.passed = false;
    console.log(`  ${match ? '[OK]  ' : '[FAIL]'} ${col}: legacy=${legacy}, aws=${aws}`);
    if (!match && FAIL_FAST) { console.error('\n[ABORT] --fail-fast'); process.exit(1); }
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
  await s3.send(new PutObjectCommand({
    Bucket: BUCKET,
    Key: `reports/verification-${Date.now()}.json`,
    Body: JSON.stringify(report, null, 2),
    ContentType: 'application/json',
  }));

  console.log(`\n${report.passed ? '[OK]    All counts match' : '[FAIL]  Count parity FAILED'}`);
  process.exit(report.passed ? 0 : 1);
}

main().catch(err => { console.error('[FATAL]', err.message); process.exit(1); });
