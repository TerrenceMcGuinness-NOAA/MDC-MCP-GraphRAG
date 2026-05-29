# Implementation Plan

## Overview

Make the tenant rollback CLI `delete_tenant_indices.py` actually run against
real AWS. Three faults: `main()` never wires the data layer (`None` stub), the
deletion logic calls four methods that don't exist on the real adapters, and
the unit doubles encode that fictional API so CI stayed green.

- **Fix A — wire `main()`** to the real data layer via the existing
  `build_ingestion_data_access()` helper.
- **Fix B — re-implement the four operations** against the real surface: the
  raw opensearch-py client (`_raw_client()`) for index list/delete/
  delete-by-query, and `NeptuneAdapter.query(..., tenant=None)` for the
  `DETACH DELETE`.
- **Fix C — rewrite the test doubles** to match the real adapter contract, plus
  a fidelity guard, so this mock-only defect can't recur.

TDD ordering: bug-condition exploration test (1, EXPECTED TO FAIL on unfixed
code) → real-contract test doubles (2) → wire `main()` (3) → re-implement
operations (4) → Fix/Preservation/fidelity property+unit tests (5, 6, 7) →
exploration test flips fail→pass (8) → live dry-run verification gate (9,
operator-run) → checkpoint (10). Pure-test tasks are marked `[ ]*`. All paths
are relative to the workspace root `/mdc-mcp-rag/eib-mcp-rag-server/`.

References:
- Bugfix: `.kiro/specs/rollback-cli-real-adapters/bugfix.md` (C(X), Fix/Preservation)
- Design: `.kiro/specs/rollback-cli-real-adapters/design.md` (Changes 1–4, Properties 1–3)
- Blocks: Task 12 of `.kiro/specs/ingest-dedupe-and-graph-fix/` (gw_v17 cleanup + re-ingest)

## Tasks

- [ ]* 1. Write bug condition exploration test (BEFORE any fix)
  - **Property 1: Bug Condition** — Rollback CLI Cannot Run Against Real Adapters
  - **CRITICAL**: This test MUST FAIL on the current unfixed code — the failure confirms the bug
  - **DO NOT fix the test or code when it fails** — the failure is the success criterion for this task
  - **GOAL**: Surface the `AttributeError` that demonstrates `C(X)` — both the `None`-wired path and the fictional-method path
  - Add to `mcp_server_python/tests/unit/test_delete_tenant_indices.py` (or a new `test_rollback_real_adapters.py` — recommend keeping it in the existing file so the rewrite in task 2 is colocated)
  - **Test case 1 — None-wired**: call `run_delete(tenant_id="gw_v17", catalog_path=<tmp>, dry_run=False, vector_db=None, graph_db=None, raw_os_client=None)` for a valid non-empty-prefix tenant; assert it completes WITHOUT `AttributeError`. On UNFIXED code this FAILS (`'NoneType' object has no attribute 'list_indices'`)
  - **Test case 2 — real-contract fake**: drive `_delete_tenant_data` with a fake that exposes ONLY the real surface (`indices.get_alias`/`indices.delete`/`delete_by_query` + Neptune `query`); on UNFIXED code it FAILS because the code calls the fictional `list_indices`/`execute_cypher`
  - Run on UNFIXED code → **EXPECTED OUTCOME: FAILS** (proves the bug). If it PASSES, the root-cause hypothesis is wrong — STOP and re-derive
  - Document the counterexamples (the exact `AttributeError` messages)
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [ ]* 2. Rewrite the test doubles to match the real adapter contract
  - **Property 3: Mock Fidelity** — Doubles Match the Real Surface
  - Per design Change 4. Replace the fictional `StubVectorDB` (`list_indices`/`delete_index`/`delete_by_query`) and `StubGraphDB.execute_cypher` with:
    - `FakeIndices` (sync `get_alias(*, index)` glob via `fnmatch`, `delete(*, index)` recording deletions)
    - `FakeRawClient` (`.indices = FakeIndices(...)`, `delete_by_query(*, index, body)` recording calls)
    - `FakeGraphDB` (async `query(cypher, params=None, *, tenant=None)` recording calls)
  - Update existing assertions to the real shape: `fake.indices.deleted`, `fake.dbq_calls`, `fake_graph.queries[0]` has `params=={"prefix": "GW_V17_"}` and `tenant is None`
  - Add a **fidelity guard test**: assert the doubles expose exactly the method names the script calls (`hasattr(raw.indices, "get_alias")`, `"delete"`, `hasattr(raw, "delete_by_query")`, and `FakeGraphDB.query` is a coroutine)
  - File: `mcp_server_python/tests/unit/test_delete_tenant_indices.py`
  - _Note: these tests will FAIL until the fixes in tasks 3–4 land; that is expected (TDD)._
  - _Requirements: 2.6, 2.8, 3.4, 3.5, 3.6_

