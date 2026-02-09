/**
 * UnifiedDataAccess.js - Unified Data Access Layer
 * 
 * Provides unified interface to both Neo4j graph and ChromaDB vector databases.
 * Implements hybrid query patterns combining graph traversal and semantic search.
 * 
 * Features:
 * - Hybrid queries (graph + vector combined)
 * - Context-aware code retrieval
 * - Dependency-enhanced search
 * - Unified health checks
 * - Connection management
 * 
 * @version 1.0.0
 * @author NOAA EMC Global Workflow Team
 */

import { GraphDatabase } from './GraphDatabase.js';
import { VectorDatabase } from './VectorDatabase.js';

export class UnifiedDataAccess {
  constructor(config = {}) {
    this.graphDB = new GraphDatabase(config.neo4j || {});
    this.vectorDB = new VectorDatabase(config.chromadb || {});
    this.connected = false;
    
    this.metrics = {
      hybridQueries: 0,
      graphQueries: 0,
      vectorQueries: 0,
      cacheHits: 0,
      cacheMisses: 0
    };

    // Simple cache for frequently accessed data
    this.cache = new Map();
    this.cacheTimeout = config.cacheTimeout || 300000; // 5 minutes default
  }

  /**
   * Initialize connections to both databases
   */
  async connect() {
    if (this.connected) {
      return;
    }

    try {
      await Promise.all([
        this.graphDB.connect().catch(err => {
          console.error('[WARN] GraphDB connection failed:', err.message);
          console.error('   Continuing with VectorDB only...');
          return null; // Continue even if graphDB fails
        }),
        this.vectorDB.connect().catch(err => {
          console.error('[WARN] VectorDB connection failed:', err.message);
          console.error('   Continuing with GraphDB only...');
          return null; // Continue even if vectorDB fails
        })
      ]);

      this.connected = true;
      console.log('[OK] Unified Data Access Layer connected');
    } catch (error) {
      console.error('[ERROR] Failed to initialize databases:', error.message);
      // Mark as connected anyway to allow partial functionality
      this.connected = true;
      throw new Error(`Database initialization failed: ${error.message}`);
    }
  }

  /**
   * Hybrid query: Semantic search with graph context enrichment
   * @param {string} queryText - Search query
   * @param {object} options - Query options
   * @returns {Promise<Array>} Results with graph context
   */
  async hybridQuery(queryText, options = {}) {
    if (!this.connected) {
      await this.connect();
    }

    const {
      collection = 'global-workflow-docs-v8-0-0',  // v8.0.0: MPNet embeddings
      nResults = 10,
      includeGraphContext = true,
      includeDependencies = true,
      includeCallers = true
    } = options;

    this.metrics.hybridQueries++;

    try {
      // Step 1: Vector search for relevant documents
      console.error(`[STATS] Starting vector query: collection="${collection}", query="${queryText}", nResults=${nResults}`);
      const vectorResults = await this.vectorDB.query(collection, queryText, { nResults });
      console.error(`[OK] Vector query returned ${vectorResults.length} results`);
      this.metrics.vectorQueries++;

      if (!includeGraphContext || vectorResults.length === 0) {
        console.error(`[SKIP]  Skipping graph enrichment (includeGraphContext=${includeGraphContext}, resultCount=${vectorResults.length})`);
        return vectorResults;
      }

      // Step 2: Enrich results with graph context
      console.error(`🔗 Starting graph enrichment for ${vectorResults.length} results...`);
      const enrichedResults = await Promise.all(
        vectorResults.map(async (result) => {
          const enriched = { ...result };
          const filePath = result.metadata?.filePath || result.metadata?.file;

          if (!filePath) {
            return enriched;
          }

          // Add graph context
          enriched.graphContext = {};

          try {
            // Get imports/dependencies
            if (includeDependencies) {
              enriched.graphContext.imports = await this.graphDB.findFileImports(filePath);
            }

            // Get functions and classes
            const [functions, classes] = await Promise.all([
              this.graphDB.findFileFunctions(filePath),
              this.graphDB.findFileClasses(filePath)
            ]);
            
            enriched.graphContext.functions = functions;
            enriched.graphContext.classes = classes;

            // Get callers for functions (if requested)
            if (includeCallers && functions.length > 0) {
              const callers = await Promise.all(
                functions.slice(0, 3).map(f => // Limit to first 3 functions
                  this.graphDB.findCallers(f.functionName)
                    .catch(() => [])
                )
              );
              enriched.graphContext.callers = callers.flat();
            }

          } catch (error) {
            console.warn(`Failed to enrich ${filePath} with graph context:`, error.message);
          }

          return enriched;
        })
      );

      return enrichedResults;
    } catch (error) {
      console.error('Hybrid query failed:', error.message);
      throw error;
    }
  }

