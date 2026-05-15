/**
 * OpenSearchAdapter.js - OpenSearch Vector Database Adapter
 *
 * Implements VectorDatabaseAdapter for AWS OpenSearch Service.
 * Uses k-NN search with 768-dim MPNet embeddings (same model as ChromaDB).
 * Authenticates via AWS SigV4 (IAM role on ECS, env credentials locally).
 *
 * Output format is identical to VectorDatabase._formatQueryResults():
 *   { id, text, metadata, distance, score }
 *   where score = cosine similarity in [0, 1], distance = 1 - score
 *
 * Index naming: ChromaDB collection name → OpenSearch index name
 *   e.g. "code-with-context-v8-0-0" → "mdc-code-context"
 *   Falls back to the collection name itself if no mapping exists.
 *
 * @version 1.0.0
 * @author Phase 48 — AWS Infrastructure Port
 */

import { Client } from '@opensearch-project/opensearch';
import { AwsSigv4Signer } from '@opensearch-project/opensearch/lib/aws/index-v3.js';
import { defaultProvider } from '@aws-sdk/credential-provider-node';
import { pipeline } from '@xenova/transformers';
import { Agent as HttpsAgent } from 'node:https';
import { VectorDatabaseAdapter } from './VectorDatabaseAdapter.js';

// Singleton embedding model — shared with ChromaDB adapter if both loaded
let _embedder = null;
let _embedderPromise = null;
const EMBEDDING_MODEL = 'Xenova/all-mpnet-base-v2';
const EMBEDDING_DIM = 768;

// ChromaDB collection → OpenSearch index name mapping
// Index names use model-aware naming: mdc-{domain}-{model-short}
const COLLECTION_TO_INDEX = {
  'code-with-context-v8-0-0':       'mdc-code-context-mpnet768',
  'global-workflow-docs-v8-0-0':    'mdc-workflow-docs-mpnet768',
  'jjobs-v8-0-0':                   'mdc-jjobs-mpnet768',
  'community-summaries':            'mdc-community-summaries-mpnet768',
  'ee2-standards-v5-0-0-enhanced':  'mdc-ee2-standards-mpnet768',
};

export class OpenSearchAdapter extends VectorDatabaseAdapter {
  /**
   * @param {object} config
   * @param {string} config.endpoint  - OpenSearch domain endpoint (https://...)
   * @param {string} [config.region]  - AWS region (default: AWS_REGION env or us-east-1)
   * @param {number} [config.maxSockets=10]     - Max concurrent HTTPS sockets per microVM
   *   (matches Neptune maxConnectionPoolSize; see Phase 56).
   * @param {number} [config.maxFreeSockets=5]  - Max idle sockets kept in pool.
   * @param {number} [config.keepAliveMsecs=30000] - TCP keepalive interval (30s).
   * @param {number} [config.socketTimeout=60000]  - Per-socket I/O timeout (60s).
   */
  constructor(config = {}) {
    super();
    this.endpoint = config.endpoint || process.env.OPENSEARCH_ENDPOINT || '';
    this.region   = config.region   || process.env.AWS_REGION || 'us-east-1';
    this.poolConfig = {
      maxSockets:     config.maxSockets     || 10,
      maxFreeSockets: config.maxFreeSockets || 5,
      keepAliveMsecs: config.keepAliveMsecs || 30000,
      socketTimeout:  config.socketTimeout  || 60000,
    };
    this.client   = null;
    this.agent    = null;
    this.connected = false;
    this.metrics = { queriesExecuted: 0, documentsAdded: 0, avgQueryTime: 0, lastQueryTime: null };
  }

  /** Initialize OpenSearch client with SigV4 auth and load embedding model */
  async connect() {
    if (this.connected) return;

    if (!this.endpoint) {
      throw new Error('OpenSearchAdapter: endpoint is required (set OPENSEARCH_ENDPOINT or pass config.endpoint)');
    }

    // Bounded HTTPS agent prevents unbounded socket accumulation in long-lived
    // microVMs. Phase 56 fix — OpenSearch has a hard cluster limit of 1000
    // connections; without this, multiple microVMs (from Kiro reconnect storms)
    // each open unbounded connections and hit the limit.
    // Mirrors Neptune's maxConnectionPoolSize: 10 from fix 6ad5094.
    this.agent = new HttpsAgent({
      maxSockets:     this.poolConfig.maxSockets,
      maxFreeSockets: this.poolConfig.maxFreeSockets,
      keepAlive:      true,
      keepAliveMsecs: this.poolConfig.keepAliveMsecs,
      timeout:        this.poolConfig.socketTimeout,
    });

    this.client = new Client({
      ...AwsSigv4Signer({
        region: this.region,
        service: 'es',
        getCredentials: defaultProvider(),
      }),
      node: this.endpoint,
      agent: () => this.agent,
    });

    // Load singleton embedding model
    if (!_embedder) {
      if (_embedderPromise) {
        await _embedderPromise;
      } else {
        _embedderPromise = pipeline('feature-extraction', EMBEDDING_MODEL)
          .then(m => { _embedder = m; _embedderPromise = null; return m; })
          .catch(e => { _embedderPromise = null; throw e; });
        await _embedderPromise;
      }
    }

    this.connected = true;
    console.error(`[OK] OpenSearchAdapter connected: ${this.endpoint}`);
  }

