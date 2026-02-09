/**
 * Phase 24D: GraphGuidedRetrieval — Core Fusion Engine
 *
 * Consolidates GGSR weighted traversal (Neo4j) + semantic enrichment (ChromaDB)
 * into a single retrieval layer consumed by CodeAnalysisTools.
 *
 * Replaces ~50 lines of duplicated boilerplate per tool with one method call.
 *
 * @version 1.0.0
 * @phase 24D
 */

import { GGSRTraversalPrototypes } from './GGSRTraversalPrototypes.js';

const DEFAULT_COLLECTION = 'code-with-context-v8-0-0';
const COMMUNITY_COLLECTION = 'community-summaries';
const DEFAULT_TOKEN_BUDGET = 4000;

// Query classification patterns
const GLOBAL_PATTERNS = [
  /how does .+ work/i,
  /what does the .+ (subsystem|system|module|component|pipeline) do/i,
  /explain .+ (architecture|design|overview)/i,
  /summarize .+ (code|system|module)/i,
  /what is .+ used for/i,
  /describe .+ (functionality|purpose)/i,
  /overview of/i
];

const TRACE_PATTERNS = [
  /trace/i,
  /execution.*(path|flow|chain)/i,
  /call.*(graph|tree|chain)/i,
  /follow.*(from|through)/i
];

export class GraphGuidedRetrieval {
  /**
   * @param {object} deps
   * @param {object} deps.dataAccess - UnifiedDataAccess instance (graphDB + enrichGraphResults)
   * @param {GGSRTraversalPrototypes} deps.ggsr - GGSR traversal instance
   * @param {object} [deps.vectorDB] - VectorDatabase instance (for community summary search)
   */
  constructor({ dataAccess, ggsr, vectorDB }) {
    this.dataAccess = dataAccess;
    this.ggsr = ggsr;
    this.vectorDB = vectorDB || null;
  }

  /**
   * Core retrieval: GGSR weighted neighborhood + semantic enrichment in parallel.
   * Returns formatted markdown sections ready to append to tool output.
   *
   * @param {string} entity - Entity name (file, function, variable)
   * @param {string[]} semanticKeys - Identifiers to enrich from ChromaDB
   * @param {object} [options]
   * @param {number} [options.tokenBudget=4000]
   * @param {number} [options.maxResults=15]
   * @param {number} [options.hops=1]
   * @param {number} [options.maxSemanticKeys=8]
   * @param {string} [options.collection]
   * @param {string} [options.fileType] - Override auto-detected file type
   * @param {string} [options.query] - Original natural language query (for classification)
   * @param {string} [options.semanticLabel] - Label for semantic section subtitle
   * @returns {Promise<{ggsrSection: string, semanticSection: string, communitySection: string, metadata: object}>}
   */
  async retrieve(entity, semanticKeys = [], options = {}) {
    const {
      tokenBudget = DEFAULT_TOKEN_BUDGET,
      maxResults = 15,
      hops = 1,
      maxSemanticKeys = 8,
      collection = DEFAULT_COLLECTION,
      fileType,
      semanticLabel = 'key entities',
      query
    } = options;

    // Classify query to determine if community summaries should be included
    const queryType = this.classifyQuery(query, entity);

    const promises = [
      this._ggsrNeighborhood(entity, { tokenBudget, maxResults, hops, fileType }),
      this._semanticEnrich(semanticKeys, { collection, maxSemanticKeys })
    ];

    // Add community search for GLOBAL/HYBRID queries
    if ((queryType === 'GLOBAL' || queryType === 'HYBRID') && this.vectorDB) {
      promises.push(this.retrieveGlobal(query || entity, 3));
    }

    const results = await Promise.all(promises);
    const [ggsrResult, semanticResult] = results;
    const communityResult = results[2] || { section: '', count: 0, latencyMs: 0 };

    return {
      ggsrSection: ggsrResult.markdown,
      semanticSection: semanticResult.markdown
        ? `\n## Semantic Context\n*Content snippets from vector store for ${semanticLabel}*\n\n${semanticResult.markdown}`
        : '',
      communitySection: communityResult.section,
      metadata: {
        ggsrCount: ggsrResult.count,
        ggsrLatencyMs: ggsrResult.latencyMs,
        usedTokens: ggsrResult.usedTokens,
        tokenBudget,
        budgetExhausted: ggsrResult.budgetExhausted,
        droppedCount: ggsrResult.droppedCount,
        semanticHits: semanticResult.hitCount,
        fileType: ggsrResult.fileType,
        queryType,
        communityHits: communityResult.count,
        communityLatencyMs: communityResult.latencyMs
      }
    };
  }

