# Task 2 — Read_Router, one resolver for all four consumer paths

Implement **Task 2 (sub-tasks 2.1, 2.2, 2.3, 2.5, 2.6, 2.7) from tasks.md.**

Sub-task **2.4 already landed** in step 0: `tests/properties/conftest.py` exists
and exports `logical_collections`, `tenants`, `prefixed_tenants`, `profiles`, and
the `adapters()` fixture. Use them. Do not recreate them.

Independently shippable: when you are done **nothing calls the router.** Task 7.3
wires the adapters to it. That is not yours.

## Files you own

- NEW `mcp_server_python/src/data/read_router.py`
- NEW `mcp_server_python/tests/unit/test_read_router.py`
- NEW `mcp_server_python/tests/properties/test_scope_routing.py`
- NEW `mcp_server_python/tests/properties/test_scope_fixture_meta.py`  (2.5)

Do NOT modify either adapter, `src/data/collection_scope.py`,
`src/data/protocols.py`, or anything under `src/tools/`. Task 7 owns all of them.
If you find yourself editing an adapter you have started Task 7 — stop.

## What already exists. Use it, do not re-derive it

From `src.data.collection_scope` (landed step 2):
`scope_of(collection) -> CollectionScope | None`, `is_hybrid_domain(collection)
-> bool`, `logical_collections() -> tuple[str, ...]`, `active_scope_transport()
-> str`, `SCOPE_SHARED`, `SCOPE_TENANT`, `CollectionScope`.

From `src.config.aws_config` (pre-existing):
`resolve_index(collection, profile_short_name="titan1024") -> str`,
`get_production_indices(profile) -> dict`, `PRODUCTION_INDICES_BY_PROFILE`.

The live scope table, so you can pin expected values without guessing:

| Logical collection | Scope | Hybrid |
|---|---|---|
| `global-workflow-docs-v8-0-0` | shared | **yes** |
| `ee2-standards-v5-0-0-enhanced` | shared | no |
| `community-summaries` | shared | no |
| `code-with-context-v8-0-0` | tenant | no |
| `jjobs-v8-0-0` | tenant | no |

**Name collision to keep straight:** `logical_collections` exists twice — the
production one in `collection_scope` (keys of the scope table) and the test
generator in `tests/properties/conftest.py` (keys of
`PRODUCTION_INDICES_BY_PROFILE`). They agree today. Do not assume it; if a test
needs them equal, assert it once rather than relying on it silently.

## The five things that are easy to get wrong

**1. Resolve the physical name first, THEN prepend the prefix.** Call
`resolve_index(collection, profile)` and prefix *its result*. Never prefix the
logical identifier. Prefix-first is the exact bug `opensearch-tenant-resolution-fix`
already removed once; reintroducing it yields `gw_v17_code-with-context-v8-0-0`
instead of `gw_v17_mdc-code-context-titan1024`. This is the single highest-value
line in the module — get the order right and most of P1 falls out for free.

**2. `targets` is an ordered tuple, not a Python `set`.** R3.1 requires the
unprefixed member first for a Hybrid_Domain and R3.7's tie-break reads member
position, so ordering is load-bearing. Enforce distinctness by `physical` at
construction instead of leaning on set semantics.

**3. Take `Tenant` explicitly. Do not read the tenancy ContextVar.** Both
adapters already accept `tenant=` and every tool already passes `_tenant()`, so
explicit is the smaller change and it keeps the router a pure function of its
arguments. P9 and the whole Hypothesis suite depend on that purity — a property
generating over tenants cannot bind a ContextVar per example without becoming a
concurrency test. `tenant=None` stays the unprefixed default.

**4. `RoutingDiagnostic.render()` enforces R7.6 itself, not its call sites.**
Inside `render()`: an explicit ASCII encode check, a 1000-character cap with a
truncation marker, and a field whitelist. The record structurally cannot carry
query text or document content because neither is a field — keep it that way.
Diagnostics go to the **log channel only**, never into rendered tool output.

**5. The R1.5 fallback never raises and never returns an empty set.** An
unclassified identifier is treated as `tenant`, yields one prefixed member, sets
`fallback_applied=True`, and emits `classification="tenant-fallback"`. Note in a
docstring why this path cannot mask a config failure: an invalid override raises
`ScopeConfigError` inside `collection_scope` before the router is ever called, so
a load failure structurally cannot arrive here as a fallback.

