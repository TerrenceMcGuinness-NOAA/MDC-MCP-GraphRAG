#!/usr/bin/env node
/**
 * Backend Comparison Benchmark
 * ============================
 * Sends identical MCP tool calls to both the AWS (mdc-mcp-rag-aws) and
 * legacy (eib-mcp-gateway) servers, then scores each across 5 dimensions:
 *
 *   Score = 0.3×Latency + 0.3×Relevance + 0.2×DataCompleteness
 *         + 0.1×GraphRichness + 0.1×ErrorResilience
 *
 * Usage: node scripts/compare-backends.js [--verbose]
 */

const VERBOSE = process.argv.includes('--verbose');

// Server endpoints
const SERVERS = {
  aws: {
    name: 'mdc-mcp-rag-aws (OpenSearch + Neptune)',
    url: 'http://localhost:3000/mcp',
    headers: {}
  },
  legacy: {
    name: 'eib-mcp-gateway (ChromaDB + Neo4j)',
    url: 'https://xpjldqf6-18888.use.devtunnels.ms/mcp',
    headers: { 'Authorization': 'Bearer eib-mcp-gateway-token-2025' }
  }
};

// Test queries — same args sent to both servers
const TEST_QUERIES = [
  // Vector search tools
  {
    category: 'vector_search',
    tool: 'search_documentation',
    args: { query: 'data assimilation initialization', max_results: 10 },
    extractIds: r => extractDocIds(r),
    extractCount: r => countResults(r)
  },
  {
    category: 'vector_search',
    tool: 'search_documentation',
    args: { query: 'how does the forecast model handle sea ice', max_results: 10 },
    extractIds: r => extractDocIds(r),
    extractCount: r => countResults(r)
  },
  {
    category: 'vector_search',
    tool: 'search_ee2_standards',
    args: { query: 'error handling set -e requirements', max_results: 8 },
    extractIds: r => extractDocIds(r),
    extractCount: r => countResults(r)
  },
  {
    category: 'vector_search',
    tool: 'explain_with_context',
    args: { topic: 'Rocoto workflow manager XML configuration' },
    extractIds: r => [],
    extractCount: r => textLength(r)
  },
  // Graph traversal tools
  {
    category: 'graph_traversal',
    tool: 'find_callers_callees',
    args: { function_name: 'setuprad' },
    extractIds: r => extractNodeNames(r),
    extractCount: r => countNodes(r)
  },
  {
    category: 'graph_traversal',
    tool: 'trace_full_execution_chain',
    args: { start: 'JGLOBAL_FORECAST', direction: 'forward', max_depth: 5 },
    extractIds: r => extractNodeNames(r),
    extractCount: r => countNodes(r)
  },
  {
    category: 'graph_traversal',
    tool: 'find_dependencies',
    args: { target: 'scripts/exglobal_forecast.py', direction: 'both' },
    extractIds: r => extractNodeNames(r),
    extractCount: r => countNodes(r)
  },
  {
    category: 'graph_traversal',
    tool: 'find_env_dependencies',
    args: { variable_name: 'HOMEgfs' },
    extractIds: r => extractNodeNames(r),
    extractCount: r => countNodes(r)
  },
  // GGSR hybrid tools
  {
    category: 'ggsr_hybrid',
    tool: 'get_code_context',
    args: { symbol: 'setuprad', depth: 2 },
    extractIds: r => extractNodeNames(r),
    extractCount: r => textLength(r)
  },
  {
    category: 'ggsr_hybrid',
    tool: 'search_architecture',
    args: { query: 'ocean modeling subsystem' },
    extractIds: r => extractDocIds(r),
    extractCount: r => textLength(r)
  },
  {
    category: 'ggsr_hybrid',
    tool: 'get_change_impact',
    args: { symbol: 'exglobal_forecast', change_type: 'behavior' },
    extractIds: r => extractNodeNames(r),
    extractCount: r => countNodes(r)
  },
  {
    category: 'ggsr_hybrid',
    tool: 'trace_data_flow',
    args: { from_symbol: 'exglobal_atmos_analysis', max_depth: 5 },
    extractIds: r => extractNodeNames(r),
    extractCount: r => countNodes(r)
  },
  // Health / data completeness
  {
    category: 'health',
    tool: 'get_knowledge_base_status',
    args: { include_graph: true, include_vector: true },
    extractIds: r => [],
    extractCount: r => textLength(r)
  },
];

