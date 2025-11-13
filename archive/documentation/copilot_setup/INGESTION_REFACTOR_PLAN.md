# Ingestion Refactor Plan - Hybrid ChromaDB + Neo4j Graph RAG

**Date**: October 15, 2025
**Status**: Planning Complete - Ready to Implement
**Goal**: Refactor ingestion pipeline to support dual-store architecture (ChromaDB for vectors + Neo4j for graph)

---

## Executive Summary

We're refactoring the existing ingestion scripts to populate **both** ChromaDB (vector embeddings for semantic search) and Neo4j (graph database for structural relationships). This enables the hybrid RAG architecture where:

- **ChromaDB** answers: "What code/docs are semantically similar to this error?"
- **Neo4j** answers: "What components depend on this? What breaks if I change X?"

---

## Current Architecture (What We Have)

### ✅ Infrastructure Status

| Component | Status | Version | Port |
|-----------|--------|---------|------|
| ChromaDB | ✅ Running | 1.1.1 | 8080 |
| Neo4j | ✅ Running | 5.15.0 | 7474/7687 |
| LangFlow | ✅ Running | Latest | 7860 |
| Node.js Client (chromadb) | ✅ Installed | 3.0.17 | N/A |
| Node.js Client (neo4j-driver) | ✅ Installed | 6.0.0 | N/A |

### 📂 Existing Ingestion Scripts

```
src/ingestion/
├── URLFetcher.js            ← Fetches external documentation
├── ContentExtractor.js      ← Extracts/cleans content from HTML/PDF/MD
└── DocumentationIngester.js ← Orchestrates URL-based doc ingestion
```

**Current Capabilities:**
- Fetch external documentation URLs
- Extract clean content from multiple formats (HTML, PDF, Markdown, JSON, XML)
- Semantic chunking with quality scoring
- Save to JSON files for ChromaDB ingestion

**Current Limitations:**
- No source code parsing
- No graph structure extraction
- No Neo4j integration
- No relationship mapping

---

## Target Architecture (Where We're Going)

### 🎯 Refactored Ingestion Pipeline

```
src/ingestion/
├── URLFetcher.js                   ← KEEP (works well)
├── ContentExtractor.js             ← KEEP (works well)
├── DocumentationIngester.js        ← KEEP (works well)
│
├── neo4j/                          ← NEW DIRECTORY
│   ├── Neo4jClient.js              ← Connection wrapper & query helpers
│   ├── GraphSchema.js              ← Schema definitions & constraints
│   ├── SubmoduleGraphIngester.js   ← Parse .gitmodules → Component nodes
│   ├── CMakeGraphIngester.js       ← Parse CMakeLists.txt → Dependencies
│   ├── CodeStructureIngester.js    ← Parse source → Functions/Classes
│   └── RelationshipBuilder.js      ← Build cross-graph relationships
│
├── HybridIngestionOrchestrator.js  ← NEW: Coordinates ChromaDB + Neo4j
└── IngestionStrategy.js            ← NEW: Decides what goes where
```

### 🔀 Data Flow

```
┌─────────────────────────────────────────────────────────┐
│ Source Code & Documentation                             │
│  • .gitmodules files                                    │
│  • CMakeLists.txt files                                 │
│  • Python/Fortran/C++ source files                      │
│  • README.md documentation                              │
│  • External URL documentation                           │
└──────────────────┬──────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────┐
│ HybridIngestionOrchestrator                             │
│  Decides what data goes to which store                  │
└─────────┬──────────────────────────┬────────────────────┘
          │                          │
          ▼                          ▼
┌──────────────────────┐   ┌──────────────────────┐
│ ChromaDB Pipeline    │   │ Neo4j Pipeline       │
│                      │   │                      │
│ ContentExtractor     │   │ SubmoduleIngester    │
│ └─> Semantic chunks  │   │ └─> Component nodes  │
│                      │   │                      │
│ DocumentationIngester│   │ CMakeIngester        │
│ └─> Doc embeddings   │   │ └─> DEPENDS_ON edges │
│                      │   │                      │
│ Code text embeddings │   │ CodeStructureIngester│
│                      │   │ └─> Function nodes   │
│                      │   │ └─> CALLS edges      │
└──────────┬───────────┘   └──────────┬───────────┘
           │                          │
           ▼                          ▼
    ┌─────────────┐            ┌─────────────┐
    │  ChromaDB   │            │   Neo4j     │
    │   Vectors   │            │   Graph     │
    └─────────────┘            └─────────────┘
```

---

## Implementation Phases

### Phase 0: Foundation (CURRENT - Start Here) ⭐

**Goal**: Create Neo4j infrastructure and test basic graph ingestion
**Duration**: 2-3 hours
**Complexity**: Low
**Risk**: Low

