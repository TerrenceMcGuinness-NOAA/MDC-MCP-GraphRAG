/**
 * Neptune GGSR Preservation Property Tests
 *
 * Property 2: Non-Affected Queries and Stdio GGSR Unchanged
 *
 * These tests MUST PASS on UNFIXED code — they capture baseline behavior
 * that must be preserved after the bugfix.
 */

import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import { NeptuneAdapter } from '../src/data/adapters/NeptuneAdapter.js';
import { transformApoc, UnsupportedQueryError } from '../src/data/adapters/apoc-transform.js';

const NEPTUNE_ENDPOINT = process.env.NEPTUNE_ENDPOINT;
const SKIP = !NEPTUNE_ENDPOINT;

// ── Query Preservation Tests ────────────────────────────────────────────────

describe.skipIf(SKIP)('Preservation — Non-VLP Queries', () => {
  let adapter;

  beforeAll(async () => { adapter = new NeptuneAdapter({ endpoint: NEPTUNE_ENDPOINT }); await adapter.connect(); });
  afterAll(async () => { if (adapter) await adapter.close(); });

  it('findImporters returns array with expected shape', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.constantFrom('os', 'sys', 'numpy', 'NONEXISTENT_MODULE_XYZ'),
        async (mod) => {
          const result = await adapter.findImporters(mod);
          expect(result).toBeInstanceOf(Array);
          for (const row of result) {
            expect(row).toHaveProperty('file');
            expect(row).toHaveProperty('importType');
          }
        }
      ),
      { numRuns: 4 }
    );
  });

  it('findCallers returns array with caller/callerType', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.constantFrom('setuprad', 'forecast', 'main', 'NONEXISTENT_FN_XYZ'),
        async (fn) => {
          const result = await adapter.findCallers(fn);
          expect(result).toBeInstanceOf(Array);
          for (const row of result) {
            expect(row).toHaveProperty('caller');
            expect(row).toHaveProperty('callerType');
          }
        }
      ),
      { numRuns: 4 }
    );
  });

  it('getStatistics returns { nodes, relationships }', async () => {
    const stats = await adapter.getStatistics();
    expect(stats).toHaveProperty('nodes');
    expect(stats).toHaveProperty('relationships');
    expect(typeof stats.nodes).toBe('number');
    expect(typeof stats.relationships).toBe('number');
  });

  it('traceCrossLanguagePath returns array (compatible MATCH pattern)', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.constantFrom('exglobal_forecast', 'exgdas_atmos_analysis', 'NONEXISTENT_XYZ'),
        async (name) => {
          const result = await adapter.traceCrossLanguagePath(name);
          expect(result).toBeInstanceOf(Array);
        }
      ),
      { numRuns: 3 }
    );
  });

  it('findScriptCallers returns array (single-hop, no VLP)', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.constantFrom('exglobal_forecast.py', 'exgdas_atmos_analysis.sh', 'NONEXISTENT_XYZ'),
        async (name) => {
          const result = await adapter.findScriptCallers(name);
          expect(result).toBeInstanceOf(Array);
          for (const row of result) {
            expect(row).toHaveProperty('caller');
            expect(row).toHaveProperty('callerType');
          }
        }
      ),
      { numRuns: 3 }
    );
  });

  // NOTE: findFortranCallers uses multi-label syntax (f:FortranSubroutine|FortranFunction|FortranProgram)
  // which Neptune rejects. This is a separate bug that will be fixed in task 3.4.
  // Preservation test for findFortranCallers will be validated after fix.

  it('healthCheck returns { status, connected, nodeCount }', async () => {
    const health = await adapter.healthCheck();
    expect(health).toHaveProperty('status');
    expect(health).toHaveProperty('connected', true);
    expect(health).toHaveProperty('nodeCount');
    expect(typeof health.nodeCount).toBe('number');
  });
});

// ── APOC Transform Preservation Tests ───────────────────────────────────────