  /**
   * Graph-to-Vector enrichment: Fetch ChromaDB content for graph-discovered nodes
   * 
   * This is the "reverse hybrid query" — takes Neo4j node names/paths and fetches
   * semantic content from ChromaDB to provide context alongside graph structure.
   * 
   * Use cases:
   *   - find_env_dependencies: enrich script names with descriptions/content
   *   - find_callers_callees: add semantic context to bare function names
   *   - analyze_code_structure: attach content snippets to graph node results
   * 
   * @param {Array<string>} identifiers - Node names, file paths, or script names from graph
   * @param {object} options - Enrichment options
   * @returns {Promise<Map<string, object>>} Map of identifier -> {content, metadata}
   * @version 1.0.0  Phase 24 Gap 2
   */
  async enrichGraphResults(identifiers, options = {}) {
    if (!this.connected) {
      await this.connect();
    }

    const {
      collection = 'code-with-context-v8-0-0',
      nResultsPerQuery = 2,
      maxIdentifiers = 15,    // Limit concurrent queries
      includeContent = true
    } = options;

    this.metrics.vectorQueries++;

    const enrichmentMap = new Map();
    const queryBatch = identifiers.slice(0, maxIdentifiers);

    try {
      const results = await Promise.all(
        queryBatch.map(async (identifier) => {
          try {
            // Query ChromaDB for content matching this graph node
            const vectorHits = await this.vectorDB.query(
              collection,
              identifier,
              { nResults: nResultsPerQuery }
            );

            if (vectorHits && vectorHits.length > 0) {
              const best = vectorHits[0];
              return {
                identifier,
                content: includeContent ? (best.document || best.content || '').substring(0, 500) : null,
                metadata: best.metadata || {},
                score: best.score || best.distance,
                found: true
              };
            }
            return { identifier, found: false };
          } catch (err) {
            return { identifier, found: false, error: err.message };
          }
        })
      );

      for (const r of results) {
        if (r.found) {
          enrichmentMap.set(r.identifier, r);
        }
      }

      return enrichmentMap;
    } catch (error) {
      console.error('[WARN] Graph-to-vector enrichment failed:', error.message);
      return enrichmentMap; // Return empty map, don't break the tool
    }
  }

  /**
   * Find code with dependencies (graph-first approach)
   * @param {string} identifier - Function/class/file name
   * @param {object} options - Query options
   * @returns {Promise<object>} Code with full dependency context
   */
  async findCodeWithDependencies(identifier, options = {}) {
    if (!this.connected) {
      await this.connect();
    }

    const { maxDepth = 2, includeSemanticSimilar = true } = options;

    this.metrics.graphQueries++;

    try {
      // Step 1: Search graph for the identifier
      let filePath = identifier;
      let functions = [];
      let classes = [];

      // Try to find as file first
      if (!identifier.includes('/')) {
        // Might be a function or class name
        const searchResults = await this.graphDB.query(
          `MATCH (n) WHERE n.name = $name RETURN labels(n) as labels, n`,
          { name: identifier }
        );

        if (searchResults.length > 0) {
          const node = searchResults[0];
          if (node.labels.includes('Function')) {
            functions = [node.n];
            // Find the file containing this function
            const fileResult = await this.graphDB.query(
              `MATCH (f:File)-[:DEFINES]->(func:Function {name: $name}) RETURN f.path as path`,
              { name: identifier }
            );
            filePath = fileResult[0]?.path;
          } else if (node.labels.includes('Class')) {
            classes = [node.n];
            const fileResult = await this.graphDB.query(
              `MATCH (f:File)-[:DEFINES]->(c:Class {name: $name}) RETURN f.path as path`,
              { name: identifier }
            );
            filePath = fileResult[0]?.path;
          }
        }
      }

      if (!filePath) {
        throw new Error(`Could not find ${identifier} in graph database`);
      }

      // Step 2: Get full dependency graph
      const [imports, dependencyGraph, fileInfo] = await Promise.all([
        this.graphDB.findFileImports(filePath),
        this.graphDB.findDependencyGraph(filePath, maxDepth),
        this.graphDB.query(
          `MATCH (f:File {path: $path}) RETURN f`,
          { path: filePath }
        )
      ]);

      // Step 3: Get functions and classes if not already loaded
      if (functions.length === 0) {
        functions = await this.graphDB.findFileFunctions(filePath);
      }
      if (classes.length === 0) {
        classes = await this.graphDB.findFileClasses(filePath);
      }

      // Step 4: Get callers for each function
      const callersMap = {};
      for (const func of functions) {
        callersMap[func.functionName] = await this.graphDB.findCallers(func.functionName);
      }

      // Step 5: Optionally get semantically similar code
      let similarCode = [];
      if (includeSemanticSimilar && fileInfo.length > 0) {
        try {
          similarCode = await this.vectorDB.query(
            'code-with-context-v8-0-0',  // v8.0.0: MPNet embeddings
            identifier,
            { nResults: 5 }
          );
        } catch (error) {
          console.warn('[WARN] Failed to fetch similar code from vector DB:', error.message);
        }
      }

      return {
        identifier,
        filePath,
        file: fileInfo[0]?.f || {},
        imports,
        dependencyGraph,
        functions,
        classes,
        callersMap,
        similarCode
      };

    } catch (error) {
      console.error(`Failed to find code with dependencies for ${identifier}:`, error.message);
      throw error;
    }
  }

