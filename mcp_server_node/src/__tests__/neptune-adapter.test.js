/**
 * Tests for apoc-transform.js and NeptuneAdapter (Step 9)
 *
 * 5.5: Unit tests for each APOC replacement + UnsupportedQueryError
 * P3:  APOC Transformation Semantic Preservation (property test)
 * P2b: Adapter Output Compatibility — NeptuneAdapter.query() output matches GraphDatabase._recordToObject()
 */

import { describe, test, expect, vi, beforeEach } from 'vitest';
import fc from 'fast-check';
import { transformApoc, UnsupportedQueryError } from '../data/adapters/apoc-transform.js';

// ---------------------------------------------------------------------------
// 5.5: Unit tests for each APOC replacement
// ---------------------------------------------------------------------------
describe('apoc-transform: unit tests', () => {

  test('apoc.path.expand → variable-length path MATCH', () => {
    const input = `CALL apoc.path.expand(n, 'CALLS>', '', 1, 3) YIELD path AS p`;
    const out = transformApoc(input);
    expect(out).toContain('MATCH p = (n)-[*1..3]->()');
    expect(out).not.toContain('apoc.');
  });

  test('apoc.algo.dijkstra (unweighted) → shortestPath()', () => {
    const input = `CALL apoc.algo.dijkstra(a, b, 'CALLS') YIELD path AS p`;
    const out = transformApoc(input);
    expect(out).toContain('shortestPath');
    expect(out).not.toContain('apoc.algo.dijkstra');
  });

  test('apoc.algo.dijkstra (weighted) → shortestPath() with warning comment', () => {
    const input = `CALL apoc.algo.dijkstra(a, b, 'CALLS', 'weight') YIELD path AS p, weight AS w`;
    const out = transformApoc(input);
    expect(out).toContain('shortestPath');
    expect(out).toContain('WARNING');
    expect(out).not.toContain('apoc.algo.dijkstra');
  });

  test('apoc.periodic.iterate → UNWIND batch pattern', () => {
    const input = `CALL apoc.periodic.iterate('MATCH (n:File) RETURN n', 'SET n.processed = true', {batchSize: 100})`;
    const out = transformApoc(input);
    expect(out).toContain('UNWIND');
    expect(out).toContain('_batch');
    expect(out).not.toContain('apoc.periodic.iterate');
  });

  test('apoc.create.node → CREATE statement', () => {
    const input = `CALL apoc.create.node(['File', 'CodeFile'], {path: '/a.py'}) YIELD node AS n`;
    const out = transformApoc(input);
    expect(out).toContain('CREATE (n:File:CodeFile');
    expect(out).not.toContain('apoc.create.node');
  });

  test('apoc.merge.node → MERGE with ON CREATE SET / ON MATCH SET', () => {
    const input = `CALL apoc.merge.node(['Function'], {name: 'foo'}, {created: true}, {updated: true}) YIELD node AS n`;
    const out = transformApoc(input);
    expect(out).toContain('MERGE (n:Function {name: \'foo\'})');
    expect(out).toContain('ON CREATE SET');
    expect(out).toContain('ON MATCH SET');
    expect(out).not.toContain('apoc.merge.node');
  });

  test('unknown APOC procedure throws UnsupportedQueryError', () => {
    const input = `CALL apoc.refactor.mergeNodes([a, b]) YIELD node`;
    expect(() => transformApoc(input)).toThrow(UnsupportedQueryError);
    expect(() => transformApoc(input)).toThrow('apoc.refactor.mergeNodes');
  });

  test('query with no APOC passes through unchanged', () => {
    const input = `MATCH (n:File) RETURN n.path AS path LIMIT 10`;
    expect(transformApoc(input)).toBe(input);
  });
});

