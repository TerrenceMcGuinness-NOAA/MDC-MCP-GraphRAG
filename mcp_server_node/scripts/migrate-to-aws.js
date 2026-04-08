/**
 * migrate-to-aws.js — Step 16: Data Migration (ChromaDB → OpenSearch, Neo4j → Neptune)
 *
 * Exports legacy data to S3, then loads into AWS backends.
 * Watermarks track progress for idempotent re-execution on failure.
 * Model-aware: reads model metadata from ChromaDB, uses model-aware S3 keys and indices.
 *
 * Phases:
 *   1. export-vectors  — ChromaDB collections → S3 (vectors/{collection}-{model}.json.gz)
 *   2. export-graph    — Neo4j dump → S3 (mdc-mcp-rag-migration/graph/)
 *   3. load-vectors    — S3 → OpenSearch model-aware indices
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
 *
 * Requirements: 14.1-14.6, 16.1-16.4, 18.1-18.7, 19.1-19.5
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
import { createInterface } from 'node:readline';
import { HttpRequest } from '@smithy/protocol-http';
import { SignatureV4 } from '@smithy/signature-v4';
import crypto from '@aws-crypto/sha256-js';
const { Sha256 } = crypto;

// ── Configuration ────────────────────────────────────────────────────────────

const REGION   = process.env.AWS_REGION || 'us-east-1';
const BUCKET   = process.env.MIGRATION_BUCKET || 'mdc-mcp-rag-migration';
const CHROMA_URL = process.env.CHROMADB_URL || 'http://127.0.0.1:8080';
const NEO4J_URI  = process.env.NEO4J_URI    || 'bolt://localhost:7687';
const NEO4J_PASS = process.env.NEO4J_PASSWORD || 'gfsworkflow2025';
const OS_ENDPOINT = process.env.OPENSEARCH_ENDPOINT || '';
const NEPTUNE_EP  = process.env.NEPTUNE_ENDPOINT    || '';

// Legacy collection → base OpenSearch index (preserved for backward compat, Req 14.5)
const COLLECTION_TO_INDEX = {
  'code-with-context-v8-0-0':      'mdc-code-context',
  'global-workflow-docs-v8-0-0':   'mdc-workflow-docs',
  'jjobs-v8-0-0':                  'mdc-jjobs',
  'community-summaries':           'mdc-community-summaries',
  'ee2-standards-v5-0-0-enhanced': 'mdc-ee2-standards',
};

// Known model suffixes (mirrors embedding_registry.py)
const KNOWN_MODEL_SUFFIXES = ['mpnet768', 'titan1024', 'nova256', 'nova512', 'nova1024', 'nova3072'];

const WATERMARK_KEY = 'watermarks/migration-state.json';
const BATCH_SIZE = 500;

// ── Neptune IAM auth helper ──────────────────────────────────────────────────

/** Sanitize properties for Neptune: convert non-simple values to JSON strings */
function sanitizeProps(props) {
  if (!props) return {};
  const out = {};
  for (const [k, v] of Object.entries(props)) {
    if (v === null || v === undefined) continue;
    if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') {
      out[k] = v;
    } else {
      out[k] = JSON.stringify(v);
    }
  }
  return out;
}

async function makeNeptuneDriver(accessMode) {
  const epUrl = new URL(NEPTUNE_EP.replace('wss://', 'https://').replace('bolt+s://', 'https://'));
  const host = epUrl.hostname;
  const port = parseInt(epUrl.port) || 8182;
  const req = new HttpRequest({
    method: 'GET', protocol: 'bolt', hostname: host, port,
    path: '/opencypher', headers: { host: `${host}:${port}` },
  });
  const signer = new SignatureV4({
    credentials: defaultProvider(), region: REGION,
    service: 'neptune-db', sha256: Sha256,
  });
  const signed = await signer.sign(req, { unsignableHeaders: new Set(['x-amz-content-sha256']) });
  const creds = JSON.stringify({
    Authorization: signed.headers['authorization'],
    HttpMethod: signed.method,
    'X-Amz-Date': signed.headers['x-amz-date'],
    Host: signed.headers['host'],
    'X-Amz-Security-Token': signed.headers['x-amz-security-token'],
  });
  const authToken = { scheme: 'basic', realm: 'realm', principal: 'username', credentials: creds };
  const driver = neo4j.driver(`bolt://${host}:${port}`, authToken, {
    encrypted: 'ENCRYPTION_ON', trust: 'TRUST_SYSTEM_CA_SIGNED_CERTIFICATES',
    disableLosslessIntegers: true,
  });
  const session = driver.session({ defaultAccessMode: accessMode });
  return { driver, session };
}

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