  /**
   * Search across multiple collections with graph enrichment
   * @param {string} queryText - Search query
   * @param {object} options - Query options
   * @returns {Promise<Array>} Combined results
   */
  async multiSourceSearch(queryText, options = {}) {
    if (!this.connected) {
      await this.connect();
    }

    const {
      // v8.0.0 for docs, v5.0.0 for EE2 (already MPNet)
      collections = ['global-workflow-docs-v8-0-0', 'ee2-standards-v5-0-0-enhanced'],
      nResults = 10,
      enrichWithGraph = true
    } = options;

    this.metrics.hybridQueries++;

    try {
      // Search all collections in parallel
      const results = await this.vectorDB.multiCollectionQuery(
        collections,
        queryText,
        { nResults }
      );

      // Enrich with graph data if requested
      if (enrichWithGraph) {
        for (const result of results) {
          const filePath = result.metadata?.filePath || result.metadata?.file;
          // Enrich any result with file path, regardless of collection
          if (filePath) {
            try {
              const [imports, functions] = await Promise.all([
                this.graphDB.findFileImports(filePath).catch(() => []),
                this.graphDB.findFileFunctions(filePath).catch(() => [])
              ]);
              result.graphContext = { imports, functions };
            } catch (error) {
              // Silent fail - not all documents will have graph data
            }
          }
        }
      }

      return results;
    } catch (error) {
      console.error('Multi-source search failed:', error.message);
      throw error;
    }
  }

  /**
   * Find related code based on dependencies
   * @param {string} filePath - File path
   * @param {object} options - Query options
   * @returns {Promise<object>} Related code and documentation
   */
  async findRelatedCode(filePath, options = {}) {
    if (!this.connected) {
      await this.connect();
    }

    const { includeDocumentation = true, maxResults = 20 } = options;

    this.metrics.graphQueries++;

    try {
      // Get imports and dependency graph
      const [imports, dependencyGraph] = await Promise.all([
        this.graphDB.findFileImports(filePath),
        this.graphDB.findDependencyGraph(filePath, 2)
      ]);

      // Extract unique module names
      const moduleNames = [...new Set(imports.map(i => i.moduleName))];

      // Find files that import the same modules
      const relatedFiles = await Promise.all(
        moduleNames.slice(0, 5).map(moduleName =>
          this.graphDB.findImporters(moduleName)
        )
      );

      // Get documentation if requested
      let documentation = [];
      if (includeDocumentation && moduleNames.length > 0) {
        // Search for documentation about these modules
        const docQuery = moduleNames.slice(0, 3).join(' ');
        documentation = await this.vectorDB.query(
          'global-workflow-docs-v8-0-0',  // v8.0.0: MPNet embeddings
          docQuery,
          { nResults: 5 }
        );
      }

      return {
        filePath,
        imports,
        dependencyGraph,
        relatedFiles: relatedFiles.flat().slice(0, maxResults),
        documentation
      };

    } catch (error) {
      console.error(`Failed to find related code for ${filePath}:`, error.message);
      throw error;
    }
  }

