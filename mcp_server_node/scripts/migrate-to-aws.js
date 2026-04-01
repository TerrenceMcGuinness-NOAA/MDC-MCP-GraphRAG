/**
 * migrate-to-aws.js — Step 16: Data Migration (ChromaDB → OpenSearch, Neo4j → Neptune)
 *
 * Exports legacy data to S3, then loads into AWS backends.
 * Watermarks track progress for idempotent re-execution on failure.
 *
 * Phases:
 *   1. export-vectors  — ChromaDB collections → S3 (mdc-mcp-rag-migration/vectors/)
 *   2. export-graph    — Neo4j dump → S3 (mdc-mcp-rag-migration/graph/)
 *   3. load-vectors    — S3 → OpenSearch bulk index (embeddings transferred bitwise)
 *   4. load-graph      — S3 → Neptune bulk loader
 *   5. verify          — count parity check + report
 *
 * Usage:
 *   node scripts/migrate-to-aws.js [--phase <phase>] [--dry-run]
 *
 * Env vars (legacy source):
 *   CHROMADB_URL        — default: http://127.0.0.1:8080
 *   NEO4J_URI           — default: bolt://localhost:7687
 *   NEO4J_PASSWORD      — default: gfsworkflow2025
 *
 * Env vars (AWS target):
 *   OPENSEARCH_ENDPOINT — required for load-vectors / verify
 *   NEPTUNE_ENDPOINT    — required for load-graph / verify
 *   AWS_REGION          — default: us-east-1
 *   MIGRATION_BUCKET    — default: mdc-mcp-rag-migration
 */

import { S3Client, PutObjectCommand, GetObjectCommand, HeadObjectCommand } from '@aws-sdk/client-s3';
import { Client as OpenSearchClient } from '@opensearch-project/opensearch';
import { AwsSigv4Signer } from '@opensearch-project/opensearch/lib/aws/index-v3.js';
import { defaultProvider } from '@aws-sdk/credential-provider-node';
import neo4j from 'neo4j-driver';
import { ChromaClient } from 'chromadb';
import { createWriteStream, createReadStream, mkdirSync, existsSync } from 'node:fs';
import { readFile, writeFile, unlink } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { pipeline } from 'node:stream/promises';
import { createGzip, createGunzip } from 'node:zlib';

// ── Configuration ────────────────────────────────────────────────────────────

const REGION   = process.env.AWS_REGION || 'us-east-1';
const BUCKET   = process.env.MIGRATION_BUCKET || 'mdc-mcp-rag-migration';
const CHROMA_URL = process.env.CHROMADB_URL || 'http://127.0.0.1:8080';
const NEO4J_URI  = process.env.NEO4J_URI    || 'bolt://localhost:7687';
const NEO4J_PASS = process.env.NEO4J_PASSWORD || 'gfsworkflow2025';
const OS_ENDPOINT = process.env.OPENSEARCH_ENDPOINT || '';
const NEPTUNE_EP  = process.env.NEPTUNE_ENDPOINT    || '';

const COLLECTION_TO_INDEX = {
  'code-with-context-v8-0-0':      'mdc-code-context',
  'global-workflow-docs-v8-0-0':   'mdc-workflow-docs',
  'jjobs-v8-0-0':                  'mdc-jjobs',
  'community-summaries':           'mdc-community-summaries',
  'ee2-standards-v5-0-0-enhanced': 'mdc-ee2-standards',
};

const WATERMARK_KEY = 'watermarks/migration-state.json';
const BATCH_SIZE = 500;

// ── CLI args ─────────────────────────────────────────────────────────────────

const args = process.argv.slice(2);
const phaseArg = args[args.indexOf('--phase') + 1] || 'all';
const DRY_RUN  = args.includes('--dry-run');

if (DRY_RUN) console.log('[INFO] DRY RUN — no writes to AWS');

// ── AWS clients ───────────────────────────────────────────────────────────────

const s3 = new S3Client({ region: REGION });

function makeOsClient() {
  if (!OS_ENDPOINT) throw new Error('OPENSEARCH_ENDPOINT required');
  return new OpenSearchClient({
    ...AwsSigv4Signer({ region: REGION, service: 'es', getCredentials: defaultProvider() }),
    node: OS_ENDPOINT,
  });
}

// ── Watermark helpers (idempotency) ──────────────────────────────────────────

async function loadWatermarks() {
  try {
    const resp = await s3.send(new GetObjectCommand({ Bucket: BUCKET, Key: WATERMARK_KEY }));
    const body = await resp.Body.transformToString();
    return JSON.parse(body);
  } catch {
    return {};
  }
}

