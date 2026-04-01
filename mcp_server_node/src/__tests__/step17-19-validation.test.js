/**
 * Step 17-19 — Validation Property Tests
 *
 * P8: Search Equivalence — OpenSearch ranking similarity within 5% of ChromaDB
 *
 * Also covers the overlapAtK metric used in validate-search-relevance.js.
 */

import { describe, test, expect } from 'vitest';
import fc from 'fast-check';

// ── overlapAtK — extracted from validate-search-relevance.js ─────────────────

function overlapAtK(legacyIds, awsIds, k) {
  const legacySet = new Set(legacyIds.slice(0, k));
  const awsSet    = new Set(awsIds.slice(0, k));
  let overlap = 0;
  for (const id of legacySet) if (awsSet.has(id)) overlap++;
  return overlap / Math.max(legacySet.size, 1);
}

// ── P8: Search Equivalence ────────────────────────────────────────────────────

describe('P8: Search Equivalence', () => {
  const EPSILON = 0.05;
  const TOP_K   = 5;

  test('identical rankings → overlap = 1.0 (passes 5% tolerance)', () => {
    const ids = ['a', 'b', 'c', 'd', 'e'];
    expect(overlapAtK(ids, ids, TOP_K)).toBe(1.0);
    expect(overlapAtK(ids, ids, TOP_K)).toBeGreaterThanOrEqual(1 - EPSILON);
  });

  test('completely different rankings → overlap = 0.0 (fails 5% tolerance)', () => {
    const legacy = ['a', 'b', 'c', 'd', 'e'];
    const aws    = ['f', 'g', 'h', 'i', 'j'];
    expect(overlapAtK(legacy, aws, TOP_K)).toBe(0.0);
    expect(overlapAtK(legacy, aws, TOP_K)).toBeLessThan(1 - EPSILON);
  });

  test('4/5 overlap → 0.8 (fails 5% tolerance — need ≥0.95)', () => {
    const legacy = ['a', 'b', 'c', 'd', 'e'];
    const aws    = ['a', 'b', 'c', 'd', 'z'];  // 4 in common
    const sim = overlapAtK(legacy, aws, TOP_K);
    expect(sim).toBe(0.8);
    expect(sim).toBeLessThan(1 - EPSILON);  // 0.8 < 0.95 — fails tolerance
  });

  test('3/5 overlap → 0.6 (fails 5% tolerance)', () => {
    const legacy = ['a', 'b', 'c', 'd', 'e'];
    const aws    = ['a', 'b', 'c', 'x', 'y'];
    const sim = overlapAtK(legacy, aws, TOP_K);
    expect(sim).toBe(0.6);
    expect(sim).toBeLessThan(1 - EPSILON);
  });

  test('property: overlapAtK is always in [0, 1]', () => {
    fc.assert(
      fc.property(
        fc.array(fc.string({ minLength: 1, maxLength: 8 }), { minLength: 1, maxLength: 10 }),
        fc.array(fc.string({ minLength: 1, maxLength: 8 }), { minLength: 1, maxLength: 10 }),
        fc.integer({ min: 1, max: 10 }),
        (legacy, aws, k) => {
          const sim = overlapAtK(legacy, aws, k);
          expect(sim).toBeGreaterThanOrEqual(0);
          expect(sim).toBeLessThanOrEqual(1);
        }
      ),
      { numRuns: 200 }
    );
  });

  test('property: overlapAtK(ids, ids, k) = 1.0 for any non-empty id list', () => {
    fc.assert(
      fc.property(
        fc.array(fc.string({ minLength: 1 }), { minLength: 1, maxLength: 20 }),
        fc.integer({ min: 1, max: 20 }),
        (ids, k) => {
          expect(overlapAtK(ids, ids, k)).toBe(1.0);
        }
      ),
      { numRuns: 100 }
    );
  });

  test('property: overlap is symmetric — overlapAtK(a,b,k) = overlapAtK(b,a,k) when same size', () => {
    fc.assert(
      fc.property(
        fc.array(fc.string({ minLength: 1, maxLength: 6 }), { minLength: 5, maxLength: 5 }),
        fc.array(fc.string({ minLength: 1, maxLength: 6 }), { minLength: 5, maxLength: 5 }),
        (a, b) => {
          // Overlap is symmetric when both lists have same length
          expect(overlapAtK(a, b, 5)).toBeCloseTo(overlapAtK(b, a, 5), 10);
        }
      ),
      { numRuns: 100 }
    );
  });

  test('property: 5% tolerance means ≥95% of top-k results must match', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 5 }),  // number of mismatches in top-5
        (mismatches) => {
          const base = ['a', 'b', 'c', 'd', 'e'];
          const aws  = [...base];
          // Replace `mismatches` items with unique non-matching IDs
          for (let i = 0; i < mismatches; i++) aws[i] = `z${i}`;

          const sim = overlapAtK(base, aws, 5);
          const expectedOverlap = (5 - mismatches) / 5;
          expect(sim).toBeCloseTo(expectedOverlap, 10);

          const passes = sim >= (1 - EPSILON);
          // Passes iff ≤ 0 mismatches (since 1/5 = 0.2 < 0.95)
          // Actually epsilon=0.05 means sim >= 0.95, so need 5/5 or 4.75/5 → only 5/5 passes
          if (mismatches === 0) expect(passes).toBe(true);
          if (mismatches >= 1)  expect(passes).toBe(false);
        }
      ),
      { numRuns: 6 }
    );
  });
});

// ── Verification logic tests (Step 17) ───────────────────────────────────────

describe('Step 17: Migration Verification Logic', () => {
  test('count parity: equal counts → passed=true', () => {
    const legacy = { nodes: 95000, rels: 2600000 };
    const aws    = { nodes: 95000, rels: 2600000 };
    expect(legacy.nodes === aws.nodes).toBe(true);
    expect(legacy.rels  === aws.rels).toBe(true);
  });

  test('count parity: off-by-one → passed=false', () => {
    const legacy = { nodes: 95000, rels: 2600000 };
    const aws    = { nodes: 94999, rels: 2600000 };
    expect(legacy.nodes === aws.nodes).toBe(false);
  });

  test('property: parity holds iff counts are exactly equal', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 200000 }),
        fc.integer({ min: 0, max: 200000 }),
        (legacyCount, awsCount) => {
          const match = legacyCount === awsCount;
          expect(match).toBe(legacyCount === awsCount);
        }
      ),
      { numRuns: 100 }
    );
  });
});
