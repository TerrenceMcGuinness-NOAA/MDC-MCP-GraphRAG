# Implementation Plan: Neptune Traversal Query Optimization

## Overview

This plan implements two complementary query-layer optimizations — UNION ALL
Decomposition and a BFS Walker — to resolve 9 graph-query timeouts in the
cross_language and code_structure benchmark categories. The implementation is
purely internal (no tool API changes, no re-ingestion). Work proceeds from
foundational constants through quick-win UNION ALL fixes, then the BFS Walker
algorithm, strategy integration, multi-tenant scoping, observability, and testing.

## Tasks

- [x] 1. Add BFS constants and configuration to `_traversal_bounds.py`
  - [x] 1.1 Add `BFS_ACTIVATION_THRESHOLD` and `BFS_FAN_OUT_LIMIT` constants
    - Add two new module-level constants to `mcp_server_python/src/tools/_traversal_bounds.py`
    - `BFS_ACTIVATION_THRESHOLD: int = _int_env("MCP_BFS_ACTIVATION_THRESHOLD", 30)` — degree at which BFS replaces single-query
    - `BFS_FAN_OUT_LIMIT: int = _int_env("MCP_BFS_FAN_OUT_LIMIT", 100)` — max nodes per type per hop
    - Add a `_use_bfs(degree: int | None, requested_depth: int) -> bool` helper function that returns True when degree >= BFS_ACTIVATION_THRESHOLD OR requested_depth > 3 OR degree is None (fail-safe)
    - Export all new symbols in `__all__`
    - _Requirements: 3.1, 3.2, 3.4, 6.1, 6.2, 6.3_

  - [x] 1.2 Write unit tests for BFS constants and `_use_bfs` strategy selector
    - Add tests to `mcp_server_python/tests/unit/test_traversal_bounds.py`
    - Test env-var override parsing for both new constants
    - Test `_use_bfs` returns False when degree < 30 AND depth <= 3
    - Test `_use_bfs` returns True when degree >= 30
    - Test `_use_bfs` returns True when depth > 3 (regardless of degree)
    - Test `_use_bfs` returns True when degree is None (fail-safe)
    - _Requirements: 3.1, 3.2, 6.2_

