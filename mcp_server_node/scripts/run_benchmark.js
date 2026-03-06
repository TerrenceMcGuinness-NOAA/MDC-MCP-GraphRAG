#!/usr/bin/env node

/**
 * RAG Benchmark Harness with Regression Detection
 *
 * Loads a ground truth corpus, calls MCP tool handlers directly,
 * computes quality metrics (P@K, R@K, MRR, Coverage, Latency),
 * and detects regressions against prior runs.
 *
 * Usage:
 *   node scripts/run_benchmark.js                  # full benchmark
 *   node scripts/run_benchmark.js --dry-run         # validate corpus only
 *   node scripts/run_benchmark.js --category code_structure
 *   node scripts/run_benchmark.js --compare          # regression report only
 */

import { readFileSync, writeFileSync, readdirSync, mkdirSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'url';
import { dirname, join, resolve } from 'path';

// ---------------------------------------------------------------------------
// Paths
// ---------------------------------------------------------------------------
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const PROJECT_ROOT = resolve(__dirname, '..');
const CORPUS_PATH = join(PROJECT_ROOT, 'test', 'benchmark', 'ground_truth.json');
const RESULTS_DIR = join(PROJECT_ROOT, 'test', 'benchmark', 'results');

// ---------------------------------------------------------------------------
// CLI flags
// ---------------------------------------------------------------------------
const args = process.argv.slice(2);
const FLAG_DRY_RUN = args.includes('--dry-run');
const FLAG_COMPARE = args.includes('--compare');
const FLAG_CATEGORY = (() => {
  const idx = args.indexOf('--category');
  return idx !== -1 && args[idx + 1] ? args[idx + 1] : null;
})();

// ---------------------------------------------------------------------------
// Ground truth loader
// ---------------------------------------------------------------------------
function loadCorpus() {
  if (!existsSync(CORPUS_PATH)) {
    console.log(`[ERROR] Ground truth corpus not found: ${CORPUS_PATH}`);
    process.exit(1);
  }
  const raw = JSON.parse(readFileSync(CORPUS_PATH, 'utf-8'));
  const queries = [];
  for (const [catName, catQueries] of Object.entries(raw.categories)) {
    for (const q of catQueries) {
      queries.push({ ...q, category: catName });
    }
  }
  return { ...raw, _queries: queries };
}

// ---------------------------------------------------------------------------
// Metric helpers
// ---------------------------------------------------------------------------
function resultTextMatches(resultText, keyword) {
  return resultText.toLowerCase().includes(keyword.toLowerCase());
}

function extractResultTexts(toolResult) {
  // MCP format: { content: [{ type: 'text', text: '...' }] }
  if (toolResult && Array.isArray(toolResult.content)) {
    return toolResult.content
      .filter(c => c.type === 'text')
      .map(c => c.text);
  }
  if (typeof toolResult === 'string') return [toolResult];
  if (toolResult && typeof toolResult === 'object') {
    return [JSON.stringify(toolResult)];
  }
  return [];
}

function computeQueryMetrics(resultTexts, expectedResults, k) {
  const combined = resultTexts.join('\n');

  // Precision@K: fraction of expected keywords found in top-K text
  const matchedKeywords = expectedResults.filter(kw => resultTextMatches(combined, kw));
  const precisionAtK = expectedResults.length > 0
    ? matchedKeywords.length / Math.min(k, expectedResults.length)
    : 0;

  // Recall@K: fraction of expected keywords found
  const recallAtK = expectedResults.length > 0
    ? matchedKeywords.length / expectedResults.length
    : 0;

  // MRR: 1/rank of first text chunk containing any expected keyword
  let mrr = 0;
  for (let i = 0; i < resultTexts.length && i < k; i++) {
    const found = expectedResults.some(kw => resultTextMatches(resultTexts[i], kw));
    if (found) {
      mrr = 1 / (i + 1);
      break;
    }
  }

  // Coverage flag: at least one expected keyword matched
  const covered = matchedKeywords.length > 0;

  return { precision: clamp01(precisionAtK), recall: clamp01(recallAtK), mrr, covered, matchedKeywords };
}

function clamp01(v) { return Math.max(0, Math.min(1, v)); }

function percentile(sortedArr, p) {
  if (sortedArr.length === 0) return 0;
  const idx = Math.ceil(p / 100 * sortedArr.length) - 1;
  return sortedArr[Math.max(0, idx)];
}

function aggregateMetrics(queryResults) {
  if (queryResults.length === 0) {
    return { precision_at_k: 0, recall_at_k: 0, mrr: 0, coverage: 0, latency_p50_ms: 0, latency_p95_ms: 0 };
  }
  const avg = (arr) => arr.reduce((s, v) => s + v, 0) / arr.length;
  const latencies = queryResults.map(q => q.latency_ms).sort((a, b) => a - b);
  return {
    precision_at_k: round4(avg(queryResults.map(q => q.precision))),
    recall_at_k: round4(avg(queryResults.map(q => q.recall))),
    mrr: round4(avg(queryResults.map(q => q.mrr))),
    coverage: round4(queryResults.filter(q => q.covered).length / queryResults.length),
    latency_p50_ms: Math.round(percentile(latencies, 50)),
    latency_p95_ms: Math.round(percentile(latencies, 95)),
  };
}

function round4(v) { return Math.round(v * 10000) / 10000; }

// ---------------------------------------------------------------------------
// Tool module loader — instantiate tool classes, build handler map
// ---------------------------------------------------------------------------
async function buildToolMap() {
  // Dynamic imports (ES modules)
  const { WorkflowInfoTools } = await import(join(PROJECT_ROOT, 'src', 'tools', 'WorkflowInfoTools.js'));
  const { CodeAnalysisTools } = await import(join(PROJECT_ROOT, 'src', 'tools', 'CodeAnalysisTools.js'));
  const { SemanticSearchTools } = await import(join(PROJECT_ROOT, 'src', 'tools', 'SemanticSearchTools.js'));
  const { EE2ComplianceTools } = await import(join(PROJECT_ROOT, 'src', 'tools', 'EE2ComplianceTools.js'));
  const { OperationalTools } = await import(join(PROJECT_ROOT, 'src', 'tools', 'OperationalTools.js'));
  const { GraphRAGTools } = await import(join(PROJECT_ROOT, 'src', 'tools', 'GraphRAGTools.js'));

  // Lightweight shim: collects registered tool handlers
  const toolMap = new Map();
  const shim = {
    registerTool(name, _desc, _schema, handler) {
      toolMap.set(name, handler);
    }
  };

  // Instantiate modules (they'll lazily connect to DBs on first call)
  const modules = [
    new WorkflowInfoTools(),
    new CodeAnalysisTools(),
    new SemanticSearchTools(),
    new EE2ComplianceTools(),
    new OperationalTools(),
    new GraphRAGTools(),
  ];

  // Register all tools into our shim
  for (const mod of modules) {
    if (typeof mod.registerWith === 'function') {
      mod.registerWith(shim);
    } else if (typeof mod.registerTools === 'function') {
      mod.registerTools(shim);
    }
  }

  console.log(`[OK] Loaded ${toolMap.size} tool handlers from ${modules.length} modules`);
  return { toolMap, modules };
}

// ---------------------------------------------------------------------------
// Execute a single benchmark query
// ---------------------------------------------------------------------------
async function runQuery(toolMap, query, k) {
  const handler = toolMap.get(query.tool);
  if (!handler) {
    return {
      id: query.id,
      precision: 0,
      recall: 0,
      mrr: 0,
      covered: false,
      latency_ms: 0,
      matched_results: [],
      expected_results: query.expected_results,
      error: `Tool not found: ${query.tool}`,
    };
  }

  const start = performance.now();
  let toolResult;
  try {
    toolResult = await handler(query.tool_args);
  } catch (err) {
    const latency = Math.round(performance.now() - start);
    return {
      id: query.id,
      precision: 0,
      recall: 0,
      mrr: 0,
      covered: false,
      latency_ms: latency,
      matched_results: [],
      expected_results: query.expected_results,
      error: err.message,
    };
  }
  const latency = Math.round(performance.now() - start);

  const resultTexts = extractResultTexts(toolResult);
  const metrics = computeQueryMetrics(resultTexts, query.expected_results, k);

  return {
    id: query.id,
    precision: metrics.precision,
    recall: metrics.recall,
    mrr: metrics.mrr,
    covered: metrics.covered,
    latency_ms: latency,
    matched_results: metrics.matchedKeywords,
    expected_results: query.expected_results,
  };
}

// ---------------------------------------------------------------------------
// Results I/O
// ---------------------------------------------------------------------------
function saveResults(results) {
  if (!existsSync(RESULTS_DIR)) {
    mkdirSync(RESULTS_DIR, { recursive: true });
  }
  const ts = results.timestamp.replace(/:/g, '-').replace(/\.\d+Z$/, '');
  const filename = `${ts}.json`;
  const filepath = join(RESULTS_DIR, filename);
  writeFileSync(filepath, JSON.stringify(results, null, 2));
  return filepath;
}

function loadPreviousResult() {
  if (!existsSync(RESULTS_DIR)) return null;
  const files = readdirSync(RESULTS_DIR)
    .filter(f => f.endsWith('.json'))
    .sort();
  if (files.length === 0) return null;
  const latest = files[files.length - 1];
  try {
    return JSON.parse(readFileSync(join(RESULTS_DIR, latest), 'utf-8'));
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Regression detection
// ---------------------------------------------------------------------------
function detectRegressions(current, previous, config) {
  if (!previous) {
    return { compared_to: null, warnings: [], errors: [] };
  }

  const warnPct = config.regression_threshold_pct / 100;
  const errorPct = config.critical_threshold_pct / 100;
  const minCov = config.minimum_coverage_pct / 100;
  const warnings = [];
  const errors = [];

  const metricKeys = ['precision_at_k', 'recall_at_k', 'mrr', 'coverage'];
  const friendlyNames = {
    precision_at_k: 'P@K',
    recall_at_k: 'R@K',
    mrr: 'MRR',
    coverage: 'Coverage',
  };

  // Check overall + per-category
  const scopes = [
    { label: 'Overall', cur: current.overall, prev: previous.overall },
  ];
  for (const cat of Object.keys(current.categories)) {
    if (previous.categories && previous.categories[cat]) {
      scopes.push({ label: cat, cur: current.categories[cat], prev: previous.categories[cat] });
    }
  }

  for (const { label, cur, prev } of scopes) {
    for (const mk of metricKeys) {
      const curVal = cur[mk] || 0;
      const prevVal = prev[mk] || 0;
      if (prevVal === 0) continue;
      const drop = (prevVal - curVal) / prevVal;
      if (drop > errorPct) {
        errors.push(
          `${label} ${friendlyNames[mk]} dropped ${(drop * 100).toFixed(0)}% (${prevVal.toFixed(2)} -> ${curVal.toFixed(2)})`
        );
      } else if (drop > warnPct) {
        warnings.push(
          `${label} ${friendlyNames[mk]} dropped ${(drop * 100).toFixed(0)}% (${prevVal.toFixed(2)} -> ${curVal.toFixed(2)})`
        );
      }
    }
    // Coverage floor check
    if ((cur.coverage || 0) < minCov) {
      errors.push(`${label} Coverage ${(cur.coverage * 100).toFixed(0)}% below minimum ${config.minimum_coverage_pct}%`);
    }
  }

  return { compared_to: previous.timestamp, warnings, errors };
}

// ---------------------------------------------------------------------------
// Formatted console output
// ---------------------------------------------------------------------------
function padRight(s, len) { return (s + ' '.repeat(len)).slice(0, len); }

function printCategoryLine(label, metrics) {
  const cov = `${Math.round(metrics.coverage * 100)}%`;
  console.log(
    `[OK] ${padRight(label + ':', 20)}` +
    `P@5=${metrics.precision_at_k.toFixed(2)}  ` +
    `R@5=${metrics.recall_at_k.toFixed(2)}  ` +
    `MRR=${metrics.mrr.toFixed(2)}  ` +
    `Cov=${padRight(cov, 5)} ` +
    `P50=${metrics.latency_p50_ms}ms`
  );
}

function printRegressionReport(regression) {
  if (!regression.compared_to) {
    console.log('[OK] No previous result found for regression comparison');
    return;
  }
  console.log(`[OK] Compared to: ${regression.compared_to}`);
  for (const w of regression.warnings) {
    console.log(`[WARN] Regression: ${w}`);
  }
  for (const e of regression.errors) {
    console.log(`[ERROR] Regression: ${e}`);
  }
  if (regression.warnings.length === 0 && regression.errors.length === 0) {
    console.log('[OK] No regressions detected');
  }
}

function printComparisonTable(current, previous) {
  if (!previous) {
    console.log('[OK] Only one result available. Run benchmark again to enable comparison.');
    return;
  }

  const metricKeys = ['precision_at_k', 'recall_at_k', 'mrr', 'coverage'];
  const short = { precision_at_k: 'P@K', recall_at_k: 'R@K', mrr: 'MRR', coverage: 'Cov' };
  const allCats = ['Overall', ...Object.keys(current.categories)];

  // Header
  const hdr = padRight('Category', 20) +
    metricKeys.map(m => padRight(short[m], 18)).join('');
  console.log('');
  console.log(hdr);
  console.log('-'.repeat(hdr.length));

  for (const cat of allCats) {
    const cur = cat === 'Overall' ? current.overall : current.categories[cat];
    const prev = cat === 'Overall' ? previous.overall : (previous.categories || {})[cat];
    let line = padRight(cat, 20);
    for (const mk of metricKeys) {
      const cv = (cur && cur[mk]) || 0;
      const pv = (prev && prev[mk]) || 0;
      const delta = cv - pv;
      const sign = delta >= 0 ? '+' : '';
      line += padRight(`${cv.toFixed(2)} (${sign}${delta.toFixed(2)})`, 18);
    }
    console.log(line);
  }
  console.log('');
}

// ---------------------------------------------------------------------------
// --compare mode: show regression report from last two results
// ---------------------------------------------------------------------------
function runCompareOnly() {
  if (!existsSync(RESULTS_DIR)) {
    console.log('[ERROR] No results directory found');
    process.exit(1);
  }
  const files = readdirSync(RESULTS_DIR).filter(f => f.endsWith('.json')).sort();
  if (files.length < 2) {
    console.log('[ERROR] Need at least two result files for comparison');
    process.exit(1);
  }
  const current = JSON.parse(readFileSync(join(RESULTS_DIR, files[files.length - 1]), 'utf-8'));
  const previous = JSON.parse(readFileSync(join(RESULTS_DIR, files[files.length - 2]), 'utf-8'));
  const corpus = loadCorpus();

  console.log(`[OK] Comparing: ${files[files.length - 1]} vs ${files[files.length - 2]}`);
  const regression = detectRegressions(current, previous, corpus.metrics_config);
  printComparisonTable(current, previous);
  printRegressionReport(regression);
  process.exit(regression.errors.length > 0 ? 1 : 0);
}

// ---------------------------------------------------------------------------
// --dry-run mode: validate corpus and print query plan
// ---------------------------------------------------------------------------
function runDryRun(corpus) {
  const queries = corpus._queries;
  const filtered = FLAG_CATEGORY
    ? queries.filter(q => q.category === FLAG_CATEGORY)
    : queries;

  if (FLAG_CATEGORY && filtered.length === 0) {
    console.log(`[ERROR] Unknown category: ${FLAG_CATEGORY}`);
    const cats = [...new Set(queries.map(q => q.category))].sort();
    console.log(`[OK] Available categories: ${cats.join(', ')}`);
    process.exit(1);
  }

  console.log(`[OK] Ground truth v${corpus.version} — ${filtered.length} queries`);
  console.log(`[OK] Metrics config: K=${corpus.metrics_config.k}, ` +
    `warn=${corpus.metrics_config.regression_threshold_pct}%, ` +
    `error=${corpus.metrics_config.critical_threshold_pct}%, ` +
    `min_cov=${corpus.metrics_config.minimum_coverage_pct}%`);
  console.log('');

  const byCategory = {};
  for (const q of filtered) {
    (byCategory[q.category] ||= []).push(q);
  }

  for (const [cat, qs] of Object.entries(byCategory).sort()) {
    console.log(`[OK] ${cat} (${qs.length} queries):`);
    for (const q of qs) {
      const argsStr = JSON.stringify(q.tool_args);
      const truncArgs = argsStr.length > 60 ? argsStr.slice(0, 57) + '...' : argsStr;
      console.log(`     ${q.id}  ${q.tool}(${truncArgs})  expects ${q.expected_results.length} keywords`);
    }
  }

  console.log('');
  const tools = [...new Set(filtered.map(q => q.tool))].sort();
  console.log(`[OK] Tools required: ${tools.join(', ')}`);
  console.log('[OK] Dry run complete — no tools were called');
}

// ---------------------------------------------------------------------------
// Main benchmark run
// ---------------------------------------------------------------------------
async function runBenchmark() {
  const corpus = loadCorpus();
  const k = corpus.metrics_config.k;
  let queries = corpus._queries;

  if (FLAG_CATEGORY) {
    queries = queries.filter(q => q.category === FLAG_CATEGORY);
    if (queries.length === 0) {
      console.log(`[ERROR] Unknown category: ${FLAG_CATEGORY}`);
      process.exit(1);
    }
  }

  const categoryNames = [...new Set(queries.map(q => q.category))].sort();
  console.log(`[OK] Loading ground truth corpus: ${queries.length} queries across ${categoryNames.length} categories`);

  // Build tool map from live modules
  console.log('[OK] Connecting to databases...');
  const { toolMap, modules } = await buildToolMap();

  // Verify required tools exist
  const requiredTools = [...new Set(queries.map(q => q.tool))];
  const missing = requiredTools.filter(t => !toolMap.has(t));
  if (missing.length > 0) {
    console.log(`[WARN] Missing tools (queries will score 0): ${missing.join(', ')}`);
  }

  // Execute benchmark
  console.log(`[OK] Running benchmark (K=${k})...`);
  const queryResults = [];
  let completed = 0;
  for (const q of queries) {
    const result = await runQuery(toolMap, q, k);
    queryResults.push(result);
    completed++;
    if (completed % 10 === 0 || completed === queries.length) {
      process.stdout.write(`\r[OK] Progress: ${completed}/${queries.length}`);
    }
  }
  console.log('');

  // Aggregate per-category
  const categories = {};
  for (const cat of categoryNames) {
    const catResults = queryResults.filter(q => {
      const query = queries.find(oq => oq.id === q.id);
      return query && query.category === cat;
    });
    categories[cat] = aggregateMetrics(catResults);
  }

  // Aggregate overall
  const overall = aggregateMetrics(queryResults);

  // Print per-category results
  for (const cat of categoryNames) {
    printCategoryLine(cat, categories[cat]);
  }
  printCategoryLine('Overall', overall);

  // Build output
  const now = new Date().toISOString();
  const previous = loadPreviousResult();
  const regression = detectRegressions(
    { overall, categories },
    previous,
    corpus.metrics_config
  );

  const output = {
    timestamp: now,
    version: '1.0.0',
    corpus_version: corpus.version,
    total_queries: queries.length,
    overall,
    categories,
    queries: queryResults.map(qr => ({
      id: qr.id,
      precision: qr.precision,
      recall: qr.recall,
      mrr: qr.mrr,
      latency_ms: qr.latency_ms,
      matched_results: qr.matched_results,
      expected_results: qr.expected_results,
      ...(qr.error ? { error: qr.error } : {}),
    })),
    regression,
  };

  // Save results
  const filepath = saveResults(output);
  console.log(`[OK] Results saved to ${filepath}`);

  // Print regression report
  if (regression.compared_to) {
    printComparisonTable({ overall, categories }, previous);
  }
  printRegressionReport(regression);

  // Log any per-query errors
  const errQueries = queryResults.filter(q => q.error);
  if (errQueries.length > 0) {
    console.log(`[WARN] ${errQueries.length} queries had errors:`);
    for (const eq of errQueries) {
      console.log(`  ${eq.id}: ${eq.error}`);
    }
  }

  // Cleanly close database connections so the process can exit
  for (const mod of modules) {
    if (mod.dataAccess && typeof mod.dataAccess.close === 'function') {
      await mod.dataAccess.close().catch(() => {});
    }
  }

  // Exit code: 1 if critical regressions
  process.exit(regression.errors.length > 0 ? 1 : 0);
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------
async function main() {
  try {
    if (FLAG_COMPARE) {
      runCompareOnly();
      return;
    }

    const corpus = loadCorpus();

    if (FLAG_DRY_RUN) {
      runDryRun(corpus);
      return;
    }

    await runBenchmark();
  } catch (err) {
    console.log(`[ERROR] Benchmark failed: ${err.message}`);
    if (process.env.DEBUG) {
      console.error(err.stack);
    }
    process.exit(1);
  }
}

main();
