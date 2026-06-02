# Bugfix Requirements Document

## Introduction

The multi-tenant foundation (`omd-tenants-1-foundation`) built a complete
tenant-resolution stack — `resolve_tenant`, the `tenant_aware` decorator, the
`_ctx_var` ContextVar, prefix-scoping on both adapters, and attribution
headers. The `gw_v17` tenant's data is now fully ingested and correct in
OpenSearch and Neptune (verified 2026-05-30). But **no MCP client can reach
any tenant other than the default `gw`**, because the tool layer never wires
the tenancy machinery to the tool surface.

**The defect.** `src/tenancy/resolver.py::tenant_aware(catalog)` is a decorator
factory that pops an optional `tenant_id` kwarg, calls `resolve_tenant`, sets
the ContextVar for the call's duration, and applies the attribution header. It
is fully implemented and unit-tested. **But it is applied to zero tools.** A
repository-wide search for `tenant_aware` / `@wrap` across `src/tools/` finds
no application site — only a docstring mention. As a result:

1. No tool declares or accepts a `tenant_id` parameter, so FastMCP never
   exposes `tenant_id` in any tool's input schema. A client literally cannot
   pass it.
2. Because the decorator is not attached, no tool sets the `_ctx_var`
   ContextVar from a request. Tenant resolution falls through to
   `catalog.defaults.tenant_id` (`gw`) on every call.

**Observed behaviour.** A `search_documentation("JGDAS_ATMOS_ANALYSIS_WDQMS …")`
call returns `*Tenant: gw*` and searches the legacy unprefixed collections —
there is no way to target `gw_v17_*` indices or `GW_V17_*` graph labels from
the client. The `gw_v17` data exists but is unreachable.

**Why the tools still "work" today.** The adapter prefix-scoping helpers and
the `workflow_info` tool use `get_current_tenant_or_none()`, which returns
`None` outside a `tenant_aware` scope and falls back to the `gw`/unprefixed
path. So every call silently serves the `gw` baseline. This was a deliberate
transitional safety net (foundation Task 8.2 "defense in depth") that was
never followed by wiring the decorator in — the wiring is the missing step.

**Scope of affected tools.** 52 tools across 9 modules are registered with
`@mcp.tool`. Not all need tenant scoping — the SDD-workflow tools, the utility
tools (`get_server_info`, `mcp_health_check`, etc.), and the static
`workflow_info` tools operate on server-global or filesystem state. The
**tenant-scoped tools** are those that query OpenSearch or Neptune:
`semantic_search` (search_documentation, find_related_files,
explain_with_context, get_knowledge_base_status, check_knowledge_integrity),
`code_analysis` (all 6), `graph_rag` (get_code_context, search_architecture,
find_similar_code, get_change_impact, trace_data_flow), `operational`
(get_operational_guidance, explain_workflow_component, list_job_scripts,
get_job_details), and `ee2_compliance` search tools. The design phase resolves
the exact per-tool list.

**Root cause.** The `omd-tenants-1-foundation` Group F/G work wired the
ContextVar-consuming side (adapters read `get_current_tenant_or_none()`) and
built the decorator, but the final step — decorating each tool registration so
the request-side `tenant_id` flows into the ContextVar — was never completed.
The `omd-tenants-2-v17-pilot` branch-isolation smoke probe (Group D) would have
caught this at Phase C, but Phase C never ran because the tenant data wasn't
correctly ingested until the 2026-05-30 re-ingest.

**Affected files:**
- `src/tools/semantic_search.py`, `code_analysis.py`, `graph_rag.py`,
  `operational.py`, `ee2_compliance.py` — tool registrations needing the
  `tenant_id` parameter + `tenant_aware` wrapper
- `src/tenancy/resolver.py` — `tenant_aware` decorator (already correct;
  reference only, but may need a small adjustment so the wrapped function's
  exposed schema includes `tenant_id` — see design)
- `src/mcp_server.py` (or wherever the per-module `register_*` functions are
  called) — must pass the loaded `catalog` so `tenant_aware(catalog)` can be
  built and applied
- Tests: a new tenant-routing test asserting tools expose `tenant_id` and route
  to the correct prefix

## Bug Analysis

### Current Behavior (Defect)

What happens today when a client tries to target a non-default tenant.

1.1 WHEN a client inspects any tool's input schema, THEN no `tenant_id` parameter is present, because no tool declares it and the `tenant_aware` wrapper is not applied.

1.2 WHEN a client calls any tenant-scoped tool (e.g. `search_documentation`), THEN tenant resolution falls through to `catalog.defaults.tenant_id` (`gw`) because no request sets the `_ctx_var` ContextVar.

1.3 WHEN any tenant-scoped tool runs, THEN the OpenSearch adapter resolves the unprefixed collection and the Neptune adapter uses unprefixed labels, so only the `gw` baseline data is returned regardless of the client's intent.

1.4 WHEN a tool renders its response, THEN the attribution header always reads `*Tenant: gw*`, since `gw` is the only tenant ever resolved.

