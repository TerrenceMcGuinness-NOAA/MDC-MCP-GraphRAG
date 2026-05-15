# Bugfix Requirements Document

## Introduction

The AWS-ported MCP server (`mdc-mcp-rag-aws`) running with `DB_BACKEND=aws` against Neptune has two related bugs that prevent the Graph-Guided Semantic Retrieval (GGSR) algorithm from functioning correctly. Bug 1: `NeptuneAdapter.traceCrossLanguageChain()` generates directed variable-length path syntax (`->[:REL*1..N]->`) that Neptune's openCypher rejects. Bug 2: The HTTP wrapper (`mcp-http-server.js`) initializes a shared GGSR instance but never injects it into per-request `UnifiedMCPServer` instances, so tools like `get_code_context` return degraded results without GGSR neighborhood data. Together these bugs break the `trace_full_execution_chain` and `get_code_context` tools on the AWS backend.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN `trace_full_execution_chain` is called with any entity name (e.g., `"JGLOBAL_FORECAST"`) on the Neptune backend THEN the system returns a Neptune query syntax error (`Invalid input '>'`) because `NeptuneAdapter.traceCrossLanguageChain()` generates directed variable-length path patterns (`->[:SOURCES|INVOKES|EXECUTES|CALLS*1..5]->`) that Neptune's openCypher does not support

1.2 WHEN `trace_full_execution_chain` is called with `direction = 'reverse'` on the Neptune backend THEN the system returns a Neptune query syntax error (`Invalid input '<'`) because the reverse path pattern (`<-[:REL*1..N]<-`) is also unsupported by Neptune

1.3 WHEN `get_code_context` is called via the HTTP wrapper (`mcp-http-server.js`) for any symbol (e.g., `"setuprad"`) THEN the system returns incomplete results without GGSR neighborhood data because the shared `sharedGGSR` instance is never injected into the per-request `UnifiedMCPServer` instances' `graphRAGTools` and `codeAnalysisTools` modules

1.4 WHEN any GGSR traversal method (`crossLanguageTrace`, `budgetAwareNeighborhood`) is invoked via the HTTP wrapper THEN the system either fails or returns degraded results because the per-request tool module instances have `this.ggsr = null` and `this.retrieval = null`

### Expected Behavior (Correct)

2.1 WHEN `trace_full_execution_chain` is called with any entity name on the Neptune backend THEN the system SHALL return a multi-language execution tree (matching the legacy structure of nodes, languages, and bridge crossings) by using Neptune-compatible Cypher that decomposes the directed variable-length path into separate MATCH clauses per relationship segment (mirroring the multi-OPTIONAL-MATCH approach used in `GraphDatabase.traceCrossLanguageChain()`)

2.2 WHEN `trace_full_execution_chain` is called with `direction = 'reverse'` on the Neptune backend THEN the system SHALL return the reverse execution chain using Neptune-compatible Cypher with reversed relationship direction in individual MATCH clauses rather than a single directed variable-length path

2.3 WHEN `get_code_context` is called via the HTTP wrapper for any symbol THEN the system SHALL return full GGSR neighborhood data (graph neighborhood with community summaries) by injecting the shared `sharedGGSR` instance and a corresponding `GraphGuidedRetrieval` instance into the per-request `UnifiedMCPServer`'s `graphRAGTools` and `codeAnalysisTools` modules

2.4 WHEN any GGSR traversal method is invoked via the HTTP wrapper THEN the system SHALL produce results equivalent to the stdio transport by ensuring the per-request tool modules have valid `ggsr` and `retrieval` references from the shared initialization

### Unchanged Behavior (Regression Prevention)

3.1 WHEN any of the existing 45 validated tools are called on the Neptune backend THEN the system SHALL CONTINUE TO return correct results (the existing 45/45 tool validation must continue to pass)

3.2 WHEN `NeptuneAdapter.traceCrossLanguagePath()` is called (the simpler Shell→Fortran-only trace) THEN the system SHALL CONTINUE TO work correctly since it uses a compatible MATCH/OPTIONAL-MATCH pattern that Neptune already supports

3.3 WHEN the MCP server is started via stdio transport (not HTTP wrapper) THEN the system SHALL CONTINUE TO initialize GGSR via `UnifiedMCPServer.start()` and inject it into tool modules as before

3.4 WHEN queries containing `CALL apoc.*` procedures are executed on Neptune THEN the system SHALL CONTINUE TO transform them via the existing 5 APOC transforms in `apoc-transform.js`

3.5 WHEN `NeptuneAdapter.query()` is called with standard openCypher queries (no directed variable-length paths) THEN the system SHALL CONTINUE TO execute them without modification

3.6 WHEN the HTTP wrapper handles `/health` or non-MCP endpoints THEN the system SHALL CONTINUE TO respond correctly without being affected by GGSR injection changes

3.7 WHEN `GGSRTraversalPrototypes` methods (`oneHopNeighborhood`, `twoHopNeighborhood`, `fortranWeightedTraversal`) are called against Neptune THEN the system SHALL CONTINUE TO work correctly since they use undirected or simple directed patterns that Neptune supports
