# Task 3 — content-carrying tenant catalog transport

Implement **Task 3 (sub-tasks 3.1, 3.2) from tasks.md.**

## Why this task exists at all

Requirements 5.3 and 5.7 presuppose an environment variable whose *content* is
byte-identical to a mounted file. That transport does not exist today:
`src/tenancy/runtime.py::get_catalog` reads `MCP_TENANT_CATALOG_PATH`, which
names a *path*. The design records this as a gap the requirements did not
anticipate. You are adding the missing transport.

## Files you own

- MODIFY `mcp_server_python/src/config/tenants.py` (add `load_catalog_from_transport`)
- MODIFY `mcp_server_python/src/tenancy/runtime.py` (switch `get_catalog`)
- NEW `mcp_server_python/tests/unit/test_tenant_catalog_transport.py`
- NEW `mcp_server_python/tests/properties/test_scope_transport.py` (property P4)

## The constraint that will bite you if you miss it

**`load_catalog(path)` keeps its existing signature and behaviour untouched.**
The ingestion scripts under `mcp_server_python/scripts/` import it, and
Requirement 12.2 freezes that directory byte-for-byte — a test enforces it via
SHA-256. `src/tools/smoke_queries.py` imports it too. Only
`runtime.get_catalog()` switches to the new function. Add, do not replace.

## Precedence

`MCP_TENANT_CATALOG_YAML` (inline YAML content) beats
`MCP_TENANT_CATALOG_PATH` (a path) beats the bundled `src/config/tenants.yaml`.
One rule, applied identically under both form factors — no per-environment
branching, which is what Requirement 5.7 is actually asking for.

Both transports must parse through the **same parser**, so byte-identical
content provably yields an equal TenantCatalog, an equal index_prefix, and an
equal Resolved_Collection_Set. That structural equality is what makes P4
testable rather than merely asserted. Memoize the content read.

## The hard-error path

A catalog source that exists and cannot be read or parsed is Requirement 5.6:
raise, name the failing source, resolve nothing, issue no read. Do **NOT**
degrade to the bundled default and do NOT fall back to treating everything as
tenant-scoped. Silent degradation here would reintroduce the blind spot this
whole spec exists to close.

## 3.2 — property P4

`tests/properties/test_scope_transport.py`. Marked `@pytest.mark.property`,
`max_examples >= 100`, tagged:

    # Feature: shared-scope-query-routing, Property 4: Form-factor and transport invariance

**Depends on `tests/properties/conftest.py` from Task 2.4, which has already
landed** (step 0: 343 lines, 11 tests green). Import its generators; do not write
your own, which would defeat the single-source intent.

P4 also references `resolve_read_targets`, which Task 2 owns and which may not
exist yet. If it is absent, write P4 against the transport layer only (equal
catalogs from equal content, across both transports and both simulated form
factors) and leave a clearly marked TODO for the router assertion. Do not create
`read_router.py` yourself.

_Requirements: 5.2, 5.3, 5.6, 5.7, 12.2, 13.7_
