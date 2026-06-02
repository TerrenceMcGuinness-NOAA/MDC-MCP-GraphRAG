# Tenant ID Tool Exposure — Bugfix Design

## Overview

The multi-tenant resolution stack is complete (`resolve_tenant`, the
`tenant_aware` decorator, the `_ctx_var` ContextVar, adapter prefix-scoping,
attribution) but **never wired to the tool surface**: zero of the 52
`@mcp.tool` registrations expose a `tenant_id` parameter or attach the
`tenant_aware` wrapper. Every tenant-scoped call therefore falls through to the
default `gw` tenant, and the freshly-ingested `gw_v17` data is unreachable from
any MCP client.

The fix exposes `tenant_id` on the **tenant-scoped** tools (the ones that touch
OpenSearch/Neptune) and routes it into the existing ContextVar machinery, while
leaving the utility / SDD-workflow / static `workflow_info` tools untouched.

**The central design constraint.** FastMCP builds each tool's input schema by
**introspecting the decorated function's signature**. The existing
`tenant_aware` decorator wraps with `async def inner(*args, tenant_id=None,
**kwargs)` — applying it naively would collapse every tool's explicit
parameters (`file_path`, `query`, …) into `*args/**kwargs`, destroying the
schema. So the design must inject `tenant_id` into the exposed schema **without
erasing the real parameters.** This drives the chosen approach.

## Glossary

- **Tenant_Scoped_Tool**: a tool whose result depends on OpenSearch/Neptune
  data and therefore must honour a `tenant_id` (e.g. `search_documentation`,
  `find_dependencies`). Contrast with server-global tools.
- **Server_Global_Tool**: a tool operating on server/process/filesystem state
  with no tenant dimension (utility, SDD-workflow, static `workflow_info`). It
  does NOT get a `tenant_id`.
- **tenant_aware**: the existing decorator factory in `resolver.py` that pops
  `tenant_id`, calls `resolve_tenant`, sets `_ctx_var`, applies attribution.
- **_ctx_var**: the `ContextVar[TenantContext|None]` the adapters read via
  `get_current_tenant_or_none()`.
- **Schema_Preservation**: keeping each tool's explicit parameters visible in
  the FastMCP-exposed input schema after the wrapper is applied.
- **F / F'**: original (unwired) / fixed (wired) tool layer.

## Bug Details

### Bug Condition

A client calls a Tenant_Scoped_Tool intending a non-default tenant. Today the
tool surface has no `tenant_id` parameter to convey that intent, and the
`tenant_aware` wrapper is not attached, so the request never sets `_ctx_var`
and resolution falls through to `gw`.

**Formal Specification:**
```
FUNCTION isBugCondition(X)
  INPUT:  X = (Tenant_Scoped_Tool T, request_tenant_id R)
  OUTPUT: boolean
  RETURN T in TENANT_SCOPED_TOOLS
         AND R is a valid catalog tenant_id
         AND R != catalog.defaults.tenant_id
END FUNCTION
```

Under F, this condition cannot even be expressed by a client (no `tenant_id`
field); any call to a Tenant_Scoped_Tool returns the `gw` baseline regardless
of intent.

### Examples

- `search_documentation("MPAS Voronoi", tenant_id="gw_v17")` → today: schema
  rejects/ignores `tenant_id`, returns `*Tenant: gw*` baseline. Fixed: returns
  `gw_v17_*` index hits with `*Tenant: gw_v17*`.
- `find_dependencies("dev/jobs/JGDAS_ATMOS_ANALYSIS_WDQMS", tenant_id="gw_v17")`
  → today: unreachable; resolves to `gw`. Fixed: queries `GW_V17_`-labelled
  nodes.
- `get_server_info()` (Server_Global_Tool) → unchanged; no `tenant_id` added.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Calls without `tenant_id` resolve to `gw` exactly as today (clause 3.1).
- Server_Global_Tools get no `tenant_id` and behave identically (clause 3.2).
- `gw` (empty prefix) uses unprefixed indices/labels — passthrough (3.3).
- `gw` attribution header is `*Tenant: gw*` / `*Branch: develop*` (3.4).
- Existing adapter/resolver/attribution tests pass unchanged (3.5).

