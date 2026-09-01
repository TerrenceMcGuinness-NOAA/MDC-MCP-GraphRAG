# Phase 83: COTS Name-Type-Tolerant Predicate

**Version**: 1.0.0
**Date**: 2026-09-01
**Status**: Proposed — decision required (Options 1 vs 2)
**Priority**: High
**Depends on**: Phase 82 (BLOCKED — premise falsified, findings inherited)
**Branch**: `develop`

---

## 1. Problem Statement

Phase 82 proved that the COTS benchmark's 7 graph query failures are caused by
**mixed-type `name` property values** in the Neo4j graph, not by a `toString()`
dialect quirk. The `name` property is heterogeneous:

| `name` type | Node count | Example |
|-------------|-----------|---------|
| String | 321,520 | `"forecast_det"` |
| Integer (Long) | **452** | `17` |
| String list | **4** | `["UFSATM","GOCART"]` |

**Behavior gap between engines:**

- **Neptune openCypher**: silently tolerates `toLower(toString(non-string))` —
  coerces any type, never throws.
- **Neo4j Community 5.26**: strict type checking — `toLower()` throws
  `CypherTypeError` on non-string input and **aborts the entire query**.

Neither the original form (`toLower(toString(n.name))`) nor the Phase 82 fix
(`toLower(n.name)`) works on both backends:

| Predicate form | Fails on Neo4j for | Fails on Neptune for |
|----------------|-------------------|---------------------|
| `toLower(toString(n.name))` | 4 list-named nodes | nothing (tolerates) |
| `toLower(n.name)` | 452 integer-named nodes | nothing (tolerates) |

**Constraint**: Neptune has no APOC, no `IS :: TYPE` predicate, and no
`valueType()`, so Neo4j-native type-guard tricks do not port directly.

---

## 2. Proposed Options

The CLI agent executing this spec MUST evaluate both options, choose one, and
document the rationale before implementing.

### Option 1: Type-Tolerant Predicate (pure openCypher)

Emit a single predicate form valid on both backends. The `name` property must
be coerced to a string regardless of its runtime type. Candidate patterns:

**Pattern 1a — `CASE` with `toString()` + list join:**
```cypher
WHERE toLower(
  CASE
    WHEN size([x IN [n.name] WHERE x IS NOT NULL]) > 0
      AND head([x IN [n.name] WHERE x IS NOT NULL]) = n.name
    THEN toString(n.name)
    ELSE reduce(s = '', x IN n.name | s + toString(x) + ' ')
  END
) CONTAINS toLower($param)
```

**Pattern 1b — coalesce + toString on the scalar path only:**
```cypher
WHERE toLower(coalesce(toString(n.name), '')) CONTAINS toLower($param)
```
*(Needs live validation — `toString()` on a list may throw on Neo4j.)*

**Pattern 1c — catch-all with reduce (treats everything as list):**
```cypher
WHERE toLower(
  reduce(s = '', x IN
    CASE WHEN n.name = head([n.name]) THEN [n.name] ELSE n.name END
  | s + toString(x) + ' ')
) CONTAINS toLower($param)
```

**Pros**: Single code path, no backend branching, no `DB_BACKEND` dependency.
**Cons**: Complex Cypher, must be validated on both engines for edge cases
(null, empty list, integer, string, string-list). Performance impact unknown.

### Option 2: Backend-Dialect Branching

Emit different predicates keyed off `DB_BACKEND`:

**Neo4j (COTS) path — use `IS :: STRING` type guard:**
```cypher
WHERE n.name IS :: STRING AND toLower(n.name) CONTAINS toLower($param)
```

**Neptune (AWS) path — keep current form:**
```cypher
WHERE toLower(toString(n.name)) CONTAINS toLower($param)
```

The branching point is in the 4 query-building functions identified in Phase 82
(§2). The `DB_BACKEND` value is already available in the config environment.