  /**
   * Extended retrieve for 2-hop dependency graphs.
   * Same as retrieve() but includes hop1/hop2 counts in metadata.
   */
  async retrieveDependency(entity, semanticKeys = [], options = {}) {
    const result = await this.retrieve(entity, semanticKeys, {
      maxResults: 20,
      hops: 2,
      ...options
    });

    return result;
  }

  /**
   * Fortran-specific retrieval using fortranWeightedTraversal.
   * For trace_execution_path when graphType === 'fortran'.
   *
   * @param {string} functionName
   * @param {object} rawResults - Pre-collected callers/callChain from graph queries
   * @param {string[]} semanticKeys
   * @param {object} [options]
   * @returns {Promise<{ggsrSection: string, semanticSection: string, metadata: object}>}
   */
  async retrieveFortranScored(functionName, rawResults, semanticKeys = [], options = {}) {
    const {
      maxRows = 20,
      fileType = 'fortran',
      collection = DEFAULT_COLLECTION,
      maxSemanticKeys = 8,
      semanticLabel = 'key entities'
    } = options;

    const [ggsrResult, semanticResult] = await Promise.all([
      this._scoreRawResults(rawResults, { maxRows, fileType }),
      this._semanticEnrich(semanticKeys, { collection, maxSemanticKeys })
    ]);

    return {
      ggsrSection: ggsrResult.markdown,
      semanticSection: semanticResult.markdown
        ? `\n## Semantic Context\n*Content snippets from vector store for ${semanticLabel}*\n\n${semanticResult.markdown}`
        : '',
      metadata: {
        ggsrCount: ggsrResult.count,
        semanticHits: semanticResult.hitCount,
        fileType
      }
    };
  }

  // ---- 24E-3: Query Classification & Global Retrieval ----

  /**
   * Classify a query as LOCAL, GLOBAL, TRACE, or HYBRID.
   * LOCAL: entity-specific ("what calls gsi?") → GGSR neighborhood
   * GLOBAL: system-level ("how does data assimilation work?") → community summaries
   * TRACE: execution path ("trace exglobal_forecast") → trace pipeline
   * HYBRID: mixed → both GGSR + community summaries
   *
   * @param {string} query - Natural language query or entity name
   * @param {string} [entity] - Explicit entity if provided separately
   * @returns {'LOCAL'|'GLOBAL'|'TRACE'|'HYBRID'}
   */
  classifyQuery(query, entity) {
    if (!query) return 'LOCAL';

    const isGlobal = GLOBAL_PATTERNS.some(p => p.test(query));
    const isTrace = TRACE_PATTERNS.some(p => p.test(query));
    const hasEntity = entity && entity.length > 0;

    if (isTrace) return 'TRACE';
    if (isGlobal && hasEntity) return 'HYBRID';
    if (isGlobal) return 'GLOBAL';
    return 'LOCAL';
  }

  /**
   * Retrieve community summaries for a global/system-level query.
   * Searches the community-summaries ChromaDB collection.
   *
   * @param {string} query - Query text
   * @param {number} [nResults=5] - Number of summaries to return
   * @returns {Promise<{section: string, count: number, latencyMs: number}>}
   */
  async retrieveGlobal(query, nResults = 5) {
    if (!this.vectorDB || !query) {
      return { section: '', count: 0, latencyMs: 0 };
    }

    const startTime = Date.now();
    try {
      const results = await this.vectorDB.query(COMMUNITY_COLLECTION, query, {
        nResults,
        include: ['documents', 'metadatas', 'distances']
      });

      if (!results || results.length === 0) {
        return { section: '', count: 0, latencyMs: Date.now() - startTime };
      }

      let md = '\n## Community Context\n';
      md += '*Hierarchical summaries from Leiden community detection (Phase 24E)*\n\n';

      for (const r of results) {
        const score = r.score != null ? r.score.toFixed(2) : 'N/A';
        const size = r.metadata?.size || '?';
        const lang = r.metadata?.language || '?';
        md += `### Community (${size} nodes, ${lang}) — relevance: ${score}\n`;
        md += `${r.text || ''}\n\n`;
      }

      return {
        section: md,
        count: results.length,
        latencyMs: Date.now() - startTime
      };
    } catch (err) {
      console.error('[WARN] Community summary search failed:', err.message);
      return { section: '', count: 0, latencyMs: Date.now() - startTime };
    }
  }

