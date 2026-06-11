# Requirements Document

## Introduction

`OpenSearchAdapter.query` resolves a logical collection name to an OpenSearch
index name in the wrong order: it applies the tenant `index_prefix` first, then
asks `resolve_index` to translate the (now-prefixed) legacy collection name to
the real `mdc-<domain>-<profile>` index name. The lookup table is keyed by the
unprefixed legacy name, so the prefixed key is not in the map; `resolve_index`
returns the prefixed legacy name unchanged, and the query falls through to a
non-existent index, raising `NotFoundError(404, 'index_not_found_exception')`.

For the default `gw` tenant the bug is invisible because `index_prefix` is empty
and the lookup matches. For every prefixed tenant (`gw_v17`, `gw_sfs`, etc.)
every tool that searches `code-with-context-v8-0-0`,
`global-workflow-docs-v8-0-0`, `community-summaries`, `jjobs-v8-0-0`, or
`ee2-standards-v5-0-0-enhanced` fails with a raw 404, even though three of those
v17 indices contain ~57,000 ingested documents. The reported v17 vector-side
"writes 0 docs" symptom is therefore a tool-side resolution bug, not an
ingestion gap.

A second, related bug surfaced in the same investigation:
`get_knowledge_base_status`'s vector-side enumeration does not filter by
`tenant.index_prefix`, so `kb_status(gw_v17)` and `kb_status(gw)` report the
same 16-collection / 252,081-document view. The graph-side enumeration of the
same tool *is* tenant-aware (different label-prefix counts per tenant). This
spec fixes both issues in one deploy.

A third, smaller observation: the v17 code index is named
`gw_v17_mdc-code-titan1024`, whereas the gw production convention is
`mdc-code-context-titan1024`. After this resolution-order fix lands, the v17
code search will still 404 (looking for `gw_v17_mdc-code-context-titan1024`)
until that single index is renamed or aliased. This spec captures the rename as
a gated post-deploy operator task, not a code change.

## Glossary

- **Logical_Collection**: the legacy v8 collection name a tool passes to the
  vector adapter, e.g. `code-with-context-v8-0-0`, `community-summaries`.
- **Production_Index_Map**: the `PRODUCTION_INDICES_BY_PROFILE` table in
  `src/config/aws_config.py` that maps a Logical_Collection + embedding profile
  to a Real_Index_Name.
- **Real_Index_Name**: the actual OpenSearch index name an embedding profile's
  documents live in for the default `gw` tenant, e.g. `mdc-code-context-titan1024`.
- **Tenant_Prefix**: the `tenant.index_prefix` string (empty for `gw`,
  `gw_v17_` for the v17 staging tenant, etc.) that scopes every tenant's data
  to a distinct OpenSearch index family.
- **Resolved_Index**: the final OpenSearch index name a query targets, after
  both Production_Index_Map lookup and Tenant_Prefix application.
- **Os_Adapter**: the `OpenSearchAdapter` class in
  `src/data/opensearch_adapter.py`.
- **Resolve_Tenant_Index**: the static method
  `OpenSearchAdapter.resolve_tenant_index(collection, tenant)` that prepends
  `tenant.index_prefix`.
- **Resolve_Index**: the function `src/config/aws_config.py::resolve_index`
  that looks up a Logical_Collection in the Production_Index_Map and returns
  the Real_Index_Name (or the input unchanged on miss).
- **Status_Tool**: the `get_knowledge_base_status` MCP tool whose vector-side
  block currently ignores the active tenant.
- **Vector_Status_Block**: the part of `Status_Tool`'s output that lists
  collections / per-index document counts; today produced by
  `_render_vector_status_block` in `src/tools/semantic_search.py`.

## Bug 1 — Resolution order is reversed in `OpenSearchAdapter.query`

### Bug condition C(X)

