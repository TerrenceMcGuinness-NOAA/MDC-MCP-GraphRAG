# Neptune GGSR Compatibility Bugfix Design

## Overview

The AWS-ported MCP server has two bugs preventing GGSR from functioning on Neptune. Bug 1: `NeptuneAdapter.traceCrossLanguageChain()` generates directed variable-length path syntax (`->[:REL*1..N]->`) that Neptune's openCypher rejects with `Invalid input '>'`. Bug 2: `mcp-http-server.js` initializes `sharedGGSR` but never injects it into per-request `UnifiedMCPServer` instances, so `get_code_context` and other GGSR-dependent tools return degraded results. The fix rewrites Neptune-incompatible Cypher patterns and adds GGSR injection to the HTTP request handler.

## Glossary

- **Bug_Condition (C)**: Two conditions: (C1) directed variable-length path syntax in NeptuneAdapter queries that Neptune rejects; (C2) missing GGSR/retrieval injection in HTTP per-request instances
- **Property (P)**: (P1) Neptune queries return correct cross-language execution chains; (P2) HTTP-served tools return full GGSR neighborhood data
- **Preservation**: Existing 45/45 validated tools, stdio transport GGSR injection, `traceCrossLanguagePath()`, APOC transforms, and standard openCypher queries must remain unchanged
- **`traceCrossLanguageChain()`**: Method in `NeptuneAdapter.js` (line 413) that traces multi-language execution paths using `SOURCES|INVOKES|EXECUTES|CALLS` relationships
- **`findUpstreamExecutors()`**: Method in `NeptuneAdapter.js` (line 424) that finds J-Jobs triggering a Fortran program using `SOURCES|INVOKES*1..3`
- **`sharedGGSR`**: The `GGSRTraversalPrototypes` instance created once at HTTP server startup but never passed to per-request tool modules
- **Directed variable-length path**: Cypher syntax like `->[:REL*1..N]->` — supported by Neo4j but rejected by Neptune's openCypher

## Bug Details

### Bug Condition

The bug manifests in two independent scenarios:

**C1 — Neptune Cypher Syntax**: When any NeptuneAdapter method generates a directed variable-length path pattern (`-[:REL*1..N]->` or `<-[:REL*1..N]<-`), Neptune rejects the query. The affected methods are `traceCrossLanguageChain`, `findUpstreamExecutors`, `traceCallChain`, `traceScriptChain`, `tracePythonCallChain`, `traceFortranCallChain`, `findDependencyGraph`, and `findCircularDependencies`.

**C2 — Missing GGSR Injection**: When the HTTP wrapper creates a per-request `UnifiedMCPServer`, it injects `sharedDataAccess` into `semanticSearchTools`, `operationalTools`, `codeAnalysisTools`, and `graphRAGTools` — but never injects `sharedGGSR` or a `GraphGuidedRetrieval` instance. The `codeAnalysisTools.ggsr` and `graphRAGTools.ggsr` remain `null`.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type { queryType: string, transport: string }
  OUTPUT: boolean

  // C1: Neptune directed variable-length path
  LET c1 = input.queryType CONTAINS directed variable-length path pattern
            AND backend = 'neptune'
            AND query MATCHES /->?\[:[A-Z|]+\*\d+\.\.\d+\]->?/

  // C2: Missing GGSR in HTTP transport
  LET c2 = input.transport = 'http'
            AND tool IN ['get_code_context', 'search_architecture', 'find_similar_code',
                         'get_change_impact', 'trace_data_flow', 'get_code_context']
            AND perRequestInstance.codeAnalysisTools.ggsr = null
            AND perRequestInstance.graphRAGTools.ggsr = null

  RETURN c1 OR c2
