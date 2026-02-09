#!/usr/bin/env node

/**
 * benchmark_runner.js - Phase 24G Automated Benchmark Harness
 *
 * Runs 50 benchmark queries against 4 system configurations and
 * compares hit rate, latency, and result quality.
 *
 * Systems under test:
 *   1. Baseline: VectorDatabase.query (vector-only search_documentation)
 *   2. GGSR: GraphGuidedRetrieval.retrieve (graph neighborhood only)
 *   3. GGSR+Community: retrieve with community summaries enabled
 *   4. Full: All above + crossLanguageTrace
 *
 * Usage: node --input-type=module src/graphrag/evaluation/benchmark_runner.js
 *
 * @version 1.0.0
 * @phase Phase 24G
 */

import { readFileSync, writeFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { GraphDatabase } from '../../data/GraphDatabase.js';
import { VectorDatabase } from '../../data/VectorDatabase.js';
import { GGSRTraversalPrototypes } from '../GGSRTraversalPrototypes.js';
import { GraphGuidedRetrieval } from '../GraphGuidedRetrieval.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const CORPUS_PATH = join(__dirname, 'benchmark_corpus.json');
const RESULTS_PATH = join(__dirname, 'benchmark_results.json');
const CODE_COLLECTION = 'code-with-context-v8-0-0';
const COMMUNITY_COLLECTION = 'community-summaries';

// ---- System Configurations ----

class BenchmarkRunner {
  constructor() {
    this.graphDB = null;
    this.vectorDB = null;
    this.ggsr = null;
    this.retrieval = null;
    this.corpus = null;
    this.results = { systems: {}, perQuery: [], timestamp: new Date().toISOString() };
  }

  async init() {
    console.log('[INFO] Initializing benchmark runner...');

    // Load corpus
    this.corpus = JSON.parse(readFileSync(CORPUS_PATH, 'utf-8'));
    console.log(`[OK] Loaded ${this.corpus.queries.length} benchmark queries`);

    // Connect to services
    this.graphDB = new GraphDatabase({
      uri: 'bolt://localhost:7687',
      user: 'neo4j',
      password: 'gfsworkflow2025'
    });
    await this.graphDB.connect();

    this.vectorDB = new VectorDatabase();
    await this.vectorDB.connect();

    this.ggsr = new GGSRTraversalPrototypes(this.graphDB);

    // Retrieval WITHOUT community search
    this.retrievalLocal = new GraphGuidedRetrieval({
      dataAccess: { graphDB: this.graphDB, enrichGraphResults: async () => new Map(), vectorDB: null },
      ggsr: this.ggsr,
      vectorDB: null
    });

    // Retrieval WITH community search
    this.retrievalFull = new GraphGuidedRetrieval({
      dataAccess: { graphDB: this.graphDB, enrichGraphResults: async () => new Map(), vectorDB: this.vectorDB },
      ggsr: this.ggsr,
      vectorDB: this.vectorDB
    });

    console.log('[OK] All services connected');
  }

  /**
   * System 1: Baseline — vector-only search
   */
  async runBaseline(query) {
    const start = Date.now();
    try {
      const results = await this.vectorDB.query(CODE_COLLECTION, query.query, { nResults: 10 });
      const latencyMs = Date.now() - start;
      const texts = results.map(r => (r.text || '').toLowerCase());
      const hit = this._checkHit(query, texts);
      return { system: 'baseline', latencyMs, resultCount: results.length, hit, texts };
    } catch (err) {
      return { system: 'baseline', latencyMs: Date.now() - start, resultCount: 0, hit: false, error: err.message };
    }
  }

  /**
   * System 2: GGSR — graph neighborhood only (no community summaries)
   */
  async runGGSR(query) {
    const start = Date.now();
    try {
      if (!query.entity) {
        return { system: 'ggsr', latencyMs: Date.now() - start, resultCount: 0, hit: false, note: 'no entity' };
      }
      const ctx = await this.retrievalLocal.retrieve(query.entity, [query.entity], {
        tokenBudget: 4000, maxResults: 15, hops: 1
      });
      const latencyMs = Date.now() - start;
      const text = (ctx.ggsrSection || '').toLowerCase();
      const hit = this._checkHit(query, [text]);
      return { system: 'ggsr', latencyMs, resultCount: ctx.metadata?.ggsrCount || 0, hit, queryType: 'LOCAL' };
    } catch (err) {
      return { system: 'ggsr', latencyMs: Date.now() - start, resultCount: 0, hit: false, error: err.message };
    }
  }

  /**
   * System 3: GGSR + Community summaries
   */
  async runGGSRCommunity(query) {
    const start = Date.now();
    try {
      const ctx = await this.retrievalFull.retrieve(query.entity, [query.entity].filter(Boolean), {
        tokenBudget: 4000, maxResults: 15, hops: 1,
        query: query.query  // Enables query classification for community routing
      });
      const latencyMs = Date.now() - start;
      const allText = ((ctx.ggsrSection || '') + (ctx.communitySection || '')).toLowerCase();
      const hit = this._checkHit(query, [allText]);
      return {
        system: 'ggsr_community', latencyMs,
        resultCount: (ctx.metadata?.ggsrCount || 0) + (ctx.metadata?.communityHits || 0),
        hit, queryType: ctx.metadata?.queryType || 'LOCAL',
        communityHits: ctx.metadata?.communityHits || 0
      };
    } catch (err) {
      return { system: 'ggsr_community', latencyMs: Date.now() - start, resultCount: 0, hit: false, error: err.message };
    }
  }

  /**
   * System 4: Full — GGSR + Community + Cross-language trace
   */
  async runFull(query) {
    const start = Date.now();
    try {
      // Start with GGSR+Community
      const ctx = await this.retrievalFull.retrieve(query.entity, [query.entity].filter(Boolean), {
        tokenBudget: 4000, maxResults: 15, hops: 2,
        query: query.query
      });

      // Add cross-language trace for relevant queries
      let crossLangText = '';
      if (query.entity && (query.category === 'cross_language' || query.category === 'trace')) {
        try {
          const result = await this.ggsr.crossLanguageTrace(query.entity, { maxDepth: 3 });
          if (result && result.traces && result.traces.length > 0) {
            crossLangText = JSON.stringify(result).toLowerCase();
          }
        } catch {
          // Non-fatal
        }
      }

      const latencyMs = Date.now() - start;
      const allText = ((ctx.ggsrSection || '') + (ctx.communitySection || '') + crossLangText).toLowerCase();
      const hit = this._checkHit(query, [allText]);

      return {
        system: 'full', latencyMs,
        resultCount: (ctx.metadata?.ggsrCount || 0) + (ctx.metadata?.communityHits || 0),
        hit, queryType: ctx.metadata?.queryType || 'LOCAL',
        communityHits: ctx.metadata?.communityHits || 0,
        crossLangTraces: crossLangText.length > 0
      };
    } catch (err) {
      return { system: 'full', latencyMs: Date.now() - start, resultCount: 0, hit: false, error: err.message };
    }
  }

  /**
   * Check if expected entities appear in result text.
   */
  _checkHit(query, texts) {
    const allText = texts.join(' ');

    // For GLOBAL queries, check community keywords
    if (query.expectedCommunityKeywords) {
      const hits = query.expectedCommunityKeywords.filter(kw => allText.includes(kw.toLowerCase()));
      return hits.length >= Math.ceil(query.expectedCommunityKeywords.length / 2);
    }

    // For entity-based queries, check expectedInResults
    if (query.expectedInResults) {
      const hits = query.expectedInResults.filter(e => allText.includes(e.toLowerCase()));
      return hits.length > 0;
    }

    return false;
  }

  /**
   * Run all queries against all systems.
   */
  async runAll() {
    const queries = this.corpus.queries;
    const systemNames = ['baseline', 'ggsr', 'ggsr_community', 'full'];
    const systemResults = {};
    for (const s of systemNames) {
      systemResults[s] = { hits: 0, total: 0, latencies: [], errors: 0 };
    }

    console.log(`\n[INFO] Running ${queries.length} queries × 4 systems = ${queries.length * 4} evaluations...\n`);

    for (let i = 0; i < queries.length; i++) {
      const q = queries[i];
      const row = { id: q.id, category: q.category, query: q.query, results: {} };

      // Run all 4 systems
      const [baseline, ggsr, ggsrComm, full] = await Promise.all([
        this.runBaseline(q),
        this.runGGSR(q),
        this.runGGSRCommunity(q),
        this.runFull(q)
      ]);

      for (const r of [baseline, ggsr, ggsrComm, full]) {
        const sys = systemResults[r.system];
        sys.total++;
        if (r.hit) sys.hits++;
        sys.latencies.push(r.latencyMs);
        if (r.error) sys.errors++;
        row.results[r.system] = { hit: r.hit, latencyMs: r.latencyMs, resultCount: r.resultCount };
      }

      this.results.perQuery.push(row);

      // Progress
      const hitStr = [baseline, ggsr, ggsrComm, full].map(r => r.hit ? 'Y' : 'n').join('/');
      if ((i + 1) % 10 === 0 || i === queries.length - 1) {
        console.log(`[${String(i + 1).padStart(2)}/${queries.length}] ${q.id} ${q.category.padEnd(15)} hits: ${hitStr}`);
      }
    }

    // Compute aggregate metrics
    for (const [name, sys] of Object.entries(systemResults)) {
      const sorted = [...sys.latencies].sort((a, b) => a - b);
      this.results.systems[name] = {
        hitRate: sys.total > 0 ? (sys.hits / sys.total * 100).toFixed(1) + '%' : '0%',
        hits: sys.hits,
        total: sys.total,
        errors: sys.errors,
        p50LatencyMs: sorted[Math.floor(sorted.length * 0.5)] || 0,
        p95LatencyMs: sorted[Math.floor(sorted.length * 0.95)] || 0,
        avgLatencyMs: Math.round(sorted.reduce((a, b) => a + b, 0) / sorted.length)
      };
    }

    // Per-category breakdown
    this.results.byCategory = {};
    for (const cat of this.corpus.categories) {
      this.results.byCategory[cat] = {};
      for (const sys of systemNames) {
        const catQueries = this.results.perQuery.filter(r => r.category === cat);
        const hits = catQueries.filter(r => r.results[sys]?.hit).length;
        this.results.byCategory[cat][sys] = {
          hitRate: catQueries.length > 0 ? (hits / catQueries.length * 100).toFixed(0) + '%' : '0%',
          hits, total: catQueries.length
        };
      }
    }
  }

  /**
   * Print comparison report.
   */
  printReport() {
    console.log('\n' + '='.repeat(80));
    console.log('  Phase 24G: GraphRAG Benchmark Results');
    console.log('='.repeat(80));

    // Overall results
    console.log('\n## Overall Results\n');
    console.log('| System          | Hit Rate | P50 (ms) | P95 (ms) | Avg (ms) | Errors |');
    console.log('|-----------------|----------|----------|----------|----------|--------|');
    for (const [name, data] of Object.entries(this.results.systems)) {
      console.log(`| ${name.padEnd(15)} | ${String(data.hitRate).padEnd(8)} | ${String(data.p50LatencyMs).padEnd(8)} | ${String(data.p95LatencyMs).padEnd(8)} | ${String(data.avgLatencyMs).padEnd(8)} | ${String(data.errors).padEnd(6)} |`);
    }

    // Per-category breakdown
    console.log('\n## Per-Category Hit Rate\n');
    console.log('| Category        | Baseline | GGSR     | +Community | Full     |');
    console.log('|-----------------|----------|----------|------------|----------|');
    for (const [cat, data] of Object.entries(this.results.byCategory)) {
      console.log(`| ${cat.padEnd(15)} | ${String(data.baseline?.hitRate).padEnd(8)} | ${String(data.ggsr?.hitRate).padEnd(8)} | ${String(data.ggsr_community?.hitRate).padEnd(10)} | ${String(data.full?.hitRate).padEnd(8)} |`);
    }

    // Success criteria check
    console.log('\n## Go/No-Go Assessment\n');
    const full = this.results.systems.full;
    const baseline = this.results.systems.baseline;
    const fullRate = parseFloat(full?.hitRate) || 0;
    const baseRate = parseFloat(baseline?.hitRate) || 0;
    const improvement = (fullRate - baseRate).toFixed(1);

    console.log(`Baseline hit rate:    ${baseline?.hitRate}`);
    console.log(`Full GraphRAG rate:   ${full?.hitRate}`);
    console.log(`Improvement:          +${improvement}pp`);
    console.log(`P95 latency:          ${full?.p95LatencyMs}ms (target: <1000ms)`);

    const crossLang = this.results.byCategory.cross_language;
    const globalCat = this.results.byCategory.global;
    console.log(`Global query rate:    ${globalCat?.full?.hitRate} (target: ≥60%)`);
    console.log(`Cross-lang rate:      ${crossLang?.full?.hitRate} (target: ≥50%)`);

    const goNoGo = fullRate >= 60 && parseFloat(full?.p95LatencyMs) < 1000;
    console.log(`\n>>> GO/NO-GO: ${goNoGo ? '[GO] — Proceed to Phase 24H' : '[EVALUATE] — Review failure cases'}`);
    console.log('='.repeat(80));
  }

  /**
   * Save results to JSON.
   */
  saveResults() {
    writeFileSync(RESULTS_PATH, JSON.stringify(this.results, null, 2));
    console.log(`\n[OK] Results saved to ${RESULTS_PATH}`);
  }

  async close() {
    if (this.graphDB) await this.graphDB.close();
  }
}

// ---- Main ----
const runner = new BenchmarkRunner();
try {
  await runner.init();
  await runner.runAll();
  runner.printReport();
  runner.saveResults();
} catch (err) {
  console.error('[ERROR] Benchmark failed:', err);
} finally {
  await runner.close();
}
