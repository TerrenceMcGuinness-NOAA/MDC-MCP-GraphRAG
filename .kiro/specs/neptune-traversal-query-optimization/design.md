# Design Document — Neptune Traversal Query Optimization

## Overview

This design addresses the 9 remaining graph-query timeouts (30s) observed in the
2026-08-28 full benchmark run (68 cases, db.r6g.xlarge 32GB). The optimization is
purely query-layer: same tool API, same inputs, same outputs — but the internal
query strategy changes so that combinatorial path enumeration is avoided and
Neptune's property indices are leveraged.

Two complementary strategies are introduced:

1. **UNION ALL Decomposition** — replaces OR-predicate anchor clauses
   (`name = $x OR path = $x`) with a `UNION ALL` of two index-seekable branches.
   Proven to reduce latency from 28.57s to 0.06s in `semantic_search.py`
   (2026-08-27). Resolves Root Cause B (2 of 9 failures).

2. **BFS Walker** — replaces multi-type variable-length patterns
   (`[:CALLS|USES|SOURCES|...*1..5]`) with an application-side breadth-first
   traversal that issues simple, bounded, single-type, single-hop queries
   iteratively. Resolves Root Causes A and C (7 of 9 failures).

Both strategies are gated by the existing degree-probe infrastructure from
`bounded-graph-traversal` [8.36.0]. Low-degree nodes continue to use the
original single-query pattern (fast, unchanged behavior). The BFS Walker only
activates when the combinatorial risk is real.

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Tool Call (unchanged API)                       │
└─────────────────────┬───────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│            UNION ALL Anchor Resolution (Req 1)                      │
│  ┌──────────────────────────┐  ┌──────────────────────────────┐    │
│  │ Branch 1: WHERE name=$x  │  │ Branch 2: WHERE path=$x      │    │
│  └──────────────────────────┘  └──────────────────────────────┘    │
└─────────────────────┬───────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                Pre-flight Degree Probe (existing)                    │
│                    anchor_degree(name, rel_types)                    │
└──────┬──────────────────────────┬──────────────────────────────┬────┘
       │                          │                              │
  degree > FAN_OUT        degree >= BFS_THRESHOLD          degree < BFS_THRESHOLD
  (existing guard)         AND depth > 3                   AND depth <= 3
       │                          │                              │
       ▼                          ▼                              ▼
┌──────────────┐  ┌────────────────────────────────┐  ┌──────────────────────┐
│ Degraded_    │  │     BFS Walker (Req 2)         │  │  Original single-    │
│ Result       │  │  per-type, per-hop, bounded    │  │  query pattern       │
│ (one-hop)    │  │  with visited-set + fan-out    │  │  (unchanged, fast)   │
└──────────────┘  └────────────────────────────────┘  └──────────────────────┘
       │                          │                              │
       │              ┌───────────┴───────────┐                  │
       │              │ Timeout during BFS?   │                  │
       │              └───────┬───────────────┘                  │
       │                      │ yes                              │
       │                      ▼                                  │
       │              ┌──────────────┐                           │
       │              │ Degraded_    │                           │
       │              │ Result       │                           │
       │              └──────────────┘                           │
       │                      │                                  │
       ▼                      ▼                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Format + Return markdown                          │
