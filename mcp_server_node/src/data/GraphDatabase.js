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
    // Query both Function and PythonFunction labels (Phase 24I)
    const cypher = `
      MATCH path = (f)-[:CALLS*1..${depth}]->(called)
      WHERE (f:Function OR f:PythonFunction) AND f.name = $functionName
        AND (called:Function OR called:PythonFunction)
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
    // Query both Function and PythonFunction labels (Phase 24I)
    const cypher = `
      MATCH (caller)-[c:CALLS]->(f)
      WHERE (f:Function OR f:PythonFunction) AND f.name = $functionName
      OPTIONAL MATCH (file)-[:DEFINES]->(caller)
      WHERE file:File OR file:PythonModule
      RETURN caller.name as callerName,
             COALESCE(file.path, file.file_path) as callerFile,
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
    // Query both File→Function and PythonModule→PythonFunction (Phase 24I)
    const cypher = `
      MATCH (f)-[:DEFINES]->(func)
      WHERE ((f:File AND f.path = $filePath) OR (f:PythonModule AND f.file_path = $filePath))
        AND (func:Function OR func:PythonFunction)
      RETURN func.name as functionName,
             COALESCE(func.lineNumber, func.line_number) as lineNumber,
             func.endLineNumber as endLineNumber,
             func.decorators as decorators,
             COALESCE(func.async, func.is_async) as isAsync
      ORDER BY COALESCE(func.lineNumber, func.line_number)
    `;
    return this.query(cypher, { filePath });
  }

  /**
   * Find all classes defined in a file
   * @param {string} filePath - Path to the file
   * @returns {Promise<Array>} Classes in the file
   */
  async findFileClasses(filePath) {
    // Query both File→Class and PythonModule→PythonClass (Phase 24I)
    const cypher = `
      MATCH (f)-[:DEFINES]->(c)
      WHERE ((f:File AND f.path = $filePath) OR (f:PythonModule AND f.file_path = $filePath))
        AND (c:Class OR c:PythonClass)
      OPTIONAL MATCH (c)-[:HAS_METHOD|DEFINES]->(m)
      WHERE m:Function OR m:PythonFunction
      RETURN c.name as className,
             COALESCE(c.lineNumber, c.line_number) as lineNumber,
             COALESCE(c.baseClasses, c.base_classes) as baseClasses,
             collect(m.name) as methods
      ORDER BY COALESCE(c.lineNumber, c.line_number)
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
      MATCH (s:CodeFile)-[rel:DEPENDS_ON_ENV|EXPORTS|SETS]->(e:EnvironmentVariable)
      WHERE s.name CONTAINS $scriptName OR s.path CONTAINS $scriptName
      RETURN s.name as script,
             e.name as envVar,
             e.is_ee2_standard as isEE2,
             type(rel) as relationship
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
      totalScripts: "MATCH (s:CodeFile) WHERE s.language = 'shell' RETURN count(s) as count",
      jJobs: "MATCH (s:CodeFile {script_type: 'j-job'}) RETURN count(s) as count",
      exScripts: "MATCH (s:CodeFile {script_type: 'ex-script'}) RETURN count(s) as count",
      ushScripts: "MATCH (s:CodeFile {script_type: 'ush'}) RETURN count(s) as count",
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

  // ============================================================================
  // PYTHON GRAPH METHODS (Phase 24I)
  // ============================================================================

  /**
   * Find Python functions/modules that call a specific function
   * @param {string} name - Name of the Python function
   * @returns {Promise<Array>} Python entities that call this
   */
  async findPythonCallers(name) {
    const cypher = `
      MATCH (caller:PythonFunction)-[c:CALLS]->(target:PythonFunction)
      WHERE target.name =~ $pattern
      OPTIONAL MATCH (mod:PythonModule)-[:DEFINES]->(caller)
      RETURN caller.name as callerName,
             COALESCE(mod.file_path, caller.file_path) as callerFile,
             labels(caller)[0] as callerType,
             'CALLS' as relationship
      ORDER BY callerName
      LIMIT 100
    `;
    return this.query(cypher, { pattern: `(?i)${name}` });
  }

  /**
   * Trace Python call chain (CALLS relationships)
   * @param {string} name - Name of the Python function
   * @param {number} depth - Maximum depth (default: 3)
   * @returns {Promise<Array>} Call chain
   */
  async tracePythonCallChain(name, depth = 3) {
    const depthInt = Math.min(Math.max(parseInt(depth, 10) || 3, 1), 10);
    const cypher = `
      MATCH (start:PythonFunction)
      WHERE start.name =~ $pattern
      MATCH path = (start)-[:CALLS*1..${depthInt}]->(called:PythonFunction)
      RETURN start.name as source,
             called.name as callee,
             called.file_path as file,
             labels(called)[0] as calleeType,
             length(path) as depth
      ORDER BY depth, callee
      LIMIT 100
    `;
    return this.query(cypher, { pattern: `(?i)${name}` });
  }

  /**
   * Get Python graph statistics
   * @returns {Promise<object>} Python graph statistics
   */
  async getPythonGraphStats() {
    const queries = {
      modules: 'MATCH (n:PythonModule) RETURN count(n) as count',
      functions: 'MATCH (n:PythonFunction) RETURN count(n) as count',
      classes: 'MATCH (n:PythonClass) RETURN count(n) as count',
      callsRels: 'MATCH (:PythonFunction)-[r:CALLS]->(:PythonFunction) RETURN count(r) as count',
      importsRels: 'MATCH (:PythonModule)-[r:IMPORTS]->(:PythonModule) RETURN count(r) as count',
      invokesRels: 'MATCH ()-[r:INVOKES]->(:PythonModule) RETURN count(r) as count',
      definesRels: 'MATCH (:PythonModule)-[r:DEFINES]->() RETURN count(r) as count'
    };

    const stats = {};
    for (const [key, cypher] of Object.entries(queries)) {
      const result = await this.query(cypher, {});
      stats[key] = result[0]?.count || 0;
    }
    return stats;
  }

  // ============================================================================
  // FORTRAN GRAPH METHODS (Phase 10 M5)
  // ============================================================================

  /**
   * Find Fortran subroutines/functions that call a specific subroutine
   * @param {string} name - Name of the Fortran subroutine/function
   * @returns {Promise<Array>} Fortran entities that call this
   */
  async findFortranCallers(name) {
    const cypher = `
      MATCH (caller)-[c:CALLS]->(target)
      WHERE (target:FortranSubroutine OR target:FortranFunction OR target:FortranProgram)
        AND target.name =~ $pattern
      RETURN caller.name as callerName,
             caller.filepath as callerFile,
             labels(caller)[0] as callerType,
             'CALLS' as relationship
      ORDER BY callerName
      LIMIT 100
    `;
    return this.query(cypher, { pattern: `(?i).*${name}.*` });
  }

  /**
   * Trace Fortran call chain (CALLS relationships)
   * @param {string} name - Name of the Fortran entity
   * @param {number} depth - Maximum depth (default: 3)
   * @returns {Promise<Array>} Call chain
   */
  async traceFortranCallChain(name, depth = 3) {
    const depthInt = Math.min(Math.max(parseInt(depth, 10) || 3, 1), 10);
    const cypher = `
      MATCH (start)
      WHERE (start:FortranSubroutine OR start:FortranFunction OR start:FortranProgram)
        AND start.name =~ $pattern
      MATCH path = (start)-[:CALLS*1..${depthInt}]->(called)
      RETURN start.name as source,
             called.name as callee,
             called.filepath as file,
             labels(called)[0] as calleeType,
             length(path) as depth
      ORDER BY depth, callee
      LIMIT 100
    `;
    return this.query(cypher, { pattern: `(?i).*${name}.*` });
  }

  /**
   * Find Fortran modules used by a subroutine/program (USES relationships)
   * @param {string} name - Name of the Fortran entity
   * @returns {Promise<Array>} Modules used
   */
  async findFortranModuleUses(name) {
    const cypher = `
      MATCH (user)-[:USES]->(mod:FortranModule)
      WHERE user.name =~ $pattern
      RETURN user.name as userName,
             mod.name as moduleName,
             mod.filepath as moduleFile
      ORDER BY moduleName
      LIMIT 50
    `;
    return this.query(cypher, { pattern: `(?i).*${name}.*` });
  }

  /**
   * Trace cross-language execution path: Shell → EXECUTES → Fortran → CALLS
   * @param {string} scriptName - Name of the shell script or J-Job
   * @param {number} fortranDepth - Depth to trace into Fortran (default: 3)
   * @returns {Promise<Array>} Cross-language execution path
   */
  async traceCrossLanguagePath(scriptName, fortranDepth = 3) {
    const depthInt = Math.min(Math.max(parseInt(fortranDepth, 10) || 3, 1), 10);
    // Phase 24F Step 9: Fixed label — query File, ShellScript, and CodeFile to cover all bridge node types
    const cypher = `
      MATCH (shell)
      WHERE (shell:File OR shell:ShellScript OR shell:CodeFile)
      AND (shell.name =~ $pattern OR shell.path =~ $pattern OR shell.absolutePath =~ $pattern)
      OPTIONAL MATCH shellPath = (shell)-[:SOURCES|INVOKES*0..2]->(exScript)
      WHERE exScript:ShellScript OR exScript:CodeFile OR exScript:File
      OPTIONAL MATCH (exScript)-[:EXECUTES]->(prog:FortranProgram)
      OPTIONAL MATCH fortranPath = (prog)-[:CALLS*1..${depthInt}]->(sub)
      OPTIONAL MATCH (exScript)-[:INVOKES]->(pyMod:PythonModule)
      WITH shell, exScript, prog, sub, pyMod,
           CASE WHEN shellPath IS NULL THEN 0 ELSE length(shellPath) END as shellDepth,
           CASE WHEN fortranPath IS NULL THEN 0 ELSE length(fortranPath) END as fortranDepth
      RETURN DISTINCT 
             shell.name as sourceScript,
             exScript.name as executingScript,
             prog.name as fortranProgram,
             sub.name as fortranSubroutine,
             labels(sub)[0] as subroutineType,
             pyMod.name as pythonModule,
             pyMod.file_path as pythonFilePath,
             shellDepth,
             fortranDepth
      ORDER BY shellDepth, fortranDepth
      LIMIT 200
    `;
    return this.query(cypher, { pattern: `(?i).*${scriptName}.*` });
  }

  /**
   * Trace execution chain across language boundaries (Phase 24F Step 2).
   * @param {string} name - Starting node name (J-Job, script, Fortran program, etc.)
   * @param {number} depth - Maximum hops per language segment (default: 5)
   * @param {'forward'|'reverse'|'both'} direction - Traversal direction
   * @returns {Promise<Object>} { chain, bridges, stats }
   */
  async traceCrossLanguageChain(name, depth = 5, direction = 'forward') {
    const depthInt = Math.min(Math.max(parseInt(depth, 10) || 5, 1), 10);
    const pattern = `(?i).*${name.replace(/[.*+?^${}()|[\]\\]/g, '\\\\$&')}.*`;
    const results = { chain: [], bridges: [], stats: { languages: new Set(), totalNodes: 0, bridgeCrossings: 0 } };

    if (direction === 'forward' || direction === 'both') {
      const forwardCypher = `
        MATCH (start)
        WHERE (start:ShellScript OR start:File OR start:FortranProgram OR start:PythonFunction OR start:PythonModule)
        AND (start.name =~ $pattern OR start.path =~ $pattern)
        WITH start, labels(start)[0] AS startLabel
        OPTIONAL MATCH shellPath = (start)-[:SOURCES|INVOKES*0..3]->(exScript:ShellScript)
        WITH start, startLabel, collect(DISTINCT exScript) AS shellHops
        UNWIND (CASE WHEN size(shellHops) > 0 THEN shellHops ELSE [start] END) AS pivot
        OPTIONAL MATCH (pivot)-[execRel:EXECUTES]->(prog:FortranProgram)
        OPTIONAL MATCH fortranPath = (prog)-[:CALLS*1..${depthInt}]->(sub)
        WHERE sub:FortranSubroutine OR sub:FortranFunction
        OPTIONAL MATCH (pivot)-[invRel:INVOKES]->(pyMod:PythonModule)
        OPTIONAL MATCH (pyMod)-[:DEFINES]->(pyFunc:PythonFunction)
        RETURN DISTINCT
          start.name AS source, startLabel,
          pivot.name AS bridgeScript, labels(pivot)[0] AS pivotLabel,
          prog.name AS fortranProgram,
          collect(DISTINCT sub.name) AS fortranChain,
          pyMod.name AS pythonModule,
          pyFunc.name AS pythonFunction,
          CASE WHEN execRel IS NOT NULL THEN true ELSE false END AS hasFortranBridge,
          CASE WHEN invRel IS NOT NULL THEN true ELSE false END AS hasPythonBridge
        LIMIT 200
      `;
      const fwd = await this.query(forwardCypher, { pattern });
      for (const row of fwd) {
        if (row.source) {
          results.chain.push({ name: row.source, label: row.startLabel, language: this._labelToLanguage(row.startLabel), direction: 'forward', hop: 0 });
          results.stats.languages.add(this._labelToLanguage(row.startLabel));
        }
        if (row.bridgeScript && row.bridgeScript !== row.source) {
          results.chain.push({ name: row.bridgeScript, label: row.pivotLabel, language: 'shell', direction: 'forward', hop: 1, relType: 'SOURCES/INVOKES' });
          results.stats.languages.add('shell');
        }
        if (row.hasFortranBridge && row.fortranProgram) {
          results.bridges.push({ from: row.bridgeScript || row.source, to: row.fortranProgram, type: 'EXECUTES', fromLang: 'shell', toLang: 'fortran' });
          results.chain.push({ name: row.fortranProgram, label: 'FortranProgram', language: 'fortran', direction: 'forward', hop: 2, relType: 'EXECUTES' });
          results.stats.bridgeCrossings++;
          results.stats.languages.add('fortran');
          for (const sub of (row.fortranChain || [])) {
            results.chain.push({ name: sub, label: 'FortranSubroutine', language: 'fortran', direction: 'forward', hop: 3, relType: 'CALLS' });
          }
        }
        if (row.hasPythonBridge && row.pythonModule) {
          results.bridges.push({ from: row.bridgeScript || row.source, to: row.pythonModule, type: 'INVOKES', fromLang: 'shell', toLang: 'python' });
          results.chain.push({ name: row.pythonModule, label: 'PythonModule', language: 'python', direction: 'forward', hop: 2, relType: 'INVOKES' });
          results.stats.bridgeCrossings++;
          results.stats.languages.add('python');
          if (row.pythonFunction) {
            results.chain.push({ name: row.pythonFunction, label: 'PythonFunction', language: 'python', direction: 'forward', hop: 3, relType: 'DEFINES' });
          }
        }
      }
    }

    if (direction === 'reverse' || direction === 'both') {
      const reverseCypher = `
        MATCH (target)
        WHERE (target:FortranProgram OR target:FortranSubroutine OR target:FortranFunction
               OR target:PythonModule OR target:PythonFunction OR target:ShellScript)
        AND (target.name =~ $pattern)
        WITH target, labels(target)[0] AS targetLabel
        OPTIONAL MATCH (target)<-[:CALLS*0..${depthInt}]-(prog:FortranProgram)
        OPTIONAL MATCH (prog)<-[:EXECUTES]-(script)
        WHERE script:ShellScript OR script:File
        OPTIONAL MATCH callerPath = (jjob:ShellScript)-[:SOURCES|INVOKES*1..3]->(script)
        WHERE jjob.type = 'j-job'
        RETURN DISTINCT
          target.name AS targetName, targetLabel,
          prog.name AS fortranProgram,
          script.name AS executorScript, labels(script)[0] AS scriptLabel,
          collect(DISTINCT jjob.name) AS triggeringJJobs
        LIMIT 200
      `;
      const rev = await this.query(reverseCypher, { pattern });
      for (const row of rev) {
        if (row.targetName) {
          results.chain.push({ name: row.targetName, label: row.targetLabel, language: this._labelToLanguage(row.targetLabel), direction: 'reverse', hop: 0 });
        }
        if (row.fortranProgram && row.fortranProgram !== row.targetName) {
          results.chain.push({ name: row.fortranProgram, label: 'FortranProgram', language: 'fortran', direction: 'reverse', hop: 1, relType: 'CALLS' });
        }
        if (row.executorScript) {
          results.bridges.push({ from: row.executorScript, to: row.fortranProgram || row.targetName, type: 'EXECUTES', fromLang: 'shell', toLang: 'fortran' });
          results.chain.push({ name: row.executorScript, label: row.scriptLabel, language: 'shell', direction: 'reverse', hop: 2, relType: 'EXECUTES' });
          results.stats.bridgeCrossings++;
          results.stats.languages.add('shell');
        }
        for (const jjob of (row.triggeringJJobs || [])) {
          results.chain.push({ name: jjob, label: 'ShellScript', language: 'shell', direction: 'reverse', hop: 3, relType: 'SOURCES/INVOKES' });
        }
      }
    }

    // Deduplicate chain entries
    const seen = new Set();
    results.chain = results.chain.filter(entry => {
      const key = `${entry.name}:${entry.direction}:${entry.hop}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });

    results.stats.totalNodes = results.chain.length;
    results.stats.languages = [...results.stats.languages];
    return results;
  }

  /**
   * Find upstream executors of a Fortran program (Phase 24F Step 8).
   * @param {string} fortranName - FortranProgram name
   * @returns {Promise<Array>} Upstream shell scripts and J-Jobs
   */
  async findUpstreamExecutors(fortranName) {
    const cypher = `
      MATCH (prog:FortranProgram)<-[:EXECUTES]-(script)
      WHERE prog.name = $name
      AND (script:ShellScript OR script:File)
      OPTIONAL MATCH callerPath = (jjob:ShellScript)-[:SOURCES|INVOKES*1..3]->(script)
      WHERE jjob.type = 'j-job'
      RETURN DISTINCT prog.name AS program, script.name AS executor_script,
             labels(script)[0] AS script_label,
             collect(DISTINCT jjob.name) AS triggering_jjobs
    `;
    return this.query(cypher, { name: fortranName });
  }

  /** Map a Neo4j label to a language string. */
  _labelToLanguage(label) {
    if (!label) return 'unknown';
    if (label.startsWith('Fortran')) return 'fortran';
    if (label.startsWith('Python')) return 'python';
    if (['ShellScript', 'File', 'CodeFile'].includes(label)) return 'shell';
    return 'other';
  }

  /**
   * Get Fortran graph statistics
   * @returns {Promise<object>} Fortran graph statistics
   */
  async getFortranGraphStats() {
    const queries = {
      modules: 'MATCH (n:FortranModule) RETURN count(n) as count',
      subroutines: 'MATCH (n:FortranSubroutine) RETURN count(n) as count',
      functions: 'MATCH (n:FortranFunction) RETURN count(n) as count',
      programs: 'MATCH (n:FortranProgram) RETURN count(n) as count',
      callsRels: 'MATCH ()-[r:CALLS]->() WHERE NOT type(r) = "CALLS_SHELL" RETURN count(r) as count',
      usesRels: 'MATCH ()-[r:USES]->() RETURN count(r) as count',
      executesRels: 'MATCH ()-[r:EXECUTES]->() RETURN count(r) as count'
    };

    const stats = {};
    for (const [key, cypher] of Object.entries(queries)) {
      const result = await this.query(cypher, {});
      stats[key] = result[0]?.count || 0;
    }
    return stats;
  }
}
