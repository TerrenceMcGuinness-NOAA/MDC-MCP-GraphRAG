# SDD: Phase 24E - Hierarchical Community Summarization

**Version:** 2.1.0  
**Created:** 2026-02-05  
**Updated:** 2026-02-25  
**Author:** AI Assistant + Terry McGuinness  
**Status:** IN PROGRESS — 24E-1/2/3/5 COMPLETE (hierarchy materialized, template summaries); 24E-4 superseded by 24E-7; **24E-6 SCRIPTS IMPLEMENTED** (pipeline scripts committed, awaiting batch execution via GitHub CLI); **24E-7 PLANNED** (staleness propagation, unifying deferred 24E-4 with 24H-3 `_dirty` infrastructure)  
**Dependency:** Phase 24A-D (Graph-Guided Speculative Retrieval)

> **📋 MASTER REFERENCE:** [phase24_consolidated_architecture.md](phase24_consolidated_architecture.md)

---

## 1. Executive Summary

Phase 24 establishes Graph-Guided Speculative Retrieval for **local queries** ("How does config.resources work?"). This phase extends the architecture to handle **global queries** ("What's the overall error handling strategy?") through hierarchical community detection and LLM-generated summaries.

### The GraphRAG Completion

| Query Type | Phase 24A-D | Phase 24E |
|------------|-------------|-----------|
| Local | ✅ Node neighborhood traversal | Enhanced with community context |
| Global | ❌ No single node contains answer | ✅ Community summaries enable holistic answers |

### Key Innovation

Transform the flat node graph into a **hierarchical knowledge structure** where communities at each level have LLM-generated summaries that capture emergent patterns invisible at the individual node level.

---

## 2. Problem Statement

### The Global Query Gap

```
User: "What are the main architectural patterns in this codebase?"

Current System (Phase 24A-D):
- Extracts entities: "architectural", "patterns", "codebase"
- Finds nodes matching these terms: possibly some docs, maybe architecture.md
- Returns fragmented results that don't synthesize the whole

Needed:
- Pre-computed summaries that describe subsystem purposes
- Hierarchical rollups: functions → modules → subsystems → architecture
- Single retrieval that answers holistic questions
```

### Why Node-Level RAG Fails for Global Queries

Consider asking "How does error handling work across this system?"

- Error handling code is distributed across 50+ files
- No single file describes the strategy
- Keyword search returns fragments without synthesis
- User must manually piece together the pattern

**Solution:** Pre-compute community summaries that capture cross-cutting concerns.

---

## 3. Technical Architecture

### 3.1 Community Hierarchy Levels

```
Level 3: Architecture Layer
         ┌─────────────────────────────────────────────────┐
         │ "The forecast system comprises four major       │
         │  subsystems: configuration, execution,          │
         │  post-processing, and validation..."            │
         └─────────────────────────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
Level 2: Subsystem
    ┌─────────┐        ┌─────────────┐      ┌──────────┐
    │ Config  │        │ Execution   │      │ PostProc │
    │ Subsys  │        │ Subsystem   │      │ Subsys   │
    └─────────┘        └─────────────┘      └──────────┘
         │                    │                    │
    ┌────┴────┐          ┌───┴───┐           ┌───┴───┐
    ▼         ▼          ▼       ▼           ▼       ▼
Level 1: Module
 ┌──────┐ ┌──────┐  ┌──────┐ ┌──────┐  ┌──────┐ ┌──────┐
 │config│ │ env/ │  │ jobs/│ │ ex/  │  │ post/│ │ vrfy/│
 │ parm │ │      │  │      │ │      │  │      │ │      │
 └──────┘ └──────┘  └──────┘ └──────┘  └──────┘ └──────┘
    │         │         │        │         │        │
    ▼         ▼         ▼        ▼         ▼        ▼
Level 0: Individual Files/Functions (existing nodes)
```

### 3.2 Neo4j Schema Extension

```cypher
// New node type for community summaries
CREATE CONSTRAINT community_id IF NOT EXISTS
FOR (c:Community) REQUIRE c.id IS UNIQUE;

// Community node properties
(:Community {
  id: "community_L2_config_subsystem",
  level: 2,
  name: "Configuration Subsystem",
  summary: "This subsystem manages computational resource...",
  summary_embedding: [0.123, -0.456, ...],  // For semantic search
  member_count: 47,
  key_entities: ["config.resources", "env/HERA.env", ...],
  cross_cutting_concerns: ["error_handling", "logging"],
  created_at: datetime(),
  updated_at: datetime(),
  stale: false
})

// Hierarchical relationships
(:Community)-[:CONTAINS]->(:File|:Function|:Community)
(:Community)-[:PARENT_OF]->(:Community)
(:Community)-[:INTERACTS_WITH {
  interaction_type: "data_flow" | "control_flow" | "config",
  strength: 0.8
}]->(:Community)

// Link nodes to their community membership
(:File)-[:MEMBER_OF]->(:Community)
(:Function)-[:MEMBER_OF]->(:Community)
```

### 3.3 Community Detection Pipeline

```
┌─────────────────────────────────────────────────────────┐
│  Step 1: Project Graph for Community Detection          │
│  (Filter to structural relationships only)              │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│  Step 2: Run Hierarchical Community Detection           │
│  Neo4j GDS: Louvain or Leiden algorithm                 │
│  Output: communityId at multiple resolutions            │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│  Step 3: Extract Community Members                      │
│  Group nodes by communityId at each level               │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│  Step 4: Generate Community Summaries (LLM)             │
│  Bottom-up: L0 → L1 → L2 → L3                          │
│  Input: member nodes, relationships, child summaries    │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│  Step 5: Embed Summaries for Semantic Search            │
│  Store in Neo4j + mirror to ChromaDB collection         │
└─────────────────────┬───────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│  Step 6: Compute Inter-Community Relationships          │
│  Aggregate member relationships to community level      │
└─────────────────────────────────────────────────────────┘
```

### 3.4 Neo4j GDS Implementation

**Step 1: Create Graph Projection**
```cypher
CALL gds.graph.project(
  'codeGraph',
  ['File', 'Function', 'Module'],
  {
    CALLS: { orientation: 'UNDIRECTED' },
    IMPORTS: { orientation: 'UNDIRECTED' },
    SOURCES: { orientation: 'UNDIRECTED' },
    DEPENDS_ON: { orientation: 'UNDIRECTED' },
    CONTAINS: { orientation: 'UNDIRECTED' }
  }
)
```

**Step 2: Run Leiden Algorithm (preferred over Louvain)**
```cypher
CALL gds.leiden.stream('codeGraph', {
  maxLevels: 4,
  gamma: 1.0,
  theta: 0.01,
  includeIntermediateCommunities: true
})
YIELD nodeId, communityId, intermediateCommunityIds
WITH gds.util.asNode(nodeId) AS node, 
     communityId AS level3,
     intermediateCommunityIds[0] AS level1,
     intermediateCommunityIds[1] AS level2
RETURN node.path, level1, level2, level3
```

**Step 3: Create Community Nodes**
```cypher
// Aggregate nodes into communities at each level
MATCH (n:File)
WHERE n.communityL1 IS NOT NULL
WITH n.communityL1 AS cid, collect(n) AS members
MERGE (c:Community {id: 'L1_' + toString(cid), level: 1})
SET c.member_count = size(members),
    c.key_entities = [m IN members | m.name][0..10]
WITH c, members
UNWIND members AS m
MERGE (m)-[:MEMBER_OF]->(c)
```