└─────────────────────────────────────────────────────────────────────┘
```

## Architecture

### Layered Guard Stack (extended from bounded-graph-traversal)

The existing [8.36.0] guard stack is:

1. **Degree probe** → Hub? → Degraded_Result
2. **Depth cap** → Clamp `max_depth` → bounded `*1..N`
3. **Statement timeout** → Catch → Degraded_Result

This optimization inserts a new layer between #1 and #2:

1. Degree probe → Hub? → Degraded_Result *(unchanged)*
2. **Strategy selection** → BFS_Walker or single-query *(new)*
3. Depth cap → applied within selected strategy *(unchanged semantic)*
4. Statement timeout → catches failures in either strategy *(unchanged)*

### File Ownership

| File | Changes |
|------|---------|
| `src/tools/_traversal_bounds.py` | Add `BFS_ACTIVATION_THRESHOLD`, `BFS_FAN_OUT_LIMIT` constants; export new helper `bfs_walk` |
| `src/tools/_bfs_walker.py` | **New file** — the BFS Walker algorithm |
| `src/tools/code_analysis.py` | Replace `_cross_language_nodes` body with BFS-gated strategy; UNION ALL in `_one_hop_neighbors` anchor |
| `src/tools/graph_rag.py` | UNION ALL in `trace_data_flow` outgoing query and shortestPath anchor |
| `src/tools/semantic_search.py` | No changes (already optimized) |
| `src/data/neptune_adapter.py` | No changes (interface sufficient) |
| `src/tenancy/resolver.py` | No changes (`_scope_and` / `tenant_label_predicate` reused as-is) |

## Components and Interfaces

### Component 1: BFS Walker (`src/tools/_bfs_walker.py`)

A standalone, importable async function that performs application-side
breadth-first traversal across the cross-language edge set.

```python
@dataclass(frozen=True, slots=True)
class BFSResult:
    """Output of a BFS walk."""
    nodes: list[dict[str, Any]]       # {name, path, labels, hop, relType, direction}
    hops_expanded: int                 # actual depth reached
    queries_issued: int                # total Neptune calls made
    wall_clock_ms: int                 # total time
    truncated: bool                    # True if any hop hit the fan-out limit


async def bfs_walk(
    graph_db: Any,
    *,
    start_name: str,
    direction: Literal["forward", "reverse"],
    edge_types: Sequence[str],
    max_depth: int,
    fan_out_limit: int,
    result_limit: int,
    timeout_s: float,
    scope_pred: str,
    tenant: Any,
    label_scope_expanded: bool,
) -> BFSResult:
    """Application-side BFS across edge_types, bounded per hop."""
    ...
```

**Key design decisions:**

- Each hop issues `len(edge_types)` parallel queries (one per type) via
  `asyncio.gather`. Each query is a simple single-hop pattern:
  ```cypher
  MATCH (a)-[:CALLS]->(b)
  WHERE id(a) IN $ids AND <label_scope_pred_on_b>
  RETURN DISTINCT id(b) AS nid, b.name AS name, b.path AS path,
         labels(b) AS labels
  LIMIT <fan_out_limit>
  ```
- A `visited: set[str]` prevents re-expansion (cycle detection).
- Early termination when no new nodes are discovered.
- Total wall-clock is bounded by `timeout_s` via `asyncio.wait_for` around
  the entire BFS loop.
- The seed node is resolved separately (using UNION ALL) before the walk
  starts.

### Component 2: UNION ALL Anchor Resolver

A helper function (in `_traversal_bounds.py` or `_bfs_walker.py`) that
resolves a node by name/path using the index-seekable UNION ALL pattern:

```python
async def resolve_anchor_ids(
    graph_db: Any,
    name: str,
    *,
    scope_pred: str,
    tenant: Any,
    timeout_s: float,
) -> list[str]:
    """Resolve anchor node IDs using UNION ALL decomposition."""
    cypher = (
        "MATCH (n) WHERE n.name = $name" + scope_pred + " "
        "RETURN id(n) AS nid "
        "UNION ALL "
        "MATCH (n) WHERE n.path = $name" + scope_pred + " "
        "RETURN id(n) AS nid"
    )
    rows = await graph_db.query(cypher, {"name": name}, tenant=tenant, timeout=timeout_s)
    return list({r["nid"] for r in (rows or []) if r.get("nid")})
```

This feeds the BFS Walker's initial frontier and replaces the OR-predicate
anchor in `trace_data_flow`'s one-hop and shortest-path queries.

### Component 3: Strategy Selector (within each tool)

Each tool's traversal path gains a selection branch:

```python
degree = await anchor_degree(graph_db, name, rel_set, tenant, scope_pred)

if is_hub(degree):
    # Existing path: Degraded_Result (one-hop)
    return _degraded_body(...)

if _use_bfs(degree, requested_depth):
    # NEW: BFS Walker
    result = await bfs_walk(graph_db, start_name=name, ...)
    return _format_bfs_result(result)
