#!/usr/bin/env node

/**
 * GraphRAG Agentic Tools Module — Phase 24H
 *
 * Five new MCP tools that expose the full GraphRAG stack (24A-G) as
 * first-class agentic capabilities for LLM-driven code understanding.
 *
 * Tools:
 *   1. get_code_context     — "Understand anything" single-call context
 *   2. search_architecture  — Global/holistic architecture queries
 *   3. find_similar_code    — Semantic similarity + graph enrichment
 *   4. get_change_impact    — Blast radius + risk scoring
 *   5. trace_data_flow      — Cross-language execution traces
 *
 * @version 1.0.0
 * @phase Phase 24H
 */

import { UnifiedDataAccess } from '../data/UnifiedDataAccess.js';
import { GGSRTraversalPrototypes } from '../graphrag/GGSRTraversalPrototypes.js';
import { GraphGuidedRetrieval } from '../graphrag/GraphGuidedRetrieval.js';

const CODE_COLLECTION = 'code-with-context-v8-0-0';
const COMMUNITY_COLLECTION = 'community-summaries';

export class GraphRAGTools {
  constructor(dataAccess = null) {
    this.dataAccess = dataAccess;
    this.isInitialized = !!dataAccess;
    this.ggsr = null;
    this.retrieval = null;
  }

  async initialize() {
    if (this.isInitialized) return;

    console.error('[INIT] Initializing GraphRAG Tools...');
    this.dataAccess = new UnifiedDataAccess();
    await this.dataAccess.connect();

    if (this.dataAccess.graphDB) {
      this.ggsr = new GGSRTraversalPrototypes(this.dataAccess.graphDB);
      this.retrieval = new GraphGuidedRetrieval({
        dataAccess: this.dataAccess,
        ggsr: this.ggsr,
        vectorDB: this.dataAccess.vectorDB || null
      });
    }

    this.isInitialized = true;
    console.error('[OK] GraphRAG Tools initialized');
  }

  async ensureInitialized() {
    if (!this.isInitialized) await this.initialize();
  }

  // ---- Tool Registration ----