// ── Model-aware helpers ───────────────────────────────────────────────────────

/**
 * Extract model short name from ChromaDB collection metadata.
 * Falls back to 'mpnet768' for legacy collections without model metadata.
 * Requirements: 14.1, 14.2
 */
function extractModelFromMetadata(metadata) {
  if (!metadata) return 'mpnet768';
  // Check explicit model_profile field
  if (metadata.model_profile) return metadata.model_profile;
  // Check embedding_model field (legacy format)
  if (metadata.embedding_model) {
    if (metadata.embedding_model.includes('mpnet')) return 'mpnet768';
    if (metadata.embedding_model.includes('titan')) return 'titan1024';
  }
  return 'mpnet768';
}

/**
 * Map collection name + model to an OpenSearch index name.
 * Model-aware: {base-index}-{model-suffix}
 * Legacy fallback: COLLECTION_TO_INDEX mapping
 * Requirements: 14.3, 14.5
 */
function collectionToModelIndex(collectionName, modelSuffix) {
  const baseIndex = COLLECTION_TO_INDEX[collectionName];
  if (!baseIndex) return `${collectionName}-${modelSuffix}`;
  return `${baseIndex}-${modelSuffix}`;
}

/**
 * Build S3 key for a collection+model export.
 * Requirements: 14.2, 18.1
 */
function vectorS3Key(collectionName, modelSuffix) {
  return `vectors/${collectionName}-${modelSuffix}.json.gz`;
}

/**
 * Build watermark key for a collection+model combination.
 * Requirements: 18.5, 18.6
 */
function wmKey(phase, collectionName, modelSuffix) {
  return `${phase}:${collectionName}:${modelSuffix}`;
}

// ── Phase 1: Export ChromaDB → S3 (model-aware) ───────────────────────────────

async function exportVectors(wm) {
  console.log('\n[PHASE 1] Export ChromaDB → S3 (model-aware)');
  const chroma = new ChromaClient({ path: `${CHROMA_URL}/api/v2` });
  const collections = await chroma.listCollections();
  const names = collections.map(c => c.name).filter(n => COLLECTION_TO_INDEX[n]);

  for (const name of names) {
    // Get collection metadata to determine model
    const col = await chroma.getCollection({ name });
    const colMeta = col.metadata || {};
    const modelSuffix = extractModelFromMetadata(colMeta);
    const s3Key = vectorS3Key(name, modelSuffix);
    const wk = wmKey('export', name, modelSuffix);

    if (wm[wk] === 'done') {
      console.log(`[SKIP]  ${name} (${modelSuffix}) — already exported`);
      continue;
    }

    console.log(`[INFO]  Exporting ${name} (model=${modelSuffix})...`);
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
          id:           batch.ids[i],
          content:      batch.documents[i],
          metadata:     { ...batch.metadatas[i] || {}, model_profile: modelSuffix },
          embedding:    batch.embeddings[i],
          model_profile: modelSuffix,
        });
      }
      offset += BATCH_SIZE;
    }

    if (!DRY_RUN) {
      // Stream NDJSON (one JSON object per line) through gzip to avoid
      // hitting Node.js string length limits on large collections.
      const tmpFile = join(tmpdir(), `${name}-${modelSuffix}.json.gz`);
      await new Promise((res, rej) => {
        const gz = createGzip();
        const out = createWriteStream(tmpFile);
        gz.on('error', rej); out.on('error', rej); out.on('finish', res);
        gz.pipe(out);
        for (let i = 0; i < docs.length; i++) {
          const line = JSON.stringify(docs[i]);
          gz.write(i === 0 ? line : '\n' + line);
        }
        gz.end();
      });
      const body = await readFile(tmpFile);
      await s3.send(new PutObjectCommand({
        Bucket: BUCKET, Key: s3Key, Body: body, ContentType: 'application/gzip',
      }));
      await unlink(tmpFile);
    }

    wm[wk] = 'done';
    wm[`${wk}:count`] = docs.length;
    wm[`${wk}:model`] = modelSuffix;
    await saveWatermarks(wm);
    console.log(`[OK]    ${name} (${modelSuffix}) — ${docs.length} docs → s3://${BUCKET}/${s3Key}`);
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

