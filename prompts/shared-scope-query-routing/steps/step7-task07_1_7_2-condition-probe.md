# Task 7.1 + 7.2 — protocol widening and the Collection_Condition probe

Implement **ONLY sub-tasks 7.1 and 7.2 of Task 7 from tasks.md.**

**Do NOT implement 7.3, 7.4, 7.5, 7.6, 7.7, or 7.8.** Those six are one atomic
unit and they are the next step, not yours. In particular do NOT touch `query()`'s
routing: `resolve_tenant_index(...)` stays exactly where it is. Your step adds a
new capability and changes no routing decision.

## Why Task 7 is split here

tasks.md binds 7.3, 7.5, and 7.6 together: shipping 7.3 without 7.6 turns a
passing `branch_isolation` probe into a failing one for the correct reason, which
is worse than either end state. That atomicity is real and the next step honours
it. 7.1 and 7.2 are outside it — 7.1 documents existing reality in the protocol
and 7.2 adds a method nothing calls yet — so landing them first shrinks the
atomic step from eight sub-tasks to six and gives the probe a tested classifier
to build on rather than a new one written under the same commit.

## Files you own

- MODIFY `mcp_server_python/src/data/protocols.py`
- MODIFY `mcp_server_python/src/data/chromadb_adapter.py`
- MODIFY `mcp_server_python/src/data/opensearch_adapter.py`
- MODIFY `mcp_server_python/tests/conftest.py`            (MockVectorDB)
- MODIFY `mcp_server_python/tests/unit/test_conftest_mocks.py`  (extend only)
- NEW    `mcp_server_python/tests/unit/test_collection_condition.py`

Do NOT modify `src/data/read_router.py`, `src/data/collection_scope.py`,
`src/data/vector_errors.py`, anything under `src/tools/`, or
`src/tools/smoke_queries.py`. All of those belong to the atomic step or are
already landed.

## What already exists. Import it, do not redefine it

- **`CollectionCondition` is already defined** in `src/data/read_router.py` as a
  `StrEnum` with `UNPROVISIONED`, `PROVISIONED_EMPTY`, `PROVISIONED_POPULATED`.
  Its docstring already says "the classifier that returns it is implemented on
  the adapters by Task 7.2" — that is you. Import it; do not declare a second
  copy.
- **`CollectionNotProvisionedError`** is in `src/data/vector_errors.py` and both
  adapters already raise it on absence (Task 4, landed). That is where your
  `UNPROVISIONED` answer comes from for free.
- **`count_documents(collection) -> int` already exists on both adapters and is
  already non-raising** — it returns `0` for a missing collection or any client
  error. It is the correct backing call for the ambiguous case. Do not write a
  new counter.

## 7.1 — widen the protocol, do not broaden its behaviour

Add `tenant: Any = None` to `VectorDBProtocol.query`. This **documents existing
reality**: both adapters already accept `tenant=` and every tool already passes
`_tenant()`. You are closing a latent drift, not creating a parameter.

Add `physical_collection` to `VECTOR_RESULT_KEYS` (currently
`{"id", "content", "metadata", "score"}`) and document the key on results.

**`physical_collection` is a NEW key. Do not repurpose `collection`.**
`semantic_search.py:528` renders `source_line += f" | **Collection:**
{collection_name}"`. Renaming or re-pointing `collection` moves default-tenant
output bytes and violates R6.2. The atomic step populates the new key; you only
declare it.

Declare `collection_condition(physical_collection) -> CollectionCondition` as a
protocol member. **`multi_collection_query`, `sample_metadata`,
`count_documents`, and `health_check` are unchanged** — do not touch their
signatures.

Update `MockVectorDB` in `tests/conftest.py` with the new method and key, and
extend the existing assertions in `tests/unit/test_conftest_mocks.py` rather than
rewriting them. `MockVectorDB` is a test double, not production code, and is not
covered by R12.2's freeze.

## 7.2 — the three things that make this probe correct

**1. Take the free answers first. Probe only the ambiguous case.**
`UNPROVISIONED` falls out of the normalized exception at zero cost.
`PROVISIONED_POPULATED` is implied at zero cost whenever a member returned at
least one hit. The **only** state where `provisioned-empty` and
`provisioned-populated` are indistinguishable from the read alone is a member
that returned zero hits and did not raise. Probe exactly that, and back it with
`count_documents`. A probe on every read would be a latency regression for no
information.

**2. Never cache `UNPROVISIONED`.** TTL cache keyed by physical name, default
300 s via `MCP_COLLECTION_CONDITION_TTL_S` — but absence is the one answer that
must never be cached. A collection can be provisioned at any moment, and a stale
absence is far more damaging than a stale count: it would make a freshly
populated tenant look permanently empty. Cache the two positive conditions only.

**3. It never raises, and it never writes.** R12.5 permits reads and metadata
counts and nothing else. No create, no delete, no write, on any path including
the error path. A unit test must assert no mutating client call is made.

Kill switch `MCP_COLLECTION_CONDITION_PROBE=0`, default enabled: treat any
non-raising member as `PROVISIONED_POPULATED`, and record on the log channel that
the probe is off. The atomic step's R7.7 annotation then degrades to naming only
unprovisioned members, which is why the switch is worth having.

## The default-tenant cost, to accept rather than hide

R6.8 requires the Collection_Condition to be logged **even for the
Default_Tenant**, so the probe fires for `gw` too on a zero-hit read. Two things
follow, and both are acceptable:

- **Response bytes are unchanged.** A log line is not rendered output, so R6.2
  byte-equivalence holds. Assert this.
- **Backend call volume on the `gw` zero-hit path rises by at most one O(1)
  metadata count per collection per TTL window.** That is the honest cost. Do not
  add a `gw` special case to avoid it — the log record is required, and a
  tenant-conditional probe would make the `gw` and prefixed-tenant paths diverge
  in a way the atomic step then has to reason about twice.

## Tests

Use the **existing** `adapters()` fixture from `tests/properties/conftest.py`
(parameterised over `chromadb` and `opensearch`) so both form factors are swept
rather than assumed symmetric. Do not write a second fixture.

Cover: each of the three classifications; a populated collection returning zero
hits classifies `PROVISIONED_POPULATED` and not `PROVISIONED_EMPTY`;
`UNPROVISIONED` is not cached while the positive conditions are; the TTL boundary;
the kill-switch path; no mutating call on any path; and that a `gw` zero-hit
response body is byte-identical with the probe on and off.

_Requirements: 3.5, 6.8, 7.3, 7.4, 7.8, 12.5_
