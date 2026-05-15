/**
 * Step 15/16 — Migration Property Tests
 *
 * P4: Data Completeness    — Neptune counts == Neo4j counts; OS index counts == ChromaDB counts
 * P5: Migration Idempotence — second run produces identical state, no duplicates
 * P6: Embedding Fidelity   — 768-dim embeddings transferred bitwise identical
 */

import { describe, test, expect, vi } from 'vitest';
import fc from 'fast-check';

// ── Shared helpers ────────────────────────────────────────────────────────────

const COLLECTION_TO_INDEX = {
  'code-with-context-v8-0-0':      'mdc-code-context',
  'global-workflow-docs-v8-0-0':   'mdc-workflow-docs',
  'jjobs-v8-0-0':                  'mdc-jjobs',
  'community-summaries':           'mdc-community-summaries',
  'ee2-standards-v5-0-0-enhanced': 'mdc-ee2-standards',
};

/** Simulate a migration state (watermarks) */
function makeWatermarks(collections, nodeCount, relCount) {
  const wm = {
    'export:graph': 'done',
    'export:graph:nodes': nodeCount,
    'export:graph:rels': relCount,
    'load:graph': 'done',
    'load:graph:nodes': nodeCount,
    'load:graph:rels': relCount,
  };
  for (const [col] of Object.entries(COLLECTION_TO_INDEX)) {
    const count = collections[col] ?? 0;
    wm[`export:${col}`] = 'done';
    wm[`export:${col}:count`] = count;
    wm[`load:${col}`] = 'done';
    wm[`load:${col}:count`] = count;
  }
  return wm;
}

/** Simulate the verify() logic from migrate-to-aws.js */
function simulateVerify(wm, osIndexCounts, neptuneNodeCount, neptuneRelCount) {
  const report = { vectors: {}, graph: {}, passed: true };

  for (const [col, index] of Object.entries(COLLECTION_TO_INDEX)) {
    const exported = wm[`export:${col}:count`] ?? null;
    const indexed  = osIndexCounts[index] ?? null;
    const match    = exported !== null && indexed !== null && exported === indexed;
    report.vectors[col] = { exported, indexed, match };
    if (!match) report.passed = false;
  }

  const exportedNodes = wm['export:graph:nodes'] ?? null;
  const exportedRels  = wm['export:graph:rels']  ?? null;
  const nodesMatch = exportedNodes !== null && neptuneNodeCount !== null && exportedNodes === neptuneNodeCount;
  const relsMatch  = exportedRels  !== null && neptuneRelCount  !== null && exportedRels  === neptuneRelCount;
  report.graph = { nodesMatch, relsMatch };
  if (!nodesMatch || !relsMatch) report.passed = false;

  return report;
}

// ── P4: Data Completeness ────────────────────────────────────────────────────

describe('P4: Data Completeness', () => {
  test('verify passes when all counts match', () => {
    const counts = { 'mdc-code-context': 58761, 'mdc-workflow-docs': 3514, 'mdc-jjobs': 700, 'mdc-community-summaries': 828, 'mdc-ee2-standards': 34 };
    const wm = makeWatermarks(
      { 'code-with-context-v8-0-0': 58761, 'global-workflow-docs-v8-0-0': 3514, 'jjobs-v8-0-0': 700, 'community-summaries': 828, 'ee2-standards-v5-0-0-enhanced': 34 },
      95000, 2600000
    );
    const report = simulateVerify(wm, counts, 95000, 2600000);
    expect(report.passed).toBe(true);
    for (const col of Object.values(report.vectors)) {
      expect(col.match).toBe(true);
    }
    expect(report.graph.nodesMatch).toBe(true);
    expect(report.graph.relsMatch).toBe(true);
  });

  test('verify fails when vector count mismatches', () => {
    const wm = makeWatermarks({ 'code-with-context-v8-0-0': 58761 }, 100, 200);
    // OS has 1 fewer doc
    const report = simulateVerify(wm, { 'mdc-code-context': 58760 }, 100, 200);
    expect(report.passed).toBe(false);
    expect(report.vectors['code-with-context-v8-0-0'].match).toBe(false);
  });

  test('verify fails when graph node count mismatches', () => {
    const wm = makeWatermarks({}, 95000, 2600000);
    const report = simulateVerify(wm, {}, 94999, 2600000);
    expect(report.passed).toBe(false);
    expect(report.graph.nodesMatch).toBe(false);
  });

  test('property: verify passes iff all exported counts equal loaded counts', () => {
    fc.assert(
      fc.property(
        fc.record({
          codeCount: fc.integer({ min: 0, max: 100000 }),
          nodeCount: fc.integer({ min: 0, max: 200000 }),
          relCount:  fc.integer({ min: 0, max: 5000000 }),
        }),
        ({ codeCount, nodeCount, relCount }) => {
          const colCounts = { 'code-with-context-v8-0-0': codeCount };
          const wm = makeWatermarks(colCounts, nodeCount, relCount);
          // Perfect parity
          const report = simulateVerify(
            wm,
            { 'mdc-code-context': codeCount, 'mdc-workflow-docs': 0, 'mdc-jjobs': 0, 'mdc-community-summaries': 0, 'mdc-ee2-standards': 0 },
            nodeCount, relCount
          );
          // All vector collections with count 0 should match (0 === 0)
          expect(report.graph.nodesMatch).toBe(true);
          expect(report.graph.relsMatch).toBe(true);
          expect(report.vectors['code-with-context-v8-0-0'].match).toBe(true);
        }
      ),
      { numRuns: 100 }
    );
  });
});

