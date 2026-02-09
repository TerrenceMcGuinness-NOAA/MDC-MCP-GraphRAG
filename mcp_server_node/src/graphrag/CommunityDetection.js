#!/usr/bin/env node

/**
 * CommunityDetection.js - Leiden Community Detection via Neo4j GDS
 *
 * Wraps Neo4j Graph Data Science (GDS) Leiden algorithm to discover
 * hierarchical communities across the multi-language code graph
 * (Fortran + Python + Shell). Communities are written back to Neo4j
 * nodes as `communityId` and `intermediateCommunityIds` properties.
 *
 * Requires: Neo4j GDS 2.13+ plugin installed.
 *
 * @version 1.0.0
 * @phase Phase 24E-1
 * @author Terry McGuinness + AI Assistants
 * @date 2026-02-09
 */

const GRAPH_NAME = 'code-community-graph';

// Node labels to include in community detection
const NODE_LABELS = [
  'FortranSubroutine',
  'FortranFunction',
  'FortranModule',
  'FortranProgram',
  'PythonModule',
  'PythonFunction',
  'PythonClass',
  'File',
  'CodeFile'
];

// Relationship types to project (undirected for Leiden)
const REL_TYPES = [
  'CALLS',
  'USES',
  'IMPORTS',
  'DEFINES',
  'EXECUTES',
  'INVOKES',
  'INHERITS',
  'SOURCES',
  'DEPENDS_ON',
  'DEPENDS_ON_ENV'
];

const neo4j_import = import('neo4j-driver');

class CommunityDetection {

  constructor(graphDB) {
    this.graphDB = graphDB;
  }

  /**
   * Execute a write-mode query (GDS write operations need WRITE access).
   * GraphDatabase.query() is READ-only by design; this method accesses
   * the driver directly for GDS write procedures.
   */
  async _writeQuery(cypher, params = {}) {
    const neo4j = (await neo4j_import).default;
    const session = this.graphDB.driver.session({
      database: this.graphDB.config.database,
      defaultAccessMode: neo4j.session.WRITE
    });
    try {
      const result = await session.run(cypher, params);
      return result.records.map(record => {
        const obj = {};
        record.keys.forEach(key => {
          const val = record.get(key);
          obj[key] = (val && typeof val === 'object' && val.toNumber) ? val.toNumber() : val;
        });
        return obj;
      });
    } finally {
      await session.close();
    }
  }

  /**
   * Check if GDS is available in the connected Neo4j instance.
   * @returns {Promise<{available: boolean, version: string|null}>}
   */
  async checkGDS() {
    try {
      const result = await this.graphDB.query('RETURN gds.version() AS v');
      return { available: true, version: result[0]?.v || 'unknown' };
    } catch {
      return { available: false, version: null };
    }
  }

  /**
   * Project the multi-language code graph into GDS in-memory format.
   * Drops existing projection if present.
   * @returns {Promise<{nodeCount: number, relationshipCount: number}>}
   */
  async projectGraph() {
    // Drop existing projection if any
    try {
      await this._writeQuery(
        `CALL gds.graph.drop('${GRAPH_NAME}') YIELD graphName RETURN graphName`
      );
    } catch {
      // Graph didn't exist — fine
    }

    // Build relationship projection with UNDIRECTED orientation (Leiden requirement)
    // GDS expects Cypher map literals with unquoted keys
    const relEntries = REL_TYPES.map(r => `${r}: {orientation: 'UNDIRECTED'}`).join(', ');

    const cypher = `
      CALL gds.graph.project(
        '${GRAPH_NAME}',
        ${JSON.stringify(NODE_LABELS)},
        {${relEntries}}
      )
      YIELD graphName, nodeCount, relationshipCount
      RETURN graphName, nodeCount, relationshipCount
    `;

    const result = await this._writeQuery(cypher);
    const row = result[0] || {};
    return {
      nodeCount: this._toInt(row.nodeCount),
      relationshipCount: this._toInt(row.relationshipCount)
    };
  }