- [ ] 3. Wire `main()` to the real data layer
  - Per design Change 1. **File**: `mcp_server_python/scripts/delete_tenant_indices.py`
  - Replace the `TODO(Phase C)` `vector_db = None` / `graph_db = None` stub with a call to `build_ingestion_data_access()` (imported from `_ingest_common`), returning `(uda, raw_os_client)`
  - On connect failure: print a `[ERROR] failed to connect data layer` message naming the env vars (DB_BACKEND / OPENSEARCH_ENDPOINT / NEPTUNE_ENDPOINT / AWS_REGION) and return 1
  - Pass `vector_db=uda.vector_db`, `graph_db=uda.graph_db`, and a new `raw_os_client=raw_os_client` into `run_delete`; `await uda.close()` in a `finally`
  - Thread a `raw_os_client` parameter through `run_delete` → `_delete_tenant_data`
  - _Bug_Condition: isBugCondition(X) — main() supplies None adapters (bugfix.md 1.1, 1.2)_
  - _Expected_Behavior: main() builds a connected data layer (clause 2.1)_
  - _Preservation: run_delete control flow / exit codes unchanged (3.1, 3.2, 3.3)_
  - _Requirements: 2.1_

- [ ] 4. Re-implement the four operations against the real adapter surface
  - Per design Change 2 + Change 3. **File**: `mcp_server_python/scripts/delete_tenant_indices.py` (`_delete_tenant_data`)
  - **list**: `await asyncio.to_thread(raw_os_client.indices.get_alias, index=f"{index_prefix}*")` → keys; filter `startswith(index_prefix)`; wrap in `try/except NotFoundError` → treat as zero indices
  - **delete index**: `await asyncio.to_thread(raw_os_client.indices.delete, index=idx)` per target
  - **Neptune**: `await graph_db.query(cypher, params={"prefix": label_prefix}, tenant=None)` — **`tenant=None` is required** so `_rewrite_cypher` does not mangle the already-prefixed `DETACH DELETE`
  - **registry**: with `--clear-registry-entries`, `await asyncio.to_thread(raw_os_client.delete_by_query, index=SHAIndex.REGISTRY_INDEX, body={"query": {"term": {"tenant_id": tenant_id}}})`
  - Dry-run still calls `get_alias` (read-only) to print an accurate plan, then short-circuits before any delete; the registry delete-by-query line is printed, not executed
  - _Bug_Condition: isBugCondition(X) — fictional adapter methods (bugfix.md 1.3)_
  - _Expected_Behavior: operations target raw opensearch-py client + Neptune query (clauses 2.2, 2.3, 2.4, 2.5)_
  - _Preservation: prefix-scoping, registry-index preservation, DETACH DELETE label scoping unchanged (3.4, 3.5, 3.6)_
  - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.7_

- [ ]* 5. Write the Fix Checking property/unit test
  - **Property 1: Expected Behavior** — Real-Adapter-Backed Rollback Completes
  - For inputs where `isBugCondition(X)` holds: `run_delete` with the real-contract fakes completes without `AttributeError`, calls `get_alias` + `indices.delete`, calls Neptune `query` with `tenant=None`, and (with the flag) issues one scoped `delete_by_query`
  - File: `mcp_server_python/tests/unit/test_delete_tenant_indices.py`
  - Run on FIXED code → **EXPECTED OUTCOME: PASSES**
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.7_

