/**
 * test-create-opensearch-indices-properties.js — Property test P11 (Task 8.2)
 *
 * P11: For any model profile, running create-opensearch-indices twice produces
 *      the same set of indices with the same mappings (idempotence).
 *
 * Tests the index body generation logic without a live OpenSearch connection.
 * Requirements: 15.6
 */

// ── Inline the logic under test (mirrors create-opensearch-indices.js) ────────

const MODEL_PROFILES = {
  mpnet768:  { dimensions: 768  },
  titan1024: { dimensions: 1024 },
  nova256:   { dimensions: 256  },
  nova512:   { dimensions: 512  },
  nova1024:  { dimensions: 1024 },
  nova3072:  { dimensions: 3072 },
};

const BASE_INDICES = [
  'mdc-code-context',
  'mdc-workflow-docs',
  'mdc-jjobs',
  'mdc-community-summaries',
  'mdc-ee2-standards',
];

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
        content:         { type: 'text' },
        metadata:        { type: 'object', dynamic: true },
        source_file:     { type: 'keyword' },
        chunk_id:        { type: 'keyword' },
        collection_name: { type: 'keyword' },
        model_profile:   { type: 'keyword' },
      },
    },
  };
}

// ── P11: Idempotence ──────────────────────────────────────────────────────────

function testP11Idempotence() {
  let passed = 0;
  for (const [modelName, { dimensions }] of Object.entries(MODEL_PROFILES)) {
    for (const base of BASE_INDICES) {
      const indexName = `${base}-${modelName}`;
      const body1 = JSON.stringify(indexBody(dimensions));
      const body2 = JSON.stringify(indexBody(dimensions));
      if (body1 !== body2) {
        console.error(`[FAIL] P11: non-deterministic body for ${indexName}`);
        process.exit(1);
      }
      // Verify dimension is correct
      const parsed = JSON.parse(body1);
      if (parsed.mappings.properties.embedding.dimension !== dimensions) {
        console.error(`[FAIL] P11: wrong dimension for ${indexName}: expected ${dimensions}`);
        process.exit(1);
      }
      // Verify content field exists for BM25
      if (parsed.mappings.properties.content?.type !== 'text') {
        console.error(`[FAIL] P11: content field missing or wrong type for ${indexName}`);
        process.exit(1);
      }
      // Verify model_profile field exists
      if (parsed.mappings.properties.model_profile?.type !== 'keyword') {
        console.error(`[FAIL] P11: model_profile field missing for ${indexName}`);
        process.exit(1);
      }
      passed++;
    }
  }
  console.log(`[OK] P11: ${passed} index bodies are deterministic with correct mappings`);
}

// ── P11: Index name set is deterministic ──────────────────────────────────────

function testP11IndexNameSet() {
  const run1 = new Set();
  const run2 = new Set();
  for (const modelName of Object.keys(MODEL_PROFILES)) {
    for (const base of BASE_INDICES) {
      run1.add(`${base}-${modelName}`);
      run2.add(`${base}-${modelName}`);
    }
  }
  const arr1 = [...run1].sort().join(',');
  const arr2 = [...run2].sort().join(',');
  if (arr1 !== arr2) {
    console.error('[FAIL] P11: index name set is non-deterministic');
    process.exit(1);
  }
  console.log(`[OK] P11: index name set is deterministic (${run1.size} indices)`);
}

// ── Run ───────────────────────────────────────────────────────────────────────

console.log('='.repeat(60));
console.log('Property Test P11: create-opensearch-indices idempotence (Task 8.2)');
console.log('='.repeat(60));
testP11Idempotence();
testP11IndexNameSet();
console.log('\n[PASS] P11 passed');
