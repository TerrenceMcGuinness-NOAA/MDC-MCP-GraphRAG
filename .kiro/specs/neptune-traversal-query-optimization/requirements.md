# Requirements Document

## Introduction

The 2026-08-28 full benchmark run (68 cases, db.r6g.xlarge 32GB Neptune instance)
achieved 90% overall coverage but 9 graph queries failed with 30-second timeouts.
All 9 failures occur in the `cross_language` and `code_structure` benchmark
categories — the two categories that issue deep multi-hop traversals via
`trace_full_execution_chain`, `trace_data_flow`, and `find_callers_callees`.

Three root causes drive the timeouts:

- **Root Cause A** (6 of 9 failures): Variable-length `*1..5` expansion across 6
  relationship types simultaneously (`SOURCES|INVOKES|EXECUTES|CALLS|USES|DEFINES`).
  At each hop, every outgoing edge of every type is explored, producing a
  combinatorial path count (500^5 candidate paths at depth 5 for hub nodes) that
  exceeds the 30-second timeout.
- **Root Cause B** (2 of 9 failures): OR predicate on an unlabelled anchor node
  (`a.name = $name OR a.path = $name`) prevents Neptune from using its property
  index, forcing a full scan. A UNION ALL decomposition of the same pattern in
  the graph-enrichment path was proven effective on 2026-08-27 (28.57s → 0.06s).
- **Root Cause C** (1 of 9 failure): Reverse variable-length expansion — identical
  combinatorial issue as Root Cause A but traversing incoming edges.

The existing `bounded-graph-traversal` [8.36.0] provides a degree-probe + timeout
backstop that makes these failures graceful (Degraded_Result instead of unhandled
exceptions). This feature optimizes the query shapes themselves so that the
backstop fires less often and more queries complete successfully within the time
bound.

This is a query-layer-only optimization: same tool API surface, same inputs, same
outputs, faster execution. No graph schema changes, no re-ingestion, no tool
signature changes.

## Glossary

- **BFS_Walker**: An application-side breadth-first traversal that issues per-type,
  single-hop queries iteratively and merges results in Python, replacing a single
  multi-type variable-length openCypher pattern.
- **UNION_ALL_Decomposition**: The technique of splitting an OR-predicate query
  into two index-seekable `MATCH` clauses joined by `UNION ALL`, enabling Neptune
  to use property indices on each branch independently.
- **Multi_Type_Expansion**: A variable-length pattern that traverses multiple
  relationship types simultaneously (e.g. `[:CALLS|USES|SOURCES*1..5]`), causing
  combinatorial path enumeration at each hop.
- **Per_Type_BFS**: The replacement strategy where each relationship type is
  expanded independently in a single-hop query per depth level, with
  application-side merging of results across types.
- **Fan_Out_Limit**: The maximum number of neighbor nodes collected per hop per
  relationship type during Per_Type_BFS traversal.
- **Cross_Language_Edge_Set**: The set of relationship types traversed by
  cross-language tools: SOURCES, INVOKES, EXECUTES, CALLS, USES, DEFINES.
- **Hub_Node**: A node whose degree exceeds the bounded-graph-traversal
  Fan_Out_Threshold (currently 100 edges), triggering the existing degree-probe
  short-circuit.
- **Anchor_Predicate**: The WHERE clause that identifies the traversal's starting
  node, typically matching on `name` and/or `path` properties.
- **Label_Scope_Predicate**: The tenant-scoping filter (`_scope_and`) applied via
  `labels(n)` checks to restrict traversal to the active tenant's graph partition.
- **Statement_Timeout**: The per-query time bound (default 30s) enforced by the
  Neptune_Adapter as a backstop against runaway queries.
- **Benchmark_Coverage**: The percentage of benchmark test cases that return a
  successful (non-timeout, non-error) result.

## Requirements

### Requirement 1: UNION ALL Decomposition of OR Anchor Predicates

**User Story:** As a tool caller, I want `trace_full_execution_chain` and
`trace_data_flow` queries to use index-seekable predicates, so that anchor-node
resolution completes in milliseconds instead of timing out.

#### Acceptance Criteria

1. WHEN a traversal query uses an Anchor_Predicate of the form
   `(node.name = $name OR node.path = $name)`, THE Query_Optimizer SHALL
   rewrite it as a `UNION ALL` of two queries — one matching `node.name = $name`
   and one matching `node.path = $name` — so that Neptune can use its property
   index on each branch independently.