- [ ]* 6. Write the Preservation Checking unit tests
  - **Property 2: Preservation** — Control-Flow Contract Unchanged
  - Unknown tenant → exit 1, no calls on either fake; `gw` (empty prefix) → exit 2, no calls, even with `--clear-registry-entries`; `--dry-run` → exit 0, `fake.indices.deleted == []` and `fake.dbq_calls == []`
  - Prefix scoping: only `gw_v17_*` deleted; `mdc-content-sha-registry` and `gw_sfs_*` untouched
  - File: `mcp_server_python/tests/unit/test_delete_tenant_indices.py`
  - Run on FIXED code → **EXPECTED OUTCOME: PASSES**
  - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [ ]* 7. Add the get_alias NotFoundError + edge-case unit tests
  - `get_alias` raising `NotFoundError` → treated as zero target indices (no crash, empty plan)
  - `--clear-registry-entries` issues exactly one `delete_by_query` scoped to `tenant_id`; registry index never appears in `fake.indices.deleted`
  - File: `mcp_server_python/tests/unit/test_delete_tenant_indices.py`
  - _Requirements: 2.4, 3.5_

- [ ] 8. Verify the exploration test now passes on fixed code
  - **Property 1: Expected Behavior** — Rollback CLI Runs Against Real Adapters
  - **IMPORTANT**: Re-run the SAME test from task 1 — do NOT write a new one
  - Run on FIXED code → **EXPECTED OUTCOME: PASSES** (flips fail→pass — no `AttributeError`)
  - Also run tasks 2, 5, 6, 7 and confirm the full `test_delete_tenant_indices.py` suite is green with no regressions across the broader suite
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

- [ ] 9. Live dry-run verification gate (OPERATOR-RUN)
  - From the operator host with the AWS env vars set, run:
    ```bash
    DB_BACKEND=aws OPENSEARCH_ENDPOINT=... NEPTUNE_ENDPOINT=... AWS_REGION=us-east-1 \
    MCP_EMBEDDING_PROFILE=titan1024 \
    python3.12 mcp_server_python/scripts/delete_tenant_indices.py \
      --tenant gw_v17 --clear-registry-entries --dry-run \
      --catalog mcp_server_python/src/config/tenants.yaml
    ```
  - **EXPECTED**: connects the real data layer, lists the real `gw_v17_*` indices, prints the plan (indices + `GW_V17_*` Neptune labels + the scoped registry delete-by-query), performs ZERO mutations, exits 0 — the invocation that was raising `AttributeError` now succeeds
  - This is read-only (dry-run). The destructive execute path is Task 12 of `ingest-dedupe-and-graph-fix` (separately gated)
  - _Requirements: 2.6, 2.7_

- [ ] 10. Checkpoint — Ensure all tests pass
  - Confirm task 1 (now passing) plus tasks 2, 5, 6, 7 all pass on the fixed code with no regressions, and the live dry-run (task 9) succeeded
  - Ask the user if questions arise

## Follow-up: Defect 4 — Neptune `any()` predicate (found during Task 9)

> **Status note (2026-05-29):** Tasks 1–8 landed (commit c317c91). The live
> verification (originally framed as a dry-run gate) was run as the full
> remediation wrapper, which exposed **Defect 4**: the Neptune node-deletion
> cypher uses the `any()` list predicate, unsupported by Neptune
> (`400 'any' predicate function is not supported`). The OpenSearch deletes had
> already committed, leaving a partial state (3 indices gone; 92 `GW_V17_JJob`
> nodes + 26,316 registry rows remain). Tasks 11–14 fix Defect 4. The fixed
> rollback is idempotent, so a single re-run completes the partial cleanup.

