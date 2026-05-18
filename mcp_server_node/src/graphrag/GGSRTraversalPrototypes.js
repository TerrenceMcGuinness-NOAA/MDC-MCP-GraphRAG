#!/usr/bin/env node

/**
 * GGSRTraversalPrototypes.js - Graph-Guided Speculative Retrieval Traversal
 *
 * Implements weighted neighborhood traversal for GGSR (Phase 24A acceleration).
 * Provides 1-hop and 2-hop Cypher queries with relationship type weights and
 * hop decay, enabling anticipatory context loading for RAG queries.
 *
 * Weight Matrix (from Phase 24 consolidated architecture):
 *   CALLS=1.0, SOURCES=0.95, CALLED_BY=0.9, DEPENDS_ON=0.8,
 *   IMPORTS=0.7, USES=0.7, DOC_REFERENCES=0.6, SAME_DIRECTORY=0.4,
 *   AUTHORED_BY=0.3, EXECUTES=1.0
 *
 * Hop Decay: 0.5× per additional hop (max 2-hop)
 *
 * @version 1.0.0
 * @phase Phase 28A (accelerates Phase 24A)
 * @author Terry McGuinness + AI Assistants
 * @date 2026-02-09
 */

// Relationship weight matrix per Phase 24 spec (Phase 34C: +4 NCEPLIBS types)
const RELATIONSHIP_WEIGHTS = {
  CALLS:              1.0,
  EXECUTES:           1.0,
  SOURCES:            0.95,
  INVOKES:            0.9,
  CALLED_BY:          0.9,
  DEPENDS_ON:         0.8,
  DEPENDS_ON_ENV:     0.8,
  IMPORTS:            0.7,
  USES:               0.7,
  INHERITS:           0.7,
  DEFINES:            0.65,
  PROVIDED_BY:        0.6,   // Phase 34C: links Fortran USE → NCEPLIBS ExternalLibrary
  EXPORTS:            0.6,
  DOC_REFERENCES:     0.6,
  DOC_DESCRIBES:      0.55,
  TRANSITIVELY_DEPENDS: 0.5, // Phase 34C: indirect library deps (nemsio→w3emc)
  HAS_METHOD:         0.5,
  CONTAINS:           0.5,
  SETS:               0.5,
  DOCUMENTED_BY:      0.4,   // Phase 34C: links graph nodes → ChromaDB docs
  SAME_DIRECTORY:     0.4,
  BUILT_BY:           0.35,
  BUILD_ORCHESTRATES: 0.35,
  REQUIRES_VERSION:   0.3,   // Phase 34C: platform version constraints
  AUTHORED:           0.3,
  AUTHORED_BY:        0.3,
  CONTRIBUTED_TO:     0.3
};

const HOP_DECAY = 0.5;
const BRIDGE_DECAY_OVERRIDE = 0.8; // Phase 24F: reduced penalty for cross-language bridge hops
const DEFAULT_TOKEN_BUDGET = 4000;

// Phase 24F: Language label categories for bridge detection
const SHELL_LABELS = new Set(['ShellScript', 'File', 'CodeFile']);
const FORTRAN_LABELS = new Set(['FortranProgram', 'FortranSubroutine', 'FortranFunction', 'FortranModule']);
const PYTHON_LABELS = new Set(['PythonFunction', 'PythonModule', 'PythonClass']);

function isLanguageBridge(prevLabel, currLabel) {
  const toLang = (label) => SHELL_LABELS.has(label) ? 'shell' :
    FORTRAN_LABELS.has(label) ? 'fortran' :
    PYTHON_LABELS.has(label) ? 'python' : 'other';
  const prev = toLang(prevLabel);
  const curr = toLang(currLabel);
  return prev !== curr && prev !== 'other' && curr !== 'other';
}

export class GGSRTraversalPrototypes {
  constructor(graphDB) {
    this.graphDB = graphDB;
  }

