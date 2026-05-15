/**
 * Property Tests for OpenSearchAdapter (Step 7)
 *
 * P7:  Score Normalization — all cosine similarity scores in [0, 1]
 * P2a: Adapter Output Compatibility — output structure matches VectorDatabase._formatQueryResults()
 */

import { describe, test, expect, vi, beforeEach } from 'vitest';
import fc from 'fast-check';

vi.mock('@opensearch-project/opensearch', () => ({ Client: vi.fn() }));
vi.mock('@opensearch-project/opensearch/lib/aws/index-v3.js', () => ({
  AwsSigv4Signer: vi.fn(() => ({})),
}));
vi.mock('@aws-sdk/credential-provider-node', () => ({
  defaultProvider: vi.fn(() => () => Promise.resolve({ accessKeyId: 'x', secretAccessKey: 'y' })),
}));
vi.mock('@xenova/transformers', () => ({
  pipeline: vi.fn(() => Promise.resolve(
    async (texts) => ({ tolist: () => texts.map(() => Array(768).fill(0.1)) })
  )),
}));

import { Client } from '@opensearch-project/opensearch';
import { OpenSearchAdapter } from '../data/adapters/OpenSearchAdapter.js';

function mockClientWith(hits) {
  Client.mockImplementation(() => ({
    search: vi.fn(async () => ({ body: { hits: { hits } } })),
    cluster: { health: vi.fn(async () => ({ body: { status: 'green' } })) },
    cat: { indices: vi.fn(async () => ({ body: [] })) },
    count: vi.fn(async () => ({ body: { count: 0 } })),
  }));
}

async function freshAdapter(hits) {
  mockClientWith(hits);
  const adapter = new OpenSearchAdapter({ endpoint: 'https://os.example.com', region: 'us-east-1' });
  await adapter.connect();
  return adapter;
}

// ---------------------------------------------------------------------------
// P7: Score Normalization
// ---------------------------------------------------------------------------
describe('P7: Score Normalization', () => {
  test('all scores from query() are in [0, 1] for any raw _score values', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.array(fc.float({ min: 0, max: 2, noNaN: true }), { minLength: 1, maxLength: 20 }),
        async (rawScores) => {
          const hits = rawScores.map((s, i) => ({
            _id: `doc-${i}`, _score: s,
            _source: { content: 'text', metadata: {} },
          }));
          const adapter = await freshAdapter(hits);
          const results = await adapter.query('code-with-context-v8-0-0', 'test');
          for (const r of results) {
            expect(r.score).toBeGreaterThanOrEqual(0);
            expect(r.score).toBeLessThanOrEqual(1);
          }
        }
      ),
      { numRuns: 30 }
    );
  });

  test('distance = 1 - score for all results', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.array(fc.float({ min: 0, max: 1, noNaN: true }), { minLength: 1, maxLength: 10 }),
        async (rawScores) => {
          const hits = rawScores.map((s, i) => ({
            _id: `doc-${i}`, _score: s,
            _source: { content: 'text', metadata: {} },
          }));
          const adapter = await freshAdapter(hits);
          const results = await adapter.query('mdc-code-context', 'test');
          for (const r of results) {
            expect(r.distance).toBeCloseTo(1 - r.score, 10);
          }
        }
      ),
      { numRuns: 20 }
    );
  });
});

// ---------------------------------------------------------------------------
// P2a: Adapter Output Compatibility
// ---------------------------------------------------------------------------
describe('P2a: Adapter Output Compatibility', () => {
  test('query() output has same shape as VectorDatabase._formatQueryResults()', async () => {
    const hits = [
      { _id: 'id1', _score: 0.9, _source: { content: 'hello world', metadata: { file: 'a.py' } } },
      { _id: 'id2', _score: 0.7, _source: { content: 'foo bar',     metadata: {} } },
    ];
    const adapter = await freshAdapter(hits);
    const results = await adapter.query('global-workflow-docs-v8-0-0', 'query');

    expect(results).toHaveLength(2);
    for (const r of results) {
      expect(r).toHaveProperty('id');
      expect(r).toHaveProperty('text');
      expect(r).toHaveProperty('metadata');
      expect(r).toHaveProperty('distance');
      expect(r).toHaveProperty('score');
      expect(typeof r.id).toBe('string');
      expect(typeof r.score).toBe('number');
      expect(typeof r.distance).toBe('number');
      expect(typeof r.metadata).toBe('object');
    }
  });

  test('multiCollectionQuery() adds collection field and returns top-N by score', async () => {
    let call = 0;
    Client.mockImplementation(() => ({
      search: vi.fn(async () => {
        call++;
        const s = call % 2 === 1 ? 0.95 : 0.8;
        return { body: { hits: { hits: [
          { _id: `h${call}a`, _score: s,       _source: { content: 'A', metadata: {} } },
          { _id: `h${call}b`, _score: s - 0.4, _source: { content: 'B', metadata: {} } },
        ] } } };
      }),
      cluster: { health: vi.fn(async () => ({ body: { status: 'green' } })) },
      cat: { indices: vi.fn(async () => ({ body: [] })) },
    }));

    const adapter = new OpenSearchAdapter({ endpoint: 'https://os.example.com' });
    await adapter.connect();

    const results = await adapter.multiCollectionQuery(
      ['code-with-context-v8-0-0', 'global-workflow-docs-v8-0-0'],
      'test',
      { nResults: 3 }
    );

    expect(results.length).toBeLessThanOrEqual(3);
    for (let i = 1; i < results.length; i++) {
      expect(results[i - 1].score).toBeGreaterThanOrEqual(results[i].score);
    }
    for (const r of results) {
      expect(r).toHaveProperty('collection');
    }
  });

  test('_buildFilter translates where clauses correctly', async () => {
    const adapter = await freshAdapter([]);
    expect(adapter._buildFilter({ file_type: 'python' }))
      .toEqual([{ term: { 'metadata.file_type': 'python' } }]);
    expect(adapter._buildFilter({ lang: { $in: ['py', 'sh'] } }))
      .toEqual([{ terms: { 'metadata.lang': ['py', 'sh'] } }]);
    expect(adapter._buildFilter({ score: { $gte: 0.5, $lte: 1.0 } }))
      .toEqual([
        { range: { 'metadata.score': { gte: 0.5 } } },
        { range: { 'metadata.score': { lte: 1.0 } } },
      ]);
  });

  test('collection name mapping: known names map to mdc-* indices', async () => {
    const adapter = await freshAdapter([]);
    expect(adapter._toIndex('code-with-context-v8-0-0')).toBe('mdc-code-context');
    expect(adapter._toIndex('global-workflow-docs-v8-0-0')).toBe('mdc-workflow-docs');
    expect(adapter._toIndex('jjobs-v8-0-0')).toBe('mdc-jjobs');
    expect(adapter._toIndex('unknown-collection')).toBe('unknown-collection');
  });
});