### 3.5 Summary Generation Prompt

```javascript
const COMMUNITY_SUMMARY_PROMPT = `
You are analyzing a code community (cluster of related code files/functions).

## Community Members
{{member_list}}

## Key Relationships Within Community
{{internal_relationships}}

## Relationships to Other Communities  
{{external_relationships}}

## Child Community Summaries (if Level > 1)
{{child_summaries}}

## Task
Generate a technical summary of this code community that captures:

1. **Purpose**: What is the primary responsibility of this code cluster?
2. **Key Components**: What are the 3-5 most important files/functions?
3. **Data Flow**: How does data move through this community?
4. **External Interfaces**: How does this community interact with others?
5. **Cross-Cutting Concerns**: What patterns (error handling, logging, etc.) are present?

Keep the summary under 300 words. Be specific and technical.
Focus on information that would help a developer understand this subsystem.
`;
```

### 3.6 Dual Retrieval Router

```javascript
class DualRetrievalRouter {
  constructor(ggsr, communityIndex) {
    this.ggsr = ggsr;  // Phase 24A-D GraphGuidedRetrieval
    this.communityIndex = communityIndex;
  }

  async route(query) {
    const queryType = await this.classifyQuery(query);
    
    if (queryType === 'LOCAL') {
      // Existing Phase 24 path + community context enrichment
      const localResults = await this.ggsr.retrieve(query);
      const communityContext = await this.getCommunitySummary(
        localResults.primaryResults[0]
      );
      return {
        ...localResults,
        communityContext: communityContext
      };
    } 
    else if (queryType === 'GLOBAL') {
      // New community-based retrieval
      return await this.globalRetrieval(query);
    }
    else {
      // HYBRID: Both paths
      const [local, global] = await Promise.all([
        this.ggsr.retrieve(query),
        this.globalRetrieval(query)
      ]);
      return this.mergeResults(local, global);
    }
  }

  async classifyQuery(query) {
    // Heuristics + optional LLM classification
    const globalSignals = [
      /overall|architecture|pattern|strategy|approach/i,
      /how does .* work across/i,
      /what are the main|major|key/i,
      /summary|overview|explain the system/i
    ];
    
    const localSignals = [
      /specific file|function|class|method/i,
      /how does \w+\.\w+ work/i,  // specific symbol
      /where is .* defined|called|used/i
    ];

    const globalScore = globalSignals.filter(r => r.test(query)).length;
    const localScore = localSignals.filter(r => r.test(query)).length;

    if (globalScore > localScore + 1) return 'GLOBAL';
    if (localScore > globalScore + 1) return 'LOCAL';
    return 'HYBRID';
  }

  async globalRetrieval(query) {
    // 1. Embed query
    const queryEmbedding = await this.embed(query);
    
    // 2. Search community summaries (semantic)
    const relevantCommunities = await this.searchCommunitySummaries(
      queryEmbedding,
      { levels: [2, 3], limit: 5 }  // Prefer higher-level summaries
    );
    
    // 3. Optionally drill down to Level 1 for specifics
    const enrichedCommunities = await this.enrichWithChildren(
      relevantCommunities
    );
    
    // 4. Assemble context
    return {
      summaries: enrichedCommunities.map(c => c.summary),
      graphContext: this.buildCommunityGraph(enrichedCommunities),
      tokensUsed: this.countTokens(enrichedCommunities)
    };
  }
}
```

---

## 4. Implementation Phases

### Phase 24E-1: Community Detection (Week 1-2)

**Objective:** Run Leiden algorithm on existing graph, validate community structure

**Steps:**
- [x] Install/enable Neo4j GDS plugin (GDS 2.13.7, Neo4j 5.26.20-community)
- [x] Create graph projection with appropriate relationships (9 labels, 10 rel types → 25,352 nodes, 958,660 rels)
- [x] Run Leiden community detection (3,841 communities, modularity 0.8184)
- [x] **RESOLVED (24E-5, v7.20.0):** Leiden re-run with `includeIntermediateCommunities: true`. 25,377 nodes now have `communityLevels` array property. 4 hierarchical levels materialized.
- [x] Validate: Do communities align with intuitive code boundaries? (size distribution: 3,767 singleton, 17 size 2-3, 16 size 200+)
- [x] Store community assignments as node properties (`communityId` written to all 25,352 nodes)

**Validation Query:**
```cypher
// Check if communities respect directory structure
MATCH (f:File)-[:MEMBER_OF]->(c:Community {level: 1})
WITH c, collect(DISTINCT split(f.path, '/')[0]) AS topDirs
RETURN c.id, topDirs, size(topDirs) AS dirDiversity
ORDER BY dirDiversity DESC
LIMIT 20
// Expect: Most L1 communities span 1-3 top directories
```

**Success Criteria:**
- Communities detected at 3+ levels
- >70% of L1 communities map to single directory trees
- No community exceeds 500 members (manageable for summarization)

### Phase 24E-2: Summary Generation Pipeline (Week 3-4)

**Objective:** Generate LLM summaries bottom-up

**Steps:**
- [x] Implement summary generation prompt (§3.5) — template-based with 16 keyword patterns for purpose inference
- [x] Build summary pipeline: `CommunitySummarizer.summarizeAll()` processes communities with 3+ members
- [x] **RESOLVED (24E-5, v7.20.0):** 1,036 Community nodes created (L0:694, L1:175, L2:86, L3:81). 21,559 MEMBER_OF, 978 PARENT_OF, 1,297 INTERACTS_WITH. 828 summaries in Neo4j + ChromaDB. `retrieveGlobal()` updated with level-aware drill-down.
- [ ] **GAP:** Bottom-up L1→L2→L3 summarization not done (no hierarchy). All 63 summaries are flat/leaf-level.
- [x] Embed summaries and store vectors — `Xenova/all-mpnet-base-v2` embeddings, batch upsert
- [x] Create ChromaDB collection `community-summaries` — 63 summaries, 2 batches (50+13)

**Pipeline Script:**
```javascript
async function generateAllSummaries(neo4j, llm, embedder) {
  // Process bottom-up
  for (const level of [1, 2, 3]) {
    const communities = await neo4j.query(`
      MATCH (c:Community {level: $level})
      WHERE c.summary IS NULL
      RETURN c
    `, { level });
    
    for (const community of communities) {
      const context = await gatherCommunityContext(neo4j, community);
      const summary = await llm.generate(COMMUNITY_SUMMARY_PROMPT, context);
      const embedding = await embedder.embed(summary);
      
      await neo4j.query(`
        MATCH (c:Community {id: $id})
        SET c.summary = $summary,
            c.summary_embedding = $embedding,
            c.updated_at = datetime()
      `, { id: community.id, summary, embedding });
    }
  }
}
```

**Success Criteria:**
- All communities have summaries
- Summaries are <300 words
- L3 summaries reference L2 child summaries coherently

### Phase 24E-3: Dual Retrieval Integration (Week 5-6)

**Objective:** Integrate community retrieval with Phase 24D MCP

**Steps:**
- [x] Implement DualRetrievalRouter (§3.6) — `classifyQuery()` in GraphGuidedRetrieval
- [x] Add query classification logic — LOCAL | GLOBAL | TRACE | HYBRID routing
- [x] Create `search_architecture` MCP tool for global queries — in GraphRAGTools.js (Phase 24H)
- [x] Modify `search_documentation` to include community context — communitySection in results
- [x] A/B test: With vs without community summaries — Phase 24G benchmark: 60% hit rate (+20pp vs baseline)

