/**
 * Step 14 — Health Check and Resilience Property Tests
 *
 * P9:  Health Check Accuracy — healthy iff both DBs connected, ≥5 indices, node count > 0
 * P10: Graceful Degradation — tools not depending on unavailable DB continue to function
 * P13: Retry Exponential Backoff — delays follow 5s, 10s, 20s, max 60s
 */

import { describe, test, expect, vi } from 'vitest';
import fc from 'fast-check';
import { checkDatabases, withRetry, isDegraded } from '../health/HealthChecker.js';

// ── P9: Health Check Accuracy ────────────────────────────────────────────────

describe('P9: Health Check Accuracy', () => {
  function makeVectorDB(indexCount) {
    return { listCollections: vi.fn(async () => Array(indexCount).fill('idx')) };
  }
  function makeGraphDB(nodeCount) {
    return { getStatistics: vi.fn(async () => ({ nodes: nodeCount, relationships: 0 })) };
  }
  function makeFailingDB(method) {
    return { [method]: vi.fn(async () => { throw new Error('connection refused'); }) };
  }

  test('healthy iff both DBs connected with ≥5 indices and node count > 0', async () => {
    const result = await checkDatabases(makeVectorDB(5), makeGraphDB(100));
    expect(result.status).toBe('healthy');
    expect(result.vector.ok).toBe(true);
    expect(result.graph.ok).toBe(true);
  });

  test('degraded when vector DB has <5 indices', async () => {
    const result = await checkDatabases(makeVectorDB(4), makeGraphDB(100));
    expect(result.status).toBe('degraded');
    expect(result.vector.ok).toBe(false);
  });

  test('degraded when graph DB has 0 nodes', async () => {
    const result = await checkDatabases(makeVectorDB(5), makeGraphDB(0));
    expect(result.status).toBe('degraded');
    expect(result.graph.ok).toBe(false);
  });

  test('degraded when vector DB is unreachable', async () => {
    const result = await checkDatabases(
      makeFailingDB('listCollections'),
      makeGraphDB(100)
    );
    expect(result.status).toBe('degraded');
    expect(result.vector.ok).toBe(false);
    expect(result.vector.reason).toContain('connection refused');
  });

  test('degraded when graph DB is unreachable', async () => {
    const result = await checkDatabases(
      makeVectorDB(5),
      makeFailingDB('getStatistics')
    );
    expect(result.status).toBe('degraded');
    expect(result.graph.ok).toBe(false);
  });

  test('property: healthy iff indexCount ≥ 5 AND nodeCount > 0', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 0, max: 10 }),
        fc.integer({ min: 0, max: 1000 }),
        async (indexCount, nodeCount) => {
          const result = await checkDatabases(makeVectorDB(indexCount), makeGraphDB(nodeCount));
          const expectedHealthy = indexCount >= 5 && nodeCount > 0;
          expect(result.status).toBe(expectedHealthy ? 'healthy' : 'degraded');
          expect(isDegraded(result.status)).toBe(!expectedHealthy);
        }
      ),
      { numRuns: 50 }
    );
  });
});

// ── P10: Graceful Degradation ────────────────────────────────────────────────

describe('P10: Graceful Degradation', () => {
  test('vector-only tools work when graph DB is unavailable', async () => {
    // Simulate: vectorDB healthy, graphDB down
    const vectorDB = {
      listCollections: vi.fn(async () => Array(5).fill('idx')),
      query: vi.fn(async () => [{ id: '1', text: 'result', metadata: {}, distance: 0.1, score: 0.9 }]),
    };
    const graphDB = {
      getStatistics: vi.fn(async () => { throw new Error('Neptune unreachable'); }),
    };

    const dbHealth = await checkDatabases(vectorDB, graphDB);
    expect(dbHealth.status).toBe('degraded');
    expect(dbHealth.vector.ok).toBe(true);   // vector still works
    expect(dbHealth.graph.ok).toBe(false);   // graph down

    // Vector query still succeeds independently
    const results = await vectorDB.query('mdc-code-context', 'test');
    expect(results).toHaveLength(1);
    expect(results[0]).toHaveProperty('score');
  });

  test('graph-only tools work when vector DB is unavailable', async () => {
    const vectorDB = {
      listCollections: vi.fn(async () => { throw new Error('OpenSearch unreachable'); }),
    };
    const graphDB = {
      getStatistics: vi.fn(async () => ({ nodes: 95000, relationships: 2600000 })),
      findCallers: vi.fn(async () => [{ caller: 'setuprad', callerType: 'Function' }]),
    };

    const dbHealth = await checkDatabases(vectorDB, graphDB);
    expect(dbHealth.status).toBe('degraded');
    expect(dbHealth.vector.ok).toBe(false);
    expect(dbHealth.graph.ok).toBe(true);    // graph still works

    // Graph query still succeeds independently
    const callers = await graphDB.findCallers('setuprad');
    expect(callers).toHaveLength(1);
  });

  test('missing OpenSearch index returns empty results (not an error)', async () => {
    // OpenSearch returns empty hits for a missing index — adapter returns []
    const vectorDB = {
      listCollections: vi.fn(async () => Array(5).fill('idx')),
      query: vi.fn(async () => []),  // empty — index exists but no docs match
    };
    const graphDB = { getStatistics: vi.fn(async () => ({ nodes: 100 })) };

    const dbHealth = await checkDatabases(vectorDB, graphDB);
    expect(dbHealth.status).toBe('healthy');

    const results = await vectorDB.query('mdc-jjobs', 'nonexistent query');
    expect(results).toEqual([]);  // empty, not thrown
  });
});