**Scope:** Only Tenant_Scoped_Tools change. The set is fixed in the design
(see "Tenant-scoped tool inventory"). Everything else is byte-for-byte
unchanged.

## Hypothesized Root Cause

The foundation Group F/G wired the **consuming** side (adapters read
`get_current_tenant_or_none()`) and built the `tenant_aware` decorator, but the
final **producing** step — attaching the decorator and surfacing `tenant_id`
on each tool — was deferred behind the transitional
`get_current_tenant_or_none()` safety net and never completed. Two concrete
faults:

1. **Decorator not applied** — no `@wrap` / `tenant_aware` site in `src/tools/`.
2. **Catalog not threaded** — `register(mcp, data)` functions don't receive the
   catalog, so there's nothing to build `tenant_aware(catalog)` from at
   registration time.

## Correctness Properties

Property 1: Tenant routing

For any Tenant_Scoped_Tool T and valid tenant id R, calling T with
`tenant_id=R` resolves the R TenantContext, scopes the OpenSearch query to
R's `index_prefix` and the Neptune query to R's `label_prefix`, and renders
the `*Tenant: R*` attribution header.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4**

Property 2: Schema preservation

For any Tenant_Scoped_Tool T, after the fix T's FastMCP-exposed input schema
contains ALL of T's original parameters PLUS an optional `tenant_id` string —
no original parameter is lost or renamed.

**Validates: Requirements 2.1**

Property 3: Default preservation

For any Tenant_Scoped_Tool T called WITHOUT `tenant_id`, F'(T) produces the
same result as F(T) — the `gw` baseline (precedence chain unchanged).

**Validates: Requirements 2.6, 3.1, 3.3, 3.4**

Property 4: Server-global tools untouched

For any Server_Global_Tool T, F'(T) == F(T): no `tenant_id` in the schema, no
attribution wrapper, identical behaviour.

**Validates: Requirements 3.2, 3.5**

Property 5: Unknown tenant error

For any Tenant_Scoped_Tool T called with `tenant_id=R` where R is not in the
catalog, F'(T) returns a clear error naming R and the known tenant ids (no
silent fallback).

**Validates: Requirements 2.5**

## Fix Implementation

### Approach decision: explicit `tenant_id` parameter + signature-preserving wrap

Two candidate approaches were considered:

**Approach A (rejected) — apply the existing `*args/**kwargs` decorator.**
Naively decorating each tool with the current `tenant_aware` collapses the
schema (FastMCP sees only `*args/**kwargs`). Could be salvaged with
`inspect.Signature` surgery to re-inject the original params + `tenant_id`, but
that is fragile and obscure.

**Approach B (chosen) — declare `tenant_id` explicitly on each tool, resolve
in-body via a small context-manager helper.** Each Tenant_Scoped_Tool gains an
explicit `tenant_id: str | None = None` parameter (so FastMCP exposes it
naturally, Schema_Preservation is automatic), and wraps its body in a
`tenant_scope(tenant_id)` async context manager that sets/resets `_ctx_var` and
applies attribution. This keeps the signature honest, the schema correct, and
the change uniform and greppable.

### Change 1 — `tenant_scope` context manager (resolver.py)

Add an async context manager alongside the existing `tenant_aware` (which we
keep for any future signature-erasing use, but Approach B does not rely on it):

```python
# src/tenancy/resolver.py

from contextlib import asynccontextmanager

@asynccontextmanager
async def tenant_scope(tenant_id: str | None, catalog: "TenantCatalog"):
    """Resolve tenant_id and bind the ContextVar for the call's duration.

    Yields the resolved TenantContext. Raises UnknownTenantError on an
    unknown id (caller renders the error). Mirrors the resolution the
    tenant_aware decorator performs, but composes cleanly with an explicit
    tenant_id parameter on the tool signature.
    """
    ctx = resolve_tenant(request_tenant_id=tenant_id, catalog=catalog)
    token = _ctx_var.set(ctx)
    try:
        yield ctx
    finally:
        _ctx_var.reset(token)
```

