# Data Access Layer

## Overview

The Data Access Layer provides a unified interface to both Neo4j graph database and ChromaDB vector database. It implements hybrid query patterns that combine graph traversal with semantic search for Context7-inspired RAG capabilities.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   UnifiedDataAccess                         │
│  (Hybrid queries combining graph + vector)                 │
└───────────────────┬─────────────────────────────────────────┘
                    │
        ┌───────────┴───────────┐
        │                       │
┌───────▼──────────┐    ┌──────▼──────────┐
│  GraphDatabase   │    │ VectorDatabase  │
│   (Neo4j)        │    │   (ChromaDB)    │
└──────────────────┘    └─────────────────┘
```

## Components

### GraphDatabase.js

Neo4j graph database client for code structure relationships.

**Key Features:**
- Connection pooling with Bolt driver
- Query patterns for IMPORTS, CALLS, DEFINES relationships
- Dependency tracing and call graph traversal
- Circular dependency detection
- Health checks and performance metrics

**Example Usage:**

```javascript
import { GraphDatabase } from './src/data/GraphDatabase.js';

const graphDB = new GraphDatabase({
  uri: 'bolt://localhost:7687',
  username: 'neo4j',
  password: 'gfsworkflow2025'
});

await graphDB.connect();

// Find all files that import a module
const importers = await graphDB.findImporters('wxflow');

// Trace function call chain
const callChain = await graphDB.traceCallChain('run_forecast', 3);

// Get dependency graph for a file
const deps = await graphDB.findDependencyGraph('/path/to/file.py', 2);

// Get statistics
const stats = await graphDB.getStatistics();
console.log(`Files: ${stats.fileCount}, Functions: ${stats.functionCount}`);
```

**Key Methods:**

| Method | Description |
|--------|-------------|
| `findImporters(moduleName)` | Find all files importing a module |
| `findFileImports(filePath)` | Get all imports in a file |
| `traceCallChain(functionName, depth)` | Trace function call chain |
| `findCallers(functionName)` | Find functions that call a function |
| `findFileFunctions(filePath)` | Get functions defined in a file |
| `findFileClasses(filePath)` | Get classes defined in a file |
| `findDependencyGraph(filePath, depth)` | Get dependency graph |
| `findCircularDependencies(maxDepth)` | Detect circular dependencies |
| `getStatistics()` | Get code structure statistics |

### VectorDatabase.js

ChromaDB vector database client for semantic search.

**Key Features:**
- Automatic embedding generation with Xenova transformers
- Collection management (create, list, delete)
- Batch operations for performance
- Multi-collection search
- Metadata filtering
- Health checks and performance metrics

**Example Usage:**

```javascript
import { VectorDatabase } from './src/data/VectorDatabase.js';

const vectorDB = new VectorDatabase({
  host: '127.0.0.1',
  port: 8080,
  embeddingModel: 'Xenova/all-MiniLM-L6-v2'
});

await vectorDB.connect();

// Add documents
await vectorDB.addDocuments('code_with_context', [
  {
    id: 'func_001',
    text: 'def process_data(input_file): ...',
    metadata: { filePath: '/src/process.py', type: 'function' }
  }
]);

// Semantic search
const results = await vectorDB.query('code_with_context', 'data processing', {
  nResults: 10,
  where: { type: 'function' }
});

// Multi-collection search
const multiResults = await vectorDB.multiCollectionQuery(
  ['code_with_context', 'global-workflow-docs'],
  'forecast initialization',
  { nResults: 20 }
);

// Get document by ID
const doc = await vectorDB.getDocument('code_with_context', 'func_001');
```

**Key Methods:**

| Method | Description |
|--------|-------------|
| `generateEmbeddings(text)` | Generate embeddings for text |
| `getOrCreateCollection(name, metadata)` | Get/create collection |
| `listCollections()` | List all collections |
| `addDocuments(collectionName, documents)` | Add documents with embeddings |
| `query(collectionName, queryText, options)` | Semantic search |
| `multiCollectionQuery(collections, queryText, options)` | Search multiple collections |
| `getDocument(collectionName, id)` | Get document by ID |
| `updateMetadata(collectionName, id, metadata)` | Update document metadata |
| `deleteDocuments(collectionName, ids)` | Delete documents |
| `getCollectionCount(collectionName)` | Get document count |

### UnifiedDataAccess.js

Unified interface combining graph and vector databases for hybrid queries.

**Key Features:**
- Hybrid queries (graph + vector combined)
- Context-aware code retrieval
- Dependency-enhanced search
- Execution path tracing with code snippets
- Related code discovery
- Unified health checks and metrics

**Example Usage:**

```javascript
import { UnifiedDataAccess } from './src/data/UnifiedDataAccess.js';

const unified = new UnifiedDataAccess({
  neo4j: {
    uri: 'bolt://localhost:7687',
    username: 'neo4j',
    password: 'gfsworkflow2025'
  },
  chromadb: {
    host: '127.0.0.1',
    port: 8080
  }
});

await unified.connect();

// Hybrid query with graph context enrichment
const results = await unified.hybridQuery('forecast initialization', {
  collection: 'code_with_context',
  nResults: 10,
  includeGraphContext: true,
  includeDependencies: true,
  includeCallers: true
});