  /**
   * 1-hop weighted neighborhood traversal
   * Returns neighbors scored by relationship weight
   *
   * @param {string} entityName - Node name to traverse from
   * @param {object} options - Traversal options
   * @returns {Promise<object>} Weighted neighborhood results with latency
   */
  async oneHopNeighborhood(entityName, options = {}) {
    const {
      maxResults = 25,
      minWeight = 0.3,
      tokenBudget = DEFAULT_TOKEN_BUDGET
    } = options;

    const startTime = Date.now();
    const limitInt = Math.floor(maxResults * 2);

    const cypher = `
      MATCH (n)-[r]-(hop1)
      WHERE n.name =~ $pattern
      RETURN n.name AS source,
             labels(n) AS sourceLabels,
             type(r) AS relType,
             hop1.name AS neighbor,
             labels(hop1) AS neighborLabels,
             hop1.filepath AS neighborPath
      LIMIT ${limitInt}
    `;

    const { pattern, fileType, baseName } = this._buildFlexiblePattern(entityName);
    const results = await this.graphDB.query(cypher, {
      pattern
    });

    const scored = results
      .map(r => ({
        source: r.source,
        neighbor: r.neighbor,
        neighborPath: r.neighborPath,
        relType: r.relType,
        neighborLabels: r.neighborLabels,
        weight: RELATIONSHIP_WEIGHTS[r.relType] || 0.3,
        hop: 1,
        score: RELATIONSHIP_WEIGHTS[r.relType] || 0.3
      }))
      .filter(r => r.score >= minWeight)
      .sort((a, b) => b.score - a.score)
      .slice(0, maxResults);

    const latencyMs = Date.now() - startTime;

    return {
      entity: entityName,
      baseName,
      fileType,
      hops: 1,
      neighbors: scored,
      count: scored.length,
      latencyMs,
      meetsTarget: latencyMs < 100
    };
  }

  /**
   * 2-hop weighted neighborhood traversal with hop decay
   * First hop scored at full weight, second hop at weight × HOP_DECAY
   *
   * @param {string} entityName - Node name to traverse from
   * @param {object} options - Traversal options
   * @returns {Promise<object>} Weighted 2-hop neighborhood with latency
   */
  async twoHopNeighborhood(entityName, options = {}) {
    const {
      maxResults = 50,
      minWeight = 0.2,
      tokenBudget = DEFAULT_TOKEN_BUDGET
    } = options;

    const startTime = Date.now();
    const limitInt = Math.floor(maxResults * 3);

    const cypher = `
      MATCH (n)-[r1]-(hop1)
      WHERE n.name =~ $pattern
      OPTIONAL MATCH (hop1)-[r2]-(hop2)
      WHERE hop2 <> n
      RETURN n.name AS source,
             type(r1) AS rel1Type,
             hop1.name AS hop1Name,
             labels(hop1) AS hop1Labels,
             hop1.filepath AS hop1Path,
             type(r2) AS rel2Type,
             hop2.name AS hop2Name,
             labels(hop2) AS hop2Labels,
             hop2.filepath AS hop2Path
      LIMIT ${limitInt}
    `;

    const { pattern, fileType, baseName } = this._buildFlexiblePattern(entityName);
    const results = await this.graphDB.query(cypher, { pattern });

    // Deduplicate and score
    const neighborMap = new Map();

    for (const r of results) {
      // Score hop-1 neighbor
      const hop1Key = r.hop1Name;
      if (hop1Key && !neighborMap.has(hop1Key)) {
        const weight1 = RELATIONSHIP_WEIGHTS[r.rel1Type] || 0.3;
        neighborMap.set(hop1Key, {
          name: r.hop1Name,
          path: r.hop1Path,
          labels: r.hop1Labels,
          relType: r.rel1Type,
          hop: 1,
          weight: weight1,
          score: weight1
        });
      }

      // Score hop-2 neighbor with decay
      if (r.hop2Name && r.hop2Name !== entityName) {
        const hop2Key = r.hop2Name;
        const weight1 = RELATIONSHIP_WEIGHTS[r.rel1Type] || 0.3;
        const weight2 = RELATIONSHIP_WEIGHTS[r.rel2Type] || 0.3;
        const decayedScore = weight1 * weight2 * HOP_DECAY;

        if (!neighborMap.has(hop2Key) || neighborMap.get(hop2Key).score < decayedScore) {
          neighborMap.set(hop2Key, {
            name: r.hop2Name,
            path: r.hop2Path,
            labels: r.hop2Labels,
            relType: `${r.rel1Type}→${r.rel2Type}`,
            hop: 2,
            weight: weight2,
            score: decayedScore
          });
        }
      }
    }

    const scored = Array.from(neighborMap.values())
      .filter(n => n.score >= minWeight)
      .sort((a, b) => b.score - a.score)
      .slice(0, maxResults);

    const latencyMs = Date.now() - startTime;

    return {
      entity: entityName,
      baseName,
      fileType,
      hops: 2,
      neighbors: scored,
      hop1Count: scored.filter(n => n.hop === 1).length,
      hop2Count: scored.filter(n => n.hop === 2).length,
      count: scored.length,
      latencyMs,
      meetsTarget: latencyMs < 100
    };
  }

