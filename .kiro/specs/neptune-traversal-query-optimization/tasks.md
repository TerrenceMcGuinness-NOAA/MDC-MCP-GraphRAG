# Implementation Plan: Neptune Traversal Query Optimization

## Overview

This plan implements two complementary query-layer optimizations — UNION ALL
Decomposition and a BFS Walker — to resolve 9 graph-query timeouts in the
cross_language and code_structure benchmark categories. The implementation is
purely internal (no tool API changes, no re-ingestion). Work proceeds from
foundational constants through quick-win UNION ALL fixes, then the BFS Walker
algorithm, strategy integration, multi-tenant scoping, observability, and testing.

## Tasks

- [ ] 1. Add BFS constants and configuration to `_traversal_bounds.py`
  - [-] 1.1 Add `BFS_ACTIVATION_THRESHOLD` and `BFS_FAN_OUT_LIMIT` constants
    - Add two new module-level constants to `mcp_server_python/src/tools/_traversal_bounds.py`
    - `BFS_ACTIVATION_THRESHOLD: int = _int_env("MCP_BFS_ACTIVATION_THRESHOLD", 30)` — degree at which BFS replaces single-query
    - `BFS_FAN_OUT_LIMIT: int = _int_env("MCP_BFS_FAN_OUT_LIMIT", 100)` — max nodes per type per hop
    - Add a `_use_bfs(degree: int | None, requested_depth: int) -> bool` helper function that returns True when degree >= BFS_ACTIVATION_THRESHOLD OR requested_depth > 3 OR degree is None (fail-safe)
    - Export all new symbols in `__all__`
    - _Requirements: 3.1, 3.2, 3.4, 6.1, 6.2, 6.3_

  - [~] 1.2 Write unit tests for BFS constants and `_use_bfs` strategy selector
    - Add tests to `mcp_server_python/tests/unit/test_traversal_bounds.py`
    - Test env-var override parsing for both new constants
    - Test `_use_bfs` returns False when degree < 30 AND depth <= 3
    - Test `_use_bfs` returns True when degree >= 30
    - Test `_use_bfs` returns True when depth > 3 (regardless of degree)
    - Test `_use_bfs` returns True when degree is None (fail-safe)
    - _Requirements: 3.1, 3.2, 6.2_

- [ ] 2. Implement UNION ALL Decomposition for anchor resolution
  - [~] 2.1 Create `resolve_anchor_ids` helper in `_bfs_walker.py`
    - Create new file `mcp_server_python/src/tools/_bfs_walker.py`
    - Implement `resolve_anchor_ids(graph_db, name, *, scope_pred, tenant, timeout_s) -> list[str]` per the design
    - The function issues a UNION ALL query: one branch WHERE `n.name = $name`, one WHERE `n.path = $name`, each with the scope predicate
    - Deduplicate returned node IDs via set
    - Handle timeout errors gracefully (return empty list)
    - Reference the proven pattern from `semantic_search.py::_enrich_with_graph_counts`
    - _Requirements: 1.1, 1.3, 1.4_

  - [~] 2.2 Apply UNION ALL to `trace_data_flow` outgoing query in `graph_rag.py`
    - In `mcp_server_python/src/tools/graph_rag.py`, locate the one-hop outgoing fan-out query in `trace_data_flow` (matches `WHERE source.name = $name OR source.path = $name`)
    - Replace with UNION ALL of two branches: one WHERE `source.name = $name`, one WHERE `source.path = $name`
    - Apply application-side dedup by `(name, type, relType)` and `LIMIT 25` after merging
    - Preserve existing scope predicate and timeout on each branch
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [~] 2.3 Apply UNION ALL to `trace_data_flow` shortestPath anchor in `graph_rag.py`
    - Locate the shortestPath query seed-node lookup in `trace_data_flow` that uses an OR predicate
    - Replace with UNION ALL decomposition or use `resolve_anchor_ids` to pre-resolve the start node, then issue the path query by ID
    - Preserve existing Label_Scope_Predicate and Statement_Timeout
    - _Requirements: 1.1, 1.2, 1.4_

  - [~] 2.4 Apply UNION ALL to `_one_hop_neighbors` anchor in `code_analysis.py`
    - In `mcp_server_python/src/tools/code_analysis.py`, locate `_one_hop_neighbors` (or equivalent) that uses `(a.name = $name OR a.path = $name)`
    - Replace with UNION ALL of two branches, each with scope predicate
    - Application-side dedup + LIMIT after merging
    - _Requirements: 1.1, 1.2, 1.3_

  - [~] 2.5 Write unit tests for UNION ALL decomposition
    - Add tests to `mcp_server_python/tests/unit/test_graph_rag_tools.py` and `test_code_analysis_tools.py`
    - Mock `graph_db.query` to verify the emitted Cypher contains `UNION ALL` (not `OR`)
    - Verify result deduplication: inject overlapping rows from both branches, assert no duplicates in output
    - Verify scope predicate is present on both branches
    - Verify timeout parameter is passed through
    - _Requirements: 1.1, 1.3, 1.4, 1.5_

