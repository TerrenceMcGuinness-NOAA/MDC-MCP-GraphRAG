# Phase 83 — COTS Name-Type-Tolerant Predicate: Decision + Implementation

## SDD Reference

`sdd_framework/workflows/phase83_cots_name_type_tolerant_predicate.md`

## Background

Phase 82 discovered that 7 COTS graph query failures are caused by **mixed-type
`name` property values** (452 integers, 4 lists among 321,520 strings). Neptune
silently tolerates type mismatches; Neo4j Community throws `CypherTypeError` and
aborts the entire query. Neither `toLower(toString(n.name))` (original) nor
`toLower(n.name)` (Phase 82 fix) works on both backends.

## Your Task

You must **decide between Option 1 and Option 2**, implement it, and validate
on the COTS benchmark. Read the full spec first, then follow the steps.

---

### Step 1 — Decision: Test patterns on live Neo4j (Task 1)

Connect to Neo4j COTS and test both options against the mixed-type nodes:

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_python
PYTHONPATH="$PWD:$PYTHONPATH" python3 << 'PYEOF'
import asyncio
from neo4j import AsyncGraphDatabase

URI = "bolt://localhost:7687"
AUTH = ("neo4j", "gfsworkflow2025")

async def test():
    drv = AsyncGraphDatabase.driver(URI, auth=AUTH)
    async with drv.session() as s:
        # Inventory non-string names
        r = await s.run(
            "MATCH (n) WHERE n.name IS NOT NULL "
            "RETURN count(n) AS total, "
            "count(CASE WHEN n.name IS :: STRING THEN 1 END) AS strings, "
            "count(CASE WHEN n.name IS :: INTEGER THEN 1 END) AS ints"
        )
        rec = await r.single()
        print(f"Nodes: total={rec['total']} string={rec['strings']} int={rec['ints']}")

        # Option 2: IS :: STRING type guard
        print("\n=== OPTION 2: WHERE n.name IS :: STRING AND toLower(n.name) CONTAINS ... ===")
        try:
            r = await s.run(
                "MATCH (n) WHERE n.name IS :: STRING "
                "AND toLower(n.name) CONTAINS 'forecast' "
                "RETURN n.name AS name, labels(n) AS labels LIMIT 5"
            )
            rows = [rec async for rec in r]
            print(f"  OK: {len(rows)} rows returned")
            for row in rows[:3]:
                print(f"    {row['name']} {row['labels']}")
        except Exception as e:
            print(f"  FAILED: {e}")

        # Option 1b: coalesce(toString(), '')
        print("\n=== OPTION 1b: toLower(coalesce(toString(n.name), '')) CONTAINS ... ===")
        try:
            r = await s.run(
                "MATCH (n) WHERE toLower(coalesce(toString(n.name), '')) "
                "CONTAINS 'forecast' "
                "RETURN n.name AS name, labels(n) AS labels LIMIT 5"
            )
            rows = [rec async for rec in r]
            print(f"  OK: {len(rows)} rows returned")
            for row in rows[:3]:
                print(f"    {row['name']} {row['labels']}")
        except Exception as e:
            print(f"  FAILED: {e}")

        # Test: does toString() throw on a list in Neo4j?
        print("\n=== EDGE CASE: toString() on a list-valued name ===")
        try:
            r = await s.run(
                "MATCH (n) WHERE NOT n.name IS :: STRING AND NOT n.name IS :: INTEGER "
                "RETURN n.name AS name, toString(n.name) AS stringified LIMIT 3"
            )
            rows = [rec async for rec in r]
            print(f"  OK: {len(rows)} list-named nodes")
            for row in rows:
                print(f"    raw={row['name']}  toString={row['stringified']}")
        except Exception as e:
            print(f"  FAILED on list: {e}")

        # Test: does IS :: STRING exist on Neptune openCypher?
        # (If you have Neptune access, test this too. If not, document the assumption.)
        print("\n=== Neptune note ===")
        print("  IS :: STRING is Neo4j-specific (Cypher 25).")
        print("  Neptune openCypher does NOT support it.")
        print("  If Option 2 chosen, Neptune path keeps toString() form.")

    await drv.close()

asyncio.run(test())
PYEOF
```

**After running the tests**, decide:

- **Option 1** if a unified predicate works on both backends
- **Option 2** if you need backend-specific predicates (Neo4j uses `IS :: STRING`
  guard, Neptune keeps `toString()`)

Amend the SDD spec `phase83_cots_name_type_tolerant_predicate.md` §2 with a
`### Decision` subsection recording your choice and evidence.

Record: `record_sdd_step(step=1, name="Decision: tested patterns, chose Option N", tag="research")`

