# Requirements Document

## Introduction

When a tenant's OpenSearch index is genuinely absent (i.e. ingestion has not
populated it for that tenant yet), four tools return inconsistent diagnostics:

- `search_architecture` → raw `[ERROR] search_architecture failed:
  NotFoundError(404, 'index_not_found_exception', 'no such index
  [gw_v17_mdc-community-summaries-titan1024]', ...)`.
- `find_similar_code` → raw `[ERROR] find_similar_code failed:
  NotFoundError(404, ...)`.
- `get_operational_guidance` → raw `[ERROR] get_operational_guidance
  failed: NotFoundError(404, ...)`.
- `search_documentation` (multi-collection mode) → silently returns
  `No results found for: "..."`.
- `search_documentation` (explicit `collection=` mode) → same raw
  `[ERROR]` shape as the other three.

The leak of internal exception text is poor user experience and inconsistent
across the surface. This spec aligns the four tools on a single SKIP-shaped
diagnostic — `[INFO] No results: collection X is not provisioned for tenant Y`
— so a missing index is reported as a clean configuration condition, not a
runtime failure.

This is a companion spec to `opensearch-tenant-resolution-fix`. After that
spec lands, the v17 vector-search 404 wave for the **mapped** indices is
gone (the resolved index name is correct). What remains is the genuine
"index does not exist for this tenant" case (e.g. v17 has no
`gw_v17_mdc-community-summaries-titan1024`, no
`gw_v17_mdc-ee2-standards-*`, no mpnet/nova variants). Those calls SHOULD
succeed-with-skip rather than fail, and they SHOULD all use the same
rendered shape.

The fix is tool-layer only — a small helper that detects the
`index_not_found_exception` condition and returns a consistent
`[INFO]`-prefixed block. No data-layer changes, no new collections, no
re-ingestion.

## Glossary

- **Missing_Index_Condition**: an OpenSearch search call raises a 404 with
  a body whose `type` is `index_not_found_exception`. The Resolved_Index
  was correctly computed but the index does not exist on the cluster.
- **Resolved_Index**: the final OpenSearch index name a query targets,
  after both `resolve_index` (Logical_Collection → Real_Index_Name) and
  the tenant `index_prefix` have been applied (per the
  `opensearch-tenant-resolution-fix` spec).
- **Skip_Block**: the standardised tool-layer diagnostic this spec
  introduces — a single `[INFO]` line plus a one-line reason, the same
  shape across all four tools.
- **Affected_Tools**: the set `{search_architecture, find_similar_code,
  get_operational_guidance, search_documentation}`. These are the four
  tenant-scoped, vector-only tools whose current behaviour is
  inconsistent under the Missing_Index_Condition.
- **Detect_Helper**: a small predicate `_is_missing_index_exc(exc)` that
  returns True iff the exception is a 404 with body type
  `index_not_found_exception` (or string-equivalent fallback). Lives in
  the tool layer next to `_error_text` / `_info_text`.
- **Render_Helper**: a small renderer
  `_missing_index_skip(tool_name, query, collection)` that returns the
  Skip_Block markdown. Same in all four tools (centralised).

## Bug-Condition C(X) — inconsistent rendering on missing index

A caller invokes one of the Affected_Tools with a `tenant_id` whose
prefix family does not yet have the underlying index provisioned (e.g.
`search_architecture(tenant_id="gw_v17")` against
`gw_v17_mdc-community-summaries-titan1024`, which does not exist). The
adapter raises `NotFoundError(404, 'index_not_found_exception', ...)`.

Today's behaviour:

- For three of the four tools, the raw exception text leaks into the
  caller's response as `[ERROR] <tool> failed: NotFoundError(...)`.
- For the fourth (`search_documentation` in multi-collection mode), the
  per-collection swallowing in `multi_collection_query` quietly drops the
  failed collection and returns `[]`, which renders as
  `No results found for: "..."` — silent, no indication that an index is
  missing or that this is a configuration condition rather than an empty
  search.

Both shapes are wrong for different reasons. The user's report (item 8)
explicitly calls out the inconsistency. This spec aligns all four on the
Skip_Block.

## Requirements

### Requirement 1: Centralised detection of the Missing_Index_Condition

**User Story:** As a maintainer, I want a single predicate that
identifies the Missing_Index_Condition, so the four tools cannot drift
in how they decide whether to skip vs error.

#### Acceptance Criteria

1. THE codebase SHALL expose a tool-layer helper
   `_is_missing_index_exc(exc: Exception) -> bool` that returns True if
   and only if the exception is an opensearchpy `NotFoundError` with
   `error.type == 'index_not_found_exception'`, OR (string-fallback
   when the exception type is not opensearchpy-specific) the exception's
   string form contains the literal token `'index_not_found_exception'`.
2. THE helper SHALL be defined exactly once and imported from a single
   module (preferred location: `src/tools/_common.py`, alongside other
   shared tool helpers).
3. THE helper SHALL NOT depend on opensearchpy at import time (allow a
   try/except ImportError) so the unit tests do not require the AWS
   SDK to be installed.

### Requirement 2: Centralised renderer for the Skip_Block

