# Bugfix Requirements Document

## Introduction

The tenant rollback CLI `mcp_server_python/scripts/delete_tenant_indices.py`
(Group G of `omd-tenants-2-v17-pilot`, Requirements R7.1–R7.3) passes all of
its unit tests but cannot run against real AWS. The defect surfaced when
attempting the prerequisite cleanup for Task 12 of the
`ingest-dedupe-and-graph-fix` spec — wiping the broken `gw_v17` data before
re-ingestion. The first real invocation fails immediately:

```
AttributeError: 'NoneType' object has no attribute 'list_indices'
```

Two compounding faults make the tool non-functional, and a third (test
fidelity) is why neither was caught.

**Defect 1 — data layer never wired (None stub).** In `main()` the script
hardcodes the data-access slots to `None`:

```python
# Build real data access layer (only when not testing)
# TODO(Phase C): wire build_unified_data_access() here
vector_db = None
graph_db = None
```

So every CLI invocation (anything not a unit test that injects stubs) reaches
`_delete_tenant_data` with `vector_db=None`, and the first call
`await vector_db.list_indices()` raises `AttributeError`. This is the same
`TODO(Phase C)` stub pattern the v8 ingestion entry scripts originally had;
that pattern was already resolved for them by a shared helper
`build_ingestion_data_access()` in `mcp_server_python/scripts/_ingest_common.py`
(it loads config, builds a connected `UnifiedDataAccess`, and returns the
facade plus the underlying opensearch-py client). The rollback script never
received that wiring.

**Defect 2 — calls four adapter methods that do not exist.** Even with the
data layer wired, the script calls methods that are not implemented on the
real adapters:

- `vector_db.list_indices()` — not on `OpenSearchAdapter`
- `vector_db.delete_index(name)` — not on `OpenSearchAdapter`
- `vector_db.delete_by_query(index=, body=)` — not on `OpenSearchAdapter`
  (used by `--clear-registry-entries`)
- `graph_db.execute_cypher(cypher, params)` — not on `NeptuneAdapter`; the
  real method is `query(cypher, *, tenant=None, params=...)`

The real adapters expose:

- `OpenSearchAdapter`: `connect`, `query`, `multi_collection_query`,
  `health_check`, `close`, `_generate_embedding`, and `_raw_client()` — the
  last returns the underlying opensearch-py client, which DOES provide
  `.indices.get_alias(...)`, `.indices.delete(...)`, and `.delete_by_query(...)`.
- `NeptuneAdapter`: `connect`, `query(cypher, *, tenant, params)`,
  `health_check`, `get_statistics`, `close`.

The rollback operations must therefore be implemented against the **raw
opensearch-py client** (via `_raw_client()`) and the Neptune **`query`**
method — not the fictional methods.

**Defect 3 (root-cause amplifier) — tests validate a fictional adapter
contract.** The unit tests in
`mcp_server_python/tests/unit/test_delete_tenant_indices.py` inject hand-written
`StubVectorDB` / `StubGraphDB` doubles into
`run_delete(..., vector_db=<stub>, graph_db=<stub>)`. Those stubs implement
`list_indices`, `delete_index`, `delete_by_query`, and `execute_cypher` —
methods that exist only on the stubs, never on the real adapters. The suite
passes 100% green while the tool is completely non-functional in production.
The `main()` path that wires the real data layer (the `None` stub) is never
exercised by any test. This is a mock-fidelity defect: the doubles defined an
interface the real code never implemented.

**Defect 4 (follow-up, found during Task 9 live verification) — Neptune
rejects the `any()` predicate.** After Defects 1–3 were fixed, the live run of
the destructive rollback failed in the Neptune step with
`400 'any' predicate function is not supported`. The node-deletion cypher

```
MATCH (n) WHERE any(label IN labels(n) WHERE label STARTS WITH $prefix) DETACH DELETE n
```

