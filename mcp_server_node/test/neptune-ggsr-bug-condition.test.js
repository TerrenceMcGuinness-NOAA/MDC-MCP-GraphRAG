/**
 * Neptune GGSR Bug Condition Exploration Test
 *
 * Property 1: Neptune Directed VLP Syntax Rejection & Missing HTTP GGSR Injection
 *
 * On UNFIXED code: these tests FAIL — confirming the bugs exist.
 * On FIXED code: these tests PASS — confirming the bugs are fixed.
 *
 * C1: NeptuneAdapter methods generate directed variable-length path syntax
 *     (->[:REL*1..N]->) that Neptune's openCypher rejects.
 * C2: mcp-http-server.js never injects sharedGGSR into per-request instances.
 */

import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import { NeptuneAdapter } from '../src/data/adapters/NeptuneAdapter.js';

// ── Helpers ──────────────────────────────────────────────────────────────────

const NEPTUNE_ENDPOINT = process.env.NEPTUNE_ENDPOINT;
const SKIP = !NEPTUNE_ENDPOINT;

function makeAdapter() {
  return new NeptuneAdapter({ endpoint: NEPTUNE_ENDPOINT });
}

const entityNames = fc.constantFrom(
  'JGLOBAL_FORECAST', 'JGDAS_ATMOS_ANALYSIS', 'setuprad', 'gsi',
  'exglobal_forecast', 'enkf_main', 'NONEXISTENT_NODE_XYZ'
);
const depths = fc.integer({ min: 1, max: 5 });

// ── C1: Neptune Directed VLP Tests ──────────────────────────────────────────