**New MCP Tools:**
```javascript
// Tool: search_architecture
{
  name: "search_architecture",
  description: "Answer high-level questions about codebase architecture, patterns, and subsystems",
  parameters: {
    query: { type: "string", description: "Architectural question" },
    depth: { type: "number", description: "Community level (1-3)", default: 2 }
  }
}

// Tool: get_subsystem_summary  
{
  name: "get_subsystem_summary",
  description: "Get summary of a specific code subsystem/community",
  parameters: {
    subsystem: { type: "string", description: "Subsystem name or path prefix" }
  }
}
```

**Success Criteria:**
- Query router correctly classifies >80% of test queries
- Global queries return relevant community summaries
- Response latency <1s for community retrieval

### Phase 24E-4: Incremental Update Pipeline (SUPERSEDED by 24E-7)

**Status:** SUPERSEDED — Original scope (file-level dirty tracking, staleness propagation, incremental re-clustering) has been reorganized. File-level dirty tracking was partially delivered in Phase 24H-3 (`mark_as_modified` sets `_dirty` on Neo4j nodes). The remaining work (staleness propagation to Community nodes, selective re-summarization) is now captured in **24E-7** below, which also integrates the new LLM summary pipeline from 24E-6.

**Original Steps (for reference):**
- [x] Implement file-level dirty tracking — **Partial (24H-3)**: `mark_as_modified` sets `n._dirty = true` on Neo4j nodes
- [ ] ~~Define staleness propagation rules~~ → moved to 24E-7
- [ ] ~~Build incremental re-clustering for small changes~~ → moved to 24E-7
- [ ] ~~Build full re-clustering trigger for large changes~~ → moved to 24E-7
- [ ] ~~Implement summary invalidation cascade~~ → moved to 24E-7

**Staleness Rules:**
```javascript
const STALENESS_RULES = {
  // When a file changes:
  FILE_CHANGED: {
    invalidate: ['L1_community'],  // Direct parent
    mark_stale: ['L2_community', 'L3_community'],  // Ancestors
    threshold: 0.2  // If >20% of L1 members change, invalidate L1
  },
  
  // When a relationship changes:
  RELATIONSHIP_CHANGED: {
    invalidate: [],
    mark_stale: ['L1_community'],
    recompute_on: 10  // Recompute community structure after 10 rel changes
  }
};
```

**Incremental Update Query:**
```cypher
// Mark communities stale when members change
MATCH (f:File {dirty: true})-[:MEMBER_OF]->(c:Community)
SET c.stale = true
WITH c
MATCH (c)<-[:PARENT_OF*]-(ancestor:Community)
SET ancestor.stale = true
```

**Success Criteria:**
- File change triggers summary staleness in <100ms
- Incremental summary regeneration completes in <30s
- Full re-clustering needed only for >10% codebase changes

### Phase 24E-5: Community Node Materialization & Hierarchical Structure

**Objective:** Create the full hierarchical community structure in Neo4j as first-class graph entities, enabling drill-down queries, inter-community impact analysis, and multi-resolution understanding of the Global Workflow architecture.

**Motivation:** The Global Workflow is one of the most complex computational pipelines on Earth — modeling the planet's atmosphere, ocean, sea ice, land surface, and chemistry across multiple coupled models (FV3, MOM6, CICE, WW3, GOCART). Understanding how these subsystems interact at different levels of abstraction is essential for the developers evolving this infrastructure. Flat `communityId` properties are insufficient; the system needs navigable hierarchical communities as first-class graph entities.

**Status:** ✅ COMPLETE (v7.20.0, commit 27ad4e5, February 24, 2026)

**Prerequisites:**
- Neo4j GDS 2.13+ (available: v2.13.7)
- Existing `communityId` property on 25,352 nodes (3,841 communities)
- ChromaDB `community-summaries` collection (63 docs)

**Steps:**

#### Step 1: Re-run Leiden with Hierarchical Levels

Re-run community detection with `includeIntermediateCommunities: true` to capture the full hierarchy. Write intermediate community IDs as separate properties.

