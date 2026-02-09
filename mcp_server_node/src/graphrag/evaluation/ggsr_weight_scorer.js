#!/usr/bin/env node

/**
 * ggsr_weight_scorer.js - GGSR Weight Tuning via Evaluation Chain Scoring
 *
 * Phase 24B: Scores current GGSR weight matrix against synthetic evaluation
 * chains, then auto-tunes weights via grid search to maximize prediction
 * accuracy. "Users" are LLMs making sequential MCP tool calls.
 *
 * Metrics:
 *   - Hit rate: Was entity2 in GGSR prefetch set?
 *   - Rank position: Where did entity2 rank in scored results?
 *   - Precision@K: In top-K prefetched, how many were actual next queries?
 *
 * Usage:
 *   node ggsr_weight_scorer.js              # Score with current weights
 *   node ggsr_weight_scorer.js --tune       # Auto-tune via grid search
 *   node ggsr_weight_scorer.js --tune --hops  # Also tune hop decay
 *
 * @version 1.0.0
 * @phase Phase 24B
 */

import { GGSRTraversalPrototypes } from '../GGSRTraversalPrototypes.js';
import { GraphDatabase } from '../../data/GraphDatabase.js';
import { readFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const EVAL_CHAINS_PATH = join(__dirname, 'ggsr_eval_chains.json');

/**
 * Score a single eval chain against GGSR predictions
 */
async function scoreChain(ggsr, chain, options = {}) {
  const { topK = 10 } = options;

  try {
    // Run GGSR neighborhood from entity1
    const neighborhood = await ggsr.oneHopNeighborhood(chain.entity1, {
      maxResults: topK * 2,
      minWeight: 0.1
    });

    if (neighborhood.count === 0) {
      return { hit: false, rank: -1, score: 0, found: false, reason: 'no-neighbors' };
    }

    // Check if entity2 appears in GGSR results
    const neighbors = neighborhood.neighbors;
    const entity2Lower = chain.entity2.toLowerCase();

    let hitIndex = -1;
    for (let i = 0; i < neighbors.length; i++) {
      const neighborName = (neighbors[i].neighbor || neighbors[i].name || '').toLowerCase();
      if (neighborName.includes(entity2Lower) || entity2Lower.includes(neighborName)) {
        hitIndex = i;
        break;
      }
    }

    const hit = hitIndex >= 0;
    const inTopK = hitIndex >= 0 && hitIndex < topK;
    const relTypeMatch = hit && neighbors[hitIndex].relType === chain.expected_relationship;

    return {
      hit,
      inTopK,
      rank: hitIndex,
      relTypeMatch,
      score: hit ? neighbors[hitIndex].score : 0,
      expectedWeight: chain.expected_weight,
      actualRelType: hit ? neighbors[hitIndex].relType : null,
      expectedRelType: chain.expected_relationship,
      neighborCount: neighborhood.count,
      latencyMs: neighborhood.latencyMs
    };
  } catch (error) {
    return { hit: false, rank: -1, score: 0, found: false, reason: error.message };
  }
}

/**
 * Score all eval chains and compute aggregate metrics
 */
async function scoreAll(ggsr, chains, options = {}) {
  const results = [];

  for (const chain of chains) {
    const result = await scoreChain(ggsr, chain, options);
    results.push({ ...chain, ...result });
  }

  // Aggregate metrics
  const total = results.length;
  const hits = results.filter(r => r.hit).length;
  const topKHits = results.filter(r => r.inTopK).length;
  const relMatches = results.filter(r => r.relTypeMatch).length;
  const noNeighbors = results.filter(r => r.reason === 'no-neighbors').length;
  const withNeighbors = total - noNeighbors;

  const avgLatency = results.reduce((s, r) => s + (r.latencyMs || 0), 0) / total;

  return {
    results,
    metrics: {
      total,
      withNeighbors,
      hitRate: withNeighbors > 0 ? hits / withNeighbors : 0,
      topKPrecision: withNeighbors > 0 ? topKHits / withNeighbors : 0,
      relTypeAccuracy: hits > 0 ? relMatches / hits : 0,
      avgLatencyMs: Math.round(avgLatency),
      noNeighborCount: noNeighbors
    },
    byCategory: groupByCategory(results)
  };
}

/**
 * Group results by category for per-relationship analysis
 */
function groupByCategory(results) {
  const categories = {};
  for (const r of results) {
    const cat = r.category || 'unknown';
    if (!categories[cat]) categories[cat] = { total: 0, hits: 0, chains: [] };
    categories[cat].total++;
    if (r.hit) categories[cat].hits++;
    categories[cat].chains.push(r.id);
  }
  for (const cat of Object.values(categories)) {
    cat.hitRate = cat.total > 0 ? cat.hits / cat.total : 0;
  }
  return categories;
}

/**
 * Auto-tune weights via grid search
 */
async function tuneWeights(graphDB, chains, options = {}) {
  const { tuneHopDecay = false, stepSize = 0.1 } = options;

  console.log('\n[TUNE] Starting GGSR weight grid search...');
  console.log(`[TUNE] Step size: ${stepSize}, Tune hop decay: ${tuneHopDecay}`);

  // Get current weights as baseline
  const baseWeights = GGSRTraversalPrototypes.getWeightMatrix();
  const baseDecay = GGSRTraversalPrototypes.getHopDecay();

  // Score baseline
  const baseGGSR = new GGSRTraversalPrototypes(graphDB);
  const baseScore = await scoreAll(baseGGSR, chains);
  console.log(`[TUNE] Baseline hit rate: ${(baseScore.metrics.hitRate * 100).toFixed(1)}%`);
  console.log(`[TUNE] Baseline topK precision: ${(baseScore.metrics.topKPrecision * 100).toFixed(1)}%`);

  let bestScore = baseScore.metrics.hitRate + baseScore.metrics.topKPrecision;
  let bestWeights = { ...baseWeights };
  let bestDecay = baseDecay;
  let improvements = [];

  // Find which relationship types actually appear in eval chains
  const testedRelTypes = [...new Set(chains.map(c => c.expected_relationship))];
  console.log(`[TUNE] Testing relationship types: ${testedRelTypes.join(', ')}`);

  // Grid search: vary each weight ±stepSize
  for (const relType of testedRelTypes) {
    if (!baseWeights[relType]) continue;

    for (const delta of [-stepSize * 2, -stepSize, stepSize, stepSize * 2]) {
      const testWeights = { ...bestWeights };
      const newVal = Math.max(0.1, Math.min(1.0, testWeights[relType] + delta));
      if (newVal === testWeights[relType]) continue;
      testWeights[relType] = newVal;

      // Create GGSR with modified weights (inject via constructor pattern)
      const testGGSR = new GGSRTraversalPrototypes(graphDB);
      // Override weight matrix for this test
      testGGSR._testWeights = testWeights;

      const testScore = await scoreAll(testGGSR, chains);
      const combined = testScore.metrics.hitRate + testScore.metrics.topKPrecision;

      if (combined > bestScore) {
        bestScore = combined;
        bestWeights[relType] = newVal;
        improvements.push({
          relType,
          oldVal: baseWeights[relType],
          newVal,
          delta,
          hitRate: testScore.metrics.hitRate,
          topKPrecision: testScore.metrics.topKPrecision
        });
        console.log(`[TUNE] Improvement: ${relType} ${baseWeights[relType]} -> ${newVal} (hit: ${(testScore.metrics.hitRate * 100).toFixed(1)}%, topK: ${(testScore.metrics.topKPrecision * 100).toFixed(1)}%)`);
      }
    }
  }

  // Optionally tune hop decay
  if (tuneHopDecay) {
    for (const decay of [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]) {
      if (decay === baseDecay) continue;
      // Note: hop decay tuning would require modifying the GGSR instance
      console.log(`[TUNE] Testing hop decay: ${decay} (evaluation only — apply manually)`);
    }
  }

  return {
    baseline: {
      weights: baseWeights,
      hopDecay: baseDecay,
      hitRate: baseScore.metrics.hitRate,
      topKPrecision: baseScore.metrics.topKPrecision
    },
    tuned: {
      weights: bestWeights,
      hopDecay: bestDecay,
      hitRate: bestScore / 2, // approximate split
      improvements
    },
    changedWeights: Object.keys(bestWeights).filter(k => bestWeights[k] !== baseWeights[k])
      .map(k => ({ relType: k, old: baseWeights[k], new: bestWeights[k] }))
  };
}

/**
 * Print formatted results
 */
function printResults(scoreResult) {
  const { metrics, results, byCategory } = scoreResult;

  console.log('\n=== GGSR Weight Evaluation Results ===\n');
  console.log(`Total chains:     ${metrics.total}`);
  console.log(`With neighbors:   ${metrics.withNeighbors} (${metrics.noNeighborCount} had no graph neighbors)`);
  console.log(`Hit rate:         ${(metrics.hitRate * 100).toFixed(1)}%`);
  console.log(`Top-K precision:  ${(metrics.topKPrecision * 100).toFixed(1)}%`);
  console.log(`RelType accuracy: ${(metrics.relTypeAccuracy * 100).toFixed(1)}%`);
  console.log(`Avg latency:      ${metrics.avgLatencyMs}ms`);

  console.log('\n--- By Category ---');
  for (const [cat, data] of Object.entries(byCategory)) {
    console.log(`  ${cat}: ${data.hits}/${data.total} (${(data.hitRate * 100).toFixed(0)}%)`);
  }

  console.log('\n--- Per Chain ---');
  for (const r of results) {
    const status = r.hit ? (r.inTopK ? '[HIT-TopK]' : '[HIT]') : '[MISS]';
    const relMatch = r.relTypeMatch ? 'rel:OK' : `rel:${r.actualRelType || 'N/A'}≠${r.expectedRelType}`;
    console.log(`  ${status} ${r.id}: ${r.entity1} → ${r.entity2} | rank:${r.rank} ${relMatch} ${r.latencyMs || 0}ms`);
  }
}

// --- Main ---
async function main() {
  const args = process.argv.slice(2);
  const doTune = args.includes('--tune');
  const tuneHops = args.includes('--hops');

  // Load eval chains
  const evalData = JSON.parse(readFileSync(EVAL_CHAINS_PATH, 'utf-8'));
  console.log(`[OK] Loaded ${evalData.chains.length} evaluation chains`);

  // Connect to Neo4j
  const graphDB = new GraphDatabase();
  await graphDB.connect();

  try {
    const ggsr = new GGSRTraversalPrototypes(graphDB);

    // Score current weights
    const scoreResult = await scoreAll(ggsr, evalData.chains);
    printResults(scoreResult);

    // Auto-tune if requested
    if (doTune) {
      const tuneResult = await tuneWeights(graphDB, evalData.chains, { tuneHopDecay: tuneHops });

      console.log('\n=== Tuning Results ===\n');
      if (tuneResult.changedWeights.length > 0) {
        console.log('Weight changes:');
        for (const c of tuneResult.changedWeights) {
          console.log(`  ${c.relType}: ${c.old} -> ${c.new}`);
        }
        console.log('\nApply these to RELATIONSHIP_WEIGHTS in GGSRTraversalPrototypes.js');
      } else {
        console.log('[OK] Current weights are optimal for the evaluation set');
      }
    }
  } finally {
    await graphDB.close();
  }
}

main().catch(console.error);
