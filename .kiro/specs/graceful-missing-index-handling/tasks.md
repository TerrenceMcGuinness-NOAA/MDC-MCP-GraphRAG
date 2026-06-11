# Implementation Plan — `graceful-missing-index-handling`

## Overview

Companion to `opensearch-tenant-resolution-fix`. Aligns four tools on a
single `[INFO]`-prefixed Skip_Block when their backing OpenSearch index
is genuinely absent for the active tenant. Tool-layer-only change —
~25 lines of helpers in `src/tools/_common.py` plus four ~3-line edits
in the tool wrappers. Each affected tool gets a Bug-Condition
Exploration test per the workspace's Bugfix Workflow standard.

Delivered in five waves: helpers + their unit tests, tool wiring per
tool with paired tests, the Bug-Condition Exploration tests, the
CHANGELOG + suite gate, and the gated build/deploy/live validation.

## Tasks

- [x] 1. Add Detect_Helper and Render_Helper to `src/tools/_common.py`
  - Create or extend `mcp_server_python/src/tools/_common.py` with two
    pure-Python helpers:
    - `_is_missing_index_exc(exc: BaseException) -> bool`
      - Imports `opensearchpy.exceptions.NotFoundError` inside a
        try/except (no hard dependency at import time).
      - Returns True iff the exception is a `NotFoundError` whose
        `info['error']['type'] == 'index_not_found_exception'`, OR
        `'index_not_found_exception' in str(exc)`.
    - `_missing_index_skip(*, tool, query, collection, tenant_id) -> str`
      - Returns the standardised Skip_Block markdown.
      - Begins with `[INFO]`, includes collection name + tenant id,
        includes the `get_knowledge_base_status` advisory, ASCII-only.
  - Also add a tiny `_tenant_id_or_none()` adapter (next to `_tenant()`
    in the relevant tool module, OR in `_common.py` if more than one
    tool needs to import it) that returns the active tenant's id or
    `None`.
  - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x]* 1.1 Helper unit tests
    - New file `mcp_server_python/tests/unit/test_tool_common_helpers.py`
      (or extend existing test file if `_common.py` already has one).
    - `_is_missing_index_exc`:
      - opensearchpy-shaped `NotFoundError` with correct `error.type`
        → True.
      - opensearchpy-shaped `NotFoundError` with a different
        `error.type` (e.g. `document_missing_exception`) → False.
      - Synthetic `Exception("... index_not_found_exception ...")` →
        True.
      - `RuntimeError("transport boom")` → False.
      - `BaseException("...")` direct → False (not an `Exception`
        descendant in the structured branch; falls back to string
        check, which is False here).
    - `_missing_index_skip`:
      - Output starts with `[INFO]`.
      - Contains tool name, collection short name, tenant id, and the
        `get_knowledge_base_status` advisory.
      - `output.encode('ascii')` does not raise.
    - _Validates: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 2.4, 2.5_

- [x] 2. Wire `search_architecture` to use the helpers
  - In `mcp_server_python/src/tools/graph_rag.py`:
    `_tool_search_architecture` — extend the existing `except Exception
    as exc:` block with a `_is_missing_index_exc` branch that returns
    `_missing_index_skip(tool="search_architecture",
    query=query, collection=COMMUNITY_COLLECTION,
    tenant_id=_tenant_id_or_none())` BEFORE the existing `[ERROR]`
    formatter.
  - _Requirements: 3.1, 3.6, 4.1, 4.2_

  - [x]* 2.1 Tests for `search_architecture`
    - In `mcp_server_python/tests/unit/test_graph_rag_tools.py` (or
      whichever file exercises the tool today):
      - **Healthy-path**: mock `vector_db.query` to return a synthetic
        hit list → output byte-equivalent to today's rendering.
      - **Missing-index**: mock `vector_db.query` to raise a synthetic
        opensearchpy-shaped 404 → output begins with `[INFO]` and
        contains the tenant id + the `community-summaries` collection
        name.
      - **Non-404**: mock `vector_db.query` to raise
        `RuntimeError("transport boom")` → output begins with `[ERROR]`
        and contains `transport boom`.
    - **Bug-Condition Exploration**: one test that on the unfixed code
      asserts the rendered output begins with `[ERROR]` and contains
      `index_not_found_exception`, and on the fixed code asserts
      `[INFO]` + tenant id + collection name. Confirm both directions
      before commit.
    - _Validates: 3.1, 4.1, 4.2, 5.1, 5.3_

