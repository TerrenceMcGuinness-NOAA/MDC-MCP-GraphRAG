#!/usr/bin/env node

/**
 * Neo4jClient - Connection wrapper for Neo4j Graph Database
 *
 * Provides a clean, reusable interface for all Neo4j operations:
 * - Connection management with pooling
 * - Query execution with error handling
 * - Transaction support
 * - Statistics and monitoring
 * - Batch operations for performance
 *
 * @version 1.0.0
 * @author NOAA EMC Global Workflow Team
 */

import neo4j from 'neo4j-driver';

export class Neo4jClient {
  constructor(config = {}) {
    this.config = {
      uri: config.uri || process.env.NEO4J_URI || 'bolt://127.0.0.1:7687',
      user: config.user || process.env.NEO4J_USER || 'neo4j',
      password: config.password || process.env.NEO4J_PASSWORD || 'gfsworkflow2025',
      database: config.database || 'neo4j',
      maxConnectionPoolSize: config.maxConnectionPoolSize || 50,
      connectionTimeout: config.connectionTimeout || 30000,
      ...config
    };

    this.driver = null;
    this.connected = false;

    this.stats = {
      queriesExecuted: 0,
      queriesFailed: 0,
      nodesCreated: 0,
      relationshipsCreated: 0,
      transactionsCommitted: 0,
      transactionsRolledBack: 0,
      totalQueryTime: 0,
      averageQueryTime: 0
    };
  }

  /**
   * Connect to Neo4j database
   */
  async connect() {
    if (this.connected) {
      console.warn('[WARN]  Already connected to Neo4j');
      return;
    }

    try {
      console.error(`🔗 Connecting to Neo4j at ${this.config.uri}...`);

      this.driver = neo4j.driver(
        this.config.uri,
        neo4j.auth.basic(this.config.user, this.config.password),
        {
          maxConnectionPoolSize: this.config.maxConnectionPoolSize,
          connectionTimeout: this.config.connectionTimeout
        }
      );

      // Verify connectivity
      const serverInfo = await this.driver.getServerInfo();
      this.connected = true;

      console.error(`[OK] Connected to Neo4j ${serverInfo.agent}`);
      console.error(`   Protocol: ${serverInfo.protocolVersion}`);
      console.error(`   Address: ${serverInfo.address}`);

    } catch (error) {
      throw new Error(`Failed to connect to Neo4j: ${error.message}`);
    }
  }

  /**
   * Disconnect from Neo4j database
   */
  async disconnect() {
    if (!this.connected) {
      return;
    }

    try {
      await this.driver.close();
      this.connected = false;
      console.error('🔌 Disconnected from Neo4j');
    } catch (error) {
      console.error(`[WARN]  Error disconnecting: ${error.message}`);
    }
  }

  /**
   * Ensure connection is established
   */
  _ensureConnected() {
    if (!this.connected || !this.driver) {
      throw new Error('Not connected to Neo4j. Call connect() first.');
    }
  }

  /**
   * Run a Cypher query
   */
  async runQuery(cypher, parameters = {}, options = {}) {
    this._ensureConnected();

    const startTime = Date.now();
    const session = this.driver.session({
      database: options.database || this.config.database,
      defaultAccessMode: options.write ? neo4j.session.WRITE : neo4j.session.READ
    });

    try {
      const result = await session.run(cypher, parameters);

      // Update statistics
      const queryTime = Date.now() - startTime;
      this.stats.queriesExecuted++;
      this.stats.totalQueryTime += queryTime;
      this.stats.averageQueryTime = this.stats.totalQueryTime / this.stats.queriesExecuted;

      // Extract summary statistics
      if (result.summary && result.summary.counters) {
        const counters = result.summary.counters;
        this.stats.nodesCreated += counters.updates().nodesCreated || 0;
        this.stats.relationshipsCreated += counters.updates().relationshipsCreated || 0;
      }

      return {
        records: result.records,
        summary: result.summary,
        queryTime
      };

    } catch (error) {
      this.stats.queriesFailed++;
      throw new Error(`Query failed: ${error.message}\nQuery: ${cypher.substring(0, 200)}...`);
    } finally {
      await session.close();
    }
  }