uses the openCypher `any()` list predicate, which Amazon Neptune's openCypher
engine does not implement. This cypher came verbatim from
`omd-tenants-2-v17-pilot` design §6 and was never executed against real Neptune
— the test double (`FakeGraphDB.query`) only records the cypher string, so the
mocks again validated a fiction (the same mock-fidelity family as Defect 3).
The OpenSearch index deletes run *before* the Neptune step, so the failed run
left a **partial state**: the three `gw_v17_*` indices were deleted, but the
`GW_V17_*` Neptune nodes (verified: 92 `GW_V17_JJob` orphans from the original
broken ingest) and the 26,316 stale registry rows were NOT cleared.

The Neptune-compatible approach (verified live): `CALL db.labels()` is also
unsupported, but `MATCH (n) RETURN DISTINCT labels(n)` works for label
discovery, and per-label `MATCH (n:` + "`" + `<Label>` + "`" + `) DETACH DELETE n`
works for deletion. The fix discovers the tenant's labels, filters by
`label_prefix` in Python, and issues one `DETACH DELETE` per matching label.

**Root cause.** A dependency-injection test seam (passing `vector_db` /
`graph_db` into `run_delete`) was paired with stub doubles whose API and query
semantics diverged from the real adapters, while production `main()` wiring was
deferred as a `TODO(Phase C)` `None` stub. The fix must (a) wire `main()` to the
real data layer via the existing `build_ingestion_data_access()` helper, (b)
implement the four operations against the real adapter surface (raw opensearch-py
client + Neptune `query`), (c) make the test doubles conform to the real adapter
contract so this class of bug is caught going forward, and (d) replace the
Neptune `any()`-predicate cypher with a label-discovery + per-label
`DETACH DELETE` that Neptune's openCypher engine actually supports.

This bug blocks Task 12 of `ingest-dedupe-and-graph-fix` (the gated cleanup +
re-ingest of `gw_v17`). It is in the implementation of
`omd-tenants-2-v17-pilot` design §6 (rollback path).

**Affected files:**
- `mcp_server_python/scripts/delete_tenant_indices.py` — `main()` `None` stub + four fictional adapter calls
- `mcp_server_python/tests/unit/test_delete_tenant_indices.py` — stubs encode a fictional adapter API; `main()` wiring untested
- `mcp_server_python/scripts/_ingest_common.py` — `build_ingestion_data_access()` (the helper to reuse)
- `mcp_server_python/src/data/opensearch_adapter.py`, `mcp_server_python/src/data/neptune_adapter.py` — real adapter surface (read-only reference)

## Bug Analysis

### Current Behavior (Defect)

What currently happens when the rollback CLI is invoked against real
infrastructure.

1.1 WHEN `delete_tenant_indices.py` is invoked from the command line (not via a unit test that injects stubs) THEN `main()` sets `vector_db = None` and `graph_db = None` and passes them through to `_delete_tenant_data`.

1.2 WHEN `_delete_tenant_data` reaches `await vector_db.list_indices()` with `vector_db is None` THEN the process raises `AttributeError: 'NoneType' object has no attribute 'list_indices'` and exits non-zero before any plan is produced.

1.3 WHEN (hypothetically) the data layer were wired to the real adapters THEN the calls `vector_db.list_indices()`, `vector_db.delete_index(...)`, `vector_db.delete_by_query(...)`, and `graph_db.execute_cypher(...)` would each raise `AttributeError` because those methods do not exist on `OpenSearchAdapter` / `NeptuneAdapter`.

1.4 WHEN the unit suite runs THEN it injects stub doubles implementing the fictional methods, so it passes green — giving a false signal that the tool works, while the `main()` real-wiring path is never exercised.

1.5 WHEN an operator attempts the documented rollback (R7.1–R7.3) or Task 12 of `ingest-dedupe-and-graph-fix` THEN the cleanup cannot be performed at all, blocking the `gw_v17` remediation.

