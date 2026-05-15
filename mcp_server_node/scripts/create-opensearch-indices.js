/**
 * create-opensearch-indices.js — Step 15: OpenSearch Index Definitions
 *
 * Creates MDC MCP RAG indices with k-NN mappings, model-aware dimensions,
 * and BM25 content field. Idempotent: skips indices that already exist.
 *
 * Usage:
 *   node scripts/create-opensearch-indices.js [--model <short_name|all>]
 *
 * Env vars:
 *   OPENSEARCH_ENDPOINT  — required
 *   AWS_REGION           — default: us-east-1
 *
 * Requirements: 10.1, 10.2, 15.1-15.6, 26.1
 */

import { Client } from '@opensearch-project/opensearch';
import { AwsSigv4Signer } from '@opensearch-project/opensearch/lib/aws/index-v3.js';
import { defaultProvider } from '@aws-sdk/credential-provider-node';

const REGION   = process.env.AWS_REGION || 'us-east-1';
const ENDPOINT = process.env.OPENSEARCH_ENDPOINT;

if (!ENDPOINT) {
  console.error('[ERROR] OPENSEARCH_ENDPOINT is required');
  process.exit(1);
}

// ── Model registry (mirrors embedding_registry.py) ───────────────────────────

const MODEL_PROFILES = {
  mpnet768:  { dimensions: 768,  provider: 'local'   },
  titan1024: { dimensions: 1024, provider: 'bedrock' },
  nova256:   { dimensions: 256,  provider: 'bedrock' },
  nova512:   { dimensions: 512,  provider: 'bedrock' },
  nova1024:  { dimensions: 1024, provider: 'bedrock' },
  nova3072:  { dimensions: 3072, provider: 'bedrock' },
};

// Base index names (one per content domain)
const BASE_INDICES = [
  'mdc-code-context',
  'mdc-workflow-docs',
  'mdc-jjobs',
  'mdc-community-summaries',
  'mdc-ee2-standards',
];

// ── CLI args ─────────────────────────────────────────────────────────────────

const args = process.argv.slice(2);
const modelArg = args[args.indexOf('--model') + 1] || 'mpnet768';

function resolveModels(arg) {
  if (arg === 'all') return Object.keys(MODEL_PROFILES);
  if (!MODEL_PROFILES[arg]) {
    console.error(`[ERROR] Unknown model '${arg}'. Available: ${Object.keys(MODEL_PROFILES).join(', ')}`);
    process.exit(1);
  }
  return [arg];
}

const selectedModels = resolveModels(modelArg);

// ── Index mapping factory ─────────────────────────────────────────────────────

function indexBody(dimensions) {
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

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  const client = new Client({
    ...AwsSigv4Signer({ region: REGION, service: 'es', getCredentials: defaultProvider() }),
    node: ENDPOINT,
  });

  console.log(`[INFO] Models: ${selectedModels.join(', ')}`);
  console.log(`[INFO] Base indices: ${BASE_INDICES.length}`);
  console.log(`[INFO] Total indices to ensure: ${selectedModels.length * BASE_INDICES.length}\n`);

  let created = 0, skipped = 0, errors = 0;

  for (const modelName of selectedModels) {
    const { dimensions } = MODEL_PROFILES[modelName];
    for (const base of BASE_INDICES) {
      // Model-aware index name (e.g. mdc-code-context-mpnet768)
      const index = `${base}-${modelName}`;
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

  console.log(`\nDone: ${created} created, ${skipped} skipped, ${errors} errors`);
  if (errors > 0) process.exit(1);
}

main().catch(err => { console.error('[FATAL]', err.message); process.exit(1); });