  /** Generate 768-dim embeddings using the singleton MPNet model */
  async generateEmbeddings(text) {
    if (!_embedder) await this.connect();
    const texts = Array.isArray(text) ? text : [text];
    const output = await _embedder(texts, { pooling: 'mean', normalize: true });
    const embeddings = output.tolist();
    return Array.isArray(text) ? embeddings : embeddings[0];
  }

  /**
   * Semantic k-NN search within one collection/index.
   *
   * @param {string} collectionName - ChromaDB collection name (mapped to OS index)
   * @param {string} queryText
   * @param {object} options
   * @param {number}  [options.nResults=10]
   * @param {object}  [options.where]  - Metadata filter (ChromaDB-style key/value map)
   * @returns {Promise<Array<{id,text,metadata,distance,score}>>}
   */
  async query(collectionName, queryText, options = {}) {
    if (!this.connected) await this.connect();

    const index = this._toIndex(collectionName);
    const nResults = options.nResults || 10;
    const t0 = Date.now();

    const queryVector = await this.generateEmbeddings(queryText);

    const osQuery = {
      size: nResults,
      query: {
        knn: {
          embedding: {
            vector: queryVector,
            k: nResults,
          },
        },
      },
      _source: ['content', 'metadata', 'source_file', 'chunk_id', 'collection_name'],
    };

    // Translate ChromaDB `where` filter to OpenSearch bool filter
    if (options.where && Object.keys(options.where).length > 0) {
      osQuery.query = {
        bool: {
          must: [{ knn: { embedding: { vector: queryVector, k: nResults } } }],
          filter: this._buildFilter(options.where),
        },
      };
    }

    const resp = await this.client.search({ index, body: osQuery });

    const elapsed = Date.now() - t0;
    this.metrics.queriesExecuted++;
    this.metrics.lastQueryTime = elapsed;
    this.metrics.avgQueryTime =
      (this.metrics.avgQueryTime * (this.metrics.queriesExecuted - 1) + elapsed) /
      this.metrics.queriesExecuted;

    return this._formatHits(resp.body.hits.hits);
  }

  /**
   * Search across multiple collections, merge and return top-N by score.
   *
   * @param {Array<string>} collectionNames
   * @param {string} queryText
   * @param {object} options
   * @returns {Promise<Array>}
   */
  async multiCollectionQuery(collectionNames, queryText, options = {}) {
    if (!this.connected) await this.connect();

    const nResults = options.nResults || 10;
    const allResults = [];

    for (const name of collectionNames) {
      try {
        const results = await this.query(name, queryText, { ...options, nResults });
        results.forEach(r => { r.collection = name; });
        allResults.push(...results);
      } catch (err) {
        console.error(`[WARN] OpenSearchAdapter.multiCollectionQuery: skipping "${name}" — ${err.message}`);
      }
    }

    // Sort by score descending (higher = more similar), return top N
    allResults.sort((a, b) => b.score - a.score);
    return allResults.slice(0, nResults);
  }

  /** Add documents to an index (used by migration/ingestion) */
  async addDocuments(collectionName, documents) {
    if (!this.connected) await this.connect();

    const index = this._toIndex(collectionName);
    const body = [];

    for (const doc of documents) {
      const embedding = doc.embedding || (await this.generateEmbeddings(doc.text));
      body.push({ index: { _index: index, _id: doc.id } });
      body.push({
        content: doc.text,
        embedding,
        metadata: doc.metadata || {},
        source_file: doc.metadata?.source_file || '',
        chunk_id: doc.id,
        collection_name: collectionName,
      });
    }

    const resp = await this.client.bulk({ body });
    if (resp.body.errors) {
      const failed = resp.body.items.filter(i => i.index?.error).length;
      console.error(`[WARN] OpenSearchAdapter.addDocuments: ${failed} of ${documents.length} failed`);
    }
    this.metrics.documentsAdded += documents.length;
  }

  /** List all indices (analogous to listCollections) */
  async listCollections() {
    if (!this.connected) await this.connect();
    const resp = await this.client.cat.indices({ format: 'json' });
    return resp.body.map(i => i.index).filter(n => !n.startsWith('.'));
  }

  /** Document count for an index */
  async getCollectionCount(collectionName) {
    if (!this.connected) await this.connect();
    const index = this._toIndex(collectionName);
    const resp = await this.client.count({ index });
    return resp.body.count;
  }

