/**
 * NeptuneAdapter.js - AWS Neptune Graph Database Adapter
 *
 * Implements GraphDatabaseAdapter for AWS Neptune using the neo4j-driver
 * over the Neptune Bolt endpoint (Neptune supports the Bolt protocol with
 * openCypher since engine version 1.2+).
 *
 * Key differences from Neo4j:
 *   - IAM auth via SigV4 (Neptune does not use username/password over Bolt)
 *   - No APOC procedures — queries are pre-transformed via apoc-transform.js
 *   - Neptune Bolt endpoint format: wss://<cluster>:8182/opencypher
 *
 * Output format is identical to GraphDatabase._recordToObject():
 *   Plain JS objects with Neo4j Integer → number conversion.
 *
 * @version 1.0.0
 * @author Phase 48 — AWS Infrastructure Port
 */

import neo4j from 'neo4j-driver';
import { HttpRequest } from '@smithy/protocol-http';
import { SignatureV4 } from '@smithy/signature-v4';
import { defaultProvider } from '@aws-sdk/credential-provider-node';
import crypto from '@aws-crypto/sha256-js';
import { GraphDatabaseAdapter } from './GraphDatabaseAdapter.js';
import { transformApoc } from './apoc-transform.js';

const { Sha256 } = crypto;

export class NeptuneAdapter extends GraphDatabaseAdapter {
  /**
   * @param {object} config
   * @param {string} config.endpoint  - Neptune Bolt endpoint (wss://host:8182/opencypher)
   * @param {string} [config.region]  - AWS region (default: AWS_REGION env or us-east-1)
   * @param {number} [config.maxConnectionPoolSize=50]
   * @param {number} [config.connectionTimeout=30000]
   */
  constructor(config = {}) {
    super();
    this.endpoint = config.endpoint || process.env.NEPTUNE_ENDPOINT || '';
    this.region   = config.region   || process.env.AWS_REGION || 'us-east-1';
    this.config   = {
      maxConnectionPoolSize: config.maxConnectionPoolSize || 10,
      connectionTimeout:     config.connectionTimeout     || 30000,
    };
    this.driver    = null;
    this.connected = false;
    this.metrics   = { queriesExecuted: 0, queriesFailed: 0, avgQueryTime: 0, lastQueryTime: null };
  }

  /**
   * Generate a SigV4-signed IAM auth token for Neptune Bolt.
   * Per AWS docs: sign a GET to /opencypher, serialize headers as JSON password.
   */
  async _getAuthToken() {
    // Extract host:port from endpoint (wss://host:port or bolt+s://host:port)
    const url = new URL(this.endpoint.replace('bolt+s://', 'https://').replace('wss://', 'https://'));
    const host = url.hostname;
    const port = parseInt(url.port || '8182', 10);
    const hostPort = `${host}:${port}`;

    const req = new HttpRequest({
      method: 'GET',
      protocol: 'bolt',
      hostname: host,
      port,
      path: '/opencypher',
      headers: { host: hostPort },
    });

    const signer = new SignatureV4({
      credentials: defaultProvider(),
      region: this.region,
      service: 'neptune-db',
      sha256: Sha256,
    });

    const signed = await signer.sign(req, {
      unsignableHeaders: new Set(['x-amz-content-sha256']),
    });

    const authInfo = {
      Authorization: signed.headers['authorization'],
      HttpMethod: signed.method,
      'X-Amz-Date': signed.headers['x-amz-date'],
      Host: signed.headers['host'],
      'X-Amz-Security-Token': signed.headers['x-amz-security-token'],
    };

    return neo4j.auth.basic('username', JSON.stringify(authInfo));
  }