**User Story:** As a caller of any of the Affected_Tools, I want the
SKIP shape to be byte-identical across tools so my client logic does
not have to special-case any of them.

#### Acceptance Criteria

1. THE codebase SHALL expose a tool-layer helper
   `_missing_index_skip(*, tool: str, query: str, collection: str,
   tenant_id: str | None) -> str` that returns the Skip_Block markdown.
2. THE Skip_Block SHALL begin with the literal token `[INFO]` (not
   `[ERROR]`) on the first line, mirroring the
   `[INFO] Script content is not available on the hosted Python port`
   precedent already in the codebase.
3. THE Skip_Block SHALL include a single rationale line stating the
   collection name and the active tenant, e.g.
   `Collection 'community-summaries' is not provisioned for tenant
   'gw_v17'.`
4. THE Skip_Block SHALL include a single advisory line pointing the
   caller at `get_knowledge_base_status` for the tenant's available
   collections.
5. THE Skip_Block SHALL be ASCII-only and SHALL NOT include credentials,
   query bodies, exception stack traces, or response payloads.

### Requirement 3: Affected_Tools route Missing_Index_Condition through Render_Helper

**User Story:** As a caller of any of the four Affected_Tools, when the
backing index is missing for my tenant, I want the response to be the
clean Skip_Block, not the raw exception text.

#### Acceptance Criteria

1. WHEN `search_architecture` is invoked AND the underlying
   `vector_db.query` raises a Missing_Index_Condition, THE tool SHALL
   return the Skip_Block instead of `[ERROR] search_architecture
   failed: ...`.
2. WHEN `find_similar_code` is invoked AND the underlying
   `vector_db.query` raises a Missing_Index_Condition, THE tool SHALL
   return the Skip_Block instead of `[ERROR] find_similar_code
   failed: ...`.
3. WHEN `get_operational_guidance` is invoked AND the underlying
   `vector_db.query` raises a Missing_Index_Condition, THE tool SHALL
   return the Skip_Block instead of `[ERROR] get_operational_guidance
   failed: ...`.
4. WHEN `search_documentation` is invoked with an explicit `collection=`
   parameter AND the underlying `vector_db.query` raises a
   Missing_Index_Condition, THE tool SHALL return the Skip_Block instead
   of `[ERROR] Error searching documentation: ...`.
5. WHEN `search_documentation` is invoked in multi-collection mode AND
   the per-collection swallow in `multi_collection_query` discarded one
   or more collections AND the merged hit list is empty, THE tool SHALL
   continue to return its current `No results found for: "..."` rendering
   (Property 4 byte-equivalence on the multi-collection healthy path —
   no new SKIP rendering is introduced for this path; aligning it would
   require a wider data-layer change and is out of scope).
6. THE Missing_Index_Condition SHALL be detected by `_is_missing_index_exc`
   in every tool's exception handler before falling through to the
   generic `[ERROR]` formatting.

### Requirement 4: No regression for healthy paths (Property 4)

**User Story:** As a maintainer, I want every default-tenant call site
to continue producing byte-identical output, so this fix never regresses
the production gw path.

#### Acceptance Criteria

1. WHEN any Affected_Tool is invoked AND the underlying call returns
   results normally, THE rendered output SHALL be byte-equivalent to
   today's output.
2. WHEN any Affected_Tool is invoked AND the underlying call raises an
   exception that is NOT a Missing_Index_Condition (e.g. transport
   error, auth failure, malformed query), THE tool SHALL continue to
   return its current `[ERROR] ... failed: <exc>` rendering. The new
   behaviour applies ONLY to Missing_Index_Condition.
3. THE fix SHALL NOT alter `OpenSearchAdapter.query`,
   `multi_collection_query`, or any other data-layer code.
4. THE fix SHALL NOT introduce a new dependency, environment variable,
   or public tool parameter.

### Requirement 5: Bug-Condition Exploration tests

**User Story:** As a maintainer, I want explicit Bug-Condition Exploration
tests for each of the four tools so the inconsistency cannot return
silently in a future change.

#### Acceptance Criteria

1. THE bugfix SHALL include a unit test for each of `search_architecture`,
   `find_similar_code`, `get_operational_guidance`, and
   `search_documentation` (explicit-collection mode) that:
   - On the unfixed code, asserts the rendered output begins with
     `[ERROR]` and contains the substring `index_not_found_exception`.
   - On the fixed code, asserts the rendered output begins with
     `[INFO]` and contains the active tenant id and the collection name.
   - Confirm both directions before commit (Bugfix Workflow standard).
2. THE bugfix SHALL include a unit test that the helper
   `_is_missing_index_exc` returns True for a synthetic
   opensearchpy-shaped 404 and False for a generic transport error.
3. THE bugfix SHALL include a Property 4 test for each tool: a healthy
   call (mocked hits returned) produces output byte-equivalent to a
   pre-fix snapshot.
4. THE bugfix SHALL include a unit test that
   `search_documentation(multi-collection)` whose backing
   `multi_collection_query` returned `[]` (because every collection
   404'd internally) still renders the legacy `No results found for:
   "..."` line — explicit Property 4 contract for the path that does
   not change.
