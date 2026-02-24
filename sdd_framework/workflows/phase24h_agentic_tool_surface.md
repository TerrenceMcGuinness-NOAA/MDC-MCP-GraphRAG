# SDD: Phase 24H - Agentic MCP Tool Surface

**Version:** 1.1.0  
**Created:** 2026-02-05  
**Updated:** 2026-02-24  
**Author:** AI Assistant + Terry McGuinness  
**Status:** Partially Complete — 24H-1/24H-2 delivered (v7.11.0), 24H-3/24H-4 ready for CLI handoff  
**Dependencies:** Phase 24A-D (GGSR), Phase 24E (Community Summarization), Phase 24F (Cross-Language), Phase 24G (Benchmark), Phase 31 (SDD Session Model)

> **📋 MASTER REFERENCE:** [phase24_consolidated_architecture.md](phase24_consolidated_architecture.md)

---

## 1. Executive Summary

Phases 24A-E establish the GraphRAG retrieval infrastructure. This phase defines the **MCP tool surface** that exposes this infrastructure to LLM agents for long-running, autonomous coding tasks.

### Design Philosophy

The tool surface is organized around **agent workflows**, not database operations:

| Workflow | Tools |
|----------|-------|
| Understanding code | Discovery tools |
| Planning changes | Impact analysis tools |
| Making changes | Modification-aware tools |
| Validating changes | Test coverage tools |
| Long-running sessions | Session state tools |

### Key Innovation

Move from "search and retrieve" tools to **workflow-aware tools** that anticipate multi-step agent reasoning patterns.

---

## 2. Problem Statement

### Current Tool Limitations

```
Agent: "I need to refactor the resource allocation logic"

Current Tools Available:
- search_documentation(query) → Returns text chunks
- search_codebase(query) → Returns file matches

Agent Must:
1. Search for "resource allocation" 
2. Read each file manually
3. Search for callers (separate query)
4. Search for tests (separate query)
5. Search for config dependencies (separate query)
6. Manually track what it's examined
7. Hope it didn't miss anything
```

**Problems:**
- Too many round-trips
- No impact analysis
- No session continuity
- Agent can't answer "what breaks if I change this?"

### Target State

```
Agent: "I need to refactor the resource allocation logic"

Tools Available:
- get_code_context("config.resources") → Full neighborhood + community summary
- get_change_impact("config.resources", "signature_change") → Blast radius
- get_test_coverage("config.resources") → What tests exercise this?
- mark_as_modified("config.resources") → Track for session
- get_session_context() → What have I touched?

Agent Gets:
- Complete context in 1-2 calls
- Knows what will break
- Knows what tests to run
- Can resume after interruption
```

---

## 3. Tool Taxonomy

### 3.1 Tool Categories