  /** Connect to Neptune via Bolt with SigV4 IAM auth and exponential backoff retry. */
  async connect() {
    if (this.connected) return;

    if (!this.endpoint) {
      throw new Error('NeptuneAdapter: endpoint is required (set NEPTUNE_ENDPOINT or pass config.endpoint)');
    }

    const { withRetry } = await import('../../health/HealthChecker.js');

    const boltUri = this.endpoint.startsWith('wss://')
      ? this.endpoint.replace('wss://', 'bolt+s://')
      : this.endpoint;

    await withRetry(async () => {
      const authToken = await this._getAuthToken();
      this.driver = neo4j.driver(
        boltUri,
        authToken,
        {
          maxConnectionPoolSize: this.config.maxConnectionPoolSize,
          connectionTimeout:     this.config.connectionTimeout,
          disableLosslessIntegers: true,
        }
      );
      await this.driver.verifyConnectivity();
    }, {
      maxAttempts: 4,
      onRetry: (attempt, delayMs, err) =>
        console.error(`[WARN] NeptuneAdapter connect attempt ${attempt} failed (${err.message}), retrying in ${delayMs}ms`),
    });

    this.connected = true;
    console.error(`[OK] NeptuneAdapter connected: ${boltUri}`);
  }

  /**
   * Execute an openCypher query against Neptune.
   * APOC procedures are automatically transformed before execution.
   *
   * @param {string} cypher - Cypher/openCypher query (APOC calls are transformed)
   * @param {object} params - Query parameters
   * @returns {Promise<Array>} Results as plain JS objects (same format as GraphDatabase.query())
   */
  async query(cypher, params = {}) {
    if (!this.connected) await this.connect();

    const transformed = transformApoc(cypher)
      .replace(/labels\((\w+)\)\[0\]/g, 'head(labels($1))');

    // Attempt query, reconnect on SigV4 expiry
    for (let attempt = 0; attempt < 2; attempt++) {
      const session = this.driver.session({ defaultAccessMode: neo4j.session.READ });
      const t0 = Date.now();

      try {
        const result = await session.run(transformed, params);
        const elapsed = Date.now() - t0;
        this.metrics.queriesExecuted++;
        this.metrics.lastQueryTime = elapsed;
        this.metrics.avgQueryTime =
          (this.metrics.avgQueryTime * (this.metrics.queriesExecuted - 1) + elapsed) /
          this.metrics.queriesExecuted;
        return result.records.map(r => this._recordToObject(r));
      } catch (err) {
        // Detect SigV4 signature expiry and reconnect
        if (attempt === 0 && this._isSignatureExpired(err)) {
          console.error(`[WARN] NeptuneAdapter: SigV4 signature expired, reconnecting...`);
          await session.close();
          await this._reconnect();
          continue; // retry with fresh token
        }
        this.metrics.queriesFailed++;
        console.error(`[ERROR] NeptuneAdapter.query failed: ${err.message}`);
        throw err;
      } finally {
        await session.close().catch(() => {});
      }
    }
  }

  /**
   * Detect if an error is a SigV4 signature expiry.
   */
  _isSignatureExpired(err) {
    if (!err) return false;
    const msg = err.message || '';
    return msg.includes('Signature expired') ||
           msg.includes('is now earlier than') ||
           msg.includes('Credential should be scoped');
  }

  /**
   * Force reconnect with fresh SigV4 credentials.
   */
  async _reconnect() {
    try {
      if (this.driver) await this.driver.close();
    } catch {}
    this.driver = null;
    this.connected = false;
    await this.connect();
  }

  // ── GraphDatabaseAdapter method implementations ───────────────────────────
  // All methods delegate to query() with the same Cypher as GraphDatabase.js.
  // This ensures output format parity with the Neo4j legacy adapter.

  async findImporters(moduleName) {
    return this.query(
      `MATCH (f:File)-[i:IMPORTS]->(m:Module {name: $moduleName})
       RETURN f.path AS file, i.type AS importType, i.alias AS alias`,
      { moduleName }
    );
  }

  async findFileImports(filePath) {
    return this.query(
      `MATCH (f:File {path: $filePath})-[i:IMPORTS]->(m)
       RETURN m.name AS module, i.type AS importType, i.alias AS alias`,
      { filePath }
    );
  }

  async traceCallChain(functionName, depth = 3) {
    const depthInt = Math.min(Math.max(parseInt(depth, 10) || 3, 1), 5);
    const results = await this.query(
      `MATCH (f {name: $name})-[:CALLS*1..${depthInt}]->(callee)
       RETURN callee.name AS callee, head(labels(callee)) AS calleeType,
              1 AS depth
       LIMIT 100`,
      { name: functionName }
    );
    return results.map(r => ({
      callee: r.callee,
      name: r.callee,
      calleeType: r.calleeType,
      type: r.calleeType,
      depth: r.depth || 1
    }));
  }

