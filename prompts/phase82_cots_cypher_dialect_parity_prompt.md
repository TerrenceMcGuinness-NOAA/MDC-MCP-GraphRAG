# Phase 82 — COTS Cypher Dialect Parity: `toString()` Fix

## SDD Reference

`sdd_framework/workflows/phase82_cots_cypher_dialect_parity.md`

Session: `phase82_cots_cypher_dialect_parity` (7 steps, started 2026-09-01)

## Context

The first COTS benchmark (Neo4j 5.26.20 Community + ChromaDB 1.1.1) showed 7
graph query failures, all from `toLower(toString(n.name))` in Cypher WHERE
clauses. Neptune treats `toString()` on a string property as a harmless
no-op; Neo4j Community rejects or silently mishandles it. The fix is to
remove the `toString()` wrapper — `n.name` is always a string in the graph
schema. One site (`graph_rag.py:485`) already has the correct form in its
`is_testing` branch, proving the fix works.

## Pre-fix COTS Baseline

- Results file: `/tmp/bench_cots_2026-09-01/2026-09-01T19-46-03.json`
- Graph failures: **7**
- Architecture coverage: **40%** (6/10 cases returned 0 matches)
- Overall coverage: **80%**
- Precision@k: **0.59**

## Steps

Work through each step in order. After each step, use `record_sdd_step` to
mark it complete before moving to the next.

---

### Step 1 — Fix `ggsr_traversal.py` (Task 1: 2 sites)

File: `mcp_server_python/src/graphrag/ggsr_traversal.py`

**Site 1 (line ~369)** — 1-hop query:
```python
# BEFORE:
"WHERE toLower(toString(n.name)) CONTAINS toLower($baseName) "
# AFTER:
"WHERE toLower(n.name) CONTAINS toLower($baseName) "
```

**Site 2 (line ~387)** — 2-hop query:
```python
# BEFORE:
"WHERE toLower(toString(n.name)) CONTAINS toLower($baseName) "
# AFTER:
"WHERE toLower(n.name) CONTAINS toLower($baseName) "
```

**Docstring (line ~340)** — Update the docstring that explains the
`toString` choice. Replace the paragraph starting "The name predicate is"
with a note that `toString()` was removed in Phase 82 because Neo4j
Community treats it differently than Neptune. `toLower(n.name)` is valid
openCypher on both backends since `name` is always a string.

Record: `record_sdd_step(step=1, name="Fix ggsr_traversal.py", tag="implement")`

---

### Step 2 — Fix `graph_rag.py` (Task 2: 1 site + cleanup)

File: `mcp_server_python/src/tools/graph_rag.py`

**Site 3 (line ~491)** — production fuzzy-match fallback:
```python
# BEFORE:
"MATCH (n) WHERE toLower(toString(n.name)) CONTAINS toLower($name)"
# AFTER:
"MATCH (n) WHERE toLower(n.name) CONTAINS toLower($name)"
```

**Cleanup** — The `is_testing` branch (line ~484–493) exists solely because
the test path already uses the correct form while production had `toString()`.
After the fix, both branches emit identical Cypher. **Remove the branching**:
delete the `import sys as _sys` / `is_testing` check / `if`/`else` and keep
only the corrected single query. The result should be approximately:

```python
        try:
            cypher = (
                "MATCH (n) WHERE toLower(n.name) CONTAINS toLower($name)"
                f"{_scope_and('n')} "
                "RETURN n.name AS name, labels(n) AS labels LIMIT 5"
            )
            fuzzy_rows = await graph.query(
                cypher,
                {"name": symbol},
                tenant=_tenant(),
            )
```

Record: `record_sdd_step(step=2, name="Fix graph_rag.py", tag="implement")`

---

### Step 3 — Fix `semantic_search.py` (Task 3: 1 site)

File: `mcp_server_python/src/tools/semantic_search.py`

**Site 4 (line ~816)** — topic graph enrichment:
```python
# BEFORE:
"WHERE toLower(toString(n.name)) CONTAINS toLower($topic) "
# AFTER:
"WHERE toLower(n.name) CONTAINS toLower($topic) "
```

Record: `record_sdd_step(step=3, name="Fix semantic_search.py", tag="implement")`

---

### Step 4 — Add regression-prevention unit tests (Task 4)

Add tests that assert the generated Cypher does **not** contain `toString(`.
Follow the existing pattern in `test_graph_rag_tools.py` which uses
`data.graph_db.call_log` to capture emitted Cypher and makes assertions on
the query string (see lines ~1732–1770 for examples).

**Test 4.1** — In `tests/unit/test_graph_rag_tools.py`, add a test for
`get_code_context` fuzzy fallback that:
1. Invokes `get_code_context` with a symbol that does NOT match any canned
   rows (to trigger the fuzzy fallback path)
2. Captures the Cypher from `data.graph_db.call_log`
3. Asserts `"toString(" not in cypher` for any query containing `CONTAINS`
4. Asserts `"toLower(n.name)" in cypher`
5. Asserts there is no `is_testing` / `pytest` branch (the branching was removed)

**Test 4.2** — In `tests/unit/test_semantic_search_tools.py` (or
`test_graph_rag_tools.py` if semantic_search tests live elsewhere), add a
test for `explain_with_context` that:
1. Invokes `explain_with_context` with a topic
2. Captures graph queries from the call log
3. Asserts `"toString(" not in cypher` for any query containing `CONTAINS`

**Test 4.3** — In the appropriate GGSR test file (check
`tests/unit/test_ggsr_traversal.py` or similar), add a test for
`_multi_hop_query` that:
1. Invokes `_multi_hop_query` with hops=1 and hops=2
2. Captures the emitted Cypher
3. Asserts `"toString(" not in cypher`