**Pros**: Clean, readable, optimal per-engine. Type guard skips non-string
nodes cleanly (they can't match a substring search anyway).
**Cons**: Introduces a real dialect split — two code paths to maintain. Must
verify `IS :: STRING` is not supported on Neptune (would cause a syntax error).

---

## 3. Requirements

### R1: Decision gate
Before any code change, the executing agent MUST:
1. Test each candidate predicate pattern against the live Neo4j COTS database
   (bolt://localhost:7687) with the known problem nodes (452 integers, 4 lists)
2. Test each candidate against Neptune (if accessible) or document assumptions
3. Record which option was chosen and why in this spec (amend §2 with a
   `### Decision` subsection)

### R2: Zero graph query failures on COTS benchmark
Post-fix: `graph_queries.failed_queries == 0` on the full 68-case COTS benchmark.

### R3: No Neptune regression
If Option 2 is chosen, verify the Neptune path is unchanged. If Option 1, verify
the unified predicate works on Neptune (or document that it will be validated on
the AWS side).

### R4: Architecture coverage restored
`architecture` category coverage >= 80% on COTS benchmark (was 40% with 7
failures).

### R5: Affected code sites
Same 4 sites as Phase 82 §2:

| # | File | Line | Function |
|---|------|------|----------|
| 1 | `src/graphrag/ggsr_traversal.py` | ~369 | `_multi_hop_query` (1-hop) |
| 2 | `src/graphrag/ggsr_traversal.py` | ~387 | `_multi_hop_query` (2-hop) |
| 3 | `src/tools/graph_rag.py` | ~491 | `_tool_get_code_context` (fuzzy fallback) |
| 4 | `src/tools/semantic_search.py` | ~816 | `_tool_explain_with_context` (topic lookup) |

### R6: Regression-prevention tests
Add unit tests asserting the chosen predicate form is emitted (not the old one).

---

## 4. Tasks

### Task 1: Decision — evaluate options on live data (Step 1)
- [ ] 1.1 Connect to Neo4j COTS (bolt://localhost:7687, neo4j/gfsworkflow2025)
- [ ] 1.2 Run Option 1 candidate patterns against nodes with integer `name`
- [ ] 1.3 Run Option 1 candidate patterns against nodes with list `name`
- [ ] 1.4 Run Option 2 `IS :: STRING` guard against the same nodes
- [ ] 1.5 If Neptune is accessible, test chosen pattern there too
- [ ] 1.6 Choose Option 1 or 2, document rationale in §2 `### Decision`

### Task 2: Implement the chosen option (Steps 2-3)
- [ ] 2.1 Apply the chosen predicate to site 1 (`ggsr_traversal.py` 1-hop)
- [ ] 2.2 Apply the chosen predicate to site 2 (`ggsr_traversal.py` 2-hop)
- [ ] 2.3 Apply the chosen predicate to site 3 (`graph_rag.py` fuzzy fallback)
- [ ] 2.4 Apply the chosen predicate to site 4 (`semantic_search.py` topic)
- [ ] 2.5 If Option 2: add helper function for dialect-aware predicate emission
- [ ] 2.6 Update docstrings with the rationale and Phase 83 reference

### Task 3: Add regression tests (Step 4)
- [ ] 3.1 Test asserting emitted Cypher matches chosen pattern (per site)
- [ ] 3.2 If Option 2: test both backend paths are exercised
- [ ] 3.3 Run unit + property test suites — no new failures

### Task 4: COTS benchmark validation (Step 5)
- [ ] 4.1 Run full 68-case benchmark with DB_BACKEND=cots
- [ ] 4.2 Confirm graph_queries.failed_queries == 0
- [ ] 4.3 Confirm architecture coverage >= 80%
- [ ] 4.4 Confirm no regressions in other categories
- [ ] 4.5 Compare against Phase 82 pre-fix baseline

### Task 5: Documentation (Step 6)
- [ ] 5.1 Update CHANGELOG.md with Phase 83 entry
- [ ] 5.2 Mark this spec Status: Complete
- [ ] 5.3 Stage all changes (do NOT commit — git policy 08)

---

## 5. Verification Criteria

| Criterion | Gate |
|-----------|------|
| Decision documented in §2 | Rationale subsection present |
| Chosen predicate tested on live Neo4j | Query log evidence |
| Zero graph failures on COTS benchmark | `graph_queries.failed_queries == 0` |
| Architecture coverage >= 80% | Benchmark category result |
| Overall coverage >= 88% | Benchmark overall result |
| No Neptune regression | Unit tests pass / live validation if accessible |
| Regression tests added | Assertions on emitted Cypher |
| CHANGELOG updated | Version entry present |

---

## 6. CLI Execution Plan

```bash
# Step 1: Decision — test patterns on live Neo4j
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_python
PYTHONPATH="$PWD:$PYTHONPATH" python3 << 'PYEOF'
import asyncio
from neo4j import AsyncGraphDatabase

URI = "bolt://localhost:7687"
AUTH = ("neo4j", "gfsworkflow2025")

async def test_patterns():
    drv = AsyncGraphDatabase.driver(URI, auth=AUTH)
    async with drv.session() as s:
        # Count non-string name nodes
        r = await s.run(
            "MATCH (n) WHERE n.name IS NOT NULL "
            "RETURN count(n) AS total, "
            "count(CASE WHEN n.name IS :: STRING THEN 1 END) AS strings, "
            "count(CASE WHEN n.name IS :: INTEGER THEN 1 END) AS ints"
        )
        rec = await r.single()
        print(f"Total: {rec['total']}, Strings: {rec['strings']}, Ints: {rec['ints']}")

        # Option 2: IS :: STRING guard
        print("\n--- Option 2: IS :: STRING guard ---")
        r = await s.run(
            "MATCH (n) WHERE n.name IS :: STRING "
            "AND toLower(n.name) CONTAINS 'forecast' "
            "RETURN n.name AS name, labels(n) AS labels LIMIT 5"
        )
        async for rec in r:
            print(f"  {rec['name']} {rec['labels']}")

        # Option 1b: coalesce + toString
        print("\n--- Option 1b: coalesce(toString(n.name), '') ---")
        try:
            r = await s.run(
                "MATCH (n) WHERE toLower(coalesce(toString(n.name), '')) "
                "CONTAINS 'forecast' "
                "RETURN n.name AS name, labels(n) AS labels LIMIT 5"
            )
            async for rec in r:
                print(f"  {rec['name']} {rec['labels']}")
        except Exception as e:
            print(f"  FAILED: {e}")

    await drv.close()

asyncio.run(test_patterns())
PYEOF

# Steps 2-4: Implement, test, benchmark (after decision)
# See Tasks 2-4 above

# Step 5: COTS benchmark
PYTHONPATH="$PWD:$PYTHONPATH" \
  DB_BACKEND=cots \
  NEO4J_URI=bolt://localhost:7687 \
  NEO4J_USER=neo4j \
  NEO4J_PASSWORD=gfsworkflow2025 \
  CHROMADB_HOST=127.0.0.1 \
  CHROMADB_PORT=8080 \
  python3 scripts/run_benchmark.py \
    --results-dir /tmp/bench_cots_phase83_$(date +%F)

# Step 5 gate check:
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
ok = gq["failed_queries"] == 0 and arch >= 0.80 and overall >= 0.88
print(f"\n{'[PASS]' if ok else '[FAIL]'} Phase 83 gates")
sys.exit(0 if ok else 1)
PYEOF
```

---

## 7. Phase 82 Findings Reference

### Data collected during Phase 82 execution

- **Pre-fix COTS baseline**: `/tmp/bench_cots_2026-09-01/2026-09-01T19-46-03.json`
  - Graph failures: 7, Architecture: 40%, Overall: 80%, Precision: 0.59
- **Post-fix (toString removed)**: identical — 7 failures, 40%, 80%
- **Node type distribution**: 321,520 string / 452 integer / 4 list
- **Failing shapes**: GGSR 2-hop (5/9 fail), topic enrichment (2/2 fail)
- **Phase 82 SDD session**: `session_2026-09-01_anet1u` — status: blocked

### Key insight
The `name` property is **ingestion-controlled** — the 452 integers and 4 lists
came from the graph-building pipeline. Option 3 (ingest-side normalization) is
valid long-term but out of scope for this phase. Options 1 and 2 fix the
query layer without touching ingestion.