async function saveWatermarks(wm) {
  if (DRY_RUN) return;
  await s3.send(new PutObjectCommand({
    Bucket: BUCKET, Key: WATERMARK_KEY,
    Body: JSON.stringify(wm, null, 2),
    ContentType: 'application/json',
  }));
}

// ── Phase 1: Export ChromaDB → S3 ────────────────────────────────────────────

async function exportVectors(wm) {
  console.log('\n[PHASE 1] Export ChromaDB → S3');
  const chroma = new ChromaClient({ path: `${CHROMA_URL}/api/v2` });
  const collections = await chroma.listCollections();
  const names = collections.map(c => c.name).filter(n => COLLECTION_TO_INDEX[n]);

  for (const name of names) {
    const s3Key = `vectors/${name}.json.gz`;
    if (wm[`export:${name}`] === 'done') {
      console.log(`[SKIP]  ${name} — already exported`);
      continue;
    }

    console.log(`[INFO]  Exporting ${name}...`);
    const col = await chroma.getCollection({ name });
    const total = await col.count();

    // Fetch all documents in batches
    const docs = [];
    let offset = 0;
    while (offset < total) {
      const batch = await col.get({
        limit: BATCH_SIZE, offset,
        include: ['documents', 'metadatas', 'embeddings'],
      });
      for (let i = 0; i < batch.ids.length; i++) {
        docs.push({
          id:        batch.ids[i],
          content:   batch.documents[i],
          metadata:  batch.metadatas[i] || {},
          embedding: batch.embeddings[i],  // 768-dim, transferred bitwise
        });
      }
      offset += BATCH_SIZE;
    }

    if (!DRY_RUN) {
      const json = JSON.stringify(docs);
      // Gzip and upload
      const tmpFile = join(tmpdir(), `${name}.json.gz`);
      await new Promise((res, rej) => {
        const gz = createGzip();
        const out = createWriteStream(tmpFile);
        gz.on('error', rej); out.on('error', rej); out.on('finish', res);
        gz.pipe(out);
        gz.end(json);
      });
      const body = await readFile(tmpFile);
      await s3.send(new PutObjectCommand({
        Bucket: BUCKET, Key: s3Key, Body: body, ContentType: 'application/gzip',
      }));
      await unlink(tmpFile);
    }

    wm[`export:${name}`] = 'done';
    wm[`export:${name}:count`] = docs.length;
    await saveWatermarks(wm);
    console.log(`[OK]    ${name} — ${docs.length} docs → s3://${BUCKET}/${s3Key}`);
  }
}

// ── Phase 2: Export Neo4j → S3 ───────────────────────────────────────────────

async function exportGraph(wm) {
  console.log('\n[PHASE 2] Export Neo4j → S3');
  if (wm['export:graph'] === 'done') {
    console.log('[SKIP]  Graph already exported');
    return;
  }

  const driver = neo4j.driver(NEO4J_URI, neo4j.auth.basic('neo4j', NEO4J_PASS), { disableLosslessIntegers: true });
  const session = driver.session({ defaultAccessMode: neo4j.session.READ });

  try {
    // Export nodes
    const nodeResult = await session.run('MATCH (n) RETURN n, labels(n) AS labels LIMIT 200000');
    const nodes = nodeResult.records.map(r => ({
      labels: r.get('labels'),
      properties: r.get('n').properties,
    }));

    // Export relationships
    const relResult = await session.run(
      'MATCH (a)-[r]->(b) RETURN id(a) AS fromId, id(b) AS toId, type(r) AS type, properties(r) AS props, a.name AS fromName, b.name AS toName LIMIT 5000000'
    );
    const rels = relResult.records.map(r => ({
      fromName: r.get('fromName'), toName: r.get('toName'),
      type: r.get('type'), props: r.get('props'),
    }));

    const dump = { nodes, relationships: rels, exportedAt: new Date().toISOString() };

    if (!DRY_RUN) {
      const json = JSON.stringify(dump);
      const tmpFile = join(tmpdir(), 'neo4j-dump.json.gz');
      await new Promise((res, rej) => {
        const gz = createGzip(); const out = createWriteStream(tmpFile);
        gz.on('error', rej); out.on('error', rej); out.on('finish', res);
        gz.pipe(out); gz.end(json);
      });
      const body = await readFile(tmpFile);
      await s3.send(new PutObjectCommand({
        Bucket: BUCKET, Key: 'graph/neo4j-dump.json.gz', Body: body, ContentType: 'application/gzip',
      }));
      await unlink(tmpFile);
    }

    wm['export:graph'] = 'done';
    wm['export:graph:nodes'] = nodes.length;
    wm['export:graph:rels'] = rels.length;
    await saveWatermarks(wm);
    console.log(`[OK]    Graph — ${nodes.length} nodes, ${rels.length} rels → s3://${BUCKET}/graph/`);
  } finally {
    await session.close();
    await driver.close();
  }
}