// ============================================================================
// Result extraction helpers
// ============================================================================

function getResultText(result) {
  try {
    if (!result) return '';
    if (typeof result === 'string') return result;
    if (result.content && Array.isArray(result.content)) {
      return result.content.map(c => c.text || '').join('\n');
    }
    if (result.content && typeof result.content === 'string') return result.content;
    return JSON.stringify(result);
  } catch { return ''; }
}

function extractDocIds(result) {
  const text = getResultText(result);
  // Extract document IDs, file paths, or source references
  const ids = new Set();
  // Match file paths
  const pathMatches = text.match(/(?:source|file|path)[:\s]+([^\s,\n]+)/gi) || [];
  pathMatches.forEach(m => {
    const path = m.replace(/^(?:source|file|path)[:\s]+/i, '').trim();
    if (path.length > 3) ids.add(path.toLowerCase());
  });
  // Match numbered results
  const numMatches = text.match(/\d+\.\s+\*\*([^*]+)\*\*/g) || [];
  numMatches.forEach(m => {
    const name = m.replace(/^\d+\.\s+\*\*/, '').replace(/\*\*$/, '').trim();
    if (name.length > 2) ids.add(name.toLowerCase());
  });
  // Fallback: extract any quoted strings
  const quoted = text.match(/`([^`]+)`/g) || [];
  quoted.forEach(m => {
    const val = m.replace(/`/g, '').trim();
    if (val.length > 3 && val.length < 100) ids.add(val.toLowerCase());
  });
  return [...ids];
}

function extractNodeNames(result) {
  const text = getResultText(result);
  const names = new Set();
  // Match function/subroutine/module names
  const patterns = [
    /(?:name|function|subroutine|module|script|program)[:\s]+`?([A-Za-z_]\w+)`?/gi,
    /\*\*([A-Za-z_]\w+)\*\*/g,
    /`([A-Za-z_]\w{2,})`/g,
  ];
  patterns.forEach(pat => {
    let m;
    while ((m = pat.exec(text)) !== null) {
      if (m[1] && m[1].length > 2 && m[1].length < 60) {
        names.add(m[1].toLowerCase());
      }
    }
  });
  return [...names];
}

function countResults(result) {
  const text = getResultText(result);
  // Count numbered items or bullet points
  const numbered = (text.match(/^\d+\./gm) || []).length;
  const bullets = (text.match(/^[-*•]/gm) || []).length;
  return Math.max(numbered, bullets, 1);
}

function countNodes(result) {
  const text = getResultText(result);
  const names = extractNodeNames(result);
  return names.length || 1;
}

function textLength(result) {
  return getResultText(result).length;
}

// ============================================================================
// MCP JSON-RPC caller
// ============================================================================

let requestId = 1;

async function callMcpTool(server, toolName, args) {
  const id = requestId++;
  const body = JSON.stringify({
    jsonrpc: '2.0',
    id,
    method: 'tools/call',
    params: { name: toolName, arguments: args }
  });

  const start = performance.now();
  try {
    // First send initialize
    const initBody = JSON.stringify({
      jsonrpc: '2.0',
      id: id * 1000,
      method: 'initialize',
      params: {
        protocolVersion: '2025-03-26',
        capabilities: {},
        clientInfo: { name: 'benchmark', version: '1.0.0' }
      }
    });

    const initResp = await fetch(server.url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...server.headers },
      body: initBody,
      signal: AbortSignal.timeout(15000)
    });

    // Get session header if present
    const sessionId = initResp.headers.get('mcp-session-id') || '';
    const toolHeaders = { 'Content-Type': 'application/json', ...server.headers };
    if (sessionId) toolHeaders['mcp-session-id'] = sessionId;

    // Now call the tool
    const resp = await fetch(server.url, {
      method: 'POST',
      headers: toolHeaders,
      body,
      signal: AbortSignal.timeout(60000)
    });

    const elapsed = performance.now() - start;
    const text = await resp.text();

    // Parse response — handle SSE or JSON
    let result = null;
    if (text.includes('event:') || text.includes('data:')) {
      // SSE format — extract last data line
      const dataLines = text.split('\n').filter(l => l.startsWith('data:'));
      for (const line of dataLines) {
        try {
          const parsed = JSON.parse(line.substring(5));
          if (parsed.result) result = parsed.result;
        } catch {}
      }
    } else {
      try {
        const parsed = JSON.parse(text);
        result = parsed.result || parsed;
      } catch {}
    }

    return { success: true, result, elapsed, error: null };
  } catch (err) {
    const elapsed = performance.now() - start;
    return { success: false, result: null, elapsed, error: err.message };
  }
}

