/**
 * GraphDatabase.js - Neo4j Graph Database Client
 * 
 * Provides connection and query methods for Neo4j graph database.
 * Handles code structure relationships (IMPORTS, CALLS, DEFINES).
 * 
 * Features:
 * - Connection pooling with Bolt driver
 * - Common query patterns for code analysis
 * - Dependency tracing and call graph traversal
 * - Health checks and metrics
 * - Automatic reconnection handling
 * 
 * @version 1.0.0
 * @author NOAA EMC Global Workflow Team
 */

import neo4j from 'neo4j-driver';

export class GraphDatabase {
  constructor(config = {}) {
    this.config = {
      uri: config.uri || process.env.NEO4J_URI || 'bolt://localhost:7687',
      username: config.username || process.env.NEO4J_USERNAME || 'neo4j',
      password: config.password || process.env.NEO4J_PASSWORD || 'gfsworkflow2025',
      database: config.database || process.env.NEO4J_DATABASE || 'neo4j',
      maxConnectionPoolSize: config.maxConnectionPoolSize || 50,
      connectionTimeout: config.connectionTimeout || 30000,
      ...config
    };

    this.driver = null;
    this.connected = false;
    this.metrics = {
      queriesExecuted: 0,
      queriesFailed: 0,
      avgQueryTime: 0,
      lastQueryTime: null
    };
  }

  /**
   * Initialize connection to Neo4j
   */
  async connect() {
    if (this.connected) {
      return;
    }

    try {
      this.driver = neo4j.driver(
        this.config.uri,
        neo4j.auth.basic(this.config.username, this.config.password),
        {
          maxConnectionPoolSize: this.config.maxConnectionPoolSize,
          connectionTimeout: this.config.connectionTimeout,
          disableLosslessIntegers: true // Return numbers as JS numbers, not BigInt
        }
      );

      // Verify connection
      await this.driver.verifyConnectivity();
      this.connected = true;
      console.log('[OK] Connected to Neo4j:', this.config.uri);
    } catch (error) {
      console.error('[ERROR] Failed to connect to Neo4j:', error.message);
      throw error;
    }
  }

  /**
   * Execute a Cypher query
   * @param {string} cypher - Cypher query string
   * @param {object} params - Query parameters
   * @returns {Promise<Array>} Query results
   */
  async query(cypher, params = {}) {
    if (!this.connected) {
      await this.connect();
    }

    const session = this.driver.session({
      database: this.config.database,
      defaultAccessMode: neo4j.session.READ
    });

    const startTime = Date.now();

    try {
      const result = await session.run(cypher, params);
      const queryTime = Date.now() - startTime;

      // Update metrics
      this.metrics.queriesExecuted++;
      this.metrics.lastQueryTime = queryTime;
      this.metrics.avgQueryTime = 
        (this.metrics.avgQueryTime * (this.metrics.queriesExecuted - 1) + queryTime) / 
        this.metrics.queriesExecuted;

      // Convert Neo4j records to plain objects
      return result.records.map(record => this._recordToObject(record));
    } catch (error) {
      this.metrics.queriesFailed++;
      console.error('Query failed:', error.message);
      throw error;
    } finally {
      await session.close();
    }
  }

  /**
   * Find all files that import a specific module
   * @param {string} moduleName - Name of the module
   * @returns {Promise<Array>} Files that import this module
   */
  async findImporters(moduleName) {
    const cypher = `
      MATCH (f:File)-[i:IMPORTS]->(m:Module {name: $moduleName})
      RETURN f.path as file, 
             i.type as importType, 
             i.itemName as importedItem,
             i.lineNumber as lineNumber
      ORDER BY f.path
    `;
    return this.query(cypher, { moduleName });
  }

  /**
   * Find all imports in a file
   * @param {string} filePath - Path to the file
   * @returns {Promise<Array>} All imports in the file
   */
  async findFileImports(filePath) {
    const cypher = `
      MATCH (f:File {path: $filePath})-[i:IMPORTS]->(m:Module)
      RETURN m.name as moduleName,
             i.type as importType,
             i.itemName as importedItem,
             i.alias as alias,
             i.lineNumber as lineNumber
      ORDER BY i.lineNumber
    `;
    return this.query(cypher, { filePath });
  }

