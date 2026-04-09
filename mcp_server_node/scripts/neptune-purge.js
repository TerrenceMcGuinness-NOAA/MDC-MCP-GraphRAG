/**
 * neptune-purge.js — Batched purge of all Neptune data
 * Usage: node scripts/neptune-purge.js
 */
import { HttpRequest } from '@smithy/protocol-http';
import { SignatureV4 } from '@smithy/signature-v4';
import { defaultProvider } from '@aws-sdk/credential-provider-node';
import crypto from '@aws-crypto/sha256-js';
const { Sha256 } = crypto;
import https from 'node:https';

const HOST = 'mdc-mcp-rag-neptune.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com';
const PORT = 8182;

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

async function main() {
  let result = await neptuneQuery('MATCH (n) RETURN count(n) AS c');
  const initial = result?.results?.[0]?.c ?? 0;
  console.log(`[INFO]  Starting purge: ${initial} nodes`);

  let totalDeleted = 0;
  let round = 0;
  let deleted;
  do {
    result = await neptuneQuery('MATCH (n) WITH n LIMIT 10000 DETACH DELETE n RETURN count(n) AS deleted');
    deleted = result?.results?.[0]?.deleted ?? 0;
    totalDeleted += deleted;
    round++;
    if (deleted > 0) console.log(`[INFO]  Round ${round}: deleted ${deleted} (total: ${totalDeleted})`);
  } while (deleted > 0);

  result = await neptuneQuery('MATCH (n) RETURN count(n) AS c');
  console.log(`[OK]    Purge complete. Final node count: ${result?.results?.[0]?.c ?? 'unknown'}`);
  result = await neptuneQuery('MATCH ()-[r]->() RETURN count(r) AS c');
  console.log(`[OK]    Final rel count: ${result?.results?.[0]?.c ?? 'unknown'}`);
}

main().catch(err => { console.error('[FATAL]', err.message); process.exit(1); });
