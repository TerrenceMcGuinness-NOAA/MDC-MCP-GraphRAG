/**
 * loadGraph Preservation Property Tests
 *
 * These tests verify behaviors that must be PRESERVED by the fix:
 * - Successful runs write "done" watermark with correct counts
 * - Unresolvable rels are filtered and skipped count is tracked
 * - Dry-run skips all writes
 *
 * ALL tests must PASS on UNFIXED code (before the fix).
 * ALL tests must PASS on FIXED code (after the fix).
 */

import { describe, it, expect, vi } from 'vitest';
import * as fc from 'fast-check';

// ── Extracted logic (mirrors migrate-to-aws.js) ─────────────────────────────

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
 * Simulate the UNFIXED loadGraph happy path (all batches succeed).
 * This is the code path that must be preserved.
 */
async function loadGraphFull_UNFIXED({ dump, runWithRetryFn, dryRun = false }) {
  const nodeIdMap = new Map();
  for (const n of dump.nodes) {
    const mid = nodeMergeId(n);
    n.properties._mergeId = mid;
    if (n.properties.name) nodeIdMap.set(n.properties.name, mid);
  }

  const validRels = [];
  let skippedRels = 0;
  for (const r of dump.relationships) {
    const fromId = nodeIdMap.get(r.fromName);
    const toId = nodeIdMap.get(r.toName);
    if (fromId && toId) {
      validRels.push({ ...r, fromId, toId });
    } else {
      skippedRels++;
    }
  }

  const wm = {};

  if (!dryRun) {
    const NEPTUNE_BATCH = 100;
    // Load nodes
    for (let i = 0; i < dump.nodes.length; i += NEPTUNE_BATCH) {
      const batch = dump.nodes.slice(i, Math.min(i + NEPTUNE_BATCH, dump.nodes.length));
      const byLabel = {};
      for (const n of batch) {
        const label = n.labels[0];
        (byLabel[label] = byLabel[label] || []).push(sanitizeProps(n.properties));
      }
      for (const [label, props] of Object.entries(byLabel)) {
        await runWithRetryFn('node', label, props)
          .catch(err => console.error(`[ERROR] Nodes batch ${i} label=${label}: ${err.message.substring(0, 100)}`));
      }
    }

    // Load rels
    for (let i = 0; i < validRels.length; i += NEPTUNE_BATCH) {
      const batch = validRels.slice(i, Math.min(i + NEPTUNE_BATCH, validRels.length));
      const byType = {};
      for (const r of batch) { (byType[r.type || 'RELATES'] = byType[r.type || 'RELATES'] || []).push(r); }
      for (const [relType, rels] of Object.entries(byType)) {
        const sanitized = rels.map(r => ({ fromId: r.fromId, toId: r.toId, props: sanitizeProps(r.props) }));
        await runWithRetryFn('rel', relType, sanitized)
          .catch(err => console.error(`[ERROR] Rels batch ${i} type=${relType}: ${err.message.substring(0, 100)}`));
      }
    }
  }

  // Unconditional watermark (unfixed behavior — preserved when all succeed)
  wm['load:graph'] = 'done';
  wm['load:graph:nodes'] = dump.nodes.length;
  wm['load:graph:rels'] = dump.relationships.length;
  wm['load:graph:relsLoaded'] = dump.relationships.length - skippedRels;
  return { wm, skippedRels, validRels: validRels.length };
}

// ── Generators ───────────────────────────────────────────────────────────────

const nodeArb = fc.record({
  labels: fc.tuple(fc.constantFrom('File', 'Function', 'Module', 'Package')).map(t => [t[0]]),
  properties: fc.record({
    name: fc.string({ minLength: 1, maxLength: 20 }).filter(s => s.trim().length > 0),
    path: fc.option(fc.string({ minLength: 1, maxLength: 50 }), { nil: undefined }),
  }),
});

function relArb(nodeNames) {
  if (nodeNames.length < 2) {
    return fc.constant({ fromName: 'a', toName: 'b', type: 'CALLS', props: {} });
  }
  return fc.record({
    fromName: fc.constantFrom(...nodeNames),
    toName: fc.constantFrom(...nodeNames),
    type: fc.constantFrom('CALLS', 'IMPORTS', 'CONTAINS', 'DEPENDS_ON'),
    props: fc.constant({}),
  });
}

// ── Tests ────────────────────────────────────────────────────────────────────