```javascript
// In CommunityDetection.js — new method: runHierarchicalLeiden()
async runHierarchicalLeiden({ maxLevels = 5, gamma = 1.0 } = {}) {
  // GDS Leiden with intermediate communities produces an array of
  // community assignments at each hierarchical level per node.
  //
  // Strategy: Use gds.leiden.stream (not .write) to get
  // intermediateCommunityIds, then write each level explicitly.
  const cypher = `
    CALL gds.leiden.stream('${GRAPH_NAME}', {
      maxLevels: ${maxLevels},
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
  return this._writeQuery(cypher);
}
```

**Validation**: Confirm `maxDepth >= 3` and `nodesUpdated = 25,352`.

**GDS Note**: The `gds.leiden.stream` returns `intermediateCommunityIds` as a list where index 0 is the finest (Level 0) and higher indices are coarser. The final `communityId` is the coarsest level.

#### Step 2: Create Community Label Nodes

Materialize each distinct community at each level as a `(:Community)` node.

```cypher
// For each level in the hierarchy, create Community nodes
// Level detection from node.communityLevels array
UNWIND range(0, 4) AS levelIdx
MATCH (n)
WHERE n.communityLevels IS NOT NULL
  AND size(n.communityLevels) > levelIdx
WITH levelIdx, n.communityLevels[levelIdx] AS cid, collect(n) AS members
WITH levelIdx, cid, members, size(members) AS memberCount
WHERE memberCount >= 2  // Skip singletons
MERGE (c:Community {communityId: cid, level: levelIdx})
SET c.memberCount = memberCount,
    c.createdAt = datetime(),
    c.name = 'Community_L' + toString(levelIdx) + '_' + toString(cid)
```

**Expected output**: ~200-500 Community nodes across 3-5 levels (most of the 3,841 are singletons at Level 0).

**Constraint**: Add uniqueness constraint:
```cypher
CREATE CONSTRAINT community_unique IF NOT EXISTS
FOR (c:Community) REQUIRE (c.communityId, c.level) IS UNIQUE
```

#### Step 3: Create MEMBER_OF Relationships

Link code nodes to their leaf-level (L0) community.

```cypher
MATCH (n)
WHERE n.communityLevels IS NOT NULL
WITH n, n.communityLevels[0] AS leafCid
MATCH (c:Community {communityId: leafCid, level: 0})
MERGE (n)-[:MEMBER_OF]->(c)
```

**Expected**: ~22,000+ MEMBER_OF relationships (25,352 minus singletons).

#### Step 4: Create PARENT_OF Hierarchy

Link communities across levels.

```cypher
// For each node, its community at level N is a child of its community at level N+1
MATCH (n)
WHERE n.communityLevels IS NOT NULL AND size(n.communityLevels) >= 2
UNWIND range(0, size(n.communityLevels) - 2) AS idx
WITH DISTINCT n.communityLevels[idx] AS childCid, idx AS childLevel,
     n.communityLevels[idx + 1] AS parentCid, idx + 1 AS parentLevel
MATCH (child:Community {communityId: childCid, level: childLevel})
MATCH (parent:Community {communityId: parentCid, level: parentLevel})
MERGE (parent)-[:PARENT_OF]->(child)
```

**Expected**: ~100-300 PARENT_OF edges forming a tree.

#### Step 5: Compute INTERACTS_WITH Between Communities

Aggregate cross-community edges into inter-community interaction relationships.

```cypher
// At each level, find communities that interact via member edges
UNWIND range(0, 4) AS levelIdx
MATCH (a)-[r]->(b)
WHERE a.communityLevels IS NOT NULL AND b.communityLevels IS NOT NULL
  AND size(a.communityLevels) > levelIdx
  AND size(b.communityLevels) > levelIdx
  AND a.communityLevels[levelIdx] <> b.communityLevels[levelIdx]
WITH levelIdx,
     a.communityLevels[levelIdx] AS aCid,
     b.communityLevels[levelIdx] AS bCid,
     type(r) AS relType,
     count(*) AS strength
WHERE strength >= 3  // Significant interactions only
MATCH (ca:Community {communityId: aCid, level: levelIdx})
MATCH (cb:Community {communityId: bCid, level: levelIdx})
MERGE (ca)-[ix:INTERACTS_WITH]->(cb)
SET ix.strength = strength,
    ix.relTypes = collect(DISTINCT relType),
    ix.level = levelIdx
```

**Expected**: ~50-200 INTERACTS_WITH edges at each level. These are the subsystem boundaries.

#### Step 6: Enrich Community Nodes with Metadata

Add language breakdown, dominant purpose, and key member names.

```cypher
MATCH (c:Community)<-[:MEMBER_OF]-(n)
WITH c, labels(n) AS nlabels, n.name AS nname
WITH c,
     collect(DISTINCT CASE
       WHEN 'FortranSubroutine' IN nlabels OR 'FortranFunction' IN nlabels THEN 'Fortran'
       WHEN 'PythonFunction' IN nlabels OR 'PythonModule' IN nlabels THEN 'Python'
       WHEN 'ShellScript' IN nlabels OR 'File' IN nlabels THEN 'Shell'
       ELSE 'Other'
     END) AS languages,
     collect(nname)[0..10] AS keyMembers,
     count(n) AS size
SET c.languages = languages,
    c.keyMembers = keyMembers,
    c.memberCount = size
```

#### Step 7: Re-generate Hierarchical Summaries

Update `CommunitySummarizer` to generate summaries bottom-up: L0 → L1 → L2 → top.

Higher-level summaries should reference their child summaries, not raw members. Update the ChromaDB `community-summaries` collection with richer, level-aware summaries.

```javascript
// In CommunitySummarizer.js — new method: summarizeHierarchical()
async summarizeHierarchical() {
  // Get max depth
  const maxLevel = await this.cd.getMaxCommunityLevel();

  for (let level = 0; level <= maxLevel; level++) {
    const communities = await this.cd.getCommunitiesAtLevel(level);

    for (const c of communities) {
      let summary;
      if (level === 0) {
        // Leaf: summarize from raw member nodes + internal relationships
        const members = await this.cd.getCommunityMembers(c.communityId);
        const rels = await this.cd.getCommunityRelationships(c.communityId);
        summary = this.generateSummary(c.communityId, members, rels);
      } else {
        // Parent: summarize from child community summaries + inter-community interactions
        const children = await this.cd.getChildCommunities(c.communityId, level);
        const interactions = await this.cd.getCommunityInteractions(c.communityId, level);
        summary = this.generateParentSummary(c.communityId, children, interactions);
      }

      // Write summary to Neo4j Community node
      await this.cd._writeQuery(
        'MATCH (c:Community {communityId: $cid, level: $level}) SET c.summary = $summary',
        { cid: c.communityId, level, summary }
      );

      // Also upsert to ChromaDB for semantic search
      documents.push({
        id: `community-L${level}-${c.communityId}`,
        text: summary,
        metadata: { communityId: c.communityId, level, size: c.memberCount }
      });
    }
  }
  // Batch store in ChromaDB (replace existing collection)
  await this.vectorDB.deleteCollection('community-summaries');
  await this.vectorDB.getOrCreateCollection('community-summaries');
  await this.vectorDB.addDocuments('community-summaries', documents);
}
```

#### Step 8: Wire Into GraphGuidedRetrieval

Update `GraphGuidedRetrieval.retrieveGlobal()` to:
- Search community summaries with level preference (query Level 2-3 first for global, Level 0-1 for local)
- Drill down: when a high-level community matches, fetch its children for detail
- Include `INTERACTS_WITH` edges in results to show subsystem boundaries

```javascript
// In GraphGuidedRetrieval.js — updated retrieveGlobal()
async retrieveGlobal(query, nResults = 5) {
  // 1. Search community summaries (prefer higher levels for global)
  const results = await this.vectorDB.query('community-summaries', query, {
    nResults: nResults * 2,
    where: { level: { $gte: 1 } },  // Prefer level 1+
    include: ['documents', 'metadatas', 'distances']
  });

  // 2. For top matches, drill down to children
  const enriched = [];
  for (const r of results.slice(0, nResults)) {
    const children = await this.graphDB.query(`
      MATCH (c:Community {communityId: $cid, level: $level})-[:PARENT_OF]->(child:Community)
      RETURN child.name, child.summary, child.memberCount
      ORDER BY child.memberCount DESC LIMIT 5
    `, { cid: r.metadata.communityId, level: r.metadata.level });

    const interactions = await this.graphDB.query(`
      MATCH (c:Community {communityId: $cid, level: $level})-[ix:INTERACTS_WITH]->(other:Community)
      RETURN other.name, ix.strength, ix.relTypes
      ORDER BY ix.strength DESC LIMIT 5
    `, { cid: r.metadata.communityId, level: r.metadata.level });

    enriched.push({ ...r, children, interactions });
  }

  // 3. Format as markdown context
  return this.formatCommunityContext(enriched);
}
```

#### Step 9: Update Pipeline Script

Extend `run_community_detection.js` to orchestrate the full pipeline:
1. Project graph → 2. Hierarchical Leiden → 3. Create Community nodes → 4. MEMBER_OF → 5. PARENT_OF → 6. INTERACTS_WITH → 7. Metadata enrichment → 8. Hierarchical summaries

Add `--materialize` flag to the script for backward compatibility.

#### Step 10: Validation & Tests

- **Unit test**: Community nodes created, hierarchy valid (every child has exactly one parent at next level)
- **Integration test**: `search_architecture("How does data assimilation work?")` returns Level 2+ community with children
- **Regression test**: Existing LOCAL queries still work, no performance degradation
- **Benchmark**: Re-run Phase 24G 50-query corpus, measure global query accuracy improvement

**Success Criteria:**
- Community nodes exist at 3+ hierarchical levels
- Every non-singleton community has a summary in both Neo4j and ChromaDB
- PARENT_OF tree is valid (acyclic, single parent per level)
- INTERACTS_WITH captures ≥80% of cross-subsystem communication patterns
- Global query accuracy improves from 40% (template-only) to ≥60%
- `search_architecture` returns hierarchical context with drill-down
- No regression in LOCAL/TRACE query performance

**Implementation Files:**
| File | Changes |
|------|---------|
| `src/graphrag/CommunityDetection.js` | Add `runHierarchicalLeiden()`, `materializeCommunityNodes()`, `getCommunitiesAtLevel()`, `getChildCommunities()`, `getCommunityInteractions()`, `getMaxCommunityLevel()` |
| `src/graphrag/CommunitySummarizer.js` | Add `summarizeHierarchical()`, `generateParentSummary()` |
| `src/graphrag/GraphGuidedRetrieval.js` | Update `retrieveGlobal()` for level-aware search + drill-down |
| `scripts/run_community_detection.js` | Add `--materialize` flag, full pipeline orchestration |
| `src/__tests__/CommunityHierarchy.test.js` | New test file: hierarchy validation, drill-down, INTERACTS_WITH |

**Estimated Effort:** 4-6 hours across 10 steps

### Phase 24E-6: LLM-Generated Community Summaries via GitHub Models API

**Objective:** Replace the 828 template-based keyword-inference summaries with true LLM-generated narrative summaries, closing the global query accuracy gap from 60% to >75%.

**Status:** SCRIPTS IMPLEMENTED (February 25, 2026) — SDD session `session_2026-02-25_et3ltn`. Awaiting batch execution via GitHub CLI.

**Motivation:** The current `CommunitySummarizer.generateSummary()` uses 16 hardcoded keyword patterns to infer purpose (e.g., `['gsi', 'radiance', 'satellite'] → "Data assimilation / observation processing"`). This produces structurally repetitive summaries that list *what's in* each community but cannot explain *what it does*, describe data flow, or identify cross-cutting patterns. An LLM can synthesize member metadata + relationships into developer-quality subsystem overviews that enable semantic search to match conceptual queries (e.g., "How does error handling work?") even when no member name contains the query terms.

**Approach:** Three-script offline batch pipeline using the GitHub Models API (`https://models.inference.ai.azure.com/chat/completions`) authenticated via `gh auth token`. This requires no new API keys — it uses the existing GitHub Copilot subscription.

**Prerequisites:**
- [x] GitHub CLI authenticated (`gh auth status` confirmed: TerrenceMcGuinness-NOAA)
- [x] GitHub Models API accessible (`gpt-4o-mini` confirmed working, Feb 25 2026)
- [x] 1,036 Community nodes in Neo4j with MEMBER_OF, PARENT_OF, INTERACTS_WITH relationships
- [x] 828 template summaries in `community-summaries` ChromaDB collection (to be replaced)

#### Step 1: Export Community Contexts (`scripts/export_community_contexts.js`)

Extract, for each of the 828 non-singleton communities, the full context an LLM needs:

```javascript
// Output: community_contexts.json
// For each community at each level:
{
  "communityId": 42,
  "level": 0,
  "memberCount": 87,
  "members": [
    {"name": "gsi_main", "type": "FortranSubroutine", "path": "sorc/gsi.fd/..."},
    {"name": "setuprad", "type": "FortranSubroutine", "path": "sorc/gsi.fd/..."},
    ...
  ],
  "internalRelationships": [
    {"source": "gsi_main", "rel": "CALLS", "target": "setuprad"},
    {"source": "gsi_main", "rel": "CALLS", "target": "read_obs"},
    ...
  ],
  "externalRelationships": [
    {"source": "hybens_info", "rel": "CALLS", "target": "enkf_update", "targetCommunity": 55}
  ],
  "languages": ["Fortran", "Shell"],
  "childSummaries": []  // Populated for L1+ after L0 generation
}
```

**Queries:**
```cypher
// Members
MATCH (c:Community {communityId: $cid, level: $level})<-[:MEMBER_OF]-(n)
RETURN n.name, labels(n)[0] AS type, n.path LIMIT 200

// Internal relationships
MATCH (c:Community {communityId: $cid, level: $level})<-[:MEMBER_OF]-(a)
      -[r]->(b)-[:MEMBER_OF]->(c)
RETURN a.name, type(r), b.name LIMIT 100

// External relationships  
MATCH (c:Community {communityId: $cid, level: $level})<-[:MEMBER_OF]-(a)
      -[r]->(b)-[:MEMBER_OF]->(other:Community)
WHERE other <> c
RETURN a.name, type(r), b.name, other.communityId LIMIT 50

// Children (for L1+)
MATCH (c:Community {communityId: $cid, level: $level})-[:PARENT_OF]->(child:Community)
RETURN child.communityId, child.level, child.summary, child.memberCount
```

**Output:** `mcp_server_node/data/community_contexts.json` (~5-10MB)

#### Step 2: Generate LLM Summaries (`scripts/generate_llm_summaries.js`)

Loop through exported contexts, call `gpt-4o-mini` via GitHub Models API, produce summaries bottom-up (L0 first, then L1 using L0 summaries, etc.).

```javascript
import { execSync } from 'child_process';
import { readFileSync, writeFileSync, existsSync } from 'fs';

const API_URL = 'https://models.inference.ai.azure.com/chat/completions';
const MODEL = 'gpt-4o-mini';
const MAX_TOKENS = 500;
const DELAY_MS = 2500;  // ~24 req/min, within Copilot rate limits

// Get token from gh CLI (no hardcoded secrets)
function getGitHubToken() {
  return execSync('gh auth token', { encoding: 'utf8' }).trim();
}

// Resume support: skip communities already in output file
const OUTPUT_FILE = 'data/llm_summaries.json';
const existing = existsSync(OUTPUT_FILE) 
  ? JSON.parse(readFileSync(OUTPUT_FILE, 'utf8')) 
  : [];
const doneIds = new Set(existing.map(s => `${s.level}-${s.communityId}`));

async function generateSummary(context, token) {
  const prompt = buildPrompt(context);  // Section 3.5 prompt template
  
  const response = await fetch(API_URL, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      model: MODEL,
      messages: [
        { role: 'system', content: 'You are a senior software engineer analyzing a code community in the NOAA Global Workflow — one of the most complex computational weather forecasting pipelines on Earth.' },
        { role: 'user', content: prompt }
      ],
      max_tokens: MAX_TOKENS,
      temperature: 0.3  // Low creativity, high factual consistency
    })
  });

  const data = await response.json();
  return data.choices?.[0]?.message?.content || null;
}

// Process bottom-up: L0 → L1 → L2 → L3
for (const level of [0, 1, 2, 3]) {
  const communities = contexts.filter(c => c.level === level);
  console.log(`[INFO] Level ${level}: ${communities.length} communities`);
  
  for (const ctx of communities) {
    const key = `${ctx.level}-${ctx.communityId}`;
    if (doneIds.has(key)) continue;  // Resume support
    
    // For L1+, inject child summaries from prior level
    if (level > 0) {
      ctx.childSummaries = existing
        .filter(s => ctx.childCommunityIds?.includes(s.communityId) && s.level === level - 1)
        .map(s => s.summary);
    }
    
    const summary = await generateSummary(ctx, token);
    if (summary) {
      existing.push({ communityId: ctx.communityId, level: ctx.level, summary });
      writeFileSync(OUTPUT_FILE, JSON.stringify(existing, null, 2));  // Save after each (resume-safe)
    }
    
    await sleep(DELAY_MS);
  }
}
```

**Rate Limiting & Resumability:**
- `gpt-4o-mini` rate limit with Copilot: ~15-30 req/min
- 2.5s delay between calls → ~24 req/min (conservative)
- 828 communities / 24 req/min = ~35 minutes total runtime
- Output saved after each community — if interrupted, re-run skips completed entries
- Bottom-up ordering ensures L1+ summaries have child context available

**Estimated Cost:** $0 (included in GitHub Copilot subscription via GitHub Models API)

**Output:** `mcp_server_node/data/llm_summaries.json`

#### Step 3: Import LLM Summaries (`scripts/import_llm_summaries.js`)

Load the generated summaries into both Neo4j (Community node `summary` property) and ChromaDB (`community-summaries` collection). Embeddings are generated automatically by `VectorDatabase.addDocuments()` via `Xenova/all-mpnet-base-v2`.

```javascript
import { readFileSync } from 'fs';
import { GraphDatabase } from '../src/data/GraphDatabase.js';
import { VectorDatabase } from '../src/data/VectorDatabase.js';

const COLLECTION = 'community-summaries';

async function main() {
  const summaries = JSON.parse(readFileSync('data/llm_summaries.json', 'utf8'));
  console.log(`[INFO] Importing ${summaries.length} LLM-generated summaries...`);

  const graphDB = new GraphDatabase();
  const vectorDB = new VectorDatabase();
  await graphDB.connect();
  await vectorDB.connect();

  // 1. Write summaries to Neo4j Community nodes
  let neo4jUpdated = 0;
  for (const s of summaries) {
    try {
      await graphDB.query(
        'MATCH (c:Community {communityId: $cid, level: $level}) SET c.summary = $summary, c.summarySource = "llm", c.summaryModel = "gpt-4o-mini", c.summaryGeneratedAt = datetime()',
        { cid: s.communityId, level: s.level, summary: s.summary }
      );
      neo4jUpdated++;
    } catch (e) {
      console.error(`[WARN] Neo4j update failed for L${s.level}-${s.communityId}: ${e.message}`);
    }
  }
  console.log(`[OK] Neo4j: ${neo4jUpdated}/${summaries.length} Community nodes updated`);

  // 2. Replace ChromaDB collection (embeddings auto-generated)
  try { await vectorDB.deleteCollection(COLLECTION); } catch {}
  await vectorDB.getOrCreateCollection(COLLECTION, {
    description: 'LLM-generated hierarchical community summaries (Phase 24E-6)'
  });

  const documents = summaries.map(s => ({
    id: `community-L${s.level}-${s.communityId}`,
    text: s.summary,
    metadata: {
      communityId: s.communityId,
      level: s.level,
      summarySource: 'llm',
      generatedAt: new Date().toISOString()
    }
  }));

  const BATCH = 50;
  for (let i = 0; i < documents.length; i += BATCH) {
    await vectorDB.addDocuments(COLLECTION, documents.slice(i, i + BATCH));
  }
  console.log(`[OK] ChromaDB: ${documents.length} summaries stored in '${COLLECTION}'`);

  await graphDB.close();
}
```

**Output:** 828 community summaries replaced in both Neo4j and ChromaDB.

#### Step 4: Validation

- Re-run Phase 24G 50-query benchmark corpus against the new LLM summaries
- Compare global query accuracy: template (60%) vs LLM (target >75%)
- Verify `search_architecture` returns richer, more relevant context
- Spot-check 10-20 summaries manually for factual accuracy and coherence

**Success Criteria:**
- All 828 communities have LLM-generated summaries in both Neo4j and ChromaDB
- Global query accuracy improves from 60% to ≥75% on Phase 24G benchmark
- No regression in LOCAL/TRACE query performance or latency
- Summaries are <400 words, specific, and technically accurate
- `Community.summarySource = "llm"` set on all updated nodes (for auditability)

**Implementation Files:**
| File | New/Modified | Description |
|------|-------------|-------------|
| `scripts/export_community_contexts.js` | New (COMMITTED) | Extract community context from Neo4j → JSON |
| `scripts/generate_llm_summaries.js` | New (COMMITTED) | Call GitHub Models API for each community → JSON |
| `scripts/import_llm_summaries.js` | New (COMMITTED) | Load JSON summaries → Neo4j + ChromaDB |
| `data/community_contexts.json` | New (generated) | Intermediate context file (~5-10MB) |
| `data/llm_summaries.json` | New (generated) | LLM output file (~1-2MB) |

**Estimated Effort:** 3-4 hours (scripts) + ~35 min (batch run) + 1 hour (validation)

**Dependencies:**
- [x] GitHub CLI authenticated with Copilot subscription
- [x] GitHub Models API access confirmed (`gpt-4o-mini`)
- [x] 1,036 Community nodes with hierarchy in Neo4j
- [x] `VectorDatabase.addDocuments()` auto-generates embeddings

#### Execution Runbook (24E-6)

> **Intent:** Execute the committed pipeline scripts to replace all 828 template-based
> community summaries with LLM-generated narrative summaries. This is a one-time batch
> operation that upgrades global query accuracy from ~60% to >75%. After completion,
> the MCP server's `search_architecture` and `search_documentation` tools will return
> richer, semantically meaningful community context for holistic codebase questions.

**Executor:** GitHub CLI session (Claude Opus 4.6 or human operator)
**Working directory:** `mcp_server_node/`
**Estimated wall-clock time:** ~45 minutes total

##### Pre-flight Checks (run ALL before proceeding)

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node

# 1. Verify GitHub auth (MUST show TerrenceMcGuinness-NOAA)
gh auth status

# 2. Verify GitHub Models API is reachable
TOKEN=$(gh auth token)
curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"ping"}],"max_tokens":5}' \
  https://models.inference.ai.azure.com/chat/completions
