/**
 * Neo4jLegacyAdapter.js - Neo4j Legacy Adapter
 *
 * Wraps the existing GraphDatabase (Neo4j) implementation behind
 * the GraphDatabaseAdapter interface. Every method is a pure passthrough
 * to the wrapped instance — return formats are identical.
 *
 * Covers all method groups: base graph, shell script, Python, Fortran,
 * and cross-language methods.
 *
 * Usage:
 *   // Dependency injection (wrap existing instance)
 *   const adapter = new Neo4jLegacyAdapter(existingGraphDB);
 *
 *   // Config-based construction (creates GraphDatabase internally)
 *   const adapter = new Neo4jLegacyAdapter({ uri: 'bolt://localhost:7687' });
 *
 * @version 1.0.0
 * @author Phase 48 — AWS Infrastructure Port
 */

import { GraphDatabaseAdapter } from './GraphDatabaseAdapter.js';
import { GraphDatabase } from '../GraphDatabase.js';

export class Neo4jLegacyAdapter extends GraphDatabaseAdapter {
  /**
   * @param {GraphDatabase|object} configOrInstance - Existing GraphDatabase instance or config object
   */
  constructor(configOrInstance = {}) {
    super();
    if (configOrInstance instanceof GraphDatabase) {
      this.db = configOrInstance;
    } else {
      this.db = new GraphDatabase(configOrInstance);
    }
  }

  // ── Base Graph Methods ────────────────────────────────────────────────

  /** @inheritdoc */
  async connect() {
    return this.db.connect();
  }

  /** @inheritdoc */
  async query(cypher, params = {}) {
    return this.db.query(cypher, params);
  }

  /** @inheritdoc */
  async findImporters(moduleName) {
    return this.db.findImporters(moduleName);
  }

  /** @inheritdoc */
  async findFileImports(filePath) {
    return this.db.findFileImports(filePath);
  }

  /** @inheritdoc */
  async traceCallChain(functionName, depth = 3) {
    return this.db.traceCallChain(functionName, depth);
  }

  /** @inheritdoc */
  async findCallers(functionName) {
    return this.db.findCallers(functionName);
  }

  /** @inheritdoc */
  async findFileFunctions(filePath) {
    return this.db.findFileFunctions(filePath);
  }

  /** @inheritdoc */
  async findFileClasses(filePath) {
    return this.db.findFileClasses(filePath);
  }

  /** @inheritdoc */
  async analyzeModuleUsage(moduleName) {
    return this.db.analyzeModuleUsage(moduleName);
  }

  /** @inheritdoc */
  async findDependencyGraph(filePath, depth = 2) {
    return this.db.findDependencyGraph(filePath, depth);
  }

  /** @inheritdoc */
  async findCircularDependencies(maxDepth = 5) {
    return this.db.findCircularDependencies(maxDepth);
  }

  /** @inheritdoc */
  async getStatistics() {
    return this.db.getStatistics();
  }

  /** @inheritdoc */
  async getRelationshipStats() {
    return this.db.getRelationshipStats();
  }

  /** @inheritdoc */
  async searchFiles(pattern) {
    return this.db.searchFiles(pattern);
  }

  /** @inheritdoc */
  async findFilesByLanguage(language) {
    return this.db.findFilesByLanguage(language);
  }

  /** @inheritdoc */
  async addChunkIdToFile(filePath, chunkId) {
    return this.db.addChunkIdToFile(filePath, chunkId);
  }

  /** @inheritdoc */
  async addChunkIdToFunction(functionName, filePath, chunkId) {
    return this.db.addChunkIdToFunction(functionName, filePath, chunkId);
  }

  /** @inheritdoc */
  async healthCheck() {
    return this.db.healthCheck();
  }

  /** @inheritdoc */
  getMetrics() {
    return this.db.getMetrics();
  }

  /** @inheritdoc */
  async close() {
    return this.db.close();
  }

  // ── Shell Script Methods ──────────────────────────────────────────────

  /** @inheritdoc */
  async findScriptCallers(scriptName) {
    return this.db.findScriptCallers(scriptName);
  }

  /** @inheritdoc */
  async traceScriptChain(scriptName, depth = 2) {
    return this.db.traceScriptChain(scriptName, depth);
  }

  /** @inheritdoc */
  async findScriptEnvDeps(scriptName) {
    return this.db.findScriptEnvDeps(scriptName);
  }

  /** @inheritdoc */
  async getScriptGraphStats() {
    return this.db.getScriptGraphStats();
  }

  // ── Python Methods ────────────────────────────────────────────────────

  /** @inheritdoc */
  async findPythonCallers(name) {
    return this.db.findPythonCallers(name);
  }

  /** @inheritdoc */
  async tracePythonCallChain(name, depth = 3) {
    return this.db.tracePythonCallChain(name, depth);
  }

  /** @inheritdoc */
  async getPythonGraphStats() {
    return this.db.getPythonGraphStats();
  }

  // ── Fortran Methods ───────────────────────────────────────────────────

  /** @inheritdoc */
  async findFortranCallers(name) {
    return this.db.findFortranCallers(name);
  }

  /** @inheritdoc */
  async traceFortranCallChain(name, depth = 3) {
    return this.db.traceFortranCallChain(name, depth);
  }

  /** @inheritdoc */
  async findFortranModuleUses(name) {
    return this.db.findFortranModuleUses(name);
  }

  /** @inheritdoc */
  async traceCrossLanguagePath(scriptName, fortranDepth = 3) {
    return this.db.traceCrossLanguagePath(scriptName, fortranDepth);
  }

  /** @inheritdoc */
  async traceCrossLanguageChain(name, depth = 5, direction = 'forward') {
    return this.db.traceCrossLanguageChain(name, depth, direction);
  }

  /** @inheritdoc */
  async findUpstreamExecutors(fortranName) {
    return this.db.findUpstreamExecutors(fortranName);
  }

  /** @inheritdoc */
  async getFortranGraphStats() {
    return this.db.getFortranGraphStats();
  }
}

export default Neo4jLegacyAdapter;
