# Data Access Layer - Quick Reference

## Import
```javascript
import { GraphDatabase, VectorDatabase, UnifiedDataAccess } from './src/data/index.js';
```

## GraphDatabase (Neo4j)

### Connect
```javascript
const graphDB = new GraphDatabase({
  uri: 'bolt://localhost:7687',
  username: 'neo4j',
  password: 'gfsworkflow2025'
});
await graphDB.connect();
```

### Common Queries
```javascript
// Find importers
const importers = await graphDB.findImporters('wxflow');

// Find imports in file
const imports = await graphDB.findFileImports('/path/to/file.py');

// Trace call chain
const chain = await graphDB.traceCallChain('function_name', 3);

// Find callers
const callers = await graphDB.findCallers('function_name');

// Get functions in file
const funcs = await graphDB.findFileFunctions('/path/to/file.py');

// Get classes in file
const classes = await graphDB.findFileClasses('/path/to/file.py');

// Dependency graph
const deps = await graphDB.findDependencyGraph('/path/to/file.py', 2);

// Circular dependencies
const circular = await graphDB.findCircularDependencies(5);

// Statistics
const stats = await graphDB.getStatistics();

// Health check
const health = await graphDB.healthCheck();
```

## VectorDatabase (ChromaDB)

### Connect
```javascript
const vectorDB = new VectorDatabase({
  host: '127.0.0.1',
  port: 8080,
  embeddingModel: 'Xenova/all-MiniLM-L6-v2'
});
await vectorDB.connect();
```

### Document Operations
```javascript
// Add documents
await vectorDB.addDocuments('collection_name', [
  {
    id: 'doc1',
    text: 'Document content',
    metadata: { key: 'value' }
  }
]);

// Query (semantic search)
const results = await vectorDB.query('collection_name', 'search query', {
  nResults: 10,
  where: { key: 'value' }
});

// Multi-collection search
const results = await vectorDB.multiCollectionQuery(
  ['collection1', 'collection2'],
  'search query',
  { nResults: 20 }
);

// Get document
const doc = await vectorDB.getDocument('collection_name', 'doc_id');

// Update metadata
await vectorDB.updateMetadata('collection_name', 'doc_id', { updated: true });

// Delete documents
await vectorDB.deleteDocuments('collection_name', ['doc1', 'doc2']);

// List collections
const collections = await vectorDB.listCollections();

// Collection count
const count = await vectorDB.getCollectionCount('collection_name');
```

## UnifiedDataAccess (Hybrid)

### Connect
```javascript
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
```

### Hybrid Queries
```javascript
// Semantic search with graph enrichment
const results = await unified.hybridQuery('forecast initialization', {
  collection: 'code_with_context',
  nResults: 10,
  includeGraphContext: true,
  includeDependencies: true,
  includeCallers: true
});

// Result structure:
// {
//   id: 'chunk_123',
//   text: 'code content',
//   metadata: { filePath: '/src/file.py' },
//   distance: 0.15,
//   score: 0.85,
//   graphContext: {
//     imports: [...],
//     functions: [...],
//     classes: [...],
//     callers: [...]
//   }
// }

// Find code with dependencies
const code = await unified.findCodeWithDependencies('function_name', {
  maxDepth: 2,
  includeSemanticSimilar: true
});

// Multi-source search
const results = await unified.multiSourceSearch('query', {
  collections: ['collection1', 'collection2'],
  nResults: 15,
  enrichWithGraph: true
});

// Find related code
const related = await unified.findRelatedCode('/path/to/file.py', {
  includeDocumentation: true,
  maxResults: 20
});

// Trace execution path
const path = await unified.traceExecutionPath('function_name', {
  maxDepth: 3,
  includeCode: true
});

// Statistics
const stats = await unified.getStatistics();

// Health check
const health = await unified.healthCheck();

// Clear cache
unified.clearCache();
```

## Health Checks

```javascript
// GraphDatabase
const graphHealth = await graphDB.healthCheck();
// { status: 'healthy', connected: true, metrics: {...}, statistics: {...} }

// VectorDatabase
const vectorHealth = await vectorDB.healthCheck();
// { status: 'healthy', connected: true, heartbeat: N, collections: [...], metrics: {...} }

// UnifiedDataAccess
const unifiedHealth = await unified.healthCheck();
// { status: 'healthy', graph: {...}, vector: {...}, metrics: {...} }
```

## Metrics

```javascript
// GraphDatabase
const graphMetrics = graphDB.getMetrics();
// { queriesExecuted: N, queriesFailed: N, avgQueryTime: N, lastQueryTime: N, connected: true }

// VectorDatabase
const vectorMetrics = vectorDB.getMetrics();
// { queriesExecuted: N, documentsAdded: N, embeddingsGenerated: N, avgQueryTime: N, connected: true }

// UnifiedDataAccess
const unifiedMetrics = unified.getMetrics();
// { unified: {...}, graph: {...}, vector: {...} }
```

## Error Handling

All methods throw errors on failure. Use try-catch:

```javascript
try {
  const results = await unified.hybridQuery('query');
} catch (error) {
  console.error('Query failed:', error.message);
}
```

Health checks never throw:
```javascript
const health = await unified.healthCheck();
// Always returns { status: 'healthy' | 'degraded' | 'unhealthy', ... }
```

## Close Connections

```javascript
await graphDB.close();
await vectorDB.close();
await unified.close();  // Closes both graph and vector
```

## Testing

```bash
# Run all tests
npm test

# Watch mode
npm run test:watch

# Coverage
npm run test:coverage

# Data layer only
npm run test:data

# Health check
node test-data-access.js
```

## Environment Variables

```bash
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=gfsworkflow2025
CHROMADB_HOST=127.0.0.1
CHROMADB_PORT=8080
```

## Documentation

- **Full API Documentation**: `docs/DATA_ACCESS_LAYER.md`
- **Implementation Details**: `WEEK_1_COMPLETE.md`
- **This Reference**: `QUICK_REFERENCE.md`

## Common Patterns

### Pattern 1: Search with Context
```javascript
const results = await unified.hybridQuery(query, {
  collection: 'code_with_context',
  includeGraphContext: true,
  includeDependencies: true
});
```

### Pattern 2: Code Discovery
```javascript
const code = await unified.findCodeWithDependencies(identifier, {
  maxDepth: 2,
  includeSemanticSimilar: true
});
```

### Pattern 3: Multi-Collection Search
```javascript
const results = await unified.multiSourceSearch(query, {
  collections: ['code_with_context', 'docs', 'operational_docs'],
  enrichWithGraph: true
});
```

### Pattern 4: Execution Analysis
```javascript
const path = await unified.traceExecutionPath(functionName, {
  maxDepth: 3,
  includeCode: true
});
```

## Performance Tips

1. **Use connection pooling** (automatic)
2. **Batch operations** for multiple documents
3. **Cache frequently accessed data** (UnifiedDataAccess has built-in caching)
4. **Limit result counts** with `nResults` parameter
5. **Disable graph enrichment** when not needed: `includeGraphContext: false`

## Support

- GitHub Issue: [#363](https://github.com/TerrenceMcGuinness-NOAA/global-workflow/issues/363)
- Documentation: `docs/DATA_ACCESS_LAYER.md`
- Tests: `src/data/__tests__/`