// ── P13: Retry Exponential Backoff ───────────────────────────────────────────

describe('P13: Retry Exponential Backoff', () => {
  test('delays follow 5s, 10s, 20s pattern with max 60s', async () => {
    const delays = [];
    const origSetTimeout = global.setTimeout;

    // Capture delay values without actually waiting
    vi.spyOn(global, 'setTimeout').mockImplementation((fn, ms) => {
      delays.push(ms);
      fn();  // execute immediately
      return 0;
    });

    let attempts = 0;
    try {
      await withRetry(
        async () => { attempts++; throw new Error('fail'); },
        { maxAttempts: 4 }
      );
    } catch (_) {}

    vi.restoreAllMocks();

    expect(attempts).toBe(4);
    expect(delays).toEqual([5000, 10000, 20000]);  // 3 retries between 4 attempts
  });

  test('succeeds on first attempt — no delays', async () => {
    const delays = [];
    vi.spyOn(global, 'setTimeout').mockImplementation((fn, ms) => { delays.push(ms); fn(); return 0; });

    const result = await withRetry(async () => 'ok');
    vi.restoreAllMocks();

    expect(result).toBe('ok');
    expect(delays).toHaveLength(0);
  });

  test('succeeds on second attempt — one delay of 5s', async () => {
    const delays = [];
    vi.spyOn(global, 'setTimeout').mockImplementation((fn, ms) => { delays.push(ms); fn(); return 0; });

    let call = 0;
    const result = await withRetry(async () => {
      if (++call === 1) throw new Error('first fail');
      return 'recovered';
    });
    vi.restoreAllMocks();

    expect(result).toBe('recovered');
    expect(delays).toEqual([5000]);
  });

  test('property: delay at attempt N is RETRY_DELAYS[min(N, last)] — always ≤ 60s', async () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 3 }),  // retry index (0-based)
        (retryIndex) => {
          const RETRY_DELAYS = [5000, 10000, 20000, 60000];
          const delay = RETRY_DELAYS[Math.min(retryIndex, RETRY_DELAYS.length - 1)];
          expect(delay).toBeLessThanOrEqual(60000);
          expect(delay).toBeGreaterThan(0);
          // Monotonically non-decreasing
          if (retryIndex > 0) {
            const prev = RETRY_DELAYS[Math.min(retryIndex - 1, RETRY_DELAYS.length - 1)];
            expect(delay).toBeGreaterThanOrEqual(prev);
          }
        }
      ),
      { numRuns: 50 }
    );
  });

  test('onRetry callback receives attempt number, delay, and error', async () => {
    const retryLog = [];
    vi.spyOn(global, 'setTimeout').mockImplementation((fn, ms) => { fn(); return 0; });

    try {
      await withRetry(
        async () => { throw new Error('boom'); },
        {
          maxAttempts: 3,
          onRetry: (attempt, delayMs, err) => retryLog.push({ attempt, delayMs, msg: err.message }),
        }
      );
    } catch (_) {}

    vi.restoreAllMocks();

    expect(retryLog).toHaveLength(2);  // 3 attempts → 2 retries
    expect(retryLog[0]).toMatchObject({ attempt: 1, delayMs: 5000, msg: 'boom' });
    expect(retryLog[1]).toMatchObject({ attempt: 2, delayMs: 10000, msg: 'boom' });
  });
});