  async findCallers(functionName) {
    return this.query(
      `MATCH (caller)-[:CALLS]->(f {name: $name})
       RETURN caller.name AS caller, head(labels(caller)) AS callerType`,
      { name: functionName }
    );
  }

  async findFileFunctions(filePath) {
    return this.query(
      `MATCH (f:File {path: $filePath})-[:DEFINES]->(fn:Function)
       RETURN fn.name AS name, fn.startLine AS startLine, fn.endLine AS endLine`,
      { filePath }
    );
  }

  async findFileClasses(filePath) {
    return this.query(
      `MATCH (f:File {path: $filePath})-[:DEFINES]->(c:Class)
       RETURN c.name AS name, c.startLine AS startLine`,
      { filePath }
    );
  }

  async analyzeModuleUsage(moduleName) {
    return this.query(
      `MATCH (f)-[:IMPORTS]->(m:Module {name: $name})
       RETURN count(f) AS importCount, collect(DISTINCT f.path)[..10] AS sampleFiles`,
      { name: moduleName }
    );
  }

  async findDependencyGraph(filePath, depth = 2) {
    return this.query(
      `MATCH path = (f:File {path: $filePath})-[:IMPORTS*1..${depth}]->(dep)
       RETURN [n IN nodes(path) | n.path] AS depChain`,
      { filePath }
    );
  }

  async findCircularDependencies(maxDepth = 5) {
    return this.query(
      `MATCH path = (f:File)-[:IMPORTS*2..${maxDepth}]->(f)
       RETURN [n IN nodes(path) | n.path] AS cycle LIMIT 20`
    );
  }

  async getStatistics() {
    // Neptune lacks Neo4j's count store, so full-graph MATCH (n) RETURN count(n)
    // scans all 63K+ nodes and times out. Use label-specific counts instead,
    // which leverage Neptune's label index for O(1) lookups.
    //
    // IMPORTANT: Ensure connection is established BEFORE parallel queries.
    // On cold AgentCore microVMs, parallel queries race the connection and
    // some silently fail with pool timeouts.
    if (!this.connected) await this.connect();

    const labels = ['File', 'Function', 'Class', 'Module', 'ShellScript', 'EnvVar',
                    'FortranModule', 'FortranSubroutine', 'FortranFunction', 'FortranProgram',
                    'PythonModule', 'PythonFunction'];
    const counts = await Promise.all(
      labels.map(async (label) => {
        try {
          const r = await this.query(`MATCH (n:${label}) RETURN count(n) AS count`);
          return r[0]?.count ?? 0;
        } catch (err) {
          console.error(`[WARN] NeptuneAdapter.getStatistics: ${label} count failed: ${err.message}`);
          return 0;
        }
      })
    );
    const totalNodes = counts.reduce((sum, c) => sum + c, 0);

    // Relationship count by type (indexed, much faster than untyped scan)
    const relTypes = ['IMPORTS', 'DEFINES', 'CALLS', 'SOURCES', 'INVOKES',
                      'USES', 'EXECUTES', 'DEPENDS_ON_ENV', 'EXPORTS'];
    const relCounts = await Promise.all(
      relTypes.map(async (type) => {
        try {
          const r = await this.query(`MATCH ()-[r:${type}]->() RETURN count(r) AS count`);
          return r[0]?.count ?? 0;
        } catch (err) {
          console.error(`[WARN] NeptuneAdapter.getStatistics: ${type} rel count failed: ${err.message}`);
          return 0;
        }
      })
    );
    const totalRels = relCounts.reduce((sum, c) => sum + c, 0);

    // Build per-label breakdown for detailed stats
    const labelBreakdown = {};
    labels.forEach((label, i) => { if (counts[i] > 0) labelBreakdown[label] = counts[i]; });

    return {
      nodes: totalNodes,
      relationships: totalRels,
      fileCount: counts[0] ?? 0,
      functionCount: counts[1] ?? 0,
      classCount: counts[2] ?? 0,
      labelBreakdown,
    };
  }