  /**
   * Fortran-specific weighted traversal for CALLS/USES relationships
   * Weights: CALLS=1.0, USES=0.7, EXECUTES=1.0
   *
   * @param {string} entityName - Fortran entity name
   * @param {number} maxDepth - Max traversal depth (1-5)
   * @returns {Promise<object>} Weighted Fortran call chain
   */
  async fortranWeightedTraversal(entityName, maxDepth = 3) {
    const startTime = Date.now();
    const depthInt = Math.min(Math.max(parseInt(maxDepth, 10) || 3, 1), 5);

    // CALLS chain with weights
    const callsCypher = `
      MATCH (start)
      WHERE (start:FortranSubroutine OR start:FortranFunction OR start:FortranProgram)
        AND start.name =~ $pattern
      MATCH path = (start)-[:CALLS*1..${depthInt}]->(called)
      RETURN start.name AS source,
             called.name AS target,
             called.filepath AS targetPath,
             labels(called)[0] AS targetType,
             length(path) AS depth
      ORDER BY length(path)
    `;

    // USES chain with weights
    const usesCypher = `
      MATCH (user)-[:USES]->(mod:FortranModule)
      WHERE user.name =~ $pattern
      RETURN user.name AS source,
             mod.name AS target,
             mod.filepath AS targetPath,
             'FortranModule' AS targetType,
             1 AS depth
    `;

    const { pattern, fileType, baseName } = this._buildFlexiblePattern(entityName);

    const [callsResults, usesResults] = await Promise.all([
      this.graphDB.query(callsCypher, { pattern }),
      this.graphDB.query(usesCypher, { pattern })
    ]);

    // Apply weights with hop decay
    const weightedCalls = callsResults.map(r => ({
      ...r,
      relType: 'CALLS',
      weight: RELATIONSHIP_WEIGHTS.CALLS,
      score: RELATIONSHIP_WEIGHTS.CALLS * Math.pow(HOP_DECAY, r.depth - 1)
    }));

    const weightedUses = usesResults.map(r => ({
      ...r,
      relType: 'USES',
      weight: RELATIONSHIP_WEIGHTS.USES,
      score: RELATIONSHIP_WEIGHTS.USES
    }));

    const combined = [...weightedCalls, ...weightedUses]
      .sort((a, b) => b.score - a.score);

    const latencyMs = Date.now() - startTime;

    return {
      entity: entityName,
      baseName,
      fileType: fileType || 'fortran',
      calls: weightedCalls,
      uses: weightedUses,
      combined,
      callCount: weightedCalls.length,
      usesCount: weightedUses.length,
      latencyMs,
      meetsTarget: latencyMs < 100
    };
  }