# Expected: 200

# 3. Verify Neo4j is running and has Community nodes
curl -s -o /dev/null -w "%{http_code}" http://localhost:7474
# Expected: 200

# 4. Verify ChromaDB is running
curl -s http://localhost:8080/api/v2/heartbeat | head -1
# Expected: {"nanosecond heartbeat":...}

# 5. Verify Node.js can import required modules
node -e "
  Promise.all([
    import('./src/data/GraphDatabase.js'),
    import('./src/data/VectorDatabase.js'),
    import('./src/graphrag/CommunityDetection.js')
  ]).then(() => console.log('[OK] All modules importable'))
    .catch(e => { console.error('[FAIL]', e.message); process.exit(1); });
"

# 6. Verify scripts exist and parse
node --check scripts/export_community_contexts.js && echo "[OK] export"
node --check scripts/generate_llm_summaries.js && echo "[OK] generate"
node --check scripts/import_llm_summaries.js && echo "[OK] import"
```

**STOP** if any check fails. Do not proceed to execution.

##### Execution Sequence (strict order — do NOT parallelize)

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node

# ──────────────────────────────────────────────────────────
# STEP 1: Export community contexts from Neo4j → JSON
# ──────────────────────────────────────────────────────────
# Reads all Community nodes (L0-L3) with members, relationships,
# child summaries, and interactions. Writes data/community_contexts.json.
# Expected: ~828 communities exported, file size ~5-10MB, runtime ~2-3 min.

node scripts/export_community_contexts.js

# CHECKPOINT: Verify output exists and has expected count
node -e "
  const d = JSON.parse(require('fs').readFileSync('data/community_contexts.json','utf8'));
  console.log('Communities exported:', d.length);
  const byLevel = {};
  d.forEach(c => byLevel[c.level] = (byLevel[c.level]||0)+1);
  Object.entries(byLevel).sort().forEach(([l,n]) => console.log('  L'+l+':', n));
  if (d.length < 800) { console.error('[WARN] Expected ~828, got', d.length); process.exit(1); }
  console.log('[OK] Export verified');
"

# ──────────────────────────────────────────────────────────
# STEP 2: Generate LLM summaries via GitHub Models API
# ──────────────────────────────────────────────────────────
# Calls gpt-4o-mini for each community context. Bottom-up order:
# L0 first (694), then L1 (175), L2 (86), L3 (81).
# Resume-safe: saves after every 5 communities. If interrupted,
# re-run the same command — it skips already-completed entries.
# Expected: ~828 summaries, runtime ~35 min, $0 cost.

# RECOMMENDED: Dry-run first to verify API connectivity (processes 3 only)
node scripts/generate_llm_summaries.js --dry-run

# FULL RUN (only after dry-run succeeds):
node scripts/generate_llm_summaries.js

# CHECKPOINT: Verify all communities have summaries
node -e "
  const d = JSON.parse(require('fs').readFileSync('data/llm_summaries.json','utf8'));
  const ok = d.filter(r => r.summary);
  const fail = d.filter(r => !r.summary);
  console.log('Total:', d.length, '| Success:', ok.length, '| Failed:', fail.length);
  if (fail.length > 0) {
    console.log('[WARN] Failed communities:');
    fail.forEach(f => console.log('  L'+f.level+'-'+f.communityId+':', f.error));
    console.log('Re-run generate_llm_summaries.js to retry failed entries.');
  } else {
    console.log('[OK] All summaries generated');
  }
"

# ──────────────────────────────────────────────────────────
# STEP 3: Import LLM summaries → Neo4j + ChromaDB
# ──────────────────────────────────────────────────────────
# Writes summaries to Neo4j Community nodes (summary, summarySource,
# summaryModel, summaryTimestamp) and to ChromaDB community-summaries
# collection (with auto-generated embeddings via Xenova/all-mpnet-base-v2).
# Expected: ~828 nodes updated in Neo4j, ~828 docs in ChromaDB, runtime ~5 min.

# RECOMMENDED: Dry-run first to preview
node scripts/import_llm_summaries.js --dry-run

# FULL RUN:
node scripts/import_llm_summaries.js

# CHECKPOINT: Verify Neo4j and ChromaDB state
node -e "
  import('./src/data/GraphDatabase.js').then(async ({ GraphDatabase }) => {
    const db = new GraphDatabase();
    await db.connect();
    const r = await db.query(
      'MATCH (c:Community) WHERE c.summary IS NOT NULL ' +
      'RETURN c.summarySource AS source, count(*) AS n ORDER BY source'
    );
    console.log('Neo4j summaries by source:');
    r.forEach(row => console.log('  ' + row.source + ':', row.n));
    const llm = r.find(x => x.source === 'llm');
    if (!llm || llm.n < 800) {
      console.error('[WARN] Expected ~828 LLM summaries, got', llm?.n || 0);
    } else {
      console.log('[OK] Neo4j import verified');
    }
    await db.close();
  });
"
```

