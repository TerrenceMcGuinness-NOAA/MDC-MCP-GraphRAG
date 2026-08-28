# Task 7.3-7.8 — the routing substitution, atomic

Implement **sub-tasks 7.3, 7.4, 7.5, 7.6, 7.7, and 7.8 of Task 7 from tasks.md.**
7.1 and 7.2 already landed in step 7; the protocol is widened and
`collection_condition` exists and is tested on both adapters.

**This is the step where the bug stops existing.** Everything before it was
scaffolding. Read this whole prompt before touching a file.

## Two constraints that make this step unlike the others

**1. It is atomic. Do not stop partway.** 7.3, 7.5, and 7.6 must land together.
Assertion 4 of the current `branch_isolation` probe treats develop-sourced content
under `gw_v17` as an isolation violation, so 7.3 without 7.6 turns a passing probe
into a failing one *for the correct reason* — a worse state than either end. If
you run out of room, say so and leave the tree unmodified rather than landing a
subset.

**2. You are spending a one-shot resource.** `tests/baselines/pre_change/` was
recorded from revision `4eb4229`, before any rendering path moved. It cannot be
re-recorded now. 7.8 compares against it, and if you "fix" a mismatch by editing
a baseline or adding a mask, the default-tenant byte-equivalence guarantee is
gone permanently and silently. **A differing span not covered by a mask earned in
6.2 is a regression in your code.** Masks are not a tool available to you.

## Files you own

- MODIFY `mcp_server_python/src/data/chromadb_adapter.py`
- MODIFY `mcp_server_python/src/data/opensearch_adapter.py`
- MODIFY `mcp_server_python/src/tools/semantic_search.py`
- MODIFY `mcp_server_python/src/tools/ee2_compliance.py`
- MODIFY `mcp_server_python/src/tools/graph_rag.py`
- MODIFY `mcp_server_python/src/tools/operational.py`
- MODIFY `mcp_server_python/src/tools/smoke_queries.py`
- NEW    `mcp_server_python/tests/properties/test_scope_merge.py`
- NEW    tests for 7.6 and 7.7 (name them as you see fit, under `tests/unit/`)

Do NOT modify `read_router.py`, `collection_scope.py`, `vector_errors.py`,
`protocols.py`, anything under `scripts/`, or any file in
`tests/baselines/pre_change/`.

## 7.3 — the substitution and the inner merge

Replace the unconditional `index = self.resolve_tenant_index(real, tenant) if
tenant else real` in each adapter's `query` with `resolve_read_targets(...)`.
After this, **the Read_Router is the only component that applies an
`index_prefix` on the read path.** That is what makes P3's substitutability hold:
patching the router changes what both adapters address, identically.

Implement the design's seven numbered steps exactly:

1. **Fan out** one read per member with **identical** `query_text`, `k`,
   `similarity_threshold`, and `where`, concurrently via
   `asyncio.gather(..., return_exceptions=True)`. Ask each member for `k`, **not
   `k/n`** — a member may legitimately supply all `k` survivors.
2. **Classify and triage.** `CollectionNotProvisionedError` marks that member
   `UNPROVISIONED` and contributes zero hits. Any other failure propagates as a
   query failure. Only when **every** member is absent does the adapter raise,
   once for the whole set.
3. **Attach provenance.** Stamp `physical_collection = m_i.physical` on every
   hit. Exactly one name per hit, always a member of the addressed set.
4. **Order** by `(-score, member_index, str(hit["id"]))`. Total, because
   `(member_index, id)` is unique within one read.
5. **De-duplicate** on a SHA-256 digest of normalized content: `content`, else
   `document`, else `text`, else `""`; `strip()`; collapse internal whitespace
   runs to one space; UTF-8. Keep the first in step-4 order and keep **its own**
   `physical_collection`, so a document in both members is retained as the shared
   copy attributed to the shared collection.
6. **Cap** at the first `k`, or all survivors if fewer.
7. **Emit** one `RoutingDiagnostic` for the resolution, plus per-member condition
   records for any `UNPROVISIONED` or `PROVISIONED_EMPTY` member.

### The scores you are merging are not comparable, and you must not fix that

On OpenSearch the per-member score is a clamped `_score` from a `bool.should` of
BM25 plus k-NN. BM25 depends on index-local corpus statistics, so the same
document scores differently in `mdc-workflow-docs-titan1024` (35,980 docs) than
in `gw_v17_mdc-workflow-docs-titan1024` (28,459 docs), and the `[0,1]` clamp
compresses everything above 1.0 onto exactly 1.0.

Per-member normalization and RRF fusion were both **considered and rejected**, not
overlooked: either would have to apply to the outer cross-collection merge to be
coherent, and that moves `gw` ordering for `search_documentation` — a direct R6.2
violation. Do not relitigate this. Keep raw per-member scores and let the
tie-break carry the ordering.

State the resulting semantics in a comment so no later reader mistakes it for
score-accurate ranking: **for a Hybrid_Domain the merged order is score-bucketed,
and within a bucket shared content precedes branch-local content.** That is
R3.1's unprefixed-first ordering plus R3.7's member-position tie-break, and it is
a defensible editorial choice — NWS-wide docs outrank branch-local docs at equal
apparent relevance.

### Three things not to touch

- **`physical_collection` is a NEW key.** Do not repurpose `collection`.
  `semantic_search.py:528` renders `f" | **Collection:** {collection_name}"`.