// ============================================================================
// Scoring functions
// ============================================================================

function jaccard(setA, setB) {
  if (setA.length === 0 && setB.length === 0) return 1.0;
  const a = new Set(setA);
  const b = new Set(setB);
  const intersection = [...a].filter(x => b.has(x)).length;
  const union = new Set([...a, ...b]).size;
  return union === 0 ? 1.0 : intersection / union;
}

function computeScores(results) {
  const awsLatencies = [];
  const legacyLatencies = [];
  const overlaps = [];
  let awsErrors = 0, legacyErrors = 0;
  let awsTotalCount = 0, legacyTotalCount = 0;
  let awsGraphNodes = 0, legacyGraphNodes = 0;
  let graphQueries = 0;

  for (const r of results) {
    awsLatencies.push(r.aws.elapsed);
    legacyLatencies.push(r.legacy.elapsed);

    if (!r.aws.success) awsErrors++;
    if (!r.legacy.success) legacyErrors++;

    if (r.aws.success && r.legacy.success) {
      const awsIds = r.query.extractIds(r.aws.result);
      const legacyIds = r.query.extractIds(r.legacy.result);
      overlaps.push(jaccard(awsIds, legacyIds));

      const awsCount = r.query.extractCount(r.aws.result);
      const legacyCount = r.query.extractCount(r.legacy.result);
      awsTotalCount += awsCount;
      legacyTotalCount += legacyCount;

      if (r.query.category === 'graph_traversal' || r.query.category === 'ggsr_hybrid') {
        awsGraphNodes += awsCount;
        legacyGraphNodes += legacyCount;
        graphQueries++;
      }
    }
  }

  const n = results.length;

  // 1. Latency score (0-100, lower is better)
  const awsP50 = percentile(awsLatencies, 50);
  const legacyP50 = percentile(legacyLatencies, 50);
  const awsP95 = percentile(awsLatencies, 95);
  const legacyP95 = percentile(legacyLatencies, 95);
  // Score: ratio of opponent's latency to yours (capped at 100)
  const awsLatencyScore = Math.min(100, (legacyP50 / Math.max(awsP50, 1)) * 50);
  const legacyLatencyScore = Math.min(100, (awsP50 / Math.max(legacyP50, 1)) * 50);

  // 2. Relevance quality (based on result overlap — higher overlap = both are good)
  const avgOverlap = overlaps.length > 0 ? overlaps.reduce((a, b) => a + b, 0) / overlaps.length : 0;
  // Both get credit for overlap; the one with more results gets a bonus
  const awsRelevanceScore = Math.min(100, avgOverlap * 70 + (awsTotalCount >= legacyTotalCount ? 30 : 15));
  const legacyRelevanceScore = Math.min(100, avgOverlap * 70 + (legacyTotalCount >= awsTotalCount ? 30 : 15));

  // 3. Data completeness (based on total result volume)
  const maxCount = Math.max(awsTotalCount, legacyTotalCount, 1);
  const awsCompletenessScore = (awsTotalCount / maxCount) * 100;
  const legacyCompletenessScore = (legacyTotalCount / maxCount) * 100;

  // 4. Graph richness (for graph/GGSR queries)
  const maxGraph = Math.max(awsGraphNodes, legacyGraphNodes, 1);
  const awsGraphScore = (awsGraphNodes / maxGraph) * 100;
  const legacyGraphScore = (legacyGraphNodes / maxGraph) * 100;

  // 5. Error resilience
  const awsErrorScore = ((n - awsErrors) / n) * 100;
  const legacyErrorScore = ((n - legacyErrors) / n) * 100;

  // Composite score
  const awsComposite = 0.3 * awsLatencyScore + 0.3 * awsRelevanceScore +
                        0.2 * awsCompletenessScore + 0.1 * awsGraphScore +
                        0.1 * awsErrorScore;
  const legacyComposite = 0.3 * legacyLatencyScore + 0.3 * legacyRelevanceScore +
                           0.2 * legacyCompletenessScore + 0.1 * legacyGraphScore +
                           0.1 * legacyErrorScore;

  return {
    aws: {
      latency: { p50: awsP50, p95: awsP95, score: awsLatencyScore },
      relevance: { avgOverlap, totalCount: awsTotalCount, score: awsRelevanceScore },
      completeness: { totalCount: awsTotalCount, score: awsCompletenessScore },
      graphRichness: { nodeCount: awsGraphNodes, score: awsGraphScore },
      errorResilience: { errors: awsErrors, total: n, score: awsErrorScore },
      composite: awsComposite
    },
    legacy: {
      latency: { p50: legacyP50, p95: legacyP95, score: legacyLatencyScore },
      relevance: { avgOverlap, totalCount: legacyTotalCount, score: legacyRelevanceScore },
      completeness: { totalCount: legacyTotalCount, score: legacyCompletenessScore },
      graphRichness: { nodeCount: legacyGraphNodes, score: legacyGraphScore },
      errorResilience: { errors: legacyErrors, total: n, score: legacyErrorScore },
      composite: legacyComposite
    },
    overlap: avgOverlap,
    queryCount: n
  };
}