Attribution stays where it is — the tool returns its rendered body and the
registration wrapper applies `attribute(body, ctx.tenant)` (see Change 3).

### Change 2 — thread the catalog into `register(...)`

Each tool module's `register(mcp, data)` gains an optional `catalog`:

```python
def register(mcp: FastMCP, data: Any = None,
             catalog: "TenantCatalog | None" = None) -> None:
    catalog = catalog or get_catalog()   # get_catalog() exists in tenancy.runtime
    ...
```

`get_catalog()` (in `src/tenancy/runtime.py`) is the module-level singleton
already used by health checks/smoke probes, so even callers that don't pass a
catalog resolve the same one. `src/mcp_server.py` is updated to pass the loaded
catalog to each `register_*` for explicitness.

### Change 3 — tenant-scoped tool pattern

Each Tenant_Scoped_Tool declares `tenant_id` and wraps its body. Example
(`search_documentation`):

```python
@mcp.tool(
    name="search_documentation",
    description="Hybrid semantic + graph search ... (accepts optional tenant_id)",
)
async def search_documentation(
    query: str,
    collection: str | None = None,
    max_results: int = 8,
    include_graph: bool = True,
    similarity_threshold: float = 0.1,
    tenant_id: str | None = None,        # NEW — exposed in schema
) -> str:
    try:
        async with tenant_scope(tenant_id, catalog) as ctx:
            body = await _tool_search_documentation(
                data, query=query, collection=collection,
                max_results=max_results, include_graph=include_graph,
                similarity_threshold=similarity_threshold,
            )
            from src.tools._attribution import attribute
            return attribute(body, ctx.tenant)
    except UnknownTenantError as e:
        return _error_text(str(e))      # clear error, no fallback (R2.5)
```

To avoid repeating the try/`tenant_scope`/attribute boilerplate across ~20
tools, the design introduces one tiny helper used inside each tool body:

```python
# src/tools/_tenant_helper.py  (new)
async def run_tenant_scoped(tenant_id, catalog, coro_factory):
    """Resolve tenant_id, run coro_factory() inside the scope, attribute the
    result. coro_factory is a zero-arg async callable returning the rendered
    body. Returns an error string on UnknownTenantError."""
    try:
        async with tenant_scope(tenant_id, catalog) as ctx:
            body = await coro_factory()
            return attribute(body, ctx.tenant)
    except UnknownTenantError as e:
        return f"[ERROR] {e}"
```

Tool body becomes:

```python
return await run_tenant_scoped(
    tenant_id, catalog,
    lambda: _tool_search_documentation(data, query=query, ...),
)
```

### Tenant-scoped tool inventory (the exact set to modify)

| Module | Tools getting `tenant_id` |
|---|---|
| `semantic_search` | search_documentation, find_related_files, explain_with_context, get_knowledge_base_status, check_knowledge_integrity |
| `code_analysis` | analyze_code_structure, find_dependencies, trace_execution_path, find_callers_callees, trace_full_execution_chain, find_env_dependencies |
| `graph_rag` | get_code_context, search_architecture, find_similar_code, get_change_impact, trace_data_flow |
| `operational` | get_operational_guidance, explain_workflow_component, list_job_scripts, get_job_details |
| `ee2_compliance` | search_ee2_standards |
| `workflow_info` | describe_component, get_workflow_structure (read tenant.workflow_root), get_system_configs |

**Explicitly NOT modified (Server_Global_Tools):**
- `utility`: get_server_info, mcp_health_check, get_health_trend, get_quality_metrics
- `sdd_workflow`: all 9 (operate on SDD execution state, not tenant data)
- `graph_rag` session tools: mark_as_modified, get_session_context,
  checkpoint_state, restore_checkpoint (session-scoped, not tenant-scoped)
- `ee2_compliance` content-analysis tools: analyze_ee2_compliance,
  generate_compliance_report, scan_repository_compliance,
  extract_code_for_analysis (operate on passed-in content, not stored data)