// ── Phase 3: Load S3 → OpenSearch (model-aware) ──────────────────────────────

async function loadVectors(wm) {
  console.log('\n[PHASE 3] Load S3 → OpenSearch (model-aware)');
  const os = makeOsClient();

  // Find all exported collection+model combinations from watermarks
  const exportKeys = Object.keys(wm).filter(k => k.startsWith('export:') && wm[k] === 'done' && !k.includes(':count') && !k.includes(':model') && k !== 'export:graph');

  if (exportKeys.length === 0) {
    // Fallback: try legacy collection names with default model
    for (const collection of Object.keys(COLLECTION_TO_INDEX)) {
      exportKeys.push(`export:${collection}:mpnet768`);
    }
  }

  for (const wk of exportKeys) {
    // Parse watermark key: "export:{collection}:{model}"
    const parts = wk.split(':');
    if (parts.length < 3) continue;
    const modelSuffix = parts[parts.length - 1];
    const collectionName = parts.slice(1, -1).join(':');

    if (!KNOWN_MODEL_SUFFIXES.includes(modelSuffix)) continue;

    const s3Key = vectorS3Key(collectionName, modelSuffix);
    const targetIndex = collectionToModelIndex(collectionName, modelSuffix);
    const loadWk = wmKey('load', collectionName, modelSuffix);

    if (wm[loadWk] === 'done') {
      console.log(`[SKIP]  ${collectionName} (${modelSuffix}) → ${targetIndex} — already loaded`);
      continue;
    }

    // Check export exists in S3
    try {
      await s3.send(new HeadObjectCommand({ Bucket: BUCKET, Key: s3Key }));
    } catch {
      console.log(`[SKIP]  ${collectionName} (${modelSuffix}) — no export at s3://${BUCKET}/${s3Key}`);
      continue;
    }

    console.log(`[INFO]  Loading ${collectionName} (${modelSuffix}) → ${targetIndex}...`);

    // Download and decompress via NDJSON streaming (avoids string length limit)
    const resp = await s3.send(new GetObjectCommand({ Bucket: BUCKET, Key: s3Key }));
    const gunzip = createGunzip();
    resp.Body.pipe(gunzip);
    const rl = createInterface({ input: gunzip, crlfDelay: Infinity });

    if (!DRY_RUN) {
      let batch = [];
      let totalIndexed = 0;
      for await (const line of rl) {
        if (!line.trim()) continue;
        const doc = JSON.parse(line);
        batch.push(doc);
        if (batch.length >= BATCH_SIZE) {
          const body = batch.flatMap(d => [
            { index: { _index: targetIndex, _id: d.id } },
            {
              content:         d.content,
              embedding:       d.embedding,
              metadata:        d.metadata,
              source_file:     d.metadata?.source_file || d.metadata?.filePath || '',
              chunk_id:        d.id,
              collection_name: collectionName,
              model_profile:   modelSuffix,
            },
          ]);
          const result = await os.bulk({ body });
          if (result.body.errors) {
            const failed = result.body.items.filter(i => i.index?.error).length;
            console.error(`[WARN]  ${failed} docs failed in batch ${Math.floor(totalIndexed / BATCH_SIZE) + 1}`);
          }
          totalIndexed += batch.length;
          batch = [];
        }
      }
      // Flush remaining
      if (batch.length > 0) {
        const body = batch.flatMap(d => [
          { index: { _index: targetIndex, _id: d.id } },
          {
            content:         d.content,
            embedding:       d.embedding,
            metadata:        d.metadata,
            source_file:     d.metadata?.source_file || d.metadata?.filePath || '',
            chunk_id:        d.id,
            collection_name: collectionName,
            model_profile:   modelSuffix,
          },
        ]);
        const result = await os.bulk({ body });
        if (result.body.errors) {
          const failed = result.body.items.filter(i => i.index?.error).length;
          console.error(`[WARN]  ${failed} docs failed in final batch`);
        }
        totalIndexed += batch.length;
      }
      wm[loadWk] = 'done';
      wm[`${loadWk}:count`] = totalIndexed;
      await saveWatermarks(wm);
      console.log(`[OK]    ${collectionName} (${modelSuffix}) → ${targetIndex}: ${totalIndexed} docs`);
    } else {
      let count = 0;
      for await (const line of rl) { if (line.trim()) count++; }
      wm[loadWk] = 'done';
      wm[`${loadWk}:count`] = count;
      await saveWatermarks(wm);
      console.log(`[OK]    ${collectionName} (${modelSuffix}) → ${targetIndex}: ${count} docs`);
    }
  }
}

