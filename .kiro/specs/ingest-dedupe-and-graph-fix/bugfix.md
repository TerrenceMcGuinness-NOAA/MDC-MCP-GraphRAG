# Bugfix Requirements Document

## Introduction

An overnight full-branch ingestion of the `gw_v17` tenant reported success (every
ingestion script exited 0) but produced structurally broken data. Two distinct
defects in the v8 tenant ingestion pipeline combined to leave the `gw_v17` code
and J-Jobs collections without usable content and the Neptune graph empty for the
entire tenant.

The three entry scripts (`ingest_documentation_v8.py`, `ingest_code_v8.py`,
`ingest_jjobs_v8.py`) walk the same worktree
(`/mnt/efs-staging/supported_repos/global-workflow/dev-v17`) and compute SHA-256
over the same files. They run sequentially and share a single, unprefixed dedupe
registry index (`mdc-content-sha-registry`, managed by `SHAIndex` in
`mcp_server_python/scripts/_ingest_dedupe.py`).

**Defect 1 — collection-blind dedupe collision.** `SHAIndex.lookup` queries the
registry on `{"term": {"sha": sha}}` and `SHAIndex.register` writes with `id=sha` —
the registry is keyed by content SHA *alone*, with no notion of which collection
(documentation, code, jjobs) a file belongs to. Because the documentation pass runs
first and registers every file's SHA, the subsequent code and jjobs passes find every
file already present and mark all of them as duplicates (100% dedupe efficiency). They
write only reference documents (`is_reference: True`, `embedding: None`,
`canonical_tenant: gw`) instead of embedding real content. Verified in OpenSearch:
`gw_v17_mdc-code-titan1024` holds 26,316 documents, all references, with zero embedded
code content. The dedupe mechanism's intended purpose is *cross-tenant* reuse (avoid
re-embedding a file that is byte-identical between `gw` and `gw_v17` within the same
collection); it was never meant to dedupe *across collections* within one tenant. A
file that legitimately belongs to multiple collections (e.g. a `.py` file is both
"documentation" and "code") must be embedded once per collection.