  /**
   * Run Leiden community detection and write results back to Neo4j nodes.
   * Each node gets: communityId (int), intermediateCommunityIds (int[])
   *
   * @param {object} opts
   * @param {number} [opts.maxLevels=5] - Maximum hierarchical levels
   * @param {number} [opts.gamma=1.0] - Resolution parameter (higher = more communities)
   * @param {string} [opts.writeProperty='communityId'] - Property name to write
   * @returns {Promise<{communityCount: number, ranLevels: number, modularity: number}>}
   */
  async runLeiden({ maxLevels = 5, gamma = 1.0, writeProperty = 'communityId' } = {}) {
    const cypher = `
      CALL gds.leiden.write('${GRAPH_NAME}', {
        maxLevels: ${Math.floor(maxLevels)},
        gamma: ${gamma},
        writeProperty: '${writeProperty}'
      })
      YIELD communityCount, ranLevels, modularity, nodePropertiesWritten
      RETURN communityCount, ranLevels, modularity, nodePropertiesWritten
    `;

    const result = await this._writeQuery(cypher);
    const row = result[0] || {};
    return {
      communityCount: this._toInt(row.communityCount),
      ranLevels: this._toInt(row.ranLevels),
      modularity: row.modularity,
      nodePropertiesWritten: this._toInt(row.nodePropertiesWritten)
    };
  }

  /**
   * Get statistics about the detected communities.
   * @returns {Promise<{totalCommunities: number, sizeDistribution: Array}>}
   */
  async getCommunityStats() {
    const cypher = `
      MATCH (n)
      WHERE n.communityId IS NOT NULL
      WITH n.communityId AS cid, count(n) AS size
      WITH collect({communityId: cid, size: size}) AS allCommunities,
           count(cid) AS totalCommunities,
           min(size) AS minSize,
           max(size) AS maxSize,
           avg(size) AS avgSize
      RETURN totalCommunities, minSize, maxSize, avgSize,
             [c IN allCommunities | c][..20] AS topCommunities
    `;

    const result = await this.graphDB.query(cypher);
    const row = result[0] || {};

    // Also get size distribution buckets
    const distCypher = `
      MATCH (n)
      WHERE n.communityId IS NOT NULL
      WITH n.communityId AS cid, count(n) AS size
      WITH CASE
        WHEN size = 1 THEN 'singleton'
        WHEN size <= 3 THEN '2-3'
        WHEN size <= 10 THEN '4-10'
        WHEN size <= 50 THEN '11-50'
        WHEN size <= 200 THEN '51-200'
        ELSE '200+'
      END AS bucket, count(*) AS cnt
      RETURN bucket, cnt ORDER BY cnt DESC
    `;
    const distResult = await this.graphDB.query(distCypher);

    return {
      totalCommunities: this._toInt(row.totalCommunities),
      minSize: this._toInt(row.minSize),
      maxSize: this._toInt(row.maxSize),
      avgSize: parseFloat((row.avgSize || 0).toFixed(1)),
      sizeDistribution: distResult.map(r => ({ bucket: r.bucket, count: this._toInt(r.cnt) })),
      topCommunities: (row.topCommunities || []).map(c => ({
        communityId: this._toInt(c.communityId),
        size: this._toInt(c.size)
      }))
    };
  }

  /**
   * Get all members of a specific community.
   * @param {number} communityId
   * @param {number} [limit=200]
   * @returns {Promise<Array<{name: string, label: string, type: string}>>}
   */
  async getCommunityMembers(communityId, limit = 200) {
    const cypher = `
      MATCH (n)
      WHERE n.communityId = $communityId
      RETURN labels(n)[0] AS label,
             coalesce(n.name, n.file_path, n.absolutePath, n.path, 'unnamed') AS name,
             n.communityId AS communityId
      ORDER BY label, name
      LIMIT ${Math.floor(limit)}
    `;
    const result = await this.graphDB.query(cypher, { communityId });
    return result.map(r => ({
      name: r.name,
      label: r.label,
      communityId: this._toInt(r.communityId)
    }));
  }