function percentile(arr, p) {
  const sorted = [...arr].sort((a, b) => a - b);
  const idx = Math.ceil((p / 100) * sorted.length) - 1;
  return sorted[Math.max(0, idx)] || 0;
}

// ============================================================================
// Report generator
// ============================================================================

function generateReport(results, scores) {
  const lines = [];
  lines.push('# Backend Comparison Report');
  lines.push(`\n**Date:** ${new Date().toISOString()}`);
  lines.push(`**Queries:** ${scores.queryCount}`);
  lines.push(`**AWS Server:** ${SERVERS.aws.name}`);
  lines.push(`**Legacy Server:** ${SERVERS.legacy.name}`);

  lines.push('\n## Composite Scores\n');
  lines.push('| Server | Score | Winner |');
  lines.push('|--------|-------|--------|');
  const awsWin = scores.aws.composite > scores.legacy.composite;
  const delta = Math.abs(scores.aws.composite - scores.legacy.composite).toFixed(1);
  lines.push(`| **AWS** | **${scores.aws.composite.toFixed(1)}** | ${awsWin ? `✅ +${delta}` : ''} |`);
  lines.push(`| **Legacy** | **${scores.legacy.composite.toFixed(1)}** | ${!awsWin ? `✅ +${delta}` : ''} |`);

  lines.push('\n## Dimension Breakdown\n');
  lines.push('| Dimension | Weight | AWS Score | Legacy Score | Winner |');
  lines.push('|-----------|--------|-----------|--------------|--------|');

  const dims = [
    ['Latency (P50)', 0.3, scores.aws.latency.score, scores.legacy.latency.score],
    ['Relevance Quality', 0.3, scores.aws.relevance.score, scores.legacy.relevance.score],
    ['Data Completeness', 0.2, scores.aws.completeness.score, scores.legacy.completeness.score],
    ['Graph Richness', 0.1, scores.aws.graphRichness.score, scores.legacy.graphRichness.score],
    ['Error Resilience', 0.1, scores.aws.errorResilience.score, scores.legacy.errorResilience.score],
  ];

  for (const [name, weight, awsS, legS] of dims) {
    const w = awsS > legS ? 'AWS' : awsS < legS ? 'Legacy' : 'Tie';
    lines.push(`| ${name} | ${weight} | ${awsS.toFixed(1)} | ${legS.toFixed(1)} | ${w} |`);
  }

  lines.push('\n## Latency Details\n');
  lines.push('| Metric | AWS | Legacy |');
  lines.push('|--------|-----|--------|');
  lines.push(`| P50 | ${scores.aws.latency.p50.toFixed(0)} ms | ${scores.legacy.latency.p50.toFixed(0)} ms |`);
  lines.push(`| P95 | ${scores.aws.latency.p95.toFixed(0)} ms | ${scores.legacy.latency.p95.toFixed(0)} ms |`);

  lines.push('\n## Per-Query Results\n');
  lines.push('| # | Tool | Category | AWS (ms) | Legacy (ms) | AWS OK | Legacy OK | Overlap |');
  lines.push('|---|------|----------|----------|-------------|--------|-----------|---------|');

  results.forEach((r, i) => {
    const awsOk = r.aws.success ? '✅' : '❌';
    const legOk = r.legacy.success ? '✅' : '❌';
    let overlap = '—';
    if (r.aws.success && r.legacy.success) {
      const awsIds = r.query.extractIds(r.aws.result);
      const legIds = r.query.extractIds(r.legacy.result);
      overlap = (jaccard(awsIds, legIds) * 100).toFixed(0) + '%';
    }
    lines.push(`| ${i + 1} | ${r.query.tool} | ${r.query.category} | ${r.aws.elapsed.toFixed(0)} | ${r.legacy.elapsed.toFixed(0)} | ${awsOk} | ${legOk} | ${overlap} |`);
  });

  // Error details
  const errors = results.filter(r => !r.aws.success || !r.legacy.success);
  if (errors.length > 0) {
    lines.push('\n## Errors\n');
    for (const r of errors) {
      if (!r.aws.success) lines.push(`- **AWS** ${r.query.tool}: ${r.aws.error}`);
      if (!r.legacy.success) lines.push(`- **Legacy** ${r.query.tool}: ${r.legacy.error}`);
    }
  }

  lines.push('\n## Methodology\n');
  lines.push('```');
  lines.push('Score = 0.3 × Latency + 0.3 × Relevance + 0.2 × DataCompleteness');
  lines.push('      + 0.1 × GraphRichness + 0.1 × ErrorResilience');
  lines.push('```');
  lines.push('- **Latency**: Ratio of opponent P50 to own P50 (faster = higher score)');
  lines.push('- **Relevance**: Jaccard overlap of extracted result IDs + volume bonus');
  lines.push('- **Data Completeness**: Ratio of total result volume to max');
  lines.push('- **Graph Richness**: Ratio of graph node counts for graph/GGSR queries');
  lines.push('- **Error Resilience**: Percentage of successful tool calls');

  return lines.join('\n');
}