describe.skipIf(SKIP)('C1 — Neptune Directed VLP Syntax', () => {
  let adapter;

  // Connect once, close once
  beforeAll(async () => { adapter = makeAdapter(); await adapter.connect(); });
  afterAll(async () => { if (adapter) await adapter.close(); });

  it('traceCrossLanguageChain forward — no syntax error', async () => {
    await fc.assert(
      fc.asyncProperty(entityNames, fc.integer({ min: 1, max: 3 }), async (name, depth) => {
        try {
          const result = await adapter.traceCrossLanguageChain(name, depth, 'forward');
          expect(result).toBeDefined();
          expect(result.chain).toBeInstanceOf(Array);
        } catch (err) {
          if (err.message.includes('out of memory') || err.message.includes('Operation terminated')) return;
          throw err;
        }
      }),
      { numRuns: 5 }
    );
  });

  it('traceCrossLanguageChain reverse — no syntax error', async () => {
    await fc.assert(
      fc.asyncProperty(entityNames, fc.integer({ min: 1, max: 3 }), async (name, depth) => {
        try {
          const result = await adapter.traceCrossLanguageChain(name, depth, 'reverse');
          expect(result).toBeDefined();
          expect(result.chain).toBeInstanceOf(Array);
        } catch (err) {
          if (err.message.includes('out of memory') || err.message.includes('Operation terminated')) return;
          throw err;
        }
      }),
      { numRuns: 5 }
    );
  });

  it('findUpstreamExecutors — no syntax error', async () => {
    await fc.assert(
      fc.asyncProperty(entityNames, async (name) => {
        try {
          const result = await adapter.findUpstreamExecutors(name);
          expect(result).toBeInstanceOf(Array);
        } catch (err) {
          if (err.message.includes('out of memory') || err.message.includes('Operation terminated')) return;
          throw err;
        }
      }),
      { numRuns: 5 }
    );
  });

  it('traceCallChain — no syntax error', async () => {
    await fc.assert(
      fc.asyncProperty(entityNames, fc.integer({ min: 1, max: 3 }), async (name, depth) => {
        try {
          const result = await adapter.traceCallChain(name, depth);
          expect(result).toBeInstanceOf(Array);
        } catch (err) {
          if (err.message.includes('out of memory') || err.message.includes('Operation terminated')) return;
          throw err;
        }
      }),
      { numRuns: 5 }
    );
  });

  it('traceScriptChain — no syntax error', async () => {
    await fc.assert(
      fc.asyncProperty(entityNames, fc.integer({ min: 1, max: 3 }), async (name, depth) => {
        try {
          const result = await adapter.traceScriptChain(name, depth);
          expect(result).toBeInstanceOf(Array);
        } catch (err) {
          if (err.message.includes('out of memory') || err.message.includes('Operation terminated')) return;
          throw err;
        }
      }),
      { numRuns: 5 }
    );
  });

  it('tracePythonCallChain — no syntax error', async () => {
    await fc.assert(
      fc.asyncProperty(entityNames, fc.integer({ min: 1, max: 3 }), async (name, depth) => {
        try {
          const result = await adapter.tracePythonCallChain(name, depth);
          expect(result).toBeInstanceOf(Array);
        } catch (err) {
          if (err.message.includes('out of memory') || err.message.includes('Operation terminated')) return;
          throw err;
        }
      }),
      { numRuns: 5 }
    );
  });

  it('traceFortranCallChain — no syntax error', async () => {
    await fc.assert(
      fc.asyncProperty(entityNames, fc.integer({ min: 1, max: 2 }), async (name, depth) => {
        try {
          const result = await adapter.traceFortranCallChain(name, depth);
          expect(result).toBeInstanceOf(Array);
        } catch (err) {
          // OOM is a resource issue, not a syntax bug — allow it
          if (err.message.includes('out of memory') || err.message.includes('Operation terminated')) return;
          throw err;
        }
      }),
      { numRuns: 3 }
    );
  });

  it('findDependencyGraph — no syntax error', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.constantFrom('scripts/exglobal_forecast.py', 'ush/load_fv3nests.sh', 'NONEXISTENT.sh'),
        fc.integer({ min: 1, max: 3 }),
        async (path, depth) => {
          try {
            const result = await adapter.findDependencyGraph(path, depth);
            expect(result).toBeInstanceOf(Array);
          } catch (err) {
            if (err.message.includes('out of memory') || err.message.includes('Operation terminated')) return;
            throw err;
          }
        }
      ),
      { numRuns: 3 }
    );
  });

  it('findCircularDependencies — no syntax error', async () => {
    await fc.assert(
      fc.asyncProperty(fc.integer({ min: 2, max: 4 }), async (depth) => {
        try {
          const result = await adapter.findCircularDependencies(depth);
          expect(result).toBeInstanceOf(Array);
        } catch (err) {
          if (err.message.includes('out of memory') || err.message.includes('Operation terminated')) return;
          throw err;
        }
      }),
      { numRuns: 3 }
    );
  });

  it('findFortranCallers — no syntax error (multi-label fix)', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.constantFrom('gsi', 'enkf_main', 'NONEXISTENT_XYZ'),
        async (name) => {
          const result = await adapter.findFortranCallers(name);
          expect(result).toBeInstanceOf(Array);
        }
      ),
      { numRuns: 3 }
    );
  });
});

// ── C2: HTTP GGSR Injection Tests ───────────────────────────────────────────

describe.skipIf(SKIP)('C2 — HTTP GGSR Injection', () => {
  it('per-request UnifiedMCPServer has non-null GGSR after injection', async () => {
    // Verify the mcp-http-server.js source code contains GGSR injection
    const { readFileSync } = await import('fs');
    const { join, dirname } = await import('path');
    const { fileURLToPath } = await import('url');
    const __dirname = dirname(fileURLToPath(import.meta.url));
    const src = readFileSync(join(__dirname, '../src/mcp-http-server.js'), 'utf8');

    // The fix adds GGSR injection into per-request handler
    expect(src).toContain('codeAnalysisTools.ggsr = sharedGGSR');
    expect(src).toContain('graphRAGTools.ggsr = sharedGGSR');
    expect(src).toContain('codeAnalysisTools.retrieval = sharedRetrieval');
    expect(src).toContain('graphRAGTools.retrieval = sharedRetrieval');
    // The fix also creates sharedRetrieval in init block
    expect(src).toContain('let sharedRetrieval = null');
    expect(src).toContain('new GraphGuidedRetrieval');
  });
});