  registerWith(server) {
    // Tool 1: get_code_context
    server.registerTool(
      'get_code_context',
      'Get comprehensive context for a code symbol including graph neighborhood, community/subsystem summary, and semantic snippets. Use as the FIRST step when examining any code entity.',
      {
        type: 'object',
        properties: {
          symbol: {
            type: 'string',
            description: 'Code symbol name (function, subroutine, module, file, or program). Examples: "setuprad", "enkf_main", "exglobal_forecast"'
          },
          depth: {
            type: 'number',
            description: 'Relationship traversal depth (1=direct, 2=neighbors-of-neighbors, 3=deep)',
            default: 2,
            minimum: 1,
            maximum: 3
          },
          include_community: {
            type: 'boolean',
            description: 'Include community/subsystem architectural summary',
            default: true
          },
          token_budget: {
            type: 'number',
            description: 'Max tokens for context (lower=precise, higher=broad)',
            default: 4000
          }
        },
        required: ['symbol']
      },
      this.getCodeContext.bind(this)
    );

    // Tool 2: search_architecture
    server.registerTool(
      'search_architecture',
      'Search the codebase architecture for high-level understanding. Returns community/subsystem summaries matching the query. Best for "how does X work?", "what is the Y subsystem?", "overview of Z" questions.',
      {
        type: 'object',
        properties: {
          query: {
            type: 'string',
            description: 'Architecture question (e.g., "how does data assimilation work?", "ocean modeling subsystem", "MPI communication patterns")'
          },
          max_results: {
            type: 'number',
            description: 'Maximum community summaries to return',
            default: 5,
            minimum: 1,
            maximum: 10
          }
        },
        required: ['query']
      },
      this.searchArchitecture.bind(this)
    );

    // Tool 3: find_similar_code
    server.registerTool(
      'find_similar_code',
      'Find code patterns semantically similar to a given symbol or description. Useful for consistent refactoring, finding duplicates, or discovering related functionality.',
      {
        type: 'object',
        properties: {
          code_or_symbol: {
            type: 'string',
            description: 'Code symbol name or natural language description to find similar patterns for'
          },
          similarity_threshold: {
            type: 'number',
            description: 'Minimum similarity score (0.0-1.0)',
            default: 0.7,
            minimum: 0.0,
            maximum: 1.0
          },
          max_results: {
            type: 'number',
            description: 'Maximum results to return',
            default: 10,
            minimum: 1,
            maximum: 25
          }
        },
        required: ['code_or_symbol']
      },
      this.findSimilarCode.bind(this)
    );

    // Tool 4: get_change_impact
    server.registerTool(
      'get_change_impact',
      'Analyze the blast radius of changing a code symbol. Shows direct/indirect dependents, risk score, and recommendations. USE THIS BEFORE MAKING SIGNIFICANT CHANGES.',
      {
        type: 'object',
        properties: {
          symbol: {
            type: 'string',
            description: 'Symbol to analyze change impact for (function, module, file)'
          },
          change_type: {
            type: 'string',
            enum: ['signature', 'behavior', 'delete', 'rename'],
            description: 'Type of change being considered',
            default: 'behavior'
          },
          include_indirect: {
            type: 'boolean',
            description: 'Include transitive/indirect impacts (2-3 hops out)',
            default: true
          }
        },
        required: ['symbol']
      },
      this.getChangeImpact.bind(this)
    );

    // Tool 5: trace_data_flow
    server.registerTool(
      'trace_data_flow',
      'Trace execution flow from a source symbol through the codebase, including cross-language paths (Shell to Fortran to Python). Essential for understanding how scripts invoke programs.',
      {
        type: 'object',
        properties: {
          from_symbol: {
            type: 'string',
            description: 'Source symbol to trace from (e.g., "exglobal_atmos_analysis", "enkf_main")'
          },
          to_symbol: {
            type: 'string',
            description: 'Optional destination symbol. If omitted, shows all downstream paths.'
          },
          max_depth: {
            type: 'number',
            description: 'Maximum path length to search',
            default: 5,
            minimum: 1,
            maximum: 10
          }
        },
        required: ['from_symbol']
      },
      this.traceDataFlow.bind(this)
    );

    console.error('[OK] Registered 5 GraphRAG tools (Phase 24H)');
  }

  // ---- Tool Handlers ----