  /**
   * Score an array of raw graph results with GGSR weights
   * Works for any relationship type — used by all CodeAnalysisTools
   *
   * @param {Array} results - Raw graph results with relType or relationship field
   * @param {object} options - Scoring options
   * @returns {Array} Results augmented with weight and score fields, sorted by score
   */
  scoreResults(results, options = {}) {
    const { hopField = 'depth', defaultHop = 1 } = options;

    return results
      .map(r => {
        const relType = r.relType || r.relationship || r.type || 'UNKNOWN';
        const hop = r[hopField] || defaultHop;
        const weight = RELATIONSHIP_WEIGHTS[relType] || 0.3;
        // Phase 24F: Use reduced decay for cross-language bridge hops
        const prevLabel = r.sourceLabel || r.prevLabel;
        const currLabel = r.targetLabel || r.targetType;
        const decay = (prevLabel && currLabel && isLanguageBridge(prevLabel, currLabel))
          ? BRIDGE_DECAY_OVERRIDE : HOP_DECAY;
        const score = weight * Math.pow(decay, hop - 1);
        return { ...r, relType, weight, score, hop };
      })
      .sort((a, b) => b.score - a.score);
  }

  /**
   * Format scored results as a markdown table for tool output
   *
   * @param {Array} scored - Results from scoreResults()
   * @param {object} options - Formatting options
   * @returns {string} Markdown table
   */
  formatWeightedTable(scored, options = {}) {
    const { maxRows = 20, nameField = 'name', fileType = null } = options;
    if (!scored || scored.length === 0) return '';

    let md = `\n## GGSR Weighted Analysis\n`;
    if (fileType) md += `*Source type: ${fileType}*\n`;
    md += `\n| Entity | Relationship | Weight | Score | Hop |\n`;
    md += `|--------|-------------|--------|-------|-----|\n`;

    for (const entry of scored.slice(0, maxRows)) {
      const name = entry[nameField] || entry.target || entry.neighbor || entry.name || 'unknown';
      md += `| \`${name}\` | ${entry.relType} | ${entry.weight} | ${entry.score.toFixed(3)} | ${entry.hop} |\n`;
    }
    if (scored.length > maxRows) {
      md += `\n*... and ${scored.length - maxRows} more weighted results*\n`;
    }
    return md;
  }

  /**
   * Get the static weight matrix for external consumers
   * @returns {object} Relationship weight configuration
   */
  static getWeightMatrix() {
    return { ...RELATIONSHIP_WEIGHTS };
  }

  /**
   * Get hop decay factor
   * @returns {number} Hop decay multiplier
   */
  static getHopDecay() {
    return HOP_DECAY;
  }

  /**
   * Estimate token count for a text string
   * Uses word-count heuristic: tokens ≈ words × 1.3
   * Accurate within ~10% for English code/documentation
   *
   * @param {string} text - Text to estimate tokens for
   * @returns {number} Estimated token count
   */
  static estimateTokens(text) {
    if (!text) return 0;
    const words = text.split(/\s+/).filter(w => w.length > 0).length;
    return Math.ceil(words * 1.3);
  }

  /**
   * Estimate tokens for a GGSR neighbor result row (table format)
   * Each row: "| `name` | relType | weight | score | hop |" ≈ 15-25 tokens
   * @private
   */
  static _estimateRowTokens(neighbor) {
    const name = neighbor.name || neighbor.neighbor || '';
    return Math.ceil(15 + (name.length / 4));
  }

