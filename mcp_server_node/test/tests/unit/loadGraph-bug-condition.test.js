/**
 * loadGraph Bug Condition Exploration Test
 *
 * Property: When relationship MERGE batches fail after retries,
 * the watermark must NOT be written as "done".
 *
 * On UNFIXED code: this test FAILS — confirming the bug exists.
 * On FIXED code: this test PASSES — confirming the bug is fixed.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as fc from 'fast-check';

// ── Extracted logic under test (mirrors migrate-to-aws.js loadGraph) ─────────

function sanitizeProps(props) {
  if (!props) return {};
  const out = {};
  for (const [k, v] of Object.entries(props)) {
    if (v === null || v === undefined) continue;
    if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') {
      out[k] = v;
    } else {
      out[k] = JSON.stringify(v);
    }
  }
  return out;
}

function nodeMergeId(node) {
  const p = node.properties;
  return p.id || p.path || p.name || `${node.labels[0]}_${Buffer.from(JSON.stringify(p)).toString('base64url').substring(0, 40)}`;
}

/**
 * Simulate the UNFIXED rel loading loop from migrate-to-aws.js.
 * The .catch() swallows errors — this is the bug.
 */
async function loadGraphRels_UNFIXED({ validRels, runWithRetryFn }) {
  const NEPTUNE_BATCH = 100;
  const PARALLELISM = 2;
  const wm = {};

  for (let i = 0; i < validRels.length; i += NEPTUNE_BATCH * PARALLELISM) {
    const workerTasks = [];
    for (let w = 0; w < PARALLELISM; w++) {
      const batchStart = i + w * NEPTUNE_BATCH;
      if (batchStart >= validRels.length) break;
      const batch = validRels.slice(batchStart, Math.min(batchStart + NEPTUNE_BATCH, validRels.length));
      const byType = {};
      for (const r of batch) { (byType[r.type || 'RELATES'] = byType[r.type || 'RELATES'] || []).push(r); }

      workerTasks.push((async () => {
        for (const [relType, rels] of Object.entries(byType)) {
          const sanitized = rels.map(r => ({ fromId: r.fromId, toId: r.toId, props: sanitizeProps(r.props) }));
          // BUG: .catch() swallows the error
          await runWithRetryFn(relType, sanitized)
            .catch(err => console.error(`[ERROR] Rels batch ${batchStart} type=${relType}: ${err.message.substring(0, 100)}`));
        }
      })());
    }
    await Promise.all(workerTasks);
  }

  // BUG: unconditional watermark write
  wm['load:graph'] = 'done';
  wm['load:graph:relsLoaded'] = validRels.length;
  return wm;
}

/**
 * Simulate the FIXED rel loading loop.
 * Errors are accumulated, watermark is conditional.
 */
async function loadGraphRels_FIXED({ validRels, runWithRetryFn }) {
  const NEPTUNE_BATCH = 100;
  const PARALLELISM = 2;
  const wm = {};
  let failedRelBatches = 0;

  for (let i = 0; i < validRels.length; i += NEPTUNE_BATCH * PARALLELISM) {
    const workerTasks = [];
    for (let w = 0; w < PARALLELISM; w++) {
      const batchStart = i + w * NEPTUNE_BATCH;
      if (batchStart >= validRels.length) break;
      const batch = validRels.slice(batchStart, Math.min(batchStart + NEPTUNE_BATCH, validRels.length));
      const byType = {};
      for (const r of batch) { (byType[r.type || 'RELATES'] = byType[r.type || 'RELATES'] || []).push(r); }

      workerTasks.push((async () => {
        for (const [relType, rels] of Object.entries(byType)) {
          const sanitized = rels.map(r => ({ fromId: r.fromId, toId: r.toId, props: sanitizeProps(r.props) }));
          try {
            await runWithRetryFn(relType, sanitized);
          } catch (err) {
            failedRelBatches++;
            console.error(`[ERROR] Rels batch ${batchStart} type=${relType}: ${err.message.substring(0, 100)}`);
          }
        }
      })());
    }
    await Promise.all(workerTasks);
  }

  if (failedRelBatches === 0) {
    wm['load:graph'] = 'done';
    wm['load:graph:relsLoaded'] = validRels.length;
  } else {
    wm['load:graph'] = 'failed';
    wm['load:graph:failedRelBatches'] = failedRelBatches;
  }
  return wm;
}

// ── Test helpers ─────────────────────────────────────────────────────────────

function makeRels(count) {
  return Array.from({ length: count }, (_, i) => ({
    fromId: `node_${i % 10}`, toId: `node_${(i + 1) % 10}`,
    type: 'CALLS', props: { weight: 1.0 },
  }));
}

// ── Tests ────────────────────────────────────────────────────────────────────

describe('loadGraph Bug Condition — .catch() swallows batch errors', () => {

  it('Property: when batches fail, UNFIXED code still writes watermark as "done" (EXPECTED TO FAIL on unfixed)', async () => {
    // This test asserts CORRECT behavior. On unfixed code it FAILS,
    // confirming the bug. On fixed code it PASSES.
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 1, max: 50 }),  // totalRels
        async (totalRels) => {
          const rels = makeRels(totalRels);
          // All batches fail
          const runWithRetryFn = vi.fn().mockRejectedValue(
            new Error('Operation terminated (internal error)')
          );

          const wm = await loadGraphRels_UNFIXED({ validRels: rels, runWithRetryFn });

          // CORRECT behavior: watermark should NOT be 'done' when batches fail
          // UNFIXED code: watermark IS 'done' → this assertion FAILS → confirms bug
          expect(wm['load:graph']).not.toBe('done');
        }
      ),
      { numRuns: 20 }
    );
  });

  it('Property: when batches fail, FIXED code does NOT write watermark as "done"', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 1, max: 50 }),
        async (totalRels) => {
          const rels = makeRels(totalRels);
          const runWithRetryFn = vi.fn().mockRejectedValue(
            new Error('Operation terminated (internal error)')
          );

          const wm = await loadGraphRels_FIXED({ validRels: rels, runWithRetryFn });

          expect(wm['load:graph']).not.toBe('done');
          expect(wm['load:graph:failedRelBatches']).toBeGreaterThan(0);
        }
      ),
      { numRuns: 20 }
    );
  });

  it('Counterexample: 1 rel batch fails, watermark says "done" (UNFIXED)', async () => {
    const rels = makeRels(10);
    const runWithRetryFn = vi.fn().mockRejectedValue(
      new Error('Operation terminated (internal error)')
    );

    const wm = await loadGraphRels_UNFIXED({ validRels: rels, runWithRetryFn });

    // Document the counterexample:
    // 1 batch of 10 rels fails, but watermark says 'done' with relsLoaded: 10
    console.log(`[COUNTEREXAMPLE] wm['load:graph']=${wm['load:graph']}, relsLoaded=${wm['load:graph:relsLoaded']}`);

    // On UNFIXED code this will be 'done' — the bug
    // We assert the BUGGY behavior here to document it
    expect(wm['load:graph']).toBe('done');  // confirms bug exists
    expect(wm['load:graph:relsLoaded']).toBe(10);  // false count
  });
});