- [~] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Implement BFS Walker algorithm
  - [~] 4.1 Implement `BFSResult` dataclass in `_bfs_walker.py`
    - Define `@dataclass(frozen=True, slots=True)` with fields: `nodes: list[dict[str, Any]]`, `hops_expanded: int`, `queries_issued: int`, `wall_clock_ms: int`, `truncated: bool`
    - Each node dict carries: `name`, `path`, `labels`, `hop`, `relType`, `direction`
    - _Requirements: 2.1_

  - [~] 4.2 Implement `_expand_one_hop` helper in `_bfs_walker.py`
    - Single-type, single-hop, bounded expansion function
    - Takes frontier IDs, edge type, direction, fan_out_limit, scope predicate for target, tenant, timeout
    - Builds Cypher pattern based on direction (`forward` → `(a)-[:TYPE]->(b)`, `reverse` → `(b)-[:TYPE]->(a)`)
    - Applies scope_pred to target node `b` (replacing `(n)` with `(b)` in the predicate string)
    - Carries `LIMIT fan_out_limit` to bound result set
    - Returns list of node dicts or empty list on error
    - _Requirements: 2.2, 2.3, 2.6_

  - [~] 4.3 Implement `bfs_walk` main function in `_bfs_walker.py`
    - Signature per design: `async def bfs_walk(graph_db, *, start_name, direction, edge_types, max_depth, fan_out_limit, result_limit, timeout_s, scope_pred, tenant, label_scope_expanded) -> BFSResult`
    - Step 1: Resolve anchor via `resolve_anchor_ids`
    - Step 2: Initialize visited set with anchor IDs, frontier with anchor IDs
    - Step 3: BFS loop — for each depth level, expand all edge types via `asyncio.gather` on `_expand_one_hop` calls
    - Track visited-set across hops (cycle prevention)
    - Early termination when hop produces zero new nodes
    - Global result cap at `result_limit`
    - Overall wall-clock bounded by `asyncio.wait_for` with `timeout_s`
    - On timeout, set `truncated=True` and return partial results
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.7_

  - [~] 4.4 Write unit tests for `bfs_walk` and `_expand_one_hop`
    - Add `mcp_server_python/tests/unit/test_bfs_walker.py`
    - Test basic 2-hop traversal with mock graph — verify correct nodes discovered
    - Test cycle prevention: mock graph with A→B→A, verify no infinite loop, no duplicate nodes
    - Test early termination: hop produces zero new nodes, BFS stops
    - Test fan-out limit caps per-hop results
    - Test overall timeout triggers truncated=True
    - Test result_limit caps total output
    - Test direction handling (forward vs reverse patterns)
    - _Requirements: 2.1, 2.3, 2.4, 2.5, 2.7_