2. THE UNION_ALL_Decomposition SHALL be applied to the anchor resolution in
   `trace_full_execution_chain` (both forward and reverse directions) and in
   `trace_data_flow` (the one-hop outgoing fan-out query and the seed-node lookup).
3. THE UNION_ALL_Decomposition SHALL produce the same result set as the original
   OR-predicate query (set-equivalent rows, deduplicated).
4. WHEN the UNION_ALL_Decomposition is applied, THE resulting queries SHALL each
   carry the existing Label_Scope_Predicate and Statement_Timeout unchanged.
5. THE UNION_ALL_Decomposition SHALL reduce the P95 latency of the affected
   queries from the current 28+ seconds to under 5 seconds for the benchmark
   cases `cl_006` and `cl_010`.

### Requirement 2: Per-Type BFS Decomposition of Multi-Type Variable-Length Patterns

**User Story:** As a tool caller, I want cross-language traversals to avoid
combinatorial path enumeration, so that deep traversals from moderately-connected
nodes complete within the timeout instead of exploding.

#### Acceptance Criteria

1. WHEN a Traversal_Tool issues a Multi_Type_Expansion pattern
   (e.g. `[:SOURCES|INVOKES|EXECUTES|CALLS|USES|DEFINES*1..N]`), THE BFS_Walker
   SHALL decompose it into iterative single-hop, single-type queries executed
   per depth level, with application-side merging of discovered nodes.
2. THE BFS_Walker SHALL expand each relationship type independently at each depth
   level, issuing one bounded query per type per hop (up to
   `|Cross_Language_Edge_Set| × Effective_Depth` queries total).
3. EACH single-hop query issued by the BFS_Walker SHALL carry a `LIMIT` clause
   set to the Fan_Out_Limit (configurable, default 100 nodes per type per hop)
   to prevent any individual expansion from returning an unbounded result set.
4. THE BFS_Walker SHALL track the visited-node set across hops to avoid cycles
   and redundant re-expansion (a node already discovered at depth N is not
   re-expanded at depth N+1).
5. THE BFS_Walker SHALL terminate early when a hop produces zero new nodes
   across all relationship types, regardless of remaining depth budget.
6. THE BFS_Walker SHALL apply the existing Label_Scope_Predicate to each
   single-hop query so that tenant isolation is maintained at every expansion step.
7. THE BFS_Walker SHALL produce a result set that is a subset of what the original
   Multi_Type_Expansion would return — it may discover fewer paths (due to the
   Fan_Out_Limit) but SHALL NOT introduce nodes that the original pattern would
   not reach.

### Requirement 3: Selective BFS Activation via Degree Probe

**User Story:** As a tool caller, I want traversals from low-degree nodes to use
the existing single-query pattern (which is fast for small graphs), and only switch
to the BFS_Walker for nodes where the combinatorial expansion is a risk.

#### Acceptance Criteria

1. WHEN a Traversal_Tool's pre-flight degree probe reports a Node_Degree below
   the Fan_Out_Threshold AND the Effective_Depth is 3 or less, THE Traversal_Tool
   SHALL use the existing single-query variable-length pattern (no BFS
   decomposition).
2. WHEN a Traversal_Tool's pre-flight degree probe reports a Node_Degree at or
   above a BFS_Activation_Threshold (configurable, default 30), OR the
   Effective_Depth exceeds 3, THE Traversal_Tool SHALL use the BFS_Walker
   instead of the single-query pattern.
3. IF a timeout occurs during traversal (regardless of which strategy was
   selected), THEN THE Traversal_Tool SHALL fall back to the BFS_Walker before
   resorting to the Degraded_Result. IF the BFS_Walker also fails or times out,
   THEN THE Traversal_Tool SHALL fall through to the existing
   bounded-graph-traversal Degraded_Result behavior.
4. THE BFS_Activation_Threshold SHALL be a configurable constant defined alongside
   the existing traversal-bounds constants, with an environment-variable override
   (`MCP_BFS_ACTIVATION_THRESHOLD`).

### Requirement 4: Label-Scope Predicate on Expanded Nodes

**User Story:** As a multi-tenant system, I want traversal expansion to filter
expanded nodes by tenant label at every hop, so that cross-tenant edges do not
inflate the working set and waste traversal budget.

#### Acceptance Criteria

1. WHEN the BFS_Walker issues single-hop expansion queries, THE query SHALL
   include the Label_Scope_Predicate on the target node (not only the anchor),
   so that only nodes belonging to the active tenant are collected.
