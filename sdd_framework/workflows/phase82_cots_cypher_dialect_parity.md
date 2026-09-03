# Phase 82: COTS Cypher Dialect Parity — `toString()` Graph Query Failures

**Version**: 1.1.0
**Date**: 2026-09-01
**Status**: **BLOCKED** — premise falsified by implementation (see §0)
**Priority**: High
**Depends on**: Phase 81 (neptune-traversal-query-optimization)
**Superseded by**: Phase 83 (cots-name-type-tolerant-predicate)
**Branch**: `develop`

---

## 0. BLOCKED — Implementation Findings (2026-09-01)

> **This phase was implemented, benchmarked, reverted, and blocked in a single
> CLI session. The prescribed fix does not work and the core premise is wrong.**

### What was done
Steps 1–4 were implemented exactly as specified: `toString()` removed from all
4 sites, the `is_testing` branch removed, and 3 regression tests added. All 4
new tests passed with no new unit/property failures. Then Step 6's COTS
benchmark falsified the fix.

### Benchmark result — fix changed nothing

| Gate | Required | Pre-fix | Post-fix |
|------|----------|---------|----------|
| Graph failures | 0 | 7 | **7** |
| Architecture coverage | ≥80% | 40% | **40%** |
| Overall coverage | ≥88% | 80% | **80%** |

Identical. Same 7 failures, same 2 query shapes (5 from GGSR 2-hop, 2 from
topic enrichment).

### Real root cause — `name` is NOT always a string

The spec's premise ("`n.name` is always a string") is **false**. Direct
inspection of the `gw_v17` Neo4j COTS graph:

| `name` type | Node count | Example |
|-------------|-----------|---------|
| String | 321,520 | `"forecast_det"` |
| Integer (Long) | **452** | `17` |
| String list | **4** | `["UFSATM","GOCART"]` |

This is a **Neo4j-vs-Neptune engine-behavior gap**, not a `toString()` dialect
quirk:

- `toLower(n.name)` (the "fix") → `CypherTypeError: Expected a string value for
  toLower, but got: Long(17)` on the **452** integer-named nodes.
- `toLower(toString(n.name))` (pre-fix) → `toString(): got StringArray[...]` on
  the **4** list-named nodes.

Neptune silently tolerates the type mismatch; Neo4j Community throws and aborts
the whole query. **Neither form is correct** — the prescribed change trades 4
problem nodes for 452, with no change to the benchmark's failure count.

**Correction to §1 below**: Neo4j accepts `toString()` on a string fine. The
original claim that `toString()` "raises ProcedureNotFound" or "returns
unexpected results" is wrong. The failure is purely the type mismatch on
non-string `name` values.

### Why reverted
The change meets no gate and is arguably a regression (452 integer-name
failures vs. 4 list-name nodes). All Step 1–4 edits were reverted; the SDD
session was set to blocked. No CHANGELOG entry, no "Status: Complete."

### Handoff
The correct fix needs a **decision between competing approaches** — see
**Phase 83** (`phase83_cots_name_type_tolerant_predicate.md`), which re-scopes
this work and lays out the options for an AWS-side CLI decision (where both
Neptune and Neo4j are reachable for live validation).

---

## 1. Problem Statement (ORIGINAL — premise now known false, retained for history)

The first COTS benchmark run (2026-09-01, Neo4j 5.26.20 Community + ChromaDB
1.1.1, corpus v1.1.0, 68 cases) revealed **7 graph query failures** and a
**10% coverage regression** compared to the Neptune baseline (Phase 81
[8.41.1]).

### Root Cause — `toString()` Cypher Function on Neo4j Community

All 7 failures trace to **one pattern** used in 4 code sites across 3 files:

```cypher
WHERE toLower(toString(n.name)) CONTAINS toLower($param)
```

On **Neptune openCypher**, `toString()` on a string property is a no-op that
silently coerces any type to a string. On **Neo4j Community Edition**, this
same call either:

- Raises `Neo.ClientError.Procedure.ProcedureNotFound` on older versions, or
- Returns unexpected results when the property is already a string (the
  `toString()` call is redundant but may interact with Neo4j's type-checking
  differently when the property is null or multi-valued)

The fix is straightforward: replace `toString(n.name)` with `n.name` in the
WHERE clause. The `name` property is always a string in the graph schema, so
the coercion wrapper is unnecessary on both backends. One call site
(`graph_rag.py:485`) already demonstrates the correct form in its
`is_testing` branch — `toLower(n.name) CONTAINS toLower($name)` — confirming
the fix works.

