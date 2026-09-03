# Task 4 — cross-backend missing-collection normalization

Implement **Task 4 (sub-tasks 4.1, 4.2, 4.3, 4.4) from tasks.md.**

This is independently shippable and valuable on its own: it makes a COTS
missing-collection read render a Skip_Block instead of `[ERROR]`, regardless of
whether the rest of this spec ever lands.

## Files you own

- NEW `mcp_server_python/src/data/vector_errors.py`
- MODIFY `mcp_server_python/src/data/chromadb_adapter.py`
- MODIFY `mcp_server_python/src/data/opensearch_adapter.py`
- MODIFY `mcp_server_python/src/tools/_common.py` (widen `_is_missing_index_exc`)
- NEW `mcp_server_python/tests/unit/test_vector_errors_normalization.py`
- MODIFY `mcp_server_python/tests/unit/test_tool_common_helpers.py` (extend only)

Do NOT change adapter `query()` routing. Task 7.3 owns that. You are touching
only the error-classification path.

## The defect, precisely

`ChromaDBAdapter.query` currently catches everything and re-raises
`ValueError(f"ChromaDB query failed on index={index!r}: {exc}")`. That wrap
erases the distinction between "collection absent" and "query blew up", which is
why `_is_missing_index_exc` — which matches OpenSearch's
`index_not_found_exception` token — never fires on COTS. Same logical condition,
two incompatible signals, one classifier that only understands one of them.

## Order of operations matters

Classify **before** the existing catch-all wrap. On a match raise
`CollectionNotProvisionedError`. Otherwise fall through to the existing
`ValueError` wrap **with its current message unchanged**, so connection,
authentication, and embedding-generation failures keep their present shape and
stay distinguishable from absence (Requirement 4.6).

## Detection needs both forms

`pyproject.toml` pins `chromadb==1.3.4`, but the interpreter actually has
**1.5.8 installed**. That drift is itself the argument for the guarded import:
verified against the installed 1.5.8, `chromadb.errors` exports `NotFoundError`
but has **no `InvalidCollectionException`** — the nearest relatives are
`InvalidArgumentError` and `InvalidDimensionException`. Do not hard-code a class
that may not exist. So:

- a **guarded** import that tolerates absent names. `NotFoundError` is present
  in 1.5.8 and is the primary signal; treat any others as optional extras
  discovered via `getattr`, not as required imports.
- a case-insensitive substring fallback on `"does not exist"` /
  `"collection not found"`.

Enumerate what is actually available rather than trusting this list:
`python3.12 -c "import chromadb.errors as e; print(sorted(n for n in dir(e) if not n.startswith('_')))"`.
Note that under bare `python3` (3.9) `chromadb.errors` does not import at all,
which is one more reason to use `python3.12`.

This mirrors the two-form approach `_is_missing_index_exc` already uses for
`opensearchpy`. Read that function before writing yours; match its shape.

## Widen, do not replace

`_is_missing_index_exc` becomes
`isinstance(exc, CollectionNotProvisionedError) or <existing checks>`.

Four call sites depend on its current behaviour:
`semantic_search._tool_search_documentation`,
`graph_rag._tool_search_architecture`, `graph_rag._tool_find_similar_code`,
`operational._tool_get_operational_guidance`. All four must keep working
unchanged — that is a Requirement 6.2 byte-equivalence concern, not a nicety.
Extend the existing detection-matrix assertions in
`test_tool_common_helpers.py`; do not rewrite them.

## 4.4 — do not touch the Skip_Block text

`_missing_index_skip` in `src/tools/_common.py` is already the single renderer
and its text is already backend-independent: it interpolates only `tool`,
`collection`, and `tenant_id`. **Leave the text alone.** Requirement 4.4 asks you
to *prove* character-for-character identity across backends, and editing the
renderer would make the test tautological.

Also assert Requirement 4.7: when every member of a Resolved_Collection_Set is
absent the adapter raises **once for the whole set**, and the tool renders
**exactly one** Skip_Block naming the *logical* collection and the tenant_id —
never the physical names, which would leak routing detail Requirement 7.6
confines to the log channel.

**4.4 uses the `adapters()` fixture from Task 2.4**, which has already landed
in `tests/properties/conftest.py` (parameterised on `["chromadb", "opensearch"]`).
Use it; do not write a duplicate.

_Requirements: 4.3, 4.4, 4.6, 4.7, 6.2_