  /**
   * Budget-aware neighborhood traversal
   * Runs GGSR traversal and truncates results to fit within token budget.
   * Returns highest-scored neighbors first, stops when budget exhausted.
   *
   * @param {string} entityName - Node name to traverse from
   * @param {object} options - Traversal options
   * @param {number} options.tokenBudget - Max tokens for GGSR context (default: 4000)
   * @param {number} options.maxResults - Max neighbors to consider (default: 50)
   * @param {number} options.hops - 1 or 2 hop traversal (default: 1)
   * @returns {Promise<object>} Budget-constrained results with token accounting
   */
  async budgetAwareNeighborhood(entityName, options = {}) {
    const {
      tokenBudget = DEFAULT_TOKEN_BUDGET,
      maxResults = 50,
      hops = 1,
      minWeight = 0.2
    } = options;

    // Run full traversal first
    const traversalOptions = { maxResults, minWeight };
    const raw = hops === 2
      ? await this.twoHopNeighborhood(entityName, traversalOptions)
      : await this.oneHopNeighborhood(entityName, traversalOptions);

    if (raw.count === 0) {
      return {
        ...raw,
        usedTokens: 0,
        remainingBudget: tokenBudget,
        droppedCount: 0,
        budgetExhausted: false
      };
    }

    // Table header overhead: ~30 tokens
    const HEADER_TOKENS = 30;
    let usedTokens = HEADER_TOKENS;
    const budgeted = [];
    let droppedCount = 0;

    // Neighbors are already sorted by score (highest first)
    for (const neighbor of raw.neighbors) {
      const rowTokens = GGSRTraversalPrototypes._estimateRowTokens(neighbor);

      if (usedTokens + rowTokens > tokenBudget) {
        droppedCount = raw.neighbors.length - budgeted.length;
        break;
      }

      neighbor.estimatedTokens = rowTokens;
      budgeted.push(neighbor);
      usedTokens += rowTokens;
    }

    return {
      entity: raw.entity,
      baseName: raw.baseName,
      fileType: raw.fileType,
      hops: raw.hops,
      neighbors: budgeted,
      count: budgeted.length,
      totalAvailable: raw.count,
      usedTokens,
      remainingBudget: tokenBudget - usedTokens,
      droppedCount,
      budgetExhausted: droppedCount > 0,
      latencyMs: raw.latencyMs,
      meetsTarget: raw.meetsTarget,
      ...(raw.hop1Count !== undefined ? { hop1Count: raw.hop1Count, hop2Count: raw.hop2Count } : {})
    };
  }