// ── Phase 3: Load S3 → OpenSearch ────────────────────────────────────────────

async function loadVectors(wm) {
  console.log('\n[PHASE 3] Load S3 → OpenSearch');
  const os = makeOsClient();

  for (const [collection, index] of Object.entries(COLLECTION_TO_INDEX)) {
    const s3Key = `vectors/${collection}.json.gz`;
    if (wm[`load:${collection}`] === 'done') {
      console.log(`[SKIP]  ${collection} → ${index} — already loaded`);
      continue;
    }

    // Check export exists
    try {
      await s3.send(new HeadObjectCommand({ Bucket: BUCKET, Key: s3Key }));
    } catch {
      console.log(`[SKIP]  ${collection} — no export found at s3://${BUCKET}/${s3Key}`);
      continue;
    }

    console.log(`[INFO]  Loading ${collection} → ${index}...`);

    // Download and decompress
    const resp = await s3.send(new GetObjectCommand({ Bucket: BUCKET, Key: s3Key }));
    const chunks = [];
    const gunzip = createGunzip();
    resp.Body.pipe(gunzip);
    for await (const chunk of gunzip) chunks.push(chunk);
    const docs = JSON.parse(Buffer.concat(chunks).toString());

    if (!DRY_RUN) {
      // Bulk index in batches
      let indexed = 0;
      for (let i = 0; i < docs.length; i += BATCH_SIZE) {
        const batch = docs.slice(i, i + BATCH_SIZE);
        const body = batch.flatMap(doc => [
          { index: { _index: index, _id: doc.id } },
          {
            content:         doc.content,
            embedding:       doc.embedding,   // bitwise transfer — no re-generation
            metadata:        doc.metadata,
            source_file:     doc.metadata?.source_file || doc.metadata?.filePath || '',
            chunk_id:        doc.id,
            collection_name: collection,
          },
        ]);
        const result = await os.bulk({ body });
        if (result.body.errors) {
          const failed = result.body.items.filter(i => i.index?.error).length;
          console.error(`[WARN]  ${failed} docs failed in batch ${i / BATCH_SIZE + 1}`);
        }
        indexed += batch.length;
      }
    }

    wm[`load:${collection}`] = 'done';
    wm[`load:${collection}:count`] = docs.length;
    await saveWatermarks(wm);
    console.log(`[OK]    ${collection} → ${index}: ${docs.length} docs`);
  }
}

// ── Phase 4: Load S3 → Neptune ───────────────────────────────────────────────

async function loadGraph(wm) {
  console.log('\n[PHASE 4] Load S3 → Neptune');
  if (wm['load:graph'] === 'done') {
    console.log('[SKIP]  Graph already loaded');
    return;
  }
  if (!NEPTUNE_EP) { console.log('[SKIP]  NEPTUNE_ENDPOINT not set'); return; }

  // Download dump
  let dump;
  try {
    const resp = await s3.send(new GetObjectCommand({ Bucket: BUCKET, Key: 'graph/neo4j-dump.json.gz' }));
    const chunks = []; const gunzip = createGunzip();
    resp.Body.pipe(gunzip);
    for await (const chunk of gunzip) chunks.push(chunk);
    dump = JSON.parse(Buffer.concat(chunks).toString());
  } catch (err) {
    console.log(`[SKIP]  No graph dump found: ${err.message}`);
    return;
  }

  if (!DRY_RUN) {
    const boltUri = NEPTUNE_EP.startsWith('wss://')
      ? NEPTUNE_EP.replace('wss://', 'bolt+s://')
      : NEPTUNE_EP;
    const driver = neo4j.driver(boltUri, neo4j.auth.none(), { disableLosslessIntegers: true });
    const session = driver.session({ defaultAccessMode: neo4j.session.WRITE });

    try {
      // Load nodes in batches via UNWIND
      for (let i = 0; i < dump.nodes.length; i += BATCH_SIZE) {
        const batch = dump.nodes.slice(i, i + BATCH_SIZE);
        // Group by label set for efficient MERGE
        const byLabel = {};
        for (const n of batch) {
          const key = n.labels.sort().join(':');
          (byLabel[key] = byLabel[key] || []).push(n.properties);
        }
        for (const [labelKey, props] of Object.entries(byLabel)) {
          const label = labelKey.split(':')[0];  // primary label
          await session.run(
            `UNWIND $props AS p MERGE (n:${label} {name: p.name}) ON CREATE SET n += p ON MATCH SET n += p`,
            { props }
          );
        }
      }

      // Load relationships in batches
      for (let i = 0; i < dump.relationships.length; i += BATCH_SIZE) {
        const batch = dump.relationships.slice(i, i + BATCH_SIZE);
        await session.run(
          `UNWIND $rels AS r
           MATCH (a {name: r.fromName}), (b {name: r.toName})
           MERGE (a)-[rel:\`${batch[0]?.type || 'RELATES'}\`]->(b)
           ON CREATE SET rel += r.props`,
          { rels: batch }
        );
      }
    } finally {
      await session.close();
      await driver.close();
    }
  }

  wm['load:graph'] = 'done';
  wm['load:graph:nodes'] = dump.nodes.length;
  wm['load:graph:rels'] = dump.relationships.length;
  await saveWatermarks(wm);
  console.log(`[OK]    Graph loaded: ${dump.nodes.length} nodes, ${dump.relationships.length} rels`);
}

