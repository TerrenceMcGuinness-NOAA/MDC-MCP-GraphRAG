#!/usr/bin/env node

/**
 * GraphRAG Agentic Tools Module — Phase 24H
 *
 * Nine MCP tools that expose the full GraphRAG stack (24A-G) as
 * first-class agentic capabilities for LLM-driven code understanding.
 *
 * Tools (Phase 24H-1):
 *   1. get_code_context     — "Understand anything" single-call context
 *   2. search_architecture  — Global/holistic architecture queries
 *   3. find_similar_code    — Semantic similarity + graph enrichment
 *   4. get_change_impact    — Blast radius + risk scoring
 *   5. trace_data_flow      — Cross-language execution traces
 *
 * Tools (Phase 24H-3 — Session State):
 *   6. mark_as_modified     — Track file modifications in active session
 *   7. get_session_context  — Aggregated view of session work
 *   8. checkpoint_state     — Snapshot session state for recovery
 *   9. restore_checkpoint   — Roll back to a named checkpoint
 *
 * @version 2.0.0
 * @phase Phase 24H
 */

import { UnifiedDataAccess } from '../data/UnifiedDataAccess.js';
import { GGSRTraversalPrototypes } from '../graphrag/GGSRTraversalPrototypes.js';
import { GraphGuidedRetrieval } from '../graphrag/GraphGuidedRetrieval.js';
import { SessionManager } from '../sdd/SessionManager.js';

const CODE_COLLECTION = 'code-with-context-v8-0-0';
const COMMUNITY_COLLECTION = 'community-summaries';