// ── Phase 4: Load S3 → Neptune ───────────────────────────────────────────────

const RETRIABLE_ERRORS = ['Operation terminated', 'conflicting concurrent', 'please retry', 'internal error'];

async function runWithRetry(sessionFn, query, params, maxRetries = 5) {
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await sessionFn().run(query, params);
    } catch (err) {
      const retriable = RETRIABLE_ERRORS.some(s => err.message.includes(s));
      if (!retriable || attempt === maxRetries) throw err;
      const delay = Math.min(500 * Math.pow(2, attempt), 30000);
      console.warn(`[RETRY] Attempt ${attempt + 1}/${maxRetries}, wait ${delay}ms: ${err.message.substring(0, 80)}`);
      await new Promise(r => setTimeout(r, delay));
    }
  }
}

/** Derive a stable unique merge key for a node */
function nodeMergeId(node) {
  const p = node.properties;
  return p.id || p.path || p.name || `${node.labels[0]}_${Buffer.from(JSON.stringify(p)).toString('base64url').substring(0, 40)}`;
}

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

  // Pre-process: assign stable _mergeId to every node, build lookup for rels
  const nodeIdMap = new Map(); // name → _mergeId (for rel resolution)
  for (const n of dump.nodes) {
    const mid = nodeMergeId(n);
    n.properties._mergeId = mid;
    if (n.properties.name) nodeIdMap.set(n.properties.name, mid);
  }

  // Pre-filter rels: resolve fromName/toName to _mergeId, skip unresolvable
  const validRels = [];
  let skippedRels = 0;
  for (const r of dump.relationships) {
    const fromId = nodeIdMap.get(r.fromName);
    const toId = nodeIdMap.get(r.toName);
    if (fromId && toId) {
      validRels.push({ ...r, fromId, toId });
    } else {
      skippedRels++;
    }
  }
  if (skippedRels > 0) console.log(`[INFO]  Skipping ${skippedRels} rels with unresolvable endpoints`);

  if (!DRY_RUN) {
    const NEPTUNE_BATCH = 100;  // AWS recommends 100-200 per request
    const PARALLELISM = 4;      // 2x vCPU for db.r6g.large
    const REFRESH_MS = 4 * 60 * 1000;
    const WM_INTERVAL = 2000;   // Save watermark every N items

    // Parallel writer pool
    class WriterPool {
      constructor(n) { this.n = n; this.workers = []; this.lastRefresh = 0; }
      async init() {
        for (let i = 0; i < this.n; i++) this.workers.push(await makeNeptuneDriver(neo4j.session.WRITE));
        this.lastRefresh = Date.now();
      }
      session(i) { return this.workers[i % this.n].session; }
      sessionFn(i) { return () => this.workers[i % this.n].session; }
      async refreshAll() {
        for (const w of this.workers) { try { await w.session.close(); await w.driver.close(); } catch {} }
        this.workers = [];
        for (let i = 0; i < this.n; i++) this.workers.push(await makeNeptuneDriver(neo4j.session.WRITE));
        this.lastRefresh = Date.now();
        console.log(`[INFO]  Refreshed ${this.n} Neptune sessions`);
      }
      async refreshIfNeeded() { if (Date.now() - this.lastRefresh > REFRESH_MS) await this.refreshAll(); }
      async closeAll() { for (const w of this.workers) { try { await w.session.close(); await w.driver.close(); } catch {} } }
    }

    const pool = new WriterPool(PARALLELISM);
    await pool.init();

    try {
      // ── Load nodes ──
      const nodeStart = wm['load:graph:nodeProgress'] || 0;
      console.log(`[INFO]  Loading nodes: ${dump.nodes.length} total, resuming from ${nodeStart} (batch=${NEPTUNE_BATCH}, writers=${PARALLELISM})`);

      for (let i = nodeStart; i < dump.nodes.length; i += NEPTUNE_BATCH * PARALLELISM) {
        await pool.refreshIfNeeded();

        // Fan out batches across parallel writers (serialize within each worker)
        const workerTasks = [];
        for (let w = 0; w < PARALLELISM; w++) {
          const batchStart = i + w * NEPTUNE_BATCH;
          if (batchStart >= dump.nodes.length) break;
          const batch = dump.nodes.slice(batchStart, Math.min(batchStart + NEPTUNE_BATCH, dump.nodes.length));

          // Group by label for efficient MERGE
          const byLabel = {};
          for (const n of batch) {
            const label = n.labels[0];
            (byLabel[label] = byLabel[label] || []).push(sanitizeProps(n.properties));
          }

          workerTasks.push((async () => {
            for (const [label, props] of Object.entries(byLabel)) {
              await runWithRetry(pool.sessionFn(w),
                `UNWIND $props AS p MERGE (n:\`${label}\` {_mergeId: p._mergeId}) ON CREATE SET n += p ON MATCH SET n += p`,
                { props }
              ).catch(err => console.error(`[ERROR] Nodes batch ${batchStart} label=${label}: ${err.message.substring(0, 100)}`));
            }
          })());
        }
        await Promise.all(workerTasks);

        // Progress watermark + logging
        const progress = Math.min(i + NEPTUNE_BATCH * PARALLELISM, dump.nodes.length);
        if (progress - (wm['load:graph:nodeProgress'] || 0) >= WM_INTERVAL) {
          wm['load:graph:nodeProgress'] = progress;
          await saveWatermarks(wm);
        }
        if (progress % 10000 < NEPTUNE_BATCH * PARALLELISM) {
          const pct = ((progress / dump.nodes.length) * 100).toFixed(1);
          console.log(`[INFO]  Nodes: ${progress}/${dump.nodes.length} (${pct}%)`);
        }
      }
      console.log(`[OK]    All ${dump.nodes.length} nodes loaded`);

      // ── Load relationships ──
      const relStart = wm['load:graph:relProgress'] || 0;
      console.log(`[INFO]  Loading rels: ${validRels.length} valid, resuming from ${relStart} (batch=${NEPTUNE_BATCH}, writers=${PARALLELISM})`);

      // Refresh pool before starting rels (may have been a while)
      await pool.refreshAll();

      for (let i = relStart; i < validRels.length; i += NEPTUNE_BATCH * PARALLELISM) {
        await pool.refreshIfNeeded();

        const workerTasks = [];
        for (let w = 0; w < PARALLELISM; w++) {
          const batchStart = i + w * NEPTUNE_BATCH;
          if (batchStart >= validRels.length) break;
          const batch = validRels.slice(batchStart, Math.min(batchStart + NEPTUNE_BATCH, validRels.length));

          // Group by type
          const byType = {};
          for (const r of batch) { (byType[r.type || 'RELATES'] = byType[r.type || 'RELATES'] || []).push(r); }

          workerTasks.push((async () => {
            for (const [relType, rels] of Object.entries(byType)) {
              const sanitized = rels.map(r => ({ fromId: r.fromId, toId: r.toId, props: sanitizeProps(r.props) }));
              await runWithRetry(pool.sessionFn(w),
                `UNWIND $rels AS r
                 MATCH (a {_mergeId: r.fromId}), (b {_mergeId: r.toId})
                 MERGE (a)-[rel:\`${relType}\`]->(b)
                 ON CREATE SET rel += r.props`,
                { rels: sanitized }
              ).catch(err => console.error(`[ERROR] Rels batch ${batchStart} type=${relType}: ${err.message.substring(0, 100)}`));
            }
          })());
        }
        await Promise.all(workerTasks);

        const progress = Math.min(i + NEPTUNE_BATCH * PARALLELISM, validRels.length);
        if (progress - (wm['load:graph:relProgress'] || 0) >= WM_INTERVAL) {
          wm['load:graph:relProgress'] = progress;
          await saveWatermarks(wm);
        }
        if (progress % 100000 < NEPTUNE_BATCH * PARALLELISM) {
          const pct = ((progress / validRels.length) * 100).toFixed(1);
          console.log(`[INFO]  Rels: ${progress}/${validRels.length} (${pct}%)`);
        }
      }
      console.log(`[OK]    All ${validRels.length} rels loaded (${skippedRels} skipped)`);

    } finally {
      await pool.closeAll();
    }
  }

  wm['load:graph'] = 'done';
  wm['load:graph:nodes'] = dump.nodes.length;
  wm['load:graph:rels'] = dump.relationships.length;
  wm['load:graph:relsLoaded'] = dump.relationships.length - skippedRels;
  await saveWatermarks(wm);
  console.log(`[OK]    Graph loaded: ${dump.nodes.length} nodes, ${dump.relationships.length} rels`);
}