  /**
   * Trace call chain from a function
   * @param {string} functionName - Name of the function
   * @param {number} depth - Maximum depth to trace (default: 3)
   * @returns {Promise<Array>} Call chain with relationships
   */
  async traceCallChain(functionName, depth = 3) {
    const cypher = `
      MATCH path = (f:Function {name: $functionName})-[:CALLS*1..${depth}]->(called:Function)
      RETURN f.name as source,
             [n in nodes(path) | n.name] as callChain,
             length(path) as depth
      ORDER BY depth
      LIMIT 100
    `;
    return this.query(cypher, { functionName });
  }

  /**
   * Find functions that call a specific function (reverse call chain)
   * @param {string} functionName - Name of the function
   * @returns {Promise<Array>} Functions that call this function
   */
  async findCallers(functionName) {
    const cypher = `
      MATCH (caller:Function)-[c:CALLS]->(f:Function {name: $functionName})
      MATCH (file:File)-[:DEFINES]->(caller)
      RETURN caller.name as callerName,
             file.path as callerFile,
             c.lineNumber as lineNumber
      ORDER BY callerFile
    `;
    return this.query(cypher, { functionName });
  }

  /**
   * Find all functions defined in a file
   * @param {string} filePath - Path to the file
   * @returns {Promise<Array>} Functions in the file
   */
  async findFileFunctions(filePath) {
    const cypher = `
      MATCH (f:File {path: $filePath})-[:DEFINES]->(func:Function)
      RETURN func.name as functionName,
             func.lineNumber as lineNumber,
             func.endLineNumber as endLineNumber,
             func.decorators as decorators,
             func.async as isAsync
      ORDER BY func.lineNumber
    `;
    return this.query(cypher, { filePath });
  }

  /**
   * Find all classes defined in a file
   * @param {string} filePath - Path to the file
   * @returns {Promise<Array>} Classes in the file
   */
  async findFileClasses(filePath) {
    const cypher = `
      MATCH (f:File {path: $filePath})-[:DEFINES]->(c:Class)
      OPTIONAL MATCH (c)-[:HAS_METHOD]->(m:Function)
      RETURN c.name as className,
             c.lineNumber as lineNumber,
             c.baseClasses as baseClasses,
             collect(m.name) as methods
      ORDER BY c.lineNumber
    `;
    return this.query(cypher, { filePath });
  }

  /**
   * Analyze module usage across the codebase
   * @param {string} moduleName - Name of the module
   * @returns {Promise<object>} Usage statistics
   */
  async analyzeModuleUsage(moduleName) {
    const cypher = `
      MATCH (f:File)-[i:IMPORTS]->(m:Module {name: $moduleName})
      WITH m, count(DISTINCT f) as importCount, collect(DISTINCT f.path) as files
      RETURN m.name as moduleName,
             importCount,
             files
    `;
    const results = await this.query(cypher, { moduleName });
    return results[0] || { moduleName, importCount: 0, files: [] };
  }

  /**
   * Find dependency graph for a file (imports and their imports)
   * @param {string} filePath - Path to the file
   * @param {number} depth - Depth of dependency graph (default: 2)
   * @returns {Promise<Array>} Dependency graph
   */
  async findDependencyGraph(filePath, depth = 2) {
    const cypher = `
      MATCH path = (f:File {path: $filePath})-[:IMPORTS*1..${depth}]->(m:Module)
      RETURN [n in nodes(path) | CASE 
        WHEN 'File' IN labels(n) THEN {type: 'File', name: n.path}
        WHEN 'Module' IN labels(n) THEN {type: 'Module', name: n.name}
      END] as dependencyPath
      LIMIT 100
    `;
    return this.query(cypher, { filePath });
  }

  /**
   * Find circular dependencies
   * @param {number} maxDepth - Maximum depth to check (default: 5)
   * @returns {Promise<Array>} Circular dependency paths
   */
  async findCircularDependencies(maxDepth = 5) {
    const cypher = `
      MATCH path = (f:File)-[:IMPORTS*2..${maxDepth}]->(f)
      WHERE ALL(r in relationships(path) WHERE type(r) = 'IMPORTS')
      RETURN [n in nodes(path) | n.path] as cycle,
             length(path) as cycleLength
      LIMIT 50
    `;
    return this.query(cypher);
  }