```
┌─────────────────────────────────────────────────────────────────┐
│                     MCP TOOL SURFACE                            │
├─────────────────────────────────────────────────────────────────┤
│  DISCOVERY          │  IMPACT           │  SESSION              │
│  ─────────────────  │  ───────────────  │  ──────────────────   │
│  get_code_context   │  get_change_impact│  mark_as_modified     │
│  trace_data_flow    │  find_dependents  │  get_session_context  │
│  get_test_coverage  │  check_interface  │  checkpoint_state     │
│  find_similar_code  │  preview_refactor │  restore_checkpoint   │
│  search_architecture│                   │  get_modification_log │
├─────────────────────────────────────────────────────────────────┤
│  GRAPH INTROSPECTION (Debug/Advanced)                           │
│  ─────────────────────────────────────                          │
│  get_node_neighborhood  │  get_community_members                │
│  explain_relationship   │  get_graph_stats                      │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Tool Priority for Implementation

| Priority | Tool | Value | Complexity |
|----------|------|-------|------------|
| P0 | get_code_context | Critical | Medium |
| P0 | get_change_impact | Critical | High |
| P0 | get_session_context | Critical | Low |
| P1 | trace_data_flow | High | High |
| P1 | get_test_coverage | High | Medium |
| P1 | mark_as_modified | High | Low |
| P2 | find_similar_code | Medium | Medium |
| P2 | search_architecture | Medium | Low (uses 24E) |
| P2 | checkpoint_state | Medium | Medium |
| P3 | Graph introspection | Debug | Low |

---

## 4. Tool Specifications

### 4.1 Discovery Tools

#### `get_code_context`

**Purpose:** Primary entry point for understanding any code symbol. Returns the symbol, its graph neighborhood, and relevant community context.

```javascript
{
  name: "get_code_context",
  description: "Get comprehensive context for a code symbol including its relationships, callers, callees, and architectural context. Use this as the first step when examining any code.",
  parameters: {
    symbol: {
      type: "string",
      description: "Code symbol (function, file, class, or path pattern)",
      required: true
    },
    depth: {
      type: "number", 
      description: "Relationship traversal depth (1-3)",
      default: 2
    },
    include_community: {
      type: "boolean",
      description: "Include community/subsystem summary",
      default: true
    },
    include_source: {
      type: "boolean",
      description: "Include source code content",
      default: true
    }
  }
}
```

**Implementation:**
```javascript
async function get_code_context(params) {
  const { symbol, depth = 2, include_community = true, include_source = true } = params;
  
  // 1. Find the node
  const node = await neo4j.query(`
    MATCH (n:File|Function|Class)
    WHERE n.name =~ $pattern OR n.path =~ $pattern
    RETURN n LIMIT 1
  `, { pattern: `(?i).*${escapeRegex(symbol)}.*` });
  
  if (!node) return { error: "Symbol not found", suggestions: await findSimilar(symbol) };
  
  // 2. Get neighborhood (Phase 24A-D GGSR)
  const neighborhood = await ggsr.traverseGraph(node, { maxHops: depth });
  
  // 3. Get community context (Phase 24E)
  let communityContext = null;
  if (include_community) {
    communityContext = await neo4j.query(`
      MATCH (n)-[:MEMBER_OF]->(c:Community)
      WHERE id(n) = $nodeId
      OPTIONAL MATCH (c)-[:PARENT_OF*]->(ancestor:Community)
      RETURN c.summary AS l1_summary, 
             collect(DISTINCT ancestor.summary) AS ancestor_summaries
    `, { nodeId: node.id });
  }
  
  // 4. Get source content
  let sourceContent = null;
  if (include_source) {
    sourceContent = await chromadb.get(node.chroma_id);
  }
  
  // 5. Assemble response
  return {
    symbol: {
      name: node.name,
      path: node.path,
      type: node.labels[0],
      signature: node.signature,
      docstring: node.docstring
    },
    relationships: {
      calls: neighborhood.filter(r => r.type === 'CALLS').map(formatRelationship),
      called_by: neighborhood.filter(r => r.type === 'CALLED_BY').map(formatRelationship),
      imports: neighborhood.filter(r => r.type === 'IMPORTS').map(formatRelationship),
      sources: neighborhood.filter(r => r.type === 'SOURCES').map(formatRelationship),
      depends_on: neighborhood.filter(r => r.type === 'DEPENDS_ON').map(formatRelationship)
    },
    community: communityContext ? {
      subsystem_summary: communityContext.l1_summary,
      architectural_context: communityContext.ancestor_summaries
    } : null,
    source: sourceContent,
    graph_location: {
      community_id: node.community_l1,
      centrality: node.pagerank_score
    }
  };
}
```

**Example Response:**
```json
{
  "symbol": {
    "name": "config.resources",
    "path": "parm/config/config.resources",
    "type": "File",
    "signature": null,
    "docstring": "Resource configuration for forecast jobs"
  },
  "relationships": {
    "calls": [],
    "called_by": [
      {"name": "JGFS_FORECAST", "path": "jobs/JGFS_FORECAST", "weight": 0.9},
      {"name": "JGFS_ATMOS_ANALYSIS", "path": "jobs/JGFS_ATMOS_ANALYSIS", "weight": 0.9}
    ],
    "sources": [
      {"name": "HERA.env", "path": "env/HERA.env", "weight": 0.95},
      {"name": "WCOSS2.env", "path": "env/WCOSS2.env", "weight": 0.95}
    ],
    "depends_on": [
      {"name": "config.base", "path": "parm/config/config.base", "weight": 0.8}
    ]
  },
  "community": {
    "subsystem_summary": "The Configuration Subsystem manages computational resources, environment settings, and platform-specific adaptations...",
    "architectural_context": ["The GFS Workflow System comprises four major subsystems..."]
  },
  "source": "#!/bin/bash\n# Resource configuration...",
  "graph_location": {
    "community_id": "L1_config_subsystem",
    "centrality": 0.847
  }
}
```

---

#### `trace_data_flow`

**Purpose:** Track how data moves from one symbol to another. Critical for understanding impact of type/format changes.

```javascript
{
  name: "trace_data_flow",
  description: "Trace how data flows from a source to a destination through the codebase. Essential for understanding the impact of data format or type changes.",
  parameters: {
    from_symbol: {
      type: "string",
      description: "Source symbol (where data originates)",
      required: true
    },
    to_symbol: {
      type: "string",
      description: "Destination symbol (optional - if omitted, shows all downstream)",
      required: false
    },
    max_depth: {
      type: "number",
      description: "Maximum path length to search",
      default: 5
    },
    data_type: {
      type: "string",
      description: "Filter by data type (e.g., 'config', 'env_var', 'file')",
      required: false
    }
  }
}
```

**Implementation:**
```javascript
async function trace_data_flow(params) {
  const { from_symbol, to_symbol, max_depth = 5, data_type } = params;
  
  const query = to_symbol ? `
    // Specific path query
    MATCH path = shortestPath(
      (source)-[:DATA_FLOWS_TO|CALLS|SOURCES*1..${max_depth}]->(dest)
    )
    WHERE source.name =~ $fromPattern AND dest.name =~ $toPattern
    RETURN path, length(path) as hops,
           [r IN relationships(path) | type(r)] as relationship_types,
           [n IN nodes(path) | {name: n.name, type: labels(n)[0]}] as path_nodes
    ORDER BY hops
    LIMIT 5
  ` : `
    // All downstream query
    MATCH path = (source)-[:DATA_FLOWS_TO|CALLS|SOURCES*1..${max_depth}]->(downstream)
    WHERE source.name =~ $fromPattern
    WITH downstream, min(length(path)) as min_hops, collect(path)[0] as sample_path
    RETURN downstream.name, downstream.path, min_hops, 
           [n IN nodes(sample_path) | n.name] as via
    ORDER BY min_hops
    LIMIT 20
  `;
  
  const results = await neo4j.query(query, {
    fromPattern: `(?i).*${escapeRegex(from_symbol)}.*`,
    toPattern: to_symbol ? `(?i).*${escapeRegex(to_symbol)}.*` : null
  });
  
  return {
    source: from_symbol,
    destination: to_symbol || "ALL_DOWNSTREAM",
    paths: results.map(r => ({
      endpoint: r.downstream?.name || r.path_nodes?.slice(-1)[0]?.name,
      hops: r.hops || r.min_hops,
      via: r.via || r.path_nodes?.map(n => n.name),
      relationship_chain: r.relationship_types
    })),
    summary: `Found ${results.length} data flow paths from ${from_symbol}`
  };
}
```

---

#### `get_test_coverage`

**Purpose:** Find tests that exercise a given symbol. Critical for knowing what to run after changes.

```javascript
{
  name: "get_test_coverage",
  description: "Find all tests that exercise a given code symbol. Use before making changes to know what tests to run.",
  parameters: {
    symbol: {
      type: "string",
      description: "Code symbol to find test coverage for",
      required: true
    },
    include_indirect: {
      type: "boolean",
      description: "Include tests that indirectly exercise this code through callers",
      default: true
    }
  }
}
```

**Implementation:**
```javascript
async function get_test_coverage(params) {
  const { symbol, include_indirect = true } = params;
  
  const directQuery = `
    MATCH (t:Test)-[:TESTS]->(target)
    WHERE target.name =~ $pattern
    RETURN t.name, t.path, 'direct' as coverage_type, target.name as tests_target
  `;
  
  const indirectQuery = `
    MATCH (t:Test)-[:TESTS]->(tested)-[:CALLS*1..3]->(target)
    WHERE target.name =~ $pattern
    RETURN DISTINCT t.name, t.path, 'indirect' as coverage_type, 
           tested.name as tests_target,
           length(shortestPath((tested)-[:CALLS*]->(target))) as hops_away
  `;
  
  const directTests = await neo4j.query(directQuery, { pattern: symbolPattern(symbol) });
  const indirectTests = include_indirect 
    ? await neo4j.query(indirectQuery, { pattern: symbolPattern(symbol) })
    : [];
  
  return {
    symbol: symbol,
    direct_tests: directTests.map(t => ({
      test: t.name,
      path: t.path,
      tests: t.tests_target
    })),
    indirect_tests: indirectTests.map(t => ({
      test: t.name,
      path: t.path,
      via: t.tests_target,
      distance: t.hops_away
    })),
    coverage_summary: {
      direct_count: directTests.length,
      indirect_count: indirectTests.length,
      has_coverage: directTests.length > 0,
      recommendation: directTests.length === 0 
        ? "⚠️ No direct tests found. Consider adding tests before refactoring."
        : `✓ ${directTests.length} direct tests cover this symbol.`
    }
  };
}
```

---

#### `find_similar_code`

**Purpose:** Find code patterns similar to a given snippet or symbol. Useful for consistent refactoring.

```javascript
{
  name: "find_similar_code",
  description: "Find code patterns similar to a given snippet or symbol. Use when refactoring to ensure consistency across similar code.",
  parameters: {
    code_or_symbol: {
      type: "string",
      description: "Code snippet or symbol name to find similar patterns for",
      required: true
    },
    similarity_threshold: {
      type: "number",
      description: "Minimum similarity score (0.0-1.0)",
      default: 0.7
    },
    max_results: {
      type: "number",
      description: "Maximum results to return",
      default: 10
    }
  }
}
```

**Implementation:**
```javascript
async function find_similar_code(params) {
  const { code_or_symbol, similarity_threshold = 0.7, max_results = 10 } = params;
  
  // 1. Get embedding for the query
  const queryEmbedding = await embedder.embed(code_or_symbol);
  
  // 2. Search ChromaDB for similar documents
  const similar = await chromadb.query({
    collection: "code_embeddings",
    query_embedding: queryEmbedding,
    n_results: max_results * 2,  // Over-fetch to filter
    include: ["documents", "metadatas", "distances"]
  });
  
  // 3. Filter by threshold and format
  const filtered = similar.results
    .filter(r => (1 - r.distance) >= similarity_threshold)
    .slice(0, max_results);
  
  // 4. Enrich with graph context
  const enriched = await Promise.all(filtered.map(async (r) => {
    const graphNode = await neo4j.query(`
      MATCH (n) WHERE n.chroma_id = $chromaId
      OPTIONAL MATCH (n)-[:MEMBER_OF]->(c:Community)
      RETURN n.name, n.path, labels(n)[0] as type, c.name as community
    `, { chromaId: r.metadata.id });
    
    return {
      name: graphNode?.name || r.metadata.name,
      path: graphNode?.path || r.metadata.path,
      type: graphNode?.type || 'Unknown',
      similarity: (1 - r.distance).toFixed(3),
      community: graphNode?.community,
      snippet: r.document.substring(0, 200) + '...'
    };
  }));
  
  return {
    query: code_or_symbol.substring(0, 100),
    similar_code: enriched,
    summary: `Found ${enriched.length} similar code patterns above ${similarity_threshold} threshold`
  };
}
```

---

### 4.2 Impact Analysis Tools

#### `get_change_impact`

**Purpose:** The critical tool for safe refactoring. Shows blast radius of proposed changes.

```javascript
{
  name: "get_change_impact",
  description: "Analyze the impact of changing a code symbol. Shows what will break, what tests to run, and what documentation may need updates. USE THIS BEFORE MAKING ANY SIGNIFICANT CHANGES.",
  parameters: {
    symbol: {
      type: "string",
      description: "Symbol to analyze change impact for",
      required: true
    },
    change_type: {
      type: "string",
      enum: ["signature", "behavior", "delete", "rename", "move"],
      description: "Type of change being considered",
      required: true
    },
    include_indirect: {
      type: "boolean",
      description: "Include indirect/transitive impacts",
      default: true
    }
  }
}
```

**Implementation:**
```javascript
async function get_change_impact(params) {
  const { symbol, change_type, include_indirect = true } = params;
  
  const maxHops = include_indirect ? 3 : 1;
  
  // 1. Find direct dependents
  const dependents = await neo4j.query(`
    MATCH (target)<-[r:CALLS|IMPORTS|SOURCES|DEPENDS_ON*1..${maxHops}]-(dependent)
    WHERE target.name =~ $pattern
    WITH dependent, min(length(r)) as distance, collect(type(r)) as rel_types
    RETURN dependent.name, dependent.path, labels(dependent)[0] as type,
           distance, rel_types
    ORDER BY distance, dependent.name
  `, { pattern: symbolPattern(symbol) });
  
  // 2. Find affected tests
  const affectedTests = await get_test_coverage({ symbol, include_indirect });
  
  // 3. Find documentation references
  const docRefs = await neo4j.query(`
    MATCH (d:Documentation)-[:DOCUMENTS|REFERENCES]->(target)
    WHERE target.name =~ $pattern
    RETURN d.name, d.path
  `, { pattern: symbolPattern(symbol) });
  
  // 4. Check for interface implementations
  const interfaces = await neo4j.query(`
    MATCH (target)-[:IMPLEMENTS]->(i:Interface)
    WHERE target.name =~ $pattern
    OPTIONAL MATCH (other)-[:IMPLEMENTS]->(i)
    WHERE other <> target
    RETURN i.name as interface, collect(other.name) as other_implementors
  `, { pattern: symbolPattern(symbol) });
  
  // 5. Compute risk score
  const riskScore = computeRiskScore({
    dependentCount: dependents.length,
    testCoverage: affectedTests.direct_tests.length,
    hasInterface: interfaces.length > 0,
    changeType: change_type
  });
  
  return {
    symbol: symbol,
    change_type: change_type,
    
    direct_impacts: dependents
      .filter(d => d.distance === 1)
      .map(d => ({ name: d.name, path: d.path, type: d.type })),
    
    indirect_impacts: dependents
      .filter(d => d.distance > 1)
      .map(d => ({ name: d.name, path: d.path, distance: d.distance })),
    
    tests_to_run: {
      required: affectedTests.direct_tests,
      recommended: affectedTests.indirect_tests.slice(0, 5)
    },
    
    documentation_updates: docRefs,
    
    interface_considerations: interfaces.length > 0 ? {
      warning: "This symbol implements an interface. Changes may require updates to other implementors.",
      interfaces: interfaces
    } : null,
    
    risk_assessment: {
      score: riskScore,
      level: riskScore > 0.7 ? 'HIGH' : riskScore > 0.4 ? 'MEDIUM' : 'LOW',
      factors: [
        `${dependents.length} dependent symbols`,
        `${affectedTests.direct_tests.length} direct tests`,
        interfaces.length > 0 ? `Implements ${interfaces.length} interface(s)` : null
      ].filter(Boolean)
    },
    
    recommendations: generateRecommendations(change_type, riskScore, dependents)
  };
}

