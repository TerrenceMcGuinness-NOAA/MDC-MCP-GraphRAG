# Task 8 — the two remaining read-path corrections

Implement **Task 8 (sub-tasks 8.1 and 8.2) from tasks.md.**

Both are independently shippable and small. Task 7.3 landed in step 8, so
`query()` now routes through `resolve_read_targets` on both adapters and the
Read_Router is the only component that applies an `index_prefix` on the read path.
These two corrections close what that substitution left behind.

## Files you own

- MODIFY `mcp_server_python/src/graphrag/graph_guided_retrieval.py`   (8.1)
- MODIFY `mcp_server_python/src/tools/semantic_search.py`             (8.2)
- MODIFY `mcp_server_python/src/data/opensearch_adapter.py`           (8.2, docstring only)
- NEW    tests under `mcp_server_python/tests/unit/` for both sub-tasks

Do NOT modify `read_router.py`, `collection_scope.py`, `vector_errors.py`,
`protocols.py`, `chromadb_adapter.py`, anything under `scripts/`, or anything in
`tests/baselines/`.

## 8.1 — GGSR bypasses tenancy entirely

`GraphGuidedRetrieval._safe_semantic_enrich` (line ~233) calls
`self._vector_db.query(collection, query_text, k=..., similarity_threshold=...,
include_graph=False)` and **passes no `tenant=`**. The adapter's signature defaults
`tenant=None`, which the Read_Router treats as the unprefixed default. So every
GGSR-enriched read resolves as if it were the default tenant, whatever tenant is
actually active — tenancy is bypassed, not merely degraded.

Add a `tenant` parameter to `_safe_semantic_enrich` and forward it to
`query(...)`. Thread it from the caller at line ~178 (`vector_coro =
self._safe_semantic_enrich(...)`). Keep the default `None` so existing callers
that do not pass a tenant keep today's behaviour exactly.

### The physical-name default: verify, do not fix

`DEFAULT_SEMANTIC_COLLECTION = "mdc-code-context-mpnet768"` (line 36) is a
**physical** name, and mpnet768-pinned at that, so it bypasses profile resolution
entirely. That is a real layering violation and it is **out of scope. Leave the
constant alone.**

It is latent rather than live because `graph_rag.get_code_context` passes
`default_collection=CODE_COLLECTION` and `collection=CODE_COLLECTION`, so the
physical default is never actually the value that reaches the adapter today.

What you must verify is the failure mode if it ever does: a physical name is not a
key of `PRODUCTION_INDICES_BY_PROFILE`, so `scope_of()` returns `None` and the
Read_Router takes its R1.5 `tenant` fallback — one prefixed member,
`fallback_applied=True`, `classification="tenant-fallback"`, and **no exception**.
Write a test proving it resolves cleanly rather than raising. That test is the
guard that keeps this latent instead of becoming a live outage if a caller ever
stops passing `collection=`.

Tests: the tenant reaches the adapter (assert on the captured `tenant=` kwarg);
the R1.5 fallback path for the physical-name default resolves without raising.

_Requirements: 1.5, 2.5_

## 8.2 — three citations, and one of them is on dead code

Three comments cite the wrong invariant for default-tenant preservation. Verified
locations and current text:

| File:line | Currently says | Must cite |
|---|---|---|
| `src/tools/semantic_search.py:476` | `(Property 4 / R3.5)` | Property 3 |
| `src/tools/semantic_search.py:894` | `(Property 4)` | Property 3 |
| `src/data/opensearch_adapter.py:274` | `yields passthrough (R3.3)` | Property 3 |

The correct citation is **Property 3 (Empty-prefix passthrough)** of
`.kiro/specs/omd-tenants-1-foundation/design.md`, confirmed at line 1171 of that
document: for any tenant with an empty `index_prefix` and any collection `c`,
`resolve_tenant_index(c, T) == c`. **Property 4 is Resolution determinism**
(line 1181) — repeated invocations agreeing with each other, which is a different
claim entirely. The mis-citation has already propagated; do not leave it.

### Do not "correct" the citations that are already right

`opensearch_adapter.py` lines **180** and **205** cite this spec's `R3.3` and
`R3.7` for the multi-member merge, and they are **correct** — R3.3-R3.8 genuinely
govern sets with more than one member. Only line **274**, inside
`resolve_tenant_index`'s docstring, is describing empty-prefix passthrough and
therefore mis-cites. Two different R3.3s are in play: this spec's (multi-member
merge) and the invariant at line 274 (passthrough). Read each line before
touching it.

### `resolve_tenant_index` is now dead, and you are not deleting it

Step 8's substitution left `resolve_tenant_index` orphaned — it is called from
nowhere in `src/`, on either adapter. `_render_vector_status_block` was expected
to call it but does not; it derives `prefix = tenant.index_prefix if tenant else
""` independently, which is exactly the query-path/status-path divergence Tasks 10
and 11 exist to close.

So you are fixing a docstring on dead code. Do it anyway — R6.4 asks for the
citation to be right, it is two words, and the method is still public API that a
future caller could reach for. **Do not delete either definition.** Removal is a
Task 10 decision, once the status path routes through `tenant_collection_set` and
the method is provably unreachable rather than merely uncalled.

Test: assert neither file cites Property 4 as the default-preservation invariant.
Write it so it would fail if the mis-citation were reintroduced anywhere in either
file, not just at the three lines above.

_Requirements: 6.4_