// ---------------------------------------------------------------------------
// P3: APOC Transformation Semantic Preservation (property test)
// ---------------------------------------------------------------------------
describe('P3: APOC Transformation Semantic Preservation', () => {

  test('transformed query never contains apoc. calls', async () => {
    // Generate queries with known APOC patterns and verify output is APOC-free
    const knownPatterns = [
      `CALL apoc.path.expand(n, 'CALLS>', '', 1, 3) YIELD path AS p RETURN p`,
      `CALL apoc.create.node(['File'], {path: '/x.py'}) YIELD node AS n RETURN n`,
      `CALL apoc.merge.node(['Fn'], {name: 'f'}, {c: 1}, {u: 1}) YIELD node AS n RETURN n`,
      `CALL apoc.periodic.iterate('MATCH (n) RETURN n', 'SET n.x=1', {batchSize:10})`,
    ];

    for (const q of knownPatterns) {
      const out = transformApoc(q);
      expect(out).not.toMatch(/apoc\./i);
    }
  });

  test('property: any query without apoc. is returned unchanged', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 200 }).filter(s => !s.includes('apoc.')),
        (cypher) => {
          expect(transformApoc(cypher)).toBe(cypher);
        }
      ),
      { numRuns: 200 }
    );
  });

  test('property: UnsupportedQueryError is thrown for any unknown apoc.* call', () => {
    // Generate unknown procedure names (not in the known set)
    const known = ['apoc.path.expand', 'apoc.algo.dijkstra', 'apoc.periodic.iterate',
                   'apoc.create.node', 'apoc.merge.node'];
    fc.assert(
      fc.property(
        fc.stringMatching(/^[a-z]{3,10}\.[a-z]{3,10}$/).filter(
          s => !known.some(k => k.endsWith(s))
        ),
        (proc) => {
          const q = `CALL apoc.${proc}() YIELD result`;
          expect(() => transformApoc(q)).toThrow(UnsupportedQueryError);
        }
      ),
      { numRuns: 50 }
    );
  });
});

// ---------------------------------------------------------------------------
// P2b: NeptuneAdapter output compatibility
// ---------------------------------------------------------------------------
describe('P2b: NeptuneAdapter output compatibility', () => {
  // Mock neo4j-driver before importing NeptuneAdapter
  vi.mock('neo4j-driver', async (importOriginal) => {
    const actual = await importOriginal();
    return {
      default: {
        ...actual.default,
        driver: vi.fn(),
        auth: { none: vi.fn(() => ({})), basic: vi.fn(() => ({})) },
        session: { READ: 'READ' },
        isInt: actual.default.isInt,
      },
    };
  });

  test('query() returns plain objects with same keys as record', async () => {
    const neo4j = (await import('neo4j-driver')).default;

    const fakeRecord = {
      keys: ['name', 'count'],
      get: (k) => k === 'name' ? 'foo' : { toNumber: () => 42, low: 42, high: 0 },
    };

    neo4j.driver.mockReturnValue({
      verifyConnectivity: vi.fn(async () => {}),
      session: vi.fn(() => ({
        run: vi.fn(async () => ({ records: [fakeRecord] })),
        close: vi.fn(async () => {}),
      })),
      close: vi.fn(async () => {}),
    });

    const { NeptuneAdapter } = await import('../data/adapters/NeptuneAdapter.js');
    const adapter = new NeptuneAdapter({ endpoint: 'bolt+s://neptune.example.com:8182' });
    await adapter.connect();

    const results = await adapter.query('MATCH (n) RETURN n.name AS name, count(n) AS count');
    expect(results).toHaveLength(1);
    expect(results[0]).toHaveProperty('name', 'foo');
    // neo4j.isInt returns false for our mock object, so value passes through as-is
    expect(results[0]).toHaveProperty('count');
  });

  test('query() applies APOC transformation before execution', async () => {
    const neo4j = (await import('neo4j-driver')).default;
    let capturedCypher = '';

    neo4j.driver.mockReturnValue({
      verifyConnectivity: vi.fn(async () => {}),
      session: vi.fn(() => ({
        run: vi.fn(async (cypher) => { capturedCypher = cypher; return { records: [] }; }),
        close: vi.fn(async () => {}),
      })),
      close: vi.fn(async () => {}),
    });

    const { NeptuneAdapter } = await import('../data/adapters/NeptuneAdapter.js');
    const adapter = new NeptuneAdapter({ endpoint: 'bolt+s://neptune.example.com:8182' });
    await adapter.connect();

    await adapter.query(`CALL apoc.path.expand(n, 'CALLS>', '', 1, 3) YIELD path AS p RETURN p`);
    expect(capturedCypher).not.toContain('apoc.');
    expect(capturedCypher).toContain('MATCH p = (n)-[*1..3]->()');
  });
});