function computeRiskScore({ dependentCount, testCoverage, hasInterface, changeType }) {
  let score = 0;
  score += Math.min(dependentCount / 20, 0.4);  // Max 0.4 from dependents
  score += testCoverage === 0 ? 0.3 : 0;        // No tests = risky
  score += hasInterface ? 0.2 : 0;               // Interface = coordination needed
  score += changeType === 'delete' ? 0.2 : 
           changeType === 'signature' ? 0.15 : 0.05;
  return Math.min(score, 1.0);
}
```

---

### 4.3 Session State Tools

#### `mark_as_modified`

**Purpose:** Track files/symbols the agent has modified during a session. Enables incremental graph updates and session continuity.

```javascript
{
  name: "mark_as_modified",
  description: "Mark a file or symbol as modified during this session. Enables tracking of changes and incremental graph updates.",
  parameters: {
    path_or_symbol: {
      type: "string",
      description: "File path or symbol that was modified",
      required: true
    },
    modification_type: {
      type: "string",
      enum: ["content", "created", "deleted", "renamed"],
      description: "Type of modification",
      default: "content"
    },
    summary: {
      type: "string",
      description: "Brief description of the change",
      required: false
    }
  }
}
```

**Implementation:**
```javascript
// Session state stored in memory (or Redis for distributed)
const sessionState = {
  id: generateSessionId(),
  started_at: new Date(),
  modifications: [],
  checkpoints: []
};