2. WHEN the existing single-query variable-length pattern is used (per
   Requirement 3.1), THE query SHALL include the Label_Scope_Predicate on the
   terminal node of the pattern in addition to the anchor node.
3. WHEN no tenant is specified (default `gw` tenant with unprefixed labels), THE
   Label_Scope_Predicate on expanded nodes SHALL be omitted (no filtering), since
   the default tenant's nodes carry no prefix and filtering would exclude them.
4. THE Label_Scope_Predicate applied to expanded nodes SHALL use the same
   `_scope_and` helper used for anchor nodes, ensuring consistency with the
   existing tenant-isolation mechanism.

### Requirement 5: Backward Compatibility for Non-Hub Traversals

**User Story:** As a tool caller querying non-hub nodes, I want my results to
remain unchanged after this optimization, so that existing behavior is preserved
for the common case.

#### Acceptance Criteria

1. WHEN a traversal's Anchor_Node has a Node_Degree below the
   BFS_Activation_Threshold AND the Effective_Depth is 3 or less, THE
   Traversal_Tool SHALL return results equivalent to the pre-optimization
   behavior (same nodes, same edges, same ordering where ordering was previously
   defined).
2. THE feature SHALL NOT modify any tool's public API (function signature,
   parameter names, return type, or description).
3. THE feature SHALL NOT modify ingestion scripts, graph schema, tenant logic,
   or the Neptune_Adapter's connection/auth handling.
4. THE feature SHALL NOT require re-ingestion of any tenant's graph data.
5. THE existing bounded-graph-traversal infrastructure (degree probe,
   Statement_Timeout backstop, Degraded_Result rendering) SHALL remain intact
   and continue to function as the last-resort guard for queries that slip past
   the new optimizations.

### Requirement 6: Configuration and Tunability

**User Story:** As an operator, I want the BFS parameters to be tunable without
code changes, so that I can adjust thresholds as the graph grows or Neptune
instance changes.

#### Acceptance Criteria

1. THE Fan_Out_Limit, BFS_Activation_Threshold, and any new traversal constants
   SHALL be defined as named module-level constants in a single location alongside
   the existing traversal-bounds constants (not scattered as literals).
2. WHERE an environment variable override is provided (e.g.
   `MCP_BFS_ACTIVATION_THRESHOLD`, `MCP_BFS_FAN_OUT_LIMIT`), THE tool SHALL use
   the override value, falling back to the default when unset or unparseable.
3. THE default values SHALL be chosen conservatively so the out-of-the-box
   behavior is safe on the current `gw` and `gw_v17` baselines where hub nodes
   (JGLOBAL_FORECAST, setuprad) exist.

### Requirement 7: Benchmark Coverage Improvement

**User Story:** As a platform operator, I want the query optimizations to
measurably reduce benchmark failures, so that overall coverage meets the 95%+
target.

#### Acceptance Criteria

1. WHEN the full benchmark suite (68 cases) is run after this optimization lands,
   THE graph-query timeout count SHALL be 3 or fewer (reduced from the current 9).
2. WHEN the `cross_language` category is run after this optimization, THE category
   coverage SHALL be 100% (up from current 90%).
3. WHEN the `code_structure` category is run after this optimization, THE category
   coverage SHALL be 70% or higher (up from current 50%).
4. THE overall benchmark coverage SHALL reach 95% or higher (up from current 90%).
5. THE graph P95 latency SHALL be 10,000ms or lower (reduced from the current
   17,190ms).

### Requirement 8: Observability of BFS Execution

**User Story:** As an operator, I want to see when the BFS_Walker activates and
how it performs, so that I can tune thresholds and detect regressions.

#### Acceptance Criteria

1. WHEN the BFS_Walker is activated for a traversal, THE Traversal_Tool SHALL
   log at info level the tool name, Anchor_Node name, measured Node_Degree,
   the BFS_Activation_Threshold that triggered it, and the number of hops
   actually expanded.
2. WHEN the BFS_Walker completes, THE Traversal_Tool SHALL log the total nodes
   discovered, total queries issued, and wall-clock time of the BFS walk. THE
   completion event SHALL be logged even when the traversal discovers zero nodes,
   so that operators can use the data for threshold tuning and regression
   detection.
3. THE log output SHALL NOT include tenant credentials or full result payloads.
   Non-ASCII characters are permitted in log output as long as credentials are
   excluded.
4. THE tool response to the caller SHALL indicate when BFS was used (a brief
   note in the response header, e.g. `[optimized: BFS walker, N hops, M nodes]`)
   so that callers can distinguish BFS results from single-query results without
   requiring server log access.
