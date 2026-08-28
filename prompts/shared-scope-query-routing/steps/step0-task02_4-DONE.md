# Task 2.4 — shared property generators and the cross-adapter fixture

Implement **Task 2.4 from tasks.md, and nothing else.**

Creates `mcp_server_python/tests/properties/conftest.py`.

## Why this runs first

tasks.md schedules 2.4 in wave 4, but Task 3.2 and Task 4.4 both consume the
generators defined here and are scheduled earlier. That is an ordering defect in
the plan. 2.4 has no dependencies of its own — `PRODUCTION_INDICES_BY_PROFILE`,
`src/config/tenants.yaml`, `ChromaDBAdapter`, and `OpenSearchAdapter` all exist
in the tree today — so it is pulled forward to unblock them.

## What to build

Five reusable pieces, per the task text:

- `logical_collections()` — the five keys of `PRODUCTION_INDICES_BY_PROFILE`.
- `tenants()` — every tenant in `src/config/tenants.yaml`: gw, gw_sfs,
  gw_jedi_gfs, gw_v17, gw_gefs_v12. Read the catalog; do not hardcode a list
  that can drift from it.
- `prefixed_tenants()` — the subset whose `index_prefix` is non-empty.
- `profiles()` — titan1024 and mpnet768, plus nova1024 where Requirement 5.4
  applies. Note nova1024 has no index map, which is deliberate coverage.
- `adapters()` — `@pytest.fixture(params=["chromadb", "opensearch"])` yielding a
  ChromaDBAdapter or an OpenSearchAdapter.

## Constraints specific to the fixture

- Construct each adapter with an **explicit `embedding_function`** so the
  fixture needs neither Bedrock nor sentence-transformers. This is what keeps
  the property suite hermetic and fast.
- Give each a client double that serves recorded responses **and records every
  call**, because later properties (P8, P10, and the no-write sweep) assert on
  what was called, not just on what came back.
- Both parameter ids must be `chromadb` and `opensearch` exactly. A later
  meta-test asserts those two strings appear in collected node ids.

## Out of scope

Do NOT implement any property test. P1 through P10 belong to their own tasks.
This handoff delivers the generators and the fixture only.

_Requirements: 4.5, 13.7_
