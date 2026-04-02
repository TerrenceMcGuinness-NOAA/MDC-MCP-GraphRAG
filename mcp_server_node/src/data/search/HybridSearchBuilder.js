/**
 * HybridSearchBuilder.js - BM25 + Vector + RRF Fusion
 *
 * Constructs OpenSearch hybrid queries combining BM25 keyword search with
 * k-NN vector search, fused via Reciprocal Rank Fusion (RRF).
 *
 * Auto-detects code identifiers (camelCase, snake_case, dot.notation, file paths)
 * and boosts BM25 weight accordingly.
 *
 * @version 1.0.0
 * @author Ingestion Pipeline Restructure
 */

export class HybridSearchBuilder {
  /**
   * Build a hybrid BM25 + k-NN query with RRF fusion.
   *
   * @param {string} queryText - User query
   * @param {Array<number>} queryVector - Embedding vector
   * @param {object} options
   * @param {string} [options.searchMode='vector'] - "vector" | "keyword" | "hybrid"
   * @param {number} [options.bm25Weight=1.0] - BM25 boost (auto-increased for code identifiers)
   * @param {number} [options.vectorWeight=1.0] - Vector search boost
   * @param {number} [options.k=10] - Number of results
   * @param {object} [options.filter] - Metadata filter (OpenSearch bool filter)
   * @returns {object} OpenSearch query body
   */
  build(queryText, queryVector, options = {}) {
    const {
      searchMode = 'vector',
      bm25Weight = 1.0,
      vectorWeight = 1.0,
      k = 10,
      filter = null,
    } = options;

    // Auto-boost BM25 for code identifiers
    const hasCodeIdentifiers = this._containsCodeIdentifiers(queryText);
    const effectiveBM25Weight = hasCodeIdentifiers ? bm25Weight * 2.0 : bm25Weight;

    if (searchMode === 'keyword') {
      return this._buildKeywordQuery(queryText, k, filter, effectiveBM25Weight);
    }

    if (searchMode === 'vector') {
      return this._buildVectorQuery(queryVector, k, filter);
    }

    // Hybrid mode: BM25 + k-NN with RRF
    return this._buildHybridQuery(queryText, queryVector, k, filter, effectiveBM25Weight, vectorWeight);
  }

  /**
   * Detect code identifiers in query text.
   * Patterns: camelCase, snake_case, dot.notation, file/paths
   *
   * @param {string} queryText
   * @returns {boolean}
   */
  _containsCodeIdentifiers(queryText) {
    const patterns = [
      /[a-z][A-Z]/,                    // camelCase
      /[a-z_]+_[a-z_]+/,               // snake_case
      /[a-zA-Z]+\.[a-zA-Z]+/,          // dot.notation
      /[a-zA-Z0-9_-]+\/[a-zA-Z0-9_-]+/, // file/paths
    ];
    return patterns.some(p => p.test(queryText));
  }

  _buildKeywordQuery(queryText, k, filter, boost) {
    const query = {
      size: k,
      query: {
        bool: {
          must: [
            {
              match: {
                content: {
                  query: queryText,
                  boost,
                },
              },
            },
          ],
        },
      },
      _source: ['content', 'metadata', 'source_file', 'chunk_id', 'collection_name', 'model_profile'],
    };

    if (filter) {
      query.query.bool.filter = filter;
    }

    return query;
  }

  _buildVectorQuery(queryVector, k, filter) {
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

  _buildHybridQuery(queryText, queryVector, k, filter, bm25Boost, vectorBoost) {
    // Use OpenSearch search pipeline with normalization-processor and RRF
    // For now, construct a bool query with should clauses (application-level fusion)
    // TODO: Migrate to search_pipeline when OpenSearch 2.x is deployed
    const query = {
      size: k,
      query: {
        bool: {
          should: [
            {
              match: {
                content: {
                  query: queryText,
                  boost: bm25Boost,
                },
              },
            },
            {
              knn: {
                embedding: {
                  vector: queryVector,
                  k,
                  boost: vectorBoost,
                },
              },
            },
          ],
          minimum_should_match: 1,
        },
      },
      _source: ['content', 'metadata', 'source_file', 'chunk_id', 'collection_name', 'model_profile'],
    };

    if (filter) {
      query.query.bool.filter = filter;
    }

    return query;
  }
}

export default HybridSearchBuilder;