  /**
   * Run a write query (convenience method)
   */
  async runWriteQuery(cypher, parameters = {}) {
    return this.runQuery(cypher, parameters, { write: true });
  }

  /**
   * Run multiple queries in a transaction
   */
  async runTransaction(queries, options = {}) {
    this._ensureConnected();

    const session = this.driver.session({
      database: options.database || this.config.database,
      defaultAccessMode: neo4j.session.WRITE
    });

    try {
      const result = await session.executeWrite(async tx => {
        const results = [];

        for (const query of queries) {
          const { cypher, parameters = {} } = query;
          const queryResult = await tx.run(cypher, parameters);
          results.push({
            records: queryResult.records,
            summary: queryResult.summary
          });
        }

        return results;
      });

      this.stats.transactionsCommitted++;
      return result;

    } catch (error) {
      this.stats.transactionsRolledBack++;
      throw new Error(`Transaction failed: ${error.message}`);
    } finally {
      await session.close();
    }
  }

  /**
   * Batch create nodes (more efficient than individual creates)
   */
  async batchCreateNodes(label, nodeDataArray, options = {}) {
    if (nodeDataArray.length === 0) {
      return { created: 0 };
    }

    const batchSize = options.batchSize || 1000;
    let totalCreated = 0;

    console.error(`[LOAD] Batch creating ${nodeDataArray.length} ${label} nodes (batches of ${batchSize})...`);

    for (let i = 0; i < nodeDataArray.length; i += batchSize) {
      const batch = nodeDataArray.slice(i, i + batchSize);

      const cypher = `
        UNWIND $batch AS nodeData
        MERGE (n:${label} {${options.mergeKey || 'id'}: nodeData.${options.mergeKey || 'id'}})
        SET n += nodeData
        RETURN count(n) as created
      `;

      const result = await this.runWriteQuery(cypher, { batch });
      const created = result.records[0].get('created').toNumber();
      totalCreated += created;

      if ((i / batchSize + 1) % 10 === 0) {
        console.error(`   Progress: ${i + batch.length}/${nodeDataArray.length} nodes processed`);
      }
    }

    console.error(`[OK] Created ${totalCreated} ${label} nodes`);
    return { created: totalCreated };
  }

  /**
   * Batch create relationships
   */
  async batchCreateRelationships(relationshipType, relationshipDataArray, options = {}) {
    if (relationshipDataArray.length === 0) {
      return { created: 0 };
    }

    const batchSize = options.batchSize || 1000;
    let totalCreated = 0;

    console.error(`🔗 Batch creating ${relationshipDataArray.length} ${relationshipType} relationships...`);

    for (let i = 0; i < relationshipDataArray.length; i += batchSize) {
      const batch = relationshipDataArray.slice(i, i + batchSize);

      const cypher = `
        UNWIND $batch AS relData
        MATCH (a:${options.fromLabel} {${options.fromKey}: relData.from})
        MATCH (b:${options.toLabel} {${options.toKey}: relData.to})
        MERGE (a)-[r:${relationshipType}]->(b)
        SET r += relData.properties
        RETURN count(r) as created
      `;

      const result = await this.runWriteQuery(cypher, { batch });
      const created = result.records[0].get('created').toNumber();
      totalCreated += created;

      if ((i / batchSize + 1) % 10 === 0) {
        console.error(`   Progress: ${i + batch.length}/${relationshipDataArray.length} relationships processed`);
      }
    }

    console.error(`[OK] Created ${totalCreated} ${relationshipType} relationships`);
    return { created: totalCreated };
  }

  /**
   * Get count of nodes by label
   */
  async getNodeCount(label = null) {
    const cypher = label
      ? `MATCH (n:${label}) RETURN count(n) as count`
      : `MATCH (n) RETURN count(n) as count`;

    const result = await this.runQuery(cypher);
    return result.records[0].get('count').toNumber();
  }