  async getRelationshipStats() {
    // Use typed relationship counts instead of scanning all relationships
    // Ensure connection before parallel queries (cold-start protection)
    if (!this.connected) await this.connect();

    const relTypes = ['IMPORTS', 'DEFINES', 'CALLS', 'SOURCES', 'INVOKES',
                      'USES', 'EXECUTES', 'DEPENDS_ON_ENV', 'EXPORTS'];
    const results = await Promise.all(
      relTypes.map(async (type) => {
        try {
          const r = await this.query(`MATCH ()-[r:${type}]->() RETURN count(r) AS count`);
          return { relationshipType: type, count: r[0]?.count ?? 0 };
        } catch (err) {
          console.error(`[WARN] NeptuneAdapter.getRelationshipStats: ${type} failed: ${err.message}`);
          return { relationshipType: type, count: 0 };
        }
      })
    );
    return results.filter(r => r.count > 0).sort((a, b) => b.count - a.count);
  }

  async searchFiles(pattern) {
    const likePattern = pattern.replace(/\*/g, '%');
    return this.query(
      `MATCH (f:File) WHERE f.path CONTAINS $pat RETURN f.path AS path LIMIT 100`,
      { pat: likePattern }
    );
  }

  async findFilesByLanguage(language) {
    return this.query(
      `MATCH (f:File {language: $language}) RETURN f.path AS path`,
      { language }
    );
  }

  async addChunkIdToFile(filePath, chunkId) {
    await this.query(
      `MATCH (f:File {path: $filePath}) SET f.chunkId = $chunkId`,
      { filePath, chunkId }
    );
  }

  async addChunkIdToFunction(functionName, filePath, chunkId) {
    await this.query(
      `MATCH (fn:Function {name: $name})-[:DEFINED_IN]->(f:File {path: $filePath})
       SET fn.chunkId = $chunkId`,
      { name: functionName, filePath, chunkId }
    );
  }

  async healthCheck() {
    try {
      if (!this.connected) await this.connect();
      // Use a label-specific count instead of full-graph scan (Neptune has no count store)
      const result = await this.query('MATCH (n:File) RETURN count(n) AS nodeCount');
      const nodeCount = result[0]?.nodeCount ?? 0;
      return {
        status: nodeCount > 0 ? 'healthy' : 'degraded',
        connected: true,
        nodeCount,
        metrics: this.metrics,
        timestamp: new Date().toISOString(),
      };
    } catch (err) {
      return { status: 'unhealthy', connected: false, error: err.message, timestamp: new Date().toISOString() };
    }
  }

  getMetrics() {
    return { ...this.metrics, connected: this.connected, endpoint: this.endpoint };
  }

  async close() {
    if (this.driver) await this.driver.close();
    this.connected = false;
    console.error('[OK] NeptuneAdapter closed');
  }

  // ── Shell Script Methods ──────────────────────────────────────────────────

  async findScriptCallers(scriptName) {
    return this.query(
      `MATCH (caller)-[:SOURCES|INVOKES]->(s {name: $name})
       RETURN caller.name AS caller, head(labels(caller)) AS callerType`,
      { name: scriptName }
    );
  }

  async traceScriptChain(scriptName, depth = 2) {
    const depthInt = Math.min(Math.max(parseInt(depth, 10) || 2, 1), 5);
    const results = await this.query(
      `MATCH (s {name: $name})-[:SOURCES|INVOKES*1..${depthInt}]->(child)
       RETURN DISTINCT child.name AS callee, head(labels(child)) AS calleeType,
              1 AS depth
       LIMIT 100`,
      { name: scriptName }
    );
    return results.map(r => ({
      callee: r.callee,
      name: r.callee,
      calleeType: r.calleeType,
      type: r.calleeType,
      depth: r.depth || 1
    }));
  }

  async findScriptEnvDeps(scriptName) {
    return this.query(
      `MATCH (s {name: $name})-[:USES]->(v:EnvVar)
       RETURN v.name AS envVar, v.value AS defaultValue`,
      { name: scriptName }
    );
  }