// ============================================================================
// Main
// ============================================================================

async function main() {
  console.log('=== Backend Comparison Benchmark ===\n');
  console.log(`AWS:    ${SERVERS.aws.url}`);
  console.log(`Legacy: ${SERVERS.legacy.url}`);
  console.log(`Queries: ${TEST_QUERIES.length}\n`);

  const results = [];

  for (let i = 0; i < TEST_QUERIES.length; i++) {
    const q = TEST_QUERIES[i];
    process.stdout.write(`[${i + 1}/${TEST_QUERIES.length}] ${q.tool} (${q.category})...`);

    // Call both servers in parallel
    const [awsResult, legacyResult] = await Promise.all([
      callMcpTool(SERVERS.aws, q.tool, q.args),
      callMcpTool(SERVERS.legacy, q.tool, q.args),
    ]);

    const awsOk = awsResult.success ? '✅' : '❌';
    const legOk = legacyResult.success ? '✅' : '❌';
    console.log(` AWS:${awsResult.elapsed.toFixed(0)}ms${awsOk} Legacy:${legacyResult.elapsed.toFixed(0)}ms${legOk}`);

    if (VERBOSE) {
      if (awsResult.error) console.log(`  AWS error: ${awsResult.error}`);
      if (legacyResult.error) console.log(`  Legacy error: ${legacyResult.error}`);
    }

    results.push({ query: q, aws: awsResult, legacy: legacyResult });
  }

  console.log('\n=== Computing Scores ===\n');
  const scores = computeScores(results);

  console.log(`AWS Composite:    ${scores.aws.composite.toFixed(1)} / 100`);
  console.log(`Legacy Composite: ${scores.legacy.composite.toFixed(1)} / 100`);
  const winner = scores.aws.composite > scores.legacy.composite ? 'AWS' : 'Legacy';
  const delta = Math.abs(scores.aws.composite - scores.legacy.composite).toFixed(1);
  console.log(`\nWinner: ${winner} (+${delta} points)\n`);

  // Generate report
  const report = generateReport(results, scores);
  const reportPath = 'docs/backend-comparison-report.md';

  const fs = await import('fs');
  fs.writeFileSync(reportPath, report);
  console.log(`Report written to: ${reportPath}`);
}

main().catch(err => {
  console.error('Fatal:', err);
  process.exit(1);
});