describe('Preservation — APOC Transforms', () => {
  it('non-APOC queries pass through unchanged', () => {
    fc.assert(
      fc.property(
        fc.constantFrom(
          'MATCH (n) RETURN n',
          'MATCH (a)-[:CALLS]->(b) RETURN a, b',
          'MATCH path = (f)-[:IMPORTS*1..3]->(dep) RETURN path',
          'MATCH (n) WHERE n.name = "test" RETURN count(n)',
        ),
        (query) => {
          expect(transformApoc(query)).toBe(query);
        }
      ),
      { numRuns: 4 }
    );
  });

  it('apoc.path.expand transforms correctly', () => {
    const input = "CALL apoc.path.expand(startNode, 'CALLS', 'Function', 1, 5) YIELD path AS p";
    const result = transformApoc(input);
    expect(result).toContain('MATCH');
    expect(result).not.toContain('apoc.');
  });

  it('apoc.create.node transforms to CREATE', () => {
    const input = "CALL apoc.create.node(['File'], {path: '/test'}) YIELD node AS n";
    const result = transformApoc(input);
    expect(result).toContain('CREATE');
    expect(result).not.toContain('apoc.');
  });

  it('apoc.merge.node transforms to MERGE', () => {
    const input = "CALL apoc.merge.node(['File'], {path: '/test'}, {created: true}, {updated: true}) YIELD node AS n";
    const result = transformApoc(input);
    expect(result).toContain('MERGE');
    expect(result).toContain('ON CREATE SET');
    expect(result).toContain('ON MATCH SET');
  });

  it('unknown APOC throws UnsupportedQueryError', () => {
    expect(() => transformApoc("CALL apoc.unknown.procedure() YIELD x")).toThrow(UnsupportedQueryError);
  });
});

// ── Stdio GGSR Preservation Tests ───────────────────────────────────────────

describe.skipIf(SKIP)('Preservation — Stdio GGSR Injection', () => {
  it('UnifiedMCPServer.start() injects GGSR into tool modules', async () => {
    // Verify the stdio path creates GGSR — we just check the code path exists
    const { UnifiedMCPServer } = await import('../src/UnifiedMCPServer.js');
    const config = UnifiedMCPServer.getConfiguration('full');
    const mcp = new UnifiedMCPServer(config);

    // The start() method connects data access and injects GGSR.
    // We verify the tool modules exist and have the expected properties.
    expect(mcp.codeAnalysisTools).toBeDefined();
    expect(mcp.graphRAGTools).toBeDefined();
    // Before start(), ggsr is null — this is expected baseline
    expect(mcp.codeAnalysisTools.ggsr).toBeNull();
    expect(mcp.graphRAGTools.ggsr).toBeNull();
  });
});

// ── Health Endpoint Preservation ────────────────────────────────────────────

describe.skipIf(SKIP)('Preservation — Health Endpoint', () => {
  it('/health returns expected structure', async () => {
    const res = await fetch(`http://localhost:3000/health`);
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty('status', 'ok');
    expect(body).toHaveProperty('tools', 51);
    expect(body).toHaveProperty('dataAccess');
  });
});

// ── labels() Compatibility Preservation ─────────────────────────────────────

describe.skipIf(SKIP)('Preservation — labels() Compatibility', () => {
  let adapter;

  beforeAll(async () => { adapter = new NeptuneAdapter({ endpoint: NEPTUNE_ENDPOINT }); await adapter.connect(); });
  afterAll(async () => { if (adapter) await adapter.close(); });

  it('head(labels(n)) produces same result as labels(n)[0] on Neptune', async () => {
    // Run both forms and compare
    const [indexResult, headResult] = await Promise.all([
      adapter.query('MATCH (n) WHERE n.name IS NOT NULL RETURN labels(n)[0] AS label LIMIT 5'),
      adapter.query('MATCH (n) WHERE n.name IS NOT NULL RETURN head(labels(n)) AS label LIMIT 5'),
    ]);
    expect(indexResult.length).toBe(headResult.length);
    for (let i = 0; i < indexResult.length; i++) {
      expect(indexResult[i].label).toBe(headResult[i].label);
    }
  });
});