// Results include both semantic search and graph context:
// {
//   id: 'chunk_123',
//   text: 'def initialize_forecast(): ...',
//   metadata: { filePath: '/src/forecast.py' },
//   distance: 0.15,
//   score: 0.85,
//   graphContext: {
//     imports: [...],
//     functions: [...],
//     classes: [...],
//     callers: [...]
//   }
// }

// Find code with full dependency context
const codeWithDeps = await unified.findCodeWithDependencies('initialize_forecast', {
  maxDepth: 2,
  includeSemanticSimilar: true
});

// Trace execution path with code snippets
const executionPath = await unified.traceExecutionPath('run_forecast', {
  maxDepth: 3,
  includeCode: true
});

// Find related code based on dependencies
const related = await unified.findRelatedCode('/src/forecast.py', {
  includeDocumentation: true,
  maxResults: 20
});

// Multi-source search across collections
const multiResults = await unified.multiSourceSearch('data assimilation', {
  collections: ['code_with_context', 'global-workflow-docs', 'operational_docs'],
  nResults: 15,
  enrichWithGraph: true
});

// Get comprehensive statistics
const stats = await unified.getStatistics();
console.log('Graph:', stats.graph);
console.log('Vector:', stats.vector);
console.log('Unified Metrics:', stats.unified);
```

**Key Methods:**

| Method | Description |
|--------|-------------|
| `hybridQuery(queryText, options)` | Semantic search with graph enrichment |
| `findCodeWithDependencies(identifier, options)` | Get code with full dependency context |
| `multiSourceSearch(queryText, options)` | Search across multiple collections |
| `findRelatedCode(filePath, options)` | Find related code via dependencies |
| `traceExecutionPath(functionName, options)` | Trace call chain with snippets |
| `getStatistics()` | Get comprehensive statistics |
| `healthCheck()` | Check health of both databases |

## Testing

### Running Tests

```bash
# Install test dependencies
npm install

# Run all tests
npm test

# Run with watch mode
npm run test:watch

# Run with coverage report
npm run test:coverage

# Run only data layer tests
npm run test:data
```

### Test Structure

```
src/data/__tests__/
├── GraphDatabase.test.js       # Neo4j tests
├── VectorDatabase.test.js      # ChromaDB tests
└── UnifiedDataAccess.test.js   # Hybrid query tests
```

### Coverage Targets

- **Lines:** 85%
- **Functions:** 85%
- **Branches:** 80%
- **Statements:** 85%

### Test Environment

Tests require running instances of:
- Neo4j (bolt://localhost:7687)
- ChromaDB (http://127.0.0.1:8080)

Set environment variables:
```bash
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USERNAME=neo4j
export NEO4J_PASSWORD=gfsworkflow2025
export CHROMADB_HOST=127.0.0.1
export CHROMADB_PORT=8080
```

## Performance Considerations

### Connection Pooling

Both databases use connection pooling:
- **Neo4j:** `maxConnectionPoolSize: 50`
- **ChromaDB:** HTTP client with keep-alive

### Batch Operations

VectorDatabase supports batch operations:
```javascript
// Process 150 documents in batches of 100
await vectorDB.addDocuments(collection, documents); // Auto-batches
```

### Caching

UnifiedDataAccess includes simple caching:
```javascript
// Cache timeout: 5 minutes default
const unified = new UnifiedDataAccess({ cacheTimeout: 300000 });

// Clear cache manually
unified.clearCache();
```

### Metrics Tracking

All components track performance metrics:
```javascript
const metrics = unified.getMetrics();
console.log('Hybrid Queries:', metrics.unified.hybridQueries);
console.log('Avg Query Time:', metrics.graph.avgQueryTime);
console.log('Cache Hit Rate:', 
  metrics.unified.cacheHits / 
  (metrics.unified.cacheHits + metrics.unified.cacheMisses)
);
```

## Error Handling

All methods use try-catch with appropriate error logging:

```javascript
try {
  const results = await unified.hybridQuery('test');
} catch (error) {
  console.error('Query failed:', error.message);
  // Error is propagated, handle appropriately
}
```

Health checks never throw:
```javascript
const health = await unified.healthCheck();
// Always returns { status: 'healthy' | 'degraded' | 'unhealthy', ... }
```

## Integration with MCP Tools

### Before (RAGTools without graph context):
```javascript
async searchDocumentation(query, maxResults) {
  const results = await this.chromaClient.query(collection, query);
  return results; // Just vector search
}
```

### After (Using UnifiedDataAccess):
```javascript
async searchDocumentation(query, maxResults) {
  const results = await this.unifiedDB.hybridQuery(query, {
    collection: 'global-workflow-docs',
    nResults: maxResults,
    includeGraphContext: true,
    includeDependencies: true
  });
  return results; // Vector search + graph enrichment
}
```

## Next Steps

See `MCP_REFACTORING_PLAN_2025-10-16.md` for:
- Week 2: Tool Consolidation using this data layer
- Week 3: Context7 ingestion improvements
- Week 4: Deployment automation

## References

- [Neo4j Driver Documentation](https://neo4j.com/docs/javascript-manual/current/)
- [ChromaDB Documentation](https://docs.trychroma.com/)
- [Xenova Transformers](https://huggingface.co/docs/transformers.js/)
- [Context7 Paper](https://arxiv.org/abs/2310.03025) (inspiration)
