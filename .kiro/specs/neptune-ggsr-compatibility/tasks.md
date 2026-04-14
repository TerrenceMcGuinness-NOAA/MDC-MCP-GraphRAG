# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Neptune Directed VLP Syntax Rejection & Missing HTTP GGSR Injection
  - **CRITICAL**: This test MUST FAIL on unfixed code — failure confirms the bugs exist
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior — it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples demonstrating both C1 (Neptune syntax errors) and C2 (null GGSR injection)
  - **Test file**: `mcp_server_node/test/neptune-ggsr-bug-condition.test.js`
  - **C1 — Neptune Directed VLP Tests** (Scoped PBT):
    - Test `traceCrossLanguageChain(name, depth, 'forward')` — generates `->[:SOURCES|INVOKES|EXECUTES|CALLS*1..N]->` which Neptune rejects
    - Test `traceCrossLanguageChain(name, depth, 'reverse')` — generates `<-[:REL*1..N]<-` which Neptune rejects
    - Test `findUpstreamExecutors(name)` — generates `[:SOURCES|INVOKES*1..3]->` which Neptune rejects
    - Test `traceCallChain(name, depth)` — generates `[:CALLS*1..N]->` directed VLP
    - Test `traceScriptChain(name, depth)` — generates `[:SOURCES|INVOKES*1..N]->` directed VLP
    - Test `tracePythonCallChain(name, depth)` — generates `[:CALLS*1..N]->` directed VLP
    - Test `traceFortranCallChain(name, depth)` — generates `[:CALLS*1..N]->` directed VLP
    - Test `findDependencyGraph(path, depth)` — generates `[:IMPORTS*1..N]->` directed VLP
    - Test `findCircularDependencies(depth)` — generates `[:IMPORTS*2..N]->` directed VLP
    - Use fast-check to generate random entity names and depths (1-10), assert no Neptune syntax error thrown
    - Assert results contain expected structure: `chain` (array), `labels` (array), `rels` (array) for traceCrossLanguageChain
  - **C2 — HTTP GGSR Injection Tests**:
    - Create per-request `UnifiedMCPServer` via the HTTP handler pattern (from `mcp-http-server.js` lines 60-72)
    - Assert `mcp.codeAnalysisTools.ggsr === null` on unfixed code (confirms bug)
    - Assert `mcp.graphRAGTools.ggsr === null` on unfixed code (confirms bug)
    - Assert `mcp.codeAnalysisTools.retrieval === null` on unfixed code (confirms bug)
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Tests FAIL (this is correct — it proves the bugs exist)
  - Document counterexamples found (e.g., "traceCrossLanguageChain('JGLOBAL_FORECAST', 5, 'forward') throws Neptune syntax error")
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Non-Affected Queries and Stdio GGSR Unchanged
  - **IMPORTANT**: Follow observation-first methodology
  - **Test file**: `mcp_server_node/test/neptune-ggsr-preservation.test.js`
  - **Observe on UNFIXED code first**, then write property-based tests:
  - **Query Preservation Tests**:
    - Observe: `findImporters(moduleName)` returns correct results on unfixed code
    - Observe: `findCallers(functionName)` returns correct results on unfixed code
    - Observe: `getStatistics()` returns `{ nodes, relationships }` on unfixed code
    - Observe: `traceCrossLanguagePath(scriptName, depth)` returns correct results (uses compatible MATCH/OPTIONAL MATCH)
    - Observe: `findScriptCallers(name)` returns correct results (single-hop, no VLP)
    - Observe: `findFortranCallers(name)` returns correct results (single-hop, no VLP)
    - Observe: `healthCheck()` returns `{ status, connected, nodeCount }` on unfixed code
    - Write property-based test: for all non-VLP queries, the query method produces identical results before and after fix
    - Use fast-check to generate random module/function names, verify non-VLP methods never throw and return consistent structure
  - **APOC Transform Preservation Tests**:
    - Observe: `transformApoc('MATCH (n) RETURN n')` returns input unchanged (no APOC)
    - Observe: all 5 APOC transforms produce correct output
    - Write property-based test: for all queries NOT containing `apoc.`, `transformApoc` returns input unchanged
  - **Stdio GGSR Preservation Tests**:
    - Observe: `UnifiedMCPServer.start()` injects GGSR into `codeAnalysisTools` and `graphRAGTools`
    - Write test asserting stdio transport initialization path is unchanged
  - **Health Endpoint Preservation**:
    - Observe: `/health` returns `{ status: 'ok', tools: 51, dataAccess: boolean }`
    - Write test asserting health endpoint response structure is unchanged after GGSR injection changes
  - **`labels()` Compatibility Preservation**:
    - Observe: methods using `labels(n)[0]` (e.g., `findCallers`, `findScriptCallers`, `findFortranCallers`) return correct label strings
    - Write test: for all single-hop queries returning labels, verify `head(labels(n))` produces same result as `labels(n)[0]`
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