  /**
   * Get count of relationships by type
   */
  async getRelationshipCount(type = null) {
    const cypher = type
      ? `MATCH ()-[r:${type}]->() RETURN count(r) as count`
      : `MATCH ()-[r]->() RETURN count(r) as count`;

    const result = await this.runQuery(cypher);
    return result.records[0].get('count').toNumber();
  }

  /**
   * Clear all data (use with caution!)
   */
  async clearDatabase() {
    console.error('[WARN]  Clearing entire database...');

    await this.runWriteQuery('MATCH (n) DETACH DELETE n');

    console.error('[OK] Database cleared');
    return true;
  }

  /**
   * Create indexes for better query performance
   */
  async createIndex(label, property, options = {}) {
    const indexName = options.name || `idx_${label}_${property}`;

    try {
      const cypher = `CREATE INDEX ${indexName} IF NOT EXISTS FOR (n:${label}) ON (n.${property})`;
      await this.runWriteQuery(cypher);
      console.error(`[OK] Created index: ${indexName}`);
    } catch (error) {
      console.error(`[WARN]  Index creation failed: ${error.message}`);
    }
  }

  /**
   * Create uniqueness constraint
   */
  async createUniqueConstraint(label, property, options = {}) {
    const constraintName = options.name || `unique_${label}_${property}`;

    try {
      const cypher = `CREATE CONSTRAINT ${constraintName} IF NOT EXISTS FOR (n:${label}) REQUIRE n.${property} IS UNIQUE`;
      await this.runWriteQuery(cypher);
      console.error(`[OK] Created constraint: ${constraintName}`);
    } catch (error) {
      console.error(`[WARN]  Constraint creation failed: ${error.message}`);
    }
  }

  /**
   * Get database statistics
   */
  async getDatabaseStats() {
    const nodeCount = await this.getNodeCount();
    const relationshipCount = await this.getRelationshipCount();

    // Get node counts by label
    const labelResult = await this.runQuery(`
      CALL db.labels() YIELD label
      CALL {
        WITH label
        MATCH (n)
        WHERE label IN labels(n)
        RETURN count(n) as count
      }
      RETURN label, count
      ORDER BY count DESC
    `);

    const labelCounts = {};
    labelResult.records.forEach(record => {
      labelCounts[record.get('label')] = record.get('count').toNumber();
    });

    // Get relationship counts by type
    const typeResult = await this.runQuery(`
      CALL db.relationshipTypes() YIELD relationshipType
      CALL {
        WITH relationshipType
        MATCH ()-[r]->()
        WHERE type(r) = relationshipType
        RETURN count(r) as count
      }
      RETURN relationshipType, count
      ORDER BY count DESC
    `);

    const typeCounts = {};
    typeResult.records.forEach(record => {
      typeCounts[record.get('relationshipType')] = record.get('count').toNumber();
    });

    return {
      totalNodes: nodeCount,
      totalRelationships: relationshipCount,
      nodesByLabel: labelCounts,
      relationshipsByType: typeCounts,
      clientStats: this.stats
    };
  }

  /**
   * Get client statistics
   */
  getStats() {
    return {
      ...this.stats,
      connected: this.connected,
      averageQueryTimeMs: Math.round(this.stats.averageQueryTime)
    };
  }

  /**
   * Reset statistics
   */
  resetStats() {
    this.stats = {
      queriesExecuted: 0,
      queriesFailed: 0,
      nodesCreated: 0,
      relationshipsCreated: 0,
      transactionsCommitted: 0,
      transactionsRolledBack: 0,
      totalQueryTime: 0,
      averageQueryTime: 0
    };
  }

  /**
   * Test connection health
   */
  async healthCheck() {
    try {
      await this.runQuery('RETURN 1 as health');
      return { healthy: true, connected: this.connected };
    } catch (error) {
      return { healthy: false, connected: this.connected, error: error.message };
    }
  }
}