  /**
   * Get code structure statistics
   * @returns {Promise<object>} Statistics about the code structure
   */
  async getStatistics() {
    const cypher = `
      MATCH (f:File)
      OPTIONAL MATCH (f)-[:DEFINES]->(func:Function)
      OPTIONAL MATCH (f)-[:DEFINES]->(c:Class)
      OPTIONAL MATCH (f)-[:IMPORTS]->(m:Module)
      RETURN count(DISTINCT f) as fileCount,
             count(DISTINCT func) as functionCount,
             count(DISTINCT c) as classCount,
             count(DISTINCT m) as moduleCount
    `;
    const results = await this.query(cypher);
    return results[0] || { fileCount: 0, functionCount: 0, classCount: 0, moduleCount: 0 };
  }

  /**
   * Get relationship statistics
   * @returns {Promise<object>} Statistics about relationships
   */
  async getRelationshipStats() {
    const cypher = `
      MATCH ()-[r]->()
      RETURN type(r) as relationshipType, count(r) as count
      ORDER BY count DESC
    `;
    return this.query(cypher);
  }

  /**
   * Search files by pattern
   * @param {string} pattern - File path pattern (supports wildcards)
   * @returns {Promise<Array>} Matching files
   */
  async searchFiles(pattern) {
    const cypher = `
      MATCH (f:File)
      WHERE f.path CONTAINS $pattern
      RETURN f.path as filePath,
             f.language as language,
             f.absolutePath as absolutePath
      ORDER BY f.path
      LIMIT 100
    `;
    return this.query(cypher, { pattern });
  }

  /**
   * Find files by language
   * @param {string} language - Programming language
   * @returns {Promise<Array>} Files in that language
   */
  async findFilesByLanguage(language) {
    const cypher = `
      MATCH (f:File {language: $language})
      RETURN f.path as filePath,
             f.absolutePath as absolutePath
      ORDER BY f.path
    `;
    return this.query(cypher, { language });
  }

  /**
   * Add chunk ID to a file node (for linking to ChromaDB)
   * @param {string} filePath - Path to the file
   * @param {string} chunkId - ChromaDB chunk ID
   */
  async addChunkIdToFile(filePath, chunkId) {
    const cypher = `
      MATCH (f:File {path: $filePath})
      SET f.chunkId = $chunkId
      RETURN f.path as filePath, f.chunkId as chunkId
    `;
    return this.query(cypher, { filePath, chunkId });
  }

  /**
   * Add chunk IDs to function nodes (for linking to ChromaDB)
   * @param {string} functionName - Name of the function
   * @param {string} filePath - Path to the file containing the function
   * @param {string} chunkId - ChromaDB chunk ID
   */
  async addChunkIdToFunction(functionName, filePath, chunkId) {
    const cypher = `
      MATCH (f:File {path: $filePath})-[:DEFINES]->(func:Function {name: $functionName})
      SET func.chunkId = $chunkId
      RETURN func.name as functionName, func.chunkId as chunkId
    `;
    return this.query(cypher, { functionName, filePath, chunkId });
  }

