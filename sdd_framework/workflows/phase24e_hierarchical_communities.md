# SDD: Phase 24E - Hierarchical Community Summarization

**Version:** 1.2.0  
**Created:** 2026-02-05  
**Updated:** 2026-02-24  
**Author:** AI Assistant + Terry McGuinness  
**Status:** COMPLETE — 24E-1/2/3 operational (flat communities + ChromaDB summaries); 24E-4 deferred; **24E-5 COMPLETE** (v7.20.0: 1,036 Community nodes, 4 levels, 21,559 MEMBER_OF, 978 PARENT_OF, 1,297 INTERACTS_WITH, 828 summaries)  
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

### Phase 24E-4: Incremental Update Pipeline (Week 7-8)

**Objective:** Keep communities and summaries fresh as code changes

**Steps:**
- [ ] Implement file-level dirty tracking
- [ ] Define staleness propagation rules
- [ ] Build incremental re-clustering for small changes
- [ ] Build full re-clustering trigger for large changes
- [ ] Implement summary invalidation cascade

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

---

## 5. Success Metrics

| Metric | Baseline (24D only) | Target (24E) | Measurement |
|--------|---------------------|--------------|-------------|
| Global query accuracy | ~30% | >75% | 40% (Phase 24G benchmark — template summaries; LLM upgrade needed) |
| Queries for architecture understanding | 5-10 | 1-2 | 1-2 via `search_architecture` tool |
| Community boundary alignment | N/A | >70% match dirs | Reasonable — 63 of 3,841 communities are multi-node |
| Summary freshness | N/A | <24hr stale | Manual re-run via `run_community_detection.js` |
| Global retrieval latency | N/A | <1000ms | ~120ms P95 (Phase 24G benchmark) |

---

## 6. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Communities don't match intuitive boundaries | Medium | High | Manual override capability; tune Leiden parameters |
| Summary generation too expensive | Medium | Medium | Batch during off-hours; cache aggressively |
| Staleness cascade invalidates too much | Low | Medium | Tune thresholds; lazy regeneration |
| Neo4j GDS not available/licensed | Low | High | Fallback to external clustering (NetworkX) |
| Summaries become stale faster than regenerated | Medium | Medium | Priority queue for high-traffic communities |

---

## 7. Dependencies

### Required Infrastructure
- [ ] Neo4j GDS plugin (Graph Data Science library)
- [ ] LLM access for summary generation (budget ~$50-100 for full corpus)
- [ ] Embedding model for summary vectors
- [ ] ChromaDB collection for community summaries

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
