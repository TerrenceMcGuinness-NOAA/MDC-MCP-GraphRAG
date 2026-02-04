/**
 * Embedding Utilities for MCP Server
 * 
 * Provides consistent MPNet embeddings (768 dimensions) for semantic search.
 * Uses @xenova/transformers for ONNX-based inference.
 * 
 * @module embeddings
 * @version 8.0.0
 * @date February 4, 2026
 */

let pipeline = null;
let extractor = null;
let isLoading = false;
let loadPromise = null;

const MODEL_NAME = 'Xenova/all-mpnet-base-v2';
const EMBEDDING_DIMENSIONS = 768;

/**
 * Initialize the embedding model (lazy loading)
 * @returns {Promise<Function>} The extractor pipeline
 */
async function getExtractor() {
  if (extractor) {
    return extractor;
  }
  
  if (isLoading && loadPromise) {
    return loadPromise;
  }
  
  isLoading = true;
  loadPromise = (async () => {
    try {
      // Dynamically import to avoid blocking
      const transformers = await import('@xenova/transformers');
      pipeline = transformers.pipeline;
      
      console.log('[Embeddings] Loading MPNet model...');
      extractor = await pipeline('feature-extraction', MODEL_NAME);
      console.log('[Embeddings] Model loaded successfully');
      
      return extractor;
    } catch (error) {
      console.error('[Embeddings] Failed to load model:', error.message);
      throw error;
    } finally {
      isLoading = false;
    }
  })();
  
  return loadPromise;
}

/**
 * Generate embedding for a single text
 * @param {string} text - Text to embed
 * @returns {Promise<number[]>} 768-dimensional embedding vector
 */
async function embed(text) {
  const ext = await getExtractor();
  const output = await ext(text, { pooling: 'mean', normalize: true });
  return Array.from(output.data);
}

/**
 * Generate embeddings for multiple texts
 * @param {string[]} texts - Array of texts to embed
 * @returns {Promise<number[][]>} Array of 768-dimensional embedding vectors
 */
async function embedBatch(texts) {
  const ext = await getExtractor();
  const embeddings = [];
  
  for (const text of texts) {
    const output = await ext(text, { pooling: 'mean', normalize: true });
    embeddings.push(Array.from(output.data));
  }
  
  return embeddings;
}

/**
 * Query ChromaDB collection using MPNet embeddings
 * @param {object} collection - ChromaDB collection instance
 * @param {string} queryText - Query text
 * @param {number} nResults - Number of results (default: 5)
 * @returns {Promise<object>} ChromaDB query results
 */
async function queryWithEmbeddings(collection, queryText, nResults = 5) {
  const queryEmbedding = await embed(queryText);
  
  return await collection.query({
    queryEmbeddings: [queryEmbedding],
    nResults,
    include: ['documents', 'metadatas', 'distances']
  });
}

/**
 * Get model info
 * @returns {object} Model configuration
 */
function getModelInfo() {
  return {
    model: MODEL_NAME,
    dimensions: EMBEDDING_DIMENSIONS,
    loaded: !!extractor
  };
}

export {
  embed,
  embedBatch,
  queryWithEmbeddings,
  getExtractor,
  getModelInfo,
  MODEL_NAME,
  EMBEDDING_DIMENSIONS
};

export default {
  embed,
  embedBatch,
  queryWithEmbeddings,
  getExtractor,
  getModelInfo,
  MODEL_NAME,
  EMBEDDING_DIMENSIONS
};
