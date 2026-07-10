# Phase 68 — RAG Data-Plane Gap Closure & Tenant-Scope Clarification

**Version**: 0.1.0
**Created**: 2026-07-09
**Status**: draft
**Estimated effort**: 2 days (spec + code fixes; no re-ingest here)
**Depends on**: Phase 67 (`supported_repos/` rename, commit `c15080f`),
`cots-reingest-ralph-loop` (PoC, superseded), `cots-reingest-ralph-framework`
(in-flight; consumes decisions from this phase)

---

## 1. Executive Summary

The 2026-07-09 full-mode health run surfaced eight concrete gaps in the RAG
data plane. Some are code fixes (Phase-67 path-rename leaks, ChromaDB adapter
missing the metadata-sampler interface). One is a reporting artifact of a
collection-name mismatch. Two are correctness prerequisites already tracked in
the follow-up framework spec. And — critically — the shape of the mismatch
points to a missing **architectural principle** that neither the manifest nor
the tenant catalog encodes today:

> **Documentation is NWS-wide and belongs in a single shared embedding space.
> Tenants exist to give an LLM code-base awareness across multiple workflow
> branches and, in the future, across repos outside the global-workflow
> umbrella. Docs are NOT tenant-scoped.**

This phase (a) records that principle in machine-readable form (a `scope:
tenant | shared` field on every manifest source and stage), (b) fixes the two
Phase-67 path leaks that keep `workflow_info` and the integrity coverage-gap
check inoperative, (c) adds the ChromaDB adapter interface the integrity
tools call, (d) makes `get_knowledge_base_status` report a real per-collection
document count, and (e) feeds two concrete decisions into
`cots-reingest-ralph-framework` (Task 2.3 collection naming; Task 5 matrix
expansion). No re-ingest runs under this phase.

---

## 2. Scope

### 2.1 In Scope

- **Manifest schema** — add a required `scope: tenant | shared` field on every
  source in `unified_ingest_manifest.yaml`. Classify all 67 current sources:
  - `on_disk_submodule`, `url_crawl`, `standards`, `community_summary` → `shared`
  - `code_parse`, `config_parse`, `jjob_docs` → `tenant`
- **Work_Matrix builder** (`reingest_state.py init`) — respect `scope`. Shared
  stages produce **one** unit (not N × tenants). Same-tenant `depends_on` rules
  still apply for tenant stages; shared stages have no tenant coupling.
- **Collection naming reconciliation** (formalizes framework Task 2.3):
  - Shared: `mdc-{domain}-mpnet768[-{ver}]` (no prefix)
  - Tenant: `{tenant_prefix}mdc-{domain}-mpnet768[-{ver}]`
  - Default (unversioned) drops the `-{ver}` suffix so serving names are stable.
- **Tenant catalog documentation** — document the two-axis model (branches of
  global-workflow today; arbitrary external repos tomorrow). No code change to
  `tenants.yaml` schema in this phase, but add worked examples in
  `.kiro/steering/` for "adding a non-global-workflow tenant."
- **Path-rename leak fixes** — replace the last two hard-coded
  `supported_repos/global-workflow` paths in `workflow_info` and
  `check_knowledge_integrity`'s coverage-gap check with the tenant-resolved
  `ctx.tenant.workflow_root` (or the mount base for the default tenant).