// ── Phase 5: Verify count parity ─────────────────────────────────────────────

async function verify(wm) {
  console.log('\n[PHASE 5] Verification — count parity');
  const report = { timestamp: new Date().toISOString(), vectors: {}, graph: {}, passed: true };

  // Vector parity
  if (OS_ENDPOINT) {
    const os = makeOsClient();
    for (const [collection, index] of Object.entries(COLLECTION_TO_INDEX)) {
      const exported = wm[`export:${collection}:count`] ?? null;
      let indexed = null;
      try {
        const r = await os.count({ index });
        indexed = r.body.count;
      } catch { /* index may not exist yet */ }
      const match = exported !== null && indexed !== null && exported === indexed;
      report.vectors[collection] = { exported, indexed, match };
      if (!match) report.passed = false;
      console.log(`  ${match ? '[OK]' : '[FAIL]'} ${collection}: exported=${exported}, indexed=${indexed}`);
    }
  }

  // Graph parity
  const exportedNodes = wm['export:graph:nodes'] ?? null;
  const exportedRels  = wm['export:graph:rels']  ?? null;
  let neptuneNodes = null, neptuneRels = null;

  if (NEPTUNE_EP && !DRY_RUN) {
    const boltUri = NEPTUNE_EP.startsWith('wss://') ? NEPTUNE_EP.replace('wss://', 'bolt+s://') : NEPTUNE_EP;
    const driver = neo4j.driver(boltUri, neo4j.auth.none(), { disableLosslessIntegers: true });
    const session = driver.session({ defaultAccessMode: neo4j.session.READ });
    try {
      const nr = await session.run('MATCH (n) RETURN count(n) AS c');
      const rr = await session.run('MATCH ()-[r]->() RETURN count(r) AS c');
      neptuneNodes = nr.records[0]?.get('c') ?? 0;
      neptuneRels  = rr.records[0]?.get('c') ?? 0;
    } finally { await session.close(); await driver.close(); }
  }

  const nodesMatch = exportedNodes !== null && neptuneNodes !== null && exportedNodes === neptuneNodes;
  const relsMatch  = exportedRels  !== null && neptuneRels  !== null && exportedRels  === neptuneRels;
  report.graph = { exportedNodes, neptuneNodes, nodesMatch, exportedRels, neptuneRels, relsMatch };
  if (!nodesMatch || !relsMatch) report.passed = false;

  console.log(`  ${nodesMatch ? '[OK]' : '[FAIL]'} Nodes: exported=${exportedNodes}, neptune=${neptuneNodes}`);
  console.log(`  ${relsMatch  ? '[OK]' : '[FAIL]'} Rels:  exported=${exportedRels},  neptune=${neptuneRels}`);

  // Upload report
  if (!DRY_RUN) {
    await s3.send(new PutObjectCommand({
      Bucket: BUCKET, Key: `reports/migration-report-${Date.now()}.json`,
      Body: JSON.stringify(report, null, 2), ContentType: 'application/json',
    }));
  }

  console.log(`\n${report.passed ? '[OK]    Migration verified' : '[FAIL]  Count parity check FAILED'}`);
  return report;
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  console.log(`[START] MDC MCP RAG Migration — phase=${phaseArg}${DRY_RUN ? ' (dry-run)' : ''}`);
  const wm = await loadWatermarks();

  const run = p => phaseArg === 'all' || phaseArg === p;

  if (run('export-vectors')) await exportVectors(wm);
  if (run('export-graph'))   await exportGraph(wm);
  if (run('load-vectors'))   await loadVectors(wm);
  if (run('load-graph'))     await loadGraph(wm);
  if (run('verify'))         await verify(wm);

  console.log('\n[DONE]  Migration complete');
}

main().catch(err => { console.error('[FATAL]', err.message, err.stack); process.exit(1); });