- [x] 3. Wire `find_similar_code` to use the helpers
  - In `mcp_server_python/src/tools/graph_rag.py`:
    `_tool_find_similar_code` — same pattern as Task 2 with
    `tool="find_similar_code"` and `collection=CODE_COLLECTION`.
  - _Requirements: 3.2, 3.6, 4.1, 4.2_

  - [x]* 3.1 Tests for `find_similar_code`
    - Same three test shapes as Task 2.1 (healthy / missing-index /
      non-404) plus the Bug-Condition Exploration test, scoped to
      `find_similar_code` and the code collection.
    - _Validates: 3.2, 4.1, 4.2, 5.1, 5.3_

- [x] 4. Wire `get_operational_guidance` to use the helpers
  - In `mcp_server_python/src/tools/operational.py`:
    `_tool_get_operational_guidance` — same pattern with
    `tool="get_operational_guidance"` and
    `collection=WORKFLOW_DOCS_COLLECTION`.
  - _Requirements: 3.3, 3.6, 4.1, 4.2_

  - [x]* 4.1 Tests for `get_operational_guidance`
    - Same three test shapes plus the Bug-Condition Exploration test,
      scoped to `get_operational_guidance` and the workflow-docs
      collection.
    - _Validates: 3.3, 4.1, 4.2, 5.1, 5.3_

- [x] 5. Wire `search_documentation` (explicit-collection branch) to use the helpers
  - In `mcp_server_python/src/tools/semantic_search.py`:
    `_tool_search_documentation` — extend the existing `except Exception
    as exc:` block with the `_is_missing_index_exc` branch ONLY for the
    explicit-`collection=` code path. The multi-collection branch is
    intentionally unchanged (Property 4 / R3.5).
  - _Requirements: 3.4, 3.5, 3.6, 4.1, 4.2_

  - [x]* 5.1 Tests for `search_documentation`
    - Same three test shapes for the explicit-`collection=` branch.
    - **Multi-collection Property 4**: a test that mocks
      `multi_collection_query` to return `[]` (per-collection swallow
      already happened internally) and asserts the rendered output is
      the literal `No results found for: "..."` line — on BOTH the
      unfixed and the fixed code. Explicit contract that this path does
      not change.
    - Bug-Condition Exploration: as above, scoped to the
      explicit-`collection=` branch.
    - _Validates: 3.4, 3.5, 4.1, 4.2, 5.1, 5.3, 5.4_

- [x] 6. CHANGELOG and full-suite gate
  - CHANGELOG entry under the next available patch version after
    `[8.36.2]` (i.e. `[8.36.3]` if `opensearch-tenant-resolution-fix`
    has shipped first; if the two ship together, fold under one entry).
  - `cd mcp_server_python && python3.12 -m pytest tests/unit/
    tests/properties/ -q` must be green; report count vs the
    then-current baseline (1341 + delta from
    `opensearch-tenant-resolution-fix`).
  - `python3.12 -m py_compile` clean on `_common.py`, `graph_rag.py`,
    `operational.py`, `semantic_search.py`.
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3, 5.4_