  /**
   * Health check - verify connection and basic query
   * @returns {Promise<object>} Health status
   */
  async healthCheck() {
    try {
      if (!this.connected) {
        await this.connect();
      }

      const result = await this.query('RETURN 1 as health');
      const stats = await this.getStatistics();

      return {
        status: 'healthy',
        connected: this.connected,
        metrics: this.metrics,
        statistics: stats,
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
   * Close the connection
   */
  async close() {
    if (this.driver) {
      await this.driver.close();
      this.connected = false;
      console.log('[OK] Neo4j connection closed');
    }
  }

  /**
   * Convert Neo4j record to plain JavaScript object
   * @private
   */
  _recordToObject(record) {
    const obj = {};
    record.keys.forEach(key => {
      const value = record.get(key);
      obj[key] = this._convertValue(value);
    });
    return obj;
  }

  /**
   * Convert Neo4j values to plain JavaScript
   * @private
   */
  _convertValue(value) {
    if (value === null || value === undefined) {
      return value;
    }

    // Handle Neo4j Integer
    if (neo4j.isInt(value)) {
      return value.toNumber();
    }

    // Handle arrays
    if (Array.isArray(value)) {
      return value.map(v => this._convertValue(v));
    }

    // Handle objects
    if (typeof value === 'object' && value.constructor.name === 'Object') {
      const converted = {};
      Object.keys(value).forEach(key => {
        converted[key] = this._convertValue(value[key]);
      });
      return converted;
    }

    return value;
  }

  // ============================================================================
  // SHELL SCRIPT GRAPH METHODS (Phase 27B)
  // ============================================================================

  /**
   * Find scripts that source/invoke a specific script
   * @param {string} scriptName - Name of the shell script (e.g., JGFS_ATMOS_ANALYSIS)
   * @returns {Promise<Array>} Scripts that source or invoke this script
   */
  async findScriptCallers(scriptName) {
    const cypher = `
      MATCH (caller:ShellScript)-[r:SOURCES|INVOKES]->(s:ShellScript)
      WHERE s.name CONTAINS $scriptName OR s.path CONTAINS $scriptName
      RETURN caller.name as name,
             caller.path as file,
             caller.type as type,
             type(r) as relationship,
             r.line as lineNumber
      ORDER BY caller.type, caller.name
    `;
    return this.query(cypher, { scriptName });
  }

  /**
   * Find scripts that are sourced/invoked by a script
   * @param {string} scriptName - Name of the shell script
   * @param {number} depth - Maximum depth to trace (default: 2)
   * @returns {Promise<Array>} Scripts sourced or invoked by this script
   */
  async traceScriptChain(scriptName, depth = 2) {
    const cypher = `
      MATCH (s:ShellScript)
      WHERE s.name CONTAINS $scriptName OR s.path CONTAINS $scriptName
      MATCH path = (s)-[:SOURCES|INVOKES*1..${depth}]->(target:ShellScript)
      RETURN DISTINCT target.name as name,
             target.path as file,
             target.type as type,
             length(path) as depth
      ORDER BY depth, target.type, target.name
      LIMIT 100
    `;
    return this.query(cypher, { scriptName });
  }

  /**
   * Find environment variables a script depends on
   * @param {string} scriptName - Name of the shell script
   * @returns {Promise<Array>} Environment variables used by this script
   */
  async findScriptEnvDeps(scriptName) {
    const cypher = `
      MATCH (s:ShellScript)-[:DEPENDS_ON_ENV|EXPORTS]->(e:EnvironmentVariable)
      WHERE s.name CONTAINS $scriptName OR s.path CONTAINS $scriptName
      RETURN s.name as script,
             e.name as envVar,
             e.default_value as defaultValue,
             type(head([(s)-[r]->(e) | r])) as relationship
      ORDER BY e.name
    `;
    return this.query(cypher, { scriptName });
  }

  /**
   * Get shell script graph statistics
   * @returns {Promise<object>} Graph statistics for shell scripts
   */
  async getScriptGraphStats() {
    const queries = {
      totalScripts: 'MATCH (s:ShellScript) RETURN count(s) as count',
      jJobs: "MATCH (s:ShellScript {type: 'j-job'}) RETURN count(s) as count",
      exScripts: "MATCH (s:ShellScript {type: 'ex-script'}) RETURN count(s) as count",
      ushScripts: "MATCH (s:ShellScript {type: 'ush-script'}) RETURN count(s) as count",
      envVars: 'MATCH (e:EnvironmentVariable) RETURN count(e) as count',
      sourcesRels: 'MATCH ()-[r:SOURCES]->() RETURN count(r) as count',
      invokesRels: 'MATCH ()-[r:INVOKES]->() RETURN count(r) as count',
      exportsRels: 'MATCH ()-[r:EXPORTS]->() RETURN count(r) as count',
      dependsRels: 'MATCH ()-[r:DEPENDS_ON_ENV]->() RETURN count(r) as count'
    };

    const stats = {};
    for (const [key, cypher] of Object.entries(queries)) {
      const result = await this.query(cypher, {});
      stats[key] = result[0]?.count || 0;
    }
    return stats;
  }

  /**
   * Get metrics for monitoring
   * @returns {object} Current metrics
   */
  getMetrics() {
    return {
      ...this.metrics,
      connected: this.connected,
      config: {
        uri: this.config.uri,
        database: this.config.database
      }
    };
  }
}
