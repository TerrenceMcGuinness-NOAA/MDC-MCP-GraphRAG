# Phase 79: Shared-Scope Collection Query Routing Fix

**Status**: DESIGN
**Created**: 2026-08-18
**Session**: phase79_shared_scope_query_routing
**Severity**: HIGH — all non-default tenants are blind to shared knowledge

## Problem Statement

The `scope` property (`"shared"` vs `"tenant"`) was introduced in the unified
ingest manifest and `CollectionNamer` to separate NWS-wide content (docs, EE2
standards, community summaries) from per-branch content (code, jjobs, configs).
The **write side** (ingestion) honours scope correctly: shared sources are
ingested into unprefixed collections, tenant sources get the
`{tenant.index_prefix}` prefix.

The **read side** (query routing in `chromadb_adapter.py` and
`opensearch_adapter.py`) has no concept of scope. `resolve_tenant_index()`
blindly prepends the tenant's `index_prefix` to every collection name. When a
non-default tenant (e.g. `gw_v17`) queries `search_documentation`, the
adapter tries to open `gw_v17_mdc-workflow-docs-mpnet768` — a collection that
does not exist because docs were ingested into the unprefixed
`mdc-workflow-docs-mpnet768`. The query silently 404s inside
`multi_collection_query`, which swallows per-collection exceptions, and the
tool returns zero results.

## Discovered Via

Deep health scan on 2026-08-18 using `mcp_health_check(deep=true,
detailed=true, functional=true)`, `get_knowledge_base_status(all_tenants=true,
tenant_id=<each>)`, and `check_knowledge_integrity(tenant_id=<each>)`.

The v17 tenant reported only 2,610 vector docs across 2 tenant-prefixed
collections while the default `gw` tenant showed 220,538 docs across 15
collections. Three other tenants (`gw_sfs`, `gw_jedi_gfs`, `gw_gefs_v12`)
reported zero vector docs and zero graph nodes despite having reachable
workflow mounts. The root cause is that none of these tenants can reach the
58 shared documentation sources (22K+ docs), EE2 standards (34 docs), or
community summaries (2,113 docs).

## Architecture of the Gap

```
WRITE SIDE (CollectionNamer)             READ SIDE (chromadb_adapter.query)
─────────────────────────────            ──────────────────────────────────
scope="shared" → unprefixed name         resolve_tenant_index() blindly
scope="tenant" → prefixed name           prepends prefix to ALL collection
                                         names — no scope awareness
Result: shared data correctly            Result: non-default tenants
ingested into unprefixed                 query gw_v17_mdc-workflow-docs-*
collections ✓                            which doesn't exist → silent 404 ✗
```

### Call Path (search_documentation, default fan-out)

```
search_documentation(query, tenant_id="gw_v17")
  └─ multi_collection_query(
         ["global-workflow-docs-v8-0-0",     ← shared scope
          "code-with-context-v8-0-0",        ← tenant scope
          "jjobs-v8-0-0",                    ← tenant scope
          "ee2-standards-v5-0-0-enhanced",   ← shared scope
          "community-summaries"],            ← shared scope
         tenant=Tenant(index_prefix="gw_v17_"))
       └─ self.query("global-workflow-docs-v8-0-0", ..., tenant=...)
            └─ resolve_tenant_index("mdc-workflow-docs-mpnet768",
                                    tenant)
                 → "gw_v17_mdc-workflow-docs-mpnet768"  ← DOES NOT EXIST
                 → silently caught, returns []
```

## Impact

| Tenant | Shared Docs Accessible | Shared Standards | Community Summaries |
|--------|------------------------|------------------|---------------------|
| gw (default, no prefix) | ✓ 22,498 | ✓ 34 | ✓ 2,113 |
| gw_v17 | ✗ 0 | ✗ 0 | ✗ 0 |
| gw_sfs | ✗ 0 | ✗ 0 | ✗ 0 |
| gw_jedi_gfs | ✗ 0 | ✗ 0 | ✗ 0 |
| gw_gefs_v12 | ✗ 0 | ✗ 0 | ✗ 0 |

**Every non-default tenant is completely blind to shared knowledge.**

Tools affected: `search_documentation`, `explain_with_context`,
`search_ee2_standards`, `search_architecture`, `find_similar_code`,
`get_code_context`, `find_related_files` — any tool that queries shared
collections.

### v17-Specific Additional Gaps

Beyond the shared-scope routing bug, the v17 tenant has further gaps:

- **Python graph coverage**: 40 Python files under `ush/workflow/` but 0
  Python nodes in the graph (the Python graph ingest was never run for v17).
- **Missing relationship types**: No `IMPORTS` (9,141 in gw) or `DEPENDS_ON`
  (4,032 in gw) edges — confirms the Python ingest never ran.
- **Vector thinness**: Only `gw_v17_mdc-jjobs-titan1024-v9-0-0` (92 docs)
  and `gw_v17_mdc-workflow-docs-titan1024-v9-0-0` (2,518 docs) exist.
  Missing: code-context, community summaries parity, EE2, mpnet768 copies.

These are separate ingestion tasks, but the shared-scope fix is prerequisite
— without it, even a fully ingested v17 would miss 3 of 5 default search
collections.

## Affected Files

### Read-side (query routing) — primary fix targets