async function mark_as_modified(params) {
  const { path_or_symbol, modification_type = 'content', summary } = params;
  
  const modification = {
    id: generateModificationId(),
    target: path_or_symbol,
    type: modification_type,
    summary: summary,
    timestamp: new Date(),
    graph_stale: true
  };
  
  sessionState.modifications.push(modification);
  
  // Mark graph nodes as dirty
  await neo4j.query(`
    MATCH (n:File|Function)
    WHERE n.path =~ $pattern OR n.name =~ $pattern
    SET n.dirty = true, 
        n.last_modified_session = $sessionId,
        n.last_modified_at = datetime()
    WITH n
    MATCH (n)-[:MEMBER_OF]->(c:Community)
    SET c.stale = true
    RETURN count(n) as nodes_marked
  `, { 
    pattern: symbolPattern(path_or_symbol),
    sessionId: sessionState.id 
  });
  
  return {
    tracked: true,
    modification_id: modification.id,
    session_modifications_count: sessionState.modifications.length,
    message: `Marked ${path_or_symbol} as modified. Graph nodes flagged for re-indexing.`
  };
}
```

---

#### `get_session_context`

**Purpose:** Return what the agent has examined and modified in this session. Critical for resumption and avoiding re-work.

```javascript
{
  name: "get_session_context",
  description: "Get summary of current session: what has been examined, modified, and any checkpoints. Use at start of resumed work or to avoid re-examining code.",
  parameters: {
    include_examined: {
      type: "boolean",
      description: "Include list of examined symbols (via get_code_context calls)",
      default: true
    },
    include_modifications: {
      type: "boolean",
      description: "Include list of modifications made",
      default: true
    }
  }
}
```

**Implementation:**
```javascript
async function get_session_context(params) {
  const { include_examined = true, include_modifications = true } = params;
  
  return {
    session: {
      id: sessionState.id,
      started_at: sessionState.started_at,
      duration_minutes: Math.round((new Date() - sessionState.started_at) / 60000)
    },
    
    examined: include_examined ? {
      symbols: sessionState.examined || [],
      count: (sessionState.examined || []).length,
      last_examined: (sessionState.examined || []).slice(-5)
    } : null,
    
    modifications: include_modifications ? {
      files: sessionState.modifications,
      count: sessionState.modifications.length,
      by_type: groupBy(sessionState.modifications, 'type')
    } : null,
    
    checkpoints: sessionState.checkpoints.map(cp => ({
      id: cp.id,
      name: cp.name,
      created_at: cp.created_at,
      modifications_at_checkpoint: cp.modifications_count
    })),
    
    graph_state: {
      dirty_nodes: await neo4j.query(`
        MATCH (n {dirty: true, last_modified_session: $sessionId})
        RETURN count(n) as count
      `, { sessionId: sessionState.id }).then(r => r[0]?.count || 0),
      stale_communities: await neo4j.query(`
        MATCH (c:Community {stale: true})
        RETURN count(c) as count
      `).then(r => r[0]?.count || 0)
    }
  };
}
```

---

#### `checkpoint_state`

**Purpose:** Create a named checkpoint that can be restored. Essential for long-running tasks with multiple phases.

```javascript
{
  name: "checkpoint_state",
  description: "Create a named checkpoint of current session state. Use between major phases of work to enable recovery.",
  parameters: {
    name: {
      type: "string",
      description: "Descriptive name for the checkpoint",
      required: true
    },
    notes: {
      type: "string",
      description: "Notes about what was accomplished before this checkpoint",
      required: false
    }
  }
}
```

**Implementation:**
```javascript
async function checkpoint_state(params) {
  const { name, notes } = params;
  
  const checkpoint = {
    id: generateCheckpointId(),
    name: name,
    notes: notes,
    created_at: new Date(),
    modifications_count: sessionState.modifications.length,
    modifications_snapshot: [...sessionState.modifications],
    examined_snapshot: [...(sessionState.examined || [])],
    graph_dirty_count: await neo4j.query(`
      MATCH (n {dirty: true, last_modified_session: $sessionId})
      RETURN count(n) as count
    `, { sessionId: sessionState.id }).then(r => r[0]?.count || 0)
  };
  
  sessionState.checkpoints.push(checkpoint);
  
  // Persist to durable storage for recovery across restarts
  await persistCheckpoint(sessionState.id, checkpoint);
  
  return {
    checkpoint_created: true,
    checkpoint_id: checkpoint.id,
    checkpoint_name: name,
    state_summary: {
      modifications_captured: checkpoint.modifications_count,
      symbols_examined: checkpoint.examined_snapshot.length,
      dirty_graph_nodes: checkpoint.graph_dirty_count
    },
    message: `Checkpoint "${name}" created. Can restore with restore_checkpoint("${checkpoint.id}")`
  };
}
```

---

### 4.4 Graph Introspection Tools (Debug/Advanced)

#### `get_graph_stats`

**Purpose:** Overview of graph health and coverage. Useful for debugging and understanding corpus coverage.

```javascript
{
  name: "get_graph_stats",
  description: "Get statistics about the knowledge graph: node counts, relationship coverage, community health.",
  parameters: {}
}
```

**Implementation:**
```javascript
async function get_graph_stats() {
  const stats = await neo4j.query(`
    MATCH (n)
    WITH labels(n)[0] AS label, count(n) AS count
    RETURN label, count
    ORDER BY count DESC
  `);
  
  const relStats = await neo4j.query(`
    MATCH ()-[r]->()
    WITH type(r) AS rel_type, count(r) AS count
    RETURN rel_type, count
    ORDER BY count DESC
  `);
  
  const communityStats = await neo4j.query(`
    MATCH (c:Community)
    WITH c.level AS level, count(c) AS count, avg(c.member_count) AS avg_members
    RETURN level, count, avg_members
    ORDER BY level
  `);
  
  const healthMetrics = await neo4j.query(`
    MATCH (n)
    WHERE n.dirty = true OR n.stale = true
    RETURN 
      sum(CASE WHEN n.dirty THEN 1 ELSE 0 END) AS dirty_nodes,
      sum(CASE WHEN n.stale THEN 1 ELSE 0 END) AS stale_communities
  `);
  
  return {
    nodes: {
      total: stats.reduce((sum, s) => sum + s.count, 0),
      by_type: Object.fromEntries(stats.map(s => [s.label, s.count]))
    },
    relationships: {
      total: relStats.reduce((sum, s) => sum + s.count, 0),
      by_type: Object.fromEntries(relStats.map(s => [s.rel_type, s.count]))
    },
    communities: {
      by_level: Object.fromEntries(communityStats.map(c => [
        `L${c.level}`, 
        { count: c.count, avg_members: Math.round(c.avg_members) }
      ]))
    },
    health: {
      dirty_nodes: healthMetrics[0]?.dirty_nodes || 0,
      stale_communities: healthMetrics[0]?.stale_communities || 0,
      status: (healthMetrics[0]?.dirty_nodes || 0) < 100 ? 'HEALTHY' : 'NEEDS_REINDEX'
    }
  };
}
```

---

## 5. Implementation Phases

### Phase 24H-1: Core Discovery Tools ✅ Complete (v7.11.0)

**Deliverables:**
- [x] `get_code_context` - Full implementation with GGSR integration (GraphRAGTools.js)
- [x] `find_similar_code` - ChromaDB semantic search with graph enrichment (GraphRAGTools.js)
- [x] `search_architecture` - Community summary search (GraphRAGTools.js)
- [x] Tool registration in MCP server
- [x] Parameter aliases added for backward compatibility (Phase 29, v7.20.2)

**Success Criteria:** Met — tools registered and callable, <500ms typical latency.

### Phase 24H-2: Impact Analysis + Trace Tools ✅ Complete (v7.11.0)

**Deliverables:**
- [x] `get_change_impact` - Blast radius analysis with risk scoring (GraphRAGTools.js)
- [x] `trace_data_flow` - Data flow tracing across codebase (GraphRAGTools.js)
- [ ] `get_test_coverage` - **Deferred** — requires `:Test` nodes + `:TESTS` relationships in Neo4j graph schema (not yet ingested)

**Success Criteria:** Partially met — impact analysis and data flow work. Test coverage blocked on graph schema extension.

### Phase 24H-3: Session State Tools — READY FOR IMPLEMENTATION

> **Design Decision (2026-02-24):** Open Question #2 resolved — **extend Phase 31 SessionManager.js** with filesystem persistence. No Redis or SQLite needed. The existing `active_session.json` + `history.jsonl` pattern handles all 24H session requirements.

**Deliverables:**
- [ ] Extend `SessionManager.js` with `modifications[]`, `examined[]`, `checkpoints[]` arrays on active session schema
- [ ] `mark_as_modified` tool — append to `modifications[]` + set `dirty=true` on Neo4j nodes + flag communities as stale
- [ ] `get_session_context` tool — aggregated view of examined symbols, modifications, checkpoints, graph dirty state
- [ ] `checkpoint_state` tool — snapshot current modifications/examined to `execution_state/checkpoints/<id>.json`
- [ ] `restore_checkpoint` tool — roll back session state to named checkpoint
- [ ] Auto-record examined symbols when `get_code_context` is called (internal, no new tool)

**Persistence Design:**
- Session state: `sdd_framework/execution_state/active_session.json` (existing file, extended schema)
- Checkpoint files: `sdd_framework/execution_state/checkpoints/<checkpoint_id>.json` (new directory)
- Audit trail: `sdd_framework/execution_state/history.jsonl` (existing file, new event types: `symbol_examined`, `file_modified`, `checkpoint_created`, `checkpoint_restored`)
- No new dependencies (no Redis, no SQLite)

**Tool Registration:** Register in `GraphRAGTools.js` (not SDDWorkflowTools — these are agent-workflow tools, not plan-tracking tools). The tools call `SessionManager` methods but are part of the GraphRAG discovery/impact workflow.

**Overlap with SDD Tools:**
- SDD `record_sdd_step` tracks *plan progress* ("Step 3: implement X") → SDDWorkflowTools.js
- 24H `mark_as_modified` tracks *code changes* ("modified config.resources") → GraphRAGTools.js
- Both write to the same `active_session.json` via `SessionManager` — orthogonal concerns, shared state

**Success Criteria:**
- Session state persists across MCP server restarts (same as Phase 31 — guaranteed by filesystem writes)
- Checkpoints enable work resumption within a session
- `get_session_context` returns examined + modified + checkpoint data in single call

### Phase 24H-4: Integration & Documentation — READY FOR IMPLEMENTATION

**Deliverables:**
- [ ] `get_graph_stats` tool — Neo4j aggregation query (node counts, relationship coverage, community health)
- [ ] Update instruction files with new tools via `generate-tool-docs.js --check`
- [ ] Agent workflow examples in `eib-mcp-tools.instructions.md`
- [ ] Performance benchmarks for all 24H tools

**De-scoped from original spec:**
- `find_dependents` — already covered by `find_dependencies({ target, direction: 'downstream' })`
- `check_interface_compliance` — requires `:Interface` + `:IMPLEMENTS` relationships (not in graph schema)
- `get_node_neighborhood` — covered by GGSR internals exposed via `get_code_context`
- `explain_relationship` — low priority (P3), defer to future phase

**Success Criteria:**
- All new tools documented in MCP manifest and instruction files
- `generate-tool-docs.js --check` passes with 0 warnings
- End-to-end agent workflow demonstrated

---

## 6. Success Metrics

| Metric | Current | Target | Measurement |
|--------|---------|--------|-------------|
| Tool calls per refactoring task | 10-20 | 3-5 | Agent logs |
| Context completeness (user rating) | Unknown | >4.0/5.0 | Feedback |
| Session resumption success rate | N/A | >90% | Checkpoint tests |
| Impact prediction accuracy | N/A | >85% | Compare predicted vs actual breaks |
| Tool latency P95 | N/A | <1000ms | Performance logs |

---

## 7. Example Agent Workflow

### Refactoring Task: "Update config.resources to use YAML instead of shell"

```
Agent: Let me understand what I'm working with.