  /**
   * Trace execution path (graph-based call chain)
   * @param {string} functionName - Starting function
   * @param {object} options - Trace options
   * @returns {Promise<object>} Call chain with code snippets
   */
  async traceExecutionPath(functionName, options = {}) {
    if (!this.connected) {
      await this.connect();
    }

    const { maxDepth = 3, includeCode = true } = options;

    this.metrics.graphQueries++;

    try {
      // Get call chain from graph
      const callChain = await this.graphDB.traceCallChain(functionName, maxDepth);

      // Get callers (reverse direction)
      const callers = await this.graphDB.findCallers(functionName);

      // If includeCode, fetch code snippets from ChromaDB
      let codeSnippets = {};
      if (includeCode) {
        // Get unique function names from call chain
        const allFunctions = new Set();
        callChain.forEach(chain => {
          chain.callChain?.forEach(fn => allFunctions.add(fn));
        });

        // Fetch code snippets (limit to prevent overwhelming response)
        const snippetPromises = Array.from(allFunctions)
          .slice(0, 10)
          .map(async (fn) => {
            try {
              const results = await this.vectorDB.query(
                'code-with-context-v8-0-0',  // v8.0.0: MPNet embeddings
                fn,
                { nResults: 1 }
              );
              return [fn, results[0] || null];
            } catch (error) {
              return [fn, null];
            }
          });

        const snippets = await Promise.all(snippetPromises);
        codeSnippets = Object.fromEntries(snippets);
      }

      return {
        functionName,
        callChain,
        callers,
        codeSnippets
      };

    } catch (error) {
      console.error(`Failed to trace execution path for ${functionName}:`, error.message);
      throw error;
    }
  }

  /**
   * Get comprehensive statistics from both databases
   * @returns {Promise<object>} Combined statistics
   */
  async getStatistics() {
    if (!this.connected) {
      await this.connect();
    }

    try {
      const [graphStats, graphRelStats, collections] = await Promise.all([
        this.graphDB.getStatistics(),
        this.graphDB.getRelationshipStats(),
        this.vectorDB.listCollections()
      ]);

      // Get counts for each collection
      const collectionCounts = await Promise.all(
        collections.map(async (name) => {
          const count = await this.vectorDB.getCollectionCount(name);
          return [name, count];
        })
      );

      return {
        graph: {
          ...graphStats,
          relationships: graphRelStats
        },
        vector: {
          collections: Object.fromEntries(collectionCounts),
          totalCollections: collections.length
        },
        unified: {
          ...this.metrics,
          cacheSize: this.cache.size
        }
      };

    } catch (error) {
      console.error('Failed to get statistics:', error.message);
      throw error;
    }
  }

  /**
   * Health check for both databases
   * @returns {Promise<object>} Health status
   */
  async healthCheck() {
    try {
      const [graphHealth, vectorHealth] = await Promise.all([
        this.graphDB.healthCheck(),
        this.vectorDB.healthCheck()
      ]);

      const overallStatus = 
        graphHealth.status === 'healthy' && vectorHealth.status === 'healthy'
          ? 'healthy'
          : 'degraded';

      return {
        status: overallStatus,
        connected: this.connected,
        graph: graphHealth,
        vector: vectorHealth,
        metrics: this.metrics,
        timestamp: new Date().toISOString()
      };
    } catch (error) {
      return {
        status: 'unhealthy',
        connected: false,
        error: error.message,
        timestamp: new Date().toISOString()
      };
    }
  }

  /**
   * Clear cache
   */
  clearCache() {
    this.cache.clear();
    console.log('[OK] Cache cleared');
  }

  /**
   * Get cached result or execute function
   * @private
   */
  async _getOrCache(key, fn, ttl = this.cacheTimeout) {
    if (this.cache.has(key)) {
      const cached = this.cache.get(key);
      if (Date.now() - cached.timestamp < ttl) {
        this.metrics.cacheHits++;
        return cached.data;
      }
      this.cache.delete(key);
    }

    this.metrics.cacheMisses++;
    const data = await fn();
    this.cache.set(key, { data, timestamp: Date.now() });
    return data;
  }

  /**
   * Get metrics
   * @returns {object} Current metrics
   */
  getMetrics() {
    return {
      unified: this.metrics,
      graph: this.graphDB.getMetrics(),
      vector: this.vectorDB.getMetrics()
    };
  }

  /**
   * Close all connections
   */
  async close() {
    await Promise.all([
      this.graphDB.close(),
      this.vectorDB.close()
    ]);
    this.clearCache();
    this.connected = false;
    console.log('[OK] Unified Data Access Layer closed');
  }
}
