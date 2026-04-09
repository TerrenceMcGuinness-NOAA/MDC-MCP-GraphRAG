#!/usr/bin/env node
/**
 * neptune-bulk-load.js — Invoke Neptune bulk loader API
 *
 * Usage:
 *   node scripts/neptune-bulk-load.js nodes     # Load nodes.csv.gz
 *   node scripts/neptune-bulk-load.js rels      # Load relationships.csv.gz
 *   node scripts/neptune-bulk-load.js status <loadId>  # Check status
 */
import { HttpRequest } from '@smithy/protocol-http';
import { SignatureV4 } from '@smithy/signature-v4';
import { defaultProvider } from '@aws-sdk/credential-provider-node';
import crypto from '@aws-crypto/sha256-js';
const { Sha256 } = crypto;
import https from 'node:https';

const HOST = 'mdc-mcp-rag-neptune.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com';
const PORT = 8182;
const ROLE_ARN = 'arn:aws:iam::903050880929:role/service-role/mdc-mcp-rag-neptune-s3-loader';
const BUCKET = process.env.MIGRATION_BUCKET || 'mdc-mcp-rag-migration';

async function neptuneHttp(method, path, body) {
  const bodyStr = body ? JSON.stringify(body) : '';
  const req = new HttpRequest({
    method, protocol: 'https:', hostname: HOST, port: PORT, path,
    headers: {
      host: `${HOST}:${PORT}`,
      'Content-Type': 'application/json',
      ...(bodyStr ? { 'Content-Length': String(Buffer.byteLength(bodyStr)) } : {}),
    },
    ...(bodyStr ? { body: bodyStr } : {}),
  });
  const signer = new SignatureV4({
    credentials: defaultProvider(), region: 'us-east-1',
    service: 'neptune-db', sha256: Sha256,
  });
  const signed = await signer.sign(req);
  return new Promise((resolve, reject) => {
    const r = https.request({
      hostname: HOST, port: PORT, path, method,
      headers: signed.headers, rejectUnauthorized: true,
    }, res => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); } catch { resolve({ raw: data }); }
      });
    });
    r.on('error', reject);
    if (bodyStr) r.write(bodyStr);
    r.end();
  });
}

async function neptuneQuery(query) {
  const body = 'query=' + encodeURIComponent(query);
  const req = new HttpRequest({
    method: 'POST', protocol: 'https:', hostname: HOST, port: PORT,
    path: '/opencypher',
    headers: {
      host: `${HOST}:${PORT}`,
      'Content-Type': 'application/x-www-form-urlencoded',
      'Content-Length': String(Buffer.byteLength(body)),
    },
    body,
  });
  const signer = new SignatureV4({
    credentials: defaultProvider(), region: 'us-east-1',
    service: 'neptune-db', sha256: Sha256,
  });
  const signed = await signer.sign(req);
  return new Promise((resolve, reject) => {
    const r = https.request({
      hostname: HOST, port: PORT, path: '/opencypher', method: 'POST',
      headers: signed.headers, rejectUnauthorized: true,
    }, res => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); } catch { resolve({ raw: data }); }
      });
    });
    r.on('error', reject);
    r.write(body);
    r.end();
  });
}

async function startLoad(s3Key) {
  console.log(`[INFO]  Starting bulk load: s3://${BUCKET}/${s3Key}`);
  const result = await neptuneHttp('POST', '/loader', {
    source: `s3://${BUCKET}/${s3Key}`,
    format: 'opencypher',
    iamRoleArn: ROLE_ARN,
    region: 'us-east-1',
    failOnError: 'TRUE',
    parallelism: 'OVERSUBSCRIBE',
    updateSingleCardinalityProperties: 'TRUE',
  });
  console.log('[INFO]  Loader response:', JSON.stringify(result, null, 2));
  return result?.payload?.loadId;
}

async function pollStatus(loadId) {
  console.log(`[INFO]  Polling loader status: ${loadId}`);
  let status;
  do {
    await new Promise(r => setTimeout(r, 5000));
    const result = await neptuneHttp('GET', `/loader/${loadId}?details=true&errors=true`, null);
    status = result?.payload?.overallStatus?.status;
    const totalRecords = result?.payload?.overallStatus?.totalRecords ?? '?';
    const totalDuplicates = result?.payload?.overallStatus?.totalDuplicates ?? '?';
    const totalTimeSpent = result?.payload?.overallStatus?.totalTimeSpent ?? '?';
    console.log(`[INFO]  Status: ${status}, records: ${totalRecords}, dupes: ${totalDuplicates}, time: ${totalTimeSpent}s`);

    if (status === 'LOAD_FAILED' || status === 'LOAD_CANCELLED_BY_USER') {
      console.error('[ERROR] Load failed:', JSON.stringify(result, null, 2));
      return status;
    }
  } while (status !== 'LOAD_COMPLETED');
  return status;
}

async function main() {
  const cmd = process.argv[2];

  if (cmd === 'nodes') {
    const loadId = await startLoad('graph-csv/nodes.csv.gz');
    if (!loadId) { console.error('[ERROR] No loadId returned'); process.exit(1); }
    const status = await pollStatus(loadId);
    if (status === 'LOAD_COMPLETED') {
      const result = await neptuneQuery('MATCH (n) RETURN count(n) AS c');
      console.log(`[OK]    Node count: ${result?.results?.[0]?.c ?? 'unknown'}`);
    }
  } else if (cmd === 'rels') {
    const loadId = await startLoad('graph-csv/relationships.csv.gz');
    if (!loadId) { console.error('[ERROR] No loadId returned'); process.exit(1); }
    const status = await pollStatus(loadId);
    if (status === 'LOAD_COMPLETED') {
      const result = await neptuneQuery('MATCH ()-[r]->() RETURN count(r) AS c');
      console.log(`[OK]    Rel count: ${result?.results?.[0]?.c ?? 'unknown'}`);
    }
  } else if (cmd === 'status') {
    const loadId = process.argv[3];
    if (!loadId) { console.error('Usage: neptune-bulk-load.js status <loadId>'); process.exit(1); }
    const result = await neptuneHttp('GET', `/loader/${loadId}?details=true&errors=true`, null);
    console.log(JSON.stringify(result, null, 2));
  } else {
    console.error('Usage: neptune-bulk-load.js <nodes|rels|status> [loadId]');
    process.exit(1);
  }
}

main().catch(err => { console.error('[FATAL]', err.message, err.stack); process.exit(1); });
