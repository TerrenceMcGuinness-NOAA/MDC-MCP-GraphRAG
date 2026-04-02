/**
 * MatryoshkaQuery.js - Adaptive Dimension Truncation
 *
 * Supports Matryoshka embeddings (e.g., Amazon Nova) by truncating stored
 * embeddings to a specified prefix length at query time.
 *
 * Uses OpenSearch script_score or k-NN query with truncated prefix for
 * lower-dimension searches.
 *
 * @version 1.0.0
 * @author Ingestion Pipeline Restructure
 */

export class MatryoshkaQuery {
  /**
   * Build a k-NN query with adaptive dimension truncation.
   *
   * @param {Array<number>} queryVector - Full-dimension query vector
   * @param {object} options
   * @param {number} [options.dimensions] - Target dimension (truncate to this prefix)
   * @param {number} [options.k=10] - Number of results
   * @param {object} [options.filter] - Metadata filter
   * @returns {object} OpenSearch query body
   */
  build(queryVector, options = {}) {
    const { dimensions, k = 10, filter = null } = options;

    if (!dimensions || dimensions >= queryVector.length) {
      // No truncation needed
      return this._buildStandardQuery(queryVector, k, filter);
    }

    // Truncate query vector to prefix
    const truncatedVector = this._truncate(queryVector, dimensions);
    return this._buildTruncatedQuery(truncatedVector, k, filter, dimensions);
  }

  /**
   * Truncate vector to specified prefix length.
   *
   * @param {Array<number>} vector
   * @param {number} targetDim
   * @returns {Array<number>}
   */
  _truncate(vector, targetDim) {
    return vector.slice(0, targetDim);
  }

  _buildStandardQuery(queryVector, k, filter) {
    const query = {
      size: k,
      query: {
        knn: {
          embedding: {
            vector: queryVector,
            k,
          },
        },
      },
      _source: ['content', 'metadata', 'source_file', 'chunk_id', 'collection_name', 'model_profile'],
    };

    if (filter) {
      query.query = {
        bool: {
          must: [{ knn: { embedding: { vector: queryVector, k } } }],
          filter,
        },
      };
    }

    return query;
  }

  _buildTruncatedQuery(truncatedVector, k, filter, dimensions) {
    // Use script_score to compute cosine similarity on truncated prefix
    const query = {
      size: k,
      query: {
        script_score: {
          query: filter ? { bool: { filter } } : { match_all: {} },
          script: {
            source: `
              def truncated = new double[${dimensions}];
              for (int i = 0; i < ${dimensions}; i++) {
                truncated[i] = doc['embedding'][i];
              }
              return cosineSimilarity(params.query_vector, truncated) + 1.0;
            `,
            params: {
              query_vector: truncatedVector,
            },
          },
        },
      },
      _source: ['content', 'metadata', 'source_file', 'chunk_id', 'collection_name', 'model_profile'],
    };

    return query;
  }
}

export default MatryoshkaQuery;