// ── Phase 5: Verify count parity (model-aware) ───────────────────────────────

async function verify(wm) {
  console.log('\n[PHASE 5] Verification — count parity (model-aware)');
  const report = { timestamp: new Date().toISOString(), vectors: {}, graph: {}, passed: true };

  // Vector parity — check each collection+model combination
  if (OS_ENDPOINT) {
    const os = makeOsClient();
    const exportKeys = Object.keys(wm).filter(k =>
      k.startsWith('export:') && wm[k] === 'done' &&
      !k.includes(':count') && !k.includes(':model') && k !== 'export:graph'
    );

    for (const wk of exportKeys) {
      const parts = wk.split(':');
      if (parts.length < 3) continue;
      const modelSuffix = parts[parts.length - 1];
      const collectionName = parts.slice(1, -1).join(':');
      if (!KNOWN_MODEL_SUFFIXES.includes(modelSuffix)) continue;

      const targetIndex = collectionToModelIndex(collectionName, modelSuffix);
      const exported = wm[`${wk}:count`] ?? null;
      let indexed = null;
      try {
        const r = await os.count({ index: targetIndex });
        indexed = r.body.count;
      } catch { /* index may not exist yet */ }
      const match = exported !== null && indexed !== null && exported === indexed;
      const key = `${collectionName}:${modelSuffix}`;
      report.vectors[key] = { exported, indexed, index: targetIndex, match };
      if (!match) report.passed = false;
      console.log(`  ${match ? '[OK]' : '[FAIL]'} ${key} → ${targetIndex}: exported=${exported}, indexed=${indexed}`);
    }
  }

  // Graph parity
  const exportedNodes = wm['export:graph:nodes'] ?? null;
  const exportedRels  = wm['export:graph:rels']  ?? null;
  let neptuneNodes = null, neptuneRels = null;

  if (NEPTUNE_EP && !DRY_RUN) {
    const { driver, session } = await makeNeptuneDriver(neo4j.session.READ);
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