- [ ] 7. Phase A — gated build + deploy + live validation
  - STOP-AND-CONFIRM before ECR push and `update-agent-runtime`.
  - Build the next `python-tenants-vN` image, push, cut the runtime
    forward. If `opensearch-tenant-resolution-fix` has already shipped,
    this is the next bump; if both fixes ship together, merge into one
    image with one CHANGELOG entry.
  - Live validation matrix:
    - **gw (healthy paths — should be unchanged)**:
      - `search_architecture(tenant_id="gw", query="ocean modeling")` →
        ranked community summaries unchanged.
      - `find_similar_code(tenant_id="gw", code_or_symbol="forecast")`
        → ranked hits unchanged.
      - `get_operational_guidance(tenant_id="gw", operation="failed
        forecast restart", platform="hera")` → ranked hits unchanged.
      - `search_documentation(tenant_id="gw", query="GEMPAK")` → ranked
        hits unchanged.
    - **gw_v17 (missing-index paths — should now be Skip_Blocks)**:
      - `search_architecture(tenant_id="gw_v17", query="ocean modeling")`
        → `[INFO]` Skip_Block citing `community-summaries` and `gw_v17`.
      - `search_documentation(tenant_id="gw_v17",
        query="EE2 file naming",
        collection="ee2-standards-v5-0-0-enhanced")` → `[INFO]`
        Skip_Block citing `ee2-standards-v5-0-0-enhanced` and `gw_v17`.
      - `find_similar_code(tenant_id="gw_v17",
        code_or_symbol="forecast")` → either ranked hits (if
        `opensearch-tenant-resolution-fix` Phase B alias is already
        in place) or `[INFO]` Skip_Block (if not). Whichever it is,
        verify the shape, not the content.
      - `get_operational_guidance(tenant_id="gw_v17", operation="failed
        forecast restart", platform="hera")` → ranked hits (the
        `gw_v17_mdc-workflow-docs-titan1024` index DOES exist with
        28,458 docs; this is the healthy path on v17).
    - **Multi-collection unchanged**:
      - `search_documentation(tenant_id="gw_v17", query="GEMPAK")` (no
        explicit collection) → either ranked hits (the workflow-docs
        index resolves) or the literal `No results found for:
        "GEMPAK"` line. Either way, NOT a Skip_Block (Property 4 / R3.5).
  - Record runtime version + image tag + ECR digest. Rollback target:
    the previous tag.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 4.1 (live)_

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "1.1"] },
    { "id": 1, "tasks": ["2", "2.1", "3", "3.1", "4", "4.1", "5", "5.1"] },
    { "id": 2, "tasks": ["6"] },
    { "id": 3, "tasks": ["7"] }
  ]
}
```

Wave 0 lands the helpers and their unit tests — pure utility code, no
runtime side effects. Wave 1 wires the four tools to the helpers in
parallel (no inter-tool dependency) along with their paired tests
(healthy / missing-index / non-404 / Bug-Condition Exploration). Wave 2
is the CHANGELOG + suite gate. Wave 3 is the gated runtime deploy with
the live validation matrix.

## Notes

- **Companion ordering with `opensearch-tenant-resolution-fix`.** That
  spec swaps the resolution order (the actual bug behind the bulk of
  v17 vector failures). This spec aligns the *remaining* genuine
  missing-index responses on a clean shape. They can ship together in
  one image (recommended — one deploy, one CHANGELOG entry) or
  sequentially. Either way, this spec's helpers are agnostic to the
  resolution-order fix and do not depend on it.
- **Why we don't touch `multi_collection_query`'s per-collection
  swallow.** Aligning that path would require either:
  (a) a per-collection skip-propagation signature (`merged: list,
  skipped: list[str]`) and renderer changes, or
  (b) raising on first 404 and losing the resilient-fan-out behaviour.
  Both are wider blast-radius changes that this spec is not the right
  vehicle for. The current behaviour is preserved as Property 4
  (R3.5 / R5.4 / Test 5.1 multi-collection assertion).
- **Why `[INFO]` and not `[SKIP]`.** The `[SKIP]` token is reserved by
  the smoke harness for `SmokeResult`-shaped diagnostics. The user-
  facing precedent for "operation succeeded with no result" is `[INFO]`
  (e.g. `[INFO] Script content is not available on the hosted Python
  port` from the existing `get_job_details` path). Reusing `[INFO]`
  keeps the marker space consistent.
- **No data-layer change.** `OpenSearchAdapter.query`,
  `multi_collection_query`, the resolver, `aws_config.py`,
  `unified_data_access.py` — all unchanged. Tool-layer only.
- **Property 4 (default-tenant byte-equivalence) is the contract.**
  Any regression on `gw` paths is fix-the-fix territory, not weaken-
  the-test territory.