  // ---- Internal methods ----

  async _ggsrNeighborhood(entity, { tokenBudget, maxResults, hops, fileType }) {
    if (!this.ggsr || !entity) {
      return { markdown: '', count: 0, latencyMs: 0, usedTokens: 0, budgetExhausted: false, droppedCount: 0, fileType: null };
    }

    try {
      const neighborhood = await this.ggsr.budgetAwareNeighborhood(entity, {
        tokenBudget, maxResults, hops
      });

      if (neighborhood.count === 0) {
        return { markdown: '', count: 0, latencyMs: neighborhood.latencyMs, usedTokens: 0, budgetExhausted: false, droppedCount: 0, fileType: neighborhood.fileType };
      }

      const neighborKey = neighborhood.neighbors[0].neighbor !== undefined ? 'neighbor' : 'name';
      const scored = this.ggsr.scoreResults(
        neighborhood.neighbors.map(n => ({
          name: n[neighborKey] || n.name,
          relType: n.relType,
          depth: n.hop
        }))
      );

      let md = this.ggsr.formatWeightedTable(scored, {
        maxRows: maxResults,
        fileType: fileType || neighborhood.fileType
      });

      // Stats line
      if (hops >= 2) {
        md += `*Hop1: ${neighborhood.hop1Count || 0} | Hop2: ${neighborhood.hop2Count || 0} | Latency: ${neighborhood.latencyMs}ms | Tokens: ${neighborhood.usedTokens}/${tokenBudget}*\n`;
      } else {
        md += `*Latency: ${neighborhood.latencyMs}ms | Tokens: ${neighborhood.usedTokens}/${tokenBudget}*\n`;
      }

      if (neighborhood.budgetExhausted) {
        md += `*Budget exhausted — ${neighborhood.droppedCount} lower-scored neighbors omitted*\n`;
      }

      return {
        markdown: md,
        count: neighborhood.count,
        latencyMs: neighborhood.latencyMs,
        usedTokens: neighborhood.usedTokens,
        budgetExhausted: neighborhood.budgetExhausted,
        droppedCount: neighborhood.droppedCount,
        fileType: fileType || neighborhood.fileType,
        hop1Count: neighborhood.hop1Count,
        hop2Count: neighborhood.hop2Count
      };
    } catch (err) {
      console.error('[WARN] GGSR neighborhood failed:', err.message);
      return { markdown: '', count: 0, latencyMs: 0, usedTokens: 0, budgetExhausted: false, droppedCount: 0, fileType: null };
    }
  }

  async _scoreRawResults(rawResults, { maxRows, fileType }) {
    if (!this.ggsr || rawResults.length === 0) {
      return { markdown: '', count: 0 };
    }

    try {
      const scored = this.ggsr.scoreResults(rawResults);
      const md = this.ggsr.formatWeightedTable(scored, { maxRows, fileType });
      return { markdown: md, count: scored.length };
    } catch (err) {
      console.error('[WARN] GGSR scoring failed:', err.message);
      return { markdown: '', count: 0 };
    }
  }

  async _semanticEnrich(keys, { collection, maxSemanticKeys }) {
    const filtered = (keys || []).filter(Boolean);
    if (filtered.length === 0 || !this.dataAccess) {
      return { markdown: '', hitCount: 0 };
    }

    try {
      const enrichment = await this.dataAccess.enrichGraphResults(filtered, {
        collection,
        nResultsPerQuery: 1,
        maxIdentifiers: maxSemanticKeys
      });

      if (!enrichment || enrichment.size === 0) {
        return { markdown: '', hitCount: 0 };
      }

      let md = '';
      for (const [name, data] of enrichment) {
        if (data.content && data.content.length > 20) {
          md += `### \`${name}\`\n`;
          md += `${data.content.substring(0, 300)}${data.content.length > 300 ? '...' : ''}\n\n`;
        }
      }

      return { markdown: md, hitCount: enrichment.size };
    } catch (err) {
      console.error('[WARN] Vector enrichment failed:', err.message);
      return { markdown: '', hitCount: 0 };
    }
  }
}