## Cardinality — the whole contract in four rows

| Case | Members |
|---|---|
| `shared`, non-hybrid | 1, unprefixed, for **every** tenant |
| `tenant` | 1, prefixed — only when `index_prefix` is non-empty |
| `shared` + hybrid + non-empty prefix | 2, **unprefixed first** |
| empty prefix (default `gw`) | collapses every case above to 1, equal to `resolve_index(collection, profile)` |

Consequences to assert directly: under `gw_v17`/`titan1024`,
`tenant_collection_set` holds **six** members for five logical collections (docs
contributes two). Under `gw` it holds **five**. The default-tenant collapse must
be structural — no `if tenant is default` branch.

## Sub-task notes

**2.1** — models frozen with slots. `ResolvedTarget(physical, scope, prefixed)`.
`ResolvedCollectionSet` carries `logical, scope, hybrid, tenant_id, index_prefix,
profile, targets, fallback_applied, unmapped_profile` plus a `physical_names`
property. `CollectionCondition` is a `StrEnum` with `UNPROVISIONED`,
`PROVISIONED_EMPTY`, `PROVISIONED_POPULATED` — you define it here; Task 7.2
implements the classifier that returns it. Test `render()` against non-ASCII
input and a 10 KB collection name.

**2.2** — `resolve_read_targets(collection, tenant=None, *, profile=None)`.
Profile defaults from `MCP_EMBEDDING_PROFILE`. Exactly **one** diagnostic per
resolution. R2.8: `get_production_indices("nova1024")` returns `{}` so
`resolve_index` passes the name through — apply the same scope decision to the
passthrough identifier, leave cardinality unchanged, emit
`classification="unmapped-profile"`. R7.5: a `shared` set with no unprefixed
member emits `classification="routing-misconfiguration"` naming collection and
tenant, and **still returns the set** so the read proceeds over what remains.

Purity is a frozen-dict lookup, a frozenset membership test, a
`PRODUCTION_INDICES_BY_PROFILE` lookup, a string concatenation, and one
`os.environ` read. No socket, no file handle, no existence probe.

**2.3** — `tenant_collection_set` is the single answer to "which physical
collections belong to tenant T", later consumed by the Status_Reporter,
Integrity_Checker, and Health_Reporter so all three agree with the query path.
De-duplicate by physical name; order by `logical_collections()` then within-set
position so repeated invocations enumerate identically. Populate `by_logical`.

**2.5** — optional in tasks.md, included here because it is cheap and it guards
the AWS/COTS sweep: assert both `chromadb` and `opensearch` parameter ids appear
in collected node ids for tests taking `adapters()`, so a future change cannot
quietly drop a backend. Keep it in its own module so it does not collide with the
property modules.

**2.6 / 2.7** — `@pytest.mark.property`, `deadline=None`, `max_examples` >= 100
and 200 for P1. Tag each with the comment
`# Feature: shared-scope-query-routing, Property N: <name>`. P1 prefix-iff-tenant,
P2 default-tenant identity, P5 cross-tenant disjointness, P6 universal
reachability of shared scope, P3 backend invariance (router half), P9 purity.

P3 and P9 are **structural**, not observational. P3 holds because the router
takes no backend argument and reads no backend environment variable — assert that
the resolved names under `DB_BACKEND=aws` equal those under `DB_BACKEND=cots` as
exact case-sensitive strings. P9 holds because there is no I/O — exercise the
router with socket and filesystem access replaced by raising doubles rather than
by inspecting the source.

P6 carries the point of the whole spec: for any tenant, any profile, any `shared`
collection, `resolve_index(c, p)` is a member of the resolved set, and membership
does **not** vary with provisioning state.

_Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.8, 2.1, 2.2, 2.3, 2.8, 2.9, 3.1, 3.5, 3.6, 4.1, 4.2, 4.5, 5.1, 5.4, 5.5, 6.1, 6.7, 7.2, 7.5, 7.6, 7.8, 8.1, 8.2, 8.3, 9.1, 9.4, 10.1, 11.1, 11.2, 11.3, 13.1, 13.2, 13.7_