  /**
   * get_code_context — comprehensive single-call context for any symbol
   */
  async getCodeContext(args) {
    await this.ensureInitialized();
    // Phase 29: accept common aliases for symbol
    const symbol = args.symbol || args.function_name || args.file_path;
    const { depth = 2, include_community = true, token_budget = 4000 } = args;

    try {
      // 1. Find the node in Neo4j
      const nodeInfo = await this.dataAccess.graphDB.query(
        `MATCH (n) WHERE n.name = $name OR n.absolutePath CONTAINS $name
         RETURN n.name AS name, labels(n) AS labels, n.absolutePath AS path,
                n.type AS type, n.communityId AS communityId
         LIMIT 1`,
        { name: symbol }
      );

      if (!nodeInfo || nodeInfo.length === 0) {
        // Try fuzzy match
        const fuzzy = await this.dataAccess.graphDB.query(
          `MATCH (n) WHERE toLower(n.name) CONTAINS toLower($name)
           RETURN n.name AS name, labels(n) AS labels LIMIT 5`,
          { name: symbol }
        );
        return {
          content: [{
            type: 'text',
            text: `Symbol "${symbol}" not found in graph.\n\n` +
              (fuzzy.length > 0
                ? `Did you mean: ${fuzzy.map(f => `\`${f.name}\` (${f.labels[0]})`).join(', ')}?`
                : 'No similar symbols found.')
          }]
        };
      }

      const node = nodeInfo[0];

      // 2. GGSR neighborhood
      const ctx = await this.retrieval.retrieve(symbol, [symbol], {
        tokenBudget: token_budget,
        maxResults: 15,
        hops: depth,
        query: include_community ? `What is ${symbol} and what does it do?` : null
      });

      // 3. Get callers (reverse direction)
      const callers = await this.dataAccess.graphDB.query(
        `MATCH (caller)-[r:CALLS|USES|IMPORTS|EXECUTES|INVOKES]->(target)
         WHERE target.name = $name
         RETURN caller.name AS name, labels(caller)[0] AS type, type(r) AS relType
         LIMIT 10`,
        { name: symbol }
      );

      // 4. Build structured response
      let response = `# Code Context: \`${node.name}\`\n\n`;
      response += `**Type**: ${node.labels?.join(', ') || 'Unknown'}\n`;
      if (node.path) response += `**Path**: ${node.path}\n`;
      response += '\n';

      // Callers section
      if (callers.length > 0) {
        response += `## Called By (${callers.length} callers)\n\n`;
        response += '| Caller | Type | Relationship |\n|--------|------|-------------|\n';
        for (const c of callers) {
          response += `| \`${c.name}\` | ${c.type} | ${c.relType} |\n`;
        }
        response += '\n';
      }

      // GGSR neighborhood
      if (ctx.ggsrSection) {
        response += ctx.ggsrSection + '\n';
      }

      // Community context
      if (ctx.communitySection) {
        response += ctx.communitySection + '\n';
      }

      // Semantic snippets
      if (ctx.semanticSection) {
        response += ctx.semanticSection + '\n';
      }

      return { content: [{ type: 'text', text: response }] };

    } catch (error) {
      return { content: [{ type: 'text', text: `[ERROR] get_code_context failed: ${error.message}` }] };
    }
  }

  /**
   * search_architecture — global/holistic architecture queries
   */
  async searchArchitecture(args) {
    await this.ensureInitialized();
    const { query, max_results = 5 } = args;

    try {
      if (!this.dataAccess.vectorDB) {
        return { content: [{ type: 'text', text: '[ERROR] VectorDB not available for architecture search' }] };
      }

      // Search community summaries
      const results = await this.dataAccess.vectorDB.query(
        COMMUNITY_COLLECTION, query, { nResults: max_results }
      );

      if (!results || results.length === 0) {
        return { content: [{ type: 'text', text: `No architectural context found for: "${query}"` }] };
      }

      let response = `# Architecture Search: "${query}"\n\n`;
      response += `Found ${results.length} relevant subsystems/communities:\n\n`;

      for (let i = 0; i < results.length; i++) {
        const r = results[i];
        const score = r.score != null ? r.score : (r.distance != null ? (1 - r.distance).toFixed(3) : 'N/A');
        response += `## ${i + 1}. ${r.metadata?.communityId != null ? `Community ${r.metadata.communityId}` : 'Community'} (relevance: ${score})\n\n`;
        response += `${r.text || r.document || 'No summary available'}\n\n`;
        if (r.metadata?.nodeCount) {
          response += `*${r.metadata.nodeCount} nodes, ${r.metadata.dominantType || 'mixed'} type*\n\n`;
        }
        response += '---\n\n';
      }

      return { content: [{ type: 'text', text: response }] };

    } catch (error) {
      return { content: [{ type: 'text', text: `[ERROR] search_architecture failed: ${error.message}` }] };
    }
  }

  /**
   * find_similar_code — semantic similarity + graph enrichment
   */
  async findSimilarCode(args) {
    await this.ensureInitialized();
    // Phase 29: accept common aliases for code_or_symbol
    const code_or_symbol = args.code_or_symbol || args.code_snippet || args.symbol;
    const { similarity_threshold = 0.7, max_results = 10 } = args;

    try {
      if (!this.dataAccess.vectorDB) {
        return { content: [{ type: 'text', text: '[ERROR] VectorDB not available for similarity search' }] };
      }

      // Search code embeddings
      const results = await this.dataAccess.vectorDB.query(
        CODE_COLLECTION, code_or_symbol, { nResults: max_results * 2 }
      );

      // Filter by threshold
      const filtered = (results || [])
        .map(r => ({
          ...r,
          similarity: r.score != null ? r.score : (r.distance != null ? 1 - r.distance : 0)
        }))
        .filter(r => r.similarity >= similarity_threshold)
        .slice(0, max_results);

      if (filtered.length === 0) {
        return {
          content: [{
            type: 'text',
            text: `No code found above ${similarity_threshold} similarity threshold for: "${code_or_symbol}"`
          }]
        };
      }

      let response = `# Similar Code: "${code_or_symbol}"\n\n`;
      response += `Found ${filtered.length} matches above ${similarity_threshold} similarity:\n\n`;
      response += '| # | File | Similarity | Preview |\n|---|------|------------|--------|\n';

      for (let i = 0; i < filtered.length; i++) {
        const r = filtered[i];
        const filePath = r.metadata?.file_path || r.metadata?.source || 'unknown';
        const fileName = filePath.split('/').pop();
        const preview = (r.text || '').substring(0, 60).replace(/\n/g, ' ').replace(/\|/g, '\\|');
        response += `| ${i + 1} | \`${fileName}\` | ${r.similarity.toFixed(3)} | ${preview}... |\n`;
      }

      return { content: [{ type: 'text', text: response }] };

    } catch (error) {
      return { content: [{ type: 'text', text: `[ERROR] find_similar_code failed: ${error.message}` }] };
    }
  }

  /**
   * get_change_impact — blast radius analysis with risk scoring
   */
  async getChangeImpact(args) {
    await this.ensureInitialized();
    // Phase 29: accept common aliases for symbol
    const symbol = args.symbol || args.file_path || args.function_name;
    const { change_type = 'behavior', include_indirect = true } = args;

    try {
      const maxHops = include_indirect ? 3 : 1;

      // 1. Find direct dependents (who calls/uses/imports this?)
      const directDeps = await this.dataAccess.graphDB.query(
        `MATCH (dependent)-[r:CALLS|USES|IMPORTS|EXECUTES|INVOKES|SOURCES]->(target)
         WHERE target.name = $name
         RETURN DISTINCT dependent.name AS name, labels(dependent)[0] AS type,
                type(r) AS relType, dependent.absolutePath AS path
         ORDER BY dependent.name`,
        { name: symbol }
      );

      // 2. Find indirect dependents (transitive callers, limited scope)
      let indirectDeps = [];
      if (include_indirect && directDeps.length < 100) {
        const directNames = directDeps.map(d => d.name);
        indirectDeps = await this.dataAccess.graphDB.query(
          `MATCH (indirect)-[:CALLS|USES|IMPORTS]->(direct)-[:CALLS|USES|IMPORTS]->(target)
           WHERE target.name = $name
           AND NOT indirect.name IN $directNames
           AND indirect.name <> $name
           RETURN DISTINCT indirect.name AS name, labels(indirect)[0] AS type,
                  indirect.absolutePath AS path
           ORDER BY indirect.name
           LIMIT 20`,
          { name: symbol, directNames }
        );
      }

      // 3. Get community context (what subsystem is this in?)
      const community = await this.dataAccess.graphDB.query(
        `MATCH (n) WHERE n.name = $name
         RETURN n.communityId AS communityId
         LIMIT 1`,
        { name: symbol }
      );

      let communityInfo = '';
      if (community.length > 0 && community[0].communityId != null && this.dataAccess.vectorDB) {
        try {
          const cid = typeof community[0].communityId === 'object'
            ? community[0].communityId.toNumber?.() || community[0].communityId
            : community[0].communityId;
          const summaries = await this.dataAccess.vectorDB.query(
            COMMUNITY_COLLECTION, symbol, { nResults: 1 }
          );
          if (summaries.length > 0) {
            communityInfo = summaries[0].text || '';
          }
        } catch {
          // Non-critical
        }
      }

      // 4. Compute risk score
      const riskScore = this._computeRiskScore({
        directCount: directDeps.length,
        indirectCount: indirectDeps.length,
        changeType: change_type
      });

      // 5. Build response
      let response = `# Change Impact: \`${symbol}\`\n\n`;
      response += `**Change Type**: ${change_type}\n`;
      response += `**Risk Level**: ${riskScore.level} (${riskScore.score.toFixed(2)})\n\n`;

      // Risk factors
      response += `## Risk Factors\n\n`;
      for (const factor of riskScore.factors) {
        response += `- ${factor}\n`;
      }
      response += '\n';

      // Direct dependents
      response += `## Direct Dependents (${directDeps.length})\n\n`;
      if (directDeps.length > 0) {
        response += '| Dependent | Type | Relationship |\n|-----------|------|-------------|\n';
        for (const d of directDeps) {
          response += `| \`${d.name}\` | ${d.type} | ${d.relType} |\n`;
        }
      } else {
        response += '*No direct dependents found — this symbol may be a leaf node.*\n';
      }
      response += '\n';

      // Indirect dependents
      if (indirectDeps.length > 0) {
        response += `## Indirect Dependents (${indirectDeps.length})\n\n`;
        response += '| Dependent | Type |\n|-----------|------|\n';
        for (const d of indirectDeps) {
          response += `| \`${d.name}\` | ${d.type} |\n`;
        }
        response += '\n';
      }

      // Community context
      if (communityInfo) {
        response += `## Subsystem Context\n\n${communityInfo}\n\n`;
      }

      // Recommendations
      response += `## Recommendations\n\n`;
      response += this._generateRecommendations(change_type, riskScore, directDeps.length);

      return { content: [{ type: 'text', text: response }] };

    } catch (error) {
      return { content: [{ type: 'text', text: `[ERROR] get_change_impact failed: ${error.message}` }] };
    }
  }

  /**
   * trace_data_flow — cross-language execution traces
   */
  async traceDataFlow(args) {
    await this.ensureInitialized();
    // Phase 29: accept common aliases for from_symbol
    const from_symbol = args.from_symbol || args.variable || args.symbol;
    const { to_symbol, max_depth = 5 } = args;

    try {
      let response = `# Data Flow Trace: \`${from_symbol}\``;
      if (to_symbol) response += ` → \`${to_symbol}\``;
      response += '\n\n';

      // 1. Cross-language traces (Shell→Fortran→Python)
      let crossLangSection = '';
      if (this.ggsr) {
        try {
          const traces = await this.ggsr.crossLanguageTrace(from_symbol, { maxDepth: max_depth });
          if (traces && traces.traces && traces.traces.length > 0) {
            crossLangSection += `## Cross-Language Execution Paths (${traces.traces.length})\n\n`;
            for (const trace of traces.traces) {
              crossLangSection += `### ${trace.type}: ${trace.shell || from_symbol} → ${trace.target}\n\n`;
              if (trace.targetPath) crossLangSection += `**Target**: \`${trace.targetPath}\`\n`;
              if (trace.chain && trace.chain.length > 0) {
                crossLangSection += `**Call chain** (${trace.chain.length} deep): `;
                crossLangSection += trace.chain.slice(0, 10).map(c => `\`${c}\``).join(' → ');
                if (trace.chain.length > 10) crossLangSection += ` ... (+${trace.chain.length - 10} more)`;
                crossLangSection += '\n';
              }
              crossLangSection += '\n';
            }
          }
        } catch {
          // Cross-language trace not available for this entity
        }
      }

      // 2. Graph neighborhood (CALLS/USES outgoing)
      const outgoing = await this.dataAccess.graphDB.query(
        `MATCH (source)-[r:CALLS|USES|IMPORTS|EXECUTES|INVOKES|SOURCES]->(target)
         WHERE source.name = $name
         RETURN target.name AS name, labels(target)[0] AS type, type(r) AS relType
         ORDER BY type(r), target.name
         LIMIT 25`,
        { name: from_symbol }
      );

      // 3. If to_symbol specified, find shortest path
      let pathSection = '';
      if (to_symbol) {
        const paths = await this.dataAccess.graphDB.query(
          `MATCH path = shortestPath(
             (source)-[:CALLS|USES|IMPORTS|EXECUTES|INVOKES|SOURCES*1..${max_depth}]->(dest)
           )
           WHERE source.name = $from AND dest.name = $to
           RETURN [n IN nodes(path) | n.name] AS nodeNames,
                  [r IN relationships(path) | type(r)] AS relTypes,
                  length(path) AS hops
           LIMIT 3`,
          { from: from_symbol, to: to_symbol }
        );

        if (paths.length > 0) {
          pathSection += `## Shortest Path to \`${to_symbol}\`\n\n`;
          for (const p of paths) {
            const chain = p.nodeNames.map((n, i) =>
              i < p.relTypes.length ? `\`${n}\` -[${p.relTypes[i]}]→` : `\`${n}\``
            ).join(' ');
            pathSection += `**${p.hops} hops**: ${chain}\n\n`;
          }
        } else {
          pathSection += `## Path to \`${to_symbol}\`\n\nNo path found within ${max_depth} hops.\n\n`;
        }
      }

      // Build response
      if (crossLangSection) response += crossLangSection;
      if (pathSection) response += pathSection;

      if (outgoing.length > 0) {
        response += `## Outgoing Relationships (${outgoing.length})\n\n`;
        response += '| Target | Type | Relationship |\n|--------|------|-------------|\n';
        for (const o of outgoing) {
          response += `| \`${o.name || 'unnamed'}\` | ${o.type} | ${o.relType} |\n`;
        }
        response += '\n';
      }

      if (!crossLangSection && !pathSection && outgoing.length === 0) {
        response += `No data flow found from \`${from_symbol}\`. Check the symbol name and try again.\n`;
      }

      return { content: [{ type: 'text', text: response }] };

    } catch (error) {
      return { content: [{ type: 'text', text: `[ERROR] trace_data_flow failed: ${error.message}` }] };
    }
  }

  // ---- Helper Methods ----

  _computeRiskScore({ directCount, indirectCount, changeType }) {
    let score = 0;
    const factors = [];

    // Dependent count impact
    score += Math.min(directCount / 20, 0.4);
    factors.push(`${directCount} direct dependent(s)`);

    if (indirectCount > 0) {
      score += Math.min(indirectCount / 50, 0.2);
      factors.push(`${indirectCount} indirect dependent(s)`);
    }

    // Change type impact
    const typeScores = { delete: 0.3, signature: 0.25, rename: 0.2, behavior: 0.1 };
    score += typeScores[changeType] || 0.1;
    factors.push(`Change type: ${changeType}`);

    score = Math.min(score, 1.0);
    const level = score > 0.7 ? 'HIGH' : score > 0.4 ? 'MEDIUM' : 'LOW';

    return { score, level, factors };
  }

  _generateRecommendations(changeType, riskScore, directCount) {
    let recs = '';
    if (riskScore.level === 'HIGH') {
      recs += '1. **Review all direct dependents** before making changes\n';
      recs += '2. Consider **incremental rollout** — change one caller at a time\n';
      recs += '3. Add **regression tests** for each dependent\n';
    } else if (riskScore.level === 'MEDIUM') {
      recs += '1. Review direct dependents for compatibility\n';
      recs += '2. Run existing tests after changes\n';
    } else {
      recs += '1. Low risk — proceed with standard review\n';
    }

    if (changeType === 'delete') {
      recs += `- **WARNING**: Deleting this symbol affects ${directCount} dependent(s)\n`;
    }
    if (changeType === 'signature') {
      recs += '- Update all callers to match new signature\n';
    }
    if (changeType === 'rename') {
      recs += '- Search for string references (config files, docs) that may reference old name\n';
    }

    return recs;
  }
}
