# Requirements Document

## Introduction

The graph-traversal tools (`trace_full_execution_chain`, `trace_execution_path`,
`find_callers_callees`, `trace_data_flow`, and `find_dependencies`' circular-check)
issue variable-length openCypher path queries against Neptune. When the anchor
node is hyper-connected — e.g. `JGLOBAL_FORECAST` on the `gw` baseline has 500+
direct edges — these queries cause Neptune to enumerate a combinatorial number of
paths before any `LIMIT` applies, producing a query timeout or an out-of-memory
condition on the Neptune side and a failed/empty tool response.

The root cause is twofold: (1) the variable-length patterns expand to large depths
(`trace_full_execution_chain` uses `*1..10` across six relationship types), and
(2) the existing `LIMIT` clauses truncate the *result set* but not the *path
enumeration* — Neptune materializes all matching paths first, so `LIMIT` does not
prevent the explosion. There is also no pre-flight check of the anchor node's
degree (edge count) before launching an expansion, and no server-side statement
timeout to bound a runaway query.

This feature adds bounded-traversal guards to the affected tools so that a
traversal from a hyper-connected node degrades gracefully (a truncated,
clearly-labeled partial result) instead of timing out or OOM-ing Neptune. It is a
tool-layer (query) change deployed to the AgentCore runtime — it does not change
how the graph is ingested, and it does not require re-ingestion.

After this feature lands:
- `trace_full_execution_chain` / `trace_execution_path` / `find_callers_callees`
  return a bounded, labeled result for `JGLOBAL_FORECAST` and other hub nodes
  instead of timing out
- Every variable-length traversal carries an effective depth cap and a per-hop
  fan-out guard, and surfaces a `[truncated]` marker when it trims output
- A Neptune statement timeout bounds any traversal server-side as a backstop

## Glossary

- **Traversal_Tool**: Any MCP tool that issues a variable-length path query —
  `trace_full_execution_chain`, `trace_execution_path`, `find_callers_callees`,
  `trace_data_flow`, and the circular-dependency check inside `find_dependencies`.
- **Anchor_Node**: The node a traversal starts from, matched by `name`/`path`
  (e.g. the `function_name`, `start`, or `from_symbol` argument).
- **Node_Degree**: The count of direct relationships (in a given direction and
  edge-type set) incident to a node.
- **Hub_Node**: An Anchor_Node whose Node_Degree exceeds the Fan_Out_Threshold
  (e.g. `JGLOBAL_FORECAST`, 500+ edges).
- **Fan_Out_Threshold**: The configurable Node_Degree above which a traversal
  switches from full variable-length expansion to a bounded/summarized strategy.
- **Effective_Depth**: The maximum path length a Traversal_Tool will request from
  Neptune for a given call, after applying the feature's depth cap (which may be
  lower than the caller-supplied `max_depth`).
- **Path_Materialization**: Neptune's enumeration of all paths matching a
  variable-length pattern before `LIMIT`/`RETURN` projection — the step that
  explodes for Hub_Nodes.
- **Statement_Timeout**: A server-side per-query time bound that causes Neptune to
  abort a query rather than run unbounded.
- **Degraded_Result**: A bounded, explicitly-labeled partial response a
  Traversal_Tool returns when it declines to fully expand a Hub_Node.
- **Neptune_Adapter**: The existing `NeptuneAdapter` that executes openCypher
  queries; the natural place to plumb a per-query Statement_Timeout.

## Requirements

### Requirement 1: Pre-flight Degree Check

**User Story:** As a tool caller, I want a deep traversal from a hyper-connected
node to detect the hub before expanding, so that the query never attempts a
combinatorial Path_Materialization.

#### Acceptance Criteria

1. WHEN a Traversal_Tool resolves its Anchor_Node, THE Traversal_Tool SHALL issue
   a bounded degree-count query (a single-hop `count` over the traversal's
   relationship-type set, with a `LIMIT` on the count probe) before issuing any
   variable-length path query.
2. IF the Anchor_Node's Node_Degree is greater than the Fan_Out_Threshold, THEN
   THE Traversal_Tool SHALL NOT issue the unbounded variable-length expansion and
   SHALL instead produce a Degraded_Result per Requirement 4.