  async getScriptGraphStats() {
    // Ensure connection before parallel queries (cold-start protection)
    if (!this.connected) await this.connect();

    // Count scripts by type property and env vars by label
    const [scripts, jjobs, exScripts, ushScripts, envVars,
           sourcesRels, invokesRels, exportsRels, dependsRels] = await Promise.all([
      this.query('MATCH (n:ShellScript) RETURN count(n) AS count'),
      this.query("MATCH (n:ShellScript {type: 'j-job'}) RETURN count(n) AS count"),
      this.query("MATCH (n:ShellScript {type: 'ex-script'}) RETURN count(n) AS count"),
      this.query("MATCH (n:ShellScript {type: 'ush-script'}) RETURN count(n) AS count"),
      this.query('MATCH (n:EnvVar) RETURN count(n) AS count'),
      this.query('MATCH ()-[r:SOURCES]->() RETURN count(r) AS count'),
      this.query('MATCH ()-[r:INVOKES]->() RETURN count(r) AS count'),
      this.query('MATCH ()-[r:EXPORTS]->() RETURN count(r) AS count'),
      this.query('MATCH ()-[r:DEPENDS_ON_ENV]->() RETURN count(r) AS count'),
    ]);
    return {
      totalScripts: scripts[0]?.count ?? 0,
      jJobs: jjobs[0]?.count ?? 0,
      exScripts: exScripts[0]?.count ?? 0,
      ushScripts: ushScripts[0]?.count ?? 0,
      envVars: envVars[0]?.count ?? 0,
      sourcesRels: sourcesRels[0]?.count ?? 0,
      invokesRels: invokesRels[0]?.count ?? 0,
      exportsRels: exportsRels[0]?.count ?? 0,
      dependsRels: dependsRels[0]?.count ?? 0,
    };
  }

  // ── Python Methods ────────────────────────────────────────────────────────

  async findPythonCallers(name) {
    return this.query(
      `MATCH (caller:PythonFunction)-[:CALLS]->(f {name: $name})
       RETURN caller.name AS caller, caller.file AS file`,
      { name }
    );
  }

  async tracePythonCallChain(name, depth = 3) {
    const depthInt = Math.min(Math.max(parseInt(depth, 10) || 3, 1), 5);
    const results = await this.query(
      `MATCH (f:PythonFunction {name: $name})-[:CALLS*1..${depthInt}]->(callee)
       RETURN callee.name AS callee, callee.file AS file,
              1 AS depth
       LIMIT 100`,
      { name }
    );
    return results.map(r => ({
      callee: r.callee,
      name: r.callee,
      file: r.file,
      depth: r.depth || 1
    }));
  }

  async getPythonGraphStats() {
    if (!this.connected) await this.connect();
    const [fns, modules, rels] = await Promise.all([
      this.query('MATCH (n:PythonFunction) RETURN count(n) AS count'),
      this.query('MATCH (n:PythonModule) RETURN count(n) AS count'),
      this.query('MATCH ()-[r:CALLS]->(:PythonFunction) RETURN count(r) AS count'),
    ]);
    return { functions: fns[0]?.count ?? 0, modules: modules[0]?.count ?? 0, calls: rels[0]?.count ?? 0 };
  }

  // ── Fortran Methods ───────────────────────────────────────────────────────

  async findFortranCallers(name) {
    return this.query(
      `MATCH (caller)-[:CALLS]->(f {name: $name})
       WHERE f:FortranSubroutine OR f:FortranFunction OR f:FortranProgram
       RETURN caller.name AS caller, head(labels(caller)) AS callerType`,
      { name }
    );
  }

  async traceFortranCallChain(name, depth = 3) {
    const depthInt = Math.min(Math.max(parseInt(depth, 10) || 3, 1), 5);
    const results = await this.query(
      `MATCH (f {name: $name})-[:CALLS*1..${depthInt}]->(callee)
       WHERE (f:FortranSubroutine OR f:FortranFunction OR f:FortranProgram)
         AND (callee:FortranSubroutine OR callee:FortranFunction OR callee:FortranProgram)
       RETURN DISTINCT callee.name AS callee, head(labels(callee)) AS calleeType,
              1 AS depth
       LIMIT 100`,
      { name }
    );
    return results.map(r => ({
      callee: r.callee,
      name: r.callee,
      calleeType: r.calleeType,
      type: r.calleeType,
      depth: r.depth || 1
    }));
  }