**Deliverables:**
1. ✅ Neo4j connection test script (`test-neo4j-connection.js`) - DONE
2. 🔲 `src/ingestion/neo4j/Neo4jClient.js` - Connection wrapper
3. 🔲 `src/ingestion/neo4j/GraphSchema.js` - Schema definition
4. 🔲 `src/ingestion/neo4j/SubmoduleGraphIngester.js` - First real ingestion
5. 🔲 Demo query script showing dependency graph

**Clear Ending Point**: Can visualize all 50+ submodules in Neo4j Browser with DEPENDS_ON relationships

**Why Start Here**:
- Self-contained module (doesn't touch existing code)
- Quick win (can see results in <3 hours)
- Validates approach before larger refactor
- Can abort easily if issues arise

---

### Phase 1: Core Graph Infrastructure (Next)

**Goal**: Complete Neo4j ingestion infrastructure
**Duration**: 1 week
**Complexity**: Medium
**Deliverables:**

1. `CMakeGraphIngester.js` - Parse CMake dependency declarations
2. `CodeStructureIngester.js` - Extract function/class structure
3. `RelationshipBuilder.js` - Cross-link nodes
4. Schema constraints and indexes

**Clear Ending Point**: Can answer "What depends on component X?" and "Show call graph for function Y"

---

### Phase 2: Hybrid Orchestration

**Goal**: Coordinate ChromaDB + Neo4j ingestion
**Duration**: 3-4 days
**Complexity**: Medium
**Deliverables:**

1. `HybridIngestionOrchestrator.js` - Dual-store coordinator
2. `IngestionStrategy.js` - Decision logic for data routing
3. Update existing ingesters to work with orchestrator
4. Integration tests

**Clear Ending Point**: Single command ingests to both stores simultaneously

---

### Phase 3: Enhanced RAG Query Integration

**Goal**: Update RAGTools to query both stores
**Duration**: 1 week
**Complexity**: High
**Deliverables:**

1. `src/tools/HybridRAGTools.js` - Query orchestrator
2. Update `src/tools/RAGTools.js` to use hybrid queries
3. Graph-aware error analysis
4. Dependency impact analysis tools

**Clear Ending Point**: Can answer hybrid queries like "Show similar errors AND affected components"

---

## Phase 0 Detailed Implementation (START HERE)

This is our **next big step** with a clear ending point.

### File 1: `src/ingestion/neo4j/Neo4jClient.js`

**Purpose**: Reusable Neo4j connection manager
**Lines of Code**: ~150
**Complexity**: Low

```javascript
/**
 * Neo4jClient - Connection wrapper for Neo4j database
 *
 * Provides:
 * - Connection pooling
 * - Query execution helpers
 * - Transaction management
 * - Error handling
 */
export class Neo4jClient {
  constructor(config = {}) {
    this.uri = config.uri || process.env.NEO4J_URI || 'bolt://127.0.0.1:7687';
    this.user = config.user || process.env.NEO4J_USER || 'neo4j';
    this.password = config.password || process.env.NEO4J_PASSWORD || 'gfsworkflow2025';
    this.driver = null;
  }

  async connect() { /* ... */ }
  async disconnect() { /* ... */ }
  async runQuery(cypher, params) { /* ... */ }
  async runTransaction(queries) { /* ... */ }
  async getStats() { /* ... */ }
}
```

### File 2: `src/ingestion/neo4j/GraphSchema.js`

**Purpose**: Define all node types, relationships, and constraints
**Lines of Code**: ~200
**Complexity**: Low

```javascript
/**
 * GraphSchema - Neo4j schema definitions
 *
 * Defines:
 * - Node labels and properties
 * - Relationship types
 * - Constraints and indexes
 */
export const SCHEMA = {
  nodes: {
    Component: {
      label: 'Component',
      properties: {
        name: 'STRING',
        path: 'STRING',
        language: 'STRING',
        description: 'STRING',
        loc: 'INTEGER'
      },
      indexes: ['name', 'path']
    },
    // ... more node types
  },
  relationships: {
    DEPENDS_ON: {
      type: 'DEPENDS_ON',
      properties: {
        version: 'STRING',
        type: 'STRING'
      }
    },
    // ... more relationship types
  }
};

export async function applySchema(client) { /* ... */ }
```

### File 3: `src/ingestion/neo4j/SubmoduleGraphIngester.js`

**Purpose**: Parse .gitmodules and create Component nodes
**Lines of Code**: ~250
**Complexity**: Medium

```javascript
/**
 * SubmoduleGraphIngester - Git submodule structure ingestion
 *
 * Parses:
 * - .gitmodules files (recursive)
 * - Creates Component nodes
 * - Creates CONTAINS relationships
 * - Extracts basic metadata
 */
export class SubmoduleGraphIngester {
  constructor(neo4jClient) {
    this.client = neo4jClient;
    this.stats = { componentsCreated: 0, relationshipsCreated: 0 };
  }

  async ingestRepositoryStructure(repoPath) {
    // 1. Find all .gitmodules files
    // 2. Parse each file
    // 3. Create Component nodes
    // 4. Create CONTAINS relationships
    // 5. Return stats
  }

  async parseGitmodulesFile(filePath) { /* ... */ }
  async createComponentNode(componentData) { /* ... */ }
  async createContainsRelationship(parent, child) { /* ... */ }
}
```

### File 4: Demo Query Script

**Purpose**: Prove value with visualizations
**File**: `scripts/demo-graph-queries.js`

```javascript
// Demo Query 1: Show all components
const allComponents = await client.runQuery(`
  MATCH (c:Component)
  RETURN c.name, c.path, c.language
  ORDER BY c.name
`);

// Demo Query 2: Show dependency tree
const depTree = await client.runQuery(`
  MATCH path = (root:Component)-[:CONTAINS*]->(child:Component)
  WHERE root.name = 'global-workflow'
  RETURN path
  LIMIT 100
`);

// Demo Query 3: Find components with most dependencies
const topDeps = await client.runQuery(`
  MATCH (c:Component)-[:DEPENDS_ON]->(dep:Component)
  WITH c, COUNT(dep) as depCount
  ORDER BY depCount DESC
  LIMIT 10
  RETURN c.name, depCount
`);
```

---

## Success Criteria for Phase 0

At the end of Phase 0, we must be able to:

1. ✅ Connect to Neo4j from Node.js (DONE - test-neo4j-connection.js passes)
2. 🎯 Run `node scripts/ingest-submodules.js` and see:
   - 50+ Component nodes created
   - CONTAINS relationships showing submodule hierarchy
   - No errors
3. 🎯 Open Neo4j Browser (http://localhost:7474) and visualize:
   - Full component graph
   - Dependency chains
   - Submodule structure
4. 🎯 Run demo queries successfully:
   - List all components
   - Show dependency tree from root
   - Find most-depended-on components

**Time Estimate**: 2-3 hours
**Risk**: Low (isolated, can delete if fails)
**Decision Gate**: If visualization impresses → Continue to Phase 1, otherwise re-evaluate

---

## Next Immediate Actions

### Now (This Session)
1. ✅ Create `INGESTION_REFACTOR_PLAN.md` (this document) - DONE
2. 🔲 Create `src/ingestion/neo4j/` directory
3. 🔲 Implement `Neo4jClient.js`
4. 🔲 Implement `GraphSchema.js`
5. 🔲 Implement `SubmoduleGraphIngester.js`
6. 🔲 Create demo query script
7. 🔲 Test full pipeline

### After Phase 0 (Next Session)
- Review results
- Decision: Continue or pivot?
- If continue → Start Phase 1 (CMake ingestion)

---

## Benefits of This Approach

### ✅ Low Risk
- Phase 0 is isolated (doesn't touch existing code)
- Can abort with `sudo docker stop global-workflow-neo4j`
- No impact on ChromaDB ingestion

### ✅ Quick Validation
- See results in <3 hours
- Visual feedback in Neo4j Browser
- Clear success/failure criteria

### ✅ Clear Scope
- Well-defined ending point
- Measurable deliverables
- Easy to demonstrate value

### ✅ Foundation for Future
- Neo4jClient reusable across all phases
- GraphSchema defines entire data model
- Patterns established for other ingesters

---

## Files to Create in Phase 0

1. `src/ingestion/neo4j/Neo4jClient.js` (150 lines)
2. `src/ingestion/neo4j/GraphSchema.js` (200 lines)
3. `src/ingestion/neo4j/SubmoduleGraphIngester.js` (250 lines)
4. `scripts/ingest-submodules.js` (100 lines - CLI runner)
5. `scripts/demo-graph-queries.js` (150 lines - demo queries)

**Total**: ~850 lines of code
**Time**: 2-3 hours
**Complexity**: Low-Medium

---

## Conclusion

**Recommendation**: Proceed with Phase 0 implementation immediately.

This is the perfect next step because:
- Infrastructure is ready (Neo4j running, drivers installed)
- Clear scope and ending point
- Low risk, high value
- Quick feedback loop
- Establishes patterns for future work

**Starting Point**: Create `src/ingestion/neo4j/Neo4jClient.js`
**Ending Point**: Can visualize 50+ components in Neo4j Browser
**Decision Gate**: Review visualization → Continue or Pivot

---

**Status**: Ready to begin Phase 0 implementation
**Next File to Create**: `src/ingestion/neo4j/Neo4jClient.js`
**Estimated Completion**: 2-3 hours from start
**Updated**: October 15, 2025