- [ ] 5. Integrate strategy selector into traversal tools
  - [~] 5.1 Integrate BFS Walker into `_cross_language_nodes` in `code_analysis.py`
    - Locate `_cross_language_nodes` (called by `trace_full_execution_chain`)
    - After the degree probe, add strategy selection: if `_use_bfs(degree, requested_depth)` → call `bfs_walk` with the cross-language edge set
    - Else if `is_hub(degree)` → existing Degraded_Result (unchanged)
    - Else → existing single-query variable-length pattern (unchanged)
    - Format BFS result into the same markdown structure as the existing tool output
    - _Requirements: 3.1, 3.2, 5.1, 5.5_

  - [~] 5.2 Integrate BFS Walker into `trace_data_flow` in `graph_rag.py`
    - After the degree probe in `trace_data_flow`, add the same strategy selector
    - When BFS is selected, call `bfs_walk` with the data-flow edge types and format results
    - Preserve the existing shortestPath query (already UNION-ALL'd from task 2.3) for the `to_symbol` path
    - _Requirements: 3.1, 3.2, 5.1_

  - [~] 5.3 Integrate BFS Walker into `find_callers_callees` in `code_analysis.py`
    - After the degree probe, add strategy selection
    - When BFS is selected, run `bfs_walk` with direction=forward for callees and direction=reverse for callers
    - Format results to match existing output structure
    - _Requirements: 3.1, 3.2, 5.1_

  - [~] 5.4 Add timeout fallback chain (single-query → BFS → Degraded_Result)
    - In each tool's single-query path, catch timeout exceptions
    - On timeout, attempt BFS Walker as fallback before falling through to Degraded_Result
    - If BFS also times out, fall through to existing Degraded_Result behavior
    - _Requirements: 3.3, 5.5_

  - [~] 5.5 Write unit tests for strategy integration
    - Test that degree < 30 AND depth ≤ 3 uses single-query path (mock verifies no `bfs_walk` call)
    - Test that degree >= 30 triggers BFS path (mock verifies `bfs_walk` is called)
    - Test that depth > 3 triggers BFS regardless of degree
    - Test hub degree (>= 100) still produces Degraded_Result (unchanged behavior)
    - Test timeout fallback chain: single-query timeout → BFS attempt → Degraded_Result
    - _Requirements: 3.1, 3.2, 3.3, 5.1, 5.5_

- [~] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Apply Label-Scope Predicate on expanded nodes
  - [~] 7.1 Add scope predicate to BFS Walker expansion queries
    - In `_expand_one_hop`, when `label_scope_expanded=True` and a non-default tenant is active, include the Label_Scope_Predicate on the target node `b`
    - For the default `gw` tenant (no prefix), omit the filter (pass empty scope_pred)
    - Use the `_scope_and` / `tenant_label_predicate` helper from `src/tenancy/resolver.py`
    - _Requirements: 4.1, 4.3, 4.4_

  - [~] 7.2 Add scope predicate to terminal node in single-query patterns
    - In the existing single-query variable-length patterns (used when BFS is not activated), ensure the Label_Scope_Predicate is applied to the terminal node of the path pattern
    - Verify the predicate is already present (from bounded-graph-traversal [8.36.0]); add it if missing
    - _Requirements: 4.2, 4.4_

  - [~] 7.3 Write unit tests for label-scope on expanded nodes
    - Test non-default tenant: mock verifies scope predicate appears in expansion query on target node
    - Test default tenant: mock verifies no scope predicate on expansion queries
    - Test consistency: same `_scope_and` output used for both anchor and expanded nodes
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [ ] 8. Add observability logging for BFS activation
  - [~] 8.1 Add BFS activation and completion logging
    - In the BFS Walker (or strategy selector), log at `info` level when BFS activates: tool name, anchor name, measured degree, threshold, direction, max_depth
    - On completion, log: total nodes discovered, queries issued, wall-clock ms
    - Log even when zero nodes discovered (for tuning visibility)
    - Ensure no tenant credentials or full payloads in log output
    - _Requirements: 8.1, 8.2, 8.3_

  - [~] 8.2 Add `[optimized: BFS walker, N hops, M nodes]` response header
    - When BFS is used, prepend a brief indicator line to the tool's markdown response
    - Format: `[optimized: BFS walker, N hops, M nodes, Xms]`
    - When single-query is used, no indicator (unchanged behavior)
    - _Requirements: 8.4_

  - [~] 8.3 Write unit tests for observability
    - Capture log output; verify activation log contains required fields (tool, anchor, degree, threshold)
    - Verify completion log contains required fields (nodes, queries, wall_ms)
    - Verify response header is present when BFS is used and absent when single-query is used
    - Verify no credentials leak in log output
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

- [~] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Write property-based tests
  - [~] 10.1 Write property test for UNION ALL set equivalence
    - **Property 1: UNION ALL Set Equivalence**
    - **Validates: Requirements 1.3**
    - File: `mcp_server_python/tests/properties/test_bfs_walker_props.py`
    - Generate random (name, path) pairs; run both OR-query and UNION ALL against a mock; assert set equality of returned IDs
    - Use Hypothesis with `@settings(max_examples=100)`

  - [~] 10.2 Write property test for BFS subset guarantee
    - **Property 2: BFS Subset Guarantee**
    - **Validates: Requirements 2.7**
    - Generate random DAGs (Hypothesis `st.data()` + adjacency lists); run BFS + equivalent single-expansion; assert BFS result ⊆ single-expansion result

  - [~] 10.3 Write property test for visited-set cycle prevention
    - **Property 3: BFS Visited-Set Prevents Cycles**
    - **Validates: Requirements 2.4**
    - Generate random cyclic graphs; run BFS; assert termination (completes within timeout), no duplicate node IDs in output

  - [~] 10.4 Write property test for early termination
    - **Property 4: BFS Early Termination**
    - **Validates: Requirements 2.5**
    - Generate graphs with dead-end branches (nodes with no outgoing edges at some depth); assert BFS stops immediately when frontier is empty

  - [~] 10.5 Write property test for strategy selection consistency
    - **Property 5: Strategy Selection Consistency**
    - **Validates: Requirements 3.1, 5.1**
    - Generate (degree, depth) pairs in full int range; assert `_use_bfs` returns False only when degree < BFS_ACTIVATION_THRESHOLD AND depth <= 3

  - [~] 10.6 Write property test for label scope on expanded nodes
    - **Property 6: Label Scope on Expanded Nodes**
    - **Validates: Requirements 4.1, 4.2**
    - Generate tenant configs (with/without prefix); assert scope predicate presence/absence on target node queries matches tenant type

  - [~] 10.7 Write property test for timeout fallback chain
    - **Property 7: Timeout Fallback Chain**
    - **Validates: Requirements 3.3, 5.5**
    - Inject timeouts at random points in the mock graph_db; assert result is always a valid Degraded_Result (never an unhandled exception)

  - [~] 10.8 Write property test for fan-out limit bounds
    - **Property 8: Fan-Out Limit Bounds Per-Hop Results**
    - **Validates: Requirements 2.3**
    - Generate high-degree hops (mock graph_db returns > FAN_OUT_LIMIT rows before LIMIT); assert per-hop result count ≤ BFS_FAN_OUT_LIMIT

- [ ] 11. Run benchmark validation against live Neptune
  - [~] 11.1 Run failing benchmark cases and verify resolution
    - Execute `mcp_server_python/scripts/run_benchmark.py` targeting cases: `cl_001`, `cl_003`, `cl_004`, `cl_006`, `cl_008`, `cl_010`, `cl_t01`
    - Verify all complete within 30s (no timeouts)
    - Verify `cl_006` and `cl_010` (Root Cause B) complete under 5s
    - _Requirements: 7.1, 7.2, 1.5_

  - [~] 11.2 Run full 68-case benchmark and verify coverage targets
    - Run `mcp_server_python/scripts/run_benchmark.py` with all 68 cases
    - Verify overall coverage ≥ 95% (Requirement 7.4)
    - Verify `cross_language` category = 100% (Requirement 7.2)
    - Verify `code_structure` category ≥ 70% (Requirement 7.3)
    - Verify graph P95 latency ≤ 10,000ms (Requirement 7.5)
    - Confirm no regressions in `semantic_search` and `operational` categories
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

- [~] 12. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The BFS Walker is a new file (`src/tools/_bfs_walker.py`) — no existing file conflicts
- Constants extend the existing `_traversal_bounds.py` file (alongside `FAN_OUT_THRESHOLD`, `TIMEOUT_S`, etc.)
- The UNION ALL pattern is proven in production (`semantic_search.py::_enrich_with_graph_counts`)
- Benchmark tasks (11.x) require live Neptune connectivity — run only when AWS access is available
- The `_scope_and` helper from `src/tenancy/resolver.py` is reused for label scoping

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4", "4.1"] },
    { "id": 3, "tasks": ["2.5", "4.2"] },
    { "id": 4, "tasks": ["4.3"] },
    { "id": 5, "tasks": ["4.4", "5.1", "5.2", "5.3"] },
    { "id": 6, "tasks": ["5.4", "7.1", "7.2"] },
    { "id": 7, "tasks": ["5.5", "7.3", "8.1", "8.2"] },
    { "id": 8, "tasks": ["8.3"] },
    { "id": 9, "tasks": ["10.1", "10.2", "10.3", "10.4", "10.5", "10.6", "10.7", "10.8"] },
    { "id": 10, "tasks": ["11.1"] },
    { "id": 11, "tasks": ["11.2"] }
  ]
}
```