| File | What needs to change |
|------|---------------------|
| `mcp_server_python/src/data/chromadb_adapter.py` | `query()` must skip `resolve_tenant_index()` for shared-scope collections |
| `mcp_server_python/src/data/opensearch_adapter.py` | Same — `resolve_tenant_index()` must respect scope |
| `mcp_server_python/src/tools/semantic_search.py` | `DEFAULT_SEARCH_COLLECTIONS` must carry scope metadata, or the adapter must know which collections are shared |

### Scope metadata SPOT — design decision required

The scope information currently lives only in the ingest manifest
(`sources_manifest.yaml`). The query path doesn't read the manifest. Options:

1. **Tag the collection list** — change `DEFAULT_SEARCH_COLLECTIONS` from a
   flat tuple of names to a tuple of `(name, scope)` pairs. The adapter skips
   prefixing when `scope="shared"`. Minimal blast radius.

2. **Teach the adapter** — the adapter reads the manifest (or a derived
   lookup table) at init time and knows which physical collections are shared.
   More correct but couples the adapter to the manifest.

3. **Convention-based** — shared collections never carry a tenant prefix in
   the physical name, so the adapter could check if the prefixed name exists
   and fall back to unprefixed. Fragile and adds latency (two lookups).

4. **Dual-query fan-out** — `multi_collection_query` receives two lists:
   shared (always unprefixed) and tenant (prefixed). Clean separation.

**Recommended**: Option 1 (tagged collection list) for minimum change surface.
The scope tag is the single discriminator; the adapter receives it and skips
prefixing. No manifest coupling, no extra round-trips.

## Scope of Work

### Must-have (fixes the blind-spot)

1. Introduce a scope-aware collection descriptor (namedtuple or dataclass)
   replacing the raw string in `DEFAULT_SEARCH_COLLECTIONS` and
   `CONTEXT_TYPE_COLLECTIONS`.
2. Propagate scope through `multi_collection_query` → `query()`.
3. In `query()`: if `scope == "shared"`, skip `resolve_tenant_index()`.
4. Mirror the fix in `opensearch_adapter.py` for the AWS backend.
5. Unit tests: assert that `search_documentation(tenant_id="gw_v17")` queries
   unprefixed shared collections and prefixed tenant collections.
6. Integration smoke: call `search_documentation` as v17 and confirm results
   come back from shared docs.

### Should-have (validates the fix end-to-end)

7. Update `get_knowledge_base_status(tenant_id="gw_v17")` to report both
   shared and tenant-scoped collection counts, so the status tool no longer
   implies v17 has only 2 collections.
8. Update `check_knowledge_integrity(tenant_id="gw_v17")` to include shared
   collections in its coverage report.
9. Update `_filter_indices_by_tenant()` in the health check to show shared
   collections alongside tenant-prefixed ones.

### Nice-to-have (future)

10. v17 Python graph ingest (separate task, not gated by this fix).
11. v17 code-context + mpnet768 parity ingestion.
12. Backfill `gw_sfs`, `gw_jedi_gfs`, `gw_gefs_v12` graph + vector data.

## Invariants & Constraints

- **No ingestion-side changes.** The write path in `CollectionNamer` is
  already correct. This phase is read-side only.
- **Default tenant (`gw`) must be byte-equivalent.** The fix must not alter
  any behaviour for the default tenant (empty prefix → no prefixing →
  passthrough). This preserves Property 4 from the tenancy spec.
- **`multi_collection_query` must continue to swallow per-collection 404s.**
  A tenant might have tenant-scoped code-context ingested but not jjobs —
  that's a valid partial state, not an error.
- **Both backends.** The fix must apply symmetrically to `chromadb_adapter.py`
  (COTS/on-prem) and `opensearch_adapter.py` (AWS).

## Test Strategy

| Test | Type | What it proves |
|------|------|---------------|
| Unit: scope-aware `query()` skips prefix for shared | unit | Core fix |
| Unit: scope-aware `query()` applies prefix for tenant | unit | No regression |
| Unit: default tenant (`gw`) unchanged | unit | Property 4 |
| Unit: `multi_collection_query` mixes shared + tenant | unit | Fan-out correct |
| Integration: `search_documentation(tenant_id="gw_v17")` returns docs | integration | End-to-end |
| Integration: `get_knowledge_base_status(tenant_id="gw_v17")` shows shared | integration | Status accurate |

## Dependencies

- `tenants.yaml` — reads tenant definitions (no changes needed)
- `collection_namer.py` — source of truth for scope assignments (no changes)
- `sources_manifest.yaml` — scope metadata origin (read-only reference)

## Notes

- The `resolve_tenant_index()` static method is used in both adapters and in
  `_render_vector_status_block()` for the health check. All call sites need
  the scope parameter or an alternative routing mechanism.
- The Node.js server (`mcp_server_node/`) has a parallel implementation in
  `VectorDatabase.js`. It does not use tenant prefixing at query time (it has
  no tenant concept yet), so it is not affected — but if tenancy is ported to
  Node.js, the same pattern must be followed.
- This gap was introduced when the tenant system (Phase 60) added
  `resolve_tenant_index()` without coordinating with the manifest scope model
  (Phase 68). Neither phase anticipated the interaction.
