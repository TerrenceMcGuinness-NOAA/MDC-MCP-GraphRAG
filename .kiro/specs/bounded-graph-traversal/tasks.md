# Implementation Plan — `bounded-graph-traversal`

## Overview

Add bounded-traversal guards (pre-flight degree check, effective depth cap,
statement-timeout backstop, graceful Degraded_Result) to the five graph-traversal
tools so a query from a hyper-connected node degrades to a labeled partial result
instead of timing out or OOM-ing Neptune. Tool-layer change only: a new
`_traversal_bounds.py` constants/helpers module, one additive `timeout` parameter
on `NeptuneAdapter.query`, and the three-step preamble wired into each open-
expansion traversal helper. No ingestion, schema, or tenant-logic change; no
re-ingestion.

Delivered in seven waves: the shared bounds module and the adapter timeout first
(independent), then the per-tool integrations, then the test campaigns, then a
gated live validation and a deploy. The deploy is the same `update-agent-runtime`
path used for Gaps C/D/E.

## Tasks

- [ ] 1. Implement `_traversal_bounds.py` (constants + helpers)
  - New module co-located with the tools (importable as
    `src.tools._traversal_bounds`). Per design §"New module".
  - Env-overridable constants: `FAN_OUT_THRESHOLD` (100), `FULL_CHAIN_DEPTH` (5),
    `CALL_CHAIN_DEPTH` (4), `DATA_FLOW_DEPTH` (5), `RESULT_LIMIT` (200),
    `TIMEOUT_S` (30.0), each via `_int_env`/`_float_env` with safe fallback.
  - `effective_depth(requested, ceiling) -> (int, bool)` clamps to `[1, ceiling]`
    and returns a clamped flag.
  - `degraded_notice(anchor, degree, threshold) -> str` renders the standard
    `[INFO] Highly connected node` block including measured degree + threshold.
  - `anchor_degree(graph_db, name, rel_types, tenant, scope_pred) -> int | None`
    single-hop count probe, tenant-scoped, timeout-wrapped; returns `None` on
    failure/timeout (fail-safe to hub).
  - _Requirements: 1.1, 1.4, 1.5, 2.1, 2.2, 4.2, 4.3, 6.1, 6.2, 6.3_

  - [ ]* 1.1 Unit tests for `_traversal_bounds.py`
    - `effective_depth` over negative/zero/huge/in-range inputs.
    - `anchor_degree` returns count for a small mock node; returns `None` when the
      mocked query raises or times out.
    - `degraded_notice` contains node name, degree, threshold.
    - Env overrides change constants; invalid env values fall back to defaults.
    - File: `mcp_server_python/tests/unit/test_traversal_bounds.py` (new)
    - _Validates: 1.5, 2.1, 4.2, 6.2_

- [ ] 2. Add optional `timeout` parameter to `NeptuneAdapter.query`
  - Per design §"NeptuneAdapter.query". Additive keyword `timeout: float | None =
    None`. When set, wrap the `asyncio.to_thread(self._run_session, ...)` call in
    `asyncio.wait_for`; on `asyncio.TimeoutError` raise `NeptuneAdapterError` with
    a clear timeout message and increment `queries_failed`.
  - `timeout=None` path is byte-for-byte the current behavior (no regression).
  - _Requirements: 5.1, 5.4, 5.5_

  - [ ]* 2.1 Unit tests for the adapter timeout
    - Mocked slow `_run_session` + `timeout=0.01` → raises `NeptuneAdapterError`
      with timeout message; metrics incremented.
    - `timeout=None` → unchanged behavior, existing adapter tests still pass.
    - File: `mcp_server_python/tests/unit/test_data_layer.py` (extend)
    - _Validates: 5.1, 5.4, 5.5_

- [ ] 3. Wire bounds into `code_analysis.py` open-expansion helpers
  - `_call_chain`: degree-gate on `CALLS` (or `SOURCES|INVOKES|EXECUTES` for
    shell) → hub returns a sentinel the caller renders as Degraded_Result; non-hub
    runs `*1..CALL_CHAIN_DEPTH` with `RESULT_LIMIT` and `timeout=TIMEOUT_S`.
  - `_cross_language_nodes` (powers `trace_full_execution_chain`): same gate on the
    six `CROSS_LANGUAGE_EDGES`; `*1..FULL_CHAIN_DEPTH`; timeout.
  - `_callers`: degree-gate (reverse direction) + timeout on the single-hop caller
    query (already one-hop, just add timeout + degree note when large).
  - `_circular_dependencies`: keep `*2..5` + `LIMIT 20`, add `timeout=TIMEOUT_S`.
  - The tool functions (`_tool_trace_execution_path`, `_tool_find_callers_callees`,
    `_tool_trace_full_execution_chain`) render the Degraded_Result via
    `degraded_notice` and the one-hop neighbor list, as a successful response.
  - Preserve `_scope_and(...)` on every emitted query (probe, degraded, expansion).
  - _Requirements: 1.1, 1.2, 1.3, 2.3, 2.4, 3.1, 3.2, 3.3, 4.1, 4.4, 4.5, 5.2, 5.3, 7.5, 8.1_

  - [ ]* 3.1 Tool tests for code_analysis traversals
    - Hub path (mock degree probe > threshold): assert Degraded_Result, labeled,
      non-`[ERROR]`, and `call_log` contains no `*1..` expansion query.
    - Non-hub path: assert bounded `*1..N` query with capped depth + `LIMIT`, and
      rendered result matches pre-feature expectation.
    - Timeout path: expansion mocked to raise timeout → Degraded_Result, no raise.
    - Tenant scoping: every emitted query called with `tenant=` and `_scope_and`.
    - File: `mcp_server_python/tests/unit/test_code_analysis_tools.py` (extend)
    - _Validates: 1.2, 3.4, 4.1, 4.4, 5.3, 7.5_