export class GraphRAGTools {
  constructor(dataAccess = null, sessionManager = null) {
    this.dataAccess = dataAccess;
    this.isInitialized = !!dataAccess;
    this.ggsr = null;
    this.retrieval = null;
    this.sessionManager = sessionManager || new SessionManager();
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

    // Tool 6: mark_as_modified (Phase 24H-3)
    server.registerTool(
      'mark_as_modified',
      'Record a file modification in the active session. Tracks what the agent has changed for session continuity and impact awareness. Optionally marks Neo4j nodes as dirty.',
      {
        type: 'object',
        properties: {
          file_path: {
            type: 'string',
            description: 'Path of the modified file (e.g., "parm/config/config.resources")'
          },
          change_type: {
            type: 'string',
            enum: ['content', 'signature', 'delete', 'rename'],
            description: 'Type of change made',
            default: 'content'
          },
          description: {
            type: 'string',
            description: 'What was changed (e.g., "Converted to YAML format")'
          }
        },
        required: ['file_path']
      },
      this.markAsModified.bind(this)
    );

    // Tool 7: get_session_context (Phase 24H-3)
    server.registerTool(
      'get_session_context',
      'Get aggregated view of the active session: examined symbols, file modifications, checkpoints, and progress. Use to understand what the agent has done so far in a long-running task.',
      {
        type: 'object',
        properties: {
          include_dirty: {
            type: 'boolean',
            description: 'Include graph dirty state for modified nodes',
            default: true
          }
        }
      },
      this.getSessionContext.bind(this)
    );

    // Tool 8: checkpoint_state (Phase 24H-3)
    server.registerTool(
      'checkpoint_state',
      'Snapshot current session state (modifications, examined symbols) to a checkpoint file. Use before making risky changes so you can restore later.',
      {
        type: 'object',
        properties: {
          name: {
            type: 'string',
            description: 'Checkpoint name (e.g., "pre-yaml-refactor")'
          },
          description: {
            type: 'string',
            description: 'What this checkpoint represents'
          }
        },
        required: ['name']
      },
      this.checkpointState.bind(this)
    );

    // Tool 9: restore_checkpoint (Phase 24H-3)
    server.registerTool(
      'restore_checkpoint',
      'Roll back session state (modifications, examined symbols) to a previously created checkpoint. Use to undo session tracking when a refactoring approach fails.',
      {
        type: 'object',
        properties: {
          checkpoint_id: {
            type: 'string',
            description: 'Checkpoint ID to restore (from checkpoint_state response or get_session_context)'
          }
        },
        required: ['checkpoint_id']
      },
      this.restoreCheckpoint.bind(this)
    );

    console.error('[OK] Registered 9 GraphRAG tools (Phase 24H-1/24H-3)');
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

      // Phase 24H-3: Auto-record examined symbol
      try {
        this.sessionManager.recordExamined(symbol, {
          type: node.labels?.[0],
          path: node.path || null
        });
      } catch (_) {
        // Silent — session tracking is best-effort
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

      // Phase 51 fix: over-fetch, then filter by similarity floor and prefer
      // curated L1/L2 hierarchy (added in Phase 24E) over noisy L0 micro-leaves.
      const SIMILARITY_FLOOR = 0.2;
      const MIN_LEVEL = 1;
      const LEVEL_BOOST = 0.25;

      const raw = await this.dataAccess.vectorDB.query(
        COMMUNITY_COLLECTION, query, { nResults: Math.max(max_results * 4, 20) }
      );

      const scored = (raw || []).map(r => {
        const similarity = r.score != null
          ? r.score
          : (r.distance != null ? 1 - r.distance : 0);
        const levelRaw = r.metadata?.level;
        const level = typeof levelRaw === 'number'
          ? levelRaw
          : (levelRaw != null ? Number(levelRaw) || 0 : 0);
        return {
          ...r,
          similarity,
          level,
          rankScore: similarity * (1 + LEVEL_BOOST * level)
        };
      });

      const filtered = scored
        .filter(r => r.level >= MIN_LEVEL && r.similarity >= SIMILARITY_FLOOR)
        .sort((a, b) => b.rankScore - a.rankScore)
        .slice(0, max_results);

      if (filtered.length === 0) {
        return {
          content: [{
            type: 'text',
            text: `No high-confidence architectural matches for "${query}" (similarity floor ${SIMILARITY_FLOOR}, level >= ${MIN_LEVEL}). Try a more specific symbol or filename.`
          }]
        };
      }

      let response = `# Architecture Search: "${query}"\n\n`;
      response += `Found ${filtered.length} relevant subsystems/communities (filtered: similarity >= ${SIMILARITY_FLOOR}, level >= ${MIN_LEVEL}):\n\n`;

      for (let i = 0; i < filtered.length; i++) {
        const r = filtered[i];
        response += `## ${i + 1}. ${r.metadata?.communityId != null ? `Community ${r.metadata.communityId}` : 'Community'} (similarity: ${r.similarity.toFixed(3)}, level: ${r.level})\n\n`;
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

  // ---- Phase 24H-3: Session State Tool Handlers ----

  /**
   * mark_as_modified — record a file modification in the active session
   */
  async markAsModified(args) {
    const filePath = args.file_path;
    const { change_type = 'content', description = '' } = args;

    try {
      const session = this.sessionManager.markAsModified(filePath, change_type, description);

      // Best-effort: mark Neo4j node as dirty if graph is available
      let graphDirty = false;
      try {
        if (this.isInitialized && this.dataAccess?.graphDB) {
          await this.dataAccess.graphDB.query(
            `MATCH (n) WHERE n.absolutePath CONTAINS $path
             SET n._dirty = true, n._dirtyAt = $now
             RETURN count(n) AS updated`,
            { path: filePath, now: new Date().toISOString() }
          );
          graphDirty = true;
        }
      } catch (_) {
        // Graph unavailable — session state still recorded
      }

      const mods = session.modifications || [];
      let response = `# File Modification Recorded\n\n`;
      response += `**File**: \`${filePath}\`\n`;
      response += `**Change Type**: ${change_type}\n`;
      if (description) response += `**Description**: ${description}\n`;
      response += `**Graph Dirty**: ${graphDirty ? 'Yes (node flagged)' : 'No (graph unavailable)'}\n`;
      response += `\n**Total Modifications**: ${mods.length}\n`;

      return { content: [{ type: 'text', text: response }] };
    } catch (error) {
      return { content: [{ type: 'text', text: `[ERROR] mark_as_modified failed: ${error.message}` }] };
    }
  }

  /**
   * get_session_context — aggregated view of the active session
   */
  async getSessionContext(args) {
    try {
      const ctx = this.sessionManager.getSessionContext();

      if (!ctx.active) {
        return { content: [{ type: 'text', text: '# No Active Session\n\nStart a session with `start_sdd_session` to enable session state tracking.' }] };
      }

      let response = `# Session Context\n\n`;
      response += `**Session**: ${ctx.sessionId}\n`;
      response += `**Phase**: ${ctx.phase}\n`;
      response += `**Started**: ${ctx.startedAt}\n`;
      response += `**Last Activity**: ${ctx.lastActivityAt}\n`;
      response += `**Progress**: ${ctx.summary.stepsCompleted}/${ctx.totalSteps} steps\n\n`;

      // Summary
      response += `## Summary\n\n`;
      response += `| Metric | Count |\n|--------|-------|\n`;
      response += `| Files Modified | ${ctx.summary.filesModified} |\n`;
      response += `| Symbols Examined | ${ctx.summary.symbolsExamined} |\n`;
      response += `| Checkpoints | ${ctx.summary.checkpointsCreated} |\n`;
      response += `| Steps Completed | ${ctx.summary.stepsCompleted} |\n`;
      response += `| Steps Remaining | ${ctx.summary.stepsRemaining} |\n\n`;

      // Modifications
      if (ctx.modifications.length > 0) {
        response += `## Modifications (${ctx.modifications.length})\n\n`;
        response += '| File | Type | Description | When |\n|------|------|-------------|------|\n';
        for (const m of ctx.modifications) {
          response += `| \`${m.filePath}\` | ${m.changeType} | ${m.description || '-'} | ${m.modifiedAt} |\n`;
        }
        response += '\n';
      }

      // Examined symbols
      if (ctx.examined.length > 0) {
        response += `## Examined Symbols (${ctx.examined.length})\n\n`;
        for (const e of ctx.examined) {
          response += `- \`${e.symbol}\`${e.type ? ` (${e.type})` : ''}\n`;
        }
        response += '\n';
      }

      // Checkpoints
      if (ctx.checkpoints.length > 0) {
        response += `## Checkpoints (${ctx.checkpoints.length})\n\n`;
        response += '| ID | Name | Created |\n|----|------|---------|\n';
        for (const c of ctx.checkpoints) {
          response += `| \`${c.checkpointId}\` | ${c.name} | ${c.createdAt} |\n`;
        }
        response += '\n';
      }

      return { content: [{ type: 'text', text: response }] };
    } catch (error) {
      return { content: [{ type: 'text', text: `[ERROR] get_session_context failed: ${error.message}` }] };
    }
  }

  /**
   * checkpoint_state — snapshot current session state
   */
  async checkpointState(args) {
    const { name, description = '' } = args;

    try {
      const checkpoint = this.sessionManager.createCheckpoint(name, description);

      let response = `# Checkpoint Created\n\n`;
      response += `**ID**: \`${checkpoint.checkpointId}\`\n`;
      response += `**Name**: ${name}\n`;
      if (description) response += `**Description**: ${description}\n`;
      response += `**Created**: ${checkpoint.createdAt}\n\n`;
      response += `**Snapshot**: ${checkpoint.modifications.length} modification(s), ${checkpoint.examined.length} examined symbol(s), ${checkpoint.completedSteps.length} step(s)\n\n`;
      response += `Use \`restore_checkpoint("${checkpoint.checkpointId}")\` to roll back to this state.\n`;

      return { content: [{ type: 'text', text: response }] };
    } catch (error) {
      return { content: [{ type: 'text', text: `[ERROR] checkpoint_state failed: ${error.message}` }] };
    }
  }

  /**
   * restore_checkpoint — roll back session state to a named checkpoint
   */
  async restoreCheckpoint(args) {
    const checkpointId = args.checkpoint_id;

    try {
      const session = this.sessionManager.restoreCheckpoint(checkpointId);

      let response = `# Checkpoint Restored\n\n`;
      response += `**Checkpoint**: \`${checkpointId}\`\n`;
      response += `**Modifications**: ${(session.modifications || []).length} file(s)\n`;
      response += `**Examined**: ${(session.examined || []).length} symbol(s)\n\n`;
      response += `Session state rolled back. New modifications/examinations will be tracked from this point.\n`;

      return { content: [{ type: 'text', text: response }] };
    } catch (error) {
      return { content: [{ type: 'text', text: `[ERROR] restore_checkpoint failed: ${error.message}` }] };
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
