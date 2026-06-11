/**
 * create-opensearch-indices.js — Step 15: OpenSearch Index Definitions
 *
 * Creates MDC MCP RAG indices with k-NN mappings, model-aware dimensions,
 * and BM25 content field. Idempotent: skips indices that already exist.
 *
 * Usage:
 *   node scripts/create-opensearch-indices.js [--model <short_name|all>] [--prefix <string>]
 *
 * Flags:
 *   --model   short model name (e.g. titan1024) or 'all'. Default: mpnet768.
 *   --prefix  optional string prepended to every generated index name,
 *             enabling tenant-prefixed index creation (e.g. --prefix gw_v17_
 *             produces gw_v17_mdc-code-context-titan1024). Default: '' (none).
 *
 * Env vars:
 *   OPENSEARCH_ENDPOINT  — required
 *   AWS_REGION           — default: us-east-1
 *
 * Requirements: 10.1, 10.2, 15.1-15.6, 26.1
 */

import { fileURLToPath } from 'node:url';
import { Client } from '@opensearch-project/opensearch';
import { AwsSigv4Signer } from '@opensearch-project/opensearch/lib/aws/index-v3.js';
import { defaultProvider } from '@aws-sdk/credential-provider-node';

const REGION   = process.env.AWS_REGION || 'us-east-1';
const ENDPOINT = process.env.OPENSEARCH_ENDPOINT;

// ── Model registry (mirrors embedding_registry.py) ───────────────────────────

export const MODEL_PROFILES = {
  mpnet768:  { dimensions: 768,  provider: 'local'   },
  titan1024: { dimensions: 1024, provider: 'bedrock' },
  nova256:   { dimensions: 256,  provider: 'bedrock' },
  nova512:   { dimensions: 512,  provider: 'bedrock' },
  nova1024:  { dimensions: 1024, provider: 'bedrock' },
  nova3072:  { dimensions: 3072, provider: 'bedrock' },
};

// Base index names (one per content domain)
export const BASE_INDICES = [
  'mdc-code-context',
  'mdc-workflow-docs',
  'mdc-jjobs',
  'mdc-community-summaries',
  'mdc-ee2-standards',
];

// ── CLI parsing helpers ────────────────────────────────────────────────────

export function parseModel(args) {
  const i = args.indexOf('--model');
  return i !== -1 ? (args[i + 1] || 'mpnet768') : 'mpnet768';
}

export function parsePrefix(args) {
  const i = args.indexOf('--prefix');
  return i !== -1 ? (args[i + 1] || '') : '';
}

export function resolveModels(arg) {
  if (arg === 'all') return Object.keys(MODEL_PROFILES);
  if (!MODEL_PROFILES[arg]) {
    console.error(`[ERROR] Unknown model '${arg}'. Available: ${Object.keys(MODEL_PROFILES).join(', ')}`);
    process.exit(1);
  }
  return [arg];
}

// Index name construction: optional tenant prefix + base + model.
export function buildIndexName(prefix, base, modelName) {
  return `${prefix}${base}-${modelName}`;
}

// ── Index mapping factory ─────────────────────────────────────────────────────

export function indexBody(dimensions) {
  return {
    settings: {
      index: {
        knn: true,
        'knn.algo_param.ef_search': 512,
        number_of_shards: 2,
        number_of_replicas: 1,
      },
    },
    mappings: {
      properties: {
        embedding: {
          type: 'knn_vector',
          dimension: dimensions,
          method: {
            name: 'hnsw',
            engine: 'nmslib',
            space_type: 'cosinesimil',
            parameters: { ef_construction: 512, m: 16 },
          },
        },
        content:         { type: 'text' },   // BM25 searchable (Req 26.1)
        metadata:        { type: 'object', dynamic: true },
        source_file:     { type: 'keyword' },
        chunk_id:        { type: 'keyword' },
        collection_name: { type: 'keyword' },
        model_profile:   { type: 'keyword' }, // tracks which model generated embeddings
      },
    },
  };
}

// ── Index ensure loop (idempotent, client-injectable for tests) ───────────────

export async function ensureIndices(client, { models, prefix = '' }) {
  let created = 0, skipped = 0, errors = 0;

  for (const modelName of models) {
    const { dimensions } = MODEL_PROFILES[modelName];
    for (const base of BASE_INDICES) {
      // Model-aware, optionally tenant-prefixed index name
      // (e.g. gw_v17_mdc-code-context-titan1024)
      const index = buildIndexName(prefix, base, modelName);
      try {
        const exists = await client.indices.exists({ index });
        if (exists.body) {
          console.log(`[SKIP]  ${index} — already exists`);
          skipped++;
          continue;
        }
        await client.indices.create({ index, body: indexBody(dimensions) });
        console.log(`[OK]    ${index} — created (${dimensions}-dim)`);
        created++;
      } catch (err) {
        console.error(`[ERROR] ${index} — ${err.message}`);
        errors++;
      }
    }
  }

  return { created, skipped, errors };
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  if (!ENDPOINT) {
    console.error('[ERROR] OPENSEARCH_ENDPOINT is required');
    process.exit(1);
  }

  const args = process.argv.slice(2);
  const selectedModels = resolveModels(parseModel(args));
  const prefix = parsePrefix(args);

  const client = new Client({
    ...AwsSigv4Signer({ region: REGION, service: 'es', getCredentials: defaultProvider() }),
    node: ENDPOINT,
  });

  console.log(`[INFO] Models: ${selectedModels.join(', ')}`);
  console.log(`[INFO] Prefix: ${prefix || '(none)'}`);
  console.log(`[INFO] Base indices: ${BASE_INDICES.length}`);
  console.log(`[INFO] Total indices to ensure: ${selectedModels.length * BASE_INDICES.length}\n`);

  const { created, skipped, errors } = await ensureIndices(client, {
    models: selectedModels,
    prefix,
  });

  console.log(`\nDone: ${created} created, ${skipped} skipped, ${errors} errors`);
  if (errors > 0) process.exit(1);
}

// Run only when invoked directly (not when imported by tests).
const isMain = process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1];
if (isMain) {
  main().catch(err => { console.error('[FATAL]', err.message); process.exit(1); });
}
