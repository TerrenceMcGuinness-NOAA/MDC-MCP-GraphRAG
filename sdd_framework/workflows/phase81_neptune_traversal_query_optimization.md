# Phase 81: Neptune Traversal Query Optimization

**Version**: 1.0.0
**Date**: 2026-08-28
**Status**: Proposed
**Priority**: Medium
**Depends on**: Phase 80 (deploy), bounded-graph-traversal [8.36.0]
**Branch**: `update_shared_scoping` or successor

---

## 1. Problem Statement

The 2026-08-28 full benchmark run (68 cases, db.r6g.xlarge 32GB) scored 90%
coverage overall but 9 graph queries failed with 30s timeouts. All 9 are in the
`cross_language` and `code_structure` categories — the two categories that issue
deep multi-hop traversals via `trace_full_execution_chain`, `trace_data_flow`,
and `find_callers_callees`.

Two root causes are identified:

### Root Cause A — Variable-length expansion across 6 relationship types

```cypher
MATCH p = (start)-[:SOURCES|INVOKES|EXECUTES|CALLS|USES|DEFINES*1..5]->(n)
WHERE (start.name = $name OR start.path = $name) ...
```

This pattern asks Neptune to expand `*1..5` hops across **six** relationship
types simultaneously. At each hop, every outgoing edge of every type is
explored. For hub nodes (500+ edges), this produces a combinatorial path
count (500^5 candidate paths at depth 5) that exceeds the 30s timeout even
on 32GB.

**Affected**: 6 of 9 failures (forward chain traversal)
**Tools**: `trace_full_execution_chain`, `trace_execution_path`

### Root Cause B — OR predicate on unlabelled anchor node

```cypher
MATCH (a)-[r:SOURCES|INVOKES|EXECUTES|CALLS|USES|DEFINES]->(x)
WHERE (a.name = $name OR a.path = $name) ...
```

The `a.name = $name OR a.path = $name` disjunction on an unlabelled node
prevents index usage — the same pattern class fixed in the `_enrich_with_graph_counts`
UNION ALL rewrite (Phase 80 amendment, 2026-08-27). This is the one-hop
directed-neighbor query in `trace_data_flow`.

**Affected**: 2 of 9 failures
**Tools**: `trace_data_flow`

### Root Cause C — Reverse variable-length expansion

```cypher
MATCH p = (n)<-[:SOURCES|INVOKES|EXECUTES|CALLS|USES|DEFINES*1..5]-(start)
WHERE (start.name = $name OR start.path = $name) ...
```

Same as Root Cause A but in reverse direction. Same combinatorial issue.

**Affected**: 1 of 9 failures
**Tools**: `trace_full_execution_chain` (reverse)

---

## 2. Benchmark Evidence

From the 2026-08-28T21-05-19 full run (post db.r6g.xlarge resize):

| Metric | Before resize (r5.large) | After resize (r6g.xlarge) | Target |
|--------|--------------------------|---------------------------|--------|
| Graph failures | 11 (OOM + timeout) | 9 (timeout only) | 0-3 |
| cross_language coverage | 80% | 90% | 100% |
| code_structure coverage | 50% | 50% | 70%+ |
| Overall coverage | 88.3% | 90.0% | 95%+ |

Failure breakdown by query shape:
- 6× forward `*1..5` multi-type expansion (Root Cause A)
- 2× one-hop OR-predicate anchor (Root Cause B)
- 1× reverse `*1..5` multi-type expansion (Root Cause C)

---

## 3. Proposed Fixes

### Fix 1 — UNION ALL the OR predicates in trace_data_flow (Root Cause B)

**Effort**: Low (same pattern as the 2026-08-27 enrichment fix)
**Expected gain**: 2 of 9 failures resolved
**File**: `mcp_server_python/src/tools/graph_rag.py`

Replace:
```cypher
MATCH (a)-[r:...]->(x)
WHERE (a.name = $name OR a.path = $name) ...
```

With:
```cypher
MATCH (a)-[r:...]->(x) WHERE a.name = $name ...
UNION ALL
MATCH (a)-[r:...]->(x) WHERE a.path = $name ...
```

Each branch is index-seekable; the disjunction is not.

### Fix 2 — Per-edge-type sequential expansion (Root Cause A & C)

**Effort**: Medium
**Expected gain**: 4-7 of 9 failures resolved
**Files**: `mcp_server_python/src/tools/graph_rag.py`, `src/tools/code_analysis.py`

Instead of one `*1..5` pattern across all 6 types simultaneously, decompose
into per-type BFS with application-side merging:

```python
# Instead of:
#   MATCH p = (start)-[:SOURCES|INVOKES|EXECUTES|CALLS|USES|DEFINES*1..5]->(n)
# Do:
results = set()
frontier = {start_id}
for depth in range(max_depth):
    next_frontier = set()
    for rel_type in ["CALLS", "USES", "SOURCES", "INVOKES", "EXECUTES", "DEFINES"]:
        # Single-type, single-hop, bounded
        neighbors = query(f"""
            MATCH (a)-[:{rel_type}]->(b)
            WHERE id(a) IN $ids
            RETURN DISTINCT id(b) AS nid
            LIMIT {fan_out_limit}
        """, {"ids": list(frontier)})
        next_frontier.update(neighbors)
    results.update(next_frontier)
    frontier = next_frontier
    if not frontier:
        break
```

