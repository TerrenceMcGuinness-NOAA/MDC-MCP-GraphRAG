# Tasks 10 + 11 — make the reporting paths agree with the query path

Implement **Task 10 (10.1-10.5) and Task 11 (11.1-11.3) from tasks.md.**

Task 7.3 landed in step 8, so `query()` routes through `resolve_read_targets` and
shared collections are reachable. But three reporting paths still compute their own
independent view of which collections belong to a tenant, so they under-report
while the query path is correct. This step converges all three on
`tenant_collection_set()`.

## Run them in dependency order, not numeric order

**10.1 -> 10.2 -> 10.3 -> 10.4 -> 11.1 -> 11.2 -> 11.3 -> 10.5**

10.5 is last despite its number. P8 asserts that the Status_Reporter, the
Integrity_Checker, and the Health_Reporter all enumerate the same set, and its
Integrity_Checker half cannot be written until 11.1 and 11.2 exist. tasks.md calls
11.1 a scheduling prerequisite rather than a caveat for exactly this reason. Writing
10.5 early forces either a half-property or a deferral, and this spec already had
to correct one wave-ordering defect of that shape.

## Files you own

- MODIFY `mcp_server_python/src/tools/semantic_search.py`      (10.1, 10.2, 11.1, 11.2)
- MODIFY `mcp_server_python/src/data/unified_data_access.py`    (10.3)
- MODIFY `mcp_server_python/src/tools/utility.py`               (10.3, 10.4)
- MODIFY `mcp_server_python/src/data/opensearch_adapter.py`     (dead-code removal, see below)
- MODIFY `mcp_server_python/src/data/chromadb_adapter.py`       (dead-code removal, see below)
- MODIFY `mcp_server_python/tests/unit/test_kb_status_and_sampler.py`   (10.2, 11.3)
- MODIFY `mcp_server_python/tests/unit/test_semantic_search_tools.py`   (10.2)
- NEW    `mcp_server_python/tests/properties/test_scope_reporting.py`   (10.5)

Do NOT modify `read_router.py`, `collection_scope.py`, `vector_errors.py`,
`protocols.py`, anything under `scripts/`, or anything in `tests/baselines/`.

## Finish the dead-code removal step 8 created

Step 8's substitution orphaned `resolve_tenant_index` on both adapters — it is
called from nowhere in `src/`. It was left in place because
`_render_vector_status_block` was *expected* to call it and instead derived its own
prefix, which is the very divergence 10.1 closes. Once 10.1 routes the status block
through `tenant_collection_set`, the method is provably unreachable rather than
merely uncalled.

**Delete both `resolve_tenant_index` definitions as part of 10.1**, along with the
now-unused `_index_in_tenant_scope` and `_filter_indices_by_tenant` that 10.2
names. Two dead public methods that look like the obvious helper are a trap for the
next caller. Confirm with a grep that nothing references them, tests included,
before removing.

## 10.1 — names from the router, counts from health_check

Rebuild `semantic_search._render_vector_status_block`. The single most important
rule: **take collection *names* from `tenant_collection_set(...)` and use
`health_check` only as a *count source* for those names, never as the name
source.** That inversion is what structurally prevents a bookkeeping index like
`mdc-content-sha-registry` from appearing in a prefixed tenant's listing — not a
filter that has to enumerate what to exclude.

- Label each listed collection with the single Collection_Scope the Scope_Authority
  reports for the logical collection it resolved from. **Both Hybrid_Domain members
  get that same value** — scope is a property of the logical collection, not of the
  member.
- Compute the total as the arithmetic **sum over the listed collections**, with an
  unprovisioned collection counting zero. Do not take it from a backend aggregate,
  which spans collections outside the listed set.
- Render present-but-empty as a count of zero and absent as unprovisioned,
  **distinguishably**. One or more absent collections must not turn the report into
  an error result.
- Omit every collection carrying another tenant's declared prefix.

### Do not fix the `gw` over-count

The `gw` block must stay byte-equivalent (R6.3), which is why scope-labelling and
re-totalling apply **only where `index_prefix` is non-empty**. That deliberately
leaves the pre-existing `mdc-content-sha-registry` over-count in the `gw` total.
You will be able to see that it is wrong. Leave it. A follow-up spec converges the
two paths; correcting it here moves default-tenant bytes and fails 7.8's
byte-equivalence guard, which is backed by a one-shot baseline that cannot be
re-recorded.

## 10.2 — delete the filter that caused the blind spot

Remove `_filter_indices_by_tenant` and `_index_in_tenant_scope`. The latter's
prefix test is precisely what excluded shared collections from the non-default
view: **a name-shape test cannot distinguish a shared collection from another
tenant's**, so it structurally cannot express "the unprefixed shared collection
belongs to `gw_v17` too". That is why the fix is a different source of truth rather
than a better predicate.

