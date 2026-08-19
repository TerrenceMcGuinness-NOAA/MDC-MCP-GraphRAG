# Task 12.2 + 12.3 — prove the round trip, prove nothing writes

Implement **sub-tasks 12.2 and 12.3 from tasks.md**, plus one small repair
described at the end. 12.1 landed in step 5.

Both are pure test work. **No production behaviour changes in this step** except
the two-line repair in the last section.

## Files you own

- NEW `mcp_server_python/tests/properties/test_scope_write_read.py`   (12.2)
- NEW `mcp_server_python/tests/properties/test_scope_no_writes.py`    (12.3)
- MODIFY `mcp_server_python/tests/unit/test_default_preservation_citation.py` (repair)

Do NOT modify anything under `src/`, anything under `scripts/`, or anything in
`tests/baselines/`.

## 12.2 — P7 is the property that would have caught a real defect

**P7 — Write-read round trip.** For any manifest source with a
`collection_target` and a `scope`, and any tenant for which it was ingested, the
physical name `resolve_collection_name` produces is a member of
`resolve_read_targets(s.collection_target, T, profile=p)` for the profile that
ingested it.

Generators: manifest sources parsed from `src/config/unified_manifest.json`, plus
`tenants` and `profiles` from `tests/properties/conftest.py`. Marked
`@pytest.mark.property`, `max_examples >= 100`, tagged
`# Feature: shared-scope-query-routing, Property 7: Write-read round trip`.

This is not ceremony. **P7 is exactly the property that would have caught the
step 6 profile-default defect**, where the Read_Router pinned `titan1024` while
`collection_namer` defaulted to `mpnet768`, so with `MCP_EMBEDDING_PROFILE` unset
the read path addressed `mdc-code-context-titan1024` for content the write path had
written to `mdc-code-context-mpnet768`. That was found by hand in review because P7
did not exist yet. Write it so it would fail on that condition: **include the
no-env-var case in the profile generator**, not only explicit profiles.

The claim P7 establishes is the one that matters operationally: every collection
the write path created is reachable by the read path for the tenant that owns it,
so **this change requires no re-ingestion.** If P7 fails for any source, that
conclusion is false and the deploy plan changes.

_Requirements: 1.6, 12.1, 12.3, 13.7_

## 12.3 — a read must never create what it cannot find

New file, kept separate from `test_scope_merge.py` so the two can be worked
independently.

Sweep every path this spec introduced — `query`, `collection_condition`, and the
status, integrity, and health enumerations — against an adapter double that
**raises on any mutating call**: `upsert_document`,
`get_or_create_collection`, any index-creation API, any delete.

The case that matters most: **include an absent member of a
Resolved_Collection_Set.** A shared collection that a tenant cannot reach, or a
tenant collection never ingested, must be *reported* as unprovisioned and never
*created* to make a read succeed. ChromaDB's `get_or_create_collection` makes that
failure mode one keystroke away, which is why this is a property sweep and not a
single unit test.

Note while writing it that `collection_condition` deliberately probes on the
zero-hit path via `count_documents`. That is a read and a metadata count, both
permitted by R12.5. Assert it stays that way.

_Requirements: 12.5_

## Repair — a pinned-line test is constraining implementation choices

`tests/unit/test_default_preservation_citation.py` (written in step 9) locates the
Property 3 citations by **line index**: `lines[475]` and `lines[893]`. That has
already cost real work. Step 10 had to preserve every line at or above 894 in
`semantic_search.py` byte-for-byte, and had to avoid a top-level `import math` --
using integer ceil-division instead -- purely because adding an import would shift
those indices and break this test.

That is a test dictating implementation choices for no benefit. **Re-express both
assertions to locate the citation by content rather than by position**: find the
comment by its surrounding text or by regex over the whole file, and assert the
citation on the matched line.

Keep every other assertion in the file exactly as it is. In particular keep the
whole-file scan for any `Property 4` reference and keep the checks pinning the
correct `R3.3` / `R3.7` multi-member merge citations at their current sites, since
those guard against a future sweep clobbering correct citations. Only the two
positional lookups change.

_Requirements: 6.4 (unchanged intent, brittleness removed)_