### Benchmark Evidence

| Metric              | Neptune (8.41.1) | COTS (this run) | Delta     |
|---------------------|------------------|-----------------|-----------|
| Timeouts            | 0                | 0               | same      |
| Graph Failures      | 0                | **7**           | **+7** ⚠️ |
| Graph P95 (ms)      | 1,482            | 453             | 3.3× faster ✅ |
| Graph Max (ms)      | 11,198           | 579             | 19× faster ✅ |
| Precision@k         | 0.73             | 0.59            | −0.14 ⚠️  |
| Coverage            | 90%              | 80%             | −10% ⚠️   |
| Architecture cov    | N/A              | **40%**         | ⚠️ outlier |

The 7 graph failures caused 6 of 10 `architecture` cases to return 0 matches
(40% coverage), directly accounting for the overall coverage drop.

### Failing Query Shapes (from benchmark instrumentation)

**Shape 1** — GGSR multi-hop traversal (5 of 9 calls failed):
```
MATCH (n)-[r1]-(hop1) WHERE toLower(toString(n.name)) CONTAINS toLower($baseName)
  AND size([__lbl IN labels(n) ...
```

**Shape 2** — Topic graph enrichment (2 of 2 calls failed):
```
MATCH (n) WHERE toLower(toString(n.name)) CONTAINS toLower($topic)
  RETURN n.name AS name, labels(n) AS labels, ...
```

---

## 2. Affected Code Sites

| # | File | Line | Function | Context |
|---|------|------|----------|---------|
| 1 | `src/graphrag/ggsr_traversal.py` | ~369 | `_multi_hop_query` | 1-hop GGSR traversal WHERE clause |
| 2 | `src/graphrag/ggsr_traversal.py` | ~387 | `_multi_hop_query` | 2-hop GGSR traversal WHERE clause |
| 3 | `src/tools/graph_rag.py` | ~491 | `_tool_get_code_context` | Production fuzzy-match fallback (test branch already correct at ~485) |
| 4 | `src/tools/semantic_search.py` | ~816 | `_tool_explain_with_context` | Graph-enrichment topic lookup |

All 4 sites use the identical pattern: `toLower(toString(X)) CONTAINS toLower($param)`.

---

## 3. Requirements

### R1: Remove `toString()` wrapper from all Cypher WHERE clauses
Replace `toLower(toString(n.name))` with `toLower(n.name)` at all 4 code sites.
The `name` property is always a string in the graph schema; the coercion is
redundant.

### R2: Eliminate the test/production divergence in `graph_rag.py`
The `is_testing` branch at `graph_rag.py:~485` already uses the correct form
(`toLower(n.name)`). After the fix, the test and production branches should emit
identical Cypher (or the branching can be removed if no other differences exist).

### R3: Zero graph query failures on COTS benchmark
Re-run the full 68-case benchmark with `DB_BACKEND=cots` and confirm:
- `graph_queries.failed_queries == 0`
- `architecture` category coverage >= 80% (matching or exceeding Neptune)
- No regressions in other categories

### R4: Neptune compatibility preserved
The fix must not regress Neptune. `toLower(n.name)` is valid openCypher on
both backends. Verify by running the unit test suite (all mocked, but confirms
no Cypher shape regressions) and confirming the query shapes remain openCypher-
compliant.

### R5: Add a COTS-specific unit test gate
Add at least one unit test per affected function that asserts the generated
Cypher does NOT contain `toString(` in any WHERE clause. This prevents future
regressions where someone re-adds the wrapper for Neptune-specific reasons.

---

## 4. Tasks

### Task 1: Fix `ggsr_traversal.py` — GGSR multi-hop queries
- [ ] 1.1 Replace `toString(n.name)` → `n.name` in 1-hop query (~line 369)
- [ ] 1.2 Replace `toString(n.name)` → `n.name` in 2-hop query (~line 387)
- [ ] 1.3 Update docstring (~line 340) to note the removal and why

### Task 2: Fix `graph_rag.py` — `get_code_context` fuzzy fallback
- [ ] 2.1 Replace `toString(n.name)` → `n.name` in production branch (~line 491)
- [ ] 2.2 Evaluate removing the `is_testing` branch divergence if now identical

### Task 3: Fix `semantic_search.py` — `explain_with_context` graph enrichment
- [ ] 3.1 Replace `toString(n.name)` → `n.name` in topic lookup (~line 816)