**Defect 2 — graph nodes never created.** In both `ingest_code_v8.py` and
`ingest_jjobs_v8.py`, the Neptune graph write (`uda.graph_db.query(...)` with a
`MERGE` cypher) is nested inside the `else` branch — the non-duplicate path. When
dedupe hit 100%, the `else` branch never executed, so zero graph nodes were created
for `gw_v17`. The graph is what `find_dependencies`, `find_callers_callees`, and
`trace_execution_path` traverse; with an empty graph these tools return nothing for
the tenant, and the branch-isolation smoke probe (Assertion 1: "WDQMS J-Job visible
under `gw_v17`") fails. A file's graph node represents its *existence* and
relationships, which is independent of whether its *content* is reused for embedding.
Graph modeling must always happen, regardless of the embedding-dedupe decision.

**Root cause.** The dedupe design conflated two separable concerns: (a) *embedding
dedupe*, a legitimate cost optimization that skips re-embedding identical content
across tenants within the same collection; and (b) *existence / graph modeling*, which
must always occur so every file has its graph node and its per-collection OpenSearch
presence. Two code-level faults follow: the registry key is `sha` alone (must be
`(collection, sha)` with cross-tenant-within-collection semantics), and the graph-write
call is gated on the dedupe `else` branch (must be unconditional).

This bug is in the implementation of `.kiro/specs/omd-tenants-2-v17-pilot/` design
§2.4 (content-addressed dedupe) and §2.5 (graph writes); the corrected behavior should
later be reflected back into that spec's design, but this bugfix spec is the immediate
vehicle. Re-ingestion is also blocked until the bad data is removed: the three
`gw_v17_*` prefixed indices and the empty `GW_V17_*` graph labels must be wiped
(`delete_tenant_indices.py --tenant gw_v17`) and the stale `gw_v17` entries in the
shared `mdc-content-sha-registry` cleared. That cleanup is a remediation prerequisite
detailed in the design phase.

**Affected files:**
- `mcp_server_python/scripts/_ingest_dedupe.py` — `SHAIndex.lookup` / `SHAIndex.register` (registry key)
- `mcp_server_python/scripts/ingest_documentation_v8.py` — dedupe loop / registration
- `mcp_server_python/scripts/ingest_code_v8.py` — graph write inside `else` branch
- `mcp_server_python/scripts/ingest_jjobs_v8.py` — graph write inside `else` branch
- `mcp_server_python/tests/properties/test_v17_pilot.py` — P5 dedupe correctness (needs per-collection scoping assertions)

## Bug Analysis

### Current Behavior (Defect)

What currently happens when a tenant is ingested after a prior collection's pass has
already registered its files' SHAs in the shared registry.

1.1 WHEN the documentation pass has registered a file's SHA in `mdc-content-sha-registry` AND the code pass later walks the same file THEN the system treats it as a duplicate (lookup matches on `sha` alone) and writes only a reference document into `gw_v17_mdc-code-titan1024` with `embedding: None` and no embedded code content.

1.2 WHEN the documentation pass has registered a file's SHA AND the J-Jobs pass later walks the same file THEN the system treats it as a duplicate and writes only a reference document into `gw_v17_mdc-jjobs-titan1024` with no embedded content.

1.3 WHEN a file is treated as a duplicate in `ingest_code_v8.py` or `ingest_jjobs_v8.py` THEN the graph `MERGE` (nested in the `else` branch) does not execute, so no graph node is created for that file.

1.4 WHEN a full tenant ingestion completes and code/jjobs dedupe efficiency reaches 100% THEN the ingestion report shows `nodes_created_by_label: {}` and `relationships_created: 0`, leaving the Neptune graph empty for the tenant.

1.5 WHEN `find_dependencies`, `find_callers_callees`, or `trace_execution_path` query symbols belonging to the affected tenant THEN they return empty results because no graph nodes exist.

1.6 WHEN the branch-isolation smoke probe runs (Assertion 1: WDQMS J-Job visible under `gw_v17`) THEN it fails because the tenant has zero graph nodes.

### Expected Behavior (Correct)

What should happen instead, once dedupe is scoped per collection and graph modeling is
decoupled from the dedupe decision.

2.1 WHEN the code pass walks a file whose SHA was registered only by another collection (e.g. documentation) within the same tenant THEN the system SHALL NOT treat it as a duplicate and SHALL embed the file as real content into `gw_v17_mdc-code-titan1024`.

2.2 WHEN the J-Jobs pass walks a file whose SHA was registered only by another collection within the same tenant THEN the system SHALL NOT treat it as a duplicate and SHALL embed the file as real content into `gw_v17_mdc-jjobs-titan1024`.

2.3 WHEN any file is ingested by `ingest_code_v8.py` or `ingest_jjobs_v8.py`, regardless of whether it was deduped THEN the system SHALL create (MERGE) its graph node unconditionally.

2.4 WHEN a full tenant ingestion completes THEN the ingestion report's `nodes_created_by_label` SHALL be non-empty for the code and jjobs collections, reflecting one graph node per ingested file.

2.5 WHEN the dedupe registry is consulted or written THEN lookup and register SHALL be scoped by `(collection, sha)`, so a SHA registered under one collection does not mask the same SHA in a different collection.

2.6 WHEN a file legitimately belongs to multiple collections THEN the system SHALL embed it once per collection it belongs to.

2.7 WHEN `find_dependencies`, `find_callers_callees`, or `trace_execution_path` query the tenant's symbols after the fix THEN they SHALL return populated results.

2.8 WHEN the branch-isolation smoke probe runs after the fix THEN Assertion 1 (WDQMS J-Job visible under `gw_v17`) SHALL pass.

### Unchanged Behavior (Regression Prevention)

Existing behavior that must be preserved — the legitimate cross-tenant embedding
optimization, the `gw` baseline, and the reference-document mechanics.

3.1 WHEN a file is byte-identical between `gw` and `gw_v17` within the SAME collection THEN the system SHALL CONTINUE TO dedupe it (write a reference document, skip re-embedding) — the legitimate cross-tenant embedding optimization is preserved.

3.2 WHEN the documentation pass runs (which does not model the graph by design) THEN it SHALL CONTINUE TO create no graph nodes; only the code and jjobs collections model the graph.

3.3 WHEN the `gw` baseline tenant is queried (search, dependencies, callers/callees, traces) THEN it SHALL CONTINUE TO return correct results with no regression.

3.4 WHEN a genuine cross-tenant-within-collection duplicate is detected THEN its reference document SHALL CONTINUE TO have the existing shape (`is_reference: True`, `canonical_index`, `canonical_id`, `canonical_tenant`, `embedding: None`, `content: "<reference: see canonical doc>"`).

3.5 WHEN a reference document is resolved at query time THEN the system SHALL CONTINUE TO follow `metadata.canonical_index` / `canonical_id` to the canonical document.

3.6 WHEN tenant data is rolled back THEN the shared `mdc-content-sha-registry` SHALL CONTINUE TO be a system-level, unprefixed index (only the tenant's own stale entries are cleared; the index itself is not deleted).

### Bug Condition Derivation

**Key definitions:**
- **F** — the original (unfixed) pipeline (current code).
- **F'** — the fixed pipeline.
- **X** — an ingestion run of a tenant `T`, in some collection `c ∈ {documentation, code, jjobs}`, over a file `f` whose content SHA `s` was already registered in `mdc-content-sha-registry` by a *prior collection's* pass of the *same tenant* `T`.

**Bug condition C(X)** — identifies the inputs that trigger the bug:

```pascal
FUNCTION isBugCondition(X)
  INPUT:  X = (tenant T, collection c, file f with sha s)
  OUTPUT: boolean

  // The SHA was previously registered, but by a DIFFERENT collection
  // (registry is keyed by sha alone, so the collection is invisible to it).
  existing ← registry.lookupBySha(s)
  RETURN existing.exists
         AND existing.collection ≠ c
         AND existing.tenant = T
END FUNCTION
```

Under F, `isBugCondition(X)` causes `f` to be written as a reference document with no
embedding AND (for code/jjobs) skips the graph `MERGE`, because both the dedupe result
and the graph write share the single `if result.is_duplicate / else` branch.

**Fix property (Fix Checking)** — desired behavior for buggy inputs:

```pascal
// Property: Fix Checking — collection-scoped dedupe + unconditional graph write
FOR ALL X WHERE isBugCondition(X) DO
  result ← F'(X)
  // 1. Not deduped: a SHA seen only in another collection is NOT a duplicate here
  ASSERT result.embedded_real_content = TRUE
  ASSERT result.is_reference = FALSE
  // 2. Graph node created regardless of any dedupe decision (code/jjobs collections)
  ASSERT (c IN {code, jjobs}) IMPLIES result.graph_node_created = TRUE
END FOR
```

**Preservation property (Preservation Checking)** — for all non-buggy inputs, F' behaves
identically to F:

```pascal
// Property: Preservation Checking
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT F(X) = F'(X)
END FOR
```

In particular, the preserved (`NOT isBugCondition(X)`) cases include:
- A SHA registered by the SAME collection under a DIFFERENT tenant → still deduped to a
  reference document (legitimate cross-tenant embedding optimization, clause 3.1).
- A SHA never registered before → still embedded as real content (clause 2.1/2.2 baseline).
- The `gw` baseline tenant → unchanged results (clause 3.3).
- Documentation-collection graph behavior → still creates no graph nodes (clause 3.2).
