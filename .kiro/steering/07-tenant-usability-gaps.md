# Multi-Tenant Usability Gap Assessment (2026-05-30)

Short-form assessment after the corrected `gw_v17` overnight re-ingest
completed. The ingest itself succeeded; two distinct gaps stand between
"data is correct in the stores" and "multi-tenant system is usable from a
client." Captured here so the next session resumes with full context.

## Ingest verification — PASS

The dedupe-graph fix (`ingest-dedupe-and-graph-fix`) is confirmed working
against live AWS. Saturday's re-ingest vs Friday's broken run:

| Dimension | Friday (broken) | Saturday (fixed) |
|---|---|---|
| docs embedded | 26,059 | 26,316 real |
| code embedded | 0 (all refs) | 26,316 real |
| jjobs embedded | 0 | 92 real |
| `GW_V17_File` nodes | 0 | 30,221 |
| `GW_V17_JJob` nodes | 0 | 92 |
| registry keys | sha-only (collided) | per-collection (26316/26316/92) |

OpenSearch `gw_v17_*` indices hold real embedded content (not references).
The `mdc-content-sha-registry` has correct `(collection, sha)` composite keys.
Both defects from the bugfix specs are resolved.

## Gap A — Tool interface does not expose `tenant_id` (RESOLVED 2026-06-02)

**Status: FIXED** — commit `ca44057` on `develop_aws` (CHANGELOG `[8.28.0]`).
Code landed and all 522 tenant/tool tests pass. Deploy to the runtime
(Task 14: image rebuild + `update-agent-runtime`) remains the only gated,
operator-run step before clients can exercise it live.

**Fix shipped (Approach B).** 24 tenant-scoped tools now declare an explicit
`tenant_id: str | None = None` parameter (surfaced in the FastMCP schema) and
route their bodies through `run_tenant_scoped()` → `tenant_scope()` →
`_ctx_var`. The broken `_wire_tenant_aware` monkey-patch (an `*args/**kwargs`
wrapper that could never surface `tenant_id` in the schema) was removed. See
`.kiro/specs/tenant-id-tool-exposure/`.

**Symptom (historical).** Every MCP query tool resolved to the default `gw`
tenant. There was no client-reachable way to query `gw_v17` (or any
non-default tenant). A `search_documentation` call returned `*Tenant: gw*`
and hit the legacy unprefixed collections.

**Root cause (confirmed in source).** The tenancy plumbing is COMPLETE —
`src/tenancy/resolver.py::tenant_aware(catalog)` already pops a
`tenant_id` kwarg, calls `resolve_tenant`, sets the ContextVar, and applies
the attribution header. BUT the tool registrations in `src/tools/*.py`:
  1. do NOT apply the `tenant_aware` wrapper (`@wrap`) to most tools, and
  2. do NOT declare `tenant_id` in the tool's own signature, so FastMCP never
     exposes it in the tool schema.

So the decorator that would consume `tenant_id` is not attached, and even
where it is, the parameter isn't surfaced to the client. Tenant resolution
silently falls through to `catalog.defaults.tenant_id` (gw).

Verified: `search_documentation(query, collection, max_results, include_graph,
similarity_threshold)` — no `tenant_id`. The `tenant_aware` wrapper is defined
but not consistently applied.

**Fix shape (bugfix candidate — see below).** Apply `tenant_aware` to all
query tools AND ensure `tenant_id: str | None = None` is surfaced in each
tool's exposed schema. The branch-isolation smoke probe (v17-pilot Group D)
would have caught this at Phase C — but Phase C never ran (data wasn't ready
until this re-ingest).

## Gap B — Graph has nodes but no relationships (KNOWN, spec'd)

**Symptom.** `GW_V17_File` (30,221) and `GW_V17_JJob` (92) nodes exist, but
ZERO relationships between them. `find_dependencies` / `find_callers_callees`
/ `trace_execution_path` would return empty for gw_v17 even once Gap A is
fixed — the nodes are islands.

**Root cause.** The v8 code/jjobs ingesters create NODES only. The
relationship-producing ingesters (shell graph, code-graph-enriched, python
graph, Rocoto) were never ported to the Python tenant-aware pipeline. This is
the gap the `graph-port-*` spec series addresses:
  - `graph-port-shell-ops` (requirements + design DONE) — SOURCES, INVOKES,
    EXPORTS, DEPENDS_ON_ENV, READS_CONFIG, DEFINES, EXECUTES
  - `graph-port-workflow-structure` (stub) — Rocoto DAG, SETS_ENV
  - `graph-port-python-community` (stub) — Python AST + community detection

Note: the v8 code ingester reports `relationships_created: 0` BY DESIGN — it
was only ever a node-creator. The CALLS/USES edges in the `gw` baseline came
from a separate enriched-code ingestion that also needs porting (folds into
the graph-port series, likely a 4th spec `graph-port-code-relationships` or an
extension of shell-ops).

## Priority order to reach a usable multi-tenant system

1. ~~**Gap A — `tenant_id` on the tools**~~ **DONE** (`ca44057`, [8.28.0]).
   Code landed + tested; only the gated runtime deploy (Task 14) remains.
2. **Gap B — relationship ingesters** (`graph-port-*` series). shell-ops is
   ready to implement (requirements + design done).
3. Rebuild image → update runtime → run v17-pilot Phase C smoke probe (which
   validates both gaps via branch_isolation). The Gap A deploy and this step
   are the same `update-agent-runtime` action.

## Spec inventory (as of 2026-05-30)

| Spec | Status |
|---|---|
| `ingest-dedupe-and-graph-fix` | tasks 1-11 landed; Task 12 (re-ingest) DONE Saturday |
| `rollback-cli-real-adapters` | all 4 defects fixed + verified live |
| `graph-port-shell-ops` | requirements + design DONE; tasks pending |
| `graph-port-workflow-structure` | requirements STUB |
| `graph-port-python-community` | requirements STUB |
| `tenant-id-tool-exposure` (Gap A) | FIXED — `ca44057`, [8.28.0]; Task 14 deploy gated |