If any of these test files don't exist yet, create them following the existing
patterns in the test suite.

Record: `record_sdd_step(step=4, name="Add regression-prevention tests", tag="validate")`

---

### Step 5 — Run unit and property test suites (Task 6)

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_python
PYTHONPATH="$PWD:$PYTHONPATH" python3 -m pytest tests/unit/ -v --tb=short 2>&1 | tail -40
PYTHONPATH="$PWD:$PYTHONPATH" python3 -m pytest tests/properties/ -v --tb=short 2>&1 | tail -40
```

Confirm no new failures introduced by the changes. Pre-existing failures are
documented in the Phase 81 CHANGELOG (5 known: `test_tenancy` P6,
`test_environment` module count, `test_error_analysis` taxonomy key,
`test_workflow_info_tools` root naming, `rag-data-plane-gap-closure` R15.3
working-tree guard).

Record: `record_sdd_step(step=5, name="Unit and property tests pass", tag="validate")`

---

### Step 6 — Run COTS benchmark (Task 5)

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_python
PYTHONPATH="$PWD:$PYTHONPATH" \
  DB_BACKEND=cots \
  NEO4J_URI=bolt://localhost:7687 \
  NEO4J_USER=neo4j \
  NEO4J_PASSWORD=gfsworkflow2025 \
  CHROMADB_HOST=127.0.0.1 \
  CHROMADB_PORT=8080 \
  python3 scripts/run_benchmark.py \
    --results-dir /tmp/bench_cots_phase82_$(date +%F)
```

**Verification gates** (from the SDD spec):

```bash
python3 << 'PYEOF'
import json, glob, sys

results_dir = glob.glob("/tmp/bench_cots_phase82_*")[0]
latest = sorted(glob.glob(f"{results_dir}/*.json"))[-1]
with open(latest) as f:
    d = json.load(f)

gq = d["graph_queries"]
arch_cov = d["categories"]["architecture"]["coverage"]
overall_cov = d["overall"]["coverage"]

print(f"Results:            {latest}")
print(f"Graph failures:     {gq['failed_queries']}")
print(f"Architecture cov:   {arch_cov:.0%}")
print(f"Overall coverage:   {overall_cov:.0%}")
print(f"Precision@k:        {d['overall']['precision_at_k']}")

failed = []
if gq["failed_queries"] != 0:
    failed.append(f"graph failures: {gq['failed_queries']} (expected 0)")
if arch_cov < 0.80:
    failed.append(f"architecture coverage: {arch_cov:.0%} (expected >=80%)")
if overall_cov < 0.88:
    failed.append(f"overall coverage: {overall_cov:.0%} (expected >=88%)")

if failed:
    print("\n[FAIL] Gates not met:")
    for f in failed:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("\n[PASS] All Phase 82 gates met")
PYEOF
```

Record: `record_sdd_step(step=6, name="COTS benchmark passes gates", tag="validate")`

---

### Step 7 — Documentation (Task 7)

1. Update `CHANGELOG.md` with a Phase 82 entry. Format:

```markdown
## [8.42.0] - cots-cypher-dialect-parity: remove toString() from graph queries (Sep X, 2026)

### Summary
Remove `toString()` wrapper from 4 Cypher WHERE clauses across 3 files.
The wrapper is a no-op on Neptune but fails on Neo4j Community Edition,
causing 7 graph query failures and 40% architecture coverage on COTS.
After the fix: 0 graph failures, architecture coverage restored to >=80%.

### Changed
- **`src/graphrag/ggsr_traversal.py`** — `_multi_hop_query` 1-hop and 2-hop:
  `toLower(toString(n.name))` → `toLower(n.name)`
- **`src/tools/graph_rag.py`** — `_tool_get_code_context` fuzzy fallback:
  removed `is_testing` branch, unified on `toLower(n.name)`
- **`src/tools/semantic_search.py`** — `_tool_explain_with_context`:
  `toLower(toString(n.name))` → `toLower(n.name)`

### Tests
- 3 new regression-prevention assertions: generated Cypher must not contain
  `toString(` in WHERE clauses
- COTS benchmark: 0 graph failures (was 7), architecture coverage >=80% (was 40%)
```

2. Update the SDD spec `phase82_cots_cypher_dialect_parity.md`:
   - Change `**Status**: Proposed` to `**Status**: Complete`
   - Check all task boxes `[x]`

3. Stage all changes: `git add -A` (do NOT commit — per git policy 08)

Record: `record_sdd_step(step=7, name="CHANGELOG and docs updated", tag="document")`

Then: `complete_sdd_session(summary="Phase 82 complete: removed toString() from 4 Cypher sites, 0 COTS graph failures, architecture coverage restored")`

---

## Files Modified (expected)

| File | Change |
|------|--------|
| `src/graphrag/ggsr_traversal.py` | 2 query fixes + docstring update |
| `src/tools/graph_rag.py` | 1 query fix + remove is_testing branch |
| `src/tools/semantic_search.py` | 1 query fix |
| `tests/unit/test_graph_rag_tools.py` | 2 new tests (get_code_context, GGSR) |
| `tests/unit/test_semantic_search_tools.py` | 1 new test (explain_with_context) |
| `CHANGELOG.md` | Phase 82 entry |
| `sdd_framework/workflows/phase82_*.md` | Status → Complete |

## Constraints

- **No API changes** — tool signatures, parameters, and return shapes are unchanged
- **No schema changes** — graph data and indexes are untouched
- **No ingestion changes** — ChromaDB collections and Neo4j nodes are unchanged
- **openCypher only** — `toLower(n.name)` is valid on both Neptune and Neo4j
- **No new dependencies** — pure string replacement in existing Cypher
- **Git policy 08** — stage changes only, do not commit or push
