# Implementation Plan — `opensearch-tenant-resolution-fix`

## Overview

Two focused tool-layer bug fixes shipped in one image. Bug 1 swaps the order of
operations in `OpenSearchAdapter.query` so `resolve_index` runs before the
tenant-prefix is applied — closes the v17 vector-search 404 wave. Bug 2 makes
`get_knowledge_base_status`'s vector block tenant-aware. A small post-deploy
operator step adds an OpenSearch alias so v17 code search reaches the
existing `gw_v17_mdc-code-titan1024` index. Both code fixes carry a
Bug-Condition Exploration test per the workspace's Bugfix Workflow standard.

Delivered in five waves: Bug 1 + tests, Bug 2 + tests, CHANGELOG + suite,
gated build/deploy/live validation, gated alias creation.

## Tasks

- [x] 1. Bug 1 fix — swap resolution order in `OpenSearchAdapter.query`
  - In `src/data/opensearch_adapter.py::OpenSearchAdapter.query`, swap the
    two-line `scoped = ...; index = resolve_index(scoped, ...)` block so
    `resolve_index` runs first against the bare `collection` and the tenant
    prefix is applied to the **resolved** name.
  - Apply the same swap consistently in `multi_collection_query` (verify
    whether it goes through `query` per-collection or has its own resolution
    inline; if inline, fix in-place).
  - Add the info-level "passthrough" log line emitted when `resolve_index`
    returns the input unchanged (R4.1, R4.2). ASCII-only, no payloads.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 3.2, 4.1, 4.2_

  - [x]* 1.1 Bug 1 unit + Bug-Condition Exploration tests
    - In `tests/unit/test_data_layer.py`, add tests covering:
      - Default tenant + mapped collection → Real_Index_Name unchanged
        (Property 4 byte-equivalence).
      - Non-default tenant + mapped collection → `f"{prefix}{real_name}"`.
      - Non-default tenant + unmapped collection → passthrough
        (`f"{prefix}{collection}"`) AND the info log emitted exactly once.
      - `multi_collection_query` over a list of mixed mapped/unmapped names
        each resolves correctly per the rule.
    - Bug-Condition Exploration: a single test that on the **unfixed** code
      asserts the broken Resolved_Index `"gw_v17_code-with-context-v8-0-0"`
      and on the **fixed** code asserts the correct
      `"gw_v17_mdc-code-context-titan1024"`. Demonstrate both directions
      before committing.
    - _Validates: 1.1, 1.2, 1.3, 4.1, 6.1, 6.2_

- [x] 2. Bug 2 fix — tenant-scoped vector status block
  - In `src/tools/semantic_search.py`, extend `_render_vector_status_block`
    to read the active tenant via the existing `_tenant()` helper and filter
    the indices listing returned by `vector_db.health_check(deep=True)`:
      - Non-default tenant: keep indices whose name starts with the tenant's
        `index_prefix`.
      - Default tenant: keep indices whose name does NOT start with any
        non-empty tenant prefix declared in the catalog (mirror the
        `tenant_label_predicate` exclusion logic from
        `src/tenancy/resolver.py`).
  - Add a `**Tenant prefix:**` header line so the scoping is visible.
  - Recompute total documents and the `Status` flag from the filtered subset.
  - Threading: pass tenant down via `_tenant()` (no signature change to the
    public `get_knowledge_base_status` tool function).
  - Use a small helper `_filter_indices_by_tenant(health, prefix, others)` so
    it is unit-testable in isolation.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.2_

  - [x]* 2.1 Bug 2 unit + Bug-Condition Exploration tests
    - In `tests/unit/test_semantic_search_tools.py` (or extend the file
      currently exercising `get_knowledge_base_status`):
      - With a synthetic `MockVectorDB` returning a mix of `mdc-*` and
        `gw_v17_mdc-*` indices:
        - `tenant_id="gw"` → rendered table contains only `mdc-*` rows.
        - `tenant_id="gw_v17"` → rendered table contains only `gw_v17_mdc-*`
          rows.
      - The header line includes the tenant prefix or `(none)`.
      - Tally + status flag reflect the filtered subset.
    - Bug-Condition Exploration: asserts that on **unfixed** code,
      `kb_status(gw_v17)` returns the same collection list as `kb_status(gw)`,
      and on **fixed** code returns a smaller, prefix-scoped list.
    - _Validates: 2.1, 2.2, 2.3, 2.4, 6.3_

