# Gap Analysis & Session Context — 2026-08-27 (Thursday)

**Purpose**: Preserve working context across potential context compaction so
tomorrow's session can resume cleanly without rediscovery.

**Branch**: `update_shared_scoping` (ahead of origin by 5 commits)
**Live MCP Server**: HEALTHY (4/4 components, 105,891 nodes, 4,729,093 rels)
**Platform**: AWS AgentCore (`mdc_mcp_rag_server_python-v5K2F8BGrN`)

---

## 1. What Happened Today (2026-08-27)

### Neptune Graph Enrichment Query Fix (the big one)

The 2026-08-26 nightly benchmark run exposed a catastrophic performance
regression in `_enrich_with_graph_counts()` (called by `search_documentation`
when `include_graph=True`). The root cause:

```cypher
-- OLD (28.57s per call, 72 calls = half the run's graph budget)
MATCH (n)-[r]-(m)
WHERE n.name = $name OR n.path = $name OR n.filepath = $name
RETURN count(r) AS count
```

A 3-way OR across different properties of an **unlabelled** node cannot use an
index. Neptune evaluated the predicate against every node (~106K) and expanded
relationships from each. With 20 of these fired concurrently via
`asyncio.gather`, the single db.r5.large was saturated — even a trivial
`RETURN 1` from a separate process timed out.

**Fix** (in working tree, uncommitted):

```cypher
-- NEW (0.06s total via UNION ALL — 475x faster)
MATCH (n)-[r]-(m) WHERE n.name = $name RETURN count(r) AS count
UNION ALL
MATCH (n)-[r]-(m) WHERE n.path = $name RETURN count(r) AS count
UNION ALL
MATCH (n)-[r]-(m) WHERE n.filepath = $name RETURN count(r) AS count
```

Plus a `Semaphore(4)` to actually bound concurrency (the old code claimed to cap
it but didn't — plain `gather` over 20 items).

**File**: `mcp_server_python/src/tools/semantic_search.py`
**Spec-first check**: PASS (trivial single-file perf fix, no public surface change)
**Status**: Uncommitted working-tree change. Ready to commit.

### Earlier Commits (already pushed to origin or ahead locally)

| Commit | Summary |
|--------|---------|
| `7e98182` | feat(benchmark): per-graph-query timing instrument in `run_benchmark.py` |
| `b7a669e` | fix(graph): remove Neo4j-APOC calls Neptune cannot execute |
| `824ab4e` | docs(report): fill calibration section from first live benchmark |
| `ce69214` | docs(verification): fill shared-scope rows 2.1, 2.2 from live invocations |
| `3fcc725` | docs(changelog): record Phase 80 completion |

---

## 2. Spec Status Summary

### Active / Near-Complete

| Spec | Status | Next Action |
|------|--------|-------------|
| `default-tenant-freeze-retirement` (Phase 80) | Code DONE. tasks.md 7/11 checked (8-11 unchecked but commits exist) | Mark tasks complete in tasks.md, push |
| `shared-scope-query-routing` (Phase 79) | Harness complete (14/14 tasks). Operator deploy gated. | Push branch, operator deploys |
| `rag-drift-remediation-aug2026` | Req 1 (docs re-crawl) and Req 5 (benchmark) partially done | Continue benchmark runs post-fix |

### Open / Blocked

| Spec | Blocker |
|------|---------|
| `gemini-embedding-provider` | Awaiting Google API key |
| `graph-port-workflow-structure` | Requirements stub only |
| `graph-port-fortran-ast` | Depends on v17 Fortran coverage decisions |
| `cots-reingest-ralph-framework` | Parallel Works host access |
| Gap J (community-summaries) | Q3 work — Neo4j GDS vs Neptune, Node→Python port |

---

## 3. Uncommitted Working-Tree Changes

| File | Nature |
|------|--------|
| `mcp_server_python/src/tools/semantic_search.py` | UNION ALL query fix + semaphore |
| `.kiro/specs/default-tenant-freeze-retirement/requirements.md` | Minor spec text update |
| `.kiro/settings/mcp.json` | Local MCP config tweak |

---

## 4. Key Numbers (as of today)

| Metric | Value |
|--------|-------|
| Neptune nodes (health-check scope) | 105,891 |
| Neptune relationships | 4,729,093 |
| OpenSearch indices (gw baseline) | 5 |
| Tenants active | 5 (gw, gw_sfs, gw_jedi_gfs, gw_v17, gw_gefs_v12) |
| Test suite (last full run) | 1,916 passing, 4 pre-existing failures |
| Branch ahead of origin | 5 commits |
| Branch ahead of develop_aws | 134 commits |

---

## 5. Tomorrow's Priorities (2026-08-28)

### P1 — Commit and push the Neptune query fix

The UNION ALL rewrite is the highest-impact change pending. Without it, every
benchmark run and every `search_documentation(..., include_graph=True)` call
risks saturating the Neptune instance. Commit as a trivial perf fix, push to
`update_shared_scoping`.

### P2 — Re-run the benchmark with the fix applied

The 2026-08-26 run was invalidated by the 28.57s queries. A clean run with the
fix will establish the true quality baseline and confirm the per-query timing
instrument (`7e98182`) now shows sub-second graph times.

### P3 — Mark Phase 80 tasks complete and push

Tasks 8-11 in `default-tenant-freeze-retirement/tasks.md` have corresponding
commits but aren't checked off. Update the task file, push the branch.

### P4 — Plan the merge path to develop_aws

`update_shared_scoping` is 134 commits ahead of `develop_aws`. The branch
carries Phase 79 (shared-scope-query-routing) and Phase 80 (freeze retirement).
Decision needed: squash-merge (loses atomicity evidence) vs merge-commit
(preserves it). The Phase 80 changelog notes that squash loses verifiable
gate-continuity sequencing.

### P5 — Operator deploy (gated)

Both Phase 79 and Phase 80 need a runtime deploy (`update-agent-runtime` with
new ECR tag). This is operator-gated per git policy 08.

---

## 6. Known Risks / Watch Items

- **Neptune instance saturation**: fixed by P1, but until deployed, any client
  calling `search_documentation` with `include_graph=True` against 8+ results
  can still reproduce the issue on the live runtime.
- **Gap J (community-summaries)**: still 0 docs for v17. Blocks
  `search_architecture(tenant_id="gw_v17")`. Q3 target.
- **Four pre-existing test failures**: known, scoped out of Phase 80. One is
  Hypothesis-cached and doesn't reproduce on clean machines.
- **Merge conflict risk**: 134-commit divergence from develop_aws means rebase
  or merge will require attention.