##### Post-Execution Actions

1. **Spot-check 5 summaries** — pick one from each level and verify it reads as a coherent, technically accurate subsystem description (not a keyword list):
   ```bash
   node -e "
     import('./src/data/GraphDatabase.js').then(async ({ GraphDatabase }) => {
       const db = new GraphDatabase();
       await db.connect();
       for (const level of [0, 1, 2, 3]) {
         const r = await db.query(
           'MATCH (c:Community {level: \$level}) WHERE c.summarySource = \"llm\" ' +
           'RETURN c.communityId, c.name, c.summary LIMIT 1', { level }
         );
         if (r[0]) console.log('--- L' + level + ':', r[0].name, '---\n' + r[0].summary + '\n');
       }
       await db.close();
     });
   "
   ```

2. **Git commit the generated data files** (optional but recommended for reproducibility):
   ```bash
   cd /mcp_rag_eib/eib-mcp-rag-server
   git add mcp_server_node/data/community_contexts.json mcp_server_node/data/llm_summaries.json
   git commit -m "Phase 24E-6: LLM summary batch output (828 communities) [data artifacts]"
   ```

3. **Start SDD session for validation** — return to VS Code Copilot session and use:
   - `start_sdd_session` (phase: `phase24e_hierarchical_communities`, steps: 3)
   - Step 1: Run Phase 24G benchmark queries against new summaries
   - Step 2: Compare accuracy metrics (template vs LLM)
   - Step 3: Record final metrics and close