1.6 WHEN the destructive rollback reaches the Neptune step (after Defects 1–3 are fixed) THEN the cypher `MATCH (n) WHERE any(label IN labels(n) WHERE label STARTS WITH $prefix) DETACH DELETE n` raises `400 'any' predicate function is not supported` because Neptune's openCypher engine does not implement the `any()` list predicate.

1.7 WHEN that Neptune step fails THEN the OpenSearch index deletes (which run first) have already committed, leaving a partial state: the `gw_v17_*` indices are deleted but the `GW_V17_*` Neptune nodes and the stale registry rows remain.

### Expected Behavior (Correct)

What should happen once the data layer is wired and operations target the real
adapter surface.

2.1 WHEN `delete_tenant_indices.py` is invoked from the command line THEN `main()` SHALL build a connected data-access layer via `build_ingestion_data_access()` (the same helper the ingestion scripts use) rather than leaving `vector_db` / `graph_db` as `None`.

2.2 WHEN the script lists a tenant's indices THEN it SHALL enumerate real indices through the underlying opensearch-py client (e.g. `_raw_client().indices.get_alias(index=f"{index_prefix}*")`) and filter to those starting with the tenant's `index_prefix`.

2.3 WHEN the script deletes an index THEN it SHALL call the real opensearch-py client `indices.delete(index=...)` (wrapped for async as the codebase does elsewhere).

2.4 WHEN `--clear-registry-entries` is set THEN the script SHALL issue a real `delete_by_query` against `mdc-content-sha-registry` scoped to `{"term": {"tenant_id": <tenant>}}` through the opensearch-py client, and SHALL NOT delete the registry index itself.

2.5 WHEN the script deletes Neptune nodes THEN it SHALL call the real `NeptuneAdapter.query(cypher, params=..., tenant=None)` method (not `execute_cypher`) using a Neptune-compatible deletion that does NOT use the unsupported `any()` predicate (see 2.9, 2.10).

2.6 WHEN `--dry-run` is set THEN the script SHALL connect, list the real target indices, print the full plan (indices, Neptune label prefix, and — if `--clear-registry-entries` — the scoped registry delete-by-query), and perform ZERO mutations.

2.7 WHEN the rollback completes against live AWS THEN the tenant's prefixed OpenSearch indices, its `label_prefix` Neptune nodes, and (with the flag) its registry rows SHALL be removed, unblocking Task 12 of `ingest-dedupe-and-graph-fix`.

2.8 WHEN the unit tests run THEN the test doubles SHALL conform to the REAL adapter contract (the opensearch-py client surface used: `indices.get_alias`, `indices.delete`, `delete_by_query`; and `NeptuneAdapter.query`), so a future divergence between the script's calls and the real adapter API is caught by the suite.

2.9 WHEN the script determines which Neptune labels to delete THEN it SHALL discover labels via `MATCH (n) RETURN DISTINCT labels(n)` (Neptune does NOT support `CALL db.labels()`), flatten the result, and filter to labels starting with the tenant's `label_prefix` in Python.

2.10 WHEN the script deletes the discovered labels THEN it SHALL issue one `MATCH (n:` `` `<Label>` `` `) DETACH DELETE n` per matching label (back-tick-quoted label, no `any()` predicate); for `gw_v17` this resolves to `GW_V17_JJob` (verified: 92 orphan nodes) and any other `GW_V17_*` labels present.

### Unchanged Behavior (Regression Prevention)

Existing behavior that must be preserved.

3.1 WHEN an unknown tenant id is supplied THEN the script SHALL CONTINUE TO exit 1 with the known-IDs hint, making no AWS calls.

3.2 WHEN the target tenant has an empty `index_prefix` or `label_prefix` (i.e. `gw`) THEN the script SHALL CONTINUE TO refuse with exit 2 and the protective message, making no AWS calls — even when `--clear-registry-entries` is set.

