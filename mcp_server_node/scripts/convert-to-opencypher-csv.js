#!/usr/bin/env node
/**
 * convert-to-opencypher-csv.js — Convert Neo4j JSON dump to openCypher CSV for Neptune bulk loader
 *
 * Downloads s3://mdc-mcp-rag-migration/graph/neo4j-dump.json.gz
 * Outputs nodes.csv.gz and relationships.csv.gz to s3://mdc-mcp-rag-migration/graph-csv/
 *
 * Usage: node scripts/convert-to-opencypher-csv.js [--dry-run]
 */

import { S3Client, GetObjectCommand, PutObjectCommand } from '@aws-sdk/client-s3';
import { Upload } from '@aws-sdk/lib-storage';
import { createGunzip, createGzip } from 'node:zlib';
import { PassThrough } from 'node:stream';

const REGION = process.env.AWS_REGION || 'us-east-1';
const BUCKET = process.env.MIGRATION_BUCKET || 'mdc-mcp-rag-migration';
const DRY_RUN = process.argv.includes('--dry-run');
const s3 = new S3Client({ region: REGION });

function nodeMergeId(node) {
  const p = node.properties;
  return p.id || p.path || p.name || `${node.labels[0]}_${Buffer.from(JSON.stringify(p)).toString('base64url').substring(0, 40)}`;
}

function sanitizeValue(v) {
  if (v === null || v === undefined) return '';
  if (typeof v === 'string') return v;
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  return JSON.stringify(v);
}

function csvEscape(val) {
  const s = String(val);
  if (s.includes('"') || s.includes(',') || s.includes('\n') || s.includes('\r')) {
    return '"' + s.replace(/"/g, '""') + '"';
  }
  return s;
}

function neptuneType(val) {
  if (typeof val === 'number') return Number.isInteger(val) ? 'Int' : 'Double';
  if (typeof val === 'boolean') return 'Bool';
  return 'String';
}

async function main() {
  console.log(`[START] openCypher CSV converter${DRY_RUN ? ' (dry-run)' : ''}`);

  // Download and parse dump
  console.log('[INFO]  Downloading graph dump from S3...');
  const resp = await s3.send(new GetObjectCommand({ Bucket: BUCKET, Key: 'graph/neo4j-dump.json.gz' }));
  const chunks = [];
  const gunzip = createGunzip();
  resp.Body.pipe(gunzip);
  for await (const chunk of gunzip) chunks.push(chunk);
  const dump = JSON.parse(Buffer.concat(chunks).toString());
  console.log(`[OK]    Parsed: ${dump.nodes.length} nodes, ${dump.relationships.length} rels`);

  // Build node ID map
  const nodeIdMap = new Map();
  for (const n of dump.nodes) {
    const mid = nodeMergeId(n);
    n.properties._mergeId = mid;
    if (n.properties.name) nodeIdMap.set(n.properties.name, mid);
  }

  // Collect node property keys and types
  const nodePropTypes = new Map();
  for (const n of dump.nodes) {
    for (const [k, v] of Object.entries(n.properties)) {
      if (v === null || v === undefined) continue;
      if (!nodePropTypes.has(k)) nodePropTypes.set(k, neptuneType(v));
    }
  }
  nodePropTypes.set('_mergeId', 'String');
  const nodeProps = [...nodePropTypes.keys()].sort();

  // ── Generate and upload nodes CSV ──
  console.log('[INFO]  Generating nodes CSV...');
  const nodeHeader = ['~id', '~label', ...nodeProps.map(k => `${k}:${nodePropTypes.get(k)}`)].map(csvEscape).join(',');

  if (!DRY_RUN) {
    const nodeGz = createGzip();
    const nodeUpload = new Upload({
      client: s3,
      params: { Bucket: BUCKET, Key: 'graph-csv/nodes.csv.gz', Body: nodeGz, ContentType: 'application/gzip' },
    });
    nodeGz.write(nodeHeader + '\n');
    for (const n of dump.nodes) {
      const mid = n.properties._mergeId;
      const row = [csvEscape(mid), csvEscape(n.labels[0])];
      for (const k of nodeProps) row.push(csvEscape(sanitizeValue(n.properties[k])));
      nodeGz.write(row.join(',') + '\n');
    }
    nodeGz.end();
    await nodeUpload.done();
    console.log(`[OK]    ${dump.nodes.length} node rows uploaded`);
  } else {
    console.log(`[OK]    ${dump.nodes.length} node rows (dry-run)`);
  }

  // ── Pre-filter rels ──
  let skippedRels = 0;
  let validRelCount = 0;

  // Collect rel property keys (scan first 10K for types)
  const relPropTypes = new Map();
  for (let i = 0; i < Math.min(dump.relationships.length, 10000); i++) {
    const r = dump.relationships[i];
    if (!r.props) continue;
    for (const [k, v] of Object.entries(r.props)) {
      if (v === null || v === undefined) continue;
      if (!relPropTypes.has(k)) relPropTypes.set(k, neptuneType(v));
    }
  }
  const relProps = [...relPropTypes.keys()].sort();
  const relHeader = ['~id', '~start', '~end', '~type', ...relProps.map(k => `${k}:${relPropTypes.get(k)}`)].map(csvEscape).join(',');

  // ── Stream rels CSV to S3 (avoids OOM) ──
  console.log('[INFO]  Generating relationships CSV (streaming)...');

  if (!DRY_RUN) {
    const relGz = createGzip();
    const relUpload = new Upload({
      client: s3,
      params: { Bucket: BUCKET, Key: 'graph-csv/relationships.csv.gz', Body: relGz, ContentType: 'application/gzip' },
    });
    relGz.write(relHeader + '\n');

    for (let i = 0; i < dump.relationships.length; i++) {
      const r = dump.relationships[i];
      const fromId = nodeIdMap.get(r.fromName);
      const toId = nodeIdMap.get(r.toName);
      if (!fromId || !toId) { skippedRels++; continue; }

      const row = [csvEscape(`rel_${validRelCount}`), csvEscape(fromId), csvEscape(toId), csvEscape(r.type || 'RELATES')];
      for (const k of relProps) row.push(csvEscape(sanitizeValue(r.props?.[k])));
      relGz.write(row.join(',') + '\n');
      validRelCount++;

      if (validRelCount % 500000 === 0) {
        console.log(`[INFO]  Rels: ${validRelCount} written...`);
      }
    }
    relGz.end();
    await relUpload.done();
    console.log(`[OK]    ${validRelCount} rel rows uploaded`);
  } else {
    for (const r of dump.relationships) {
      const fromId = nodeIdMap.get(r.fromName);
      const toId = nodeIdMap.get(r.toName);
      if (!fromId || !toId) { skippedRels++; continue; }
      validRelCount++;
    }
    console.log(`[OK]    ${validRelCount} rel rows (dry-run)`);
  }

  if (skippedRels > 0) console.log(`[INFO]  Skipped ${skippedRels} rels with unresolvable endpoints`);
  console.log(`[DONE]  Nodes: ${dump.nodes.length}, Rels: ${validRelCount} (${skippedRels} skipped)`);
}

main().catch(err => { console.error('[FATAL]', err.message, err.stack); process.exit(1); });