- **ChromaDB adapter — `metadata_sampler`** — implement the interface the
  integrity tools call so `Path Consistency` and `Stale Embeddings` checks can
  actually run on COTS (currently both `[SKIP]` — "vector adapter does not
  expose a metadata sampler").
- **`get_knowledge_base_status` count fix** — sum documents across all
  collections (per tenant scope); do not report `Total Documents: 0 [ERROR]
  Unhealthy` when 15 non-empty collections exist.
- **Feed decisions into `cots-reingest-ralph-framework`** — record the shared
  vs tenant collection-name policy in that spec's `progress.md`
  Corrections/Codebase Patterns section, so the next iteration of the loop uses
  the corrected names.

### 2.2 Out of Scope

- **Any re-ingest execution.** The 44 pending units + partial `documentation`
  resume continue under `cots-reingest-ralph-framework/tasks.md`. This phase
  only unblocks and clarifies them.
- **Graph version-stamping for `shell_graph`/`fortran_graph`/`config`/`rocoto`/
  `bridge`** — already tracked as framework Task 2.2. Do not duplicate.
- **URL-crawl stale/never refreshes** — pre-existing gap tracked as
  `url-crawl-gap-closure` and Phase 58. Not this phase.
- **Serving-collection cutover** — human-gated, framework Task 7.
- **Removing the `phase48-scratch` collection** — separately confirmed
  destructive action; not in this phase.

---

## 3. Design Principle — Tenant vs Shared Scope

Two independent concerns were conflated in the current manifest:

| Concern | Correct scope | Rationale |
|---|---|---|
| NWS-wide documentation, EE2 standards, general-purpose community summaries | **shared** | Same text, same embeddings for every tenant. Prefixing wastes storage 5×, splits recall, and forces re-ingest for every new tenant. |
| Per-branch code, jjobs, and derived graph labels | **tenant** | Two branches diverge; a `gw_v17` `JJob` is not the same file as a `gw` `JJob`. LLM needs to answer "what does this branch's code look like" without cross-contamination. |
| Repos outside global-workflow (future: `parallel-works-mcp`, `nceplibs`, …) | **tenant** | Same mechanism — a tenant is any (repo, branch) pair the LLM should be aware of, not just a global-workflow branch. |

### 3.1 Manifest field

Add a single required field on every source:

```yaml
sources:
  - id: mom6-docs
    type: url_crawl
    scope: shared            # NEW
    target_collection: mdc-workflow-docs-mpnet768
    ...
  - id: fortran-code-context
    type: code_parse
    scope: tenant            # NEW
    target_collection: mdc-code-context-mpnet768
    ...
```

Existing collections classify as:

| Collection | Scope | Sources |
|---|---|---|
| `mdc-workflow-docs-mpnet768` | shared | 58 url_crawl + 1 on_disk_submodule |
| `mdc-ee2-standards-mpnet768` | shared | 1 standards |
| `mdc-community-summaries-mpnet768` | shared | 1 community_summary |
| `mdc-code-context-mpnet768` | tenant | 3 code_parse + 2 config_parse |
| `mdc-jjobs-mpnet768` | tenant | 1 jjob_docs |

### 3.2 Work_Matrix impact

For 5 tenants + 14 stages, the current builder produces 62 units (5 × 12
per-tenant + 2 global). With `scope`, the same shape becomes:

| Category | Units | Comment |
|---|---:|---|
| Per-tenant stages (worktree, reset, code, jjobs, config, shell_graph, fortran_graph, expdir, rocoto, bridge, validate) | 55 | 5 × 11 |
| Shared stages (documentation, ee2_standards, community_summaries) | 3 | 1 × 3 (formerly `documentation` was per-tenant) |
| **Total** | **58** | vs 62 today; 4 fewer units, and — more importantly — the shared docs get ingested **once**, not five times |

The `.reingest_state/v9-0-0/` file must be regenerated (or idempotently
migrated) after this change. The already-done tenant-scoped units carry
forward; the previously-per-tenant `documentation` units collapse to a single
shared unit (already partially ingested via the PoC `gw_v17 documentation`
partial write — 2,518 docs — which is the correct starting checkpoint since
they went into the shared `mdc-workflow-docs-*` collection anyway).

---

## 4. Acceptance Criteria

| # | Probe | Pass condition |
|---|---|---|
| 1 | Manifest schema | Every source has `scope: tenant\|shared`; parser errors on missing/invalid |
| 2 | Work_Matrix expansion | `reingest_state.py init` produces 58 units (55 tenant + 3 shared) for the current 5-tenant catalog |
| 3 | Shared collection naming | Shared-scope sources resolve to unprefixed names regardless of tenant |
| 4 | Tenant collection naming | Tenant-scope sources resolve to `{prefix}mdc-{domain}-mpnet768[-{ver}]` |
| 5 | workflow_info functional | `mcp_health_check --functional` reports `workflow_info` as `[OK] pass`, not `[SKIP]` |
| 6 | Integrity coverage check | `check_knowledge_integrity` runs the coverage check (not `[SKIP] no Fortran files found in supported_repos/global-workflow`) |
| 7 | Metadata sampler present | ChromaDB adapter exposes `sample_metadata(collection, n)`; integrity `Path Consistency` and `Stale Embeddings` run (not `[SKIP] adapter does not expose a metadata sampler`) |
| 8 | KB-status doc count | `get_knowledge_base_status` reports non-zero `Total Documents` when at least one collection has documents; status is `[OK] Healthy` in that case |
| 9 | Framework spec updated | `cots-reingest-ralph-framework/progress.md` has Corrections/Codebase-Patterns entries for the shared-vs-tenant naming; framework Task 2.3 unblocked |
| 10 | No behaviour change for AWS | AWS-path ingest/serving unchanged (spec explicitly leaves OpenSearch/Neptune naming alone in this phase) |
| 11 | Nothing pushed | Working tree staged; no auto-commit, no auto-push (git policy 08) |

---

## 5. Task List

Sub-tasks marked `*` are test-only and may be skipped to ship faster.

- [ ] **1. Manifest schema — add `scope` field**
  - [ ] 1.1 Extend the schema loader in the manifest parser: `scope` is required, must be `tenant` or `shared`, unknown value → hard error with source id
  - [ ] 1.2 Classify all 67 existing sources per §3.1 table
  - [ ] 1.3 Bump manifest version 9.0.0 → 9.1.0 (schema change); dated entry
  - [ ]* 1.4 Unit test: schema round-trip; missing `scope` raises; unknown value raises

- [ ] **2. Work_Matrix builder respects `scope`**
  - [ ] 2.1 In `reingest_state.py` matrix build: for `scope: shared` stages emit one unit (tenant field `__global__`); for `scope: tenant` emit N units
  - [ ] 2.2 Preserve existing done/skipped statuses across the migration (idempotent `init` already does this — verify)
  - [ ] 2.3 Regenerate `PROGRESS.md`; confirm the 5 → 1 collapse of `documentation` is reflected
  - [ ]* 2.4 Unit test: builder produces the exact 55 + 3 expected shape from a fixture catalog + fixture stages
  - [ ]* 2.5 Unit test: migration from a pre-scope state.json preserves terminal statuses; only regenerates pending units

- [ ] **3. Collection-name reconciliation (feeds framework Task 2.3)**
  - [ ] 3.1 Define the canonical name function `resolve_collection_name(source, tenant, version)` in `mcp_server_python/src/data/collection_namer.py`:
    - `shared`: `f"mdc-{domain}-{profile}{suffix}"`
    - `tenant`: `f"{tenant.index_prefix}mdc-{domain}-{profile}{suffix}"`
    - `suffix = "" if version == DEFAULT else f"-{version}"`
  - [ ] 3.2 Replace ad-hoc name construction in `_ingest_common.write_vector_doc` and the v8 ingesters with `resolve_collection_name`
  - [ ] 3.3 Update `progress.md` in `cots-reingest-ralph-framework` (Corrections + Codebase Patterns) with the new rule
  - [ ]* 3.4 Unit test: 8 cases across (shared|tenant) × (default|explicit ver) × (empty|non-empty prefix)

- [ ] **4. Phase-67 path-rename leak fix**
  - [ ] 4.1 `workflow_info` module: replace the hard-coded `supported_repos/global-workflow` with `ctx.tenant.workflow_root` (default tenant resolves to `.pw_workflow_mount/develop`)
  - [ ] 4.2 `check_knowledge_integrity` coverage-gap check: same replacement
  - [ ]* 4.3 Add functional-validation assertion: `workflow_info` returns `[OK] pass` in `mcp_health_check --functional`

- [ ] **5. ChromaDB adapter — `metadata_sampler` interface**
  - [ ] 5.1 Add `sample_metadata(collection: str, n: int = 20) -> list[dict]` to the ChromaDB adapter using ChromaDB's `get()` with a limit; return `[]` on empty
  - [ ] 5.2 Wire the two `check_knowledge_integrity` `[SKIP]` paths to use it
  - [ ]* 5.3 Unit test: mock ChromaDB collection with 3 documents; assert 3 items returned; empty collection returns `[]`

- [ ] **6. `get_knowledge_base_status` — fix document count**
  - [ ] 6.1 Iterate the live collections list and sum `collection.count()`; return the sum as `Total Documents`
  - [ ] 6.2 Health status becomes `[OK] Healthy` when `count > 0` OR when the tenant has zero applicable collections (don't punish a fresh tenant)
  - [ ]* 6.3 Unit test with mocked adapter returning 3 collections × N docs

- [ ] **7. Tenant catalog — document the two-axis model**
  - [ ] 7.1 Add worked example in `.kiro/steering/11-tenant-roadmap.md` (or a sibling): "Adding a non-global-workflow tenant" — walks through adding e.g. `pw_mcp` pointing at `supported_repos/parallel-works-mcp` on branch `main`
  - [ ] 7.2 Clarify in that doc: `workflow_subdir` becomes a repo-relative anchor, not a global-workflow branch checkout — no code change required, just naming

- [ ] **8. CHANGELOG + spec cross-references**
  - [ ] 8.1 Dated `[Unreleased]` entry summarizing the schema change, the two leak fixes, the adapter interface, the KB-status fix, and the framework-spec cross-reference
  - [ ] 8.2 Add a two-line note to `cots-reingest-ralph-framework/design.md` pointing at Phase 68 for the scope model and Task 3 above for the collection namer

- [ ] **9. Verification pass**
  - [ ] 9.1 Re-run `mcp_health_check --deep --detailed --functional`; assert 11/11 pass (no SKIPs left except optional community_summaries)
  - [ ] 9.2 Re-run `check_knowledge_integrity`; assert 4/4 actually run (no SKIP)
  - [ ] 9.3 Re-run `get_knowledge_base_status`; assert `Total Documents > 0` and status `[OK]`
  - [ ] 9.4 Re-run `list_all_sources --include_gaps`; assert every source has a scope; assert the 5 collection gap-detector rows show the corrected names

- [ ] **10. Commit staging (no push)**
  - [ ] 10.1 Stage all changes; leave for human review (git policy 08)

---

## 6. Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Rebuilding the Work_Matrix loses terminal statuses | Would need to re-run gw_v17's completed graph stages | Task 2.2 explicitly preserves done/skipped in idempotent `init`; add regression test 2.5 |
| Shared collections need to be re-embedded with the corrected name | One extra ingest run for documentation | This is exactly what the framework spec's Task 5 is going to do anyway; changing the target collection name now avoids double-writing |
| Downstream consumers assume tenant-prefixed doc collections | Serving queries against `gw_v17_mdc-workflow-docs-*` would 404 | The current `mdc-*-mpnet768` unprefixed collections are ALREADY unprefixed in ChromaDB (see health output); the fix aligns the ingester with reality, not the other way around |
| Removing hard-coded `supported_repos/global-workflow` breaks a caller not yet audited | Runtime error in an untested module | Grep for the exact string before/after; add functional assertion in health check |

---

## 7. Notes

- This phase is deliberately spec + minor code fixes. The heavy lifting is in
  `cots-reingest-ralph-framework/tasks.md`. Once Phase 68 lands, Framework
  Task 2.3 has an authoritative name, Task 5 has a smaller matrix (58 units),
  and the two integrity gaps (workflow_info skip; metadata sampler skip) stop
  hiding real problems.
- The tenant-scope clarification is the durable value here — it prevents the
  next 3 tenants (be they global-workflow branches or external repos) from
  duplicating the doc embedding space by default.