3.3 WHEN `--dry-run` is set THEN the script SHALL CONTINUE TO perform zero mutations and exit 0.

3.4 WHEN deletion runs THEN it SHALL CONTINUE TO delete ONLY indices whose names start with the tenant's `index_prefix`; the shared `mdc-content-sha-registry` system index and other tenants' prefixed indices SHALL remain untouched.

3.5 WHEN `--clear-registry-entries` clears registry rows THEN it SHALL CONTINUE TO scope the delete-by-query to `tenant_id == <tenant>` and SHALL CONTINUE TO preserve the registry index itself (only the tenant's rows are removed).

3.7 WHEN the Neptune deletion runs against a tenant whose labels are already absent (e.g. a resumed run after a partial failure) THEN per-label `DETACH DELETE` SHALL be a safe no-op (zero nodes matched), keeping the operation idempotent.

3.6 WHEN Neptune nodes are deleted THEN the cypher SHALL CONTINUE TO be a `DETACH DELETE` scoped to labels starting with the tenant's `label_prefix`.

### Bug Condition Derivation

**Key definitions:**
- **F** — the original (unfixed) rollback CLI.
- **F'** — the fixed rollback CLI.
- **X** — an invocation of `delete_tenant_indices.py` from the command line
  (the production `main()` entry, NOT a unit test that injects stub
  adapters), against a valid non-empty-prefix tenant `T`.

**Bug condition C(X)** — identifies the inputs that trigger the bug:

```pascal
FUNCTION isBugCondition(X)
  INPUT:  X = (cli invocation, tenant T)
  OUTPUT: boolean

  // Production main() leaves the data layer unwired; even if wired,
  // the operations call methods absent from the real adapters, and the
  // Neptune deletion uses the unsupported any() predicate.
  RETURN X.entrypoint = "cli_main"          // not a stub-injected test call
         AND T.index_prefix ≠ ""             // passes the empty-prefix guard
         AND T.label_prefix ≠ ""
END FUNCTION
```

Under F, `isBugCondition(X)` causes the process to raise `AttributeError`
(either `NoneType.list_indices` because the data layer is `None`, or a missing
method on the real adapter once wired) or, after Defects 1–3 are fixed, a
Neptune `400 'any' predicate function is not supported` error — in every case
before the rollback fully completes.

**Fix property (Fix Checking)** — desired behavior for buggy inputs:

```pascal
// Property: Fix Checking — real-adapter-backed rollback
FOR ALL X WHERE isBugCondition(X) DO
  result ← F'(X)
  // Connects the real data layer (no NoneType error)
  ASSERT result.data_layer_connected = TRUE
  // Operations target the real adapter surface (raw opensearch-py + Neptune query)
  ASSERT result.used_raw_opensearch_client = TRUE
  ASSERT result.used_neptune_query = TRUE
  // Neptune deletion uses label-discovery + per-label DETACH DELETE (no any())
  ASSERT result.neptune_delete_used_per_label = TRUE
  ASSERT result.neptune_delete_used_any_predicate = FALSE
  // Dry-run produces a plan with zero mutations; execute removes only prefixed data
  ASSERT result.completed_without_attribute_error = TRUE
  ASSERT result.completed_without_neptune_400 = TRUE
END FOR
```

**Preservation property (Preservation Checking)** — for all non-buggy inputs,
F' behaves identically to F:

```pascal
// Property: Preservation Checking
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT F(X) = F'(X)
END FOR
```

In particular, the preserved (`NOT isBugCondition(X)`) cases include:
- Unknown tenant → exit 1, no AWS calls (clause 3.1).
- Empty-prefix tenant `gw` → exit 2, no AWS calls, even with
  `--clear-registry-entries` (clause 3.2).
- Control-flow / guard logic in `run_delete` (exit codes, prefix filtering,
  dry-run gating) is unchanged — only the adapter-facing operations and the
  `main()` wiring change.