- **`multi_collection_query` is unchanged** in signature and in its
  cross-collection merge, including its `content[:200]` fingerprint and its cap.
  Each per-logical-collection `query` now does the intra-set fan-out internally,
  so the outer loop sees exactly what it saw before. The two de-duplication rules
  coexist deliberately; the outer one is more aggressive on the prefix and less
  precise overall, and tightening it changes which hits survive for `gw`.
- **No `if tenant is default` branch in the merge path.** Under the
  Default_Tenant every set has exactly one member, so the merge is the identity
  *by construction*. A branch is a thing to get wrong.

## 7.4 — P10, and the generator that decides whether it works

New file `tests/properties/test_scope_merge.py`, marked `@pytest.mark.property`,
`max_examples >= 100`, tagged
`# Feature: shared-scope-query-routing, Property 10: Result cap, provenance, and total ordering`.

Assert: at most `k` hits; every hit carries exactly one `physical_collection`
drawn from the addressed set; the score sequence is non-increasing; the ordering
key is injective over returned hits; no two survivors share a normalized content
digest.

**Forced score collisions must be a first-class generation strategy, not an
incidental case.** Because of the `[0,1]` clamp, ties are common in production
rather than rare. A generator producing only distinct scores would exercise the
tie-break almost never and would pass while the total-order guarantee was broken.
Draw scores from a small discrete set including `1.0` with elevated weight,
alongside a continuous range. Also generate duplicate content, duplicate ids, and
member counts in `{1, 2}`. Run against both adapters through `adapters()`.

## 7.5 — the annotation, gated on a non-empty prefix

In the zero-hit renderers of `semantic_search.py`, `ee2_compliance.py`,
`graph_rag.py`, and `operational.py`: when a read returns zero hits under a
tenant whose `index_prefix` is non-empty **and** at least one addressed member is
`unprovisioned` or `provisioned-empty`, name each such Physical_Collection and
its Collection_Scope in the response body, say that the zero-hit result reflects
an unreachable or empty collection rather than an absence of matching content,
and leave the rest of the body unchanged from the all-populated zero-hit
response.

**Gate on `tenant.index_prefix` being non-empty.** Under `gw` the condition goes
to the log channel and nowhere else, so the rendered zero-hit body stays
byte-equivalent. Confine **every** `RoutingDiagnostic` to `log.info`, the R1.5
fallback diagnostic included, and add a test asserting no diagnostic string ever
appears in rendered tool output on any path.

## 7.6 — realign the probe, and mind what stays frozen

In `smoke_queries.py::_smoke_branch_isolation`, replace assertion 4's origin
test. It currently classifies leakage with
`"/develop/" in (h.get("metadata", {}).get("source") or "")` — a source-path
substring match **R8.4 forbids**. Derive origin from the `physical_collection`
attached in 7.3: a hit originates from a tenant when that name carries that
tenant's non-empty `index_prefix`, and is shared when it carries no tenant's
non-empty prefix.

Restate the invariant the probe encodes: a hit whose attached name carries one
tenant's non-empty prefix is absent from results returned to any other tenant; a
hit whose attached name carries no tenant's non-empty prefix is present in
results returned to **every** tenant, prefixed tenants included. Note this is the
inverse of what the probe asserts today — shared content under `gw_v17` is now
the expected outcome, not a violation.

Add: R8.3 (`ee2-standards-v5-0-0-enhanced`, `k=10`, under `gw_v17`, at least one
unprefixed hit); R8.6 (`global-workflow-docs-v8-0-0`, `k=10`, under `gw_v17`, at
least one `gw_v17`-prefixed hit **and** at least one unprefixed); R8.2 in its
restated form for both `gw_v17` and the Default_Tenant.

Failure modes must stay diagnostic: a hit with no attached name fails naming the
collection and tenant (R8.7); an unprovisioned member, a provisioned-and-empty
member, and a query error each fail naming the collection, its scope, and which
of the three was observed, keeping unprovisioned distinct from provisioned-empty
(R8.8).

**Leave the two graph-side assertions alone.** Their query text and label scoping
must stay byte-identical and produce the same pass/fail outcome for any data
state. Add a unit test comparing both query strings to their pre-change form.

Unit-test the classifier with fixtures whose `metadata` deliberately contradicts
the attached `physical_collection`: **classification must follow the name.**

## 7.7 — audit the call sites

Assert that every shared-scope-reachable adapter call passes an identifier that is
a **key of the active profile's entry in `PRODUCTION_INDICES_BY_PROFILE`**, never
a physical name, across: `semantic_search.py` (both `_tool_search_documentation`
branches — the explicit-collection `query()` and the `multi_collection_query()`
fan-out), `ee2_compliance.py` (the three `EE2_COLLECTION` sites), `graph_rag.py`
(`_tool_search_architecture`, `_render_community_section` feeding
`get_code_context`, and `_fetch_community_context` feeding `get_change_impact`),
and `operational.py`.

Note the requirements attribute both community sites to `get_code_context`; the
second actually feeds `get_change_impact`. Both realign identically, so the
mis-attribution changes nothing — but do not let it confuse you into thinking a
site is missing.

Also assert `find_similar_code`, `get_job_details`, and `list_job_scripts` return
only prefixed-member hits under a prefixed tenant. They are correct today and
must stay correct.

## 7.8 — the guard you cannot regenerate

Run `tests/unit/test_default_tenant_byte_equivalence.py`. Resolve every
difference in favour of preservation. Re-read constraint 2 at the top of this
prompt before you consider any other resolution.

_Requirements: 2.4-2.7, 2.9, 3.2-3.5, 3.7-3.9, 4.1, 4.2, 4.8, 6.1-6.8, 7.1, 7.7, 7.9, 8.1-8.8, 13.7_
