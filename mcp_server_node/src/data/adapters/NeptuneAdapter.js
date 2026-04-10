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
      maxConnectionPoolSize: config.maxConnectionPoolSize || 50,
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

    const transformed = transformApoc(cypher);
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
      this.metrics.queriesFailed++;
      console.error(`[ERROR] NeptuneAdapter.query failed: ${err.message}`);
      throw err;
    } finally {
      await session.close();
    }
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
    return this.query(
      `MATCH path = (f:Function {name: $name})-[:CALLS*1..${depth}]->(callee)
       RETURN [n IN nodes(path) | n.name] AS chain,
              [r IN relationships(path) | type(r)] AS rels`,
      { name: functionName }
    );
  }

  async findCallers(functionName) {
    return this.query(
      `MATCH (caller)-[:CALLS]->(f {name: $name})
       RETURN caller.name AS caller, labels(caller)[0] AS callerType`,
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
    const [nodes, rels] = await Promise.all([
      this.query('MATCH (n) RETURN count(n) AS count'),
      this.query('MATCH ()-[r]->() RETURN count(r) AS count'),
    ]);
    return { nodes: nodes[0]?.count ?? 0, relationships: rels[0]?.count ?? 0 };
  }

  async getRelationshipStats() {
    return this.query(
      `MATCH ()-[r]->() RETURN type(r) AS relType, count(r) AS count ORDER BY count DESC`
    );
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
      const result = await this.query('MATCH (n) RETURN count(n) AS nodeCount LIMIT 1');
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
       RETURN caller.name AS caller, labels(caller)[0] AS callerType`,
      { name: scriptName }
    );
  }

  async traceScriptChain(scriptName, depth = 2) {
    return this.query(
      `MATCH path = (s {name: $name})-[:SOURCES|INVOKES*1..${depth}]->(child)
       RETURN [n IN nodes(path) | n.name] AS chain`,
      { name: scriptName }
    );
  }

  async findScriptEnvDeps(scriptName) {
    return this.query(
      `MATCH (s {name: $name})-[:USES]->(v:EnvVar)
       RETURN v.name AS envVar, v.value AS defaultValue`,
      { name: scriptName }
    );
  }

  async getScriptGraphStats() {
    const [scripts, envVars, rels] = await Promise.all([
      this.query('MATCH (n:ShellScript) RETURN count(n) AS count'),
      this.query('MATCH (n:EnvVar) RETURN count(n) AS count'),
      this.query('MATCH ()-[r:SOURCES|INVOKES|USES]->() RETURN count(r) AS count'),
    ]);
    return {
      scripts: scripts[0]?.count ?? 0,
      envVars: envVars[0]?.count ?? 0,
      relationships: rels[0]?.count ?? 0,
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
    return this.query(
      `MATCH path = (f:PythonFunction {name: $name})-[:CALLS*1..${depth}]->(callee)
       RETURN [n IN nodes(path) | n.name] AS chain`,
      { name }
    );
  }

  async getPythonGraphStats() {
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
      `MATCH (caller)-[:CALLS]->(f:FortranSubroutine|FortranFunction|FortranProgram {name: $name})
       RETURN caller.name AS caller, labels(caller)[0] AS callerType`,
      { name }
    );
  }

  async traceFortranCallChain(name, depth = 3) {
    return this.query(
      `MATCH path = (f {name: $name})-[:CALLS*1..${depth}]->(callee)
       WHERE f:FortranSubroutine OR f:FortranFunction OR f:FortranProgram
       RETURN [n IN nodes(path) | n.name] AS chain,
              [n IN nodes(path) | labels(n)[0]] AS types`,
      { name }
    );
  }

  async findFortranModuleUses(name) {
    return this.query(
      `MATCH (f {name: $name})-[:USES]->(m:FortranModule)
       RETURN m.name AS module`,
      { name }
    );
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
    const relDir = direction === 'reverse' ? '<-' : '->';
    return this.query(
      `MATCH path = (start {name: $name})${relDir}[:SOURCES|INVOKES|EXECUTES|CALLS*1..${depth}]${relDir}(end)
       RETURN [n IN nodes(path) | n.name] AS chain,
              [n IN nodes(path) | labels(n)[0]] AS labels,
              [r IN relationships(path) | type(r)] AS rels`,
      { name }
    );
  }

  async findUpstreamExecutors(fortranName) {
    return this.query(
      `MATCH (prog:FortranProgram {name: $name})<-[:EXECUTES]-(script)
       WHERE script:ShellScript OR script:File
       OPTIONAL MATCH (jjob:ShellScript)-[:SOURCES|INVOKES*1..3]->(script)
       WHERE jjob.type = 'j-job'
       RETURN DISTINCT prog.name AS program, script.name AS executor_script,
              labels(script)[0] AS script_label,
              collect(DISTINCT jjob.name) AS triggering_jjobs`,
      { name: fortranName }
    );
  }

  async getFortranGraphStats() {
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
    if (typeof value === 'object' && value.constructor?.name === 'Object') {
      const out = {};
      for (const k of Object.keys(value)) out[k] = this._convertValue(value[k]);
      return out;
    }
    return value;
  }
}

export default NeptuneAdapter;