  /** Health check — verifies cluster is green/yellow and indices exist */
  async healthCheck(options = {}) {
    const minCollections = options.minCollections || 1;
    try {
      if (!this.connected) await this.connect();
      const health = await this.client.cluster.health({});
      const indices = await this.listCollections();
      const status = health.body.status === 'red' ? 'unhealthy'
        : indices.length >= minCollections ? 'healthy' : 'degraded';
      return {
        status,
        connected: true,
        clusterStatus: health.body.status,
        indices,
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

  /**
   * Release all HTTPS sockets held by the OpenSearch client.
   *
   * Phase 56 fix: previously a no-op — this leaked sockets whenever a microVM
   * was torn down (SIGTERM, idle timeout). Now we explicitly close the client
   * (flushing pending requests) and destroy the HTTPS agent to release every
   * socket in the pool.
   */
  async close() {
    try {
      if (this.client && typeof this.client.close === 'function') {
        await this.client.close();
      }
    } catch (err) {
      console.error(`[WARN] OpenSearchAdapter.close: client.close failed — ${err.message}`);
    }
    try {
      if (this.agent && typeof this.agent.destroy === 'function') {
        this.agent.destroy();
      }
    } catch (err) {
      console.error(`[WARN] OpenSearchAdapter.close: agent.destroy failed — ${err.message}`);
    }
    this.client = null;
    this.agent = null;
    this.connected = false;
    console.error('[OK] OpenSearchAdapter closed');
  }

  /**
   * Comparative query across multiple vector spaces (model profiles).
   * Execute a single query text against multiple model-aware collections.
   *
   * @param {string} queryText - Query text
   * @param {Array<string>} modelProfiles - Model profile short names (e.g., ['mpnet768', 'titan1024'])
   * @param {object} options - Query options
   * @param {string} options.baseDomain - Base collection domain (e.g., 'code-with-context')
   * @param {string} options.version - Collection version (e.g., 'v8-0-0')
   * @param {number} [options.nResults=10] - Number of results per model
   * @returns {Promise<object>} Results grouped by model profile
   */
  async comparativeQuery(queryText, modelProfiles, options = {}) {
    if (!this.connected) await this.connect();

    const { baseDomain, version, nResults = 10 } = options;
    if (!baseDomain || !version) {
      throw new Error('comparativeQuery requires baseDomain and version in options');
    }

    const results = {};

    // Query each model-aware collection in parallel
    const promises = modelProfiles.map(async (modelProfile) => {
      const collectionName = `${baseDomain}-${version}-${modelProfile}`;
      try {
        const modelResults = await this.query(collectionName, queryText, { nResults });
        results[modelProfile] = modelResults;
      } catch (err) {
        console.error(`[WARN] comparativeQuery: failed for ${modelProfile} — ${err.message}`);
        results[modelProfile] = [];
      }
    });

    await Promise.all(promises);
    return results;
  }

  // ---------------------------------------------------------------------------
  // Private helpers
  // ---------------------------------------------------------------------------

  /** Map ChromaDB collection name → OpenSearch index name */
  _toIndex(collectionName) {
    return COLLECTION_TO_INDEX[collectionName] || collectionName;
  }

  /**
   * Convert ChromaDB-style `where` filter to OpenSearch bool filter clauses.
   * Supports: { key: value } (term) and { key: { $eq/$in/$gte/$lte } }
   *
   * @param {object} where
   * @returns {Array} OpenSearch filter clauses
   */
  _buildFilter(where) {
    const filters = [];
    for (const [key, value] of Object.entries(where)) {
      const field = `metadata.${key}`;
      if (value !== null && typeof value === 'object') {
        if ('$eq'  in value) filters.push({ term:  { [field]: value.$eq } });
        if ('$in'  in value) filters.push({ terms: { [field]: value.$in } });
        if ('$gte' in value) filters.push({ range: { [field]: { gte: value.$gte } } });
        if ('$lte' in value) filters.push({ range: { [field]: { lte: value.$lte } } });
      } else {
        filters.push({ term: { [field]: value } });
      }
    }
    return filters;
  }

  /**
   * Format OpenSearch hits into the same structure as VectorDatabase._formatQueryResults().
   * OpenSearch k-NN returns cosine similarity as _score in [0, 1] (nmslib cosinesimil).
   * We set score = _score, distance = 1 - score to match ChromaDB convention.
   *
   * @param {Array} hits - resp.body.hits.hits
   * @returns {Array<{id,text,metadata,distance,score}>}
   */
  _formatHits(hits) {
    return hits.map(hit => {
      const score = Math.min(1, Math.max(0, hit._score ?? 0));  // clamp to [0,1]
      return {
        id:       hit._id,
        text:     hit._source?.content ?? null,
        metadata: hit._source?.metadata ?? {},
        distance: 1 - score,
        score,
      };
    });
  }
}

export default OpenSearchAdapter;