  async findFortranModuleUses(name) {
    const results = await this.query(
      `MATCH (user)-[:USES]->(mod:FortranModule)
       WHERE toLower(user.name) CONTAINS toLower($name)
       RETURN user.name AS userName, mod.name AS moduleName, mod.filepath AS moduleFile
       ORDER BY moduleName
       LIMIT 50`,
      { name }
    );
    return results;
  }

  async traceCrossLanguagePath(scriptName, fortranDepth = 3) {
    return this.query(
      `MATCH (s {name: $name})-[:EXECUTES]->(prog:FortranProgram)
       OPTIONAL MATCH path = (prog)-[:CALLS*1..${fortranDepth}]->(callee)
       RETURN s.name AS script, prog.name AS program,
              [n IN nodes(path) | n.name] AS fortranChain`,
      { name: scriptName }
    );
  }

  async traceCrossLanguageChain(name, depth = 5, direction = 'forward') {
    const depthInt = Math.min(Math.max(parseInt(depth, 10) || 5, 1), 10);
    const results = { chain: [], bridges: [], stats: { languages: new Set(), totalNodes: 0, bridgeCrossings: 0 } };

    if (direction === 'forward' || direction === 'both') {
      // Query 1: Find start node
      const starts = await this.query(
        `MATCH (start)
         WHERE (start:ShellScript OR start:File OR start:FortranProgram OR start:PythonFunction OR start:PythonModule)
         AND (toLower(start.name) CONTAINS toLower($name) OR toLower(start.path) CONTAINS toLower($name))
         RETURN start.name AS name, head(labels(start)) AS label LIMIT 10`,
        { name }
      );
      if (starts.length === 0) { /* no start node — skip forward */ }
      else {
        for (const s of starts) {
          results.chain.push({ name: s.name, label: s.label, language: this._labelToLanguage(s.label), direction: 'forward', hop: 0 });
          results.stats.languages.add(this._labelToLanguage(s.label));
        }
        const startNames = starts.map(s => s.name);

        // Query 2: Shell children via SOURCES/INVOKES (per-hop, up to 3)
        const pivotNames = new Set(startNames);
        const pivotLabels = {};
        for (const s of starts) pivotLabels[s.name] = s.label;

        for (let hop = 1; hop <= 3; hop++) {
          const parents = [...pivotNames];
          const children = await this.query(
            `MATCH (p)-[r]->(c:ShellScript)
             WHERE p.name IN $parents AND type(r) IN ['SOURCES', 'INVOKES']
             RETURN DISTINCT c.name AS name, head(labels(c)) AS label LIMIT 100`,
            { parents }
          );
          if (children.length === 0) break;
          for (const c of children) {
            if (!pivotNames.has(c.name)) {
              pivotNames.add(c.name);
              pivotLabels[c.name] = c.label;
              results.chain.push({ name: c.name, label: c.label, language: 'shell', direction: 'forward', hop, relType: 'SOURCES/INVOKES' });
              results.stats.languages.add('shell');
            }
          }
        }

        // If no shell children found, use start nodes as pivots
        const allPivots = [...pivotNames];

        // Query 3: Fortran bridge — EXECUTES → FortranProgram → CALLS chain
        const fortranBridges = await this.query(
          `MATCH (pivot)-[:EXECUTES]->(prog:FortranProgram)
           WHERE pivot.name IN $pivots
           RETURN pivot.name AS pivotName, prog.name AS progName LIMIT 100`,
          { pivots: allPivots }
        );
        for (const fb of fortranBridges) {
          results.bridges.push({ from: fb.pivotName, to: fb.progName, type: 'EXECUTES', fromLang: 'shell', toLang: 'fortran' });
          results.chain.push({ name: fb.progName, label: 'FortranProgram', language: 'fortran', direction: 'forward', hop: 2, relType: 'EXECUTES' });
          results.stats.bridgeCrossings++;
          results.stats.languages.add('fortran');

          // Fortran call chain from this program
          const subs = await this.query(
            `MATCH (prog:FortranProgram {name: $progName})-[:CALLS*1..${depthInt}]->(sub)
             WHERE sub:FortranSubroutine OR sub:FortranFunction
             RETURN DISTINCT sub.name AS name LIMIT 200`,
            { progName: fb.progName }
          );
          for (const sub of subs) {
            results.chain.push({ name: sub.name, label: 'FortranSubroutine', language: 'fortran', direction: 'forward', hop: 3, relType: 'CALLS' });
          }
        }

        // Query 4: Python bridge — INVOKES → PythonModule → DEFINES → PythonFunction
        const pythonBridges = await this.query(
          `MATCH (pivot)-[:INVOKES]->(pyMod:PythonModule)
           WHERE pivot.name IN $pivots
           OPTIONAL MATCH (pyMod)-[:DEFINES]->(pyFunc:PythonFunction)
           RETURN pivot.name AS pivotName, pyMod.name AS modName,
                  collect(DISTINCT pyFunc.name) AS funcs LIMIT 100`,
          { pivots: allPivots }
        );
        for (const pb of pythonBridges) {
          if (!pb.modName) continue;
          results.bridges.push({ from: pb.pivotName, to: pb.modName, type: 'INVOKES', fromLang: 'shell', toLang: 'python' });
          results.chain.push({ name: pb.modName, label: 'PythonModule', language: 'python', direction: 'forward', hop: 2, relType: 'INVOKES' });
          results.stats.bridgeCrossings++;
          results.stats.languages.add('python');
          for (const fn of (pb.funcs || [])) {
            if (fn) results.chain.push({ name: fn, label: 'PythonFunction', language: 'python', direction: 'forward', hop: 3, relType: 'DEFINES' });
          }
        }
      }
    }

    if (direction === 'reverse' || direction === 'both') {
      // Query 1: Find target node
      const targets = await this.query(
        `MATCH (target)
         WHERE (target:FortranProgram OR target:FortranSubroutine OR target:FortranFunction
                OR target:PythonModule OR target:PythonFunction OR target:ShellScript)
         AND toLower(target.name) CONTAINS toLower($name)
         RETURN target.name AS name, head(labels(target)) AS label LIMIT 10`,
        { name }
      );
      for (const t of targets) {
        results.chain.push({ name: t.name, label: t.label, language: this._labelToLanguage(t.label), direction: 'reverse', hop: 0 });
      }

      // Query 2: Trace back through Fortran CALLS to FortranProgram
      const targetNames = targets.map(t => t.name);
      const fortranProgs = await this.query(
        `MATCH (target)<-[:CALLS*0..${depthInt}]-(prog:FortranProgram)
         WHERE target.name IN $targets
         RETURN DISTINCT target.name AS targetName, prog.name AS progName LIMIT 100`,
        { targets: targetNames }
      );
      const progNames = new Set();
      for (const fp of fortranProgs) {
        if (fp.progName && fp.progName !== fp.targetName) {
          results.chain.push({ name: fp.progName, label: 'FortranProgram', language: 'fortran', direction: 'reverse', hop: 1, relType: 'CALLS' });
        }
        progNames.add(fp.progName);
      }

      // Query 3: Find executor scripts via EXECUTES
      if (progNames.size > 0) {
        const executors = await this.query(
          `MATCH (prog)<-[:EXECUTES]-(script)
           WHERE prog.name IN $progs AND (script:ShellScript OR script:File)
           RETURN DISTINCT prog.name AS progName, script.name AS scriptName,
                  head(labels(script)) AS scriptLabel LIMIT 100`,
          { progs: [...progNames] }
        );
        const scriptNames = [];
        for (const ex of executors) {
          results.bridges.push({ from: ex.scriptName, to: ex.progName, type: 'EXECUTES', fromLang: 'shell', toLang: 'fortran' });
          results.chain.push({ name: ex.scriptName, label: ex.scriptLabel, language: 'shell', direction: 'reverse', hop: 2, relType: 'EXECUTES' });
          results.stats.bridgeCrossings++;
          results.stats.languages.add('shell');
          scriptNames.push(ex.scriptName);
        }

        // Query 4: Find triggering J-Jobs via SOURCES/INVOKES (per-hop)
        if (scriptNames.length > 0) {
          const jjobs = await this.query(
            `MATCH (jjob:ShellScript)-[r]->(script)
             WHERE script.name IN $scripts AND jjob.type = 'j-job'
             AND type(r) IN ['SOURCES', 'INVOKES']
             RETURN DISTINCT jjob.name AS name LIMIT 100`,
            { scripts: scriptNames }
          );
          for (const jj of jjobs) {
            results.chain.push({ name: jj.name, label: 'ShellScript', language: 'shell', direction: 'reverse', hop: 3, relType: 'SOURCES/INVOKES' });
          }
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

  async findUpstreamExecutors(fortranName) {
    return this.query(
      `MATCH (prog:FortranProgram {name: $name})<-[:EXECUTES]-(script)
       WHERE script:ShellScript OR script:File
       OPTIONAL MATCH (jjob:ShellScript)-[:SOURCES|INVOKES*1..3]->(script)
       WHERE jjob.type = 'j-job'
       RETURN DISTINCT prog.name AS program, script.name AS executor_script,
              head(labels(script)) AS script_label,
              collect(DISTINCT jjob.name) AS triggering_jjobs`,
      { name: fortranName }
    );
  }

  async getFortranGraphStats() {
    if (!this.connected) await this.connect();
    const keys = ['FortranModule', 'FortranSubroutine', 'FortranFunction', 'FortranProgram'];
    const stats = {};
    await Promise.all(keys.map(async label => {
      const r = await this.query(`MATCH (n:${label}) RETURN count(n) AS count`);
      stats[label.replace('Fortran', '').toLowerCase() + 's'] = r[0]?.count ?? 0;
    }));
    const [calls, uses, executes] = await Promise.all([
      this.query('MATCH ()-[r:CALLS]->() RETURN count(r) AS count'),
      this.query('MATCH ()-[r:USES]->() RETURN count(r) AS count'),
      this.query('MATCH ()-[r:EXECUTES]->() RETURN count(r) AS count'),
    ]);
    return { ...stats, callsRels: calls[0]?.count ?? 0, usesRels: uses[0]?.count ?? 0, executesRels: executes[0]?.count ?? 0 };
  }

  // ── Private helpers ───────────────────────────────────────────────────────

  /** Map a node label to a language string. */
  _labelToLanguage(label) {
    if (!label) return 'unknown';
    if (label.startsWith('Fortran')) return 'fortran';
    if (label.startsWith('Python')) return 'python';
    if (['ShellScript', 'File', 'CodeFile'].includes(label)) return 'shell';
    return 'other';
  }

  /** Convert a Neo4j/Neptune record to a plain JS object (same as GraphDatabase._recordToObject) */
  _recordToObject(record) {
    const obj = {};
    record.keys.forEach(key => { obj[key] = this._convertValue(record.get(key)); });
    return obj;
  }

  _convertValue(value) {
    if (value === null || value === undefined) return value;
    if (neo4j.isInt(value)) return value.toNumber();
    if (Array.isArray(value)) return value.map(v => this._convertValue(v));
    // Handle Neo4j Node objects (have labels and properties)
    if (value.labels && value.properties) {
      return { ...value.properties, _labels: value.labels };
    }
    // Handle Neo4j Relationship objects
    if (value.type && value.properties && value.start && value.end) {
      return { ...value.properties, _type: value.type };
    }
    // Handle Neo4j Path objects
    if (value.segments) {
      return value.segments.map(s => ({
        start: this._convertValue(s.start),
        rel: this._convertValue(s.relationship),
        end: this._convertValue(s.end)
      }));
    }
    if (typeof value === 'object' && value.constructor?.name === 'Object') {
      const out = {};
      for (const k of Object.keys(value)) out[k] = this._convertValue(value[k]);
      return out;
    }
    return value;
  }
}

export default NeptuneAdapter;