Each individual query is simple, bounded, and index-seekable. The application
controls breadth (fan-out limit per hop) and can short-circuit when a hop
returns too many results.

**Trade-offs**:
- More queries (up to `6 × max_depth` vs 1), but each is fast (<100ms)
- Total latency: ~600ms for 5 hops × 6 types vs 30s timeout + failure
- Loses the path-ordering semantics of the `*1..5` pattern (application
  reconstructs paths from the BFS tree if needed)

### Fix 3 — Increase statement timeout for chain tools (config only)

**Effort**: Minimal (env var)
**Expected gain**: 1-2 of 9 failures (borderline cases that finish in 30-45s)
**Env var**: `MCP_TRAVERSAL_TIMEOUT_S=45` (from current 30)

Low-confidence fix — the combinatorial queries are unlikely to complete in
45s if they can't in 30s. But borderline cases may benefit.

### Fix 4 — Pre-filter by label before expansion

**Effort**: Low-Medium
**Expected gain**: Reduces working set, may help 2-3 cases

Add the tenant label predicate to the anchor AND to the expanded node:

```cypher
MATCH p = (start)-[:CALLS*1..5]->(n)
WHERE start.name = $name
  AND size([l IN labels(start) WHERE l STARTS WITH 'GW_V17_']) > 0
  AND size([l IN labels(n) WHERE l STARTS WITH 'GW_V17_']) > 0
```

Currently only the anchor is label-scoped; expanded nodes at depth 2+ may
cross into other tenants' labels. This narrows the search space.

---

## 4. Implementation Steps

| Step | Fix | Tag | Description | Effort |
|------|-----|-----|-------------|--------|
| 1 | Fix 1 | implement | UNION ALL for `trace_data_flow` anchor predicates | 1h |
| 2 | Fix 1 | validate | Re-run `cl_006`, `cl_010` cases, confirm resolution | 30min |
| 3 | Fix 2 | design | Design the per-type BFS decomposition for `trace_full_execution_chain` | 2h |
| 4 | Fix 2 | implement | Implement BFS walker in `graph_rag.py` | 4h |
| 5 | Fix 2 | validate | Re-run full `cross_language` category | 1h |
| 6 | Fix 4 | implement | Add label predicate to expanded nodes in chain queries | 1h |
| 7 | — | validate | Full benchmark re-run, compare against today's baseline | 30min |
| 8 | — | document | Update wiki with post-optimization benchmark results | 30min |

**Estimated total**: 1-2 days of code work

---

## 5. Success Criteria

| Metric | Current (2026-08-28) | Target |
|--------|---------------------|--------|
| Graph query failures | 9 | ≤ 3 |
| cross_language coverage | 90% | 100% |
| code_structure coverage | 50% | ≥ 70% |
| Overall coverage | 90% | ≥ 95% |
| Graph P95 latency | 17,190ms | ≤ 10,000ms |
| Zero OOM errors | Yes (already met) | Maintained |

---

## 6. Scope Boundaries

**In scope**:
- Query-shape optimizations in `graph_rag.py` and `code_analysis.py`
- Application-side BFS decomposition for variable-length patterns
- Benchmark regression testing

**Out of scope**:
- Neptune instance resizing (already done — db.r6g.xlarge is sufficient)
- Changes to graph schema or ingestion
- Changes to the `bounded-graph-traversal` timeout/degree-probe infrastructure
  (those remain as the backstop)
- Tool API surface changes (same inputs, same outputs, faster)

---

## 7. Risk Assessment

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| BFS decomposition changes result ordering | Medium | Compare result sets before/after; accept set-equivalence, not order-equivalence |
| Per-type queries increase total latency for non-hub nodes | Low | The current `*1..5` completes in <1s for non-hub cases; only switch to BFS when degree probe fires |
| Fix 4 (label filtering on expanded nodes) drops cross-tenant references | Low | Only applied in tenant-scoped mode; default `gw` has no label filter |

---

## 8. Relationship to Other Work

- **bounded-graph-traversal [8.36.0]**: The backstop that makes these timeouts
  graceful rather than fatal. This phase optimizes the queries themselves so the
  backstop fires less often.
- **Phase 80 (freeze retirement)**: The benchmark harness that measures the
  improvement. The nightly comparison will detect regressions.
- **Gap J (community summaries)**: The Leiden graph export uses bulk reads, not
  traversals — unaffected by this work.
- **Neptune query fix (2026-08-27)**: The UNION ALL pattern for `_enrich_with_graph_counts`
  is the direct precedent for Fix 1.

---

## 9. Reference Data

### Benchmark baseline (2026-08-28T21-05-19)

```
Platform:   AWS AgentCore v40
Instance:   db.r6g.xlarge (32GB Graviton)
Corpus:     v1.1.0 (68 cases)
Coverage:   90.0% (default), 100% (tenant)
Failures:   9 graph timeouts (0 OOM)
```

### Affected case IDs

`cl_001`, `cl_003`, `cl_004`, `cl_006`, `cl_008`, `cl_010`, `cl_t01`
(all `cross_language` category)

Plus `code_structure` uncovered cases from degree-probe short-circuits:
`cs_001` through `cs_005` (hub-node degraded results — different fix path,
lower priority since the Degraded_Result is informative)