3. IF the Anchor_Node's Node_Degree is less than or equal to the
   Fan_Out_Threshold, THEN THE Traversal_Tool SHALL proceed with the bounded
   variable-length expansion per Requirement 2.
4. THE degree-count query SHALL itself be bounded so that counting the edges of a
   Hub_Node cannot become an expensive operation (e.g. count over a single hop,
   never a variable-length pattern).
5. IF the degree-count query fails or times out, THEN THE Traversal_Tool SHALL
   treat the Anchor_Node as a Hub_Node (fail safe toward the Degraded_Result)
   rather than attempting the full expansion.

### Requirement 2: Effective Depth Capping

**User Story:** As a system operator, I want every variable-length traversal to
carry a hard depth ceiling, so that no single call can request a depth that risks
Path_Materialization blow-up.

#### Acceptance Criteria

1. THE Traversal_Tool SHALL clamp the caller-supplied `max_depth` to a feature
   Effective_Depth ceiling before constructing the variable-length pattern.
2. THE Effective_Depth ceiling SHALL be configurable per tool, with conservative
   defaults: cross-language full-chain traversal SHALL default to an Effective_Depth
   no greater than 5 (reduced from the current 10), and single-edge-type call-chain
   traversal SHALL default to an Effective_Depth no greater than 4.
3. WHEN the feature clamps a caller-supplied `max_depth` below the requested value,
   THE Traversal_Tool SHALL note the applied Effective_Depth in the response so the
   caller knows the traversal was bounded.
4. THE variable-length pattern emitted SHALL always carry an explicit upper bound
   (`*1..N` form); THE Traversal_Tool SHALL NOT emit an unbounded
   (`*` or `*1..`) variable-length pattern under any input.

### Requirement 3: Per-Hop Fan-Out Bounding

**User Story:** As a tool caller, I want traversals to bound the breadth they
explore at each hop, so that a moderately-connected node does not still produce an
unmanageable path count even within the depth cap.

#### Acceptance Criteria

1. WHERE a Traversal_Tool expands a node whose Node_Degree is within the
   Fan_Out_Threshold but still large, THE Traversal_Tool SHALL bound the total
   work by combining the Effective_Depth cap with a result `LIMIT` and a
   Statement_Timeout, so that the query returns within the timeout or is aborted.
2. THE Traversal_Tool SHALL apply a `LIMIT` to every variable-length path query
   such that the number of returned paths is bounded to a configurable maximum
   (default no greater than 200 rows).
3. WHERE Neptune supports pushing the `LIMIT` into the traversal (so enumeration
   stops early), THE Traversal_Tool's query SHALL be structured to enable that
   push-down (e.g. by avoiding post-`WITH` re-sorts that force full
   materialization before `LIMIT`).
4. THE Traversal_Tool SHALL preserve existing correctness for non-hub nodes: a
   traversal whose Anchor_Node is within the Fan_Out_Threshold and whose natural
   result is below the row `LIMIT` SHALL return the same set of results it returns
   today (no behavior change for the common case).

### Requirement 4: Graceful Degraded Result for Hub Nodes

**User Story:** As a tool caller, I want a clear, useful partial answer when a node
is too connected to fully traverse, so that I get the node's immediate neighborhood
and an explanation instead of an error.

#### Acceptance Criteria

1. WHEN a Traversal_Tool declines a full expansion because the Anchor_Node is a
   Hub_Node, THE Traversal_Tool SHALL return a one-hop (direct neighbors only)
   view of the Anchor_Node, bounded by the result `LIMIT`.
2. THE Degraded_Result SHALL include an explicit, human-readable notice stating
   that the node is highly connected (including its measured Node_Degree) and that
   the traversal was limited to direct neighbors.
3. THE Degraded_Result SHALL include the Anchor_Node's Node_Degree and the
   Fan_Out_Threshold that triggered the degradation.
4. THE Degraded_Result SHALL be a successful tool response (not an `[ERROR]`),
   so that callers receive actionable content rather than a failure.