END FUNCTION
```

### Examples

- `traceCrossLanguageChain("JGLOBAL_FORECAST", 5, "forward")` generates `(start {name: $name})->[:SOURCES|INVOKES|EXECUTES|CALLS*1..5]->(end)` → Neptune returns `Invalid input '>'`
- `traceCrossLanguageChain("setuprad", 5, "reverse")` generates `(start {name: $name})<-[:SOURCES|INVOKES|EXECUTES|CALLS*1..5]<-(end)` → Neptune returns `Invalid input '<'`
- `findUpstreamExecutors("gsi")` generates `(jjob:ShellScript)-[:SOURCES|INVOKES*1..3]->(script)` → Neptune returns syntax error
- HTTP `get_code_context("setuprad")` → returns results without GGSR neighborhood (missing `oneHopNeighborhood`, `twoHopNeighborhood` data)
- HTTP `search_architecture("data assimilation")` → returns degraded results without graph-guided retrieval fusion

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- All 45 currently validated tools must continue to pass on Neptune
- `NeptuneAdapter.traceCrossLanguagePath()` must continue to work (it uses compatible `MATCH/OPTIONAL MATCH` patterns)
- Stdio transport GGSR injection via `UnifiedMCPServer.start()` must remain unchanged
- All 5 APOC transforms in `apoc-transform.js` must continue to function
- Standard openCypher queries without directed variable-length paths must execute without modification
- `/health` endpoint and non-MCP endpoints must respond correctly
- `GGSRTraversalPrototypes` methods (`oneHopNeighborhood`, `twoHopNeighborhood`, `fortranWeightedTraversal`) must continue to work (they use undirected or simple patterns)
- Neptune's `labels()` return format differences must be handled (returns array, not single value in some contexts)

**Scope:**
All inputs that do NOT involve directed variable-length path patterns or HTTP transport GGSR injection should be completely unaffected by this fix. This includes:
- Simple `MATCH (a)-[:REL]->(b)` single-hop directed queries
- Undirected variable-length paths `(a)-[:REL*1..N]-(b)` (already Neptune-compatible)
- Stdio transport tool invocations
- APOC-transformed queries
- Vector DB (ChromaDB/OpenSearch) queries

## Hypothesized Root Cause

Based on the bug description and code analysis, the root causes are:

1. **Neptune openCypher Limitation — Directed Variable-Length Paths**: Neptune's openCypher implementation does not support the syntax `->[:REL*1..N]->` (directed variable-length relationship patterns). Neo4j supports this, so the NeptuneAdapter methods were copied from `GraphDatabase.js` without adaptation. The legacy `GraphDatabase.traceCrossLanguageChain()` (lines 742-840) works around this by decomposing into separate `OPTIONAL MATCH` clauses per relationship type and hop level, which Neptune supports.

2. **Multi-Relationship Type in Variable-Length Paths**: Neptune may also reject `[:SOURCES|INVOKES|EXECUTES|CALLS*1..N]` even in undirected form. The safe pattern is to decompose into individual relationship-type matches or use separate MATCH clauses.

3. **HTTP Server Missing GGSR Injection**: In `mcp-http-server.js` (lines 60-72), the per-request handler injects `sharedDataAccess` into `mcp.semanticSearchTools`, `mcp.operationalTools`, `mcp.codeAnalysisTools`, and `mcp.graphRAGTools` — but only sets `.dataAccess` and `.isInitialized`. It never sets `.ggsr` or `.retrieval`, even though `sharedGGSR` is available. The stdio path (`UnifiedMCPServer.start()`, lines 1222-1240) correctly creates both `ggsr` and `retrieval` and injects them into `codeAnalysisTools` and `graphRAGTools`.

4. **Neptune `labels()` and `length(path)` Differences**: Neptune's `labels()` function may return results differently than Neo4j (e.g., as a list rather than indexed). Additionally, Neptune does not support `length(path)` — `size()` must be used instead. These are secondary issues that may surface once the primary query syntax is fixed.

## Correctness Properties

Property 1: Bug Condition — Neptune Directed Path Queries Return Valid Results

_For any_ call to `NeptuneAdapter.traceCrossLanguageChain(name, depth, direction)` where `name` matches an existing node and `direction` is `'forward'` or `'reverse'`, the fixed method SHALL return an array of result objects containing `chain` (array of node names), `labels` (array of node labels), and `rels` (array of relationship types) — matching the structure returned by `GraphDatabase.traceCrossLanguageChain()` — without throwing a Neptune syntax error.

**Validates: Requirements 2.1, 2.2**

Property 2: Preservation — Non-Affected Queries Unchanged

_For any_ NeptuneAdapter query that does NOT use directed variable-length path syntax (e.g., `findImporters`, `findCallers`, `getStatistics`, `traceCrossLanguagePath`), the fixed code SHALL produce exactly the same results as the original code, preserving all existing query behavior and output format.

**Validates: Requirements 3.1, 3.2, 3.5**

Property 3: Bug Condition — HTTP GGSR Injection Provides Full Results

_For any_ HTTP request to `/mcp` that invokes a GGSR-dependent tool (`get_code_context`, `search_architecture`, `find_similar_code`, `get_change_impact`, `trace_data_flow`), the fixed HTTP handler SHALL inject `sharedGGSR` and a `GraphGuidedRetrieval` instance into the per-request `codeAnalysisTools` and `graphRAGTools`, such that `mcp.codeAnalysisTools.ggsr !== null` and `mcp.graphRAGTools.ggsr !== null`.

**Validates: Requirements 2.3, 2.4**

Property 4: Preservation — Stdio Transport Unchanged

_For any_ MCP server started via stdio transport (`UnifiedMCPServer.start()`), the fixed code SHALL produce exactly the same GGSR initialization behavior as the original code, preserving the existing `ggsr` and `retrieval` injection into `codeAnalysisTools` and `graphRAGTools`.

**Validates: Requirements 3.3, 3.6**


## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `mcp_server_node/src/data/adapters/NeptuneAdapter.js`

**Method**: `traceCrossLanguageChain(name, depth, direction)`

**Specific Changes**:
1. **Rewrite to decomposed MATCH pattern**: Replace the single directed variable-length path query with the multi-`OPTIONAL MATCH` approach used by `GraphDatabase.traceCrossLanguageChain()` (lines 742-840). The forward direction decomposes into:
   - `MATCH (start)` with name filter
   - `OPTIONAL MATCH shellPath = (start)-[:SOURCES|INVOKES*0..3]->(exScript:ShellScript)` → decompose to `OPTIONAL MATCH (start)-[:SOURCES]->(s1)` and `OPTIONAL MATCH (start)-[:INVOKES]->(s2)` with `UNION` or `UNWIND`
   - `OPTIONAL MATCH (pivot)-[:EXECUTES]->(prog:FortranProgram)`
   - `OPTIONAL MATCH (prog)-[:CALLS*1..N]->(sub)` (single-rel directed — may need undirected fallback)
   - `OPTIONAL MATCH (pivot)-[:INVOKES]->(pyMod:PythonModule)`
   - Assemble results in the same `chain/labels/rels` output format

2. **Neptune-safe variable-length paths**: For single-relationship-type patterns like `[:CALLS*1..N]`, convert directed `->` to undirected `-` with a `WHERE` clause filtering direction (or keep directed if Neptune supports single-rel directed VLP — needs testing). If Neptune rejects even `(a)-[:CALLS*1..3]->(b)`, use undirected `(a)-[:CALLS*1..3]-(b)` with label-based direction filtering.

3. **Replace `labels(n)[0]` with `head(labels(n))`**: Neptune may return labels differently; `head()` is safer and more portable.

4. **Replace `length(path)` with `size(nodes(path))-1`**: Neptune does not support `length(path)`.

**Method**: `findUpstreamExecutors(fortranName)`

**Specific Changes**:
5. **Decompose multi-rel variable-length path**: Replace `(jjob:ShellScript)-[:SOURCES|INVOKES*1..3]->(script)` with separate OPTIONAL MATCH clauses:
   - `OPTIONAL MATCH (jjob:ShellScript)-[:SOURCES]->(script)` 
   - `OPTIONAL MATCH (jjob:ShellScript)-[:INVOKES]->(script)`
   - `OPTIONAL MATCH (jjob:ShellScript)-[:SOURCES]->()-[:SOURCES]->(script)` (2-hop)
   - Or use undirected `(jjob)-[:SOURCES|INVOKES*1..3]-(script)` with direction filtering

**Other affected methods** (same pattern — directed VLP with single rel type):
6. **`traceCallChain`**: `[:CALLS*1..N]->` — test if Neptune accepts single-rel directed VLP; if not, convert to undirected with label filter
7. **`traceScriptChain`**: `[:SOURCES|INVOKES*1..N]->` — multi-rel, needs decomposition
8. **`tracePythonCallChain`**: `[:CALLS*1..N]->` — same as traceCallChain
9. **`traceFortranCallChain`**: `[:CALLS*1..N]->` — same as traceCallChain
10. **`findDependencyGraph`**: `[:IMPORTS*1..N]->` — single-rel directed VLP
11. **`findCircularDependencies`**: `[:IMPORTS*2..N]->` — single-rel directed VLP

**Alternative approach — Cypher rewriter in `apoc-transform.js`**:
Instead of rewriting each method individually, add a Neptune Cypher compatibility transform that runs in `NeptuneAdapter.query()` alongside `transformApoc()`. This transform would:
- Detect directed variable-length patterns via regex
- Convert `->[:REL*M..N]->` to `-[:REL*M..N]-` (undirected)
- Add `WHERE` clauses for direction filtering where needed
- Handle multi-rel patterns by decomposing or converting to undirected

This approach is riskier (regex-based Cypher rewriting is fragile) but fixes all methods at once. The recommended approach is to rewrite the critical methods (`traceCrossLanguageChain`, `findUpstreamExecutors`) explicitly and add the Cypher rewriter as a safety net for any remaining patterns.

---

**File**: `mcp_server_node/src/mcp-http-server.js`

**Section**: Per-request handler (lines 60-72)

**Specific Changes**:
1. **Inject GGSR into per-request instances**: After injecting `sharedDataAccess`, also inject `sharedGGSR` and create a shared `GraphGuidedRetrieval` instance:
   ```
   if (sharedGGSR) {
     if (mcp.codeAnalysisTools) {
       mcp.codeAnalysisTools.ggsr = sharedGGSR;
       mcp.codeAnalysisTools.retrieval = sharedRetrieval;
     }
     if (mcp.graphRAGTools) {
       mcp.graphRAGTools.ggsr = sharedGGSR;
       mcp.graphRAGTools.retrieval = sharedRetrieval;
     }
   }
   ```

2. **Create shared `GraphGuidedRetrieval` alongside `sharedGGSR`**: In the initialization block (lines 88-95), after creating `sharedGGSR`, also create a `sharedRetrieval` instance:
   ```
   const { GraphGuidedRetrieval } = await import('./graphrag/GraphGuidedRetrieval.js');
   sharedRetrieval = new GraphGuidedRetrieval({
     dataAccess: sharedDataAccess,
     ggsr: sharedGGSR,
     vectorDB: sharedDataAccess.vectorDB || null,
   });
   ```

3. **Declare `sharedRetrieval`**: Add `let sharedRetrieval = null;` alongside the existing `let sharedGGSR = null;` declaration.

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bugs on unfixed code, then verify the fixes work correctly and preserve existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bugs BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write tests that execute the affected NeptuneAdapter methods against a Neptune endpoint and verify the HTTP handler's GGSR injection. Run these tests on the UNFIXED code to observe failures.

**Test Cases**:
1. **Forward Chain Test**: Call `traceCrossLanguageChain("JGLOBAL_FORECAST", 5, "forward")` on Neptune — expect syntax error (will fail on unfixed code)
2. **Reverse Chain Test**: Call `traceCrossLanguageChain("setuprad", 5, "reverse")` on Neptune — expect syntax error (will fail on unfixed code)
3. **Upstream Executors Test**: Call `findUpstreamExecutors("gsi")` on Neptune — expect syntax error on the `SOURCES|INVOKES*1..3` pattern (will fail on unfixed code)
4. **HTTP GGSR Null Test**: Create a per-request `UnifiedMCPServer` via the HTTP handler and assert `mcp.codeAnalysisTools.ggsr === null` (will confirm bug on unfixed code)
5. **Single-Rel Directed VLP Test**: Call `traceCallChain("forecast", 3)` on Neptune — may fail if Neptune rejects even single-rel directed VLP (will confirm/refute hypothesis)

**Expected Counterexamples**:
- Neptune returns `Invalid input '>'` or `Invalid input '<'` for directed variable-length paths
- Per-request `codeAnalysisTools.ggsr` is `null` despite `sharedGGSR` being initialized
- Possible causes: Neptune openCypher spec does not include directed VLP syntax

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed functions produce the expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  IF input.bugType = 'neptune_syntax' THEN
    result := NeptuneAdapter_fixed.traceCrossLanguageChain(input.name, input.depth, input.direction)
    ASSERT result IS Array
    ASSERT result[0].chain IS Array OF strings
    ASSERT result[0].labels IS Array OF strings
    ASSERT result[0].rels IS Array OF strings
    ASSERT NO Neptune syntax error thrown
  END IF
  IF input.bugType = 'ggsr_injection' THEN
    mcp := createPerRequestMCP(sharedDataAccess, sharedGGSR, sharedRetrieval)
    ASSERT mcp.codeAnalysisTools.ggsr IS NOT null
    ASSERT mcp.graphRAGTools.ggsr IS NOT null
    ASSERT mcp.codeAnalysisTools.retrieval IS NOT null
    ASSERT mcp.graphRAGTools.retrieval IS NOT null
  END IF
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed functions produce the same result as the original functions.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT NeptuneAdapter_original.query(input) = NeptuneAdapter_fixed.query(input)
  ASSERT UnifiedMCPServer_original.start() behavior = UnifiedMCPServer_fixed.start() behavior
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many query patterns automatically across the input domain
- It catches edge cases where the Cypher rewriter might incorrectly transform a valid query
- It provides strong guarantees that non-affected methods produce identical results

**Test Plan**: Observe behavior on UNFIXED code first for non-affected queries (e.g., `findImporters`, `findCallers`, `getStatistics`), then write property-based tests capturing that behavior.

**Test Cases**:
1. **Simple Query Preservation**: Verify `findImporters`, `findCallers`, `getStatistics` return identical results before and after fix
2. **APOC Transform Preservation**: Verify all 5 APOC transforms continue to produce correct output
3. **Stdio GGSR Preservation**: Verify `UnifiedMCPServer.start()` still injects GGSR into `codeAnalysisTools` and `graphRAGTools`
4. **Health Endpoint Preservation**: Verify `/health` returns correct response after GGSR injection changes
5. **traceCrossLanguagePath Preservation**: Verify the simpler Shell→Fortran trace continues to work

### Unit Tests

- Test `traceCrossLanguageChain` forward direction returns valid chain structure on Neptune
- Test `traceCrossLanguageChain` reverse direction returns valid chain structure on Neptune
- Test `findUpstreamExecutors` returns triggering J-Jobs without syntax error
- Test HTTP per-request handler injects GGSR into `codeAnalysisTools` and `graphRAGTools`
- Test `sharedRetrieval` is created alongside `sharedGGSR` during initialization
- Test edge cases: empty results when no matching nodes exist, depth=1 minimum

### Property-Based Tests

- Generate random entity names and depths, verify `traceCrossLanguageChain` never throws Neptune syntax errors
- Generate random query strings, verify the Cypher rewriter (if used) only transforms directed VLP patterns and leaves other queries unchanged
- Generate random tool invocations via HTTP, verify GGSR-dependent tools have non-null `ggsr` references

### Integration Tests

- Test full `trace_full_execution_chain` tool invocation on Neptune backend end-to-end
- Test full `get_code_context` tool invocation via HTTP transport end-to-end
- Test that all 45 validated tools continue to pass after both fixes are applied
- Test switching between stdio and HTTP transports produces equivalent GGSR results