- [ ]* 11. Write the Defect 4 exploration test (BEFORE the fix)
  - **Property 4: Bug Condition** — Neptune Rejects the `any()` Predicate
  - **CRITICAL**: MUST FAIL on the current code — the failure confirms Defect 4
  - Add to `mcp_server_python/tests/unit/test_delete_tenant_indices.py`
  - With a `FakeGraphDB` that raises on a cypher containing `any(` (simulating Neptune's 400), drive `_delete_tenant_data` and assert it completes without that error. On current code it FAILS (the code emits the `any()` cypher)
  - Optionally add a `@pytest.mark.live` integration test that runs the real DISTINCT-labels + per-label delete against Neptune (skipped by default)
  - Run on current code → **EXPECTED OUTCOME: FAILS**. Document the counterexample (the `any()` cypher string)
  - _Requirements: 1.6, 1.7_

- [ ] 12. Replace the Neptune deletion with label-discovery + per-label DETACH DELETE
  - Per design Change (Defect 4) + the mapping-table row. **File**: `mcp_server_python/scripts/delete_tenant_indices.py` (`_delete_tenant_data`)
  - Discover labels: `await graph_db.query("MATCH (n) RETURN DISTINCT labels(n) AS labels", tenant=None)`; flatten; filter to labels starting with `label_prefix` in Python
  - Delete per label: for each matching label, `await graph_db.query(f"MATCH (n:` `` `{lbl}` `` `) DETACH DELETE n", tenant=None)` (back-tick-quoted; no `any()`; no params — labels can't be parameterized)
  - Dry-run prints the discovered labels (read-only DISTINCT-labels query is allowed) without issuing deletes
  - _Bug_Condition: 1.6 (Neptune rejects any())_
  - _Expected_Behavior: 2.5, 2.9, 2.10_
  - _Preservation: 3.7 (idempotent no-op when labels absent)_
  - _Requirements: 2.5, 2.9, 2.10, 3.7_

- [ ]* 13. Update the test doubles + Fix/Preservation tests for Defect 4
  - **Property 4: Expected Behavior** — Supported-Dialect Neptune Deletion
  - `FakeGraphDB.query` records all cypher calls; assert: (a) one DISTINCT-labels discovery query, (b) one `DETACH DELETE` per matching label, (c) NO call contains `any(`, (d) all calls pass `tenant=None`
  - Preservation/idempotence: when discovery returns no matching labels, zero DETACH DELETE calls are made (safe no-op)
  - Fidelity: the `FakeGraphDB` rejects an `any(`-containing cypher (mirrors Neptune) so a regression to the old predicate is caught
  - File: `mcp_server_python/tests/unit/test_delete_tenant_indices.py`
  - Run on FIXED code → **EXPECTED OUTCOME: PASSES**; task-11 test flips fail→pass
  - _Requirements: 2.5, 2.9, 2.10, 3.7_

- [ ] 14. Re-run live dry-run + complete the partial cleanup (OPERATOR-RUN, GATED)
  - Live dry-run (read-only): same command as task 9; confirm it now also prints the discovered `GW_V17_*` labels and exits 0 with zero mutations
  - **STOP-AND-CONFIRM** before the destructive execute
  - Execute: `delete_tenant_indices.py --tenant gw_v17 --clear-registry-entries` — idempotently completes the partial cleanup (skips already-deleted indices, deletes the 92 `GW_V17_JJob` nodes, clears the 26,316 registry rows)
  - Verify: `gw_v17_*` indices absent, `GW_V17_*` Neptune nodes == 0, registry `tenant_id==gw_v17` rows == 0 → tenant fully clean, ready for re-ingest (Task 12 of `ingest-dedupe-and-graph-fix`)
  - _Requirements: 2.7, 3.7_

## Notes

- **Three faults, one surgical fix.** Fix A (wire main, task 3), Fix B
  (real operations, task 4), Fix C (real-contract doubles, task 2). No public
  adapter API change — the rollback uses the existing `_raw_client()` seam and
  `NeptuneAdapter.query`.
- **Bug-condition methodology.** Task 1 is the exploration test that MUST fail
  on unfixed code. Tasks 5 (Fix Checking) and 6 (Preservation) encode the
  design's correctness properties. Task 8 re-runs the task-1 test to confirm
  fail→pass.
- **The `tenant=None` detail.** The Neptune `DETACH DELETE` must pass
  `tenant=None` so `_rewrite_cypher` does not re-prefix the already-prefixed
  label match — a silent-corruption trap if missed.
- **This unblocks Task 12 of `ingest-dedupe-and-graph-fix`.** Once task 14's
  cleanup completes, the gated destructive re-ingest can proceed.
- **Defect 4 (Neptune `any()`).** Found during the live run of task 9 (executed
  via the remediation wrapper). Neptune supports neither `any()` nor
  `CALL db.labels()`; the fix discovers labels with `DISTINCT labels(n)` and
  deletes per label. Tasks 11–14.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2"] },
    { "id": 2, "tasks": ["3"] },
    { "id": 3, "tasks": ["4"] },
    { "id": 4, "tasks": ["5", "6", "7"] },
    { "id": 5, "tasks": ["8"] },
    { "id": 6, "tasks": ["9"] },
    { "id": 7, "tasks": ["10"] },
    { "id": 8, "tasks": ["11"] },
    { "id": 9, "tasks": ["12"] },
    { "id": 10, "tasks": ["13"] },
    { "id": 11, "tasks": ["14"] }
  ]
}
```
