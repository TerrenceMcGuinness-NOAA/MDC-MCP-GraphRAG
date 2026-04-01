/**
 * create-opensearch-indices.js — Step 15: OpenSearch Index Definitions
 *
 * Creates the 5 MDC MCP RAG indices with k-NN mappings (768-dim, nmslib, cosinesimil, hnsw).
 * Idempotent: skips indices that already exist.
 *
 * Usage:
 *   node scripts/create-opensearch-indices.js
 *
 * Env vars:
 *   OPENSEARCH_ENDPOINT  — required
 *   AWS_REGION           — default: us-east-1
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

// 5 indices — matches COLLECTION_TO_INDEX in OpenSearchAdapter.js
const INDICES = [
  'mdc-code-context',
  'mdc-workflow-docs',
  'mdc-jjobs',
  'mdc-community-summaries',
  'mdc-ee2-standards',
];

// Shared mapping for all 5 indices (Requirements 17.1, 17.2)
function indexBody() {
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
          dimension: 768,
          method: {
            name: 'hnsw',
            engine: 'nmslib',
            space_type: 'cosinesimil',
            parameters: { ef_construction: 512, m: 16 },
          },
        },
        content:         { type: 'text' },
        metadata:        { type: 'object', dynamic: true },
        source_file:     { type: 'keyword' },
        chunk_id:        { type: 'keyword' },
        collection_name: { type: 'keyword' },
      },
    },
  };
}

async function main() {
  const client = new Client({
    ...AwsSigv4Signer({ region: REGION, service: 'es', getCredentials: defaultProvider() }),
    node: ENDPOINT,
  });

  let created = 0, skipped = 0;

  for (const index of INDICES) {
    try {
      const exists = await client.indices.exists({ index });
      if (exists.body) {
        console.log(`[SKIP]  ${index} — already exists`);
        skipped++;
        continue;
      }
      await client.indices.create({ index, body: indexBody() });
      console.log(`[OK]    ${index} — created`);
      created++;
    } catch (err) {
      console.error(`[ERROR] ${index} — ${err.message}`);
      process.exit(1);
    }
  }

  console.log(`\nDone: ${created} created, ${skipped} skipped`);
}

main().catch(err => { console.error('[FATAL]', err.message); process.exit(1); });