[calls get_code_context("config.resources")]
→ Gets: source, callers, dependencies, community context

Agent: Before I change this, let me check what will break.

[calls get_change_impact("config.resources", "behavior")]
→ Gets: 12 direct dependents, 47 indirect, 3 tests, HIGH risk

Agent: I need to find all similar config files to update them consistently.

[calls find_similar_code("config.resources")]
→ Gets: config.base, config.fcst, config.anal (similar patterns)

Agent: Let me checkpoint before I start making changes.

[calls checkpoint_state("pre-yaml-refactor", "Analyzed impact, ready to modify")]
→ Gets: checkpoint_id for recovery

Agent: [makes changes to config.resources]

[calls mark_as_modified("parm/config/config.resources", "content", "Converted to YAML format")]
→ Gets: confirmation, graph marked dirty

Agent: [continues modifying dependent files...]

Agent: Let me verify what I've done so far.

[calls get_session_context()]
→ Gets: 5 files modified, 12 symbols examined, checkpoint available
```

---

## 8. Open Questions — RESOLVED

1. **Tool Granularity:** Should `get_change_impact` be split into separate tools for different concerns (tests, deps, docs)?
   > **Resolved (v7.11.0):** No. `get_change_impact` returns a unified response with `direct_impacts`, `indirect_impacts`, and `risk_assessment` sections. Splitting would increase round-trips — the opposite of the 24H design goal.

2. **Session Persistence:** Redis vs SQLite vs filesystem for checkpoint storage?
   > **Resolved (2026-02-24):** **Filesystem** — extend Phase 31 `SessionManager.js`. The existing `active_session.json` + `history.jsonl` pattern handles all session state requirements. Checkpoints stored as individual JSON files in `execution_state/checkpoints/`. No new dependencies needed. See Phase 24H-3 implementation plan above.

3. **Rate Limiting:** Should expensive tools (data flow tracing) have rate limits?
   > **Resolved (v7.11.0):** Not rate-limited, but guarded by a 15-second GGSR timeout. Results still return partial data on timeout. This is sufficient for IDE modality where the human controls call frequency.

4. **Async Tools:** Should long-running tools (full impact analysis) be async with polling?
   > **Resolved:** No. MCP stdio transport is synchronous by design. The 15s GGSR guard ensures no tool blocks indefinitely. If async execution becomes needed for CLI/YOLO modality (Phase 4C USD), it would be a transport-layer concern, not a tool-layer concern.

5. **Tool Composition:** Should we provide meta-tools that compose multiple tools (e.g., `prepare_for_refactor`)?
   > **Resolved:** Deferred. LLM agents already compose tools naturally via multi-step reasoning. Meta-tools would reduce agent flexibility. Revisit if CLI batch execution (Phase 4C) shows a need for atomic multi-tool operations.

---

## 9. Appendix: Full Tool Manifest

```javascript
const GRAPHRAG_MCP_TOOLS = {
  // Discovery
  get_code_context: { category: 'discovery', priority: 'P0' },
  trace_data_flow: { category: 'discovery', priority: 'P1' },
  get_test_coverage: { category: 'discovery', priority: 'P1' },
  find_similar_code: { category: 'discovery', priority: 'P2' },
  search_architecture: { category: 'discovery', priority: 'P2' },
  
  // Impact Analysis
  get_change_impact: { category: 'impact', priority: 'P0' },
  find_dependents: { category: 'impact', priority: 'P1' },
  check_interface_compliance: { category: 'impact', priority: 'P2' },
  
  // Session State
  mark_as_modified: { category: 'session', priority: 'P1' },
  get_session_context: { category: 'session', priority: 'P0' },
  checkpoint_state: { category: 'session', priority: 'P2' },
  restore_checkpoint: { category: 'session', priority: 'P2' },
  
  // Graph Introspection
  get_graph_stats: { category: 'debug', priority: 'P3' },
  get_node_neighborhood: { category: 'debug', priority: 'P3' },
  explain_relationship: { category: 'debug', priority: 'P3' }
};
```

---

### Implementation Status Summary (2026-02-24)

| Sub-Phase | Status | Tools | Version |
|-----------|--------|-------|--------|
| 24H-1 Discovery | ✅ Complete | `get_code_context`, `find_similar_code`, `search_architecture` | v7.11.0 |
| 24H-2 Impact/Trace | ✅ Complete | `get_change_impact`, `trace_data_flow` | v7.11.0 |
| 24H-2 Test Coverage | ⏸ Blocked | `get_test_coverage` | Needs `:Test` graph nodes |
| 24H-3 Session State | 📋 Ready | `mark_as_modified`, `get_session_context`, `checkpoint_state`, `restore_checkpoint` | Extend Phase 31 SessionManager |
| 24H-4 Integration | 📋 Ready | `get_graph_stats` + docs | After 24H-3 |
| De-scoped | — | `find_dependents` (covered by `find_dependencies`), `check_interface_compliance`, `get_node_neighborhood`, `explain_relationship` | — |

*Document generated as part of SDD Phase 24H prospectus. Updated 2026-02-24 with Open Question resolutions and Phase 31 extension plan.*