5. WHERE the one-hop neighbor set itself exceeds the result `LIMIT`, THE
   Degraded_Result SHALL truncate to the `LIMIT` and append a `[truncated: N of M
   shown]`-style marker.

### Requirement 5: Neptune Statement Timeout Backstop

**User Story:** As a system operator, I want any traversal query to be bounded
server-side, so that a query that slips past the depth and degree guards still
cannot run unbounded against Neptune.

#### Acceptance Criteria

1. THE Neptune_Adapter SHALL support an optional per-query Statement_Timeout passed
   by the Traversal_Tool when issuing a variable-length path query.
2. WHEN a Traversal_Tool issues a variable-length path query, THE Traversal_Tool
   SHALL pass a Statement_Timeout (configurable, default no greater than 30
   seconds) to the Neptune_Adapter.
3. IF a traversal query exceeds its Statement_Timeout, THEN THE Traversal_Tool
   SHALL catch the resulting timeout error and return a Degraded_Result per
   Requirement 4 (or a clear timeout notice when no partial data is available),
   never an unhandled exception.
4. THE Statement_Timeout SHALL be applied only to traversal queries; non-traversal
   queries (single-node lookups, counts) SHALL retain their existing behavior
   unless a timeout is explicitly supplied.
5. WHERE the Neptune endpoint does not honor a per-query timeout parameter, THE
   Neptune_Adapter SHALL enforce the bound client-side (e.g. via the existing
   `asyncio.to_thread` call wrapped in `asyncio.wait_for`) so the tool still
   returns within the bound.

### Requirement 6: Configuration and Tunability

**User Story:** As a system operator, I want the traversal bounds to be tunable
without code edits, so that I can adjust thresholds as the graph grows.

#### Acceptance Criteria

1. THE Fan_Out_Threshold, the per-tool Effective_Depth ceilings, the result
   `LIMIT`, and the Statement_Timeout SHALL each be defined as named module
   constants in one location, not scattered as literals across queries.
2. WHERE an environment variable override is provided for a bound (e.g.
   `MCP_TRAVERSAL_FANOUT_THRESHOLD`, `MCP_TRAVERSAL_MAX_DEPTH`,
   `MCP_TRAVERSAL_TIMEOUT_S`), THE tool SHALL use the override value, falling back
   to the default when unset or invalid.
3. THE default values SHALL be chosen conservatively so the out-of-the-box
   behavior is safe on the current `gw` baseline (where `JGLOBAL_FORECAST` and
   similar hubs exist).

### Requirement 7: Backward Compatibility and Scope

**User Story:** As a developer, I want the bounding guards to leave normal
traversals unchanged and to stay within the tool layer, so that the change is low
risk and needs no re-ingestion.

#### Acceptance Criteria

1. THE feature SHALL modify only tool-layer query code (`graph_rag.py`,
   `code_analysis.py`) and the `Neptune_Adapter` query signature; it SHALL NOT
   modify ingestion scripts, graph schema, or tenant logic.
2. THE feature SHALL NOT require re-ingestion of any tenant's graph.
3. A traversal from a non-hub Anchor_Node whose result is within the bounds SHALL
   return results equivalent to the pre-feature behavior (same nodes, same edges,
   same ordering where ordering was previously defined).
4. THE feature's new behavior SHALL apply uniformly across all tenants (the bounds
   are tenant-independent; they operate on Node_Degree, not tenant identity).
5. THE existing tenant-scoping predicates (`_scope_and`, label-prefix rewriting)
   SHALL remain applied to every traversal query unchanged.

### Requirement 8: Observability

**User Story:** As an operator, I want to see when traversals are being bounded, so
that I can tell whether the guards are firing and tune the thresholds.

#### Acceptance Criteria

1. WHEN a Traversal_Tool applies a degree-based degradation, depth clamp, or
   timeout fallback, THE Traversal_Tool SHALL log the event at info level with the
   tool name, the Anchor_Node, the measured Node_Degree (when known), and which
   guard fired.
2. THE log output SHALL be ASCII-only and SHALL NOT include tenant credentials or
   full result payloads.
3. THE Degraded_Result rendered to the caller SHALL make the guard that fired
   discoverable (per Requirements 2.3 and 4.2) without requiring access to server
   logs.