- [x] 3. Fix Neptune GGSR Compatibility Bugs

  - [x] 3.1 Rewrite `NeptuneAdapter.traceCrossLanguageChain()` to decomposed multi-OPTIONAL-MATCH approach
    - Replace single directed VLP query `->[:SOURCES|INVOKES|EXECUTES|CALLS*1..N]->` with decomposed approach matching `GraphDatabase.traceCrossLanguageChain()` (lines 742-840)
    - Forward direction: decompose into `MATCH (start)` → `OPTIONAL MATCH shellPath = (start)-[:SOURCES|INVOKES*0..3]->(exScript:ShellScript)` → `OPTIONAL MATCH (pivot)-[:EXECUTES]->(prog:FortranProgram)` → `OPTIONAL MATCH (prog)-[:CALLS*1..N]->(sub)` → `OPTIONAL MATCH (pivot)-[:INVOKES]->(pyMod:PythonModule)`
    - Reverse direction: decompose into `MATCH (target)` → `OPTIONAL MATCH (target)<-[:CALLS*0..N]-(prog:FortranProgram)` → `OPTIONAL MATCH (prog)<-[:EXECUTES]-(script)` → `OPTIONAL MATCH callerPath = (jjob:ShellScript)-[:SOURCES|INVOKES*1..3]->(script)`
    - Assemble results in same `chain/labels/rels` output format as original method
    - Use undirected VLP `-[:REL*1..N]-` where Neptune rejects directed, with label-based filtering
    - _Bug_Condition: isBugCondition(input) where input.queryType contains directed VLP AND backend = 'neptune'_
    - _Expected_Behavior: Returns array of {chain, labels, rels} objects matching GraphDatabase output structure_
    - _Preservation: traceCrossLanguagePath() must remain unchanged (already compatible)_
    - _Requirements: 2.1, 2.2_

  - [x] 3.2 Decompose `findUpstreamExecutors()` multi-rel directed VLP
    - Replace `(jjob:ShellScript)-[:SOURCES|INVOKES*1..3]->(script)` with separate OPTIONAL MATCH clauses per relationship type
    - Pattern: `OPTIONAL MATCH (jjob:ShellScript)-[:SOURCES]->(script)` + `OPTIONAL MATCH (jjob:ShellScript)-[:INVOKES]->(script)` + multi-hop variants
    - Or use undirected `(jjob)-[:SOURCES|INVOKES*1..3]-(script)` with `WHERE` direction filtering
    - Replace `labels(script)[0]` with `head(labels(script))` for Neptune compatibility
    - _Bug_Condition: isBugCondition(input) where query contains [:SOURCES|INVOKES*1..3]->_
    - _Expected_Behavior: Returns {program, executor_script, script_label, triggering_jjobs} without syntax error_
    - _Preservation: Single-hop EXECUTES match must remain unchanged_
    - _Requirements: 2.1_

  - [x] 3.3 Fix remaining directed VLP methods in NeptuneAdapter
    - **`traceCallChain`** (line 182): Replace `(f:Function {name: $name})-[:CALLS*1..N]->(callee)` — convert directed `->` to undirected `-` or decompose
    - **`traceScriptChain`** (line 319): Replace `(s {name: $name})-[:SOURCES|INVOKES*1..N]->(child)` — multi-rel, needs decomposition into separate MATCH clauses
    - **`tracePythonCallChain`** (line 358): Replace `(f:PythonFunction {name: $name})-[:CALLS*1..N]->(callee)` — same pattern as traceCallChain
    - **`traceFortranCallChain`** (line 385): Replace `(f {name: $name})-[:CALLS*1..N]->(callee)` — same pattern, also fix `labels(n)[0]` → `head(labels(n))`
    - **`findDependencyGraph`** (line 223): Replace `(f:File {path: $filePath})-[:IMPORTS*1..N]->(dep)` — single-rel directed VLP
    - **`findCircularDependencies`** (line 231): Replace `(f:File)-[:IMPORTS*2..N]->(f)` — single-rel directed VLP for cycle detection
    - Replace all `labels(n)[0]` with `head(labels(n))` across affected methods
    - Replace any `length(path)` with `size(nodes(path))-1` if present
    - _Bug_Condition: All methods generate directed VLP patterns rejected by Neptune_
    - _Expected_Behavior: All methods return correct results using Neptune-compatible Cypher_
    - _Preservation: Non-VLP methods (findCallers, findImporters, etc.) must remain unchanged_
    - _Requirements: 2.1_

  - [x] 3.4 Fix `labels(n)[0]` in non-VLP methods for Neptune portability
    - **`findCallers`** (line 191): Replace `labels(caller)[0]` with `head(labels(caller))`
    - **`findScriptCallers`** (line 311): Replace `labels(caller)[0]` with `head(labels(caller))`
    - **`findFortranCallers`** (line 377): Replace `labels(caller)[0]` with `head(labels(caller))`
    - These are single-hop queries that work on Neptune but use `labels()[0]` which may behave differently
    - _Bug_Condition: Neptune labels() indexing may differ from Neo4j_
    - _Expected_Behavior: head(labels(n)) returns first label consistently on both backends_
    - _Preservation: Query logic and output structure must remain identical_
    - _Requirements: 2.1_

  - [x] 3.5 Inject `sharedGGSR` and `sharedRetrieval` into HTTP per-request instances
    - In `mcp-http-server.js`, add `let sharedRetrieval = null;` alongside existing `let sharedGGSR = null;`
    - In initialization block (after `sharedGGSR` creation), create `sharedRetrieval`:
      ```
      const { GraphGuidedRetrieval } = await import('./graphrag/GraphGuidedRetrieval.js');
      sharedRetrieval = new GraphGuidedRetrieval({ dataAccess: sharedDataAccess, ggsr: sharedGGSR, vectorDB: sharedDataAccess.vectorDB || null });
      ```
    - In per-request handler (after `sharedDataAccess` injection), inject GGSR:
      ```
      if (sharedGGSR) {
        if (mcp.codeAnalysisTools) { mcp.codeAnalysisTools.ggsr = sharedGGSR; mcp.codeAnalysisTools.retrieval = sharedRetrieval; }
        if (mcp.graphRAGTools) { mcp.graphRAGTools.ggsr = sharedGGSR; mcp.graphRAGTools.retrieval = sharedRetrieval; }
      }
      ```
    - _Bug_Condition: isBugCondition(input) where transport = 'http' AND perRequestInstance.codeAnalysisTools.ggsr = null_
    - _Expected_Behavior: Per-request instances have non-null ggsr and retrieval references_
    - _Preservation: Stdio transport initialization via UnifiedMCPServer.start() must remain unchanged_
    - _Requirements: 2.3, 2.4_

  - [x] 3.6 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Neptune Queries Return Valid Results & HTTP GGSR Injected
    - **IMPORTANT**: Re-run the SAME test from task 1 — do NOT write a new test
    - The test from task 1 encodes the expected behavior
    - When this test passes, it confirms the expected behavior is satisfied:
      - `traceCrossLanguageChain` returns `{chain, labels, rels}` arrays without syntax error
      - `findUpstreamExecutors` returns results without syntax error
      - All other VLP methods execute without Neptune syntax errors
      - HTTP per-request `codeAnalysisTools.ggsr !== null` and `graphRAGTools.ggsr !== null`
    - Run bug condition exploration test from task 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms bugs are fixed)
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 3.7 Verify preservation tests still pass
    - **Property 2: Preservation** - Non-Affected Queries and Stdio GGSR Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Run preservation property tests from task 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm all tests still pass after fix:
      - Non-VLP queries (`findImporters`, `findCallers`, `getStatistics`, etc.) return identical results
      - APOC transforms continue to function
      - Stdio transport GGSR injection unchanged
      - `/health` endpoint responds correctly
      - `traceCrossLanguagePath()` still works
      - `GGSRTraversalPrototypes` methods still work

- [x] 4. Checkpoint - Ensure all tests pass
  - Run full test suite: `npx vitest run` from `mcp_server_node/`
  - Verify bug condition exploration test (task 1) passes — confirms bugs are fixed
  - Verify preservation tests (task 2) pass — confirms no regressions
  - Verify existing test suite passes (if applicable)
  - Ensure all Neptune-incompatible directed VLP patterns have been eliminated from NeptuneAdapter
  - Ask the user if questions arise
