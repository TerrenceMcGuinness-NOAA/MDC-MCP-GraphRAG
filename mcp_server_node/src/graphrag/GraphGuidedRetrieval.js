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
const DEFAULT_TOKEN_BUDGET = 4000;

export class GraphGuidedRetrieval {
  /**
   * @param {object} deps
   * @param {object} deps.dataAccess - UnifiedDataAccess instance (graphDB + enrichGraphResults)
   * @param {GGSRTraversalPrototypes} deps.ggsr - GGSR traversal instance
   */
  constructor({ dataAccess, ggsr }) {
    this.dataAccess = dataAccess;
    this.ggsr = ggsr;
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
   * @param {string} [options.semanticLabel] - Label for semantic section subtitle
   * @returns {Promise<{ggsrSection: string, semanticSection: string, metadata: object}>}
   */
  async retrieve(entity, semanticKeys = [], options = {}) {
    const {
      tokenBudget = DEFAULT_TOKEN_BUDGET,
      maxResults = 15,
      hops = 1,
      maxSemanticKeys = 8,
      collection = DEFAULT_COLLECTION,
      fileType,
      semanticLabel = 'key entities'
    } = options;

    const [ggsrResult, semanticResult] = await Promise.all([
      this._ggsrNeighborhood(entity, { tokenBudget, maxResults, hops, fileType }),
      this._semanticEnrich(semanticKeys, { collection, maxSemanticKeys })
    ]);

    return {
      ggsrSection: ggsrResult.markdown,
      semanticSection: semanticResult.markdown
        ? `\n## Semantic Context\n*Content snippets from vector store for ${semanticLabel}*\n\n${semanticResult.markdown}`
        : '',
      metadata: {
        ggsrCount: ggsrResult.count,
        ggsrLatencyMs: ggsrResult.latencyMs,
        usedTokens: ggsrResult.usedTokens,
        tokenBudget,
        budgetExhausted: ggsrResult.budgetExhausted,
        droppedCount: ggsrResult.droppedCount,
        semanticHits: semanticResult.hitCount,
        fileType: ggsrResult.fileType
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