`OpenSearchAdapter.query` is invoked with a Logical_Collection (e.g.
`code-with-context-v8-0-0`) and a `tenant` whose `index_prefix` is non-empty
(e.g. `gw_v17_`). The current implementation calls `Resolve_Tenant_Index`
first, producing `gw_v17_code-with-context-v8-0-0`, then calls `Resolve_Index`
on the prefixed string. The Production_Index_Map is keyed by the bare
Logical_Collection, so the prefixed key is not found and `Resolve_Index`
returns the prefixed legacy name unchanged. The OpenSearch query then targets
`gw_v17_code-with-context-v8-0-0`, which does not exist as an index, and the
adapter raises `NotFoundError(404, 'index_not_found_exception')`.

## Bug 2 — `get_knowledge_base_status` vector block is tenant-blind

### Bug condition C(X)

`Status_Tool` is invoked with `tenant_id="gw_v17"` (or any non-default tenant).
The Vector_Status_Block enumerates all OpenSearch indices via
`vector_db.health_check(deep=True)` without any filter on the active tenant's
Tenant_Prefix. The output reports the same 16-collection / 252,081-document
roll-up regardless of which tenant the caller asked about, masking the true
per-tenant footprint and giving an inaccurate impression that v17 is fully
populated when in fact only three v17-prefixed indices exist.

## Requirements

### Requirement 1: Resolve_Index runs before Tenant_Prefix in the adapter

**User Story:** As a tool calling `vector_db.query`, I want the adapter to
translate a Logical_Collection to its Real_Index_Name before applying the
Tenant_Prefix, so that the Resolved_Index targets a real OpenSearch index for
every tenant whose data follows the production naming convention.

#### Acceptance Criteria

1. WHEN `Os_Adapter.query` is called with a Logical_Collection and a `tenant`
   whose `index_prefix` is empty, THE adapter SHALL produce the same
   Resolved_Index it produces today (no behavior change for the default `gw`
   tenant; Property 4 healthy-path equivalence).
2. WHEN `Os_Adapter.query` is called with a Logical_Collection and a `tenant`
   whose `index_prefix` is non-empty, THE adapter SHALL apply Resolve_Index
   first to obtain a Real_Index_Name, THEN apply the Tenant_Prefix, producing
   `f"{tenant.index_prefix}{real_index_name}"` (e.g.
   `gw_v17_mdc-code-context-titan1024`).
3. WHEN the Logical_Collection is not present in the Production_Index_Map for
   the active embedding profile (e.g. a Nova profile or a non-production
   collection name), THE adapter SHALL fall back to applying the Tenant_Prefix
   directly to the Logical_Collection (preserving today's pass-through
   behaviour for unmapped names; R8.4 of the existing aws_config spec).
4. THE same resolution order SHALL apply uniformly to `query`,
   `multi_collection_query`, and any other adapter entry point that targets a
   per-collection index.

### Requirement 2: Vector_Status_Block scopes to active tenant

**User Story:** As a caller of `get_knowledge_base_status` who passes a
`tenant_id`, I want the vector-side roll-up to reflect only that tenant's
indices, so that the reported collection list and document counts match what
that tenant's tools can actually search.

#### Acceptance Criteria

1. WHEN `Status_Tool` is invoked with a `tenant_id` whose Tenant_Prefix is
   empty (default `gw`), THE Vector_Status_Block SHALL list all OpenSearch
   indices that do not begin with any non-empty Tenant_Prefix declared in the
   tenant catalog (i.e. the unprefixed/base set), matching today's `gw`
   behaviour.
2. WHEN `Status_Tool` is invoked with a `tenant_id` whose Tenant_Prefix is
   non-empty (e.g. `gw_v17_`), THE Vector_Status_Block SHALL list only
   OpenSearch indices whose name begins with that Tenant_Prefix, with their
   per-index document counts.
3. THE Vector_Status_Block SHALL include the active Tenant_Prefix value (or
   `(none)` for the default tenant) in its rendered header so the scoping is
   visible to the caller.
4. THE total-documents tally and `Status` flag in the Vector_Status_Block
   SHALL be computed from the tenant-scoped subset, not the global set.
