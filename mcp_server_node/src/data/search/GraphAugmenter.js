/**
 * GraphAugmenter.js - Graph-Augmented Vector Retrieval
 *
 * Expands vector search results with 1-hop graph neighbors from Neptune/Neo4j.
 * Queries for CALLS, USES, IMPORTS, CONTAINS relationships to enrich context.
 *
 * Graceful fallback: if graph DB unavailable, returns original results unchanged.
 *
 * @version 1.0.0
 * @author Ingestion Pipeline Restructure
 */

export class GraphAugmenter {
  /**
   * Expand vector search results with 1-hop graph neighbors.
   *
   * @param {Array} vectorResults - Results from vector search
   * @param {GraphDatabaseAdapter} graphDB - Neptune/Neo4j adapter
   * @param {object} options
   * @param {number} [options.hopDepth=1] - 1 or 2 (default: 1)
   * @param {Array<string>} [options.relationshipTypes] - Relationship types to traverse
   * @returns {Promise<Array>} Results with graph_context field
   */
  async augment(vectorResults, graphDB, options = {}) {
    const { hopDepth = 1, relationshipTypes = ['CALLS', 'USES', 'IMPORTS', 'CONTAINS'] } = options;

    if (!graphDB || !vectorResults || vectorResults.length === 0) {
      return vectorResults;
    }

    try {
      const augmented = [];

      for (const result of vectorResults) {
        const graphContext = await this._fetchNeighbors(
          result,
          graphDB,
          hopDepth,
          relationshipTypes
        );

        augmented.push({
          ...result,
          graph_context: graphContext,
        });
      }

      return augmented;
    } catch (error) {
      console.error('[WARN] GraphAugmenter: graph expansion failed, returning original results:', error.message);
      return vectorResults;
    }
  }

  /**
   * Fetch 1-hop or 2-hop neighbors for a single result.
   *
   * @param {object} result - Vector search result
   * @param {GraphDatabaseAdapter} graphDB
   * @param {number} hopDepth
   * @param {Array<string>} relationshipTypes
   * @returns {Promise<object>} Graph context
   */
  async _fetchNeighbors(result, graphDB, hopDepth, relationshipTypes) {
    const sourceFile = result.metadata?.source_file || result.metadata?.file_path;
    if (!sourceFile) {
      return { neighbors: [], relationships: [] };
    }

    const relTypeFilter = relationshipTypes.map(t => `'${t}'`).join(', ');
    const query = hopDepth === 1
      ? this._build1HopQuery(sourceFile, relTypeFilter)
      : this._build2HopQuery(sourceFile, relTypeFilter);

    try {
      const records = await graphDB.executeQuery(query);
      return this._parseNeighbors(records);
    } catch (error) {
      console.error(`[WARN] GraphAugmenter: query failed for ${sourceFile}:`, error.message);
      return { neighbors: [], relationships: [] };
    }
  }

  _build1HopQuery(sourceFile, relTypeFilter) {
    return `
      MATCH (n {file_path: $sourceFile})-[r]->(m)
      WHERE type(r) IN [${relTypeFilter}]
      RETURN m.file_path AS neighbor, type(r) AS relationship, m.label AS label
      LIMIT 20
    `.replace('$sourceFile', `'${sourceFile}'`);
  }

  _build2HopQuery(sourceFile, relTypeFilter) {
    return `
      MATCH (n {file_path: $sourceFile})-[r1]->(m)-[r2]->(o)
      WHERE type(r1) IN [${relTypeFilter}] AND type(r2) IN [${relTypeFilter}]
      RETURN o.file_path AS neighbor, type(r2) AS relationship, o.label AS label
      LIMIT 20
    `.replace('$sourceFile', `'${sourceFile}'`);
  }

  _parseNeighbors(records) {
    const neighbors = [];
    const relationships = [];

    for (const record of records) {
      const neighbor = record.get ? record.get('neighbor') : record.neighbor;
      const relationship = record.get ? record.get('relationship') : record.relationship;
      const label = record.get ? record.get('label') : record.label;

      if (neighbor) {
        neighbors.push({ file_path: neighbor, label });
        relationships.push(relationship);
      }
    }

    return { neighbors, relationships };
  }
}

export default GraphAugmenter;