else:
    # Existing path: single-query variable-length pattern (fast for small graphs)
    rows = await graph_db.query(f"MATCH p=(start)-[:{edges}*1..{depth}]->(n) ...")
    return _format_rows(rows)
```

Where `_use_bfs` encapsulates Requirement 3:

```python
def _use_bfs(degree: int | None, requested_depth: int) -> bool:
    """True when BFS should be used instead of single-query expansion."""
    if degree is None:
        return True  # fail-safe: probe failed
    if degree >= BFS_ACTIVATION_THRESHOLD:
        return True
    if requested_depth > 3:
        return True
    return False
```

### Component 4: Label-Scope on Expanded Nodes (Requirement 4)

In the BFS Walker's per-hop queries, the target node `b` carries the
Label_Scope_Predicate when a non-default tenant is active:

```cypher
-- For tenant gw_v17:
MATCH (a)-[:CALLS]->(b)
WHERE id(a) IN $ids
  AND size([l IN labels(b) WHERE l STARTS WITH 'GW_V17_']) > 0
RETURN DISTINCT id(b) AS nid, b.name AS name, ...
LIMIT 100

-- For default tenant gw (no prefix):
MATCH (a)-[:CALLS]->(b)
WHERE id(a) IN $ids
RETURN DISTINCT id(b) AS nid, b.name AS name, ...
LIMIT 100
```

The `_scope_and(var)` helper from `resolver.py` already generates the
correct predicate for both cases. The BFS Walker applies it to the
expansion target at every hop (parameter `label_scope_expanded=True`).

## Data Models

### BFSResult (dataclass)

```python
@dataclass(frozen=True, slots=True)
class BFSResult:
    nodes: list[dict[str, Any]]
    hops_expanded: int
    queries_issued: int
    wall_clock_ms: int
    truncated: bool
```

Each node dict in `nodes` carries:
```python
{
    "name": str,
    "path": str | None,
    "labels": list[str],
    "hop": int,           # depth at which discovered
    "relType": str,       # edge type that led here
    "direction": str,     # "forward" or "reverse"
}
```

### New Constants (in `_traversal_bounds.py`)

| Constant | Env Override | Default | Description |
|----------|-------------|---------|-------------|
| `BFS_ACTIVATION_THRESHOLD` | `MCP_BFS_ACTIVATION_THRESHOLD` | 30 | Node degree above which BFS replaces single-query |
| `BFS_FAN_OUT_LIMIT` | `MCP_BFS_FAN_OUT_LIMIT` | 100 | Max nodes collected per type per hop |

These sit alongside the existing constants:

| Constant | Default | Role |
|----------|---------|------|
| `FAN_OUT_THRESHOLD` | 100 | Hub → Degraded_Result (unchanged) |
| `FULL_CHAIN_DEPTH` | 5 | Depth cap for full-chain (unchanged) |
| `CALL_CHAIN_DEPTH` | 4 | Depth cap for call-chain (unchanged) |
| `DATA_FLOW_DEPTH` | 5 | Depth cap for data-flow (unchanged) |
| `RESULT_LIMIT` | 200 | Max rows returned (unchanged) |
| `TIMEOUT_S` | 30.0 | Statement timeout (unchanged) |

### Strategy Selection Thresholds

```
degree:  0 ─────────── 30 ─────────── 100 ──────── ∞
          │              │               │
          │  Single-     │  BFS Walker   │  Degraded_Result
          │  query       │  (per-type,   │  (one-hop only)
          │  (fast)      │  bounded)     │
          │              │               │
          └──────────────┴───────────────┘
                         │
                    BFS also if
                    depth > 3
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all
valid executions of a system — essentially, a formal statement about what the
system should do. Properties serve as the bridge between human-readable
specifications and machine-verifiable correctness guarantees.*

### Property 1: UNION ALL Set Equivalence

*For any* anchor name `n` and scope predicate `s`, the UNION ALL decomposition
(`MATCH ... WHERE name=$n UNION ALL MATCH ... WHERE path=$n`) SHALL return the
same set of node IDs as the original OR-predicate
(`WHERE name=$n OR path=$n`), with deduplication.

