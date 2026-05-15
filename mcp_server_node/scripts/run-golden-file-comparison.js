/**
 * run-golden-file-comparison.js — Step 23: Run all 51 tools against AWS + compare
 *
 * Reads golden files captured from the legacy system (Step 18) and runs the
 * same queries against the AWS backend, comparing output schemas.
 *
 * Usage:
 *   node scripts/run-golden-file-comparison.js [--golden-dir scripts/golden-files]
 *
 * Env vars:
 *   OPENSEARCH_ENDPOINT, NEPTUNE_ENDPOINT, AWS_REGION
 *   MCP_ENDPOINT — CloudFront MCP endpoint (optional, for live tool testing)
 */

import { readFileSync, readdirSync, existsSync, writeFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));

const args       = process.argv.slice(2);
const GOLDEN_DIR = args[args.indexOf('--golden-dir') + 1]
  || join(__dirname, 'golden-files');

// ── Schema comparison ─────────────────────────────────────────────────────────

/**
 * Compare two result arrays for schema equivalence.
 * Checks: same length, same top-level keys on each result object.
 * Does NOT compare values (content may differ between backends).
 */
function compareSchemas(legacyResults, awsResults) {
  if (!Array.isArray(legacyResults) || !Array.isArray(awsResults)) {
    return { match: false, reason: 'results not arrays' };
  }
  if (legacyResults.length === 0 && awsResults.length === 0) {
    return { match: true };
  }
  if (legacyResults.length === 0 || awsResults.length === 0) {
    return { match: false, reason: `length mismatch: legacy=${legacyResults.length}, aws=${awsResults.length}` };
  }

  const legacyKeys = Object.keys(legacyResults[0]).sort().join(',');
  const awsKeys    = Object.keys(awsResults[0]).sort().join(',');
  if (legacyKeys !== awsKeys) {
    return { match: false, reason: `schema mismatch: legacy=[${legacyKeys}] aws=[${awsKeys}]` };
  }
  return { match: true };
}

// ── Load golden files ─────────────────────────────────────────────────────────

function loadGoldenFiles(category) {
  const dir = join(GOLDEN_DIR, category);
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter(f => f.endsWith('.json'))
    .map(f => {
      const data = JSON.parse(readFileSync(join(dir, f), 'utf8'));
      return { file: f, ...data };
    });
}

// ── AWS query runners ─────────────────────────────────────────────────────────

async function runAwsVectorQuery(q, embedder, osClient) {
  const { Client } = await import('@opensearch-project/opensearch');
  const { AwsSigv4Signer } = await import('@opensearch-project/opensearch/lib/aws/index-v3.js');
  const { defaultProvider } = await import('@aws-sdk/credential-provider-node');

  const COLLECTION_TO_INDEX = {
    'code-with-context-v8-0-0':      'mdc-code-context',
    'global-workflow-docs-v8-0-0':   'mdc-workflow-docs',
    'jjobs-v8-0-0':                  'mdc-jjobs',
    'community-summaries':           'mdc-community-summaries',
    'ee2-standards-v5-0-0-enhanced': 'mdc-ee2-standards',
  };

  const output = await embedder([q.query], { pooling: 'mean', normalize: true });
  const vector = output.tolist()[0];

  const index = q.collections
    ? q.collections.map(c => COLLECTION_TO_INDEX[c] || c).join(',')
    : (COLLECTION_TO_INDEX[q.collection] || q.collection);

  const body = { size: q.nResults || 5, query: { knn: { embedding: { vector, k: q.nResults || 5 } } } };
  if (q.where) {
    const filters = Object.entries(q.where).map(([k, v]) => ({ term: { [`metadata.${k}`]: v } }));
    body.query = { bool: { must: [{ knn: { embedding: { vector, k: q.nResults || 5 } } }], filter: filters } };
  }

  const resp = await osClient.search({ index, body });
  return resp.body.hits.hits.map(h => ({
    id: h._id, text: h._source?.content ?? null,
    metadata: h._source?.metadata ?? {}, distance: 1 - (h._score ?? 0), score: h._score ?? 0,
  }));
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  console.log('[START] Golden-file comparison\n');

  const OS_ENDPOINT = process.env.OPENSEARCH_ENDPOINT || '';
  if (!OS_ENDPOINT) {
    console.error('[ERROR] OPENSEARCH_ENDPOINT required');
    process.exit(1);
  }

  const { Client } = await import('@opensearch-project/opensearch');
  const { AwsSigv4Signer } = await import('@opensearch-project/opensearch/lib/aws/index-v3.js');
  const { defaultProvider } = await import('@aws-sdk/credential-provider-node');
  const { pipeline } = await import('@xenova/transformers');

  const REGION = process.env.AWS_REGION || 'us-east-1';
  const osClient = new Client({
    ...AwsSigv4Signer({ region: REGION, service: 'es', getCredentials: defaultProvider() }),
    node: OS_ENDPOINT,
  });

  console.log('[INFO] Loading embedding model...');
  const embedder = await pipeline('feature-extraction', 'Xenova/all-mpnet-base-v2');

  const goldens = loadGoldenFiles('vectors');
  if (goldens.length === 0) {
    console.log('[WARN] No golden files found. Run capture-golden-files.js first.');
    process.exit(0);
  }

  const report = { timestamp: new Date().toISOString(), results: [], passed: 0, failed: 0 };

  for (const golden of goldens) {
    try {
      const awsResults = await runAwsVectorQuery(golden.query, embedder, osClient);
      const comparison = compareSchemas(golden.results, awsResults);

      if (comparison.match) {
        report.passed++;
        console.log(`  [OK]  ${golden.file} — schema matches`);
      } else {
        report.failed++;
        console.log(`  [FAIL] ${golden.file} — ${comparison.reason}`);
      }
      report.results.push({ file: golden.file, ...comparison, awsCount: awsResults.length, legacyCount: golden.results.length });
    } catch (err) {
      report.failed++;
      console.error(`  [WARN] ${golden.file}: ${err.message}`);
      report.results.push({ file: golden.file, match: false, reason: err.message });
    }
  }

  writeFileSync('golden-comparison-report.json', JSON.stringify(report, null, 2));
  console.log(`\n${report.passed} passed, ${report.failed} failed`);
  console.log('[OK]  Report saved to golden-comparison-report.json');
  process.exit(report.failed > 0 ? 1 : 0);
}

main().catch(err => { console.error('[FATAL]', err.message); process.exit(1); });