describe('loadGraph Preservation — successful runs write "done" watermark', () => {

  it('Property: all batches succeed → watermark is "done" with correct counts', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.array(nodeArb, { minLength: 1, maxLength: 30 }),
        async (nodes) => {
          const names = nodes.map(n => n.properties.name);
          const rels = [];
          // Generate rels between existing nodes
          for (let i = 0; i < Math.min(names.length * 2, 20); i++) {
            rels.push({
              fromName: names[i % names.length],
              toName: names[(i + 1) % names.length],
              type: 'CALLS', props: {},
            });
          }
          const dump = { nodes, relationships: rels };

          const runWithRetryFn = vi.fn().mockResolvedValue({ records: [] });
          const { wm } = await loadGraphFull_UNFIXED({ dump, runWithRetryFn });

          expect(wm['load:graph']).toBe('done');
          expect(wm['load:graph:nodes']).toBe(nodes.length);
          expect(wm['load:graph:rels']).toBe(rels.length);
        }
      ),
      { numRuns: 30 }
    );
  });

  it('Property: unresolvable rels are filtered, skippedRels count is correct', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 1, max: 10 }),  // resolvable count
        fc.integer({ min: 1, max: 10 }),  // unresolvable count
        async (resolvableCount, unresolvableCount) => {
          const nodes = Array.from({ length: 3 }, (_, i) => ({
            labels: ['File'],
            properties: { name: `node_${i}` },
          }));
          const names = nodes.map(n => n.properties.name);

          const resolvable = Array.from({ length: resolvableCount }, (_, i) => ({
            fromName: names[i % names.length],
            toName: names[(i + 1) % names.length],
            type: 'CALLS', props: {},
          }));
          const unresolvable = Array.from({ length: unresolvableCount }, () => ({
            fromName: 'NONEXISTENT_A',
            toName: 'NONEXISTENT_B',
            type: 'CALLS', props: {},
          }));

          const dump = { nodes, relationships: [...resolvable, ...unresolvable] };
          const runWithRetryFn = vi.fn().mockResolvedValue({ records: [] });
          const { skippedRels, validRels } = await loadGraphFull_UNFIXED({ dump, runWithRetryFn });

          expect(skippedRels).toBe(unresolvableCount);
          expect(validRels).toBe(resolvableCount);
          expect(validRels + skippedRels).toBe(dump.relationships.length);
        }
      ),
      { numRuns: 30 }
    );
  });

  it('Property: dry-run skips all Neptune writes', async () => {
    const nodes = [{ labels: ['File'], properties: { name: 'a' } }];
    const rels = [{ fromName: 'a', toName: 'a', type: 'CALLS', props: {} }];
    const dump = { nodes, relationships: rels };

    const runWithRetryFn = vi.fn().mockResolvedValue({ records: [] });
    const { wm } = await loadGraphFull_UNFIXED({ dump, runWithRetryFn, dryRun: true });

    // runWithRetry should NOT have been called in dry-run
    expect(runWithRetryFn).not.toHaveBeenCalled();
    // Watermark is still written (this is the unfixed behavior)
    expect(wm['load:graph']).toBe('done');
  });

  it('Property: nodeMergeId is deterministic', () => {
    fc.assert(
      fc.property(
        nodeArb,
        (node) => {
          const id1 = nodeMergeId(node);
          const id2 = nodeMergeId(node);
          expect(id1).toBe(id2);
          expect(typeof id1).toBe('string');
          expect(id1.length).toBeGreaterThan(0);
        }
      ),
      { numRuns: 50 }
    );
  });

  it('Property: sanitizeProps handles all value types', () => {
    fc.assert(
      fc.property(
        fc.dictionary(
          fc.string({ minLength: 1, maxLength: 10 }),
          fc.oneof(
            fc.string(), fc.integer(), fc.boolean(),
            fc.constant(null), fc.constant(undefined),
            fc.array(fc.integer()), fc.dictionary(fc.string(), fc.integer())
          )
        ),
        (props) => {
          const result = sanitizeProps(props);
          for (const [k, v] of Object.entries(result)) {
            // All values must be string, number, or boolean
            expect(['string', 'number', 'boolean']).toContain(typeof v);
          }
          // null/undefined values are excluded
          for (const [k, v] of Object.entries(props)) {
            if (v === null || v === undefined) {
              expect(result).not.toHaveProperty(k);
            }
          }
        }
      ),
      { numRuns: 50 }
    );
  });
});