**Validates: Requirements 1.3**

### Property 2: BFS Subset Guarantee

*For any* start node and edge set, the BFS Walker's result set SHALL be a
subset of the nodes reachable via the equivalent variable-length pattern — it
may discover fewer nodes (due to the Fan_Out_Limit) but SHALL NOT introduce
any node that the original pattern would not reach.

**Validates: Requirements 2.7**

### Property 3: BFS Visited-Set Prevents Cycles

*For any* graph containing cycles, the BFS Walker SHALL terminate (never
loop indefinitely) because a node already in the visited set is not
re-expanded, and the frontier shrinks monotonically toward empty.

**Validates: Requirements 2.4**

### Property 4: BFS Early Termination

*For any* BFS walk where a hop produces zero new nodes across all
relationship types, the BFS Walker SHALL terminate immediately regardless
of remaining depth budget, returning the nodes discovered so far.

**Validates: Requirements 2.5**

### Property 5: Strategy Selection Consistency

*For any* node with degree below `BFS_ACTIVATION_THRESHOLD` and requested
depth ≤ 3, the strategy selector SHALL choose the single-query path, and
the results SHALL be equivalent to the pre-optimization behavior.

**Validates: Requirements 3.1, 5.1**

### Property 6: Label Scope on Expanded Nodes

*For any* non-default tenant and BFS hop, every node in the expansion
result SHALL carry a label matching the tenant's prefix (verified via the
Label_Scope_Predicate applied to the target node in each per-hop query).

**Validates: Requirements 4.1, 4.2**

### Property 7: Timeout Fallback Chain

*For any* traversal that times out during BFS execution, the tool SHALL
catch the timeout and return a Degraded_Result (not an unhandled
exception), preserving the existing bounded-graph-traversal contract.

**Validates: Requirements 3.3, 5.5**

### Property 8: Fan-Out Limit Bounds Per-Hop Results

*For any* single BFS hop and relationship type, the number of nodes
collected SHALL NOT exceed `BFS_FAN_OUT_LIMIT`, ensuring that no
individual expansion query returns an unbounded result set.

**Validates: Requirements 2.3**

## Error Handling

### Failure Modes and Recovery

| Failure Mode | Detection | Recovery |
|---|---|---|
| Anchor resolution timeout (UNION ALL) | `_is_timeout_error(exc)` | Return `[ERROR]` — cannot proceed without anchor |
| Degree probe failure | Returns `None` | Treat as hub → BFS (fail-safe toward bounded) |
| BFS hop query timeout | `asyncio.TimeoutError` in `wait_for` | Stop BFS, return partial results + truncation notice |
| BFS overall timeout | Outer `wait_for` around BFS loop | Fall through to Degraded_Result (one-hop) |
| Single-query pattern timeout | Existing `_is_timeout_error` catch | Existing path: attempt BFS fallback first, then Degraded_Result |
| Neptune connection error | Raised by adapter | Propagated to tool-level `[ERROR]` handler (unchanged) |

### Fallback Chain (Requirement 3.3)

```
Single-query pattern (fast path)
    │ timeout
    ▼
BFS Walker (bounded decomposition)
    │ timeout
    ▼
Degraded_Result (one-hop neighbors)
    │ timeout on one-hop
    ▼
Empty result with timeout notice
```

The fallback only activates for the strategy-selection path (degree below
FAN_OUT_THRESHOLD). Nodes already classified as hubs go directly to
Degraded_Result (no BFS attempt for nodes with 100+ edges — the BFS fan-out
limit at 100/type would still be expensive).

## Testing Strategy

### Unit Tests (mock-based)

- **Strategy selection logic**: inject `MockGraphDB` responses to test all
  branches of `_use_bfs` — low-degree node → single-query, medium-degree →
  BFS, hub → degraded.
- **BFS Walker isolation**: seed mock with multi-hop adjacency, verify
  visited-set prevents cycles, early termination on empty frontier,
  fan-out limit caps results.
- **UNION ALL correctness**: compare results of OR-query vs UNION ALL query
  against mock graph with nodes matchable by name, path, or both.
