# Task 12.1 — write-path immutability check

Implement **Task 12.1 from tasks.md, and nothing else.** Do NOT implement 12.2
(property P7) or 12.3 (the no-writes sweep).

## Files you own

- NEW `mcp_server_python/tests/unit/test_write_path_frozen.py`
- NEW digest manifest asset, e.g. `mcp_server_python/tests/assets/write_path_digests.json`

## Why the manifest lives under tests/

A file placed under `mcp_server_python/scripts/` to check that `scripts/` has not
changed would itself change `scripts/`, failing its own assertion on first run.
Put it under `tests/`. The same reasoning governs the Task 6 capture harness.

## Two assertions

**One — file digests.** SHA-256 of every file under
`mcp_server_python/scripts/`, compared against recorded digests. On mismatch,
fail naming every file that differs. Record the digests from the current tree.

Be deliberate about what you walk: exclude `__pycache__`, `*.pyc`, and any
runtime output directory such as `scripts/ingestion_reports/` — that last one
holds generated JSON that legitimately changes and would make the test a
tripwire on unrelated activity. Document the exclusion set in the test docstring
so a future reader knows it was a choice, not an oversight.

**Two — naming stability.** Sweep `resolve_collection_name` over the
Requirement 12.1 combination space: the five logical-collection domains, both
Collection_Scope values, every tenant in the catalog, the default plus one
non-default collection version, and each of titan1024, mpnet768, nova1024.
Compare each result against a pinned expected name, or assert the same rejection
of the combination. "Rejection" counts as observable behaviour — a combination
that raises today must still raise, with the same exception type.

## Note

This task is pure verification scaffolding. It should pass immediately on the
current tree. If either assertion fails on first run, that is a real finding
about the tree, not a bug in your test — report it rather than adjusting the
expected values to match.

_Requirements: 12.1, 12.2, 12.7_