- [x] 3. CHANGELOG and full-suite gate
  - CHANGELOG entry under `[8.36.2]` (current latest is `[8.36.1]`; this is a
    small bugfix on top of the health-check-bugfixes deploy).
  - `cd mcp_server_python && python3.12 -m pytest tests/unit/ tests/properties/ -q`
    must be green; report the count vs the current 1341 baseline (expect a
    few new tests).
  - `python3.12 -m py_compile` clean on the two edited files.
  - _Requirements: 3.1, 6.1, 6.2, 6.3, 6.4_

- [x] 4. Phase A — gated build + deploy + live validation
  - STOP-AND-CONFIRM before ECR push and `update-agent-runtime`.
  - Build `python-tenants-v10`, push, cut runtime v33 → v34. Carry the full
    lossless deploy payload (env vars, VPC subnets, SG, EFS access point,
    MMDSv2/S3-endpoint flags) — same shape as the v33 deploy.
  - Live validation (gw — should be unchanged):
    - `search_documentation("GEMPAK", tenant_id="gw")` → returns hits as today.
    - `search_architecture("ocean modeling", tenant_id="gw")` → returns
      community summaries as today.
    - `find_similar_code("forecast initialization", tenant_id="gw")` → returns
      ranked hits as today.
    - `get_knowledge_base_status(tenant_id="gw")` → vector list contains
      only `mdc-*` indices (no `gw_v17_*` rows).
  - Live validation (gw_v17 — should now reach real indices):
    - `search_documentation("GEMPAK", tenant_id="gw_v17")` → returns hits
      from `gw_v17_mdc-workflow-docs-titan1024` (the index has 28,458 docs;
      expect a non-empty result for a likely-present term, e.g. "GEMPAK"
      via env var GEMPAKHOME).
    - `find_similar_code("forecast", tenant_id="gw_v17")` → 404 still expected
      pre-Task 5 (alias not yet created), with the cleaner diagnostic; will
      succeed after Task 5.
    - `search_architecture("ocean", tenant_id="gw_v17")` → 404 expected
      (no `gw_v17_mdc-community-summaries-titan1024` index ingested);
      this is companion-spec territory.
    - `get_knowledge_base_status(tenant_id="gw_v17")` → vector list shows
      only `gw_v17_mdc-*` indices with their per-index counts.
  - Record runtime version + image tag + ECR digest. Rollback target:
    `python-tenants-v9` (v33).
  - _Requirements: 1.1, 1.2, 2.1, 2.2 (live)_

- [x] 5. Phase B — gated v17 code-index alias (operator-run)
  - STOP-AND-CONFIRM before issuing the `_aliases` POST.
  - Issue (idempotent — no-op if alias exists):

    ```bash
    curl -s --aws-sigv4 "aws:amz:us-east-1:es" \
      --user "$AWS_ID:$AWS_SECRET" \
      -X POST \
      "https://${OS_ENDPOINT}/_aliases" \
      -H 'Content-Type: application/json' -d '{
        "actions": [
          {"add": {
            "index": "gw_v17_mdc-code-titan1024",
            "alias": "gw_v17_mdc-code-context-titan1024"
          }}
        ]
      }'
    ```

  - Live validation:
    - `find_similar_code("forecast", tenant_id="gw_v17")` → returns ranked
      hits from the renamed/aliased index (no more 404).
    - `get_code_context(symbol="...", tenant_id="gw_v17", include_community=True)`
      now reaches the code collection (community-summaries piece will still
      404 — companion spec).
  - Rollback (if needed): same POST with `"remove"` instead of `"add"`.
  - _Requirements: 5.1, 5.2, 5.3, 5.4_