---

### Step 2 — Implement chosen predicate (Task 2: 4 sites)

Apply the chosen predicate form to all 4 sites:

**If Option 2 (dialect branching):**

Create a helper in a shared location (e.g. `src/tools/_query_helpers.py` or
inline in each file):

```python
from src.config.environment import load_config

def _name_contains_predicate(var: str, param: str) -> str:
    """Type-tolerant name CONTAINS predicate, backend-aware."""
    cfg = load_config()
    if cfg.db_backend == "cots":
        # Neo4j: skip non-string name values (they can't match a text search)
        return f"{var}.name IS :: STRING AND toLower({var}.name) CONTAINS toLower(${param})"
    else:
        # Neptune: toString() handles all types silently
        return f"toLower(toString({var}.name)) CONTAINS toLower(${param})"
```

Then replace the 4 inline predicates with calls to this helper.

**If Option 1 (unified predicate):**

Replace all 4 sites with the validated pattern from Step 1.

**Sites to update:**

1. `src/graphrag/ggsr_traversal.py` ~line 369 (1-hop)
2. `src/graphrag/ggsr_traversal.py` ~line 387 (2-hop)
3. `src/tools/graph_rag.py` ~line 491 (fuzzy fallback)
4. `src/tools/semantic_search.py` ~line 816 (topic lookup)

Record: `record_sdd_step(step=2, name="Implement predicate at 4 sites", tag="implement")`

---

### Step 3 — Remove the is_testing branch (Task 2 cleanup)

In `src/tools/graph_rag.py` (~line 484), the `is_testing` branch diverges test
vs production Cypher. After the fix, unify to one path using the chosen
predicate. Remove the `import sys as _sys` / `is_testing` check.

Record: `record_sdd_step(step=3, name="Remove is_testing branch divergence", tag="implement")`

---

### Step 4 — Add regression tests (Task 3)

Add tests asserting the emitted Cypher matches the chosen pattern:

- Test per-site that generated Cypher does NOT contain the old pattern
- If Option 2: test both `cots` and `aws` backend paths
- Run full unit + property suites:

```bash
PYTHONPATH="$PWD:$PYTHONPATH" python3 -m pytest tests/unit/ -v --tb=short 2>&1 | tail -30
PYTHONPATH="$PWD:$PYTHONPATH" python3 -m pytest tests/properties/ -v --tb=short 2>&1 | tail -30
```

Record: `record_sdd_step(step=4, name="Regression tests added and passing", tag="validate")`

---

### Step 5 — COTS benchmark validation (Task 4)

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
    --results-dir /tmp/bench_cots_phase83_$(date +%F)
```

**Gates:**

```bash
python3 << 'PYEOF'
import json, glob, sys
results_dir = sorted(glob.glob("/tmp/bench_cots_phase83_*"))[-1]
latest = sorted(glob.glob(f"{results_dir}/*.json"))[-1]
with open(latest) as f:
    d = json.load(f)
gq = d["graph_queries"]
arch = d["categories"]["architecture"]["coverage"]
overall = d["overall"]["coverage"]
print(f"Graph failures:   {gq['failed_queries']}")
print(f"Arch coverage:    {arch:.0%}")
print(f"Overall coverage: {overall:.0%}")
failed = []
if gq["failed_queries"] != 0:
    failed.append(f"graph failures: {gq['failed_queries']} (want 0)")
if arch < 0.80:
    failed.append(f"arch coverage: {arch:.0%} (want >=80%)")
if overall < 0.88:
    failed.append(f"overall: {overall:.0%} (want >=88%)")
if failed:
    print("\n[FAIL]")
    for f in failed: print(f"  - {f}")
    sys.exit(1)
print("\n[PASS] All Phase 83 gates met")
PYEOF
```

Record: `record_sdd_step(step=5, name="COTS benchmark gates met", tag="validate")`

---

### Step 6 — Documentation (Task 5)

1. Update `CHANGELOG.md` with Phase 83 entry
2. Update the SDD spec status to Complete, check all task boxes
3. Stage all changes: `git add -A` (do NOT commit — git policy 08)

Record: `record_sdd_step(step=6, name="CHANGELOG and docs updated", tag="document")`

Then: `complete_sdd_session(summary="Phase 83 complete: type-tolerant name predicate, 0 COTS graph failures")`

---

## Constraints

- **No API changes** — tool signatures unchanged
- **No schema/ingestion changes** — graph data untouched (Option 3 deferred)
- **No Neptune regression** — Neptune path must remain functional
- **Git policy 08** — stage only, do not commit or push
- **openCypher subset** — if Option 1, predicate must be valid on both engines