- [x] 2. Implement UNION ALL Decomposition for anchor resolution
  - [x] 2.1 Create `resolve_anchor_ids` helper in `_bfs_walker.py`
    - Create new file `mcp_server_python/src/tools/_bfs_walker.py`
    - Implement `resolve_anchor_ids(graph_db, name, *, scope_pred, tenant, timeout_s) -> list[str]` per the design
    - The function issues a UNION ALL query: one branch WHERE `n.name = $name`, one WHERE `n.path = $name`, each with the scope predicate
    - Deduplicate returned node IDs via set
    - Handle timeout errors gracefully (return empty list)
    - Reference the proven pattern from `semantic_search.py::_enrich_with_graph_counts`
    - _Requirements: 1.1, 1.3, 1.4_

  - [x] 2.2 Apply UNION ALL to `trace_data_flow` outgoing query in `graph_rag.py`
    - In `mcp_server_python/src/tools/graph_rag.py`, locate the one-hop outgoing fan-out query in `trace_data_flow` (matches `WHERE source.name = $name OR source.path = $name`)
    - Replace with UNION ALL of two branches: one WHERE `source.name = $name`, one WHERE `source.path = $name`
    - Apply application-side dedup by `(name, type, relType)` and `LIMIT 25` after merging
    - Preserve existing scope predicate and timeout on each branch
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [x] 2.3 Apply UNION ALL to `trace_data_flow` shortestPath anchor in `graph_rag.py`
    - Locate the shortestPath query seed-node lookup in `trace_data_flow` that uses an OR predicate
    - Replace with UNION ALL decomposition or use `resolve_anchor_ids` to pre-resolve the start node, then issue the path query by ID
    - Preserve existing Label_Scope_Predicate and Statement_Timeout
    - _Requirements: 1.1, 1.2, 1.4_

  - [x] 2.4 Apply UNION ALL to `_one_hop_neighbors` anchor in `code_analysis.py`
    - In `mcp_server_python/src/tools/code_analysis.py`, locate `_one_hop_neighbors` (or equivalent) that uses `(a.name = $name OR a.path = $name)`
    - Replace with UNION ALL of two branches, each with scope predicate
    - Application-side dedup + LIMIT after merging
    - _Requirements: 1.1, 1.2, 1.3_

  - [x] 2.5 Write unit tests for UNION ALL decomposition
    - Add tests to `mcp_server_python/tests/unit/test_graph_rag_tools.py` and `test_code_analysis_tools.py`
    - Mock `graph_db.query` to verify the emitted Cypher contains `UNION ALL` (not `OR`)
    - Verify result deduplication: inject overlapping rows from both branches, assert no duplicates in output
    - Verify scope predicate is present on both branches
    - Verify timeout parameter is passed through
    - _Requirements: 1.1, 1.3, 1.4, 1.5_

  - [x] 2.6 Apply UNION ALL to the `anchor_degree` probe in `_traversal_bounds.py`
    - Follow-on site found by the task 11.1 live benchmark: the degree probe's own `(a.name = $name OR a.path = $name)` anchor is the dominant remaining graph cost (~11.25s/call, 78.8s of the run's 110s graph time), blocking Requirement 1.5
    - Resolve the anchor via `resolve_anchor_ids` (UNION ALL, index-seekable) then count edges by `id(a) IN $ids`, matching the pattern `_expand_one_hop` already uses
    - A naive UNION ALL of two `count(r)` branches double-counts a node matching on both `name` and `path`; id-resolution-then-count is set-correct by construction
    - Extend `resolve_anchor_ids` with a node-variable parameter (so the probe keeps its `a` variable and the caller's `_scope_and("a")` fragment needs no retargeting) and a failure sink (so a resolution timeout stays distinguishable from "no match")
    - Preserve the probe's fail-safe exactly: `0` for no edges / no `deg` / unresolvable anchor, `None` only on raise or timeout
    - Preserve the Label_Scope_Predicate and Statement_Timeout on every branch
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 5.2, 5.3_

  - [x] 2.7 Apply UNION ALL to `_cross_language_seed_row` in `code_analysis.py`
    - Follow-on site found by the task 11.1 live benchmark: 7.3s total across 7 calls
    - Replace `(n.name = $name OR n.path = $name)` with two `LIMIT 1` branches joined by `UNION ALL`, taking the first row application-side
    - Preserve the Label_Scope_Predicate on both branches and the Statement_Timeout on the query
    - Preserve the existing `[]`-on-no-resolve contract and the propagate-on-error behaviour the BFS fallback depends on
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 5.2_

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement BFS Walker algorithm
  - [x] 4.1 Implement `BFSResult` dataclass in `_bfs_walker.py`
    - Define `@dataclass(frozen=True, slots=True)` with fields: `nodes: list[dict[str, Any]]`, `hops_expanded: int`, `queries_issued: int`, `wall_clock_ms: int`, `truncated: bool`
    - Each node dict carries: `name`, `path`, `labels`, `hop`, `relType`, `direction`
    - _Requirements: 2.1_

  - [x] 4.2 Implement `_expand_one_hop` helper in `_bfs_walker.py`
    - Single-type, single-hop, bounded expansion function
    - Takes frontier IDs, edge type, direction, fan_out_limit, scope predicate for target, tenant, timeout
    - Builds Cypher pattern based on direction (`forward` → `(a)-[:TYPE]->(b)`, `reverse` → `(b)-[:TYPE]->(a)`)
    - Applies scope_pred to target node `b` (replacing `(n)` with `(b)` in the predicate string)
    - Carries `LIMIT fan_out_limit` to bound result set
    - Returns list of node dicts or empty list on error
    - _Requirements: 2.2, 2.3, 2.6_

  - [x] 4.3 Implement `bfs_walk` main function in `_bfs_walker.py`
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

  - [x] 4.4 Write unit tests for `bfs_walk` and `_expand_one_hop`
    - Add `mcp_server_python/tests/unit/test_bfs_walker.py`
    - Test basic 2-hop traversal with mock graph — verify correct nodes discovered
    - Test cycle prevention: mock graph with A→B→A, verify no infinite loop, no duplicate nodes
    - Test early termination: hop produces zero new nodes, BFS stops
    - Test fan-out limit caps per-hop results
    - Test overall timeout triggers truncated=True
    - Test result_limit caps total output
    - Test direction handling (forward vs reverse patterns)
    - _Requirements: 2.1, 2.3, 2.4, 2.5, 2.7_

- [x] 5. Integrate strategy selector into traversal tools
  - [x] 5.1 Integrate BFS Walker into `_cross_language_nodes` in `code_analysis.py`
    - Locate `_cross_language_nodes` (called by `trace_full_execution_chain`)
    - After the degree probe, add strategy selection: if `_use_bfs(degree, requested_depth)` → call `bfs_walk` with the cross-language edge set
    - Else if `is_hub(degree)` → existing Degraded_Result (unchanged)
    - Else → existing single-query variable-length pattern (unchanged)
    - Format BFS result into the same markdown structure as the existing tool output
    - _Requirements: 3.1, 3.2, 5.1, 5.5_

  - [x] 5.2 Integrate BFS Walker into `trace_data_flow` in `graph_rag.py`
    - After the degree probe in `trace_data_flow`, add the same strategy selector
    - When BFS is selected, call `bfs_walk` with the data-flow edge types and format results
    - Preserve the existing shortestPath query (already UNION-ALL'd from task 2.3) for the `to_symbol` path
    - _Requirements: 3.1, 3.2, 5.1_

  - [x] 5.3 Integrate BFS Walker into `find_callers_callees` in `code_analysis.py`
    - After the degree probe, add strategy selection
    - When BFS is selected, run `bfs_walk` with direction=forward for callees and direction=reverse for callers
    - Format results to match existing output structure
    - _Requirements: 3.1, 3.2, 5.1_

  - [x] 5.4 Add timeout fallback chain (single-query → BFS → Degraded_Result)
    - In each tool's single-query path, catch timeout exceptions
    - On timeout, attempt BFS Walker as fallback before falling through to Degraded_Result
    - If BFS also times out, fall through to existing Degraded_Result behavior
    - _Requirements: 3.3, 5.5_

  - [x] 5.5 Write unit tests for strategy integration
    - Landed as the **tool-level strategy routing matrix** in
      `mcp_server_python/tests/unit/test_code_analysis_tools.py`, section
      `══ Task 5.5 — tool-level strategy routing matrix ══` (15 tests), and
      `mcp_server_python/tests/unit/test_graph_rag_tools.py`, section
      `══ Task 5.5 — tool-level strategy routing for trace_data_flow ══`
      (5 tests). Previously marked `[-]`; the pure-selector and
      fallback-chain claims were already covered elsewhere (see below), so
      what these add is the routing decision *at the tool boundary*
    - Routing is observed through the **emitted queries**, not by
      monkeypatching `bfs_walk`, because the query shapes are what actually
      reach Neptune and they are unambiguous: the walker's per-type
      single-hop seek (`WHERE id(a) IN $ids` / `RETURN DISTINCT id(b) AS
      nid`), the single query's variable-length `*1..N` pattern, and the
      one-hop Degraded_Result (`RETURN DISTINCT x.name AS name, coalesce(...)`
      plus the "Highly connected node" notice). Degree bands are derived from
      `BFS_ACTIVATION_THRESHOLD` / `FAN_OUT_THRESHOLD` rather than hardcoded,
      so an env override moves the tests with the implementation (R6.1, R6.2)
    - Test that degree < 30 AND depth <= 3 uses single-query path (mock verifies no `bfs_walk` call)
      — **already covered** for the pure selector by Property 5
      (`test_bfs_walker_props.py`, full int range with a boundary band derived
      from `BFS_ACTIVATION_THRESHOLD`) and the truth-table grid in
      `test_traversal_bounds.py`; and at tool level for
      `trace_execution_path` by Property 7's control arm. **Newly landed** at
      tool level for `trace_data_flow` (below-threshold degree keeps the
      UNION_ALL_Decomposed fan-out), `find_callers_callees` (below-threshold
      degree keeps the `(caller)-[:CALLS]->(f)` + `CALLS*1..` pair), and
      `trace_full_execution_chain` (`max_depth=3` with a below-threshold
      degree — the one configuration where that tool keeps the single query).
      Each seeds the walker's rows as well, so a walk that ran anyway would
      surface in the rendered output and be caught
    - Test that degree >= 30 triggers BFS path (mock verifies `bfs_walk` is called)
      — **the identified gap; newly landed.** No test asserted this at tool
      level. Now pinned at the *exact* boundary (`degree ==
      BFS_ACTIVATION_THRESHOLD`, since `>=` versus `>` is what a mid-band
      degree cannot distinguish) for `trace_data_flow` and
      `find_callers_callees`, the latter also asserting the walk runs **once
      per direction per edge type** (a three-type shell edge set yields
      exactly six single-hop expansions, forward and reverse, and no
      interleaved variable-length pattern). `degree == FAN_OUT_THRESHOLD` is
      asserted to *still walk* rather than degrade, because `is_hub` is a
      strict `>` — the "at/above 100" phrasing in the original bullet does not
      match the implementation
    - Test that depth > 3 triggers BFS regardless of degree
      — **partially covered** already: `test_trace_full_execution_chain_clamps_max_depth_to_ceiling`
      exercises the depth arm incidentally. **Newly landed** as an isolated
      pair for `trace_full_execution_chain` — `max_depth=3` versus
      `max_depth=4` with the degree held below the activation threshold, so
      the two tests differ only in requested depth — plus a parametrized
      assertion that at the tool's default `max_depth=5` *every* non-hub
      degree band is walker-produced (5 > 3 fires unconditionally, so that
      tool has no single-query arm at its default and the tests assert that
      rather than pretending otherwise). For `trace_data_flow` the converse is
      pinned: `_OUTGOING_DEPTH` is 1, so a `max_depth=99` request cannot reach
      the depth arm and the fan-out stays on the single query
    - Test hub degree (>= 100) still produces Degraded_Result (unchanged behavior)
      — **newly landed per-tool** (previously only the pre-BFS
      `bounded-graph-traversal` assertions existed, which predate the walker
      and so could not assert "and no walk was attempted"). Now covered for
      `find_callers_callees` and `trace_full_execution_chain` (notice +
      one-hop neighbors, and neither a walk expansion nor a `*1..` pattern
      emitted) and for `trace_data_flow`, whose hub shape differs by design:
      its fan-out is one-hop either way, so the single query still runs and
      the notice *is* the Degraded_Result — what must not happen is a walk.
      Documents the guard order hub -> BFS -> single-query
    - Test timeout fallback chain: single-query timeout → BFS attempt → Degraded_Result
      — **already covered** end-to-end by Property 7
      (`test_bfs_walker_props.py`), which drives
      `code_analysis._tool_trace_execution_path` with timeouts injected into
      any subset of its six query stages and asserts the terminal shape
      (fallback-answered / degraded-answered / `[ERROR]`). **Newly landed** as
      the per-tool link-by-link assertion for `trace_execution_path`: link 2
      (single query times out -> the *walk* is what retries it, asserted on
      the expansion cypher, its rows render, the response carries the
      `[optimized: ...]` indicator and the timeout notice, and the one-hop
      probe is never issued) and link 3 (walk salvages nothing -> the one-hop
      Degraded_Result, with the walk's anchor resolution and expansion proven
      to have been attempted first)
    - NOT covered: the fallback chain per-tool for `find_callers_callees`,
      `trace_full_execution_chain` and `trace_data_flow`. Property 7 covers
      the chain's invariant only through `trace_execution_path`; the other
      three tools' fallback arms have the same shape but no direct test
    - _Requirements: 3.1, 3.2, 3.3, 5.1, 5.5_

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Apply Label-Scope Predicate on expanded nodes
  - [x] 7.1 Add scope predicate to BFS Walker expansion queries
    - In `_expand_one_hop`, when `label_scope_expanded=True` and a non-default tenant is active, include the Label_Scope_Predicate on the target node `b`
    - For the default `gw` tenant (no prefix), omit the filter (pass empty scope_pred)
    - Use the `_scope_and` / `tenant_label_predicate` helper from `src/tenancy/resolver.py`
    - _Requirements: 4.1, 4.3, 4.4_

  - [x] 7.2 Add scope predicate to terminal node in single-query patterns
    - In the existing single-query variable-length patterns (used when BFS is not activated), ensure the Label_Scope_Predicate is applied to the terminal node of the path pattern
    - Verify the predicate is already present (from bounded-graph-traversal [8.36.0]); add it if missing
    - _Requirements: 4.2, 4.4_

  - [x] 7.3 Write unit tests for label-scope on expanded nodes
    - Landed in `mcp_server_python/tests/unit/test_bfs_walker.py`, section
      `══ Task 7.3 — Label_Scope_Predicate on expanded nodes ══` (~390 lines).
      Previously marked `[-]`; the work exists, so the marker was corrected
      during the checkpoint-12 close-out
    - Test non-default tenant: mock verifies scope predicate appears in expansion query on target node
      — COVERED (inclusion form on `labels(b)`, asserted per hop and per edge
      type, and for the reverse pattern where `b` is still the discovered node)
    - Test default tenant: mock verifies no scope predicate on expansion queries
      — COVERED **with a correction to R4.3's wording**: for default `gw` in a
      multi-tenant catalog `tenant_label_predicate` returns the *exclusion* form,
      which is applied to the target (it admits every unprefixed baseline node
      and rejects another tenant's prefixed neighbours). The genuinely-unscoped
      case R4.3 describes — no active tenant context, or no tenant in the catalog
      declaring a prefix — is covered separately, as is the
      `label_scope_expanded=False` opt-out
    - Test consistency: same `_scope_and` output used for both anchor and expanded nodes
      — COVERED structurally for both tenants: the expansion fragment is asserted
      byte-identical to `_scope_and("b")` and to `_retarget_scope_pred(_scope_and("n"), "b")`
    - NOT covered (R4.2, the single-query terminal-node scoping from task 7.2):
      only `code_analysis._one_hop_neighbors` has a direct test. The
      `graph_rag._outgoing_union_cypher` `target_scope_pred` parameter,
      `_call_chain`'s `_scope_and("callee")`, and `_cross_language_nodes`'
      terminal `_scope_and("n")` have no direct test. Property 6
      (`test_bfs_walker_props.py`) covers R4.2 only at the walker level
    - _Requirements: 4.1, 4.2 (partial — see above), 4.3, 4.4_

- [x] 8. Add observability logging for BFS activation
  - [x] 8.1 Add BFS activation and completion logging
    - In the BFS Walker (or strategy selector), log at `info` level when BFS activates: tool name, anchor name, measured degree, threshold, direction, max_depth
    - On completion, log: total nodes discovered, queries issued, wall-clock ms
    - Log even when zero nodes discovered (for tuning visibility)
    - Ensure no tenant credentials or full payloads in log output
    - _Requirements: 8.1, 8.2, 8.3_

  - [x] 8.2 Add `[optimized: BFS walker, N hops, M nodes]` response header
    - When BFS is used, prepend a brief indicator line to the tool's markdown response
    - Format: `[optimized: BFS walker, N hops, M nodes, Xms]`
    - When single-query is used, no indicator (unchanged behavior)
    - _Requirements: 8.4_

  - [x] 8.3 Write unit tests for observability
    - Landed in `mcp_server_python/tests/unit/test_bfs_walker.py`, section
      `══ Task 8.3 — BFS observability (log lines + response indicator) ══`
    - Capture log output; verify activation log contains required fields (tool, anchor, degree, threshold)
      — COVERED via `caplog` scoped to the `src.tools._bfs_walker` logger, plus
      the `tool=unknown` / `degree=unknown` renderings, the `info` level, that the
      line precedes anchor resolution, and that the logged `max_depth` is the
      clamped budget rather than the request
    - Verify completion log contains required fields (nodes, queries, wall_ms)
      — COVERED, with every number asserted equal to the returned `BFSResult`'s,
      and emitted for both zero-node shapes (anchor never resolved; hop found
      nothing) and after a wall-clock truncation
    - Verify response header is present when BFS is used and absent when single-query is used
      — COVERED at the helper level (`bfs_optimized_header` exact format,
      zero-node walk, multi-walk aggregation, `insert_bfs_header` placement after
      the title, no-op with no walk and with empty lines) and at the tool level
      for all four `insert_bfs_header` call sites: `trace_execution_path`
      (Property 7, `test_bfs_walker_props.py`), `find_callers_callees` and
      `trace_full_execution_chain` (`test_code_analysis_tools.py`), and
      `trace_data_flow` (`test_graph_rag_tools.py`), each paired with a
      single-query negative
    - Verify no credentials leak in log output
      — COVERED: a tenant double whose `repr` carries a marker, the scope
      predicate and its label prefix, discovered-node `name` / `path` / labels,
      and the emitted cypher and frontier ids are all asserted absent
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

- [x] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Write property-based tests
  - [x] 10.1 Write property test for UNION ALL set equivalence
    - **Property 1: UNION ALL Set Equivalence**
    - **Validates: Requirements 1.3**
    - File: `mcp_server_python/tests/properties/test_bfs_walker_props.py`
    - Generate random (name, path) pairs; run both OR-query and UNION ALL against a mock; assert set equality of returned IDs
    - Use Hypothesis with `@settings(max_examples=100)`

  - [x] 10.2 Write property test for BFS subset guarantee
    - **Property 2: BFS Subset Guarantee**
    - **Validates: Requirements 2.7**
    - Generate random DAGs (Hypothesis `st.data()` + adjacency lists); run BFS + equivalent single-expansion; assert BFS result ⊆ single-expansion result

  - [x] 10.3 Write property test for visited-set cycle prevention
    - **Property 3: BFS Visited-Set Prevents Cycles**
    - **Validates: Requirements 2.4**
    - Generate random cyclic graphs; run BFS; assert termination (completes within timeout), no duplicate node IDs in output

  - [x] 10.4 Write property test for early termination
    - **Property 4: BFS Early Termination**
    - **Validates: Requirements 2.5**
    - Generate graphs with dead-end branches (nodes with no outgoing edges at some depth); assert BFS stops immediately when frontier is empty

  - [x] 10.5 Write property test for strategy selection consistency
    - **Property 5: Strategy Selection Consistency**
    - **Validates: Requirements 3.1, 5.1**
    - Generate (degree, depth) pairs in full int range; assert `_use_bfs` returns False only when degree < BFS_ACTIVATION_THRESHOLD AND depth <= 3

  - [x] 10.6 Write property test for label scope on expanded nodes
    - **Property 6: Label Scope on Expanded Nodes**
    - **Validates: Requirements 4.1, 4.2**
    - Generate tenant configs (with/without prefix); assert scope predicate presence/absence on target node queries matches tenant type

  - [x] 10.7 Write property test for timeout fallback chain
    - **Property 7: Timeout Fallback Chain**
    - **Validates: Requirements 3.3, 5.5**
    - Inject timeouts at random points in the mock graph_db; assert result is always a valid Degraded_Result (never an unhandled exception)

  - [x] 10.8 Write property test for fan-out limit bounds
    - **Property 8: Fan-Out Limit Bounds Per-Hop Results**
    - **Validates: Requirements 2.3**
    - Generate high-degree hops (mock graph_db returns > FAN_OUT_LIMIT rows before LIMIT); assert per-hop result count ≤ BFS_FAN_OUT_LIMIT

- [x] 11. Run benchmark validation against live Neptune
  - [x] 11.1 Run failing benchmark cases and verify resolution
    - Execute `mcp_server_python/scripts/run_benchmark.py` targeting cases: `cl_001`, `cl_003`, `cl_004`, `cl_006`, `cl_008`, `cl_010`, `cl_t01`
    - Verify all complete within 30s (no timeouts)
    - Verify `cl_006` and `cl_010` (Root Cause B) complete under 5s
    - _Requirements: 7.1, 7.2, 1.5_

  - [x] 11.2 Run full 68-case benchmark and verify timeout + latency bounds
    - Run `mcp_server_python/scripts/run_benchmark.py` with all 68 cases
    - Verify graph-query timeout count ≤ 3 (Requirement 7.1) — observed 0
    - Verify graph P95 latency ≤ 10,000ms (Requirement 7.5) — observed 1,482ms
    - Record category and overall coverage as observed; do NOT gate on the
      coverage numbers. Requirements 7.2, 7.3, and 7.4 were deferred out of scope
      on 2026-08-31 (see requirements.md *Deferred: Coverage Targets*)
    - Confirm no regressions: covered/uncovered case set unchanged versus baseline,
      and `semantic_search`, `architecture`, `ee2_compliance`, `operational` all 100%
    - Capture the before/after numbers in requirements.md *Observed Results*
    - _Requirements: 7.1, 7.5_

- [x] 12. Final checkpoint - Ensure all tests pass
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