Update the tests that import them (`test_kb_status_and_sampler.py`,
`test_semantic_search_tools.py`) by **re-expressing their intent against
`tenant_collection_set`, not by deleting the coverage.** The ChromaDB-shaped-payload
case and the empty-tenant-is-healthy case must still be asserted.

## 10.3 — the fourth defect manifestation

`UnifiedDataAccess._vector_health` computes
`indexCount = len(raw.get("indices") or raw.get("collections") or [])` with no
tenant scoping at all, then gates overall health on `index_count >= min_indices`,
and `mcp_health_check` renders that count verbatim. The requirements never name
this one; R11.1 names the Health_Reporter as the consumer, but the change lands one
layer below the tool.

`indexCount` becomes the cardinality of `tenant_collection_set(...)`. Include the
unprefixed member of every `shared` collection for a prefixed tenant, omit every
foreign-prefixed collection, and name each enumerated collection with its
Collection_Scope read off `ResolvedTarget.scope` rather than re-derived.

**Report the vector component degraded only where the absent collection is the
unprefixed member of a `shared` logical collection.** A tenant that has simply not
ingested its own code is not unhealthy. This preserves
`rag-data-plane-gap-closure` R6.2 — a fresh tenant is healthy — and getting it
wrong would make every new tenant look broken on the day it is created.

## 10.4 — skip is a third outcome, not a flavour of pass

With `functional=True` and a data state satisfying the realigned assertions, report
the probe as passing. When it cannot execute, report `skipped` — **distinct from
passing and from failing** — with the blocking condition indicated. Unit test it by
raising `SkipProbe`. A probe that silently reports pass when it could not run is
worse than one that fails.

## 11.1 — the sampler currently samples every tenant at once

`_build_vector_sampler` calls `sample_metadata(collection=None)`: no scoping
whatsoever, so integrity findings describe an unscoped mixture of every tenant's
data. Replace it with an allocator that iterates the members of
`tenant_collection_set(...)` and names each collection explicitly. Also update
`_check_path_consistency` and `_check_stale_embeddings`.

- **`sample_metadata` itself is unchanged.** Both adapters already accept a named
  collection with a `limit` (and the legacy `n` alias), which is all a scoped
  checker needs. Widening the protocol was considered and rejected.
- Retain the existing `_scroll_sampler` fallback for adapters lacking
  `sample_metadata`.
- Draw at most `sample_size` records, only from the union. Exclude every
  non-member, including foreign-prefixed collections and collections that are not
  the resolution of any logical collection.
- Cap any single member's contribution at `ceil(sample_size / member_count)` for as
  long as another member still holds unsampled records, so one large collection
  cannot starve the rest.
- Allocate in an order **identical across repeated invocations** for the same
  `(tenant, profile, sample_size)` triple.
- Track per-member counts and name each member in the report with the number of
  records drawn from it.
- An absent or empty member contributes zero records **and the remaining sub-checks
  still complete and render.**
- Clamp `sample_size` outside `[1, 1000]` to the nearest in-range value and state
  the value used in the report.

## 11.2 — coverage-gap count over the whole union

Compute `_check_coverage_gap`'s ingested-document count as the sum of
per-collection document counts over every member of the active tenant's union,
counting **both** the `shared` and the `tenant` members. Preserve the existing
per-language check structure from `fortran-coverage-gap-path-fix`;
`tests/unit/test_coverage_gap_multilang.py` must keep passing.

## 11.3 — the edge cases that matter

Extend `test_kb_status_and_sampler.py`: without a `tenant_id` the sampled
collections equal the Default_Tenant's union across all five logical collections; an
absent member and a zero-document member each contribute zero records while the
remaining sub-checks complete; an out-of-range `sample_size` clamps and the value
used appears in the rendered report.

## 10.5 — P8, and the injection that makes it real

New file `tests/properties/test_scope_reporting.py`, marked
`@pytest.mark.property`, `max_examples >= 100`, tagged
`# Feature: shared-scope-query-routing, Property 8: Reporting agreement`.

**P8 — Reporting agreement.** For any tenant and any profile, the set the
Status_Reporter lists, the set the Integrity_Checker samples, and the set the
Health_Reporter enumerates are each equal to `tenant_collection_set(T, profile=p)`.

**The generator must inject arbitrary non-member names into the stubbed
enumeration** — foreign-prefixed names and bookkeeping indices such as
`mdc-content-sha-registry` — and assert none appears in any of the three outputs.
Without that injection the property degenerates into three functions agreeing
because they were all handed a clean list, which proves nothing about the filtering
that is the actual subject. Run against both adapters through `adapters()`.

_Requirements: 1.4, 6.3, 9.1-9.8, 10.1-10.8, 11.1-11.7, 13.7_