4. **Update this spec** — change 24E-6 status from `SCRIPTS IMPLEMENTED` to `COMPLETE` and record actual metrics.

5. **Update CHANGELOG.md** — add entry for the batch execution results.

##### Failure Recovery

| Failure | Recovery |
|---------|----------|
| Step 1 export fails (Neo4j down) | Verify Neo4j: `curl localhost:7474`. Restart if needed: `docker compose -f docker-compose.devops.yaml up -d neo4j` |
| Step 2 API rate-limited (429) | Script auto-retries with exponential backoff (3 attempts). If persistent, increase `DELAY_MS` via `--batch-size 1` |
| Step 2 interrupted mid-run | Re-run same command — resume-safe, skips completed entries |
| Step 2 partial failures | Re-run same command — only retries entries with `summary: null` |
| Step 3 import fails (ChromaDB down) | Use `--skip-chromadb` to do Neo4j only, then `--skip-neo4j` after ChromaDB restart |
| Wrong summaries imported | Re-run Step 2 with fresh output (`rm data/llm_summaries.json`), then Step 3 |

---

### Phase 24E-7: Staleness Propagation & Selective Re-Summarization

**Objective:** Connect Phase 24H-3's `mark_as_modified` dirty tracking to Community node staleness, enabling selective LLM re-summarization of only the affected communities instead of a full pipeline re-run.

**Status:** PLANNED (February 25, 2026). Supersedes the original 24E-4.

**Motivation:** The current workaround for stale summaries is a full `run_community_detection.js --materialize` re-run (~828 API calls, ~35 min). With staleness propagation, only the communities whose members actually changed need re-summarization. In a typical PR touching 5-10 files, this means re-generating 2-5 summaries instead of 828.

**Prerequisites:**
- [x] `mark_as_modified` sets `_dirty = true` on Neo4j nodes (24H-3)
- [ ] 24E-6 LLM summary pipeline operational (for selective re-generation)

#### Step 1: Staleness Propagation Query

When files are marked dirty (via `mark_as_modified` or after a graph re-ingestion), propagate staleness up the community hierarchy:

```cypher
// Propagate _dirty from member nodes to their Community ancestors
MATCH (n {_dirty: true})-[:MEMBER_OF]->(c:Community)
SET c._stale = true, c._staleAt = datetime()
WITH c
MATCH (c)<-[:PARENT_OF*]-(ancestor:Community)
SET ancestor._stale = true, ancestor._staleAt = datetime()
RETURN count(DISTINCT ancestor) + count(DISTINCT c) AS staleCommunities
```

#### Step 2: Selective Re-Summarization Script (`scripts/resummarize_stale.js`)

Re-export context for only stale communities, re-generate their LLM summaries, and re-import:

```javascript
// 1. Find stale communities
const stale = await graphDB.query(`
  MATCH (c:Community {_stale: true})
  RETURN c.communityId, c.level, c.memberCount
  ORDER BY c.level ASC
`);

// 2. Export context for stale communities only
// 3. Call GitHub Models API for each (same as 24E-6 Step 2)
// 4. Import updated summaries (same as 24E-6 Step 3)

// 5. Clear staleness
await graphDB.query(`
  MATCH (c:Community {_stale: true})
  REMOVE c._stale, c._staleAt
`);
await graphDB.query(`
  MATCH (n {_dirty: true})
  REMOVE n._dirty, n._dirtyAt
`);
```

#### Step 3: Community Structure Re-evaluation Trigger

If >20% of nodes in a Level 0 community are dirty, the community boundaries themselves may have shifted. Trigger a localized Leiden re-run:

```javascript
// Check if community structure needs re-computation
const overThreshold = await graphDB.query(`
  MATCH (c:Community {level: 0, _stale: true})<-[:MEMBER_OF]-(n)
  WITH c, count(n) AS total, sum(CASE WHEN n._dirty = true THEN 1 ELSE 0 END) AS dirty
  WHERE toFloat(dirty) / total > 0.2
  RETURN c.communityId, dirty, total
`);

if (overThreshold.length > 0) {
  console.log(`[WARN] ${overThreshold.length} communities may need re-clustering`);
  // Flag for full re-run in next scheduled pipeline
}
```

#### Step 4: Integration with `mark_as_modified` Tool

Add a post-hook to `mark_as_modified` that propagates staleness immediately:

```javascript
// In GraphRAGTools.markAsModified(), after setting _dirty on the node:
try {
  await this.dataAccess.graphDB.query(`
    MATCH (n {_dirty: true})-[:MEMBER_OF]->(c:Community)
    WHERE NOT c._stale = true
    SET c._stale = true, c._staleAt = datetime()
    WITH c
    MATCH (c)<-[:PARENT_OF*]-(ancestor:Community)
    WHERE NOT ancestor._stale = true
    SET ancestor._stale = true, ancestor._staleAt = datetime()
  `);
} catch (_) { /* non-fatal */ }
```

**Success Criteria:**
- `mark_as_modified` propagates staleness to Community nodes in <100ms
- `resummarize_stale.js` regenerates only stale summaries
- Typical PR (5-10 files) triggers 2-5 community re-summarizations (~15-30 seconds)
- Full re-clustering triggered only when >20% of a community's members change

**Implementation Files:**
| File | New/Modified | Description |
|------|-------------|-------------|
| `scripts/resummarize_stale.js` | New | Selective re-summarization of stale communities |
| `src/tools/GraphRAGTools.js` | Modified | Add staleness propagation hook to `markAsModified` |

**Estimated Effort:** 2-3 hours

**Dependencies:**
- 24E-6 complete (LLM summary pipeline must exist for selective re-generation)
- 24H-3 `mark_as_modified` operational (already delivered)

---

## 5. Success Metrics

| Metric | Baseline (24D only) | Target (24E complete) | Current (24E-5) | Measurement |
|--------|---------------------|----------------------|-----------------|-------------|
| Global query accuracy | ~30% | >75% | 60% (template) | Phase 24G benchmark; 24E-6 LLM upgrade targets ≥75% |
| Queries for architecture understanding | 5-10 | 1-2 | 1-2 | via `search_architecture` tool |
| Community boundary alignment | N/A | >70% match dirs | Reasonable | 63 of 3,841 communities are multi-node |
| Summary freshness | N/A | <24hr stale | Manual re-run | 24E-7 will enable selective re-summarization |
| Global retrieval latency | N/A | <1000ms | ~120ms P95 | Phase 24G benchmark |
| Summary quality | N/A | Developer-grade narratives | Keyword enumeration | 24E-6 replaces templates with LLM |
| Stale summary turnaround | N/A | <2 min (5-10 file PR) | Full re-run (~35 min) | 24E-7 selective re-summarization |

---

## 6. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Communities don't match intuitive boundaries | Medium | High | Manual override capability; tune Leiden parameters |
| GitHub Models API rate limits hit during batch | Medium | Low | Resume-safe script; 2.5s delay; run during off-hours |
| LLM summaries hallucinate incorrect relationships | Low | Medium | Low temperature (0.3); validation step; spot-check |
| Staleness cascade invalidates too many summaries | Low | Medium | Tune threshold (20%); lazy regeneration |
| Neo4j GDS not available/licensed | Low | High | Fallback to external clustering (NetworkX) |
| GitHub token scope changes break Models API | Low | Medium | `gh auth refresh` as fallback; document required scopes |

---

## 7. Dependencies

### Required Infrastructure
- [x] Neo4j GDS plugin (Graph Data Science library) — v2.13.7 installed
- [x] LLM access — GitHub Models API via `gh auth token` (Copilot subscription)
- [x] Embedding model for summary vectors — `Xenova/all-mpnet-base-v2` (auto-generated)
- [x] ChromaDB collection for community summaries — `community-summaries` (828 docs)

### Phase 24 Integration Points
- **24A**: Cypher patterns extended for community traversal
- **24B**: Weight matrix extended with `MEMBER_OF` relationships  
- **24C**: Token budget includes community summaries
- **24D**: MCP tools extended with community-aware variants

---

## 8. Open Questions

1. **Naming Communities:** Should communities have auto-generated names or human-curated labels?
2. **Cross-Repository Communities:** If graphs span repos, should communities cross repo boundaries?
3. **Summary Update Triggers:** Real-time vs batched summary regeneration?
4. **Embedding Model:** Same model as document embeddings or specialized?
5. **Community Granularity:** What's the right number of L1/L2/L3 communities for a codebase of this size?

---

## 9. Appendix: Before/After for Global Queries

### Before (Phase 24D Only)

```
User: "What's the error handling strategy in this codebase?"

System: [extracts entities: "error", "handling", "strategy"]
        [graph traversal finds nodes with "error" in name]
        [returns: err_chk function, error.sh, some log files]

LLM: "I found some error-related files:
      - err_chk in ush/err_chk.sh
      - Some error logging in...
      
      Would you like me to search for more?"

Result: Fragmented, no synthesis, requires follow-ups
```

### After (Phase 24E)

```
User: "What's the error handling strategy in this codebase?"

System: [classifies as GLOBAL query]
        [searches community summaries for "error handling"]
        [finds L2 summary: "Execution Subsystem"]
        [finds L2 summary: "Validation Subsystem"]
        [retrieves cross-cutting concern: "error_handling"]

LLM: "The codebase uses a layered error handling strategy:

      **Execution Layer** (jobs/, ex/):
      Error handling follows the 'fail-fast with checkpointing' pattern.
      Each job script sources err_chk() which logs to comroot and 
      exits non-zero. Rocoto handles retry logic externally.

      **Validation Layer** (vrfy/):
      Uses 'log-and-continue' for non-critical validation failures,
      with summary reports generated post-run.

      **Configuration Layer** (config/, env/):
      Defensive defaults with explicit unset-variable errors 
      (set -u is standard). Missing config fails at parse time.

      **Cross-Cutting Patterns:**
      - All scripts source ush/err_chk.sh
      - Exit codes follow WCOSS conventions (0=success, 1-127=app error)
      - Critical errors write to both stdout and COMROOT/logs/

      Want me to dive into any specific layer?"

Result: Synthesized answer from community summaries, one query
```

---

## 10. References

### Internal
- Phase 24 SDD (GGSR foundation)
- ADVANCED_FUTURE_WORK.md §3.3 (Learned Graph Embeddings - future)

### External
- **Traag et al. (2019)**: "From Louvain to Leiden: guaranteeing well-connected communities" - Leiden algorithm. [arXiv:1810.08473](https://arxiv.org/abs/1810.08473)
- **Edge et al. (2024)**: "From Local to Global: A Graph RAG Approach to Query-Focused Summarization" - Microsoft GraphRAG. [arXiv:2404.16130](https://arxiv.org/abs/2404.16130)
- Neo4j GDS Documentation: Community Detection Algorithms

---

*Document generated as part of SDD Phase 24E prospectus - Q2-Q3 2026*