- [ ] 4. Wire bounds into `graph_rag.py` traversals
  - `trace_data_flow`: clamp shortestPath depth to `DATA_FLOW_DEPTH`; add
    `timeout=TIMEOUT_S` to the outgoing query and the shortestPath query; on
    timeout return a Degraded_Result/notice. (No degree gate — shortestPath does
    not explode the same way.)
  - `get_change_impact`: add `timeout=TIMEOUT_S` to the direct + indirect queries
    (already shallow; timeout is the backstop). Ensure the indirect query keeps a
    `LIMIT` and no post-`WITH` re-sort that defeats push-down.
  - `get_code_context` caller query: add `timeout=TIMEOUT_S` (it's one-hop; cheap
    insurance).
  - Preserve `_scope_and(...)` on every emitted query.
  - _Requirements: 2.1, 2.2, 3.2, 3.3, 5.2, 5.3, 7.5, 8.1_

  - [ ]* 4.1 Tool tests for graph_rag traversals
    - `trace_data_flow` depth clamp applied; timeout path returns notice not raise.
    - `get_change_impact` timeout path handled gracefully.
    - Tenant scoping preserved on all emitted queries.
    - File: `mcp_server_python/tests/unit/test_graph_rag_tools.py` (extend)
    - _Validates: 2.1, 5.3, 7.5_

- [ ]* 5. Property-based tests (P1–P5)
  - P1 Bounded depth always: random `max_depth` (negative/zero/huge) → emitted
    pattern always `*1..N`, `1 <= N <= ceiling`.
  - P2 Hub short-circuit: degree > threshold or `None` → Degraded_Result, no
    expansion query.
  - P3 Non-hub equivalence: deterministic small-graph fixture → rendered output
    byte-equal to pre-feature snapshot.
  - P4 Timeout never raises: expansion mocked to time out at random points →
    never raises.
  - P5 Tenant scoping preserved: random tenant ids → every emitted query carries
    the tenant.
  - File: `mcp_server_python/tests/properties/test_traversal_bounds_props.py` (new)
  - _Validates: 1.2, 2.1, 2.2, 2.4, 3.4, 4.1, 4.4, 5.3, 7.3, 7.4, 7.5_

- [ ] 6. Update CHANGELOG and run full suite
  - CHANGELOG entry under a new version header (next after the current latest).
  - `python3.12 -m pytest tests/unit/ tests/properties/ -q` green; report the
    count vs baseline.
  - _Requirements: 7.1, 7.2, 7.3_

- [ ] 7. Phase A — gated build + deploy + live validation
  - STOP-AND-CONFIRM before ECR push and `update-agent-runtime` (AWS write-safety).
  - Build the image, push a new tag, cut the runtime to the new version (carry the
    full env-var + VPC + EFS payload as in prior deploys).
  - Live checks against `gw`:
    - `trace_full_execution_chain(start="JGLOBAL_FORECAST")` → bounded
      Degraded_Result within the timeout (not OOM/timeout).
    - `find_callers_callees(function_name="JGLOBAL_FORECAST")` → bounded result.
    - `get_code_context(symbol="setuprad")` and a normal `trace_execution_path`
      → full results unchanged (non-hub equivalence).
  - Record the runtime version + image tag; update
    `.kiro/steering/12-multi-tenant-gap-tracker.md` Gap G → RESOLVED.
  - _Requirements: 4.1, 4.4, 7.3 (live)_

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "1.1", "2", "2.1"] },
    { "id": 1, "tasks": ["3", "3.1"] },
    { "id": 2, "tasks": ["4", "4.1"] },
    { "id": 3, "tasks": ["5"] },
    { "id": 4, "tasks": ["6"] },
    { "id": 5, "tasks": ["7"] }
  ]
}
```

Wave 0 lands the two independent foundations (the bounds module and the adapter
timeout) with their unit tests. Waves 1 and 2 wire the guards into the two tool
files (code_analysis depends on the bounds module; graph_rag likewise — they are
independent of each other and could run in parallel, but are sequenced to keep
review focused). Wave 3 runs the property campaign once all integrations exist.
Wave 4 is the CHANGELOG + full-suite gate. Wave 5 is the gated build/deploy/live
validation — the only wave with AWS side effects.

## Notes

- **The degree check is the actual fix.** Depth caps and the timeout are
  defense-in-depth; the pre-flight single-hop count is what prevents the
  combinatorial Path_Materialization from ever starting on a hub node.
- **`LIMIT` is not a guard by itself.** Neptune materializes all matching paths
  before applying `LIMIT`, so the existing `LIMIT 200` clauses did not prevent the
  OOM. This is why the degree gate and depth cap are required, not just a smaller
  `LIMIT`.
- **Deploy required (unlike Gap F).** Gap F was an offline ingest script; this is
  served tool code, so it follows the same build → ECR push → `update-agent-runtime`
  path as Gaps C/D/E. Carry the full lossless deploy payload (env vars, VPC subnets,
  SG, EFS access point, MMDSv2/S3-endpoint flags).
- **Backward compatibility is the bar for non-hub nodes.** Property 3 + the
  non-hub tool tests are the contract: a normal symbol's traversal must return the
  same results it does today. The guards only change behavior for hub nodes and
  timeouts.
- **Tenant scoping must survive every new query.** The degree probe and the
  one-hop degraded query are new emitted queries — each must carry `tenant=` and
  the `_scope_and` predicate, same as the expansion they guard (Property 5).
- **Server-side abort is a deferred follow-up.** The timeout is client-side
  (`asyncio.wait_for`); passing Neptune's `queryTimeoutMillis` to abort the
  statement server-side is noted in the design's Open Questions, not in scope here.