  /**
   * Get the largest communities with their member breakdown by node type.
   * Useful for generating summaries.
   * @param {number} [minSize=3] - Minimum community size to include
   * @param {number} [limit=50] - Max communities to return
   * @returns {Promise<Array>}
   */
  async getLargestCommunities(minSize = 3, limit = 50) {
    const cypher = `
      MATCH (n)
      WHERE n.communityId IS NOT NULL
      WITH n.communityId AS cid, labels(n)[0] AS label,
           coalesce(n.name, n.file_path, n.absolutePath, 'unnamed') AS name
      WITH cid, collect({label: label, name: name}) AS members, count(*) AS size
      WHERE size >= ${Math.floor(minSize)}
      RETURN cid AS communityId, size, members
      ORDER BY size DESC
      LIMIT ${Math.floor(limit)}
    `;
    const result = await this.graphDB.query(cypher);
    return result.map(r => ({
      communityId: this._toInt(r.communityId),
      size: this._toInt(r.size),
      members: r.members,
      // Compute type breakdown
      typeBreakdown: this._typeBreakdown(r.members)
    }));
  }

  /**
   * Get internal relationships within a community (for summary context).
   * @param {number} communityId
   * @param {number} [limit=100]
   * @returns {Promise<Array<{source: string, rel: string, target: string}>>}
   */
  async getCommunityRelationships(communityId, limit = 100) {
    const cypher = `
      MATCH (a)-[r]->(b)
      WHERE a.communityId = $communityId AND b.communityId = $communityId
      RETURN coalesce(a.name, a.file_path, 'unnamed') AS source,
             type(r) AS rel,
             coalesce(b.name, b.file_path, 'unnamed') AS target
      LIMIT ${Math.floor(limit)}
    `;
    return this.graphDB.query(cypher, { communityId });
  }

  /**
   * Drop the in-memory GDS graph projection to free memory.
   */
  async dropProjection() {
    try {
      await this._writeQuery(
        `CALL gds.graph.drop('${GRAPH_NAME}') YIELD graphName RETURN graphName`
      );
    } catch {
      // Already dropped
    }
  }

  /**
   * Full pipeline: project → detect → stats → cleanup.
   * @param {object} opts - Leiden parameters
   * @returns {Promise<{projection: object, leiden: object, stats: object}>}
   */
  async runFullPipeline(opts = {}) {
    const startTime = Date.now();

    console.log('[INFO] Phase 24E-1: Starting community detection pipeline...');

    // Step 1: Project graph
    console.log('[INFO] Projecting multi-language graph into GDS...');
    const projection = await this.projectGraph();
    console.log(`[OK] Projected: ${projection.nodeCount} nodes, ${projection.relationshipCount} rels`);

    // Step 2: Run Leiden
    console.log('[INFO] Running Leiden community detection...');
    const leiden = await this.runLeiden(opts);
    console.log(`[OK] Leiden: ${leiden.communityCount} communities, ${leiden.ranLevels} levels, modularity=${leiden.modularity.toFixed(4)}`);

    // Step 3: Get stats
    const stats = await this.getCommunityStats();
    console.log(`[OK] Size distribution: ${stats.sizeDistribution.map(d => `${d.bucket}=${d.count}`).join(', ')}`);

    // Step 4: Cleanup GDS projection (data is written to nodes)
    await this.dropProjection();
    console.log(`[OK] GDS projection dropped. Community IDs persisted on ${leiden.nodePropertiesWritten} nodes.`);

    const elapsed = Date.now() - startTime;
    console.log(`[OK] Community detection complete in ${elapsed}ms`);

    return { projection, leiden, stats, elapsedMs: elapsed };
  }

  // --- Helpers ---

  _toInt(val) {
    if (val == null) return 0;
    if (typeof val === 'object' && val.toNumber) return val.toNumber();
    return Number(val) || 0;
  }

  _typeBreakdown(members) {
    const counts = {};
    for (const m of members) {
      counts[m.label] = (counts[m.label] || 0) + 1;
    }
    return counts;
  }
}

export default CommunityDetection;