### Task 4: Add regression-prevention unit tests
- [ ] 4.1 Add test asserting `_multi_hop_query` Cypher contains no `toString(`
- [ ] 4.2 Add test asserting `_tool_get_code_context` Cypher contains no `toString(`
- [ ] 4.3 Add test asserting `_tool_explain_with_context` Cypher contains no `toString(`

### Task 5: COTS benchmark validation
- [ ] 5.1 Run full 68-case benchmark: `DB_BACKEND=cots python3 scripts/run_benchmark.py`
- [ ] 5.2 Confirm `graph_queries.failed_queries == 0`
- [ ] 5.3 Confirm `architecture` coverage >= 80%
- [ ] 5.4 Confirm no regressions in other categories vs pre-fix COTS run
- [ ] 5.5 Compare COTS results against Neptune baseline — document parity

### Task 6: Unit test suite validation
- [ ] 6.1 Run `tests/unit/` — confirm no Cypher shape regressions
- [ ] 6.2 Run `tests/properties/` — confirm BFS walker and traversal properties hold

### Task 7: Documentation
- [ ] 7.1 Update `CHANGELOG.md` with Phase 82 entry
- [ ] 7.2 Record COTS benchmark results in benchmark history

---

## 5. Verification Criteria

| Criterion | Gate |
|-----------|------|
| All 4 `toString()` sites removed | Code inspection |
| Zero graph failures on COTS benchmark | `graph_queries.failed_queries == 0` |
| Architecture coverage >= 80% on COTS | Benchmark category result |
| Overall coverage >= 88% on COTS | Benchmark overall result |
| No Neptune regression | Unit + property tests pass |
| Regression-prevention tests added | 3+ new test assertions |
| CHANGELOG updated | Version entry present |

---

## 6. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `toString()` removal breaks Neptune | Very Low | High | `toLower(n.name)` is valid openCypher; unit tests will catch shape changes |
| Null `name` properties cause errors | Low | Medium | Add `coalesce(n.name, '')` if any nodes have null names; check graph schema |
| Multi-valued name properties | Very Low | Low | Neo4j Community does not support multi-valued properties; Neptune stores as list only via specific ingestion |
| Architecture coverage still below 80% | Medium | Low | Some misses may be data/corpus issues (like the Neptune baseline's code_structure gaps) rather than query failures |

---

## 7. CLI Execution Plan

```bash
# Step 1: Apply the fix (4 sites across 3 files)
# — see Tasks 1-3 above

# Step 2: Run unit tests
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_python
PYTHONPATH="$PWD:$PYTHONPATH" DB_BACKEND=cots \
  python3 -m pytest tests/unit/ -v --tb=short 2>&1 | tail -30

# Step 3: Run property tests
PYTHONPATH="$PWD:$PYTHONPATH" DB_BACKEND=cots \
  python3 -m pytest tests/properties/ -v --tb=short 2>&1 | tail -30

# Step 4: Run COTS benchmark (full 68-case)
PYTHONPATH="$PWD:$PYTHONPATH" \
  DB_BACKEND=cots \
  NEO4J_URI=bolt://localhost:7687 \
  NEO4J_USER=neo4j \
  NEO4J_PASSWORD=gfsworkflow2025 \
  CHROMADB_HOST=127.0.0.1 \
  CHROMADB_PORT=8080 \
  python3 scripts/run_benchmark.py \
    --results-dir /tmp/bench_cots_phase82_$(date +%F)

# Step 5: Compare results
python3 -c "
import json
with open('/tmp/bench_cots_phase82_$(date +%F)/<latest>.json') as f:
    d = json.load(f)
gq = d['graph_queries']
print(f'Graph failures: {gq[\"failed_queries\"]}')
print(f'Architecture cov: {d[\"categories\"][\"architecture\"][\"coverage\"]}')
print(f'Overall cov: {d[\"overall\"][\"coverage\"]}')
assert gq['failed_queries'] == 0, 'FAIL: graph failures remain'
assert d['categories']['architecture']['coverage'] >= 0.80, 'FAIL: architecture below 80%'
print('PASS: all gates met')
"
```

---

## 8. Benchmark Reference

### Pre-fix COTS baseline (2026-09-01)
- Results file: `/tmp/bench_cots_2026-09-01/2026-09-01T19-46-03.json`
- Provenance: `python:run_benchmark.py:cots:titan1024`
- Graph failures: 7
- Architecture coverage: 40%
- Overall coverage: 80%

### Neptune baseline (2026-08-31, Phase 81)
- Results file: `/tmp/bench_t11_2/results/2026-08-31T18-01-12.json`
- Graph failures: 0
- Overall coverage: 90%
- Graph P95: 1,482ms