### Wave 3 + 4 completion note (2026-06-11)

- **Wave 3 (Task 4) DONE.** Built + pushed `python-tenants-v10` (ECR digest
  `sha256:4cb8e4508bdf8110795dfa638c9aefe3d391ce55ec8421abc4801b5d49cecd00`),
  cut runtime `mdc_mcp_rag_server_python-v5K2F8BGrN` v33 -> **v34 (READY)**
  with the lossless payload (sg-096489a0876cc78c1, 2 subnets,
  requireServiceS3Endpoint, requireMMDSV2, 6 env vars). Rollback target:
  `python-tenants-v9` (v33).
- **Bug 1 + Bug 2 verified live.** `get_knowledge_base_status(gw)` lists only
  `mdc-*` (Property 4 holds); `get_knowledge_base_status(gw_v17)` now shows
  `**Tenant prefix:** gw_v17_` + only its 3 `gw_v17_mdc-*` indices (57,109
  docs). gw search / find_similar_code / search_architecture unchanged.
  gw_v17 queries now target `gw_v17_mdc-*` (no more 404).
- **Wave 4 (Task 5) alias DONE** but **R5.3 post-condition NOT met.** The
  alias `gw_v17_mdc-code-context-titan1024 -> gw_v17_mdc-code-titan1024` was
  created (`acknowledged: true`, verified). `find_similar_code(gw_v17)` no
  longer 404s — it now resolves through the alias — BUT returns
  `RequestError(400, ... Field 'embedding' is not knn_vector type)`.
- **NEW BLOCKER (out of scope for this spec).** All `gw_v17_mdc-*` indices
  were ingested with `embedding` mapped as `float` instead of `knn_vector`
  (confirmed via `_mapping/field/embedding` on `gw_v17_mdc-code-titan1024`).
  v17 vector *search* therefore 400s on every collection regardless of the
  resolution fix or alias. Requires re-creating the v17 indices with the
  `knn_vector` mapping and re-ingesting — a separate ingestion-side spec,
  not addressed here.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "1.1"] },
    { "id": 1, "tasks": ["2", "2.1"] },
    { "id": 2, "tasks": ["3"] },
    { "id": 3, "tasks": ["4"] },
    { "id": 4, "tasks": ["5"] }
  ]
}
```

Wave 0 swaps the resolution order in the adapter (the actual fix for the bulk
of v17 vector failures). Wave 1 is the independent vector-status scoping fix.
Wave 2 is the CHANGELOG + suite gate. Wave 3 is the gated runtime deploy.
Wave 4 is the gated OpenSearch alias creation that finishes off v17 code
search.

## Notes

- **Bug 1 is the root cause for most v17 vector failures.** Three of three
  declared v17 indices (`gw_v17_mdc-jjobs-titan1024`,
  `gw_v17_mdc-workflow-docs-titan1024`, `gw_v17_mdc-code-titan1024`) become
  reachable after this swap; the third needs Task 5's alias because of an
  ingest-side naming inconsistency.
- **Bug 2 is independent.** It fixes the user-visible
  `get_knowledge_base_status` lying about per-tenant scope. Same code path,
  same deploy, but the two bugs do not share files.
- **Companion spec territory.** A second spec (`graceful-missing-index-handling`,
  to be written next) wraps the remaining `index_not_found` cases (v17 has no
  `community-summaries`, no `ee2-standards`, no mpnet/nova variants) so tools
  return clean SKIP-shaped diagnostics instead of raw 404 stacks.
- **No infra change, no schema change, no re-ingestion.** Same tool-layer
  deploy path as Gaps C/D/E/G and `health-check-bugfixes`.
- **Property 4 (default-tenant byte-equivalence) is the contract.** Any
  regression on `gw` paths is a fix-the-fix moment, not a "weaken the test"
  moment.
- **The OpenSearch alias in Task 5 is reversible.** Rolling it back is the
  same POST with `"remove"`. The alias does not affect any other tenant or
  the gw production index.
