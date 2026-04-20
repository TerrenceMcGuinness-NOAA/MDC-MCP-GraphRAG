/**
 * Unit Tests for GraphRAGTools — Phase 51
 *
 * Focused on search_architecture similarity floor + level boost behavior.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { GraphRAGTools } from '../tools/GraphRAGTools.js';

function makeTools(vectorResults) {
  const dataAccess = {
    vectorDB: {
      query: vi.fn().mockResolvedValue(vectorResults)
    },
    graphDB: { query: vi.fn() }
  };
  const tools = new GraphRAGTools(dataAccess, { /* sessionManager stub */
    getSessionState: () => null,
    markFileModified: () => {},
    getSessionContext: () => ({}),
    createCheckpoint: () => ({}),
    restoreCheckpoint: () => ({})
  });
  // Skip ensureInitialized (no graphrag stack needed for this test)
  tools.ensureInitialized = vi.fn().mockResolvedValue();
  return { tools, dataAccess };
}

describe('GraphRAGTools.searchArchitecture (Phase 51)', () => {
  it('filters out L0 micro-communities with low similarity', async () => {
    const { tools } = makeTools([
      { text: 'L0 noise', metadata: { communityId: 3525, level: 0 }, distance: 1.4 },  // sim ≈ -0.4
      { text: 'L0 noise 2', metadata: { communityId: 3526, level: 0 }, distance: 0.95 } // sim ≈ 0.05
    ]);

    const result = await tools.searchArchitecture({ query: 'GFS forecast job' });
    expect(result.content[0].text).toMatch(/No high-confidence architectural matches/);
  });

  it('keeps L1/L2 communities above the floor and boosts higher levels', async () => {
    const { tools } = makeTools([
      { text: 'L1 forecast subsystem', metadata: { communityId: 12, level: 1 }, distance: 0.6 },  // sim 0.4
      { text: 'L2 GFS umbrella',     metadata: { communityId: 7,  level: 2 }, distance: 0.6 },  // sim 0.4 -> boosted higher
      { text: 'L0 stray',            metadata: { communityId: 99, level: 0 }, distance: 0.5 }   // filtered
    ]);

    const result = await tools.searchArchitecture({ query: 'GFS forecast job', max_results: 5 });
    const text = result.content[0].text;

    // Only L1/L2 included
    expect(text).toContain('Community 7');
    expect(text).toContain('Community 12');
    expect(text).not.toContain('Community 99');

    // L2 ranked above L1 (boost factor 1 + 0.25*level)
    const idxL2 = text.indexOf('Community 7');
    const idxL1 = text.indexOf('Community 12');
    expect(idxL2).toBeGreaterThan(-1);
    expect(idxL1).toBeGreaterThan(-1);
    expect(idxL2).toBeLessThan(idxL1);
  });

  it('rejects results below the 0.2 similarity floor', async () => {
    const { tools } = makeTools([
      { text: 'L1 weak', metadata: { communityId: 1, level: 1 }, distance: 0.85 } // sim 0.15
    ]);

    const result = await tools.searchArchitecture({ query: 'anything' });
    expect(result.content[0].text).toMatch(/No high-confidence architectural matches/);
  });
});