- **Label-scope filtering**: verify non-default tenant queries include the
  scope predicate on expanded nodes; default tenant omits it.
- **Timeout handling**: `MockGraphDB` raises `TimeoutError` at controlled
  points; verify fallback chain fires correctly.

### Property-Based Tests (Hypothesis)

Property-based testing is appropriate here because:
- The BFS Walker is a pure algorithm with clear input/output (graph adjacency
  → reachable node set).
- Universal properties hold across all valid graph shapes (subset guarantee,
  cycle termination, early termination).
- Input space is large (arbitrary graph topologies, degree distributions).

**Library**: `hypothesis` (already in dev dependencies, `.hypothesis/` present)

**Configuration**: minimum 100 examples per property test.

**Tag format**: `Feature: neptune-traversal-query-optimization, Property N: <text>`

Each correctness property above maps to a single property-based test:

1. **UNION ALL set equivalence** — generate random (name, path) pairs; run both
   query shapes against a mock; assert set equality of returned IDs.
2. **BFS subset guarantee** — generate random DAGs; run BFS + single-query
   pattern; assert BFS result ⊆ single-query result.
3. **Visited-set prevents cycles** — generate random cyclic graphs; run BFS;
   assert termination and no duplicate nodes in output.
4. **Early termination** — generate graphs with dead-end branches; assert BFS
   stops at the first empty frontier.
5. **Strategy selection** — generate (degree, depth) pairs; assert correct
   strategy choice per the threshold rules.
6. **Label scope** — generate tenant configs; assert scope predicate presence/
   absence on expanded-node queries.
7. **Timeout fallback** — inject timeouts at random points; assert
   Degraded_Result is returned (never an unhandled exception).
8. **Fan-out limit** — generate high-degree hops; assert per-hop result count
   ≤ `BFS_FAN_OUT_LIMIT`.

### Integration Tests (against live Neptune — benchmark harness)

- Re-run the failing benchmark cases (`cl_001`, `cl_003`, `cl_004`, `cl_006`,
  `cl_008`, `cl_010`, `cl_t01`) and verify completion within 30s.
- Full 68-case benchmark run to confirm overall coverage ≥ 95%.
- Regression check: re-run `semantic_search` and `operational` categories to
  confirm no degradation.

---

## Appendix: BFS Walker Algorithm (Pseudocode)

```python
async def bfs_walk(graph_db, *, start_name, direction, edge_types,
                   max_depth, fan_out_limit, result_limit, timeout_s,
                   scope_pred, tenant, label_scope_expanded):
    t0 = time.monotonic()

    # Step 1: Resolve anchor via UNION ALL
    anchor_ids = await resolve_anchor_ids(
        graph_db, start_name, scope_pred=scope_pred,
        tenant=tenant, timeout_s=timeout_s
    )
    if not anchor_ids:
        return BFSResult(nodes=[], hops_expanded=0, ...)

    # Step 2: Fetch seed node metadata
    seed_nodes = await _fetch_node_metadata(graph_db, anchor_ids, tenant)

    # Step 3: BFS loop
    visited: set[str] = set(anchor_ids)
    frontier: set[str] = set(anchor_ids)
    all_nodes: list[dict] = seed_nodes  # hop=0 entries
    queries_issued = 0
    truncated = False

    for depth in range(1, max_depth + 1):
        if not frontier:
            break  # Early termination (Req 2.5)

        # Expand each edge type in parallel
        next_frontier: set[str] = set()
        hop_tasks = []
        for edge_type in edge_types:
            hop_tasks.append(
                _expand_one_hop(
                    graph_db, frontier, edge_type, direction,
                    fan_out_limit, scope_pred if label_scope_expanded else "",
                    tenant, timeout_s
                )
            )

        hop_results = await asyncio.gather(*hop_tasks, return_exceptions=True)
        queries_issued += len(edge_types)

        for i, result in enumerate(hop_results):
            if isinstance(result, BaseException):
                if _is_timeout_error(result):
                    truncated = True
                    continue
                raise result
            for node in result:
                nid = node["nid"]
                if nid not in visited:  # Cycle prevention (Req 2.4)
                    visited.add(nid)
                    next_frontier.add(nid)
                    node["hop"] = depth
                    node["relType"] = edge_types[i]
                    node["direction"] = direction
                    all_nodes.append(node)

        frontier = next_frontier

        # Global result cap
        if len(all_nodes) >= result_limit:
            truncated = True
            all_nodes = all_nodes[:result_limit]
            break

    wall_ms = int((time.monotonic() - t0) * 1000)
    return BFSResult(
        nodes=all_nodes,
        hops_expanded=depth,
        queries_issued=queries_issued,
        wall_clock_ms=wall_ms,
        truncated=truncated,
    )


async def _expand_one_hop(graph_db, frontier_ids, edge_type, direction,
                          fan_out_limit, scope_pred_on_target, tenant, timeout_s):
    """Single-type, single-hop, bounded expansion."""
    if direction == "reverse":
        pattern = f"MATCH (b)-[:{edge_type}]->(a)"
    else:
        pattern = f"MATCH (a)-[:{edge_type}]->(b)"

    # scope_pred_on_target is "" for default tenant, or " AND <labels(b)...>"
    cypher = (
        pattern +
        " WHERE id(a) IN $ids" +
        scope_pred_on_target.replace("(n)", "(b)") +  # apply to target
        " RETURN DISTINCT id(b) AS nid, b.name AS name, b.path AS path,"
        " labels(b) AS labels"
        f" LIMIT {fan_out_limit}"
    )
    rows = await graph_db.query(
        cypher, {"ids": list(frontier_ids)},
        tenant=tenant, timeout=timeout_s
    )
    return rows or []
```