  /**
   * Escape special regex characters for Cypher regex patterns
   * @private
   */
  _escapeRegex(str) {
    return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  /**
   * Normalize entity name by stripping common file extensions for Neo4j matching
   * Returns both the stripped name and detected file type for GGSR metadata
   * @private
   * @returns {{ name: string, ext: string|null, fileType: string|null }}
   */
  _normalizeEntityName(name) {
    const extMatch = name.match(/\.(py|sh|f90|F90|f|F|c|h|yaml|yml|json|xml|cfg|conf|txt|md|rst)$/);
    if (!extMatch) return { name, ext: null, fileType: null };

    const ext = extMatch[1].toLowerCase();
    const FILE_TYPE_MAP = {
      py: 'python', sh: 'shell',
      f90: 'fortran', f: 'fortran', 'F90': 'fortran', 'F': 'fortran',
      c: 'c', h: 'c-header',
      yaml: 'yaml', yml: 'yaml', json: 'json', xml: 'xml',
      cfg: 'config', conf: 'config',
      txt: 'text', md: 'markdown', rst: 'rst'
    };

    return {
      name: name.replace(/\.(py|sh|f90|F90|f|F|c|h|yaml|yml|json|xml|cfg|conf|txt|md|rst)$/, ''),
      ext: extMatch[0],
      fileType: FILE_TYPE_MAP[ext] || ext
    };
  }

  /**
   * Build a flexible regex pattern that matches with or without file extension
   * @private
   */
  _buildFlexiblePattern(entityName) {
    const parsed = this._normalizeEntityName(entityName);
    const escaped = this._escapeRegex(parsed.name);
    // Match: entity name optionally followed by any common extension
    return {
      pattern: `(?i).*${escaped}(\\\\.(py|sh|f90|F90|f|F|c|h))?.*`,
      fileType: parsed.fileType,
      ext: parsed.ext,
      baseName: parsed.name
    };
  }

  /**
   * Phase 24F-3: Cross-language trace traversal.
   * Follows Shell→Fortran (EXECUTES) and Shell→Python (INVOKES) bridges,
   * then continues into language-specific call chains.
   *
   * @param {string} entityName - Starting entity (shell script, Fortran program, Python module)
   * @param {object} [options]
   * @param {number} [options.maxDepth=3] - Max depth for language-internal CALLS chains
   * @param {number} [options.limit=30] - Max results
   * @returns {Promise<object>} Cross-language trace results
   */
  async crossLanguageTrace(entityName, options = {}) {
    const { maxDepth = 3, limit = 30 } = options;
    const start = Date.now();
    const { pattern } = this._buildFlexiblePattern(entityName);
    const limitVal = Math.floor(Math.min(limit, 100));

    // Query 1: Shell → Fortran → CALLS chain
    const fortranTraceQuery = `
      MATCH (shell:File)-[:EXECUTES]->(prog:FortranProgram)
      WHERE shell.absolutePath =~ $pattern OR prog.name =~ $pattern
      OPTIONAL MATCH (prog)-[:CALLS*1..${Math.floor(maxDepth)}]->(callee)
      RETURN shell.absolutePath AS shellPath,
             prog.name AS program, prog.file_path AS progPath,
             collect(DISTINCT {name: callee.name, type: head(labels(callee))}) AS callChain
      LIMIT ${limitVal}
    `;

    // Query 2: Shell → Python → DEFINES/CALLS chain
    const pythonTraceQuery = `
      MATCH (shell:File)-[:INVOKES]->(py:PythonModule)
      WHERE shell.absolutePath =~ $pattern OR py.name =~ $pattern
             OR py.file_path =~ $pattern
      OPTIONAL MATCH (py)-[:DEFINES]->(func:PythonFunction)
      OPTIONAL MATCH (func)-[:CALLS]->(callee:PythonFunction)
      RETURN shell.absolutePath AS shellPath,
             py.name AS module, py.file_path AS modulePath,
             collect(DISTINCT {name: func.name, type: 'PythonFunction'}) AS functions,
             collect(DISTINCT {name: callee.name, type: 'PythonFunction'}) AS callees
      LIMIT ${limitVal}
    `;

    try {
      const [fortranResults, pythonResults] = await Promise.all([
        this.graphDB.query(fortranTraceQuery, { pattern }),
        this.graphDB.query(pythonTraceQuery, { pattern })
      ]);

      const traces = [];

      // Process Fortran traces
      for (const rec of (fortranResults || [])) {
        const shellName = rec.shellPath ? rec.shellPath.split('/').pop() : null;
        const callees = (rec.callChain || []).filter(c => c.name);
        traces.push({
          type: 'shell-to-fortran',
          shell: shellName,
          target: rec.program,
          targetPath: rec.progPath,
          chain: callees.map(c => c.name),
          chainLength: callees.length,
          weight: RELATIONSHIP_WEIGHTS.EXECUTES
        });
      }

      // Process Python traces
      for (const rec of (pythonResults || [])) {
        const shellName = rec.shellPath ? rec.shellPath.split('/').pop() : null;
        const funcs = (rec.functions || []).filter(f => f.name);
        const calls = (rec.callees || []).filter(c => c.name);
        traces.push({
          type: 'shell-to-python',
          shell: shellName,
          target: rec.module,
          targetPath: rec.modulePath,
          functions: funcs.map(f => f.name),
          callees: calls.map(c => c.name),
          weight: RELATIONSHIP_WEIGHTS.INVOKES
        });
      }

      const latencyMs = Date.now() - start;
      return {
        entity: entityName,
        traces,
        traceCount: traces.length,
        fortranTraces: traces.filter(t => t.type === 'shell-to-fortran').length,
        pythonTraces: traces.filter(t => t.type === 'shell-to-python').length,
        latencyMs,
        meetsTarget: latencyMs < 100
      };
    } catch (err) {
      console.error('[WARN] Cross-language trace failed:', err.message);
      return {
        entity: entityName, traces: [], traceCount: 0,
        fortranTraces: 0, pythonTraces: 0,
        latencyMs: Date.now() - start, meetsTarget: false,
        error: err.message
      };
    }
  }
}

export default GGSRTraversalPrototypes;