5. THE graph-side block of `Status_Tool` SHALL be unchanged by this fix
   (already tenant-aware via label-prefix rewriting).

### Requirement 3: No regression for existing callers

**User Story:** As a maintainer, I want the resolution-order and status-scoping
fixes to leave every default-tenant call site byte-equivalent, so that the only
observable change is for non-default tenants where the bug was active.

#### Acceptance Criteria

1. THE existing test suite SHALL continue to pass without modification beyond
   adding new tests for the fixed behaviour.
2. WHEN any tool calls the adapter or the status renderer with no
   `tenant_id` (or with `tenant_id="gw"` and an empty `index_prefix`), THE
   produced output SHALL be byte-equivalent to today's output for the same
   inputs against the same OpenSearch state.
3. THE fix SHALL NOT introduce a new dependency, environment variable, or
   public adapter method.
4. THE fix SHALL NOT alter the Production_Index_Map content.

### Requirement 4: Diagnostic logging on resolution miss

**User Story:** As an operator debugging a tenant's tool failure, I want a
log line when a Logical_Collection misses the Production_Index_Map for the
active embedding profile, so I can tell whether a 404 stemmed from an unmapped
collection vs. a missing tenant index.

#### Acceptance Criteria

1. WHEN `Os_Adapter.query` calls Resolve_Index and Resolve_Index returns the
   input unchanged (i.e. miss), THE adapter SHALL log a single info-level line
   identifying the Logical_Collection, the active embedding profile, and the
   tenant id, before issuing the OpenSearch request.
2. THE log line SHALL be ASCII-only and SHALL NOT include credentials,
   query bodies, or response payloads (R8.2 of the bounded-graph-traversal
   precedent).

### Requirement 5: V17 code-index rename — gated post-deploy operator task

**User Story:** As an operator, I want a documented, idempotent operator step
to align the v17 code index with the production naming convention, so that
the resolution-order fix unblocks v17 code search end-to-end.

#### Acceptance Criteria

1. THE spec's tasks SHALL include a documented operator step that renames the
   existing OpenSearch index `gw_v17_mdc-code-titan1024` to the
   convention-matching name `gw_v17_mdc-code-context-titan1024` (or installs
   an OpenSearch alias from the latter to the former), so a query for
   `code-with-context-v8-0-0` under `tenant_id=gw_v17` resolves to the
   ingested ~28,559 docs.
2. THE operator step SHALL be gated, idempotent, and reversible.
3. THE step SHALL document the post-condition: a smoke probe like
   `find_similar_code(tenant_id="gw_v17")` succeeds and returns ranked
   results from the renamed/aliased index.
4. WHERE the v17 community-summaries / ee2-standards / mpnet768 / nova1024
   indices are still missing after this fix, the spec SHALL document that
   `search_architecture(tenant_id="gw_v17")` (and similar) will return a
   clean "no such index" diagnostic — addressed by the companion spec
   `graceful-missing-index-handling`, not by this one.

### Requirement 6: Regression tests (Bug-Condition Exploration)

**User Story:** As a maintainer, I want explicit Bug-Condition Exploration
tests for both bugs so they cannot return silently in a future change.

#### Acceptance Criteria

1. THE bugfix SHALL include a unit test that fails on the unfixed code and
   passes on the fixed code for `Os_Adapter.query` over a non-default tenant
   plus a Logical_Collection in the Production_Index_Map (Bug 1's exploration
   test).
2. THE bugfix SHALL include a unit test for the default-tenant equivalence
   case (Property 4): same inputs, same Resolved_Index pre- and post-fix.
3. THE bugfix SHALL include a unit test that fails on the unfixed code and
   passes on the fixed code for `Status_Tool`'s Vector_Status_Block when the
   active tenant has a non-empty Tenant_Prefix (Bug 2's exploration test).
4. THE bugfix SHALL include a unit test that the diagnostic miss-log line is
   emitted exactly once per query when Resolve_Index returns the input
   unchanged.