## Appendix: UNION ALL Rewrite for `trace_data_flow`

**Before** (Root Cause B — index-defeating OR):
```cypher
MATCH (source)-[r:CALLS|USES|IMPORTS|EXECUTES|INVOKES|SOURCES]->(target)
WHERE source.name = $name OR source.path = $name
RETURN target.name AS name, labels(target)[0] AS type, type(r) AS relType
ORDER BY type(r), target.name LIMIT 25
```

**After** (UNION ALL with per-branch LIMIT, then application-side dedup/sort):
```cypher
MATCH (source)-[r:CALLS|USES|IMPORTS|EXECUTES|INVOKES|SOURCES]->(target)
WHERE source.name = $name <scope_pred>
RETURN target.name AS name, labels(target)[0] AS type, type(r) AS relType
UNION ALL
MATCH (source)-[r:CALLS|USES|IMPORTS|EXECUTES|INVOKES|SOURCES]->(target)
WHERE source.path = $name <scope_pred>
RETURN target.name AS name, labels(target)[0] AS type, type(r) AS relType
```

Application-side: deduplicate by `(name, type, relType)`, sort by
`(relType, name)`, take first 25. This preserves the original semantics
while enabling Neptune to use property indices on each branch.

The same pattern applies to `_one_hop_neighbors` in `code_analysis.py`:

**Before:**
```cypher
MATCH (a)-[r:{rel_set}]->(x)
WHERE (a.name = $name OR a.path = $name) <scope>
RETURN DISTINCT x.name AS name, ... LIMIT 200
```

**After:**
```cypher
MATCH (a)-[r:{rel_set}]->(x)
WHERE a.name = $name <scope>
RETURN DISTINCT x.name AS name, ...
UNION ALL
MATCH (a)-[r:{rel_set}]->(x)
WHERE a.path = $name <scope>
RETURN DISTINCT x.name AS name, ...
```

Application-side dedup + LIMIT.

## Appendix: Observability (Requirement 8)

BFS activation is logged at `info` level:

```
[bfs-walker] ACTIVATED tool=trace_full_execution_chain anchor=JGLOBAL_FORECAST
  degree=174 threshold=30 direction=forward max_depth=5
```

BFS completion:

```
[bfs-walker] COMPLETED tool=trace_full_execution_chain anchor=JGLOBAL_FORECAST
  nodes=42 queries=18 hops=3 wall_ms=847
```

Response header (visible to callers without log access):

```
[optimized: BFS walker, 3 hops, 42 nodes, 847ms]
```