- `github_tools`: all 4 (query GitHub API, not the tenant data layer)

The design phase's inventory is authoritative; the requirements' "design phase
resolves the exact list" is satisfied here.

## Data Models

No persistent data-model changes. The only schema change is additive and
in-memory: each Tenant_Scoped_Tool's FastMCP input schema gains an optional
`tenant_id: string` field. No OpenSearch/Neptune/registry schema is touched.

| Element | Before | After |
|---|---|---|
| Tenant_Scoped_Tool input schema | original params | original params + optional `tenant_id` |
| Server_Global_Tool input schema | original params | unchanged |
| `_ctx_var` ContextVar | set by nothing (always None at call) | set by `tenant_scope` per request |

## Error Handling

- **Unknown `tenant_id`** → `UnknownTenantError` caught in
  `run_tenant_scoped`, rendered as `[ERROR] unknown tenant_id=<R>; known:
  [...]` (R2.5). No silent fallback.
- **`tenant_id=None`** → normal precedence chain (request→env→catalog→gw);
  never an error.
- **Catalog unavailable at registration** → `get_catalog()` raises at startup
  (same failure mode as today's health checks); the server fails fast rather
  than registering half-tenant-aware tools.
- **Attribution on non-string bodies** → `attribute()` already passes
  non-strings through unchanged (foundation behaviour); no new handling.

## Testing Strategy

### Validation Approach

Bugfix methodology: an exploration test that FAILS on current code (asserts a
tenant-scoped tool exposes `tenant_id` and routes to the prefix — fails because
the param doesn't exist), then Fix Checking (routing works) and Preservation
(defaults + server-global tools unchanged).

### Exploratory Bug Condition Checking

Register the tools on a FastMCP test instance; introspect
`search_documentation`'s input schema and assert `tenant_id` is present. On
current code this FAILS (no such field). Also: call a tenant-scoped tool with a
stub data layer and assert the resolved ContextVar tenant == requested — fails
today (always `gw`).

### Fix Checking

```
FOR ALL X WHERE isBugCondition(X) DO
  ASSERT F'(X).resolved_tenant == X.R
  ASSERT opensearch query used R.index_prefix
  ASSERT neptune query used R.label_prefix
  ASSERT attribution header == "*Tenant: R*"
END FOR
```

Implemented with a stub `UnifiedDataAccess` that records the index/label its
adapters were asked for, driven through the registered tool with
`tenant_id="gw_v17"`.

### Preservation Checking

```
FOR ALL X WHERE NOT isBugCondition(X) DO ASSERT F(X) = F'(X) END FOR
```

Cases: no-`tenant_id` call → `gw`; Server_Global_Tool schema has no
`tenant_id`; `gw`-targeted call → unprefixed; existing resolver/adapter/
attribution suites pass unchanged.

### Unit / Property / Integration

- **Unit**: schema introspection per Tenant_Scoped_Tool (has `tenant_id`); per
  Server_Global_Tool (no `tenant_id`); `run_tenant_scoped` error path on
  unknown id; `tenant_scope` sets/resets `_ctx_var`.
- **Property**: for any catalog tenant R, a tenant-scoped tool routes to R's
  prefix (Fix Checking generalised); for any Server_Global_Tool, schema is
  unchanged (Preservation).
- **Integration (post-deploy, gated)**: rebuild image, update runtime, then
  the v17-pilot branch-isolation smoke probe issues
  `find_dependencies(..., tenant_id="gw_v17")` / `search_documentation(...,
  tenant_id="gw")` and observes tenant-scoped results (R2.7).

## Out of Scope

- The graph having no relationships for `gw_v17` (Gap B — the `graph-port-*`
  series). This spec makes the tenant data *reachable*; the graph-traversal
  tools will return nodes-only results for `gw_v17` until Gap B lands. That is
  a separate, already-spec'd concern.
- Per-tenant runtime deployment or auth. `tenant_id` is a request parameter on
  the shared runtime, not a deployment boundary.
- Changes to `resolve_tenant`'s precedence chain (unchanged).