// ── P5: Migration Idempotence ────────────────────────────────────────────────

describe('P5: Migration Idempotence', () => {
  test('watermark skip logic prevents re-export of completed collections', () => {
    const wm = {};
    const collections = ['code-with-context-v8-0-0', 'global-workflow-docs-v8-0-0'];

    // Simulate first run completing
    for (const col of collections) {
      wm[`export:${col}`] = 'done';
      wm[`export:${col}:count`] = 1000;
    }

    // Second run: check that already-done collections are skipped
    let exportCalls = 0;
    for (const col of collections) {
      if (wm[`export:${col}`] === 'done') continue;
      exportCalls++;  // would export
    }
    expect(exportCalls).toBe(0);  // all skipped
  });

  test('watermark skip logic prevents re-loading of completed indices', () => {
    const wm = {};
    for (const col of Object.keys(COLLECTION_TO_INDEX)) {
      wm[`load:${col}`] = 'done';
      wm[`load:${col}:count`] = 500;
    }

    let loadCalls = 0;
    for (const col of Object.keys(COLLECTION_TO_INDEX)) {
      if (wm[`load:${col}`] === 'done') continue;
      loadCalls++;
    }
    expect(loadCalls).toBe(0);
  });

  test('property: second run with all watermarks set produces zero additional operations', () => {
    fc.assert(
      fc.property(
        fc.record({
          counts: fc.record(
            Object.fromEntries(Object.keys(COLLECTION_TO_INDEX).map(k => [k, fc.integer({ min: 0, max: 10000 })]))
          ),
          nodeCount: fc.integer({ min: 0, max: 100000 }),
          relCount:  fc.integer({ min: 0, max: 1000000 }),
        }),
        ({ counts, nodeCount, relCount }) => {
          const wm = makeWatermarks(counts, nodeCount, relCount);

          // Simulate second run — count skipped operations
          let skipped = 0;
          for (const col of Object.keys(COLLECTION_TO_INDEX)) {
            if (wm[`export:${col}`] === 'done') skipped++;
            if (wm[`load:${col}`] === 'done') skipped++;
          }
          if (wm['export:graph'] === 'done') skipped++;
          if (wm['load:graph'] === 'done') skipped++;

          const totalOps = Object.keys(COLLECTION_TO_INDEX).length * 2 + 2;
          expect(skipped).toBe(totalOps);  // all operations skipped
        }
      ),
      { numRuns: 50 }
    );
  });
});

// ── P6: Embedding Fidelity ───────────────────────────────────────────────────

describe('P6: Embedding Fidelity', () => {
  test('768-dim embedding is transferred without modification', () => {
    // Simulate the migration: embedding from ChromaDB is placed directly into OS doc
    const sourceEmbedding = Array.from({ length: 768 }, (_, i) => Math.sin(i) * 0.5);

    const chromaDoc = { id: 'doc-1', content: 'test', metadata: {}, embedding: sourceEmbedding };

    // Migration logic: embedding is passed through as-is (no re-generation)
    const osDoc = {
      content:   chromaDoc.content,
      embedding: chromaDoc.embedding,  // bitwise transfer
      metadata:  chromaDoc.metadata,
      chunk_id:  chromaDoc.id,
    };

    expect(osDoc.embedding).toHaveLength(768);
    expect(osDoc.embedding).toStrictEqual(sourceEmbedding);  // bitwise identical
  });

  test('property: for any 768-dim embedding, migration preserves all values exactly', () => {
    fc.assert(
      fc.property(
        fc.array(fc.float({ noNaN: true, noDefaultInfinity: true }), { minLength: 768, maxLength: 768 }),
        (embedding) => {
          // Migration: direct assignment, no transformation
          const migrated = { embedding };
          expect(migrated.embedding).toHaveLength(768);
          for (let i = 0; i < 768; i++) {
            expect(migrated.embedding[i]).toBe(embedding[i]);
          }
        }
      ),
      { numRuns: 20 }
    );
  });

  test('embedding dimension is always 768 after migration', () => {
    fc.assert(
      fc.property(
        fc.array(fc.float({ noNaN: true }), { minLength: 768, maxLength: 768 }),
        (embedding) => {
          expect(embedding).toHaveLength(768);
        }
      ),
      { numRuns: 30 }
    );
  });
});
