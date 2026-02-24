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
   * Re-run Leiden with includeIntermediateCommunities to capture hierarchy.
   * Writes communityId (coarsest level) and communityLevels (array, index 0 = finest)
   * back to each node.
   *
   * @param {object} opts
   * @param {number} [opts.maxLevels=5] - Maximum hierarchical levels
   * @param {number} [opts.gamma=1.0] - Resolution parameter
   * @returns {Promise<{nodesUpdated: number, topCommunities: number, maxDepth: number}>}
   */
  async runHierarchicalLeiden({ maxLevels = 5, gamma = 1.0 } = {}) {
    console.log('[INFO] Running hierarchical Leiden with includeIntermediateCommunities...');
    const cypher = `
      CALL gds.leiden.stream('${GRAPH_NAME}', {
        maxLevels: ${Math.floor(maxLevels)},
        gamma: ${gamma},
        includeIntermediateCommunities: true
      })
      YIELD nodeId, communityId, intermediateCommunityIds
      WITH gds.util.asNode(nodeId) AS node,
           communityId AS topLevel,
           intermediateCommunityIds AS levels
      SET node.communityId = topLevel,
          node.communityLevels = levels
      RETURN count(*) AS nodesUpdated,
             count(DISTINCT topLevel) AS topCommunities,
             max(size(levels)) AS maxDepth
    `;
    const result = await this._writeQuery(cypher);
    const row = result[0] || {};
    return {
      nodesUpdated: this._toInt(row.nodesUpdated),
      topCommunities: this._toInt(row.topCommunities),
      maxDepth: this._toInt(row.maxDepth)
    };
  }

  /**
   * Materialize Community nodes from communityLevels arrays.
   * Creates (:Community {communityId, level}) nodes and uniqueness constraint.
   * @returns {Promise<{communityNodesCreated: number, levels: number}>}
   */
  async materializeCommunityNodes() {
    console.log('[INFO] Creating Community label nodes...');

    // Create uniqueness constraint first
    try {
      await this._writeQuery(
        `CREATE CONSTRAINT community_unique IF NOT EXISTS
         FOR (c:Community) REQUIRE (c.communityId, c.level) IS UNIQUE`
      );
      console.log('[OK] Community uniqueness constraint created');
    } catch (err) {
      console.log('[INFO] Community constraint may already exist:', err.message);
    }

    // Determine max depth
    const depthResult = await this.graphDB.query(`
      MATCH (n) WHERE n.communityLevels IS NOT NULL
      RETURN max(size(n.communityLevels)) AS maxDepth
    `);
    const maxDepth = this._toInt(depthResult[0]?.maxDepth);
    console.log(`[INFO] Max hierarchy depth: ${maxDepth}`);

    let totalCreated = 0;
    for (let levelIdx = 0; levelIdx < maxDepth; levelIdx++) {
      const result = await this._writeQuery(`
        MATCH (n)
        WHERE n.communityLevels IS NOT NULL
          AND size(n.communityLevels) > ${levelIdx}
        WITH ${levelIdx} AS levelIdx, n.communityLevels[${levelIdx}] AS cid, collect(n) AS members
        WITH levelIdx, cid, size(members) AS memberCount
        WHERE memberCount >= 2
        MERGE (c:Community {communityId: cid, level: levelIdx})
        SET c.memberCount = memberCount,
            c.createdAt = datetime(),
            c.name = 'Community_L' + toString(levelIdx) + '_' + toString(cid)
        RETURN count(c) AS created
      `);
      const created = this._toInt(result[0]?.created);
      totalCreated += created;
      console.log(`[OK] Level ${levelIdx}: ${created} Community nodes`);
    }

    return { communityNodesCreated: totalCreated, levels: maxDepth };
  }

  /**
   * Create MEMBER_OF relationships from code nodes to their L0 community.
   * @returns {Promise<{relationshipsCreated: number}>}
   */
  async createMemberOfRelationships() {
    console.log('[INFO] Creating MEMBER_OF relationships...');
    const result = await this._writeQuery(`
      MATCH (n)
      WHERE n.communityLevels IS NOT NULL AND size(n.communityLevels) > 0
      WITH n, n.communityLevels[0] AS leafCid
      MATCH (c:Community {communityId: leafCid, level: 0})
      MERGE (n)-[:MEMBER_OF]->(c)
      RETURN count(*) AS created
    `);
    const created = this._toInt(result[0]?.created);
    console.log(`[OK] Created ${created} MEMBER_OF relationships`);
    return { relationshipsCreated: created };
  }

  /**
   * Create PARENT_OF hierarchy between community levels.
   * @returns {Promise<{relationshipsCreated: number}>}
   */
  async createParentOfHierarchy() {
    console.log('[INFO] Creating PARENT_OF hierarchy...');
    const result = await this._writeQuery(`
      MATCH (n)
      WHERE n.communityLevels IS NOT NULL AND size(n.communityLevels) >= 2
      UNWIND range(0, size(n.communityLevels) - 2) AS idx
      WITH DISTINCT n.communityLevels[idx] AS childCid, idx AS childLevel,
           n.communityLevels[idx + 1] AS parentCid, idx + 1 AS parentLevel
      MATCH (child:Community {communityId: childCid, level: childLevel})
      MATCH (parent:Community {communityId: parentCid, level: parentLevel})
      MERGE (parent)-[:PARENT_OF]->(child)
      RETURN count(*) AS created
    `);
    const created = this._toInt(result[0]?.created);
    console.log(`[OK] Created ${created} PARENT_OF relationships`);
    return { relationshipsCreated: created };
  }

  /**
   * Compute INTERACTS_WITH between communities at each level.
   * Aggregates cross-community code edges.
   * @param {number} [minStrength=3] - Minimum edge count for significance
   * @returns {Promise<{relationshipsCreated: number}>}
   */
  async computeInteractsWith(minStrength = 3) {
    console.log('[INFO] Computing INTERACTS_WITH between communities...');

    const depthResult = await this.graphDB.query(`
      MATCH (n) WHERE n.communityLevels IS NOT NULL
      RETURN max(size(n.communityLevels)) AS maxDepth
    `);
    const maxDepth = this._toInt(depthResult[0]?.maxDepth);

    let totalCreated = 0;
    for (let levelIdx = 0; levelIdx < maxDepth; levelIdx++) {
      const result = await this._writeQuery(`
        MATCH (a)-[r]->(b)
        WHERE a.communityLevels IS NOT NULL AND b.communityLevels IS NOT NULL
          AND size(a.communityLevels) > ${levelIdx}
          AND size(b.communityLevels) > ${levelIdx}
          AND a.communityLevels[${levelIdx}] <> b.communityLevels[${levelIdx}]
          AND NOT a:Community AND NOT b:Community
        WITH ${levelIdx} AS levelIdx,
             a.communityLevels[${levelIdx}] AS aCid,
             b.communityLevels[${levelIdx}] AS bCid,
             type(r) AS relType,
             count(*) AS strength
        WHERE strength >= ${minStrength}
        MATCH (ca:Community {communityId: aCid, level: ${levelIdx}})
        MATCH (cb:Community {communityId: bCid, level: ${levelIdx}})
        MERGE (ca)-[ix:INTERACTS_WITH]->(cb)
        SET ix.strength = strength,
            ix.level = ${levelIdx}
        RETURN count(ix) AS created
      `);
      const created = this._toInt(result[0]?.created);
      totalCreated += created;
      console.log(`[OK] Level ${levelIdx}: ${created} INTERACTS_WITH edges`);
    }

    return { relationshipsCreated: totalCreated };
  }

  /**
   * Enrich Community nodes with language breakdown and key member names.
   * @returns {Promise<{enriched: number}>}
   */
  async enrichCommunityMetadata() {
    console.log('[INFO] Enriching Community nodes with metadata...');
    const result = await this._writeQuery(`
      MATCH (c:Community)<-[:MEMBER_OF]-(n)
      WITH c,
           CASE
             WHEN 'FortranSubroutine' IN labels(n) OR 'FortranFunction' IN labels(n) OR 'FortranModule' IN labels(n) THEN 'Fortran'
             WHEN 'PythonFunction' IN labels(n) OR 'PythonModule' IN labels(n) THEN 'Python'
             WHEN 'ShellScript' IN labels(n) OR 'File' IN labels(n) THEN 'Shell'
             ELSE 'Other'
           END AS lang,
           n.name AS nname
      WITH c,
           collect(DISTINCT lang) AS languages,
           collect(nname)[0..10] AS keyMembers,
           count(*) AS memberSize
      SET c.languages = languages,
          c.keyMembers = keyMembers,
          c.memberCount = memberSize
      RETURN count(c) AS enriched
    `);
    const enriched = this._toInt(result[0]?.enriched);
    console.log(`[OK] Enriched ${enriched} Community nodes`);
    return { enriched };
  }

  /**
   * Get communities at a specific hierarchical level.
   * @param {number} level
   * @param {number} [minSize=2]
   * @returns {Promise<Array<{communityId: number, level: number, memberCount: number, name: string}>>}
   */
  async getCommunitiesAtLevel(level, minSize = 2) {
    const result = await this.graphDB.query(`
      MATCH (c:Community {level: $level})
      WHERE c.memberCount >= $minSize
      RETURN c.communityId AS communityId, c.level AS level,
             c.memberCount AS memberCount, c.name AS name,
             c.languages AS languages, c.keyMembers AS keyMembers,
             c.summary AS summary
      ORDER BY c.memberCount DESC
    `, { level, minSize });
    return result.map(r => ({
      communityId: this._toInt(r.communityId),
      level: this._toInt(r.level),
      memberCount: this._toInt(r.memberCount),
      name: r.name,
      languages: r.languages || [],
      keyMembers: r.keyMembers || [],
      summary: r.summary || null
    }));
  }

  /**
   * Get child communities of a parent community.
   * @param {number} communityId
   * @param {number} level - Level of the parent
   * @returns {Promise<Array>}
   */
  async getChildCommunities(communityId, level) {
    const result = await this.graphDB.query(`
      MATCH (parent:Community {communityId: $cid, level: $level})-[:PARENT_OF]->(child:Community)
      RETURN child.communityId AS communityId, child.level AS level,
             child.memberCount AS memberCount, child.name AS name,
             child.summary AS summary, child.languages AS languages,
             child.keyMembers AS keyMembers
      ORDER BY child.memberCount DESC
    `, { cid: communityId, level });
    return result.map(r => ({
      communityId: this._toInt(r.communityId),
      level: this._toInt(r.level),
      memberCount: this._toInt(r.memberCount),
      name: r.name,
      summary: r.summary || null,
      languages: r.languages || [],
      keyMembers: r.keyMembers || []
    }));
  }

  /**
   * Get inter-community interactions at a given level.
   * @param {number} communityId
   * @param {number} level
   * @returns {Promise<Array>}
   */
  async getCommunityInteractions(communityId, level) {
    const result = await this.graphDB.query(`
      MATCH (c:Community {communityId: $cid, level: $level})-[ix:INTERACTS_WITH]->(other:Community)
      RETURN other.communityId AS communityId, other.name AS name,
             ix.strength AS strength, other.memberCount AS memberCount,
             other.languages AS languages
      ORDER BY ix.strength DESC LIMIT 10
    `, { cid: communityId, level });
    return result.map(r => ({
      communityId: this._toInt(r.communityId),
      name: r.name,
      strength: this._toInt(r.strength),
      memberCount: this._toInt(r.memberCount),
      languages: r.languages || []
    }));
  }

  /**
   * Get the maximum community hierarchy level.
   * @returns {Promise<number>}
   */
  async getMaxCommunityLevel() {
    const result = await this.graphDB.query(`
      MATCH (c:Community)
      RETURN max(c.level) AS maxLevel
    `);
    return this._toInt(result[0]?.maxLevel);
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