1.5 WHEN the `gw_v17` (or any non-default) tenant's data is queried, THEN it is unreachable from any MCP client — the `gw_v17_*` indices and `GW_V17_*` graph labels cannot be targeted.

### Expected Behavior (Correct)

What should happen once the decorator is wired and `tenant_id` is exposed.

2.1 WHEN a client inspects a tenant-scoped tool's input schema, THEN a `tenant_id` parameter (optional string) SHALL be present and documented.

2.2 WHEN a client calls a tenant-scoped tool with `tenant_id="gw_v17"`, THEN the `tenant_aware` wrapper SHALL resolve the `gw_v17` TenantContext and set the `_ctx_var` ContextVar for the duration of the call.

2.3 WHEN a tenant-scoped tool runs with `tenant_id="gw_v17"`, THEN the OpenSearch adapter SHALL resolve `gw_v17_`-prefixed indices and the Neptune adapter SHALL use `GW_V17_`-prefixed labels, returning that tenant's data.

2.4 WHEN a tenant-scoped tool renders its response under `tenant_id="gw_v17"`, THEN the attribution header SHALL read `*Tenant: gw_v17*` and `*Branch: dev/gfs.v17*` (per the foundation/branch-line behaviour).

2.5 WHEN a client calls a tenant-scoped tool with an unknown `tenant_id`, THEN the tool SHALL return a clear error naming the unknown id and the known tenant ids (surfacing `UnknownTenantError`), rather than silently falling back.

2.6 WHEN a client calls a tenant-scoped tool WITHOUT `tenant_id`, THEN resolution SHALL follow the existing precedence chain (request → `MCP_DEFAULT_TENANT` → catalog default → `gw`), preserving today's default behaviour.

2.7 WHEN the branch-isolation smoke probe runs after the fix, THEN it SHALL be able to issue `find_dependencies(..., tenant_id="gw_v17")` and `search_documentation(..., tenant_id="gw")` and observe the tenant-scoped results that Assertions 1–4 require.

### Unchanged Behavior (Regression Prevention)

Behaviour that must be preserved.

3.1 WHEN a client calls a tenant-scoped tool without `tenant_id`, THEN it SHALL CONTINUE TO return the `gw` baseline results identically to today (no behavioural change for existing default-tenant clients).

3.2 WHEN a non-tenant-scoped tool is called (utility tools, SDD-workflow tools, static `workflow_info` tools), THEN it SHALL CONTINUE TO behave exactly as today (no `tenant_id` added where it has no meaning).

3.3 WHEN the `gw` tenant (empty prefix) is resolved, THEN the adapters SHALL CONTINUE TO use the unprefixed indices and labels (the passthrough/identity behaviour from foundation P3).

3.4 WHEN a tool's response is rendered for the `gw` tenant, THEN the attribution header SHALL CONTINUE TO read `*Tenant: gw*` / `*Branch: develop*`.

3.5 WHEN existing unit/property tests for the adapters, resolver, and attribution run, THEN they SHALL CONTINUE TO pass unchanged.

### Bug Condition Derivation

**Key definitions:**
- **F** — the original (unfixed) tool layer (decorator defined, never applied).
- **F'** — the fixed tool layer (decorator applied to tenant-scoped tools,
  `tenant_id` exposed in their schemas).
- **X** — an MCP tool call to a tenant-scoped tool `T` with an explicit
  `request_tenant_id` value `R` (where `R` is a valid non-default tenant such
  as `gw_v17`).

**Bug condition C(X):**

```pascal
FUNCTION isBugCondition(X)
  INPUT:  X = (tenant-scoped tool T, request_tenant_id R)
  OUTPUT: boolean

  // The client intends a non-default tenant, but the tool surface
  // provides no way to convey it and the decorator is not attached.
  RETURN T in TENANT_SCOPED_TOOLS
         AND R is a valid catalog tenant_id
         AND R != catalog.defaults.tenant_id   // a non-default tenant
END FUNCTION
```

Under F, `isBugCondition(X)` cannot even be expressed by a client (no
`tenant_id` parameter exists); when approximated by any call to a
tenant-scoped tool, the result is always the `gw` baseline regardless of `R`.

**Fix property (Fix Checking):**

```pascal
FOR ALL X WHERE isBugCondition(X) DO
  result ← F'(X)
  // tenant_id is accepted and routes to the requested tenant
  ASSERT result.resolved_tenant_id = X.R
  ASSERT result.opensearch_index startswith catalog.by_id(R).index_prefix
  ASSERT result.neptune_labels prefixed_with catalog.by_id(R).label_prefix
  ASSERT result.attribution_header contains "*Tenant: " + R + "*"
END FOR
```

**Preservation property (Preservation Checking):**

```pascal
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT F(X) = F'(X)
END FOR
```

Preserved (`NOT isBugCondition(X)`) cases include: calls without `tenant_id`
(still `gw`); calls to non-tenant-scoped tools (unchanged); `gw`-targeted calls
(unprefixed passthrough); and all existing adapter/resolver/attribution tests.
